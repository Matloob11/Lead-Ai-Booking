"""Which chats belong to the Lead AI screen, and the few hooks that keep it so.

Everything the rest of the code base calls lives here, so the main inbox only
ever holds one-line calls into this module:

- ``hide_lead_ai(queryset)``: the main inbox list leaves these chats out.
- ``event_name(conversation, event)``: live events for them get a ``leadai.``
  prefix, which the main inbox does not listen to and the Lead AI screen does.
- ``is_lead_ai(conversation)``: Sara and the inbox AI desk stay silent.
- ``mark_campaign`` / ``before_campaign_send`` / ``recipient_saved``: a
  campaign sent with the popup checkbox puts each chat it reaches here,
  before its first message is broadcast; ``mark_campaign`` also takes the
  script (playbook) the popup chose, which ``playbook_for`` reads per chat.
- ``move_to_inbox``: the one way back to the main inbox.
- ``desk_q`` / ``desk_groups`` / ``desk_event_groups``: the Lead AI desk (batch
  2e, Q37). An agent with Lead AI access (``Agent.can_lead_ai``) opens every
  chat on the Lead AI screen, whatever its number, and hears its live events;
  the main inbox list still leaves those chats out (``hide_lead_ai``).
"""

from __future__ import annotations

import logging

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import LeadAiCampaign, LeadAiChat

logger = logging.getLogger(__name__)

EVENT_PREFIX = "leadai."
GENERAL = LeadAiCampaign.Playbook.GENERAL
IC_SHOPS = LeadAiCampaign.Playbook.IC_SHOPS
# The live channel of the agents with Lead AI access who are not panel admins (a panel admin hears
# every number's group already): every Lead AI chat's "leadai.*" events, and nothing else.
DESK_GROUP = "wa.leadai.desk"


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


# The Lead AI desk (batch 2e spec §2.12, board T100; Q37) --------------------


def has_desk_access(user) -> bool:
    """The agent follows every Lead AI chat (Matloob, Q37, 2026-10-17: the chats are not assigned; the agents
    with Lead AI access follow them on the Lead AI screen). Granted per agent in "Agents & access"
    (``Agent.can_lead_ai``), and only with the Official API inbox, which every Lead AI chat belongs to."""
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "can_lead_ai", False)
        and getattr(user, "can_official_api", True)
    )


def desk_q(user):
    """inbox.visibility's clause for the desk: every active Lead AI chat, on any number, for an agent with Lead AI
    access; None for anyone else, whose visibility stays exactly what it was (not even a query more). The main
    inbox list leaves these chats out all the same (hide_lead_ai)."""
    if not has_desk_access(user):
        return None
    return Q(pk__in=LeadAiChat.objects.filter(active=True).values("conversation_id"))


def desk_groups(user) -> list[str]:
    """The live group a desk agent joins (inbox.consumers): only one who is no panel admin, since a panel admin
    hears every number's group, and would get each event twice."""
    from apps.inbox.visibility import sees_all_inbox_chats

    return [DESK_GROUP] if has_desk_access(user) and not sees_all_inbox_chats(user) else []


def desk_groups_for(event: str, conversation=None) -> tuple[list[str], list[str]]:
    """The groups besides the number's and the owner's that hear an event (inbox.events.publish), as (in full, trimmed):
    a Lead AI chat's own ("leadai.*") reach the desk in full, and the chat's Bitrix responsible on the handover desk
    (handover_desk.live_groups) in full when they hold the chat's number, trimmed when they have the chat through the
    desk alone (trim_for_desk: the chat and the customer, nothing of the team). A chat back in the main inbox is no
    desk chat, and its plain events reach neither."""
    if not str(event or "").startswith(EVENT_PREFIX):
        return [], []
    full = [DESK_GROUP]
    if conversation is None:
        return full, []
    from .handover_desk import live_groups

    theirs, trimmed = live_groups(conversation)
    return full + theirs, trimmed


def desk_event_groups(event: str, conversation=None) -> list[str]:
    """The groups that hear an event in full (desk_groups_for)."""
    return desk_groups_for(event, conversation)[0]


def desk_scoped_groups(event: str, conversation=None) -> list[str]:
    """The groups that hear an event trimmed (desk_groups_for)."""
    return desk_groups_for(event, conversation)[1]


def trim_for_desk(data: dict) -> dict:
    """A live frame's data for the responsible's channel (handover_desk.trim_live)."""
    from .handover_desk import trim_live

    return trim_live(data)


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


def playbook_value(value) -> str:
    """A playbook the assistant knows; anything else is general."""
    return value if value in LeadAiCampaign.Playbook.values else GENERAL


def mark_campaign(campaign, playbook: str | None = None, community: str | None = None) -> LeadAiCampaign:
    """Make a campaign a Lead AI campaign whose chats follow ``playbook``.

    Not given, it is general (as is an unknown value). A campaign marked
    already keeps its playbook unless one is passed. ``community``: the pack the
    campaign sells (assistant/communities.py; Cursor's C44 popup passes it), kept
    as the pack's own name; a name no pack knows is left out.
    """
    from .assistant import communities

    chosen = playbook_value(playbook)
    pack = communities.by_name(community) if community else None
    wanted = pack.name if pack is not None and not pack.default else ""
    row, created = LeadAiCampaign.objects.get_or_create(campaign=campaign, defaults={"playbook": chosen, "community": wanted})
    fields = []
    if not created and playbook is not None and row.playbook != chosen:
        row.playbook = chosen
        fields.append("playbook")
    if not created and community is not None and row.community != wanted:
        row.community = wanted
        fields.append("community")
    if fields:
        row.save(update_fields=fields)
    return row


def _campaign_row(campaign) -> LeadAiCampaign | None:
    if campaign is None or not getattr(campaign, "pk", None):
        return None
    try:
        with transaction.atomic():
            return LeadAiCampaign.objects.filter(campaign_id=campaign.pk).first()
    except DatabaseError:
        logger.exception("Lead AI campaign lookup failed for campaign %s", campaign.pk)
        return None


def is_lead_ai_campaign(campaign) -> bool:
    return _campaign_row(campaign) is not None


def inherit_campaign(source, target) -> None:
    """A retry of a Lead AI campaign ("resend skipped") is a Lead AI campaign too, with its playbook."""
    row = _campaign_row(source)
    if row is not None:
        mark_campaign(target, playbook=row.playbook)


def playbooks(conversation_ids) -> dict:
    """{conversation id: playbook} for those of these chats that are on the Lead AI
    screen: two queries for a whole page of the list.

    The newest Lead AI campaign that reached the chat decides, so a shop
    campaign sent to a chat an older campaign put here switches it to the shop
    script; a chat with no such send on record follows the campaign that put
    it here.
    """
    from apps.campaigns.models import CampaignRecipient

    ids = [int(pk) for pk in conversation_ids if pk]
    if not ids:
        return {}
    out = {
        conversation_id: playbook_value(value)
        for conversation_id, value in LeadAiChat.objects.filter(conversation_id__in=ids, active=True).values_list(
            "conversation_id", "campaign__lead_ai__playbook"
        )
    }
    if out:
        sends = (
            CampaignRecipient.objects.filter(conversation_id__in=list(out), campaign__lead_ai__isnull=False)
            .order_by("pk")
            .values_list("conversation_id", "campaign__lead_ai__playbook")
        )
        for conversation_id, value in sends:  # oldest first: the newest is the one kept
            out[conversation_id] = playbook_value(value)
    return out


def playbook_for(conversation) -> str:
    """The script the assistant follows in this chat; general when it is not a Lead AI chat."""
    if conversation is None or not getattr(conversation, "pk", None):
        return GENERAL
    return playbooks([conversation.pk]).get(conversation.pk, GENERAL)


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
        # Off its responsible's handover desk too: the chat is a person's in the main inbox now.
        from .handover_desk import clear

        clear(conversation, agent)
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
