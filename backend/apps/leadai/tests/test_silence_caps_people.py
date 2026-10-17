"""Batch 2d, the launch fixes (2026-10-15): silence, caps and people (launch review issues 2, 3, 4, 14, 18 and 21).

What went wrong live, and what each test proves with the launch chats' own words (chat_<id>.json of the review) and the
model's live answers rebuilt from them; each fails without its guard (the patched-out cases show it):

- A. the reply cap (chats 91 and 78): a shops chat may send 12 replies an hour and 30 a day; a capped burst is answered
  once the cap frees, by the same turn row, however old it is, unless someone wrote since; the cap alert is high
  priority, reaches the Lead AI alert list and carries their words, the lead and the chat; a general chat keeps 6/20;
- B. a handover nobody answered (chats 88, 136): one more alert after 30 minutes of office time, once per handover;
- C. a call (chat 88): no call time is ever promised; the request goes with the time they gave in the handover alert and
  on the lead's timeline; a chase while a person has the chat gets an apology and an urgent alert, a call's time given
  then is passed on, a goodbye (chat 57) gets nothing;
- D. must-answer questions (chats 95, 91 and 78): handed to a person with the questions listed, never "at the viewing";
  commission alone is Matloob's own line (Q24);
- E. a STOP as the first answer (chat 112) reaches the lead's owner and the alert list;
- F. handover lines (chats 114, 105, 136): never "please contact Manhial", an apology may repeat, a handover asks
  nothing more, a shops chat's holding line says "our agent";
- G. the eval's scenarios, with the live answers.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai; the chat is lead 555's.
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import Agent
from apps.inbox.models import Message
from apps.leadai import bitrix_status, tasks
from apps.leadai.assistant import alerts, caps, crm_fields, engine, hours, people, rules
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChatState, LeadAiSettings, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, _outbound, answer, fake_send_location, fake_send_text
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_eval_guard_fixes import run_scenario
from apps.leadai.tests.test_follow_up_holds import DEFERRED_78, NINE_QUESTIONS
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, shop_answer

DUBAI = hours.DUBAI
MODEL = "apps.leadai.assistant.openai_client.complete_json"
SHOPS_HOLDING = people.line(people.HOLDING, "en", shops=True)
GENERAL_HOLDING = rules.line("holding", "en")
# Chat 88's own words, our slot offer before them, and the model's live answer (turn 88, reply 180150).
CALL_WORDS_88 = "We can have a call at 11.30 - 12 PM"
SLOTS_88 = (
    "No problem, many tenants open a new licence. Our agent will guide you through the process. I can hold a slot for you "
    "today at 11:30 AM or 12:00 PM — which is better?"
)
PROMISE_88 = "Our agent will call you today between 11:30 and 12:00 to discuss your needs and guide you further."
FACTS_88 = {
    "for_client": False, "property_type": "shop", "intent": "rent", "community": "France", "size_sqft": 400, "shop_type": "type_1",
    "licence_kind": "new", "trade_licence": "no", "customer_name": "Abd",
}
# Chat 95's live answer (reply 180120): all nine questions "at the viewing".
DEFERRED_95 = (
    "Thanks for your detailed questions about the shop for your dessert takeaway and production kitchen. Good question — I'll "
    "have our agent confirm those technical points for you at the viewing. Meanwhile, what size shop are you looking for?"
)
# Chat 91's live answer to the gas line and chimney (reply 180239).
GAS_91 = (
    "Good question — I'll have our agent confirm that for you at the viewing. Is 2:30 PM or 4:30 PM today better for you to "
    "come to our office and see the shops? Our agent will drive you to the shops and back."
)
GOODBYE_57 = "its ok sir no prblm thankyou for ur response"
# Chat 114's live reply (180130), and chat 105's (180252).
MANHIAL_114 = "We handle shops for rent in International City. For apartments, please contact Manhial as you mentioned. If you need a shop later, we are here to help."


def minutes(n):
    return NOW + dt.timedelta(minutes=n)


class PeopleBase(ShopsBase):
    """The tests' shops chat, its alerts listed to Matloob (2311) as live."""

    def setUp(self):
        super().setUp()
        self.list_matloob()

    def replies(self, count, first_minutes_ago):
        """``count`` replies of the assistant's own, one turn each, a minute apart from ``first_minutes_ago``."""
        for index in range(count):
            self.ours("Sure.", minutes_ago=first_minutes_ago - index, turn=9000 + index)

    def requeued(self, message, completions):
        """The task the cap's sweep queues (tasks._answer_capped): run_turn with requeued=True."""
        calls = []

        def model(messages, schema_, **kwargs):
            calls.append(messages)
            return completions[min(len(calls) - 1, len(completions) - 1)]

        with patch(MODEL, side_effect=model), patch("apps.inbox.services.send_text", side_effect=fake_send_text), patch(
            "apps.inbox.services.send_location", side_effect=fake_send_location
        ), patch("apps.leadai.tasks.sync_appointment_crm.delay"), patch("apps.leadai.tasks.record_crm_note.delay"), self.captureOnCommitCallbacks(
            execute=True
        ):
            outcome = engine.run_turn(message.pk, requeued=True)
        return outcome, calls

    def alerts_of(self, kind):
        return list(LeadAiAlert.objects.filter(conversation=self.conversation, kind=kind).order_by("pk"))

    def who_got(self, kind):
        return {(row.agent.username if row.agent else None, row.bitrix_user_id) for row in self.alerts_of(kind)}


# A. The reply cap -----------------------------------------------------------------------------------------------


class CapTests(PeopleBase):
    def test_chat_91_a_shops_chat_may_send_twelve_replies_an_hour(self):
        # Chat 91 got six replies in 16 minutes live, then "can you show me at least the video" was capped.
        self.replies(6, 16)
        video = self.inbound("can you show me at least the video of the sho[?", seconds_ago=20)
        outcome, calls, _, _ = self.turn(video, [shop_answer("Sure! Our agent can share it. What size do you need?")])
        self.assertNotEqual(outcome.reason, engine.CAPPED_REASON)
        self.assertEqual(len(calls), 1)
        self.assertEqual(caps.limits("ic_shops"), (12, 30))
        self.assertEqual(caps.limits("general"), (engine.CAP_PER_HOUR, engine.CAP_PER_DAY))

    def test_chat_91_with_the_old_cap_it_went_silent(self):
        self.replies(6, 16)
        video = self.inbound("can you show me at least the video of the sho[?", seconds_ago=20)
        with patch.object(caps, "SHOPS_PER_HOUR", 6):
            outcome, calls, _, _ = self.turn(video, [shop_answer("Sure!")])
        self.assertEqual((outcome.reason, calls), (engine.CAPPED_REASON, []))

    def capped_91(self):
        """Chat 91's last three messages, each turn held back by the cap (12 replies in the last 20 minutes)."""
        self.replies(12, 20)
        held = []
        for text, seconds in (("can you show me at least the video of the sho[?", 40), ("i cant come today as im at work", 25), ("i will be available on saturday", 10)):
            message = self.inbound(text, seconds_ago=seconds)
            outcome, calls, _, _ = self.turn(message, [shop_answer("never asked")])
            self.assertEqual((outcome.reason, calls), (engine.CAPPED_REASON, []))
            held.append(message)
        return held

    def test_chat_91_the_cap_alert_is_high_reaches_the_list_and_says_when_it_answers(self):
        self.capped_91()
        rows = self.alerts_of("cap")
        self.assertEqual(self.who_got("cap"), {("agent", "77"), ("matloob", "2311")})
        self.assertEqual({row.priority for row in rows}, {"high"})
        text = rows[0].text
        self.assertIn("It answers their newest message by itself at about 2:40 PM", text)  # the oldest reply leaves the hour
        self.assertIn("Their last words: can you show me at least the video of the sho(?", text)
        self.assertIn("Lead: 555", text)
        self.assertIn("Chat: https://", text)
        self.assertIn("/marketplace/app/76/", text)
        self.assertEqual(rows[0].title, "Reply limit reached: Ahmed Khan")

    def test_chat_91_the_capped_burst_is_answered_once_the_hour_frees(self):
        video, work, saturday = self.capped_91()
        held = LeadAiTurn.objects.get(inbound=saturday)
        self.later(39)
        self.assertEqual(caps.to_answer(timezone.now()), [])  # the cap still holds
        self.later(41)
        with patch("apps.leadai.tasks.assistant_turn.apply_async") as queued:
            tasks._answer_capped()
        queued.assert_called_once_with(args=[saturday.pk], kwargs={"requeued": True})
        self.assertEqual(caps.to_answer(timezone.now()), [])  # stamped: not again for five minutes
        reply = "No problem. I can hold a slot for you on Saturday at 11:00 AM or 5:00 PM — which is better?"
        outcome, calls = self.requeued(saturday, [shop_answer(reply, invited=True)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome.status, LeadAiTurn.Status.REPLIED)
        self.assertIsNotNone(outcome.reply_message_id)  # (a video asked for with no type in view: the types list, shop_flow)
        turn = LeadAiTurn.objects.get(inbound=saturday)
        self.assertEqual((turn.pk, turn.status), (held.pk, LeadAiTurn.Status.REPLIED))  # the same row, taken up again
        self.assertIn(caps.CAPPED_AT, turn.actions)
        # The model heard the whole burst, 41 minutes old (never "too old to answer"), and no stale alert went.
        burst = calls[0][1]["content"].split("NEW SINCE YOUR LAST REPLY (answer these):\n", 1)[1]
        for text in ("video of the sho", "at work", "saturday"):
            self.assertIn(text, burst)
        self.assertFalse(self.alerts_of("stale"))
        self.assertEqual(caps.to_answer(timezone.now() + dt.timedelta(minutes=10)), [])  # answered: nothing waits
        for message in (video, work):
            self.assertEqual(LeadAiTurn.objects.get(inbound=message).reason, engine.CAPPED_REASON)  # older messages, in the burst

    def test_chat_78_ok_to_the_slots_is_answered_after_the_cap(self):
        # Chat 78, 14:33 live: "Ok" to "3:00 PM or 3:30 PM" after six replies (reply limit reached, no booking, no to-do).
        self.replies(12, 30)
        self.ours("Thank you, got it. I can hold a slot for you today at 3:00 PM or 3:30 PM — which is better?", minutes_ago=18, turn=9100)
        ok = self.inbound("Ok", seconds_ago=30)
        outcome, calls, _, _ = self.turn(ok, [shop_answer("never asked")])
        self.assertEqual((outcome.reason, calls), (engine.CAPPED_REASON, []))
        self.later(31)
        self.assertEqual(caps.to_answer(timezone.now()), [])  # 13 replies: the second oldest leaves the hour at 14:31
        self.later(32)
        self.assertEqual(caps.to_answer(timezone.now()), [ok.pk])
        outcome, calls = self.requeued(ok, [shop_answer("Great! Which works better for you, 3:00 PM or 3:30 PM?")])
        self.assertEqual(len(calls), 1)  # an "ok" to our question is answered, as it would have been
        self.assertEqual(LeadAiTurn.objects.get(inbound=ok).status, LeadAiTurn.Status.REPLIED)

    def test_a_capped_message_someone_answered_since_is_left_alone(self):
        *_, saturday = self.capped_91()
        _outbound(self.conversation, self.matloob, Message.Kind.TEXT, "Hi Riza, Matloob here. Saturday works.", {}, created_at=minutes(5))
        self.later(41)
        self.assertEqual(caps.to_answer(timezone.now()), [])
        outcome, calls = self.requeued(saturday, [shop_answer("never")])
        self.assertEqual((outcome.reason, calls), ("answered since the reply cap held it back", []))
        self.assertEqual(LeadAiTurn.objects.get(inbound=saturday).reason, engine.CAPPED_REASON)

    def test_a_newer_message_answered_meanwhile_leaves_the_older_capped_turn(self):
        *_, saturday = self.capped_91()
        self.later(41)
        newer = self.inbound("hello?", seconds_ago=5)
        self.assertEqual(caps.to_answer(timezone.now()), [])  # the newest capped turn is not the newest message
        self.assertIsNotNone(engine._newer_inbound(saturday))
        self.assertEqual(newer.direction, Message.Direction.INBOUND)

    def test_a_stopped_or_transferred_chat_is_not_taken_up_again(self):
        *_, saturday = self.capped_91()
        self.later(41)
        self.set_state(stopped_at=timezone.now(), stop_reason="stop_all")
        self.assertEqual(caps.to_answer(timezone.now()), [])

    def test_frees_at_is_the_oldest_reply_in_the_window_plus_the_window(self):
        self.replies(12, 20)
        self.assertEqual(caps.frees_at(self.conversation, "ic_shops", NOW, "hour"), minutes(40))
        self.assertIsNone(caps.frees_at(self.conversation, "ic_shops", minutes(41), "hour"))
        self.assertEqual(caps.reached(self.conversation, "ic_shops", NOW), "hour")
        self.assertEqual(caps.reached(self.conversation, "ic_shops", minutes(41)), "")


class GeneralCapTests(GeneralBase):
    def test_a_general_chat_keeps_six_an_hour_and_its_capped_message_stays_capped(self):
        self.list_matloob()
        for index in range(engine.CAP_PER_HOUR):
            self.ours("Sure.", minutes_ago=20 - index, turn=9000 + index)
        message = self.inbound("and?", seconds_ago=20)
        outcome, calls, _, _ = self.turn(message, [answer()])
        self.assertEqual((outcome.reason, calls), (engine.CAPPED_REASON, []))
        rows = list(LeadAiAlert.objects.filter(kind="cap"))
        self.assertEqual({row.bitrix_user_id for row in rows}, {"77"})  # the chat's own people, not the list
        self.assertEqual({row.priority for row in rows}, {"normal"})
        self.assertEqual(rows[0].title, "Lead AI paused in one chat")
        self.later(60)
        self.assertEqual(caps.to_answer(timezone.now()), [])  # never taken up again in a general chat


# B. A handover nobody answered ------------------------------------------------------------------------------------


class EscalationTests(PeopleBase):
    def handed(self, minutes_ago, reason="call_requested", **fields):
        """Chat 88 at 10:35 live: handed over for a call, our line, and nobody from the team since."""
        self.inbound(CALL_WORDS_88, seconds_ago=minutes_ago * 60 + 20)
        self.ours(people.line(people.CALL_PASSED, "en", shops=True), minutes_ago=minutes_ago)
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=minutes_ago), handover_reason=reason, facts=FACTS_88, **fields)

    def test_chat_88_a_handover_nobody_answered_is_escalated_once_after_30_office_minutes(self):
        self.handed(31)
        self.assertEqual(people.escalate_waiting(NOW), 1)
        rows = self.alerts_of(people.WAITING)
        self.assertEqual(self.who_got(people.WAITING), {("agent", "77"), ("matloob", "2311")})
        self.assertEqual({row.priority for row in rows}, {"high"})
        text = rows[0].text
        self.assertIn("Abd (WhatsApp +971501234567) asked for a call.", text)
        self.assertIn("nobody from the team has written in it since (31 minutes of office time)", text)
        self.assertIn(f"Their last words: {CALL_WORDS_88}", text)
        self.assertIn("Lead: 555", text)
        self.assertEqual(rows[0].title, "Still waiting for a person: Abd")
        self.assertEqual(people.escalate_waiting(minutes(30)), 0)  # once per handover
        with patch.object(people, "escalate_waiting") as sweep:
            tasks._escalate_handovers()
        sweep.assert_called_once()

    def test_not_before_30_minutes(self):
        self.handed(29)
        self.assertEqual(people.escalate_waiting(NOW), 0)

    def test_chat_136_told_it_would_be_connected_and_nobody_came(self):
        # 10:39 live: "I will connect you to our agent who can assist you further here", then "OK", and nobody wrote.
        self.inbound("AM LOOKING FOR STUDIO APARTMENTS", seconds_ago=100 * 60 + 20)
        self.ours("We specialize in shops in International City. For studio apartments, I will connect you to our agent who can assist you further here.", minutes_ago=100)
        self.inbound("OK", seconds_ago=96 * 60)
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=100), handover_reason="unclear", facts={"customer_name": "Appu"})
        self.assertEqual(people.escalate_waiting(NOW), 1)
        text = self.alerts_of(people.WAITING)[0].text
        self.assertIn("Appu (WhatsApp +971501234567) needs a person to take over.", text)
        self.assertIn("(100 minutes of office time)", text)
        self.assertIn("Their last words: OK", text)

    def test_a_person_who_wrote_since_is_answering(self):
        self.handed(40)
        _outbound(self.conversation, self.matloob, Message.Kind.TEXT, "Hi Abd, I'll call you in 5 minutes.", {}, created_at=minutes(-5))
        self.assertEqual(people.escalate_waiting(NOW), 0)
        self.assertTrue(engine.person_wrote_since(self.conversation, NOW - dt.timedelta(minutes=40)))

    def test_only_in_office_time(self):
        # Handed over on Saturday at 19:50: 10 minutes that day, Sunday closed, 20 more on Monday from 10:00.
        saturday = dt.datetime(2026, 10, 10, 19, 50, tzinfo=DUBAI)
        self.assertEqual(people.office_minutes(saturday, dt.datetime(2026, 10, 12, 10, 19, tzinfo=DUBAI)), 29)
        self.assertEqual(people.office_minutes(saturday, dt.datetime(2026, 10, 12, 10, 20, tzinfo=DUBAI)), 30)
        self.assertFalse(people.office_open(dt.datetime(2026, 10, 12, 21, 0, tzinfo=DUBAI)))
        self.assertFalse(people.office_open(dt.datetime(2026, 10, 11, 12, 0, tzinfo=DUBAI)))  # Sunday
        self.handed(31)
        self.assertEqual(people.escalate_waiting(dt.datetime(2026, 10, 12, 20, 30, tzinfo=DUBAI)), 0)

    def test_a_handover_made_in_bitrix_or_an_agents_pause_is_not_escalated(self):
        self.handed(45, reason=bitrix_status.HANDED_REASON)
        self.assertEqual(people.escalate_waiting(NOW), 0)
        self.set_state(handover_reason="call_requested", paused_at=NOW - dt.timedelta(minutes=40), paused_by=self.agent)
        self.assertEqual(people.escalate_waiting(NOW), 0)
        self.set_state(paused_at=None, paused_by=None)
        self.assertEqual(people.escalate_waiting(NOW), 1)


class GeneralEscalationTests(GeneralBase):
    def test_a_general_chat_is_not_escalated(self):
        self.list_matloob()
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=45), handover_reason="customer_asked_human")
        self.assertEqual(people.escalate_waiting(NOW), 0)


# C. A call ----------------------------------------------------------------------------------------------------------


class CallTests(PeopleBase):
    def chat_88(self):
        self.set_state(facts=FACTS_88, invites=2)
        self.ours(SLOTS_88, minutes_ago=2)
        return self.inbound(CALL_WORDS_88, seconds_ago=30)

    def live_88(self):
        return shop_answer(
            PROMISE_88, action="tentative", place="call", date="2026-10-13", time="11:30", words=CALL_WORDS_88, handover="call_requested"
        )

    def test_chat_88_no_call_time_is_promised_and_the_team_gets_the_time(self):
        message = self.chat_88()
        outcome, _, crm_delay, note_delay = self.turn(message, [self.live_88()])
        body = self.body(outcome)
        self.assertEqual(body, people.line(people.CALL_PASSED, "en", shops=True))
        self.assertNotIn("will call you", body)
        state = self.state()
        self.assertEqual(state.handover_reason, "call_requested")
        call = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual((call.status, call.place), ("tentative", "call"))
        rows = self.alerts_of("handover")
        self.assertEqual(self.who_got("handover"), {("agent", "77"), ("matloob", "2311")})
        text = rows[0].text
        self.assertIn("Abd (WhatsApp +971501234567) asked for a call.", text)
        self.assertIn("Call asked for: Tuesday 13 October 2026, 11:30 AM", text)
        self.assertIn(f"Their words: {CALL_WORDS_88}", text)
        self.assertIn("Lead: 555", text)
        self.assertIn("The assistant promised no time", text)
        self.assertEqual({row.priority for row in rows}, {"high"})
        self.assertFalse(self.alerts_of("tentative"))  # one alert: the handover's carries the time
        note = [call for call in note_delay.call_args_list if call.args[1] == "call"]
        self.assertEqual(len(note), 1)
        self.assertIn("Call asked for: Tuesday 13 October 2026, 11:30 AM", note[0].args[2])
        crm_delay.assert_called_once()  # the tentative call's own timeline comment, as before
        self.assertEqual(self.actions(message)["people"], people.CALL_PASSED)

    def test_chat_88_without_the_guard_the_promise_went_out(self):
        message = self.chat_88()
        with patch.object(people, "settle", return_value=""):
            outcome, _, _, _ = self.turn(message, [self.live_88()])
        self.assertEqual(self.body(outcome), PROMISE_88)

    def test_a_call_asked_with_no_time_asks_which_time_suits_them(self):
        self.ours("Great. What business will the shop be for?", minutes_ago=2)
        message = self.inbound("Can someone call me please?", seconds_ago=30)
        outcome, _, _, note_delay = self.turn(message, [shop_answer("Sure, our agent will call you shortly.", handover="call_requested")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_ASK, "en", shops=True))
        self.assertIn("Call asked for: no time given yet", self.alerts_of("handover")[0].text)

    def test_a_call_asked_for_in_their_words_is_handed_over_whatever_the_model_tagged(self):
        self.ours("Great. What business will the shop be for?", minutes_ago=2)
        message = self.inbound("Please call me, I am driving", seconds_ago=30)
        outcome, _, _, _ = self.turn(message, [shop_answer("Sure! What business will the shop be for?")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_ASK, "en", shops=True))
        self.assertEqual(self.state().handover_reason, "call_requested")

    def handed_88(self):
        """Chat 88 after 10:35: handed over for the call, our line, the tentative call; 90 minutes on."""
        self.set_state(facts=FACTS_88, invites=2, handed_over_at=NOW - dt.timedelta(minutes=90), handover_reason="call_requested",
                       holding_line_at=NOW - dt.timedelta(minutes=90))
        self.inbound(CALL_WORDS_88, seconds_ago=91 * 60)
        self.ours(people.line(people.CALL_PASSED, "en", shops=True), minutes_ago=90)
        LeadAiAppointment.objects.create(
            conversation=self.conversation, status="tentative", place="call", starts_at=dt.datetime(2026, 10, 12, 13, 0, tzinfo=DUBAI),
            note=CALL_WORDS_88, customer_words=CALL_WORDS_88,
        )

    def test_chat_88_a_chase_gets_an_apology_and_an_urgent_alert_never_the_holding_line(self):
        self.handed_88()
        chase = self.inbound("will i get any call??", seconds_ago=20)
        outcome, calls, _, _ = self.turn(chase, [shop_answer("", send=False)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), people.line(people.CHASE, "en", shops=True))
        rows = self.alerts_of(people.QUIET_CHASE)
        self.assertEqual(self.who_got(people.QUIET_CHASE), {("agent", "77"), ("matloob", "2311")})
        self.assertEqual({row.priority for row in rows}, {"high"})
        self.assertIn("Abd (WhatsApp +971501234567) is still waiting for us: they asked for a call", rows[0].text)
        self.assertIn("Call asked for: Monday 12 October 2026, 1:00 PM", rows[0].text)
        self.assertIn("Their last words: will i get any call??", rows[0].text)
        self.assertEqual(self.actions(chase)["quiet"], people.QUIET_CHASE)
        # Another chase two minutes on: no second apology yet, and no second urgent alert inside CHASE_ALERT_EVERY (batch
        # 2d's review: "Hello?", "??", "anyone there?" a minute apart were three alerts to each of them).
        self.later(2)
        again = self.inbound("hello??", seconds_ago=10)
        outcome, _, _, _ = self.turn(again, [shop_answer("", send=False)])
        self.assertEqual(outcome.reason, "no reply needed")
        self.assertEqual(len({row.dedupe_key.rsplit(":", 1)[0] for row in self.alerts_of(people.QUIET_CHASE)}), 1)
        # Past it, a chase is alerted again.
        self.later(13)
        later = self.inbound("anyone there?", seconds_ago=10)
        self.turn(later, [shop_answer("", send=False)])
        self.assertEqual(len({row.dedupe_key.rsplit(":", 1)[0] for row in self.alerts_of(people.QUIET_CHASE)}), 2)

    def test_chat_88_without_the_guard_the_chase_got_the_holding_line(self):
        self.handed_88()
        chase = self.inbound("will i get any call??", seconds_ago=20)
        with patch.object(people, "quiet_reply", return_value=(people.QUIET_HOLDING, GENERAL_HOLDING)):
            outcome, _, _, _ = self.turn(chase, [shop_answer("", send=False)])
        self.assertEqual(self.body(outcome), GENERAL_HOLDING)
        self.assertFalse(self.alerts_of(people.QUIET_CHASE))

    def test_a_call_time_given_while_handed_over_is_passed_on(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=5), handover_reason="call_requested", holding_line_at=NOW - dt.timedelta(minutes=15))
        self.ours(people.line(people.CALL_ASK, "en", shops=True), minutes_ago=5)
        message = self.inbound("11:30 tomorrow is fine", seconds_ago=20)
        outcome, _, _, note_delay = self.turn(message, [shop_answer("", send=False)])
        self.assertEqual(self.body(outcome), people.line(people.CALL_PASSED, "en", shops=True))
        rows = self.alerts_of("call_time")
        self.assertIn("gave the time for the call they asked for", rows[0].text)
        self.assertIn("Their words: 11:30 tomorrow is fine", rows[0].text)
        self.assertEqual([call.args[1] for call in note_delay.call_args_list], ["call"])

    def test_an_hour_for_a_visit_while_a_call_waits_is_no_call_time(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=5), handover_reason="call_requested")
        self.ours(people.line(people.CALL_ASK, "en", shops=True), minutes_ago=5)
        message = self.inbound("I can come to the office at 5", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer("", send=False)])
        self.assertEqual(self.body(outcome), SHOPS_HOLDING)
        self.assertFalse(self.alerts_of("call_time"))

    def test_chat_57_a_goodbye_while_handed_over_gets_nothing(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=2), handover_reason="customer_asked_human")
        self.ours(SHOPS_HOLDING, minutes_ago=1)
        goodbye = self.inbound(GOODBYE_57, seconds_ago=20)
        outcome, _, _, _ = self.turn(goodbye, [shop_answer("", send=False)])
        self.assertEqual(outcome.reason, "no reply needed")
        self.assertEqual(self.actions(goodbye)["quiet"], people.QUIET_CLOSING)
        self.assertEqual(Message.objects.filter(conversation=self.conversation, direction="out", pk__gt=goodbye.pk).count(), 0)
        with patch.object(people, "quiet_reply", return_value=(people.QUIET_HOLDING, SHOPS_HOLDING)):
            again = self.inbound(GOODBYE_57, seconds_ago=5)
            outcome, _, _, _ = self.turn(again, [shop_answer("", send=False)])
        self.assertEqual(self.body(outcome), SHOPS_HOLDING)  # without the guard: the holding line, as live

    def test_chat_136_a_shops_chats_holding_line_says_our_agent(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(hours=3), handover_reason="customer_asked_human")
        message = self.inbound("Is there parking near the shops?", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer("", send=False)])
        self.assertEqual(self.body(outcome), "Our agent has your message and will reply here.")


class GeneralCallTests(GeneralBase):
    def test_a_general_chats_call_request_gets_the_specialist_line_and_no_promise(self):
        self.list_matloob()
        message = self.inbound("Please call me, I am driving", seconds_ago=30)
        outcome, _, _, _ = self.turn(message, [answer("Sure, our specialist will call you in 10 minutes.", handover="call_requested")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_ASK, "en", shops=False))
        self.assertIn("specialist", self.body(outcome))

    def test_a_general_chats_holding_line_is_as_it_was(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(hours=3), handover_reason="customer_asked_human")
        outcome, _, _, _ = self.turn(self.inbound("Is there parking?", seconds_ago=20), [answer("", send=False)])
        self.assertEqual(self.body(outcome), GENERAL_HOLDING)


# D. Must-answer questions ------------------------------------------------------------------------------------------


MUST_ANSWER_LINE = people.line(people.MUST_ANSWER, "en", shops=True)


class MustAnswerTests(PeopleBase):
    """Must-answer questions go to a person, and the chat goes on (people.MUST_ANSWER_PAUSES False; batch 2d's review:
    the handover silenced chats 91, 78 and 59 for hours)."""

    def test_chat_95_nine_questions_go_to_a_person_before_any_visit(self):
        message = self.inbound(NINE_QUESTIONS, seconds_ago=30)
        live = shop_answer(
            DEFERRED_95,
            facts={"for_client": False, "property_type": "shop", "intent": "rent", "customer_name": "Madj",
                   "business_activity": "small dessert takeaway and production kitchen",
                   "notes": ["NOC for F&B", "Dubai Municipality approval for food establishment", "total electrical load in kW",
                             "water supply and drainage inside shop", "installation of preparation and hand-wash sinks"]},
        )
        outcome, _, _, _ = self.turn(message, [live])
        body = self.body(outcome)
        # The line, and the model's own question that is no deferral; never "at the viewing".
        self.assertEqual(body, f"{MUST_ANSWER_LINE} Meanwhile, what size shop are you looking for?")
        self.assertNotIn("at the viewing", body)
        self.assertIsNone(self.state().handed_over_at)  # the chat goes on
        self.assertEqual(self.alerts_of("handover"), [])
        rows = self.alerts_of(people.QUESTIONS)
        self.assertEqual(self.who_got(people.QUESTIONS), {("agent", "77"), ("matloob", "2311")})
        self.assertEqual({row.priority for row in rows}, {"high"})
        text = rows[0].text
        self.assertIn("asked questions a person must answer before any visit", text)
        self.assertIn(
            "Questions to answer before any visit: exhaust or ventilation; grease trap; NOC; Municipality approval; drainage or water; "
            "power load; Ejari; deposit; VAT; total upfront amount", text,
        )
        self.assertIn("Their questions: Hi, I’m seriously interested", text)
        self.assertIn("9. What is the complete upfront amount", text)  # all nine, past the model's 500-character line
        self.assertIn("keeps arranging the visit meanwhile", text)
        self.assertNotIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_HANDED)), self.fields())
        actions = self.actions(message)
        self.assertEqual((actions["must_answer"][0], actions["questions_waiting"]), ("exhaust or ventilation", True))

    def test_chat_95_paused_when_matloob_says_so(self):
        message = self.inbound(NINE_QUESTIONS, seconds_ago=30)
        with patch.object(people, "MUST_ANSWER_PAUSES", True):
            outcome, _, _, _ = self.turn(message, [shop_answer(DEFERRED_95)])
        self.assertEqual(self.body(outcome), MUST_ANSWER_LINE)
        self.assertEqual(self.state().handover_reason, people.MUST_ANSWER_REASON)
        self.assertIn("Questions to answer before any visit: exhaust or ventilation", self.alerts_of("handover")[0].text)
        self.assertIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_HANDED)), self.fields())

    def test_chat_95_without_the_guard_they_went_to_the_viewing(self):
        message = self.inbound(NINE_QUESTIONS, seconds_ago=30)
        with patch.object(people, "settle", return_value=""):
            outcome, _, _, _ = self.turn(message, [shop_answer(DEFERRED_95)])
        self.assertIn("at the viewing", self.body(outcome))
        self.assertIsNone(self.state().handed_over_at)

    def test_chat_91_the_gas_line_and_chimney_and_then_the_video_he_asked_for(self):
        self.set_state(facts={"for_client": False, "property_type": "shop", "business_activity": "restaurant or cafeteria"}, invites=1)
        self.ours("The shops are spaces ready for you. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", minutes_ago=7)
        message = self.inbound("is there available gas line and chimney?", seconds_ago=20)
        live = GAS_91.replace("2:30 PM or 4:30 PM", "3:00 PM or 5:00 PM")
        outcome, _, _, _ = self.turn(message, [shop_answer(live, invited=True)])
        # The second invitation waits for his licence (engine.discovery_first), and the drive goes with it.
        self.assertEqual(self.body(outcome), f"{MUST_ANSWER_LINE} {rules.line('ask_licence', 'en')}")
        self.assertEqual(self.state().invites, 1)  # no invitation went
        self.assertIn("Questions to answer before any visit: gas line; chimney", self.alerts_of(people.QUESTIONS)[0].text)
        # Live, 21 seconds later: "can you show me at least the video of the sho[?" was capped and then never answered; now
        # the chat is his, and the video is a type's media step.
        self.later(1)
        video = self.inbound("can you show me at least the video of the sho[?", seconds_ago=5)
        self.set_state(facts={"for_client": False, "property_type": "shop", "business_activity": "restaurant or cafeteria", "shop_type": "type_2"})
        outcome, calls, _, _ = self.turn(video, [shop_answer("Sure! Here is the video.")])
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(outcome.reason, "no reply needed")
        self.assertIsNone(self.state().handed_over_at)

    def test_chat_78_the_detail_computation_keeps_the_type_1_match_for_his_33k(self):
        self.ours(
            "We have 3 shop types: Small (400-550 sq ft) from AED 33,000, Medium (600-800 sq ft) from AED 48,000, and Large "
            "(900-1,200 sq ft) from AED 80,000 per year. What size or budget do you have in mind?", minutes_ago=2,
        )
        for text, seconds in (("And can u give me the detai computation i need back area", 40), ("Parking side", 30)):
            self.inbound(text, seconds_ago=seconds)
        message = self.inbound("33k", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer(DEFERRED_78, facts={"budget_aed": 33000, "budget_basis": "per_year"})])
        body = self.body(outcome)
        self.assertIn(MUST_ANSWER_LINE, body)
        self.assertIn("400-550 sq ft, from AED 33,000 a year", body)  # live, the batch dropped it with the whole reply
        self.assertNotIn("at the viewing", body)
        self.assertTrue(body.endswith("What business will you run in the shop?"))
        self.assertIn("Questions to answer before any visit: total upfront amount", self.alerts_of(people.QUESTIONS)[0].text)
        self.assertIsNone(self.state().handed_over_at)

    def test_commission_alone_is_matloobs_own_line_not_a_handover(self):
        message = self.inbound("What is the commission?", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer("Good question — I'll have our agent confirm that for you at the viewing.")])
        self.assertIsNone(self.state().handed_over_at)
        self.assertEqual(people.must_answer(["What is the commission?"]), [])
        with patch.object(people, "MUST_ANSWER_COMMISSION", True):
            self.assertEqual(people.must_answer(["What is the commission?"]), ["commission"])

    def test_someone_who_wants_no_shop_is_not_handed_over_for_a_question(self):
        self.set_state(facts={"need": "home", "wanted": "a studio", "property_type": "studio"})
        message = self.inbound("What is the deposit for the studio?", seconds_ago=20)
        self.turn(message, [shop_answer("Our agent will go through the deposit with you at our office.", segment="residential_tenant")])
        self.assertIsNone(self.state().handed_over_at)

    def test_a_stronger_handover_keeps_its_own_words_with_the_questions_listed(self):
        message = self.inbound("Can you call me about the gas line and the chimney?", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer("Sure.", handover="call_requested")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_ASK, "en", shops=True))
        self.assertEqual(self.state().handover_reason, "call_requested")
        self.assertIn("Questions to answer before any visit: gas line; chimney", self.alerts_of("handover")[0].text)


class GeneralMustAnswerTests(GeneralBase):
    def test_a_general_chat_keeps_its_answer(self):
        message = self.inbound("Is there a gas line in the shop?", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [answer("Our specialist will confirm that with you. Would you like to visit our office?")])
        self.assertEqual(self.body(outcome), "Our specialist will confirm that with you. Would you like to visit our office?")
        self.assertIsNone(self.state().handed_over_at)


# E. A STOP as the first answer ----------------------------------------------------------------------------------------


class StopReachesTheOwnerTests(PeopleBase):
    def resolve(self, assigned="2651"):
        with patch("apps.crmlink.client.configured", return_value=True), patch(
            "apps.leadai.assistant.crm.record_for", return_value=("lead", 555, True)
        ), patch("apps.leadai.assistant.crm.read_record", return_value={"assigned": assigned, "stage": "UC_MJDO60", "fields": {}}), self.captureOnCommitCallbacks(execute=True):
            tasks.resolve_responsible(self.conversation.pk)

    def test_chat_112_a_stop_tap_as_the_first_answer_reaches_the_leads_owner_and_the_list(self):
        tap = self.tap("Stop messages", seconds_ago=20)
        with patch("apps.leadai.tasks.resolve_responsible.delay") as lookup:
            outcome, calls, _, _ = self.turn(tap, [shop_answer("never")])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), "Done, you won't receive more messages from us.")
        lookup.assert_called_once_with(self.conversation.pk)  # live, the lookup never ran: the rule returned before it
        self.assertIsNotNone(self.state().responsible_checked_at)
        self.assertEqual(self.who_got("opt_out"), {("agent", "77"), ("matloob", "2311")})
        text = self.alerts_of("opt_out")[0].text
        self.assertIn("Please do not message them again from any number.", text)
        self.assertIn("Lead: 555", text)
        # The lookup answers: lead 79466's owner (2651) hears of it too, once.
        self.resolve()
        self.assertEqual(self.who_got("opt_out"), {("agent", "77"), ("matloob", "2311"), (None, "2651")})
        self.assertEqual(self.state().responsible_bitrix_user_id, "2651")
        self.resolve()
        self.assertEqual(len(self.alerts_of("opt_out")), 3)

    def test_without_the_catch_up_the_owner_never_heard(self):
        tap = self.tap("Stop messages", seconds_ago=20)
        self.turn(tap, [shop_answer("never")])
        with patch.object(alerts, "reach_responsible", return_value=0):
            self.resolve()
        self.assertNotIn((None, "2651"), self.who_got("opt_out"))

    def test_an_alert_older_than_the_catch_up_stays_where_it_went(self):
        self.turn(self.tap("Stop messages", seconds_ago=20), [shop_answer("never")])
        LeadAiAlert.objects.update(created_at=NOW - tasks.RESPONSIBLE_CATCH_UP - dt.timedelta(minutes=1))
        self.resolve()
        self.assertNotIn((None, "2651"), self.who_got("opt_out"))

    def test_an_admin_alert_never_reaches_a_responsible(self):
        alerts.raise_alert(kind="ai_quota", conversation=self.conversation, title="x", text="y", dedupe_key="ai_quota:test", admins=True)
        self.resolve()
        self.assertEqual({row.bitrix_user_id for row in LeadAiAlert.objects.filter(kind="ai_quota")}, {""})


class GeneralStopTests(GeneralBase):
    def test_a_general_chats_stop_reaches_its_owner_then_the_responsible_not_the_list(self):
        self.list_matloob()
        self.turn(self.inbound("STOP", seconds_ago=20), [answer()])
        rows = LeadAiAlert.objects.filter(kind="opt_out")
        self.assertEqual({row.bitrix_user_id for row in rows}, {"77"})
        self.assertNotIn("Lead: 555", rows[0].text)
        Agent.objects.create_user(username="owner2651", password="x", bitrix_user_id="2651", can_official_api=True)
        with patch("apps.crmlink.client.configured", return_value=True), patch(
            "apps.leadai.assistant.crm.record_for", return_value=("lead", 555, True)
        ), patch("apps.leadai.assistant.crm.read_record", return_value={"assigned": "2651", "stage": "UC_MJDO60", "fields": {}}):
            tasks.resolve_responsible(self.conversation.pk)
        self.assertEqual({row.bitrix_user_id for row in LeadAiAlert.objects.filter(kind="opt_out")}, {"77", "2651"})


# F. Handover lines -------------------------------------------------------------------------------------------------------


class HandoverLineTests(PeopleBase):
    def test_chat_114_never_sends_the_customer_to_chase_a_colleague(self):
        self.ours("Sorry for the confusion. Is the shop for yourself, or are you checking for a client?", minutes_ago=2)
        message = self.inbound("Manhial told me already", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer(MANHIAL_114, handover="unclear", segment="other")])
        body = self.body(outcome)
        self.assertNotIn("contact Manhial", body)
        self.assertTrue(body.endswith(SHOPS_HOLDING))
        self.assertIn("colleague", self.actions(message)["trimmed"])
        with patch.object(people, "settle", return_value=""):
            again = self.inbound("Manhial told me already", seconds_ago=5)
            self.set_state(handed_over_at=None, handover_reason="")
            outcome, _, _, _ = self.turn(again, [shop_answer(MANHIAL_114, handover="unclear", segment="other")])
        self.assertIn("please contact Manhial", self.body(outcome))  # without the guard, as live

    APOLOGY = "Sorry for the confusion. A salon, got it. What size do you need?"

    def apology_turn(self):
        self.ours("Sorry for the confusion. What business will the shop be for?", minutes_ago=2)
        message = self.inbound("I told you, it is for a salon", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer(self.APOLOGY, facts={"business_activity": "salon"})])
        return self.body(outcome)

    def test_chat_114_an_apology_may_repeat(self):
        self.assertEqual(self.apology_turn(), self.APOLOGY)

    def test_chat_114_without_the_guard_the_sorry_went(self):
        with patch.object(people, "is_apology", return_value=False):
            self.assertEqual(self.apology_turn(), "A salon, got it. What size do you need?")  # as live: turn 84 "repeat"

    def test_chat_105_a_handover_reply_asks_nothing_more(self):
        message = self.inbound("I want to talk to someone about it", seconds_ago=20)
        reply = "Sure. Are you looking for a shop for a business, or something else?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, handover="customer_asked_human")])
        self.assertEqual(self.body(outcome), f"Sure. {SHOPS_HOLDING}")
        self.assertIn("handover_question", self.actions(message)["trimmed"])

    def test_a_complaints_promised_call_goes_and_the_holding_line_follows(self):
        message = self.inbound("Your agent said she would call me this morning and nobody called", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer("We're sorry about that. Our agent will call you shortly.", handover="complaint_or_upset")])
        self.assertEqual(self.body(outcome), f"We're sorry about that. {SHOPS_HOLDING}")
        self.assertEqual(self.state().handover_reason, "complaint_or_upset")

    def test_a_complaint_with_a_call_keeps_its_apology_and_the_alert_carries_the_call(self):
        message = self.inbound("Nobody called me! Call me at 5 pm", seconds_ago=20)
        live = shop_answer(
            "We're sorry about that. Our agent will call you at 5 PM.", handover="complaint_or_upset", action="tentative", place="call",
            date="2026-10-12", time="17:00", words="Nobody called me! Call me at 5 pm",
        )
        outcome, _, _, note_delay = self.turn(message, [live])
        self.assertEqual(self.body(outcome), f"We're sorry about that. {SHOPS_HOLDING}")
        self.assertEqual(self.state().handover_reason, "complaint_or_upset")
        text = self.alerts_of("handover")[0].text
        self.assertIn("is upset or complaining", text)
        self.assertIn("Call asked for: Monday 12 October 2026, 5:00 PM", text)
        self.assertEqual([call.args[1] for call in note_delay.call_args_list], ["call"])

    def test_a_reply_that_already_says_a_colleague_replies_gets_no_second_line(self):
        message = self.inbound("I want to talk to a person", seconds_ago=20)
        reply = "Sure. Our agent will reply to you here. You can contact him for more details."
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, handover="customer_asked_human")])
        self.assertEqual(self.body(outcome), "Sure. Our agent will reply to you here.")


# Reading the customer and our reply (pure) ------------------------------------------------------------------------------


class ReadingTests(SimpleTestCase):
    def test_must_answer_reads_the_launch_questions(self):
        self.assertEqual(
            people.must_answer([NINE_QUESTIONS]),
            ["exhaust or ventilation", "grease trap", "NOC", "Municipality approval", "drainage or water", "power load", "Ejari",
             "deposit", "VAT", "total upfront amount"],
        )
        self.assertEqual(people.must_answer(["is there available gas line and chimney?"]), ["gas line", "chimney"])
        self.assertEqual(people.must_answer(["And can u give me the detai computation i need back area"]), ["total upfront amount"])
        for text, topics in (
            ("Kya gas line hai?", ["gas line"]), ("هل يوجد خط غاز؟", ["gas line"]), ("How much total I have to pay upfront?", ["total upfront amount"]),
            ("Can I get rent free period for fit out?", ["fit-out period"]), ("how long is the contract?", ["contract"]), ("Is VAT included in the rent?", ["VAT"]),
            ("How much is the deposit?", ["deposit"]), ("Do you have exhaust?", ["exhaust or ventilation"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(people.must_answer([text]), topics)

    def test_a_shop_customers_ordinary_words_are_no_must_answer_question(self):
        for text in (
            "I had a gas station before", "What is the rent?", "Is DEWA included?", "I want a 1 year contract", "What about the commission?",
            "share me the prices and spaces so i  could decide", "can you show me at least the video of the sho[?", "are they an existing restaurant?",
            "i want to know the location", "Is there parking?", "Parking side", "33k", "Is the shop on the road side?", "What size do you have?",
            "Can I see the shop tomorrow?", "Is the rent yearly?", "How many cheques?", "Mobile phone shop", "I need 400 sq ft",
        ):
            with self.subTest(text=text):
                self.assertEqual(people.must_answer([text]), [])

    def test_closings(self):
        for text in (GOODBYE_57, "ok thank you so much", "Thanks a lot sir", "ok bye", "thank you, have a nice day", "No problem, thank you",
                     "shukriya bhai", "شكرا جزيلا", "ok will wait", "no thanks", "Alright thank you sir", "JazakAllah khair"):
            with self.subTest(text=text):
                self.assertTrue(people.is_closing(text))
        for text in ("I will wait", "ok thanks, call me at 5", "Thank you. When will you call?", "ok", "thank you but I need a bigger shop",
                     "will i get any call??", "Thanks, what is the rent?"):
            with self.subTest(text=text):
                self.assertFalse(people.is_closing(text))

    def test_chases(self):
        for text in ("will i get any call??", "no one called", "nobody called me yet", "still waiting", "any update?", "hello?", "??",
                     "anyone there?", "when will you call", "you said you will call", "no call yet", "i am waiting for your call",
                     "koi call nahi aya", "abhi tak call nahi aaya", "ما احد اتصل", "ابھی تک کال نہیں آئی"):
            with self.subTest(text=text):
                self.assertTrue(people.is_chase(text))
        for text in ("Is there parking near the shops?", "ok thank you", "Hi, I want a shop", "When can I see the shop?", "What is the rent?", "hi",
                     GOODBYE_57, "11:30 tomorrow is fine", CALL_WORDS_88, "will you call me?"):
            with self.subTest(text=text):
                self.assertFalse(people.is_chase(text))

    def test_call_requests(self):
        for text in (CALL_WORDS_88, "Please call me, I am driving", "call me at 5", "Can you call me?", "give me a call", "mujhe call karo",
                     "call kar lo", "اتصل بي", "کال کریں", "I prefer a call"):
            with self.subTest(text=text):
                self.assertTrue(people.asks_for_call(text))
        for text in ("don't call me", "Do not call me, only WhatsApp", "I will call you later", "Can I call your office?", "will i get any call??",
                     "Send me the video"):
            with self.subTest(text=text):
                self.assertFalse(people.asks_for_call(text))

    def test_our_promises_and_chases_of_a_colleague(self):
        for sentence in (PROMISE_88, "We'll call you shortly.", "Our agent will give you a call.", "You will receive a call soon.",
                         "Hamare agent aap ko call karenge.", "سيتصل بك وكيلنا."):
            with self.subTest(sentence=sentence):
                self.assertTrue(people.promises_call(sentence))
        for sentence in ("Our agent will reply to you here.", "Our agent will guide you through the process.", "Our agent will drive you to the shops and back.",
                         *(people.line(kind, "en", shops=True) for kind in people.KINDS)):
            with self.subTest(sentence=sentence):
                self.assertFalse(people.promises_call(sentence))
        for sentence in ("For apartments, please contact Manhial as you mentioned.", "You can reach our agent directly.", "Kindly call our office.",
                         "You can contact him for more details.", "Feel free to message Ahmed.", "Aap Manhial se rabta karein."):
            with self.subTest(sentence=sentence):
                self.assertTrue(people.sends_to_colleague(sentence))
        for sentence in ("Please contact us here anytime.", "Our agent will contact you.", "Please visit our office.", "Please let me know.",
                         rules.line("licence_copy", "en"), "You can ask our agent at the viewing."):
            with self.subTest(sentence=sentence):
                self.assertFalse(people.sends_to_colleague(sentence))

    def test_every_line_in_six_languages_and_the_shops_words(self):
        for kind in people.KINDS:
            for shops_chat in (True, False):
                for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
                    with self.subTest(kind=kind, shops=shops_chat, language=language):
                        text = people.line(kind, language, shops=shops_chat)
                        self.assertTrue(text)
                        if language == "en" and shops_chat:
                            self.assertNotIn("specialist", text)
        self.assertEqual(people.line(people.HOLDING, "en", shops=False), GENERAL_HOLDING)
        self.assertEqual(people.converted_line("let_me_know", "en", shops=True), rules.line("let_me_know", "en"))


# G. The eval's scenarios, with the live answers -------------------------------------------------------------------------


class EvalTests(TestCase):
    def scenario(self, scenario_id):
        return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)

    def test_the_live_answers_pass_and_fail_without_the_guards(self):
        live = {
            "shops-call-time-88": eval_answer(
                PROMISE_88, action="tentative", place="call", date="2026-10-15", time="11:30", words=CALL_WORDS_88, handover="call_requested"
            ),
            "shops-call-chase-88": eval_answer("", send=False),
            "shops-goodbye-57": eval_answer("", send=False),
            "shops-must-answer-95": eval_answer(DEFERRED_95, facts={"business_activity": "small dessert takeaway and production kitchen"}),
            "shops-gas-chimney-91": eval_answer(GAS_91, invited=True),
            "shops-computation-78": eval_answer(DEFERRED_78, facts={"budget_aed": 33000, "budget_basis": "per_year"}),
        }
        for scenario_id, completion in live.items():
            with self.subTest(scenario_id):
                run, calls = run_scenario(self.scenario(scenario_id), completion)
                self.assertEqual((run.failures, calls), ([], 1))
                with patch.object(people, "settle", return_value=""), patch.object(
                    people, "quiet_reply", return_value=(people.QUIET_HOLDING, GENERAL_HOLDING)
                ):
                    run, _ = run_scenario(self.scenario(scenario_id), completion)
                self.assertTrue(run.failures)
