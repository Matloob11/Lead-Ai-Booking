"""Batch 2e's real-model gate, round 11 (2026-10-19, on the server's build context): 570 of 574 (99.3%), the model's own
words 301 of 304 (99.0%), the shop scenarios 186 of 188, but the every-run rule failed on one scenario, one run:

- shops-gate-half-hour #1: "Can I come today at 4:30?" got "Our office is open today, but viewings start on the hour. I can
  hold a slot for you at 4:00 PM or 6:00 PM — which is better?" and a tentative for today with no hour. claims.settle cut
  the hourly sentence (never true: hours.SLOT), but engine.passed_over_hour read the offer's shape alone, and "4:00 PM or
  6:00 PM" (one slot beside theirs, the other an hour and a half off on the other side) is no passing-over by round 1's
  rule. Now the reply's own hourly sentence says why their half hour was passed over, whatever else it offers on their
  day: their own hour is the visit's (claims.says_hourly, read before claims.settle cuts the sentence: upgrade_exact_time
  runs first, live and in the eval). Their time on the hour, or another day's offer, keeps round 1's rule.

The other three runs that failed were the model's own (shop-invite, shops-same-day-window-96, lang-inshallah-english),
each passing its other run; none is a code, money or policy scenario.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import claims, engine, schema
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_deployed_gate_2d import CAN_I_COME, at, tentative
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_launch_gate import run_eval

# The round-11 run's answer (eval2e_r11.log, shops-gate-half-hour #1): the reply before claims cut its first sentence.
HOURLY_FOUR_OR_SIX = "Our office is open today, but viewings start on the hour. I can hold a slot for you at 4:00 PM or 6:00 PM — which is better?"
FOUR_OR_SIX = "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?"
HOURLY_ALONE = "Our slots start on the hour. Which hour suits you today?"


class HourlySaidTests(SimpleTestCase):
    def upgrade(self, reply, said=CAN_I_COME, **proposal):
        answer = schema.normalize(tentative(reply, **({"date": "2026-10-12"} | proposal)).data, shops=True)
        return engine.upgrade_exact_time(answer, said, None, NOW)

    def test_the_hourly_sentence_says_why_their_half_hour_was_passed_over(self):
        self.assertEqual(self.upgrade(HOURLY_FOUR_OR_SIX), at(12, 16, 30))
        self.assertEqual(self.upgrade(HOURLY_ALONE), at(12, 16, 30))
        self.assertEqual(self.upgrade("Viewings are hourly, so I can hold 5:00 PM for you today.", time="17:00"), at(12, 16, 30))

    def test_round_ones_rule_stands_without_it(self):
        self.assertIsNone(self.upgrade(FOUR_OR_SIX))
        # Their time on the hour: no hourly reason applies to it.
        self.assertIsNone(self.upgrade(HOURLY_FOUR_OR_SIX, said="Can I come today at 4:00?"))
        # Another day's offer is not their visit, hourly or not.
        self.assertIsNone(self.upgrade("Viewings start on the hour. I can hold tomorrow at 11:00 AM or 5:00 PM for you."))
        # The model's own hour far from theirs: its choice, not a passing-over.
        self.assertIsNone(self.upgrade("Viewings are hourly, so I can hold 7:00 PM for you today.", time="19:00"))

    def test_what_says_hourly_reads(self):
        for text in (HOURLY_FOUR_OR_SIX, HOURLY_ALONE, "We only book full hours.", "Hamare slots har ghante par hote hain."):
            with self.subTest(text):
                self.assertTrue(claims.says_hourly(text))
        for text in (FOUR_OR_SIX, "Our office is open every day from 9 AM.", "", None):
            with self.subTest(text):
                self.assertFalse(claims.says_hourly(text))


class HalfHourEvalTests(SimpleTestCase):
    def test_the_round_11_run_passes_now_and_fails_with_the_sentence_unread(self):
        live = tentative(HOURLY_FOUR_OR_SIX, words=CAN_I_COME, share_location=True, maker=eval_answer)
        run = run_eval("shops-gate-half-hour", live)
        self.assertEqual((run.failures, run.when), ([], at(12, 16, 30)))
        self.assertNotIn("on the hour", run.out)
        with patch.object(claims, "says_hourly", return_value=False):
            self.assertNotEqual(run_eval("shops-gate-half-hour", live).failures, [])
