"""The shops playbook's media library and its sends (board T30, T31, T32).

The library (LeadAiShopMedia) holds, per shop type, one video and up to six
photos, and one photo of the office front: the build pack's limits. Files are
checked by their bytes, never by their names: an MP4 with an H.264 video track
(and AAC sound, if any) of at most 16 MB, the size WhatsApp delivers; a JPEG or
PNG of at most 5 MB. Admins add, replace, delete and reorder them from the Lead
AI screen (media_views.py), and ``leadai_media_import`` loads the build pack's
folders ("Type 1 ...", "Tpye 2 ..." with its typo, "office") in file-name order.

Sending, from the assistant (engine.py) and its task (tasks.send_shop_media):
- ``send_list``: the WhatsApp list of the three shop types (assistant/shop_flow.py
  writes it), through the gateway's interactive send;
- ``send_type``: a type's video, then its photos one by one (WhatsApp has no
  album send), then its detail card with [Book viewing] [See other types].
Every message is stored with payload.source "leadai_ai" before the gateway is
called, so no turn running meanwhile takes it for a colleague's. A media id
belongs to the number that uploaded it and WhatsApp forgets it after about 30
days, so each file's id is cached per number (LeadAiShopMediaUpload) and
uploaded again when older than 25 days or when a send says the id is no good.
A file that is missing or refused is skipped; the card always goes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import logging
import os
import re
import time
import unicodedata

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import LeadAiShopMedia, LeadAiShopMediaUpload

logger = logging.getLogger(__name__)

Shop = LeadAiShopMedia.Shop
Kind = LeadAiShopMedia.Kind
TYPE_SHOPS = (Shop.TYPE_1, Shop.TYPE_2, Shop.TYPE_3)
MB = 1024 * 1024
VIDEO_MAX = 16 * MB
PHOTO_MAX = 5 * MB
VIDEOS_PER_TYPE = 1
PHOTOS_PER_TYPE = 6
OFFICE_PHOTOS = 1
NAME_MAX = 120
MEDIA_ID_FRESH = dt.timedelta(days=25)
# Between two sends of one type, so the video, the photos and the card arrive in order.
SEND_PAUSE = 1.2
MIME = {"mp4": "video/mp4", "jpeg": "image/jpeg", "png": "image/png"}
# MP4 sample entries: WhatsApp plays H.264 video with AAC sound (or none). A phone's
# metadata or timecode track ("mebx", "tmcd") is neither, and is left alone.
H264 = {"avc1", "avc3"}
OTHER_VIDEO = {"hvc1", "hev1", "av01", "vp08", "vp09", "mp4v", "dvh1", "dvhe"}
OTHER_SOUND = {"ac-3", "ec-3", "Opus", "opus", "alac", "samr", "sawb", ".mp3", "fLaC", "lpcm", "sowt", "twos", "ipcm", "fpcm"}
EXTENSION = {"mp4": "mp4", "jpeg": "jpg", "png": "png"}
# What a gateway send answers when the media id is no good (expired, another number's).
_BAD_MEDIA_ID = re.compile(
    r"media.{0,40}(?:id|attachment).{0,40}(?:invalid|not valid|not found|does not exist|expired)"
    r"|(?:invalid|unknown|expired).{0,40}media|131053|131052|\b2494102\b",
    re.IGNORECASE,
)
# The build pack's folders: "Type 1 400 550sqft", "Tpye 2 700 800 sqft", "type-3", "office".
_FOLDER = re.compile(r"^\s*(?:type|tpye|typ)[\s_-]*([123])(?!\d)", re.IGNORECASE)


class MediaRejected(ValueError):
    """The file cannot go in the library; the message says why, for an admin."""


# Checking a file ---------------------------------------------------------------------------------


def sniff(head: bytes) -> str:
    """'mp4', 'jpeg' or 'png' from a file's first bytes, else ''."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4"
    return ""


def _boxes(data: bytes, start: int, end: int):
    """(type, body start, body end) of each ISO base media box between start and end."""
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        header = 8
        if size == 1 and pos + 16 <= end:
            size = int.from_bytes(data[pos + 8 : pos + 16], "big")
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def mp4_codecs(data: bytes) -> set[str]:
    """The sample entry of every track in an MP4 ("avc1", "mp4a", "hvc1", ...): the codecs.

    Walks moov > trak > mdia > minf > stbl > stsd; an empty set when the file has
    no readable movie box.
    """
    found: set[str] = set()
    path = (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"stsd")

    def walk(start, end, depth):
        for kind, body, stop in _boxes(data, start, end):
            if kind != path[depth]:
                continue
            if kind == b"stsd":
                # version and flags (4) and the entry count (4), then the sample entries.
                for entry, _, _ in _boxes(data, body + 8, stop):
                    found.add(entry.decode("latin-1"))
            else:
                walk(body, stop, depth + 1)

    walk(0, len(data), 0)
    return found


def clean_name(name) -> str:
    """The uploaded name for people: the last path part, printable, at most NAME_MAX characters."""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C")
    return (" ".join(base.split()) or "file")[:NAME_MAX]


def check_file(name: str, data: bytes, shop: str = "") -> tuple[str, str, str]:
    """(kind, mime type, format) of a file the library may hold, else MediaRejected.

    ``shop``: "office" takes a photo only.
    """
    label = clean_name(name)
    if not data:
        raise MediaRejected(f"{label}: the file is empty.")
    found = sniff(data[:16])
    if found == "mp4":
        if shop == Shop.OFFICE:
            raise MediaRejected(f"{label}: the office takes one photo (JPEG or PNG), not a video.")
        if len(data) > VIDEO_MAX:
            raise MediaRejected(f"{label}: the video is {len(data) / MB:.1f} MB; WhatsApp delivers videos of at most 16 MB.")
        codecs = mp4_codecs(data)
        if not codecs & H264 or codecs & OTHER_VIDEO:
            what = ", ".join(sorted(codecs)) or "no readable video track"
            raise MediaRejected(f"{label}: the video must be H.264 (MP4 with an avc1 track); this one has {what}.")
        if codecs & OTHER_SOUND:
            raise MediaRejected(f"{label}: the sound must be AAC (mp4a); this one has {', '.join(sorted(codecs & OTHER_SOUND))}.")
        return Kind.VIDEO, MIME["mp4"], "mp4"
    if found in ("jpeg", "png"):
        if len(data) > PHOTO_MAX:
            raise MediaRejected(f"{label}: the photo is {len(data) / MB:.1f} MB; at most 5 MB.")
        return Kind.PHOTO, MIME[found], found
    raise MediaRejected(f"{label}: only an MP4 video (H.264) or a JPEG or PNG photo can go in the library.")


def limit_error(shop: str, kind: str, *, ignore_pk=None) -> str:
    """'' when the shop has room for one more file of this kind, else why not."""
    rows = LeadAiShopMedia.objects.filter(shop=shop, kind=kind)
    if ignore_pk is not None:
        rows = rows.exclude(pk=ignore_pk)
    count = rows.count()
    if shop == Shop.OFFICE:
        return "The office has its photo already: replace or delete it first." if count >= OFFICE_PHOTOS else ""
    label = Shop(shop).label
    if kind == Kind.VIDEO and count >= VIDEOS_PER_TYPE:
        return f"{label} has its video already: replace or delete it first."
    if kind == Kind.PHOTO and count >= PHOTOS_PER_TYPE:
        return f"{label} has {PHOTOS_PER_TYPE} photos already, the most a type takes: delete one first."
    return ""


def folder_shop(name) -> str:
    """The shop a build-pack folder is for: "Type 1 400 550sqft" is type_1, the typo
    "Tpye 2 ..." type_2, "office" office; '' for anything else."""
    text = str(name or "").strip()
    match = _FOLDER.match(text)
    if match:
        return f"type_{match[1]}"
    return Shop.OFFICE if text.casefold().startswith("office") else ""


def _natural(name: str):
    """File-name order, numbers by value ("2.jpg" before "10.jpg")."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)]


# The library -----------------------------------------------------------------------------------------


def rows_for(shop: str) -> list[LeadAiShopMedia]:
    """A shop's files in sending order: the video first, then the photos by ``order``."""
    rows = list(LeadAiShopMedia.objects.filter(shop=shop).order_by("order", "pk"))
    return [row for row in rows if row.kind == Kind.VIDEO] + [row for row in rows if row.kind == Kind.PHOTO]


def _next_order(shop: str) -> int:
    last = LeadAiShopMedia.objects.filter(shop=shop).order_by("-order").values_list("order", flat=True).first()
    return (last or 0) + 1


def add(shop: str, name: str, data: bytes, *, uploaded_by=None, order: int | None = None) -> tuple[LeadAiShopMedia, bool]:
    """Put one file in the library: (row, created). The same bytes in this shop already: that
    row, unchanged. Raises MediaRejected for a file it cannot hold or a shop that is full."""
    if shop not in Shop.values:
        raise MediaRejected("Choose Type 1, Type 2, Type 3 or the office.")
    kind, mime, found = check_file(name, data, shop)
    sha = hashlib.sha256(data).hexdigest()
    existing = LeadAiShopMedia.objects.filter(shop=shop, sha256=sha).first()
    if existing is not None:
        return existing, False
    error = limit_error(shop, kind)
    if error:
        raise MediaRejected(error)
    row = LeadAiShopMedia(
        shop=shop,
        kind=kind,
        file_name=clean_name(name),
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha,
        order=_next_order(shop) if order is None else order,
        uploaded_by=uploaded_by,
    )
    row.file.save(f"{shop}-{sha[:16]}.{EXTENSION[found]}", ContentFile(data), save=False)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        _drop_file(row.file.name)
        return LeadAiShopMedia.objects.get(shop=shop, sha256=sha), False
    return row, True


def replace(row: LeadAiShopMedia, name: str, data: bytes, *, uploaded_by=None) -> LeadAiShopMedia:
    """The same place in the order, another file (of the same kind, or a photo for a photo)."""
    kind, mime, found = check_file(name, data, row.shop)
    if kind != row.kind:
        raise MediaRejected(f"{clean_name(name)}: replace a {row.kind} with a {row.kind}.")
    sha = hashlib.sha256(data).hexdigest()
    if LeadAiShopMedia.objects.filter(shop=row.shop, sha256=sha).exclude(pk=row.pk).exists():
        raise MediaRejected(f"{clean_name(name)}: this file is in the library already.")
    old = row.file.name
    row.file.save(f"{row.shop}-{sha[:16]}.{EXTENSION[found]}", ContentFile(data), save=False)
    row.file_name = clean_name(name)
    row.mime_type = mime
    row.size_bytes = len(data)
    row.sha256 = sha
    row.asset = None  # the next send links a fresh attachment; old messages keep theirs
    row.uploaded_by = uploaded_by or row.uploaded_by
    row.save()
    LeadAiShopMediaUpload.objects.filter(media=row).delete()  # the gateway ids were for the old bytes
    if old != row.file.name:
        _drop_file(old)
    return row


def delete(row: LeadAiShopMedia) -> None:
    name = row.file.name
    row.delete()
    _drop_file(name)


def reorder(shop: str, ids: list) -> list[LeadAiShopMedia]:
    """Number a shop's files in the order of ``ids`` (every one of its files, once)."""
    rows = {row.pk: row for row in LeadAiShopMedia.objects.filter(shop=shop)}
    wanted = []
    for raw in ids or []:
        try:
            pk = int(raw)
        except (TypeError, ValueError):
            raise MediaRejected("Send the files' ids as numbers.") from None
        if pk not in rows or pk in wanted:
            raise MediaRejected("Send each of this shop's files once, in the new order.")
        wanted.append(pk)
    if set(wanted) != set(rows):
        raise MediaRejected("Send each of this shop's files once, in the new order.")
    with transaction.atomic():
        for position, pk in enumerate(wanted, start=1):
            LeadAiShopMedia.objects.filter(pk=pk).update(order=position)
    return rows_for(shop)


def _drop_file(name: str) -> None:
    """Remove a stored file nobody needs any more. A sent message's attachment keeps it:
    the thread still shows what went out."""
    if not name:
        return
    from apps.inbox.models import MediaAsset

    if LeadAiShopMedia.objects.filter(file=name).exists() or MediaAsset.objects.filter(file=name).exists():
        return
    try:
        LeadAiShopMedia._meta.get_field("file").storage.delete(name)
    except OSError:
        logger.warning("Lead AI could not delete the library file %s", name)


# The build pack's folders -----------------------------------------------------------------------------


def import_directory(path: str, *, dry_run: bool = False, uploaded_by=None) -> list[str]:
    """Load every "Type N ..." / "office" folder under ``path`` into the library, files in
    name order, and a file at the top whose name starts with "office" (the build pack's
    office_front.jpg) as the office photo. Returns one line per folder and file: what was
    added, what was there already, what was refused and why. ``dry_run`` checks and
    reports, and stores nothing. A type takes its first video and its first six photos by
    name; the rest are reported."""
    lines: list[str] = []
    if not os.path.isdir(path):
        raise MediaRejected(f"{path} is not a directory.")
    planned: dict = {}  # (shop, kind) -> files this run adds (or would add)
    top = sorted(os.listdir(path), key=_natural)
    # The office photo at the top first, then the folders, all in name order.
    loose = [name for name in top if os.path.isfile(os.path.join(path, name)) and name.casefold().startswith("office")]
    for item in loose:
        lines.append(_import_file(Shop.OFFICE, os.path.join(path, item), item, planned, dry_run=dry_run, uploaded_by=uploaded_by))
    for folder in top:
        full = os.path.join(path, folder)
        if not os.path.isdir(full):
            if folder not in loose:
                lines.append(f"skipped file '{clean_name(folder)}': not in a 'Type 1/2/3 ...' or 'office' folder")
            continue
        shop = folder_shop(folder)
        if not shop:
            lines.append(f"skipped folder '{clean_name(folder)}': not 'Type 1/2/3 ...' or 'office'")
            continue
        for item in sorted(os.listdir(full), key=_natural):
            file_path = os.path.join(full, item)
            if os.path.isfile(file_path):
                lines.append(_import_file(shop, file_path, item, planned, dry_run=dry_run, uploaded_by=uploaded_by))
    return lines


def _import_file(shop: str, file_path: str, item: str, planned: dict, *, dry_run: bool, uploaded_by) -> str:
    """One file of the import: the line that says what became of it."""
    label = f"{Shop(shop).label} / {clean_name(item)}"
    try:
        size = os.path.getsize(file_path)
        if size > VIDEO_MAX:
            # Not read at all: no file the library may hold is this large.
            return f"refused {Shop(shop).label}: {clean_name(item)}: {size / MB:.1f} MB; a video takes at most 16 MB, a photo 5 MB."
        with open(file_path, "rb") as handle:
            data = handle.read()
        kind, _, _ = check_file(item, data, shop)
    except MediaRejected as exc:
        return f"refused {Shop(shop).label}: {exc}"
    except OSError as exc:
        return f"refused {label}: cannot read it ({type(exc).__name__})"
    sha = hashlib.sha256(data).hexdigest()
    if LeadAiShopMedia.objects.filter(shop=shop, sha256=sha).exists():
        return f"already there {label}"
    # A dry run stores nothing, so what it would have added counts here; a real run's rows count themselves.
    have = LeadAiShopMedia.objects.filter(shop=shop, kind=kind).count() + planned.get((shop, kind), 0)
    room = OFFICE_PHOTOS if shop == Shop.OFFICE else (VIDEOS_PER_TYPE if kind == Kind.VIDEO else PHOTOS_PER_TYPE)
    if have >= room:
        return f"left out {label}: {Shop(shop).label} takes at most {room} {kind}{'s' if room > 1 else ''}"
    if dry_run:
        planned[(shop, kind)] = planned.get((shop, kind), 0) + 1
        return f"would add {label} ({kind}, {len(data) / MB:.1f} MB)"
    try:
        add(shop, item, data, uploaded_by=uploaded_by)
    except MediaRejected as exc:
        return f"refused {label}: {exc}"
    return f"added {label} ({kind}, {len(data) / MB:.1f} MB)"


# Sending ------------------------------------------------------------------------------------------------


def _bad_media_id(exc) -> bool:
    return bool(_BAD_MEDIA_ID.search(str(exc)))


def gateway_media_id(row: LeadAiShopMedia, number, *, force: bool = False) -> str:
    """The gateway's id for this file on this number: the cached one while it is fresh,
    else a new upload. Raises AlotsError or SendBlocked when the gateway refuses it."""
    from apps.gateway.client import AlotsClient
    from apps.inbox.services import SendBlocked

    now = timezone.now()
    cached = LeadAiShopMediaUpload.objects.filter(media=row, number=number).first()
    if cached is not None and not force and cached.gateway_id and cached.uploaded_at > now - MEDIA_ID_FRESH:
        return cached.gateway_id
    with row.file.open("rb") as handle:
        data = handle.read()
    gateway_id = AlotsClient().upload_media(number.phone_number_id, io.BytesIO(data), row.file_name, row.mime_type)
    if not gateway_id:
        raise SendBlocked("The gateway would not take the file.")
    LeadAiShopMediaUpload.objects.update_or_create(media=row, number=number, defaults={"gateway_id": gateway_id, "uploaded_at": now})
    return gateway_id


def forget_upload(media_pk, number_id) -> None:
    """A send with this file's id failed later (a status webhook): upload it again next time."""
    LeadAiShopMediaUpload.objects.filter(media_id=media_pk, number_id=number_id).delete()


def _asset(row: LeadAiShopMedia):
    """The inbox attachment a sent copy of this file links to (made once per file)."""
    from apps.inbox.models import MediaAsset

    if row.asset_id:
        return row.asset
    asset = MediaAsset(
        mime_type=row.mime_type,
        file_name=row.file_name,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        downloaded=True,
    )
    asset.file.name = row.file.name  # the library's own copy: nothing is duplicated
    asset.save()
    LeadAiShopMedia.objects.filter(pk=row.pk).update(asset=asset)
    row.asset = asset
    return asset


def _payload(turn_id, **extra) -> dict:
    from .assistant import transcript

    return {"source": transcript.ASSISTANT, "turn": turn_id, **extra}


def send_file(conversation, row: LeadAiShopMedia, *, turn_id=None, shop_type: str = "", caption: str = ""):
    """One library file to the customer, stored as ours before the gateway is called."""
    from apps.gateway.client import AlotsClient, AlotsError
    from apps.inbox import services as inbox_services
    from apps.inbox.events import publish_message, publish_status
    from apps.inbox.models import Message

    if not conversation.is_session_open:
        raise inbox_services.SendBlocked("The 24-hour window is closed.")
    kind = Message.Kind.VIDEO if row.kind == Kind.VIDEO else Message.Kind.IMAGE
    asset = _asset(row)
    gateway_id = gateway_media_id(row, conversation.number)
    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=kind,
        body=caption,
        media=asset,
        payload=_payload(
            turn_id, shop_media=shop_type or row.shop, shop_media_id=row.pk, media_id=gateway_id, asset_id=asset.pk,
            filename=row.file_name, gateway_kind=kind,
        ),
        status=Message.Status.QUEUED,
    )
    inbox_services._touch(conversation, caption or f"[{kind}]", kind)
    client = AlotsClient()
    to = inbox_services.format_recipient_for_gateway(conversation.contact.wa_id)
    try:
        try:
            response = client.send_media(conversation.number.phone_number_id, to, kind, gateway_id, caption=caption)
        except AlotsError as exc:
            if not _bad_media_id(exc):
                raise
            # The cached id is no good any more: upload once more and send again.
            gateway_id = gateway_media_id(row, conversation.number, force=True)
            message.payload = {**message.payload, "media_id": gateway_id}
            message.save(update_fields=["payload"])
            response = client.send_media(conversation.number.phone_number_id, to, kind, gateway_id, caption=caption)
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        publish_status(message)
        raise
    inbox_services._record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return message


def send_interactive(conversation, body: str, interactive: dict, *, turn_id=None, preview: str = "", **extra):
    """An interactive message (the shop types list) through the gateway's interactive send,
    stored as ours before the gateway is called."""
    from apps.gateway.client import AlotsClient, AlotsError
    from apps.inbox import services as inbox_services
    from apps.inbox.events import publish_message, publish_status
    from apps.inbox.models import Message

    if not conversation.is_session_open:
        raise inbox_services.SendBlocked("The 24-hour window is closed.")
    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.INTERACTIVE,
        body=body,
        payload=_payload(turn_id, interactive=interactive, **extra),
        status=Message.Status.QUEUED,
    )
    inbox_services._touch(conversation, preview or body, Message.Kind.INTERACTIVE)
    try:
        response = AlotsClient().send_interactive(
            conversation.number.phone_number_id, inbox_services.format_recipient_for_gateway(conversation.contact.wa_id), interactive
        )
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        publish_status(message)
        raise
    inbox_services._record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return message


def send_list(conversation, language: str, shops_facts, *, turn_id=None):
    """The three shop types as a WhatsApp list (assistant/shop_flow.list_interactive)."""
    from .assistant import shop_flow

    interactive = shop_flow.list_interactive(language, shops_facts)
    return send_interactive(
        conversation,
        shop_flow.list_text(language, shops_facts),
        interactive,
        turn_id=turn_id,
        preview=interactive["body"]["text"],
        shop_list=True,
    )


def send_card(conversation, language: str, shop_type: str, shops_facts, *, turn_id=None):
    """The type's detail card, with [Book viewing] [See other types] (reply buttons)."""
    from apps.inbox import services as inbox_services

    from .assistant import shop_flow

    return inbox_services.send_buttons(
        conversation,
        None,
        shop_flow.card_text(language, shop_type, shops_facts),
        shop_flow.card_buttons(language, shop_type),
        payload=_payload(turn_id, shop_card=shop_type),
    )


def _still_ours(conversation) -> str:
    """'' while the assistant may still message this chat, else why not."""
    from .models import LeadAiChat, LeadAiChatState, LeadAiSettings

    chat = LeadAiChat.objects.filter(conversation=conversation, active=True).first()
    if chat is None:
        return "not a Lead AI chat any more"
    conversation.refresh_from_db(fields=["session_expires_at", "linked_conversation"])
    if conversation.linked_conversation_id:
        return "transferred"
    state = LeadAiChatState.objects.filter(conversation=conversation).first()
    if state is not None and (state.stopped_at or state.paused_at):
        return "stopped or paused"
    if not LeadAiSettings.load().answers(conversation.contact.wa_id):
        return "assistant switched off"
    if not conversation.is_session_open:
        return "the 24-hour window is closed"
    return ""


def _sent_by_turn(conversation, turn_id) -> tuple[set, bool]:
    """(library file ids, card sent) this turn's media task sent already: a task delivered
    twice never sends anything twice."""
    from apps.inbox.models import Message

    if turn_id is None:
        return set(), False
    rows = Message.objects.filter(
        conversation=conversation, direction=Message.Direction.OUTBOUND, payload__turn=turn_id
    ).values_list("payload", flat=True)
    files, card = set(), False
    for payload in rows:
        if not isinstance(payload, dict):
            continue
        if payload.get("shop_media_id"):
            files.add(payload["shop_media_id"])
        if payload.get("shop_card"):
            card = True
    return files, card


def send_type(conversation_id: int, shop_type: str, turn_id=None, language: str = "en", *, files: bool = True) -> dict:
    """A type's video, its photos one by one, then its detail card (tasks.send_shop_media);
    ``files`` False: the card alone (the type's files went out today already).

    Nothing goes once the chat is no longer the assistant's to answer. A file the
    gateway refuses is skipped; the card always follows. What this turn's task sent
    already (a task delivered twice) is not sent again. Returns what was sent."""
    from apps.gateway.client import AlotsError
    from apps.inbox.models import Conversation
    from apps.inbox.services import SendBlocked

    from .models import LeadAiSettings

    out: dict = {"files": 0, "skipped": [], "card": None, "stopped": ""}
    conversation = Conversation.objects.select_related("contact", "number").filter(pk=conversation_id).first()
    if conversation is None or shop_type not in TYPE_SHOPS:
        out["stopped"] = "no such chat or shop type"
        return out
    facts = LeadAiSettings.load().shops_facts
    from .assistant import shop_flow

    done, card_done = _sent_by_turn(conversation, turn_id)
    for row in rows_for(shop_type) if files else []:
        if row.pk in done:
            continue
        why = _still_ours(conversation)
        if why:
            out["stopped"] = why
            return out
        caption = shop_flow.video_caption(shop_type, facts) if row.kind == Kind.VIDEO else ""
        try:
            send_file(conversation, row, turn_id=turn_id, shop_type=shop_type, caption=caption)
            out["files"] += 1
        except (AlotsError, SendBlocked, OSError, ValueError) as exc:
            logger.warning("Lead AI skipped library file %s for conversation %s: %s", row.pk, conversation_id, exc)
            out["skipped"].append(row.pk)
            continue
        time.sleep(SEND_PAUSE)
    if card_done:
        out["stopped"] = "the card went out already"
        return out
    why = _still_ours(conversation)
    if why:
        out["stopped"] = why
        return out
    card = send_card(conversation, language, shop_type, facts, turn_id=turn_id)
    out["card"] = card.pk
    return out
