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
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import WabaNumber, WaTemplate
from apps.gateway.client import AlotsClient, AlotsError

from .events import publish_conversation, publish_message, publish_status
from .models import AssignmentLog, Contact, Conversation, MediaAsset, Message

logger = logging.getLogger(__name__)


class SendBlocked(Exception):
    """Raised when the request is valid but WhatsApp rules forbid it."""


def _record_result(message, response):
    """Attach the gateway's wamid, or the failure, to a queued message."""
    wamid = None
    if isinstance(response, dict):
        entries = response.get("messages") or []
        if entries:
            wamid = entries[0].get("id")

    if wamid:
        message.wamid = wamid
        message.status = Message.Status.SENT
        message.save(update_fields=["wamid", "status"])
    else:
        message.status = Message.Status.FAILED
        message.error_detail = "Gateway returned no message id"
        message.save(update_fields=["status", "error_detail"])


def _touch(conversation, preview, kind=Message.Kind.TEXT):
    conversation.last_message_at = timezone.now()
    conversation.last_message_preview = preview[:255]
    conversation.last_message_kind = kind
    conversation.save(
        update_fields=["last_message_at", "last_message_preview", "last_message_kind"]
    )


def send_text(conversation, agent, body, reply_to=None):
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
    )
    _touch(conversation, body)

    try:
        response = AlotsClient().send_text(
            conversation.number.phone_number_id,
            conversation.contact.wa_id,
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

    _record_result(message, response)
    publish_message(message)
    return message


def send_media(conversation, agent, kind, media_id, caption="", filename="", asset=None):
    """Send a file the agent already uploaded to the gateway.

    ``asset`` is our own copy of that file. Linking it is what makes the sent
    photo visible in the thread — without it the message knows only the
    gateway's id, which nothing can render.
    """
    if not conversation.is_session_open:
        raise SendBlocked("The 24-hour window is closed. Send an approved template first.")

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
        },
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, caption or f"[{kind}]", kind)

    try:
        response = AlotsClient().send_media(
            conversation.number.phone_number_id,
            conversation.contact.wa_id,
            kind,
            media_id,
            caption=caption,
            filename=filename,
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        raise

    _record_result(message, response)
    publish_message(message)
    return message


def send_location(conversation, agent, latitude, longitude, name="", address=""):
    """Drop a pin — in this business, almost always a property's."""
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
        payload={"location": location},
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, preview, Message.Kind.LOCATION)

    try:
        response = AlotsClient().send_location(
            conversation.number.phone_number_id,
            conversation.contact.wa_id,
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

    _record_result(message, response)
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


def send_buttons(conversation, agent, body, buttons, header="", footer=""):
    """Send up to three tappable reply buttons.

    The customer's tap comes back as an ordinary inbound message carrying the
    button's id, so nothing special is needed to receive the answer.
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
        payload={"interactive": interactive},
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, body, Message.Kind.INTERACTIVE)

    try:
        response = AlotsClient().send_interactive(
            conversation.number.phone_number_id, conversation.contact.wa_id, interactive
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        raise

    _record_result(message, response)
    publish_message(message)
    return message


def build_template_components(template, variables=None, header_variables=None, header_media_id=None):
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

    return components or None


def send_template(conversation, agent, template, variables=None, header_variables=None, header_media_id=None):
    """Send an approved template, which also reopens the free-form window.

    The window is only extended once the gateway accepts the message; assuming
    success would let an agent type into a window WhatsApp still considers shut.
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

    components = build_template_components(template, variables, header_variables, header_media_id)
    preview = render_body(template, variables) or template.name

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.TEMPLATE,
        body=preview,
        template=template,
        payload={
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
            conversation.contact.wa_id,
            template.name,
            template.language,
            components,
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        raise

    _record_result(message, response)

    # Deliberately does not open the free-form window. Only a message *from* the
    # customer does that — a delivered template merely earns the right to be
    # replied to. Opening it here made the panel show an open window, let the
    # agent type, and hand them Meta's error 131047 once the send failed.
    publish_message(message)
    return message


@transaction.atomic
def start_conversation(number, agent, to, template, variables=None, header_variables=None, header_media_id=None):
    """Open a brand-new chat. A template is the only lawful first message."""
    wa_id = "".join(ch for ch in to if ch.isdigit())
    if len(wa_id) < 8:
        raise SendBlocked("Enter a valid phone number with country code.")

    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    conversation, _ = Conversation.objects.get_or_create(
        number=number, contact=contact, defaults={"assigned_agent": agent}
    )
    if conversation.assigned_agent is None:
        conversation.assigned_agent = agent
        conversation.save(update_fields=["assigned_agent"])

    send_template(conversation, agent, template, variables, header_variables, header_media_id)
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
    previous = conversation.assigned_agent
    conversation.assigned_agent = to_agent
    conversation.save(update_fields=["assigned_agent"])

    AssignmentLog.objects.create(
        conversation=conversation,
        from_agent=previous,
        to_agent=to_agent,
        changed_by=changed_by,
        reason=reason,
    )
    publish_conversation(conversation, "conversation.assigned")
    return conversation


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
    return _upload_bytes(
        number,
        django_file.read(),
        django_file.name,
        getattr(django_file, "content_type", "") or "application/octet-stream",
        agent,
    )
