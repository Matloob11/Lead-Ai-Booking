"""Two live POSTs to utility-suggestions. Print cards, not secrets."""

from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.catalog.views import suggest_utility_templates

CANNED = {
    "viewing_confirmed",
    "viewing_reminder",
    "documents_needed",
    "callback_scheduled",
    "payment_received",
}

User = get_user_model()
agent = User.objects.filter(is_active=True).order_by("id").first()
print(f"agent_id={getattr(agent, 'id', None)}", flush=True)

factory = APIRequestFactory()


def post(label, body, name):
    request = factory.post(
        "/api/catalog/templates/utility-suggestions/",
        {
            "body_text": body,
            "name": name,
            "header_text": "",
            "footer_text": "",
            "language": "en",
            "category": "UTILITY",
        },
        format="json",
        HTTP_HOST="127.0.0.1",
    )
    force_authenticate(request, user=agent)
    res = suggest_utility_templates(request)
    data = res.data
    rows = data.get("suggestions") or []
    names = [row.get("name") for row in rows]
    bodies = [row.get("body") for row in rows]
    print(f"--- {label} status={res.status_code}", flush=True)
    print(
        f"ai_configured={data.get('ai_configured')} source={data.get('source')} "
        f"ai_error={data.get('ai_error')!r}",
        flush=True,
    )
    print(
        f"marketing={data.get('original_would_be_marketing')} count={len(names)} names={names}",
        flush=True,
    )
    print(f"analysis={data.get('analysis')}", flush=True)
    for index, row in enumerate(rows, 1):
        print(
            f"  body{index}={row.get('body')} examples={row.get('body_examples')}",
            flush=True,
        )
    canned_hit = [item for item in names if item in CANNED]
    print(f"canned_names={canned_hit or 'none'}", flush=True)
    return names, " ".join(str(item or "") for item in bodies).lower()


view_names, view_joined = post(
    "viewing",
    "Hello Ahmed, your viewing at The Oasis is confirmed for Tuesday 11:00.",
    "oasis_viewing",
)
print(
    f"viewing_stays={('oasis' in view_joined or 'viewing' in view_joined)} "
    f"invented_docs={'document' in view_joined} invented_pay={'payment' in view_joined} "
    f"count_ok={1 <= len(view_names) <= 3}",
    flush=True,
)

promo_names, promo_joined = post(
    "marketing",
    "NEW PHASE OF VILLAS starting from AED 14M. Book now at Dubai Hills!",
    "hills_launch",
)
print(
    f"promo_keeps_hills={'hills' in promo_joined} "
    f"promo_canned={any(name in CANNED for name in promo_names)} "
    f"count_ok={1 <= len(promo_names) <= 3}",
    flush=True,
)
