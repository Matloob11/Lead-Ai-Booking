#!/usr/bin/env python3
"""Fetch Bitrix lead fields + recent timeline comments. Usage: ID from argv."""
from __future__ import annotations

import json
import os
import sys
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

lead_id = sys.argv[1] if len(sys.argv) > 1 else "72122"


def post(method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


lead = (post("crm.lead.get", {"ID": lead_id}).get("result") or {})
keys = [
    "ID",
    "TITLE",
    "STATUS_ID",
    "NAME",
    "UF_CRM_CONVERSATION_HEALTH",
    "UF_CRM_AI_MONITOR",
    "UF_CRM_WA_CHAT",
]
out = {k: lead.get(k) for k in keys}
out["PHONE"] = lead.get("PHONE")
wa = out.get("UF_CRM_WA_CHAT") or ""
out["UF_CRM_WA_CHAT_LEN"] = len(str(wa))
out["UF_CRM_WA_CHAT_HEAD"] = str(wa)[:200]
print("bitrixLead", json.dumps(out, ensure_ascii=False)[:2500])

comments = (
    post(
        "crm.timeline.comment.list",
        {
            "filter": {"ENTITY_ID": int(lead_id), "ENTITY_TYPE": "lead"},
            "order": {"ID": "DESC"},
            "select": ["ID", "COMMENT", "CREATED"],
        },
    ).get("result")
    or []
)
print("commentCount", len(comments))
for c in comments[:8]:
    text = (c.get("COMMENT") or "").replace("\n", " | ")[:180]
    print("comment", c.get("ID"), text)

# Confirm enum labels for health field
enums = post(
    "crm.lead.userfield.list",
    {"filter": {"FIELD_NAME": "UF_CRM_CONVERSATION_HEALTH"}},
).get("result") or []
if enums:
    items = (enums[0].get("LIST") or [])[:8]
    print("healthEnums", [(i.get("ID"), i.get("VALUE")) for i in items])
