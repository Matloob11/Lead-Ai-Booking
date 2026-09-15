#!/usr/bin/env python3
"""Widen UF_CRM_WA_CHAT / AI_MONITOR so Bitrix stops shredding multiline text.

Bitrix string fields use SETTINGS.SIZE as the visible column width. SIZE=20
makes a 16-row textarea ~20 characters wide — long chats wrap mid-word and
look like overlapping columns on the lead card.

Bitrix Cloud sometimes ignores SIZE via crm.lead.userfield.update while still
accepting ROWS. This script tries several REST shapes until SIZE sticks.
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

base = (os.environ.get("BITRIX_WEBHOOK_BASE") or "").rstrip("/")
if not base:
    sys.exit("BITRIX_WEBHOOK_BASE missing")

CHAT_SETTINGS = {
    "SIZE": 80,
    "ROWS": 18,
    "REGEXP": "",
    "MIN_LENGTH": 0,
    "MAX_LENGTH": 0,
    "DEFAULT_VALUE": "",
}
MONITOR_SETTINGS = {
    "SIZE": 80,
    "ROWS": 8,
    "REGEXP": "",
    "MIN_LENGTH": 0,
    "MAX_LENGTH": 0,
    "DEFAULT_VALUE": "",
}


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


def field_meta(name: str) -> dict | None:
    rows = post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": name}}).get("result") or []
    return rows[0] if rows else None


def size_of(meta: dict | None) -> int:
    if not meta:
        return 0
    try:
        return int((meta.get("SETTINGS") or {}).get("SIZE") or 0)
    except (TypeError, ValueError):
        return 0


def try_updates(fid: int, label: str, settings: dict) -> None:
    attempts = [
        (
            "crm.lead.userfield.update",
            {
                "id": fid,
                "fields": {
                    "EDIT_FORM_LABEL": {"en": label},
                    "LIST_COLUMN_LABEL": {"en": label},
                    "LIST_FILTER_LABEL": {"en": label},
                    "SHOW_IN_LIST": "Y",
                    "EDIT_IN_LIST": "Y",
                    "SETTINGS": settings,
                },
            },
        ),
        (
            "crm.lead.userfield.update",
            {
                "id": fid,
                "fields": {
                    "SETTINGS": {
                        "SIZE": str(settings["SIZE"]),
                        "ROWS": str(settings["ROWS"]),
                    }
                },
            },
        ),
        (
            "userfieldconfig.update",
            {
                "moduleId": "crm",
                "field": {
                    "id": fid,
                    "editFormLabel": {"en": label},
                    "listColumnLabel": {"en": label},
                    "listFilterLabel": {"en": label},
                    "settings": {
                        "size": settings["SIZE"],
                        "rows": settings["ROWS"],
                    },
                },
            },
        ),
        (
            "userfieldconfig.update",
            {
                "moduleId": "crm",
                "field": {
                    "id": fid,
                    "settings": {
                        "SIZE": settings["SIZE"],
                        "ROWS": settings["ROWS"],
                    },
                },
            },
        ),
        # Older / alternate method names seen on some portals
        (
            "user.userfield.update",
            {
                "id": fid,
                "fields": {"SETTINGS": settings},
            },
        ),
    ]

    for method, payload in attempts:
        resp = post(method, payload)
        after = field_meta_by_id(fid)
        print(
            f"  try {method} -> result={resp.get('result')!r} "
            f"err={resp.get('error')!r} size={size_of(after)} rows={(after or {}).get('SETTINGS', {}).get('ROWS')}"
        )
        if size_of(after) >= 60:
            return
    print("  WARN: SIZE still < 60 after all attempts")


def field_meta_by_id(fid: int) -> dict | None:
    got = post("crm.lead.userfield.get", {"id": fid})
    return got.get("result")


do_fix = "--fix" in sys.argv

for name, settings, label in (
    ("UF_CRM_WA_CHAT", CHAT_SETTINGS, "WhatsApp Chat"),
    ("UF_CRM_AI_MONITOR", MONITOR_SETTINGS, "AI Monitor"),
):
    meta = field_meta(name)
    if not meta:
        print(f"MISSING {name}")
        continue
    fid = int(meta["ID"])
    print(
        f"=== {name} id={fid} before SIZE={size_of(meta)} "
        f"ROWS={(meta.get('SETTINGS') or {}).get('ROWS')} type={meta.get('USER_TYPE_ID')}"
    )
    print("  full SETTINGS", json.dumps(meta.get("SETTINGS") or {}, ensure_ascii=False))
    if not do_fix:
        continue
    try_updates(fid, label, settings)
    after = field_meta(name) or {}
    print(
        f"after SIZE={size_of(after)} ROWS={(after.get('SETTINGS') or {}).get('ROWS')}"
    )

if not do_fix:
    print("dry-run only; pass --fix to apply")
