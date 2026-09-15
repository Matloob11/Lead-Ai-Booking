# Label the four newly synced Blue Brick Official numbers (already in catalog).
from django.utils import timezone
from apps.catalog.models import WabaNumber

ROWS = [
    ("971556829046", "1285696127962374", "1057813046858481"),
    ("971557466914", "1388181304374711", "3581973095301440"),
    ("971556748730", "1298497780011285", "2116723579060974"),
    ("971557327268", "1264896570048040", "1727614985177215"),
]

for phone, pnid, waba in ROWS:
    row = WabaNumber.objects.filter(phone_number_id=pnid).first()
    if row is None:
        row = WabaNumber.objects.filter(phone_number=phone).first()
    if row is None:
        print("MISSING", phone, pnid)
        continue
    fields = []
    if row.phone_number != phone:
        row.phone_number = phone
        fields.append("phone_number")
    if row.waba_business_id != waba:
        row.waba_business_id = waba
        fields.append("waba_business_id")
    if not (row.display_name or "").strip():
        row.display_name = "Blue Brick"
        fields.append("display_name")
    if not (row.label or "").strip():
        row.label = "Blue Brick"
        fields.append("label")
    if not row.is_active:
        row.is_active = True
        fields.append("is_active")
    if fields:
        row.save(update_fields=fields)
        print("updated", phone, ",".join(fields))
    else:
        print("ok", phone, row.label or row.display_name or "(no label)")

print(
    "blue_brick_active",
    WabaNumber.objects.filter(
        phone_number__in=[p for p, _, _ in ROWS], is_active=True
    ).count(),
)
print("note webhook still NA on Alots — paste panel URL there")
