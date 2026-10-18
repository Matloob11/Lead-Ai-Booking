"""Outbound send paths and conversation ownership changes.

Every send writes the message row first and then calls the gateway, so a chat
never silently loses a message when alots is slow or down — the row is there in
``queued`` and carries the failure if one comes back.
"""

import hashlib
import io
import logging
import mimetypes
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import WabaNumber, WaTemplate
from apps.gateway.client import AlotsClient, AlotsError

from .events import publish_message, publish_status
from .models import Contact, Conversation, MediaAsset, Message

logger = logging.getLogger(__name__)


class SendBlocked(Exception):
    """Raised when the request is valid but WhatsApp rules forbid it."""


def recipient_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def format_recipient_for_gateway(wa_id):
    """E.164 with a leading +.

    Alots (India-hosted BSP) sometimes re-parses a bare UAE MSISDN as an Indian
    number by prefixing ``91`` — ``971559298388`` becomes ``91971559298388``.
    Meta then accepts the send and fails delivery with 131026. A leading ``+``
    forces international parsing on their side.
    """
    digits = recipient_digits(wa_id)
    return f"+{digits}" if digits else ""


def recipient_mismatch_detail(intended, response):
    """Explain when the gateway resolved a different WhatsApp id than we sent."""
    want = recipient_digits(intended)
    if not want or not isinstance(response, dict):
        return None
    contacts = response.get("contacts") or []
    if not contacts or not isinstance(contacts[0], dict):
        return None
    got = recipient_digits(contacts[0].get("wa_id") or contacts[0].get("input") or "")
    if not got or got == want:
        return None
    if got == f"91{want}":
        return (
            f"Gateway resolved +{want} as +{got} (added India 91). "
            "That number is probably not on WhatsApp under this country code — "
            "fix the digits and try again. Message was not delivered as intended."
        )
    return (
        f"Gateway resolved the recipient as +{got} instead of +{want}. "
        "Check the country code. Message was not delivered as intended."
    )


def _is_status_placeholder(row):
    """A row the webhook made for this wamid before our send path could record it.

    Outbound, no sender: either gateway.ingest._create_external_outbound's
    status-only row (kind unknown, the placeholder body, the status entry as
    its payload), or a row an echo of the send made or filled in, whose
    payload is that echo, carrying the wamid as its id. Nothing our own send
    paths store looks like either; the agent's sends carry sent_by and the
    Lead AI's payload["source"].
    """
    from apps.gateway.parse import PLACEHOLDER_BODY

    payload = row.payload if isinstance(row.payload, dict) else {}
    if row.direction != Message.Direction.OUTBOUND or row.sent_by_id is not None or payload.get("source"):
        return False
    if row.kind == Message.Kind.UNKNOWN and row.body == PLACEHOLDER_BODY:
        return True
    return bool(row.wamid) and payload.get("id") == row.wamid


def _record_result(message, response, *, intended_to=None):
    """Attach the gateway's wamid, or the failure, to a queued message.

    Raises SendBlocked when the gateway accepted HTTP but the send is not
    usable (wrong wa_id, no message id) so callers — especially campaigns —
    do not mark the recipient as sent.
    """
    mismatch = recipient_mismatch_detail(intended_to, response) if intended_to else None
    if mismatch:
        wamid = None
        if isinstance(response, dict):
            entries = response.get("messages") or []
            if entries:
                wamid = entries[0].get("id")
        message.status = Message.Status.FAILED
        message.error_code = "RECIPIENT_MISMATCH"
        message.error_detail = mismatch
        if wamid:
            message.wamid = wamid
        message.save(
            update_fields=["status", "error_code", "error_detail"]
            + (["wamid"] if wamid else [])
        )
        raise SendBlocked(mismatch)

    wamid = None
    if isinstance(response, dict):
        entries = response.get("messages") or []
        if entries:
            wamid = entries[0].get("id")

    if wamid:
        try:
            with transaction.atomic():
                message.wamid = wamid
                message.status = Message.Status.SENT
                message.save(update_fields=["wamid", "status"])
        except IntegrityError:
            # A status webhook already gave this wamid to another row.
            stub = (
                Message.objects.filter(wamid=wamid).exclude(pk=message.pk).first()
            )
            if stub is None:
                raise
            if _is_status_placeholder(stub):
                # The webhook's stand-in for this very send: merged into it.
                Message.objects.filter(pk=stub.pk).update(wamid=None)
                stub.delete()
            else:
                # A real message of ours whose own send is still in flight took
                # the wamid (two senders in one chat): it keeps its row and gets
                # its own wamid when its send returns. A failure already
                # recorded on it stays. Only while it still holds this wamid:
                # its own answer may have replaced it a moment ago.
                detach = {"wamid": None}
                if stub.status != Message.Status.FAILED:
                    detach.update(status=Message.Status.QUEUED, delivered_at=None, read_at=None)
                Message.objects.filter(pk=stub.pk, wamid=wamid).update(**detach)
            message.wamid = wamid
            message.status = Message.Status.SENT
            message.save(update_fields=["wamid", "status"])
    else:
        message.status = Message.Status.FAILED
        message.error_detail = "Gateway returned no message id"
        message.save(update_fields=["status", "error_detail"])
        raise SendBlocked("Gateway returned no message id")


def _touch(conversation, preview, kind=Message.Kind.TEXT):
    conversation.last_message_at = timezone.now()
    conversation.last_message_preview = preview[:255]
    conversation.last_message_kind = kind
    conversation.save(
        update_fields=["last_message_at", "last_message_preview", "last_message_kind"]
    )


def _gateway_to(conversation):
    return format_recipient_for_gateway(conversation.contact.wa_id)


def send_text(conversation, agent, body, reply_to=None, payload=None):
    if not conversation.is_session_open:
        raise SendBlocked(
            "The 24-hour window is closed. Send an approved template to reopen the conversation."
        )
    if reply_to and reply_to.conversation_id != conversation.pk:
        raise SendBlocked("You can only quote a message from this conversation.")

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.TEXT,
        body=body,
        reply_to=reply_to,
        sent_by=agent,
        status=Message.Status.QUEUED,
        payload=payload or {},
    )
    _touch(conversation, body)

    try:
        response = AlotsClient().send_text(
            conversation.number.phone_number_id,
            _gateway_to(conversation),
            body,
            # A quote only works if WhatsApp knows the message being quoted;
            # ours does not exist there until it has a wamid.
            reply_to_wamid=reply_to.wamid if reply_to else None,
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        publish_status(message)
        raise

    _record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return message


META_VIDEO_BYTES = 16 * 1024 * 1024
META_FILE_BYTES = 100 * 1024 * 1024


def send_media(conversation, agent, kind, media_id, caption="", filename="", asset=None):
    """Send a file the agent already uploaded to the gateway.

    ``asset`` is our own copy of that file. Linking it is what makes the sent
    photo visible in the thread — without it the message knows only the
    gateway's id, which nothing can render.

    Meta's video slot is 16 MB. A larger clip is sent as a document so a
    ~90 MB property video still arrives; the thread kind stays ``video`` when
    we have the file, so the bubble still plays it.
    """
    if not conversation.is_session_open:
        raise SendBlocked("The 24-hour window is closed. Send an approved template first.")

    gateway_kind = kind
    gateway_name = filename
    size = getattr(asset, "size_bytes", 0) or 0
    if kind == Message.Kind.VIDEO and size > META_VIDEO_BYTES:
        gateway_kind = Message.Kind.DOCUMENT
        gateway_name = filename or getattr(asset, "file_name", "") or "video.mp4"

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=kind,
        body=caption,
        media=asset,
        payload={
            "media_id": media_id,
            "filename": filename,
            "asset_id": asset.pk if asset else None,
            "gateway_kind": gateway_kind,
        },
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, caption or f"[{kind}]", kind)

    try:
        response = AlotsClient().send_media(
            conversation.number.phone_number_id,
            _gateway_to(conversation),
            gateway_kind,
            media_id,
            caption=caption,
            filename=gateway_name,
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        raise

    _record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return message


def send_location(conversation, agent, latitude, longitude, name="", address="", payload=None):
    """Drop a pin — in this business, almost always a property's.

    ``payload`` adds keys to the stored row (e.g. the Lead AI's source tag),
    set before the gateway is called so a quick status webhook sees them.
    """
    if not conversation.is_session_open:
        raise SendBlocked("The 24-hour window is closed. Send an approved template first.")

    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        raise ValueError("Latitude and longitude must be numbers.")
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise ValueError("Those coordinates are not on Earth.")

    location = {
        "latitude": latitude,
        "longitude": longitude,
        "name": name,
        "address": address,
    }
    # A pin has no text of its own, so the list needs something to print.
    preview = name or address or f"{latitude:.5f}, {longitude:.5f}"

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.LOCATION,
        body=preview,
        payload={**(payload or {}), "location": location},
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, preview, Message.Kind.LOCATION)

    try:
        response = AlotsClient().send_location(
            conversation.number.phone_number_id,
            _gateway_to(conversation),
            latitude,
            longitude,
            name=name,
            address=address,
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        publish_status(message)
        raise

    _record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return message


FORWARDABLE_MEDIA = {
    Message.Kind.IMAGE,
    Message.Kind.DOCUMENT,
    Message.Kind.AUDIO,
    Message.Kind.VIDEO,
    Message.Kind.STICKER,
}


def forward_message(message, to_conversation, agent):
    """Send an existing message into another chat.

    There is no forward primitive here, so a forward is an ordinary send that
    happens to carry the same content. Media is re-uploaded from our own stored
    copy rather than resent by id: a media id belongs to the number that
    uploaded it, and the destination is often a different number.
    """
    if message.kind == Message.Kind.TEXT:
        sent = send_text(to_conversation, agent, message.body)

    elif message.kind == Message.Kind.LOCATION:
        pin = message.payload.get("location") or {}
        if not pin.get("latitude") and not pin.get("longitude"):
            raise SendBlocked("This pin has no coordinates to forward.")
        sent = send_location(
            to_conversation,
            agent,
            pin.get("latitude"),
            pin.get("longitude"),
            name=pin.get("name", ""),
            address=pin.get("address", ""),
        )

    elif message.kind in FORWARDABLE_MEDIA:
        asset = message.media
        if not asset or not asset.file:
            raise SendBlocked("The file is still downloading. Try again in a moment.")

        with asset.file.open("rb") as handle:
            payload = handle.read()

        filename = asset.file_name or os.path.basename(asset.file.name)
        mime = asset.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        media_id, copy = _upload_bytes(to_conversation.number, payload, filename, mime, agent)
        if not media_id:
            raise SendBlocked("The gateway would not accept the file.")

        sent = send_media(
            to_conversation,
            agent,
            message.kind,
            media_id,
            caption=message.body,
            filename=filename,
            asset=copy,
        )

    else:
        raise SendBlocked(f"A {message.get_kind_display().lower()} message cannot be forwarded.")

    # WhatsApp marks a forward on the bubble; keeping the origin lets us do the
    # same, and lets an admin trace where a file travelled.
    sent.payload = {**sent.payload, "forwarded_from": message.pk}
    sent.save(update_fields=["payload"])
    return sent


def _positional(values):
    """Order ``{"1": "Ali", "2": "5pm"}`` the way Meta expects to read it."""
    return [values[key] for key in sorted(values, key=lambda k: int(k))]


def render_body(template, variables):
    """Fill the placeholders so the stored message reads like what was sent.

    Without this the thread would show a raw ``Hello {{1}}`` where the customer
    saw their own name, and an agent scrolling back could not tell what went
    out.
    """
    text = template.body_text
    for index, value in (variables or {}).items():
        text = text.replace("{{%s}}" % index, str(value))
    return text


def send_buttons(conversation, agent, body, buttons, header="", footer="", payload=None):
    """Send up to three tappable reply buttons.

    The customer's tap comes back as an ordinary inbound message carrying the
    button's id, so nothing special is needed to receive the answer.
    ``payload`` adds keys to the stored row (e.g. the Lead AI's source tag).
    """
    if not conversation.is_session_open:
        raise SendBlocked("The 24-hour window is closed. Send an approved template first.")
    if not buttons:
        raise SendBlocked("Add at least one button.")
    if len(buttons) > 3:
        raise SendBlocked("WhatsApp allows at most three reply buttons.")

    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {
                    "type": "reply",
                    "reply": {"id": str(b.get("id") or f"btn_{i}")[:256], "title": str(b["title"])[:20]},
                }
                for i, b in enumerate(buttons)
            ]
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.INTERACTIVE,
        body=body,
        payload={**(payload or {}), "interactive": interactive},
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, body, Message.Kind.INTERACTIVE)

    try:
        response = AlotsClient().send_interactive(
            conversation.number.phone_number_id, _gateway_to(conversation), interactive
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        raise

    _record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return message


def build_template_components(
    template, variables=None, header_variables=None, header_media_id=None, button_variables=None
):
    """Assemble Meta's component array for one send.

    Only the parts that actually carry values are included; sending an empty
    component makes Meta reject the whole message.
    """
    components = []

    header = template.header
    if header:
        if header["format"] in {"IMAGE", "VIDEO", "DOCUMENT"} and header_media_id:
            kind = header["format"].lower()
            components.append(
                {"type": "header", "parameters": [{"type": kind, kind: {"id": header_media_id}}]}
            )
        elif header["variable_count"] and header_variables:
            components.append(
                {
                    "type": "header",
                    "parameters": [
                        {"type": "text", "text": str(v)} for v in _positional(header_variables)
                    ],
                }
            )

    if variables:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for v in _positional(variables)],
            }
        )

    # A URL button ending in {{1}} carries a suffix chosen per message. Meta
    # addresses it by the button's position, and each such button is its own
    # component rather than a list of parameters on a shared one.
    for button in template.buttons:
        if not button["variable_count"]:
            continue
        value = (button_variables or {}).get(str(button["index"]))
        if not value:
            continue
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": str(button["index"]),
                "parameters": [{"type": "text", "text": str(value)}],
            }
        )

    return components or None


def send_template(
    conversation,
    agent,
    template,
    variables=None,
    header_variables=None,
    header_media_id=None,
    button_variables=None,
    payload=None,
):
    """Send an approved template, which also reopens the free-form window.

    The window is only extended once the gateway accepts the message; assuming
    success would let an agent type into a window WhatsApp still considers shut.
    ``payload`` adds keys to the stored row (e.g. the Lead AI's source tag).
    """
    if template.status != WaTemplate.Status.APPROVED:
        raise SendBlocked(f"Template '{template.name}' is {template.status}, not approved.")
    if template.waba_business_id != conversation.number.waba_business_id:
        raise SendBlocked("That template belongs to a different WhatsApp number.")

    expected = template.variable_count
    supplied = len(variables or {})
    if supplied != expected:
        raise SendBlocked(
            f"Template '{template.name}' needs {expected} value(s), got {supplied}."
        )
    if template.requires_header_media and not header_media_id:
        raise SendBlocked(f"Template '{template.name}' needs a header {template.header['format'].lower()}.")

    components = build_template_components(
        template, variables, header_variables, header_media_id, button_variables
    )
    preview = render_body(template, variables) or template.name
    # The upload keeps a local copy under this gateway id. Without it on the
    # row, the thread shows the template text and the header picture looks lost.
    asset = None
    if header_media_id:
        asset = (
            MediaAsset.objects.filter(alots_media_id=header_media_id).order_by("-id").first()
        )

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.TEMPLATE,
        body=preview,
        template=template,
        media=asset,
        payload={
            **(payload or {}),
            "variables": variables or {},
            "header_variables": header_variables or {},
            "header_media_id": header_media_id or "",
        },
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, preview, Message.Kind.TEMPLATE)

    try:
        response = AlotsClient().send_template(
            conversation.number.phone_number_id,
            _gateway_to(conversation),
            template.name,
            template.language,
            components,
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        raise

    _record_result(message, response, intended_to=conversation.contact.wa_id)

    # Deliberately does not open the free-form window. Only a message *from* the
    # customer does that — a delivered template merely earns the right to be
    # replied to. Opening it here made the panel show an open window, let the
    # agent type, and hand them Meta's error 131047 once the send failed.
    publish_message(message)
    return message


@transaction.atomic
def start_conversation(
    number,
    agent,
    to,
    template,
    variables=None,
    header_variables=None,
    header_media_id=None,
    button_variables=None,
    hide_new_from_inbox=False,
):
    """Open a brand-new chat. A template is the only lawful first message.

    ``hide_new_from_inbox`` marks a chat that this call just created, so the
    number's agent does not see a rotate-campaign thread. A chat that already
    existed stays visible — hiding it would hide that customer's real history.
    """
    wa_id = "".join(ch for ch in to if ch.isdigit())
    if len(wa_id) < 8:
        raise SendBlocked("Enter a valid phone number with country code.")

    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    conversation, created = Conversation.objects.get_or_create(
        number=number, contact=contact, defaults={"assigned_agent": None if hide_new_from_inbox else agent}
    )
    if created and hide_new_from_inbox:
        if not conversation.staff_only:
            conversation.staff_only = True
            conversation.assigned_agent = None
            conversation.save(update_fields=["staff_only", "assigned_agent"])
    elif conversation.assigned_agent is None and not conversation.staff_only:
        conversation.assigned_agent = agent
        conversation.save(update_fields=["assigned_agent"])

    send_template(
        conversation, agent, template, variables, header_variables, header_media_id, button_variables
    )
    return conversation


def mark_read_on_whatsapp(conversation, typing=False):
    """Turn the customer's ticks blue for what they last sent us.

    Best effort by design: an agent opening a chat must not see an error
    because a receipt failed, and Meta rejects receipts for messages older than
    the window anyway.
    """
    if typing and not settings.GATEWAY_SUPPORTS_TYPING:
        return False
    if not typing and not settings.GATEWAY_SUPPORTS_READ_RECEIPTS:
        return False

    last_inbound = (
        conversation.messages.filter(direction=Message.Direction.INBOUND)
        .exclude(wamid="")
        .exclude(wamid__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if not last_inbound:
        return False

    try:
        AlotsClient().mark_read(conversation.number.phone_number_id, last_inbound.wamid, typing=typing)
        return True
    except AlotsError as exc:
        logger.info("Read receipt for conversation %s was not accepted: %s", conversation.pk, exc)
        return False


def retry_message(message, agent):
    """Send a failed message again.

    A new row is created rather than the old one revived: WhatsApp assigns a
    fresh id, and keeping the failure in the thread is the point — an agent
    needs to see that the first attempt did not arrive.
    """
    if message.status != Message.Status.FAILED:
        raise SendBlocked("Only a failed message can be sent again.")
    if message.direction != Message.Direction.OUTBOUND:
        raise SendBlocked("Only messages we sent can be retried.")

    conversation = message.conversation
    payload = message.payload or {}

    if message.kind == Message.Kind.TEMPLATE:
        if not message.template:
            raise SendBlocked("The template this message used is no longer available.")
        return send_template(
            conversation,
            agent,
            message.template,
            payload.get("variables") or {},
            payload.get("header_variables") or {},
            payload.get("header_media_id") or "",
        )

    if message.kind == Message.Kind.TEXT:
        return send_text(conversation, agent, message.body)

    if message.kind == Message.Kind.LOCATION:
        pin = payload.get("location") or {}
        if pin.get("latitude") is None and pin.get("longitude") is None:
            raise SendBlocked("This pin has no coordinates to send again.")
        return send_location(
            conversation,
            agent,
            pin.get("latitude"),
            pin.get("longitude"),
            name=pin.get("name", ""),
            address=pin.get("address", ""),
        )

    if message.kind == Message.Kind.INTERACTIVE:
        interactive = payload.get("interactive") or {}
        body = ((interactive.get("body") or {}).get("text") or message.body or "").strip()
        header = ((interactive.get("header") or {}).get("text") or "")
        footer = ((interactive.get("footer") or {}).get("text") or "")
        buttons = []
        for i, item in enumerate((interactive.get("action") or {}).get("buttons") or []):
            reply = item.get("reply") or {}
            title = reply.get("title")
            if not title:
                continue
            buttons.append({"id": reply.get("id") or f"btn_{i}", "title": title})
        return send_buttons(conversation, agent, body, buttons, header=header, footer=footer)

    media_id = payload.get("media_id")
    if not media_id:
        raise SendBlocked("The attachment is no longer available; please attach it again.")
    return send_media(
        conversation,
        agent,
        message.kind,
        media_id,
        caption=message.body,
        filename=payload.get("filename", ""),
        asset=message.media,
    )


def reassign(conversation, to_agent, changed_by, reason=""):
    from .transfer import apply_handover

    return apply_handover(conversation, to_agent, changed_by, reason)


def _upload_bytes(number: WabaNumber, payload: bytes, filename, mime_type, agent=None):
    """Push bytes to the gateway and keep our own copy.

    The gateway only hands back an id it can send with; it gives us nothing to
    display. So the file is stored here too, and the resulting asset is what
    makes a sent photo appear in the thread — the same way an inbound one does.

    Returns ``(media_id, asset)``.
    """
    media_id = AlotsClient().upload_media(
        number.phone_number_id, io.BytesIO(payload), filename, mime_type
    )
    if not media_id:
        return None, None

    asset = MediaAsset(
        alots_media_id=media_id,
        mime_type=mime_type,
        file_name=filename,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        downloaded=True,
        uploaded_by=agent,
    )
    asset.file.save(filename, ContentFile(payload), save=False)
    asset.save()
    return media_id, asset


def upload_media(number: WabaNumber, django_file, agent=None):
    """Upload what an agent picked in the composer. See ``_upload_bytes``."""
    size = getattr(django_file, "size", 0) or 0
    if size > META_FILE_BYTES:
        raise SendBlocked(
            "Official WhatsApp will not accept a file larger than 100 MB. "
            "Compress the video, or send it from a Linked phone."
        )
    mime = getattr(django_file, "content_type", "") or "application/octet-stream"
    name = django_file.name or "upload"
    # Meta rejects a video/* upload over 16 MB at the media endpoint. The same
    # bytes go through as a document, which is how a 90 MB clip is sendable.
    if mime.startswith("video/") and size > META_VIDEO_BYTES:
        mime = "application/octet-stream"
        if "." not in name:
            name = f"{name}.mp4"
    return _upload_bytes(number, django_file.read(), name, mime, agent)
