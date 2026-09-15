#!/usr/bin/env python3
"""Recreate UF_CRM_WA_CHAT / UF_CRM_AI_MONITOR with SIZE=80.

crm.lead.userfield.update can change ROWS but NOT SIZE (Bitrix docs omit SIZE
for that method). userfieldconfig.update needs a scope our webhook lacks.
So: export values → delete → add with SIZE 80 → restore (sanitized).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

base = (os.environ.get("BITRIX_WEBHOOK_BASE") or "").rstrip("/")
if not base:
    sys.exit("BITRIX_WEBHOOK_BASE missing")

CHAT = "UF_CRM_WA_CHAT"
MONITOR = "UF_CRM_AI_MONITOR"
VCARD_RE = re.compile(r"BEGIN:VCARD[\s\S]*?END:VCARD", re.I)


def post(method: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP_{e.code}", "error_description": body[:500]}


def field_meta(name: str) -> dict | None:
    rows = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": name}}).get("result") or []
    return rows[0] if rows else None


def sanitize_chat(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = VCARD_RE.sub("[contact card]", t)
    # Keep line structure; collapse ridiculous runs of blank lines.
    lines = []
    for line in t.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(line)
    out = "\n".join(lines).strip()
    if len(out) > 3500:
        cut = out[-3500:]
        nl = cut.find("\n")
        out = cut[nl + 1 :] if nl >= 0 and nl < len(cut) - 1 else cut
    return out


def sanitize_monitor(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    t = VCARD_RE.sub("[contact card]", t)
    t = re.sub(r"[ \t]+", " ", t)
    if len(t) > 2000:
        t = t[:1997] + "…"
    return t


def export_values() -> list[dict]:
    """Only pull leads that already have chat/monitor text (not the whole CRM)."""
    by_id: dict[int, dict] = {}
    filters = [
        {"!" + CHAT: ""},
        {"!" + MONITOR: ""},
    ]
    for flt in filters:
        start = 0
        while True:
            resp = post(
                "crm.lead.list",
                {
                    "order": {"ID": "ASC"},
                    "filter": flt,
                    "select": ["ID", CHAT, MONITOR],
                    "start": start,
                },
            )
            if resp.get("error"):
                print(f"  filter {flt} error: {resp.get('error')} {resp.get('error_description')}")
                break
            batch = resp.get("result") or []
            for row in batch:
                lid = int(row["ID"])
                chat = str(row.get(CHAT) or "").strip()
                mon = str(row.get(MONITOR) or "").strip()
                if not chat and not mon:
                    continue
                prev = by_id.get(lid) or {"ID": lid, CHAT: "", MONITOR: ""}
                by_id[lid] = {
                    "ID": lid,
                    CHAT: chat or prev[CHAT],
                    MONITOR: mon or prev[MONITOR],
                }
            nxt = resp.get("next")
            print(
                f"  filter={flt} start={start} batch={len(batch)} "
                f"unique={len(by_id)} next={nxt}"
            )
            if nxt is None:
                break
            start = int(nxt)
            time.sleep(0.1)
    return [by_id[k] for k in sorted(by_id)]


def delete_field(name: str) -> None:
    meta = field_meta(name)
    if not meta:
        print(f"  {name} already absent")
        return
    fid = meta["ID"]
    resp = post("crm.lead.userfield.delete", {"id": fid})
    print(f"  delete {name} id={fid} -> {resp.get('result')} {resp.get('error')}")
    if resp.get("error"):
        raise SystemExit(f"delete failed: {resp}")


def add_field(short_name: str, label: str, rows: int) -> None:
    payload = {
        "fields": {
            "FIELD_NAME": short_name,
            "USER_TYPE_ID": "string",
            "XML_ID": f"UF_CRM_{short_name}",
            "EDIT_FORM_LABEL": {"en": label},
            "LIST_COLUMN_LABEL": {"en": label},
            "LIST_FILTER_LABEL": {"en": label},
            "MULTIPLE": "N",
            "MANDATORY": "N",
            "SHOW_FILTER": "Y",
            "SHOW_IN_LIST": "Y",
            "EDIT_IN_LIST": "Y",
            "IS_SEARCHABLE": "N",
            "SETTINGS": {
                "SIZE": 80,
                "ROWS": rows,
                "REGEXP": "",
                "MIN_LENGTH": 0,
                "MAX_LENGTH": 0,
                "DEFAULT_VALUE": "",
            },
        }
    }
    resp = post("crm.lead.userfield.add", payload)
    print(f"  add {short_name} -> result={resp.get('result')} err={resp.get('error')}")
    if resp.get("error"):
        raise SystemExit(f"add failed: {resp}")


def restore(rows: list[dict]) -> None:
    ok = 0
    for i, row in enumerate(rows, 1):
        fields = {
            CHAT: sanitize_chat(row.get(CHAT) or ""),
            MONITOR: sanitize_monitor(row.get(MONITOR) or ""),
        }
        # Drop empties so we don't wipe with ""
        fields = {k: v for k, v in fields.items() if v}
        if not fields:
            continue
        resp = post("crm.lead.update", {"id": row["ID"], "fields": fields})
        if resp.get("result"):
            ok += 1
        else:
            print(f"  restore fail lead={row['ID']} {resp.get('error')} {resp.get('error_description')}")
        if i % 25 == 0:
            print(f"  restored {i}/{len(rows)}")
            time.sleep(0.2)
    print(f"  restore done ok={ok}/{len(rows)}")


def ensure_form() -> None:
    # Re-pin section after field recreate (ids change; names stay).
    HEALTH = "UF_CRM_CONVERSATION_HEALTH"
    SECTION = "a7_conversation_health"
    for extras in ({}, {"leadCustomerType": 1}, {"leadCustomerType": 2}):
        get_payload: dict = {"scope": "C"}
        if extras:
            get_payload["extras"] = extras
        cfg = post("crm.lead.details.configuration.get", get_payload).get("result")
        if cfg is None:
            continue
        cleaned = []
        for sec in cfg:
            elems = [
                e
                for e in (sec.get("elements") or [])
                if e.get("name") not in {HEALTH, MONITOR, CHAT}
            ]
            if sec.get("name") == SECTION:
                continue
            cleaned.append({**sec, "elements": elems})
        section = {
            "name": SECTION,
            "title": "Conversation Health",
            "type": "section",
            "elements": [
                {"name": HEALTH, "optionFlags": "1"},
                {"name": MONITOR, "optionFlags": "1"},
                {"name": CHAT, "optionFlags": "1"},
            ],
        }
        set_payload: dict = {"scope": "C", "data": [section] + cleaned}
        if extras:
            set_payload["extras"] = extras
        resp = post("crm.lead.details.configuration.set", set_payload)
        print("  form set", extras or "default", resp.get("result"), resp.get("error"))
    force = post("crm.lead.details.configuration.forceCommonScopeForAll", {})
    print("  forceCommon", force.get("result"), force.get("error"))


do_fix = "--fix" in sys.argv
# SAFETY: crm.lead.userfield.add/update on this portal cannot raise SIZE
# (legacy REST omits SIZE; stays 20). Deleting fields only wipes data.
# Use widen-wa-chat-userfieldconfig.py (needs userfieldconfig scope) or
# set Size=80 manually in Bitrix CRM field settings instead.
if do_fix and "--i-know-size-cannot-change" not in sys.argv:
    sys.exit(
        "REFUSING delete/recreate: SIZE stays 20 via this API. "
        "Use ops/openwa/widen-wa-chat-userfieldconfig.py --fix "
        "(webhook needs userfieldconfig), or set Size=80 in Bitrix UI. "
        "Pass --i-know-size-cannot-change only for emergency field recovery."
    )

print("=== export non-empty leads ===")
rows = export_values()
print(f"exported {len(rows)} leads with chat/monitor text")

for name in (CHAT, MONITOR):
    meta = field_meta(name)
    print(
        f"before {name}:",
        None
        if not meta
        else f"id={meta.get('ID')} SIZE={(meta.get('SETTINGS') or {}).get('SIZE')} ROWS={(meta.get('SETTINGS') or {}).get('ROWS')}",
    )

if not do_fix:
    print("dry-run only; pass --fix to recreate + restore")
    sys.exit(0)

print("=== delete ===")
delete_field(CHAT)
delete_field(MONITOR)
time.sleep(1)

print("=== add SIZE=80 ===")
add_field("WA_CHAT", "WhatsApp Chat", 18)
add_field("AI_MONITOR", "AI Monitor", 8)
time.sleep(1)

for name in (CHAT, MONITOR):
    meta = field_meta(name)
    s = (meta or {}).get("SETTINGS") or {}
    print(f"after-add {name}: id={(meta or {}).get('ID')} SIZE={s.get('SIZE')} ROWS={s.get('ROWS')}")
    if int(s.get("SIZE") or 0) < 60:
        raise SystemExit(f"SIZE did not stick on create for {name}: {s}")

print("=== restore sanitized values ===")
restore(rows)

print("=== form section ===")
ensure_form()

print("RECREATE_OK")
