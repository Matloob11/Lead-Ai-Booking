"""Batch 2e's real-model gate, round 20 (2026-10-21): 581 of 584 (99.5%), the model's own words 311 of 314 (99.0%), but
the every-run rule failed on one code scenario, one run; the second full gate (579 of 584) on another, one run:

- shops-res-for-myself #2: "For myself" got "Perfect, you're looking for a studio in International City. Any cluster you
  prefer, or are you flexible? Also, do you have a preferred move-in date?" — the cluster and half of step 2's first half,
  no balcony. residential.requirement_first (round 15) stood aside whenever either half was asked; now it stands aside only
  when both are, and puts code's balcony and move-in question in the questions' place otherwise (the cluster comes next
  turn, as before).
- shops-res-invitation-two-slots #1: "Just me" to our "Will it be for yourself, your family, or company staff?" got "No
  problem. Will it be a contract in your name?" — step 3's contract question, which is for a shared or company stay, and
  no invitation. Now code puts its invitation with two free slots in the step-3 questions' place when our side asked who
  will stay and their words say just them (engine.alone_invitation; residential.alone_said, asks_contract).
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import engine, hours, residential
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_gate_2e_round1 import normal
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

CLUSTER_AND_MOVE = "Perfect, you're looking for a studio in International City. Any cluster you prefer, or are you flexible? Also, do you have a preferred move-in date?"
BALCONY_MOVE = residential._BALCONY_MOVE["en"]
CONTRACT_ASKED = "No problem. Will it be a contract in your name?"
OCCUPANCY_ASKED = "Perfect, the Spain Cluster studio. Will it be for yourself, your family, or company staff?"


class AloneInvitationTests(SimpleTestCase):
    def test_their_words_and_the_contract_question(self):
        for text in ("Just me", "Only me", "just myself", "I will be staying alone", "Alone", "sirf main", "main akela hoon", "لوحدي", "Myself only", "Only for me"):
            with self.subTest(text=text):
                self.assertTrue(residential.alone_said([text]))
        for text in ("Just me and my wife", "Me and a friend", "My family", "We are 3", "For my company staff", "Sharing with friends", "ok", "", "Yes, book it"):
            with self.subTest(text=text):
                self.assertFalse(residential.alone_said([text]))
        self.assertTrue(residential.asks_contract("Will it be a contract in your name?"))
        self.assertTrue(residential.asks_contract("Would the contract be in your name or the company's?"))
        self.assertFalse(residential.asks_contract("The contract will be in your name."))
        self.assertFalse(residential.asks_contract("Which cluster do you prefer?"))

    def settle(self, reply, said="Just me", earlier=None, slots=None, **kwargs):
        answer = normal(res_answer(reply))
        earlier = [("assistant", OCCUPANCY_ASKED)] if earlier is None else earlier
        engine.settle(
            answer, earlier, [said], 0, playbook="ic_shops", now=NOW, residential=True, track="rent",
            slots=hours.offer_pair(NOW) if slots is None else slots, **kwargs,
        )
        return answer

    def test_the_contract_question_to_one_person_becomes_the_invitation(self):
        answer = self.settle(CONTRACT_ASKED)
        self.assertEqual(answer["reply"], f"No problem. {residential.invite_text('en', hours.offer_pair(NOW), NOW)}")
        self.assertTrue(answer["invited_to_meeting"])
        self.assertIn("alone_invitation", answer["trimmed"])
        # The model's answer to something they asked stays; only step 3's questions go.
        answer = self.settle("Yes, a balcony is possible. How many people will stay?", said="Just me. Is a balcony possible?")
        self.assertTrue(answer["reply"].startswith("Yes, a balcony is possible. Our agent will meet you"))
        # Untouched: someone beside them; our last message asked something else; the reply invites itself; the chat may
        # not be invited (no slots); the sale track; an opt-out or a handover.
        self.assertEqual(self.settle(CONTRACT_ASKED, said="Me and my wife")["reply"], CONTRACT_ASKED)
        self.assertEqual(self.settle(CONTRACT_ASKED, earlier=[("assistant", "Any cluster you prefer, or are you flexible?")])["reply"], CONTRACT_ASKED)
        self.assertEqual(self.settle(CONTRACT_ASKED, slots=[])["reply"], CONTRACT_ASKED)
        self.assertEqual(self.settle(CONTRACT_ASKED, track="sale")["reply"], CONTRACT_ASKED)
        invited = "No problem. Our agent will meet you at our office. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?"
        self.assertNotIn("alone_invitation", self.settle(invited).get("trimmed") or [])
        held = normal(res_answer(CONTRACT_ASKED, handover="unclear"))
        engine.settle(held, [("assistant", OCCUPANCY_ASKED)], ["Just me"], 0, playbook="ic_shops", now=NOW, residential=True, track="rent", slots=hours.offer_pair(NOW))
        self.assertNotIn("alone_invitation", held.get("trimmed") or [])

    def test_the_round_20_run_passes_the_scenario_now(self):
        run = run_eval("shops-res-invitation-two-slots", res_answer(CONTRACT_ASKED))
        self.assertEqual(run.failures, [], run.out)
        self.assertIn("PM or", run.out)
        self.assertNotIn("contract", run.out.lower())
        self.assertTrue(run.answer["invited_to_meeting"])
        with patch.object(engine, "alone_invitation", return_value=False):
            self.assertIn("did not invite to a meeting", run_eval("shops-res-invitation-two-slots", res_answer(CONTRACT_ASKED)).failures)


class HalfOfStepTwoTests(SimpleTestCase):
    def test_the_readers(self):
        for text in ("Do you prefer a balcony?", "Would you like a balcony, and which cluster?", "کیا آپ بالکونی پسند کریں گے؟"):
            self.assertTrue(residential.asks_balcony(text), text)
            self.assertFalse(residential.asks_move_in(text), text)
        for text in ("Also, do you have a preferred move-in date?", "When are you planning to move?", "Aap kab shift hona chahte hain?", "When would you like to move in?"):
            self.assertTrue(residential.asks_move_in(text), text)
            self.assertFalse(residential.asks_balcony(text), text)
        self.assertTrue(residential.asks_balcony(BALCONY_MOVE) and residential.asks_move_in(BALCONY_MOVE))
        self.assertFalse(residential.asks_balcony("The studio has a balcony."))  # no question
        self.assertFalse(residential.asks_move_in("Any cluster you prefer, or are you flexible?"))

    def test_the_cluster_and_the_move_in_alone_become_the_balcony_and_move_in_question(self):
        answer = {"facts": {"for_client": False}}
        reply, changed = residential.requirement_first(CLUSTER_AND_MOVE, answer, track="rent", unit="studio", facts={"property_type": "studio"}, language="en")
        self.assertTrue(changed)
        self.assertEqual(reply, f"Perfect, you're looking for a studio in International City. {BALCONY_MOVE}")
        # The move-in alone, no cluster: the same. The balcony alone: the same. Both halves: the model's own stands.
        for text in ("Great. When are you planning to move?", "Great. Do you prefer a balcony?"):
            reply, changed = residential.requirement_first(text, answer, track="rent", unit="studio", facts={}, language="en")
            self.assertEqual((reply, changed), (f"Great. {BALCONY_MOVE}", True), text)
        both = "Great. Do you prefer a balcony? And when are you planning to move in?"
        self.assertEqual(residential.requirement_first(both, answer, track="rent", unit="studio", facts={}, language="en"), (both, False))
        # Nothing of step 2 asked (the model answered something else): untouched here.
        other = "Great. Studios in International City start around AED 29,000 a year."
        self.assertEqual(residential.requirement_first(other, answer, track="rent", unit="studio", facts={}, language="en"), (other, False))
        # The move-in known already (said in the same breath): the model's cluster question stands.
        self.assertEqual(residential.requirement_first(CLUSTER_AND_MOVE, {"facts": {"for_client": False, "move_in": "next month"}}, track="rent", unit="studio", facts={}, language="en"), (CLUSTER_AND_MOVE, False))

    def test_the_round_20_run_passes_the_scenario_now(self):
        run = run_eval("shops-res-for-myself", res_answer(CLUSTER_AND_MOVE, facts={"for_client": False}))
        self.assertEqual(run.failures, [], run.out)
        self.assertIn(BALCONY_MOVE, run.out)
        self.assertNotIn("Any cluster you prefer", run.out)
        self.assertNotIn("preferred move-in date", run.out)
