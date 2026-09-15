#!/usr/bin/env python3
"""Widen WA_CHAT / AI_MONITOR via userfieldconfig.update (correct payload).

Needs a Bitrix inbound webhook whose permissions include `userfieldconfig`
(+ `crm`). Set BITRIX_USERFIELDCONFIG_WEBHOOK or BITRIX_WEBHOOK_BASE.
"""
from __future__ import annotations

import json
import os
import sys
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

base = (
    os.environ.get("BITRIX_USERFIELDCONFIG_WEBHOOK")
    or os.environ.get("BITRIX_WEBHOOK_BASE")
    or ""
).rstrip("/")
if not base:
    sys.exit("BITRIX_WEBHOOK_BASE missing")


def post(method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP_{e.code}", "error_description": body[:400]}


def field_id(name: str) -> int | None:
    rows = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": name}}).get("result") or []
    return int(rows[0]["ID"]) if rows else None


def size_of(name: str) -> tuple[int, int]:
    rows = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": name}}).get("result") or []
    if not rows:
        return 0, 0
    s = rows[0].get("SETTINGS") or {}
    return int(s.get("SIZE") or 0), int(s.get("ROWS") or 0)


do_fix = "--fix" in sys.argv

for name, size, rows in (
    ("UF_CRM_WA_CHAT", 80, 18),
    ("UF_CRM_AI_MONITOR", 80, 8),
):
    fid = field_id(name)
    before = size_of(name)
    print(f"=== {name} id={fid} before SIZE={before[0]} ROWS={before[1]}")
    if not fid or not do_fix:
        continue
    # Official shape: id is sibling of field (not nested).
    resp = post(
        "userfieldconfig.update",
        {
            "moduleId": "crm",
            "id": fid,
            "field": {"settings": {"SIZE": size, "ROWS": rows}},
        },
    )
    print("update", resp.get("result"), resp.get("error"), resp.get("error_description"))
    after = size_of(name)
    print(f"after SIZE={after[0]} ROWS={after[1]}")
    if after[0] < 60:
        print(
            "HINT: webhook needs permission `userfieldconfig`. "
            "Bitrix → Developer resources → Other → Inbound webhook → check userfieldconfig, "
            "then set BITRIX_USERFIELDCONFIG_WEBHOOK in .env and re-run with --fix."
        )
        print(
            "OR manual: CRM → Settings → Lead form fields → WhatsApp Chat / AI Monitor → Size = 80."
        )

if not do_fix:
    print("dry-run only; pass --fix to apply")
