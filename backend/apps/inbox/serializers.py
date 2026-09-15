"""Shared JSON shapes.

Kept apart from views so the WebSocket layer can send the same objects the REST
layer does — the panel then renders a pushed message without a round trip, and
there is only one definition of what a message looks like.
"""

from django.urls import reverse


def _iso(value):
    """Timestamps go out as ISO strings, never as datetime objects.

    The channel layer packs payloads with msgpack, which cannot encode a
    datetime — leaving them native made every WebSocket push fail while the
    REST responses looked fine, so the panel silently fell back to polling.
    """
    return value.isoformat() if value else None


def _message_body(message):
    """Text the panel should show — fills gaps on older button replies."""
    text = (message.body or "").strip()
    if text and text not in ("[button]", "[interactive]"):
        return message.body

    payload = message.payload or {}
    if message.kind == "button":
        label = (payload.get("button") or {}).get("text", "")
        if label:
            return label
    if message.kind == "interactive":
        interactive = payload.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        label = reply.get("title", "")
        if label:
            return label
    return message.body or ""


def _contact_cards(message):
    """Name + phones from a Meta contacts payload — panel must not parse raw JSON."""
    if message.kind != "contacts":
        return None
    cards = []
    for card in (message.payload or {}).get("contacts") or []:
        if not isinstance(card, dict):
            continue
        name = card.get("name") if isinstance(card.get("name"), dict) else {}
        formatted = (
            name.get("formatted_name")
            or " ".join(part for part in (name.get("first_name"), name.get("last_name")) if part)
            or ""
        )
        phones = []
        for phone in card.get("phones") or []:
            if not isinstance(phone, dict):
                continue
            value = str(phone.get("phone") or phone.get("wa_id") or "").strip()
            if value:
                phones.append(value)
        if formatted or phones:
            cards.append({"name": formatted, "phones": phones})
    return cards


def _album_count(message):
    if message.kind != "album":
        return None
    items = (message.payload or {}).get("album") or (message.payload or {}).get("images") or []
    if isinstance(items, dict):
        items = items.get("images") or items.get("media") or items.get("message_products") or []
    return len(items) if isinstance(items, list) else 0


def _pinned_preview(message):
    """Pinned-message card: our stored preview if the wamid is here, else payload text."""
    if message.kind != "pinned_message":
        return None
    payload = message.payload or {}
    pinned = payload.get("pinned_message") if isinstance(payload.get("pinned_message"), dict) else {}
    wamid = str(pinned.get("id") or pinned.get("message_id") or payload.get("message_id") or "")
    text = pinned.get("text") if isinstance(pinned.get("text"), dict) else {}
    body = (text.get("body") or "").strip()
    if wamid:
        from apps.inbox.models import Message

        found = Message.objects.filter(wamid=wamid).values_list("body", "kind").first()
        if found:
            found_body, found_kind = found
            return {"wamid": wamid, "body": (found_body or "").strip()[:120], "kind": found_kind}
    if body:
        return {"wamid": wamid, "body": body[:120], "kind": pinned.get("type") or "text"}
    return {"wamid": wamid, "body": "", "kind": "pinned_message"}


def _template_buttons(message):
    if not message.template_id:
        return []
    return [
        {"text": b.get("text", ""), "type": b.get("type", "")}
        for b in message.template.buttons
    ]


def serialize_agent(agent):
    if not agent:
        return None
    return {
        "id": agent.pk,
        "display_name": agent.display_name or agent.get_username(),
        "community": getattr(agent, "community", "") or "",
        "avatar_url": agent.avatar_url,
    }


def _webhook_url_for_number():
    """Inbound alots webhook on this panel — same URL for every Official number."""
    from django.conf import settings

    base = getattr(settings, "PANEL_BASE_URL", "").rstrip("/")
    if not base:
        return ""
    return f"{base}/api/gateway/webhook/alots/"


def serialize_number(number):
    if isinstance(number, dict):
        return number
    title = getattr(number, "title", None)
    if not title:
        label = getattr(number, "label", "")
        display_name = getattr(number, "display_name", "")
        phone_number = getattr(number, "phone_number", "")
        title = label or display_name or phone_number
    return {
        "id": getattr(number, "pk", getattr(number, "id", None)),
        "phone_number": getattr(number, "phone_number", ""),
        "phone_number_id": getattr(number, "phone_number_id", ""),
        "waba_business_id": getattr(number, "waba_business_id", ""),
        "label": getattr(number, "label", ""),
        "community": getattr(number, "community", "") or "",
        "account_username": getattr(number, "account_username", "") or "",
        "template_sync_error": getattr(number, "template_sync_error", "") or "",
        "display_name": getattr(number, "display_name", ""),
        "title": title,
        "quality_rating": getattr(number, "quality_rating", ""),
        "verification_status": getattr(number, "verification_status", ""),
        "webhook_configured": getattr(number, "webhook_configured", False),
        "source": getattr(number, "source", "") or "sync",
        "webhook_url": _webhook_url_for_number(),
    }


def serialize_contact(contact):
    return {
        "wa_id": contact.wa_id,
        "name": str(contact),
        "profile_name": contact.profile_name,
    }


def serialize_conversation(conversation):
    peer = getattr(conversation, "linked_conversation", None)
    return {
        "id": conversation.pk,
        "number_id": conversation.number_id,
        "contact": serialize_contact(conversation.contact),
        "assigned_agent": serialize_agent(conversation.assigned_agent),
        "status": conversation.status,
        "last_message_at": _iso(conversation.last_message_at),
        "last_message_preview": conversation.last_message_preview,
        "last_message_kind": conversation.last_message_kind,
        "unread_count": conversation.unread_count,
        "session_expires_at": _iso(conversation.session_expires_at),
        "is_session_open": conversation.is_session_open,
        "is_pinned": conversation.is_pinned,
        "is_archived": conversation.is_archived,
        "is_transferred": bool(getattr(conversation, "linked_conversation_id", None)),
        "linked_conversation_id": getattr(conversation, "linked_conversation_id", None),
        "labels": [
            {"id": l.pk, "name": l.name, "colour": l.colour} for l in conversation.labels.all()
        ],
        # Display only. Transfer does not put this number on the agent's roster.
        "number": serialize_number(conversation.number) if conversation.number_id else None,
        "linked_number": serialize_number(peer.number) if peer is not None and peer.number_id else None,
    }


def serialize_message(message, request=None):
    # Attachments go through an authenticated view rather than a public path.
    # The panel is same-origin with the API, so the session cookie rides along
    # on a plain <img src> and no signed URL is needed.
    media_url = ""
    if message.media_id:
        media_url = reverse("inbox:media-download", args=[message.media_id])
        if request:
            media_url = request.build_absolute_uri(media_url)

    return {
        "id": message.pk,
        "conversation_id": message.conversation_id,
        "direction": message.direction,
        "kind": message.kind,
        "body": _message_body(message),
        "media_url": media_url,
        "media_name": message.media.file_name if message.media else "",
        "media_mime": message.media.mime_type if message.media else "",
        "media_size": message.media.size_bytes if message.media else 0,
        "media_ready": bool(message.media and message.media.downloaded),
        # Lets the panel stop showing "loading" and say so instead.
        "media_failed": bool(message.media and not message.media.downloaded and message.media.download_error),
        "template_name": message.template.name if message.template else "",
        "template_footer": message.template.footer_text if message.template else "",
        "template_buttons": _template_buttons(message),
        "status": message.status,
        "error_code": message.error_code,
        "error_detail": message.error_detail,
        "created_at": _iso(message.created_at),
        "delivered_at": _iso(message.delivered_at),
        "read_at": _iso(message.read_at),
        "sent_by": serialize_agent(message.sent_by),
        # {wa_id: emoji}. Drawn on the bubble, not as a message of its own.
        "reactions": message.reactions or {},
        "is_starred": message.is_starred,
        # Both directions store the pin under the same key, so one shape serves.
        "location": (message.payload or {}).get("location") if message.kind == "location" else None,
        "contacts": _contact_cards(message),
        "album_count": _album_count(message),
        "pinned": _pinned_preview(message),
        # WhatsApp prints a "Forwarded" tag; this is what earns it.
        "is_forwarded": bool(message.payload.get("forwarded_from")),
        "is_panel_copy": bool(message.mirrored_from_id or (message.payload or {}).get("panel_copy")),
        # Enough of the quoted message to draw the little bar above a reply,
        # without pulling its whole record along.
        "reply_to": (
            {
                "id": message.reply_to_id,
                "direction": message.reply_to.direction,
                "kind": message.reply_to.kind,
                "body": _message_body(message.reply_to)[:120],
                # WhatsApp names whoever wrote the quoted line, and without it
                # two similar replies in a busy thread are impossible to tell
                # apart. The customer for anything inbound; for our own side the
                # agent who sent it, which is not always the one replying now.
                "sender": (
                    str(message.conversation.contact)
                    if message.reply_to.direction == "in"
                    else (
                        message.reply_to.sent_by.display_name
                        or message.reply_to.sent_by.get_username()
                    )
                    if message.reply_to.sent_by
                    else "You"
                ),
            }
            if message.reply_to_id
            else None
        ),
    }


def serialize_reminder(reminder):
    return {
        "id": reminder.pk,
        "due_at": _iso(reminder.due_at),
        "note": reminder.note,
        "is_done": reminder.is_done,
        "fired_at": _iso(reminder.fired_at),
        "conversation": serialize_conversation(reminder.conversation),
    }


def serialize_quick_reply(reply):
    return {
        "id": reply.pk,
        "shortcut": reply.shortcut,
        "body": reply.body,
        "is_shared": reply.owner_id is None,
    }


def serialize_shared_asset(asset, request=None):
    # Through the authenticated view, never MEDIA_URL: nothing serves /media/,
    # so asset.file.url was a link to a 404.
    url = reverse("inbox:shared-asset-download", args=[asset.pk]) if asset.file else ""
    if request and url:
        url = request.build_absolute_uri(url)
    return {
        "id": asset.pk,
        "title": asset.title,
        "kind": asset.kind,
        "url": url,
        "file_name": asset.file_name,
        "size_bytes": asset.size_bytes,
        "mime_type": asset.mime_type,
        "created_by": serialize_agent(asset.created_by),
        "created_at": _iso(asset.created_at),
    }
