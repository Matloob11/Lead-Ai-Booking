"""Pull every Official WABA's templates from Alots into Bitrix catalog."""

from apps.catalog.models import WabaNumber, WaTemplate
from apps.catalog.tasks import sync_templates_detail

active_wabas = (
    WabaNumber.objects.filter(is_active=True)
    .exclude(waba_business_id="")
    .values_list("waba_business_id", flat=True)
    .distinct()
    .count()
)
before = WaTemplate.objects.count()
print(f"before templates={before} active_wabas={active_wabas}", flush=True)

total, failures = sync_templates_detail()
after = WaTemplate.objects.count()
by_status = list(
    WaTemplate.objects.values_list("status").order_by("status").distinct()
)
from django.db.models import Count

status_counts = {
    row["status"]: row["n"]
    for row in WaTemplate.objects.values("status").annotate(n=Count("id"))
}

print(
    f"synced_rows={total} after_templates={after} delta={after - before} "
    f"wabas_failed={len(failures)}",
    flush=True,
)
print(f"status_counts={status_counts}", flush=True)
for row in failures[:20]:
    print(f"FAIL waba={row['waba_business_id']} {row['detail'][:200]}", flush=True)
if len(failures) > 20:
    print(f"...and {len(failures) - 20} more failures", flush=True)
