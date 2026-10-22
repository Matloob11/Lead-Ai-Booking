"""The handover desk (Matloob 2026-10-22): a Lead AI chat handed to a person belongs on the screen of exactly one agent,
the Bitrix lead's Responsible (ASSIGNED_BY_ID; when it changes in Bitrix it changes here). That agent sees only their
handed-over chats — the chat and the customer — on "My handovers" (bitrix/public/assets/modules/lead-ai/handovers.js),
where they read, reply inside the 24-hour window, send a template from the chat's own number, see the viewing the chat
booked, and say Done. Nothing else of the panel: no other chats, no numbers, no counts, no meetings list. Admins keep
everything as it was. The assistant keeps its ways: quiet while handed over, the co-pilot's draft for the agent (sent by
itself after the setting's minutes unless the agent speaks first; never for a call, a complaint or legal), back in full
once a person wrote.

- **The marker** is ``LeadAiChatState.desk_at`` (durable: ``handed_over_at`` clears the moment a person writes or after
  12 hours, and a chat answered once must stay on the desk) with ``desk_reason``; ``mark`` sets it at every handover
  (engine._apply for the model's and code's handovers and brokers, bitrix_status.apply for a person's Bot Status) and
  reads the Bitrix responsible again after the commit; ``done`` clears it (their Done, an admin's), lane.move_to_inbox
  clears it too; a reply never does.
- **Who** is the chat's ``responsible_bitrix_user_id`` compared with the agent's ``bitrix_user_id`` at query time: it
  works before the agent ever signed in (the Agent row is made at their first sign-in), and a Bitrix reassignment moves
  the chat the moment the responsible is read again (``refresh_responsibles``: every REFRESH while on a desk).
- **Visibility** is one clause, ``mine_q``, OR-ed into inbox.visibility.visible_conversation_q for an agent who is no
  panel admin, as the desk's clause is: every inbox and Lead AI endpoint (messages, send, send-template, templates,
  read, the co-pilot's draft, the chat detail) follows without a change, the main inbox list leaves Lead AI chats out
  as before, and the Lead AI screen's own list is the desk agents' and admins' (the responsible's rows come from
  ``rows``, trimmed to the chat and the customer).
- **Live**: the responsible's own channel (inbox.events.group_for_agent) hears the chat's events (``live_groups``, via
  lane.desk_event_groups), and the handover alerts reach them as before (alerts.recipients names the responsible).
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from django.db.models import Q, Subquery
from django.utils import timezone

from .models import LeadAiChatState

logger = logging.getLogger(__name__)

# The Bitrix responsible is read again this often while the chat is on a desk (a reassignment in Bitrix shows within).
REFRESH = dt.timedelta(hours=1)
REFRESH_BATCH = 50
UNCLEAR = "unclear"


def bitrix_id(user) -> str:
    return "".join(ch for ch in str(getattr(user, "bitrix_user_id", "") or "") if ch.isdigit())


def may_use(user) -> bool:
    """An agent who can have a desk: signed in, active, a Bitrix user, the Official API inbox (every Lead AI chat's)."""
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and bitrix_id(user)
        and getattr(user, "can_official_api", True)
    )


def desk_q(bitrix_user_id: str):
    """The active Lead AI chats on this Bitrix user's desk (a Subquery: building it costs no query)."""
    on_desk = LeadAiChatState.objects.filter(desk_at__isnull=False, responsible_bitrix_user_id=str(bitrix_user_id)).values("conversation_id")
    return Q(pk__in=Subquery(on_desk)) & Q(lead_ai_chat__active=True)


def mine_q(user):
    """inbox.visibility's clause for the desk: the chats on this agent's desk; None for an agent who cannot have one
    (not even a query more, as lane.desk_q does for an agent without Lead AI access)."""
    if not may_use(user):
        return None
    return desk_q(bitrix_id(user))


def mark(state, now, reason: str, fields: list) -> bool:
    """Put the chat on its responsible's desk: the state's fields set and named in ``fields`` for the caller's save
    (engine._apply, bitrix_status.apply), the Bitrix responsible read again once the caller's transaction commits.
    True when the chat was not on a desk already (a second handover in the same stay changes nothing)."""
    if state.desk_at is not None:
        return False
    state.desk_at = now
    state.desk_reason = str(reason or UNCLEAR)[:40]
    state.desk_done_at = None
    state.desk_done_by = None
    fields += ["desk_at", "desk_reason", "desk_done_at", "desk_done_by"]
    conversation_id = state.conversation_id
    transaction.on_commit(lambda: _read_responsible(conversation_id))
    return True


def _read_responsible(conversation_id: int) -> None:
    from . import tasks

    try:
        tasks.resolve_responsible.delay(conversation_id)
    except Exception:  # noqa: BLE001 - the sweep's refresh reads it within the hour
        logger.exception("Lead AI could not queue the responsible read for conversation %s", conversation_id)


def done(conversation, user, now=None) -> LeadAiChatState:
    """Their Done (the responsible's, or an admin's): off the desk; a handover still open ends with it, so the assistant
    answers in full again (as it does once a person wrote); a pause or a stop stays what it is."""
    now = now or timezone.now()
    state = LeadAiChatState.for_conversation(conversation)
    values = {"desk_at": None, "desk_done_at": now, "desk_done_by": user if getattr(user, "pk", None) else None}
    if state.handed_over_at is not None:
        values.update(handed_over_at=None, handover_reason="", holding_line_at=None, draft=None)
    LeadAiChatState.objects.filter(pk=state.pk).update(**values)
    return LeadAiChatState.objects.get(pk=state.pk)


def clear(conversation, user=None, now=None) -> None:
    """Off every desk (Move to inbox): the chat is a person's in the main inbox now."""
    LeadAiChatState.objects.filter(conversation=conversation, desk_at__isnull=False).update(
        desk_at=None, desk_done_at=now or timezone.now(), desk_done_by=user if getattr(user, "pk", None) else None
    )


def reason_text(reason: str) -> str:
    """The reason as the alerts word it (engine.HANDOVER_TEXT), else the reason itself."""
    from .assistant import engine

    text = engine.HANDOVER_TEXT.get(str(reason or ""), "")
    return str(text or reason or UNCLEAR)


def person_wrote_since(conversation, since) -> bool:
    """A person (not the assistant, not a campaign template) wrote in the chat after ``since``."""
    from apps.inbox.models import Message

    from .assistant import transcript

    rows = Message.objects.filter(
        conversation=conversation, direction=Message.Direction.OUTBOUND, created_at__gt=since, mirrored_from__isnull=True
    ).exclude(kind__in=(Message.Kind.SYSTEM, Message.Kind.TEMPLATE)).order_by("-pk")[:20]
    return any(not transcript.is_ours(row) for row in rows)


def row(conversation, now=None) -> dict | None:
    """One desk row: the chat and the customer, nothing of the team (no other agent, no campaign, no number's title),
    for the responsible's own list. None when the chat is on no desk."""
    now = now or timezone.now()
    state = getattr(conversation, "lead_ai_state", None)
    if state is None or state.desk_at is None:
        return None
    contact = conversation.contact
    waiting = max(0, int((now - state.desk_at).total_seconds() // 60))
    return {
        "id": conversation.pk,
        "number_id": conversation.number_id,
        # As the inbox serializes a contact (the panel's contactName reads display_name, then profile_name, then the number).
        "contact": {
            "id": contact.pk,
            "wa_id": contact.wa_id,
            "display_name": contact.display_name or "",
            "profile_name": contact.profile_name or "",
        },
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        "last_message_preview": conversation.last_message_preview or "",
        "last_message_kind": getattr(conversation, "last_message_kind", "") or "",
        "unread_count": int(conversation.unread_count or 0),
        "is_session_open": bool(conversation.is_session_open),
        "session_expires_at": conversation.session_expires_at.isoformat() if conversation.session_expires_at else None,
        "desk": {
            "at": state.desk_at.isoformat(),
            "reason": state.desk_reason or UNCLEAR,
            "reason_text": reason_text(state.desk_reason),
            "waiting_minutes": waiting,
            "person_wrote": person_wrote_since(conversation, state.desk_at),
        },
        "ai": {
            "quiet": state.handed_over_at is not None,
            "paused": state.paused_at is not None,
            "stopped": state.stopped_at is not None,
            "draft": bool(state.draft),
        },
    }


def refresh_responsibles(now=None) -> int:
    """The sweep: the Bitrix responsible of every chat on a desk is read again every REFRESH (REFRESH_BATCH a minute),
    so "if it changes in Bitrix it changes here" holds within the hour. Returns how many reads were queued."""
    from . import tasks

    now = now or timezone.now()
    stale = list(
        LeadAiChatState.objects.filter(desk_at__isnull=False, conversation__lead_ai_chat__active=True)
        .filter(Q(responsible_checked_at__isnull=True) | Q(responsible_checked_at__lt=now - REFRESH))
        .order_by("responsible_checked_at", "pk")
        .values_list("pk", "conversation_id")[:REFRESH_BATCH]
    )
    for pk, conversation_id in stale:
        # Marked read now, so the next minute does not queue it again; a read that fails resets it (resolve_responsible).
        LeadAiChatState.objects.filter(pk=pk).update(responsible_checked_at=now)
        tasks.resolve_responsible.delay(conversation_id)
    return len(stale)


def live_groups(conversation) -> list[str]:
    """The responsible's own live channel for a chat on their desk (inbox.events.publish, via lane.desk_event_groups):
    they hold no number group and are not the chat's owner, so nothing else would reach them."""
    from apps.inbox.events import group_for_agent

    agent_id = (
        LeadAiChatState.objects.filter(conversation_id=getattr(conversation, "pk", None), desk_at__isnull=False)
        .exclude(responsible_agent_id=None)
        .values_list("responsible_agent_id", flat=True)
        .first()
    )
    return [group_for_agent(agent_id)] if agent_id else []


def count_for(user) -> int:
    """How many chats are on this agent's desk (the panel's menu badge and the no-number card's door)."""
    if not may_use(user):
        return 0
    from apps.inbox.models import Conversation

    return Conversation.objects.filter(desk_q(bitrix_id(user))).count()
