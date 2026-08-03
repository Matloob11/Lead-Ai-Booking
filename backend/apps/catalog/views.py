from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.inbox.models import Conversation
from apps.inbox.serializers import serialize_number

from .models import NumberAssignment, WabaNumber, WaTemplate


def _require_admin(request):
    """Returns an error response, or None if the caller may administer."""
    if not request.user.has_admin_rights:
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)
    return None


def serialize_template(template):
    return {
        "id": template.pk,
        "name": template.name,
        "language": template.language,
        "category": template.category,
        "status": template.status,
        "body_text": template.body_text,
        "footer_text": template.footer_text,
        "header": template.header,
        "buttons": template.buttons,
        "variable_count": template.variable_count,
        "requires_header_media": template.requires_header_media,
        "components": template.components,
    }


def serialize_number_with_agents(number, template_counts=None, chat_counts=None):
    data = serialize_number(number)
    # ``active_assignments`` when the caller prefetched it, so a page of twenty
    # numbers is one query rather than twenty. Filtering the relation here
    # instead would go back to the database for every row.
    roster = getattr(number, "active_assignments", None)
    if roster is None:
        roster = number.assignments.filter(is_active=True).select_related("agent")

    data["agents"] = [
        {
            "agent_id": a.agent_id,
            "display_name": a.agent.display_name or a.agent.get_username(),
            "role": a.role,
        }
        for a in roster
    ]
    # A number with no approved templates cannot reopen a closed window, so it
    # can only ever reply to customers who wrote first. That is a property of
    # the number an admin has to know before handing it to an agent, and it is
    # invisible everywhere else.
    if template_counts is not None:
        data["template_count"] = template_counts.get(number.waba_business_id, 0)
    if chat_counts is not None:
        data["conversation_count"] = chat_counts.get(number.pk, 0)
    return data


def serialize_agent_row(agent):
    return {
        "id": agent.pk,
        "display_name": agent.display_name or agent.get_username(),
        "bitrix_user_id": agent.bitrix_user_id,
        "avatar_url": agent.avatar_url,
        "is_wa_admin": agent.has_admin_rights,
        "is_manual_admin": agent.is_wa_admin,
        "is_bitrix_admin": agent.is_bitrix_admin,
        "is_active": agent.is_active,
        "last_seen_at": agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        "numbers": [
            {"id": a.number_id, "phone_number": a.number.phone_number, "role": a.role}
            for a in agent.number_assignments.filter(is_active=True).select_related("number")
        ],
    }


@api_view(["GET"])
def number_list(request):
    # Admins get the assignment roster with each number, since that is the
    # screen they manage it from; agents just get their own numbers.
    if request.user.has_admin_rights:
        numbers = WabaNumber.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                "assignments",
                queryset=NumberAssignment.objects.filter(is_active=True).select_related("agent"),
                to_attr="active_assignments",
            )
        )

        # Counted once for the whole page rather than per row: templates belong
        # to a WABA and several numbers share one.
        template_counts = dict(
            WaTemplate.objects.filter(status=WaTemplate.Status.APPROVED)
            .values_list("waba_business_id")
            .annotate(n=Count("pk"))
        )
        chat_counts = dict(
            Conversation.objects.values_list("number_id").annotate(n=Count("pk"))
        )
        return Response(
            [serialize_number_with_agents(n, template_counts, chat_counts) for n in numbers]
        )
    return Response([serialize_number(n) for n in request.user.visible_numbers])


@api_view(["GET"])
def number_templates(request, pk):
    # Scoped to visible_numbers so an agent cannot read another team's templates
    # by guessing an id.
    number = get_object_or_404(request.user.visible_numbers, pk=pk)

    templates = WaTemplate.objects.filter(waba_business_id=number.waba_business_id)
    if request.GET.get("all") != "1":
        templates = templates.filter(status=WaTemplate.Status.APPROVED)

    search = request.GET.get("q", "").strip()
    if search:
        templates = templates.filter(name__icontains=search)

    return Response([serialize_template(t) for t in templates])


@api_view(["GET"])
def agent_list(request):
    """Everyone who has signed into the panel, for the assignment screen.

    Agents appear here only after their first sign-in — identity comes from
    Bitrix, so there is nobody to list until they have opened the panel once.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    agents = (
        get_user_model()
        .objects.filter(is_active=True)
        .prefetch_related("number_assignments__number")
        .order_by("display_name", "username")
    )
    return Response([serialize_agent_row(a) for a in agents])


@api_view(["PUT", "POST"])
@transaction.atomic
def number_agents(request, pk):
    """Set exactly who works a number.

    Replaces the roster rather than adding to it, so the screen can send the
    checkbox state it has and not reason about what changed. Removals are
    deactivated rather than deleted — the history of who held a number matters
    when a conversation is later questioned.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    number = get_object_or_404(WabaNumber, pk=pk)
    entries = request.data.get("agents", [])
    if not isinstance(entries, list):
        return Response({"detail": "agents must be a list"}, status=status.HTTP_400_BAD_REQUEST)

    wanted = {}
    for entry in entries:
        agent_id = entry.get("agent_id") if isinstance(entry, dict) else entry
        if agent_id is None:
            continue
        role = entry.get("role", NumberAssignment.Role.PRIMARY) if isinstance(entry, dict) else NumberAssignment.Role.PRIMARY
        wanted[int(agent_id)] = role

    known = set(get_user_model().objects.filter(pk__in=wanted).values_list("pk", flat=True))
    missing = set(wanted) - known
    if missing:
        return Response(
            {"detail": f"Unknown agent ids: {sorted(missing)}"}, status=status.HTTP_400_BAD_REQUEST
        )

    number.assignments.filter(is_active=True).exclude(agent_id__in=wanted).update(is_active=False)

    for agent_id, role in wanted.items():
        NumberAssignment.objects.update_or_create(
            number=number,
            agent_id=agent_id,
            defaults={"role": role, "is_active": True, "created_by": request.user},
        )

    number.refresh_from_db()
    return Response(serialize_number_with_agents(number))


@api_view(["PATCH", "POST"])
def update_number(request, pk):
    """Rename a number.

    The gateway's channel API returns no name at all, so without this the panel
    can only show digits. Admins normally set it to whoever works the number.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    number = get_object_or_404(WabaNumber, pk=pk)

    if "label" in request.data:
        number.label = str(request.data["label"]).strip()[:255]
        number.save(update_fields=["label"])

    return Response(serialize_number_with_agents(number))


@api_view(["POST"])
def sync_now(request):
    """Pull templates (and optionally channels) from the gateway on demand.

    A schedule already refreshes both, but an admin who has just had a template
    approved should not have to wait for the next run to use it.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    from .tasks import sync_numbers, sync_templates

    what = request.data.get("what", "templates")
    try:
        result = {}
        if what in ("numbers", "all"):
            result["numbers"] = sync_numbers()
        if what in ("templates", "all"):
            result["templates"] = sync_templates()
    except Exception as exc:  # noqa: BLE001 - surface the gateway's complaint
        return Response({"detail": f"Sync failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({"status": "ok", **result})


@api_view(["POST"])
def set_agent_admin(request, pk):
    """Grant or revoke panel admin, without touching what Bitrix says."""
    denied = _require_admin(request)
    if denied:
        return denied

    agent = get_object_or_404(get_user_model(), pk=pk)
    if agent.pk == request.user.pk:
        # Removing your own last admin right locks everyone out of this screen.
        return Response({"detail": "You cannot change your own admin rights"}, status=status.HTTP_400_BAD_REQUEST)

    agent.is_wa_admin = bool(request.data.get("is_wa_admin"))
    agent.save(update_fields=["is_wa_admin"])
    return Response(serialize_agent_row(agent))


@api_view(["GET"])
def all_templates(request):
    """List all templates (approved, pending, rejected) for the agent's WABAs."""
    waba_ids = list(
        request.user.visible_numbers.exclude(waba_business_id="")
        .values_list("waba_business_id", flat=True)
        .distinct()
    )

    templates = WaTemplate.objects.filter(waba_business_id__in=waba_ids)

    wanted_status = request.GET.get("status", "").strip().upper()
    if wanted_status and wanted_status in WaTemplate.Status.values:
        templates = templates.filter(status=wanted_status)

    search = request.GET.get("q", "").strip()
    if search:
        templates = templates.filter(name__icontains=search)

    return Response([serialize_template(t) for t in templates])


@api_view(["POST"])
def create_template(request):
    """Create a new message template and submit to Meta for approval.

    Admins only. A template is written to the company's own WhatsApp Business
    account, is reviewed by Meta under that account's name, and a rejection
    counts against it — so this is not something an agent does on their own
    behalf, however harmless the wording looks.
    """
    import re
    from apps.gateway.client import AlotsClient, AlotsError

    denied = _require_admin(request)
    if denied:
        return denied

    # Only a WABA the caller actually covers. Taking this id from the body
    # unchecked would let anyone who can reach the endpoint write templates
    # into any business account whose id they could guess or read elsewhere.
    covered = set(
        request.user.visible_numbers.exclude(waba_business_id="")
        .values_list("waba_business_id", flat=True)
    )

    waba_id = str(request.data.get("waba_business_id", "")).strip()
    if waba_id and waba_id not in covered:
        return Response(
            {"detail": "That WhatsApp Business account is not one of yours."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not waba_id:
        waba_id = next(iter(sorted(covered)), "")

    if not waba_id:
        return Response(
            {"detail": "No WhatsApp Business account found for your profile."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_name = str(request.data.get("name", "")).strip()
    clean_name = re.sub(r"[^\w]+", "_", raw_name.lower()).strip("_")
    if not clean_name:
        return Response(
            {"detail": "Template name is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    category = str(request.data.get("category", "MARKETING")).strip().upper()
    if category not in {"MARKETING", "UTILITY", "AUTHENTICATION"}:
        category = "MARKETING"

    language = str(request.data.get("language", "en")).strip() or "en"
    body_text = str(request.data.get("body_text", "")).strip()
    if not body_text:
        return Response(
            {"detail": "Body text is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    header_text = str(request.data.get("header_text", "")).strip()
    footer_text = str(request.data.get("footer_text", "")).strip()
    button_texts = request.data.get("buttons", [])
    if isinstance(button_texts, str):
        button_texts = [b.strip() for b in button_texts.split(",") if b.strip()]

    components = []
    if header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": header_text})

    components.append({"type": "BODY", "text": body_text})

    if footer_text:
        components.append({"type": "FOOTER", "text": footer_text})

    if button_texts and isinstance(button_texts, list):
        btn_list = []
        for btn in button_texts[:3]:
            btn_str = str(btn).strip()
            if btn_str:
                btn_list.append({"type": "QUICK_REPLY", "text": btn_str[:25]})
        if btn_list:
            components.append({"type": "BUTTONS", "buttons": btn_list})

    payload = {
        "name": clean_name,
        "category": category,
        "language": language,
        "components": components,
    }

    try:
        client = AlotsClient()
        meta_res = client.create_template(waba_id, payload)
        meta_id = str((meta_res or {}).get("id", ""))
        initial_status = (meta_res or {}).get("status", WaTemplate.Status.PENDING).upper()
        if initial_status not in WaTemplate.Status.values:
            initial_status = WaTemplate.Status.PENDING

        template, _ = WaTemplate.objects.update_or_create(
            waba_business_id=waba_id,
            name=clean_name,
            language=language,
            defaults={
                "meta_template_id": meta_id,
                "category": category,
                "status": initial_status,
                "components": components,
                "synced_at": timezone.now(),
            },
        )
        return Response(serialize_template(template), status=status.HTTP_201_CREATED)
    except AlotsError as exc:
        err_msg = str(exc)
        if exc.payload and isinstance(exc.payload, dict):
            err_detail = exc.payload.get("error", {}).get("message") or exc.payload.get("detail")
            if err_detail:
                err_msg = str(err_detail)
        return Response({"detail": f"Meta template submission failed: {err_msg}"}, status=status.HTTP_400_BAD_REQUEST)
