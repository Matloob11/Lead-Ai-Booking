"""Queue Old Leads Before 6 Month on Lead AI.

International City → intl_city_property_reconnect, playbook ic_shops.
Everyone else → property_enquiry_reconnect, playbook general.

Audience JSON at OLD6_PATH ({"ic": [...], "other": [...]} or a .b64 file of that).
OLD6_SEND=1 queues. Otherwise dry-run counts only.

Refuses to send unless property_enquiry_reconnect is a mixed template in this image.
"""

from __future__ import annotations

import base64
import json
import os
from collections import Counter

from django.contrib.auth import get_user_model

from apps.campaigns.crm_leads import CrmLeadSendError, send_from_leads
from apps.catalog.models import WabaNumber, WaTemplate
from apps.leadai import ic_templates

if ic_templates.kind(ic_templates.ENQUIRY_NAME) != ic_templates.MIXED:
    raise SystemExit("property_enquiry_reconnect is not mixed in this image; refusing to send")

SEND = os.environ.get("OLD6_SEND", "").strip() == "1"
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
AGENT_BITRIX = "2311"
EXTRA = {"2": "Malik"}
GROUPS = (
    ("ic", "intl_city_property_reconnect", "ic_shops"),
    ("other", "property_enquiry_reconnect", "general"),
)


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
    for (number, template), bucket in zip(targets, buckets):
        for start in range(0, len(bucket), CHUNK):
            piece = bucket[start : start + CHUNK]
            if piece:
                jobs.append((number, template, piece))
    return jobs


Agent = get_user_model()
agent = Agent.objects.filter(bitrix_user_id=AGENT_BITRIX, is_active=True).first()
if agent is None:
    raise SystemExit(f"no agent for Bitrix {AGENT_BITRIX}")

audience = load()
print(f"mode={'SEND' if SEND else 'DRY'} agent={agent.username} mixed={ic_templates.kind(ic_templates.ENQUIRY_NAME)}")

all_jobs = []
for key, template_name, playbook in GROUPS:
    rows = audience.get(key) or []
    if not isinstance(rows, list):
        raise SystemExit(f"{key} is not a list")
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
