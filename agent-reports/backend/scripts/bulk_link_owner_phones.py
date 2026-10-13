"""CLI: bulk-link all Owner Data phones to Contacts (call button).

  python scripts/bulk_link_owner_phones.py
  python scripts/bulk_link_owner_phones.py --dry-run --limit 50
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent  # backend/ locally, /app in Docker image
load_dotenv(BACKEND / ".env")
load_dotenv(BACKEND.parent / ".env")
sys.path.insert(0, str(BACKEND))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.bitrix.client import BitrixClient
from app.bitrix.owner_phone_link import sync_owner_phone_links


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also re-check already linked items",
    )
    args = parser.parse_args()

    webhook = os.environ.get("AGENT_REPORT_BITRIX_WEBHOOK") or ""
    if not webhook:
        raise SystemExit("AGENT_REPORT_BITRIX_WEBHOOK is not set")

    client = BitrixClient(webhook)
    result = sync_owner_phone_links(
        client,
        limit=args.limit,
        dry_run=args.dry_run,
        sleep_s=0.05,
        only_unlinked=not args.all,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
