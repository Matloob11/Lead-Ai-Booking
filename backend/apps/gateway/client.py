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
* ``POST …/message_templates`` reaches Meta for create. ``DELETE`` on the same
  path returns HTTP 405 — not forwarded. Removal goes through Meta Graph
  directly when ``META_GRAPH_ACCESS_TOKEN`` is configured.
"""

import logging
import time

import httpx
from django.conf import settings

from .models import ApiCall

logger = logging.getLogger(__name__)


def describe_alots_failure(fallback, payload=None):
    """The sentence alots or Meta actually returned, not just ``HTTP 500``.

    Their 500 body is often ``{isValid, response:[{status, message}]}`` — the
    useful line is ``Network Banned…``, not the status code. Meta's shape is
    ``{error:{error_user_msg, message}}``.
    """
    sentence = _payload_sentence(payload)
    if not sentence:
        return fallback
    if "network banned" in sentence.lower():
        return (
            f"{sentence} This From-number cannot send until the provider unbans it. "
            "Pick another number and try again."
        )
    return sentence


def _payload_sentence(payload):
    if not isinstance(payload, dict):
        return ""
    err = payload.get("error")
    if isinstance(err, dict):
        text = (
            err.get("error_user_msg")
            or err.get("error_user_title")
            or err.get("message")
        )
        if text:
            return str(text)
    if payload.get("detail"):
        return str(payload["detail"])
    rows = payload.get("response")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return str(rows[0].get("status") or rows[0].get("message") or "")
    if isinstance(rows, dict):
        return str(rows.get("status") or rows.get("message") or "")
    return ""


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

    def _request(self, method, path, *, json=None, files=None, params=None, log_body=True, headers=None, redact_response=False, timeout=None):
        url = f"{self.base_url}{path}"
        started = time.monotonic()
        record = ApiCall(
            method=method,
            path=path,
            request_body=json if log_body else (params if params else None),
        )
        use_headers = headers or self._headers

        try:
            with httpx.Client(timeout=timeout or self.timeout, follow_redirects=False) as client:
                response = client.request(
                    method, url, headers=use_headers, json=json, files=files, params=params
                )
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

        if redact_response and isinstance(body, dict):
            record.response_body = {"n": len(body.get("chatList") or [])}
        else:
            record.response_body = body if isinstance(body, (dict, list)) else None
        record.save()

        if response.status_code >= 400:
            raw = f"{method} {path} -> HTTP {response.status_code}"
            raise AlotsError(
                describe_alots_failure(raw, body if not redact_response else None),
                status_code=response.status_code,
                payload=body if not redact_response else None,
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

    def create_template(self, waba_business_id, payload):
        """Submit a new message template to Meta for approval."""
        return self._request(
            "POST",
            f"/{self.version}/{waba_business_id}/message_templates",
            json=payload,
        )

    def delete_template(self, waba_business_id, name, *, meta_template_id=""):
        """Remove a template from Meta by name.

        Meta deletes every language of that name, which is what we want when
        an agent is about to recreate it — a leftover language still occupies
        the name and the next create comes back as a duplicate.

        The alots gateway answers POST on this path but not DELETE (405). When
        that happens we call Meta Graph directly — see ``META_GRAPH_ACCESS_TOKEN``.
        """
        params = {"name": name}
        if meta_template_id:
            params["hsm_id"] = str(meta_template_id)
        try:
            return self._request(
                "DELETE",
                f"/{self.version}/{waba_business_id}/message_templates",
                params=params,
            )
        except AlotsError as exc:
            if exc.status_code != 405:
                raise
            return self._delete_template_via_graph(
                waba_business_id,
                name,
                meta_template_id=meta_template_id,
            )

    def _delete_template_via_graph(self, waba_business_id, name, *, meta_template_id=""):
        token = (getattr(settings, "META_GRAPH_ACCESS_TOKEN", "") or "").strip()
        if not token:
            raise AlotsError(
                "The gateway does not support DELETE on message_templates (HTTP 405). "
                "Add META_GRAPH_ACCESS_TOKEN to deploy/.env — the Meta System User "
                "token with whatsapp_business_management (the same permanent token "
                "stored in the alots WABA settings works).",
                status_code=405,
            )

        base = getattr(settings, "META_GRAPH_BASE_URL", "https://graph.facebook.com").rstrip("/")
        path = f"/{self.version}/{waba_business_id}/message_templates"
        params = {"name": name}
        if meta_template_id:
            params["hsm_id"] = str(meta_template_id)
        url = f"{base}{path}"
        started = time.monotonic()
        record = ApiCall(method="DELETE", path=f"[graph]{path}", request_body=params)

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.request(
                    "DELETE",
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except httpx.HTTPError as exc:
            record.error = str(exc)
            record.duration_ms = int((time.monotonic() - started) * 1000)
            record.save()
            raise AlotsError(f"DELETE {path} failed: {exc}") from exc

        record.duration_ms = int((time.monotonic() - started) * 1000)
        record.status_code = response.status_code

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
            raw = f"DELETE {path} -> HTTP {response.status_code}"
            raise AlotsError(
                describe_alots_failure(raw, body),
                status_code=response.status_code,
                payload=body,
            )
        return body

    # Messages -------------------------------------------------------------
    def send_raw(self, phone_number_id, payload):
        """Post a Meta Cloud API payload verbatim and return the response."""
        return self._request("POST", f"/{self.version}/{phone_number_id}/messages", json=payload)

    def send_text(self, phone_number_id, to, body, preview_url=False, reply_to_wamid=None):
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": preview_url, "body": body},
        }
        if reply_to_wamid:
            payload["context"] = {"message_id": reply_to_wamid}
        return self.send_raw(phone_number_id, payload)

    def mark_read(self, phone_number_id, wamid, typing=False):
        """Turn the customer's ticks blue, and optionally show "typing…".

        Meta carries the typing indicator on the read receipt rather than as
        its own call, and it lapses on its own after about 25 seconds or when
        a message is sent.
        """
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": wamid}
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        return self.send_raw(phone_number_id, payload)

    def send_reaction(self, phone_number_id, to, wamid, emoji):
        """Send an emoji reaction. An empty emoji removes it."""
        return self.send_raw(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "reaction",
                "reaction": {"message_id": wamid, "emoji": emoji},
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

    def send_interactive(self, phone_number_id, to, interactive):
        """Send reply buttons or a list menu.

        Only valid inside the free-form window — an interactive message is not
        a template, so it cannot reopen a closed one.
        """
        return self.send_raw(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": interactive,
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

    def send_location(self, phone_number_id, to, latitude, longitude, name=None, address=None):
        """Share a pin.

        Meta documents the coordinates as strings; this gateway answers
        "Invalid JSON format" to those and only accepts JSON numbers, so they
        go out as floats.
        """
        location = {"latitude": float(latitude), "longitude": float(longitude)}
        if name:
            location["name"] = name
        if address:
            location["address"] = address
        return self.send_raw(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "location",
                "location": location,
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
            timeout=max(self.timeout, 180),
        )
        return (body or {}).get("id") or (body or {}).get("media_id")

    # Account --------------------------------------------------------------
    def wallet_balance(self):
        body = self._request("GET", "/api/v1/user/balance")
        return (body or {}).get("walletBalance")


