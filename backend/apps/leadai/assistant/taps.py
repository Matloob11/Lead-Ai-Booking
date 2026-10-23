"""Taps on the meeting reminder's buttons, handled by code (owner's rules 54-56).

A tap needs no model: it sets the appointment's state, alerts the agents and
sends the owner's own words back ("Perfect. See you shortly."), in the
customer's language. In a shops chat, "Need to Reschedule" gets the two nearest
free slots from the slot finder instead of an open question (board T44); the
time they pick then re-books through the assistant's normal turn. It works even after "Move to inbox" (the meeting still
stands), and its alert goes out even when the assistant is switched off; only
the reply then stays unsent. A tap that is not on our reminder for a meeting
around now (reminders.tap_on_reminder) is left to the assistant's normal
turn, like any message. A customer who then types their new arrival time or a
new day is answered by the assistant's normal turn (on the Lead AI screen) or
by the agent.

Reminder v2's fourth quick reply, [Office Location] (board T45, batch 2e), asks
for the way: it changes nothing on the meeting and alerts nobody, and is
answered with the office's address and Maps link, then the pin.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.inbox.models import Message

from ..models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn
from . import alerts, calls, filters, hours, reminders, rules, transcript

logger = logging.getLogger(__name__)

SOURCE = transcript.TAP_REPLY

STATES = {
    "on_my_way": LeadAiAppointment.CustomerState.ON_MY_WAY,
    "running_late": LeadAiAppointment.CustomerState.RUNNING_LATE,
    "reschedule": LeadAiAppointment.CustomerState.RESCHEDULE,
}


def reply_line(action: str, language: str, slots: list | None = None, now=None, contact=None) -> str:
    """The owner's words for a tap (rules 54-56), in the customer's language. ``slots``: a
    shops chat's two nearest free starts, offered for "Need to Reschedule" (T44). ``contact``: whom a client on the
    way may call (LeadAiSettings.visit_contact), with "On My Way"."""
    if action == "on_my_way":
        return filters.on_my_way(language, contact)
    if action == "reschedule" and slots is not None:
        from . import shop_flow

        return shop_flow.reschedule_text(language, slots, now)
    return rules.line("ask_eta" if action == "running_late" else "ask_new_time", language)


def _reschedule_slots(conversation, appointment, now) -> list | None:
    """A shops chat's two nearest free slots for a move (never the one they have), else None."""
    from .. import lane

    if lane.playbook_for(conversation) != lane.IC_SHOPS:
        return None
    from . import engine

    # A buyer's call moves within the call pool (batch 2e slice C), a visit within the office's.
    taken = calls.taken(conversation, now) if calls.is_sales_call(appointment) else engine.taken_slots(conversation, now)
    own = [appointment.starts_at] if appointment.starts_at else []
    return hours.offer_pair(now, LeadAiSettings.load().closed_dates, [*taken, *own])


def handle(message_id: int) -> str:
    """Apply one tap. Returns what happened (for the turn log and tests)."""
    message = (
        Message.objects.select_related("conversation__contact", "conversation__assigned_agent", "reply_to")
        .filter(pk=message_id)
        .first()
    )
    if message is None or message.direction != Message.Direction.INBOUND:
        return "not an inbound message"
    # Checked before anything is claimed: a tap outside the meeting's window, or
    # on a reminder for another time, is answered by the assistant instead.
    appointment, action = reminders.tap_on_reminder(message)
    if appointment is None:
        return "not a tap on our reminder"
    try:
        with transaction.atomic():
            turn = LeadAiTurn.objects.create(conversation_id=message.conversation_id, inbound=message)
    except IntegrityError:
        return "already handled"

    conversation = message.conversation
    now = timezone.now()
    if action == reminders.LOCATION:
        return _answer_location(message, conversation, appointment, turn, now)
    outcome = LeadAiTurn.Status.SKIPPED
    reply_id = None
    with transaction.atomic():
        current = LeadAiAppointment.objects.select_for_update().get(pk=appointment.pk)
        current.customer_state = STATES[action]
        current.log("tap", action=action, message=message.pk)
        current.save(update_fields=["customer_state", "history", "updated_at"])
        _alert(conversation, current, action)
        from ..tasks import sync_appointment_crm

        event = {"on_my_way": "on_my_way", "running_late": "running_late_tap", "reschedule": "reschedule_requested"}[action]
        transaction.on_commit(lambda pk=current.pk, e=event: sync_appointment_crm.delay(pk, e, False))
    from . import live

    live.appointment_changed(conversation.pk)
    reason = f"tap: {action}"
    settings_row = LeadAiSettings.load()
    if settings_row.answers(conversation.contact.wa_id) and _window_open(conversation, now):
        language = LeadAiChatState.objects.filter(conversation=conversation).values_list("language", flat=True).first() or "en"
        slots = _reschedule_slots(conversation, appointment, now) if action == "reschedule" else None
        # A buyer's call (batch 2e slice C): "On My Way" is ready for the call, "Running Late" a later call (spec §3.3.7).
        line = (calls.tap_line(action, language) if calls.is_sales_call(appointment) else "") or reply_line(
            action, language, slots, now, contact=settings_row.visit_contact()
        )
        try:
            from apps.inbox import services as inbox_services

            sent = inbox_services.send_text(conversation, None, line, payload={"source": SOURCE, "turn": turn.pk})
            reply_id = sent.pk
            outcome = LeadAiTurn.Status.REPLIED
        except Exception as exc:  # noqa: BLE001 - the state and the alert already stand
            logger.warning("Lead AI tap reply failed on conversation %s: %s", conversation.pk, exc)
            outcome = LeadAiTurn.Status.FAILED
            reason = f"tap reply failed: {type(exc).__name__}"
    else:
        reason += " (no reply: assistant off or window closed)"

    LeadAiTurn.objects.filter(pk=turn.pk).update(
        status=outcome, reason=reason[:255], reply_message_id=reply_id, actions={"tap": action}, finished_at=timezone.now()
    )
    return reason


def _answer_location(message, conversation, appointment, turn, now) -> str:
    """[Office Location] on reminder v2 (T45): the office's address and Maps link in the customer's language, then the
    pin when the settings hold one. The meeting stays as it is and nobody is alerted (they are on their way, or about to
    be: "On My Way" says so). Only while the assistant may speak and the window is open, as any tap's reply."""
    from apps.inbox import services as inbox_services

    with transaction.atomic():
        current = LeadAiAppointment.objects.select_for_update().get(pk=appointment.pk)
        current.log("tap", action=reminders.LOCATION, message=message.pk)
        current.save(update_fields=["history", "updated_at"])
    reason = f"tap: {reminders.LOCATION}"
    outcome, reply_id = LeadAiTurn.Status.SKIPPED, None
    settings_row = LeadAiSettings.load()
    if settings_row.answers(conversation.contact.wa_id) and _window_open(conversation, now):
        language = LeadAiChatState.objects.filter(conversation=conversation).values_list("language", flat=True).first() or "en"
        payload = {"source": SOURCE, "turn": turn.pk}
        try:
            sent = inbox_services.send_text(conversation, None, reminders.location_reply(settings_row, language), payload=payload)
            reply_id, outcome = sent.pk, LeadAiTurn.Status.REPLIED
        except Exception as exc:  # noqa: BLE001 - nothing else hangs on it
            logger.warning("Lead AI could not answer the location tap on conversation %s: %s", conversation.pk, exc)
            outcome, reason = LeadAiTurn.Status.FAILED, f"tap reply failed: {type(exc).__name__}"
        if reply_id is not None and settings_row.has_pin:
            try:
                inbox_services.send_location(
                    conversation, None, float(settings_row.office_latitude), float(settings_row.office_longitude),
                    name="Our office", address=settings_row.office_address, payload=payload,
                )
            except Exception as exc:  # noqa: BLE001 - the address and the link went out already
                logger.warning("Lead AI could not send the office pin for the location tap on conversation %s: %s", conversation.pk, exc)
    else:
        reason += " (no reply: assistant off or window closed)"
    LeadAiTurn.objects.filter(pk=turn.pk).update(
        status=outcome, reason=reason[:255], reply_message_id=reply_id, actions={"tap": reminders.LOCATION}, finished_at=timezone.now()
    )
    return reason


def _window_open(conversation, now) -> bool:
    conversation.refresh_from_db(fields=["session_expires_at"])
    return bool(conversation.session_expires_at and conversation.session_expires_at > now + dt.timedelta(minutes=1))


def _alert(conversation, appointment, action: str) -> None:
    name = appointment.customer_name or conversation.contact.display_name or "The customer"
    at = hours.time_label(appointment.starts_at) if appointment.starts_at else ""
    stamp = f"{appointment.starts_at:%Y%m%d%H%M}" if appointment.starts_at else "none"
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    crm_url = alerts.crm_path(
        appointment.crm_entity or (chat.crm_entity if chat else ""), appointment.crm_id or (chat.crm_id if chat else None)
    )
    phone = f"WhatsApp +{conversation.contact.wa_id}"
    call = calls.tap_alert(action, name, at, phone) if calls.is_sales_call(appointment) else None
    if call is not None:
        # A buyer's call (batch 2e slice C): ready for it, or wants it later.
        title, text = call
        alerts.raise_alert(
            kind=action, conversation=conversation, appointment=appointment, priority="high", title=title, text=text,
            dedupe_key=f"{'on_my_way' if action == 'on_my_way' else 'running_late_tap'}:{appointment.pk}:{stamp}", crm_url=crm_url,
        )
    elif action == "on_my_way":
        alerts.raise_alert(
            kind="on_my_way",
            conversation=conversation,
            appointment=appointment,
            priority="high",
            title=f"{name} is on the way",
            text=f"{name} is on the way for the {at} meeting ({phone}).",
            dedupe_key=f"on_my_way:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif action == "running_late":
        alerts.raise_alert(
            kind="running_late",
            conversation=conversation,
            appointment=appointment,
            priority="high",
            title=f"{name} is running late",
            text=f"{name} tapped Running Late for the {at} meeting ({phone}). We asked for their arrival time.",
            dedupe_key=f"running_late_tap:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    else:
        alerts.raise_alert(
            kind="reschedule_requested",
            conversation=conversation,
            appointment=appointment,
            title=f"{name} wants to reschedule",
            text=f"{name} tapped Need to Reschedule for the {at} meeting ({phone}). We asked for a new day and time.",
            dedupe_key=f"reschedule_requested:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
