"""Batch 2e's real-model gate, round 22 (2026-10-21): 578 of 584 (99.0%), the model's own words 309 of 314 (98.4%), but
the every-run rule failed on one code scenario, one run:

- shops-gate-half-hour #2: "Can I come today at 4:30?" got "Our office is open today. The closest available slot is at
  4:00 PM or 6:00 PM. Which one works better for you?" — their half hour passed over with the claim that nearer slots are
  not there (never true: our slots are every 30 minutes), in a shape round 1's and round 11's rules do not read (one slot
  each side, the far one an hour and a half off, no hourly reason). Now "the closest / nearest / next available slot"
  beside a half hour they asked is read as the reason (claims.says_closest): engine.passed_over_hour books their own hour
  when it is free, and claims.settle cuts the sentence.
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import claims, engine, schema
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_deployed_gate_2d import CAN_I_COME, at, tentative
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_launch_gate import run_eval

CLOSEST_FOUR_OR_SIX = (
    "Our office is open today. The closest available slot is at 4:00 PM or 6:00 PM. Which one works better for you? "
    "You come to our office, and our agent will drive you to the shops and back."
)
FOUR_OR_SIX = "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?"


class ClosestSlotTests(SimpleTestCase):
    def upgrade(self, reply, said=CAN_I_COME, **proposal):
        answer = schema.normalize(tentative(reply, **({"date": "2026-10-12"} | proposal)).data, shops=True)
        return engine.upgrade_exact_time(answer, said, None, NOW)

    def test_what_says_closest_reads(self):
        for text in (CLOSEST_FOUR_OR_SIX, "The nearest available time is 5:00 PM.", "The next available viewing is at 6 PM.", "The earliest slot we have is 4:00 PM.", "No slot at 4:30."):
            with self.subTest(text):
                self.assertTrue(claims.says_closest(text))
        for text in (FOUR_OR_SIX, "Our office is open every day from 9 AM.", "The first shop is near the main road.", "", None):
            with self.subTest(text):
                self.assertFalse(claims.says_closest(text))
        self.assertTrue(claims.half_hour_asked(["Can I come today at 4:30?"]))
        self.assertFalse(claims.half_hour_asked(["Can I come today at 4?", "ok"]))

    def test_the_closest_available_slot_says_why_their_half_hour_was_passed_over(self):
        self.assertEqual(self.upgrade(CLOSEST_FOUR_OR_SIX), at(12, 16, 30))
        self.assertEqual(self.upgrade("The nearest available time is 5:00 PM today."), at(12, 16, 30))
        # Round 1's and round 11's rules stand: the plain offer either side is the model's own; their time on the hour has
        # no such reason; another day's offer is not their visit.
        self.assertIsNone(self.upgrade(FOUR_OR_SIX))
        self.assertIsNone(self.upgrade("The closest available slot is at 5:00 PM.", said="Can I come today at 4:00?"))
        self.assertIsNone(self.upgrade("The next available viewing is tomorrow at 11:00 AM.", said=CAN_I_COME))

    def test_the_sentence_goes_when_they_asked_a_half_hour(self):
        answer = schema.normalize(tentative(CLOSEST_FOUR_OR_SIX, date="2026-10-12").data, shops=True)
        cut = claims.settle(answer, ["Can I come today at 4:30?"])
        self.assertIn(claims.CLOSEST, cut)
        self.assertNotIn("closest available", answer["reply"])
        self.assertIn("Our office is open today.", answer["reply"])
        # On the hour asked: a true enough sentence, kept.
        answer = schema.normalize(tentative(CLOSEST_FOUR_OR_SIX, date="2026-10-12").data, shops=True)
        self.assertNotIn(claims.CLOSEST, claims.settle(answer, ["Can I come today at 4:00?"]))
        self.assertIn("closest available", answer["reply"])

    def test_the_round_22_run_passes_the_scenario_now(self):
        live = tentative(CLOSEST_FOUR_OR_SIX, words=CAN_I_COME, share_location=True, maker=eval_answer)
        run = run_eval("shops-gate-half-hour", live)
        self.assertEqual((run.failures, run.when), ([], at(12, 16, 30)), run.out)
        self.assertNotIn("closest available", run.out)
        self.assertNotIn("Which one works better", run.out)
