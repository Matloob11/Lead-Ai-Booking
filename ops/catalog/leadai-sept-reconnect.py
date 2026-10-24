"""Queue Lead AI ``intl_city_property_reconnect`` for September 2026 CRM leads
not yet in any Lead AI campaign.

Audience JSON arrives in ``SEPT_LEADS_B64`` (base64 of a JSON list of
``{id, phone, name, title, bot_status, wa_opt_out}``) so Bitrix REST is not
needed (429). Default dry-run; ``SEPT_SEND=1`` queues.

Agent Bitrix 2311; eight numbers 719–726; {{2}}=Malik; playbook ic_shops.
"""

from __future__ import annotations

import base64
import json
import os
from collections import Counter

from django.contrib.auth import get_user_model

from apps.campaigns.crm_leads import CrmLeadSendError, send_from_leads
from apps.campaigns.models import CampaignRecipient
from apps.catalog.models import WabaNumber, WaTemplate

SEND = os.environ.get("SEPT_SEND", "").strip() == "1"
CHUNK = 250
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
        phone = "".join(ch for ch in str(row.get("phone") or "") if ch.isdigit())
        name = str(row.get("name") or "").strip()
        out.append(
            {
                "id": lead_id,
                "phone": phone,
                "name": name,
                "title": str(row.get("title") or ""),
                "bot_status": row.get("bot_status") or "",
                "wa_opt_out": row.get("wa_opt_out") or "",
            }
        )
    return out


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


Agent = get_user_model()
agent = Agent.objects.filter(bitrix_user_id=AGENT_BITRIX, is_active=True).first()
if agent is None:
    raise SystemExit(f"no agent for Bitrix {AGENT_BITRIX}")

pairs = number_templates()
if not pairs:
    raise SystemExit("no sending numbers/templates")

leads = load_leads()
done = already_lead_ai_ids()
fresh = [row for row in leads if row["id"] not in done and len(row.get("phone") or "") >= 8]
no_phone = sum(1 for row in leads if row["id"] not in done and len(row.get("phone") or "") < 8)

print(
    f"sept_leads={len(leads)} already_lead_ai={len(done & {r['id'] for r in leads})} "
    f"fresh_with_phone={len(fresh)} no_phone={no_phone}"
)
print(f"mode={'SEND' if SEND else 'DRY'} agent={agent.username} numbers={len(pairs)} chunk={CHUNK}")

buckets: list[list[dict]] = [[] for _ in pairs]
for index, row in enumerate(fresh):
    buckets[index % len(pairs)].append(row)

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
