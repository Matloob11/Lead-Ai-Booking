#!/usr/bin/env python3
"""Backfill WhatsApp Chat + AI Monitor fields on Phase1 leads from OpenWA history."""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

OPENWA_BASE = os.environ.get("OPENWA_BASE", "http://127.0.0.1:2785").rstrip("/")
OPENWA_KEY = os.environ.get("OPENWA_API_KEY") or ""
BITRIX_BASE = (os.environ.get("BITRIX_WEBHOOK_BASE") or "").rstrip("/")
HEALTH_FIELD = os.environ.get("BITRIX_HEALTH_FIELD") or "UF_CRM_CONVERSATION_HEALTH"
REASON_FIELD = os.environ.get("BITRIX_AI_MONITOR_FIELD") or "UF_CRM_AI_MONITOR"
CHAT_FIELD = os.environ.get("BITRIX_WA_CHAT_FIELD") or "UF_CRM_WA_CHAT"
CHAT_FIELD_CHARS = int(os.environ.get("PHASE1_CHAT_FIELD_CHARS") or "3500")

ENUM_TO_LIGHT = {
    "2307": "🔴 RED",
    "2308": "🩷 PINK",
    "2309": "🟡 YELLOW",
    "2310": "⚪ WHITE",
    "2311": "🟢 GREEN",
}


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, body: Any = None) -> Any:
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        fail(f"HTTP {exc.code} {url.split('?')[0]} {detail}")
    except Exception as exc:  # noqa: BLE001
        fail(f"{type(exc).__name__}: {exc}")


def openwa(path: str) -> Any:
    return http_json(f"{OPENWA_BASE}{path}", headers={"X-API-Key": OPENWA_KEY})


def bitrix(method: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BITRIX_BASE}/{method}.json"
    if params is None:
        return http_json(url)
    return http_json(url, method="POST", body=params)


def digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def thread_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in sorted(messages, key=lambda m: m.get("timestamp") or 0):
        if msg.get("type") in {"system", "revoked", "masked"}:
            continue
        body = (msg.get("body") or "").strip() or f"[{msg.get('type') or 'message'}]"
        who = "AGENT" if msg.get("fromMe") else "CLIENT"
        lines.append(f"{who}: {body}")
    text = "\n".join(lines)
    return text[-CHAT_FIELD_CHARS:] if len(text) > CHAT_FIELD_CHARS else text


def build_phone_index() -> dict[str, tuple[str, str, str]]:
    """phone digits -> (session_id, chat_id, agent_name)."""
    sessions = openwa("/api/sessions")
    if isinstance(sessions, dict):
        sessions = sessions.get("sessions") or sessions.get("data") or []
    index: dict[str, tuple[str, str, str]] = {}
    for session in sessions:
        if session.get("status") != "ready" or session.get("removedAt"):
            continue
        sid = session["id"]
        agent = str(session.get("name") or "agent")
        chats = openwa(f"/api/sessions/{sid}/chats?limit=80")
        if isinstance(chats, dict):
            chats = chats.get("chats") or chats.get("data") or []
        for chat in chats:
            chat_id = str(chat.get("id") or "")
            name = str(chat.get("name") or "")
            for candidate in (name, chat_id.split("@")[0]):
                d = digits_only(candidate)
                if 8 <= len(d) <= 15:
                    index[d] = (sid, chat_id, agent)
    return index


def lead_phones(lead: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for phone in lead.get("PHONE") or []:
        d = digits_only(str(phone.get("VALUE") or ""))
        if d:
            out.append(d)
    return out


def main() -> None:
    if not OPENWA_KEY or not BITRIX_BASE:
        fail("OPENWA_API_KEY / BITRIX_WEBHOOK_BASE missing")

    index = build_phone_index()
    print(f"openwa_phone_index={len(index)}")

    start = 0
    filled = 0
    missed = 0
    while True:
        page = bitrix(
            "crm.lead.list",
            {
                "filter": {"SOURCE_DESCRIPTION": "Conversation Health Phase 1"},
                "select": ["ID", "TITLE", HEALTH_FIELD, REASON_FIELD, CHAT_FIELD, "PHONE"],
                "order": {"ID": "DESC"},
                "start": start,
            },
        )
        rows = page.get("result") or []
        if not rows:
            break
        for lead in rows:
            lid = lead["ID"]
            phones = lead_phones(lead)
            hit = None
            for p in phones:
                if p in index:
                    hit = index[p]
                    break
                # suffix match for country-code variants
                for key, val in index.items():
                    if key.endswith(p[-9:]) or p.endswith(key[-9:]):
                        hit = val
                        break
                if hit:
                    break
            if not hit:
                missed += 1
                print(f"miss lead={lid}")
                continue
            sid, chat_id, agent = hit
            msgs_resp = openwa(
                f"/api/sessions/{sid}/messages?{urllib.parse.urlencode({'chatId': chat_id, 'limit': 80})}"
            )
            messages = msgs_resp.get("messages") if isinstance(msgs_resp, dict) else msgs_resp
            if not isinstance(messages, list) or not messages:
                missed += 1
                print(f"empty-msgs lead={lid}")
                continue
            chat = thread_text(messages)
            health = str(lead.get(HEALTH_FIELD) or "")
            light = ENUM_TO_LIGHT.get(health, health or "?")
            prev = (lead.get(REASON_FIELD) or "").strip()
            # Keep existing Why: line if present; else leave light + note
            if "Why:" in prev:
                monitor = prev
                if not prev.startswith("🔴") and not prev.startswith("🩷") and not prev.startswith("🟡"):
                    monitor = f"{light}\n{prev}"
            else:
                why = prev or "See timeline [AI Monitor] comment"
                monitor = f"{light}\nWhy: {why}"
            bitrix(
                "crm.lead.update",
                {
                    "id": lid,
                    "fields": {
                        REASON_FIELD: monitor[:2000],
                        CHAT_FIELD: chat,
                    },
                },
            )
            filled += 1
            print(f"ok lead={lid} agent={agent} chat_chars={len(chat)}")
        if len(rows) < 50:
            break
        start += 50
    print(f"filled={filled} missed={missed}")
    if filled == 0:
        fail("no chats backfilled")
    print("backfill=PASS")


if __name__ == "__main__":
    main()
