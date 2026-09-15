"""Print full Meta errors for villa_nova2 on WABAs that still fail."""

from apps.catalog.models import WaTemplate
from apps.gateway.client import AlotsClient, AlotsError

source = WaTemplate.objects.get(pk=678)
payload = {
    "name": source.name,
    "category": source.category or "MARKETING",
    "language": source.language or "en",
    "components": source.components,
}

for waba in ("1011973244419870", "1480015549993522", "2681306488869104"):
    try:
        res = AlotsClient().create_template(waba, payload)
        print(f"OK {waba} {res}", flush=True)
    except AlotsError as exc:
        print(f"FAIL {waba} status={exc.status_code} msg={exc}", flush=True)
        print(f"  payload={getattr(exc, 'payload', None)}", flush=True)
