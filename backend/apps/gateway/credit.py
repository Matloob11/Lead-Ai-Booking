"""Hold WhatsApp sends when the gateway wallet is too low to pay for them.

A send that comes back "Insufficient credits" is not a bad number. The
recipient waits, the rest of the pending queue waits with them, and nothing
is counted toward the five-try limit. The hourly balance check lets them go
again once the wallet is back above the threshold.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

NO_CREDIT_PREFIX = "no credit:"
WAITING_NOTE = "no credit: waiting for gateway credit"
# The board names this user when the Lead AI alert list is empty.
FALLBACK_ALERT_USER = 2311


def is_no_credit(detail: str) -> bool:
    """True for the gateway's own 'Insufficient credits' refusal."""
    return "insufficient credit" in (detail or "").lower()


def waiting_detail(detail: str) -> str:
    text = (detail or "").strip() or "waiting for gateway credit"
    if text.lower().startswith(NO_CREDIT_PREFIX):
        return text[:2000]
    return f"{NO_CREDIT_PREFIX} {text}"[:2000]


def credit_is_out() -> bool:
    from .models import CreditState

    return CreditState.objects.filter(pk=1, out=True).exists()


def threshold() -> Decimal:
    raw = getattr(settings, "GATEWAY_CREDIT_WARN_BELOW", 50)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Decimal("50")


def parse_amount(raw) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, dict):
        return None
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def park_recipient(recipient, detail: str, *, undo_attempt: bool = False) -> None:
    """Leave one recipient waiting. A credit failure does not use up a try."""
    from apps.campaigns.models import CampaignRecipient

    if undo_attempt and recipient.attempt_count:
        recipient.attempt_count = max(0, int(recipient.attempt_count) - 1)
    recipient.status = CampaignRecipient.Status.FAILED
    recipient.error_detail = waiting_detail(detail)
    recipient.next_retry_at = None
    fields = ["status", "error_detail", "next_retry_at"]
    if undo_attempt:
        fields.append("attempt_count")
    recipient.save(update_fields=fields)


def park_pending() -> int:
    """Stop every not-yet-sent row without calling the gateway."""
    from apps.campaigns.models import CampaignRecipient

    return CampaignRecipient.objects.filter(status=CampaignRecipient.Status.PENDING).update(
        status=CampaignRecipient.Status.FAILED,
        error_detail=WAITING_NOTE,
        next_retry_at=None,
    )


def reclaim_credit_failures() -> int:
    """Rows already marked exhausted by this error go back to waiting."""
    from apps.campaigns.models import CampaignRecipient

    rows = CampaignRecipient.objects.filter(
        status__in=(CampaignRecipient.Status.FAILED, CampaignRecipient.Status.EXHAUSTED),
    ).filter(
        Q(error_detail__icontains="insufficient credit") | Q(error_detail__istartswith=NO_CREDIT_PREFIX)
    )
    changed = 0
    for row in rows.iterator():
        row.status = CampaignRecipient.Status.FAILED
        row.error_detail = waiting_detail(row.error_detail)
        row.next_retry_at = None
        row.attempt_count = 0
        row.save(update_fields=["status", "error_detail", "next_retry_at", "attempt_count"])
        changed += 1
    return changed


def release_parked() -> int:
    """Credit is back: the minute retry may pick these up."""
    from apps.campaigns.models import CampaignRecipient

    return CampaignRecipient.objects.filter(
        status=CampaignRecipient.Status.FAILED,
        error_detail__istartswith=NO_CREDIT_PREFIX,
        next_retry_at__isnull=True,
    ).update(next_retry_at=timezone.now())


def alert_recipients() -> list[int]:
    ids: list[int] = []
    try:
        from apps.leadai.models import LeadAiSettings

        row = LeadAiSettings.objects.filter(pk=1).first()
        if row is not None:
            ids = [int(item) for item in row.alert_user_ids()]
    except Exception:
        logger.exception("credit alert user list")
        ids = []
    return ids or [FALLBACK_ALERT_USER]


def maybe_bell() -> bool:
    """One Bitrix bell per hour, to the Lead AI alert users."""
    from .models import CreditState

    now = timezone.now()
    with transaction.atomic():
        row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
        if row.warned_at and row.warned_at > now - timedelta(hours=1):
            return False
        row.warned_at = now
        row.save(update_fields=["warned_at", "updated_at"])

    from apps.leadai.assistant.alerts import notify_bitrix

    tag = f"LEADAI|CREDIT|{now.strftime('%Y%m%d%H')}"
    message = "WhatsApp credit is out — messages are not going"
    for user_id in alert_recipients():
        try:
            notify_bitrix(
                to_user_id=user_id,
                title="WhatsApp credit is out",
                message=message,
                push=message,
                tag=tag,
            )
        except Exception:
            logger.warning("credit bell failed for user %s", user_id)
    return True


def mark_credit_out() -> None:
    from .models import CreditState

    with transaction.atomic():
        row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
        row.out = True
        row.save(update_fields=["out", "updated_at"])
    park_pending()
    reclaim_credit_failures()
    maybe_bell()


def wake_retries() -> list[int]:
    from apps.campaigns.services import requeue_due_retries
    from apps.campaigns.tasks import run_campaign

    campaign_ids = requeue_due_retries()
    for campaign_id in campaign_ids:
        run_campaign.delay(campaign_id)
    return campaign_ids


def record_balance(amount: Decimal) -> str:
    """Store the wallet reading. Below the threshold, hold. At or above, release."""
    from .models import CreditState

    low = amount < threshold()
    with transaction.atomic():
        row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
        row.balance = amount
        row.out = low
        row.save(update_fields=["balance", "out", "updated_at"])
    if low:
        park_pending()
        reclaim_credit_failures()
        maybe_bell()
        return "out"
    released = release_parked()
    if released:
        wake_retries()
    return "ok"


def poll_gateway_credit() -> str:
    from .client import AlotsClient, AlotsError

    try:
        raw = AlotsClient().wallet_balance()
    except (AlotsError, Exception):
        logger.warning("gateway credit poll failed")
        return "error"
    amount = parse_amount(raw)
    if amount is None:
        logger.warning("gateway credit poll had no balance")
        return "error"
    return record_balance(amount)
