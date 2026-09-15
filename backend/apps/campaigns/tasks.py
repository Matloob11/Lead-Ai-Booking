"""Celery runner for campaign sends — paced sends + 5‑minute auto-retry of failures."""

from __future__ import annotations

import logging
import time

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from .models import Campaign, CampaignRecipient
from .services import campaign_has_work_left, process_recipient, refresh_campaign_counts, requeue_due_retries

logger = logging.getLogger(__name__)

SEND_GAP_SEC = 1.5
RUN_LOCK_TTL = 60 * 60  # one hour — longer than a 500-recipient paced run


@shared_task(ignore_result=True)
def run_campaign(campaign_id: int) -> None:
    lock_key = f"campaign:run:{campaign_id}"
    if not cache.add(lock_key, "1", timeout=RUN_LOCK_TTL):
        logger.info("Campaign %s already running — skip duplicate worker", campaign_id)
        return

    try:
        _run_campaign_locked(campaign_id)
    finally:
        cache.delete(lock_key)


def _run_campaign_locked(campaign_id: int) -> None:
    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if not campaign:
        return
    if campaign.status == Campaign.Status.CANCELLED:
        return
    if campaign.status == Campaign.Status.DONE and not campaign_has_work_left(campaign):
        return

    is_retry_wave = bool(campaign.started_at)
    campaign.status = Campaign.Status.RETRYING if is_retry_wave else Campaign.Status.RUNNING
    updates = ["status", "finished_at"]
    campaign.finished_at = None
    if not campaign.started_at:
        campaign.started_at = timezone.now()
        updates.append("started_at")
    campaign.save(update_fields=updates)

    ids = list(
        campaign.recipients.filter(status=CampaignRecipient.Status.PENDING)
        .order_by("id")
        .values_list("id", flat=True)
    )

    for i, rid in enumerate(ids):
        if Campaign.objects.filter(pk=campaign_id, status=Campaign.Status.CANCELLED).exists():
            break
        try:
            process_recipient(rid)
        except Exception:  # noqa: BLE001
            logger.exception("Campaign %s recipient %s crashed", campaign_id, rid)
        if i < len(ids) - 1:
            time.sleep(SEND_GAP_SEC)

    campaign = Campaign.objects.filter(pk=campaign_id).first()
    if not campaign:
        return
    refresh_campaign_counts(campaign)
    if campaign.status == Campaign.Status.CANCELLED:
        campaign.finished_at = timezone.now()
        campaign.save(update_fields=["finished_at", "sent", "failed", "skipped"])
        return

    if campaign_has_work_left(campaign):
        campaign.status = Campaign.Status.RETRYING
        campaign.finished_at = None
        campaign.save(update_fields=["status", "finished_at", "sent", "failed", "skipped"])
    else:
        campaign.status = Campaign.Status.DONE
        campaign.finished_at = timezone.now()
        campaign.save(update_fields=["status", "finished_at", "sent", "failed", "skipped"])


@shared_task(ignore_result=True)
def retry_due_campaign_recipients() -> None:
    """Beat: every minute, re-queue failed recipients whose 5‑minute wait is over."""
    campaign_ids = requeue_due_retries(limit=200)
    for cid in campaign_ids:
        run_campaign.delay(cid)
    if campaign_ids:
        logger.info("Campaign retry wave for campaigns %s", campaign_ids)
