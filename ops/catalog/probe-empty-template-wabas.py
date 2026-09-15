"""Probe template list for numbers that still have zero templates."""

from apps.catalog.models import WabaNumber, WaTemplate
from apps.catalog.tasks import sync_templates_detail
from apps.gateway.client import AlotsClient, AlotsError

EMPTY_PHONES = (
    "447723351148",
    "447723356623",
    "971507563104",
    "971543752608",
    "971559783176",
    "971564821835",
)

client = AlotsClient()
for phone in EMPTY_PHONES:
    number = WabaNumber.objects.filter(phone_number=phone).first()
    if not number:
        print(f"MISSING_ROW {phone}", flush=True)
        continue
    waba = number.waba_business_id
    try:
        rows = client.list_templates(waba) or []
        print(
            f"OK {phone} waba={waba} alots_count={len(rows)} "
            f"local={WaTemplate.objects.filter(waba_business_id=waba).count()}",
            flush=True,
        )
        if rows:
            total, failures = sync_templates_detail(waba)
            print(f"  synced={total} fail={failures}", flush=True)
    except AlotsError as exc:
        print(f"ERR {phone} waba={waba} {exc}", flush=True)
        payload = getattr(exc, "payload", None)
        if payload:
            print(f"  payload={str(payload)[:300]}", flush=True)
