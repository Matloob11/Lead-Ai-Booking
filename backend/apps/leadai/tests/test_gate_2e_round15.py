"""Batch 2e's real-model gate, round 15 (2026-10-20, on the server's build context): 567 of 578 (98.1%), the model's own
words 298 of 308 (96.8%), the shop scenarios 184 of 188 (97.9%), but the every-run rule failed on two code, money and
policy scenarios, one run each:

- shops-res-for-myself #1: "For myself" got "Perfect, you're looking for a studio in International City for yourself. Any
  cluster you prefer, or are you flexible?" — step 2's cluster question before its first half (the balcony, when they
  move; brief Part 5). Now code puts the balcony and move-in question in the cluster question's place when step 1 is done
  and neither was ever asked (residential.requirement_first); the cluster comes next turn (cluster_first,
  requirement_asked_last), as shops-res-cluster-unknown expects.
- shops-nine-questions-noted-95 #1: the model's notes kept eight of his nine numbered questions (the sinks, no must-answer
  topic, so crm_facts.their_questions never added it). Now each clause of a numbered list of three lines or more that
  asks something is one of their questions whatever its topic: one no note restates is noted in their words
  (crm_facts._numbered_questions).

The other runs that failed were the model's own (shop-invite, shops-same-day-window-96, shops-food-claim-91,
shops-tap-and-question-81, shops-sale-price-early, shops-sale-price-never-hidden, shops-res-memory-asks-not-states), each
passing its other run; shops-mixed-not-known-booking failed both runs with a tentative the model held for the full name
(no code, money or policy scenario; rounds 13 and 14 passed it in every run).
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import crm_facts, residential
from apps.leadai.management.commands import leadai_eval
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

CLUSTER_ALONE = "Perfect, you're looking for a studio in International City for yourself. Any cluster you prefer, or are you flexible?"
BALCONY_MOVE = residential._BALCONY_MOVE["en"]
SINKS = "Can preparation and hand-wash sinks be installed?"
WITHOUT_SINKS = [note for note in leadai_eval.NOTES_95 if "sinks" not in note]


class RequirementFirstTests(SimpleTestCase):
    def test_the_cluster_question_alone_after_for_myself_becomes_the_balcony_and_move_in_question(self):
        answer = {"facts": {"for_client": False}}
        reply, changed = residential.requirement_first(CLUSTER_ALONE, answer, track="rent", unit="studio", facts={"property_type": "studio"}, language="en")
        self.assertTrue(changed)
        self.assertEqual(reply, f"Perfect, you're looking for a studio in International City for yourself. {BALCONY_MOVE}")
        # Who it is for known before this turn (round 2's "Yes, book a viewing"): the model's own cluster question stands.
        self.assertEqual(residential.requirement_first(CLUSTER_ALONE, answer, track="rent", unit="studio", facts={"for_client": False}, language="en"), (CLUSTER_ALONE, False))
        # Step 2's first half answered in the same breath ("For myself, with a balcony"): the cluster question stands.
        for fresh in ({"for_client": False, "balcony": "yes"}, {"for_client": False, "move_in": "next month"}):
            self.assertEqual(residential.requirement_first(CLUSTER_ALONE, {"facts": fresh}, track="rent", unit="studio", facts={}, language="en"), (CLUSTER_ALONE, False))
        earlier = [("assistant", "Perfect. Do you prefer a balcony, and when are you planning to move?"), ("customer", "no balcony")]
        self.assertEqual(residential.requirement_first(CLUSTER_ALONE, answer, track="rent", unit="studio", facts={}, earlier=earlier, language="en"), (CLUSTER_ALONE, False))
        # Step 1 not answered, the sale track, or a reply that asks the balcony itself: untouched.
        self.assertEqual(residential.requirement_first(CLUSTER_ALONE, {"facts": {}}, track="rent", unit="studio", facts={}, language="en"), (CLUSTER_ALONE, False))
        self.assertEqual(residential.requirement_first(CLUSTER_ALONE, answer, track="sale", unit="studio", facts={}, language="en"), (CLUSTER_ALONE, False))
        asks_both = "Perfect. Do you prefer a balcony, and which cluster do you prefer?"
        self.assertEqual(residential.requirement_first(asks_both, answer, track="rent", unit="studio", facts={}, language="en"), (asks_both, False))
        # In their language.
        reply, changed = residential.requirement_first(CLUSTER_ALONE, answer, track="rent", unit="studio", facts={}, language="ur_latin")
        self.assertTrue(reply.endswith(residential._BALCONY_MOVE["ur_latin"]))

    def test_the_round_15_run_passes_the_scenario_now(self):
        run = run_eval("shops-res-for-myself", res_answer(CLUSTER_ALONE, facts={"for_client": False}))
        self.assertEqual(run.failures, [])
        self.assertIn(BALCONY_MOVE, run.out)
        self.assertNotIn("Any cluster you prefer", run.out)


class NumberedQuestionsTests(SimpleTestCase):
    def test_a_numbered_question_no_note_restates_is_noted_in_their_words(self):
        self.assertEqual(crm_facts._numbered_questions([leadai_eval.NINE_QUESTIONS_95])[4], SINKS)
        notes, added = crm_facts.their_questions(WITHOUT_SINKS, [leadai_eval.NINE_QUESTIONS_95])
        self.assertEqual(added, [SINKS])
        self.assertEqual(notes, [*WITHOUT_SINKS, SINKS])
        # Every note there, in the model's words: nothing added. Restated its own way: nothing added.
        self.assertEqual(crm_facts.their_questions(list(leadai_eval.NOTES_95), [leadai_eval.NINE_QUESTIONS_95])[1], [])
        reworded = [*WITHOUT_SINKS, "sinks for preparation and hand-washing"]
        self.assertEqual(crm_facts.their_questions(reworded, [leadai_eval.NINE_QUESTIONS_95])[1], [])
        # Two numbered lines are no list; a line that asks nothing is no question.
        self.assertEqual(crm_facts._numbered_questions(["1. I am Madj.\n2. I sell desserts."]), [])
        self.assertEqual(crm_facts._numbered_questions(["1. I sell desserts.\n2. My shop is small.\n3. Is there a grease trap?"]), ["Is there a grease trap?"])
        self.assertEqual(crm_facts._numbered_questions(["1) NOC possible\n2) Can the unit get Municipality approval\n3) grease trap?"]), ["Can the unit get Municipality approval", "grease trap?"])
