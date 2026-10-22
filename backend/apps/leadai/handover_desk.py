"""The handover desk (Matloob 2026-10-22): a Lead AI chat handed to a person belongs on the screen of exactly one agent,
the Bitrix lead's Responsible (ASSIGNED_BY_ID; when it changes in Bitrix it changes here). That agent sees only their
handed-over chats — the chat and the customer — on "My handovers" (bitrix/public/assets/modules/lead-ai/handovers.js),
where they read, reply inside the 24-hour window, send a template from the chat's own number, see the viewing the chat
booked, and say Done. Nothing else of the panel: no other chats, no numbers, no counts, no meetings list. Admins keep
everything as it was. The assistant keeps its ways: quiet while handed over, the co-pilot's draft for the agent (sent by
itself after the setting's minutes unless the agent speaks first; never for a call, a complaint or legal), back in full
once a person wrote.

- **The marker** is ``LeadAiChatState.desk_at`` (durable: ``handed_over_at`` clears the moment a person writes, and a
  chat answered once must stay on the desk) with ``desk_reason``; ``mark`` sets it at every handover (engine._apply for
  the model's and code's handovers and brokers, bitrix_status.apply for a person's Bot Status) and reads the Bitrix
  responsible again after the commit; ``done`` clears it (their Done, an admin's) and ends the handover with its own
  pause (Bitrix's Handed to agent), never an agent's Pause nor a broker's; lane.move_to_inbox clears it too; a reply
  never does. The chats handed over before the desk existed were put on it by migration 0019.
- **Who** is the chat's ``responsible_bitrix_user_id`` compared with the agent's ``bitrix_user_id`` at query time: it
  works before the agent ever signed in (the Agent row is made at their first sign-in), and a Bitrix reassignment moves
  the chat the moment the responsible is read again (``refresh_responsibles``: every REFRESH while on a desk). Bitrix
  users 0 and 1 hold unassigned leads (alerts.HOLD_USERS): nobody's desk.
- **Visibility** is one clause, ``mine_q``, OR-ed into inbox.visibility.visible_conversation_q for an agent who is no
  panel admin, as the desk's clause is: every inbox and Lead AI endpoint (messages, send, send-template, templates,
  read, the co-pilot's draft, the chat detail) follows without a change, the main inbox list leaves Lead AI chats out
  as before, and the Lead AI screen's own list is the desk agents' and admins' (the responsible's rows come from
  ``rows``, trimmed to the chat and the customer). An agent who has a chat through the desk alone
  (``only_through_desk``: no admin, no Lead AI access, not the owner, none of the number's holders) gets its detail
  and its live frames trimmed the same way (``trim``, ``trim_live``): our number as digits, nothing of the team.
- **Live**: that agent's own channel (inbox.events.group_for_agent) hears the chat's events trimmed (``live_groups``,
  via lane.desk_scoped_groups), the handover alerts reach them as before (alerts.recipients names the responsible),
  and DESK_CHANGED tells them a chat came onto, or left, their desk (``changed``: a Done, a move, a reassignment).
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from .assistant.alerts import HOLD_USERS
from .models import LeadAiChatState

logger = logging.getLogger(__name__)

# The Bitrix responsible is read again this often while the chat is on a desk (a reassignment in Bitrix shows within).
REFRESH = dt.timedelta(hours=1)
REFRESH_BATCH = 50
UNCLEAR = "unclear"
# The responsible's own channel hears this when a chat comes onto, or leaves, their desk (handovers.js reads its list
# again; lead-ai.js sets the menu's count from it).
DESK_CHANGED = "leadai.desk.changed"
# What a chat's row keeps nothing of for an agent who has it through the desk alone (trim).
TEAM_KEYS = ("assigned_agent", "linked_number", "linked_conversation_id", "lead_ai_info")


def bitrix_id(user) -> str:
    """The agent's Bitrix user id, digits only: "" for none, and for Bitrix users 0 and 1, who hold unassigned leads
    (alerts.HOLD_USERS) and so are nobody's desk."""
    digits = "".join(ch for ch in str(getattr(user, "bitrix_user_id", "") or "") if ch.isdigit())
    return "" if digits in HOLD_USERS else digits


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
    """The active Lead AI chats on this Bitrix user's desk (a Subquery: building it costs no query); none at all for a
    hold user (0 and 1 hold the unassigned leads: their chats are nobody's desk)."""
    bitrix_user_id = str(bitrix_user_id or "")
    if bitrix_user_id in HOLD_USERS:
        return Q(pk__in=[])
    on_desk = LeadAiChatState.objects.filter(desk_at__isnull=False, responsible_bitrix_user_id=bitrix_user_id).values("conversation_id")
    return Q(pk__in=Subquery(on_desk)) & Q(lead_ai_chat__active=True)


def mine_q(user):
    """inbox.visibility's clause for the desk: the chats on this agent's desk; None for an agent who cannot have one
    (not even a query more, as lane.desk_q does for an agent without Lead AI access)."""
    if not may_use(user):
        return None
    return desk_q(bitrix_id(user))


def changed(agent_id, conversation_id: int, on_desk: bool) -> None:
    """Tell the agent's own live channel (inbox.events.publish_to_agent) that the chat came onto, or left, their desk,
    with their desk's count, once the caller's transaction commits (the list the panel reads then is the database's).
    Nothing for no agent (a responsible not signed in yet hears the alert, as before)."""
    if not agent_id:
        return

    def tell():
        from django.contrib.auth import get_user_model

        from apps.inbox.events import publish_to_agent

        agent = get_user_model().objects.filter(pk=agent_id).first()
        publish_to_agent(agent_id, DESK_CHANGED, {"conversation_id": conversation_id, "on_desk": on_desk, "count": count_for(agent)})

    transaction.on_commit(tell)


def mark(state, now, reason: str, fields: list) -> bool:
    """Put the chat on its responsible's desk: the state's fields set and named in ``fields`` for the caller's save
    (engine._apply, bitrix_status.apply), the Bitrix responsible read again once the caller's transaction commits (a
    responsible known already hears the chat at once). True when the chat was not on a desk already (a second handover
    in the same stay changes nothing)."""
    if state.desk_at is not None:
        return False
    state.desk_at = now
    state.desk_reason = str(reason or UNCLEAR)[:40]
    state.desk_done_at = None
    state.desk_done_by = None
    fields += ["desk_at", "desk_reason", "desk_done_at", "desk_done_by"]
    conversation_id = state.conversation_id
    transaction.on_commit(lambda: _read_responsible(conversation_id))
    changed(state.responsible_agent_id, conversation_id, True)
    return True


def _read_responsible(conversation_id: int) -> None:
    from . import tasks

    try:
        tasks.resolve_responsible.delay(conversation_id)
    except Exception:  # noqa: BLE001 - the sweep's refresh reads it within the hour
        logger.exception("Lead AI could not queue the responsible read for conversation %s", conversation_id)


def done(conversation, user, now=None) -> LeadAiChatState:
    """Their Done (the responsible's, or an admin's): off the desk; a handover still open ends with it, and so does the
    handover's own pause (Bitrix's Handed to agent: paused by nobody), so the assistant answers in full again, as it does
    once a person wrote. An agent's own Pause stays (their choice), and so does a broker's (the assistant never talks
    to a broker: Q11; Resume is the admins')."""
    from .assistant import engine

    now = now or timezone.now()
    state = LeadAiChatState.for_conversation(conversation)
    values = {"desk_at": None, "desk_done_at": now, "desk_done_by": user if getattr(user, "pk", None) else None}
    if state.handed_over_at is not None:
        values.update(handed_over_at=None, handover_reason="", holding_line_at=None, draft=None)
    if state.paused_at is not None and state.paused_by_id is None and state.desk_reason != engine.BROKER:
        values.update(paused_at=None, paused_by=None)
    LeadAiChatState.objects.filter(pk=state.pk).update(**values)
    changed(state.responsible_agent_id, conversation.pk, False)
    return LeadAiChatState.objects.get(pk=state.pk)


def clear(conversation, user=None, now=None) -> None:
    """Off every desk (Move to inbox): the chat is a person's in the main inbox now."""
    row = LeadAiChatState.objects.filter(conversation=conversation, desk_at__isnull=False).values_list("pk", "responsible_agent_id").first()
    if row is None:
        return
    pk, agent_id = row
    LeadAiChatState.objects.filter(pk=pk).update(
        desk_at=None, desk_done_at=now or timezone.now(), desk_done_by=user if getattr(user, "pk", None) else None
    )
    changed(agent_id, conversation.pk, False)


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


def person_wrote_exists():
    """``person_wrote_since`` as one annotation for a whole desk list (views.desk_mine: ``desk_person_wrote``), the
    assistant's sends told by their payload's source (transcript.is_ours); a message with no source named is a
    person's, so the key's absence is spelled out (a negated JSON lookup alone drops those rows)."""
    from apps.inbox.models import Message

    return Exists(
        Message.objects.filter(
            conversation_id=OuterRef("pk"),
            direction=Message.Direction.OUTBOUND,
            created_at__gt=OuterRef("lead_ai_state__desk_at"),
            mirrored_from__isnull=True,
        )
        .exclude(kind__in=(Message.Kind.SYSTEM, Message.Kind.TEMPLATE))
        .filter(Q(payload__source__isnull=True) | ~Q(payload__source__startswith="leadai"))
    )


def row(conversation, now=None) -> dict | None:
    """One desk row: the chat and the customer, nothing of the team (no other agent, no campaign, no number's title),
    for the responsible's own list. None when the chat is on no desk. ``desk_person_wrote`` (person_wrote_exists) is
    read when the list annotated it, else asked for this chat."""
    now = now or timezone.now()
    state = getattr(conversation, "lead_ai_state", None)
    if state is None or state.desk_at is None:
        return None
    contact = conversation.contact
    waiting = max(0, int((now - state.desk_at).total_seconds() // 60))
    wrote = getattr(conversation, "desk_person_wrote", None)
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
            "person_wrote": bool(wrote) if wrote is not None else person_wrote_since(conversation, state.desk_at),
        },
        "ai": {
            "quiet": state.handed_over_at is not None,
            "paused": state.paused_at is not None,
            "stopped": state.stopped_at is not None,
            "draft": bool(state.draft),
        },
    }


def only_through_desk(user, conversation) -> bool:
    """The agent reaches this chat through the desk alone: no panel admin, no Lead AI access, not the chat's owner,
    none of its number's holders. Their screen is then the chat and the customer, nothing of the team (``trim``)."""
    from apps.inbox.visibility import held_numbers, sees_all_inbox_chats

    from .lane import has_desk_access

    if user is None or sees_all_inbox_chats(user) or has_desk_access(user):
        return False
    if getattr(conversation, "assigned_agent_id", None) == getattr(user, "pk", None):
        return False
    return not held_numbers(user).filter(pk=conversation.number_id).exists()


def trim(row: dict) -> dict:
    """A serialized chat (inbox.serializers.serialize_conversation, views.serialize_lead_ai_conversation) for an agent
    who has it through the desk alone: our number as its digits (the composer says which line the reply goes from),
    nothing of the team (no owner, no number's name, no campaign or lead id, no earlier chats on our other numbers, no
    agent's name on a pause or a call). In place, and returned."""
    number = row.get("number")
    row["number"] = {"id": number.get("id"), "phone_number": number.get("phone_number", "")} if isinstance(number, dict) else None
    for key in TEAM_KEYS:
        if key in row:
            row[key] = None
    # The nested parts copied first: a live frame's full copy goes to the number's group with them as they were.
    ai = row.get("lead_ai_ai")
    if isinstance(ai, dict):
        row["lead_ai_ai"] = {**ai, "memory": [], "paused_by": ""}
    appointment = row.get("lead_ai_appointment")
    if isinstance(appointment, dict):
        row["lead_ai_appointment"] = {**appointment, "taken_by": "", "taken_by_id": None}
    return row


def trim_live(data: dict) -> dict:
    """A live frame's data (inbox.events.publish) for the responsible's own channel: its conversation trimmed."""
    conversation = data.get("conversation") if isinstance(data, dict) else None
    if not isinstance(conversation, dict):
        return data
    return {**data, "conversation": trim(dict(conversation))}


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
    """The responsible's own live channel for a chat on their desk that they reach through the desk alone
    (only_through_desk; inbox.events.publish, via lane.desk_scoped_groups): they hold no number group and are not the
    chat's owner, so nothing else would reach them, and the frames go trimmed (trim_live). An admin, a desk agent or a
    holder of the chat's number hears the number's or the desk's group as before: no channel of their own."""
    from apps.inbox.events import group_for_agent

    state = (
        LeadAiChatState.objects.filter(conversation_id=getattr(conversation, "pk", None), desk_at__isnull=False)
        .exclude(responsible_agent=None)
        .select_related("responsible_agent")
        .first()
    )
    if state is None or not only_through_desk(state.responsible_agent, conversation):
        return []
    return [group_for_agent(state.responsible_agent_id)]


def count_for(user) -> int:
    """How many chats are on this agent's desk (the panel's menu badge and the no-number card's door)."""
    if not may_use(user):
        return 0
    from apps.inbox.models import Conversation

    return Conversation.objects.filter(desk_q(bitrix_id(user))).count()
