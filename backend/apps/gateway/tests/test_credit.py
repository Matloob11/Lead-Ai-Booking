"""Wallet hold vs amber warn (C24). Hold only on Insufficient credits; poll warns."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.campaigns.services import campaign_has_work_left, requeue_due_retries
from apps.catalog.models import WaTemplate, WabaNumber
from apps.gateway.credit import mark_credit_out, poll_gateway_credit, record_balance, wake_retries
from apps.gateway.models import CreditState

PHRASE = "Insufficient credits. Available credits are 1.8829"


def _campaign(suffix="c24"):
    user = get_user_model().objects.create(username=f"credit-{suffix}")
    number = WabaNumber.objects.create(
        phone_number=f"9715000{suffix[-5:].zfill(5)}",
        phone_number_id=f"pid-{suffix}",
        waba_business_id=f"waba-{suffix}",
    )
    template = WaTemplate.objects.create(
        waba_business_id=f"waba-{suffix}",
        name=f"tpl_{suffix}",
        language="en",
        status=WaTemplate.Status.APPROVED,
    )
    return Campaign.objects.create(
        name=suffix,
        number=number,
        template=template,
        created_by=user,
        status=Campaign.Status.RETRYING,
    )


@override_settings(GATEWAY_CREDIT_WARN_BELOW="50")
class CreditHoldTests(TestCase):
    def setUp(self):
        self.campaign = _campaign("hold")
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
    def test_insufficient_credits_parks_and_bells_once(self, notify):
        mark_credit_out()
        mark_credit_out()
        self.exhausted.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertTrue(CreditState.objects.get(pk=1).out)
        self.assertEqual(self.exhausted.status, CampaignRecipient.Status.FAILED)
        self.assertEqual(self.exhausted.attempt_count, 0)
        self.assertIsNone(self.exhausted.next_retry_at)
        self.assertTrue(self.exhausted.error_detail.lower().startswith("no credit:"))
        self.assertEqual(self.pending.status, CampaignRecipient.Status.FAILED)
        self.assertEqual(notify.call_count, 1)
        self.assertFalse(campaign_has_work_left(self.campaign))
        self.assertEqual(requeue_due_retries(), [])

    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_poll_below_warn_is_amber_not_hold(self, notify):
        self.assertEqual(record_balance(Decimal("1.8829")), "low")
        row = CreditState.objects.get(pk=1)
        self.assertFalse(row.out)
        self.assertTrue(row.low)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, CampaignRecipient.Status.PENDING)
        self.assertEqual(notify.call_count, 1)

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
        mark_credit_out()
        self.assertEqual(record_balance(Decimal("80")), "ok")
        self.exhausted.refresh_from_db()
        self.assertFalse(CreditState.objects.get(pk=1).out)
        self.assertEqual(self.exhausted.status, CampaignRecipient.Status.FAILED)
        self.assertIsNotNone(self.exhausted.next_retry_at)
        ids = requeue_due_retries()
        self.assertIn(self.campaign.pk, ids)
        self.exhausted.refresh_from_db()
        self.assertEqual(self.exhausted.status, CampaignRecipient.Status.PENDING)
        self.assertEqual(self.exhausted.error_detail, "")

    @patch("apps.gateway.client.AlotsClient.wallet_balance", return_value="1.5")
    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_poll_uses_the_balance_endpoint(self, _notify, balance):
        self.assertEqual(poll_gateway_credit(), "low")
        balance.assert_called_once()
        row = CreditState.objects.get(pk=1)
        self.assertFalse(row.out)
        self.assertTrue(row.low)

    def test_panel_returns_out_and_low_only(self):
        CreditState.objects.create(pk=1, out=True, low=True, balance=Decimal("1.8829"))
        user = get_user_model().objects.create(username="c24-agent")
        client = APIClient()
        denied = client.get("/api/gateway/credit/")
        self.assertIn(denied.status_code, (401, 403))
        client.force_authenticate(user=user)
        body = client.get("/api/gateway/credit/").json()
        self.assertEqual(body, {"out": True, "low": True})
        self.assertNotIn("balance", body)

    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_more_than_200_parked_rows_all_requeue(self, _notify):
        mark_credit_out()
        # Extra parked rows beyond the 200 requeue cap.
        for i in range(250):
            CampaignRecipient.objects.create(
                campaign=self.campaign,
                phone=f"9715111{i:05d}",
                status=CampaignRecipient.Status.FAILED,
                error_detail="no credit: waiting for gateway credit",
                attempt_count=0,
                next_retry_at=None,
            )
        CreditState.objects.filter(pk=1).update(out=False)
        from apps.gateway.credit import release_parked

        release_parked()
        with patch("apps.campaigns.tasks.run_campaign.delay"), patch(
            "apps.campaigns.tasks.run_campaign.apply_async"
        ):
            started = wake_retries()
        self.assertIn(self.campaign.pk, started)
        pending = self.campaign.recipients.filter(status=CampaignRecipient.Status.PENDING).count()
        still_parked = self.campaign.recipients.filter(
            status=CampaignRecipient.Status.FAILED,
            error_detail__istartswith="no credit:",
            next_retry_at__isnull=True,
        ).count()
        self.assertEqual(still_parked, 0)
        self.assertGreaterEqual(pending, 200)

    @patch("apps.gateway.tasks.apply_credit_out_flag.delay")
    @patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True})
    def test_hold_survives_outer_atomic_rollback(self, _notify, delay):
        try:
            with transaction.atomic():
                mark_credit_out()
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        # Nested atomic: durable write is refused, so a Celery task is queued.
        delay.assert_called()
