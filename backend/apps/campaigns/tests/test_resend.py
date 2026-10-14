"""Resend skipped / marketing-cap rows onto a different number."""

from django.test import SimpleTestCase

from apps.campaigns.services import should_resend_recipient


class ResendSkippedTests(SimpleTestCase):
    def test_skipped_rows_are_resent(self):
        self.assertTrue(should_resend_recipient("skipped", ""))
        self.assertTrue(
            should_resend_recipient(
                "skipped",
                "Skipped: Meta marketing daily cap already hit repeatedly on this campaign.",
            )
        )

    def test_marketing_cap_exhausted_is_resent(self):
        self.assertTrue(
            should_resend_recipient(
                "exhausted",
                "Meta marketing daily cap (131049): ecosystem engagement",
            )
        )

    def test_undeliverable_is_not_resent(self):
        self.assertFalse(
            should_resend_recipient("exhausted", "Message undeliverable (131026)")
        )

    def test_sent_and_pending_are_not_resent(self):
        self.assertFalse(should_resend_recipient("sent", ""))
        self.assertFalse(should_resend_recipient("pending", ""))
        self.assertFalse(should_resend_recipient("failed", "timeout"))

    def test_opted_out_while_waiting_is_not_resent(self):
        # C25: a row skipped for a mid-wait opt-out stays skipped.
        self.assertFalse(should_resend_recipient("skipped", "Opted out while waiting."))
        self.assertFalse(should_resend_recipient("skipped", "opted out"))
