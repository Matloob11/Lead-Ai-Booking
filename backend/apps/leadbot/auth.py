"""HMAC auth for Bitrix → Django leadbot webhooks."""

from __future__ import annotations

import hashlib
import hmac
import time

from django.conf import settings


class AuthError(Exception):
    pass


MAX_SKEW_SEC = 300


def shared_secret() -> str:
    """Prefer LEADBOT_OUTREACH_SECRET; fall back to CRM_LEAD_WA_SECRET."""
    return (
        (getattr(settings, "LEADBOT_OUTREACH_SECRET", "") or "").strip()
        or (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    )


def verify_signed_request(*, timestamp: str, signature: str, body: bytes) -> None:
    secret = shared_secret()
    if not secret:
        raise AuthError("Leadbot outreach is not configured.")
    try:
        ts = int(str(timestamp or "").strip())
    except (TypeError, ValueError) as exc:
        raise AuthError("Missing request timestamp.") from exc
    if abs(int(time.time()) - ts) > MAX_SKEW_SEC:
        raise AuthError("Request expired.")
    presented = (signature or "").strip().lower()
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("ascii") + (body or b""),
        hashlib.sha256,
    ).hexdigest()
    if not presented or not hmac.compare_digest(presented, expected):
        raise AuthError("Forbidden.")
