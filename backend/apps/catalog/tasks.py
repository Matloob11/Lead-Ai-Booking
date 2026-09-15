"""Keeps the local mirror of numbers and templates in step with alots.io."""

import logging

from celery import shared_task
from django.utils import timezone

from apps.gateway.client import AlotsClient, AlotsError

from .models import WabaNumber, WaTemplate, WaTemplateHide

logger = logging.getLogger(__name__)

UNREACHABLE_WABA_TEMPLATES = (
    "Templates for this Business ID cannot be listed with the A7 gateway key."
)


def _record_template_sync(waba_id, error=""):
    WabaNumber.objects.filter(waba_business_id=waba_id).update(template_sync_error=error)


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
        existing = WabaNumber.objects.filter(phone_number_id=phone_number_id).first()
        # Admin-hidden manuals stay hidden. Alots still lists Dubai01WBX /
        # Dubai05WBX; flipping them back on would undo a roster trim.
        activate = True
        if (
            existing is not None
            and existing.source == WabaNumber.Source.MANUAL
            and not existing.is_active
        ):
            activate = False
        WabaNumber.objects.update_or_create(
            phone_number_id=phone_number_id,
            defaults={
                "phone_number": channel.get("wabaNumber", ""),
                "waba_business_id": channel.get("wabaBusinessId", ""),
                "is_active": activate,
                "synced_at": timezone.now(),
            },
        )

    # Manual rows stay active even when alots does not list them yet — an admin
    # typed those credentials in on purpose and a sync must not wipe the roster.
    stale = (
        WabaNumber.objects.filter(is_active=True, source=WabaNumber.Source.SYNC)
        .exclude(phone_number_id__in=seen)
    )
    count = stale.update(is_active=False)
    logger.info("Synced %d numbers, deactivated %d", len(seen), count)
    return len(seen)


def _active_waba_ids(waba_business_id=None):
    """Official A7 WABAs first, then manuals. One dead foreign account must not
    starve the list that agents can actually send from."""
    if waba_business_id:
        return [waba_business_id]
    qs = WabaNumber.objects.filter(is_active=True).exclude(waba_business_id="")
    ordered = []
    seen = set()
    for source in (WabaNumber.Source.SYNC, WabaNumber.Source.MANUAL):
        for waba_id in qs.filter(source=source).values_list("waba_business_id", flat=True).distinct():
            if waba_id in seen:
                continue
            seen.add(waba_id)
            ordered.append(waba_id)
    for waba_id in qs.values_list("waba_business_id", flat=True).distinct():
        if waba_id in seen:
            continue
        seen.add(waba_id)
        ordered.append(waba_id)
    return ordered


def sync_templates_detail(waba_business_id=None):
    """Refresh templates, skipping WABAs this gateway key cannot read.

    Manual numbers live on other WBBOX accounts. Listing their templates through
    A7's key returns HTTP 500; aborting the whole run for that made the library
    look empty even though a thousand approved templates were already here.
    """
    client = AlotsClient()
    waba_ids = _active_waba_ids(waba_business_id)
    total = 0
    failures = []

    for waba_id in waba_ids:
        try:
            rows = client.list_templates(waba_id) or []
        except AlotsError as exc:
            logger.warning("Template list failed for WABA %s: %s", waba_id, exc)
            failures.append({"waba_business_id": waba_id, "detail": str(exc)[:300]})
            _record_template_sync(waba_id, UNREACHABLE_WABA_TEMPLATES)
            continue
        except Exception as exc:  # noqa: BLE001 - one WABA must not stop the rest
            logger.warning("Template list crashed for WABA %s: %s", waba_id, exc)
            failures.append({"waba_business_id": waba_id, "detail": str(exc)[:300]})
            _record_template_sync(waba_id, UNREACHABLE_WABA_TEMPLATES)
            continue

        _record_template_sync(waba_id, "")
        hidden_names = WaTemplateHide.hidden_names(waba_id)

        for entry in rows:
            name = entry.get("name")
            if not name or name in hidden_names:
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

    logger.info(
        "Synced %d templates across %d WABAs (%d unreachable)",
        total,
        len(waba_ids),
        len(failures),
    )
    return total, failures


@shared_task
def sync_templates(waba_business_id=None):
    """Refresh templates for one WABA, or for every distinct WABA we know."""
    total, _failures = sync_templates_detail(waba_business_id)
    return total
