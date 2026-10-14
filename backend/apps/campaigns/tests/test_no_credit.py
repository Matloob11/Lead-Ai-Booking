"""A gateway credit refusal waits. It does not use up the five tries."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.campaigns.models import CampaignRecipient
from apps.campaigns.services import _mark_send_failed
from apps.gateway.credit import is_no_credit

PHRASE = "Insufficient credits. Available credits are 1.8829"


class _Row:
    def __init__(self, attempt_count):
        self.attempt_count = attempt_count
        self.status = CampaignRecipient.Status.PENDING
        self.error_detail = ""
        self.next_retry_at = "set"
        self.saved = None

    def save(self, update_fields=None):
        self.saved = update_fields


class NoCreditSendTests(SimpleTestCase):
    def test_phrase(self):
        self.assertTrue(is_no_credit(PHRASE))
        self.assertFalse(is_no_credit("gateway timeout"))

    @patch("apps.gateway.credit.mark_credit_out")
    def test_credit_failure_waits_and_does_not_exhaust(self, mark):
        row = _Row(5)
        _mark_send_failed(row, PHRASE)
        self.assertEqual(row.status, CampaignRecipient.Status.FAILED)
        self.assertNotEqual(row.status, CampaignRecipient.Status.EXHAUSTED)
        self.assertEqual(row.attempt_count, 4)
        self.assertIsNone(row.next_retry_at)
        self.assertTrue(row.error_detail.lower().startswith("no credit:"))
        mark.assert_called_once()

    def test_ordinary_failure_still_retries(self):
        row = _Row(1)
        _mark_send_failed(row, "gateway timeout")
        self.assertEqual(row.status, CampaignRecipient.Status.FAILED)
        self.assertEqual(row.attempt_count, 1)
        self.assertIsNotNone(row.next_retry_at)

    def test_ordinary_failure_still_exhausts(self):
        row = _Row(5)
        _mark_send_failed(row, "gateway timeout")
        self.assertEqual(row.status, CampaignRecipient.Status.EXHAUSTED)
        self.assertIsNone(row.next_retry_at)
