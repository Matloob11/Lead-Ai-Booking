"""Live hints for the Lead AI screen.

Published through inbox.events.publish, which renames them "leadai.<event>"
while the chat is on the Lead AI screen. The payloads carry flat ids only,
never a conversation or message object: the main inbox drops from its list
any chat named in a leadai.* event's conversation or message.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def thinking(conversation, on: bool) -> None:
    """'The assistant is writing a reply' on (or off) in this chat."""
    try:
        from apps.inbox.events import publish

        publish(conversation, "ai.state", {"conversation_id": conversation.pk, "state": "thinking" if on else "idle"})
    except Exception:  # noqa: BLE001 - a hint, never worth failing a turn
        logger.debug("Lead AI state event failed for %s", getattr(conversation, "pk", None))


def appointment_changed(conversation_id: int) -> None:
    """The chat's appointment or assistant state changed: the screen re-reads it."""
    try:
        from apps.inbox.events import publish
        from apps.inbox.models import Conversation

        conversation = Conversation.objects.filter(pk=conversation_id).first()
        if conversation is not None:
            publish(conversation, "ai.changed", {"conversation_id": conversation_id})
    except Exception:  # noqa: BLE001
        logger.debug("Lead AI change event failed for %s", conversation_id)
