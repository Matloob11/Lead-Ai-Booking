"""POST /api/leadai/bitrix/bot-status/: Bitrix tells the assistant a person set Bot Status or
WhatsApp Opt-out on a lead (board T52, Cursor's C12; bitrix_status.py acts on it).

The contract (SHOPS-BOT-BOARD.md, C12):
- headers X-Leadai-Ts (unix seconds) and X-Leadai-Sign = hex HMAC-SHA256 of
  "leadai-botstatus." + ts + "." + body, with CRM_LEAD_WA_SECRET (the prefix
  keeps a notify or fields signature from being replayed here);
- body {"lead_id": 123, "bot_status": 2478 or null, "wa_opt_out": 2482 or null,
  "changed_by": 2311, "at": "2026-10-13T12:00:00+04:00"}.

The method, the size and the signature are checked before anything else (the
timestamp within 300 seconds, compared in constant time); there is no session
and no CSRF here, the signature is the only key. 405 for any method but POST,
401 for a missing, wrong or old signature, 400 for a body that is not the
contract, else 200 {"ok": true, "chats": N}, also when no chat matches.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import bitrix_status

logger = logging.getLogger(__name__)

SIGN_PREFIX = b"leadai-botstatus."
MAX_SKEW = 300
MAX_BODY = 16 * 1024
ID_MAX = 10**12
# Unix seconds (ASCII digits, a sane length) and a hex SHA-256: anything else is refused before
# int() or compare_digest could raise on it ("²", a 5000-digit number, 64 non-ASCII letters).
_TS = re.compile(r"[0-9]{1,12}")
_SIGN = re.compile(r"[0-9a-f]{64}")


def sign(raw: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), SIGN_PREFIX + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def _refuse(status: int, error: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": error}, status=status)


def _int_or_none(value):
    """A positive whole number, None for null; raises ValueError for anything else."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or not 0 <= value < ID_MAX:
        raise ValueError
    return value


@csrf_exempt
def bot_status(request):
    if request.method != "POST":
        return _refuse(405, "POST only.")
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        return _refuse(400, "Body too large.")
    raw = request.body
    if not raw or len(raw) > MAX_BODY:
        return _refuse(400, "Bad body.")
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    ts = str(request.headers.get("X-Leadai-Ts") or "").strip()
    given = str(request.headers.get("X-Leadai-Sign") or "").strip().lower()
    if not secret or not _TS.fullmatch(ts) or not _SIGN.fullmatch(given) or abs(time.time() - int(ts)) > MAX_SKEW:
        return _refuse(401, "Unauthorized.")
    if not hmac.compare_digest(sign(raw, ts, secret).encode("ascii"), given.encode("ascii")):
        return _refuse(401, "Unauthorized.")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return _refuse(400, "Body is not JSON.")
    if not isinstance(body, dict):
        return _refuse(400, "Body is not an object.")
    try:
        lead_id = _int_or_none(body.get("lead_id"))
        bot = _int_or_none(body.get("bot_status"))
        opt = _int_or_none(body.get("wa_opt_out"))
        changed_by = _int_or_none(body.get("changed_by"))
    except ValueError:
        return _refuse(400, "Bad field.")
    if not lead_id:
        return _refuse(400, "No lead.")
    at = body.get("at")
    if at is not None and not isinstance(at, str):
        return _refuse(400, "Bad field.")
    chats = bitrix_status.apply(lead_id, bot_status=bot, wa_opt_out=opt, changed_by=changed_by, at=(at or "")[:40])
    logger.info("Lead AI: Bitrix set Bot Status %s / opt-out %s on lead %s (%s chats)", bot, opt, lead_id, chats)
    return JsonResponse({"ok": True, "chats": chats})


# POST /api/leadai/inventory/bitrix/: Bitrix says an Availability card was added or changed (Cursor's C46 handler,
# a7_inventory_webhook.php, on SPA 1042 in category 14 or an available stage). Header X-A7-Signature = hex HMAC-SHA256 of
# "leadai-inventory." + ts + "." + body with CRM_LEAD_WA_SECRET; ts (unix seconds) in X-A7-Ts and in the body; body
# {"event": "update", "id": 103048, "stageId": "DT1042_14:PREPARATION", "ts": 1760000000}.
INVENTORY_PREFIX = b"leadai-inventory."
# "ts":1760000000 in the raw body (the handler's json_encode puts no space after the colon; one is allowed).
_BODY_TS = re.compile(rb'"ts"\s*:\s*([0-9]{1,12})\b')
REFRESH_EVERY = 30


def inventory_sign(raw: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), INVENTORY_PREFIX + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def a7_sign(raw: bytes, ts: str, secret: str, prefix: bytes) -> str:
    return hmac.new(secret.encode(), prefix + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def _a7_event(request, prefix: bytes):
    """A box handler's signed event (X-A7-Signature over ``prefix`` + ts + "." + body, the stamp in X-A7-Ts or the
    body): (the body's object, None), or (None, the refusal) — 405, 401 for a missing, wrong or old signature, 400 for
    a body off the contract. Nothing unsigned is parsed."""
    if request.method != "POST":
        return None, _refuse(405, "POST only.")
    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > MAX_BODY:
        return None, _refuse(400, "Body too large.")
    raw = request.body
    if not raw or len(raw) > MAX_BODY:
        return None, _refuse(400, "Bad body.")
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    ts = str(request.headers.get("X-A7-Ts") or "").strip()
    given = str(request.headers.get("X-A7-Signature") or "").strip().lower()
    if not ts:
        # The handler's stamp travels in the body too: a proxy that drops the header still signs. Read with a bounded
        # pattern, not a parse: nothing unsigned is parsed (a nested document would raise past json's ValueError).
        match = _BODY_TS.search(raw)
        ts = match.group(1).decode("ascii") if match else ""
    if not secret or not _TS.fullmatch(ts) or not _SIGN.fullmatch(given) or abs(time.time() - int(ts)) > MAX_SKEW:
        return None, _refuse(401, "Unauthorized.")
    if not hmac.compare_digest(a7_sign(raw, ts, secret, prefix).encode("ascii"), given.encode("ascii")):
        return None, _refuse(401, "Unauthorized.")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, _refuse(400, "Body is not JSON.")
    if not isinstance(body, dict):
        return None, _refuse(400, "Body is not an object.")
    return body, None


@csrf_exempt
def inventory_event(request):
    """Checked like bot_status: 405 for any method but POST, 401 for a missing, wrong or old signature, 400 for a body
    off the contract; else 200 {"ok": true, "queued": true, "id": N} and the card is read again in a task
    (tasks.refresh_bitrix_unit → inventory.refresh_bitrix): its clean rows upserted, the rest retired."""
    body, refused = _a7_event(request, INVENTORY_PREFIX)
    if refused is not None:
        return refused
    try:
        card_id = _int_or_none(body.get("id"))
    except ValueError:
        return _refuse(400, "Bad field.")
    if not card_id:
        return _refuse(400, "No card.")
    from django.core.cache import cache

    from .tasks import refresh_bitrix_unit

    # One read per card per half minute: Bitrix fires on every save, and a captured request could be replayed for
    # MAX_SKEW; the sync has the rest.
    queued = bool(cache.add(f"leadai:inventory:refresh:{card_id}", 1, REFRESH_EVERY))
    if queued:
        refresh_bitrix_unit.delay(card_id)
    logger.info(
        "Lead AI inventory: Bitrix says Availability card %s %s (%s)%s",
        card_id, str(body.get("event") or "update")[:20], str(body.get("stageId") or "")[:60], "" if queued else ": read already",
    )
    return JsonResponse({"ok": True, "queued": queued, "id": card_id})


# POST /api/leadai/bitrix/new-lead/: Bitrix says a lead was created (Cursor's C67 handler, the C46 way): the same
# signature with its own prefix; body {"event": "add", "id": 80123, "ts": 1760000000}. The greet runs a minute later
# (tasks.greet_new_lead → assistant/newlead.greet), once per lead per GREET_EVERY whatever the handler repeats.
NEW_LEAD_PREFIX = b"leadai-newlead."
GREET_DELAY = 60
GREET_EVERY = 600


@csrf_exempt
def new_lead(request):
    body, refused = _a7_event(request, NEW_LEAD_PREFIX)
    if refused is not None:
        return refused
    try:
        lead_id = _int_or_none(body.get("id"))
    except ValueError:
        return _refuse(400, "Bad field.")
    if not lead_id:
        return _refuse(400, "No lead.")
    from django.core.cache import cache

    from .tasks import greet_new_lead

    queued = bool(cache.add(f"leadai:newlead:{lead_id}", 1, GREET_EVERY))
    if queued:
        greet_new_lead.apply_async(args=[lead_id], countdown=GREET_DELAY)
    logger.info("Lead AI: Bitrix says lead %s was created%s", lead_id, "" if queued else " (queued already)")
    return JsonResponse({"ok": True, "queued": queued, "id": lead_id})
