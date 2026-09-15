"""CLI: link Renewals (deal category 9) phones → Contacts for call button.

  python scripts/bulk_link_renewal_deal_phones.py --dry-run --limit 20
  python scripts/bulk_link_renewal_deal_phones.py
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
BACKEND = HERE.parent
load_dotenv(BACKEND / ".env")
load_dotenv(BACKEND.parent / ".env")
sys.path.insert(0, str(BACKEND))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.bitrix.client import BitrixClient
from app.bitrix.deal_phone_link import RENEWAL_TARGET_STAGES, sync_renewal_deal_phones


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also re-check deals that already have CONTACT_ID",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default="",
        help="Comma-separated STAGE_ID list (default: all renewal target stages)",
    )
    args = parser.parse_args()

    webhook = os.environ.get("AGENT_REPORT_BITRIX_WEBHOOK") or ""
    if not webhook:
        raise SystemExit("AGENT_REPORT_BITRIX_WEBHOOK is not set")

    stages = RENEWAL_TARGET_STAGES
    if args.stages.strip():
        stages = tuple(s.strip() for s in args.stages.split(",") if s.strip())

    client = BitrixClient(webhook)
    result = sync_renewal_deal_phones(
        client,
        limit=args.limit,
        dry_run=args.dry_run,
        sleep_s=0.02,
        only_unlinked=not args.all,
        stages=stages,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
