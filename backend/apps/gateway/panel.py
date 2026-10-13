"""The alots *panel* — the part of the gateway that has no public API.

alots' public API forwards a template create to Meta untouched, and Meta wants
a media-header sample as a handle from its Resumable Upload API. The public
API has no route for that upload. alots' own web panel has one —
``/WAMessage/WATemplate/UploadMedia`` — which mints the handle with alots' app,
and the public create then accepts that handle (proved 2026-09-22: a template
went to Pending). So a media header needs no Meta token of our own after all.

That endpoint only answers to a signed-in panel session: the account API key
is redirected to /signin. The session comes from a browser login, captured
into ``ALOTS_UI_COOKIE_B64`` (``ops/wa.sh set-alots-ui-cookie``) and then kept
in one ``PanelSession`` row, because alots' auth ticket lasts six hours and
slides: every answer that renews a cookie is folded back into the row, and
``keepalive_session`` (beat, every ten minutes) makes sure an answer comes
often enough. When the session lapses anyway, alots redirects to /signin and
that is reported as ``PanelSessionExpired`` so the screen says what to do.
"""

import hashlib
import logging
import time
from email.utils import parsedate_to_datetime

import httpx
from django.conf import settings
from django.utils import timezone

from .client import AlotsError, describe_alots_failure
from .models import ApiCall, PanelSession

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/WAMessage/WATemplate/UploadMedia"
KEEPALIVE_PATH = "/Client/MyProfile/Index"
#: The cookie alots' auth ticket lives in; its Expires is the session's.
AUTH_COOKIE = "SmartBWAomniAuth"

NOT_CONFIGURED = (
    "Image, video and document headers need a signed-in alots panel session on "
    "the server (ALOTS_UI_COOKIE_B64 is not set) or Meta's own access token "
    "(META_GRAPH_ACCESS_TOKEN). An admin can add either; text headers work "
    "without them."
)
SESSION_EXPIRED = (
    "The alots panel session stored on the server has expired. An admin must "
    "sign in to alots.io again and refresh it (ops/wa.sh set-alots-ui-cookie). "
    "Text headers still work."
)

#: What alots' panel calls each header kind in the upload form.
FILE_TYPES = {"IMAGE": "Image", "VIDEO": "Video", "DOCUMENT": "Document"}


class PanelNotConfigured(AlotsError):
    """No session on the server."""


class PanelSessionExpired(AlotsError):
    """The stored session no longer signs in."""


# ---------------------------------------------------------------- cookies --


def parse_cookie_header(text):
    """``a=1; b=2`` → {"a": "1", "b": "2"}, first occurrence wins."""
    jar = {}
    for part in str(text or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name and name not in jar:
            jar[name] = value
    return jar


def cookie_header(jar):
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def merge_set_cookies(jar, set_cookie_values):
    """Fold ``Set-Cookie`` answers into a cookie jar.

    Returns the auth cookie's Expires when it was renewed, else None. A cookie
    alots deletes (Max-Age=0, or an Expires in the past) leaves the jar.
    """
    renewed_expiry = None
    for raw in set_cookie_values or []:
        head, _, tail = str(raw).partition(";")
        name, sep, value = head.strip().partition("=")
        if not sep or not name:
            continue
        attrs = {}
        for piece in tail.split(";"):
            key, _, val = piece.strip().partition("=")
            attrs[key.strip().lower()] = val.strip()
        expires = None
        if attrs.get("expires"):
            try:
                expires = parsedate_to_datetime(attrs["expires"])
            except (TypeError, ValueError):
                expires = None
        gone = attrs.get("max-age") == "0" or (expires is not None and expires <= timezone.now())
        if gone or value == "":
            jar.pop(name, None)
            continue
        jar[name] = value
        if name == AUTH_COOKIE and expires is not None:
            renewed_expiry = expires
    return renewed_expiry


# ---------------------------------------------------------------- session --


def _seed_fingerprint(seed):
    return hashlib.sha256(seed.encode("utf-8")).hexdigest() if seed else ""


def load_session():
    """The row that holds the live session, seeded or re-seeded from the env.

    A new ``ALOTS_UI_COOKIE_B64`` (an admin captured a fresh login) has a new
    fingerprint and replaces whatever the row had grown into.
    """
    seed = (getattr(settings, "ALOTS_UI_COOKIE", "") or "").strip()
    fingerprint = _seed_fingerprint(seed)
    row = PanelSession.objects.order_by("pk").first()
    if row is None:
        row = PanelSession(cookie=seed, seed_fingerprint=fingerprint)
        if seed:
            row.save()
        return row
    if seed and row.seed_fingerprint != fingerprint:
        row.cookie = seed
        row.seed_fingerprint = fingerprint
        row.expires_at = None
        row.last_error = ""
        row.save(update_fields=["cookie", "seed_fingerprint", "expires_at", "last_error", "updated_at"])
    return row


def panel_configured():
    return bool((load_session().cookie or "").strip())


def session_summary():
    """What the screen may say about the session — never the cookie."""
    row = load_session()
    return {
        "configured": bool((row.cookie or "").strip()),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_ok_at": row.last_ok_at.isoformat() if row.last_ok_at else None,
        "last_error": row.last_error or "",
    }


class AlotsPanelClient:
    def __init__(self, cookie=None, base_url=None, timeout=None):
        self.row = None
        if cookie is None:
            self.row = load_session()
            cookie = self.row.cookie
        self.jar = parse_cookie_header(cookie)
        self.base_url = (base_url or settings.ALOTS_BASE_URL).rstrip("/")
        self.timeout = timeout or max(float(settings.ALOTS_TIMEOUT), 120.0)
        if not self.jar:
            raise PanelNotConfigured(NOT_CONFIGURED, status_code=503)

    @property
    def cookie(self):
        return cookie_header(self.jar)

    def _headers(self):
        return {
            "Cookie": self.cookie,
            "Accept": "application/json, text/html;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _absorb(self, response, ok):
        """Fold renewed cookies into the row and note the outcome."""
        try:
            renewed = merge_set_cookies(self.jar, response.headers.get_list("set-cookie"))
        except Exception:  # noqa: BLE001 - a strange header must not break an upload
            renewed = None
        if self.row is None:
            return
        self.row.cookie = self.cookie
        if renewed is not None:
            self.row.expires_at = renewed
        if ok:
            self.row.last_ok_at = timezone.now()
            self.row.last_error = ""
        else:
            self.row.last_error = SESSION_EXPIRED[:300]
        self.row.save()

    def _expired(self, response):
        location = response.headers.get("location", "")
        return response.status_code in (301, 302, 303, 307, 308) or "/signin" in location

    def keepalive(self):
        """One cheap signed-in page, so the ticket slides and the session stays."""
        record = ApiCall(method="GET", path=f"[panel]{KEEPALIVE_PATH}")
        started = time.monotonic()
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.get(f"{self.base_url}{KEEPALIVE_PATH}", headers=self._headers())
        except httpx.HTTPError as exc:
            record.error = str(exc)[:500]
            record.duration_ms = int((time.monotonic() - started) * 1000)
            record.save()
            return False
        record.duration_ms = int((time.monotonic() - started) * 1000)
        record.status_code = response.status_code
        alive = response.status_code == 200 and not self._expired(response)
        if not alive:
            record.error = f"redirect {response.headers.get('location', '')[:160]}"
        record.save()
        self._absorb(response, alive)
        return alive

    def upload_template_sample(self, payload, filename, mime_type, header_format, waba_business_id):
        """Send the sample file through alots' panel; return Meta's handle.

        The handle is minted with alots' app, so it is the one the public
        create call — which also goes out under alots' app — will accept.
        The response is logged without the handle itself.
        """
        kind = FILE_TYPES.get(str(header_format or "").upper())
        if not kind:
            raise AlotsError("The header must be an image, a video or a document.")

        record = ApiCall(
            method="POST",
            path=f"[panel]{UPLOAD_PATH}",
            request_body={"fileType": kind, "waba_business_id": waba_business_id, "bytes": len(payload)},
        )
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.post(
                    f"{self.base_url}{UPLOAD_PATH}",
                    headers=self._headers(),
                    data={
                        "fileType": kind,
                        "originalFileName": filename,
                        "WABABusinessId": str(waba_business_id),
                    },
                    files={"mediaFile": (filename, payload, mime_type)},
                )
        except httpx.HTTPError as exc:
            record.error = str(exc)
            record.duration_ms = int((time.monotonic() - started) * 1000)
            record.save()
            raise AlotsError(f"POST {UPLOAD_PATH} failed: {exc}") from exc

        record.duration_ms = int((time.monotonic() - started) * 1000)
        record.status_code = response.status_code

        if self._expired(response):
            record.error = f"redirect {response.headers.get('location', '')[:160]}"
            record.save()
            self._absorb(response, False)
            raise PanelSessionExpired(SESSION_EXPIRED, status_code=503)

        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            # The sign-in page, or an error page: either way not a session.
            record.error = response.text[:500]
            record.save()
            self._absorb(response, False)
            raise PanelSessionExpired(SESSION_EXPIRED, status_code=503)

        logged = {key: value for key, value in body.items() if key != "hValue"}
        logged["hValue"] = bool(body.get("hValue"))
        record.response_body = logged
        record.save()
        self._absorb(response, True)

        if response.status_code >= 400:
            raise AlotsError(
                describe_alots_failure(f"POST {UPLOAD_PATH} -> HTTP {response.status_code}", body),
                status_code=response.status_code,
                payload=logged,
            )
        handle = str(body.get("hValue") or "").strip()
        if not body.get("status") or not handle:
            raise AlotsError(
                f"alots did not return a sample handle: {body.get('message') or 'no message'}",
                payload=logged,
            )
        return handle


def keepalive_session():
    """Beat entry point. Returns "not-configured", "alive" or "expired"."""
    try:
        client = AlotsPanelClient()
    except PanelNotConfigured:
        return "not-configured"
    alive = client.keepalive()
    if not alive:
        logger.warning("alots panel session keepalive failed — session expired?")
    return "alive" if alive else "expired"
