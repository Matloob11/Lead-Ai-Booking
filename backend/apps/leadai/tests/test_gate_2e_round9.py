"""Batch 2e's real-model gate, round 9 (2026-10-19, on the server's build context): 568 of 574 (99.0%), the model's own
words 298 of 304 (98.0%), the shop scenarios 187 of 188, but the every-run rule failed on one money scenario:
shops-res-monthly-figure #1. "how much per month?" got "Rent is yearly in International City, usually paid in 1 to 4
cheques depending on the owner." with no band at all: nothing monthly to cut, so code added nothing.

residential.settle now adds the yearly band when the customer asked by the month and the reply holds no band, as it does
when it cuts a monthly figure.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import residential
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

# The round-9 run's answer (eval2e_r9.log, shops-res-monthly-figure #1).
ROUND_9_REPLY = (
    "Rent is yearly in International City, usually paid in 1 to 4 cheques depending on the owner. Any cluster you prefer, "
    "or are you flexible?"
)


class MonthlyAskWithNoBandTests(SimpleTestCase):
    def test_the_band_goes_with_how_it_is_paid(self):
        run = run_eval("shops-res-monthly-figure", res_answer(ROUND_9_REPLY))
        self.assertEqual(run.failures, [])
        self.assertIn("29,000", run.out)
        self.assertIn("monthly_band", run.answer.get("trimmed") or [])

    def test_it_fails_again_with_the_fix_off(self):
        with patch.object(residential, "asks_monthly", lambda texts: False):
            failures = run_eval("shops-res-monthly-figure", res_answer(ROUND_9_REPLY)).failures
        self.assertTrue(any(f.startswith("does not quote AED 29,000") for f in failures), failures)

    def test_a_reply_that_holds_the_band_gets_no_second_one(self):
        reply = "Studios in International City are generally around AED 29,000–33,000 a year, paid in 1 to 4 cheques. Any cluster you prefer?"
        run = run_eval("shops-res-monthly-figure", res_answer(reply))
        self.assertEqual(run.failures, [])
        self.assertEqual(run.out.count("29,000"), 1)
        self.assertNotIn("monthly_band", run.answer.get("trimmed") or [])

    def test_a_monthly_figure_is_still_cut_and_the_band_added(self):
        reply = "Studios are around AED 29,000–33,000 a year, so roughly AED 2,500 a month. Any cluster you prefer?"
        run = run_eval("shops-res-monthly-figure", res_answer(reply))
        self.assertEqual(run.failures, [])
        self.assertNotIn("2,500", run.out)
        self.assertIn("monthly", run.answer.get("trimmed") or [])
