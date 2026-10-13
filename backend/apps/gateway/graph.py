"""Direct calls to Meta's Graph API, for what the alots gateway does not forward.

Media-header templates are the reason this exists. Meta reviews such a template
against a sample file, and that sample is not a WhatsApp media id: it is a
*handle* from Meta's Resumable Upload API, an app-scoped call the gateway has
no route for (its swagger stops at ``/{phoneNumberId}/media``). The template is
then created through Graph as well, with the same token, so the handle and the
template belong to one app.

Needs ``META_GRAPH_ACCESS_TOKEN`` — a System User token with
``whatsapp_business_management`` on the business that owns the WABAs. The app
the token was issued for is read once from ``/app`` unless ``META_APP_ID`` is
set. Without the token every call raises ``GraphNotConfigured`` up front, with
a sentence that says what to add, rather than failing at Meta.
"""

import hashlib
import logging
import time

import httpx
from django.conf import settings

from .client import AlotsError, describe_alots_failure
from .models import ApiCall

logger = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "Image, video and document headers need Meta's own access token, and "
    "META_GRAPH_ACCESS_TOKEN is not set on the server. Add the Meta System User "
    "token (whatsapp_business_management) to deploy/.env and recreate the "
    "containers. Text headers work without it."
)

# App id per token, so /app is asked once per process rather than per upload.
_APP_IDS = {}


class GraphNotConfigured(AlotsError):
    """No token on the server — the caller can say exactly what is missing."""


class MetaGraphClient:
    def __init__(self, token=None, base_url=None, version=None, timeout=None):
        self.token = (token or getattr(settings, "META_GRAPH_ACCESS_TOKEN", "") or "").strip()
        self.base_url = (
            base_url or getattr(settings, "META_GRAPH_BASE_URL", "https://graph.facebook.com")
        ).rstrip("/")
        self.version = version or settings.ALOTS_VERSION
        self.timeout = timeout or settings.ALOTS_TIMEOUT
        if not self.token:
            raise GraphNotConfigured(NOT_CONFIGURED, status_code=503)

    def _call(
        self,
        method,
        path,
        *,
        params=None,
        json=None,
        content=None,
        headers=None,
        log_body=True,
        timeout=None,
    ):
        """One Graph request, logged like a gateway call but marked ``[graph]``.

        A file body is never logged, the token travels in a header so it never
        reaches the path column, and an upload session's ``?sig=`` is cut off
        the logged path for the same reason.
        """
        url = f"{self.base_url}/{self.version}{path}"
        use_headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if headers:
            use_headers.update(headers)

        started = time.monotonic()
        logged = json if json is not None else params
        record = ApiCall(
            method=method,
            path=f"[graph]/{self.version}{path.split('?', 1)[0]}"[:255],
            request_body=logged if log_body else None,
        )

        try:
            with httpx.Client(timeout=timeout or self.timeout, follow_redirects=False) as client:
                response = client.request(
                    method, url, headers=use_headers, params=params, json=json, content=content
                )
        except httpx.HTTPError as exc:
            record.error = str(exc)
            record.duration_ms = int((time.monotonic() - started) * 1000)
            record.save()
            raise AlotsError(f"{method} {path} failed: {exc}") from exc

        record.duration_ms = int((time.monotonic() - started) * 1000)
        record.status_code = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
            record.error = response.text[:2000]
        record.response_body = body if isinstance(body, (dict, list)) else None
        record.save()

        if response.status_code >= 400:
            raise AlotsError(
                describe_alots_failure(f"{method} {path} -> HTTP {response.status_code}", body),
                status_code=response.status_code,
                payload=body,
            )
        return body

    def app_id(self):
        """The app this token belongs to — configured, cached, or asked of Meta."""
        configured = (getattr(settings, "META_APP_ID", "") or "").strip()
        if configured:
            return configured
        key = hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]
        cached = _APP_IDS.get(key)
        if cached:
            return cached
        body = self._call("GET", "/app", params={"fields": "id"}) or {}
        app_id = str(body.get("id") or "").strip()
        if not app_id:
            raise AlotsError(
                "Meta did not say which app this token belongs to. Set META_APP_ID in deploy/.env."
            )
        _APP_IDS[key] = app_id
        return app_id

    def upload_sample(self, payload, filename, mime_type):
        """Resumable Upload API: open a session, send the bytes, return the handle.

        The handle goes into ``example.header_handle`` of a template's HEADER
        component. It is scoped to the app, not to a number, so one upload
        serves every business account the same template is submitted to.
        """
        app_id = self.app_id()
        opened = (
            self._call(
                "POST",
                f"/{app_id}/uploads",
                params={
                    "file_length": len(payload),
                    "file_type": mime_type,
                    "file_name": filename,
                },
            )
            or {}
        )
        upload_id = str(opened.get("id") or "").strip()
        if not upload_id:
            raise AlotsError("Meta did not open an upload session for the sample file.")

        finished = (
            self._call(
                "POST",
                f"/{upload_id}",
                content=payload,
                headers={
                    # This one call wants OAuth, not Bearer — Meta's own docs.
                    "Authorization": f"OAuth {self.token}",
                    "file_offset": "0",
                    "Content-Type": "application/octet-stream",
                },
                log_body=False,
                timeout=max(self.timeout, 180),
            )
            or {}
        )
        handle = str(finished.get("h") or "").strip()
        if not handle:
            raise AlotsError("Meta accepted the file but returned no media handle.")
        return handle

    def create_template(self, waba_business_id, payload):
        """Submit a template straight to Meta, in the same shape the gateway takes."""
        return self._call("POST", f"/{waba_business_id}/message_templates", json=payload)
