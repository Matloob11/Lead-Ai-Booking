"""Retry template sync for WABAs that returned HTTP 500."""

from apps.catalog.models import WabaNumber, WaTemplate
from apps.catalog.tasks import sync_templates_detail
from django.db.models import Count

RETRY = (
    "1020414087303484",  # Tranquil Crest
    "1423593616270383",  # Horizon Crest
    "1480015549993522",  # 971507563104
)

for waba in RETRY:
    phones = list(
        WabaNumber.objects.filter(waba_business_id=waba, is_active=True).values_list(
            "phone_number", flat=True
        )
    )
    before = WaTemplate.objects.filter(waba_business_id=waba).count()
    total, failures = sync_templates_detail(waba)
    after = WaTemplate.objects.filter(waba_business_id=waba).count()
    print(
        f"waba={waba} phones={phones} synced={total} before={before} after={after} "
        f"fail={failures}",
        flush=True,
    )

# Coverage summary: active numbers with zero templates
empty = []
for number in WabaNumber.objects.filter(is_active=True).exclude(waba_business_id=""):
    n = WaTemplate.objects.filter(waba_business_id=number.waba_business_id).count()
    if n == 0:
        empty.append(f"{number.phone_number}:{number.waba_business_id}")

print(f"active_numbers_with_zero_templates={len(empty)}", flush=True)
for row in empty[:30]:
    print(f"EMPTY {row}", flush=True)

totals = {
    row["status"]: row["n"]
    for row in WaTemplate.objects.values("status").annotate(n=Count("id"))
}
print(f"all_templates={WaTemplate.objects.count()} by_status={totals}", flush=True)
print(
    f"distinct_wabas_with_templates={WaTemplate.objects.values('waba_business_id').distinct().count()}",
    flush=True,
)
