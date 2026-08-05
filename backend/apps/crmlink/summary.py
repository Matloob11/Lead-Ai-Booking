"""What the customer wants, and how the agent is doing — read off the chat.

A manager looking at a lead can see forty WhatsApp messages and still not know
whether this person is buying, or whether anybody answered them. That is the
gap: the timeline records everything and summarises nothing.

Two scores rather than one, because they measure different people and can move
in opposite directions. A customer can be ready to sign while the agent has
left them on read for two days; a customer can be cold while the agent has done
everything right. One number would hide whichever of those was true.
"""

import json
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

PROMPT = """You are reading a WhatsApp conversation between a Dubai real-estate
agency and a prospective customer, and reporting on it for a manager who has not
read it.

Return JSON only, with exactly these keys:

  "summary"       2-4 sentences of plain English. What this customer is asking
                  for — budget, area, property type, timing — and where the
                  conversation currently stands. Name specifics. "Customer is
                  interested in a property" tells the manager nothing they did
                  not already know.
  "client_score"  0-100. How close this customer is to transacting. 0 is a cold
                  or dead enquiry, 100 is ready to sign. Judge it from what they
                  say and do, not from politeness.
  "agent_score"   0-100. How well our side handled it: did they answer what was
                  asked, how fast, did they follow up, did anything go
                  unanswered. Judge our messages only.
  "client_reason" One short sentence for the client score.
  "agent_reason"  One short sentence for the agent score.

Write in English even when the conversation is in Roman Urdu, Arabic or Hindi.
Be honest — a low score with a clear reason is more useful than a generous one.
If our side ignored a direct question, say so."""


class SummaryError(Exception):
    pass


def configured():
    return bool(settings.OPENAI_API_KEY)


def _transcript(messages):
    """The conversation as lines, oldest first, labelled by who spoke."""
    lines = []
    for message in messages:
        who = "CUSTOMER" if message.direction == "in" else "AGENT"
        body = (message.body or "").strip()
        if not body:
            # A photo with no caption is still a turn in the conversation, and
            # dropping it would make a thread of pictures look like silence.
            body = f"[{message.kind}]"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def summarise(messages):
    """Asks the model to read the thread. Returns the parsed dict.

    Raises rather than returning a half-answer: a summary written from a failed
    call would be pinned to a lead and believed.
    """
    if not configured():
        raise SummaryError("No OpenAI key is configured")

    transcript = _transcript(messages)
    if not transcript.strip():
        raise SummaryError("Nothing to summarise")

    try:
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": settings.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": transcript},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            timeout=settings.OPENAI_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        # The key rides in a header, not the URL, so the exception text is safe
        # to pass on as it is.
        raise SummaryError(f"OpenAI unreachable: {exc}") from None

    if response.status_code != 200:
        raise SummaryError(f"OpenAI answered {response.status_code}: {response.text[:200]}")

    try:
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
    except (KeyError, IndexError, ValueError) as exc:
        raise SummaryError(f"OpenAI returned something unreadable: {exc}") from None

    def score(key):
        try:
            return max(0, min(100, int(round(float(data.get(key, 0))))))
        except (TypeError, ValueError):
            return 0

    return {
        "summary": str(data.get("summary", "")).strip(),
        "client_score": score("client_score"),
        "agent_score": score("agent_score"),
        "client_reason": str(data.get("client_reason", "")).strip(),
        "agent_reason": str(data.get("agent_reason", "")).strip(),
    }
