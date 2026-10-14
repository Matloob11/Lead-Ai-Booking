# Read-only C22 check: phones_in_active_lead_ai on a live active chat.
# Run: temporarily via probe-crm-entities path, or manage.py shell.
from apps.campaigns.crm_leads import build_recipients, phones_in_active_lead_ai
from apps.catalog.models import WaTemplate


busy_phone = "971589763936"
idle_phone = "971500000001"
found = phones_in_active_lead_ai({busy_phone, idle_phone})
print("busy_found:", sorted(found))
assert busy_phone in found, found
assert idle_phone not in found, found

# build_recipients leave-out line shape (0-var template so body vars are not needed)
tpl = type("T", (), {"variable_count": 0, "name": "c22_probe", "language": "en", "pk": None})()
rows, skipped = build_recipients(
    template=tpl,
    leads=[
        {"id": 1, "phone": busy_phone, "name": "Busy"},
        {"id": 2, "phone": idle_phone, "name": "Idle"},
    ],
    extra_body={},
    lead_ai=True,
)
print("kept:", [r["phone"] for r in rows])
print("skipped:", skipped)
reasons = [s.get("reason") for s in skipped]
assert any("Lead AI" in (r or "") for r in reasons), reasons
print("C22_LIVE_OK")
