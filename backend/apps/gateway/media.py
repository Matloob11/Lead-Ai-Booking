"""Fetches inbound media so conversations stay readable after Meta expires it.

Meta's flow is two-step: resolve the media id to a short-lived signed URL, then
download that URL with the same bearer token. alots proxies the first step at
``GET /{version}/{mediaId}``. That path returned 500 for a *template* id during
testing, so its behaviour for media ids is unproven — failures are recorded on
the asset and retried rather than treated as fatal, and the message still shows
in the thread without its attachment.
"""

import hashlib
import logging

import httpx
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile

from apps.inbox.models import MediaAsset

logger = logging.getLogger(__name__)

MAX_BYTES = 64 * 1024 * 1024


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_media(self, asset_id, phone_number_id):
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if not asset or asset.downloaded or not asset.alots_media_id:
        return

    headers = {
        "Authorization": f"Bearer {settings.ALOTS_API_KEY}",
        "Version": settings.ALOTS_VERSION,
    }
    base = settings.ALOTS_BASE_URL.rstrip("/")

    try:
        with httpx.Client(timeout=settings.ALOTS_TIMEOUT, follow_redirects=True) as client:
            meta = client.get(
                f"{base}/{settings.ALOTS_VERSION}/{asset.alots_media_id}",
                headers=headers,
                params={"phone_number_id": phone_number_id},
            )
            meta.raise_for_status()
            info = meta.json()

            url = info.get("url")
            if not url:
                logger.warning("No media URL for asset %s: %s", asset_id, info)
                return

            asset.mime_type = asset.mime_type or info.get("mime_type", "")
            asset.size_bytes = int(info.get("file_size") or 0)
            if asset.size_bytes > MAX_BYTES:
                logger.warning("Media %s is %d bytes, skipping download", asset_id, asset.size_bytes)
                return

            blob = client.get(url, headers=headers)
            blob.raise_for_status()
            content = blob.content
    except httpx.HTTPError as exc:
        logger.warning("Media download failed for asset %s: %s", asset_id, exc)
        raise self.retry(exc=exc)

    asset.sha256 = hashlib.sha256(content).hexdigest()
    asset.size_bytes = len(content)
    extension = (asset.mime_type.split("/")[-1] or "bin").split(";")[0]
    name = asset.file_name or f"{asset.alots_media_id}.{extension}"
    asset.file.save(name, ContentFile(content), save=False)
    asset.file_name = name
    asset.downloaded = True
    asset.save()
