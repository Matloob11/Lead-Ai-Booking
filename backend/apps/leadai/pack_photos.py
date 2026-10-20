"""A listed unit's photos to the customer (the community packs' flow, round 17; Matloob 2026-10-20: the pictures come
from Property Finder and the customer is referred to our office).

When a pack chat's reply quotes a unit (its reference, or the first match), the turn queues ``send_photos``: the unit's
first PHOTOS_SENT photos (Property Finder's CDN, LeadAiUnit.photos) are downloaded, kept as inbox attachments
(MediaAsset, so the agents see them in the thread), uploaded to the gateway for the chat's number and sent as images, the
reference as the first caption. Once per unit per chat (state.facts["pack_photos"]); nothing goes once the chat is no
longer the assistant's to answer or a person was asked for since the turn (shop_media._still_ours,
unit_media.handed_over_since). A failed download or send skips that photo and never fails the turn.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time

import httpx
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

PHOTOS_SENT = 3
DOWNLOAD_TIMEOUT = 20.0
PHOTO_MAX_BYTES = 6 * 1024 * 1024
SEND_PAUSE = 0.6
FACT_KEY = "pack_photos"  # state.facts: the references whose photos went to this chat
SOURCE = "leadai_photos"  # the message payload's source: ours (transcript.is_ours reads the prefix)


def sent_before(state, unit) -> bool:
    facts = state.facts if isinstance(getattr(state, "facts", None), dict) else {}
    done = facts.get(FACT_KEY) if isinstance(facts.get(FACT_KEY), list) else []
    return bool(unit.reference) and unit.reference in done


def remember(state, unit) -> None:
    from .models import LeadAiChatState

    facts = dict(state.facts if isinstance(state.facts, dict) else {})
    done = [item for item in (facts.get(FACT_KEY) if isinstance(facts.get(FACT_KEY), list) else []) if item]
    if unit.reference and unit.reference not in done:
        done.append(unit.reference)
    facts[FACT_KEY] = done[-20:]
    LeadAiChatState.objects.filter(pk=state.pk).update(facts=facts)
    state.facts = facts


def queue(conversation, state, unit, turn_id, language: str = "en") -> bool:
    """Queue the unit's photos after the turn's commit, unless this chat had them already. Whether queued."""
    if unit is None or not unit.photos or sent_before(state, unit):
        return False
    from .tasks import send_pack_photos

    remember(state, unit)
    transaction.on_commit(lambda pk=conversation.pk, uid=unit.pk, tid=turn_id, lang=language: send_pack_photos.delay(pk, uid, tid, lang))
    return True


def _download(client: httpx.Client, url: str) -> tuple[bytes, str] | None:
    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - one photo lost, the rest go
        logger.info("Lead AI pack photo not downloaded (%s): %s", url[:80], str(exc)[:100])
        return None
    data = response.content
    mime = str(response.headers.get("content-type") or "").split(";")[0].strip().lower() or "image/jpeg"
    if not mime.startswith("image/") or not data or len(data) > PHOTO_MAX_BYTES:
        return None
    return data, mime


def _asset(data: bytes, mime: str, name: str):
    from apps.inbox.models import MediaAsset

    asset = MediaAsset(mime_type=mime, file_name=name, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), downloaded=True)
    asset.file.save(name, ContentFile(data), save=False)
    asset.save()
    return asset


def send_one(conversation, unit, data: bytes, mime: str, name: str, caption: str, turn_id) -> bool:
    """One photo: the attachment, the gateway upload for this number, the message row, the send. Whether it went."""
    from apps.gateway.client import AlotsClient, AlotsError
    from apps.inbox import services as inbox_services
    from apps.inbox.events import publish_message, publish_status
    from apps.inbox.models import Message

    asset = _asset(data, mime, name)
    client = AlotsClient()
    gateway_id = client.upload_media(conversation.number.phone_number_id, io.BytesIO(data), name, mime)
    if not gateway_id:
        logger.info("Lead AI pack photo refused by the gateway upload (%s)", name)
        return False
    message = Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.IMAGE,
        body=caption,
        media=asset,
        payload={"source": SOURCE, "turn": turn_id, "pack_unit": unit.pk, "reference": unit.reference, "media_id": gateway_id, "asset_id": asset.pk, "filename": name, "gateway_kind": "image"},
        status=Message.Status.QUEUED,
    )
    inbox_services._touch(conversation, caption or "[image]", Message.Kind.IMAGE)
    to = inbox_services.format_recipient_for_gateway(conversation.contact.wa_id)
    try:
        response = client.send_media(conversation.number.phone_number_id, to, "image", gateway_id, caption=caption)
    except AlotsError as exc:
        message.status = Message.Status.FAILED
        message.error_detail = str(exc)[:2000]
        message.save(update_fields=["status", "error_detail"])
        publish_status(message)
        return False
    inbox_services._record_result(message, response, intended_to=conversation.contact.wa_id)
    publish_message(message)
    return True


def send_photos(conversation_id: int, unit_id: int, turn_id=None, language: str = "en") -> dict:
    """The task's body: the unit's first photos to the chat, the reference as the first caption. Counts and why it stopped."""
    from apps.inbox.models import Conversation

    from . import shop_media, unit_media
    from .models import LeadAiUnit

    out = {"sent": 0, "skipped": 0, "stopped": ""}
    conversation = Conversation.objects.select_related("contact", "number").filter(pk=conversation_id).first()
    unit = LeadAiUnit.objects.filter(pk=unit_id).first()
    if conversation is None or unit is None or not unit.photos:
        out["stopped"] = "no such chat or unit, or no photos"
        return out
    why = shop_media._still_ours(conversation) or ("a person was asked for" if unit_media.handed_over_since(conversation, turn_id) else "")
    if why:
        out["stopped"] = why
        return out
    if not conversation.is_session_open:
        out["stopped"] = "the 24-hour window is closed"
        return out
    urls = [str(url) for url in unit.photos if str(url).startswith("https://")][:PHOTOS_SENT]
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": "A7-LeadAI/1.0"}) as client:
        for index, url in enumerate(urls):
            got = _download(client, url)
            if got is None:
                out["skipped"] += 1
                continue
            data, mime = got
            extension = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
            name = f"{unit.reference or unit.source_id}-{index + 1}.{extension}"
            caption = f"{unit.reference}: {unit.title}"[:200] if index == 0 and unit.reference else ""
            try:
                if send_one(conversation, unit, data, mime, name, caption, turn_id):
                    out["sent"] += 1
                else:
                    out["skipped"] += 1
            except Exception as exc:  # noqa: BLE001 - the next photo still goes
                logger.warning("Lead AI pack photo %s failed for conversation %s: %s", name, conversation_id, exc)
                out["skipped"] += 1
            time.sleep(SEND_PAUSE)
    if out["sent"]:
        from .tasks import record_crm_note

        note = [f"Sent {out['sent']} photo{'s' if out['sent'] != 1 else ''} of {unit.reference or unit.source_id} ({unit.title[:80]}) from Property Finder.", f"At {timezone.now():%d %b %Y %H:%M} UTC."]
        transaction.on_commit(lambda pk=conversation.pk, lines=note: record_crm_note.delay(pk, "photos sent", lines))
    return out
