"""Lead AI signals: confirm a chat when its campaign row settles, and wake the
assistant when a customer writes in a Lead AI chat."""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.campaigns.models import CampaignRecipient
from apps.inbox.models import Message

from .lane import is_lead_ai_conversation_id, recipient_saved

logger = logging.getLogger(__name__)

# Long enough for a customer's burst of short messages to finish, so the
# assistant answers them together; the turn waits a little longer by itself
# while the customer is still typing.
ASSISTANT_DELAY_SEC = 12


@receiver(post_save, sender=Message, dispatch_uid="leadai_assistant_on_inbound")
def on_message_saved(sender, instance, created, **kwargs):
    """A new customer message -> a reminder-tap task, or one assistant turn in a Lead AI chat.

    This runs inside the webhook ingest transaction that stores the message,
    so it does as little as possible: no new table is read here (the turn
    checks everything else), and the one lookup runs in its own savepoint
    (lane.is_lead_ai_conversation_id), so it can never undo the message.
    """
    if not created or instance.direction != Message.Direction.INBOUND:
        return
    if instance.kind in ("reaction", "system") or instance.mirrored_from_id:
        return
    payload = instance.payload if isinstance(instance.payload, dict) else {}
    if payload.get("type") == "revoke":
        return
    try:
        from .assistant.reminders import looks_like_tap

        if looks_like_tap(instance):
            from .tasks import handle_reminder_tap

            transaction.on_commit(lambda pk=instance.pk: handle_reminder_tap.apply_async(args=[pk]))
            return
        if not is_lead_ai_conversation_id(instance.conversation_id):
            return
        from .tasks import assistant_turn

        transaction.on_commit(
            lambda pk=instance.pk: assistant_turn.apply_async(args=[pk], countdown=ASSISTANT_DELAY_SEC)
        )
    except Exception:  # noqa: BLE001 - storing a customer's message must never fail
        logger.exception("Lead AI could not queue the assistant for message %s", instance.pk)


@receiver(post_save, sender=CampaignRecipient, dispatch_uid="leadai_recipient_saved")
def on_recipient_saved(sender, instance, created, update_fields=None, **kwargs):
    # Only a status change can confirm or hand back a chat; the send loop saves
    # recipients often (attempt counts, CRM ids) and those are not interesting.
    if created or not update_fields or "status" not in update_fields:
        return
    try:
        recipient_saved(instance)
    except Exception:  # noqa: BLE001 - bookkeeping must never fail a campaign send
        logger.exception("Lead AI bookkeeping failed for recipient %s", instance.pk)
