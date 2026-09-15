#!/usr/bin/env python3
"""Inspect UF_CRM_WA_CHAT field type + sample broken leads."""
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


def post(method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


fields = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": "UF_CRM_WA_CHAT"}}).get("result") or []
print("=== UF_CRM_WA_CHAT meta ===")
print(json.dumps(fields[:1], ensure_ascii=False, indent=2)[:3000])

monitor = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": "UF_CRM_AI_MONITOR"}}).get("result") or []
print("=== UF_CRM_AI_MONITOR meta ===")
print(json.dumps(monitor[:1], ensure_ascii=False, indent=2)[:1500])

for lead_id in sys.argv[1:] or ["71945", "71909", "71967"]:
    lead = (post("crm.lead.get", {"ID": lead_id}).get("result") or {})
    wa = lead.get("UF_CRM_WA_CHAT") or ""
    mon = lead.get("UF_CRM_AI_MONITOR") or ""
    print(f"\n=== lead {lead_id} ===")
    print("title", lead.get("TITLE"))
    print("wa_type", type(wa).__name__, "len", len(str(wa)))
    print("wa_repr_head", repr(str(wa)[:400]))
    print("wa_has_nl", "\\n" in str(wa) or "\n" in str(wa))
    print("wa_has_br", "<br" in str(wa).lower())
    print("wa_has_cr", "\r" in str(wa))
    # show first 15 visual lines
    text = str(wa).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    print("line_count", len(lines))
    for i, line in enumerate(lines[:12]):
        print(f"L{i}", repr(line[:120]))
    print("monitor_head", repr(str(mon)[:250]))
