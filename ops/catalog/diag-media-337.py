"""Probe why asset 337 failed; try gsauth then lookaside with/without auth."""

import httpx
from django.conf import settings

from apps.inbox.models import MediaAsset

asset = MediaAsset.objects.get(pk=337)
print("source", asset.source_url[:120], flush=True)
print("fallback", (asset.fallback_url or "")[:120], flush=True)

auth = {
    "Authorization": f"Bearer {settings.ALOTS_API_KEY}",
    "Version": settings.ALOTS_VERSION,
}

with httpx.Client(timeout=30, follow_redirects=False) as client:
    for label, url, headers in (
        ("gsauth-noauth", asset.source_url, {}),
        ("gsauth-auth", asset.source_url, auth),
        ("lookaside-auth", asset.fallback_url, auth),
        ("lookaside-noauth", asset.fallback_url, {}),
    ):
        if not url:
            continue
        try:
            r = client.get(url, headers=headers)
            print(f"{label} status={r.status_code} len={len(r.content)} ctype={r.headers.get('content-type','')[:60]}", flush=True)
        except Exception as exc:
            print(f"{label} ERR {exc}", flush=True)
