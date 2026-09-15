#!/usr/bin/env python3
"""Probe why Owner Data (type 1042) kanban shows AED0 on New Availability."""
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

TYPE_ID = int(os.environ.get("BITRIX_OWNER_DATA_TYPE_ID") or "1042")
CATEGORY_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 14
SAMPLE_ID = int(sys.argv[2]) if len(sys.argv) > 2 else 86882


def post(method: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"error": f"HTTP_{e.code}", "error_description": body[:500]}


print("=== type", TYPE_ID, "category", CATEGORY_ID, "===")

# Type / SPA meta
for method, payload in (
    ("crm.type.get", {"id": TYPE_ID}),
    ("crm.category.list", {"entityTypeId": TYPE_ID}),
    ("crm.status.entity.types", {}),
):
    resp = post(method, payload)
    print(f"--- {method} ---")
    if resp.get("error"):
        print(resp.get("error"), resp.get("error_description"))
    else:
        print(json.dumps(resp.get("result"), ensure_ascii=False)[:4000])

# Stages for this category
stages = post(
    "crm.status.list",
    {"filter": {"ENTITY_ID": f"DYNAMIC_{TYPE_ID}_STAGE_{CATEGORY_ID}"}},
)
print("--- stages ---")
if stages.get("error"):
    # try alternate entity id shapes
    print("err", stages.get("error"), stages.get("error_description"))
    for ent in (
        f"DYNAMIC_{TYPE_ID}_STAGE_{CATEGORY_ID}",
        f"DT{TYPE_ID}_{CATEGORY_ID}",
        f"DYNAMIC_{TYPE_ID}_STAGE",
    ):
        alt = post("crm.status.list", {"filter": {"ENTITY_ID": ent}})
        print("try ENTITY_ID", ent, "err", alt.get("error"), "n", len(alt.get("result") or []))
        if alt.get("result"):
            stages = alt
            break
else:
    print("n", len(stages.get("result") or []))

for st in (stages.get("result") or [])[:20]:
    print(
        f"  {st.get('STATUS_ID')} name={st.get('NAME')!r} "
        f"sort={st.get('SORT')} semantics={st.get('SEMANTICS')}"
    )

# Fields that look like money / price / lease / sale / rent / opportunity
fields = post("crm.item.fields", {"entityTypeId": TYPE_ID})
print("--- money-ish fields ---")
flist = fields.get("result") or fields.get("result", {})
if isinstance(flist, dict) and "fields" in flist:
    flist = flist["fields"]
if not isinstance(flist, dict):
    print("unexpected fields shape", type(flist), str(fields)[:500])
    flist = {}

money_keys = []
for name, meta in flist.items():
    label = ""
    if isinstance(meta, dict):
        title = meta.get("title") or meta.get("formLabel") or meta.get("listLabel") or ""
        if isinstance(title, dict):
            label = title.get("en") or next(iter(title.values()), "")
        else:
            label = str(title)
        utype = meta.get("type") or meta.get("userType") or ""
    else:
        utype = ""
    blob = f"{name} {label} {utype}".lower()
    if any(
        k in blob
        for k in (
            "price",
            "lease",
            "rent",
            "sale",
            "aed",
            "money",
            "opportunit",
            "amount",
            "sum",
            "value",
        )
    ):
        money_keys.append(name)
        print(f"  {name}: type={utype!r} label={label!r}")

# Sample item
print("--- sample item", SAMPLE_ID, "---")
item = post("crm.item.get", {"entityTypeId": TYPE_ID, "id": SAMPLE_ID})
if item.get("error"):
    print(item.get("error"), item.get("error_description"))
else:
    row = item.get("result") or {}
    if isinstance(row, dict) and "item" in row:
        row = row["item"]
    print("stageId", row.get("stageId") or row.get("STAGE_ID"))
    print("categoryId", row.get("categoryId") or row.get("CATEGORY_ID"))
    print("opportunity", row.get("opportunity") or row.get("OPPORTUNITY"))
    print("currencyId", row.get("currencyId") or row.get("CURRENCY_ID"))
    print("isManualOpportunity", row.get("isManualOpportunity"))
    for k in money_keys:
        # Bitrix item API uses camelCase ufCrm5_...
        camel = k
        if k.startswith("UF_"):
            # ufCrm5_123 style often returned as ufCrm5_123
            parts = k.split("_")
            camel = parts[0].lower() + "".join(
                p[:1].upper() + p[1:] if i else p for i, p in enumerate(parts[1:])
            )
            # simpler: try both
        val = row.get(k)
        if val is None:
            # try ufCrm5_xxx from UF_CRM_5_xxx
            alt = k
            if k.upper().startswith("UF_CRM_"):
                alt = "ufCrm" + k[7:].replace("_", "_")
            # common SPA: ufCrm5_1768...
            for cand in (k, k.lower(), camel):
                if cand in row and row[cand] is not None:
                    val = row[cand]
                    print(f"  {cand} = {val!r}")
                    break
            else:
                # brute: any key containing digits from field
                digits = "".join(ch for ch in k if ch.isdigit())
                hits = [kk for kk in row if digits and digits in kk and ("price" in kk.lower() or "uf" in kk.lower() or "Crm" in kk)]
                if not hits:
                    hits = [kk for kk in row if digits and digits in str(kk)]
                for kk in hits[:3]:
                    print(f"  {kk} = {row.get(kk)!r}")
        else:
            print(f"  {k} = {val!r}")

# Aggregate by stage: sum opportunity vs lease-like UFs for a few stages
print("--- per-stage totals (first page per stage) ---")
stage_ids = [st.get("STATUS_ID") for st in (stages.get("result") or [])]
select = ["id", "stageId", "opportunity", "currencyId", "title"] + money_keys[:30]
# normalize select to what item.list accepts — use camelCase common fields + raw UF
select = list(dict.fromkeys(select))

for sid in stage_ids[:8]:
    resp = post(
        "crm.item.list",
        {
            "entityTypeId": TYPE_ID,
            "filter": {"categoryId": CATEGORY_ID, "stageId": sid},
            "select": select,
            "start": 0,
        },
    )
    if resp.get("error"):
        print(sid, "list err", resp.get("error"), resp.get("error_description"))
        continue
    items = resp.get("result") or {}
    if isinstance(items, dict):
        items = items.get("items") or []
    total = resp.get("total")
    opp_sum = 0.0
    uf_sums: dict[str, float] = {}
    nonempty_opp = 0
    for it in items:
        try:
            o = float(it.get("opportunity") or 0)
        except (TypeError, ValueError):
            o = 0.0
        if o:
            nonempty_opp += 1
        opp_sum += o
        for k, v in it.items():
            if k in ("id", "stageId", "opportunity", "currencyId", "title"):
                continue
            try:
                n = float(v)
            except (TypeError, ValueError):
                continue
            if n:
                uf_sums[k] = uf_sums.get(k, 0.0) + n
    top_ufs = sorted(uf_sums.items(), key=lambda kv: -kv[1])[:5]
    print(
        f"{sid}: total={total} page={len(items)} opp_sum={opp_sum:.0f} "
        f"nonempty_opp={nonempty_opp} top_ufs={top_ufs}"
    )

print("DONE")
