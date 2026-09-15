"""Probe alternate gsauth paths and fresh audio assets."""

import httpx
from django.conf import settings

from apps.inbox.models import MediaAsset

auth = {
    "Authorization": f"Bearer {settings.ALOTS_API_KEY}",
    "Version": settings.ALOTS_VERSION,
}

asset = MediaAsset.objects.filter(mime_type__startswith="audio", downloaded=False).order_by("-id").first()
print("asset", asset.pk, asset.source_url, flush=True)
mid = asset.alots_media_id
# path parts from known URL
alts = [
    asset.source_url,
    asset.source_url.replace(".bin", ".ogg"),
    asset.source_url.replace("/Audio/", "/Voice/"),
    asset.source_url.replace("/Audio/Received/", "/Audio/"),
    f"https://gsauth.com/WhatsAppMedia/LiveAgent/Dubai04WBX/Audio/Received/{mid}.ogg",
    f"https://alots.io/WhatsAppMedia/LiveAgent/Dubai04WBX/Audio/Received/{mid}.bin",
    f"https://www.gsauth.com/WhatsAppMedia/LiveAgent/Dubai04WBX/Audio/Received/{mid}.bin",
]

with httpx.Client(timeout=20, follow_redirects=True) as client:
    for url in alts:
        try:
            r = client.get(url, headers=auth)
            print(f"{r.status_code} {len(r.content)} {url[:110]}", flush=True)
        except Exception as exc:
            print(f"ERR {exc} {url[:80]}", flush=True)

    # Fresh lookaside from a recent asset
    if asset.fallback_url:
        r = client.get(asset.fallback_url, headers=auth)
        print(f"lookaside {r.status_code} {r.text[:120]}", flush=True)
