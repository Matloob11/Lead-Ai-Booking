"""Retry villa_nova2 submit for WABAs that failed in the bulk deploy."""

from apps.catalog.models import WaTemplate
from apps.catalog.views import _bulk_template_results, _summarize_bulk

SOURCE_PK = 678
RETRY_WABAS = (
    "1011973244419870",
    "1369618845050157",
    "1480015549993522",
    "2681306488869104",
)

source = WaTemplate.objects.get(pk=SOURCE_PK)
parsed = {
    "clean_name": source.name,
    "category": source.category or "MARKETING",
    "language": source.language or "en",
    "components": source.components,
    "payload": {
        "name": source.name,
        "category": source.category or "MARKETING",
        "language": source.language or "en",
        "components": source.components,
    },
}

from apps.catalog.models import WabaNumber

targets = {}
for waba in RETRY_WABAS:
    phones = list(
        WabaNumber.objects.filter(is_active=True, waba_business_id=waba)
        .order_by("phone_number")
        .values_list("phone_number", flat=True)
    )
    targets[waba] = [p for p in phones if p]

print(f"retry targets={len(targets)}", flush=True)
rows = _bulk_template_results(parsed, targets)
summary = _summarize_bulk(rows)
print(
    f"created={summary['created']} skipped={summary['skipped']} failed={summary['failed']}",
    flush=True,
)
for row in rows:
    detail = row.get("detail", "")
    print(f"{row['status']} waba={row['waba_business_id']} {str(detail)[:300]}", flush=True)
