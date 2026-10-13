"""Reminders, reminder taps, the Bitrix sync and the agents' alerts: the fixes from
the review (the finding each class covers is named in its docstring).

The clock, the model, the gateway and Bitrix are the fakes of test_assistant;
Bitrix here is a small stateful fake that plans a to-do the way BP 235 does.
"""

import datetime as dt
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import WaTemplate
from apps.crmlink import client
from apps.inbox.models import Conversation, Message
from apps.leadai import lane, tasks
from apps.leadai.assistant import alerts, crm, engine, reminders, rules, taps
from apps.leadai.models import (
    LeadAiAlert,
    LeadAiAppointment,
    LeadAiChat,
    LeadAiChatState,
    LeadAiCrmStep,
    LeadAiSettings,
    LeadAiTurn,
)
from apps.leadai.tests.test_assistant import (
    NOW,
    TEST_SETTINGS,
    TUESDAY_5PM,
    Base,
    _outbound,
    fake_send_buttons,
    fake_send_template,
    fake_send_text,
)

DUBAI = TUESDAY_5PM.tzinfo
T2 = dt.datetime(2026, 10, 14, 11, 0, tzinfo=DUBAI)  # Wednesday 11:00
T3 = dt.datetime(2026, 10, 14, 15, 0, tzinfo=DUBAI)  # Wednesday 15:00
BITRIX = {**TEST_SETTINGS, "BITRIX_WEBHOOK_URL": "https://bitrix.test/rest/1/token/"}
TOOL = Path(__file__).resolve().parents[4] / "ops" / "bitrix-aws" / "a7_leadai_notify.php"


def reminder_template(category="UTILITY"):
    return WaTemplate.objects.create(
        waba_business_id="waba1",
        name=reminders.TEMPLATE_NAME,
        language="en",
        category=category,
        status=WaTemplate.Status.APPROVED,
        components=[{"type": "BODY", "text": "Hi {{1}} at {{2}} at {{3}}."}],
    )


class FakeBitrix:
    """The lead's stage, its to-dos and the comments. Like BP 235, an update of a
    lead in stage 10 plans a new "Viewing/Meeting" to-do, due now."""

    def __init__(self, stage="IN_PROCESS", assigned="88", todos=None, down=False, plans_todo=True, stale_reads=False):
        self.stage = stage
        self.assigned = assigned
        self.todos = dict(todos or {})  # id -> {"deadline", "done", "created"}
        self.down = down
        self.plans_todo = plans_todo
        self.stale_reads = stale_reads  # every read sees the stage before anyone wrote
        self.comments = []
        self.calls = []
        self.next_todo = 901

    def __call__(self, method, payload=None):
        self.calls.append((method, payload))
        if self.down:
            raise client.BitrixError(f"{method}: timed out")
        if method == "crm.lead.get":
            return {"ID": "555", "STATUS_ID": "IN_PROCESS" if self.stale_reads else self.stage, "ASSIGNED_BY_ID": self.assigned}
        if method == "crm.lead.update":
            self.stage = payload["fields"].get("STATUS_ID", self.stage)
            if self.stage == "10" and self.plans_todo:
                self.todos[self.next_todo] = {"deadline": "now", "done": False, "created": timezone.now()}
                self.next_todo += 1
            return True
        if method == "crm.activity.list":
            wanted = payload["filter"].get("ID")
            ids = sorted((i for i, t in self.todos.items() if not t["done"] and wanted in (None, i)), reverse=True)
            return [
                {"ID": str(i), "DEADLINE": self.todos[i]["deadline"], "CREATED": self.todos[i]["created"].astimezone(DUBAI).isoformat()}
                for i in ids
            ]
        if method == "crm.activity.todo.updateDeadline":
            self.todos[payload["id"]]["deadline"] = payload["value"]
            return True
        if method == "crm.activity.update":
            fields = payload["fields"]
            if "DEADLINE" in fields:
                self.todos[payload["id"]]["deadline"] = fields["DEADLINE"]
            if fields.get("COMPLETED") == "Y":
                self.todos[payload["id"]]["done"] = True
            return True
        if method == "crm.timeline.comment.add":
            self.comments.append(payload["fields"]["COMMENT"])
            return 1
        return True

    def methods(self):
        return [m for m, _ in self.calls]


def todo(deadline="now", days_old=2):
    return {"deadline": deadline, "done": False, "created": NOW - dt.timedelta(days=days_old)}


class RcBase(Base):
    def setUp(self):
        super().setUp()
        self.crm_delay = self.stub("apps.leadai.tasks.sync_appointment_crm.delay")
        self.note_delay = self.stub("apps.leadai.tasks.record_crm_note.delay")
        self.readback = self.stub("apps.leadai.tasks.crm_readback.apply_async")
        self.turn_async = self.stub("apps.leadai.tasks.assistant_turn.apply_async")
        self.tap_async = self.stub("apps.leadai.tasks.handle_reminder_tap.apply_async")

    def stub(self, target):
        patcher = patch(target)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def booked(self, starts_at=None, **fields):
        """A confirmed meeting (14:29 today by default), booked an hour ago."""
        start = starts_at or NOW + dt.timedelta(minutes=29)
        fields.setdefault("reminder_due_at", start - dt.timedelta(minutes=30))
        fields.setdefault("customer_name", "Ahmed Khan")
        fields.setdefault("history", [{"at": (NOW - dt.timedelta(hours=1)).isoformat(), "event": "confirmed"}])
        return LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=start, **fields)

    def send_due(self):
        pk, at, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_buttons", side_effect=fake_send_buttons) as send:
            route = reminders.send(pk, at, start)
        return route, send

    def state(self):
        return LeadAiChatState.for_conversation(self.conversation)

    def session_tap(self, button_id, reply_to=None, title="On My Way", **fields):
        return self.inbound(
            title,
            kind=Message.Kind.INTERACTIVE,
            payload={"interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": title}}},
            reply_to=reply_to,
            **fields,
        )


class ReminderOptOutTests(RcBase):
    """find:reminders#0: an opt-out no turn ever saw still stops the reminder."""

    def test_a_stop_in_a_chat_moved_to_the_inbox_is_recorded_and_nothing_is_sent(self):
        appointment = self.booked()
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)
        self.inbound("STOP", seconds_ago=600)
        route, send = self.send_due()
        self.assertEqual(route, "suppressed")
        send.assert_not_called()
        self.assertEqual(self.state().stop_reason, "stop_all")
        appointment.refresh_from_db()
        self.assertEqual(appointment.reminder_error, reminders.OPTED_OUT)
        self.assertTrue(LeadAiAlert.objects.filter(kind="opt_out").exists())
        tasks._reminder_problem_alert(appointment.pk)  # nobody is asked to remind them by hand
        self.assertFalse(LeadAiAlert.objects.filter(kind="reminder_failed").exists())

    def test_a_stop_then_a_thanks_is_still_a_stop(self):
        self.booked()
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)
        self.inbound("Unsubscribe", kind=Message.Kind.BUTTON, payload={"button": {"text": "Unsubscribe"}}, seconds_ago=600)
        self.inbound("🙏", seconds_ago=590)
        route, send = self.send_due()
        self.assertEqual(route, "suppressed")
        send.assert_not_called()

    def test_not_interested_cancels_the_meeting_instead_of_reminding_it(self):
        appointment = self.booked()
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)
        self.inbound("Not Interested", kind=Message.Kind.BUTTON, payload={"button": {"text": "Not Interested"}}, seconds_ago=600)
        route, send = self.send_due()
        self.assertEqual(route, "suppressed")
        send.assert_not_called()
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.reminder_error), ("cancelled", reminders.DECLINED))

    def test_what_the_assistant_judged_or_said_before_the_booking_does_not_block(self):
        self.booked()
        self.inbound("STOP", seconds_ago=3 * 3600)  # before the booking an hour ago
        stop = self.inbound("Stop", seconds_ago=600)
        # The assistant saw this one (and an agent pressed Resume since).
        LeadAiTurn.objects.create(conversation=self.conversation, inbound=stop, status=LeadAiTurn.Status.REPLIED)
        route, _ = self.send_due()
        self.assertEqual(route, "buttons")
        self.assertIsNone(self.state().stopped_at)

    def test_a_stop_followed_by_a_real_request_is_not_a_stop(self):
        self.booked()
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)
        self.inbound("Stop", seconds_ago=600)
        self.inbound("sending me studios, I need a 2BR", seconds_ago=590)
        route, _ = self.send_due()
        self.assertEqual(route, "buttons")


class TapWindowTests(RcBase):
    """find:reminders#2, find:policy#22: a tap outside its window goes to the assistant."""

    def template_tap(self, appointment, label="Need to Reschedule"):
        reminder = _outbound(
            self.conversation, None, Message.Kind.TEMPLATE, "reminder", {"source": "leadai_reminder", "appointment": appointment.pk}
        )
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(
            reminder_message=reminder, reminder_sent_at=appointment.starts_at - dt.timedelta(minutes=30)
        )
        return self.inbound(label, kind=Message.Kind.BUTTON, payload={"button": {"text": label}}, reply_to=reminder)

    def test_a_tap_two_and_a_half_hours_after_a_missed_meeting_is_answered(self):
        appointment = self.booked(NOW - dt.timedelta(hours=2, minutes=30))
        tap = self.template_tap(appointment)
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
            result = taps.handle(tap.pk)
        self.assertEqual(result, "tap: reschedule")
        appointment.refresh_from_db()
        self.assertEqual(appointment.customer_state, "reschedule")
        self.assertTrue(LeadAiAlert.objects.filter(kind="reschedule_requested").exists())
        self.assertTrue(Message.objects.filter(payload__source="leadai_tap").exists())

    def test_a_tap_after_the_window_goes_to_the_assistant_without_a_turn(self):
        # Still confirmed: the sweep closes it a minute later.
        appointment = self.booked(NOW - dt.timedelta(hours=3, minutes=5))
        tap = self.template_tap(appointment)
        self.assertEqual(reminders.tap_on_reminder(tap), (None, ""))
        tasks.handle_reminder_tap(tap.pk)
        self.assertFalse(LeadAiTurn.objects.filter(inbound=tap).exists())
        self.turn_async.assert_called_once_with(args=[tap.pk], countdown=10)

    def test_a_tap_half_a_day_before_the_meeting_is_not_ours(self):
        appointment = self.booked(NOW + dt.timedelta(hours=13))
        self.assertEqual(reminders.tap_on_reminder(self.template_tap(appointment, "On My Way")), (None, ""))


class OutboundFailedTests(RcBase):
    """find:reminders#3 (the current reminder only, one retry) and find:engine#10 (the booking tag)."""

    def failed_reminder(self, appointment, code="131047", current=True):
        row = fake_send_buttons(
            self.conversation, None, "r", [{"id": "x", "title": "On My Way"}],
            payload={"source": "leadai_reminder", "appointment": appointment.pk},
        )
        Message.objects.filter(pk=row.pk).update(status="failed", error_code=code, error_detail="Message failed")
        if current:
            LeadAiAppointment.objects.filter(pk=appointment.pk).update(reminder_message=row, reminder_sent_at=NOW - dt.timedelta(minutes=1))
        return row

    def test_a_late_failure_of_an_older_reminder_changes_nothing(self):
        appointment = self.booked(NOW + dt.timedelta(hours=3))  # rescheduled; its new reminder is not out yet
        old = self.failed_reminder(appointment, code="131026", current=False)
        tasks.outbound_failed(old.pk)
        appointment.refresh_from_db()
        self.assertEqual(appointment.reminder_error, "")
        self.assertFalse(LeadAiAlert.objects.filter(kind="reminder_failed").exists())
        self.assertIsNotNone(reminders.claim_one(appointment.reminder_due_at))

    def test_the_closed_window_retry_goes_once_however_often_the_status_comes(self):
        reminder_template()
        appointment = self.booked(NOW + dt.timedelta(minutes=25))
        failed = self.failed_reminder(appointment)
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template) as send:
            tasks.outbound_failed(failed.pk)
            tasks.outbound_failed(failed.pk)
        self.assertEqual(send.call_count, 1)
        appointment.refresh_from_db()
        self.assertEqual(appointment.reminder_message.kind, Message.Kind.TEMPLATE)

    def test_no_retry_to_a_customer_who_asked_us_to_stop(self):
        reminder_template()
        appointment = self.booked(NOW + dt.timedelta(minutes=25))
        failed = self.failed_reminder(appointment)
        LeadAiChatState.objects.filter(pk=self.state().pk).update(stopped_at=NOW, stop_reason="stop_all")
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template) as send:
            tasks.outbound_failed(failed.pk)
        send.assert_not_called()
        appointment.refresh_from_db()
        self.assertEqual(appointment.reminder_error, reminders.OPTED_OUT)
        self.assertFalse(LeadAiAlert.objects.filter(kind="reminder_failed").exists())

    def test_a_failed_booking_confirmation_is_high_priority_from_its_own_tag(self):
        booking = {"event": "confirmed", "starts_at": TUESDAY_5PM.isoformat(), "appointment": None}
        sent = _outbound(self.conversation, None, Message.Kind.TEXT, "Perfect, Ahmed.", {"source": "leadai_ai", "turn": 1, "booking": booking})
        Message.objects.filter(pk=sent.pk).update(status="failed", error_code="131026")
        tasks.outbound_failed(sent.pk)
        alert = LeadAiAlert.objects.get(kind="ai_send_failed", agent=self.agent)
        self.assertEqual(alert.priority, "high")
        self.assertIn("booking confirmation", alert.text)


class SoftLimitTests(RcBase):
    """find:reminders#5: the sweep's time limit, and claims a crash left behind."""

    def test_the_time_limit_is_not_swallowed_by_a_send(self):
        self.booked()
        pk, at, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_buttons", side_effect=SoftTimeLimitExceeded()):
            with self.assertRaises(SoftTimeLimitExceeded):
                reminders.send(pk, at, start)
        self.assertEqual(LeadAiAppointment.objects.get(pk=pk).reminder_error, "")  # stale_claims settles it

    def test_the_sweep_stops_claiming_when_its_time_is_up(self):
        self.booked()
        with patch("apps.leadai.tasks.REMINDER_CLAIMS_FOR", -1), patch(
            "apps.inbox.services.send_buttons", side_effect=fake_send_buttons
        ) as send:
            tasks._reminders()
        send.assert_not_called()
        self.assertIsNotNone(reminders.claim_one(NOW))  # left for the next sweep

    def stale(self, **message_fields):
        claimed = NOW - dt.timedelta(minutes=11)
        appointment = self.booked(NOW + dt.timedelta(minutes=25), reminder_claimed_at=claimed)
        row = _outbound(
            self.conversation, None, Message.Kind.INTERACTIVE, "r", {"source": "leadai_reminder", "appointment": appointment.pk}
        )
        Message.objects.filter(pk=row.pk).update(created_at=claimed + dt.timedelta(seconds=5), **message_fields)
        return appointment

    def test_a_row_that_never_left_is_sent_again_not_taken_for_sent(self):
        appointment = self.stale(status="queued", wamid=None)
        self.assertEqual(dict(reminders.stale_claims(NOW))[appointment.pk], "resent")
        appointment.refresh_from_db()
        self.assertIsNone(appointment.reminder_sent_at)
        self.assertIsNone(appointment.reminder_claimed_at)

    def test_a_failed_row_is_told_to_the_agents(self):
        appointment = self.stale(status="failed", error_code="131026")
        with patch("apps.inbox.services.send_buttons", side_effect=fake_send_buttons) as send:
            tasks._reminders()
        send.assert_not_called()
        appointment.refresh_from_db()
        self.assertIsNone(appointment.reminder_sent_at)
        self.assertTrue(LeadAiAlert.objects.filter(kind="reminder_failed").exists())

    def test_a_row_that_reached_whatsapp_is_linked(self):
        appointment = self.stale(status="queued", wamid="wamid.ok")
        self.assertEqual(dict(reminders.stale_claims(NOW))[appointment.pk], "linked")


class ShortWindowTests(RcBase):
    """find:reminders#6: a few minutes of window and no template still get the buttons."""

    def test_a_window_closing_within_ten_minutes_still_gets_the_buttons(self):
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=NOW + dt.timedelta(minutes=5))
        self.booked()
        route, send = self.send_due()
        self.assertEqual(route, "buttons")
        send.assert_called_once()

    def test_with_an_approved_template_the_short_window_uses_it(self):
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=NOW + dt.timedelta(minutes=5))
        reminder_template()
        self.booked()
        pk, at, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template):
            self.assertEqual(reminders.send(pk, at, start), "template")


class ButtonStampTests(RcBase):
    """find:reminders#7: a tap names the meeting time its reminder was sent for."""

    def test_the_buttons_name_the_meeting_time(self):
        appointment = self.booked()
        _, send = self.send_due()
        ids = [b["id"] for b in send.call_args.args[3]]
        self.assertEqual(ids[0], f"leadai:{appointment.pk}:202610121429:on_my_way")

    def test_a_tap_on_the_reminder_from_before_a_reschedule_is_not_ours(self):
        appointment = self.booked()
        old_reminder = _outbound(self.conversation, None, Message.Kind.INTERACTIVE, "old", {"source": "leadai_reminder"})
        # Rescheduled to tomorrow 10:00: the reschedule unlinks the old reminder.
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(
            starts_at=dt.datetime(2026, 10, 13, 10, 0, tzinfo=DUBAI), reminder_message=None, reminder_sent_at=None
        )
        self.clock.return_value = dt.datetime(2026, 10, 12, 23, 0, tzinfo=DUBAI)  # inside the new meeting's window
        stamped = f"leadai:{appointment.pk}:202610121429:on_my_way"
        for button in (f"leadai:{appointment.pk}:on_my_way", stamped):
            with self.subTest(button=button):
                self.assertEqual(reminders.tap_on_reminder(self.session_tap(button, reply_to=old_reminder)), (None, ""))
        self.assertEqual(reminders.tap_on_reminder(self.session_tap(stamped)), (None, ""))  # no context: the time decides

    def test_a_tap_on_the_current_reminder_counts_even_after_running_late_moved_the_time(self):
        appointment = self.booked()
        _, send = self.send_due()
        appointment.refresh_from_db()
        reminder = appointment.reminder_message
        on_my_way = send.call_args.args[3][0]["id"]
        self.assertEqual(reminders.tap_on_reminder(self.session_tap(on_my_way, reply_to=reminder))[0].pk, appointment.pk)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=appointment.starts_at + dt.timedelta(minutes=45))
        self.assertEqual(reminders.tap_on_reminder(self.session_tap(on_my_way, reply_to=reminder))[0].pk, appointment.pk)
        self.assertEqual(reminders.tap_on_reminder(self.session_tap(on_my_way)), (None, ""))  # no context: the time decides

    def test_a_template_quick_reply_must_answer_the_current_reminder(self):
        self.booked(reminder_sent_at=NOW - dt.timedelta(minutes=1))  # no reminder row linked
        other = _outbound(self.conversation, None, Message.Kind.TEMPLATE, "an older reminder", {"source": "leadai_reminder"})
        tap = self.inbound("On My Way", kind=Message.Kind.BUTTON, payload={"button": {"text": "On My Way"}}, reply_to=other)
        self.assertEqual(reminders.tap_on_reminder(tap), (None, ""))


class UnansweredTests(RcBase):
    """find:engine#5: a message no turn took (a long OpenAI outage) is told to the agents."""

    def test_a_message_no_turn_took_is_told_once(self):
        self.inbound("Is the shop still available?", seconds_ago=20 * 60)
        tasks._flag_unanswered()
        tasks._flag_unanswered()
        stale = LeadAiAlert.objects.filter(kind="stale")
        self.assertEqual([a.agent_id for a in stale], [self.agent.pk])
        self.assertIn("Please reply by hand", stale[0].text)

    def test_not_in_a_chat_the_switched_off_assistant_ignores(self):
        LeadAiSettings.objects.filter(pk=1).update(assistant_enabled=False)
        self.inbound("hello?", seconds_ago=20 * 60)
        tasks._flag_unanswered()
        self.assertFalse(LeadAiAlert.objects.filter(kind="stale").exists())

    def test_not_when_answered_taken_paused_or_too_fresh(self):
        message = self.inbound("hello?", seconds_ago=20 * 60)
        answer = _outbound(self.conversation, self.agent, Message.Kind.TEXT, "Hi, yes", {})
        tasks._flag_unanswered()  # an agent answered it
        answer.delete()
        turn = LeadAiTurn.objects.create(conversation=self.conversation, inbound=message, status=LeadAiTurn.Status.SKIPPED)
        tasks._flag_unanswered()  # a turn took it
        turn.delete()
        LeadAiChatState.objects.filter(pk=self.state().pk).update(paused_at=NOW)
        tasks._flag_unanswered()  # an agent paused the assistant
        LeadAiChatState.objects.filter(pk=self.state().pk).update(paused_at=None)
        Message.objects.filter(pk=message.pk).update(created_at=NOW - dt.timedelta(minutes=10))
        tasks._flag_unanswered()  # the missed-turn retries still own it
        self.assertFalse(LeadAiAlert.objects.filter(kind="stale").exists())


class MissedTapTests(RcBase):
    """find:engine#6: the safety net hands a lost tap to the tap handler."""

    def test_a_lost_tap_goes_to_the_tap_handler_not_to_the_assistant(self):
        appointment = self.booked()
        tap = self.session_tap(reminders.button_id(appointment, "on_my_way"), seconds_ago=5 * 60)
        tasks._queue_missed_turns()
        self.tap_async.assert_called_once_with(args=[tap.pk])
        self.turn_async.assert_not_called()


class StuckTurnTests(RcBase):
    """find:engine#13: a killed turn's reply counts only if it left, and a lost booking is loud."""

    def stuck(self):
        inbound = self.inbound("Tomorrow at 5 pm", seconds_ago=600)
        turn = LeadAiTurn.objects.create(conversation=self.conversation, inbound=inbound)
        LeadAiTurn.objects.filter(pk=turn.pk).update(created_at=NOW - dt.timedelta(minutes=6))
        return turn

    def reply(self, turn, **fields):
        booking = {"event": "confirmed", "starts_at": TUESDAY_5PM.isoformat(), "appointment": None}
        row = _outbound(self.conversation, None, Message.Kind.TEXT, "Perfect, Ahmed.", {"source": "leadai_ai", "turn": turn.pk, "booking": booking})
        Message.objects.filter(pk=row.pk).update(**fields)
        return row

    def test_a_reply_still_queued_is_not_an_answer(self):
        turn = self.stuck()
        self.reply(turn, status="queued", wamid=None)
        tasks._resolve_stuck_turns()
        turn.refresh_from_db()
        self.assertEqual(turn.status, "failed")
        self.assertTrue(LeadAiAlert.objects.filter(kind="ai_error").exists())

    def test_a_booking_told_but_never_recorded_raises_a_high_alert(self):
        turn = self.stuck()
        self.reply(turn, wamid="wamid.booked")
        tasks._resolve_stuck_turns()
        turn.refresh_from_db()
        self.assertEqual(turn.status, "replied")
        alert = LeadAiAlert.objects.get(kind="booking_unrecorded", agent=self.agent)
        self.assertEqual(alert.priority, "high")
        self.assertIn("Tuesday 13 October 2026, 5:00 PM", alert.text)

    def test_a_recorded_booking_raises_nothing(self):
        turn = self.stuck()
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=TUESDAY_5PM)
        self.reply(turn, wamid="wamid.booked")
        tasks._resolve_stuck_turns()
        self.assertFalse(LeadAiAlert.objects.filter(kind="booking_unrecorded").exists())


@override_settings(**BITRIX)
class CrmBase(RcBase):
    def make(self, **fields):
        defaults = dict(status="confirmed", starts_at=TUESDAY_5PM, customer_name="Ahmed", crm_entity="lead", crm_id=555)
        defaults.update(fields)
        return LeadAiAppointment.objects.create(conversation=self.conversation, **defaults)

    def sync(self, bitrix, appointment, event, revision=None, hot=False):
        bitrix.calls.clear()
        with patch("apps.crmlink.client.call", side_effect=bitrix):
            tasks.sync_appointment_crm(appointment.pk, event, hot, revision)
        appointment.refresh_from_db()
        return bitrix.methods()


class CrmTodoTests(CrmBase):
    """find:crm_alerts#0: only the assistant's own to-do is moved or completed."""

    def test_a_lead_already_in_ten_keeps_its_agents_todo(self):
        bitrix = FakeBitrix(stage="10", todos={700: todo("2026-10-15T15:00:00+04:00")})
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)
        self.assertNotIn("crm.lead.update", bitrix.methods())
        self.assertEqual(bitrix.todos[700]["deadline"], "2026-10-15T15:00:00+04:00")
        self.assertIsNone(appointment.crm_todo_id)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(status="cancelled")
        self.sync(bitrix, appointment, "cancelled", revision=2)
        self.assertFalse(bitrix.todos[700]["done"])

    def test_a_reschedule_moves_the_assistants_own_todo_not_the_newest(self):
        bitrix = FakeBitrix()
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)  # the lead goes to 10; BP 235 plans 901
        self.assertEqual(appointment.crm_todo_id, 901)
        self.assertEqual(bitrix.todos[901]["deadline"], TUESDAY_5PM.isoformat())
        # An agent edits the lead while it sits in 10: BP 235 plans 902, due now.
        bitrix.todos[902] = todo(days_old=0)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=T2)
        self.sync(bitrix, appointment, "rescheduled", revision=2)
        self.assertEqual(bitrix.todos[901]["deadline"], T2.isoformat())
        self.assertEqual(bitrix.todos[902]["deadline"], "now")
        self.assertEqual(appointment.crm_todo_id, 901)

    def test_an_older_todo_is_never_taken_for_the_one_our_update_planned(self):
        bitrix = FakeBitrix(plans_todo=False, todos={700: todo("2026-10-15T15:00:00+04:00")})
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)
        self.assertIn("crm.lead.update", bitrix.methods())
        self.assertEqual(bitrix.todos[700]["deadline"], "2026-10-15T15:00:00+04:00")
        self.assertIsNone(appointment.crm_todo_id)

    def test_our_todo_closed_in_bitrix_hands_the_meeting_to_the_heads_up(self):
        bitrix = FakeBitrix()
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)
        bitrix.todos[901]["done"] = True  # the agent ticked it off
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=T2)
        self.sync(bitrix, appointment, "rescheduled", revision=2)
        self.assertIsNone(appointment.crm_todo_id)

    def test_a_cancel_closes_our_todo_even_before_its_id_was_stored(self):
        bitrix = FakeBitrix()
        appointment = self.make()
        with patch("apps.leadai.assistant.crm.find_meeting_todo", side_effect=client.BitrixError("crm.activity.list: timed out")):
            self.sync(bitrix, appointment, "confirmed", revision=1)
        self.assertIsNone(appointment.crm_todo_id)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(status="cancelled")
        self.sync(bitrix, appointment, "cancelled", revision=2)
        self.assertTrue(bitrix.todos[901]["done"])


class CrmRevisionTests(CrmBase):
    """find:crm_alerts#1, #2, #6, #8: per-revision steps, one lead update, the hot marker."""

    def test_a_late_booking_sync_after_a_cancel_writes_nothing(self):
        bitrix = FakeBitrix()
        appointment = self.make(status="cancelled")
        self.assertEqual(self.sync(bitrix, appointment, "confirmed", revision=1), [])
        self.assertEqual(bitrix.stage, "IN_PROCESS")

    def test_a_move_back_to_an_earlier_time_is_synced(self):
        bitrix = FakeBitrix()
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)
        for revision, when in ((2, T2), (3, T3), (4, T2)):
            LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=when)
            self.sync(bitrix, appointment, "rescheduled", revision=revision)
        self.assertEqual(bitrix.todos[901]["deadline"], T2.isoformat())
        self.assertEqual(sum("MEETING RESCHEDULED" in c for c in bitrix.comments), 3)
        self.assertIn("When: Wednesday 14 October 2026, 11:00 AM", bitrix.comments[-1])

    def test_the_lead_is_updated_once_per_appointment(self):
        bitrix = FakeBitrix(stale_reads=True)  # both syncs read the lead before either wrote
        appointment = self.make()
        methods = self.sync(bitrix, appointment, "confirmed", revision=1)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=T2)
        methods += self.sync(bitrix, appointment, "rescheduled", revision=2)
        self.assertEqual(methods.count("crm.lead.update"), 1)
        self.assertEqual([i for i, t in bitrix.todos.items() if not t["done"]], [901])
        self.assertEqual(bitrix.todos[901]["deadline"], T2.isoformat())

    def test_running_late_without_a_time_is_a_comment_only(self):
        bitrix = FakeBitrix(stage="10")
        appointment = self.make(customer_state="running_late")
        self.assertEqual(self.sync(bitrix, appointment, "running_late", revision=3), ["crm.lead.get", "crm.timeline.comment.add"])
        self.assertIn("CUSTOMER RUNNING LATE", bitrix.comments[0])
        self.assertIn("not said yet when they will arrive", bitrix.comments[0])

    def test_a_hot_booking_says_so_on_the_record(self):
        bitrix = FakeBitrix()
        appointment = self.make(details={"size_sqft": 450, "move_in": "this week", "trade_licence": "yes"})
        self.sync(bitrix, appointment, "confirmed", revision=1, hot=True)
        comment = bitrix.comments[0]
        self.assertTrue(comment.startswith("WhatsApp Lead AI · HOT LEAD · MEETING CONFIRMED"))
        self.assertIn("Needs the space soon and is visiting today.", comment)
        self.assertNotIn("HOT LEAD", crm.comment_text(appointment, "confirmed"))

    def test_comments_carry_no_html(self):
        self.assertEqual(crm.safe('<a href="https://x">Wednesday</a> [b]4pm[/b]'), '‹a href="https://x"›Wednesday‹/a› (b)4pm(/b)')


class ResponsibleTests(CrmBase):
    """find:crm_alerts#4: a failed lookup is asked again; a responsible found late still hears of the booking."""

    def test_a_failed_lookup_is_asked_again(self):
        LeadAiChatState.objects.filter(pk=self.state().pk).update(responsible_checked_at=NOW)
        with patch("apps.crmlink.client.call", side_effect=client.BitrixError("crm.lead.get: timed out")):
            tasks.resolve_responsible(self.conversation.pk)
        self.assertIsNone(self.state().responsible_checked_at)

    def test_a_responsible_found_only_by_the_sync_gets_the_booking_alert(self):
        appointment = self.make()
        # The engine's own alert reached only the chat owner: the responsible was not known yet.
        engine.appointment_alert(self.conversation, self.chat, appointment, "confirmed", False, "Ahmed", revision=1)
        self.assertEqual(list(LeadAiAlert.objects.filter(kind="booked").values_list("bitrix_user_id", flat=True)), ["77"])
        self.sync(FakeBitrix(assigned="88"), appointment, "confirmed", revision=1)
        self.assertEqual(sorted(LeadAiAlert.objects.filter(kind="booked").values_list("bitrix_user_id", flat=True)), ["77", "88"])


class CrmCatchUpTests(CrmBase):
    """find:crm_alerts#9: Bitrix work a sync gave up on is tried again, then told."""

    def give_up(self, appointment, event="confirmed", hot=False, revision=1):
        with patch("apps.crmlink.client.call", side_effect=FakeBitrix(down=True)):
            result = tasks.sync_appointment_crm.apply(args=[appointment.pk, event, hot, revision], retries=len(tasks.CRM_RETRY))
        self.assertTrue(result.successful())
        appointment.refresh_from_db()

    def test_tried_again_every_fifteen_minutes_then_the_agents_are_told_once(self):
        appointment = self.make()
        self.give_up(appointment, hot=True)
        self.assertIn("timed out", appointment.crm_error)
        tasks._retry_crm_syncs()
        self.crm_delay.assert_not_called()
        self.clock.return_value = NOW + dt.timedelta(minutes=16)
        tasks._retry_crm_syncs()
        self.crm_delay.assert_called_once_with(appointment.pk, "confirmed", True, 1)
        self.clock.return_value = NOW + dt.timedelta(minutes=20)
        tasks._retry_crm_syncs()
        self.assertEqual(self.crm_delay.call_count, 1)
        self.clock.return_value = NOW + dt.timedelta(minutes=32)
        tasks._retry_crm_syncs()
        self.assertEqual(self.crm_delay.call_count, 2)
        self.clock.return_value = NOW + dt.timedelta(hours=6, minutes=1)
        tasks._retry_crm_syncs()
        tasks._retry_crm_syncs()
        self.assertEqual(self.crm_delay.call_count, 2)
        failed = LeadAiAlert.objects.filter(kind="crm_failed")
        self.assertEqual([a.agent_id for a in failed], [self.agent.pk])
        self.assertIn("Please update it by hand", failed[0].text)

    def test_another_events_sync_does_not_hide_the_failure_and_the_retry_clears_it(self):
        appointment = self.make()
        self.give_up(appointment)
        self.sync(FakeBitrix(stage="10"), appointment, "on_my_way", revision=2)
        self.assertIn("timed out", appointment.crm_error)
        bitrix = FakeBitrix()
        self.sync(bitrix, appointment, "confirmed", revision=1)
        self.assertIn("crm.lead.update", bitrix.methods())
        self.assertEqual(appointment.crm_error, "")
        self.assertFalse(LeadAiCrmStep.objects.filter(step__startswith=tasks.CRM_PENDING).exists())

    def test_a_meeting_cancelled_meanwhile_is_not_retried(self):
        appointment = self.make()
        self.give_up(appointment)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(status="cancelled")
        self.clock.return_value = NOW + dt.timedelta(minutes=16)
        tasks._retry_crm_syncs()
        self.crm_delay.assert_not_called()
        self.assertFalse(LeadAiCrmStep.objects.filter(step__startswith=tasks.CRM_PENDING).exists())


class ContactCampaignTests(RcBase):
    """find:crm_alerts#5: a card the send matched by phone is never the chosen record."""

    def chat_for(self, name, phone, owner_data_id):
        campaign = Campaign.objects.create(name=name, number=self.number, template=self.template, created_by=self.agent)
        lane.mark_campaign(campaign)
        recipient = CampaignRecipient.objects.create(campaign=campaign, phone=phone, name="Customer", owner_data_id=owner_data_id)
        lane.before_campaign_send(campaign, recipient)
        return LeadAiChat.objects.get(conversation__contact__wa_id=phone)

    def test_a_contacts_campaign_finds_its_record_by_phone(self):
        chat = self.chat_for("CRM Contacts · Lead AI · ic_shops", "971509998877", 4242)
        self.assertEqual((chat.crm_entity, chat.crm_id), ("", None))
        with patch("apps.crmlink.client.find_records", return_value=[{"type": "contact", "id": 991}]):
            self.assertEqual(crm.record_for(chat, chat.conversation), ("contact", 991, False))

    def test_the_owner_data_popup_card_is_the_chosen_record(self):
        chat = self.chat_for("Owner Data · Lead AI · ic_shops · retry", "971509998866", 4343)
        self.assertEqual(crm.record_for(chat, chat.conversation), ("owner_data", 4343, True))


class AlertDeliveryTests(RcBase):
    """find:crm_alerts#7 (no double buzz) and #10 (users 0 and 1 get the panel only)."""

    def test_the_owner_is_not_buzzed_twice_when_the_responsible_has_left(self):
        LeadAiChatState.objects.filter(pk=self.state().pk).update(responsible_bitrix_user_id="88", responsible_agent=None)
        rows = alerts.raise_alert(kind="booked", conversation=self.conversation, title="t", text="b", dedupe_key="dk")
        sent_to = []

        def notify(**kw):
            sent_to.append(kw["to_user_id"])
            return {"ok": False, "error": "No such active user."} if kw["to_user_id"] == 88 else {"ok": True, "id": 1}

        with patch("apps.leadai.assistant.alerts.notify_bitrix", side_effect=notify), patch("apps.inbox.events.publish_to_agent"):
            for row in rows:
                row.refresh_from_db()
                alerts.deliver(row)
        self.assertEqual(sorted(sent_to), [77, 88])

    def test_hold_users_get_the_panel_only(self):
        rows = alerts.raise_alert(kind="ai_down", conversation=self.conversation, title="t", text="b", dedupe_key="sys", admins=True)
        self.assertEqual([(r.agent_id, r.bitrix_user_id) for r in rows], [(self.admin.pk, "")])
        Conversation.objects.filter(pk=self.conversation.pk).update(assigned_agent=self.admin)
        self.conversation.refresh_from_db()
        rows = alerts.raise_alert(kind="booked", conversation=self.conversation, title="t", text="b", dedupe_key="own")
        self.assertEqual([(r.agent_id, r.bitrix_user_id) for r in rows], [(self.admin.pk, "")])
        departed = LeadAiAlert.objects.create(
            kind="booked", conversation=self.conversation, agent=None, bitrix_user_id="88", title="t", text="b", dedupe_key="k5"
        )
        with patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": False, "error": "No such active user."}) as notify:
            alerts.deliver(departed)
        self.assertEqual([c.kwargs["to_user_id"] for c in notify.call_args_list], [88])


@skipUnless(TOOL.exists(), "the Bitrix tool is not in this copy (the image holds the backend only)")
class NotifyToolTests(TestCase):
    """find:crm_alerts#3: the PHP tool escapes the body before it adds its own link."""

    def test_the_body_is_html_escaped_before_the_tools_own_link(self):
        source = TOOL.read_text(encoding="utf-8")
        self.assertLess(source.index("$message = htmlspecialcharsbx($plain);"), source.index("[URL="))
        self.assertIn("'<' => '‹', '>' => '›'", source)


class LanguageTests(RcBase):
    """find:policy#18: the tap answers and the free-form reminder follow the customer's language."""

    def test_a_tap_is_answered_in_the_customers_language(self):
        LeadAiChatState.objects.filter(pk=self.state().pk).update(language="ar")
        for action, expected in (("running_late", rules.line("ask_eta", "ar")), ("reschedule", rules.line("ask_new_time", "ar"))):
            LeadAiTurn.objects.all().delete()
            LeadAiAppointment.objects.all().delete()
            appointment = self.booked()
            with self.subTest(action=action):
                tap = self.session_tap(f"leadai:{appointment.pk}:{action}", title=dict(reminders.BUTTONS)[action])
                with patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
                    taps.handle(tap.pk)
                self.assertEqual(Message.objects.filter(payload__source="leadai_tap").latest("pk").body, expected)

    def test_on_my_way_with_no_language_yet_is_english(self):
        appointment = self.booked()
        tap = self.session_tap(f"leadai:{appointment.pk}:on_my_way")
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
            taps.handle(tap.pk)
        self.assertEqual(Message.objects.get(payload__source="leadai_tap").body, "Perfect. See you shortly.")

    def test_the_in_window_reminder_is_in_the_customers_language(self):
        LeadAiChatState.objects.filter(pk=self.state().pk).update(language="ur_latin")
        self.booked()
        _, send = self.send_due()
        text = send.call_args.args[2]
        self.assertTrue(text.startswith("Hi Ahmed, yaad dihani: aaj 2:29 PM par hamare office mein aap ki meeting hai:"))
        self.assertTrue(text.endswith("Barah-e-karam neeche button daba kar humein bata dein."))

    def test_with_no_name_the_greeting_stands_alone_and_the_template_stays_english(self):
        LeadAiChatState.objects.filter(pk=self.state().pk).update(language="ar")
        self.contact.display_name = ""
        self.contact.save(update_fields=["display_name"])
        appointment = self.booked(customer_name="")
        settings_row = LeadAiSettings.load()
        conversation = Conversation.objects.select_related("contact").get(pk=self.conversation.pk)
        self.assertTrue(reminders.reminder_text(appointment, conversation, settings_row, "ar").startswith("مرحباً، نذكّرك"))
        self.assertTrue(reminders.reminder_text(appointment, conversation, settings_row, "en").startswith("Hi there, a reminder"))
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=NOW - dt.timedelta(minutes=1))
        reminder_template()
        pk, at, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template) as send:
            self.assertEqual(reminders.send(pk, at, start), "template")
        self.assertEqual(send.call_args.args[3]["1"], "there")


class LiveHintTests(CrmBase):
    """The Lead AI screen hears of reminders, CRM syncs, closed meetings and taps."""

    def test_the_screen_is_told_what_changed(self):
        appointment = self.booked()
        with patch("apps.leadai.assistant.live.appointment_changed") as changed:
            self.send_due()
        changed.assert_called_with(self.conversation.pk)
        with patch("apps.leadai.assistant.live.appointment_changed") as changed:
            self.sync(FakeBitrix(), appointment, "confirmed", revision=1)
        changed.assert_called_with(self.conversation.pk)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=NOW - dt.timedelta(hours=4))
        with patch("apps.leadai.assistant.live.appointment_changed") as changed:
            tasks._close_past_appointments()
        changed.assert_called_once_with(self.conversation.pk)
