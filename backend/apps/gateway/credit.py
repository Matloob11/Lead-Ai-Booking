"""Hold WhatsApp sends when the gateway wallet refuses them.

A send that comes back "Insufficient credits" is not a bad number. The
recipient waits, the rest of the pending queue waits with them, and nothing
is counted toward the five-try limit. An amber "credit is low" warning is
separate: it never holds sends.
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
FALLBACK_ALERT_USER = 2311
# Q19 default until Matloob sets GATEWAY_CREDIT_WARN_BELOW.
DEFAULT_WARN = Decimal("1500")
LOW_BELL_HOURS = 6
OUT_BELL_HOURS = 1
POLL_FAIL_BELL_AFTER = 3


def is_no_credit(detail: str) -> bool:
    return "insufficient credit" in (detail or "").lower()


def waiting_detail(detail: str) -> str:
    text = (detail or "").strip() or "waiting for gateway credit"
    if text.lower().startswith(NO_CREDIT_PREFIX):
        return text[:2000]
    return f"{NO_CREDIT_PREFIX} {text}"[:2000]


def credit_is_out() -> bool:
    from .models import CreditState

    return CreditState.objects.filter(pk=1, out=True).exists()


def credit_is_low() -> bool:
    from .models import CreditState

    return CreditState.objects.filter(pk=1, low=True).exists()


def threshold() -> Decimal:
    raw = getattr(settings, "GATEWAY_CREDIT_WARN_BELOW", DEFAULT_WARN)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return DEFAULT_WARN


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
    from apps.campaigns.models import CampaignRecipient

    return CampaignRecipient.objects.filter(status=CampaignRecipient.Status.PENDING).update(
        status=CampaignRecipient.Status.FAILED,
        error_detail=WAITING_NOTE,
        next_retry_at=None,
    )


def reclaim_credit_failures() -> int:
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
    """Mark parked rows due. requeue_due_retries clears the prefix when flipping."""
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


def _deliver_bell(*, title: str, message: str, tag_kind: str, field: str, every: timedelta) -> bool:
    """Send one bell per user. Only stamp the warn clock when Bitrix accepts."""
    from .models import CreditState

    now = timezone.now()
    with transaction.atomic():
        row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
        stamped = getattr(row, field, None)
        if stamped and stamped > now - every:
            return False

    from apps.leadai.assistant.alerts import notify_bitrix

    hour = now.strftime("%Y%m%d%H")
    delivered = False
    for user_id in alert_recipients():
        tag = f"LEADAI|CREDIT|{tag_kind}|{hour}|{user_id}"
        try:
            body = notify_bitrix(
                to_user_id=user_id,
                title=title[:200],
                message=message[:1000],
                push=message[:200],
                tag=tag,
            )
        except Exception:
            logger.warning("credit bell failed for user %s", user_id)
            continue
        if isinstance(body, dict) and body.get("ok"):
            delivered = True
        else:
            logger.warning("credit bell refused for user %s: %s", user_id, body)

    if delivered:
        with transaction.atomic():
            row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
            setattr(row, field, now)
            row.save(update_fields=[field, "updated_at"])
    return delivered


def maybe_out_bell() -> bool:
    return _deliver_bell(
        title="WhatsApp credit is out",
        message="WhatsApp credit is out — messages are not going",
        tag_kind="OUT",
        field="warned_at",
        every=timedelta(hours=OUT_BELL_HOURS),
    )


def maybe_low_bell() -> bool:
    return _deliver_bell(
        title="WhatsApp credit is low",
        message="WhatsApp credit is low — top up before sends stop",
        tag_kind="LOW",
        field="low_warned_at",
        every=timedelta(hours=LOW_BELL_HOURS),
    )


def maybe_poll_fail_bell() -> bool:
    return _deliver_bell(
        title="WhatsApp credit check failed",
        message="The gateway credit check failed three times in a row",
        tag_kind="POLL",
        field="warned_at",
        every=timedelta(hours=OUT_BELL_HOURS),
    )


def _write_out_row() -> None:
    from .models import CreditState

    row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
    row.out = True
    row.low = True
    row.save(update_fields=["out", "low", "updated_at"])


def _persist_out_flag() -> None:
    """Write the hold so a caller's atomic rollback cannot undo it (C24)."""
    try:
        with transaction.atomic(durable=True):
            _write_out_row()
    except RuntimeError:
        # Nested inside another atomic — durable is refused. Queue a task that
        # commits on its own connection after this one settles or rolls back.
        from .tasks import apply_credit_out_flag

        apply_credit_out_flag.delay()


def mark_credit_out() -> None:
    """Record a real insufficient-credits refusal. Safe inside a rolled-back atomic."""
    _persist_out_flag()
    park_pending()
    reclaim_credit_failures()
    maybe_out_bell()


def clear_credit_out_after_send() -> None:
    """First accepted /messages while held: drop the hold so release can run."""
    from .models import CreditState

    with transaction.atomic():
        row = CreditState.objects.select_for_update().filter(pk=1, out=True).first()
        if row is None:
            return
        row.out = False
        row.save(update_fields=["out", "updated_at"])
    released = release_parked()
    if released:
        wake_retries()


def wake_retries() -> list[int]:
    """Flip every due parked row. Stagger campaign starts by one minute."""
    from apps.campaigns.services import requeue_due_retries
    from apps.campaigns.tasks import run_campaign

    started: list[int] = []
    delay = 0
    while True:
        campaign_ids = requeue_due_retries(limit=200)
        if not campaign_ids:
            break
        for campaign_id in campaign_ids:
            if campaign_id in started:
                continue
            if delay:
                run_campaign.apply_async(args=[campaign_id], countdown=delay)
            else:
                run_campaign.delay(campaign_id)
            started.append(campaign_id)
            delay += 60
        # More than 200 parked rows: keep flipping until none are due.
        if len(campaign_ids) < 200:
            break
    return started


def record_balance(amount: Decimal) -> str:
    """Poll result. Warn below the threshold; release a hold only at or above it."""
    from .models import CreditState

    low = amount < threshold()
    with transaction.atomic():
        row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
        was_out = row.out
        row.balance = amount
        row.low = low
        row.poll_failures = 0
        # A poll never *starts* a hold — only an Insufficient credits refusal does.
        # A poll at or above the warn level clears a hold.
        if not low and row.out:
            row.out = False
        row.save(update_fields=["balance", "low", "out", "poll_failures", "updated_at"])
        still_out = row.out

    if still_out:
        return "out"
    if was_out:
        released = release_parked()
        if released:
            wake_retries()
    if low:
        maybe_low_bell()
        return "low"
    return "ok"


def note_poll_failure(status_code: int | None = None) -> str:
    from .models import CreditState

    with transaction.atomic():
        row, _ = CreditState.objects.select_for_update().get_or_create(pk=1)
        row.poll_failures = int(row.poll_failures or 0) + 1
        failures = row.poll_failures
        row.save(update_fields=["poll_failures", "updated_at"])
    if status_code is not None:
        logger.warning("gateway credit poll failed http=%s", status_code)
    else:
        logger.warning("gateway credit poll failed")
    if failures >= POLL_FAIL_BELL_AFTER:
        maybe_poll_fail_bell()
    return "error"


def poll_gateway_credit() -> str:
    from .client import AlotsClient, AlotsError

    try:
        raw = AlotsClient().wallet_balance()
    except AlotsError as exc:
        return note_poll_failure(getattr(exc, "status_code", None))
    except Exception:
        return note_poll_failure(None)
    amount = parse_amount(raw)
    if amount is None:
        return note_poll_failure(None)
    return record_balance(amount)


def panel_flags() -> dict:
    from .models import CreditState

    row = CreditState.objects.filter(pk=1).first()
    return {"out": bool(row and row.out), "low": bool(row and row.low)}
