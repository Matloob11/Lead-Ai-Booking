"""One-off: submit villa_nova2 (pk 678) to every Official WABA missing it.

Skips WABAs that already have villa_nova2 or any sibling name
(villanova_, villa_nova1, villa_nova3). Output is counts only.
"""

from apps.catalog.models import WaTemplate
from apps.catalog.views import (
    _admin_waba_targets,
    _bulk_template_results,
    _summarize_bulk,
    _template_on_waba,
)

SOURCE_PK = 678
SKIP_NAMES = ("villa_nova1", "villa_nova2", "villa_nova3", "villanova_")


def main():
    source = WaTemplate.objects.get(pk=SOURCE_PK)
    if not source.components:
        raise RuntimeError("source template has no stored components")

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

    targets = _admin_waba_targets(all_numbers=True)
    filtered = {}
    skipped = 0
    for waba, phones in targets.items():
        if _template_on_waba(waba, source.name, source.language):
            skipped += 1
            continue
        if WaTemplate.objects.filter(
            waba_business_id=waba,
            name__in=SKIP_NAMES,
            language=source.language,
        ).exists():
            skipped += 1
            continue
        filtered[waba] = phones

    print(f"villa_nova2 deploy: targets={len(filtered)} skipped_wabas={skipped}", flush=True)

    rows = _bulk_template_results(parsed, filtered)
    summary = _summarize_bulk(rows)
    print(
        f"created={summary['created']} skipped={summary['skipped']} failed={summary['failed']}",
        flush=True,
    )
    for row in rows:
        if row["status"] != "failed":
            continue
        detail = str(row.get("detail", ""))[:240]
        print(f"FAIL waba={row['waba_business_id']} {detail}", flush=True)


main()
