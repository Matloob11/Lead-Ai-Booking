"""Keeps the local mirror of numbers and templates in step with alots.io."""

import logging

from celery import shared_task
from django.utils import timezone

from apps.gateway.client import AlotsClient

from .models import WabaNumber, WaTemplate

logger = logging.getLogger(__name__)


@shared_task
def sync_numbers():
    """Pull the channel list. Numbers are never deleted, only deactivated —
    their conversations must survive a number leaving the account."""
    client = AlotsClient()
    seen = []

    for channel in client.list_channels():
        phone_number_id = channel.get("phoneNumberId")
        if not phone_number_id:
            continue
        seen.append(phone_number_id)
        WabaNumber.objects.update_or_create(
            phone_number_id=phone_number_id,
            defaults={
                "phone_number": channel.get("wabaNumber", ""),
                "waba_business_id": channel.get("wabaBusinessId", ""),
                "is_active": True,
                "synced_at": timezone.now(),
            },
        )

    stale = WabaNumber.objects.filter(is_active=True).exclude(phone_number_id__in=seen)
    count = stale.update(is_active=False)
    logger.info("Synced %d numbers, deactivated %d", len(seen), count)
    return len(seen)


@shared_task
def sync_templates(waba_business_id=None):
    """Refresh templates for one WABA, or for every distinct WABA we know."""
    client = AlotsClient()
    if waba_business_id:
        waba_ids = [waba_business_id]
    else:
        waba_ids = list(
            WabaNumber.objects.filter(is_active=True)
            .exclude(waba_business_id="")
            .values_list("waba_business_id", flat=True)
            .distinct()
        )

    total = 0
    for waba_id in waba_ids:
        for entry in client.list_templates(waba_id):
            name = entry.get("name")
            if not name:
                continue
            WaTemplate.objects.update_or_create(
                waba_business_id=waba_id,
                name=name,
                language=entry.get("language", "en"),
                defaults={
                    "meta_template_id": str(entry.get("id", "")),
                    "category": entry.get("category", ""),
                    "status": entry.get("status", WaTemplate.Status.PENDING),
                    "components": entry.get("components", []),
                    "synced_at": timezone.now(),
                },
            )
            total += 1

    logger.info("Synced %d templates across %d WABAs", total, len(waba_ids))
    return total
