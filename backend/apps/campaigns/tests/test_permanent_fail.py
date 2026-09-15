"""Permanent Meta failures must not burn campaign retries."""

from django.test import SimpleTestCase

from apps.campaigns.failures import (
    PERMANENT_FAIL_CODES,
    is_permanent_send_failure,
    permanent_fail_label,
)


class PermanentFailTests(SimpleTestCase):
    def test_marketing_cap_code(self):
        ok, label = is_permanent_send_failure("131049", "ecosystem engagement")
        self.assertTrue(ok)
        self.assertIn("marketing", label.lower())

    def test_undeliverable_code(self):
        ok, label = is_permanent_send_failure("131026", "Message undeliverable")
        self.assertTrue(ok)
        self.assertIn("undeliverable", label.lower())

    def test_experiment_code(self):
        ok, _ = is_permanent_send_failure("130472", "experiment")
        self.assertTrue(ok)

    def test_recipient_mismatch(self):
        ok, _ = is_permanent_send_failure(
            "RECIPIENT_MISMATCH", "Gateway resolved +971 as +91971"
        )
        self.assertTrue(ok)

    def test_detail_text_without_code(self):
        ok, _ = is_permanent_send_failure("", "Meta marketing daily cap (131049): blocked")
        self.assertTrue(ok)
        ok2, _ = is_permanent_send_failure("", "Message undeliverable")
        self.assertTrue(ok2)

    def test_transient_errors_still_retry(self):
        ok, _ = is_permanent_send_failure("130429", "Rate limited")
        self.assertFalse(ok)
        ok2, _ = is_permanent_send_failure("", "Bitrix CRM timeout")
        self.assertFalse(ok2)

    def test_known_codes_set(self):
        self.assertTrue({"131049", "131026", "130472"} <= PERMANENT_FAIL_CODES)

    def test_label_helper(self):
        self.assertIn("131049", permanent_fail_label("131049", "x"))
