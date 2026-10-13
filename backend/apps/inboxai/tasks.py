"""Debounced reply after an inbound customer message."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.inbox.models import Message
from apps.inbox.services import SendBlocked, send_text

from .cover import cover_for
from .eligibility import (
    AI_SOURCE,
    MAX_REPLIES_PER_DAY,
    should_skip_inbound_kind,
)
from .reply import ReplyError, configured, draft_reply

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def reply_to_inbound(message_id: int) -> None:
    inbound = (
        Message.objects.select_related(
            "conversation",
            "conversation__contact",
            "conversation__number",
            "conversation__assigned_agent",
        )
        .filter(pk=message_id)
        .first()
    )
    if inbound is None:
        return
    if inbound.direction != Message.Direction.INBOUND:
        return
    if should_skip_inbound_kind(inbound.kind):
        return

    conversation = inbound.conversation
    latest = (
        conversation.messages.filter(direction=Message.Direction.INBOUND)
        .exclude(kind__in=("reaction", "system"))
        .order_by("-id")
        .first()
    )
    if latest is None or latest.pk != inbound.pk:
        return

    # Leadbot owns this thread until qualified. Do not also answer as the AI desk.
    from apps.leadbot.models import LeadAutomation

    if LeadAutomation.objects.filter(
        conversation_id=conversation.pk,
        state__in=(
            LeadAutomation.State.AWAITING_REPLY,
            LeadAutomation.State.ACTIVE,
            LeadAutomation.State.PENDING,
        ),
    ).exists():
        return

    # A Lead AI chat is answered by the agent in the Lead AI screen; no AI reply.
    from apps.leadai.lane import is_lead_ai

    if is_lead_ai(conversation):
        return

    covering = cover_for(conversation)
    if covering is None:
        return

    conversation.refresh_from_db(fields=["session_expires_at"])
    if not conversation.is_session_open:
        logger.info("AI desk skipped conversation %s: 24h window closed", conversation.pk)
        return

    since = timezone.now() - timedelta(hours=24)
    already = conversation.messages.filter(
        direction=Message.Direction.OUTBOUND,
        created_at__gte=since,
        payload__source=AI_SOURCE,
    ).count()
    if already >= MAX_REPLIES_PER_DAY:
        logger.info("AI desk hit daily cap on conversation %s", conversation.pk)
        return

    if not configured():
        logger.warning("AI desk has no OpenAI key; skipping conversation %s", conversation.pk)
        return

    history = list(
        conversation.messages.exclude(kind__in=("reaction", "system")).order_by("id")
    )
    try:
        body = draft_reply(
            messages=history,
            context=covering.context,
            inbound_text=inbound.body or "",
        )
    except ReplyError as exc:
        logger.warning("AI desk draft failed for conversation %s: %s", conversation.pk, exc)
        return

    try:
        send_text(
            conversation,
            covering.agent,
            body,
            reply_to=inbound if inbound.wamid else None,
            payload={"source": AI_SOURCE},
        )
    except SendBlocked as exc:
        logger.info("AI desk send blocked on conversation %s: %s", conversation.pk, exc)
    except Exception:
        logger.exception("AI desk send failed on conversation %s", conversation.pk)


@shared_task(ignore_result=True)
def consider_health(conversation_id: int, force: bool = False) -> None:
    from apps.inbox.models import Conversation

    from .health import consider_conversation

    conversation = (
        Conversation.objects.select_related("contact", "number", "assigned_agent")
        .filter(pk=conversation_id)
        .first()
    )
    if conversation is None:
        return
    try:
        consider_conversation(conversation, force=force)
    except Exception:
        logger.exception("inboxai health failed on conversation %s", conversation_id)
