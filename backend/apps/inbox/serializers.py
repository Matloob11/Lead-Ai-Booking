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


def serialize_agent(agent):
    if not agent:
        return None
    return {
        "id": agent.pk,
        "display_name": agent.display_name or agent.get_username(),
        "avatar_url": agent.avatar_url,
    }


def serialize_number(number):
    return {
        "id": number.pk,
        "phone_number": number.phone_number,
        "phone_number_id": number.phone_number_id,
        "waba_business_id": number.waba_business_id,
        "display_name": number.display_name,
        "quality_rating": number.quality_rating,
        "verification_status": number.verification_status,
        "webhook_configured": number.webhook_configured,
    }


def serialize_contact(contact):
    return {
        "wa_id": contact.wa_id,
        "name": str(contact),
        "profile_name": contact.profile_name,
    }


def serialize_conversation(conversation):
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
        "body": message.body,
        "media_url": media_url,
        "media_name": message.media.file_name if message.media else "",
        "media_mime": message.media.mime_type if message.media else "",
        "media_size": message.media.size_bytes if message.media else 0,
        "media_ready": bool(message.media and message.media.downloaded),
        # Lets the panel stop showing "loading" and say so instead.
        "media_failed": bool(message.media and not message.media.downloaded and message.media.download_error),
        "template_name": message.template.name if message.template else "",
        "status": message.status,
        "error_code": message.error_code,
        "error_detail": message.error_detail,
        "created_at": _iso(message.created_at),
        "delivered_at": _iso(message.delivered_at),
        "read_at": _iso(message.read_at),
        "sent_by": serialize_agent(message.sent_by),
    }
