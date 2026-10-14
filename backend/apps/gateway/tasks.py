"""Turns raw alots.io callbacks into conversations and messages.

Runs out of band so the webhook endpoint can answer immediately. Every event is
already persisted before this starts, so a failure here is recoverable: fix the
parser, then replay the pending rows.
"""

import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import WabaNumber

from .ingest import apply_status, iter_message_blobs, store_message
from .media import download_media  # noqa: F401 — celery autodiscovery
from .models import WebhookEvent
from .parse import digits, normalize_webhook_payload

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def panel_keepalive():
    """Keep the alots panel session alive — see apps/gateway/panel.py."""
    from .panel import keepalive_session

    return keepalive_session()


@shared_task(ignore_result=True)
def poll_gateway_credit():
    """Hourly wallet check. Below the threshold, hold sends and warn once."""
    from .credit import poll_gateway_credit as poll

    return poll()


def _resolve_waba_number(value):
    """Match catalog row by Meta phone_number_id, or by our MSISDN on ``from``.

    Alots often omits ``metadata.phone_number_id`` on flat phone-app outbound
    webhooks; ``from`` / ``display_phone_number`` still carry our channel digits.

    Coexistence WBX rows sometimes ship a typo'd phone_number_id that is not in
    catalog — always fall through to ``display_phone_number`` / echo ``from``.
    """
    metadata = value.get("metadata") or {}
    phone_number_id = str(metadata.get("phone_number_id") or "").strip()
    if phone_number_id:
        number = WabaNumber.objects.filter(phone_number_id=phone_number_id).first()
        if number:
            return number

    display = digits(metadata.get("display_phone_number"))
    if not display:
        for blob, _force in iter_message_blobs(value):
            display = digits(blob.get("from")) or digits(blob.get("display_phone_number"))
            if display:
                break
    if display:
        return WabaNumber.objects.filter(phone_number=display).first()
    return None


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_webhook_event(self, event_id):
    event = WebhookEvent.objects.filter(pk=event_id).first()
    if not event or event.status == WebhookEvent.Status.PROCESSED:
        return

    event.attempts += 1

    handled = False
    item_errors: list[str] = []

    try:
        payload = normalize_webhook_payload(event.payload or {})
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                number = _resolve_waba_number(value)

                if not number:
                    meta = value.get("metadata") or {}
                    logger.warning(
                        "Webhook for unknown number phone_number_id=%s display=%s",
                        meta.get("phone_number_id", ""),
                        meta.get("display_phone_number", ""),
                    )
                    continue

                metadata = value.get("metadata") or {}
                # Fill empty phone_number_id so media/download paths still work.
                if not metadata.get("phone_number_id") and number.phone_number_id:
                    metadata = {**metadata, "phone_number_id": number.phone_number_id}
                profiles = {
                    c.get("wa_id", ""): (c.get("profile") or {}).get("name", "")
                    for c in value.get("contacts") or []
                }
                for blob, force_outbound in iter_message_blobs(value):
                    try:
                        with transaction.atomic():
                            store_message(
                                number,
                                blob,
                                profiles,
                                metadata,
                                force_outbound=force_outbound,
                            )
                        handled = True
                    except Exception as exc:  # noqa: BLE001
                        item_errors.append(f"message:{type(exc).__name__}:{exc}")
                        logger.exception(
                            "Webhook message failed in event %s (continuing batch)", event_id
                        )
                for status_entry in value.get("statuses") or []:
                    try:
                        with transaction.atomic():
                            apply_status(number, status_entry)
                        handled = True
                    except Exception as exc:  # noqa: BLE001
                        item_errors.append(f"status:{type(exc).__name__}:{exc}")
                        logger.exception(
                            "Webhook status failed in event %s (continuing batch)", event_id
                        )
        if handled:
            event.status = WebhookEvent.Status.PROCESSED
            event.error = ("; ".join(item_errors))[:2000]
            from django.core.cache import cache

            if cache.add("wa_placeholder_backfill_v4", "1", 6 * 3600):
                backfill_placeholder_bodies.delay()
        elif item_errors:
            event.status = WebhookEvent.Status.FAILED
            event.error = ("; ".join(item_errors))[:2000]
            event.processed_at = timezone.now()
            event.save(update_fields=["status", "processed_at", "error", "attempts"])
            raise RuntimeError(item_errors[0])
        else:
            event.status = WebhookEvent.Status.IGNORED
            event.error = ""

        event.processed_at = timezone.now()
    except Exception as exc:  # noqa: BLE001 - the raw event must never be lost
        if event.status != WebhookEvent.Status.FAILED:
            event.status = WebhookEvent.Status.FAILED
            event.error = f"{type(exc).__name__}: {exc}"
        event.save(update_fields=["status", "error", "attempts"])
        logger.exception("Failed to process webhook event %s", event_id)
        raise self.retry(exc=exc)

    event.save(update_fields=["status", "processed_at", "error", "attempts"])
