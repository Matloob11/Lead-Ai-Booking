"""Outbound send paths and conversation ownership changes.

Every send writes the message row first and then calls the gateway, so a chat
never silently loses a message when alots is slow or down — the row is there in
``queued`` and carries the failure if one comes back.
"""

import hashlib
import logging

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


def send_text(conversation, agent, body):
    if not conversation.is_session_open:
        raise SendBlocked(
            "The 24-hour window is closed. Send an approved template to reopen the conversation."
        )

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.TEXT,
        body=body,
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, body)

    try:
        response = AlotsClient().send_text(
            conversation.number.phone_number_id, conversation.contact.wa_id, body
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

    if message.status == Message.Status.SENT:
        conversation.open_session()
        conversation.save(update_fields=["last_inbound_at", "session_expires_at"])

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


def upload_media(number: WabaNumber, django_file):
    """Push a file to the gateway and keep our own copy.

    The gateway only hands back an id it can send with; it gives us nothing to
    display. So the file is stored here too, and the resulting asset is what
    makes a sent photo appear in the thread — the same way an inbound one does.

    Returns ``(media_id, asset)``.
    """
    payload = django_file.read()
    django_file.seek(0)

    media_id = AlotsClient().upload_media(
        number.phone_number_id,
        django_file.file,
        django_file.name,
        getattr(django_file, "content_type", "application/octet-stream"),
    )
    if not media_id:
        return None, None

    asset = MediaAsset(
        alots_media_id=media_id,
        mime_type=getattr(django_file, "content_type", "") or "application/octet-stream",
        file_name=django_file.name,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        downloaded=True,
    )
    asset.file.save(django_file.name, ContentFile(payload), save=False)
    asset.save()
    return media_id, asset
