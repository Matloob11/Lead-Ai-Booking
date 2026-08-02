"""Fetches inbound media so conversations stay readable after Meta expires it.

The gateway's documented route — resolve a media id at ``GET /{version}/{id}``,
then download the signed URL it returns — does not work on this account: every
media id answers 400 ("does not exist, cannot be loaded due to missing
permissions"), and the same endpoint answers 500 for template ids. It is broken
on their side.

What does work is the link the webhook already carries. Each inbound media
object arrives with a ``filelink`` pointing at the gateway's own hosted copy,
which needs no credentials, alongside Meta's ``url``, which is authenticated and
expires within minutes. So the URL is captured when the message is stored and
used directly here, with the id-resolution route kept only as a fallback in case
they fix it or stop sending the link.
"""

import hashlib
import logging
import mimetypes

import httpx
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile

from apps.inbox.models import MediaAsset

logger = logging.getLogger(__name__)

MAX_BYTES = 64 * 1024 * 1024


def _auth_headers():
    return {
        "Authorization": f"Bearer {settings.ALOTS_API_KEY}",
        "Version": settings.ALOTS_VERSION,
    }


def _resolve_via_api(client, media_id, phone_number_id):
    """Fallback: ask the gateway to turn a media id into a signed URL."""
    response = client.get(
        f"{settings.ALOTS_BASE_URL.rstrip('/')}/{settings.ALOTS_VERSION}/{media_id}",
        headers=_auth_headers(),
        params={"phone_number_id": phone_number_id},
    )
    response.raise_for_status()
    return response.json().get("url")


def _fetch(client, url):
    """Download a media URL, trying it unauthenticated first.

    The gateway's hosted copy rejects nothing, but Meta's lookaside link needs
    the bearer token — and sending the token to the gateway's own CDN would leak
    it to a host that does not need it.
    """
    response = client.get(url)
    if response.status_code in (401, 403):
        response = client.get(url, headers=_auth_headers())
    response.raise_for_status()
    return response.content


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_media(self, asset_id, phone_number_id):
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if not asset or asset.downloaded:
        return

    try:
        with httpx.Client(timeout=settings.ALOTS_TIMEOUT, follow_redirects=True) as client:
            url = asset.source_url
            if not url and asset.alots_media_id:
                url = _resolve_via_api(client, asset.alots_media_id, phone_number_id)
            if not url:
                asset.download_error = "No media URL in the webhook payload"
                asset.save(update_fields=["download_error"])
                return

            content = _fetch(client, url)
    except httpx.HTTPError as exc:
        message = str(exc)[:1000]
        logger.warning("Media download failed for asset %s: %s", asset_id, message)
        asset.download_error = message
        asset.save(update_fields=["download_error"])
        if self.request.retries >= self.max_retries:
            # Stop here rather than raising: the thread should show "attachment
            # unavailable", not spin forever on a link that will never resolve.
            return
        raise self.retry(exc=exc)

    if len(content) > MAX_BYTES:
        asset.download_error = f"Attachment is {len(content)} bytes, too large to store"
        asset.save(update_fields=["download_error"])
        return

    extension = mimetypes.guess_extension(asset.mime_type.split(";")[0]) or ".bin"
    name = asset.file_name or f"{asset.alots_media_id or asset.pk}{extension}"

    asset.sha256 = asset.sha256 or hashlib.sha256(content).hexdigest()
    asset.size_bytes = len(content)
    asset.file.save(name, ContentFile(content), save=False)
    asset.file_name = name
    asset.downloaded = True
    asset.download_error = ""
    asset.save()

    logger.info("Downloaded asset %s (%d bytes)", asset_id, len(content))

    # The thread is already showing a placeholder for this attachment; tell the
    # panel it can swap in the real thing.
    from apps.inbox.events import publish_status

    for message in asset.messages.select_related("conversation").all():
        publish_status(message)
