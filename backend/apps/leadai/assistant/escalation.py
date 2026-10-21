"""Who stands above a Bitrix user: their team lead and their department head, from Cursor's C49 map endpoint
(/bitrix/tools/a7_leadai_escalation.php, built from the company structure's UF_HEAD), so a handover nobody answered
reaches them too (people.escalate_waiting; the advance plan's D: "an escalation IM to the lead's responsible and their
TL").

The call: POST {} (the whole map, one CUser::GetList there: 66 users on 2026-10-20), signed like the notify tool but
with its own prefix ("leadai-escalation." + ts + "." + body, X-Leadai-Ts / X-Leadai-Sign, CRM_LEAD_WA_SECRET); the answer
{"ok": true, "map": {"2311": {"lead": 2560, "head": 60}, ...}}, 0 for unknown. The map is kept for CACHE_SECONDS (the
structure changes rarely), a miss or a failure for a tenth of that, so a cold cache costs one call, not one per user.
Any trouble is nobody: the alert goes to the chat's people as before, never late (the lookup never raises, and the sweep
runs it last).
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
CACHE_KEY = "leadai:escalation:map"
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
    found = the_map().get(uid) or {}
    out: list[str] = []
    for role in ("lead", "head"):
        who = str(found.get(role) or "").strip()
        if who.isdigit() and who not in NOBODY and who != uid and who not in out:
            out.append(who)
    return out


def the_map() -> dict:
    """{user id: {"lead": id, "head": id}} for every user the endpoint maps, from the cache or one call."""
    found = cache.get(CACHE_KEY)
    if found is None:
        found = _fetch()
        cache.set(CACHE_KEY, found, CACHE_SECONDS if found else CACHE_SECONDS // 10)
    return found if isinstance(found, dict) else {}


def _fetch() -> dict:
    """The whole map from the endpoint, {} when it is off, unreachable or says nothing. Never raises."""
    url = endpoint()
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    if not url or not secret:
        return {}
    raw = b"{}"
    ts = str(int(time.time()))
    try:
        response = httpx.post(
            url,
            content=raw,
            headers={"Content-Type": "application/json", "X-Leadai-Ts": ts, "X-Leadai-Sign": sign(raw, ts, secret)},
            timeout=TIMEOUT,
        )
        body = response.json()
    except Exception as exc:  # noqa: BLE001 - the map is a convenience: a lookup that fails is nobody, never a failed sweep
        logger.info("Lead AI escalation map not read (%s)", type(exc).__name__)
        return {}
    if not isinstance(body, dict) or not body.get("ok") or not isinstance(body.get("map"), dict):
        logger.info("Lead AI escalation map refused (%s)", str(body.get("error") if isinstance(body, dict) else response.status_code)[:80])
        return {}
    out: dict = {}
    for key, entry in body["map"].items():
        uid = str(key).strip()
        if not uid.isdigit() or not isinstance(entry, dict):
            continue
        roles = {}
        for role in ("lead", "head"):
            try:
                value = int(entry.get(role) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                roles[role] = value
        if roles:
            out[uid] = roles
    return out
