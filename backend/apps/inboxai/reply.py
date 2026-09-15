"""One WhatsApp reply from the agent's written instructions + recent thread."""

from __future__ import annotations

import json
import logging

import httpx
from django.conf import settings

from .eligibility import HISTORY_LIMIT, REPLY_MAX, reply_language

logger = logging.getLogger(__name__)

PROMPT = """You cover WhatsApp for A7 Group Real Estate (Dubai) while the
assigned agent is unavailable. You speak as the agency, not as a chatbot.

Rules:
- Follow the agent's instructions. They are what you may offer and how you may talk.
- Do not invent prices, availability, unit numbers, discounts, or viewing slots.
- If you do not know, say an agent will confirm. Do not guess.
- Do not pitch new projects, "limited units", or "book now" unless the
  instructions explicitly say this customer already has that booking in progress.
- One short WhatsApp message. No markdown, no bullet walls, no subject line.
- Never mention that you are an AI unless the customer asks.

Return JSON only: {"reply": "the message to send"}
"""


class ReplyError(Exception):
    pass


def configured() -> bool:
    return bool(getattr(settings, "OPENAI_API_KEY", ""))


def _transcript(messages) -> str:
    lines = []
    for message in messages:
        who = "CUSTOMER" if message.direction == "in" else "AGENT"
        body = (message.body or "").strip()
        if not body:
            body = f"[{message.kind}]"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def draft_reply(*, messages, context: str, inbound_text: str) -> str:
    if not configured():
        raise ReplyError("No OpenAI key is configured")

    transcript = _transcript(list(messages)[-HISTORY_LIMIT:])
    if not transcript.strip():
        raise ReplyError("Nothing to reply to")

    user = (
        f"INSTRUCTIONS:\n{(context or '').strip() or '(none — be brief and offer to wait for an agent)'}\n\n"
        f"LANGUAGE: {reply_language(inbound_text)}\n\n"
        f"THREAD:\n{transcript}"
    )

    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": getattr(settings, "OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            },
            timeout=int(getattr(settings, "OPENAI_TIMEOUT", 45) or 45),
        )
    except httpx.HTTPError as exc:
        raise ReplyError(f"OpenAI unreachable: {exc}") from None

    if response.status_code != 200:
        raise ReplyError(f"OpenAI answered {response.status_code}")

    try:
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        reply = str(data.get("reply") or "").strip()
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ReplyError(f"OpenAI returned something unreadable: {exc}") from None

    if not reply:
        raise ReplyError("Empty reply")
    return reply[:REPLY_MAX]
