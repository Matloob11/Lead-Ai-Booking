"""Queue Old Leads Before 6 Month on Lead AI.

International City → intl_city_property_reconnect, playbook ic_shops.
Everyone else → property_enquiry_reconnect, playbook general.

Audience JSON at OLD6_PATH ({"ic": [...], "other": [...]} or a .b64 file of that).
OLD6_SEND=1 queues. Otherwise dry-run counts only.

Dedupes by lead id and canonical phone across both groups before round-robin.
Queues at most OLD6_MAX_IN_FLIGHT (default 2) campaigns at a time. Skips
agency-looking names before send.

Refuses to send unless property_enquiry_reconnect is a mixed template in this image.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections import Counter
from typing import Optional

from django.contrib.auth import get_user_model

from apps.campaigns.crm_leads import CrmLeadSendError, send_from_leads
from apps.campaigns.models import Campaign
from apps.catalog.models import WabaNumber, WaTemplate
from apps.leadai import ic_templates

if ic_templates.kind(ic_templates.ENQUIRY_NAME) != ic_templates.MIXED:
    raise SystemExit("property_enquiry_reconnect is not mixed in this image; refusing to send")

SEND = os.environ.get("OLD6_SEND", "").strip() == "1"
CHUNK = 250
MAX_IN_FLIGHT = max(1, int(os.environ.get("OLD6_MAX_IN_FLIGHT", "2") or "2"))
PHONES = [
    "971581058719",
    "971581058720",
    "971581058721",
    "971581058722",
    "971581058723",
    "971581058724",
    "971581058725",
    "971581058726",
]
AGENT_BITRIX = "2311"
EXTRA = {"2": "Malik"}
GROUPS = (
    ("ic", "intl_city_property_reconnect", "ic_shops"),
    ("other", "property_enquiry_reconnect", "general"),
)

AGENCY_WORDS = (
    "properties",
    "real estate",
    "realty",
    "brokers",
    "property consultant",
    "specialist",
    "llc",
    "group",
)
_AGENCY_RE = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:"
    + "|".join(re.escape(w) for w in AGENCY_WORDS)
    + r")(?:[^a-z0-9]|$)"
)


def canonical_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def looks_agency(row: dict) -> bool:
    blob = " ".join(str(row.get(key) or "") for key in ("name", "company", "title"))
    return bool(blob.strip() and _AGENCY_RE.search(blob))


def mask_phone(phone: str) -> str:
    digits = canonical_phone(phone)
    if len(digits) <= 4:
        return "****"
    return digits[:3] + ("*" * max(0, len(digits) - 6)) + digits[-3:]


def normalize_row(row: dict) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    try:
        lead_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        return None
    phone = canonical_phone(row.get("phone") or "")
    return {
        "id": lead_id,
        "phone": phone,
        "name": str(row.get("name") or "").strip(),
        "company": str(row.get("company") or "").strip(),
        "title": str(row.get("title") or ""),
    }


def dedupe_audience(rows: list[dict]) -> tuple[list[dict], dict]:
    """Keep first sighting of each lead id and each canonical phone. Before round-robin."""
    seen_ids: set[int] = set()
    seen_phones: set[str] = set()
    kept: list[dict] = []
    stats = {"dup_lead_id": 0, "dup_phone": 0, "no_phone": 0, "no_id": 0}
    for raw in rows:
        row = normalize_row(raw)
        if row is None:
            stats["no_id"] += 1
            continue
        if row["id"] <= 0:
            stats["no_id"] += 1
            continue
        if row["id"] in seen_ids:
            stats["dup_lead_id"] += 1
            continue
        if len(row["phone"]) < 8:
            stats["no_phone"] += 1
            continue
        if row["phone"] in seen_phones:
            stats["dup_phone"] += 1
            continue
        seen_ids.add(row["id"])
        seen_phones.add(row["phone"])
        kept.append(row)
    return kept, stats


def filter_agency(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, skipped = [], []
    for row in rows:
        if looks_agency(row):
            skipped.append(row)
        else:
            kept.append(row)
    return kept, skipped


def load() -> dict:
    path = os.environ.get("OLD6_PATH", "").strip()
    if not path:
        raise SystemExit("OLD6_PATH is required")
    text = open(path, encoding="utf-8").read().strip()
    data = json.loads(base64.b64decode(text).decode("utf-8") if path.endswith(".b64") else text)
    if not isinstance(data, dict):
        raise SystemExit("audience must be an object")
    return data


def pairs(template_name: str) -> list[tuple]:
    found = []
    for phone in PHONES:
        number = WabaNumber.objects.filter(phone_number=phone, is_active=True).first()
        template = None
        if number:
            template = WaTemplate.objects.filter(
                waba_business_id=number.waba_business_id,
                name=template_name,
                language="en",
                status=WaTemplate.Status.APPROVED,
            ).first()
        if number and template:
            found.append((number, template))
        else:
            print(f"SKIP {template_name} on {phone}")
    return found


def jobs_for(rows: list, template_name: str) -> list:
    targets = pairs(template_name)
    if not targets:
        raise SystemExit(f"no approved number for {template_name}")
    buckets = [[] for _ in targets]
    for index, row in enumerate(rows):
        buckets[index % len(targets)].append(row)
    jobs = []
    print(f"  split_per_number ({template_name}):")
    for (number, template), bucket in zip(targets, buckets):
        print(f"    +{number.phone_number} n={len(bucket)}")
        for start in range(0, len(bucket), CHUNK):
            piece = bucket[start : start + CHUNK]
            if piece:
                jobs.append((number, template, piece))
    return jobs


def wait_for_capacity() -> None:
    while True:
        inflight = Campaign.objects.filter(
            status__in=[Campaign.Status.QUEUED, Campaign.Status.RUNNING],
        ).count()
        if inflight < MAX_IN_FLIGHT:
            return
        print(f"wait inflight={inflight} max={MAX_IN_FLIGHT}")
        time.sleep(5)


Agent = get_user_model()
agent = Agent.objects.filter(bitrix_user_id=AGENT_BITRIX, is_active=True).first()
if agent is None:
    raise SystemExit(f"no agent for Bitrix {AGENT_BITRIX}")

audience = load()
print(
    f"mode={'SEND' if SEND else 'DRY'} agent={agent.username} "
    f"mixed={ic_templates.kind(ic_templates.ENQUIRY_NAME)} max_in_flight={MAX_IN_FLIGHT}"
)

# Dedupe across both groups first so the same phone cannot land in IC and other.
combined: list[dict] = []
raw_counts: dict[str, int] = {}
for key, _template_name, _playbook in GROUPS:
    rows = audience.get(key) or []
    if not isinstance(rows, list):
        raise SystemExit(f"{key} is not a list")
    raw_counts[key] = len(rows)
    for row in rows:
        normalized = normalize_row(row)
        if normalized is not None:
            normalized["_group"] = key
            combined.append(normalized)

print(f"audience ic={raw_counts.get('ic', 0)} other={raw_counts.get('other', 0)} combined={len(combined)}")

deduped, dedupe_stats = dedupe_audience(combined)
after_agency, agency_skipped = filter_agency(deduped)
print(
    f"duplicates_removed dup_lead_id={dedupe_stats['dup_lead_id']} "
    f"dup_phone={dedupe_stats['dup_phone']} no_phone={dedupe_stats['no_phone']} "
    f"no_id={dedupe_stats['no_id']} agency={len(agency_skipped)} fresh={len(after_agency)}"
)

if agency_skipped:
    print(f"agency_examples (up to 20 of {len(agency_skipped)}):")
    for row in agency_skipped[:20]:
        label = (row.get("name") or row.get("company") or row.get("title") or "")[:80]
        print(
            f"  group={row.get('_group')} lead={row.get('id')} "
            f"phone={mask_phone(row.get('phone'))} {label!r}"
        )

by_group: dict[str, list] = {"ic": [], "other": []}
for row in after_agency:
    by_group.setdefault(row.get("_group") or "other", []).append(row)

all_jobs = []
for key, template_name, playbook in GROUPS:
    rows = by_group.get(key) or []
    jobs = jobs_for(rows, template_name)
    print(f"{key} leads={len(rows)} template={template_name} playbook={playbook} jobs={len(jobs)} sizes={[len(j[2]) for j in jobs]}")
    all_jobs.append((playbook, jobs))

if not SEND:
    print("dry run: nothing queued")
    raise SystemExit(0)

results = []
skip_reasons: Counter = Counter()
for playbook, jobs in all_jobs:
    for number, template, batch in jobs:
        wait_for_capacity()
        try:
            out = send_from_leads(
                agent=agent,
                template_id=template.pk,
                leads=batch,
                extra_body=dict(EXTRA),
                number_id=number.pk,
                lead_ai=True,
                lead_ai_playbook=playbook,
                community="International City" if playbook == "ic_shops" else "",
            )
        except CrmLeadSendError as exc:
            print(f"FAIL {template.name} +{number.phone_number} n={len(batch)}: {exc}")
            continue
        for row in out.get("skipped") or []:
            skip_reasons[str((row or {}).get("reason") or "other")] += 1
        print(
            f"OK campaign={out.get('campaign_id')} {template.name} playbook={playbook} "
            f"+{number.phone_number} queued={out.get('queued')} skipped={out.get('skipped_count')}"
        )
        results.append(out)

print(f"campaigns={len(results)} total_queued={sum(int(r.get('queued') or 0) for r in results)}")
if skip_reasons:
    print("skipped:", dict(skip_reasons))
print("SEND_DONE")
