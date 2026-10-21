"""Who stands above a Bitrix user: their team lead and their department head, from Cursor's C49 map endpoint
(/bitrix/tools/a7_leadai_escalation.php, built from the company structure's UF_HEAD), so a handover nobody answered
reaches them too (people.escalate_waiting; the advance plan's D: "an escalation IM to the lead's responsible and their
TL").

The call: POST {"user_id": 2311}, signed like the notify tool but with its own prefix ("leadai-escalation." + ts + "."
+ body, X-Leadai-Ts / X-Leadai-Sign, CRM_LEAD_WA_SECRET); the answer {"ok": true, "map": {"2311": {"lead": 2560, "head":
60}}}, 0 for unknown. One answer is kept for CACHE_SECONDS per user (the structure changes rarely); a miss or a failure
for a tenth of that. Any trouble is nobody: the alert goes to the chat's people as before, never late.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SIGN_PREFIX = b"leadai-escalation."
CACHE_SECONDS = 6 * 3600
TIMEOUT = httpx.Timeout(10, connect=5)
# Bitrix users 0 and 1 hold unassigned leads: nobody's work (alerts.HOLD_USERS).
NOBODY = {"", "0", "1"}


def sign(raw: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), SIGN_PREFIX + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def endpoint() -> str:
    return (getattr(settings, "LEADAI_BITRIX_ESCALATION_URL", "") or "").strip()


def above(bitrix_user_id) -> list[str]:
    """The user's team lead, then their department head (Bitrix ids as strings), each once, never the user themselves
    nor a hold user; [] when unknown, not configured or not answered."""
    uid = str(bitrix_user_id or "").strip()
    if not uid.isdigit() or uid in NOBODY:
        return []
    key = f"leadai:escalation:{uid}"
    found = cache.get(key)
    if found is None:
        found = _fetch(int(uid))
        cache.set(key, found, CACHE_SECONDS if found else CACHE_SECONDS // 10)
    out: list[str] = []
    for role in ("lead", "head"):
        who = str(found.get(role) or "").strip()
        if who.isdigit() and who not in NOBODY and who != uid and who not in out:
            out.append(who)
    return out


def _fetch(user_id: int) -> dict:
    """{"lead": id, "head": id} for one user from the map endpoint, {} when it is off, unreachable or says nothing."""
    url = endpoint()
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    if not url or not secret:
        return {}
    raw = json.dumps({"user_id": int(user_id)}, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    try:
        response = httpx.post(
            url,
            content=raw,
            headers={"Content-Type": "application/json", "X-Leadai-Ts": ts, "X-Leadai-Sign": sign(raw, ts, secret)},
            timeout=TIMEOUT,
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Lead AI escalation map not read for user %s (%s)", user_id, type(exc).__name__)
        return {}
    if not isinstance(body, dict) or not body.get("ok"):
        logger.info("Lead AI escalation map refused for user %s (%s)", user_id, str((body or {}).get("error") if isinstance(body, dict) else response.status_code)[:80])
        return {}
    entry = (body.get("map") or {}).get(str(int(user_id))) if isinstance(body.get("map"), dict) else None
    if not isinstance(entry, dict):
        return {}
    out = {}
    for role in ("lead", "head"):
        try:
            value = int(entry.get(role) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            out[role] = value
    return out
