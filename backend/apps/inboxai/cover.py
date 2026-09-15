"""Who covers a conversation right now, if anyone."""

from __future__ import annotations

from dataclasses import dataclass

from apps.inbox.models import Message

from .eligibility import (
    desk_covers,
    is_ai_outbound_payload,
    last_ours_is_human,
    stack_context,
)
from .models import AgentAiDesk, ConversationAiCover


@dataclass
class Covering:
    agent: object
    context: str
    origin: str  # "cover" or "desk"


def _agent_sees(agent, conversation) -> bool:
    if agent is None:
        return False
    return agent.visible_numbers.filter(pk=conversation.number_id).exists()


def _has_human_outbound(conversation) -> bool:
    qs = conversation.messages.filter(
        direction=Message.Direction.OUTBOUND, sent_by__isnull=False
    ).order_by("-id")
    for message in qs[:40]:
        if not is_ai_outbound_payload(message.payload):
            return True
    return False


def _last_outbound_snapshot(conversation):
    message = (
        conversation.messages.filter(direction=Message.Direction.OUTBOUND)
        .order_by("-id")
        .first()
    )
    if message is None:
        return None
    return {"sent_by_id": message.sent_by_id, "payload": message.payload}


def cover_for(conversation) -> Covering | None:
    """Return the agent + stacked context that should answer this inbound, or None.

    Per-chat cover wins when it is enabled and not paused. Otherwise the
    assigned agent's desk may cover, scoped to that agent's own numbers —
    never the whole company.
    """
    cover = (
        ConversationAiCover.objects.filter(conversation=conversation)
        .select_related("agent")
        .first()
    )
    if cover and cover.enabled and cover.paused_at is None and _agent_sees(cover.agent, conversation):
        desk = AgentAiDesk.objects.filter(agent=cover.agent).first()
        return Covering(
            agent=cover.agent,
            context=stack_context(desk.context if desk else "", cover.context),
            origin="cover",
        )

    agent = conversation.assigned_agent
    if not agent or not _agent_sees(agent, conversation):
        return None

    desk = AgentAiDesk.objects.filter(agent=agent, enabled=True).first()
    if not desk:
        return None
    is_selected = (
        desk.selected.filter(pk=conversation.pk).exists() if desk.scope == AgentAiDesk.Scope.SELECTED else False
    )
    if not desk_covers(
        scope=desk.scope,
        is_selected=is_selected,
        has_human_outbound=_has_human_outbound(conversation),
    ):
        return None
    # Agent already typing in this thread — leave it to them.
    if last_ours_is_human(_last_outbound_snapshot(conversation)):
        return None

    return Covering(agent=agent, context=stack_context(desk.context, ""), origin="desk")
