"""Turns raw alots.io callbacks into conversations and messages.

Runs out of band so the webhook endpoint can answer immediately. Every event is
already persisted before this starts, so a failure here is recoverable: fix the
parser, then replay the pending rows.
"""

import logging
from datetime import datetime, timezone as dt_timezone

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import WabaNumber
from apps.inbox.models import Contact, Conversation, MediaAsset, Message

from .models import WebhookEvent

logger = logging.getLogger(__name__)

# Meta message types we store verbatim under a media asset.
MEDIA_KINDS = {"image", "document", "audio", "video", "sticker"}

STATUS_MAP = {
    "sent": Message.Status.SENT,
    "delivered": Message.Status.DELIVERED,
    "read": Message.Status.READ,
    "failed": Message.Status.FAILED,
}


def _ts(value):
    """Meta sends unix seconds as a string."""
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError):
        return timezone.now()


def _describe(message):
    """A short preview for the conversation list."""
    kind = message.get("type", "unknown")
    if kind == "text":
        return message.get("text", {}).get("body", "")
    if kind in MEDIA_KINDS:
        caption = message.get(kind, {}).get("caption", "")
        return caption or f"[{kind}]"
    if kind == "location":
        return "[location]"
    if kind == "button":
        return message.get("button", {}).get("text", "[button]")
    if kind == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title", "[interactive]")
    if kind == "reaction":
        return message.get("reaction", {}).get("emoji", "[reaction]")
    return f"[{kind}]"


def _store_inbound(number, message, contact_profiles):
    wa_id = message.get("from", "")
    if not wa_id:
        return None

    profile_name = contact_profiles.get(wa_id, "")
    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    if profile_name and contact.profile_name != profile_name:
        contact.profile_name = profile_name
        contact.save(update_fields=["profile_name"])

    conversation, created = Conversation.objects.get_or_create(number=number, contact=contact)

    kind = message.get("type", "unknown")
    if kind not in Message.Kind.values:
        kind = Message.Kind.UNKNOWN

    sent_at = _ts(message.get("timestamp"))
    preview = _describe(message)

    media = None
    if kind in MEDIA_KINDS:
        blob = message.get(message["type"], {})
        media = MediaAsset.objects.create(
            alots_media_id=blob.get("id", ""),
            mime_type=blob.get("mime_type", ""),
            file_name=blob.get("filename", ""),
            sha256=blob.get("sha256", ""),
        )

    msg, msg_created = Message.objects.get_or_create(
        wamid=message.get("id") or None,
        defaults={
            "conversation": conversation,
            "direction": Message.Direction.INBOUND,
            "kind": kind,
            "body": preview if kind == "text" else message.get(kind, {}).get("caption", ""),
            "media": media,
            "payload": message,
            "status": Message.Status.RECEIVED,
            "created_at": sent_at,
        },
    )
    if not msg_created:
        return conversation

    # An inbound message is what opens Meta's free-form window.
    conversation.open_session(sent_at)
    conversation.last_message_at = sent_at
    conversation.last_message_preview = preview[:255]
    conversation.unread_count = conversation.unread_count + 1
    conversation.status = Conversation.Status.OPEN
    conversation.save(
        update_fields=[
            "last_inbound_at",
            "session_expires_at",
            "last_message_at",
            "last_message_preview",
            "unread_count",
            "status",
        ]
    )

    if media and media.alots_media_id:
        from .media import download_media

        download_media.delay(media.pk, number.phone_number_id)

    from apps.inbox.events import publish_message

    publish_message(msg)
    return conversation


def _apply_status(status_entry):
    wamid = status_entry.get("id")
    if not wamid:
        return

    message = Message.objects.filter(wamid=wamid).first()
    if not message:
        # A status can outrun the send call that created the row; the sender
        # backfills the wamid, so a miss here is expected and harmless.
        logger.info("Status for unknown wamid %s", wamid)
        return

    new_status = STATUS_MAP.get(status_entry.get("status", ""))
    if not new_status:
        return

    # Statuses can arrive out of order; never walk a message backwards.
    rank = [
        Message.Status.QUEUED,
        Message.Status.SENT,
        Message.Status.DELIVERED,
        Message.Status.READ,
    ]
    if new_status != Message.Status.FAILED and message.status in rank and new_status in rank:
        if rank.index(new_status) <= rank.index(message.status):
            return

    fields = ["status"]
    message.status = new_status
    stamped = _ts(status_entry.get("timestamp"))

    if new_status == Message.Status.DELIVERED and not message.delivered_at:
        message.delivered_at = stamped
        fields.append("delivered_at")
    if new_status == Message.Status.READ and not message.read_at:
        message.read_at = stamped
        fields.append("read_at")
    if new_status == Message.Status.FAILED:
        errors = status_entry.get("errors") or [{}]
        message.error_code = str(errors[0].get("code", ""))[:32]
        message.error_detail = errors[0].get("title") or errors[0].get("message", "")
        fields += ["error_code", "error_detail"]

    message.save(update_fields=fields)

    from apps.inbox.events import publish_status

    publish_status(message)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_webhook_event(self, event_id):
    event = WebhookEvent.objects.filter(pk=event_id).first()
    if not event or event.status == WebhookEvent.Status.PROCESSED:
        return

    event.attempts += 1

    try:
        with transaction.atomic():
            handled = False
            for entry in event.payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
                    number = WabaNumber.objects.filter(phone_number_id=phone_number_id).first()

                    if not number:
                        # A callback for a number we do not manage. Record it
                        # rather than fail, so onboarding a new number later can
                        # replay whatever arrived early.
                        logger.warning("Webhook for unknown phone_number_id %s", phone_number_id)
                        continue

                    profiles = {
                        c.get("wa_id", ""): c.get("profile", {}).get("name", "")
                        for c in value.get("contacts", [])
                    }
                    for message in value.get("messages", []):
                        _store_inbound(number, message, profiles)
                        handled = True
                    for status_entry in value.get("statuses", []):
                        _apply_status(status_entry)
                        handled = True

            event.status = WebhookEvent.Status.PROCESSED if handled else WebhookEvent.Status.IGNORED
            event.processed_at = timezone.now()
            event.error = ""
    except Exception as exc:  # noqa: BLE001 - the raw event must never be lost
        event.status = WebhookEvent.Status.FAILED
        event.error = f"{type(exc).__name__}: {exc}"
        event.save(update_fields=["status", "error", "attempts"])
        logger.exception("Failed to process webhook event %s", event_id)
        raise self.retry(exc=exc)

    event.save(update_fields=["status", "processed_at", "error", "attempts"])
