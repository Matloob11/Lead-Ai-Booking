"""Colour bins and the false-RED guard — no ORM, same as OpenWA classify."""

from __future__ import annotations

import re

COLOURS = ("red", "pink", "yellow", "white", "green")
RECLASSIFY_EVERY_N = 10
CLASSIFY_MSG_CHARS = 12000
THREAD_MESSAGES = 120

SYSTEM_PROMPT = """You are a compliance and quality monitor for a Dubai real estate agency.
You read one full conversation between a company AGENT and a CLIENT.
The conversation may be a WhatsApp chat or a phone-call transcript.
Language is mostly English, sometimes Roman Urdu (Urdu in English letters) or a mix — understand all of them.
Classify the WHOLE conversation into exactly ONE colour:
- "red"    = Corruption / integrity risk. Clear evidence the agent is moving money or the deal OUTSIDE the company (personal account, off-books commission, "don't tell the office", bypass CRM).
- "pink"   = The CLIENT is unprofessional: abusive, threatening, insulting, or aggressively complaining.
- "yellow" = The AGENT cannot satisfy the client: no matching property, wrong budget/area, capability gap.
- "white"  = Hot, healthy deal: client interested, both sides professional, closing being discussed.
- "green"  = Normal, clean, ongoing conversation with no problems and no closing discussion yet.
Rules:
- Judge by the MEANING of the whole conversation, not single words.
- RED requires clear evidence. Vague suspicion is NOT red — use green and set needs_human_review true if unsure.
- Normal property talk, viewing schedules, pricing within company process, or polite negotiation is green (or white if actively closing).
- Never output category "red" if your reason says the chat is normal, clean, or has no integrity issue — that must be "green".
- category and reason MUST agree. RED takes priority only when evidence is clear.
Respond with ONLY this JSON, nothing else:
{"category":"red|pink|yellow|white|green","confidence":0.0,"reason":"one short sentence","flags":[],"needs_human_review":false}
"""

_CLEAN = re.compile(
    r"\b(normal|clean|no (integrity|corruption|risk)|nothing (wrong|suspicious)|no problems?)\b",
    re.I,
)
_STILL_BAD = re.compile(
    r"\b(outside (the )?compan|personal account|commission|bypass|off[- ]books|side deal)\b",
    re.I,
)


def looks_like_clean_reason(reason: str) -> bool:
    """Reasons that clearly say the chat is fine — must not stay RED."""
    text = (reason or "").lower()
    if not text.strip():
        return False
    return bool(_CLEAN.search(text) and not _STILL_BAD.search(text))


def coerce_result(parsed: dict) -> dict:
    category = str(parsed.get("category") or "green").lower().strip()
    if category not in COLOURS:
        category = "green"
    reason = str(parsed.get("reason") or "")
    if category == "red" and looks_like_clean_reason(reason):
        category = "green"
    flags = parsed.get("flags")
    try:
        confidence = float(parsed.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": category,
        "confidence": confidence,
        "reason": reason,
        "flags": [str(item) for item in flags] if isinstance(flags, list) else [],
        "needs_human_review": bool(parsed.get("needs_human_review")),
    }
