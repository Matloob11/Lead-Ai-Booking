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
    except (UnicodeDecodeError, ValueError):
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
