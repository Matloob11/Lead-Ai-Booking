"""Build full section B of a7_community_map.md from the TSVs."""
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT.parent / "files" / "temp"
OUT = Path(__file__).with_name("a7_community_map.md")

comms = []
with open(TEMP / "c43-communities.tsv", encoding="utf-8") as f:
    next(f)
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        name, _, n = line.rpartition("\t")
        if n.isdigit():
            comms.append((name, int(n)))

subs = {}
with open(TEMP / "c43-subs.tsv", encoding="utf-8") as f:
    next(f)
    for line in f:
        parts = line.rstrip("\n").split("\t", 1)
        if len(parts) == 2 and parts[0].isdigit():
            subs[int(parts[0])] = parts[1]

parents = defaultdict(list)
with open(TEMP / "c43-parents-all.tsv", encoding="utf-8") as f:
    next(f)
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        sid, comm, n = int(parts[0]), parts[1], int(parts[2])
        parents[sid].append((n, comm))
top = {sid: sorted(v, reverse=True)[0][1] for sid, v in parents.items()}

head = [
    "# C43 - Community / Sub Community map",
    "",
    "Read-only dump 2026-10-20 from Bitrix CRM (`ops/bitrix.sh sql`). No writes.",
    "",
    "- Lead **Community** field: `UF_CRM_1770537051525` (string on `b_uts_crm_lead`).",
    "- Lead **Sub Community** field: `UF_CRM_1763390179` (CRM link -> SPA **1062** Sub Community).",
    "- SPA 1062 has no parent-community user field; **Parent community** below is the most common Community value on leads that link that Sub Community id (co-occurrence). Blank means no lead carries both.",
    "- Exact Community spellings are listed so aliases can be added in Lead AI -> Communities.",
    "",
    "## A. Distinct Community values on leads",
    "",
    "| Community (exact) | Leads |",
    "|---|---:|",
]
for name, n in comms:
    head.append(f"| {name.replace('|', '\\|')} | {n} |")
head += [
    "",
    f"Total distinct spellings: **{len(comms)}**.",
    "",
    "## B. SPA 1062 Sub Community id -> name -> parent community",
    "",
    "| Id | Name | Parent community (from leads) |",
    "|---:|---|---|",
]
rows = []
for sid in sorted(subs):
    name = subs[sid].replace("|", "\\|")
    parent = top.get(sid, "").replace("|", "\\|")
    rows.append(f"| {sid} | {name} | {parent} |")
tail = [
    "",
    f"Total Sub Community cards: **{len(subs)}**. With a lead-derived parent: **{sum(1 for s in subs if s in top)}**.",
    "",
]
OUT.write_text("\n".join(head + rows + tail), encoding="utf-8")
print(f"wrote {OUT} lines={len(head)+len(rows)+len(tail)} parented={sum(1 for s in subs if s in top)}")
