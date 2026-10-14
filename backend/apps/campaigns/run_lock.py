"""Cross-process campaign run lock (C35).

Celery's LocMem ``cache.add`` only stops a second delivery inside one worker
process. With ``acks_late`` and a 3600 s Redis visibility timeout, a long
``run_campaign`` can be handed to another worker while the first is still
sending. This lock lives in Redis (``settings.REDIS_URL``) so every process
sees it. TTL is refreshed per recipient so a slow Bitrix-heavy run keeps the
lock without needing a multi-hour visibility timeout alone.
"""

from __future__ import annotations

import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "campaign:run:"
# Longer than a paced ~500-row run; refreshed on each recipient.
TTL_SEC = 60 * 90
_QUIET_UNTIL = 0.0


def _conn():
    return redis.Redis.from_url(
        getattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/0"),
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


def acquire(campaign_id: int) -> bool:
    """True when this process now holds the run lock; False if another holds it.

    Redis errors fail open (return True) so a dead Redis does not freeze every
    campaign — the same trade-off as crmlink's rate limiter.
    """
    global _QUIET_UNTIL
    import time

    now = time.monotonic()
    if now < _QUIET_UNTIL:
        return True
    key = f"{KEY_PREFIX}{int(campaign_id)}"
    try:
        return bool(_conn().set(key, "1", nx=True, ex=TTL_SEC))
    except Exception as exc:  # noqa: BLE001
        _QUIET_UNTIL = now + 10
        logger.warning("campaign run lock acquire failed: %s", exc)
        return True


def refresh(campaign_id: int) -> None:
    import time

    global _QUIET_UNTIL
    now = time.monotonic()
    if now < _QUIET_UNTIL:
        return
    key = f"{KEY_PREFIX}{int(campaign_id)}"
    try:
        _conn().expire(key, TTL_SEC)
    except Exception as exc:  # noqa: BLE001
        _QUIET_UNTIL = now + 10
        logger.warning("campaign run lock refresh failed: %s", exc)


def release(campaign_id: int) -> None:
    import time

    global _QUIET_UNTIL
    now = time.monotonic()
    if now < _QUIET_UNTIL:
        return
    key = f"{KEY_PREFIX}{int(campaign_id)}"
    try:
        _conn().delete(key)
    except Exception as exc:  # noqa: BLE001
        _QUIET_UNTIL = now + 10
        logger.warning("campaign run lock release failed: %s", exc)
