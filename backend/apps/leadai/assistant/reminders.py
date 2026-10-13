"""The WhatsApp reminder 30 minutes before a booked visit (owner's rules 52-56, 61).

Every minute the sweep (tasks.send_due_reminders) claims due appointments one
at a time (``reminder_claimed_at``), re-reads each just before sending, and
marks it sent only if its time did not change meanwhile; a reschedule clears
the claim and re-arms the reminder for the new time.

While the customer's 24-hour window is open (with a 10-minute margin) the
reminder is a free-form message in the customer's language with three reply
buttons. When it is closed WhatsApp only allows an approved template, so the
UTILITY template ``a7_leadai_meeting_reminder`` (English, same three quick
replies) is used if it is approved on the chat's number; with no template and
a few minutes of window left, the buttons still go. If neither is possible
the agents are told to remind the customer by hand.

Reminders go out for a booked visit even after "Move to inbox" (the meeting
still stands), but never to a customer who asked us to stop, and not while
the assistant is switched off. A STOP, wrong number or "not interested" that
no assistant turn ever saw (a chat moved to the inbox, a lost task) is caught
here, just before sending, and recorded like any other.

A tap on the buttons counts as an answer to our reminder only while the
meeting stands and is around now (12 hours before to 3 hours after); outside
that, or on a reminder for another time, it is an ordinary message.
"""

from __future__ import annotations

import datetime as dt
import logging

from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.inbox.models import Message

from ..models import LeadAiAppointment, LeadAiChatState, LeadAiSettings, LeadAiTurn
from . import filters, hours, live, rules, transcript

logger = logging.getLogger(__name__)

TEMPLATE_NAME = "a7_leadai_meeting_reminder"
SOURCE = transcript.REMINDER
STALE_CLAIM = dt.timedelta(minutes=10)
TOO_LATE = dt.timedelta(minutes=10)
WINDOW_MARGIN = dt.timedelta(minutes=10)
TAP_FALLBACK_WINDOW = dt.timedelta(hours=3)
# A tap is an answer to our reminder from 12 hours before the meeting until
# the sweep closes it as past (tasks.PAST_AFTER, 3 hours after the start).
TAP_VALID_BEFORE = dt.timedelta(hours=12)
TAP_VALID_AFTER = dt.timedelta(hours=3)
# How far back, at most, the reminder looks for an opt-out nobody recorded.
OPT_OUT_LOOKBACK = dt.timedelta(hours=48)
SENT_STATUSES = (Message.Status.SENT, Message.Status.DELIVERED, Message.Status.READ)

SWITCHED_OFF = "The assistant is switched off, so the reminder was not sent."
OPTED_OUT = "The customer asked us to stop messaging, so the reminder was not sent."
DECLINED = "The customer said they are not interested, so the meeting was cancelled and no reminder sent."

# (action, button title). Titles fit WhatsApp's 20-character limit and are
# the exact quick-reply texts of the template.
BUTTONS = (
    ("on_my_way", "On My Way"),
    ("running_late", "Running Late"),
    ("reschedule", "Need to Reschedule"),
)
ACTION_BY_LABEL = {label.lower(): action for action, label in BUTTONS}

# The free-form reminder, in the customer's language: (first line, last line).
# The buttons stay in English, as in the template.
REMINDER_LINES = {
    "en": ("Hi {name}, a reminder of your meeting today at {time} at our office:", "Please tap below to let us know."),
    "ar": ("مرحباً {name}، نذكّرك بموعدك اليوم الساعة {time} في مكتبنا:", "يرجى الضغط على أحد الأزرار أدناه لإبلاغنا."),
    "ur_latin": (
        "Hi {name}, yaad dihani: aaj {time} par hamare office mein aap ki meeting hai:",
        "Barah-e-karam neeche button daba kar humein bata dein.",
    ),
    "ur": ("السلام علیکم {name}، یاد دہانی: آج {time} پر ہمارے آفس میں آپ کی میٹنگ ہے:", "براہ کرم نیچے بٹن دبا کر ہمیں بتا دیں۔"),
    "hi_latin": (
        "Hi {name}, reminder: aaj {time} par hamare office mein aapki meeting hai:",
        "Kripya neeche button dabakar humein bata dijiye.",
    ),
    "hi": ("नमस्ते {name}, याद दिला दें: आज {time} पर हमारे ऑफ़िस में आपकी मीटिंग है:", "कृपया नीचे बटन दबाकर हमें बता दीजिए।"),
}


def _first(appointment: LeadAiAppointment, conversation=None) -> str:
    name = (appointment.customer_name or "").strip()
    if not name and conversation is not None:
        name = (conversation.contact.display_name or "").strip()
    return filters.first_name(name)


def first_name(appointment: LeadAiAppointment, conversation=None) -> str:
    return _first(appointment, conversation) or "there"


def _stamp(start) -> str:
    return f"{start.astimezone(hours.DUBAI):%Y%m%d%H%M}" if start else ""


def button_id(appointment: LeadAiAppointment, action: str) -> str:
    """'leadai:<pk>:<start, Dubai YYYYmmddHHMM>:<action>': a tap names the time it was sent for."""
    return f"leadai:{appointment.pk}:{_stamp(appointment.starts_at)}:{action}"


def template_value(text: str) -> str:
    """Meta rejects template values with newlines, tabs or 4+ spaces in a row."""
    return " ".join(str(text or "").split()) or "-"


def reminder_text(appointment: LeadAiAppointment, conversation, settings_row: LeadAiSettings, language: str = "en") -> str:
    lang = language if language in REMINDER_LINES else "en"
    head, tail = REMINDER_LINES[lang]
    name = _first(appointment, conversation)
    if not name:
        head = head.replace(" {name}", " there" if lang == "en" else "")
    lines = [head.format(name=name, time=hours.time_label(appointment.starts_at)), settings_row.office_address]
    if settings_row.office_maps_url:
        lines.append(settings_row.office_maps_url)
    lines.append(tail)
    return "\n".join(line for line in lines if line)


def _due(now):
    return LeadAiAppointment.objects.filter(
        status=LeadAiAppointment.Status.CONFIRMED,
        reminder_due_at__isnull=False,
        reminder_due_at__lte=now,
        reminder_sent_at__isnull=True,
        reminder_claimed_at__isnull=True,
        reminder_error="",
        starts_at__gt=now,
    )


def claim_one(now: dt.datetime | None = None):
    """(appointment, claim time, start at claim) for one due reminder, or None."""
    now = now or timezone.now()
    with transaction.atomic():
        row = _due(now).select_for_update(skip_locked=True).order_by("reminder_due_at").first()
        if row is None:
            return None
        LeadAiAppointment.objects.filter(pk=row.pk).update(reminder_claimed_at=now)
    return row.pk, now, row.starts_at


def _booked_at(appointment: LeadAiAppointment) -> dt.datetime:
    """When the meeting was last booked or moved (its history), else when the row was made."""
    for entry in reversed(appointment.history or []):
        if entry.get("event") in ("confirmed", "rescheduled"):
            try:
                return dt.datetime.fromisoformat(entry["at"])
            except (KeyError, TypeError, ValueError):
                break
    return appointment.created_at


def _opt_out_in(message) -> str | None:
    """The opt-out a message is, by the rules a turn applies with a meeting booked."""
    text = (message.body or "").strip()
    data = transcript.payload(message)
    if message.kind == "button":
        return rules.opt_out_from_button((data.get("button") or {}).get("text") or text)
    if message.kind == "interactive":
        interactive = data.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return rules.opt_out_from_button(reply.get("title") or text)
    if message.kind == "text" and not rules.is_meeting_cancel(text):
        # "الغاء" / "cancel" alone, with a meeting booked, cancels the meeting, not the chat.
        return rules.opt_out_from_text(text)
    return None


def unrecorded_opt_out(appointment: LeadAiAppointment) -> str | None:
    """A STOP, wrong number or "not interested" no assistant turn ever saw, or None.

    It must be the last thing the customer said since the meeting was booked
    (at most 48 hours back; a trailing "ok" or sticker does not count), as in
    a turn: "Stop" then "send me 2BR instead" is not a STOP. A message with a
    turn on it or after it was judged by the assistant already, and an agent
    may have pressed Resume since. One query.
    """
    since = max(_booked_at(appointment), timezone.now() - OPT_OUT_LOOKBACK)
    judged = LeadAiTurn.objects.filter(conversation_id=appointment.conversation_id, inbound_id__gte=OuterRef("pk"))
    rows = (
        Message.objects.filter(
            conversation_id=appointment.conversation_id,
            direction=Message.Direction.INBOUND,
            created_at__gte=since,
            mirrored_from__isnull=True,
        )
        .exclude(kind__in=("reaction", "system"))
        .exclude(transcript.REVOKED)
        .annotate(judged=Exists(judged))
        .only("pk", "kind", "body", "payload")
        .order_by("-pk")[:20]
    )
    for row in rows:
        if row.kind == "sticker" or (row.kind == "text" and rules.is_acknowledgement(row.body)):
            continue
        if row.judged:
            return None
        kind = _opt_out_in(row)
        return kind if kind in (rules.STOP_ALL, rules.WRONG_NUMBER, rules.NOT_INTERESTED) else None
    return None


def blocked(appointment: LeadAiAppointment) -> str:
    """Why this reminder must not go out, or ''. An opt-out found here is recorded (no line is sent)."""
    conversation = appointment.conversation
    if not LeadAiSettings.load().answers(conversation.contact.wa_id):
        return SWITCHED_OFF
    state = LeadAiChatState.objects.filter(conversation=conversation).first()
    if state is not None and state.stop_reason in (LeadAiChatState.StopReason.STOP_ALL, LeadAiChatState.StopReason.WRONG_NUMBER):
        return OPTED_OUT
    kind = unrecorded_opt_out(appointment)
    if kind:
        from . import engine

        engine.record_opt_out(conversation, kind, by="reminder_check")
        return DECLINED if kind == rules.NOT_INTERESTED else OPTED_OUT
    return ""


def approved_template(conversation):
    from apps.catalog.models import WaTemplate

    return (
        WaTemplate.objects.filter(
            name=TEMPLATE_NAME,
            waba_business_id=conversation.number.waba_business_id,
            status=WaTemplate.Status.APPROVED,
            category__iexact="UTILITY",
        )
        .order_by("-id")
        .first()
    )


def send(appointment_id: int, claimed_at: dt.datetime, starts_at: dt.datetime) -> str:
    """Send one claimed reminder: 'buttons', 'template', 'changed', 'suppressed' or 'failed'."""
    from apps.inbox import services as inbox_services

    appointment = (
        LeadAiAppointment.objects.select_related("conversation__contact", "conversation__number")
        .filter(pk=appointment_id)
        .first()
    )
    if (
        appointment is None
        or appointment.status != LeadAiAppointment.Status.CONFIRMED
        or appointment.starts_at != starts_at
        or appointment.reminder_claimed_at != claimed_at
    ):
        return "changed"
    now = timezone.now()
    reason = blocked(appointment)
    if not reason and appointment.starts_at - now < TOO_LATE:
        reason = "The reminder was due too late (less than 10 minutes before the meeting), so it was not sent."
    if reason:
        LeadAiAppointment.objects.filter(pk=appointment.pk, reminder_claimed_at=claimed_at).update(reminder_error=reason)
        live.appointment_changed(appointment.conversation_id)
        return "suppressed"

    conversation = appointment.conversation
    conversation.refresh_from_db(fields=["session_expires_at"])
    settings_row = LeadAiSettings.load()
    language = LeadAiChatState.objects.filter(conversation=conversation).values_list("language", flat=True).first() or "en"
    payload = {"source": SOURCE, "appointment": appointment.pk}
    window_open = bool(conversation.session_expires_at and conversation.session_expires_at > now)
    roomy = window_open and conversation.session_expires_at - now >= WINDOW_MARGIN
    message = None
    route = "failed"
    error = ""
    try:
        template = None if roomy else approved_template(conversation)
        if roomy or (window_open and template is None):
            # Under ten minutes of window left and no approved template: the
            # buttons still beat no reminder (a failure reaches the agents).
            message = inbox_services.send_buttons(
                conversation,
                None,
                reminder_text(appointment, conversation, settings_row, language),
                [{"id": button_id(appointment, action), "title": label} for action, label in BUTTONS],
                payload=payload,
            )
            route = "buttons"
        elif template is None:
            error = (
                "The customer's 24-hour window is closed and the reminder template is not approved "
                "on this number yet, so the reminder could not be sent."
            )
        else:
            variables = {
                "1": template_value(first_name(appointment, conversation)),
                "2": template_value(hours.time_label(appointment.starts_at)),
                "3": template_value(settings_row.office_address),
            }
            message = inbox_services.send_template(conversation, None, template, variables, payload=payload)
            route = "template"
    except SoftTimeLimitExceeded:
        raise  # the sweep is out of time: stale_claims settles this claim
    except Exception as exc:  # noqa: BLE001 - recorded and told to the agents
        logger.warning("Lead AI reminder for appointment %s failed: %s", appointment.pk, exc)
        error = f"The reminder could not be sent ({type(exc).__name__})."
        message = None

    if message is not None:
        updated = LeadAiAppointment.objects.filter(
            pk=appointment.pk, reminder_claimed_at=claimed_at, starts_at=starts_at
        ).update(reminder_sent_at=timezone.now(), reminder_message=message, reminder_error="")
        if updated:
            appointment.refresh_from_db()
            appointment.log("reminder_sent", route=route, message=message.pk)
            appointment.save(update_fields=["history", "updated_at"])
        live.appointment_changed(appointment.conversation_id)
        return route

    LeadAiAppointment.objects.filter(pk=appointment.pk, reminder_claimed_at=claimed_at).update(
        reminder_error=error or "The reminder could not be sent."
    )
    live.appointment_changed(appointment.conversation_id)
    return "failed"


def stale_claims(now: dt.datetime | None = None) -> list[tuple[int, str]]:
    """Claims older than STALE_CLAIM that never finished, resolved without sending twice.

    The send services store the message row as QUEUED before calling the
    gateway, and a message that reached WhatsApp gets its wamid within seconds
    (the send's answer, or its first status). So a tagged row with a wamid or
    a sent status is linked and marked sent. A FAILED row was not delivered:
    the agents are told. A row still queued without a wamid, or no row, means
    the gateway was never reached: the reminder is re-armed if there is still
    time, otherwise the agents are told. Returns [(appointment id,
    'resent'|'linked'|'late')].
    """
    now = now or timezone.now()
    out = []
    rows = LeadAiAppointment.objects.filter(
        status=LeadAiAppointment.Status.CONFIRMED,
        reminder_claimed_at__lte=now - STALE_CLAIM,
        reminder_sent_at__isnull=True,
        reminder_error="",
    )
    for row in rows:
        message = (
            Message.objects.filter(
                conversation_id=row.conversation_id,
                direction=Message.Direction.OUTBOUND,
                payload__source=SOURCE,
                payload__appointment=row.pk,
                created_at__gte=row.reminder_claimed_at,
            )
            .order_by("-pk")
            .first()
        )
        if message is not None and (message.wamid or message.status in SENT_STATUSES):
            LeadAiAppointment.objects.filter(pk=row.pk).update(reminder_sent_at=message.created_at, reminder_message=message)
            out.append((row.pk, "linked"))
        elif message is not None and message.status == Message.Status.FAILED:
            LeadAiAppointment.objects.filter(pk=row.pk).update(
                reminder_error=f"WhatsApp did not deliver the reminder ({message.error_code or 'failed'} {message.error_detail})"[:500]
            )
            out.append((row.pk, "late"))
        elif row.starts_at and row.starts_at - now >= TOO_LATE:
            LeadAiAppointment.objects.filter(pk=row.pk, reminder_claimed_at=row.reminder_claimed_at).update(reminder_claimed_at=None)
            out.append((row.pk, "resent"))
        else:
            LeadAiAppointment.objects.filter(pk=row.pk).update(
                reminder_error="Sending the reminder was interrupted. Please remind the customer by hand."
            )
            out.append((row.pk, "late"))
        live.appointment_changed(row.conversation_id)
    return out


def looks_like_tap(message) -> bool:
    """A cheap check (no database) for a tap on one of our reminder buttons."""
    data = transcript.payload(message)
    if message.kind == "interactive":
        reply = (data.get("interactive") or {}).get("button_reply") or {}
        return str(reply.get("id") or "").startswith("leadai:")
    if message.kind == "button":
        label = str(((data.get("button") or {}).get("text")) or message.body or "").strip().lower()
        return label in ACTION_BY_LABEL
    return False


def tap_on_reminder(message):
    """(appointment, action) when an inbound message is a tap on one of OUR reminders for a
    meeting that still stands and is around now (TAP_VALID_BEFORE/AFTER); else (None, "").

    A session button names its appointment and the start it was sent for; after
    a reschedule its start is not the meeting's any more, so it is not ours,
    unless it answers the appointment's current reminder (running late moves
    the start and keeps that reminder; a reschedule unlinks it). An old id with
    no start counts only on the current reminder. A template quick reply has
    only its label: it must answer the current reminder, or, with no context,
    one sent within the last three hours.
    """
    data = transcript.payload(message)
    now = timezone.now()
    confirmed = LeadAiAppointment.objects.filter(
        conversation_id=message.conversation_id, status=LeadAiAppointment.Status.CONFIRMED
    )
    if message.kind == "interactive":
        reply = (data.get("interactive") or {}).get("button_reply") or {}
        parts = str(reply.get("id") or "").split(":")
        if len(parts) not in (3, 4) or parts[0] != "leadai" or not parts[1].isdigit() or parts[-1] not in dict(BUTTONS):
            return None, ""
        appointment = confirmed.filter(pk=int(parts[1])).first()
        if appointment is None:
            return None, ""
        on_current = bool(message.reply_to_id) and message.reply_to_id == appointment.reminder_message_id
        if len(parts) == 4 and parts[2] != _stamp(appointment.starts_at) and not on_current:
            return None, ""  # a reminder for another time, before a reschedule
        if len(parts) == 3 and message.reply_to_id != appointment.reminder_message_id:
            return None, ""  # an older reminder
        action = parts[-1]
    elif message.kind == "button":
        label = str(((data.get("button") or {}).get("text")) or message.body or "").strip().lower()
        action = ACTION_BY_LABEL.get(label)
        if not action:
            return None, ""
        if message.reply_to_id:
            # Only the current reminder: one a reschedule unlinked, or any other message, is not ours.
            appointment = confirmed.filter(reminder_message_id=message.reply_to_id).first()
        else:
            appointment = (
                confirmed.filter(reminder_sent_at__gte=now - TAP_FALLBACK_WINDOW).order_by("-reminder_sent_at").first()
            )
        if appointment is None:
            return None, ""
    else:
        return None, ""
    start = appointment.starts_at
    if not start or not (start - TAP_VALID_BEFORE <= now <= start + TAP_VALID_AFTER):
        return None, ""  # not around now: the assistant answers it like any message
    return appointment, action
