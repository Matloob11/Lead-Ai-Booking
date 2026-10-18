"""Batch 2e's real-model gate, round 4 (2026-10-17, on the server's build context): 568 of 574 runs passed (99.0%), the
model-written ones 299 of 304 (98.4%), but the every-run rule failed on one money-or-policy scenario:
shops-res-owner-number #2. "Give me the owner's number please", in a rent chat that had said "for myself", was tagged
broker_or_for_client, so the broker line, a pause and the Broker label went out where code answers (res_no_number and our
office, Q38).

residential.unasked_broker takes that tag off, in engine.settle before anything reads the handover, but only over a
number ask alone (number_ask_alone): any other word of theirs keeps the model's tag. Round 5's review showed why no list of
broker words may decide it: every list tried missed brokers ("I'm a property manager", "أنا وكيل", "Requirement hai mere
paas") and lifted a complaint's, a legal question's or a person's handover beside a number ask.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import residential, schema
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

BROKER = "broker_or_for_client"
# The round-4 run's answer (eval2e_r4.log, shops-res-owner-number #2).
ROUND_4_REPLY = (
    "I'm AR Properties' virtual assistant — I can help with options and viewings, and connect you to our agent anytime. "
    "I can't share the owner's number, but our agent will assist you with all details and arrange viewings. I can hold a "
    "slot for you today at 3:00 PM or 5:00 PM — which is better?"
)
OWNER_ASK = ["Give me the owner's number please"]
FOR_MYSELF = [("assistant", "Are you looking for yourself or for a client?"), ("customer", "For myself")]


def tagged(**facts):
    return schema.normalize(res_answer(ROUND_4_REPLY, handover=BROKER, facts=facts).data, shops=True, residential=True)


def untag(answer, texts=OWNER_ASK, earlier=FOR_MYSELF, known=None, track=residential.RENT):
    known = {"for_client": False} if known is None else known
    return residential.unasked_broker(answer, texts, earlier, known=known, track=track)


class RoundFourRunTests(SimpleTestCase):
    def test_the_owners_number_gets_codes_line_and_our_office(self):
        run = run_eval("shops-res-owner-number", res_answer(ROUND_4_REPLY, handover=BROKER))
        self.assertEqual(run.failures, [])
        self.assertIn("unasked_broker", run.answer.get("trimmed") or [])

    def test_also_when_the_model_says_for_a_client_against_the_chat(self):
        # RENT_KNOWN says for myself: a number ask alone changes nothing they said about themselves.
        run = run_eval("shops-res-owner-number", res_answer(ROUND_4_REPLY, handover=BROKER, facts={"for_client": True}))
        self.assertEqual(run.failures, [])

    def test_it_fails_again_with_the_guard_off(self):
        with patch.object(residential, "unasked_broker", lambda *args, **kwargs: ""):
            failures = run_eval("shops-res-owner-number", res_answer(ROUND_4_REPLY, handover=BROKER)).failures
        self.assertIn("handover broker_or_for_client, expected none", failures)

    def test_the_tag_goes_with_the_words_that_promise_an_agent(self):
        answer = tagged()
        self.assertEqual(untag(answer), BROKER)
        self.assertFalse(answer["handover"]["needed"])
        self.assertNotIn("connect you to our agent", answer["reply"])
        self.assertNotIn("our agent will assist", answer["reply"])


class NumberAskAloneTests(SimpleTestCase):
    def test_a_number_ask_with_nothing_else(self):
        for texts in (
            ["Give me the owner's number please"],
            ["Hi", "Owner's number pls"],
            ["What is the owner's number?"],
            ["Can you share your number?"],
            ["Owner number please sir"],
            ["Your number please 🙏"],
        ):
            with self.subTest(texts):
                self.assertTrue(residential.number_ask_alone(texts))

    def test_anything_else_beside_it(self):
        for texts in (
            # A broker in words no list holds (round 5's review): the words themselves keep the tag.
            ["I'm a property manager, owner's number please"],
            ["أنا وكيل، رقم المالك لو سمحت"],
            ["I have someone interested in this studio, owner's number please"],
            ["Looking for a studio for an end user, owner's number please"],
            ["Agent here, owner's number please"],
            ["Broker Ali here, owner's number pls"],
            ["I'm a broker", "Give me the owner's number please"],
            # A complaint, a legal question, a time, their own number, media of theirs.
            ["Your agent never showed up. Give me the owner's number"],
            ["I need the owner's number for the Ejari registration"],
            ["5 PM today is fine. And the owner's number please"],
            ["My number is 0501234567"],
            ["[document you cannot see]", "Owner's number please"],
            ["[voice note could not be heard]", "Owner's number please"],
            # No number asked at all, courtesies only included.
            ["Please share pictures of the studio"],
            ["Hi"],
            ["Thank you sir", "Ok"],
        ):
            with self.subTest(texts):
                self.assertFalse(residential.number_ask_alone(texts))


class QElevenTests(SimpleTestCase):
    """A broker, an agent or someone sourcing for a client keeps the broker line and the pause (Q11)."""

    def test_any_other_word_keeps_the_tag(self):
        for texts in (
            ["I'm a property manager, owner's number please"],
            ["Requirement hai mere paas, owner's number do"],
            ["I've got an applicant ready with the deposit, owner's number pls"],
            ["عندي طلب على استوديو، رقم المالك"],
            ["This is Sara from Exclusive Links, owner's number please"],
        ):
            with self.subTest(texts):
                answer = tagged()
                self.assertEqual(untag(answer, texts=texts), "")
                self.assertEqual(answer["handover"]["reason"], BROKER)

    def test_an_earlier_message_of_theirs_as_a_broker_keeps_it(self):
        for earlier in (
            [("customer", "I'm a real estate broker")],
            [("assistant", "Are you looking for yourself or for a client?"), ("customer", "For a client")],
            [("assistant", "Are you looking for yourself or for a client?"), ("customer", "Agent")],
        ):
            with self.subTest(earlier):
                answer = tagged()
                self.assertEqual(untag(answer, earlier=earlier, known={}), "")
                self.assertTrue(answer["handover"]["needed"])

    def test_the_chat_saying_for_a_client_keeps_it(self):
        answer = tagged()
        self.assertEqual(untag(answer, known={"for_client": True}), "")
        self.assertTrue(answer["handover"]["needed"])

    def test_the_models_client_where_nothing_ruled_it_out_keeps_it(self):
        answer = tagged(for_client=True)
        self.assertEqual(untag(answer, earlier=[], known={}), "")
        self.assertTrue(answer["handover"]["needed"])

    def test_the_models_client_against_for_myself_comes_off_with_the_fact(self):
        answer = tagged(for_client=True)
        self.assertEqual(untag(answer), BROKER)
        self.assertIs(answer["facts"]["for_client"], False)

    def test_a_booking_or_an_opt_out_in_the_answer_keeps_it(self):
        booked = tagged()
        booked["appointment"]["action"] = "tentative"
        self.assertEqual(untag(booked), "")
        stopped = tagged()
        stopped["opt_out"] = "stop_all"
        self.assertEqual(untag(stopped), "")

    def test_only_on_the_rent_and_sale_tracks_and_only_the_broker_tag(self):
        self.assertEqual(untag(tagged(), track=residential.UNKNOWN), "")
        other = schema.normalize(res_answer(ROUND_4_REPLY, handover="customer_asked_human").data, shops=True, residential=True)
        self.assertEqual(untag(other), "")
        self.assertEqual(other["handover"]["reason"], "customer_asked_human")

    def test_the_sale_track_too(self):
        answer = tagged()
        self.assertEqual(untag(answer, track=residential.SALE), BROKER)


class MustNotFireTests(SimpleTestCase):
    """Round 5's review: a person asked for, a complaint, a legal question or media of theirs beside a number ask keeps
    the model's handover, whatever list of words would have missed it."""

    def test_the_broker_tag_stays_beside_anything_else(self):
        for texts in (
            ["Please connect me with the agent who posted this, or send me the owner's number"],
            ["This is ridiculous, give me the landlord's number please"],
            ["Bakwas service hai, owner's number do"],
            ["Can the landlord evict me before the contract ends? Owner's number please"],
            ["[shared a contact card: Ahmed]", "Owner's number please"],
        ):
            with self.subTest(texts):
                answer = tagged()
                self.assertEqual(untag(answer, texts=texts), "")
                self.assertEqual(answer["handover"]["reason"], BROKER)
