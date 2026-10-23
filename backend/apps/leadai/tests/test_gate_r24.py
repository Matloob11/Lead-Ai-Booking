"""Round 24's gate (2026-10-23): 593 of 598 (99.2%), the model's own words 316 of 320 (98.8%), but the every-run rule
failed on one code scenario, one run:

- shops-gate-half-hour #2: "Can I come today at 4:30?" got "I can hold a slot for you today at 4:00 PM or 6:00 PM" with
  "viewings start on the hour" in the English gloss and a tentative with NO date (and no time), so
  engine.upgrade_exact_time stood aside at its first line, before passed_over_hour could read the claim (rounds 11, 18
  and 22 absorbed the same claim, each time with a date on the tentative). A tentative with no day at all, over one day
  and one time of their own and the reply's own hourly or closest claim, takes their day now; any other dateless
  tentative stays the model's.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import claims
from apps.leadai.tests.test_deployed_gate_2d import CAN_I_COME, at
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_launch_gate import run_eval

FOUR_OR_SIX = (
    "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better? "
    "Our office is in Russia Cluster, Building V03, Shop 20, Dubai International City."
)
GLOSS = "Our office is open today, but viewings start on the hour. " + FOUR_OR_SIX


def dateless(reply_en):
    """The round's own answer: a tentative at the office with no date and no time."""
    return eval_answer(FOUR_OR_SIX, action="tentative", place="office", reply_en=reply_en, words=CAN_I_COME, share_location=True)


class DatelessTentativeTests(SimpleTestCase):
    def test_their_day_and_half_hour_with_the_hourly_claim_and_no_date(self):
        run = run_eval("shops-gate-half-hour", dateless(GLOSS))
        self.assertEqual((run.failures, run.when), ([], at(12, 16, 30)))
        self.assertTrue(run.upgraded)
        self.assertNotIn("on the hour", run.out)

    def test_without_the_claim_the_dateless_tentative_stays_the_models(self):
        run = run_eval("shops-gate-half-hour", dateless(""))
        self.assertNotEqual(run.when, at(12, 16, 30))
        self.assertIn("4:00 PM or 6:00 PM", run.out)
        # The guard off (no claim read anywhere): the round's answer books nothing, as before this round.
        with patch.object(claims, "says_hourly", return_value=False), patch.object(claims, "says_closest", return_value=False):
            run = run_eval("shops-gate-half-hour", dateless(GLOSS))
        self.assertNotEqual(run.when, at(12, 16, 30))
