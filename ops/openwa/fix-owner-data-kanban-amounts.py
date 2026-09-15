#!/usr/bin/env python3
"""Sync Owner Data SPA Amount (opportunity) from price UFs so kanban AED totals work.

Bitrix kanban sums the built-in `opportunity` field, not custom UFs. Cards show
Lease/Selling Price, but columns stay AED0 when opportunity is empty.

Pipelines:
  category 14 (Availability) — prefer Lease, except Sale stages → Selling
  category 13 (Owner Data calling board) — prefer Selling, else Lease
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
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
    # Agent-reports webhook is the same inbound REST user on this project.
    base = (os.environ.get("AGENT_REPORT_BITRIX_WEBHOOK") or "").rstrip("/")
if not base:
    sys.exit("BITRIX_WEBHOOK_BASE missing")

TYPE_ID = int(os.environ.get("BITRIX_OWNER_DATA_TYPE_ID") or "1042")
SELL_UF = "ufCrm5_1734247021855"  # Selling Price (In AED)
LEASE_UF = "ufCrm5_1734247036310"  # Lease Price (In AED)

# Availability (category 14)
CAT14_SALE_STAGES = {"DT1042_14:PREPARATION"}
CAT14_STAGES = {
    "DT1042_14:NEW",
    "DT1042_14:UC_G0PCBL",
    "DT1042_14:UC_39DSJP",
    "DT1042_14:UC_73SP7H",
}

# Calling board (category 13) — stages visible on the Owner Data kanban
CAT13_STAGES = {
    "DT1042_13:UC_0RLVRR",  # Name
    "DT1042_13:NEW",  # New Data
    "DT1042_13:PREPARATION",  # Assigned to Caller
    "DT1042_13:UC_2C7RN8",  # No Answer
    "DT1042_13:UC_NT7K67",  # Contacted/In Progress
    "DT1042_13:UC_DC7XPD",  # Create Availability
    "DT1042_13:UC_MG6OWT",  # Create Lead
    "DT1042_13:UC_KDOG9V",  # doesn't have for sale/rent
    "DT1042_13:UC_MXB8Q9",  # unit availability date
    "DT1042_13:UC_PVGQLX",  # talk to agent / owner
}


def post(method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP_{e.code}", "error_description": body[:400]}


def as_float(v) -> float:
    if v is None or v is False or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pick_amount(stage_id: str, item: dict, *, prefer: str) -> float:
    sell = as_float(item.get(SELL_UF))
    lease = as_float(item.get(LEASE_UF))
    if stage_id in CAT14_SALE_STAGES:
        return sell or lease
    if prefer == "sell":
        return sell or lease
    return lease or sell


def batch_update(links: list[tuple[int, float, str]]) -> tuple[int, int]:
    """Set opportunity for (id, amount, currency). Returns (ok, err)."""
    ok = err = 0
    for i in range(0, len(links), 40):
        chunk = links[i : i + 40]
        cmds = {}
        for j, (iid, amount, currency) in enumerate(chunk):
            params = {
                "entityTypeId": TYPE_ID,
                "id": iid,
                "fields[opportunity]": f"{amount:.2f}",
                "fields[currencyId]": currency or "AED",
                "fields[isManualOpportunity]": "Y",
            }
            cmds[f"u{j}"] = "crm.item.update?" + urllib.parse.urlencode(params)
        resp = post("batch", {"halt": 0, "cmd": cmds})
        result = resp.get("result") or {}
        if isinstance(result, dict) and "result" in result:
            result = result.get("result") or {}
        result_err = {}
        if isinstance(resp.get("result"), dict):
            result_err = (resp["result"].get("result_error")) or {}
        for j, _ in enumerate(chunk):
            key = f"u{j}"
            if result_err.get(key) or result.get(key) is False:
                err += 1
            elif result.get(key) is not None:
                ok += 1
            else:
                err += 1
        time.sleep(0.05)
    return ok, err


def sync_stages(
    *,
    category_id: int,
    stages: set[str],
    prefer: str,
    do_fix: bool,
) -> dict[str, int]:
    counts = {"scanned": 0, "updated": 0, "skipped": 0, "errors": 0, "would": 0}
    pending: list[tuple[int, float, str]] = []
    seen_ids: set[int] = set()

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        if not do_fix:
            counts["would"] += len(pending)
            pending = []
            return
        ok, err = batch_update(pending)
        counts["updated"] += ok
        counts["errors"] += err
        pending = []

    def handle_item(it: dict) -> None:
        iid = int(it.get("id") or 0)
        if not iid or iid in seen_ids:
            return
        seen_ids.add(iid)
        counts["scanned"] += 1
        if as_float(it.get("opportunity")) > 0:
            counts["skipped"] += 1
            return
        want = pick_amount(str(it.get("stageId") or ""), it, prefer=prefer)
        if want <= 0:
            counts["skipped"] += 1
            return
        pending.append((iid, want, str(it.get("currencyId") or "AED")))
        if len(pending) >= 40:
            flush()
            if counts["updated"] and counts["updated"] % 200 == 0:
                print(f"  progress category={category_id} {counts}")

    for stage_id in sorted(stages):
        for price_key in (SELL_UF, LEASE_UF):
            start = 0
            while True:
                resp = post(
                    "crm.item.list",
                    {
                        "entityTypeId": TYPE_ID,
                        "filter": {
                            "categoryId": category_id,
                            "stageId": stage_id,
                            "opportunity": 0,
                            f">{price_key}": 0,
                        },
                        "select": [
                            "id",
                            "stageId",
                            "opportunity",
                            "currencyId",
                            SELL_UF,
                            LEASE_UF,
                        ],
                        # Always start=0: updates remove rows from this filter, so
                        # advancing `next` would skip half the queue.
                        "start": 0,
                        "order": {"id": "ASC"},
                    },
                )
                if resp.get("error"):
                    print(
                        "list error",
                        stage_id,
                        price_key,
                        resp.get("error"),
                        resp.get("error_description"),
                    )
                    break
                result = resp.get("result") or {}
                items = result.get("items") if isinstance(result, dict) else result
                items = items or []
                if not items:
                    print(
                        f"{stage_id} {price_key[-4:]}: empty total={resp.get('total')}"
                    )
                    break
                before = counts["updated"] + counts["would"]
                for it in items:
                    handle_item(it)
                flush()
                after = counts["updated"] + counts["would"]
                print(
                    f"{stage_id} {price_key[-4:]}: page={len(items)} "
                    f"total={resp.get('total')} wrote={after - before} {counts}"
                )
                # Safety: if a full page produced no writes, stop to avoid a loop
                # (e.g. all skipped / already processed this pass).
                if after == before:
                    break
                time.sleep(0.05)
    return counts


def main() -> None:
    do_fix = "--fix" in sys.argv
    only_new = "--only-new" in sys.argv  # Availability New only (legacy cron)
    only_calling = "--calling" in sys.argv  # category 13 only
    only_availability = "--availability" in sys.argv

    jobs: list[tuple[int, set[str], str]] = []
    if only_new:
        jobs.append((14, {"DT1042_14:NEW"}, "lease"))
    elif only_calling:
        jobs.append((13, CAT13_STAGES, "sell"))
    elif only_availability:
        jobs.append((14, CAT14_STAGES, "lease"))
    else:
        # Default: Availability stages + calling board stages
        jobs.append((14, CAT14_STAGES, "lease"))
        jobs.append((13, CAT13_STAGES, "sell"))

    grand = {"scanned": 0, "updated": 0, "skipped": 0, "errors": 0, "would": 0}
    for category_id, stages, prefer in jobs:
        print(f"=== category {category_id} prefer={prefer} stages={len(stages)} fix={do_fix} ===")
        counts = sync_stages(
            category_id=category_id,
            stages=stages,
            prefer=prefer,
            do_fix=do_fix,
        )
        print(f"  category {category_id} done {counts}")
        for k, v in counts.items():
            grand[k] = grand.get(k, 0) + v

    print(f"TOTAL {grand} fix={do_fix}")
    if not do_fix:
        print("dry-run only; pass --fix to write. Flags: --only-new | --calling | --availability")


if __name__ == "__main__":
    main()
