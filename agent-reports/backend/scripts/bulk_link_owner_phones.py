"""CLI: bulk-link Owner Data phones to Contacts (call button).

  python scripts/bulk_link_owner_phones.py
  python scripts/bulk_link_owner_phones.py --dry-run --limit 50
  python scripts/bulk_link_owner_phones.py --category 13 --since-days 30
  python scripts/bulk_link_owner_phones.py --category 13 --id-min 1 --id-max 22042
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
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
    parser.add_argument(
        "--category",
        type=int,
        default=None,
        help="SPA categoryId (13=Owner Data calling, 14=Availability)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help="Only items created in the last N days",
    )
    parser.add_argument("--id-min", type=int, default=None, help="Inclusive min item id")
    parser.add_argument("--id-max", type=int, default=None, help="Exclusive max item id")
    args = parser.parse_args()

    webhook = os.environ.get("AGENT_REPORT_BITRIX_WEBHOOK") or ""
    if not webhook:
        raise SystemExit("AGENT_REPORT_BITRIX_WEBHOOK is not set")

    created_since = None
    if args.since_days is not None and args.since_days > 0:
        created_since = (
            datetime.now(timezone.utc) - timedelta(days=args.since_days)
        ).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    client = BitrixClient(webhook)
    result = sync_owner_phone_links(
        client,
        limit=args.limit,
        dry_run=args.dry_run,
        sleep_s=0.05,
        only_unlinked=not args.all,
        category_id=args.category,
        created_since=created_since,
        id_min=args.id_min,
        id_max=args.id_max,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
