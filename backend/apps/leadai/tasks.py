"""Celery tasks of the Lead AI app (autodiscovered by a7wa/celery.py).

All of them run on their own queue, "leadai" (CELERY_TASK_ROUTES), served by
the worker-leadai service, so a busy assistant never slows the main inbox's
webhook processing or campaign sends, and campaign days never delay a
meeting reminder.

- assistant_turn         answers one customer message in a Lead AI chat;
- handle_reminder_tap    a tap on the meeting reminder's buttons (no model);
- send_due_reminders     beat, every minute: reminders, stuck turns, missed
                         turns and taps, messages nobody answered, past
                         meetings, the agents' heads-up, Bitrix catch-up, and
                         the shops chats' automatic follow-ups (followups.py);
- send_follow_up         one shops chat's Template B, check-back or nudge;
- sync_appointment_crm   an appointment event's Bitrix work, step by step (a
                         booking through the Lead fields tool's "booking" action);
- crm_readback           six minutes after a stage move, checks it stuck;
- deliver_alert          one alert to the agent's panel and to Bitrix;
- record_crm_note        an opt-out or "not interested" as a timeline comment;
- record_voice_note      what a customer's voice note says, on the lead's timeline;
- resolve_responsible    the CRM record's responsible person, cached per chat;
- write_crm_fields       a shops chat's lead fields, through the Lead fields tool
                         (a shops "no" moves its lead only when nobody works it:
                         assistant/lost.py);
- write_licence_file     a shops customer's trade licence copy, to the lead;
- send_shop_media        a shop type's video, photos and detail card (shop_media.py);
- send_unit_media        a studio or one-bedroom set's photos and the question after them (unit_media.py).
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

RUNNING_TOO_LONG = dt.timedelta(minutes=5)
MISSED_FROM = dt.timedelta(minutes=2)
MISSED_UNTIL = dt.timedelta(minutes=15)
AUDIO_STILL_WAITING = dt.timedelta(minutes=5)
# A message no turn took this long after it arrived (engine.STALE_AFTER) is
# told to the agents; older than an hour, it is history.
UNANSWERED_FROM = dt.timedelta(minutes=15)
UNANSWERED_UNTIL = dt.timedelta(minutes=60)
# Reminder taps count up to this long after the start (reminders.TAP_VALID_AFTER).
PAST_AFTER = dt.timedelta(hours=3)
TENTATIVE_LAPSES = dt.timedelta(days=7)
# A shops chat's tentative visit with no time lapses this long after it was last said, one with a time
# this long after that time (launch review 2026-10-15, issue 11: an open tentative stops every nudge, and
# lapsed only after TENTATIVE_LAPSES, so chats 100, 96, 59 and 62 heard nothing more). Owner's defaults.
TIMELESS_TENTATIVE_LAPSES = dt.timedelta(hours=24)
PAST_TENTATIVE_LAPSES = dt.timedelta(hours=1)
# The sweep looks at this many of them a minute (the next minute takes the rest).
LAPSE_PAGE = 200
AGENT_HEADS_UP = dt.timedelta(minutes=60)
# The sweep stops claiming reminders after this many seconds, inside its own
# 240 s soft limit; the next sweep, a minute later, sends the rest.
REMINDER_CLAIMS_FOR = 180
CRM_RETRY = (60, 180, 600)
# A sync that gave up on a passing error (Bitrix down or throttled) leaves a
# "pending:<event>:<revision>:<hot>" step; the sweep queues it again every 15
# minutes for six hours, then tells the agents. Removed once it syncs.
CRM_PENDING = "pending:"
CRM_CATCH_UP_EVERY = dt.timedelta(minutes=15)
CRM_CATCH_UP_FOR = dt.timedelta(hours=6)
LEAD_UPDATE = "lead_update"


# The turn's own deadline (engine.py) ends its OpenAI calls well before the
# soft limit; worker-leadai's stop_grace_period (docker-compose.yml) is above
# the hard limit, so a deploy lets a turn in flight finish.
@shared_task(ignore_result=True, soft_time_limit=180, time_limit=210)
def assistant_turn(message_id: int, attempt: int = 0, first_queued_at: str = "", requeued: bool = False) -> None:
    """``requeued``: a message the reply cap held back, queued again once the cap freed (_answer_capped)."""
    from .assistant import engine

    first = first_queued_at or timezone.now().isoformat()
    try:
        engine.run_turn(message_id, attempt=attempt, first_queued_at=first, requeued=requeued)
    except engine.NotReady as wait:
        next_attempt = attempt + 1 if wait.reason == "voice note downloading" else attempt
        assistant_turn.apply_async(
            args=[message_id], kwargs={"attempt": next_attempt, "first_queued_at": first, "requeued": requeued}, countdown=wait.countdown
        )
    except SoftTimeLimitExceeded:
        logger.warning("Lead AI turn on message %s ran out of time", message_id)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def handle_reminder_tap(message_id: int) -> None:
    from .assistant import taps

    result = taps.handle(message_id)
    if result == "not a tap on our reminder":
        # It only looked like one (a template button with the same label):
        # a Lead AI chat still gets its normal answer.
        from apps.inbox.models import Message

        from .lane import is_lead_ai_conversation_id

        message = Message.objects.filter(pk=message_id).only("conversation_id").first()
        if message is not None and is_lead_ai_conversation_id(message.conversation_id):
            assistant_turn.apply_async(args=[message_id], countdown=10)


@shared_task(ignore_result=True, soft_time_limit=240, time_limit=280)
def send_due_reminders() -> None:
    from .models import LeadAiSettings

    LeadAiSettings.objects.filter(pk=1).update(last_sweep_at=timezone.now())
    for job in (
        _resolve_stuck_turns,
        _queue_missed_turns,
        _answer_capped,
        _flag_unanswered,
        _escalate_handovers,
        _close_past_appointments,
        _agent_heads_up,
        _retry_crm_syncs,
        _retry_crm_fields,
        _reminders,
        # Last: it only queues one task per due chat, and must never delay a reminder.
        _follow_ups,
    ):
        try:
            job()
        except SoftTimeLimitExceeded:
            raise
        except Exception:  # noqa: BLE001 - one job must not stop the others
            logger.exception("Lead AI sweep step %s failed", job.__name__)


def _follow_ups() -> None:
    """The shops chats due Template B (72 hours after a campaign nobody answered, or the day they
    asked us to check back) or a nudge: one send_follow_up task each (followups.py)."""
    from . import followups

    queued = followups.sweep()
    if queued:
        logger.info("Lead AI queued %s shops follow-up(s)", queued)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def send_follow_up(conversation_id: int, kind: str) -> None:
    """One shops chat's follow-up (followups.send decides again before anything goes)."""
    from . import followups

    result = followups.send(conversation_id, kind)
    if result != "sent":
        logger.info("Lead AI %s for conversation %s: %s", kind, conversation_id, result)


def _reminders() -> None:
    from .assistant import reminders

    started = time.monotonic()
    for pk, outcome in reminders.stale_claims():
        if outcome == "late":
            _reminder_problem_alert(pk)
    for _ in range(25):
        if time.monotonic() - started > REMINDER_CLAIMS_FOR:
            return
        claimed = reminders.claim_one()
        if claimed is None:
            return
        pk, claimed_at, starts_at = claimed
        route = reminders.send(pk, claimed_at, starts_at)
        if route in ("failed", "suppressed"):
            _reminder_problem_alert(pk)


def _reminder_problem_alert(appointment_id: int) -> None:
    from .assistant import alerts, hours, reminders
    from .models import LeadAiAppointment

    appointment = LeadAiAppointment.objects.select_related("conversation__contact", "conversation__assigned_agent").filter(pk=appointment_id).first()
    if appointment is None or not appointment.reminder_error:
        return
    if appointment.reminder_error in (reminders.OPTED_OUT, reminders.DECLINED):
        return  # the opt-out has its own alert, and nobody should remind them by hand
    conversation = appointment.conversation
    name = appointment.customer_name or conversation.contact.display_name or "a Lead AI customer"
    alerts.raise_alert(
        kind="reminder_failed",
        conversation=conversation,
        appointment=appointment,
        title=f"Reminder not sent to {name}",
        text=f"The 30-minute reminder for the {hours.describe(appointment.starts_at)} meeting was not sent to "
        f"{name} (WhatsApp +{conversation.contact.wa_id}). {appointment.reminder_error} Please remind them by hand.",
        dedupe_key=f"reminder_failed:{appointment.pk}:{appointment.starts_at:%Y%m%d%H%M}",
        crm_url=alerts.crm_path(appointment.crm_entity, appointment.crm_id),
    )


def _resolve_stuck_turns() -> None:
    """A turn still running after five minutes: its worker died (a deploy, out of memory).

    Its reply counts only if it reached WhatsApp (a wamid, or a sent status):
    a row still queued may never have left. A booking reply (payload
    "booking") with no confirmed meeting at that time means the customer was
    told something nothing recorded, so the agents are told at once.
    """
    from apps.inbox.models import Message

    from .assistant import alerts, reminders
    from .models import LeadAiChat, LeadAiTurn

    cutoff = timezone.now() - RUNNING_TOO_LONG
    for turn in LeadAiTurn.objects.filter(status=LeadAiTurn.Status.RUNNING, created_at__lte=cutoff).select_related(
        "conversation__contact"
    )[:50]:
        sent = Message.objects.filter(conversation_id=turn.conversation_id, payload__turn=turn.pk).order_by("pk").first()
        if sent is not None and (sent.wamid or sent.status in reminders.SENT_STATUSES):
            LeadAiTurn.objects.filter(pk=turn.pk).update(
                status=LeadAiTurn.Status.REPLIED, reply_message=sent, reason="finished by the sweep", finished_at=timezone.now()
            )
            booking = (sent.payload if isinstance(sent.payload, dict) else {}).get("booking")
            if booking:
                _unrecorded_booking_alert(turn, booking)
            continue
        LeadAiTurn.objects.filter(pk=turn.pk).update(
            status=LeadAiTurn.Status.FAILED, reason="interrupted", finished_at=timezone.now()
        )
        chat = LeadAiChat.objects.filter(conversation_id=turn.conversation_id).first()
        conversation = turn.conversation
        alerts.raise_alert(
            kind="ai_error",
            conversation=conversation,
            title="Lead AI could not reply",
            text=f"The assistant was interrupted while answering "
            f"{conversation.contact.display_name or '+' + conversation.contact.wa_id}. Please reply by hand.",
            dedupe_key=f"ai_error:{conversation.pk}:{timezone.now():%Y%m%d%H}",
            crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
        )


def _unrecorded_booking_alert(turn, booking: dict) -> None:
    """A stuck turn's booking reply went out, but no confirmed meeting at that time exists."""
    from .assistant import alerts, hours
    from .models import LeadAiAppointment, LeadAiChat

    try:
        start = dt.datetime.fromisoformat(str(booking.get("starts_at") or ""))
    except ValueError:
        start = None
    if start is not None and LeadAiAppointment.objects.filter(
        conversation_id=turn.conversation_id, status=LeadAiAppointment.Status.CONFIRMED, starts_at=start
    ).exists():
        return
    conversation = turn.conversation
    chat = LeadAiChat.objects.filter(conversation_id=turn.conversation_id).first()
    who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
    told = "moved to" if booking.get("event") == "rescheduled" else "confirmed for"
    alerts.raise_alert(
        kind="booking_unrecorded",
        conversation=conversation,
        priority="high",
        title=f"Booking not recorded: {who}",
        text=f"The assistant told {who} (WhatsApp +{conversation.contact.wa_id}) their meeting is {told} "
        f"{hours.describe(start) if start else 'a new time'}, but it was interrupted before recording it: no reminder "
        "is planned and the CRM was not updated. Please check the chat and book it by hand.",
        dedupe_key=f"booking_unrecorded:{turn.pk}",
        crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
    )


def _queue_missed_turns() -> None:
    """A Lead AI customer's message from 2-15 minutes ago with no turn and no answer.

    Covers a queueing failure in the signal (broker down for a moment). A tap
    on the reminder goes to its own handler, which applies it even with the
    assistant off, and hands it to the assistant itself if it is not ours.
    """
    from apps.inbox.models import Message

    from .assistant import reminders
    from .assistant.transcript import REVOKED
    from .models import LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn

    settings_row = LeadAiSettings.load()
    now = timezone.now()
    active = LeadAiChat.objects.filter(active=True).values_list("conversation_id", flat=True)
    candidates = (
        Message.objects.filter(
            conversation_id__in=active,
            direction=Message.Direction.INBOUND,
            created_at__gte=now - MISSED_UNTIL,
            created_at__lte=now - MISSED_FROM,
            mirrored_from__isnull=True,
        )
        .exclude(kind__in=("reaction", "system"))
        .exclude(REVOKED)
        .select_related("conversation__contact")
        .order_by("-pk")[:100]
    )
    seen = set()
    for message in candidates:
        if message.conversation_id in seen:
            continue
        seen.add(message.conversation_id)
        if reminders.looks_like_tap(message):
            if not LeadAiTurn.objects.filter(inbound=message).exists():
                handle_reminder_tap.apply_async(args=[message.pk])
            continue
        conversation = message.conversation
        if conversation.linked_conversation_id or not settings_row.answers(conversation.contact.wa_id):
            continue
        # A turn skipped by a gate leaves no row; these gates would only skip it again.
        if LeadAiChatState.objects.filter(conversation_id=conversation.pk).filter(
            Q(stopped_at__isnull=False) | Q(paused_at__isnull=False)
        ).exists():
            continue
        # A voice note's own turn may still be waiting for the download (15+30+60+90 s).
        if message.kind == "audio" and now - message.created_at < AUDIO_STILL_WAITING:
            continue
        if LeadAiTurn.objects.filter(inbound=message).exists():
            continue
        if Message.objects.filter(conversation_id=message.conversation_id, pk__gt=message.pk).exists():
            continue
        assistant_turn.apply_async(args=[message.pk])


def _answer_capped() -> None:
    """A shops chat's message the reply cap held back, answered once the cap frees (assistant/caps.py; launch
    review issue 2: chats 78 and 91 went silent mid-booking for good): the chat's newest capped message is
    queued again, and its turn takes the same row up (caps.reclaim)."""
    from .assistant import caps

    queued = caps.to_answer(timezone.now())
    for message_id in queued:
        assistant_turn.apply_async(args=[message_id], kwargs={"requeued": True})
    if queued:
        logger.info("Lead AI queued %s capped message(s) again", len(queued))


def _escalate_handovers() -> None:
    """A shops handover nobody from the team answered in 30 minutes of office time: one more alert for it
    (assistant/people.py, escalate_waiting; launch review issue 3)."""
    from .assistant import people

    people.escalate_waiting(timezone.now())


def _flag_unanswered() -> None:
    """A Lead AI customer's message 15-60 minutes old that no turn ever took and
    nobody answered (an OpenAI outage that outlasted the missed-turn retries, a
    lost task): its agents are told once, so no message ages out in silence.

    Only in chats the assistant answers: a chat the switched-off assistant
    ignores (dark launch), a stopped or paused one, or one transferred to
    another agent is the agents' own anyway.
    """
    from apps.inbox.models import Message

    from .assistant import alerts, openai_client
    from .assistant.transcript import REVOKED
    from .models import LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn

    if not openai_client.configured():
        return
    settings_row = LeadAiSettings.load()
    now = timezone.now()
    active = LeadAiChat.objects.filter(active=True).values_list("conversation_id", flat=True)
    candidates = (
        Message.objects.filter(
            conversation_id__in=active,
            direction=Message.Direction.INBOUND,
            created_at__gte=now - UNANSWERED_UNTIL,
            created_at__lte=now - UNANSWERED_FROM,
            mirrored_from__isnull=True,
        )
        .exclude(kind__in=("reaction", "system"))
        .exclude(REVOKED)
        .select_related("conversation__contact")
        .order_by("-pk")[:100]
    )
    seen = set()
    for message in candidates:
        if message.conversation_id in seen:
            continue
        seen.add(message.conversation_id)
        conversation = message.conversation
        if conversation.linked_conversation_id or not settings_row.answers(conversation.contact.wa_id):
            continue
        if LeadAiChatState.objects.filter(conversation_id=conversation.pk).filter(
            Q(stopped_at__isnull=False) | Q(paused_at__isnull=False)
        ).exists():
            continue
        if LeadAiTurn.objects.filter(inbound=message).exists():
            continue
        if (
            Message.objects.filter(conversation_id=conversation.pk, pk__gt=message.pk)
            .exclude(kind__in=("reaction", "system"))
            .exists()
        ):
            continue
        chat = LeadAiChat.objects.filter(conversation=conversation).first()
        # The same key as the turn's own stale alert: one alert per message.
        alerts.raise_alert(
            kind="stale",
            conversation=conversation,
            title="Lead AI did not answer an old message",
            text=f"A message from {conversation.contact.display_name or '+' + conversation.contact.wa_id} waited too "
            "long for the assistant (the system was busy). Please reply by hand.",
            dedupe_key=f"stale:{conversation.pk}:{message.pk}",
            crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
        )


def _close_past_appointments() -> None:
    from .assistant import live
    from .models import LeadAiAppointment

    now = timezone.now()
    for row in LeadAiAppointment.objects.filter(
        status=LeadAiAppointment.Status.CONFIRMED, starts_at__lt=now - PAST_AFTER
    )[:200]:
        row.status = LeadAiAppointment.Status.DONE
        row.reminder_due_at = None
        row.log("past")
        row.save(update_fields=["status", "reminder_due_at", "history", "updated_at"])
        live.appointment_changed(row.conversation_id)
    for row in LeadAiAppointment.objects.filter(status=LeadAiAppointment.Status.TENTATIVE, updated_at__lt=now - TENTATIVE_LAPSES)[:200]:
        row.status = LeadAiAppointment.Status.DONE
        row.log("lapsed")
        row.save(update_fields=["status", "history", "updated_at"])
        live.appointment_changed(row.conversation_id)
    _lapse_shops_tentatives(now)


# Why a shops chat's tentative visit lapsed (its history's "lapsed" entry).
LAPSED_NO_TIME = "no time agreed"
LAPSED_TIME_PASSED = "its time passed"


def _lapse_shops_tentatives(now) -> None:
    """A shops chat's tentative visit lapses a day after it was last said when it has no time
    (TIMELESS_TENTATIVE_LAPSES), and an hour after its time when it has one (PAST_TENTATIVE_LAPSES): it
    no longer holds the chat (followups.nudge_due sends nothing while a visit is open) nor tells the next
    turns they agreed to come. Its status is done, as any lapsed tentative's, its history says "lapsed"
    and why. Nothing goes to the customer; the team is alerted when the visit was theirs (_tentative_theirs:
    their words say they will come), never for a slot offer of the model's own that the 025bd91 fix no
    longer records (chats 59 and 62). A general chat's tentative keeps TENTATIVE_LAPSES, as before: no
    follow-up waits on it there."""
    from . import lane
    from .models import LeadAiAppointment

    tentative = LeadAiAppointment.objects.filter(status=LeadAiAppointment.Status.TENTATIVE)
    # The shops chats first, in the query: a general chat's tentative stays open for days and must never fill
    # the page a shops one is read from.
    chats = set(tentative.values_list("conversation_id", flat=True))
    shops_chats = sorted(pk for pk, playbook in lane.playbooks(chats).items() if playbook == lane.IC_SHOPS)
    if not shops_chats:
        return
    candidates = (
        tentative.filter(conversation_id__in=shops_chats)
        .filter(
            Q(starts_at__isnull=True, created_at__lt=now - TIMELESS_TENTATIVE_LAPSES)
            | Q(starts_at__isnull=False, starts_at__lt=now - PAST_TENTATIVE_LAPSES)
        )
        .order_by("pk")
        .values_list("pk", flat=True)[:LAPSE_PAGE]
    )
    for pk in list(candidates):
        _lapse_tentative(pk, now)


def _last_said(row) -> dt.datetime:
    """When the tentative visit was last recorded in their words (its newest "tentative" history entry),
    else when it was made: a CRM retry or a fact noted on it is no new word about the visit."""
    for entry in reversed(row.history or []):
        if isinstance(entry, dict) and entry.get("event") == "tentative":
            try:
                said = dt.datetime.fromisoformat(str(entry.get("at") or ""))
            except ValueError:
                break
            return said if said.tzinfo is not None else said.replace(tzinfo=dt.timezone.utc)
    return row.created_at


def _lapse_why(row, now) -> str:
    """Why this tentative lapses now, else '' (it stays). One with a time also waits an hour after they last
    spoke of it: "I'm on my way" said after its time is no visit to drop."""
    if row.starts_at is not None:
        passed = row.starts_at < now - PAST_TENTATIVE_LAPSES and _last_said(row) < now - PAST_TENTATIVE_LAPSES
        return LAPSED_TIME_PASSED if passed else ""
    return LAPSED_NO_TIME if _last_said(row) < now - TIMELESS_TENTATIVE_LAPSES else ""


def _tentative_theirs(row, now) -> bool:
    """Their words for the visit say they will come: a yes, a day or an hour of theirs, words of coming,
    a deferral of theirs ("I will message you"). The model's own slot offer kept their unrelated words
    ("One", "Your rent is higher than others", "If possible to send me photo first")."""
    from .assistant import engine, rules

    words = (row.customer_words or row.note or "").strip()
    if not words:
        return False
    return bool(
        engine.comes(words, now) or engine.opens_with_yes([words]) or rules.is_deferral(words) or rules.is_dated_deferral(words)
        or rules.mentions_deferral(words)
    )


def _lapse_tentative(pk: int, now) -> None:
    from .assistant import live
    from .models import LeadAiAppointment

    with transaction.atomic():
        row = (
            LeadAiAppointment.objects.select_for_update()
            .filter(pk=pk, status=LeadAiAppointment.Status.TENTATIVE)
            .first()
        )
        if row is None:
            return  # confirmed, cancelled or lapsed meanwhile
        why = _lapse_why(row, now)
        if not why:
            return  # said again lately: a day from then
        row.status = LeadAiAppointment.Status.DONE
        row.log("lapsed", why=why, start=row.starts_at.isoformat() if row.starts_at else None)
        row.save(update_fields=["status", "history", "updated_at"])
        if _tentative_theirs(row, now) and not _gone_quiet(row.conversation_id):
            _lapsed_alert(row, why)
        transaction.on_commit(lambda conversation_id=row.conversation_id: live.appointment_changed(conversation_id))


def _gone_quiet(conversation_id: int) -> bool:
    """The customer asked us to stop, declined, or is on the opt-out registry: nobody follows them up."""
    from . import optout
    from .models import LeadAiChatState

    state = LeadAiChatState.objects.filter(conversation_id=conversation_id).select_related("conversation__contact").first()
    if state is None:
        return False
    return state.stopped_at is not None or state.not_interested_at is not None or optout.is_blocked(state.conversation.contact.wa_id)


def _lapsed_alert(row, why: str) -> None:
    """The chat's people and the Lead AI alert list hear that a tentative visit of the customer's lapsed."""
    from .assistant import alerts, crm, engine, hours

    conversation = row.conversation
    who = row.customer_name or conversation.contact.display_name or "A Lead AI customer"
    what = {"call": "call", "customer_property": "viewing"}.get(row.place, "visit")
    words = (row.customer_words or row.note or "").strip()
    if why == LAPSED_TIME_PASSED:
        reason = f"Its time, {hours.describe(row.starts_at)}, has passed with nothing confirmed."
    else:
        reason = f"No day and time were agreed in the {int(TIMELESS_TENTATIVE_LAPSES.total_seconds() // 3600)} hours since they said it."
    lines = [
        f"{who} (WhatsApp +{conversation.contact.wa_id})",
        *engine._detail_lines(row.details or {}),
        f"Their words: {crm.safe(words)}" if words else "",
        reason,
        "The assistant no longer holds it open and sends them nothing about it: please follow up with them.",
    ]
    alerts.raise_alert(
        kind="tentative_lapsed",
        conversation=conversation,
        appointment=row,
        title=f"{who}: tentative {what} lapsed"[:200],
        text="\n".join(line for line in lines if line),
        dedupe_key=f"tentative_lapsed:{row.pk}",
        crm_url=alerts.crm_path(row.crm_entity, row.crm_id),
    )


def _agent_heads_up() -> None:
    """When Bitrix's own to-do could not be moved to the meeting time, the agents
    get one heads-up an hour before the visit from us instead."""
    from .assistant import alerts, hours
    from .models import LeadAiAppointment

    now = timezone.now()
    rows = LeadAiAppointment.objects.filter(
        status=LeadAiAppointment.Status.CONFIRMED,
        agent_reminded_at__isnull=True,
        crm_todo_id__isnull=True,
        starts_at__gt=now,
        starts_at__lte=now + AGENT_HEADS_UP,
    ).select_related("conversation__contact")[:50]
    for row in rows:
        conversation = row.conversation
        name = row.customer_name or conversation.contact.display_name or "A Lead AI customer"
        alerts.raise_alert(
            kind="upcoming",
            conversation=conversation,
            appointment=row,
            title=f"Meeting soon: {name} at {hours.time_label(row.starts_at)}",
            text=f"{name} (WhatsApp +{conversation.contact.wa_id}) is booked for {hours.describe(row.starts_at)} at the office.",
            dedupe_key=f"upcoming:{row.pk}:{row.starts_at:%Y%m%d%H%M}",
            crm_url=alerts.crm_path(row.crm_entity, row.crm_id),
        )
        LeadAiAppointment.objects.filter(pk=row.pk).update(agent_reminded_at=now)


def _retry_crm_syncs() -> None:
    """Bitrix work a sync gave up on for a passing reason (Bitrix down or throttled):
    queued again every 15 minutes while the meeting is open, for six hours; then
    the agents are told once. The steps already done are never repeated."""
    from .assistant import alerts, hours
    from .models import LeadAiAppointment, LeadAiCrmStep

    now = timezone.now()
    pending = (
        LeadAiCrmStep.objects.filter(step__startswith=CRM_PENDING, created_at__lte=now - CRM_CATCH_UP_EVERY)
        .select_related("appointment__conversation__contact")
        .order_by("pk")[:50]
    )
    for step in pending:
        appointment = step.appointment
        if appointment.status not in LeadAiAppointment.OPEN:
            step.delete()  # cancelled or past since: that change had its own sync
            continue
        event, revision, hot = _parse_pending(step.step)
        if now - step.created_at > CRM_CATCH_UP_FOR:
            step.delete()
            conversation = appointment.conversation
            who = appointment.customer_name or conversation.contact.display_name or f"+{conversation.contact.wa_id}"
            when = hours.describe(appointment.starts_at) if appointment.starts_at else "no time yet"
            alerts.raise_alert(
                kind="crm_failed",
                conversation=conversation,
                appointment=appointment,
                title=f"Bitrix was not updated for {who}",
                text=f"The CRM record of {who}'s meeting ({when}) could not be updated for six hours "
                f"({(appointment.crm_error or 'Bitrix did not answer')[:200]}). Please update it by hand.",
                dedupe_key=f"crm_failed:{appointment.pk}:{event}:{'' if revision is None else revision}",
                crm_url=alerts.crm_path(appointment.crm_entity, appointment.crm_id),
            )
            continue
        if appointment.updated_at > now - CRM_CATCH_UP_EVERY:
            continue  # tried again (or changed) within the last 15 minutes
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(updated_at=now)
        sync_appointment_crm.delay(appointment.pk, event, hot, revision)


# Bitrix -------------------------------------------------------------------------------------


def _step(appointment, name: str) -> bool:
    """True the first time a step is recorded; False if it was already done."""
    from .models import LeadAiCrmStep

    try:
        with transaction.atomic():
            LeadAiCrmStep.objects.create(appointment=appointment, step=name[:120])
        return True
    except IntegrityError:
        return False


def _undo_step(appointment, name: str) -> None:
    from .models import LeadAiCrmStep

    LeadAiCrmStep.objects.filter(appointment=appointment, step=name[:120]).delete()


def _agents(alerts, conversation) -> str:
    """The agents this chat's alerts reach, for the CRM comment."""
    return ", ".join(sorted({(a.display_name or a.get_username()) for a, _ in alerts.recipients(conversation) if a is not None}))


def _agent_for_bitrix(bitrix_user_id: str):
    from django.contrib.auth import get_user_model

    if not str(bitrix_user_id or "").isdigit():
        return None
    return get_user_model().objects.filter(bitrix_user_id=str(bitrix_user_id), is_active=True).first()


def _remember_responsible(conversation, bitrix_user_id: str) -> None:
    from .models import LeadAiChatState

    agent = _agent_for_bitrix(bitrix_user_id)
    state = LeadAiChatState.for_conversation(conversation)
    state.responsible_bitrix_user_id = bitrix_user_id if bitrix_user_id.isdigit() else ""
    state.responsible_agent = agent
    state.responsible_checked_at = timezone.now()
    state.save(update_fields=["responsible_bitrix_user_id", "responsible_agent", "responsible_checked_at", "updated_at"])


def _retry_or_give_up(task, exc):
    if task.request.retries < len(CRM_RETRY):
        raise task.retry(exc=exc, countdown=CRM_RETRY[task.request.retries])
    return str(exc)[:500]


def _transient(exc) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("not json", "timeout", "timed out", "unreachable", "connect", "502", "503", "504", "429"))


def _pending_step(event: str, hot: bool, revision: int | None) -> str:
    return f"{CRM_PENDING}{event}:{'' if revision is None else revision}:{int(bool(hot))}"


def _parse_pending(step: str) -> tuple[str, int | None, bool]:
    _, event, revision, hot = step.split(":")
    return event, (int(revision) if revision.isdigit() else None), hot == "1"


BOOKING_STEP = "booking:"
# A booking sent to the Lead fields tool, answered or not: the tool may have saved it before its
# answer was lost (a read timeout, its own 502 after the save), so the lead may hold our booking.
BOOKING_TRY = "booking-try:"
# The new meeting time alone, through the tool's plain fields (_book_around).
BOOKING_TIME = "booking-time:"
# The assistant's own to-do moved or closed with crm.activity (_book_around).
TODO_STEP = "todo:"
NOT_OUR_TODO = (
    "The lead has an open Viewing/Meeting to-do that Lead AI did not plan, so Lead AI left the lead's stage and "
    "to-dos as they are: please move it to Meeting/Viewing Scheduled and set the meeting time."
)


def _booked_by_us(appointment) -> bool:
    """The assistant booked this appointment's lead itself: through the Lead fields tool
    (a "booking:confirmed..." or "booking:rescheduled..." step, or such a booking sent and
    never answered: BOOKING_TRY), or before it, with the REST update it used until board T55
    (LEAD_UPDATE). A lead in stage 10 the assistant did not book holds a person's own booking
    and to-do, which nothing here touches."""
    from .models import LeadAiCrmStep

    steps = LeadAiCrmStep.objects.filter(appointment=appointment)
    return steps.filter(step=LEAD_UPDATE).exists() or steps.filter(
        Q(step__startswith=f"{BOOKING_STEP}confirmed")
        | Q(step__startswith=f"{BOOKING_STEP}rescheduled")
        | Q(step__startswith=f"{BOOKING_TRY}confirmed")
        | Q(step__startswith=f"{BOOKING_TRY}rescheduled")
    ).exists()


def _book(appointment, crm_id: int, event: str, decision: str, stamp: str, extra: list, comment_for) -> tuple[bool, str]:
    """One booking event of a lead the assistant books (sync_appointment_crm): (its comment went in
    the Lead fields tool's own call, why the tool refused it).

    The tool's booking action moves, or for a cancel closes, the lead's NEWEST open
    "Viewing/Meeting" to-do, whoever planned it (board C9). So it is used only while that
    newest one is the assistant's own (``crm_todo_id``), or there is none, or this very event
    was sent before and no answer came back (the to-do it planned then is the newest: sent
    again, the tool moves that same one and answers its id). Otherwise a person's to-do, or
    the "due now" one BP 235 plans when a person edits a lead in stage 10, would take the
    meeting time in place of ours, or be closed: ``_book_around``. ``comment_for(lines)``
    writes the event's comment with these extra lines."""
    from .assistant import crm, crm_fields
    from .models import LeadAiAppointment, LeadAiCrmStep

    step = f"{BOOKING_STEP}{stamp}"
    if not _step(appointment, step):
        return True, ""  # done before (a task delivered twice): its comment went with it
    try:
        todos = crm.open_meeting_todos(crm_id)
    except Exception:
        _undo_step(appointment, step)
        raise
    own = appointment.crm_todo_id if appointment.crm_todo_id in todos else None
    tried = f"{BOOKING_TRY}{stamp}"
    sent_before = LeadAiCrmStep.objects.filter(appointment=appointment, step=tried).exists()
    if todos and todos[0] != own and not sent_before:
        _undo_step(appointment, step)
        return _book_around(appointment, crm_id, event, decision, stamp, own, extra, comment_for), ""
    lines = list(extra)
    if decision == "move" and event != "cancelled":
        lines.append("WhatsApp Lead AI moved this lead to Meeting/Viewing Scheduled.")
    if event != "cancelled":
        _step(appointment, tried)
    try:
        answer = crm_fields.post(crm.booking_body(crm_id, appointment, event, comment_for(lines)))
    except crm_fields.FieldsError:
        _undo_step(appointment, step)  # sent again on the retry; the attempt stays ours (BOOKING_TRY)
        raise
    if not answer.get("ok"):
        # Refused (a field or enum the tool does not allow): nothing was booked there, so this
        # does not count as ours; the comment still goes, the REST way.
        _undo_step(appointment, step)
        _undo_step(appointment, tried)
        error = f"The Lead fields tool refused the booking: {answer.get('error') or 'refused'}"[:500]
        logger.warning("Lead AI booking write refused for appointment %s: %s", appointment.pk, error)
        return False, error
    done = {}
    todo = crm.todo_of(answer)
    if event != "cancelled":
        done["crm_todo_id"] = todo
        if decision == "move":
            done["crm_stage_moved_at"] = timezone.now()
            crm_readback.apply_async(args=[appointment.pk], countdown=360)
    else:
        done["crm_todo_id"] = None
    LeadAiAppointment.objects.filter(pk=appointment.pk).update(**done)
    if event != "cancelled" and not LeadAiAppointment.objects.filter(pk=appointment.pk, status=LeadAiAppointment.Status.CONFIRMED).exists():
        # Cancelled while this ran: that sync could not know the to-do was planned yet (it is the newest).
        try:
            crm_fields.post(crm.booking_body(crm_id, appointment, "cancelled"))
        except crm_fields.FieldsError as exc:
            logger.warning("Lead AI could not close the viewing to-do of appointment %s: %s", appointment.pk, exc)
    return True, ""


def _book_around(appointment, crm_id: int, event: str, decision: str, stamp: str, own, extra: list, comment_for) -> bool:
    """The lead's newest open "Viewing/Meeting" to-do is not the assistant's (_book): the booking
    action is not used, so that to-do keeps its time and stays open. The assistant's own to-do
    (``own``, still open) is moved or closed with crm.activity, which runs no lead business
    process. The meeting time goes on the lead through the tool's plain fields (BP 235 empties
    it when a person edits a lead in stage 10), with the comment in the same call; a lead the
    booking would have had to move to stage 10 stays in its stage, and the comment tells the
    agents so (NOT_OUR_TODO). With no to-do of ours, our 60-minute heads-up covers the meeting
    (crm_todo_id empty). True when the comment went with the meeting time."""
    from apps.crmlink import client

    from .assistant import crm, crm_fields
    from .models import LeadAiAppointment

    todo_step = f"{TODO_STEP}{stamp}"
    if event == "cancelled":
        if own is not None:
            if _step(appointment, todo_step):
                try:
                    crm.complete_todo(own)
                except client.BitrixError:
                    _undo_step(appointment, todo_step)
                    raise
            LeadAiAppointment.objects.filter(pk=appointment.pk).update(crm_todo_id=None)
        return False
    if decision != "already":
        extra.append(NOT_OUR_TODO)
    commented = True
    time_step = f"{BOOKING_TIME}{stamp}"
    if _step(appointment, time_step):
        try:
            answer = crm_fields.post(crm.meeting_fields_body(crm_id, appointment, comment_for(list(extra))))
        except crm_fields.FieldsError:
            _undo_step(appointment, time_step)
            raise
        commented = bool(answer.get("ok"))
        if not commented:
            _undo_step(appointment, time_step)
            logger.warning("The Lead fields tool refused the meeting time of appointment %s: %s", appointment.pk, answer.get("error"))
    if own is not None:
        if _step(appointment, todo_step):
            try:
                crm.move_todo(own, crm_id, appointment.starts_at)
            except client.BitrixError:
                _undo_step(appointment, todo_step)
                raise
    else:
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(crm_todo_id=None)
    return commented


@shared_task(bind=True, ignore_result=True, max_retries=len(CRM_RETRY), soft_time_limit=120, time_limit=150)
def sync_appointment_crm(self, appointment_id: int, event: str, hot: bool = False, revision: int | None = None) -> None:
    """One appointment event in Bitrix. Each write is recorded (LeadAiCrmStep) before
    the next, so a retry never repeats one.

    A booking (confirmed, rescheduled) on the campaign's own lead, and its cancel,
    go through the Lead fields tool's "booking" action (crm.booking_body; board
    C9, T55) with the event's comment in the same call: the tool moves the lead
    to stage 10 with the Meeting Date & Time and owns the one "Viewing/Meeting"
    to-do, all with BP 235 off. The tool moves or closes the lead's NEWEST open
    "Viewing/Meeting" to-do, so the action is used only while that one is the
    assistant's own, or there is none (_book); otherwise our own to-do is moved
    or closed by itself and nobody else's is touched (_book_around). A booking
    sent and never answered still counts as ours (BOOKING_TRY), so its retry
    finds the lead in stage 10 and sends it again. A lead already in stage 10
    that we did not book, and every lead the stage rules keep where it is
    (crm.stage_decision), get the comment alone, as every other event does (a
    REST timeline comment, which runs no business process).

    ``revision`` is the length of the appointment's history right after the
    event (engine), so each change has its own steps and comment, even back to
    an earlier time; without it the event and the start name them. A booking or
    reschedule writes nothing once the meeting is no longer confirmed (its
    cancel has its own sync); the call carries the meeting's time as it is now.
    """
    from apps.crmlink import client

    from .assistant import alerts, crm, crm_fields, live
    from .models import LeadAiAppointment, LeadAiChat, LeadAiCrmStep, LeadAiSettings

    appointment = (
        LeadAiAppointment.objects.select_related("conversation__contact", "conversation__assigned_agent")
        .filter(pk=appointment_id)
        .first()
    )
    if appointment is None or not client.configured():
        return
    pending = _pending_step(event, hot, revision)
    if event in ("confirmed", "rescheduled") and appointment.status != LeadAiAppointment.Status.CONFIRMED:
        _undo_step(appointment, pending)
        return
    conversation = appointment.conversation
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    settings_row = LeadAiSettings.load()
    if revision is not None:
        stamp = f"{event}:r{revision}"
    else:
        stamp = f"{event}:{appointment.starts_at:%Y%m%d%H%M}" if appointment.starts_at else event
    error = ""
    passing = False
    extra = []
    try:
        entity, crm_id, chosen = crm.record_for(chat, conversation)
        if not (entity and crm_id):
            error = "No CRM record was found for this customer."
        else:
            record = crm.read_record(entity, crm_id)
            if record["assigned"]:
                _remember_responsible(conversation, record["assigned"])
                if revision is not None and event in ("confirmed", "rescheduled"):
                    # A responsible known only now (a failed first lookup, a lead
                    # reassigned since) still hears of the booking; whoever has the
                    # alert already is not alerted twice.
                    from .assistant import engine

                    engine.appointment_alert(
                        conversation, chat, appointment, event, hot, appointment.customer_name, revision=revision
                    )
            LeadAiAppointment.objects.filter(pk=appointment.pk).update(crm_entity=entity, crm_id=crm_id)
            decision = crm.stage_decision(entity, chosen, record)
            ours = entity == "lead" and _booked_by_us(appointment)
            booking = ""  # the tool's booking event this sync sends, if any
            if event in ("confirmed", "rescheduled") and entity == "lead":
                if decision == "move" or (decision == "already" and ours):
                    booking = event
                elif decision in ("new lead", "held by admin"):
                    extra.append("The lead is NEW or unassigned, so its stage was left as it is. Please give it an owner.")
                elif decision in ("closed", "unknown stage"):
                    extra.append(f"The lead's stage ({record['stage'] or 'unknown'}) was left as it is; please move it if needed.")
            if event == "cancelled" and entity == "lead":
                if ours:
                    booking = "cancelled"  # the tool closes the one "Viewing/Meeting" to-do it planned
                extra.append("The lead stays in its stage; please move it if the customer will not come.")
            if booking:

                def comment_for(lines, event=event):
                    return crm.comment_text(
                        appointment, event, office_address=settings_row.office_address, agents=_agents(alerts, conversation),
                        extra=" ".join(lines), hot=hot,
                    )

                # "booking:confirmed:r1": once per event and revision.
                commented, refused = _book(appointment, crm_id, booking, decision, stamp, extra, comment_for)
                if refused:
                    error = refused
                if not commented:
                    booking = ""
            if not booking and _step(appointment, f"comment:{stamp}"):
                try:
                    crm.add_comment(
                        entity,
                        crm_id,
                        crm.comment_text(
                            appointment,
                            event,
                            office_address=settings_row.office_address,
                            agents=_agents(alerts, conversation),
                            extra=" ".join(extra),
                            hot=hot,
                        ),
                    )
                except client.BitrixError:
                    _undo_step(appointment, f"comment:{stamp}")
                    raise
    except crm_fields.FieldsError as exc:
        error = _retry_or_give_up(self, exc)
        passing = True
    except client.BitrixError as exc:
        if _transient(exc):
            error = _retry_or_give_up(self, exc)
            passing = True
        else:
            error = str(exc)[:500]
    if error:
        if passing:
            _step(appointment, pending)  # the sweep tries again (_retry_crm_syncs)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(crm_error=error)
    else:
        _undo_step(appointment, pending)
        fields = {"crm_synced_at": timezone.now()}
        # Another event's work still waiting for its retry keeps its error showing.
        if not LeadAiCrmStep.objects.filter(appointment=appointment, step__startswith=CRM_PENDING).exists():
            fields["crm_error"] = ""
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(**fields)
    live.appointment_changed(conversation.pk)


@shared_task(bind=True, ignore_result=True, max_retries=2, soft_time_limit=60, time_limit=90)
def crm_readback(self, appointment_id: int) -> None:
    """Six minutes after a stage move: the lead-shift timer can write an old stage back."""
    from apps.crmlink import client

    from .assistant import alerts, crm
    from .models import LeadAiAppointment

    appointment = LeadAiAppointment.objects.select_related("conversation__contact").filter(pk=appointment_id).first()
    if appointment is None or appointment.status != LeadAiAppointment.Status.CONFIRMED or appointment.crm_entity != "lead":
        return
    try:
        record = crm.read_record("lead", appointment.crm_id)
    except client.BitrixError as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=120)
        return
    if record["stage"] != crm.STAGE_MEETING:
        conversation = appointment.conversation
        alerts.raise_alert(
            kind="crm_stage_lost",
            conversation=conversation,
            appointment=appointment,
            title="Lead stage did not stay on Meeting/Viewing Scheduled",
            text=f"The lead of {appointment.customer_name or '+' + conversation.contact.wa_id} was moved to "
            f"Meeting/Viewing Scheduled for its meeting, but is now in {record['stage'] or 'another stage'}. "
            "Please check it.",
            dedupe_key=f"crm_stage_lost:{appointment.pk}",
            crm_url=alerts.crm_path("lead", appointment.crm_id),
        )


# Alerts a chat raised this long before its CRM responsible was known reach that person once it is.
RESPONSIBLE_CATCH_UP = dt.timedelta(hours=2)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def resolve_responsible(conversation_id: int) -> None:
    """The chat's CRM record's responsible person, cached on its state; then the alerts the chat raised before
    it was known reach them too (alerts.reach_responsible: launch chat 112's STOP, its first answer, never
    reached the lead's owner)."""
    from apps.crmlink import client
    from apps.inbox.models import Conversation

    from .assistant import alerts, crm
    from .models import LeadAiChat, LeadAiChatState

    conversation = Conversation.objects.select_related("contact", "assigned_agent").filter(pk=conversation_id).first()
    if conversation is None or not client.configured():
        return
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    try:
        entity, crm_id = _record_of(chat, conversation)
        if entity and crm_id:
            record = crm.read_record(entity, crm_id)
            _remember_responsible(conversation, record["assigned"])
            if record["assigned"]:
                alerts.reach_responsible(conversation, timezone.now() - RESPONSIBLE_CATCH_UP)
    except client.BitrixError as exc:
        logger.info("Lead AI could not resolve the responsible of conversation %s: %s", conversation_id, exc)
        # Not looked up after all: the chat's next turn asks again.
        LeadAiChatState.objects.filter(conversation_id=conversation_id).update(responsible_checked_at=None)


def _replaced(row) -> bool:
    """A newer row of the same chat replaced this one before it was sent: a newer value of
    its field, or, for a lost move, a newer Bot Status other than Lost (they booked or
    asked for a person after declining: the lead is not lost)."""
    from .assistant import crm_fields
    from .models import LeadAiCrmField

    newer = LeadAiCrmField.objects.filter(conversation_id=row.conversation_id, pk__gt=row.pk)
    if newer.filter(field=row.field).exists():
        return True
    if row.field == crm_fields.LOST:
        return newer.filter(field=crm_fields.FIELD_BOT_STATUS).exclude(value=str(crm_fields.STATUS_LOST)).exists()
    return False


@shared_task(bind=True, ignore_result=True, max_retries=len(CRM_RETRY), soft_time_limit=150, time_limit=180)
def write_crm_fields(self, row_ids) -> None:
    """One turn's shops lead fields (assistant/crm_fields.py), in one call to the tool.

    A row that a newer row of the same chat replaced is not sent (_replaced): a
    retry must never write an older Bot Status over a newer one, nor move a lead
    that has booked since to Not Interested (nor one a person set another Bot
    Status on in Bitrix since: bitrix_status.py records it). The lead is read
    first (crm.lead.get, through the REST client): a value it holds already is
    not written again, so it gets no edit and no line in its change log (launch
    review issue 26; a failed read writes everything, as before). A shops "no"
    moves the lead to its lost stage only when nobody is working it and it has
    no open to-do (assistant/lost.py: launch review issue 1); otherwise Bot
    Status Lost goes alone, with the customer's words and why on the timeline,
    and no to-do is closed or changed. A passing failure (Bitrix down, 5xx,
    429) is retried at 1, 3 and 10 minutes; after that the sweep sends the
    rows again every 15 minutes for six hours (_retry_crm_fields). A refusal (a
    field or enum the tool does not allow, no such lead) stays on the rows and
    is not retried. Nothing reaches the customer.
    """
    from django.db.models import F

    from apps.inbox.models import Conversation

    from .assistant import crm_fields, lost
    from .models import LeadAiCrmField

    rows = list(
        LeadAiCrmField.objects.filter(pk__in=list(row_ids or []), sent_at__isnull=True)
        .exclude(field=crm_fields.LICENCE_FILE)  # a licence copy has its own task (write_licence_file)
        .order_by("pk")
    )
    live = []
    for row in rows:
        if _replaced(row):
            LeadAiCrmField.objects.filter(pk=row.pk).update(error="Replaced by a newer value before it was sent.", retry_at=None)
        else:
            live.append(row)
    if not live:
        return
    lead_id = live[0].lead_id
    now = timezone.now()
    # Up to four REST reads come before the post (each may wait for its slot): should this run be cut off, the sweep
    # sends the rows again (_retry_crm_fields), as after a failed post. Every ending below sets or clears it.
    LeadAiCrmField.objects.filter(pk__in=[row.pk for row in live]).update(retry_at=now + CRM_CATCH_UP_EVERY)
    # What the lead holds now: a value it has already is not written again (no edit, no change-log line).
    current = lost.read_lead(lead_id)
    touch = lost.touch_of(current, now, lost.system_users()) if current else None
    if touch:
        # A person's touch this read shows: our write is about to hide it (it writes as user 1), so a later "no" must
        # still see it (lost.remembered_touch; review 2d).
        for row in live:
            row.payload = {**(row.payload or {}), lost.PERSON_TOUCH: touch}
            LeadAiCrmField.objects.filter(pk=row.pk).update(payload=row.payload)
    held = [row for row in live if crm_fields.holds(current, row)]
    if held:
        # A row an earlier try of ours posted already (its answer lost on the way back: a timeout, a 502) is sent, not
        # "held" (review 2d); one we never posted is the lead's own value.
        ours = [row.pk for row in held if row.attempts > 0]
        LeadAiCrmField.objects.filter(pk__in=ours).update(sent_at=now, error="", retry_at=None)
        LeadAiCrmField.objects.filter(pk__in=[row.pk for row in held if row.pk not in ours]).update(
            sent_at=now, error=crm_fields.HELD_ALREADY, retry_at=None
        )
        live = [row for row in live if row not in held]
    # A shops "no": its lost stage only for a lead nobody is working, with no open to-do (assistant/lost.py).
    moves = [row for row in live if row.field == crm_fields.LOST]
    kept: dict[int, str] = {}
    comment = ""
    if moves and lost.moved_already(current, moves[-1].value):
        # The lead sits in that lost stage, with Bot Status Lost, already: an earlier try of ours moved it (its answer
        # lost), or a person did. Nothing to move, and no "it was not moved" on its timeline (review 2d).
        mine = [row.pk for row in moves if row.attempts > 0]
        LeadAiCrmField.objects.filter(pk__in=mine).update(sent_at=now, error="", retry_at=None)
        LeadAiCrmField.objects.filter(pk__in=[row.pk for row in moves if row.pk not in mine]).update(
            sent_at=now, error=lost.ALREADY_THERE, retry_at=None
        )
        live = [row for row in live if row not in moves]
        moves = []
    if moves:
        conversation = Conversation.objects.select_related("contact").filter(pk=moves[-1].conversation_id).first()
        decision = lost.may_move(lead_id, conversation.contact.wa_id if conversation else "", now=now, lead=current)
        if not decision.move:
            kept = {row.pk: decision.why for row in moves}
            if any((row.payload or {}).get(lost.KEPT_COMMENT) for row in moves):
                logger.info("Lead AI kept lead %s in its stage again; its comment went with an earlier try", lead_id)
            else:
                comment = lost.kept_comment(moves[-1].value, (moves[-1].payload or {}).get("reason") or "", decision.why)
                # Marked before it is posted: a try whose answer is lost never posts it a second time (review 2d).
                for row in moves:
                    row.payload = {**(row.payload or {}), lost.KEPT_COMMENT: now.isoformat()}
                    LeadAiCrmField.objects.filter(pk=row.pk).update(payload=row.payload)
            logger.info("Lead AI kept lead %s in its stage on a no: %s", lead_id, decision.why)
    posting = [row for row in live if row.pk not in kept]
    if not posting and not comment:
        for pk, why in kept.items():
            LeadAiCrmField.objects.filter(pk=pk).update(sent_at=timezone.now(), error=f"{lost.NOT_MOVED}{why}"[:500], retry_at=None)
        return
    ids = [row.pk for row in live]
    LeadAiCrmField.objects.filter(pk__in=ids).update(attempts=F("attempts") + 1)
    body = crm_fields.body_for(posting, lead_id=lead_id)
    if comment:
        body["comment"] = comment
    try:
        answer = crm_fields.post(body)
    except crm_fields.FieldsError as exc:
        LeadAiCrmField.objects.filter(pk__in=ids).update(error=str(exc)[:500])
        if self.request.retries < len(CRM_RETRY):
            raise self.retry(exc=exc, countdown=CRM_RETRY[self.request.retries])
        LeadAiCrmField.objects.filter(pk__in=ids).update(retry_at=timezone.now() + CRM_CATCH_UP_EVERY)
        logger.warning("Lead AI could not write the shops fields of lead %s yet (the sweep tries again): %s", lead_id, exc)
        return
    if answer.get("ok"):
        LeadAiCrmField.objects.filter(pk__in=[row.pk for row in posting]).update(sent_at=timezone.now(), error="", retry_at=None)
        for pk, why in kept.items():
            # Bot Status Lost and the comment went; the stage stays (assistant/lost.py).
            LeadAiCrmField.objects.filter(pk=pk).update(sent_at=timezone.now(), error=f"{lost.NOT_MOVED}{why}"[:500], retry_at=None)
        return
    error = str(answer.get("error") or answer.get("detail") or "Refused")[:500]
    LeadAiCrmField.objects.filter(pk__in=ids).update(error=error, retry_at=None)
    logger.warning("The Lead fields tool refused the shops fields of lead %s: %s", lead_id, error)


# A licence copy waits this many times, LICENCE_WAIT seconds apart, for the gateway's download.
LICENCE_WAITS = 12
LICENCE_WAIT = 30


def _licence_alert(row, text: str) -> None:
    """The agents (and the listed users, 2311) hear that a licence copy did not reach the lead."""
    from apps.inbox.models import Conversation

    from .assistant import alerts

    conversation = Conversation.objects.select_related("contact", "assigned_agent").filter(pk=row.conversation_id).first()
    if conversation is None:
        return
    who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
    alerts.raise_alert(
        kind="licence",
        conversation=conversation,
        title=f"Trade licence not on the lead: {who}",
        text=f"{who} (WhatsApp +{conversation.contact.wa_id}) shared a trade licence copy: {text}",
        dedupe_key=f"licence:{conversation.pk}:{row.pk}",
        crm_url=alerts.crm_path("lead", row.lead_id),
    )


@shared_task(bind=True, ignore_result=True, max_retries=LICENCE_WAITS, soft_time_limit=90, time_limit=120)
def write_licence_file(self, row_id: int) -> None:
    """The customer's trade licence copy (a photo or PDF they sent while the shops assistant
    asked for it; board T34) to their Bitrix lead, as the Lead fields tool's license_file.

    The file comes from the stored attachment, once the gateway has downloaded it (this
    task waits for it). Only a PDF, JPEG or PNG of at most 5 MB, by its bytes, goes; any
    other file stays in the chat, and the agents (the listed users too) are told. A passing
    failure is retried like the other fields, then by the sweep (_retry_crm_fields).
    """
    from django.db.models import F

    from apps.inbox.models import Message

    from .assistant import crm_fields
    from .models import LeadAiCrmField

    row = LeadAiCrmField.objects.filter(pk=row_id, field=crm_fields.LICENCE_FILE, sent_at__isnull=True).first()
    if row is None:
        return
    if _replaced(row):
        LeadAiCrmField.objects.filter(pk=row.pk).update(error="Replaced by a newer licence copy before it was sent.", retry_at=None)
        return
    message = Message.objects.select_related("media").filter(pk=int(row.value) if row.value.isdigit() else 0).first()
    asset = message.media if message is not None else None
    if asset is None:
        LeadAiCrmField.objects.filter(pk=row.pk).update(error="The message has no file.", retry_at=None)
        return
    if not asset.downloaded or not asset.file:
        if self.request.retries < LICENCE_WAITS and not (asset.download_error and self.request.retries >= 4):
            raise self.retry(countdown=LICENCE_WAIT)
        LeadAiCrmField.objects.filter(pk=row.pk).update(error="The file never downloaded.", retry_at=None)
        _licence_alert(row, "the file could not be downloaded, so it is only in the chat. Please save it on the lead by hand.")
        return
    try:
        with asset.file.open("rb") as handle:
            data = handle.read(crm_fields.LICENCE_MAX + 1)
    except OSError as exc:
        LeadAiCrmField.objects.filter(pk=row.pk).update(error=f"The file could not be read ({type(exc).__name__}).", retry_at=None)
        _licence_alert(row, "the file could not be read here, so it is only in the chat. Please save it on the lead by hand.")
        return
    try:
        body = crm_fields.licence_body(row.lead_id, data)
    except ValueError as exc:
        LeadAiCrmField.objects.filter(pk=row.pk).update(error=f"Licence file {exc}.", retry_at=None)
        if len(data) > crm_fields.LICENCE_MAX:
            _licence_alert(row, "licence file too large, saved in the chat (the lead takes at most 5 MB). Please save it on the lead by hand.")
        else:
            _licence_alert(row, "it is not a PDF, JPEG or PNG, so it is saved in the chat only. Please save it on the lead by hand.")
        return
    LeadAiCrmField.objects.filter(pk=row.pk).update(attempts=F("attempts") + 1)
    try:
        answer = crm_fields.post(body)
    except crm_fields.FieldsError as exc:
        LeadAiCrmField.objects.filter(pk=row.pk).update(error=str(exc)[:500])
        retries = self.request.retries
        if retries < len(CRM_RETRY):
            raise self.retry(exc=exc, countdown=CRM_RETRY[retries])
        LeadAiCrmField.objects.filter(pk=row.pk).update(retry_at=timezone.now() + CRM_CATCH_UP_EVERY)
        logger.warning("Lead AI could not put the licence copy on lead %s yet (the sweep tries again): %s", row.lead_id, exc)
        return
    if answer.get("ok"):
        LeadAiCrmField.objects.filter(pk=row.pk).update(sent_at=timezone.now(), error="", retry_at=None)
        return
    error = str(answer.get("error") or "Refused")[:500]
    LeadAiCrmField.objects.filter(pk=row.pk).update(error=error, retry_at=None)
    logger.warning("The Lead fields tool refused the licence copy of lead %s: %s", row.lead_id, error)
    _licence_alert(row, f"Bitrix refused the file ({error[:120]}), so it is only in the chat. Please save it on the lead by hand.")


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def send_shop_media(conversation_id: int, shop_type: str, turn_id: int | None = None, language: str = "en", files: bool = True) -> None:
    """A shop type's video, its photos one by one, then its detail card (shop_media.send_type),
    on the leadai queue and outside the turn that asked for it; ``files`` False sends the
    card alone (the files went out today already). Nothing here can fail that turn: a file
    the gateway refuses is skipped, and when the card itself cannot go the agents are told."""
    from apps.inbox.models import Conversation

    from . import shop_media
    from .assistant import alerts
    from .models import LeadAiChat

    try:
        result = shop_media.send_type(conversation_id, shop_type, turn_id, language, files=files)
    except SoftTimeLimitExceeded:
        logger.warning("Lead AI ran out of time sending the %s media to conversation %s", shop_type, conversation_id)
        return
    except Exception as exc:  # noqa: BLE001 - told to the agents below
        logger.warning("Lead AI could not send the %s details to conversation %s: %s", shop_type, conversation_id, exc)
        conversation = Conversation.objects.select_related("contact", "assigned_agent").filter(pk=conversation_id).first()
        if conversation is None:
            return
        chat = LeadAiChat.objects.filter(conversation=conversation).first()
        who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
        alerts.raise_alert(
            kind="send_failed",
            conversation=conversation,
            title="Lead AI could not send the shop details",
            text=f"The assistant could not send {who} the details of the shop type they picked ({type(exc).__name__}). "
            "Please send them by hand.",
            dedupe_key=f"shop_media:{conversation_id}:{turn_id or shop_type}",
            crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
        )
        return
    if result.get("stopped"):
        logger.info("Lead AI stopped sending the %s media to conversation %s: %s", shop_type, conversation_id, result["stopped"])


@shared_task(ignore_result=True, soft_time_limit=300, time_limit=330)
def send_unit_media(conversation_id: int, set_id: int, turn_id: int | None = None, language: str = "en", questions: str = "", invite: bool = False) -> None:
    """A studio or one-bedroom set's photos, then the question after them (unit_media.send_set; batch 2e slice E), on
    the leadai queue and outside the turn that asked for them. A photo the gateway refuses is skipped; when nothing
    can go, the agents are told."""
    from apps.inbox.models import Conversation

    from . import unit_media
    from .assistant import alerts
    from .models import LeadAiChat

    try:
        result = unit_media.send_set(conversation_id, set_id, turn_id, language, questions, invite)
    except SoftTimeLimitExceeded:
        logger.warning("Lead AI ran out of time sending set %s to conversation %s", set_id, conversation_id)
        return
    except Exception as exc:  # noqa: BLE001 - told to the agents below
        logger.warning("Lead AI could not send set %s to conversation %s: %s", set_id, conversation_id, exc)
        conversation = Conversation.objects.select_related("contact", "assigned_agent").filter(pk=conversation_id).first()
        if conversation is None:
            return
        chat = LeadAiChat.objects.filter(conversation=conversation).first()
        who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
        alerts.raise_alert(
            kind="send_failed",
            conversation=conversation,
            title="Lead AI could not send the apartment photos",
            text=f"The assistant could not send {who} the photos of the same type of apartment they asked about "
            f"({type(exc).__name__}). Please send them by hand.",
            dedupe_key=f"unit_media:{conversation_id}:{turn_id or set_id}",
            crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
        )
        return
    if result.get("stopped"):
        logger.info("Lead AI stopped sending set %s to conversation %s: %s", set_id, conversation_id, result["stopped"])


FIELD_NAMES = {
    "UF_CRM_A7_BOT_STATUS": "Bot Status",
    "UF_CRM_A7_SHOP_TYPE": "Shop Type Wanted",
    "UF_CRM_A7_WA_OPT_OUT": "WhatsApp Opt-out",
    "UF_CRM_LEAD_1737031634747": "Purpose",
    "UF_CRM_A7_AI_BUSINESS_ACTIVITY": "Business activity",
    "UF_CRM_A7_AI_TRADE_LICENSE_STATUS": "Trade license status",
    "lost": "the move to a lost stage",
    "license_file": "the trade licence copy (it is in the chat)",
}


def _retry_crm_fields() -> None:
    """Shops lead fields the task could not write while Bitrix was down: sent again every
    15 minutes for six hours (each value its own newest row; a replaced one never),
    then the agents are told once which to set by hand. Opt-outs most of all: those
    fields keep every later campaign away from the customer (board C10, C11). A lost
    stage is never one to set by hand (assistant/lost.py): it just stays unmoved."""
    from apps.inbox.models import Conversation

    from .assistant import alerts, crm_fields, lost
    from .models import LeadAiChat, LeadAiCrmField

    now = timezone.now()
    due = list(LeadAiCrmField.objects.filter(sent_at__isnull=True, retry_at__lte=now).order_by("pk")[:200])
    retry: dict = {}
    expired: dict = {}
    for row in due:
        (expired if now - row.created_at > CRM_CATCH_UP_FOR else retry).setdefault(row.conversation_id, []).append(row)
    for conversation_id, rows in expired.items():
        LeadAiCrmField.objects.filter(pk__in=[row.pk for row in rows]).update(retry_at=None)
        # A lost stage nobody could check for six hours is not moved, and nobody is told to move it by hand: the move
        # goes only to a lead nobody is working (assistant/lost.py). Bot Status Lost, a field of its own, is still told.
        moves = [row.pk for row in rows if row.field == crm_fields.LOST]
        if moves:
            LeadAiCrmField.objects.filter(pk__in=moves).update(error=f"{lost.NOT_MOVED}Bitrix could not be reached for six hours.")
        rows = [row for row in rows if row.field != crm_fields.LOST and not _replaced(row)]
        conversation = Conversation.objects.select_related("contact").filter(pk=conversation_id).first()
        if not rows or conversation is None:
            continue
        chat = LeadAiChat.objects.filter(conversation=conversation).first()
        who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
        names = ", ".join(dict.fromkeys(FIELD_NAMES.get(row.field, row.field) for row in rows))
        logger.warning("Lead AI gave up writing %s of lead %s after six hours", names, rows[0].lead_id)
        alerts.raise_alert(
            kind="crm_failed",
            conversation=conversation,
            title=f"Bitrix was not updated for {who}",
            text=f"For six hours Bitrix did not take the shops fields of {who}'s lead {rows[0].lead_id} ({names}: "
            f"{(rows[-1].error or 'Bitrix did not answer')[:150]}). Please set them on the lead by hand.",
            dedupe_key=f"crm_fields_failed:{conversation_id}:{rows[-1].pk}",
            crm_url=alerts.crm_path("lead", rows[0].lead_id),
        )
    for conversation_id, rows in retry.items():
        ids = [row.pk for row in rows]
        # Not due again before the task has had its own tries.
        LeadAiCrmField.objects.filter(pk__in=ids).update(retry_at=now + CRM_CATCH_UP_EVERY)
        fields = [row.pk for row in rows if row.field != crm_fields.LICENCE_FILE]
        if fields:
            write_crm_fields.delay(fields)
        for row in rows:
            if row.field == crm_fields.LICENCE_FILE:
                write_licence_file.delay(row.pk)


@shared_task(bind=True, ignore_result=True, max_retries=3, soft_time_limit=60, time_limit=90)
def record_crm_note(self, conversation_id: int, kind: str, lines=None) -> None:
    """A timeline note on the chat's CRM record (a REST comment: no business process runs): an
    opt-out, or ("wanted", with its ``lines``) what a shops customer wants instead of a shop."""
    from apps.crmlink import client
    from apps.inbox.models import Conversation

    from .assistant import crm
    from .models import LeadAiChat

    conversation = Conversation.objects.select_related("contact").filter(pk=conversation_id).first()
    if conversation is None or not client.configured():
        return
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    try:
        entity, crm_id = _record_of(chat, conversation)
        if entity and crm_id:
            # The chat's name for them (their own, the campaign's, the contact's), never "Customer: -" (issue 26).
            text = crm.note_text(kind, _chat_name(conversation), conversation.contact.wa_id, lines)
            crm.add_comment(entity, crm_id, text)
    except client.BitrixError as exc:
        if _transient(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=CRM_RETRY[min(self.request.retries, len(CRM_RETRY) - 1)])


def _record_of(chat, conversation) -> tuple[str, int | None]:
    """The CRM record a chat's notes and its responsible belong to: the lead its newest Lead AI campaign was sent from
    (crm_fields.lead_of, where Bot Status and the lost move go), else the record the chat came onto the screen with
    (crm.record_for). Review 2d: a shops campaign reaching a chat an older campaign brought from a deal put the
    "wanted" and "call" notes on the deal, and alerted the deal's owner as the lead's."""
    from .assistant import crm, crm_fields

    lead = crm_fields.lead_of(chat, conversation)
    if lead:
        return "lead", int(lead)
    entity, crm_id, _ = crm.record_for(chat, conversation)
    return entity, crm_id


def _chat_name(conversation) -> str:
    """The customer's name as the assistant knows it (engine._customer_name), '' with none."""
    from .assistant import engine
    from .models import LeadAiChatState

    facts = LeadAiChatState.objects.filter(conversation=conversation).values_list("facts", flat=True).first()
    return engine._customer_name(conversation, facts if isinstance(facts, dict) else {})


@shared_task(bind=True, ignore_result=True, max_retries=3, soft_time_limit=60, time_limit=90)
def record_voice_note(self, message_id: int) -> None:
    """What a customer's voice note in a Lead AI chat says, on the chat's lead's timeline, once it is heard
    (transcribe.py queues it once per note): the timeline mirror (apps.crmlink) writes "[audio]" for one, and chat
    96's eight voice notes told the agents nothing (launch review issue 26). A REST comment: no business process runs."""
    from apps.crmlink import client
    from apps.inbox.models import Message

    from .assistant import crm, crm_fields
    from .models import LeadAiChat, LeadAiTranscript

    message = Message.objects.select_related("conversation__contact").filter(pk=message_id, direction=Message.Direction.INBOUND).first()
    heard = LeadAiTranscript.objects.filter(message_id=message_id).first()
    if message is None or heard is None or not heard.heard or not client.configured():
        return
    conversation = message.conversation
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    if chat is None:
        return
    try:
        # The lead its newest Lead AI campaign was sent from (the mirror's own record), else the chat's record.
        lead = crm_fields.lead_of(chat, conversation)
        entity, crm_id = ("lead", lead) if lead else crm.record_for(chat, conversation)[:2]
        if entity and crm_id:
            crm.add_comment(entity, crm_id, crm.voice_note_text(message.created_at, heard.text))
    except client.BitrixError as exc:
        if _transient(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=CRM_RETRY[min(self.request.retries, len(CRM_RETRY) - 1)])
        logger.info("Lead AI could not put voice note %s on the timeline: %s", message_id, exc)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def outbound_failed(message_id: int) -> None:
    """A Lead AI message (reply, reminder, pin, tap answer) WhatsApp later reported as failed.

    A reminder sent as buttons that failed because the 24-hour window had
    just closed (131047) is tried once more as the approved template; any
    other failure is told to the agents, so nobody believes the customer was
    reminded or confirmed when they were not. Only the appointment's current
    reminder counts: a late failure of an older one (before a reschedule, or
    one already retried) changes nothing, and a second copy of the same
    status never retries twice. A shops chat's Template B (followups.py) is
    only logged: it never goes twice, and the chat shows it failed.
    """
    from apps.inbox import services as inbox_services
    from apps.inbox.models import Message

    from .assistant import alerts, live, reminders, transcript
    from .models import LeadAiAppointment, LeadAiChat

    message = (
        Message.objects.select_related("conversation__contact", "conversation__number", "conversation__assigned_agent")
        .filter(pk=message_id)
        .first()
    )
    if message is None or message.status != Message.Status.FAILED:
        return
    data = message.payload if isinstance(message.payload, dict) else {}
    conversation = message.conversation
    code = message.error_code or "failed"
    now = timezone.now()
    if data.get("source") == reminders.SOURCE and data.get("appointment"):
        appointment = (
            LeadAiAppointment.objects.select_related("conversation__contact", "conversation__number")
            .filter(pk=data["appointment"], conversation=conversation)
            .first()
        )
        if (
            appointment is None
            or appointment.status != LeadAiAppointment.Status.CONFIRMED
            or appointment.reminder_message_id != message.pk
        ):
            return
        if message.kind == Message.Kind.INTERACTIVE and code == "131047" and appointment.starts_at - now >= reminders.TOO_LATE:
            reason = reminders.blocked(appointment)
            if reason:
                LeadAiAppointment.objects.filter(pk=appointment.pk, reminder_message=message).update(reminder_error=reason)
                _reminder_problem_alert(appointment.pk)
                live.appointment_changed(conversation.pk)
                return
            template = reminders.approved_template(conversation, location_button=reminders.to_the_office(appointment))
            if template is not None:
                # Take the failed row off first: a second copy of this status then finds nothing to retry.
                if not LeadAiAppointment.objects.filter(pk=appointment.pk, reminder_message=message).update(reminder_message=None):
                    return
                try:
                    retry = inbox_services.send_template(
                        conversation,
                        None,
                        template,
                        {
                            "1": reminders.template_value(reminders.first_name(appointment, conversation)),
                            "2": reminders.template_value(reminders.hours.time_label(appointment.starts_at)),
                            "3": reminders.template_value(reminders.LeadAiSettings.load().office_address),
                        },
                        payload={"source": reminders.SOURCE, "appointment": appointment.pk, "retry_of": message.pk},
                    )
                    LeadAiAppointment.objects.filter(pk=appointment.pk, reminder_message__isnull=True).update(
                        reminder_message=retry, reminder_sent_at=now
                    )
                    live.appointment_changed(conversation.pk)
                    return
                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:  # noqa: BLE001 - told to the agents below
                    logger.warning("Lead AI reminder retry failed for appointment %s: %s", appointment.pk, exc)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(
            reminder_error=f"WhatsApp did not deliver the reminder ({code} {message.error_detail})"[:500]
        )
        _reminder_problem_alert(appointment.pk)
        live.appointment_changed(conversation.pk)
        return

    if data.get("shop_media_id"):
        # A shop photo or video that did not arrive: its media id may be no good any more, so the
        # next send uploads the file again. The detail card that follows says the rest.
        from . import shop_media

        shop_media.forget_upload(data["shop_media_id"], conversation.number_id)
        logger.info("Lead AI shop media message %s failed (%s); its upload is forgotten", message.pk, code)
        return
    if data.get("source") == transcript.FOLLOW_UP:
        # A Template B WhatsApp did not deliver (a MARKETING template often meets Meta's daily
        # cap per customer): it is not sent again, and nobody is alerted; the chat shows it failed.
        logger.info("Lead AI Template B message %s (%s) was not delivered: %s", message.pk, data.get("followup"), code)
        return
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    # The engine tags its booking confirmation when it sends it, before the turn row is saved.
    booking = bool(data.get("booking"))
    who = conversation.contact.display_name or f"+{conversation.contact.wa_id}"
    alerts.raise_alert(
        kind="ai_send_failed",
        conversation=conversation,
        priority="high" if booking else "normal",
        title="A Lead AI message was not delivered",
        text=(
            f"WhatsApp did not deliver the booking confirmation to {who} ({code}). The meeting is booked, "
            "but the customer may not know: please confirm it by hand."
            if booking
            else f"WhatsApp did not deliver the assistant's message to {who} ({code}). Please check the chat and reply by hand."
        ),
        dedupe_key=f"ai_send_failed:{message.pk}",
        crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
    )


@shared_task(bind=True, ignore_result=True, max_retries=3, soft_time_limit=60, time_limit=90)
def deliver_alert(self, alert_id: int) -> None:
    from .assistant import alerts
    from .models import LeadAiAlert

    alert = LeadAiAlert.objects.select_related("conversation__assigned_agent", "agent").filter(pk=alert_id).first()
    if alert is None:
        return
    try:
        alerts.deliver(alert)
    except alerts.AlertDeliveryError as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        logger.warning("Lead AI alert %s never reached Bitrix: %s", alert_id, exc)
