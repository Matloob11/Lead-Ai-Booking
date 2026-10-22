"""A Bot Status (or WhatsApp Opt-out) a person set on a Bitrix lead reaches the assistant (board T52, C12).

Bitrix's lead-update handler (ops/bitrix-aws/a7_leadai_bot_status.php) POSTs
here when a person, never the Lead fields tool, sets Bot Status to Handed to
agent (2478), Broker (2479), Lost (2480) or Opted out (2481), or WhatsApp
Opt-out to Yes (2482). Its body carries the lead's current Bot Status, so an
opt-out may come with any status beside it. The view (bitrix_views.py) checks
the method, the size and the signature first; ``apply`` then acts on every
active Lead AI chat of that lead: the chats that came onto the screen from it
(LeadAiChat crm_entity "lead" and crm_id) and the chats a campaign sent from it
reached (CampaignRecipient.crm_lead_id).

- 2478 Handed to agent: handed over and paused until someone presses Resume
  (reason "Bitrix: handed to agent");
- 2479 Broker: the batch-1 broker path, the Broker label and a pause;
- 2480 Lost: not interested (no more invitations; an open visit is cancelled
  here, with no Bitrix write back);
- 2481 Opted out, or WhatsApp Opt-out 2482: stopped, and the lead's phones on
  the opt-out registry (optout.py), which every campaign path honours.

Applying the same change twice changes nothing more. Nothing here ever writes
to the lead (no field, no stage, no comment): the person's own save sent this,
and a write back would only come round again. Each chat gets one line in its
alerts, which the listed users (2311) receive too.

The person's value is also kept as the lead's newest one for each chat
(``remember``: a LeadAiCrmField row marked set in Bitrix, never posted), so a
value of ours queued before it never goes over it (tasks._replaced), above all a
Lost and its move waiting for a retry, and the next value of ours that differs
from it does go (crm_fields.changed). Launch review issue 19: leads 79382, 79419
and 79420 were reopened by a person after our Lost, and Bitrix now sets Handed to
agent when a person does that (board C36).
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import handover_desk
from .models import LeadAiAppointment, LeadAiChat, LeadAiChatState

logger = logging.getLogger(__name__)

HANDED = 2478
BROKER = 2479
LOST = 2480
OPTED_OUT = 2481
OPT_OUT_YES = 2482
STATUS_NAMES = {HANDED: "Handed to agent", BROKER: "Broker", LOST: "Lost", OPTED_OUT: "Opted out"}
HANDED_REASON = "Bitrix: handed to agent"
# How a row kept by ``remember`` reads (its sent_at is set: it is never posted).
SET_IN_BITRIX = "Set by a person in Bitrix: kept as the lead's newest value, never posted."


def chats_of(lead_id: int):
    """The active Lead AI chats of this lead."""
    from apps.campaigns.models import CampaignRecipient

    sent = CampaignRecipient.objects.filter(crm_lead_id=lead_id, conversation__isnull=False).values_list("conversation_id", flat=True)
    return (
        LeadAiChat.objects.filter(active=True)
        .filter(Q(crm_entity="lead", crm_id=lead_id) | Q(conversation_id__in=sent))
        .select_related("conversation__contact", "conversation__assigned_agent")
        .order_by("pk")
    )


def lead_phones(lead_id: int, chats) -> set[str]:
    """The phones of this lead we know: its chats' customers and its campaign rows."""
    from apps.campaigns.models import CampaignRecipient

    phones = {chat.conversation.contact.wa_id for chat in chats}
    phones |= set(CampaignRecipient.objects.filter(crm_lead_id=lead_id).values_list("phone", flat=True))
    return {phone for phone in phones if phone}


def effects(bot_status, wa_opt_out) -> list[str]:
    """What this change asks of the assistant, strongest first: "stop", "lost", "broker", "handed"."""
    out = []
    if bot_status == OPTED_OUT or wa_opt_out == OPT_OUT_YES:
        out.append("stop")
    if bot_status == LOST:
        out.append("lost")
    if bot_status == BROKER:
        out.append("broker")
    if bot_status == HANDED:
        out.append("handed")
    return out


def _apply_one(chat, wanted: list[str], now, reread: bool = False) -> list[str]:
    """Apply the effects to one chat; the ones that changed something. ``reread``: the lead's value read again by us
    (followups.bitrix_blocks), not a person's change: a Handed to agent still on the lead after the responsible pressed
    Done on the handover desk (handover_desk.done: desk_done_at set, and cleared by the next handover) is not applied
    again, or Done would be undone at the next nudge."""
    from .assistant import engine

    conversation = chat.conversation
    changed: list[str] = []
    with transaction.atomic():
        state, _ = LeadAiChatState.objects.select_for_update().get_or_create(conversation=conversation)
        if reread and "handed" in wanted and state.desk_done_at is not None:
            wanted = [effect for effect in wanted if effect != "handed"]
        fields: list[str] = []
        if "stop" in wanted and state.stopped_at is None:
            state.stopped_at = now
            state.stop_reason = LeadAiChatState.StopReason.STOP_ALL
            state.followup_asked_at = None
            state.followup_due_at = None
            fields += ["stopped_at", "stop_reason", "followup_asked_at", "followup_due_at"]
            changed.append("stop")
        if "lost" in wanted and state.not_interested_at is None:
            state.not_interested_at = now
            state.followup_asked_at = None
            state.followup_due_at = None
            fields += ["not_interested_at", "followup_asked_at", "followup_due_at"]
            changed.append("lost")
        if "broker" in wanted and (state.paused_at is None or not conversation.labels.filter(name__iexact=engine.BROKER_LABEL).exists()):
            if state.paused_at is None:
                state.paused_at = now
                state.paused_by = None
                fields += ["paused_at", "paused_by"]
            if state.handed_over_at is None:
                state.handed_over_at = now
                state.handover_reason = engine.BROKER
                fields += ["handed_over_at", "handover_reason"]
            conversation.labels.add(engine.broker_label())
            changed.append("broker")
            handover_desk.mark(state, now, engine.BROKER, fields)
        if "handed" in wanted and (state.paused_at is None or state.handed_over_at is None):
            if state.paused_at is None:
                state.paused_at = now
                state.paused_by = None
                fields += ["paused_at", "paused_by"]
            if state.handed_over_at is None:
                state.handed_over_at = now
                state.handover_reason = HANDED_REASON
                fields += ["handed_over_at", "handover_reason"]
            changed.append("handed")
            handover_desk.mark(state, now, HANDED_REASON, fields)
        if fields:
            state.save(update_fields=sorted(set(fields)) + ["updated_at"])
        appointment = (
            LeadAiAppointment.objects.select_for_update()
            .filter(conversation=conversation, status__in=LeadAiAppointment.OPEN)
            .order_by("-pk")
            .first()
        )
        if appointment is not None and "lost" in changed:
            # They will not come: no reminder, nobody waiting. Bitrix is not written to.
            appointment.status = LeadAiAppointment.Status.CANCELLED
            appointment.reminder_due_at = None
            appointment.log("cancelled", by="bitrix", reason="Bot Status Lost set in Bitrix")
            appointment.save(update_fields=["status", "reminder_due_at", "history", "updated_at"])
        elif appointment is not None and "stop" in changed:
            # The visit itself stays (they may still come); its reminder does not go.
            LeadAiAppointment.objects.filter(pk=appointment.pk).update(reminder_due_at=None)
    return changed


def _alert(chat, lead_id: int, bot_status, wa_opt_out, changed_by, changed: list[str], at: str) -> None:
    from .assistant import alerts

    conversation = chat.conversation
    who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
    what = []
    if bot_status in STATUS_NAMES:
        what.append(f"Bot Status {STATUS_NAMES[bot_status]}")
    if wa_opt_out == OPT_OUT_YES:
        what.append("WhatsApp Opt-out Yes")
    by = f"Bitrix user {changed_by}" if str(changed_by or "").isdigit() and int(changed_by) > 0 else "someone in Bitrix"
    done = {
        "stop": "The assistant stopped in this chat, and the phone is blocked on every campaign.",
        "lost": "The assistant will not invite them again.",
        "broker": 'The chat is labelled "Broker" and the assistant stays silent until someone presses Resume AI.',
        "handed": "The assistant is paused in this chat until someone presses Resume AI.",
    }
    lines = [f"{by} set {' and '.join(what) or 'a Bot Status'} on lead {lead_id} ({who}, WhatsApp +{conversation.contact.wa_id})."]
    lines += [done[key] for key in changed]
    alerts.raise_alert(
        kind="bitrix_status",
        conversation=conversation,
        title=f"{who}: {' and '.join(what) or 'Bot Status'} set in Bitrix",
        text="\n".join(lines),
        dedupe_key=f"bitrix_status:{conversation.pk}:{bot_status or 0}:{wa_opt_out or 0}:{(at or '')[:25]}",
        crm_url=alerts.crm_path("lead", lead_id),
    )


def remember(chat, lead_id: int, bot_status, wa_opt_out, changed_by, now) -> list[str]:
    """The person's Bot Status (and WhatsApp Opt-out Yes) as this chat's newest value for the lead it writes to
    (crm_fields.lead_of; another lead of the chat is not ours to stand for). Returns the fields kept."""
    from .assistant import crm_fields
    from .models import LeadAiCrmField

    conversation = chat.conversation
    if crm_fields.lead_of(chat, conversation) != lead_id:
        return []
    values = []
    if bot_status in crm_fields.STATUSES:
        values.append((crm_fields.FIELD_BOT_STATUS, str(bot_status)))
    if wa_opt_out == OPT_OUT_YES:
        values.append((crm_fields.FIELD_OPT_OUT, str(wa_opt_out)))
    last = crm_fields.last_values(conversation, lead_id) if values else {}
    kept = []
    for field, value in values:
        if last.get(field) == value:
            continue  # what this chat knows the lead holds already
        LeadAiCrmField.objects.create(
            conversation=conversation, lead_id=lead_id, field=field, value=value,
            payload={"set_in_bitrix": True, "changed_by": changed_by}, sent_at=now, error=SET_IN_BITRIX,
        )
        kept.append(field)
    return kept


def apply(lead_id: int, bot_status=None, wa_opt_out=None, changed_by=None, at: str = "", *, reread: bool = False) -> int:
    """Apply a person's Bitrix change to every active Lead AI chat of the lead. Returns how
    many chats there are (0 when none, or when the change asks nothing of the assistant).
    ``reread``: the lead's current value read by us, not a person's change (_apply_one)."""
    from . import optout
    from .assistant import live

    wanted = effects(bot_status, wa_opt_out)
    if not wanted:
        return 0
    chats = list(chats_of(lead_id))
    now = timezone.now()
    if "stop" in wanted:
        # The registry first: it holds even when no chat of the lead is on the screen.
        conversation = chats[0].conversation if chats else None
        for phone in lead_phones(lead_id, chats):
            optout.record(phone, reason=f"Set in Bitrix on lead {lead_id}", source=optout.Source.BITRIX, conversation=conversation)
    for chat in chats:
        changed = _apply_one(chat, wanted, now, reread=reread)
        remember(chat, lead_id, bot_status, wa_opt_out, changed_by, now)
        if changed:
            _alert(chat, lead_id, bot_status, wa_opt_out, changed_by, changed, at)
            transaction.on_commit(lambda pk=chat.conversation_id: live.appointment_changed(pk))
        logger.info("Lead AI: Bitrix Bot Status on lead %s reached conversation %s (%s)", lead_id, chat.conversation_id, ",".join(changed) or "no change")
    return len(chats)
