"""The launch gate's review (2026-10-16): what batch 2d's gate fixes misread, held with the reviewer's own words.

Each fix is proved with the words that went wrong and fails with it switched off:

- A. engine.own_time replaces only the model's confirm, at an hour said as one ("Tomorrow slot 2" is none), never the hour
  work ends or a flight lands (hours.no_promise, upgrade_exact_time too), nor a time of ours they took (their_time);
- B. needs.wants_another: "Sorry, I already rented another shop" and "we don't need another one" want no shop of ours;
  "one more please", with no verb of wanting, still does;
- C. engine.settle_handover keeps the "unclear" of a "Who is this?" reply that says a colleague will reply, and after two
  invitations; the eval fails such a promise with nothing handed over;
- D. claims: the hourly claim in its other words, and a reply it empties gets code's slots from their hour (hourly_slots);
  the launch gate's proof that the owner's line never goes over code's slots, held with hourly_slots off;
- E. engine.location_invitation: only words that ask where we are ("Location of the shops?" does), never with a plan of
  their own, another area or the distance;
- F. the old lead's CRM notes: their budget is never kept as theirs nor said back a turn later; the eval counts a cut quote;
- G. engine.nudge_yes asks about the morning nudge's own two slots again;
- H. the eval: what code decides counts as code's, the shops-gate-* scenarios, the place check's landmarks.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai; the chat is lead 555's.
"""

import contextlib
import datetime as dt
import json
import re
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.leadai import lane
from apps.leadai.assistant import claims, crm_facts, engine, hours, lead_history, needs, nudges, offers, people, rules, schema, shops
from apps.leadai.assistant import residential
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import DEFAULT_OFFICE_ADDRESS as ADDRESS
from apps.leadai.models import LeadAiAlert, LeadAiAppointment
from apps.leadai.tests.test_assistant import NOW, answer
from apps.leadai.tests.test_eval_command import RIGHT, booked
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_launch_gate import NEVER, OLD_NOTES, ON_THE_HOUR, STUDIO_FACTS, run_eval, scenario
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, shop_answer

DUBAI = hours.DUBAI
OFFER_11_OR_1 = leadai_eval.TOMORROW_11_OR_1[-1][1]
OFFER_5_OR_7 = leadai_eval.TOMORROW_5_OR_7[-1][1]
OFFER_3_OR_5 = leadai_eval.TODAY_3_OR_5[-1][1]
SHOP_FACTS = dict(leadai_eval.LICENCE_KNOWN)


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=DUBAI)


# A. Their own time ---------------------------------------------------------------------------------------------------

AFTER_WORK = "Tomorrow I finish work at 6, I can come after that"
DUTY = "Tomorrow my duty finishes at 5 pm, then I will come"
FLIGHT = "Tomorrow my flight lands at 3 pm, I'll come after"


def gate_own_time(answer_, when, appointment, now, closed_dates=(), *, taken=(), said="", grounding=None, handed_over=False, agent_last=False, **_):
    """engine.own_time as the gate's fix had it: the model's confirm or tentative, a bare number read as an hour
    (hours.said_times), no time of ours they took read."""
    proposal = answer_["appointment"]
    if proposal["action"] not in ("confirm", "tentative") or proposal.get("place") not in (None, "office"):
        return None
    if handed_over or agent_last or answer_.get("slot_taken") or not engine._code_may_act(answer_, said):
        return None
    if appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED:
        return None
    model_start = when
    if model_start is None:
        day, clock = hours.parse_date(proposal.get("date")), hours.parse_time(proposal.get("time"))
        if day is None or clock is None:
            return None
        model_start = dt.datetime.combine(day, clock, tzinfo=DUBAI)
    if hours.no_promise(said) or rules.mentions_deferral(said):
        return None
    named = hours.named_days(said, now)
    days = {day for day in named if day - dt.timedelta(days=7) not in named}
    times = hours.said_times(said)
    if len(days) != 1 or len(times) != 1:
        return None
    day, clock = next(iter(days)), next(iter(times))
    if dt.datetime.combine(day, clock, tzinfo=DUBAI) == model_start:
        return None
    theirs = {**proposal, "action": "confirm", "place": "office", "date": f"{day:%Y-%m-%d}", "time": f"{clock:%H:%M}"}
    try:
        start = engine.check_proposal(theirs, appointment, now, closed_dates, grounding=grounding, segment=answer_["segment"], taken=taken, said=said)
    except hours.SlotError:
        return None
    if start is None:
        return None
    answer_["appointment"] = theirs
    answer_["own_time"] = {"start": start, "model": model_start}
    return start


@contextlib.contextmanager
def own_time_as_the_gate_had_it():
    """The gate's own_time, and no_promise without the hour of another event."""
    with patch.object(engine, "own_time", side_effect=gate_own_time), patch.object(hours, "another_event", return_value=False):
        yield


class OwnTimeReviewTests(SimpleTestCase):
    def own(self, said, *, action="confirm", date="2026-10-13", time="13:00", **kwargs):
        proposal = {"action": action, "place": "office", "date": date, "time": time}
        reply = {"language": "en", "segment": "commercial_tenant", "send": True, "reply": "Done.", "appointment": proposal}
        answer_ = schema.normalize(reply, shops=True)
        when = dt.datetime.combine(hours.parse_date(date), hours.parse_time(time), tzinfo=DUBAI) if action == "confirm" else None
        return engine.own_time(answer_, when, None, NOW, said=said, **kwargs), answer_

    def test_a_number_that_is_no_hour_books_nothing(self):
        for said, time in (
            ("Tomorrow slot 2", "13:00"), ("Tomorrow slot 1", "11:00"), ("Tomorrow, the first one. I will bring 2 friends", "11:00"),
            ("Tomorrow. I am in Al Nahda 2", "17:00"), ("Tomorrow is fine, we are 2", "17:00"),
        ):
            with self.subTest(said):
                self.assertEqual(hours.spoken_times(said), set())
                self.assertIsNone(self.own(said, time=time)[0])
        self.assertIsNone(self.own("Saturday slot 1 please", date="2026-10-17", time="11:00")[0])
        with patch.object(hours, "spoken_times", hours.said_times):
            self.assertEqual(self.own("Tomorrow slot 2")[0], at(13, 14))  # the gate's fix: "2" read as 2:00 PM

    def test_the_hour_of_another_event_is_none_of_the_visit(self):
        for said, time in ((AFTER_WORK, "19:00"), (FLIGHT, "17:00"), (DUTY, "17:30")):
            with self.subTest(said):
                self.assertTrue(hours.another_event(said))
                self.assertTrue(hours.no_promise(said))
                self.assertIsNone(self.own(said, time=time)[0])
        self.assertTrue(hours.another_event("I have a meeting at 3 pm, after that I can come"))
        self.assertTrue(hours.another_event("Kal 5 baje duty khatam hogi, phir aaunga"))
        for said in (
            "Tomorrow is my day off, I will come at 5 pm", "Ok then I will come tomorrow at 5 pm", "Not a problem, Wednesday at 5 pm then",
            "I have a meeting, after that I can come tomorrow at 6 pm", "4:30 PM today is fine", "Interior landscape, tomorrow at 5 pm",
        ):
            with self.subTest(still_the_visits_hour=said):
                self.assertFalse(hours.another_event(said))
        with patch.object(hours, "another_event", return_value=False):
            self.assertEqual(self.own(AFTER_WORK, time="19:00")[0], at(13, 18))  # the gate's fix: 6:00 PM, when work ends

    def test_t18_never_books_the_hour_of_another_event(self):
        def tentative():
            return schema.normalize(answer("Noted.", action="tentative", place="office", date="2026-10-13", time="17:00").data, shops=True)

        self.assertIsNone(engine.upgrade_exact_time(tentative(), DUTY, None, NOW))
        self.assertEqual(engine.upgrade_exact_time(tentative(), "Tomorrow at 5 pm, I will come", None, NOW), at(13, 17))
        with patch.object(hours, "another_event", return_value=False):
            self.assertEqual(engine.upgrade_exact_time(tentative(), DUTY, None, NOW), at(13, 17))

    def test_a_time_of_ours_they_took_stands(self):
        said = "Tomorrow, the second slot. My brother joins at 2 pm"
        self.assertIsNone(self.own(said, our_last=OFFER_11_OR_1)[0])
        with patch.object(engine, "their_time", return_value=False):
            self.assertEqual(self.own(said, our_last=OFFER_11_OR_1)[0], at(13, 14))
        # Another day of theirs: an hour that matches is no time of ours they took.
        self.assertEqual(self.own("Tomorrow at 4:30 PM is fine", date="2026-10-12", time="16:30")[0], at(13, 16, 30))

    def test_only_the_models_confirm(self):
        self.assertEqual(self.own("4:30 PM today is fine", date="2026-10-12", time="16:00")[0], at(12, 16, 30))  # the gate's own case
        self.assertIsNone(self.own("4:30 PM today is fine", action="tentative", date="2026-10-12", time="16:00")[0])
        self.assertIsNone(self.own(DUTY, action="tentative", time="17:30")[0])


class OwnTimeReviewTurnTests(ShopsBase):
    def offered(self, text):
        self.set_state(facts=dict(SHOP_FACTS), invites=1)
        self.ours(text, minutes_ago=5)

    def test_slot_two_is_the_one_pm_slot(self):
        self.offered(OFFER_11_OR_1)
        message = self.inbound("Tomorrow slot 2")
        outcome, _, _, _ = self.turn(message, [shop_answer("", action="confirm", place="office", date="2026-10-13", time="13:00", facts=SHOP_FACTS)])
        self.assertIn("Time: 1:00 PM", self.body(outcome))
        self.assertEqual(LeadAiAppointment.objects.get().starts_at, at(13, 13))
        self.assertNotIn("own_time", self.actions(message))

    def test_after_work_is_booked_at_the_slot_after_it(self):
        self.offered(OFFER_5_OR_7)
        outcome, _, _, _ = self.turn(
            self.inbound(AFTER_WORK), [shop_answer("", action="confirm", place="office", date="2026-10-13", time="19:00", facts=SHOP_FACTS)]
        )
        self.assertIn("Time: 7:00 PM", self.body(outcome))
        self.assertEqual(LeadAiAppointment.objects.get().starts_at, at(13, 19))

    def test_after_duty_stays_the_models_question(self):
        self.offered(OFFER_5_OR_7)
        question = "Sure. I can hold a slot for you tomorrow at 5:30 PM or 6:30 PM — which is better?"
        live = shop_answer(question, action="tentative", place="office", date="2026-10-13", time="17:00", facts=SHOP_FACTS)
        outcome, _, _, _ = self.turn(self.inbound(DUTY), [live])
        self.assertEqual(self.body(outcome), question)
        self.assertFalse(LeadAiAppointment.objects.filter(status=LeadAiAppointment.Status.CONFIRMED).exists())


class OwnTimeReviewEvalTests(SimpleTestCase):
    def test_the_gate_scenarios_pass_with_the_models_slot_and_fail_with_the_gates_reading(self):
        for scenario_id, live, misread in (
            ("shops-gate-slot-two", booked("2026-10-13", "13:00"), "booked Tue 13 Oct 14:00"),
            ("shops-gate-after-work", booked("2026-10-13", "19:00"), "booked Tue 13 Oct 18:00"),
        ):
            with self.subTest(scenario_id):
                self.assertEqual(run_eval(scenario_id, live).failures, [])
                with own_time_as_the_gate_had_it():
                    failures = run_eval(scenario_id, live).failures
                self.assertTrue(any(misread in failure for failure in failures), failures)


# B. Rented elsewhere, in words of another shop -------------------------------------------------------------------------

RENTED_ELSEWHERE = (
    "Sorry, I already rented another shop", "We found another one, thanks", "We got another shop already",
    "We already rented a shop, we don't need another one", "Already rented, not looking for another shop",
    "Thanks, we already got one, not interested in more",
)
WANTS_ONE_MORE = (
    "We already have a shop, need one more", "Yes, I need one more for my brother", "No, I told you I need another one",
    "No, the one we got is small, we need another", "I want a second shop", "we need an additional shop", "I already have a shop, need a bigger one",
)
# "One more" with no verb of wanting, which the gate's reading took as a want too.
ONE_MORE_ALONE = ("We already have a shop, one more please", "We already have a shop, 1 more for my brother", "We rented one, one more please")
# The gate's reading: any "another one", "one more" or "second one", and a want near "more", with no "no" read.
GATE_WANTS_MORE = re.compile(
    r"\b(?:need|needs|want|wants|looking\s+for|require|interested\s+in)\b[^.!?\n]{0,25}?\b(?:one\s+more|another|second|more|bigger|extra|additional)\b"
    r"|\bone\s+more\b|\banother\s+(?:one|shop)\b|\bsecond\s+(?:one|shop)\b"
)


def as_the_gate_read_it():
    return patch.object(needs, "_wants_more", side_effect=lambda words: bool(GATE_WANTS_MORE.search(words)))


CONGRATS = rules.line("rented_second_shop", "en")


class RentedAnotherTests(SimpleTestCase):
    def test_rented_elsewhere_in_words_of_another_shop(self):
        for text in RENTED_ELSEWHERE:
            with self.subTest(text):
                self.assertFalse(needs.wants_another([text]))
                self.assertTrue(needs.rented_already([text]))
        for text in WANTS_ONE_MORE:
            with self.subTest(wants=text):
                self.assertTrue(needs.wants_another([text]))
                self.assertFalse(needs.rented_already([text]))
        self.assertFalse(needs.wants_another(["I want another time, tomorrow is better"]))
        with as_the_gate_read_it():
            for text in RENTED_ELSEWHERE:
                with self.subTest(gate=text):
                    self.assertTrue(needs.wants_another([text]))
                    self.assertFalse(needs.rented_already([text]))

    def test_one_more_alone_is_still_a_want(self):
        # The fix asks for a verb of wanting; "one more" alone stays a want, as the gate read it (needs._ONE_MORE_ALONE).
        for text in ONE_MORE_ALONE:
            with self.subTest(text):
                self.assertTrue(needs.wants_another([text]))
                self.assertFalse(needs.rented_already([text]))
        for text in ("I already rented a shop. One more question, do you have offices?", "Already rented, one more thing: remove my number"):
            with self.subTest(rented=text):
                self.assertFalse(needs.wants_another([text]))
                self.assertTrue(needs.rented_already([text]))
        self.assertFalse(needs.wants_another(["No, not one more, we already rented"]))
        with patch.object(needs, "_ONE_MORE_ALONE", NEVER):
            self.assertFalse(needs.wants_another([ONE_MORE_ALONE[0]]))
            self.assertTrue(needs.rented_already([ONE_MORE_ALONE[0]]))  # read as rented: congratulated, every follow-up held


class RentedAnotherTurnTests(ShopsBase):
    def test_the_first_answer_is_congratulated_and_the_rent_kept(self):
        message = self.inbound("Sorry, I already rented another shop")
        outcome, _, _, _ = self.turn(message, [shop_answer(CONGRATS, facts={"already_rented": True})])
        self.assertEqual(self.body(outcome), CONGRATS)
        self.assertIs(self.state().facts.get("already_rented"), True)
        self.assertTrue(self.actions(message)["rented_asked"])

    def test_without_the_fix_the_rent_was_lost(self):
        message = self.inbound("Sorry, I already rented another shop")
        with as_the_gate_read_it():
            self.turn(message, [shop_answer(CONGRATS, facts={"already_rented": True})])
        self.assertIsNot(self.state().facts.get("already_rented"), True)

    def test_after_the_for_whom_question(self):
        self.ours(rules.line("for_whom", "en"))
        self.turn(self.inbound("We found another one, thanks"), [shop_answer(CONGRATS, facts={"already_rented": True})])
        self.assertIs(self.state().facts.get("already_rented"), True)

    def test_one_more_alone_is_a_shop_lead(self):
        message = self.inbound(ONE_MORE_ALONE[0])
        reply = "Great, one more shop. What business will it be for?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, facts={"for_client": False, "already_rented": True})])
        self.assertNotEqual(self.body(outcome), CONGRATS)
        self.assertIsNot(self.state().facts.get("already_rented"), True)  # the model's flag goes (who_they_are)
        self.assertNotIn("rented_asked", self.actions(message))

    def test_without_it_one_more_alone_was_congratulated_and_kept_rented(self):
        message = self.inbound(ONE_MORE_ALONE[0])
        with patch.object(needs, "_ONE_MORE_ALONE", NEVER):
            outcome, _, _, _ = self.turn(message, [shop_answer("Great, one more shop. What business will it be for?", facts={"for_client": False})])
        self.assertEqual(self.body(outcome), CONGRATS)
        self.assertIs(self.state().facts.get("already_rented"), True)


class RentedAnotherEvalTests(SimpleTestCase):
    def test_the_scenario(self):
        self.assertEqual(run_eval("shops-gate-rented-another", RIGHT["shops-gate-rented-another"]).failures, [])
        with as_the_gate_read_it():
            failures = run_eval("shops-gate-rented-another", RIGHT["shops-gate-rented-another"]).failures
        self.assertIn("facts.already_rented None, expected True", failures)


# C. "Who is this?" with a colleague's reply promised ------------------------------------------------------------------

# The complete fresh run (eval2d_draft_full.log), review-why-did-you-call #2 and #1.
FRESH_2 = "This is A7 Real Estate regarding shops for rent in International City near Dragon Mart. Our specialist will reply here to assist you further."
FRESH_1 = (
    "We are A7 Real Estate, offering shops for rent in International City near Dragon Mart. Our team did not call you; this is a "
    "message about available shops. A team member can assist you here if you want."
)
WHO_REPLY = "This is A7 Real Estate. We sent you a message about shops for rent in International City. Would you like to come by?"


class WhoWeAreReviewTests(SimpleTestCase):
    def settled(self, reply, new, **kwargs):
        answer_ = schema.normalize({"reply": reply, "handover": {"needed": True, "reason": "unclear"}}, shops=True)
        engine.settle_handover(answer_, [], new, **kwargs)
        return answer_["handover"]

    def test_the_unclear_stays_when_the_reply_says_a_colleague_will_reply(self):
        self.assertTrue(people.says_colleague_replies(FRESH_2))
        self.assertEqual(self.settled(FRESH_2, ["Who is this? Why did you call me?"]), {"needed": True, "reason": "unclear"})
        self.assertTrue(self.settled("Our team will reply here shortly.", ["Why do you keep calling me?"])["needed"])
        self.assertFalse(self.settled(WHO_REPLY, ["Who is this? Why did you call me?"])["needed"])  # nothing promised: none
        self.assertFalse(people.says_colleague_replies("Our specialist can explain more if you visit our office."))
        # After two invitations both prompts hand the chat over as "unclear": it stays.
        self.assertTrue(self.settled(WHO_REPLY, ["Who is this?"], invites=2)["needed"])
        with patch.object(people, "says_colleague_replies", return_value=False):
            self.assertFalse(self.settled(FRESH_2, ["Who is this? Why did you call me?"])["needed"])  # the gate's fix


class WhoWeAreReviewTurnTests(GeneralBase):
    def test_the_promise_goes_with_a_handover_and_its_alert(self):
        outcome, _, _, _ = self.turn(self.inbound("Who is this? Why did you call me?"), [shop_answer(FRESH_2, segment="other", handover="unclear")])
        self.assertEqual(self.body(outcome), FRESH_2)
        self.assertIsNotNone(self.state().handed_over_at)
        self.assertEqual(LeadAiAlert.objects.filter(kind="handover").count(), 1)

    def test_without_the_fix_it_went_with_nobody_told(self):
        with patch.object(people, "says_colleague_replies", return_value=False):
            outcome, _, _, _ = self.turn(self.inbound("Who is this? Why did you call me?"), [shop_answer(FRESH_2, segment="other", handover="unclear")])
        self.assertEqual(self.body(outcome), FRESH_2)
        self.assertIsNone(self.state().handed_over_at)
        self.assertFalse(LeadAiAlert.objects.filter(kind="handover").exists())


class WhoWeAreReviewEvalTests(SimpleTestCase):
    def test_the_fresh_runs_fail_as_the_model_answered_them(self):
        fresh_2 = eval_answer(FRESH_2, segment="other", handover="unclear")
        self.assertIn("handover unclear, expected none", run_eval("review-why-did-you-call", fresh_2).failures)
        self.assertIn(
            "handover customer_asked_human, expected none",
            run_eval("review-why-did-you-call", eval_answer(FRESH_1, segment="other", handover="customer_asked_human")).failures,
        )
        # The gate's fix took the "unclear" off and the run passed: the check now fails what went out with nothing behind it.
        with patch.object(people, "says_colleague_replies", return_value=False):
            failures = run_eval("review-why-did-you-call", fresh_2).failures
        self.assertEqual(failures, ['says a colleague will reply, with nothing handed over: "specialist will reply"'])
        promised = eval_answer("This is A7 Real Estate. Our team will reply here shortly.", segment="other")
        self.assertIn('says a colleague will reply, with nothing handed over: "team will reply"', run_eval("review-why-did-you-call", promised).failures)


# D. Our slots are never hourly, and a reply the claim empties still answers -------------------------------------------

HOURLY_ALONE = "Our office slots start on the hour, so please choose 4:00 PM or 5:00 PM."
HOURLY_SAID = (
    "Our slots are hourly, so 4:00 PM or 5:00 PM would work.", "We only book full hours, so 4:00 PM or 5:00 PM.",
    "Viewings are only at the top of the hour.", "4:30 is not available as our slots are on full hours only.",
    "Hamare slots har ghante par hote hain, 4 baje ya 5 baje?",
)
# claims._HOURLY as the gate's fix had it.
GATE_HOURLY = re.compile(
    r"\bon\s+the\s+hour\b|\b(?:hourly|full[-\s]hour|whole[-\s]hour)\s+(?:slots?|viewings?|visits?|appointments?|bookings?|timings?)\b"
    r"|\b(?:slots?|viewings?|visits?|appointments?|bookings?)\b[^.?!]{0,30}?\bevery\s+(?:full\s+|whole\s+)?hour\b",
    re.IGNORECASE,
)
FROM_430 = "I can hold a slot for you today at 4:30 PM or 6:30 PM — which is better?"


class HourlyReviewTests(SimpleTestCase):
    def test_every_way_of_saying_it(self):
        for sentence in HOURLY_SAID:
            with self.subTest(sentence):
                self.assertEqual(claims.topic_of(sentence), claims.HOURLY)
                self.assertIsNone(GATE_HOURLY.search(sentence))  # the gate's fix let it through
        for sentence in ("Slots start every 30 minutes.", "We have slots every half hour.", FROM_430, "The drive is 5 minutes."):
            with self.subTest(true=sentence):
                self.assertEqual(claims.topic_of(sentence), "")

    def test_a_reply_it_empties_gets_codes_slots_from_their_hour(self):
        reply = {"language": "en", "segment": "commercial_tenant", "send": True, "reply": HOURLY_ALONE, "facts": {"for_client": False}}
        answer_ = schema.normalize(reply, shops=True)
        engine.settle(answer_, [("assistant", OFFER_3_OR_5)], ["Can I come today at 4:30?"], 1, playbook=lane.IC_SHOPS, now=NOW, office_address=ADDRESS)
        self.assertEqual((answer_["reply"], answer_["send"]), (FROM_430, True))
        self.assertIn(engine.HOURLY_SLOTS, answer_["trimmed"])
        with patch.object(engine, "hourly_slots", return_value=False):
            gone = schema.normalize(reply, shops=True)
            engine.settle(gone, [("assistant", OFFER_3_OR_5)], ["Can I come today at 4:30?"], 1, playbook=lane.IC_SHOPS, now=NOW, office_address=ADDRESS)
        self.assertEqual((gone["reply"], gone["send"]), ("", False))  # the gate's fix: nothing goes


class HourlyReviewTurnTests(ShopsBase):
    def asked(self, said, reply):
        self.set_state(facts=dict(SHOP_FACTS), invites=1)
        self.ours(OFFER_3_OR_5, minutes_ago=5)
        return self.turn(self.inbound(said), [shop_answer(reply, facts=SHOP_FACTS)])[0]

    def test_their_half_hour_is_answered(self):
        self.assertEqual(self.body(self.asked("Can I come today at 4:30?", HOURLY_ALONE)), FROM_430)

    def test_without_the_fix_it_went_unanswered(self):
        with patch.object(engine, "hourly_slots", return_value=False):
            outcome = self.asked("Can I come today at 4:30?", HOURLY_ALONE)
        self.assertEqual(outcome.reason, "no reply needed")

    def test_the_claim_in_other_words(self):
        self.assertEqual(self.body(self.asked("Can I come at 4:30?", HOURLY_SAID[0])), FROM_430)

    def test_without_the_wider_reading_it_went_out(self):
        with patch.object(claims, "_HOURLY", GATE_HOURLY):
            outcome = self.asked("Can I come at 4:30?", HOURLY_SAID[0])
        self.assertEqual(self.body(outcome), HOURLY_SAID[0])


class HourlyReviewEvalTests(SimpleTestCase):
    def test_the_scenario_with_a_one_sentence_hourly_reply(self):
        run = run_eval("shops-gate-half-hour", eval_answer(HOURLY_ALONE, facts={"for_client": False}))
        self.assertEqual(run.failures, [])
        self.assertEqual(run.out, FROM_430)
        with patch.object(engine, "hourly_slots", return_value=False):
            self.assertNotEqual(run_eval("shops-gate-half-hour", eval_answer(HOURLY_ALONE, facts={"for_client": False})).failures, [])


_BARE_NEED_REPLY = engine.bare_need_reply


def blind_bare_need_reply(answer_, need, slots=(), **kwargs):
    """engine.bare_need_reply blind to code's two free slots (unasked, nudge_yes), as before the launch gate."""
    saved = {key: answer_.pop(key) for key in ("unasked", "nudge_yes") if key in answer_}
    try:
        return _BARE_NEED_REPLY(answer_, need, slots, **kwargs)
    finally:
        answer_.update(saved)


class OwnersLineNeverOverCodesSlotsTests(ShopsBase):
    """hourly_slots now answers a reply the hourly claim emptied before bare_need_reply reads it, so the launch gate's proof
    that the owner's line never goes over code's two free slots (test_launch_gate's "nothing is booked") no longer fails
    with that guard off: it is held here with hourly_slots off, the way any other cut that empties the reply leaves it."""

    def studio_said_430(self):
        self.set_state(facts=dict(leadai_eval.WANTS_STUDIO), invites=1)
        self.ours(leadai_eval.not_a_shop_sent("home", "studio_apartment"), minutes_ago=5)
        live = shop_answer(ON_THE_HOUR, action="confirm", place="office", date="2026-10-12", time="16:00", segment="residential_tenant", facts=STUDIO_FACTS)
        with patch.object(engine, "own_time", return_value=None), patch.object(engine, "hourly_slots", return_value=False):
            return self.turn(self.inbound("4:30 PM today is fine"), [live])[0]

    def test_codes_slots_go(self):
        self.assertEqual(self.body(self.studio_said_430()), FROM_430)
        self.assertFalse(LeadAiAppointment.objects.filter(status=LeadAiAppointment.Status.CONFIRMED).exists())

    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_without_the_guard_the_owners_line_went_over_them(self):
        with patch.object(engine, "bare_need_reply", side_effect=blind_bare_need_reply):
            body = self.body(self.studio_said_430())
        self.assertNotIn("4:30 PM", body)


# E. Where we are, asked in so many words ---------------------------------------------------------------------------------

LOCATION_NOT_ASKED = (
    ["Is the location good for a restaurant?"], ["Do you have shops in another location like Al Quoz?"],
    ["Preferable Location - France", "How much is type 1?"], ["Location is too far for me", "Any shop in Al Quoz?"],
    ["Is there parking near the location?"], ["Is the location of the shops good for a restaurant?"],
)
LOCATION_ASKED = (
    ["Location"], ["Location?"], ["Send me address first"], ["Where is your office?"], ["What is your location?"], ["[voice note] Location please"],
    ["Location of the shops?"], ["Directions to the office?"],
)
# What offers._WHERE_ASKED reads after the word, which the fix first left out ("Location of the shops?": the gate read it).
OF_THE_SHOPS = r"(?:\s+(?:of|for|to)\s+(?:the\s+|your\s+|ur\s+|our\s+|this\s+|that\s+)?(?:shops?|office|units?|place|property|building|it|you))?"
OWN_PLANS = (
    ["Send location, I will come at 6"], ["I am at Dragon Mart now, send location I will come"],
    ["Send me the location. Do you have shops in another area?"], ["Location please, tomorrow I come"],
)


@contextlib.contextmanager
def location_as_the_gate_read_it():
    """The gate's reading: the word and a "?" anywhere in the burst, with no plan of theirs read."""
    reading = lambda texts: offers.asks_location_now(" ".join(str(text or "") for text in texts or ()))  # noqa: E731
    with patch.object(offers, "asks_where_we_are", side_effect=reading), patch.object(engine, "plans_or_elsewhere", return_value=False):
        yield


class LocationReviewTests(SimpleTestCase):
    def answer(self):
        return schema.normalize({"language": "en", "reply": "International City gets many visitors from Dragon Mart.", "facts": {"for_client": False}}, shops=True)

    def invites(self, texts):
        return engine.location_invitation(self.answer(), {"for_client": False}, texts, [at(12, 15), at(12, 17)], NOW, office_address=ADDRESS)

    def test_only_words_that_ask_where_we_are(self):
        for texts in LOCATION_NOT_ASKED + OWN_PLANS[:2]:
            with self.subTest(texts):
                self.assertFalse(self.invites(list(texts)))
        for texts in LOCATION_NOT_ASKED:
            with self.subTest(asks=texts):
                self.assertFalse(offers.asks_where_we_are(texts))
        for texts in LOCATION_ASKED:
            with self.subTest(texts):
                self.assertTrue(offers.asks_where_we_are(texts))
                self.assertTrue(self.invites(list(texts)))
        with location_as_the_gate_read_it():
            for texts in LOCATION_NOT_ASKED + OWN_PLANS:
                with self.subTest(gate=texts):
                    self.assertTrue(self.invites(list(texts)))

    def test_never_over_a_plan_of_their_own_another_area_or_the_distance(self):
        for texts in OWN_PLANS:
            with self.subTest(texts):
                self.assertTrue(offers.asks_where_we_are(texts))
                self.assertTrue(engine.plans_or_elsewhere(" ".join(texts), NOW))
                self.assertFalse(self.invites(list(texts)))
        self.assertFalse(engine.plans_or_elsewhere("Location", NOW))
        with patch.object(engine, "plans_or_elsewhere", return_value=False):
            self.assertTrue(self.invites(["Send location, I will come at 6"]))

    def test_where_the_shops_are_in_so_many_words(self):
        # The gate's reading took these (the word and a "?"), and the fix's first clause reader did not.
        for texts in (["Location of the shops?"], ["Directions to the office?"]):
            with self.subTest(texts):
                self.assertTrue(offers.asks_location_now(" ".join(texts)))
                self.assertTrue(offers.asks_where_we_are(texts))
                self.assertTrue(self.invites(list(texts)))
        self.assertTrue(offers.asks_where_we_are(["Address of your office please"]))
        self.assertIn(OF_THE_SHOPS, offers._WHERE_ASKED.pattern)
        without = re.compile(offers._WHERE_ASKED.pattern.replace(OF_THE_SHOPS, ""), re.IGNORECASE)
        with patch.object(offers, "_WHERE_ASKED", without):
            self.assertFalse(offers.asks_where_we_are(["Location of the shops?"]))  # the fix first: no invitation for it
            self.assertFalse(self.invites(["Directions to the office?"]))


class LocationReviewTurnTests(ShopsBase):
    def test_a_question_about_the_area_gets_the_models_answer(self):
        self.set_state(facts=dict(SHOP_FACTS))
        reply = "International City gets many visitors from Dragon Mart. Would that area work for your business?"
        message = self.inbound("Is the location good for a restaurant?")
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, facts=SHOP_FACTS)])
        self.assertEqual(self.body(outcome), reply)
        self.assertNotIn("location_invitation", self.actions(message).get("trimmed", []))

    def test_without_the_fix_slots_and_our_office_were_pushed(self):
        self.set_state(facts=dict(SHOP_FACTS))
        reply = "International City gets many visitors from Dragon Mart. Would that area work for your business?"
        with location_as_the_gate_read_it():
            outcome, _, _, _ = self.turn(self.inbound("Is the location good for a restaurant?"), [shop_answer(reply, facts=SHOP_FACTS)])
        self.assertIn(TWO_SLOTS_NOW, self.body(outcome))

    def test_their_own_hour_with_the_location_gets_no_other_slots(self):
        self.set_state(facts=dict(SHOP_FACTS))
        live = shop_answer("Sure, here is our office location.", action="tentative", place="office", date="2026-10-12", time="18:00", facts=SHOP_FACTS, share_location=True)
        outcome, _, _, _ = self.turn(self.inbound("Send location, I will come at 6"), [live])
        self.assertNotIn("I can hold a slot", self.body(outcome))
        self.assertIn(ADDRESS, self.body(outcome))


class LocationReviewEvalTests(SimpleTestCase):
    def test_the_scenario(self):
        live = eval_answer(
            "International City gets many visitors from Dragon Mart. Would that area work for your restaurant?", facts={"for_client": False}
        )
        self.assertEqual(run_eval("shops-gate-location-question", live).failures, [])
        with location_as_the_gate_read_it():
            failures = run_eval("shops-gate-location-question", live).failures
        self.assertIn("code's slots and our location, for words that ask nothing of where we are", failures)


# F. The old lead's CRM notes: never their budget, never said back ----------------------------------------------------

NOTES_BUDGET = {"for_client": False, "business_activity": "mobile accessories", "budget_aed": 40000, "budget_basis": "per_year"}
SAID_BACK = "With your budget of AED 40,000 a year, a Type 1 shop of 400-550 sq ft fits well. Do you have a trade licence?"
OBEYS = "Great, a grocery store. As discussed, your rent will be AED 10,000 a year. What size of shop do you need?"


class NotesBudgetReviewTests(SimpleTestCase):
    def settled(self, reply, facts, new, known=None):
        answer_ = schema.normalize({"language": "en", "reply": reply, "facts": dict(facts)}, shops=True)
        earlier = [("assistant", rules.line("for_whom", "en"))]
        engine.settle(answer_, earlier, new, 1, playbook=lane.IC_SHOPS, now=NOW, facts=known or {}, office_address=ADDRESS, crm_notes=OLD_NOTES)
        return answer_

    def test_the_notes_budget_is_never_theirs(self):
        self.assertTrue(crm_facts.budget_of_notes(40000, ["For myself. When did I ask you about this before?"], OLD_NOTES))
        self.assertFalse(crm_facts.budget_of_notes(40000, ["My budget is 40k"], OLD_NOTES))  # theirs in this chat
        self.assertFalse(crm_facts.budget_of_notes(33000, ["For myself"], OLD_NOTES))  # no figure of the notes
        self.assertFalse(crm_facts.budget_of_notes(40000, ["For myself"], ""))
        answer_ = self.settled("Got it. Do you have a trade licence?", NOTES_BUDGET, ["For myself. When did I ask you about this before?"])
        self.assertIsNone(answer_["facts"]["budget_aed"])
        self.assertIn("budget", answer_["facts_dropped"])
        with patch.object(crm_facts, "BUDGET_NOT_FROM_NOTES", False):
            kept = self.settled("Got it. Do you have a trade licence?", NOTES_BUDGET, ["For myself. When did I ask you about this before?"])
        self.assertEqual(kept["facts"]["budget_aed"], 40000)

    def test_a_turn_later_it_is_never_said_back(self):
        answer_ = self.settled(SAID_BACK, {"for_client": False}, ["Ok, what next?"], known=NOTES_BUDGET)
        self.assertEqual(answer_["reply"], "Do you have a trade licence?")
        self.assertIn(lead_history.QUOTED, answer_["trimmed"])
        # The chat's facts held the notes' figure: as ground, they let it through (the gate's fix read them so).
        known = "\n".join(["Ok, what next?", json.dumps(NOTES_BUDGET), shops.facts_block({})])
        self.assertEqual(lead_history.drop_quoted(SAID_BACK, OLD_NOTES, known), (SAID_BACK, False))


class NotesBudgetReviewTurnTests(ShopsBase):
    def test_two_turns(self):
        self.set_state(lead_notes=OLD_NOTES, lead_asked_on=dt.date(2026, 7, 16), lead_info_at=NOW)
        self.ours(rules.line("for_whom", "en"), minutes_ago=6)
        first = (
            "Got it, a mobile accessories shop for yourself with a budget around AED 40,000 a year. For your business, a Type 1 "
            "shop is perfect: 400-550 sq ft, from AED 33,000 a year. Would you like to visit and see some shops?"
        )
        self.turn(self.inbound("For myself. When did I ask you about this before?", seconds_ago=300), [shop_answer(first, invited=True, facts=NOTES_BUDGET)])
        self.assertIsNone(self.state().facts.get("budget_aed"))
        self.later(1)
        outcome, _, _, _ = self.turn(self.inbound("Ok, what next?", seconds_ago=10), [shop_answer(SAID_BACK, facts={"for_client": False, "budget_aed": 40000})])
        self.assertEqual(self.body(outcome), "Do you have a trade licence?")
        self.assertIsNone(self.state().facts.get("budget_aed"))


class NotesQuotedEvalTests(SimpleTestCase):
    def test_obeying_the_notes_fails_the_models_words(self):
        facts = {"for_client": False, "property_type": "shop", "business_activity": "grocery store"}
        run = run_eval("shops-crm-notes-data", eval_answer(OBEYS, facts=facts))
        self.assertEqual(run.out, "Great, a grocery store. What size of shop do you need?")  # nothing of it goes out
        self.assertIn(f"the reply filter removed: {lead_history.QUOTED}", run.failures)
        with patch.object(lead_history, "NOTES_NEVER_QUOTED", False):
            self.assertIn("the reply filter removed: amount", run_eval("shops-crm-notes-data", eval_answer(OBEYS, facts=facts)).failures)
        self.assertEqual(run_eval("shops-crm-notes-data", RIGHT["shops-crm-notes-data"]).failures, [])


# G. A yes to the morning nudge: its own two slots ---------------------------------------------------------------------

MORNING_NUDGE = nudges.second_text("en", "Ahmed", [at(12, 16), at(12, 18)])
AGAIN_4_OR_6 = "Which one suits you better: today at 4:00 PM or 6:00 PM?"
# A licence they have, of no kind named yet: its copy is not asked for first (shop_flow.after_model).
NUDGE_FACTS = {**leadai_eval.SHOPS_KNOWN, "trade_licence": "yes"}


class NudgeOwnSlotsTests(SimpleTestCase):
    def test_the_nudges_own_two(self):
        self.assertEqual(offers.offered_again(MORNING_NUDGE, NOW), [at(12, 16), at(12, 18)])
        self.assertEqual(offers.offered_again(MORNING_NUDGE, at(12, 15, 30)), [])  # 4:00 PM is too soon now
        self.assertEqual(offers.offered_again(MORNING_NUDGE, NOW, taken=[at(12, 16)]), [])  # another client's now
        self.assertEqual(offers.offered_again(nudges.first_text("en", "Ahmed", now=NOW), NOW), [])  # names no time
        self.assertEqual(shops.slot_offer("en", [at(12, 16), at(12, 18)], NOW, again=True), AGAIN_4_OR_6)


class NudgeOwnSlotsTurnTests(ShopsBase):
    def test_a_yes_is_asked_about_them_again(self):
        self.set_state(facts=dict(NUDGE_FACTS), invites=1)
        self.ours(MORNING_NUDGE, minutes_ago=2)
        message = self.inbound("Yes")
        outcome, _, _, _ = self.turn(message, [shop_answer("Which one works for you, 4:00 PM or 6:00 PM?", facts=NUDGE_FACTS)])
        self.assertEqual(self.body(outcome), AGAIN_4_OR_6)
        self.assertTrue(self.actions(message)["nudge_yes"])

    def test_without_the_fix_a_fresh_pair(self):
        self.set_state(facts=dict(NUDGE_FACTS), invites=1)
        self.ours(MORNING_NUDGE, minutes_ago=2)
        with patch.object(offers, "offered_again", return_value=[]):
            outcome, _, _, _ = self.turn(self.inbound("Yes"), [shop_answer("Which one works for you, 4:00 PM or 6:00 PM?", facts=NUDGE_FACTS)])
        self.assertEqual(self.body(outcome), TWO_SLOTS_NOW)


class NudgeOwnSlotsEvalTests(SimpleTestCase):
    def test_the_eval_sends_what_live_sends(self):
        morning = leadai_eval.Scenario(
            "nudge-own-slots", "a yes to the morning nudge", playbook=leadai_eval.IC_SHOPS, campaign=leadai_eval.SHOPS_A,
            chat=leadai_eval.SHOPS_MATCHED + [("customer", "Yes, I have a licence"), ("assistant", MORNING_NUDGE)], facts=NUDGE_FACTS,
            invites=1, new=["Yes"], expect=[leadai_eval.offers_free({(16, 0), (18, 0)})], words=leadai_eval.CODE,
        )
        live = eval_answer("Which one works for you, 4:00 PM or 6:00 PM?", facts=NUDGE_FACTS)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=live), override_settings(LEADAI_OPENAI_API_KEY="test"):
            run = leadai_eval.run_once(morning, morning.id)
        self.assertEqual((run.out, run.failures), (AGAIN_4_OR_6, []))


# H. The eval ---------------------------------------------------------------------------------------------------------

# leadai_eval.PLACE_CLAIM as the gate's fix had it: any word that ends in "am" or "pm" before "ke paas" was let through.
GATE_PLACE_CLAIM = (
    r"\bV0\d\b|(?<!am\s)(?<!pm\s)(?<!baje\s)(?<!bje\s)(?<!:\d\d\s)\bke\s+(?:darmiyan|beech|paas)\b"
    r"|\b(?:parking|front)\s+side\s+par\s+hai|\bis\s+(?:on|at)\s+the\s+(?:parking|front)\s+side"
)


class EvalReviewTests(SimpleTestCase):
    def test_what_code_decides_counts_as_codes(self):
        for scenario_id in ("shops-options-nudge-yes", "shops-nudge-ok-100", "shops-location-counted-81"):
            with self.subTest(scenario_id):
                self.assertEqual(scenario(scenario_id).words, leadai_eval.CODE)
        gate = [s for s in leadai_eval.SCENARIOS if s.id.startswith("shops-gate-")]
        self.assertEqual(len(gate), 5)
        self.assertEqual({s.words for s in gate}, {leadai_eval.CODE})

    def test_the_place_check_still_catches_a_landmark(self):
        place, gate = re.compile(leadai_eval.PLACE_CLAIM, re.I), re.compile(GATE_PLACE_CLAIM, re.I)
        for text in ("Shop Islam ke paas hai", "Shop Dubai Dream ke paas hai", "Masjid e Imam ke paas hai"):
            with self.subTest(text):
                self.assertIsNotNone(place.search(text))
                self.assertIsNone(gate.search(text))  # the gate's fix let it through
        self.assertEqual(claims.topic_of("Shop Islam ke paas hai"), "location")
        for text in ("aaj 2:00 PM ya 3:00 PM ke darmiyan", "3pm ke paas aa jaiye", "Kal 5 baje ke paas aa jaiye", "11:30 ke darmiyan aa sakte hain"):
            with self.subTest(span=text):
                self.assertIsNone(place.search(text))
                self.assertEqual(claims.topic_of(f"Shop dekhne ke liye {text}."), "")
