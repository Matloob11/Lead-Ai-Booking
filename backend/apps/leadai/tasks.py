"""Celery tasks of the Lead AI app (autodiscovered by a7wa/celery.py).

All of them run on their own queue, "leadai" (CELERY_TASK_ROUTES), served by
the worker-leadai service, so a busy assistant never slows the main inbox's
webhook processing or campaign sends, and campaign days never delay a
meeting reminder.

- assistant_turn         answers one customer message in a Lead AI chat;
- handle_reminder_tap    a tap on the meeting reminder's buttons (no model);
- send_due_reminders     beat, every minute: reminders, stuck turns, missed
                         turns and taps, messages nobody answered, past
                         meetings, the agents' heads-up, Bitrix catch-up;
- sync_appointment_crm   an appointment event's Bitrix work, step by step;
- crm_readback           six minutes after a stage move, checks it stuck;
- deliver_alert          one alert to the agent's panel and to Bitrix;
- record_crm_note        an opt-out or "not interested" as a timeline comment;
- resolve_responsible    the CRM record's responsible person, cached per chat;
- write_crm_fields       a shops chat's lead fields, through the Lead fields tool.
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
def assistant_turn(message_id: int, attempt: int = 0, first_queued_at: str = "") -> None:
    from .assistant import engine

    first = first_queued_at or timezone.now().isoformat()
    try:
        engine.run_turn(message_id, attempt=attempt, first_queued_at=first)
    except engine.NotReady as wait:
        next_attempt = attempt + 1 if wait.reason == "voice note downloading" else attempt
        assistant_turn.apply_async(
            args=[message_id], kwargs={"attempt": next_attempt, "first_queued_at": first}, countdown=wait.countdown
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
        _flag_unanswered,
        _close_past_appointments,
        _agent_heads_up,
        _retry_crm_syncs,
        _retry_crm_fields,
        _reminders,
    ):
        try:
            job()
        except SoftTimeLimitExceeded:
            raise
        except Exception:  # noqa: BLE001 - one job must not stop the others
            logger.exception("Lead AI sweep step %s failed", job.__name__)


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


def _lead_updated_at(appointment):
    """When the assistant itself moved this appointment's lead (its own update), or None."""
    from .models import LeadAiCrmStep

    return (
        LeadAiCrmStep.objects.filter(appointment=appointment, step=LEAD_UPDATE).values_list("created_at", flat=True).first()
    )


def _move_own_todo(appointment, crm_id: int) -> None:
    """Move the assistant's own "Viewing/Meeting" to-do to the meeting time.

    That is the one it stored, while it is still open, or else the one BP 235
    planned in answer to the assistant's own lead update (created at or after
    it). A to-do that was there before (an agent's own booking, an older BP 235
    one) is never touched; without one, our 60-minute heads-up covers the
    meeting. Raises BitrixError.
    """
    from .assistant import crm
    from .models import LeadAiAppointment

    if appointment.crm_todo_id:
        todo = crm.find_meeting_todo(crm_id, todo_id=appointment.crm_todo_id)
        if todo is None:
            # Done or deleted in Bitrix since: the heads-up takes its place.
            LeadAiAppointment.objects.filter(pk=appointment.pk, crm_todo_id=appointment.crm_todo_id).update(crm_todo_id=None)
            return
    else:
        since = _lead_updated_at(appointment)
        todo = crm.find_meeting_todo(crm_id, created_since=since) if since is not None else None
        if todo is None:
            return
    todo_id = int(todo["ID"])
    crm.move_todo(todo_id, crm_id, appointment.starts_at)
    LeadAiAppointment.objects.filter(pk=appointment.pk).update(crm_todo_id=todo_id)
    if not LeadAiAppointment.objects.filter(pk=appointment.pk, status=LeadAiAppointment.Status.CONFIRMED).exists():
        crm.complete_todo(todo_id)  # cancelled while this ran: that sync could not see the to-do yet


def _own_todo_to_complete(appointment, entity: str, crm_id: int) -> int | None:
    """The to-do a cancel closes: the stored one, or, while that is not stored yet
    (the booking's sync still running or failed), the one BP 235 planned after
    the assistant's own lead update. Raises BitrixError."""
    from .assistant import crm

    if appointment.crm_todo_id:
        return appointment.crm_todo_id
    since = _lead_updated_at(appointment) if entity == "lead" else None
    if since is None:
        return None
    todo = crm.find_meeting_todo(crm_id, created_since=since)
    return int(todo["ID"]) if todo is not None else None


@shared_task(bind=True, ignore_result=True, max_retries=len(CRM_RETRY), soft_time_limit=120, time_limit=150)
def sync_appointment_crm(self, appointment_id: int, event: str, hot: bool = False, revision: int | None = None) -> None:
    """One appointment event in Bitrix. Each write is recorded (LeadAiCrmStep) before
    the next, so a retry never repeats a lead update (each plans another to-do).

    ``revision`` is the length of the appointment's history right after the
    event (engine), so each change has its own steps and comment, even back to
    an earlier time; without it the event and the start name them. The lead is
    moved to stage 10 at most once per appointment. A booking or reschedule
    writes nothing once the meeting is no longer confirmed (its cancel has its
    own sync); the to-do and the comment use the meeting's time as it is now.
    """
    from apps.crmlink import client

    from .assistant import alerts, crm, live
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
            if event in ("confirmed", "rescheduled") and entity == "lead":
                if decision == "move" and _step(appointment, LEAD_UPDATE):
                    try:
                        crm.update_lead(crm_id, crm.booking_fields(record["fields"], appointment, settings_row.office_maps_url))
                    except client.BitrixError:
                        _undo_step(appointment, LEAD_UPDATE)
                        raise
                    LeadAiAppointment.objects.filter(pk=appointment.pk).update(crm_stage_moved_at=timezone.now())
                    extra.append("WhatsApp Lead AI moved this lead to Meeting/Viewing Scheduled.")
                    crm_readback.apply_async(args=[appointment.pk], countdown=360)
                elif decision in ("new lead", "held by admin"):
                    extra.append("The lead is NEW or unassigned, so its stage was left as it is. Please give it an owner.")
                elif decision in ("closed", "unknown stage"):
                    extra.append(f"The lead's stage ({record['stage'] or 'unknown'}) was left as it is; please move it if needed.")
                if decision in ("move", "already") and _step(appointment, f"todo:{stamp}"):
                    try:
                        _move_own_todo(appointment, crm_id)
                    except client.BitrixError as exc:
                        logger.warning("Lead AI could not move the meeting to-do on lead %s: %s", crm_id, exc)
            if event == "cancelled" and _step(appointment, f"todo_done:{stamp}"):
                try:
                    todo_id = _own_todo_to_complete(appointment, entity, crm_id)
                    if todo_id:
                        crm.complete_todo(todo_id)
                except client.BitrixError as exc:
                    logger.warning("Lead AI could not complete the meeting to-do of appointment %s: %s", appointment.pk, exc)
            if event == "cancelled" and entity == "lead":
                extra.append("The lead stays in its stage; please move it if the customer will not come.")
            if _step(appointment, f"comment:{stamp}"):
                agents = ", ".join(
                    sorted(
                        {
                            (a.display_name or a.get_username())
                            for a, _ in alerts.recipients(conversation)
                            if a is not None
                        }
                    )
                )
                try:
                    crm.add_comment(
                        entity,
                        crm_id,
                        crm.comment_text(
                            appointment,
                            event,
                            office_address=settings_row.office_address,
                            agents=agents,
                            extra=" ".join(extra),
                            hot=hot,
                        ),
                    )
                except client.BitrixError:
                    _undo_step(appointment, f"comment:{stamp}")
                    raise
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


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def resolve_responsible(conversation_id: int) -> None:
    from apps.crmlink import client
    from apps.inbox.models import Conversation

    from .assistant import crm
    from .models import LeadAiChat, LeadAiChatState

    conversation = Conversation.objects.select_related("contact").filter(pk=conversation_id).first()
    if conversation is None or not client.configured():
        return
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    try:
        entity, crm_id, _ = crm.record_for(chat, conversation)
        if entity and crm_id:
            record = crm.read_record(entity, crm_id)
            _remember_responsible(conversation, record["assigned"])
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


@shared_task(bind=True, ignore_result=True, max_retries=len(CRM_RETRY), soft_time_limit=60, time_limit=90)
def write_crm_fields(self, row_ids) -> None:
    """One turn's shops lead fields (assistant/crm_fields.py), in one call to the tool.

    A row that a newer row of the same chat replaced is not sent (_replaced): a
    retry must never write an older Bot Status over a newer one, nor move a lead
    that has booked since to Not Interested. A passing failure (Bitrix down,
    5xx, 429) is retried at 1, 3 and 10 minutes; after that the sweep sends the
    rows again every 15 minutes for six hours (_retry_crm_fields). A refusal (a
    field or enum the tool does not allow, no such lead) stays on the rows and
    is not retried. Nothing reaches the customer.
    """
    from django.db.models import F

    from .assistant import crm_fields
    from .models import LeadAiCrmField

    rows = list(LeadAiCrmField.objects.filter(pk__in=list(row_ids or []), sent_at__isnull=True).order_by("pk"))
    live = []
    for row in rows:
        if _replaced(row):
            LeadAiCrmField.objects.filter(pk=row.pk).update(error="Replaced by a newer value before it was sent.", retry_at=None)
        else:
            live.append(row)
    if not live:
        return
    ids = [row.pk for row in live]
    LeadAiCrmField.objects.filter(pk__in=ids).update(attempts=F("attempts") + 1)
    try:
        answer = crm_fields.post(crm_fields.body_for(live))
    except crm_fields.FieldsError as exc:
        LeadAiCrmField.objects.filter(pk__in=ids).update(error=str(exc)[:500])
        if self.request.retries < len(CRM_RETRY):
            raise self.retry(exc=exc, countdown=CRM_RETRY[self.request.retries])
        LeadAiCrmField.objects.filter(pk__in=ids).update(retry_at=timezone.now() + CRM_CATCH_UP_EVERY)
        logger.warning("Lead AI could not write the shops fields of lead %s yet (the sweep tries again): %s", live[0].lead_id, exc)
        return
    if answer.get("ok"):
        LeadAiCrmField.objects.filter(pk__in=ids).update(sent_at=timezone.now(), error="", retry_at=None)
        return
    error = str(answer.get("error") or answer.get("detail") or "Refused")[:500]
    LeadAiCrmField.objects.filter(pk__in=ids).update(error=error, retry_at=None)
    logger.warning("The Lead fields tool refused the shops fields of lead %s: %s", live[0].lead_id, error)


FIELD_NAMES = {
    "UF_CRM_A7_BOT_STATUS": "Bot Status",
    "UF_CRM_A7_SHOP_TYPE": "Shop Type Wanted",
    "UF_CRM_A7_WA_OPT_OUT": "WhatsApp Opt-out",
    "UF_CRM_LEAD_1737031634747": "Purpose",
    "UF_CRM_A7_AI_BUSINESS_ACTIVITY": "Business activity",
    "UF_CRM_A7_AI_TRADE_LICENSE_STATUS": "Trade license status",
    "lost": "the move to a lost stage",
}


def _retry_crm_fields() -> None:
    """Shops lead fields the task could not write while Bitrix was down: sent again every
    15 minutes for six hours (each value its own newest row; a replaced one never),
    then the agents are told once which to set by hand. Opt-outs most of all: those
    fields keep every later campaign away from the customer (board C10, C11)."""
    from apps.inbox.models import Conversation

    from .assistant import alerts
    from .models import LeadAiChat, LeadAiCrmField

    now = timezone.now()
    due = list(LeadAiCrmField.objects.filter(sent_at__isnull=True, retry_at__lte=now).order_by("pk")[:200])
    retry: dict = {}
    expired: dict = {}
    for row in due:
        (expired if now - row.created_at > CRM_CATCH_UP_FOR else retry).setdefault(row.conversation_id, []).append(row)
    for conversation_id, rows in expired.items():
        LeadAiCrmField.objects.filter(pk__in=[row.pk for row in rows]).update(retry_at=None)
        rows = [row for row in rows if not _replaced(row)]
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
        write_crm_fields.delay(ids)


@shared_task(bind=True, ignore_result=True, max_retries=3, soft_time_limit=60, time_limit=90)
def record_crm_note(self, conversation_id: int, kind: str) -> None:
    from apps.crmlink import client
    from apps.inbox.models import Conversation

    from .assistant import crm
    from .models import LeadAiChat

    conversation = Conversation.objects.select_related("contact").filter(pk=conversation_id).first()
    if conversation is None or not client.configured():
        return
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    try:
        entity, crm_id, _ = crm.record_for(chat, conversation)
        if entity and crm_id:
            crm.add_comment(entity, crm_id, crm.note_text(kind, conversation.contact.display_name, conversation.contact.wa_id))
    except client.BitrixError as exc:
        if _transient(exc) and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=CRM_RETRY[min(self.request.retries, len(CRM_RETRY) - 1)])


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def outbound_failed(message_id: int) -> None:
    """A Lead AI message (reply, reminder, pin, tap answer) WhatsApp later reported as failed.

    A reminder sent as buttons that failed because the 24-hour window had
    just closed (131047) is tried once more as the approved template; any
    other failure is told to the agents, so nobody believes the customer was
    reminded or confirmed when they were not. Only the appointment's current
    reminder counts: a late failure of an older one (before a reschedule, or
    one already retried) changes nothing, and a second copy of the same
    status never retries twice.
    """
    from apps.inbox import services as inbox_services
    from apps.inbox.models import Message

    from .assistant import alerts, live, reminders
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
            template = reminders.approved_template(conversation)
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
