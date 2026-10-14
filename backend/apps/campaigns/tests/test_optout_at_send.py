"""C25: an opt-out that arrives while a row is waiting holds at send time."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.campaigns.models import CampaignRecipient
from apps.campaigns.services import process_recipient


class OptOutAtSendTests(SimpleTestCase):
    @patch("apps.campaigns.services.refresh_campaign_counts")
    @patch("apps.campaigns.services.phones_blocked_by_registry", create=True)
    @patch("apps.campaigns.crm_leads.phones_blocked_by_registry")
    @patch("apps.gateway.credit.credit_is_out", return_value=False)
    @patch("apps.gateway.credit.is_no_credit", return_value=False)
    @patch("apps.campaigns.services.transaction")
    def test_registry_hit_skips_without_gateway(
        self, txn, _is_nc, _out, registry, _registry_alias, refresh
    ):
        # atomic() as a no-op context manager; select_for_update chain returns our row.
        txn.atomic.return_value.__enter__ = lambda s: None
        txn.atomic.return_value.__exit__ = lambda s, *a: False

        recipient = MagicMock()
        recipient.pk = 99
        recipient.phone = "971509998877"
        recipient.status = CampaignRecipient.Status.PENDING
        recipient.error_detail = ""
        recipient.attempt_count = 0
        recipient.campaign = MagicMock()

        qs = MagicMock()
        qs.select_related.return_value = qs
        qs.select_for_update.return_value = qs
        qs.filter.return_value.first.return_value = recipient

        registry.return_value = {"971509998877"}

        with patch(
            "apps.campaigns.services.CampaignRecipient.objects", qs
        ), patch(
            "apps.campaigns.services.ensure_owner_data"
        ) as ensure, patch(
            "apps.gateway.client.GatewayClient"
        ) as gateway:
            process_recipient(99)

        self.assertEqual(recipient.status, CampaignRecipient.Status.SKIPPED)
        self.assertEqual(recipient.error_detail, "Opted out while waiting.")
        ensure.assert_not_called()
        gateway.assert_not_called()
        refresh.assert_called_once()
        # attempt_count must not move for an opt-out hold.
        self.assertEqual(recipient.attempt_count, 0)
