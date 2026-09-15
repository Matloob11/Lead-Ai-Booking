"""Count WhatsApp Leads stage: total / blank / with details. No secrets printed."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

base = (
    os.environ.get("BITRIX_WEBHOOK_BASE")
    or os.environ.get("AGENT_REPORT_BITRIX_WEBHOOK")
    or ""
).rstrip("/")
if not base:
    raise SystemExit("BITRIX_WEBHOOK_BASE missing")


def post(method: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def nonempty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(nonempty(item) for item in value)
    if isinstance(value, dict):
        return any(nonempty(item) for item in value.values() if item not in ("ID", "VALUE_TYPE", "TYPE_ID"))
    text = str(value).strip()
    return bool(text) and text not in ("0", "false", "None", "[]", "{}")


statuses = post("crm.status.list", {"filter": {"ENTITY_ID": "STATUS"}}).get("result") or []
print("=== lead stages ===")
wa_status_ids = []
for row in statuses:
    name = str(row.get("NAME") or "")
    sid = str(row.get("STATUS_ID") or "")
    print(f"{sid}\t{name}")
    if "whatsapp" in name.lower() or "wa_lead" in sid.lower() or sid.upper() == "UC_WA_LEADS":
        wa_status_ids.append(sid)

if not wa_status_ids:
    raise SystemExit("WhatsApp Leads stage not found")

print("using_status_ids", wa_status_ids)

fields_meta = post("crm.lead.fields").get("result") or {}
detail_keys = []
for name, meta in fields_meta.items():
    label = str((meta or {}).get("formLabel") or (meta or {}).get("title") or name).lower()
    if any(
        token in label or token in name.lower()
        for token in (
            "comment",
            "bedroom",
            "client",
            "community",
            "source",
            "opportunity",
            "budget",
            "area",
            "location",
            "property",
            "type",
            "notes",
        )
    ):
        if name in ("STATUS_ID", "SOURCE_ID", "SOURCE_DESCRIPTION", "STATUS_SEMANTIC_ID"):
            continue
        detail_keys.append(name)

# Always treat these as details if filled.
for extra in ("COMMENTS", "OPPORTUNITY", "ADDRESS", "ADDRESS_CITY", "POST"):
    if extra not in detail_keys:
        detail_keys.append(extra)

print("detail_field_candidates", sorted(set(detail_keys))[:40])

select = list(
    dict.fromkeys(
        [
            "ID",
            "TITLE",
            "NAME",
            "LAST_NAME",
            "STATUS_ID",
            "SOURCE_ID",
            "SOURCE_DESCRIPTION",
            "COMMENTS",
            "PHONE",
            "EMAIL",
            "HAS_PHONE",
            "HAS_EMAIL",
            *detail_keys,
        ]
    )
)

leads = []
start = 0
while True:
    page = post(
        "crm.lead.list",
        {
            "filter": {"STATUS_ID": wa_status_ids if len(wa_status_ids) > 1 else wa_status_ids[0]},
            "select": select,
            "start": start,
            "order": {"ID": "DESC"},
        },
    )
    batch = page.get("result") or []
    if isinstance(batch, dict):
        batch = list(batch.values())
    leads.extend(batch)
    nxt = page.get("next")
    print(f"fetched {len(leads)} next={nxt}")
    if nxt is None:
        break
    start = int(nxt)

blank = 0
with_details = 0
samples_blank = []
samples_details = []

for lead in leads:
    title = str(lead.get("TITLE") or "").strip()
    name = " ".join(part for part in (lead.get("NAME"), lead.get("LAST_NAME")) if part).strip()
    comments = str(lead.get("COMMENTS") or "").strip()
    filled = []
    for key in detail_keys:
        if key in ("TITLE", "NAME", "LAST_NAME", "PHONE", "HAS_PHONE", "HAS_EMAIL", "SOURCE_ID"):
            continue
        if nonempty(lead.get(key)):
            filled.append(key)
    # A title that is only "Personal | 971..." or a bare phone is not details.
    title_is_phoneish = bool(
        title
        and (
            any(ch.isdigit() for ch in title)
            and len([ch for ch in title if ch.isdigit()]) >= 8
            and not comments
        )
    )
    has_details = bool(comments) or bool(filled)
    if has_details:
        with_details += 1
        if len(samples_details) < 5:
            samples_details.append({"id": lead.get("ID"), "title": title[:80], "fields": filled[:8], "comments": bool(comments)})
    else:
        blank += 1
        if len(samples_blank) < 5:
            samples_blank.append({"id": lead.get("ID"), "title": title[:80], "name": name[:40], "phoneish": title_is_phoneish})

print("=== WhatsApp Leads stage ===")
print(f"total={len(leads)}")
print(f"blank={blank}")
print(f"with_details={with_details}")
print("sample_blank", json.dumps(samples_blank, ensure_ascii=False))
print("sample_details", json.dumps(samples_details, ensure_ascii=False))
