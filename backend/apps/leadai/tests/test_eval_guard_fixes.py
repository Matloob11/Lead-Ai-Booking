"""The review of batch 2a's eval-gate guards (test_eval_guards), each mirrored by leadai_eval:

- F1. a chat a person has keeps its handover behaviour: the booking texts, else the
  holding line, never code's two free slots (engine._run_claimed);
- F2. a deferral said with a day or an hour needs a real deferral phrase: a bare
  "later" puts nothing off ("Today later at 5 pm" is a booking request;
  rules.is_dated_deferral, rules.mentions_deferral);
- F3. code offers the free slots around a taken tentative only where it would book the
  visit itself: an office visit, nothing handed to a person, no call
  (engine.taken_tentative, and a correction in engine.ask_model);
- F6. "Tomorrow 5": a bare hour right after today or tomorrow, ending the message, is
  read the way the prompt reads one (hours.named_times);
- F7. the licence question does not carry the location the trimmed invitation asked
  for (engine.licence_first);
- F10. the shops spam rule leaves an open visit and a lead in discovery to the model
  (engine.shops_rule);
- and the way asked in other words: "How do I come?", "Which way to your office?"
  (filters.asks_the_way).

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.inbox.models import Contact, Conversation
from apps.leadai import lane
from apps.leadai.assistant import engine, filters, hours, people, prompt, rules
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAppointment
from apps.leadai.tests.test_assistant import NOW, TUESDAY_5PM, answer
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_eval_guards import POINTER, SPAM, TAKEN_LINE, VAPE_INVITE, VAPE_KNOWN, VAPE_LICENCE, normal, scenario
from apps.leadai.tests.test_first_chat_fixes import ADDRESS, INVITATION, FirstChatBase
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, at, shop_answer

HOLDING = rules.line("holding", "en")
# A shops chat's own holding line, "our agent" as every shops line says (launch review issue 21; people.py).
SHOPS_HOLDING = people.line(people.HOLDING, "en", shops=True)
ASK_TIME = rules.line("ask_time", "en")
HANDED_OVER = {"handed_over_at": NOW - dt.timedelta(hours=1), "handover_reason": "customer_asked_human"}
ASKED_BUSINESS_ONLY = [("campaign", "Hi Sumon, A7 Real Estate here."), ("assistant", "Got it. What business will the shop be for?")]


def run_scenario(item, *completions):
    """leadai_eval.run_once on this scenario with these model answers; (run, the number of model calls)."""
    calls = []

    def model(messages, schema_, **kwargs):
        calls.append(messages)
        return completions[min(len(calls) - 1, len(completions) - 1)]

    with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
        run = leadai_eval.run_once(item, item.id)
    return run, len(calls)


def other_visit(number, start=TUESDAY_5PM, wa_id="971509994444"):
    """Another chat's confirmed office visit: its slot is taken."""
    contact = Contact.objects.create(wa_id=wa_id)
    conversation = Conversation.objects.create(number=number, contact=contact)
    return LeadAiAppointment.objects.create(conversation=conversation, status="confirmed", place="office", starts_at=start)


# F1. A person has the chat ---------------------------------------------------------------------------------


class HandedOverTakenTurnTests(ShopsBase):
    """Handed to a person an hour ago, and nobody from our team wrote since: the slot another
    client has is never offered around by code, as it was not before batch 2a."""

    def setUp(self):
        super().setUp()
        other_visit(self.number)
        self.set_state(facts={"for_client": False}, **HANDED_OVER)

    def test_a_tentative_at_another_clients_time_gets_the_holding_line(self):
        message = self.inbound("Tomorrow at 5 pm is better for me")
        outcome, calls, _, _ = self.turn(message, [shop_answer("", send=False, action="tentative", date="2026-10-13", time="17:00")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), SHOPS_HOLDING)
        self.assertNotIn("fallback", self.actions(message))
        self.assertEqual(self.state().holding_line_at, NOW)
        mine = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual((mine.status, mine.starts_at), ("tentative", None))  # their words, never the taken time

    def test_a_correction_offering_other_times_gets_the_holding_line(self):
        message = self.inbound("Tomorrow at 5 pm")
        confirm = shop_answer("", action="confirm", place="office", date="2026-10-13", time="17:00")
        outcome, calls, _, _ = self.turn(message, [confirm, shop_answer("Sorry, 5 PM is taken. Would 11 AM or 6 PM work?")])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.body(outcome), SHOPS_HOLDING)

    def test_refused_twice_it_keeps_the_line_it_had_before(self):
        # Before batch 2a, a chat a person has got "Which day and exact time suit you?" here too.
        message = self.inbound("Tomorrow at 5 pm")
        confirm = shop_answer("", action="confirm", place="office", date="2026-10-13", time="17:00")
        outcome, calls, _, _ = self.turn(message, [confirm, confirm])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.body(outcome), ASK_TIME)
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation).exists())


class HandedOverTakenGeneralTurnTests(GeneralBase):
    def test_every_playbook(self):
        other_visit(self.number)
        self.set_state(**HANDED_OVER)
        message = self.inbound("Tomorrow at 5 pm is better for me")
        outcome, calls, _, _ = self.turn(message, [answer("", send=False, action="tentative", date="2026-10-13", time="17:00")])
        self.assertEqual((len(calls), self.body(outcome)), (1, HOLDING))


class HandedOverTakenEvalTests(TestCase):
    def test_the_eval_mirrors_it(self):
        handed = replace(scenario("shops-taken"), handed_over="yes (customer_asked_human)")
        run, calls = run_scenario(handed, eval_answer("", send=False, action="tentative", date="2026-10-13", time="17:00"))
        self.assertEqual((calls, run.out_by, run.out), (1, leadai_eval.CODE, SHOPS_HOLDING))
        confirm = eval_answer("", action="confirm", place="office", date="2026-10-13", time="17:00")
        run, calls = run_scenario(handed, confirm, eval_answer("Sorry, that one is taken. Would 11:00 AM or 6:00 PM work?"))
        self.assertEqual((calls, run.out), (2, SHOPS_HOLDING))
        run, calls = run_scenario(handed, confirm, confirm)
        self.assertEqual((calls, run.still_invalid, run.out), (2, True, ASK_TIME))


# F2. A bare "later" puts nothing off ----------------------------------------------------------------------


class LaterTests(SimpleTestCase):
    def test_a_day_or_an_hour_with_only_later_is_no_deferral(self):
        for text in ("Today later at 5 pm", "Tomorrow evening, later", "Tomorrow 5 pm later", "later today at 5 pm", "ok later, tomorrow at 5"):
            with self.subTest(text=text):
                self.assertFalse(rules.is_dated_deferral(text))
                self.assertFalse(rules.mentions_deferral(text))
        self.assertEqual(engine.deferral(["Today later at 5 pm"], invites=1), "")

    def test_a_real_deferral_phrase_still_is_one(self):
        for text in (
            "Tomorrow at 5 pm, I will let you know later", "Tomorrow 5pm I'll text u", "Tomorrow at 5, will inform you",
            "kal 5 baje batata hun", "Saturday morning, I'll call you", "Tomorrow at 5 pm, I will contact you",
            "Tomorrow at 5 pm, I will massage you",
        ):
            with self.subTest(text=text):
                self.assertTrue(rules.is_dated_deferral(text))
                self.assertTrue(rules.mentions_deferral(text))
        # Alone, with no day or hour, "later" is still the plain deferral rule's, as before batch 2a.
        self.assertTrue(rules.is_deferral("later"))

    def test_nor_does_it_stop_the_exact_time_upgrade(self):
        today = normal(answer("Noted.", action="tentative", place="office", date="2026-10-12", time="17:00"))
        self.assertEqual(engine.upgrade_exact_time(today, "Today later at 5 pm", None, NOW), at(12, 17))
        tuesday = normal(answer("Noted.", action="tentative", place="office", date="2026-10-13", time="17:00"))
        self.assertEqual(engine.upgrade_exact_time(tuesday, "I will come tomorrow at 5 pm, see you later", None, NOW), TUESDAY_5PM)
        # A real deferral phrase still stops it.
        again = normal(answer("Noted.", action="tentative", place="office", date="2026-10-13", time="17:00"))
        self.assertIsNone(engine.upgrade_exact_time(again, "Tomorrow at 5 pm, I will let you know later", None, NOW))

    def test_the_eval_asks_the_model_as_live(self):
        self.assertIsNone(leadai_eval.code_first(replace(scenario("defer-with-time"), new=["Today later at 5 pm"])))
        self.assertEqual(leadai_eval.code_first(scenario("defer-with-time"))["converted"], "let_me_know")


class LaterTurnTests(FirstChatBase):
    def test_today_later_at_5_pm_is_booked_not_put_off(self):
        self.ours(INVITATION, minutes_ago=10)
        self.set_state(invites=1)
        message = self.inbound("Today later at 5 pm")
        outcome, calls, crm_delay, _ = self.turn(message, [answer("", action="confirm", place="office", date="2026-10-12", time="17:00")])
        self.assertEqual(len(calls), 1)
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.starts_at), ("confirmed", at(12, 17)))
        self.assertNotIn("rule", self.actions(message))
        crm_delay.assert_called_once()


# F3. Code offers the slots only where it would book the visit itself ----------------------------------------


class TakenTentativeExclusionsTests(SimpleTestCase):
    def tentative(self, said="Tomorrow at 5 pm is better for me", **extra):
        completion = answer("Noted.", action="tentative", place=extra.pop("place", "office"), date="2026-10-13", time="17:00", **extra)
        return engine.taken_tentative(normal(completion), None, NOW, (), [TUESDAY_5PM], said)

    def test_never_where_code_would_not_book_it(self):
        cases = {
            "an owner's time with no place": {"place": None, "segment": "owner"},
            "a handover in this answer": {"handover": "customer_asked_human"},
            "a call": {"said": "Call me tomorrow at 5 pm"},
            "a call in other words": {"said": "Tomorrow at 5 pm, please phone me"},
            "a viewing at their property": {"place": "customer_property", "segment": "owner"},
            "a call as the place": {"place": "call"},
            "someone outside our segments": {"segment": "other"},
        }
        for name, extra in cases.items():
            with self.subTest(name):
                self.assertEqual(self.tentative(**extra), [])

    def test_an_office_visit_is_still_offered_around(self):
        # The model's tentatives in eval shops-taken named no place at all (every recorded run).
        for extra in ({}, {"place": None}, {"place": "office", "segment": "owner"}):
            with self.subTest(**extra):
                self.assertEqual(self.tentative(**extra), [at(13, 16, 30), at(13, 17, 30)])

    def test_a_correction_that_hands_over_keeps_its_own_words(self):
        codes, alternatives, calls = [], [], []
        completions = (
            answer("", action="confirm", place="office", date="2026-10-13", time="17:00"),
            answer("Sorry, that time is taken. Our specialist will call you to agree another.", handover="call_requested"),
        )

        def model(messages, schema_, **kwargs):
            calls.append(messages)
            return completions[min(len(calls) - 1, 1)]

        with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
            out, when, _, _, invalid = engine.ask_model(
                prompt.SYSTEM, "context", None, NOW, (), codes=codes, taken=[TUESDAY_5PM], alternatives=alternatives, said="Tomorrow at 5 pm"
            )
        self.assertEqual((when, invalid, codes, len(calls)), (None, False, ["taken"], 2))
        self.assertNotIn("slot_taken", out)


# F6. "Tomorrow 5" ----------------------------------------------------------------------------------------------


class DayHourTests(SimpleTestCase):
    def test_a_bare_hour_right_after_today_or_tomorrow(self):
        cases = {
            "Tomorrow 5": {dt.time(17, 0)},
            "tomorrow 5.": {dt.time(17, 0)},
            "Ok, today 4": {dt.time(16, 0)},
            "Can I come tomorrow 3?": {dt.time(15, 0)},
            "kal 5": {dt.time(17, 0)},
            "aaj 6 👍": {dt.time(18, 0)},
            "Tomorrow 12": {dt.time(12, 0)},
            "tomorrow, 10": {dt.time(10, 0)},
            "day after tomorrow 11": {dt.time(11, 0)},
            "بكرة ٥": {dt.time(17, 0)},
            "غداً 7": {dt.time(19, 0)},
        }
        for text, times in cases.items():
            with self.subTest(text=text):
                self.assertEqual(hours.named_times(text), times)

    def test_nothing_else_is_read_as_one(self):
        for text in (
            "Tomorrow 8", "Tomorrow 9", "Tomorrow 15", "tomorrow 50",  # 8 and 9 are anyone's guess; no bare 24-hour hour
            "Tomorrow 5 or 6", "Tomorrow 5, 6 or 7", "Tomorrow 5-6",  # a choice or a range
            "Tomorrow 2 people will come", "Tomorrow 5 ok",  # more words after it
            "Tomorrow 5/11", "Monday 12", "Saturday 2",  # a date, or what may be a weekday's date
            "tonight 10", "tomorrow morning 5",  # 10 PM; 5 in the morning
            "Tomorrow", "5",
        ):
            with self.subTest(text=text):
                self.assertEqual(hours.named_times(text), set())

    def test_taken_tentative_and_the_upgrade_read_it_too(self):
        tentative = answer("Noted.", action="tentative", place="office", date="2026-10-13", time="17:00")
        self.assertEqual(engine.taken_tentative(normal(tentative), None, NOW, (), [TUESDAY_5PM], "Tomorrow 5"), [at(13, 16, 30), at(13, 17, 30)])
        # As the prompt reads a bare 5, "Tomorrow 5" left tentative is the customer's own exact time (board T18) ...
        self.assertEqual(engine.upgrade_exact_time(normal(tentative), "Tomorrow 5", None, NOW), TUESDAY_5PM)
        # ... and a choice still is not.
        self.assertIsNone(engine.upgrade_exact_time(normal(tentative), "Tomorrow 5 or 6", None, NOW))


class DayHourTurnTests(ShopsBase):
    def test_tomorrow_5_at_another_clients_time_gets_the_two_nearest_free(self):
        other_visit(self.number)
        self.set_state(facts={"for_client": False})
        message = self.inbound("Tomorrow 5")
        wrong = shop_answer("Tomorrow at 5 PM works. Shall I hold it for you?", action="tentative", date="2026-10-13", time="17:00")
        outcome, calls, _, _ = self.turn(message, [wrong])
        self.assertEqual((len(calls), self.body(outcome)), (1, TAKEN_LINE))


# F7. The licence question carries no location ---------------------------------------------------------------


class LicenceFirstLocationTests(SimpleTestCase):
    def settle(self, said):
        out = normal(shop_answer(VAPE_INVITE, invited=True, share_location=True, facts={"business_activity": "vape"}), True)
        return engine.settle(out, ASKED_BUSINESS_ONLY, [said], 0, playbook=lane.IC_SHOPS, now=NOW, facts=VAPE_KNOWN)

    def test_the_trimmed_invitation_takes_its_location_with_it(self):
        out = self.settle("I have vape 💨 business.")
        self.assertEqual((out["reply"], out["trimmed"], out["share_office_location"]), (VAPE_LICENCE, ["licence_first"], False))

    def test_asked_for_the_location_it_still_goes(self):
        out = self.settle("Vape business, send location")
        self.assertNotIn("licence_first", out.get("trimmed", []))
        self.assertTrue(out["share_office_location"])


class LicenceFirstLocationTurnTests(ShopsBase):
    def test_the_licence_question_goes_without_the_address(self):
        self.set_state(facts=dict(VAPE_KNOWN))
        self.ours("Got it. What business will the shop be for?", minutes_ago=5)
        message = self.inbound("I have vape 💨 business.")
        outcome, calls, _, _ = self.turn(message, [shop_answer(VAPE_INVITE, invited=True, share_location=True, facts={"business_activity": "vape"})])
        self.assertEqual((len(calls), self.body(outcome)), (1, VAPE_LICENCE))
        actions = self.actions(message)
        self.assertEqual((actions["trimmed"], actions["share_office_location"]), (["licence_first"], False))
        self.assertNotIn("location_appended", actions)


class LicenceFirstLocationEvalTests(TestCase):
    def test_the_eval_sends_no_address_either(self):
        item = scenario("shops-35283")
        no_address = replace(item, chat=[*item.chat[:-1], ("assistant", "Got it. What business will the shop be for?")])
        run, calls = run_scenario(no_address, eval_answer(VAPE_INVITE, invited=True, share_location=True, facts={"business_activity": "vape"}))
        self.assertEqual((calls, run.location_sent, run.out), (1, False, VAPE_LICENCE))


# F10. The spam rule leaves an open visit and a lead in discovery to the model --------------------------------


class SpamRuleContextTests(SimpleTestCase):
    def test_an_open_visit_or_two_discovery_facts_are_the_models(self):
        self.assertEqual(engine.shops_rule(SPAM, meeting_open=True), "")
        for facts in (
            {"business_activity": "vape", "size_sqft": 450},
            {"budget_aed": 35000, "licence_kind": "ded"},
            {"size_sqft": 450, "trade_licence": "yes"},
        ):
            with self.subTest(facts=facts):
                self.assertEqual(engine.shops_rule(SPAM, facts=facts), "")

    def test_otherwise_it_is_still_codes(self):
        for facts in (
            None, {}, {"business_activity": "vape"}, {"for_client": False, "property_type": "shop", "customer_name": "Sumon"},
            {"licence_kind": "ded", "trade_licence": "yes"},  # one fact: the licence
        ):
            with self.subTest(facts=facts):
                self.assertEqual(engine.shops_rule(SPAM, facts=facts), engine.SPAM_RULE)

    def test_the_eval_leaves_them_to_the_model_too(self):
        item = scenario("shops-spam")
        self.assertIsNone(leadai_eval.code_first(replace(item, facts={"business_activity": "vape", "size_sqft": 450})))
        self.assertIsNone(leadai_eval.code_first(replace(item, appointment={"status": "confirmed", "starts_at": at(13, 17)})))
        self.assertEqual(leadai_eval.code_first(item)["rule"], engine.SPAM_RULE)


class SpamRuleContextTurnTests(ShopsBase):
    def test_spam_words_with_a_viewing_booked_go_to_the_model(self):
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=TUESDAY_5PM)
        _, calls, _, _ = self.turn(self.inbound(SPAM), [shop_answer("", send=False)])
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.state().stopped_at)

    def test_spam_words_from_a_lead_in_discovery_go_to_the_model(self):
        self.set_state(facts={**VAPE_KNOWN, "business_activity": "vape"})
        _, calls, _, _ = self.turn(self.inbound(SPAM), [shop_answer("", send=False)])
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.state().stopped_at)


# The way asked in other words --------------------------------------------------------------------------------


class AsksTheWayParaphraseTests(SimpleTestCase):
    def test_how_do_i_come_and_which_way(self):
        for text in (
            "How do I come?", "how can i come", "How should we come, by metro?", "how to come?",
            "Which way to your office?", "Which way is your office", "which way to the office?", "Which way to you?",
        ):
            with self.subTest(text=text):
                self.assertTrue(filters.asks_the_way(text))

    def test_not_other_questions(self):
        # "Where is it?" stays out: "it" may be the shop or the unit we just described, not our office.
        for text in (
            "Which way is better, cash or cheques?", "Which way do you prefer?", "How do I come up with the deposit?",
            "How do I come in for the licence?", "How did you come to know me?", "Where is it?", "Where is the shop?",
            "Which way is your shop facing?", "Which way for you is better, cash or cheque?",
            "How should I come, with my partner or alone?",
        ):
            with self.subTest(text=text):
                self.assertFalse(filters.asks_the_way(text))


class AsksTheWayParaphraseTurnTests(FirstChatBase):
    def test_how_do_i_come_gets_the_pointer(self):
        self.ours(f"Our office is here:\n{ADDRESS}", minutes_ago=5)
        outcome, _, _, _ = self.turn(self.inbound("How do I come?"), [answer("Would 11 AM or 5 PM tomorrow work for you?")])
        self.assertEqual(self.body(outcome), f"{POINTER} Would 11 AM or 5 PM tomorrow work for you?")


class AsksTheWayParaphraseEvalTests(TestCase):
    def test_location_again_in_other_words(self):
        for said in ("How do I come?", "Which way to your office?"):
            with self.subTest(said=said):
                item = replace(scenario("location-again"), new=[said])
                run, _ = run_scenario(item, eval_answer("Would you like to visit us tomorrow at 10 AM, 2 PM or 5 PM?"))
                self.assertEqual(run.failures, [])
                self.assertTrue(run.out.startswith(POINTER))
