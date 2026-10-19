import csv
import logging

from django.db.models import Prefetch, Q
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
from apps.leadai.lane import hide_lead_ai
from apps.leadbot.models import LeadAutomation

from . import services
from .events import publish_conversation
from .models import Conversation, Label, MediaAsset, Message, QuickReply, Reminder, SharedAsset
from .send_health import with_send_health
from .serializers import (
    serialize_agent,
    serialize_conversation,
    serialize_message,
    serialize_number,
    serialize_quick_reply,
    serialize_reminder,
    serialize_shared_asset,
)

logger = logging.getLogger(__name__)


class Echo:
    """A write-only file that hands the line straight back.

    csv.writer insists on writing somewhere; giving it this instead of a buffer
    turns each writerow() into a value we can yield, which is what lets an
    export stream row by row instead of being built in memory first.
    """

    def write(self, value):
        return value


# Excel and Sheets treat a cell opening with any of these as a formula, and a
# WhatsApp message is written by whoever is on the other end of the number.
# Without this, a customer could send =HYPERLINK(...) and have it run when an
# agent opens the export.
FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(FORMULA_LEADERS) else text


# What the shared library accepts, and what each type counts as. An allowlist
# rather than a blocklist: these files are uploaded by one colleague and opened
# by another on the panel's own origin, so anything a browser might execute —
# text/html, image/svg+xml — must not be storable in the first place.
SHARED_ASSET_TYPES = {
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
    "text/plain": "document",
    "text/csv": "document",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "video/mp4": "video",
    "video/3gpp": "video",
}


def _visible_conversations(user):
    """Chats this agent may open.

    A thread belongs to ``assigned_agent``. Covering a number does not dump
    every chat on it into the list. Unassigned inbound on a held number stays
    visible until ingest claims it for the primary. A transfer is visible to
    the receiving agent only. Panel admins still see the whole roster.
    """
    from .visibility import visible_conversation_q

    return (
        Conversation.objects.filter(visible_conversation_q(user))
        .select_related(
            "contact", "number", "assigned_agent", "linked_conversation__number",
            # serialize_conversation's lead_ai flag, without a query per chat.
            "lead_ai_chat",
        )
        .prefetch_related(
            Prefetch(
                "lead_automations",
                queryset=LeadAutomation.objects.order_by("-id"),
                to_attr="leadbot_rows",
            )
        )
        .distinct()
    )


def _own_number_ids(user):
    return list(user.visible_numbers.values_list("pk", flat=True))


def _transferred_in_q(user, own_ids):
    """Chats assigned to this agent that are not on a number they hold."""
    extra = Q(assigned_agent=user)
    if own_ids:
        extra &= ~Q(number_id__in=own_ids)
    return extra


@api_view(["GET"])
def conversation_list(request):
    # A chat a Lead AI campaign sent to the Lead AI screen is listed there, not
    # here, until an agent moves it back (apps/leadai).
    queryset = hide_lead_ai(_visible_conversations(request.user))
    own_ids = _own_number_ids(request.user)

    number_id = request.GET.get("number")
    if number_id:
        # A number dropdown must not hide a chat that was transferred onto
        # this agent from a number they do not hold.
        queryset = queryset.filter(Q(number_id=number_id) | _transferred_in_q(request.user, own_ids))

    search = request.GET.get("q", "").strip()
    if search:
        digits = "".join(ch for ch in search if ch.isdigit())
        q_obj = (
            Q(contact__wa_id__icontains=search)
            | Q(contact__profile_name__icontains=search)
            | Q(contact__display_name__icontains=search)
        )
        if digits:
            q_obj |= Q(contact__wa_id__icontains=digits)
            if len(digits) >= 9:
                q_obj |= Q(contact__wa_id__endswith=digits[-9:])
        queryset = queryset.filter(q_obj)

    if request.GET.get("mine") == "1":
        queryset = queryset.filter(assigned_agent=request.user)

    label_id = request.GET.get("label")
    if label_id:
        queryset = queryset.filter(labels__pk=label_id)

    # Rotate campaign chats have their own chip. The main list skips them so
    # a page of thirty is thirty normal chats, and Load more keeps moving.
    rotate = request.GET.get("rotate")
    if rotate == "1":
        queryset = queryset.filter(staff_only=True)
    else:
        queryset = queryset.filter(staff_only=False)

    # Archived chats stay in the list unless the client asks for archived-only.
    archived = request.GET.get("archived")
    if archived == "1":
        queryset = queryset.filter(is_archived=True)
    elif archived == "0":
        queryset = queryset.filter(is_archived=False)

    # WhatsApp order: pinned first, then latest message activity. Opening a
    # chat must not change this — only send/receive updates last_message_at.
    # Transferred-in threads stay visible but are not forced above newer chats.
    queryset = queryset.order_by("-is_pinned", "-last_message_at", "-created_at")

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

    # Who is handling this chat, and how to reach them. An admin looking at a
    # customer usually wants the agent, not just their name.
    handler = conversation.assigned_agent
    assigned_agent = None
    if handler:
        assigned_agent = {
            **serialize_agent(handler),
            "bitrix_user_id": handler.bitrix_user_id or "",
            # What was assigned to them, not what they can see. An admin can
            # see all 21, which answers a different question than "which
            # number is this person's".
            "numbers": [
                {
                    "id": a.number_id,
                    "phone_number": a.number.phone_number,
                    "title": a.number.title,
                }
                for a in handler.number_assignments.filter(is_active=True).select_related("number")
            ],
        }

    # Every handover this chat has been through. The point of transferring with
    # the history intact is that the next agent can see it, so who passed it to
    # whom, and why, belongs on the profile rather than in a log file.
    history = conversation.assignment_logs.select_related(
        "from_agent", "to_agent", "changed_by"
    )[:50]

    return Response(
        {
            "wa_id": contact.wa_id,
            "name": str(contact),
            "profile_name": contact.profile_name,
            "display_name": contact.display_name,
            "notes": contact.notes,
            "first_seen_at": contact.created_at.isoformat(),
            "conversation": serialize_conversation(conversation),
            "number": serialize_number(conversation.number),
            "assigned_agent": assigned_agent,
            "assignment_history": [
                {
                    "id": log.pk,
                    "from_agent": serialize_agent(log.from_agent),
                    "to_agent": serialize_agent(log.to_agent),
                    "changed_by": serialize_agent(log.changed_by),
                    "reason": log.reason,
                    "created_at": log.created_at.isoformat(),
                }
                for log in history
            ],
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
    template = get_object_or_404(
        WaTemplate,
        pk=request.data.get("template_id"),
        waba_business_id=conversation.number.waba_business_id,
    )

    try:
        message = services.send_template(
            conversation,
            request.user,
            template,
            request.data.get("variables") or {},
            request.data.get("header_variables") or {},
            request.data.get("header_media_id") or "",
            request.data.get("button_variables") or {},
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except (KeyError, ValueError) as exc:
        return Response({"detail": f"Bad template variables: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    except AlotsError as exc:
        return Response({"detail": f"Gateway rejected the template: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_message(message, request), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def conversation_templates(request, pk):
    """Approved templates for this chat's WABA.

    Transfer grants one thread, not the number roster. The receiving agent
    still needs these when the 24-hour window is closed.
    """
    conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
    from apps.catalog.models import WaTemplate, WaTemplateHide
    from apps.catalog.views import serialize_template

    templates = WaTemplateHide.visible(
        WaTemplate.objects.filter(
            waba_business_id=conversation.number.waba_business_id,
            status=WaTemplate.Status.APPROVED,
        )
    )
    search = request.GET.get("q", "").strip()
    if search:
        templates = templates.filter(name__icontains=search)
    return Response([serialize_template(t) for t in templates])


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

    # Searching the contact's name as well as the text: an agent looking for
    # "Ahmed" means the person at least as often as the word.
    queryset = (
        Message.objects.filter(conversation__in=_visible_conversations(request.user))
        .filter(
            Q(body__icontains=term)
            | Q(conversation__contact__display_name__icontains=term)
            | Q(conversation__contact__profile_name__icontains=term)
            | Q(conversation__contact__wa_id__icontains=term)
            | Q(media__file_name__icontains=term)
        )
        .select_related(
            "conversation", "conversation__contact", "conversation__number", "sent_by", "media",
            "conversation__lead_ai_chat",
        )
    )

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

    # Under a conversation, this means that conversation's reminders. It used to
    # ignore `pk` entirely and answer with every reminder the agent had, on
    # every chat — so opening one chat showed follow-ups belonging to others as
    # though they were its own. Nothing leaked across agents, but the answer was
    # to a question nobody asked.
    #
    # The chat is checked as well as filtered on: a conversation id counts up
    # from 1, and this is one more route that takes one.
    if pk is not None:
        conversation = get_object_or_404(_visible_conversations(request.user), pk=pk)
        queryset = queryset.filter(conversation=conversation)

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
            request.data.get("button_variables") or {},
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    except AlotsError as exc:
        logger.warning(
            "New contact template refused on number %s: %s",
            number.pk,
            exc,
        )
        return Response({"detail": f"Gateway rejected the template: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(serialize_conversation(conversation), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def lookup(request):
    """Every chat this agent has with a given phone number.

    Written for the CRM tab: Bitrix hands over a lead's phone numbers, and the
    tab has to say, for each one, whether a conversation already exists and
    whether it can be written in right now.

    A number can have more than one answer. ``unique_conversation_per_number``
    is per (our number, customer), so the same customer messaged from two of our
    numbers is deliberately two threads, and the tab has to offer both rather
    than pick one.

    ``numbers`` comes back alongside because of the case that matters most: no
    conversation, or none with an open window. Then the only way to reach the
    person is a template on one of the numbers this agent covers, and the tab
    needs to know which those are without a second request.
    """
    raw = request.GET.get("phone", "")
    wa_id = "".join(ch for ch in raw if ch.isdigit())
    if not wa_id:
        return Response({"detail": "A phone number is required"}, status=status.HTTP_400_BAD_REQUEST)

    # Matched on the tail rather than exactly. Bitrix stores what somebody
    # typed — "+971 55 548 4423", "0555484423", "971555484423" — and WhatsApp
    # knows one form. The last nine digits are the part that does not change.
    tail = wa_id[-9:]

    conversations = (
        _visible_conversations(request.user)
        .filter(contact__wa_id__endswith=tail)
        .order_by("-last_message_at")
    )

    # Which of our numbers each chat is on, by name.
    #
    # serialize_conversation carries number_id and nothing else, so a caller
    # holding one conversation has an integer and no way to say whose number it
    # arrived on. The CRM tab printed "Channel #16" — a database id shown to an
    # agent as though it meant something. The join is done here rather than
    # left to the caller, because there is exactly one right answer to it.
    numbers = [serialize_number(n) for n in with_send_health(request.user.visible_numbers)]
    by_id = {n["id"]: n for n in numbers}

    rows = []
    for conversation in conversations:
        row = serialize_conversation(conversation)
        number = by_id.get(row["number_id"])
        row["number"] = number
        row["number_label"] = (number or {}).get("title") or (number or {}).get("phone_number") or ""
        rows.append(row)

    return Response({"phone": wa_id, "conversations": rows, "numbers": numbers})


@api_view(["POST"])
def assign(request, pk):
    if not request.user.has_admin_rights:
        return Response({"detail": "Only admins can reassign a chat"}, status=status.HTTP_403_FORBIDDEN)

    conversation = get_object_or_404(Conversation, pk=pk)

    from django.contrib.auth import get_user_model

    agent_id = request.data.get("agent_id")
    to_agent = get_object_or_404(get_user_model(), pk=agent_id) if agent_id else None

    try:
        conversation = services.reassign(
            conversation, to_agent, request.user, request.data.get("reason", "")
        )
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
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
    except services.SendBlocked as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
        .select_related(
            "conversation", "conversation__contact", "conversation__number", "media", "sent_by",
            "conversation__lead_ai_chat",
        )
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
                    _csv_safe(cell)
                    for cell in [
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


@api_view(["GET", "POST"])
@parser_classes([MultiPartParser])
def shared_asset_list(request):
    """Shared Media & Document Library for all agents."""
    if request.method == "POST":
        file_obj = request.FILES.get("file")
        title = str(request.data.get("title", "")).strip()
        if not file_obj:
            return Response({"detail": "File is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not title:
            title = file_obj.name

        # The browser's Content-Type is the uploader's to choose, so the type
        # is taken from an allowlist and the stored one is ours, not theirs.
        # It also keeps text/html and image/svg+xml out: both execute script
        # when a browser is persuaded to render them, and these files are
        # served back to colleagues on the panel's own origin.
        claimed = (file_obj.content_type or "").split(";")[0].strip().lower()
        kind = SHARED_ASSET_TYPES.get(claimed)
        if not kind:
            return Response(
                {
                    "detail": "That file type cannot be shared. Use a PDF, an Office "
                    "document, a JPEG/PNG/WebP image, or an MP4 video."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        asset = SharedAsset.objects.create(
            title=title[:255],
            kind=kind,
            file=file_obj,
            file_name=file_obj.name[:255],
            size_bytes=file_obj.size,
            mime_type=claimed[:128],
            created_by=request.user,
        )
        return Response(serialize_shared_asset(asset, request), status=status.HTTP_201_CREATED)

    search = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "").strip().lower()

    assets = SharedAsset.objects.all()
    if kind in SharedAsset.Kind.values:
        assets = assets.filter(kind=kind)
    if search:
        assets = assets.filter(Q(title__icontains=search) | Q(file_name__icontains=search))

    return Response([serialize_shared_asset(a, request) for a in assets])


@api_view(["GET"])
def shared_asset_download(request, pk):
    """Hand back a shared file, to a signed-in colleague only.

    MEDIA_URL is served by nothing — not nginx, not Django with DEBUG off — so
    the library's own links pointed at a 404 and the file could never be opened
    or sent. Routing it through here rather than opening /media/ keeps the
    session check on the way in, and lets the response say plainly that this is
    a download and not a page: an attachment, typed as bytes rather than as
    whatever the uploader claimed, and sandboxed if a browser tries anyway.
    """
    asset = get_object_or_404(SharedAsset, pk=pk)
    if not asset.file:
        return Response({"detail": "That file is missing"}, status=status.HTTP_404_NOT_FOUND)

    response = FileResponse(
        asset.file.open("rb"),
        content_type="application/octet-stream",
        as_attachment=True,
        filename=asset.file_name or f"asset-{asset.pk}",
    )
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["DELETE"])
def shared_asset_delete(request, pk):
    asset = get_object_or_404(SharedAsset, pk=pk)
    if not (request.user.has_admin_rights or asset.created_by_id == request.user.pk):
        return Response({"detail": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
    asset.file.delete(save=False)
    asset.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
