"""Client for the alots.io (WBBOX) WhatsApp gateway.

Verified against the live account on 2026-08-02:

* Auth is ``Authorization: Bearer <public API key>`` — one key for the whole
  account. Sending only ``X-API-KEY`` returns 401 despite what the vendor SOP
  PDF claims.
* ``POST /{version}/{phoneNumberId}/messages`` is a raw pass-through to Meta's
  Cloud API, so both free-form and template payloads work unchanged.
* Per-number template lists come from ``/{version}/{wabaId}/message_templates``
  and return 204 when that WABA has none. The account-wide
  ``/api/v1/meta/templates`` endpoint ignores every filter and omits the WABA
  id, so it cannot answer "which templates may this number use".
"""

import logging
import time

import httpx
from django.conf import settings

from .models import ApiCall

logger = logging.getLogger(__name__)


class AlotsError(Exception):
    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AlotsClient:
    def __init__(self, api_key=None, base_url=None, version=None, timeout=None):
        self.api_key = api_key or settings.ALOTS_API_KEY
        self.base_url = (base_url or settings.ALOTS_BASE_URL).rstrip("/")
        self.version = version or settings.ALOTS_VERSION
        self.timeout = timeout or settings.ALOTS_TIMEOUT
        if not self.api_key:
            raise AlotsError("ALOTS_API_KEY is not configured")

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Version": self.version,
            "Accept": "application/json",
        }

    def _request(self, method, path, *, json=None, files=None, log_body=True):
        url = f"{self.base_url}{path}"
        started = time.monotonic()
        record = ApiCall(method=method, path=path, request_body=json if log_body else None)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=self._headers, json=json, files=files)
        except httpx.HTTPError as exc:
            record.error = str(exc)
            record.duration_ms = int((time.monotonic() - started) * 1000)
            record.save()
            raise AlotsError(f"{method} {path} failed: {exc}") from exc

        record.duration_ms = int((time.monotonic() - started) * 1000)
        record.status_code = response.status_code

        # 204 is a legitimate "this WABA has no templates" answer, not an error.
        if response.status_code == 204 or not response.content:
            record.save()
            return None

        try:
            body = response.json()
        except ValueError:
            body = None
            record.error = response.text[:2000]

        record.response_body = body if isinstance(body, (dict, list)) else None
        record.save()

        if response.status_code >= 400:
            raise AlotsError(
                f"{method} {path} -> HTTP {response.status_code}",
                status_code=response.status_code,
                payload=body,
            )
        return body

    # Channels -------------------------------------------------------------
    def list_channels(self):
        """Every WABA number on the account, with its phone id and WABA id."""
        body = self._request("GET", f"/{self.version}/channels")
        return (body or {}).get("data", [])

    # Templates ------------------------------------------------------------
    def list_templates(self, waba_business_id):
        """Approved and pending templates for one WABA, in Meta's own shape."""
        body = self._request("GET", f"/{self.version}/{waba_business_id}/message_templates")
        return (body or {}).get("data", [])

    # Messages -------------------------------------------------------------
    def send_raw(self, phone_number_id, payload):
        """Post a Meta Cloud API payload verbatim and return the response."""
        return self._request("POST", f"/{self.version}/{phone_number_id}/messages", json=payload)

    def send_text(self, phone_number_id, to, body, preview_url=False):
        return self.send_raw(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": preview_url, "body": body},
            },
        )

    def send_template(self, phone_number_id, to, name, language="en", components=None):
        template = {"name": name, "language": {"code": language}}
        if components:
            template["components"] = components
        return self.send_raw(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "template",
                "template": template,
            },
        )

    def send_media(self, phone_number_id, to, kind, media_id, caption=None, filename=None):
        """Send an already-uploaded asset. ``kind`` is image/document/audio/video."""
        media = {"id": media_id}
        if caption and kind in {"image", "video", "document"}:
            media["caption"] = caption
        if filename and kind == "document":
            media["filename"] = filename
        return self.send_raw(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": kind,
                kind: media,
            },
        )

    # Media ----------------------------------------------------------------
    def upload_media(self, phone_number_id, file_obj, filename, mime_type):
        """Upload a file and return the ``media_id`` Meta assigns it."""
        body = self._request(
            "POST",
            f"/{self.version}/{phone_number_id}/media",
            files={"file": (filename, file_obj, mime_type)},
            log_body=False,
        )
        return (body or {}).get("id") or (body or {}).get("media_id")

    # Account --------------------------------------------------------------
    def wallet_balance(self):
        body = self._request("GET", "/api/v1/user/balance")
        return (body or {}).get("walletBalance")
