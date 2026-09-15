"""Fetches inbound media so conversations stay readable after Meta expires it.

The gateway's documented route — resolve a media id at ``GET /{version}/{id}``,
then download the signed URL it returns — does not work on this account: every
media id answers 400 ("does not exist, cannot be loaded due to missing
permissions"), and the same endpoint answers 500 for template ids. It is broken
on their side.

What does work is the link the webhook already carries. Each inbound media
object arrives with a ``filelink`` pointing at the gateway's own hosted copy,
which needs no credentials, alongside Meta's ``url``, which is authenticated and
expires within minutes.

That link is third-party input, so it is not fetched blindly. The worker sits on
a host that also runs Frappe, n8n and their databases, and it holds a bearer
token for the gateway — a crafted payload could otherwise reach internal
services or collect the token. Every URL is therefore checked against a host
allowlist and resolved to a public address before a request goes out, redirects
are followed by hand under the same rules, and the token is only ever offered to
Meta's own CDN.
"""

import hashlib
import ipaddress
import logging
import mimetypes
import socket
from urllib.parse import urljoin, urlparse

import httpx
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile

from apps.inbox.models import MediaAsset

logger = logging.getLogger(__name__)

MAX_BYTES = 64 * 1024 * 1024
MAX_REDIRECTS = 3


class MediaRejected(Exception):
    """The URL is not one we are willing to fetch."""


def _auth_headers():
    return {
        "Authorization": f"Bearer {settings.ALOTS_API_KEY}",
        "Version": settings.ALOTS_VERSION,
    }


def _allowed_hosts():
    hosts = {h.lower().rstrip(".") for h in settings.MEDIA_ALLOWED_HOSTS}
    gateway = urlparse(settings.ALOTS_BASE_URL).hostname
    if gateway:
        hosts.add(gateway.lower().rstrip("."))
    return hosts


def _check_url(url):
    """Return the validated host, or refuse the URL.

    Both halves matter. The allowlist stops the worker being pointed at an
    arbitrary service; resolving the name and rejecting non-public addresses
    stops an allowed name whose DNS answers with 127.0.0.1 or a LAN address
    from reaching past it.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise MediaRejected(f"Refusing non-HTTPS media URL ({parsed.scheme or 'no scheme'})")

    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _allowed_hosts():
        raise MediaRejected(f"Media host '{host}' is not allowed")

    try:
        resolved = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise MediaRejected(f"Could not resolve media host '{host}': {exc}") from exc

    for entry in resolved:
        address = ipaddress.ip_address(entry[4][0])
        if not address.is_global:
            raise MediaRejected(f"Media host '{host}' resolves to non-public address {address}")

    return host


def _fetch(client, url):
    """Download a media URL, validating every hop.

    Redirects are handled here rather than by httpx so each new location passes
    the same checks — otherwise an allowed host could bounce the worker
    anywhere, token in hand.
    """
    for _ in range(MAX_REDIRECTS + 1):
        host = _check_url(url)

        headers = {}
        if host in {h.lower().rstrip(".") for h in settings.MEDIA_AUTHENTICATED_HOSTS}:
            headers = _auth_headers()

        response = client.get(url, headers=headers, follow_redirects=False)

        if response.is_redirect:
            location = response.headers.get("Location")
            if not location:
                raise MediaRejected("Redirect without a Location header")
            url = urljoin(url, location)
            continue

        response.raise_for_status()
        return response.content

    raise MediaRejected("Too many redirects while fetching media")


def _resolve_via_api(client, media_id, phone_number_id):
    """Fallback: ask the gateway to turn a media id into a signed URL."""
    response = client.get(
        f"{settings.ALOTS_BASE_URL.rstrip('/')}/{settings.ALOTS_VERSION}/{media_id}",
        headers=_auth_headers(),
        params={"phone_number_id": phone_number_id},
    )
    response.raise_for_status()
    return response.json().get("url")


def candidate_media_urls(asset):
    """Ordered URLs to try for one inbound attachment.

    Alots voice-note ``filelink`` values end in ``.bin`` but the file on
    gsauth.com is actually ``.ogg``. Images/docs use the real extension and
    work as-is; audio always 404s on ``.bin`` and then Meta's lookaside URL
    returns 401 with our gateway token — so voice notes never landed. Try the
    mime-matched extension before falling back to Meta's short-lived link.
    """
    urls = []
    source = (getattr(asset, "source_url", None) or "").strip()
    fallback = (getattr(asset, "fallback_url", None) or "").strip()
    mime = (getattr(asset, "mime_type", None) or "").lower()

    def add(url):
        if url and url not in urls:
            urls.append(url)

    add(source)
    if source.lower().endswith(".bin"):
        if mime.startswith("audio/"):
            add(source[:-4] + ".ogg")
            add(source[:-4] + ".opus")
        elif mime.startswith("image/"):
            add(source[:-4] + ".jpg")
            add(source[:-4] + ".jpeg")
            add(source[:-4] + ".png")
            add(source[:-4] + ".webp")
        elif mime.startswith("video/"):
            add(source[:-4] + ".mp4")
        elif "pdf" in mime:
            add(source[:-4] + ".pdf")
    add(fallback)
    return urls


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_media(self, asset_id, phone_number_id):
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if not asset:
        # Reachable only if the row is gone or not yet committed. It used to be
        # the second case, and returning quietly meant a whole class of missing
        # attachments looked like a task that had succeeded.
        logger.warning("download_media: asset %s does not exist", asset_id)
        return
    if asset.downloaded:
        return

    try:
        with httpx.Client(timeout=settings.ALOTS_TIMEOUT) as client:
            urls = candidate_media_urls(asset)
            if not urls and asset.alots_media_id:
                resolved = _resolve_via_api(client, asset.alots_media_id, phone_number_id)
                urls = [resolved] if resolved else []
            if not urls:
                asset.download_error = "No media URL in the webhook payload"
                asset.save(update_fields=["download_error"])
                return

            # The gateway's copy first, Meta's as the second attempt. A miss on
            # the first is routine — it 404s for stickers — and is not worth
            # failing the download over while another link is in hand.
            content = None
            for index, url in enumerate(urls):
                try:
                    content = _fetch(client, url)
                    break
                except (httpx.HTTPError, MediaRejected) as exc:
                    if index == len(urls) - 1:
                        raise
                    logger.info("Media source %s failed for asset %s (%s); trying the next",
                                index + 1, asset_id, exc)
    except MediaRejected as exc:
        # A refused URL will never become acceptable, so do not retry it.
        logger.warning("Rejected media URL for asset %s: %s", asset_id, exc)
        asset.download_error = str(exc)[:1000]
        asset.save(update_fields=["download_error"])
        return
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
