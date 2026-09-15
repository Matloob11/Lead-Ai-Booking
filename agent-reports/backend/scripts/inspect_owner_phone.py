"""Inspect Owner Data SPA (1042) phone/call-button prerequisites."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parents[0] / ".env")
sys.path.insert(0, str(ROOT / "backend"))

from app.bitrix.client import BitrixClient


def main() -> None:
    c = BitrixClient(os.environ["AGENT_REPORT_BITRIX_WEBHOOK"])

    types = c._post("crm.type.list", {})
    owner = None
    for t in (types.get("result") or {}).get("types") or types.get("result") or []:
        if int(t.get("entityTypeId") or 0) == 1042 or "owner" in str(t.get("title") or "").lower():
            print("TYPE:", json.dumps(t, ensure_ascii=False, indent=2)[:2000])
            owner = t

    fields_payload = c._post("crm.item.fields", {"entityTypeId": 1042})
    fields = (fields_payload.get("result") or {}).get("fields") or fields_payload.get("result") or {}
    print("\n--- phone-ish fields ---")
    for k, v in sorted(fields.items()):
        if not isinstance(v, dict):
            continue
        title = str(v.get("title") or "")
        typ = str(v.get("type") or "")
        blob = f"{k} {title} {typ}".lower()
        if any(x in blob for x in ("phone", "email", "fm", "client", "contact", "company")):
            print(f"{k}: type={typ} title={title!r} isMultiple={v.get('isMultiple')} isDynamic={v.get('isDynamic')}")

    print("\n--- hasPhone / fm / contactId presence ---")
    for key in ("fm", "hasPhone", "phone", "contactId", "companyId", "client"):
        print(key, "IN fields" if key in fields else "missing", fields.get(key, {}).get("type") if isinstance(fields.get(key), dict) else "")

    item = c._post("crm.item.get", {"entityTypeId": 1042, "id": 86884})
    it = (item.get("result") or {}).get("item") or {}
    print("\n--- item 86884 key fields ---")
    for k, v in sorted(it.items()):
        lk = k.lower()
        if any(x in lk for x in ("phone", "email", "fm", "contact", "company", "client", "title", "assigned")):
            print(f"{k} = {v!r}")

    # Lead fields for comparison
    lead_fields = c._post("crm.item.fields", {"entityTypeId": 1})
    lf = (lead_fields.get("result") or {}).get("fields") or lead_fields.get("result") or {}
    print("\n--- lead hasPhone/fm ---")
    for key in ("fm", "hasPhone", "phone", "contactId"):
        print("lead", key, "yes" if key in lf else "no", (lf.get(key) or {}).get("type") if isinstance(lf.get(key), dict) else "")


if __name__ == "__main__":
    main()
