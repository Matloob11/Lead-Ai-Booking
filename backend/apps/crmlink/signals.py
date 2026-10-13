"""One hook, for both directions.

Messages are created in several places — the webhook parser for anything the
customer sends, and half a dozen functions in ``inbox.services`` for everything
an agent does. Calling the mirror from each of them would mean remembering it
in the next one somebody writes, and the one that forgot would be invisible:
the message would arrive normally and simply never appear in the CRM.

post_save is the single door every message goes through, whoever opened it.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.inbox.models import Message

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message, dispatch_uid="crmlink_mirror_message")
def on_message_saved(sender, instance, created, **kwargs):
    # Only on creation. An outbound message is written first and updated as the
    # gateway reports it sent, then delivered, then read — mirroring on every
    # save would put the same message in the timeline four times.
    if not created:
        return

    from .tasks import mirror_message

    # Queued, never run inline: this is inside the transaction that stores the
    # message, and an HTTP call to Bitrix from here would hold that transaction
    # open for as long as the portal takes to answer.
    def queue(pk=instance.pk):
        try:
            mirror_message.delay(pk)
        except Exception as exc:  # broker down, mostly
            logger.warning("Could not queue the CRM mirror for message %s: %s", pk, exc)

    if instance.direction == Message.Direction.INBOUND:
        # A customer's message, once the webhook's transaction commits: queued
        # inside it, the worker could run before the row is visible, find no
        # message and return in silence (no customer message of the first Lead
        # AI chat reached the timeline).
        transaction.on_commit(queue)
    else:
        # Ours as before. A campaign stores its template inside the send's
        # transaction and posts its own copy to the CRM (campaigns.services,
        # renewals.post_deal_timeline): mirrored after the commit as well, every
        # lead it reaches would show the message twice.
        queue()
