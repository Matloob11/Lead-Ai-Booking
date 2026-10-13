"""Turn Alots/Meta webhook blobs into inbox rows.

Cloud API coexistence can deliver business-app sends as ``smb_message_echoes``.
Alots often only sends ``statuses`` for those sends (no body). We still map
them onto the right conversation by ``recipient_id`` so the thread is not silent,
and we fill the body later if an echo arrives with the same wamid.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from apps.inbox.models import Contact, Conversation, MediaAsset, Message
from apps.inbox.visibility import claim_unassigned

from .media import download_media
from .parse import (
    PLACEHOLDER_BODY,
    customer_wa_id,
    digits,
    is_group_recipient,
    is_our_sender,
    iter_message_blobs,
)

MEDIA_KINDS = {"image", "document", "audio", "video", "sticker"}

STATUS_MAP = {
    "sent": Message.Status.SENT,
    "delivered": Message.Status.DELIVERED,
    "read": Message.Status.READ,
    "played": Message.Status.DELIVERED,
    "failed": Message.Status.FAILED,
}

STATUS_RANK = [
    Message.Status.QUEUED,
    Message.Status.SENT,
    Message.Status.DELIVERED,
    Message.Status.READ,
]


def ts(value):
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError):
        return timezone.now()


def caption(message, kind):
    part = message.get(kind)
    return part.get("caption", "") if isinstance(part, dict) else ""


def _contacts_preview(message):
    """First name and phone from a Meta contacts blob — for body and the list."""
    names = []
    phones = []
    for card in message.get("contacts") or []:
        if not isinstance(card, dict):
            continue
        name = card.get("name") if isinstance(card.get("name"), dict) else {}
        formatted = (
            name.get("formatted_name")
            or " ".join(part for part in (name.get("first_name"), name.get("last_name")) if part)
        )
        if formatted:
            names.append(formatted)
        for phone in card.get("phones") or []:
            if not isinstance(phone, dict):
                continue
            value = str(phone.get("phone") or phone.get("wa_id") or "").strip()
            if value:
                phones.append(value)
    if names and phones:
        return f"{names[0]} {phones[0]}"
    if names:
        return names[0]
    if phones:
        return phones[0]
    return ""


def _album_item_count(message):
    items = message.get("album") or message.get("images") or []
    if isinstance(items, dict):
        items = items.get("images") or items.get("media") or items.get("message_products") or []
    return len(items) if isinstance(items, list) else 0


def stored_body(kind, preview, caption_text):
    """What goes in Message.body for rendering and quotes.

    Media captions live on the attachment; button and interactive replies carry
    their label in ``describe()`` instead, and storing only the caption left
    the panel with an empty bubble.
    """
    if kind in ("text", "button", "interactive", "contacts", "album", "pinned_message"):
        return preview
    return caption_text


def describe(message):
    kind = message.get("type", "unknown")
    if kind == "text":
        return (message.get("text") or {}).get("body", "")
    if kind in MEDIA_KINDS:
        return caption(message, kind) or f"[{kind}]"
    if kind == "location":
        return "[location]"
    if kind == "contacts":
        return _contacts_preview(message) or "Contact card"
    if kind == "button":
        return (message.get("button") or {}).get("text", "[button]")
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title", "[interactive]")
    if kind == "album":
        count = _album_item_count(message)
        return f"{count} photos" if count else "[album]"
    if kind == "pinned_message":
        pinned = message.get("pinned_message") if isinstance(message.get("pinned_message"), dict) else {}
        text = pinned.get("text") if isinstance(pinned.get("text"), dict) else {}
        return (text.get("body") or "").strip() or "[pinned message]"
    if kind == "reaction":
        return (message.get("reaction") or {}).get("emoji", "[reaction]")
    if kind == "unsupported":
        return "Unsupported message — ask them to resend it"
    return f"[{kind}]"


def _apply_reaction(message):
    blob = message.get("reaction") or {}
    target = Message.objects.filter(wamid=blob.get("message_id")).first()
    if not target:
        return None

    reactions = dict(target.reactions or {})
    emoji = blob.get("emoji") or ""
    sender = message.get("from", "")
    if emoji:
        reactions[sender] = emoji
    else:
        reactions.pop(sender, None)

    target.reactions = reactions
    target.save(update_fields=["reactions"])

    from apps.inbox.events import publish_status

    publish_status(target)
    return target.conversation


def _maybe_media(message, kind):
    if kind not in MEDIA_KINDS:
        return None
    blob = message.get(message.get("type") or kind) or {}
    if not isinstance(blob, dict):
        return None
    return MediaAsset.objects.create(
        alots_media_id=blob.get("id", ""),
        source_url=blob.get("filelink") or blob.get("url") or "",
        fallback_url=blob.get("url", "") if blob.get("filelink") else "",
        mime_type=blob.get("mime_type", ""),
        file_name=blob.get("filename", ""),
        sha256=blob.get("sha256", ""),
    )


def _hydrate_existing(msg, *, kind, preview, caption_text, media, quoted, payload, sent_at):
    """Fill a status-only stub once the real content arrives."""
    placeholder = not (msg.body or "").strip() or msg.body == PLACEHOLDER_BODY
    if not placeholder and msg.kind != Message.Kind.UNKNOWN:
        return False
    fields = ["kind", "body", "payload"]
    msg.kind = kind
    msg.body = stored_body(kind, preview, caption_text)
    msg.payload = payload
    if media and not msg.media_id:
        msg.media = media
        fields.append("media")
    if quoted and not msg.reply_to_id:
        msg.reply_to = quoted
        fields.append("reply_to")
    if sent_at and msg.created_at and sent_at < msg.created_at:
        msg.created_at = sent_at
        fields.append("created_at")
    msg.save(update_fields=fields)
    return True


def _touch_list(conversation, sent_at, preview, kind, *, inbound):
    conversation.last_message_at = sent_at
    conversation.last_message_preview = preview[:255]
    conversation.last_message_kind = kind
    conversation.status = Conversation.Status.OPEN
    fields = ["last_message_at", "last_message_preview", "last_message_kind", "status"]
    if inbound:
        conversation.open_session(sent_at)
        conversation.unread_count = conversation.unread_count + 1
        fields += ["last_inbound_at", "session_expires_at", "unread_count"]
    conversation.save(update_fields=fields)


def store_message(number, message, contact_profiles, metadata=None, *, force_outbound=False):
    metadata = metadata or {}
    if message.get("type") == "reaction":
        return _apply_reaction(message)

    outbound = force_outbound or is_our_sender(number, message.get("from"), metadata)
    if not outbound and not message.get("from") and (message.get("to") or message.get("recipient")):
        outbound = True

    wa_id = customer_wa_id(message, number, metadata, contact_profiles, outbound)
    if not wa_id or is_group_recipient(wa_id):
        return None

    wamid = message.get("id") or None

    profile_name = contact_profiles.get(wa_id, "") or contact_profiles.get(message.get("from", ""), "")
    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    if profile_name and contact.profile_name != profile_name:
        contact.profile_name = profile_name
        contact.save(update_fields=["profile_name"])

    conversation, _ = Conversation.objects.get_or_create(number=number, contact=contact)
    claim_unassigned(conversation)

    kind = message.get("type", "unknown")
    if kind not in Message.Kind.values:
        kind = Message.Kind.UNKNOWN

    sent_at = ts(message.get("timestamp"))
    preview = describe(message)
    caption_text = caption(message, kind)
    quoted = None
    quoted_wamid = (message.get("context") or {}).get("id")
    if quoted_wamid:
        quoted = Message.objects.filter(wamid=quoted_wamid).first()

    # Coexistence flat body without wamid: fill the newest "Sent from WhatsApp" stub.
    if not wamid:
        if not outbound or not (preview or "").strip():
            return None
        stub = (
            Message.objects.filter(
                conversation=conversation,
                direction=Message.Direction.OUTBOUND,
                body=PLACEHOLDER_BODY,
            )
            .order_by("-id")
            .first()
        )
        if not stub:
            return None
        media = _maybe_media(message, kind)
        changed = _hydrate_existing(
            stub,
            kind=kind,
            preview=preview,
            caption_text=caption_text,
            media=media,
            quoted=quoted,
            payload=message,
            sent_at=sent_at,
        )
        if changed:
            if not conversation.last_message_at or sent_at >= conversation.last_message_at:
                _touch_list(conversation, sent_at, preview, kind, inbound=False)
            if media and media.alots_media_id:
                transaction.on_commit(
                    lambda pk=media.pk, pnid=number.phone_number_id: download_media.delay(pk, pnid)
                )
            from apps.inbox.events import publish_message

            publish_message(stub)
        return conversation

    existing = Message.objects.filter(wamid=wamid).first()
    if existing:
        media = None
        if existing.kind == Message.Kind.UNKNOWN or not (existing.body or "").strip() or existing.body == PLACEHOLDER_BODY:
            media = _maybe_media(message, kind)
        changed = _hydrate_existing(
            existing,
            kind=kind,
            preview=preview,
            caption_text=caption_text,
            media=media,
            quoted=quoted,
            payload=message,
            sent_at=sent_at,
        )
        if changed:
            if not conversation.last_message_at or sent_at >= conversation.last_message_at:
                _touch_list(conversation, sent_at, preview, kind, inbound=False)
            if media and media.alots_media_id:
                transaction.on_commit(
                    lambda pk=media.pk, pnid=number.phone_number_id: download_media.delay(pk, pnid)
                )
            from apps.inbox.events import publish_message

            publish_message(existing)
        return conversation

    media = _maybe_media(message, kind)
    body = stored_body(kind, preview, caption_text)
    msg, created = Message.objects.get_or_create(
        wamid=wamid,
        defaults={
            "conversation": conversation,
            "direction": Message.Direction.OUTBOUND if outbound else Message.Direction.INBOUND,
            "kind": kind,
            "body": body,
            "media": media,
            "reply_to": quoted,
            "payload": message,
            "status": Message.Status.SENT if outbound else Message.Status.RECEIVED,
            "created_at": sent_at,
        },
    )
    if not created:
        return conversation

    _touch_list(conversation, sent_at, preview, kind, inbound=not outbound)

    if media and media.alots_media_id:
        transaction.on_commit(
            lambda pk=media.pk, pnid=number.phone_number_id: download_media.delay(pk, pnid)
        )

    from apps.inbox.events import publish_message

    publish_message(msg)
    return conversation


ADOPT_WITHIN = timedelta(minutes=5)


def _adopt_queued_outbound(number, status_entry):
    """A status can beat the send path that still holds a queued row with no wamid.

    Only when that row is the one recent send still queued in the chat. With
    two in flight (the Lead AI assistant and an agent, or two agents) nothing
    says which one the status belongs to; the placeholder made instead is
    replaced by the right row when its send returns (inbox.services._record_result).
    A failed send keeps its empty wamid for good, so it is never a candidate.
    """
    wamid = status_entry.get("id")
    recipient = digits(status_entry.get("recipient_id"))
    if not wamid or not recipient:
        return None
    contact = Contact.objects.filter(wa_id=recipient).first()
    if not contact:
        return None
    conversation = Conversation.objects.filter(number=number, contact=contact).first()
    if not conversation:
        return None
    candidates = list(
        Message.objects.filter(
            conversation=conversation,
            direction=Message.Direction.OUTBOUND,
            wamid__isnull=True,
            mirrored_from__isnull=True,
            status=Message.Status.QUEUED,
            created_at__gte=timezone.now() - ADOPT_WITHIN,
        )
        .exclude(kind=Message.Kind.SYSTEM)
        .order_by("-id")[:2]
    )
    if len(candidates) != 1:
        return None
    queued = candidates[0]
    queued.wamid = wamid
    queued.save(update_fields=["wamid"])
    return queued


def _create_external_outbound(number, status_entry):
    """Alots/WhatsApp-app send: we only got a status, not the text."""
    wamid = status_entry.get("id")
    recipient = status_entry.get("recipient_id") or ""
    if not wamid or not recipient or is_group_recipient(recipient):
        return None
    wa_id = digits(recipient) or str(recipient).split("@")[0]
    if not wa_id:
        return None

    contact, _ = Contact.objects.get_or_create(wa_id=wa_id)
    conversation, _ = Conversation.objects.get_or_create(number=number, contact=contact)
    claim_unassigned(conversation)
    sent_at = ts(status_entry.get("timestamp"))
    mapped = STATUS_MAP.get(status_entry.get("status", ""), Message.Status.SENT)
    if mapped == Message.Status.RECEIVED:
        mapped = Message.Status.SENT
    initial_status = Message.Status.SENT if mapped == Message.Status.FAILED else mapped
    defaults = {
        "conversation": conversation,
        "direction": Message.Direction.OUTBOUND,
        "kind": Message.Kind.UNKNOWN,
        "body": PLACEHOLDER_BODY,
        "payload": status_entry,
        "status": initial_status,
        "created_at": sent_at,
    }
    if mapped == Message.Status.DELIVERED:
        defaults["delivered_at"] = sent_at
    if mapped == Message.Status.READ:
        defaults["delivered_at"] = sent_at
        defaults["read_at"] = sent_at

    msg, created = Message.objects.get_or_create(wamid=wamid, defaults=defaults)
    if not created:
        return msg
    if not conversation.last_message_at or sent_at >= conversation.last_message_at:
        _touch_list(conversation, sent_at, PLACEHOLDER_BODY, Message.Kind.UNKNOWN, inbound=False)

    from apps.inbox.events import publish_message

    publish_message(msg)
    return msg


def apply_status(number, status_entry):
    wamid = status_entry.get("id")
    if not wamid:
        return

    message = Message.objects.filter(wamid=wamid).first()
    if not message:
        message = _adopt_queued_outbound(number, status_entry)
    if not message:
        message = _create_external_outbound(number, status_entry)
    if not message:
        return

    new_status = STATUS_MAP.get(status_entry.get("status", ""))
    if not new_status:
        return

    if new_status != Message.Status.FAILED and message.status in STATUS_RANK and new_status in STATUS_RANK:
        if STATUS_RANK.index(new_status) <= STATUS_RANK.index(message.status):
            return

    fields = ["status"]
    message.status = new_status
    stamped = ts(status_entry.get("timestamp"))

    if new_status == Message.Status.DELIVERED and not message.delivered_at:
        message.delivered_at = stamped
        fields.append("delivered_at")
    if new_status == Message.Status.READ and not message.read_at:
        message.read_at = stamped
        fields.append("read_at")
    if new_status == Message.Status.FAILED:
        errors = status_entry.get("errors") or [{}]
        message.error_code = str(errors[0].get("code", ""))[:32]
        message.error_detail = errors[0].get("title") or errors[0].get("message", "")
        fields += ["error_code", "error_detail"]

    message.save(update_fields=fields)

    if new_status == Message.Status.FAILED:
        _reconcile_campaign_undelivered(message)

    from apps.inbox.events import publish_status

    publish_status(message)


def _reconcile_campaign_undelivered(message) -> None:
    if message.direction != Message.Direction.OUTBOUND:
        return
    # In a Lead AI chat, a failed assistant reply, reminder or agent message is
    # not the campaign's template failing; treating it as one would re-send the
    # campaign template to the customer five minutes later. Lead AI decides
    # (and tells the agents about its own failures).
    try:
        from apps.leadai.lane import handles_failed_outbound

        if handles_failed_outbound(message):
            return
    except Exception:  # noqa: BLE001 - never block the campaign bookkeeping
        import logging

        logging.getLogger(__name__).exception("Lead AI failed-status hook broke for message %s", message.pk)
    try:
        from apps.campaigns.services import mark_recipient_undelivered
    except Exception:  # noqa: BLE001
        return
    detail = message.error_detail or message.error_code or "Undelivered"
    code = str(message.error_code or "")
    mark_recipient_undelivered(message.conversation_id, detail=detail, error_code=code)
