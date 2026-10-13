"""Set display names on the Oct-8 WBBOX numbers already in catalog (idempotent).

They were synced active/unassigned with empty names. Webhook stays for the
operator to paste in WBBOX. Does not create rows that are not already there.
"""

from apps.catalog.models import WabaNumber

# phone -> (display_name, label). Phones match Alots list_channels + live DB.
NUMBERS = {
    "971581058717": ("Coastline Properties", "Coastline Properties"),
    "971581058718": ("Coastline Properties", "Coastline Properties"),
    "971581058719": ("Coastline Properties", "Coastline Properties"),
    "971581058720": ("Coastline Properties", "Coastline Properties"),
    "971581058723": ("Coastline Properties", "Coastline Properties"),
    "971581058724": ("Coastline Properties", "Coastline Properties"),
    "971581058725": ("Coastline Properties", "Coastline Properties"),
    "971581058726": ("Coastline Properties", "Coastline Properties"),
    "971581058721": ("Blue Brick", "Blue Brick"),
    "971581058722": ("Blue Brick Private Limited", "Blue Brick Private Limited"),
}

updated = 0
missing = 0
for phone, (display_name, label) in NUMBERS.items():
    row = WabaNumber.objects.filter(phone_number=phone).first()
    if row is None:
        missing += 1
        print(f"MISSING {phone}", flush=True)
        continue
    fields = []
    if row.display_name != display_name:
        row.display_name = display_name
        fields.append("display_name")
    if row.label != label:
        row.label = label
        fields.append("label")
    if not row.is_active:
        row.is_active = True
        fields.append("is_active")
    if fields:
        row.save(update_fields=fields + ["updated_at"] if hasattr(row, "updated_at") else fields)
        updated += 1
        print(f"updated {phone} {label} fields={fields} pnid={row.phone_number_id}", flush=True)
    else:
        print(f"ok {phone} {label} pnid={row.phone_number_id} active={row.is_active}", flush=True)

print(f"done updated={updated} missing={missing}", flush=True)
print(
    "webhook_url=https://wa.srv1802669.hstgr.cloud/api/gateway/webhook/alots/",
    flush=True,
)
print(
    "assign: Numbers screen — these ten are active and unassigned.",
    flush=True,
)
