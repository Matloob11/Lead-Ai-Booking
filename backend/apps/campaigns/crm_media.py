"""Header media for CRM campaigns: the file a Bitrix campaign popup attaches.

An approved template whose header is an image, video or document needs one
file per campaign, sent with every message as Meta's media id. The Bitrix
popup has a Bitrix session and nothing else, so the file travels the way every
CRM campaign request already does: the browser posts it to the Bitrix tool
(``a7_lead_wa.php``, action ``header-media``), and the tool streams the raw
bytes here, signed with the shared CRM secret over the timestamp, a small
metadata header and the bytes themselves.

A media id belongs to the number that uploaded it, so the file goes to the
gateway for the number the campaign will leave from. The popup gets back a
signed token rather than the bare id, and the send checks that token against
the agent, the number and the template's header kind: a file chosen for one
number can never go out from another, and a video never lands in an image
header. Leads, Owner Data, Deals, Contacts and Renewals all use this one route.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import tempfile
import time

from django.core import signing
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.gateway.client import AlotsClient, AlotsError

from .crm_leads import CrmLeadSendError, agent_for_bitrix_user, number_for_agent, shared_secret

logger = logging.getLogger(__name__)

MB = 1024 * 1024

# Meta's own limits for a header of each kind.
HEADER_MEDIA = {
    "IMAGE": {
        "word": "image",
        "types": ("image/jpeg", "image/png"),
        "limit": 5 * MB,
        "words": "a JPEG or PNG up to 5 MB",
    },
    "VIDEO": {
        "word": "video",
        "types": ("video/mp4", "video/3gpp"),
        "limit": 16 * MB,
        "words": "an MP4 or 3GP video up to 16 MB",
    },
    "DOCUMENT": {
        "word": "document",
        # Meta takes only PDF for a template's document header. A Word file
        # would upload fine and then fail on every send.
        "types": ("application/pdf",),
        "limit": 100 * MB,
        "words": "a PDF up to 100 MB",
    },
}

# By extension, because a browser may label a .docx "application/zip" or
# leave the type empty. The bytes decide in the end (``_bytes_fit``).
EXTENSION_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".mp4": "video/mp4",
    ".3gp": "video/3gpp",
    ".3gpp": "video/3gpp",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
}
TYPE_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "video/3gp": "video/3gpp"}

OOXML_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
LEGACY_OFFICE_TYPES = {"application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint"}

MAX_BODY = max(rule["limit"] for rule in HEADER_MEDIA.values())
CHUNK = MB
# The tool signs before it starts streaming, and a 100 MB document from the
# Bitrix box can take minutes to arrive; the window is wider than a send's.
UPLOAD_SKEW_SEC = 15 * 60

SIGNATURE = re.compile(r"[0-9a-f]{64}")

TOKEN_SALT = "campaigns.crm-header-media"
# Meta keeps an uploaded media id for 30 days; a popup left open for a few
# hours must still be able to send.
TOKEN_MAX_AGE = 24 * 3600


def header_word(header_format: str) -> str:
    return HEADER_MEDIA.get(str(header_format or "").upper(), {}).get("word", "file")


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


# Tokens ---------------------------------------------------------------------


def issue_media_token(*, agent, number, header_format: str, media_id: str) -> str:
    return signing.dumps(
        {"a": agent.pk, "n": number.pk, "f": header_format, "m": media_id},
        salt=TOKEN_SALT,
        compress=True,
    )


def header_media_id_for(token, *, agent, number, template, side: str = "") -> str:
    """The media id a CRM campaign may send with; "" when the template has no media header.

    ``side`` names the template in a two-template popup (Renewals: "tenant",
    "owner") so the agent knows which of the two files to choose again.
    """
    if template is None or not getattr(template, "requires_header_media", False):
        return ""
    kind = str((template.header or {}).get("format") or "").upper()
    word = header_word(kind)
    whose = f" for the {side} template" if side else ""
    text = str(token or "").strip()
    if not text:
        raise CrmLeadSendError(f"Choose the {word} for the header{whose}.")
    try:
        data = signing.loads(text, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise CrmLeadSendError(
            f"The header {word}{whose} was chosen more than a day ago. Choose it again."
        ) from exc
    except signing.BadSignature as exc:
        raise CrmLeadSendError(f"The header {word}{whose} could not be checked. Choose it again.") from exc
    if not isinstance(data, dict) or data.get("a") != agent.pk:
        raise CrmLeadSendError(f"Choose the header {word}{whose} again.")
    if data.get("n") != number.pk:
        raise CrmLeadSendError(
            f"The header {word}{whose} was uploaded for another WhatsApp number. Choose it again."
        )
    if data.get("f") != kind:
        raise CrmLeadSendError(
            f"This template's header is {_article(word)} {word}, but the file chosen{whose} is "
            f"{_article(header_word(data.get('f')))} {header_word(data.get('f'))}. "
            f"Choose {_article(word)} {word}."
        )
    media_id = str(data.get("m") or "").strip()
    if not media_id:
        raise CrmLeadSendError(f"Choose the header {word}{whose} again.")
    return media_id


# Upload ---------------------------------------------------------------------


def _bytes_fit(head: bytes, mime: str) -> bool:
    """Whether the first bytes are what the type claims. A renamed file is refused here."""
    if mime == "image/jpeg":
        return head[:3] == b"\xff\xd8\xff"
    if mime == "image/png":
        return head[:8] == b"\x89PNG\r\n\x1a\n"
    if mime in {"video/mp4", "video/3gpp"}:
        return head[4:8] == b"ftyp"
    if mime == "application/pdf":
        return b"%PDF-" in head[:1024]
    if mime in OOXML_TYPES:
        return head[:4] == b"PK\x03\x04"
    if mime in LEGACY_OFFICE_TYPES:
        return head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if mime == "text/plain":
        return b"\x00" not in head
    return False


def resolve_type(claimed, filename, header_format: str, head: bytes) -> str:
    """The media type to upload under, or "" when the file is not one this header takes."""
    allowed = HEADER_MEDIA[header_format]["types"]
    # The bytes win over the name. Windows and Bitrix often label a real JPEG
    # as application/octet-stream, or save a PNG with a .jpg name.
    if header_format == "IMAGE":
        for mime in ("image/jpeg", "image/png"):
            if mime in allowed and _bytes_fit(head, mime):
                return mime
    given = str(claimed or "").split(";")[0].strip().lower()
    given = TYPE_ALIASES.get(given, given)
    ext = os.path.splitext(str(filename or "").strip().lower())[1]
    for mime in (given, EXTENSION_TYPES.get(ext, "")):
        if mime and mime in allowed and _bytes_fit(head, mime):
            return mime
    return ""


def clean_filename(raw, mime: str) -> str:
    """The base name without control characters, at most 120 long, extension kept."""
    name = re.split(r"[/\x5c]", str(raw or ""))[-1]
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name).strip()
    root, ext = os.path.splitext(name)
    ext = ext[:16]
    name = (root[: 120 - len(ext)] + ext).strip()
    if name.strip("."):
        return name
    ext = next((e for e, t in EXTENSION_TYPES.items() if t == mime), "")
    return f"header{ext}"


def read_signed_upload(request):
    """Check the HMAC over ``ts.meta.`` plus the raw bytes while spooling them.

    Returns ``(meta, spool, size)``. The bytes are hashed as they are read, so
    a large document never needs a second copy just to be verified.
    """
    secret = shared_secret()
    if not secret:
        raise CrmLeadSendError("CRM lead WhatsApp send is not configured.")
    try:
        ts = int(str(request.headers.get("X-Crm-Ts", "")).strip())
    except ValueError as exc:
        raise CrmLeadSendError("Missing request timestamp.") from exc
    if abs(int(time.time()) - ts) > UPLOAD_SKEW_SEC:
        raise CrmLeadSendError("Request expired. Refresh the page and try again.")
    try:
        declared = int(request.headers.get("Content-Length") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_BODY:
        raise CrmLeadSendError("WhatsApp does not take a header file larger than 100 MB.")
    meta_b64 = str(request.headers.get("X-Crm-Meta", "")).strip()
    presented = str(request.headers.get("X-Crm-Sign", "")).strip().lower()
    # A signature that is not 64 hex characters can never match, so it is
    # refused before the body is read; compare_digest would also raise on
    # non-ASCII header bytes, which made a 500 out of a bad request.
    if not SIGNATURE.fullmatch(presented):
        raise CrmLeadSendError("Forbidden.")
    try:
        prefix = f"{ts}.{meta_b64}.".encode("ascii")
    except UnicodeEncodeError as exc:
        raise CrmLeadSendError("Forbidden.") from exc
    mac = hmac.new(secret.encode("utf-8"), prefix, hashlib.sha256)

    spool = tempfile.SpooledTemporaryFile(max_size=8 * MB)
    size = 0
    try:
        while True:
            chunk = request.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BODY:
                raise CrmLeadSendError("WhatsApp does not take a header file larger than 100 MB.")
            mac.update(chunk)
            spool.write(chunk)
        if not hmac.compare_digest(presented, mac.hexdigest()):
            raise CrmLeadSendError("Forbidden.")
        try:
            meta = json.loads(base64.b64decode(meta_b64, validate=True).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CrmLeadSendError("The upload could not be read. Refresh the page and try again.") from exc
        if not isinstance(meta, dict):
            raise CrmLeadSendError("The upload could not be read. Refresh the page and try again.")
    except Exception:
        spool.close()
        raise
    spool.seek(0)
    return meta, spool, size


def _status_for(exc: CrmLeadSendError) -> int:
    text = str(exc)
    if "not configured" in text:
        return 503
    if text == "Forbidden.":
        return 403
    return 400


@csrf_exempt
@require_POST
def crm_header_media(request):
    """One header file from the Bitrix tool, uploaded for the campaign's number. HMAC, no session."""
    spool = None
    try:
        meta, spool, size = read_signed_upload(request)
        agent = agent_for_bitrix_user(meta.get("bitrix_user_id"))
        number = number_for_agent(agent, meta.get("number_id"))
        header_format = str(meta.get("format") or "").strip().upper()
        rule = HEADER_MEDIA.get(header_format)
        if rule is None:
            raise CrmLeadSendError("Say whether the header is an image, a video or a document.")
        if size <= 0:
            raise CrmLeadSendError("That file is empty.")
        if size > rule["limit"]:
            raise CrmLeadSendError(f"That file is too large. WhatsApp takes {rule['words']}.")
        head = spool.read(1024)
        spool.seek(0)
        mime = resolve_type(meta.get("mime"), meta.get("filename"), header_format, head)
        if not mime:
            raise CrmLeadSendError(f"That file is not {rule['words']}.")
        name = clean_filename(meta.get("filename"), mime)
        # Straight to the gateway, streamed from the spool. No MediaAsset copy:
        # nothing reads a campaign header back, and a 100 MB brochure chosen
        # again after a number switch would otherwise pile up on the VPS disk.
        media_id = AlotsClient().upload_media(number.phone_number_id, spool, name, mime)
    except CrmLeadSendError as exc:
        return JsonResponse({"detail": str(exc)}, status=_status_for(exc))
    except AlotsError as exc:
        logger.warning("CRM header upload refused by the gateway: %s", exc)
        return JsonResponse({"detail": f"WhatsApp did not accept the file: {exc}"}, status=502)
    finally:
        if spool is not None:
            spool.close()

    if not media_id:
        return JsonResponse(
            {"detail": "WhatsApp returned no media id for that file. Try again."}, status=502
        )
    logger.info(
        "CRM header %s uploaded: agent=%s number=%s size=%s", header_format, agent.pk, number.pk, size
    )
    return JsonResponse(
        {
            "media_token": issue_media_token(
                agent=agent, number=number, header_format=header_format, media_id=media_id
            ),
            "format": header_format,
            "name": name,
            "size": size,
            "mime": mime,
            "number_id": number.pk,
        },
        status=201,
    )
