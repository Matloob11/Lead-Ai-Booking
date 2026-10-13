from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.inbox.models import Conversation

from .cover import cover_for
from .eligibility import CONTEXT_MAX
from .models import AgentAiDesk, ConversationAiCover, ConversationHealth
from .reply import configured
from .serializers import serialize_candidate, serialize_cover, serialize_desk, serialize_health_row


def _clip_context(raw) -> str:
    return str(raw or "")[:CONTEXT_MAX]


def _visible(user):
    from apps.inbox.visibility import visible_conversation_q

    return Conversation.objects.filter(visible_conversation_q(user)).select_related(
        "contact", "number", "assigned_agent"
    )


@api_view(["GET", "PUT"])
def desk(request):
    desk_row, _ = AgentAiDesk.objects.get_or_create(agent=request.user)
    if request.method == "GET":
        return Response(serialize_desk(desk_row))

    enabled = bool(request.data.get("enabled"))
    scope = str(request.data.get("scope") or AgentAiDesk.Scope.OFF)
    if scope not in AgentAiDesk.Scope.values:
        return Response({"detail": "Unknown scope"}, status=status.HTTP_400_BAD_REQUEST)
    if enabled and scope == AgentAiDesk.Scope.OFF:
        scope = AgentAiDesk.Scope.NEW

    desk_row.enabled = enabled
    desk_row.scope = scope
    desk_row.context = _clip_context(request.data.get("context"))
    desk_row.save()

    ids = request.data.get("selected_ids")
    if ids is not None:
        if not isinstance(ids, list):
            return Response({"detail": "selected_ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        clean = []
        for item in ids[:200]:
            try:
                clean.append(int(item))
            except (TypeError, ValueError):
                continue
        allowed = set(_visible(request.user).filter(pk__in=clean).values_list("pk", flat=True))
        desk_row.selected.set([pk for pk in clean if pk in allowed])

    return Response(serialize_desk(desk_row))


@api_view(["GET", "PUT"])
def conversation_cover(request, pk):
    conversation = get_object_or_404(_visible(request.user), pk=pk)
    cover = ConversationAiCover.objects.filter(conversation=conversation).first()
    if request.method == "GET":
        covering = cover_for(conversation)
        payload = serialize_cover(
            cover,
            origin=covering.origin if covering else None,
            openai_configured=configured(),
        )
        payload["conversation"] = serialize_candidate(conversation)
        return Response(payload)

    enabled = bool(request.data.get("enabled"))
    cover, _ = ConversationAiCover.objects.get_or_create(
        conversation=conversation,
        defaults={"agent": request.user, "enabled": enabled},
    )
    cover.agent = request.user
    cover.enabled = enabled
    cover.context = _clip_context(request.data.get("context"))
    if enabled or request.data.get("resume"):
        cover.paused_at = None
    cover.save()
    covering = cover_for(conversation)
    payload = serialize_cover(
        cover,
        origin=covering.origin if covering else None,
        openai_configured=configured(),
    )
    payload["conversation"] = serialize_candidate(conversation)
    return Response(payload)


@api_view(["GET"])
def candidates(request):
    queryset = _visible(request.user).filter(is_archived=False)
    search = (request.GET.get("q") or "").strip()
    if search:
        queryset = queryset.filter(
            Q(contact__wa_id__icontains=search)
            | Q(contact__profile_name__icontains=search)
            | Q(contact__display_name__icontains=search)
        )
    rows = queryset.order_by("-last_message_at", "-id")[:40]
    return Response({"results": [serialize_candidate(row) for row in rows]})


def _require_admin(request):
    if not getattr(request.user, "has_admin_rights", False):
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)
    return None


def _health_summary():
    out = {colour: 0 for colour in ConversationHealth.Colour.values}
    out["unclassified"] = 0
    out["total"] = 0
    for colour in ConversationHealth.objects.values_list("colour", flat=True):
        out["total"] += 1
        key = colour if colour in ConversationHealth.Colour.values else "unclassified"
        out[key] += 1
    return out


@api_view(["GET"])
def health_summary(request):
    denied = _require_admin(request)
    if denied:
        return denied
    return Response(_health_summary())


@api_view(["GET"])
def health_list(request):
    denied = _require_admin(request)
    if denied:
        return denied
    colour = str(request.GET.get("colour") or "").lower().strip()
    if colour not in ConversationHealth.Colour.values:
        return Response({"detail": "colour must be red|pink|yellow|white|green"}, status=status.HTTP_400_BAD_REQUEST)
    rows = (
        ConversationHealth.objects.filter(colour=colour)
        .select_related("conversation", "conversation__contact", "conversation__number")
        .order_by("-updated_at")[:200]
    )
    return Response([serialize_health_row(row) for row in rows])


@api_view(["POST"])
def health_allow_green(request):
    denied = _require_admin(request)
    if denied:
        return denied
    from .health import allow_red_as_green

    try:
        conversation_id = int(request.data.get("conversation_id"))
    except (TypeError, ValueError):
        return Response({"detail": "conversation_id is required"}, status=status.HTTP_400_BAD_REQUEST)
    row = ConversationHealth.objects.filter(conversation_id=conversation_id).select_related(
        "conversation", "conversation__contact", "conversation__number"
    ).first()
    if row is None:
        return Response({"detail": "Chat not found"}, status=status.HTTP_404_NOT_FOUND)
    try:
        allow_red_as_green(row, str(request.data.get("password") or ""))
    except PermissionError:
        return Response({"detail": "Invalid admin password"}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    row.refresh_from_db()
    return Response(serialize_health_row(row))


@api_view(["POST"])
def health_reclassify_false_red(request):
    denied = _require_admin(request)
    if denied:
        return denied
    from .health import openai_ready
    from .tasks import consider_health

    if not openai_ready():
        return Response({"enqueued": 0, "enabled": False, "candidates": 0})
    ids = list(
        ConversationHealth.objects.filter(colour="red", colour_locked=False).values_list(
            "conversation_id", flat=True
        )[:500]
    )
    for pk in ids:
        consider_health.apply_async(args=[pk], kwargs={"force": True})
    return Response({"enqueued": len(ids), "enabled": True, "candidates": len(ids)})


@api_view(["POST"])
def health_analyse(request):
    """Queue a first classify on recent Official chats that still have no colour."""
    denied = _require_admin(request)
    if denied:
        return denied
    from .health import openai_ready
    from .tasks import consider_health

    if not openai_ready():
        return Response({"enqueued": 0, "enabled": False})
    known = set(ConversationHealth.objects.exclude(colour="").values_list("conversation_id", flat=True))
    queryset = (
        Conversation.objects.filter(is_archived=False)
        .exclude(pk__in=known)
        .order_by("-last_message_at", "-id")[:300]
    )
    ids = list(queryset.values_list("pk", flat=True))
    for pk in ids:
        consider_health.apply_async(args=[pk], kwargs={"force": True})
    return Response({"enqueued": len(ids), "enabled": True})
