"""Which chats belong to the Lead AI screen, and the few hooks that keep it so.

Everything the rest of the code base calls lives here, so the main inbox only
ever holds one-line calls into this module:

- ``hide_lead_ai(queryset)``: the main inbox list leaves these chats out.
- ``event_name(conversation, event)``: live events for them get a ``leadai.``
  prefix, which the main inbox does not listen to and the Lead AI screen does.
- ``is_lead_ai(conversation)``: Sara and the inbox AI desk stay silent.
- ``mark_campaign`` / ``before_campaign_send`` / ``recipient_saved``: a
  campaign sent with the popup checkbox puts each chat it reaches here,
  before its first message is broadcast.
- ``move_to_inbox``: the one way back to the main inbox.
"""

from __future__ import annotations

import logging

from django.db import DatabaseError, transaction
from django.utils import timezone

from .models import LeadAiCampaign, LeadAiChat

logger = logging.getLogger(__name__)

EVENT_PREFIX = "leadai."


def _digits(raw) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


# Reading -------------------------------------------------------------------


def is_lead_ai(conversation) -> bool:
    """Asked inside other code's transactions (a send, an ingest), so it runs in a
    savepoint: a failure here must not abort the caller's transaction, which
    could roll back a message the gateway has already sent."""
    if conversation is None or not getattr(conversation, "pk", None):
        return False
    try:
        with transaction.atomic():
            return LeadAiChat.objects.filter(conversation_id=conversation.pk, active=True).exists()
    except DatabaseError:
        logger.exception("Lead AI lookup failed for conversation %s", conversation.pk)
        return False


def is_lead_ai_conversation_id(conversation_id) -> bool:
    """is_lead_ai by id, for the inbound-message signal: no extra query to load
    the conversation, and the same savepoint, so a failure can never abort the
    webhook ingest transaction that is storing the customer's message."""
    if not conversation_id:
        return False
    try:
        with transaction.atomic():
            return LeadAiChat.objects.filter(conversation_id=conversation_id, active=True).exists()
    except DatabaseError:
        logger.exception("Lead AI lookup failed for conversation %s", conversation_id)
        return False


def handles_failed_outbound(message) -> bool:
    """A FAILED status on an outbound message: is it Lead AI's to handle?

    Called by gateway.ingest before it re-queues the chat's campaign template.
    True means "not the campaign's failure, do not re-send it":
    - an assistant reply, reminder or pin (payload source 'leadai...'): the
      Lead AI tells the agents instead (tasks.outbound_failed);
    - any other message in an active Lead AI chat except the campaign's own
      template (an agent's message failing is not the campaign failing).
    Runs in a savepoint inside the status webhook's transaction, so a failure
    here can never undo the status update.
    """
    data = message.payload if isinstance(message.payload, dict) else {}
    source = str(data.get("source") or "")
    try:
        with transaction.atomic():
            if source.startswith("leadai"):
                from .tasks import outbound_failed

                transaction.on_commit(lambda pk=message.pk: outbound_failed.delay(pk))
                return True
            if not LeadAiChat.objects.filter(conversation_id=message.conversation_id, active=True).exists():
                return False
            if message.kind == "template" and message.template_id:
                from apps.campaigns.models import CampaignRecipient

                if CampaignRecipient.objects.filter(
                    conversation_id=message.conversation_id, campaign__template_id=message.template_id
                ).exists():
                    return False
            return True
    except DatabaseError:
        logger.exception("Lead AI failed-status check broke for message %s", message.pk)
        return False


def hide_lead_ai(queryset):
    """The main inbox list: every chat except the ones the Lead AI screen holds."""
    return queryset.exclude(lead_ai_chat__active=True)


def only_lead_ai(queryset):
    return queryset.filter(lead_ai_chat__active=True)


def event_name(conversation, event: str) -> str:
    """``message.new`` stays ``message.new`` unless the chat is a Lead AI chat."""
    if event.startswith(EVENT_PREFIX):
        return event
    try:
        return EVENT_PREFIX + event if is_lead_ai(conversation) else event
    except Exception:  # noqa: BLE001 - a lookup failure must not stop a live event
        logger.exception("Lead AI lookup failed for conversation %s", getattr(conversation, "pk", None))
        return event


# Campaigns -----------------------------------------------------------------


def mark_campaign(campaign) -> LeadAiCampaign:
    row, _ = LeadAiCampaign.objects.get_or_create(campaign=campaign)
    return row


def is_lead_ai_campaign(campaign) -> bool:
    if campaign is None or not getattr(campaign, "pk", None):
        return False
    try:
        with transaction.atomic():
            return LeadAiCampaign.objects.filter(campaign_id=campaign.pk).exists()
    except DatabaseError:
        logger.exception("Lead AI campaign lookup failed for campaign %s", campaign.pk)
        return False


def inherit_campaign(source, target) -> None:
    """A retry of a Lead AI campaign ("resend skipped") is a Lead AI campaign too."""
    if is_lead_ai_campaign(source):
        mark_campaign(target)


def _owner_data_chosen(campaign) -> bool:
    """Was the recipient's Owner Data card the agent's own pick?

    Only the Owner Data popup sends from cards the agent picked. On any other
    row (a Contacts popup row has no CRM column of its own) the send itself
    fills owner_data_id: with whatever card carries the phone, on any board,
    often another agent's listing, or with a card it makes. Neither is the
    agent's record, so the chat gets none and the assistant finds the
    customer's record by phone (crm.record_for), never as a chosen one.
    """
    from apps.campaigns.crm_leads import ENTITY_NOUNS

    label = ENTITY_NOUNS["owner_data"][2]  # send_from_leads names a campaign after its popup
    return str(getattr(campaign, "name", "") or "").startswith(f"{label} ·")


def _crm_ref(campaign, recipient) -> tuple[str, int | None]:
    if getattr(recipient, "crm_lead_id", None):
        return "lead", int(recipient.crm_lead_id)
    if getattr(recipient, "crm_deal_id", None):
        return "deal", int(recipient.crm_deal_id)
    if getattr(recipient, "owner_data_id", None) and _owner_data_chosen(campaign):
        return "owner_data", int(recipient.owner_data_id)
    return "", None


def _conversation_for(campaign, phone, *, create: bool):
    """The same (number, customer) thread start_conversation would use."""
    from apps.inbox.models import Contact, Conversation

    wa_id = _digits(phone)
    if len(wa_id) < 8:
        return None
    if not create:
        return Conversation.objects.filter(number=campaign.number, contact__wa_id=wa_id).first()
    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    conversation, _ = Conversation.objects.get_or_create(
        number=campaign.number, contact=contact, defaults={"assigned_agent": campaign.created_by}
    )
    return conversation


def before_campaign_send(campaign, recipient) -> None:
    """Put the recipient's chat in the Lead AI screen before its message goes out.

    Called just before start_conversation, inside the same transaction, which
    looks the thread up with the same (number, customer) key and so finds this
    one; the message it sends is broadcast as a Lead AI event and never
    reaches the main inbox. If the send fails, the mark rolls back with it.
    """
    if not is_lead_ai_campaign(campaign):
        return
    conversation = _conversation_for(campaign, recipient.phone, create=True)
    if conversation is None:
        return
    entity, crm_id = _crm_ref(campaign, recipient)
    # A thread with history was showing in the main inbox until now.
    was_listed = conversation.last_message_at is not None
    with transaction.atomic():
        chat, created = LeadAiChat.objects.select_for_update().get_or_create(
            conversation=conversation,
            defaults={
                "active": True,
                "confirmed": False,
                "campaign": campaign,
                "added_by": campaign.created_by,
                "crm_entity": entity,
                "crm_id": crm_id,
            },
        )
        if not created:
            if chat.active:
                return
            # The agent moved it to the inbox after THIS campaign put it here;
            # a background retry of the same campaign must not undo that. Only
            # a different Lead AI campaign brings it back.
            if chat.campaign_id == campaign.pk and chat.moved_at:
                return
            chat.active = True
            chat.confirmed = False
            chat.campaign = campaign
            chat.added_by = campaign.created_by
            chat.crm_entity = entity
            chat.crm_id = crm_id
            chat.moved_by = None
            chat.moved_at = None
            chat.save()
    if was_listed:
        # After the send commits: a failed send rolls the mark back, and the
        # chat never left the main inbox.
        pk = conversation.pk
        transaction.on_commit(lambda: _announce(pk))


def recipient_saved(recipient) -> None:
    """A Lead AI send was accepted by the gateway: note it on the chat.

    Nothing hands a chat back on a failure. A failed send rolls its mark back
    (process_recipient), and once a message went out only the agent's "Move to
    inbox" returns the chat, as agreed with Matloob on 2026-10-08.
    """
    from apps.campaigns.models import CampaignRecipient

    if recipient.status != CampaignRecipient.Status.SENT or not recipient.conversation_id:
        return
    if not is_lead_ai_campaign(recipient.campaign):
        return
    LeadAiChat.objects.filter(
        conversation_id=recipient.conversation_id, active=True, confirmed=False
    ).update(confirmed=True, updated_at=timezone.now())


# Moving ----------------------------------------------------------------------


def move_to_inbox(conversation, agent) -> bool:
    """The agent's "Move to inbox". Returns False when it was not a Lead AI chat."""
    updated = LeadAiChat.objects.filter(conversation=conversation, active=True).update(
        active=False, moved_by=agent, moved_at=timezone.now(), updated_at=timezone.now()
    )
    if updated:
        _announce(conversation.pk)
    return bool(updated)


def _announce(conversation_pk) -> None:
    """Publish the chat as it is NOW, so every screen files it in the right list.

    Re-read rather than reusing the caller's object: that one may carry a
    cached Lead AI row from before the change, which would tell the main inbox
    the chat is still Lead AI. Still Lead AI, the event goes out as
    leadai.conversation.updated (the main inbox drops the row); back in the
    inbox, as a plain conversation.updated (the main inbox lists it again).
    """
    try:
        from apps.inbox.events import publish_conversation
        from apps.inbox.models import Conversation

        conversation = (
            Conversation.objects.select_related(
                "contact", "number", "assigned_agent", "linked_conversation__number", "lead_ai_chat"
            )
            .filter(pk=conversation_pk)
            .first()
        )
        if conversation is not None:
            publish_conversation(conversation)
    except Exception:  # noqa: BLE001 - the change stands even if no socket hears it
        logger.exception("Could not announce conversation %s", conversation_pk)
