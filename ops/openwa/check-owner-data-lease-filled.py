#!/usr/bin/env python3
"""How many New Availability items have Lease/Selling price vs opportunity."""
from __future__ import annotations

import json
import os
import sys
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
TYPE_ID = 1042
LEASE = "ufCrm5_1734247036310"
SELL = "ufCrm5_1734247021855"
STAGE = "DT1042_14:NEW"


def post(method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


# Filter: lease filled
for label, flt in (
    ("lease>0", {"categoryId": 14, "stageId": STAGE, ">" + LEASE: 0}),
    ("sell>0", {"categoryId": 14, "stageId": STAGE, ">" + SELL: 0}),
    ("opp>0", {"categoryId": 14, "stageId": STAGE, ">opportunity": 0}),
    ("id=86882", {"id": 86882}),
):
    resp = post(
        "crm.item.list",
        {
            "entityTypeId": TYPE_ID,
            "filter": flt,
            "select": ["id", "stageId", "opportunity", LEASE, SELL, "title"],
            "start": 0,
        },
    )
    result = resp.get("result") or {}
    items = result.get("items") if isinstance(result, dict) else result
    items = items or []
    print(label, "total", resp.get("total"), "page", len(items), "err", resp.get("error"))
    for it in items[:3]:
        print(
            " ",
            it.get("id"),
            "stage",
            it.get("stageId"),
            "opp",
            it.get("opportunity"),
            "lease",
            it.get(LEASE),
            "sell",
            it.get(SELL),
        )

got = post("crm.item.get", {"entityTypeId": TYPE_ID, "id": 86882})
row = (got.get("result") or {}).get("item") or got.get("result") or {}
print(
    "GET 86882 stage",
    row.get("stageId"),
    "opp",
    row.get("opportunity"),
    "lease",
    row.get(LEASE),
    "sell",
    row.get(SELL),
    "keys_has_lease",
    LEASE in row,
)

# Find 86882 inside stage pagination + try alternate filters.
found = None
start = 0
while True:
    resp = post(
        "crm.item.list",
        {
            "entityTypeId": TYPE_ID,
            "filter": {"categoryId": 14, "stageId": STAGE},
            "select": ["id", "opportunity", LEASE, SELL],
            "start": start,
        },
    )
    items = (resp.get("result") or {}).get("items") or []
    for it in items:
        if int(it.get("id") or 0) == 86882:
            found = it
            print("FOUND in stage list", it)
    if resp.get("next") is None:
        break
    start = int(resp["next"])
print("86882 in stage pages?", bool(found))

for label, flt in (
    ("!lease false", {"categoryId": 14, "stageId": STAGE, "!" + LEASE: False}),
    ("!lease ''", {"categoryId": 14, "stageId": STAGE, "!" + LEASE: ""}),
    (">lease 1", {"categoryId": 14, "stageId": STAGE, ">" + LEASE: 1}),
    (">=lease 1000", {"categoryId": 14, "stageId": STAGE, ">=" + LEASE: 1000}),
):
    resp = post(
        "crm.item.list",
        {
            "entityTypeId": TYPE_ID,
            "filter": flt,
            "select": ["id", LEASE, SELL, "opportunity"],
            "start": 0,
        },
    )
    items = (resp.get("result") or {}).get("items") or []
    ids = [it.get("id") for it in items]
    print(label, "total", resp.get("total"), "has86882", 86882 in ids, "err", resp.get("error"))
