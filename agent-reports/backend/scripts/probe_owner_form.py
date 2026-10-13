"""Probe Owner Data (1042) detail form configuration."""
from __future__ import annotations

import json
import os

from app.bitrix.client import BitrixClient


def main() -> None:
    webhook = os.environ.get("AGENT_REPORT_BITRIX_WEBHOOK") or ""
    c = BitrixClient(webhook)
    for params in (
        {"entityTypeId": 1042, "scope": "C"},
        {"entityTypeId": 1042, "scope": "C", "categoryId": 13},
        {"entityTypeId": 1042, "scope": "C", "categoryId": 14},
        {"entityTypeId": 1042, "scope": "P", "userId": 1},
    ):
        try:
            r = c._post("crm.item.details.configuration.get", params)
            print("GET", params, "keys", list(r.keys()))
            result = r.get("result") or {}
            print(json.dumps(result, ensure_ascii=False, indent=2)[:8000])
        except Exception as exc:
            print("GET", params, "ERR", exc)
        print("---")


if __name__ == "__main__":
    main()
