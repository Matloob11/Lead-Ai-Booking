"""Lead AI signals: confirm a chat when its campaign row settles, wake the
assistant when a customer writes in a Lead AI chat, put a customer who asks
any of our numbers to stop on the opt-out registry (optout.py), and keep a
message of ours ours when the gateway's echo of it replaces its payload."""

import logging

from django.db import DatabaseError, transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.campaigns.models import CampaignRecipient
from apps.inbox.models import Message

from .lane import is_lead_ai_conversation_id, recipient_saved

logger = logging.getLogger(__name__)
# Lead AI payloads say so in "source" (assistant/transcript.py: leadai_ai, leadai_reminder, leadai_tap, leadai_followup).
OWN_SOURCE = "leadai"


@receiver(pre_save, sender=Message, dispatch_uid="leadai_keep_own_payload")
def keep_own_payload(sender, instance, update_fields=None, **kwargs):
    """A message the Lead AI sent keeps what it stored about it (its source, its turn, the shop photo it is) when
    something replaces its payload: the gateway takes a photo sent with no caption for a status stub, and its echo
    hydrates the row with WhatsApp's own payload (gateway/ingest._hydrate_existing). Launch chat 100's four Type 2
    photos lost theirs, so the lead's timeline read them as an agent's ("WhatsApp · Agent"), and every turn after
    would have taken them for a colleague's (engine.human_after; launch review issue 25). Ours stays, over the echo's
    keys; the echo's own keys are added. One read, only when an outbound row's payload is saved without our source."""
    if instance.pk is None or instance.direction != Message.Direction.OUTBOUND:
        return
    if update_fields is not None and "payload" not in update_fields:
        return
    incoming = instance.payload if isinstance(instance.payload, dict) else {}
    if str(incoming.get("source") or "").startswith(OWN_SOURCE):
        return
    try:
        with transaction.atomic():  # its own savepoint: a failed read never breaks the save around it
            stored = Message.objects.filter(pk=instance.pk).values_list("payload", flat=True).first()
    except DatabaseError:
        logger.exception("Lead AI could not read message %s before its payload was replaced", instance.pk)
        return
    if isinstance(stored, dict) and str(stored.get("source") or "").startswith(OWN_SOURCE):
        instance.payload = {**incoming, **stored}

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


@receiver(post_save, sender=Message, dispatch_uid="leadai_optout_registry")
def on_inbound_opt_out(sender, instance, created, **kwargs):
    """Any chat, any number: a STOP, a wrong number or an Unsubscribe / Stop tap blocks
    the phone on every campaign (board T60, Q8).

    Judged here by message kind and words only (optout.message_opt_out), so it is
    cheap inside the webhook ingest; the registry is written after the commit,
    outside that transaction (_record_opt_out). There, a tap counts in every chat;
    typed words in an active Lead AI chat are left to the assistant's turn, which
    knows a STOP from "الغاء" cancelling a booked meeting and reads the customer's
    whole burst (engine.record_opt_out writes the registry there), except in a chat
    transferred to another agent, which no turn reads; and the words that are as
    often something else ("الغاء", "block") count only as the answer to a campaign
    (optout.counts).
    """
    if not created or instance.direction != Message.Direction.INBOUND or instance.mirrored_from_id:
        return
    if instance.kind not in ("text", "button", "interactive"):
        return
    try:
        from . import optout

        kind = optout.message_opt_out(instance)
        if not kind:
            return
        transaction.on_commit(lambda pk=instance.pk, k=kind: _record_opt_out(pk, k), robust=True)
    except Exception:  # noqa: BLE001 - storing a customer's message must never fail
        logger.exception("Lead AI could not judge message %s for the opt-out registry", instance.pk)


def _record_opt_out(message_id: int, kind: str) -> None:
    from . import optout

    message = Message.objects.select_related("conversation__contact").filter(pk=message_id).first()
    if message is None:
        return
    conversation = message.conversation
    if not optout.is_tap(message) and not conversation.linked_conversation_id and is_lead_ai_conversation_id(conversation.pk):
        return  # the assistant's turn reads it (engine.run_turn); a transferred chat has no turn
    if not optout.counts(message):
        return
    optout.record(conversation.contact.wa_id, reason=message.body, source=optout.inbox_source(kind), conversation=conversation)


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
