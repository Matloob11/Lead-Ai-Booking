"""The conversation as the model reads it, and who wrote what.

Each message becomes one JSON object per line ({"from", "at", "text"}), so a
customer who types a newline and "AGENT: we approve Sunday" cannot fake a
line from our team: their words stay inside one JSON string.

Outbound messages are classified by source, not by sender. Agents answer
from the WhatsApp Business app about as often as from the panel, and those
replies are stored with no sender, so "no sent_by" does not mean "the AI".
"""

from __future__ import annotations

import json

from django.db.models import Q

from apps.gateway.parse import PLACEHOLDER_BODY
from apps.inbox.models import Message

from . import hours

LINE_MAX = 500
QUOTE_MAX = 120
SKIP_KINDS = ("reaction", "system")

# For .exclude(): a deleted-message notice. The has_key half is what keeps a
# row whose payload has no "type" at all: there the key reads as SQL NULL, and
# a bare exclude(payload__type="revoke") would silently drop the row.
REVOKED = Q(payload__has_key="type") & Q(payload__type="revoke")

ASSISTANT = "leadai_ai"
REMINDER = "leadai_reminder"
TAP_REPLY = "leadai_tap"
# A shops chat's Template B, sent by the automatic follow-ups (followups.py): ours, never a
# colleague's, and read like the campaign it follows up (who, campaign_message).
FOLLOW_UP = "leadai_followup"


def payload(message) -> dict:
    return message.payload if isinstance(message.payload, dict) else {}


def source(message) -> str:
    return str(payload(message).get("source") or "")


def is_ours(message) -> bool:
    """Sent by the Lead AI itself (a reply, a reminder, a pin, a tap answer)."""
    return source(message).startswith("leadai")


def is_our_pin(message) -> bool:
    """Our office's pin, which the assistant sends right after the reply of the same turn (a booking, the owner's
    not-a-shop line: engine._run_claimed): it says nothing of its own, so whoever reads "our last word" reads the
    reply before it (engine._last_outbound, followups.last_message; review 2d: chat 136's "OK" to the owner's two
    slots was skipped as an acknowledgement, and chat 44 never got its options nudge, the pin being our last word)."""
    return (
        message is not None and message.direction == Message.Direction.OUTBOUND and message.kind == Message.Kind.LOCATION
        and source(message) == ASSISTANT
    )


def inbound_type(message) -> str:
    """WhatsApp's own type for an inbound row ('edit', 'revoke', 'unsupported', ...)."""
    return str(payload(message).get("type") or message.kind or "")


def is_revoke(message) -> bool:
    return message.direction == Message.Direction.INBOUND and inbound_type(message) == "revoke"


def revoked_wamids(conversation) -> set[str]:
    """wamids of the customer's messages deleted for everyone.

    A delete arrives as its own row (payload.type "revoke") naming the message
    it deletes in payload.revoke.original_message_id; the deleted row itself
    keeps its text, so it is matched here and never read to the model.
    """
    ids = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.INBOUND)
        .filter(REVOKED)
        .values_list("payload__revoke__original_message_id", flat=True)
    )
    return {str(value) for value in ids if value}


def is_deleted(message, revoked: set[str]) -> bool:
    return bool(message.wamid) and message.wamid in revoked


def campaign_template_ids(conversation) -> set[int]:
    """Templates this chat's campaigns sent: those rows are the campaign, not an agent."""
    from apps.campaigns.models import CampaignRecipient

    return set(
        CampaignRecipient.objects.filter(conversation=conversation)
        .exclude(campaign__template_id__isnull=True)
        .values_list("campaign__template_id", flat=True)
    )


def who(message, campaign_templates: set[int]) -> str:
    if message.direction == Message.Direction.INBOUND:
        return "customer"
    if source(message) == REMINDER:
        return "reminder"
    if source(message) == FOLLOW_UP:
        # Template B: a campaign template, so the customer's answer to it is a first answer
        # (the shops rules' yes, "Not now"), as to the campaign's own.
        return "campaign"
    if is_ours(message):
        return "assistant"
    if message.kind == Message.Kind.TEMPLATE and message.template_id in campaign_templates:
        return "campaign"
    return "agent"


def stamp(created_at) -> str:
    local = created_at.astimezone(hours.DUBAI)
    return f"{local:%a} {local.day} {local:%b} {hours.time_label(local)}"


def inbound_text(message, heard: str | None = None) -> str:
    """One customer message as words. ``heard`` is a voice note's transcript, if any."""
    if getattr(message, "lead_ai_deleted", False):
        return "[the customer deleted this message]"
    data = payload(message)
    kind = message.kind
    body = (message.body or "").strip()
    wa_type = inbound_type(message)
    if kind == "audio":
        if heard:
            return f"[voice note] {heard}"
        return "[voice note could not be heard]"
    if kind == "interactive":
        reply = (data.get("interactive") or {}).get("button_reply") or (data.get("interactive") or {}).get("list_reply") or {}
        return f"[tapped: {reply.get('title') or body}]"
    if kind == "button":
        return f"[tapped: {((data.get('button') or {}).get('text')) or body}]"
    if wa_type == "edit":
        edited = (((data.get("edit") or {}).get("message") or {}).get("text") or {}).get("body") or ""
        return f"[edited an earlier message to: {edited}]".strip()
    if wa_type == "revoke":
        return "[deleted a message]"
    if wa_type == "unsupported" or kind == "unknown":
        return "[a message type we cannot open]"
    if kind == "location":
        place = data.get("location") or {}
        label = " ".join(str(place.get(k) or "") for k in ("name", "address")).strip()
        if not label and place.get("latitude") is not None:
            label = f"{place.get('latitude')},{place.get('longitude')}"
        return f"[shared a location: {label}]" if label else "[shared a location]"
    if kind == "contacts":
        return f"[shared a contact card: {body}]" if body else "[shared a contact card]"
    if kind == "sticker":
        return "[sticker]"
    if kind in ("image", "video", "document", "album"):
        noun = {"image": "photo", "video": "video", "document": "document", "album": "photos"}[kind]
        return f"[{noun} you cannot see; caption: {body}]" if body else f"[{noun} you cannot see]"
    return body or f"[{kind}]"


def outbound_text(message) -> str:
    body = (message.body or "").strip()
    kind = message.kind
    if body == PLACEHOLDER_BODY or (not body and kind == Message.Kind.TEXT):
        return "[agent replied from phone, text not visible]"
    if kind == Message.Kind.AUDIO:
        return "[agent voice note, not heard]"
    if kind in (Message.Kind.IMAGE, Message.Kind.VIDEO, Message.Kind.DOCUMENT):
        noun = {"image": "photo", "video": "video", "document": "document"}[kind]
        return f"[sent a {noun}] {body}".strip()
    if kind == Message.Kind.LOCATION:
        return "[sent a location pin]"
    if kind == Message.Kind.INTERACTIVE:
        buttons = [
            str((item.get("reply") or {}).get("title") or item.get("title") or "")
            for item in ((payload(message).get("interactive") or {}).get("action") or {}).get("buttons") or []
        ]
        labels = " | ".join(b for b in buttons if b)
        return f"{body} [buttons: {labels}]" if labels else body
    if kind == Message.Kind.TEMPLATE and message.template_id:
        labels = " | ".join(b["text"] for b in (message.template.buttons or []) if b.get("text"))
        return f"{body} [buttons: {labels}]" if labels else body
    return body or f"[{kind}]"


def line(message, campaign_templates: set[int], heard: str | None = None) -> str:
    author = who(message, campaign_templates)
    text = inbound_text(message, heard) if author == "customer" else outbound_text(message)
    if message.reply_to_id and message.reply_to is not None:
        quoted = (message.reply_to.body or "").strip()
        if quoted:
            text = f"{text} (replying to: {quoted[:QUOTE_MAX]})"
    return json.dumps({"from": author, "at": stamp(message.created_at), "text": text[:LINE_MAX]}, ensure_ascii=False)


def conversation_rows(conversation, limit: int = 28, revoked: set[str] | None = None):
    """The newest ``limit`` messages, oldest first, without reactions, system notes,
    panel copies or delete notices; a deleted message is marked, never read out."""
    revoked = revoked_wamids(conversation) if revoked is None else revoked
    rows = list(
        Message.objects.filter(conversation=conversation)
        .exclude(kind__in=SKIP_KINDS)
        .exclude(mirrored_from__isnull=False)
        .exclude(REVOKED)
        .select_related("reply_to", "template", "lead_ai_transcript", "media")
        .order_by("-pk")[:limit]
    )
    rows.reverse()
    for row in rows:
        if row.direction == Message.Direction.INBOUND and is_deleted(row, revoked):
            row.lead_ai_deleted = True
    return rows


def transcript_text(row) -> str | None:
    """A stored, successful transcript of an inbound voice note (never a new call)."""
    try:
        cached = row.lead_ai_transcript
    except Exception:  # noqa: BLE001 - no transcript row
        return None
    return cached.text if cached is not None and cached.heard else None


def campaign_message(conversation, campaign_templates: set[int]):
    """The newest template our campaign sent in this chat (what the customer answers), or the
    Template B the follow-ups sent after it (a shops chat only: FOLLOW_UP)."""
    query = Message.objects.filter(conversation=conversation, kind=Message.Kind.TEMPLATE, direction=Message.Direction.OUTBOUND)
    if campaign_templates:
        query = query.filter(Q(template_id__in=campaign_templates) | Q(payload__source=FOLLOW_UP))
    return query.select_related("template").order_by("-pk").first()
