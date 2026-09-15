"""Explain why panel TOTAL can be lower than catalog_watemplate count."""

from django.contrib.auth import get_user_model
from django.db.models import Count

from apps.catalog.models import WabaNumber, WaTemplate

Agent = get_user_model()
total = WaTemplate.objects.count()
active_wabas = set(
    WabaNumber.objects.filter(is_active=True)
    .exclude(waba_business_id="")
    .values_list("waba_business_id", flat=True)
)
on_active = WaTemplate.objects.filter(waba_business_id__in=active_wabas).count()
orphan = total - on_active

print(f"db_total={total} on_active_wabas={on_active} orphan_inactive_waba={orphan}", flush=True)

# Admins / who sees "all"
admins = list(Agent.objects.filter(is_wa_admin=True).values_list("id", "display_name", "username")[:20])
print(f"wa_admins={admins}", flush=True)

for agent in Agent.objects.filter(is_wa_admin=True)[:5]:
    visible = list(
        agent.visible_numbers.exclude(waba_business_id="").values_list("waba_business_id", flat=True)
    )
    wabas = set(visible)
    shown = WaTemplate.objects.filter(waba_business_id__in=wabas).count()
    by = {
        r["status"]: r["n"]
        for r in WaTemplate.objects.filter(waba_business_id__in=wabas)
        .values("status")
        .annotate(n=Count("id"))
    }
    print(
        f"admin id={agent.pk} name={agent.display_name or agent.username} "
        f"visible_numbers={agent.visible_numbers.count()} distinct_wabas={len(wabas)} "
        f"templates_shown={shown} by_status={by}",
        flush=True,
    )

# Templates on inactive / missing numbers
orphan_wabas = (
    WaTemplate.objects.exclude(waba_business_id__in=active_wabas)
    .values("waba_business_id")
    .annotate(n=Count("id"))
    .order_by("-n")[:15]
)
print("top_orphan_wabas=", list(orphan_wabas), flush=True)
