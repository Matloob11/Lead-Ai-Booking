# Read-only, run through `ops/wa.sh probe-gateway-media-template-status`:
# what Meta says today about the throwaway image-header templates that
# `probe-gateway-media-template` created on WABA 1426351832653450 (they are
# hidden from the panel, so the hourly sync never shows them). Nothing is sent.
from apps.gateway.client import AlotsClient

WABA = "1426351832653450"
rows = [t for t in (AlotsClient().list_templates(WABA) or []) if str(t.get("name", "")).startswith("zz_probe_gateway_media_")]
if not rows:
    print("no zz_probe_gateway_media_* template on", WABA)
for t in rows:
    headers = [comp.get("format") for comp in t.get("components", []) if comp.get("type") == "HEADER"]
    print(t.get("name"), "status=", t.get("status"), "category=", t.get("category"), "header=", headers, "reason=", t.get("rejected_reason"))
print("PROBE_OK")
