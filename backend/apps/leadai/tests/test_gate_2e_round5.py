"""Batch 2e's real-model gate, round 5 (2026-10-18, on the server's build context): 571 of 574 runs passed (99.5%), the
model-written ones 301 of 304 (99.0%), the shop scenarios 188 of 188, but the every-run rule failed on one policy
scenario: shops-res-invitation-two-slots #2. "Our agent can show you available studios in Spain Cluster." went out:
residential's guard took "show you available studios" for our own approved line ("take you to the available apartments").

residential.claims_availability now also cuts every sentence of the model's that the policy check's own reading flags
(availability_talk: an availability word, "we have" or "there are" beside a unit noun, outside the approved phrases).
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import residential
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

# The round-5 run's answer (eval2e_r5.log, shops-res-invitation-two-slots #2).
ROUND_5_REPLY = (
    "No problem. Normally the security deposit is around AED 2,500–3,000, refundable at tenancy end, depending on the "
    "apartment's condition. Ejari is AED 350, and DEWA requires about AED 2,000 deposit plus a connection fee. Chiller "
    "charges vary by building; our agent will confirm. Payment is usually 1 to 4 cheques. Our agent can show you available "
    "studios in Spain Cluster. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?"
)
CLAIM = "Our agent can show you available studios in Spain Cluster."


class RoundFiveRunTests(SimpleTestCase):
    def test_the_claim_goes_and_the_invitation_stays(self):
        run = run_eval("shops-res-invitation-two-slots", res_answer(ROUND_5_REPLY, invited_to_meeting=True))
        self.assertEqual(run.failures, [])
        self.assertNotIn("available studios", run.out)

    def test_it_fails_again_with_the_policy_reading_off(self):
        with patch.object(residential, "availability_talk", lambda sentence: False):
            failures = run_eval("shops-res-invitation-two-slots", res_answer(ROUND_5_REPLY, invited_to_meeting=True)).failures
        self.assertTrue(any(failure.startswith("claims a unit is available") for failure in failures), failures)


class AvailabilityTalkTests(SimpleTestCase):
    def test_what_the_policy_check_flags_is_cut(self):
        for sentence in (
            CLAIM,
            "There are two studios in France Cluster.",
            "We have nice studios in Spain Cluster.",
            "A vacant studio in Spain Cluster suits you.",
            "Would you like to see available one-bedrooms?",
            "The studio is free from next month.",
        ):
            with self.subTest(sentence):
                self.assertTrue(residential.availability_talk(sentence))
                self.assertTrue(residential.claims_availability(sentence))

    def test_the_approved_phrases_stay(self):
        for sentence in (
            "Our agent will meet you at our office and take you to the available apartments.",
            "The studio may be available next month; our agent will confirm.",
            "The price depends on the cluster and whether the unit is vacant or rented.",
            "Do you prefer a vacant unit or a tenanted one?",
            "I can hold two free slots for you today.",
            "Studios are generally around AED 29,000–33,000 a year.",
        ):
            with self.subTest(sentence):
                self.assertFalse(residential.availability_talk(sentence))
                self.assertFalse(residential.claims_availability(sentence))
