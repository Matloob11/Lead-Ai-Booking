#!/usr/bin/env python3
"""Phase 1: classify OpenWA WhatsApp threads → Bitrix Conversation Health.

Stdlib only. Intended to run on the OpenWA host (localhost:2785 + outbound HTTPS).
Never prints API keys, message bodies, or full phone numbers.
"""

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
OPENWA_KEY = os.environ.get("OPENWA_API_KEY") or os.environ.get("API_MASTER_KEY") or ""
BITRIX_BASE = (os.environ.get("BITRIX_WEBHOOK_BASE") or "").rstrip("/")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY") or ""
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
HEALTH_FIELD = os.environ.get("BITRIX_HEALTH_FIELD") or "UF_CRM_CONVERSATION_HEALTH"
REASON_FIELD = os.environ.get("BITRIX_AI_MONITOR_FIELD") or "UF_CRM_AI_MONITOR"
CHAT_FIELD = os.environ.get("BITRIX_WA_CHAT_FIELD") or "UF_CRM_WA_CHAT"
# Kanban stage for AI-created monitor leads (must not land in New Lead).
WA_LEAD_STATUS = os.environ.get("BITRIX_WA_LEAD_STATUS") or "UC_WA_LEADS"
LIMIT_CHATS = int(os.environ.get("PHASE1_CHAT_LIMIT") or "15")
MIN_MESSAGES = int(os.environ.get("PHASE1_MIN_MESSAGES") or "4")
MAX_MSG_CHARS = int(os.environ.get("PHASE1_MAX_MSG_CHARS") or "12000")
CHAT_FIELD_CHARS = int(os.environ.get("PHASE1_CHAT_FIELD_CHARS") or "3500")

# From crm.lead.userfield.get ID=2522 (created 2026-08-09)
ENUM_IDS = {
    "red": "2307",
    "pink": "2308",
    "yellow": "2309",
    "white": "2310",
    "green": "2311",
}
COLOUR_LIGHT = {
    "red": "🔴 RED",
    "pink": "🩷 PINK",
    "yellow": "🟡 YELLOW",
    "white": "⚪ WHITE",
    "green": "🟢 GREEN",
}

SYSTEM_PROMPT = """You are a compliance and quality monitor for a Dubai real estate agency.
You read one full conversation between a company AGENT and a CLIENT.
The conversation may be a WhatsApp chat or a phone-call transcript.
Language is mostly English, sometimes Roman Urdu (Urdu in English letters) or a mix — understand all of them.
Classify the WHOLE conversation into exactly ONE colour:
- "red"    = Corruption / integrity risk. The agent is trying to close or move the deal OUTSIDE the company.
- "pink"   = The CLIENT is unprofessional: abusive, threatening, insulting, or aggressively complaining.
- "yellow" = The AGENT cannot satisfy the client: no matching property, wrong budget/area, capability gap.
- "white"  = Hot, healthy deal: client interested, both sides professional, closing being discussed.
- "green"  = Normal, clean, ongoing conversation with no problems and no closing discussion yet.
Rules:
- Judge by the MEANING of the whole conversation, not single words.
- RED takes priority over everything.
Respond with ONLY this JSON, nothing else:
{"category":"red|pink|yellow|white|green","confidence":0.0,"reason":"one short sentence","flags":[],"needs_human_review":false}
"""


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
    if not OPENWA_KEY:
        fail("OPENWA_API_KEY / API_MASTER_KEY missing")
    return http_json(f"{OPENWA_BASE}{path}", headers={"X-API-Key": OPENWA_KEY})


def bitrix(method: str, params: dict[str, Any] | None = None) -> Any:
    if not BITRIX_BASE:
        fail("BITRIX_WEBHOOK_BASE missing")
    url = f"{BITRIX_BASE}/{method}.json"
    if params is None:
        return http_json(url)
    return http_json(url, method="POST", body=params)


def mask_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 6:
        return "***"
    return f"{digits[:3]}…{digits[-3:]}"


def digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def chat_phone(chat: dict[str, Any]) -> str | None:
    name = str(chat.get("name") or "")
    chat_id = str(chat.get("id") or "")
    if chat_id.endswith("@g.us") or chat_id.endswith("@newsletter"):
        return None
    for candidate in (name, chat_id.split("@")[0]):
        d = digits_only(candidate)
        if 8 <= len(d) <= 15:
            return d
    return None


def classify(agent_name: str, agent_phone: str, client_phone: str, thread: str) -> dict[str, Any]:
    if not OPENAI_KEY:
        fail("OPENAI_API_KEY missing")
    user = (
        f"CHANNEL: whatsapp\nAGENT: {agent_name} ({agent_phone or 'unknown'})\n"
        f"CLIENT: {client_phone}\nCONVERSATION:\n{thread}"
    )
    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    data = http_json(
        "https://api.openai.com/v1/chat/completions",
        method="POST",
        headers={"Authorization": f"Bearer {OPENAI_KEY}"},
        body=payload,
    )
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    cat = str(parsed.get("category") or "green").lower().strip()
    if cat not in ENUM_IDS:
        cat = "green"
    parsed["category"] = cat
    return parsed


def find_or_create_lead(phone: str, title_hint: str) -> tuple[str, bool]:
    """Return (lead_id, created). Never moves an existing sales lead out of its stage."""
    found = bitrix(
        "crm.duplicate.findbycomm",
        {"entity_type": "LEAD", "type": "PHONE", "values": [phone, f"+{phone}"]},
    )
    result = found.get("result") or {}
    lead_ids = result.get("LEAD") or []
    if lead_ids:
        return str(lead_ids[0]), False

    created = bitrix(
        "crm.lead.add",
        {
            "fields": {
                "TITLE": f"WA monitor · {title_hint[:40]}",
                "NAME": title_hint[:80] or phone,
                "OPENED": "Y",
                "STATUS_ID": WA_LEAD_STATUS,
                "SOURCE_DESCRIPTION": "Conversation Health Phase 1",
                "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
            }
        },
    )
    lead_id = created.get("result")
    if not lead_id:
        fail(f"crm.lead.add failed: {created}")
    return str(lead_id), True


def write_health(
    lead_id: str,
    category: str,
    reason: str,
    flags: list[str],
    agent: str,
    agent_phone: str,
    client: str,
    thread: str,
) -> None:
    enum_id = ENUM_IDS[category]
    light = COLOUR_LIGHT.get(category, category.upper())
    reason_line = (reason or "").strip() or "No reason returned"
    monitor_text = (
        f"{light}\n"
        f"Why: {reason_line}\n"
        f"Agent: {agent} ({agent_phone or '-'})\n"
        f"Client: {client}\n"
        f"Channel: whatsapp\n"
        f"Flags: {', '.join(flags) if flags else '-'}"
    )
    chat_snip = thread[-CHAT_FIELD_CHARS:] if thread else ""
    upd = bitrix(
        "crm.lead.update",
        {
            "id": lead_id,
            "fields": {
                HEALTH_FIELD: enum_id,
                REASON_FIELD: monitor_text[:2000],
                CHAT_FIELD: chat_snip,
            },
        },
    )
    if upd.get("error"):
        fail(f"crm.lead.update: {upd}")
    comment = (
        f"[AI Monitor] {light}\n"
        f"Agent: {agent} ({agent_phone or '-'})\n"
        f"Client: {client}\n"
        f"Channel: whatsapp\n"
        f"Reason: {reason_line}\n"
        f"Flags: {', '.join(flags) if flags else '-'}"
    )
    bitrix(
        "crm.timeline.comment.add",
        {"fields": {"ENTITY_ID": int(lead_id), "ENTITY_TYPE": "lead", "COMMENT": comment}},
    )


def thread_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in messages:
        if msg.get("type") in {"system", "revoked", "masked"}:
            continue
        body = (msg.get("body") or "").strip()
        if not body:
            body = f"[{msg.get('type') or 'message'}]"
        who = "AGENT" if msg.get("fromMe") else "CLIENT"
        lines.append(f"{who}: {body}")
    text = "\n".join(lines)
    if len(text) > MAX_MSG_CHARS:
        text = text[-MAX_MSG_CHARS:]
    return text


def main() -> None:
    sessions = openwa("/api/sessions")
    if isinstance(sessions, dict):
        sessions = sessions.get("sessions") or sessions.get("data") or []
    ready = [s for s in sessions if s.get("status") == "ready" and not s.get("removedAt")]
    if not ready:
        fail("no ready OpenWA sessions")

    # Prefer sessions with phones; take chats newest-first across sessions until LIMIT_CHATS.
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for session in ready:
        chats = openwa(f"/api/sessions/{session['id']}/chats?limit=40")
        if isinstance(chats, dict):
            chats = chats.get("chats") or chats.get("data") or []
        for chat in chats:
            if chat.get("kind") not in (None, "individual", "unknown"):
                continue
            phone = chat_phone(chat)
            if not phone:
                continue
            candidates.append((session, chat))

    candidates.sort(key=lambda pair: pair[1].get("timestamp") or 0, reverse=True)
    selected = candidates[: LIMIT_CHATS * 2]  # oversample; skip thin threads

    processed = 0
    skipped = 0
    print(f"ready-sessions={len(ready)}")
    print(f"candidate-chats={len(candidates)}")

    for session, chat in selected:
        if processed >= LIMIT_CHATS:
            break
        phone = chat_phone(chat)
        assert phone
        sid = session["id"]
        chat_id = chat["id"]
        msgs_resp = openwa(
            f"/api/sessions/{sid}/messages?{urllib.parse.urlencode({'chatId': chat_id, 'limit': 80})}"
        )
        messages = msgs_resp.get("messages") if isinstance(msgs_resp, dict) else msgs_resp
        if not isinstance(messages, list):
            skipped += 1
            continue
        # API often returns newest-first; chronological for the model.
        messages = sorted(messages, key=lambda m: m.get("timestamp") or 0)
        text = thread_text(messages)
        if text.count("\n") + 1 < MIN_MESSAGES:
            skipped += 1
            continue

        agent_name = str(session.get("name") or "agent")
        agent_phone = digits_only(str(session.get("phone") or ""))
        result = classify(agent_name, agent_phone, phone, text)
        lead_id, created = find_or_create_lead(phone, str(chat.get("name") or phone))
        write_health(
            lead_id,
            result["category"],
            str(result.get("reason") or ""),
            list(result.get("flags") or []),
            agent_name,
            agent_phone,
            phone,
            text,
        )
        processed += 1
        print(
            f"ok#{processed} lead={lead_id} colour={result['category']} "
            f"conf={result.get('confidence')} client={mask_phone(phone)} "
            f"agent={agent_name} created={created} status={WA_LEAD_STATUS if created else 'unchanged'} "
            f"review={result.get('needs_human_review')}"
        )

    print(f"processed={processed}")
    print(f"skipped-thin={skipped}")
    if processed == 0:
        fail("no chats classified — check OpenWA history depth / MIN_MESSAGES")
    print("phase1=PASS")


if __name__ == "__main__":
    main()
