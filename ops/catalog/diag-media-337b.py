"""Print lookaside 401 body + try Alots media id resolve for asset 337."""

import httpx
from django.conf import settings

from apps.inbox.models import MediaAsset, Message

asset = MediaAsset.objects.get(pk=337)
msg = Message.objects.filter(media_id=337).select_related("conversation__number").first()
pnid = msg.conversation.number.phone_number_id if msg else ""
print("phone_number_id", pnid, flush=True)
print("alots_media_id", asset.alots_media_id, flush=True)

auth = {
    "Authorization": f"Bearer {settings.ALOTS_API_KEY}",
    "Version": settings.ALOTS_VERSION,
}
base = settings.ALOTS_BASE_URL.rstrip("/")
ver = settings.ALOTS_VERSION

with httpx.Client(timeout=30, follow_redirects=False) as client:
    r = client.get(asset.fallback_url, headers=auth)
    print("lookaside body", r.text[:300], flush=True)

    for path in (
        f"/{ver}/{asset.alots_media_id}",
        f"/{ver}/{asset.alots_media_id}?phone_number_id={pnid}",
        f"/{pnid}/media/{asset.alots_media_id}",
        f"/{ver}/media/{asset.alots_media_id}",
    ):
        try:
            resp = client.get(f"{base}{path}", headers=auth)
            print(f"GET {path} -> {resp.status_code} {resp.text[:200]}", flush=True)
        except Exception as exc:
            print(f"GET {path} ERR {exc}", flush=True)
