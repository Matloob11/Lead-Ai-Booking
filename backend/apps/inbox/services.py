"""Outbound send paths and conversation ownership changes.

Every send writes the message row first and then calls the gateway, so a chat
never silently loses a message when alots is slow or down — the row is there in
``queued`` and carries the failure if one comes back.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import WabaNumber, WaTemplate
from apps.gateway.client import AlotsClient, AlotsError

from .events import publish_conversation, publish_message, publish_status
from .models import AssignmentLog, Contact, Conversation, Message

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


def _touch(conversation, preview):
    conversation.last_message_at = timezone.now()
    conversation.last_message_preview = preview[:255]
    conversation.save(update_fields=["last_message_at", "last_message_preview"])


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


def send_media(conversation, agent, kind, media_id, caption="", filename=""):
    if not conversation.is_session_open:
        raise SendBlocked("The 24-hour window is closed. Send an approved template first.")

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=kind,
        body=caption,
        payload={"media_id": media_id, "filename": filename},
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, caption or f"[{kind}]")

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


def build_template_components(template, variables):
    """Map ``{"1": "Ali"}`` onto Meta's positional body parameters."""
    if not variables:
        return None
    ordered = [variables[key] for key in sorted(variables, key=lambda k: int(k))]
    return [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": str(value)} for value in ordered],
        }
    ]


def send_template(conversation, agent, template, variables=None):
    """Send an approved template, which also reopens the free-form window.

    The window is only extended once the gateway accepts the message; assuming
    success would let an agent type into a window WhatsApp still considers shut.
    """
    if template.status != WaTemplate.Status.APPROVED:
        raise SendBlocked(f"Template '{template.name}' is {template.status}, not approved.")
    if template.waba_business_id != conversation.number.waba_business_id:
        raise SendBlocked("That template belongs to a different WhatsApp number.")

    components = build_template_components(template, variables)
    preview = template.body_text or template.name

    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.TEMPLATE,
        body=preview,
        template=template,
        payload={"variables": variables or {}},
        sent_by=agent,
        status=Message.Status.QUEUED,
    )
    _touch(conversation, preview)

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
def start_conversation(number, agent, to, template, variables=None):
    """Open a brand-new chat. A template is the only lawful first message."""
    wa_id = "".join(ch for ch in to if ch.isdigit())
    if not wa_id:
        raise SendBlocked("Enter a valid phone number.")

    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    conversation, _ = Conversation.objects.get_or_create(
        number=number, contact=contact, defaults={"assigned_agent": agent}
    )
    if conversation.assigned_agent is None:
        conversation.assigned_agent = agent
        conversation.save(update_fields=["assigned_agent"])

    send_template(conversation, agent, template, variables)
    return conversation


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
    """Push a file to the gateway and return the media id to send with."""
    return AlotsClient().upload_media(
        number.phone_number_id,
        django_file.file,
        django_file.name,
        getattr(django_file, "content_type", "application/octet-stream"),
    )
