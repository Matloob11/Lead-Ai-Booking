"""Hook inbound messages without touching gateway/tasks.py."""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.inbox.models import Message

from .eligibility import is_ai_outbound_payload, should_skip_inbound_kind

logger = logging.getLogger(__name__)

INBOUND_DELAY_SEC = 8
HEALTH_DELAY_SEC = 3


@receiver(post_save, sender=Message, dispatch_uid="inboxai_on_message")
def on_message_saved(sender, instance, created, **kwargs):
    if not created:
        return

    if not should_skip_inbound_kind(instance.kind):
        conversation_id = instance.conversation_id

        def enqueue_health():
            try:
                from .tasks import consider_health

                consider_health.apply_async(args=[conversation_id], countdown=HEALTH_DELAY_SEC)
            except Exception as exc:
                logger.warning("Could not queue health for conversation %s: %s", conversation_id, exc)

        transaction.on_commit(enqueue_health)

    if instance.direction == Message.Direction.INBOUND:
        from .tasks import reply_to_inbound

        pk = instance.pk

        def enqueue():
            try:
                reply_to_inbound.apply_async(args=[pk], countdown=INBOUND_DELAY_SEC)
            except Exception as exc:
                logger.warning("Could not queue AI desk for message %s: %s", pk, exc)

        transaction.on_commit(enqueue)
        return

    if instance.direction != Message.Direction.OUTBOUND:
        return
    if not instance.sent_by_id:
        return
    if is_ai_outbound_payload(instance.payload):
        return

    from .models import ConversationAiCover

    ConversationAiCover.objects.filter(
        conversation_id=instance.conversation_id, enabled=True, paused_at__isnull=True
    ).update(paused_at=timezone.now())
