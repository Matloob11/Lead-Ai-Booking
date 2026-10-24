"""The per-chat reply caps, and a capped message answered once the cap frees (launch review issue 2).

Live on 2026-10-15 the cap of 6 replies an hour silenced the two hottest shops customers for good: chat 78's
"Ok" to 3:00 PM or 3:30 PM, and chat 91's "can you show me at least the video", "i cant come today as im at
work" and "i will be available on saturday". The build pack's own path needs about eight replies (for whom,
the list, the media, the match, the business, the licence, its copy, the slots, the confirmation), and a
turn the cap held back was never run again: the missed-message sweep skips a message that has a turn.

- A shops chat (lane.IC_SHOPS) may send SHOPS_PER_HOUR replies an hour and SHOPS_PER_DAY a day (a general
  chat keeps engine.CAP_PER_HOUR and CAP_PER_DAY). The messages of one turn are one reply, a nudge one each
  (engine._ours_since).
- A capped turn keeps its row (SKIPPED, engine.CAPPED_REASON: followups.cap_pending holds every follow-up
  while it waits). Once the cap frees, the sweep (tasks._answer_capped, every minute) queues the chat's
  newest capped message again, when it is still the newest customer message, nobody wrote after it (us or a
  colleague), and the chat may still be answered (Lead AI, not transferred, stopped or paused, the window
  open); the task takes the same row up again (reclaim) and answers the whole burst, however old it is.
  At most once every REQUEUE_EVERY per turn, for REQUEUE_WITHIN.
- The cap alert of a shops chat says when the assistant answers by itself, carries their last words, the
  lead and where the chat is, is high priority, and reaches the Lead AI alert list too (alerts listed).

Each default is one constant here.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# A shops chat's caps (Matloob 2026-10-24: 30 replies an hour; the day stays 30).
SHOPS_PER_HOUR = 30
SHOPS_PER_DAY = 30
# The playbooks whose capped messages are answered once the cap frees; a general chat's stay as they were.
REQUEUE_PLAYBOOKS = ("ic_shops",)
# A capped turn older than this is no longer taken up again (the customer's window would be closed anyway).
REQUEUE_WITHIN = dt.timedelta(hours=24)
# The sweep queues one capped turn again at most this often (a gate that still holds it back).
REQUEUE_EVERY = dt.timedelta(minutes=5)
REQUEUE_PAGE = 100
# The shops cap alert's priority (a hot customer is mid-exchange).
ALERT_PRIORITY = "high"
# Where a turn taken up again keeps when it was capped, and when the sweep queued it.
CAPPED_AT = "capped_at"
REQUEUED_AT = "requeued_at"


def limits(playbook: str) -> tuple[int, int]:
    """(replies an hour, replies a day) a chat of this playbook may send."""
    from . import engine

    if playbook == "ic_shops":
        return SHOPS_PER_HOUR, SHOPS_PER_DAY
    return engine.CAP_PER_HOUR, engine.CAP_PER_DAY


def reached(conversation, playbook: str, now) -> str:
    """'hour' or 'day' when this chat's replies reached its cap, else ''."""
    from . import engine

    per_hour, per_day = limits(playbook)
    if engine._ours_since(conversation, now - dt.timedelta(hours=1)) >= per_hour:
        return "hour"
    if engine._ours_since(conversation, now - dt.timedelta(hours=24)) >= per_day:
        return "day"
    return ""


def frees_at(conversation, playbook: str, now, which: str) -> dt.datetime | None:
    """When the cap that holds the chat frees: its oldest reply in the window, plus the window."""
    from apps.inbox.models import Message

    from . import engine

    window = dt.timedelta(hours=1) if which == "hour" else dt.timedelta(hours=24)
    per_hour, per_day = limits(playbook)
    cap = per_hour if which == "hour" else per_day
    rows = Message.objects.filter(
        conversation=conversation, direction=Message.Direction.OUTBOUND, payload__source=engine.SOURCE, created_at__gte=now - window
    ).order_by("created_at").values_list("created_at", "payload")
    starts: list = []
    seen: set = set()
    for created_at, payload in rows:
        turn = payload.get("turn") if isinstance(payload, dict) else None
        key = ("turn", str(turn)) if turn is not None else ("alone", len(starts))
        if key in seen:
            continue
        seen.add(key)
        starts.append(created_at)
    if len(starts) < cap:
        return None
    # The reply that must leave the window before one more may go.
    return starts[len(starts) - cap] + window


def alert(conversation, chat, playbook: str, words: str, now, which: str) -> None:
    """The cap alert: a general chat's as before (with their words, the lead and the chat); a shops chat's says
    the assistant answers by itself once the cap frees, is high priority and reaches the alert list too."""
    from . import alerts, engine, hours, people

    who = engine._who(conversation)
    shops_chat = playbook == "ic_shops"
    per_hour, per_day = limits(playbook)
    if playbook in REQUEUE_PLAYBOOKS:
        free = frees_at(conversation, playbook, now, which)
        when = f"at about {hours.time_label(free)}" if free is not None and which == "hour" else (
            "when the hour frees" if which == "hour" else "when its 24-hour limit frees, if their window is still open"
        )
        head = (
            f"The assistant reached its reply limit with {who} ({per_hour} replies an hour, {per_day} a day). It answers "
            f"their newest message by itself {when}, unless someone from the team writes first: take over if it cannot wait."
        )
        title = f"Reply limit reached: {who}"
    else:
        head = f"The assistant reached its reply limit with {who}. Please take over."
        title = "Lead AI paused in one chat"
    lines = [head, people.words_line(words), *people.where_lines(conversation, chat)]
    alerts.raise_alert(
        kind="cap",
        conversation=conversation,
        priority=ALERT_PRIORITY if shops_chat else "normal",
        title=title[:200],
        text="\n".join(line for line in lines if line),
        dedupe_key=f"cap:{conversation.pk}:{now:%Y%m%d}",
        crm_url=engine._crm_url(chat),
        listed=True if shops_chat else None,
    )


def reclaim(message, now):
    """The turn the cap held back for this message, taken up again now (the sweep queued it): the same row,
    RUNNING from ``now`` (when it was capped stays in its actions), or None when it is not a capped turn any
    more (another task took it up, or it was answered)."""
    from ..models import LeadAiTurn
    from . import engine

    turn = LeadAiTurn.objects.filter(inbound=message, status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON).first()
    if turn is None:
        return None
    kept = {CAPPED_AT: (turn.actions or {}).get(CAPPED_AT) or turn.created_at.isoformat()}
    taken = LeadAiTurn.objects.filter(pk=turn.pk, status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON).update(
        status=LeadAiTurn.Status.RUNNING, reason="", created_at=now, finished_at=None, actions=kept
    )
    if not taken:
        return None
    turn.refresh_from_db()
    return turn


def is_capped(message) -> bool:
    """This message's turn is one the cap held back."""
    from ..models import LeadAiTurn
    from . import engine

    return LeadAiTurn.objects.filter(inbound=message, status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON).exists()


def to_answer(now=None) -> list[int]:
    """The inbound messages whose capped turns may be answered now (one per chat, its newest), each stamped
    so the next sweeps leave it for REQUEUE_EVERY; the sweep queues them (tasks._answer_capped)."""
    from apps.inbox.models import Message

    from .. import lane
    from ..models import LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn
    from . import engine

    now = now or timezone.now()
    turns = list(
        LeadAiTurn.objects.filter(
            status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON, created_at__gte=now - REQUEUE_WITHIN, inbound__isnull=False
        )
        .select_related("inbound", "conversation__contact")
        .order_by("-pk")[:REQUEUE_PAGE]
    )
    if not turns:
        return []
    playbooks = lane.playbooks({turn.conversation_id for turn in turns})
    settings_row = LeadAiSettings.load()
    out: list[int] = []
    seen: set[int] = set()
    for turn in turns:
        if turn.conversation_id in seen:
            continue
        seen.add(turn.conversation_id)  # the chat's newest capped turn, or none of them
        playbook = playbooks.get(turn.conversation_id, "general")
        if playbook not in REQUEUE_PLAYBOOKS:
            continue
        stamped = (turn.actions or {}).get(REQUEUED_AT)
        if stamped:
            try:
                if now - dt.datetime.fromisoformat(str(stamped)) < REQUEUE_EVERY:
                    continue
            except ValueError:
                pass
        message, conversation = turn.inbound, turn.conversation
        if conversation.linked_conversation_id or not settings_row.answers(conversation.contact.wa_id):
            continue
        if not LeadAiChat.objects.filter(conversation=conversation, active=True).exists():
            continue
        if LeadAiChatState.objects.filter(conversation=conversation).filter(Q(stopped_at__isnull=False) | Q(paused_at__isnull=False)).exists():
            continue
        if engine._newer_inbound(message) is not None:
            continue  # a newer message has its own turn (answered, or capped too: then that one is the chat's)
        if Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, pk__gt=message.pk).exclude(kind="system").exists():
            continue  # someone wrote since (a colleague took over, or our side said something)
        if not engine._window_open(conversation, now) or reached(conversation, playbook, now):
            continue
        actions = {**(turn.actions or {}), REQUEUED_AT: now.isoformat()}
        if LeadAiTurn.objects.filter(pk=turn.pk, status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON).update(actions=actions):
            out.append(message.pk)
    return out
