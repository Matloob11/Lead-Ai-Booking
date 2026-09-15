"""Link Owner Data phone UF to a Contact so Bitrix call button activates.

Usage:
  python scripts/link_owner_phone_to_contact.py 86884
"""
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
from app.bitrix.owner_phone_link import ENTITY_TYPE_ID, PHONE_UFS, link_item


def main() -> None:
    item_id = int(sys.argv[1]) if len(sys.argv) > 1 else 86884
    client = BitrixClient(os.environ["AGENT_REPORT_BITRIX_WEBHOOK"])
    item = client._post("crm.item.get", {"entityTypeId": ENTITY_TYPE_ID, "id": item_id})
    it = (item.get("result") or {}).get("item") or {}
    if not it:
        raise SystemExit(f"item {item_id} not found")
    print(json.dumps(link_item(client, it), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
