"""Deliberate writer (C29): reclaim parked credit rows and start their campaigns.

Use only when you mean to resend. Prefer ``ops/wa.sh credit-status`` to look.
"""
from apps.gateway.credit import poll_gateway_credit, reclaim_credit_failures, wake_retries
from apps.gateway.models import CreditState
from apps.campaigns.models import CampaignRecipient

status = poll_gateway_credit()
row = CreditState.objects.filter(pk=1).first()
reclaimed = reclaim_credit_failures() if (row and row.out) else 0
# Even after a recovery, parked "no credit:" rows may still be FAILED with no
# next_retry_at — wake_retries flips due parked rows and queues run_campaign.
started = wake_retries()
waiting = CampaignRecipient.objects.filter(error_detail__istartswith="no credit:").count()

print(
    "credit-release",
    f"poll={status}",
    f"out={bool(row and row.out)}",
    f"reclaimed={reclaimed}",
    f"started={len(started)}",
    f"campaign_ids={started}",
    f"waiting={waiting}",
)
