import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
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
        # Which business account it lives on. Several numbers share one WABA, so
        # this is what the screen matches a template back to a number by — an
        # agent covering four numbers otherwise sees one undifferentiated list
        # and cannot tell which of them a template can actually be sent from.
        "waba_business_id": template.waba_business_id,
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

    A schedule already refreshes both, but whoever has just had a template
    approved should not have to wait for the next run to use it — and that is
    usually the agent who asked for it, not an admin.

    Templates are therefore open to any signed-in agent. It reads from the
    gateway and writes only into our own copy: nothing is created, nothing is
    sent, and a template an agent may not use is one they already cannot see,
    because every list on this screen is scoped to their own numbers.

    Channels stay admin-only. That one rewrites the number catalogue this whole
    panel is addressed by, and it is not a refresh anybody needs mid-shift.
    """
    from .tasks import sync_numbers, sync_templates

    what = request.data.get("what", "templates")
    if what in ("numbers", "all"):
        denied = _require_admin(request)
        if denied:
            return denied
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


#: {{1}}, {{2}} … as Meta writes them, in the order they must be exampled.
VARIABLE_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def _variable_numbers(text):
    """The distinct placeholders in a piece of template text, in order."""
    seen = []
    for found in VARIABLE_RE.findall(text or ""):
        if found not in seen:
            seen.append(found)
    return seen


def _examples_for(text, supplied):
    """One example value per placeholder, in Meta's order.

    Meta rejects a template carrying {{1}} with no example for it — the review
    is a person reading the finished sentence, and "Hello {{1}}" is not one. The
    submission used to leave the whole `example` block out, so every template
    with a variable in it came back refused and the panel reported Meta's
    complaint as though the wording were at fault.

    A placeholder the composer left blank still gets something, because a
    missing entry fails the same way an absent block does.
    """
    values = supplied if isinstance(supplied, dict) else {}
    out = []
    for number in _variable_numbers(text):
        value = str(values.get(number) or values.get(int(number)) or "").strip()
        out.append(value or f"Sample {number}")
    return out


def _button_components(raw):
    """Meta's BUTTONS block from what the composer sent.

    Accepts the old shape — a list of strings, or one comma-separated string —
    because that is what the panel sent before it could describe anything but a
    quick reply, and a saved draft should not stop working.
    """
    if isinstance(raw, str):
        raw = [b.strip() for b in raw.split(",") if b.strip()]
    if not isinstance(raw, list):
        return []

    buttons = []
    # Three is Meta's limit for quick replies, and the limit this panel offers
    # for anything — a longer list is refused by Meta rather than truncated by
    # us, which reads as the template being wrong.
    for entry in raw[:3]:
        if isinstance(entry, str):
            text = entry.strip()
            if text:
                buttons.append({"type": "QUICK_REPLY", "text": text[:25]})
            continue
        if not isinstance(entry, dict):
            continue

        text = str(entry.get("text", "")).strip()[:25]
        if not text:
            continue

        kind = str(entry.get("type", "QUICK_REPLY")).strip().upper()

        if kind == "URL":
            url = str(entry.get("url", "")).strip()
            if not url:
                continue
            button = {"type": "URL", "text": text, "url": url}
            # A URL ending in a placeholder is how a template links to one
            # customer's own page, and Meta wants the finished link as proof.
            if VARIABLE_RE.search(url):
                sample = str(entry.get("example", "")).strip()
                button["example"] = [sample or VARIABLE_RE.sub("sample", url)]
            buttons.append(button)
        elif kind == "PHONE_NUMBER":
            phone = str(entry.get("phone_number", "")).strip()
            if not phone:
                continue
            buttons.append({"type": "PHONE_NUMBER", "text": text, "phone_number": phone})
        else:
            buttons.append({"type": "QUICK_REPLY", "text": text})

    return buttons


@api_view(["POST"])
def create_template(request):
    """Create a new message template and submit to Meta for approval.

    Scoped to the caller's own WhatsApp Business accounts rather than to admins.
    A template is reviewed by Meta under the company's name and a rejection
    counts against that account, so it is not nothing — but the person who knows
    what wording a customer needs is the agent talking to them, and making them
    queue behind an admin for every phrase is what left the library at twelve
    templates while the business ran on two hundred and sixty.

    What the scoping still refuses is writing into a business account the caller
    does not work on, which is the part that would actually be someone else's.
    """
    from apps.gateway.client import AlotsClient, AlotsError

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

    # What the composer typed into the "sample value" box beside each {{n}}.
    body_examples = request.data.get("body_examples", {})
    header_examples = request.data.get("header_examples", {})

    components = []
    if header_text:
        header = {"type": "HEADER", "format": "TEXT", "text": header_text}
        samples = _examples_for(header_text, header_examples)
        if samples:
            # A header takes one placeholder at most, and its examples are a
            # flat list — unlike the body's, which is a list of rows.
            header["example"] = {"header_text": samples[:1]}
        components.append(header)

    body = {"type": "BODY", "text": body_text}
    samples = _examples_for(body_text, body_examples)
    if samples:
        body["example"] = {"body_text": [samples]}
    components.append(body)

    if footer_text:
        components.append({"type": "FOOTER", "text": footer_text})

    buttons = _button_components(request.data.get("buttons", []))
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})

    payload = {
        "name": clean_name,
        "category": category,
        "language": language,
        "components": components,
    }

    # Only the call to Meta is guarded here. Recording it afterwards is a
    # separate act with separate failures, and wrapping both together meant a
    # local error — a missing import, once — was reported as "Meta template
    # submission failed" for a template Meta had already accepted. The next sync
    # would then find it and nobody would know why it existed.
    try:
        meta_res = AlotsClient().create_template(waba_id, payload) or {}
    except AlotsError as exc:
        err_msg = str(exc)
        if exc.payload and isinstance(exc.payload, dict):
            err_detail = exc.payload.get("error", {}).get("message") or exc.payload.get("detail")
            if err_detail:
                err_msg = str(err_detail)
        return Response({"detail": f"Meta template submission failed: {err_msg}"}, status=status.HTTP_400_BAD_REQUEST)

    initial_status = str(meta_res.get("status") or WaTemplate.Status.PENDING).upper()
    if initial_status not in WaTemplate.Status.values:
        initial_status = WaTemplate.Status.PENDING

    template, _ = WaTemplate.objects.update_or_create(
        waba_business_id=waba_id,
        name=clean_name,
        language=language,
        defaults={
            "meta_template_id": str(meta_res.get("id", "")),
            "category": category,
            "status": initial_status,
            "components": components,
            "synced_at": timezone.now(),
        },
    )
    return Response(serialize_template(template), status=status.HTTP_201_CREATED)
