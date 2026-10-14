"""Wallet hold: park sends below the threshold, release them above it, bell once an hour."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.campaigns.services import campaign_has_work_left, requeue_due_retries
from apps.catalog.models import WaTemplate, WabaNumber
from apps.gateway.credit import poll_gateway_credit, record_balance
from apps.gateway.models import CreditState

PHRASE = "Insufficient credits. Available credits are 1.8829"


def _campaign():
    user = get_user_model().objects.create(username="c16-credit")
    number = WabaNumber.objects.create(
        phone_number="971500000016",
        phone_number_id="pid-c16",
        waba_business_id="waba-c16",
    )
    template = WaTemplate.objects.create(
        waba_business_id="waba-c16",
        name="c16_credit",
        language="en",
        status=WaTemplate.Status.APPROVED,
    )
    return Campaign.objects.create(
        name="c16",
        number=number,
        template=template,
        created_by=user,
        status=Campaign.Status.RETRYING,
    )


@override_settings(GATEWAY_CREDIT_WARN_BELOW=50)
class CreditHoldTests(TestCase):
    def setUp(self):
        self.campaign = _campaign()
        self.exhausted = CampaignRecipient.objects.create(
            campaign=self.campaign,
            phone="971500000001",
            status=CampaignRecipient.Status.EXHAUSTED,
            error_detail=PHRASE,
            attempt_count=5,
        )
        self.pending = CampaignRecipient.objects.create(
            campaign=self.campaign,
            phone="971500000002",
            status=CampaignRecipient.Status.PENDING,
        )

    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_low_balance_parks_and_bells_once(self, notify):
        self.assertEqual(record_balance(Decimal("1.8829")), "out")
        self.assertEqual(record_balance(Decimal("1.8829")), "out")
        self.exhausted.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertTrue(CreditState.objects.get(pk=1).out)
        self.assertEqual(self.exhausted.status, CampaignRecipient.Status.FAILED)
        self.assertNotEqual(self.exhausted.status, CampaignRecipient.Status.EXHAUSTED)
        self.assertEqual(self.exhausted.attempt_count, 0)
        self.assertIsNone(self.exhausted.next_retry_at)
        self.assertTrue(self.exhausted.error_detail.lower().startswith("no credit:"))
        self.assertEqual(self.pending.status, CampaignRecipient.Status.FAILED)
        self.assertTrue(self.pending.error_detail.lower().startswith("no credit:"))
        self.assertEqual(notify.call_count, 1)
        self.assertFalse(campaign_has_work_left(self.campaign))
        self.assertEqual(requeue_due_retries(), [])

    def test_ordinary_retries_wait_while_credit_is_out(self):
        CreditState.objects.create(pk=1, out=True)
        CampaignRecipient.objects.create(
            campaign=self.campaign,
            phone="971500000003",
            status=CampaignRecipient.Status.FAILED,
            error_detail="gateway timeout",
            attempt_count=1,
            next_retry_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(requeue_due_retries(), [])

    @patch("apps.gateway.credit.wake_retries", return_value=[])
    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_balance_above_threshold_releases(self, _notify, _wake):
        record_balance(Decimal("1"))
        self.assertEqual(record_balance(Decimal("80")), "ok")
        self.exhausted.refresh_from_db()
        self.assertFalse(CreditState.objects.get(pk=1).out)
        self.assertEqual(self.exhausted.status, CampaignRecipient.Status.FAILED)
        self.assertIsNotNone(self.exhausted.next_retry_at)
        ids = requeue_due_retries()
        self.assertIn(self.campaign.pk, ids)
        self.exhausted.refresh_from_db()
        self.assertEqual(self.exhausted.status, CampaignRecipient.Status.PENDING)

    @patch("apps.gateway.client.AlotsClient.wallet_balance", return_value="1.5")
    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_poll_uses_the_balance_endpoint(self, _notify, balance):
        self.assertEqual(poll_gateway_credit(), "out")
        balance.assert_called_once()
        self.assertTrue(CreditState.objects.get(pk=1).out)

    def test_panel_hears_only_whether_sends_are_held(self):
        CreditState.objects.create(pk=1, out=True, balance=Decimal("1.8829"))
        user = get_user_model().objects.create(username="c16-agent")
        client = APIClient()
        denied = client.get("/api/gateway/credit/")
        self.assertIn(denied.status_code, (401, 403))
        client.force_authenticate(user=user)
        body = client.get("/api/gateway/credit/").json()
        self.assertEqual(body, {"out": True})
        self.assertNotIn("balance", body)
