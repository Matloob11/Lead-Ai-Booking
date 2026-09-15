"""Conversation Health for Official chats.

Classify path matches OpenWA (`openai-health.client.ts` + service increment).
Rules live in health_rules.py so they can be unit-tested without Django.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

import httpx
from django.conf import settings
from django.utils import timezone

from apps.inbox.models import Message

from .health_rules import (
    CLASSIFY_MSG_CHARS,
    RECLASSIFY_EVERY_N,
    SYSTEM_PROMPT,
    THREAD_MESSAGES,
    coerce_result,
)
from .models import ConversationHealth

logger = logging.getLogger(__name__)


def openai_ready() -> bool:
    return bool(getattr(settings, "OPENAI_API_KEY", ""))


def classify_thread(agent_name: str, agent_phone: str, client_phone: str, thread: str) -> dict:
    key = getattr(settings, "OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing")
    user = (
        f"CHANNEL: whatsapp\nAGENT: {agent_name} ({agent_phone or 'unknown'})\n"
        f"CLIENT: {client_phone}\nCONVERSATION:\n{thread}"
    )
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        },
        timeout=90,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI classify HTTP {response.status_code}: {response.text[:300]}")
    content = response.json()["choices"][0]["message"]["content"] or "{}"
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        parsed = {}
    return coerce_result(parsed)


def build_thread_text(conversation) -> str:
    messages = list(
        conversation.messages.exclude(kind__in=("reaction", "system"))
        .order_by("-id")[:THREAD_MESSAGES]
    )
    messages.reverse()
    lines = []
    for message in messages:
        who = "CLIENT" if message.direction == Message.Direction.INBOUND else "AGENT"
        body = (message.body or "").strip() or f"[{message.kind}]"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def consider_conversation(conversation, *, force: bool = False) -> ConversationHealth | None:
    """Increment the message window; classify when OpenWA would (first time or every 10)."""
    row, _ = ConversationHealth.objects.get_or_create(conversation=conversation)
    if row.colour_locked:
        return row
    if not force:
        row.message_count_since_classify = (row.message_count_since_classify or 0) + 1
        needs = (not row.colour) or row.message_count_since_classify >= RECLASSIFY_EVERY_N
        if not needs:
            row.save(update_fields=["message_count_since_classify", "updated_at"])
            return row
    if not openai_ready():
        row.save(update_fields=["message_count_since_classify", "updated_at"])
        return row
    thread = build_thread_text(conversation)
    if not thread.strip():
        row.save(update_fields=["message_count_since_classify", "updated_at"])
        return row
    contact = conversation.contact
    number = conversation.number
    agent_name = (
        getattr(conversation.assigned_agent, "display_name", None)
        or getattr(conversation.assigned_agent, "username", None)
        or getattr(number, "label", None)
        or "agent"
    )
    agent_phone = getattr(number, "phone_number", None) or ""
    client_phone = getattr(contact, "wa_id", None) or "unknown"
    result = classify_thread(
        str(agent_name),
        str(agent_phone),
        str(client_phone),
        thread[-CLASSIFY_MSG_CHARS:],
    )
    row.colour = result["category"]
    row.reason = result["reason"][:2000]
    row.flags = result["flags"][:20]
    row.confidence = result["confidence"]
    row.needs_human_review = result["needs_human_review"]
    row.message_count_since_classify = 0
    row.last_classified_at = timezone.now()
    row.save()
    logger.info("inboxai health conversation=%s colour=%s", conversation.pk, row.colour)
    return row


def allow_red_as_green(row: ConversationHealth, password: str) -> ConversationHealth:
    expected = str(getattr(settings, "CONVERSATION_HEALTH_OVERRIDE_PASSWORD", None) or "222007")
    presented = hashlib.sha256(str(password or "").encode()).digest()
    wanted = hashlib.sha256(expected.encode()).digest()
    if not hmac.compare_digest(presented, wanted):
        raise PermissionError("Invalid admin password")
    if row.colour != ConversationHealth.Colour.RED:
        raise ValueError("Only RED chats can be allowed as green")
    row.colour = ConversationHealth.Colour.GREEN
    row.colour_locked = True
    row.reason = "Admin allowed this chat (override). Treated as clean / green."
    row.flags = ["admin_override"]
    row.message_count_since_classify = 0
    row.last_classified_at = timezone.now()
    row.save()
    return row
