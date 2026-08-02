from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.catalog.models import WaTemplate
from apps.gateway.client import AlotsError

from . import services
from .models import Conversation, MediaAsset, Message


def _visible_conversations(user):
    """Every chat on every number the agent covers.

    Deliberately not filtered by ``assigned_agent``: a customer may message the
    number directly because the agent handed the number out, and that chat must
    not be invisible to them. Assignment is ownership, not access control.
    """
    return Conversation.objects.filter(number__in=user.visible_numbers).select_related(
        "contact", "number", "assigned_agent"
    )


def serialize_conversation(conversation):
    agent = conversation.assigned_agent
    return {
        "id": conversation.pk,
        "number_id": conversation.number_id,
        "contact": {
            "wa_id": conversation.contact.wa_id,
            "name": str(conversation.contact),
        },
        "assigned_agent": (
            {"id": agent.pk, "display_name": agent.display_name or agent.username} if agent else None
        ),
        "status": conversation.status,
        "last_message_at": conversation.last_message_at,
        "last_message_preview": conversation.last_message_preview,
        "unread_count": conversation.unread_count,
        "session_expires_at": conversation.session_expires_at,
        "is_session_open": conversation.is_session_open,
    }


def serialize_message(message, request=None):
    # Attachments are served through an authenticated view rather than a static
    # path: customer documents must not be readable by anyone who guesses a URL.
    media_url = ""
    if message.media_id:
        media_url = reverse("inbox:media-download", args=[message.media_id])
        if request:
            media_url = request.build_absolute_uri(media_url)

    return {
        "id": message.pk,
        "direction": message.direction,
        "kind": message.kind,
        "body": message.body,
        "media_url": media_url,
        "media_name": message.media.file_name if message.media else "",
        "template_name": message.template.name if message.template else "",
        "status": message.status,
        "error_detail": message.error_detail,
        "created_at": message.created_at,
        "delivered_at": message.delivered_at,
        "read_at": message.read_at,
        "sent_by": (
            {"id": message.sent_by.pk, "display_name": message.sent_by.display_name}
            if message.sent_by
            else None
        ),
    }


@api_view(["GET"])
def conversation_list(request):
    queryset = _visible_conversations(request.user)

    number_id = request.GET.get("number")
    if number_id:
        queryset = queryset.filter(number_id=number_id)

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(contact__wa_id__icontains=search)
            | Q(contact__profile_name__icontains=search)
            | Q(contact__display_name__icontains=search)
        )

    if request.GET.get("mine") == "1":
        queryset = queryset.filter(assigned_agent=request.user)

    limit = min(int(request.GET.get("limit", 50)), 200)
    offset = int(request.GET.get("offset", 0))
    total = queryset.count()

    return Response(
        {
            "count": total,
            "results": [serialize_conversation(c) for c in queryset[offset : offset + limit]],
        }
    )


@api_view(["GET"])
def message_list(request, pk):
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    queryset = conversation.messages.select_related("media", "template", "sent_by")

    before = request.GET.get("before")
    if before:
        queryset = queryset.filter(pk__lt=before)

    limit = min(int(request.GET.get("limit", 50)), 200)
    # Take the newest slice, then hand it back oldest-first for rendering.
    page = list(queryset.order_by("-created_at", "-id")[:limit])[::-1]

    return Response(
        {
            "conversation": serialize_conversation(conversation),
            "results": [serialize_message(m, request) for m in page],
        }
    )


@api_view(["POST"])
def mark_read(request, pk):
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    conversation.unread_count = 0
    conversation.save(update_fields=["unread_count"])
    return Response({"status": "ok"})


@api_view(["POST"])
def send(request, pk):
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    kind = request.data.get("kind", Message.Kind.TEXT)
    body = (request.data.get("body") or "").strip()

    try:
        if kind == Message.Kind.TEXT:
            if not body:
                return Response({"detail": "Message body is empty"}, status=status.HTTP_400_BAD_REQUEST)
            message = services.send_text(conversation, request.user, body)
        else:
            media_id = request.data.get("media_id")
            if not media_id:
                return Response({"detail": "media_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            message = services.send_media(
                conversation,
                request.user,
                kind,
                media_id,
                caption=body,
                filename=request.data.get("filename", ""),
            )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the message: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def send_template(request, pk):
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    template = get_object_or_404(WaTemplate, pk=request.data.get("template_id"))

    try:
        message = services.send_template(
            conversation, request.user, template, request.data.get("variables") or {}
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except (KeyError, ValueError) as exc:
        return Response({"detail": f"Bad template variables: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the template: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def start(request):
    """New Contact: open a chat with a number nobody has messaged yet."""
    number = get_object_or_404(request.user.visible_numbers, pk=request.data.get("number_id"))
    template = get_object_or_404(WaTemplate, pk=request.data.get("template_id"))

    try:
        conversation = services.start_conversation(
            number,
            request.user,
            request.data.get("to", ""),
            template,
            request.data.get("variables") or {},
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the template: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_conversation(conversation), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def assign(request, pk):
    if not request.user.is_wa_admin:
        return Response({"detail": "Only admins can reassign a chat"}, status=status.HTTP_403_FORBIDDEN)

    conversation = get_object_or_404(Conversation, pk=pk)

    from django.contrib.auth import get_user_model

    agent_id = request.data.get("agent_id")
    to_agent = get_object_or_404(get_user_model(), pk=agent_id) if agent_id else None

    services.reassign(conversation, to_agent, request.user, request.data.get("reason", ""))
    return Response(serialize_conversation(conversation))


@api_view(["GET"])
def media_download(request, pk):
    asset = get_object_or_404(MediaAsset, pk=pk)

    # The asset is only readable if one of its messages sits in a conversation
    # this agent can already open.
    visible = _visible_conversations(request.user).values_list("pk", flat=True)
    if not asset.messages.filter(conversation_id__in=visible).exists():
        raise Http404

    if not asset.file:
        return Response({"detail": "Attachment is not available yet"}, status=status.HTTP_404_NOT_FOUND)

    return FileResponse(
        asset.file.open("rb"),
        content_type=asset.mime_type or "application/octet-stream",
        filename=asset.file_name or f"attachment-{asset.pk}",
    )


@api_view(["POST"])
@parser_classes([MultiPartParser])
def media_upload(request):
    number = get_object_or_404(request.user.visible_numbers, pk=request.data.get("number_id"))
    upload = request.FILES.get("file")
    if not upload:
        return Response({"detail": "No file supplied"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        media_id = services.upload_media(number, upload)
    except AlotsError as exc:
        return Response({"detail": f"Upload failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    if not media_id:
        return Response({"detail": "Gateway returned no media id"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(
        {
            "media_id": media_id,
            "name": upload.name,
            "mime": getattr(upload, "content_type", ""),
            "size": upload.size,
        }
    )
