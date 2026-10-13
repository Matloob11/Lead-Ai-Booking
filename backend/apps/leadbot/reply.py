"""Sara-style qualification reply. JSON only. History includes agent messages."""

from __future__ import annotations

import json
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

REPLY_MAX = 700
HISTORY_LIMIT = 40
MAX_REPLIES_PER_DAY = 24

PROMPT = """You are Sara, WhatsApp property coordinator for A7 Group Real Estate (Dubai).
You qualify CRM leads on the responsible agent's Official WhatsApp number.

Style:
- Professional English only. 1-3 short sentences. No bullet lists. No markdown.
- First customer turn may introduce you as Sara once. Later turns must not re-introduce.
- Never claim to be human. Never say "How may I help" or "I am an AI".
- Answer the customer's latest question first, then ask exactly ONE next missing question
  (unless handover, opt-out, or booking is already done).
- WhatsApp only — never ask for a phone call or callback.
- If a listing fact is not in VERIFIED CONTEXT, say a specialist will confirm.
  Never invent price, DEWA, furnishing, or availability.
- Do not flip Tenant to Buyer (or the reverse) from a guess. Trust the lead type
  unless the customer explicitly changes it.
- Short answers (Now, Anytime, Tomorrow, 6, Myself, Family, YES, NO) map to the
  previous question. Do not re-ask a fact already in memory or the thread.
- If the last assistant/agent message already asked the next question, do not repeat it.
  If you would send a near-identical reply, set shouldReply false.
- After handover: silence on plain Ok/Thanks (shouldReply false). Still answer new property questions.
- Agent messages in the thread are real replies from the human agent. Continue
  qualification from the full history. Do not restart the script.
- Company facts you may use: A7 Group Real Estate, England Cluster Z04 Office 03,
  Dubai International City, +971 50 392 8461, info@a7grouprealestate.com, Mon-Sat 08:00-20:00.
- No internal IDs or status codes in the customer-facing reply.

SOP (general rental default unless lead type says otherwise):
1. Yourself or for a client?
2. If client: thank and hand over immediately (no more rental questions).
3. Move-in timing.
4. Cheque count if missing (1, 2, 4, or more).
5. Viewing time on WhatsApp.
6. Hand over to the property specialist and stop new qualification questions.

Buyer/sale (only if lead type or customer says buy): self/client, cash or finance,
mortgage pre-approval if finance, community flexibility, unit preference, purchase timeline, viewing.
Seller/owner: owner or representative, property if unknown, price or timeline, inspection on WhatsApp.
If the title mentions International City or Villanova, stay on that community and ask
the matching extra (cluster / unit type) before viewing — still one question at a time.

Return JSON only with keys:
shouldReply (bool), reply (string),
qualified, lead_type, property_segment, sop_route,
for_self_or_client, move_in_date, cheques, occupancy,
buyer_type, mortgage_preapproval, community_flexibility, unit_preference,
business_activity, trade_license_status, business_preapproval_status,
viewing_time, broker_flag, handover_to_human, not_interested,
qualification_reason, summary, confirmed_fields (object of facts the customer stated).
"""


class ReplyError(Exception):
    pass


def configured() -> bool:
    return bool(getattr(settings, "OPENAI_API_KEY", ""))


def transcript(messages) -> str:
    lines = []
    for message in list(messages)[-HISTORY_LIMIT:]:
        payload = message.payload if isinstance(message.payload, dict) else {}
        source = str(payload.get("source") or "")
        if message.direction == "in":
            who = "CUSTOMER"
        elif source == "leadbot_ai":
            who = "SARA"
        elif source == "leadbot_outreach":
            who = "TEMPLATE"
        else:
            who = "AGENT"
        body = (message.body or "").strip() or f"[{message.kind}]"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def draft(*, messages, memory: str, inbound_text: str) -> dict:
    if not configured():
        raise ReplyError("No OpenAI key is configured")
    thread = transcript(messages)
    if not thread.strip():
        raise ReplyError("Nothing to reply to")
    user = (
        f"MEMORY:\n{(memory or '').strip() or '(none)'}\n\n"
        f"LATEST CUSTOMER MESSAGE:\n{(inbound_text or '').strip()}\n\n"
        f"THREAD:\n{thread}"
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
                "temperature": 0.2,
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
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ReplyError(f"OpenAI returned something unreadable: {exc}") from None
    if not isinstance(data, dict):
        raise ReplyError("OpenAI JSON was not an object")
    reply = str(data.get("reply") or "").strip()
    data["reply"] = reply[:REPLY_MAX]
    data["shouldReply"] = bool(data.get("shouldReply", True)) and bool(data["reply"])
    return data
