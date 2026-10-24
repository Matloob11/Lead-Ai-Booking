"""Refresh the eight sending WABAs from Alots and print property_enquiry_reconnect's status."""

from apps.catalog.models import WabaNumber, WaTemplate
from apps.catalog.tasks import sync_templates_detail

PHONES = (
    "971581058719",
    "971581058720",
    "971581058721",
    "971581058722",
    "971581058723",
    "971581058724",
    "971581058725",
    "971581058726",
)
NAME = "property_enquiry_reconnect"

wabas = list(
    WabaNumber.objects.filter(phone_number__in=PHONES, is_active=True)
    .exclude(waba_business_id="")
    .values_list("waba_business_id", flat=True)
    .distinct()
)
for waba in wabas:
    total, failures = sync_templates_detail(waba)
    fail = failures[0]["detail"][:160] if failures else ""
    print(f"synced waba={waba} rows={total} failed={len(failures)} {fail}")

print("---")
for number in WabaNumber.objects.filter(phone_number__in=PHONES).order_by("phone_number"):
    row = WaTemplate.objects.filter(
        waba_business_id=number.waba_business_id, name=NAME, language="en"
    ).first()
    print(f"{number.phone_number} {row.status if row else 'MISSING'}")
