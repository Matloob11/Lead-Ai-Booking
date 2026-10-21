"""Batch 2e's real-model gate, round 20 (2026-10-21): 581 of 584 (99.5%), the model's own words 311 of 314 (99.0%), but
the every-run rule failed on one code scenario, one run:

- shops-res-for-myself #2: "For myself" got "Perfect, you're looking for a studio in International City. Any cluster you
  prefer, or are you flexible? Also, do you have a preferred move-in date?" — the cluster and half of step 2's first half,
  no balcony. residential.requirement_first (round 15) stood aside whenever either half was asked; now it stands aside only
  when both are, and puts code's balcony and move-in question in the questions' place otherwise (the cluster comes next
  turn, as before).
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import residential
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

CLUSTER_AND_MOVE = "Perfect, you're looking for a studio in International City. Any cluster you prefer, or are you flexible? Also, do you have a preferred move-in date?"
BALCONY_MOVE = residential._BALCONY_MOVE["en"]


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
