"""Queue Sara after inbound messages on an active lead automation."""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.inbox.models import Message

logger = logging.getLogger(__name__)

INBOUND_DELAY_SEC = 8


@receiver(post_save, sender=Message, dispatch_uid="leadbot_on_inbound")
def on_message_saved(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.direction != Message.Direction.INBOUND:
        return
    if instance.kind in {"reaction", "system"}:
        return

    pk = instance.pk

    def enqueue():
        try:
            from .tasks import reply_to_inbound

            reply_to_inbound.apply_async(args=[pk], countdown=INBOUND_DELAY_SEC)
        except Exception as exc:
            logger.warning("Could not queue leadbot for message %s: %s", pk, exc)

    transaction.on_commit(enqueue)
