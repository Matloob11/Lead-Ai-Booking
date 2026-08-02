from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

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


def serialize_number_with_agents(number):
    data = serialize_number(number)
    data["agents"] = [
        {
            "agent_id": a.agent_id,
            "display_name": a.agent.display_name or a.agent.get_username(),
            "role": a.role,
        }
        for a in number.assignments.filter(is_active=True).select_related("agent")
    ]
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
        numbers = WabaNumber.objects.filter(is_active=True).prefetch_related("assignments__agent")
        return Response([serialize_number_with_agents(n) for n in numbers])
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
