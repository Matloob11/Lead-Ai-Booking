"""Pure rules for which chats the AI desk may answer.

Kept free of the ORM so the decisions can be tested without spinning Django.
"""

from __future__ import annotations

import re

AI_SOURCE = "ai_desk"
SKIP_KINDS = frozenset({"reaction", "system"})
MAX_REPLIES_PER_DAY = 12
HISTORY_LIMIT = 30
CONTEXT_MAX = 8000
REPLY_MAX = 1500

ARABIC_OR_URDU = re.compile(r"[\u0600-\u06FF]")


def payload_source(payload) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("source") or "")


def is_ai_outbound_payload(payload) -> bool:
    return payload_source(payload) == AI_SOURCE


def desk_covers(*, scope: str, is_selected: bool, has_human_outbound: bool) -> bool:
    """Whether a global desk row applies to one conversation."""
    if scope == "all":
        return True
    if scope == "selected":
        return bool(is_selected)
    if scope == "new":
        return not has_human_outbound
    return False


def last_ours_is_human(last_outbound) -> bool:
    """True when the last outbound on this chat was typed by a person.

    ``last_outbound`` is None or a mapping with ``sent_by_id`` and ``payload``.
    """
    if last_outbound is None:
        return False
    if not last_outbound.get("sent_by_id"):
        return False
    return not is_ai_outbound_payload(last_outbound.get("payload"))


def should_skip_inbound_kind(kind: str) -> bool:
    return kind in SKIP_KINDS


def reply_language(text: str) -> str:
    if ARABIC_OR_URDU.search(text or ""):
        return "Match the customer's language (Arabic or Urdu script)."
    return "Write in English."


def stack_context(global_ctx: str, chat_ctx: str) -> str:
    parts = []
    global_text = (global_ctx or "").strip()
    chat_text = (chat_ctx or "").strip()
    if global_text:
        parts.append("GLOBAL INSTRUCTIONS:\n" + global_text[:CONTEXT_MAX])
    if chat_text:
        parts.append("THIS CHAT:\n" + chat_text[:CONTEXT_MAX])
    return "\n\n".join(parts)
