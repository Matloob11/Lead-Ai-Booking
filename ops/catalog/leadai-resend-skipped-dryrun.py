"""Dry-run: resend-skipped for campaigns 681-689 and 710-725.

Prints per campaign: rows that should_resend_recipient qualifies, how many of
those phones got any template from us in the last 24 hours (round 28 will skip
those at send time), and a queue plan two campaigns at a time.

Default dry-run only. Set RESEND_SKIPPED_SEND=1 only after TASKS has
\"Lead AI round 28 live\" and Matloob's go — then this still refuses unless
RESEND_SKIPPED_CONFIRM=YES.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.campaigns.services import should_resend_recipient
from apps.inbox.models import Message

SEND = os.environ.get("RESEND_SKIPPED_SEND", "").strip() == "1"
CONFIRM = os.environ.get("RESEND_SKIPPED_CONFIRM", "").strip() == "YES"
CAMPAIGN_IDS = list(range(681, 690)) + list(range(710, 726))
MAX_IN_FLIGHT = 2
SINCE = timezone.now() - timedelta(hours=24)


def phones_templated_last_24h(phones: set[str]) -> set[str]:
    """Canonical digits that got any outbound template from us in the last 24 hours."""
    if not phones:
        return set()
    rows = (
        Message.objects.filter(
            direction=Message.Direction.OUTBOUND,
            kind=Message.Kind.TEMPLATE,
            created_at__gte=SINCE,
            conversation__contact__wa_id__in=list(phones),
        )
        .values_list("conversation__contact__wa_id", flat=True)
        .distinct()
    )
    return {"".join(ch for ch in str(p) if ch.isdigit()) for p in rows}


print(f"mode={'SEND' if SEND else 'DRY'} campaigns={CAMPAIGN_IDS[0]}-{CAMPAIGN_IDS[-1]} max_in_flight={MAX_IN_FLIGHT}")
print(f"template_lookback_since={SINCE.isoformat()}")

plan: list[tuple[int, int, int, int]] = []  # campaign_id, qualify, recent_template, would_queue
totals = Counter()

for campaign_id in CAMPAIGN_IDS:
    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if campaign is None:
        print(f"campaign={campaign_id} MISSING")
        continue
    qualify: list[CampaignRecipient] = []
    for row in campaign.recipients.order_by("id"):
        if should_resend_recipient(row.status, row.error_detail or ""):
            qualify.append(row)
    phones = {"".join(ch for ch in str(r.phone or "") if ch.isdigit()) for r in qualify}
    phones.discard("")
    recent = phones_templated_last_24h(phones)
    would_queue = [r for r in qualify if "".join(ch for ch in str(r.phone or "") if ch.isdigit()) not in recent]
    print(
        f"campaign={campaign_id} number_id={campaign.number_id} "
        f"qualify={len(qualify)} recent_template_24h={len(recent)} "
        f"would_queue_after_24h_skip={len(would_queue)} "
        f"status={campaign.status}"
    )
    plan.append((campaign_id, len(qualify), len(recent), len(would_queue)))
    totals["qualify"] += len(qualify)
    totals["recent"] += len(recent)
    totals["would_queue"] += len(would_queue)

print("queue_order (two at a time):")
batch = []
for campaign_id, qualify, recent, would in plan:
    if would <= 0 and qualify <= 0:
        continue
    batch.append(campaign_id)
    if len(batch) >= MAX_IN_FLIGHT:
        print(f"  start {batch}")
        batch = []
if batch:
    print(f"  start {batch}")

print(f"totals qualify={totals['qualify']} recent_template_24h={totals['recent']} would_queue={totals['would_queue']}")

if not SEND:
    print("dry run: nothing queued (needs round 28 live + Matloob go + RESEND_SKIPPED_SEND=1 + RESEND_SKIPPED_CONFIRM=YES)")
else:
    if CONFIRM != "YES":
        raise SystemExit("refusing SEND without RESEND_SKIPPED_CONFIRM=YES")
    raise SystemExit("SEND path not implemented in this dry-run helper; use the panel Resend skipped after go")

print("PROBE_DONE")
