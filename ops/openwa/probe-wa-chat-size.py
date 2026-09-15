#!/usr/bin/env python3
"""Probe Bitrix userfield.update for UF_CRM_WA_CHAT SIZE."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_base() -> str:
    env = os.environ.get("BITRIX_WEBHOOK_BASE", "").strip()
    if env:
        return env.rstrip("/") + "/"
    root = Path(__file__).resolve().parents[2]
    for candidate in (
        root / "openwa" / ".env",
        Path("/opt/a7-wa/openwa/.env"),
        Path("/opt/a7-wa/openwa/api/.env"),
    ):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("BITRIX_WEBHOOK_BASE="):
                return line.split("=", 1)[1].strip().strip("\"'").rstrip("/") + "/"
    # last resort: scan openwa tree on server
    for p in Path("/opt/a7-wa/openwa").rglob(".env"):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("BITRIX_WEBHOOK_BASE="):
                return line.split("=", 1)[1].strip().strip("\"'").rstrip("/") + "/"
    raise SystemExit("BITRIX_WEBHOOK_BASE not found")


def call(base: str, method: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        base + method,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    base = load_base()
    field_id = int(sys.argv[1]) if len(sys.argv) > 1 else 2524

    payloads = [
        {"id": field_id, "fields": {"SETTINGS": {"SIZE": 80, "ROWS": 18}}},
        {"ID": field_id, "FIELDS": {"SETTINGS": {"SIZE": 80, "ROWS": 18}}},
        {"id": str(field_id), "fields": {"SETTINGS": {"SIZE": "80", "ROWS": "18"}}},
        {
            "id": field_id,
            "fields": {
                "EDIT_IN_LIST": "Y",
                "SETTINGS": {
                    "SIZE": 80,
                    "ROWS": 18,
                    "REGEXP": "",
                    "MIN_LENGTH": 0,
                    "MAX_LENGTH": 0,
                    "DEFAULT_VALUE": "",
                },
            },
        },
    ]

    for payload in payloads:
        try:
            r = call(base, "crm.lead.userfield.update", payload)
            print("OK", json.dumps(payload), "->", json.dumps(r))
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            print("HTTP", e.code, json.dumps(payload), body[:300])
        except Exception as e:
            print("ERR", json.dumps(payload), e)

    meta = call(base, "crm.lead.userfield.get", {"id": field_id})
    settings = meta.get("result", {}).get("SETTINGS", {})
    print("CURRENT", json.dumps(settings))
    print("USER_TYPE_ID", meta.get("result", {}).get("USER_TYPE_ID"))
    print("MULTIPLE", meta.get("result", {}).get("MULTIPLE"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
