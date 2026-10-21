"""Batch 2d's deployed gate (2026-10-17): the real-model eval on the live image failed three scenarios in every repeat
(shops-gate-half-hour failed both runs of the last draft too). Each is absorbed by code here, held with the scenario's own
customer words and the model's answers as the deployed runs recorded them, and each fails with its fix switched off:

- A. shops-gate-half-hour: "Can I come today at 4:30?" after our "today at 3:00 PM or 5:00 PM" got "The closest available
  slot is 4:00 PM or 5:00 PM" (or "4:00 PM today" alone) and a tentative for today with no hour. FREE SLOTS lists starts
  an hour apart, so their half hour looked taken. T18 (engine.upgrade_exact_time) books their own hour when the reply
  offered only the slots either side of it (engine.passed_over_hour); the hour of something else in their words never is.
- B. shops-invitation-cut-88: launch chat 88's "Preferable Location - France (P24 P23 P26 P22) / Size - 400sqft", his
  business and licence never asked, was invited with two slots and our location under them. engine.licence_first asks the
  licence before the first invitation whatever the business (a later one asks the business first: discovery_first), and
  reads where we are in so many words only (offers.asks_where_we_are): "Preferable Location" asks nothing.
- C. review-why-did-you-call: "Who is this? Why did you call me?" handed over as "unclear" with "Our specialist will reply
  here ...": engine.settle_handover takes the handover off with that sentence (engine.who_we_are_reply), so nothing that
  goes out promises a colleague nobody told; a reply that says nothing else keeps the handover, as before. An earlier
  draft's "customer_asked_human" for the same words goes the same way (engine.WHO_WE_ARE_HANDOVERS).

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai; the chat is lead 555's.
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai import lane
from apps.leadai.assistant import engine, filters, hours, needs, offers, rules, schema, shop_flow
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import DEFAULT_SHOPS_FACTS, LeadAiAlert, LeadAiAppointment
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, shop_answer

DUBAI = hours.DUBAI


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=DUBAI)


def no_passed_over_hour():
    """T18 as it was: a tentative's own hour only."""
    return patch.object(engine, "passed_over_hour", return_value=None)


# A. Their half hour ----------------------------------------------------------------------------------------------------

CAN_I_COME = "Can I come today at 4:30?"
OFFER_3_OR_5 = leadai_eval.TODAY_3_OR_5[-1][1]
SHOP_FACTS = dict(leadai_eval.LICENCE_KNOWN)
# eval2d_deployed.log, shops-gate-half-hour #1 and #2: a tentative for today with no hour, both.
CLOSEST_TWO = "Our office is open today. The closest available slot is 4:00 PM or 5:00 PM. Which one works better for you?"
CLOSEST_ONE = (
    "Our office is open now. The closest available slot is 4:00 PM today. I can hold it for you — does that work? You come to "
    "our office first, then our agent drives you to the shops and back."
)
TOMORROW_11_OR_5 = "I can hold a slot for you tomorrow at 11:00 AM or 5:00 PM — which is better?"


def tentative(reply, *, date="2026-10-12", time=None, facts=None, maker=shop_answer, **extra):
    """The model's tentative office visit for their day, with no hour (the deployed runs) unless ``time``."""
    return maker(reply, action="tentative", place="office", date=date, time=time, facts=SHOP_FACTS if facts is None else facts, **extra)


class PassedOverHourTests(SimpleTestCase):
    def upgrade(self, reply, said=CAN_I_COME, **kwargs):
        proposal = kwargs.pop("proposal", {})
        answer_ = schema.normalize(tentative(reply, **proposal).data, shops=True)
        return engine.upgrade_exact_time(answer_, said, kwargs.pop("appointment", None), NOW, **kwargs), answer_

    def test_the_deployed_runs_book_their_half_hour(self):
        for reply in (CLOSEST_TWO, CLOSEST_ONE):
            with self.subTest(reply=reply[:60]):
                start, answer_ = self.upgrade(reply)
                self.assertEqual(start, at(12, 16, 30))
                proposal = answer_["appointment"]
                self.assertEqual((proposal["action"], proposal["place"], proposal["time"]), ("confirm", "office", "16:30"))
                self.assertEqual(proposal["customer_words"], CAN_I_COME)  # theirs for the agents, never the model's
                with no_passed_over_hour():
                    self.assertIsNone(self.upgrade(reply)[0])

    def test_their_hour_named_as_taken_beside_the_slots_either_side(self):
        refused = "4:30 PM is not available. The closest available slots are 4:00 PM or 5:00 PM. Which one works for you?"
        self.assertEqual(self.upgrade(refused)[0], at(12, 16, 30))
        with no_passed_over_hour():
            self.assertIsNone(self.upgrade(refused)[0])

    def test_a_tentative_at_the_slot_beside_theirs(self):
        reply = "I can hold a slot for you today at 4:00 PM or 5:00 PM — which is better?"
        self.assertEqual(self.upgrade(reply, proposal={"time": "16:00"})[0], at(12, 16, 30))
        self.assertEqual(self.upgrade(reply, proposal={"time": "17:00"})[0], at(12, 16, 30))
        # Another time of the model's own stays the model's (the gate's review), and so does one an hour from theirs.
        self.assertIsNone(self.upgrade(reply, proposal={"time": "18:00"})[0])
        self.assertIsNone(self.upgrade("I can hold a slot for you today at 3:00 PM or 6:00 PM — which is better?", proposal={"time": "15:00"})[0])

    def test_their_own_hour_kept_by_the_model_is_t18_as_before(self):
        self.assertEqual(self.upgrade("Great, see you then.", proposal={"time": "16:30"})[0], at(12, 16, 30))
        with no_passed_over_hour():
            self.assertEqual(self.upgrade("Great, see you then.", proposal={"time": "16:30"})[0], at(12, 16, 30))

    def test_never_the_hour_of_something_else(self):
        for said in (
            "My shop closes at 10, I can come tomorrow", "I wake up at 11, I will come tomorrow",
            "Tomorrow at 4 pm I have a doctor appointment, I can come",
        ):
            with self.subTest(said):
                self.assertEqual(len(hours.spoken_times(said)), 1)  # an hour is said, but not the visit's
                self.assertIsNone(self.upgrade(TOMORROW_11_OR_5, said=said, proposal={"date": "2026-10-13"})[0])

    def test_never_without_the_slots_either_side_alone(self):
        for name, reply, said, kwargs in (
            ("the reply offers their own hour", "I can hold a slot for you today at 4:30 PM or 6:30 PM — which is better?", CAN_I_COME, {}),
            ("an hour more than half an hour away", "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?", CAN_I_COME, {}),
            ("no time offered", "Sure, our office is open today.", CAN_I_COME, {}),
            ("the slots of another day", "I can hold a slot for you tomorrow at 4:00 PM or 5:00 PM — which is better?", CAN_I_COME, {}),
            ("two hours of theirs", CLOSEST_TWO, "Can I come today at 4:30 or 5:30?", {}),
            ("no day of theirs", CLOSEST_TWO, "Can I come at 4:30?", {}),
            ("a hedge", CLOSEST_TWO, "Maybe I can come today at 4:30", {}),
            ("a deferral", CLOSEST_TWO, "Today at 4:30, I will let you know", {}),
            ("a call", CLOSEST_TWO, "Can you call me today at 4:30?", {}),
            ("another client has it", CLOSEST_TWO, CAN_I_COME, {"taken": [at(12, 16, 30)]}),
            ("a person has the chat", CLOSEST_TWO, CAN_I_COME, {"handed_over": True}),
            ("a colleague wrote last", CLOSEST_TWO, CAN_I_COME, {"agent_last": True}),
        ):
            with self.subTest(name):
                self.assertIsNone(self.upgrade(reply, said=said, **kwargs)[0])

    def test_any_hour_free_slots_does_not_list(self):
        # At 14:20 FREE SLOTS starts at 3:30 PM and lists the half hours: their 5:00 PM sits between 4:30 and 5:30.
        later = at(12, 14, 20)
        answer_ = schema.normalize(tentative("The closest slots are 4:30 PM or 5:30 PM. Which one suits you?").data, shops=True)
        self.assertEqual(engine.upgrade_exact_time(answer_, "Can I come today at 5 pm?", None, later), at(12, 17))


class HalfHourTurnTests(ShopsBase):
    def asked(self, reply):
        self.set_state(facts=dict(SHOP_FACTS), invites=1)
        self.ours(OFFER_3_OR_5, minutes_ago=5)
        message = self.inbound(CAN_I_COME)
        outcome, _, _, _ = self.turn(message, [tentative(reply, words=CAN_I_COME, share_location=True)])
        return message, outcome

    def test_their_half_hour_is_booked(self):
        message, outcome = self.asked(CLOSEST_TWO)
        body = self.body(outcome)
        self.assertTrue(body.startswith("Your viewing is confirmed"), body)
        self.assertIn("Time: 4:30 PM", body)
        self.assertNotIn("4:00 PM", body)
        self.assertEqual(LeadAiAppointment.objects.get().starts_at, at(12, 16, 30))
        self.assertEqual(LeadAiAppointment.objects.get().status, LeadAiAppointment.Status.CONFIRMED)
        self.assertTrue(self.actions(message)["upgraded"])

    def test_without_the_fix_the_model_offered_4_or_5(self):
        # Round 22 cuts the "closest available" sentence as well (claims.CLOSEST): off here too, the deployed reply goes whole.
        with no_passed_over_hour(), patch("apps.leadai.assistant.claims.half_hour_asked", return_value=False):
            _, outcome = self.asked(CLOSEST_TWO)
        self.assertTrue(self.body(outcome).startswith(CLOSEST_TWO), self.body(outcome))
        self.assertFalse(LeadAiAppointment.objects.filter(status=LeadAiAppointment.Status.CONFIRMED).exists())


class HalfHourEvalTests(SimpleTestCase):
    def test_the_deployed_runs_pass_and_fail_without_the_fix(self):
        for reply in (CLOSEST_TWO, CLOSEST_ONE):
            with self.subTest(reply=reply[:60]):
                live = tentative(reply, words=CAN_I_COME, share_location=True, maker=eval_answer)
                run = run_eval("shops-gate-half-hour", live)
                self.assertEqual(run.failures, [])
                self.assertEqual(run.when, at(12, 16, 30))
                with no_passed_over_hour():
                    failures = run_eval("shops-gate-half-hour", live).failures
                self.assertEqual(failures, ["(nothing booked (action tentative), expected Mon 12 Oct 16:30 / does not offer their 4:30 PM)"])


# B. The licence before the first invitation --------------------------------------------------------------------------

WORDS_88 = leadai_eval.TAP_WORDS_88[0]  # "Preferable Location - France (P24 P23 P26 P22)\nSize - 400sqft"
FACTS_88 = {"for_client": False, "property_type": "shop", "intent": "rent", "community": "France", "size_sqft": 400, "shop_type": "type_1", "customer_name": "Abd"}
# eval2d_deployed.log, shops-invitation-cut-88 #1 and #2: invited, with our location under it.
INVITED_88 = (
    "For a shop of 400 sq ft in France cluster, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. I can hold a slot for you "
    "today at 12:00 PM or 1:00 PM at our office. Which is better?",
    "For a shop in France cluster, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. I can hold a viewing slot for you "
    "today at 12:00 PM or 1:00 PM at our office. Which is better?",
)
ASK_LICENCE = rules.line("ask_licence", "en")
LICENCE_88 = f"For a shop of 400 sq ft in France cluster, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. {ASK_LICENCE}"


def licence_first_as_it_was(answer, known, earlier, new_texts, now=None, *, invites=0):
    """engine.licence_first before the deployed gate's fix: the business needed for any invitation, and "Location"
    anywhere in their words read as asking where we are (filters.asks_for_location)."""
    known = known or {}
    facts = dict(known)
    facts.update({key: value for key, value in answer["facts"].items() if value not in (None, "", [])})
    ours = [text for author, text in earlier if author in ("assistant", "agent")]
    last = ours[-1] if ours else ""
    if facts.get("for_client") is not False or facts.get("licence_kind") or facts.get("trade_licence"):
        return False
    if needs.of(known) is not None:
        return False
    if not (facts.get("size_sqft") or facts.get("budget_aed")):
        return False
    answering_business = bool(engine._BUSINESS_WORDS.search(last)) and bool(known.get("size_sqft") or known.get("budget_aed"))
    if not (facts.get("business_activity") or answering_business):
        return False
    if filters.offers_time(last) or engine._LICENCE_WORDS.search(last):
        return False
    said = " ".join(new_texts or [])
    if (
        rules.asks_question(said) or filters.asks_for_location(said) or filters.asks_the_way(said) or engine._VISIT_WORDS.search(said)
        or hours.named_days(said, now) or hours.named_times(said)
    ):
        return False
    sentences = filters.split_sentences(answer["reply"])
    if not (answer["invited_to_meeting"] or any(engine._inviting(sentence) for sentence in sentences)):
        return False
    kept = [sentence for sentence in sentences if not engine._inviting(sentence) and not rules.asks_question(sentence)]
    answer["reply"] = " ".join([*kept, rules.line("ask_licence", answer["language"])])
    answer["invited_to_meeting"] = False
    answer["share_office_location"] = False
    return True


def as_it_was():
    return patch.object(engine, "licence_first", side_effect=licence_first_as_it_was)


LISTED_88 = [("campaign", leadai_eval.SHOPS_A.body), *leadai_eval.CHAT_88_LISTED]
EIGHTY_EIGHT_AT = at(15, 10, 33)  # the scenario's Thursday clock


class LicenceBeforeFirstInvitationTests(SimpleTestCase):
    def settle(self, reply, *, said=WORDS_88, invites=0, known=None, facts=None, earlier=None):
        answer_ = schema.normalize(shop_answer(reply, invited=True, share_location=True, facts=FACTS_88 if facts is None else facts).data, shops=True)
        engine.settle(
            answer_, LISTED_88 if earlier is None else earlier, [said], invites, playbook=lane.IC_SHOPS, now=EIGHTY_EIGHT_AT,
            facts={"for_client": False, "property_type": "shop", "intent": "rent", "customer_name": "Abd"} if known is None else known,
            slots=[at(15, 12), at(15, 14)], office_address=leadai_eval.ADDRESS,
        )
        return answer_

    def test_the_deployed_runs_ask_the_licence(self):
        for reply in INVITED_88:
            with self.subTest(reply=reply[:40]):
                out = self.settle(reply)
                self.assertTrue(out["reply"].endswith(ASK_LICENCE), out["reply"])
                self.assertNotIn("12:00 PM", out["reply"])
                self.assertEqual((out["invited_to_meeting"], out["share_office_location"], out["trimmed"]), (False, False, ["licence_first"]))
                with as_it_was():
                    kept = self.settle(reply)
                self.assertEqual((kept["reply"], kept["invited_to_meeting"], kept["share_office_location"]), (reply, True, True))
        self.assertEqual(self.settle(INVITED_88[0])["reply"], LICENCE_88)

    def test_preferable_location_asks_nothing_of_where_we_are(self):
        self.assertTrue(filters.asks_for_location(WORDS_88))  # the reading licence_first stood aside for
        self.assertFalse(offers.asks_where_we_are([WORDS_88]))
        # Their business known, as in eval shops-35283: the old reading still let the invitation go for the word.
        with as_it_was():
            self.assertTrue(self.settle(INVITED_88[0], facts={**FACTS_88, "business_activity": "mobile accessories"})["invited_to_meeting"])
        self.assertFalse(self.settle(INVITED_88[0], facts={**FACTS_88, "business_activity": "mobile accessories"})["invited_to_meeting"])
        # Where we are asked in so many words is still invited at once.
        for said in ("Size 400sqft, France. Send me the location", "Location", "Where is your office?"):
            with self.subTest(said):
                self.assertNotIn("licence_first", self.settle(INVITED_88[0], said=said).get("trimmed", []))

    def test_a_later_invitation_asks_the_business_first(self):
        earlier = [*LISTED_88, ("customer", "Not today"), ("assistant", "No problem. Type 1 suits most new shops.")]
        out = self.settle(INVITED_88[0], said="Size - 400sqft, France", invites=1, earlier=earlier)
        self.assertNotIn("licence_first", out["trimmed"])
        self.assertIn("discovery", out["trimmed"])
        self.assertTrue(out["reply"].endswith(rules.line("ask_business", "en")), out["reply"])

    def test_never_of_someone_who_wants_no_shop_to_rent(self):
        # Without the business needed, the licence would reach a home seeker's budget (batch 2e's rent track among them).
        home = {**FACTS_88, "property_type": "studio apartment", "budget_aed": 30000, "size_sqft": None}
        for name, kwargs in {
            "a studio said now": {"said": "I need a studio for myself, budget 30k", "facts": {**FACTS_88, "property_type": None}},
            "a home recorded now": {"said": "Budget 30k, for myself", "facts": home},
            "a home known": {"said": "Budget 30k", "known": {"for_client": False, "need": "home", "wanted": "a studio apartment"}},
            "a shop to buy": {"said": "Budget 400k, for myself", "facts": {**FACTS_88, "intent": "buy"}},
        }.items():
            with self.subTest(name):
                self.assertNotIn("licence_first", self.settle(INVITED_88[0], **kwargs).get("trimmed", []))

    def test_still_never_when_the_licence_is_known_or_they_ask_to_come(self):
        for name, kwargs in {
            "a licence of theirs": {"facts": {**FACTS_88, "licence_kind": "ded", "trade_licence": "yes"}},
            "who it is for unknown": {"facts": {**FACTS_88, "for_client": None}, "known": {"property_type": "shop"}},
            "no size or budget": {"facts": {**FACTS_88, "size_sqft": None}},
            "they ask to see": {"said": "Size 400sqft, France. I want to see the shops"},
            "a day of theirs": {"said": "Size 400sqft, France, tomorrow"},
            "a question": {"said": "Size 400sqft, France. Is parking there?"},
        }.items():
            with self.subTest(name):
                self.assertNotIn("licence_first", self.settle(INVITED_88[0], **kwargs).get("trimmed", []))


class LicenceBeforeFirstInvitationTurnTests(ShopsBase):
    def eighty_eight(self, reply):
        self.clock.return_value = at(12, 10, 33)
        self.set_state(facts={"for_client": False, "property_type": "shop", "intent": "rent", "customer_name": "Abd"})
        self.ours(shop_flow.list_text("en", DEFAULT_SHOPS_FACTS), minutes_ago=2, shop_list=True)
        message = self.inbound(WORDS_88)
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, invited=True, share_location=True, facts=FACTS_88)])
        return message, outcome

    def test_chat_88_is_asked_the_licence(self):
        message, outcome = self.eighty_eight(INVITED_88[0])
        self.assertEqual(self.body(outcome), LICENCE_88)
        self.assertEqual((self.state().invites, self.actions(message)["trimmed"]), (0, ["licence_first"]))
        self.assertNotIn("location_appended", self.actions(message))

    def test_without_the_fix_he_was_invited_with_our_location(self):
        with as_it_was():
            message, outcome = self.eighty_eight(INVITED_88[0])
        self.assertIn("12:00 PM or 1:00 PM", self.body(outcome))
        self.assertTrue(self.actions(message).get("location_appended"))
        self.assertEqual(self.state().invites, 1)


class LicenceBeforeFirstInvitationEvalTests(SimpleTestCase):
    def test_the_deployed_runs_pass_and_fail_without_the_fix(self):
        for reply in INVITED_88:
            with self.subTest(reply=reply[:40]):
                live = eval_answer(reply, invited=True, share_location=True, facts=FACTS_88)
                run = run_eval("shops-invitation-cut-88", live)
                self.assertEqual(run.failures, [])
                self.assertTrue(run.out.endswith(ASK_LICENCE), run.out)
                with as_it_was():
                    failures = run_eval("shops-invitation-cut-88", live).failures
                self.assertEqual(
                    failures,
                    [
                        "does not ask about the licence", 'put our location under the licence question: "Our office location:"',
                        "invited to a meeting, expected no invitation",
                    ],
                )


# C. "Who is this? Why did you call me?" --------------------------------------------------------------------------------

WHO = "Who is this? Why did you call me?"
# eval2d_deployed.log, review-why-did-you-call #1 and #2: handed over as "unclear", both.
WHO_REPLIES = (
    (
        "This is A7 Real Estate. We sent you a message about shops available for rent in International City suitable for retail, "
        "restaurants, salons, and offices. Our specialist will reply here if you want to know more or arrange a meeting.",
        "This is A7 Real Estate. We sent you a message about shops available for rent in International City suitable for retail, "
        "restaurants, salons, and offices.",
    ),
    (
        "This is A7 Real Estate regarding shops for rent in International City near Dragon Mart. Our specialist will reply here to "
        "assist you further.",
        "This is A7 Real Estate regarding shops for rent in International City near Dragon Mart.",
    ),
)
ONLY_THE_PROMISE = "Our specialist will reply here to assist you further."
# eval2d_draft_full.log, review-why-did-you-call #1: the same words handed over as "customer_asked_human", with an offer of a
# team member (no promise of a reply).
AS_A_PERSON = (
    "We are A7 Real Estate, offering shops for rent in International City near Dragon Mart. Our team did not call you; this is a "
    "message about available shops. A team member can assist you here if you want."
)


def as_the_gate_read_who():
    """Only an "unclear" taken off a burst that asks who we are, as before the deployed gate."""
    return patch.object(engine, "WHO_WE_ARE_HANDOVERS", ("unclear",))


def without_the_cut():
    """settle_handover as the gate's review left it: a reply that promises a colleague keeps the "unclear"."""
    return patch.object(engine, "who_we_are_reply", return_value="")


class WhoWeAreReplyTests(SimpleTestCase):
    def settled(self, reply, new=(WHO,), *, shops_chat=False, reason="unclear", **kwargs):
        answer_ = schema.normalize({"reply": reply, "segment": "other", "handover": {"needed": True, "reason": reason}}, shops=shops_chat)
        engine.settle_handover(answer_, [], list(new), shops_chat=shops_chat, **kwargs)
        return answer_

    def test_asked_as_a_person_wanted_is_no_handover_either(self):
        out = self.settled(AS_A_PERSON, reason="customer_asked_human")
        self.assertEqual((out["reply"], out["handover"]["needed"]), (AS_A_PERSON, False))  # an offer of a person, no promise: kept
        out = self.settled(WHO_REPLIES[1][0], reason="customer_asked_human")
        self.assertEqual((out["reply"], out["handover"]["needed"]), (WHO_REPLIES[1][1], False))
        # Asking for a person in so many words is no "Who is this?": the handover stands.
        out = self.settled(AS_A_PERSON, new=("Who is this? I want to talk to a person",), reason="customer_asked_human")
        self.assertTrue(out["handover"]["needed"])
        for reason in ("complaint_or_upset", "call_requested", "broker_or_for_client"):
            with self.subTest(reason):
                self.assertTrue(self.settled(AS_A_PERSON, reason=reason)["handover"]["needed"])
        with as_the_gate_read_who():
            self.assertEqual(self.settled(AS_A_PERSON, reason="customer_asked_human")["handover"], {"needed": True, "reason": "customer_asked_human"})

    def test_the_deployed_runs_lose_the_promise_and_the_handover(self):
        for reply, kept in WHO_REPLIES:
            with self.subTest(reply=reply[:40]):
                for shops_chat in (False, True):
                    out = self.settled(reply, shops_chat=shops_chat)
                    self.assertEqual((out["reply"], out["handover"]["needed"], out["trimmed"]), (kept, False, [engine.COLLEAGUE_REPLY]))
                with without_the_cut():
                    out = self.settled(reply)
                self.assertEqual((out["reply"], out["handover"]), (reply, {"needed": True, "reason": "unclear"}))

    def test_a_reply_that_only_promises_or_comes_after_two_invitations_keeps_it(self):
        self.assertEqual(engine.who_we_are_reply(ONLY_THE_PROMISE), "")
        out = self.settled(ONLY_THE_PROMISE)
        self.assertEqual((out["reply"], out["handover"]["needed"]), (ONLY_THE_PROMISE, True))
        self.assertNotIn("trimmed", out)
        out = self.settled(WHO_REPLIES[1][0], invites=2)
        self.assertEqual((out["reply"], out["handover"]["needed"]), (WHO_REPLIES[1][0], True))
        # Words that ask for something else are no "Who is this?": the model's handover and words stand.
        out = self.settled(WHO_REPLIES[1][0], new=("Who is this? Please call me",))
        self.assertEqual((out["reply"], out["handover"]["needed"]), (WHO_REPLIES[1][0], True))

    def test_settle_keeps_the_mark_beside_its_own(self):
        # The address typed again (the location went out already) is settle's own cut: both are listed, the gloss is dropped.
        reply = f"This is A7 Real Estate. Our office is here: {leadai_eval.ADDRESS}. {ONLY_THE_PROMISE}"
        answer_ = schema.normalize({"reply": reply, "segment": "other", "handover": {"needed": True, "reason": "unclear"}, "language": "en"})
        engine.settle(answer_, [], [WHO], 0, playbook=lane.GENERAL, now=NOW, address_sent=leadai_eval.ADDRESS)
        self.assertEqual(answer_["trimmed"], [engine.COLLEAGUE_REPLY, "location"])
        self.assertTrue(answer_["reply"].startswith("This is A7 Real Estate."), answer_["reply"])
        self.assertFalse(answer_["handover"]["needed"])


class WhoWeAreReplyTurnTests(GeneralBase):
    def test_who_we_are_goes_without_the_promise_to_nobody(self):
        reply, kept = WHO_REPLIES[1]
        message = self.inbound(WHO)
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, segment="other", handover="unclear", reply_en=reply)])
        self.assertEqual(self.body(outcome), kept)
        self.assertIsNone(self.state().handed_over_at)
        self.assertFalse(LeadAiAlert.objects.filter(kind="handover").exists())
        self.assertIn(engine.COLLEAGUE_REPLY, self.actions(message)["trimmed"])

    def test_without_the_cut_it_was_handed_over(self):
        reply, _ = WHO_REPLIES[1]
        with without_the_cut():
            outcome, _, _, _ = self.turn(self.inbound(WHO), [shop_answer(reply, segment="other", handover="unclear")])
        self.assertEqual(self.body(outcome), reply)
        self.assertIsNotNone(self.state().handed_over_at)

    def test_a_person_offered_is_no_handover(self):
        outcome, _, _, _ = self.turn(self.inbound(WHO), [shop_answer(AS_A_PERSON, segment="other", handover="customer_asked_human")])
        self.assertEqual(self.body(outcome), AS_A_PERSON)
        self.assertIsNone(self.state().handed_over_at)

    def test_without_the_fix_a_person_was_asked_for(self):
        with as_the_gate_read_who():
            self.turn(self.inbound(WHO), [shop_answer(AS_A_PERSON, segment="other", handover="customer_asked_human")])
        self.assertIsNotNone(self.state().handed_over_at)


class WhoWeAreReplyEvalTests(SimpleTestCase):
    def test_the_deployed_runs_pass_and_fail_without_the_fix(self):
        for reply, kept in WHO_REPLIES:
            with self.subTest(reply=reply[:40]):
                live = eval_answer(reply, segment="other", handover="unclear", reply_en=reply)
                run = run_eval("review-why-did-you-call", live)
                self.assertEqual((run.failures, run.out), ([], kept))
                with without_the_cut():
                    self.assertEqual(run_eval("review-why-did-you-call", live).failures, ["handover unclear, expected none"])

    def test_the_drafts_customer_asked_human_passes_and_fails_without_the_fix(self):
        live = eval_answer(AS_A_PERSON, segment="other", handover="customer_asked_human")
        self.assertEqual((run_eval("review-why-did-you-call", live).failures, run_eval("review-why-did-you-call", live).out), ([], AS_A_PERSON))
        with as_the_gate_read_who():
            self.assertEqual(run_eval("review-why-did-you-call", live).failures, ["handover customer_asked_human, expected none"])
