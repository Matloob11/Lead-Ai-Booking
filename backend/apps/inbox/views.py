import csv

from django.db.models import Q
from django.http import FileResponse, Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.catalog.models import WaTemplate
from apps.gateway.client import AlotsError

from . import services
from .events import publish_conversation
from .models import Conversation, Label, MediaAsset, Message, QuickReply, Reminder
from .serializers import (
    serialize_conversation,
    serialize_message,
    serialize_quick_reply,
    serialize_reminder,
)


class Echo:
    """A write-only file that hands the line straight back.

    csv.writer insists on writing somewhere; giving it this instead of a buffer
    turns each writerow() into a value we can yield, which is what lets an
    export stream row by row instead of being built in memory first.
    """

    def write(self, value):
        return value


def _visible_conversations(user):
    """Every chat on every number the agent covers.

    Deliberately not filtered by ``assigned_agent``: a customer may message the
    number directly because the agent handed the number out, and that chat must
    not be invisible to them. Assignment is ownership, not access control.
    """
    return Conversation.objects.filter(number__in=user.visible_numbers).select_related(
        "contact", "number", "assigned_agent"
    )


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

    label_id = request.GET.get("label")
    if label_id:
        queryset = queryset.filter(labels__pk=label_id)

    # Archived chats stay out of the way unless asked for.
    if request.GET.get("archived") == "1":
        queryset = queryset.filter(is_archived=True)
    else:
        queryset = queryset.filter(is_archived=False)

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


@api_view(["GET", "PATCH"])
def contact_detail(request, pk):
    """The person behind a chat, and everything we know about them.

    Reached through the conversation rather than by contact id, so an agent can
    only open the profile of somebody who has written to a number they cover.
    """
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    contact = conversation.contact

    if request.method == "PATCH":
        if "display_name" in request.data:
            contact.display_name = str(request.data["display_name"]).strip()[:255]
        if "notes" in request.data:
            contact.notes = str(request.data["notes"])
        contact.save(update_fields=["display_name", "notes"])
        publish_conversation(conversation)

    messages = conversation.messages
    first = messages.order_by("created_at").first()

    # The same customer may also be talking to other numbers we run. Only the
    # ones this agent covers are listed — the profile must not become a way to
    # see chats they cannot open.
    others = (
        _visible_conversations(request.user)
        .filter(contact=contact)
        .exclude(pk=conversation.pk)
    )

    gallery = (
        messages.filter(media__isnull=False, media__downloaded=True)
        .select_related("media")
        .order_by("-created_at")[:24]
    )

    return Response(
        {
            "wa_id": contact.wa_id,
            "name": str(contact),
            "profile_name": contact.profile_name,
            "display_name": contact.display_name,
            "notes": contact.notes,
            "first_seen_at": contact.created_at.isoformat(),
            "conversation": serialize_conversation(conversation),
            "stats": {
                "total": messages.count(),
                "inbound": messages.filter(direction=Message.Direction.INBOUND).count(),
                "outbound": messages.filter(direction=Message.Direction.OUTBOUND).count(),
                "failed": messages.filter(status=Message.Status.FAILED).count(),
                "first_message_at": first.created_at.isoformat() if first else None,
            },
            "other_conversations": [serialize_conversation(c) for c in others],
            "media": [
                {
                    "message_id": m.pk,
                    "kind": m.kind,
                    "url": request.build_absolute_uri(
                        reverse("inbox:media-download", args=[m.media_id])
                    ),
                    "name": m.media.file_name,
                    "mime": m.media.mime_type,
                    "size": m.media.size_bytes,
                    "created_at": m.created_at.isoformat(),
                }
                for m in gallery
            ],
        }
    )


@api_view(["POST"])
def mark_read(request, pk):
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    conversation.unread_count = 0
    conversation.save(update_fields=["unread_count"])

    # Also tell WhatsApp, so the customer's ticks turn blue and they know a
    # person is actually looking. Best effort — never fails opening a chat.
    receipted = services.mark_read_on_whatsapp(conversation)

    # Other agents on the same number have this chat in their list too.
    publish_conversation(conversation)
    return Response({"status": "ok", "receipted": receipted})


@api_view(["POST"])
def typing(request, pk):
    """Show "typing…" on the customer's phone. Lapses by itself after ~25s."""
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    return Response({"status": "ok", "sent": services.mark_read_on_whatsapp(conversation, typing=True)})


@api_view(["POST"])
def set_flags(request, pk):
    """Pin, archive, and label a chat. None of this reaches WhatsApp."""
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)

    fields = []
    if "is_pinned" in request.data:
        conversation.is_pinned = bool(request.data["is_pinned"])
        fields.append("is_pinned")
    if "is_archived" in request.data:
        conversation.is_archived = bool(request.data["is_archived"])
        fields.append("is_archived")
    if fields:
        conversation.save(update_fields=fields)

    if "label_ids" in request.data:
        conversation.labels.set(Label.objects.filter(pk__in=request.data["label_ids"] or []))

    publish_conversation(conversation)
    return Response(serialize_conversation(conversation))


@api_view(["GET", "POST"])
def label_list(request):
    if request.method == "POST":
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"detail": "Label needs a name"}, status=status.HTTP_400_BAD_REQUEST)
        label, _ = Label.objects.get_or_create(
            name=name[:64], defaults={"colour": request.data.get("colour", "#25D366")}
        )
        return Response({"id": label.pk, "name": label.name, "colour": label.colour}, status=201)

    return Response(
        [{"id": l.pk, "name": l.name, "colour": l.colour} for l in Label.objects.all()]
    )


@api_view(["DELETE"])
def label_delete(request, pk):
    if not request.user.has_admin_rights:
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)
    get_object_or_404(Label, pk=pk).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "POST"])
def quick_reply_list(request):
    """Saved answers: the shared set, plus the caller's own."""
    mine = Q(owner=request.user) | Q(owner__isnull=True)

    if request.method == "POST":
        shortcut = str(request.data.get("shortcut", "")).strip().lstrip("/")[:32]
        body = str(request.data.get("body", "")).strip()
        if not shortcut or not body:
            return Response(
                {"detail": "A quick reply needs a shortcut and a body"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Shared replies are everyone's business, so only admins make them.
        shared = bool(request.data.get("is_shared")) and request.user.has_admin_rights
        reply, created = QuickReply.objects.update_or_create(
            owner=None if shared else request.user,
            shortcut=shortcut,
            defaults={"body": body, "created_by": request.user},
        )
        return Response(serialize_quick_reply(reply), status=201 if created else 200)

    return Response([serialize_quick_reply(r) for r in QuickReply.objects.filter(mine)])


@api_view(["DELETE"])
def quick_reply_delete(request, pk):
    reply = get_object_or_404(QuickReply, pk=pk)
    if reply.owner_id != request.user.pk and not request.user.has_admin_rights:
        return Response({"detail": "That quick reply is not yours"}, status=status.HTTP_403_FORBIDDEN)
    reply.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def send(request, pk):
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    kind = request.data.get("kind", Message.Kind.TEXT)
    body = (request.data.get("body") or "").strip()

    reply_to = None
    if request.data.get("reply_to_id"):
        reply_to = get_object_or_404(
            conversation.messages, pk=request.data["reply_to_id"]
        )

    try:
        if kind == Message.Kind.TEXT:
            if not body:
                return Response({"detail": "Message body is empty"}, status=status.HTTP_400_BAD_REQUEST)
            message = services.send_text(conversation, request.user, body, reply_to=reply_to)
        else:
            media_id = request.data.get("media_id")
            if not media_id:
                return Response({"detail": "media_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Our stored copy of the upload, so the sent file renders in the
            # thread instead of showing as an empty bubble. Scoped to the
            # caller's own uploads: an unscoped lookup would let any agent
            # attach a colleague's file to their own chat and then read it
            # through the media view.
            mine = MediaAsset.objects.filter(uploaded_by=request.user)
            asset_id = request.data.get("asset_id")
            if asset_id:
                asset = mine.filter(pk=asset_id).first()
                if asset is None:
                    return Response(
                        {"detail": "That attachment is not yours to send"},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                asset = mine.filter(alots_media_id=media_id).order_by("-id").first()

            message = services.send_media(
                conversation,
                request.user,
                kind,
                media_id,
                caption=body,
                filename=request.data.get("filename", ""),
                asset=asset,
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
            conversation,
            request.user,
            template,
            request.data.get("variables") or {},
            request.data.get("header_variables") or {},
            request.data.get("header_media_id") or "",
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except (KeyError, ValueError) as exc:
        return Response({"detail": f"Bad template variables: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the template: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def retry(request, pk):
    message = get_object_or_404(
        Message.objects.filter(conversation__in=_visible_conversations(request.user)), pk=pk
    )
    try:
        resent = services.retry_message(message, request.user)
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the message: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_message(resent, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def send_buttons(request, pk):
    """Send tappable reply buttons. The tap comes back as a normal message."""
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    try:
        message = services.send_buttons(
            conversation,
            request.user,
            (request.data.get("body") or "").strip(),
            request.data.get("buttons") or [],
            header=request.data.get("header", ""),
            footer=request.data.get("footer", ""),
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except (KeyError, TypeError) as exc:
        return Response({"detail": f"Bad button definition: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the message: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def search(request):
    """Find a message across every chat the agent can open."""
    term = request.GET.get("q", "").strip()
    if len(term) < 2:
        return Response({"detail": "Search for at least two characters"}, status=status.HTTP_400_BAD_REQUEST)

    queryset = Message.objects.filter(
        conversation__in=_visible_conversations(request.user), body__icontains=term
    ).select_related("conversation", "conversation__contact", "conversation__number", "sent_by")

    if request.GET.get("conversation"):
        queryset = queryset.filter(conversation_id=request.GET["conversation"])
    if request.GET.get("number"):
        queryset = queryset.filter(conversation__number_id=request.GET["number"])

    limit = min(int(request.GET.get("limit", 50)), 200)
    hits = queryset.order_by("-created_at")[:limit]

    return Response(
        {
            "count": queryset.count(),
            "results": [
                {
                    **serialize_message(m, request),
                    "conversation": serialize_conversation(m.conversation),
                }
                for m in hits
            ],
        }
    )


@api_view(["GET", "POST"])
def reminders(request, pk=None):
    """Follow-ups. POST under a conversation, GET lists the caller's own."""
    if request.method == "POST":
        conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
        due_at = parse_datetime(str(request.data.get("due_at", "")))
        if not due_at:
            return Response(
                {"detail": "due_at must be an ISO timestamp"}, status=status.HTTP_400_BAD_REQUEST
            )
        if timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at)

        reminder = Reminder.objects.create(
            conversation=conversation,
            agent=request.user,
            due_at=due_at,
            note=str(request.data.get("note", ""))[:255],
        )
        return Response(serialize_reminder(reminder), status=status.HTTP_201_CREATED)

    queryset = Reminder.objects.filter(agent=request.user).select_related(
        "conversation", "conversation__contact", "conversation__number"
    )
    if request.GET.get("open") != "0":
        queryset = queryset.filter(is_done=False)

    return Response([serialize_reminder(r) for r in queryset[:100]])


@api_view(["POST", "DELETE"])
def reminder_detail(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, agent=request.user)
    if request.method == "DELETE":
        reminder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    reminder.is_done = True
    reminder.save(update_fields=["is_done"])
    return Response(serialize_reminder(reminder))


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
            request.data.get("header_variables") or {},
            request.data.get("header_media_id") or "",
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the template: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_conversation(conversation), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def assign(request, pk):
    if not request.user.has_admin_rights:
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
    # The panel knows the conversation it is composing in, and often nothing
    # else, so accept either — and answer 400 with a usable message when neither
    # is present rather than a bare 404 that reads like a missing endpoint.
    conversation_id = request.data.get("conversation_id")
    number_id = request.data.get("number_id")

    if conversation_id:
        conversation = get_object_or_404(_visible_conversations(request.user), pk=conversation_id)
        number = conversation.number
    elif number_id:
        number = get_object_or_404(request.user.visible_numbers, pk=number_id)
    else:
        return Response(
            {"detail": "Send conversation_id (or number_id) alongside the file"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload = request.FILES.get("file")
    if not upload:
        return Response({"detail": "No file supplied"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        media_id, asset = services.upload_media(number, upload, agent=request.user)
    except AlotsError as exc:
        return Response({"detail": f"Upload failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    if not media_id:
        return Response({"detail": "Gateway returned no media id"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(
        {
            "media_id": media_id,
            # Send this back with the message so the thread can render the file.
            "asset_id": asset.pk if asset else None,
            "media_url": request.build_absolute_uri(
                reverse("inbox:media-download", args=[asset.pk])
            )
            if asset
            else "",
            "name": upload.name,
            "mime": getattr(upload, "content_type", ""),
            "size": upload.size,
        }
    )


@api_view(["POST"])
def send_location(request, pk):
    """Drop a pin in the chat."""
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    try:
        message = services.send_location(
            conversation,
            request.user,
            request.data.get("latitude"),
            request.data.get("longitude"),
            name=str(request.data.get("name", ""))[:200],
            address=str(request.data.get("address", ""))[:500],
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        return Response(
            {"detail": f"Gateway rejected the message: {exc}"}, status=status.HTTP_502_BAD_GATEWAY
        )

    return Response(serialize_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def forward(request, pk):
    """Send an existing message into another chat.

    Both ends are checked against the caller's own visible chats, so a forward
    cannot be used to read out of, or write into, a number they do not cover.
    """
    visible = _visible_conversations(request.user)
    message = get_object_or_404(Message.objects.filter(conversation__in=visible), pk=pk)

    target_id = request.data.get("conversation_id")
    if not target_id:
        return Response(
            {"detail": "Say which conversation to forward to"}, status=status.HTTP_400_BAD_REQUEST
        )
    target = get_object_or_404(visible, pk=target_id)
    if target.pk == message.conversation_id:
        return Response(
            {"detail": "That message is already in this chat."}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        sent = services.forward_message(message, target, request.user)
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        return Response(
            {"detail": f"Gateway rejected the message: {exc}"}, status=status.HTTP_502_BAD_GATEWAY
        )

    return Response(serialize_message(sent, request), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def star(request, pk):
    """Flag a message for the team, or clear the flag."""
    message = get_object_or_404(
        Message.objects.filter(conversation__in=_visible_conversations(request.user)), pk=pk
    )
    message.is_starred = bool(request.data.get("starred", True))
    message.save(update_fields=["is_starred"])
    return Response(serialize_message(message, request))


@api_view(["GET"])
def starred(request):
    """Every flagged message across the chats the agent can open."""
    queryset = (
        Message.objects.filter(
            conversation__in=_visible_conversations(request.user), is_starred=True
        )
        .select_related("conversation", "conversation__contact", "conversation__number", "media", "sent_by")
        .order_by("-created_at")
    )

    if request.GET.get("conversation"):
        queryset = queryset.filter(conversation_id=request.GET["conversation"])

    return Response(
        [
            {**serialize_message(m, request), "conversation": serialize_conversation(m.conversation)}
            for m in queryset[:200]
        ]
    )


@api_view(["GET"])
def export(request, pk):
    """Download a chat as a plain transcript or as CSV.

    Streamed rather than assembled: chats are never deleted here, so the oldest
    ones will outgrow whatever limit a buffered response could hold.
    """
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)

    # Deliberately not ?format=: DRF reserves that for content negotiation and
    # answers 404 for any value it has no renderer for, which would swallow this
    # endpoint entirely.
    fmt = request.GET.get("fmt", "txt").lower()
    if fmt not in {"txt", "csv"}:
        return Response({"detail": "fmt must be txt or csv"}, status=status.HTTP_400_BAD_REQUEST)

    messages = (
        conversation.messages.select_related("sent_by", "media", "template")
        .order_by("created_at", "id")
        .iterator(chunk_size=500)
    )
    them = str(conversation.contact)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    filename = f"whatsapp-{conversation.contact.wa_id}-{stamp}.{fmt}"

    def who(message):
        if message.direction == Message.Direction.INBOUND:
            return them
        return (message.sent_by and message.sent_by.display_name) or conversation.number.title

    def content(message):
        if message.kind == Message.Kind.LOCATION:
            pin = message.payload.get("location") or {}
            place = pin.get("name") or pin.get("address") or ""
            return f"[location] {place} ({pin.get('latitude')}, {pin.get('longitude')})".strip()
        if message.media:
            label = f"<{message.media.file_name or message.kind}>"
            return f"{label} {message.body}".strip()
        return message.body or f"[{message.kind}]"

    if fmt == "txt":
        def lines():
            yield f"WhatsApp chat with {them} ({conversation.contact.wa_id})\n"
            yield f"Number: {conversation.number.title} ({conversation.number.phone_number})\n"
            yield f"Exported {timezone.localtime().strftime('%d/%m/%Y %H:%M')}\n\n"
            for message in messages:
                when = timezone.localtime(message.created_at).strftime("%d/%m/%Y, %H:%M")
                yield f"[{when}] {who(message)}: {content(message)}\n"

        response = StreamingHttpResponse(lines(), content_type="text/plain; charset=utf-8")
    else:
        def rows():
            writer = csv.writer(Echo())
            yield writer.writerow(
                ["timestamp", "direction", "sender", "kind", "body", "status", "file"]
            )
            for message in messages:
                yield writer.writerow(
                    [
                        timezone.localtime(message.created_at).isoformat(),
                        message.direction,
                        who(message),
                        message.kind,
                        content(message),
                        message.status,
                        message.media.file_name if message.media else "",
                    ]
                )

        response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")

    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
