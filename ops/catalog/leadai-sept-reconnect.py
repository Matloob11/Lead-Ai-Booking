"""Queue Lead AI ``intl_city_property_reconnect`` for September 2026 CRM leads
not yet in any Lead AI campaign.

Audience JSON arrives in ``SEPT_LEADS_B64`` (base64 of a JSON list of
``{id, phone, name, title, company, bot_status, wa_opt_out}``) so Bitrix REST is not
needed (429). Default dry-run; ``SEPT_SEND=1`` queues.

Dedupes by lead id and canonical phone before round-robin. Queues at most
``SEPT_MAX_IN_FLIGHT`` (default 2) campaigns at a time. Skips agency-looking
names (Properties, Real Estate, …) before send.

Agent Bitrix 2311; eight numbers 719–726; {{2}}=Malik; playbook ic_shops.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections import Counter

from django.contrib.auth import get_user_model

from apps.campaigns.crm_leads import CrmLeadSendError, send_from_leads
from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import WabaNumber, WaTemplate

SEND = os.environ.get("SEPT_SEND", "").strip() == "1"
CHUNK = 250
MAX_IN_FLIGHT = max(1, int(os.environ.get("SEPT_MAX_IN_FLIGHT", "2") or "2"))
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
TEMPLATE_NAME = "intl_city_property_reconnect"
AGENT_BITRIX = "2311"
EXTRA = {"2": "Malik"}

# Agency / broker title words (Task 3). Matched case-insensitively on name, company, title.
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


def _clean_title(title: str) -> str:
    """Drop our channel / portal prefixes so 'A7 Group Real Estate' in the title is not an agency hit."""
    text = str(title or "")
    text = re.sub(r"(?i)WAZZUP:.*$", "", text)
    text = re.sub(r"(?i)A7\s*Group\s*Real\s*Estate", "", text)
    text = re.sub(r"(?i)Property Finder WhatsApp\s*\|?\s*", "", text)
    text = re.sub(r"(?i)Bayut WhatsApp\s*\|?\s*", "", text)
    return text.strip(" |")


def looks_agency(row: dict) -> bool:
    blob = " ".join(
        [
            str(row.get("name") or ""),
            str(row.get("company") or ""),
            _clean_title(row.get("title") or ""),
        ]
    )
    return bool(blob.strip() and _AGENCY_RE.search(blob))


def mask_phone(phone: str) -> str:
    digits = canonical_phone(phone)
    if len(digits) <= 4:
        return "****"
    return digits[:3] + ("*" * max(0, len(digits) - 6)) + digits[-3:]


def already_lead_ai_ids() -> set[int]:
    return set(
        CampaignRecipient.objects.filter(
            campaign__lead_ai__isnull=False,
            crm_lead_id__isnull=False,
            crm_lead_id__gte=73091,
            crm_lead_id__lte=78612,
        )
        .values_list("crm_lead_id", flat=True)
        .distinct()
    )


def load_leads() -> list[dict]:
    path = os.environ.get("SEPT_LEADS_PATH", "").strip()
    raw_b64 = os.environ.get("SEPT_LEADS_B64", "").strip()
    if path:
        text = open(path, "r", encoding="utf-8").read().strip()
        if path.endswith(".b64"):
            rows = json.loads(base64.b64decode(text).decode("utf-8"))
        else:
            rows = json.loads(text)
    elif raw_b64:
        rows = json.loads(base64.b64decode(raw_b64).decode("utf-8"))
    else:
        raise SystemExit("SEPT_LEADS_PATH or SEPT_LEADS_B64 is required")
    if not isinstance(rows, list):
        raise SystemExit("leads payload must be a JSON list")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            lead_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        phone = canonical_phone(row.get("phone") or "")
        out.append(
            {
                "id": lead_id,
                "phone": phone,
                "name": str(row.get("name") or "").strip(),
                "company": str(row.get("company") or "").strip(),
                "title": str(row.get("title") or ""),
                "bot_status": row.get("bot_status") or "",
                "wa_opt_out": row.get("wa_opt_out") or "",
            }
        )
    return out


def dedupe_audience(rows: list[dict]) -> tuple[list[dict], dict]:
    """Keep first sighting of each lead id and each canonical phone. Before round-robin."""
    seen_ids: set[int] = set()
    seen_phones: set[str] = set()
    kept: list[dict] = []
    stats = {
        "dup_lead_id": 0,
        "dup_phone": 0,
        "no_phone": 0,
        "no_id": 0,
    }
    for row in rows:
        lead_id = int(row.get("id") or 0)
        phone = canonical_phone(row.get("phone") or "")
        if lead_id <= 0:
            stats["no_id"] += 1
            continue
        if lead_id in seen_ids:
            stats["dup_lead_id"] += 1
            continue
        if len(phone) < 8:
            stats["no_phone"] += 1
            continue
        if phone in seen_phones:
            stats["dup_phone"] += 1
            continue
        seen_ids.add(lead_id)
        seen_phones.add(phone)
        kept.append({**row, "phone": phone})
    return kept, stats


def filter_agency(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, skipped = [], []
    for row in rows:
        if looks_agency(row):
            skipped.append(row)
        else:
            kept.append(row)
    return kept, skipped


def number_templates() -> list[tuple[WabaNumber, WaTemplate]]:
    pairs = []
    for phone in PHONES:
        number = WabaNumber.objects.filter(phone_number=phone, is_active=True).first()
        if not number:
            print(f"SKIP number missing {phone}")
            continue
        template = WaTemplate.objects.filter(
            waba_business_id=number.waba_business_id,
            name=TEMPLATE_NAME,
            language="en",
            status=WaTemplate.Status.APPROVED,
        ).first()
        if not template:
            print(f"SKIP template missing on {phone}")
            continue
        pairs.append((number, template))
    return pairs


def wait_for_capacity() -> None:
    """Do not queue the next campaign while more than MAX_IN_FLIGHT are queued/running."""
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

pairs = number_templates()
if not pairs:
    raise SystemExit("no sending numbers/templates")

leads = load_leads()
done = already_lead_ai_ids()
skip_already = [row for row in leads if row["id"] in done]
not_done = [row for row in leads if row["id"] not in done]

deduped, dedupe_stats = dedupe_audience(not_done)
after_agency, agency_skipped = filter_agency(deduped)

print(f"audience={len(leads)}")
print(
    f"skipped_already_lead_ai={len(skip_already)} "
    f"dup_lead_id={dedupe_stats['dup_lead_id']} dup_phone={dedupe_stats['dup_phone']} "
    f"no_phone={dedupe_stats['no_phone']} no_id={dedupe_stats['no_id']} "
    f"agency={len(agency_skipped)} fresh={len(after_agency)}"
)
print(f"mode={'SEND' if SEND else 'DRY'} agent={agent.username} numbers={len(pairs)} "
      f"chunk={CHUNK} max_in_flight={MAX_IN_FLIGHT}")

buckets: list[list[dict]] = [[] for _ in pairs]
for index, row in enumerate(after_agency):
    buckets[index % len(pairs)].append(row)

print("split_per_number:")
for (number, _template), bucket in zip(pairs, buckets):
    print(f"  +{number.phone_number} n={len(bucket)}")

if agency_skipped:
    print(f"agency_examples (up to 20 of {len(agency_skipped)}):")
    for row in agency_skipped[:20]:
        label = (row.get("name") or row.get("company") or row.get("title") or "")[:80]
        print(f"  lead={row.get('id')} phone={mask_phone(row.get('phone'))} {label!r}")

jobs: list[tuple[WabaNumber, WaTemplate, list[dict]]] = []
for (number, template), bucket in zip(pairs, buckets):
    for start in range(0, len(bucket), CHUNK):
        jobs.append((number, template, bucket[start : start + CHUNK]))

print(f"jobs={len(jobs)} sizes={[len(j[2]) for j in jobs]}")

if not SEND:
    print("dry run: nothing queued (SEPT_SEND=1 to send)")
    raise SystemExit(0)

results = []
skip_reasons: Counter = Counter()
for number, template, batch in jobs:
    if not batch:
        continue
    wait_for_capacity()
    try:
        out = send_from_leads(
            agent=agent,
            template_id=template.pk,
            leads=batch,
            extra_body=dict(EXTRA),
            number_id=number.pk,
            lead_ai=True,
            lead_ai_playbook="ic_shops",
            community="",
        )
    except CrmLeadSendError as exc:
        print(f"FAIL +{number.phone_number} n={len(batch)}: {exc}")
        continue
    for row in out.get("skipped") or []:
        skip_reasons[str((row or {}).get("reason") or "other")] += 1
    print(
        f"OK campaign={out.get('campaign_id')} +{number.phone_number} "
        f"queued={out.get('queued')} skipped={out.get('skipped_count')}"
    )
    results.append(out)

print(f"campaigns={len(results)} total_queued={sum(int(r.get('queued') or 0) for r in results)}")
if skip_reasons:
    print("skipped:", dict(skip_reasons))
print("SEND_DONE")
