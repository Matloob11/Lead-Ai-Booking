"""The lead score (the advance plan's F1): hot, warm or cold with its reasons, computed by code from the chat's facts and
events — never by the model alone — stored on the chat's state (LeadAiChatState.score, score_reasons, scored_at), written
to the lead's own fields when it changes (UF_CRM_A7_AI_SCORE, a number; UF_CRM_A7_AI_SCORE_WHY, a text: Cursor's C50 and
C65) and shown on the desk, which can sort hot first.

What counts (``compute``), in points on 0–100: they wrote at all; the unit, the deal, the budget, the area and the move-in
known; a full name given; a visit or call booked, held or done, or cancelled; how fast they answer us; the model's own
"wants to move fast" on a visit today; and the quiet (a chat silent for days cools down, so the daily rescore keeps the
figure honest). A chat that said no, opted out or is a broker's scores 0 or thereabouts whatever else it holds. The reasons
are English words for the desk and the lead, never the customer's own.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import re
import statistics

logger = logging.getLogger(__name__)

HOT, WARM, COLD = "hot", "warm", "cold"
HOT_FROM, WARM_FROM = 70, 40
REASONS_MAX = 255  # the state's column; the lead's text field takes 1000
QUIET_AFTER = dt.timedelta(days=3)
QUIET_LONG = dt.timedelta(days=7)
FAST_MINUTES = 60
SLOW_MINUTES = 24 * 60
RECENT_EXCHANGES = 6
RESCORE_AT_MOST = 500
UNITS_KNOWN = frozenset({"studio", "one_br", "two_plus", "villa", "townhouse", "shop"})
# A move-in or buying timeline near enough to count ("next month", "immediately", "within 2 weeks", "in 30 days"): two
# months at most; "within 3 months" or "next year" is known, not soon.
_SOON = re.compile(
    r"\b(?:immediately|asap|urgent(?:ly)?|now|this\s+(?:week|month)|next\s+(?:week|month)|within\s+(?:a|\d+)\s+(?:days?|weeks?)"
    r"|within\s+(?:a|1|2|one|two)\s+months?|in\s+(?:a|\d+|two|three|four)\s+(?:days?|weeks?)|(?:1|2|one|two)\s+months?|\d{1,2}\s+days)\b",
    re.IGNORECASE,
)


@dataclasses.dataclass(frozen=True)
class Score:
    value: int
    reasons: tuple

    @property
    def label(self) -> str:
        return label_of(self.value)

    @property
    def text(self) -> str:
        """"Hot 82: visit booked; unit known; budget known" — the lead's text field and the desk's title."""
        return f"{self.label.title()} {self.value}: {'; '.join(self.reasons) or 'nothing known yet'}"[:REASONS_MAX]


def label_of(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return COLD
    return HOT if number >= HOT_FROM else WARM if number >= WARM_FROM else COLD


def compute(
    *,
    facts: dict | None,
    track: str = "",
    unit: str = "",
    now,
    last_inbound_at=None,
    reply_minutes=(),
    appointment=None,
    hot: bool = False,
    handover_reason: str = "",
    not_interested: bool = False,
    stopped: bool = False,
) -> Score:
    """The score from what the chat holds (pure; tested). ``appointment``: the chat's latest (any status), or None;
    ``reply_minutes``: how many minutes they took to answer our last few messages (reply_minutes_for); ``hot``: the
    model's hot_lead on a visit today (engine._apply's done["hot_lead"])."""
    facts = facts or {}
    if stopped:
        return Score(0, ("opted out",))
    if not_interested:
        return Score(0, ("not interested",))
    if handover_reason == "broker_or_for_client" or facts.get("for_client") is True:
        return Score(5, ("broker or for a client",))
    points = 0
    reasons: list[str] = []

    def add(amount: int, reason: str) -> None:
        nonlocal points
        points += amount
        reasons.append(reason)

    if last_inbound_at is not None:
        add(10, "they wrote")
    if unit in UNITS_KNOWN:
        add(15, "unit known")
    if track in ("rent", "sale"):
        add(5, f"to {track.replace('sale', 'buy')}" if track == "sale" else "to rent")
    if _budget_known(facts):
        add(10, "budget known")
    if facts.get("clusters") or facts.get("cluster_flexible") is True or facts.get("community"):
        add(5, "area known")
    when = str(facts.get("move_in") or facts.get("buy_timeline") or "").strip()
    if when:
        add(10 if _SOON.search(when) else 3, "moving soon" if _SOON.search(when) else "move-in known")
    if str(facts.get("full_name") or "").strip():
        add(5, "full name given")
    if appointment is not None:
        status = getattr(appointment, "status", "")
        place = "call" if getattr(appointment, "place", "") == "call" else "visit"
        starts_at = getattr(appointment, "starts_at", None)
        if status == "confirmed" and (starts_at is None or starts_at >= now):
            add(25, f"{place} booked")
        elif status == "done":
            add(30, f"{place} done")
        elif status == "tentative":
            add(10, "time held")
        elif status == "cancelled":
            add(-15, f"{place} cancelled")
    minutes = [int(value) for value in reply_minutes or () if value is not None]
    if minutes:
        median = statistics.median(minutes)
        if median <= FAST_MINUTES:
            add(10, "replies within the hour")
        elif median > SLOW_MINUTES:
            add(-5, "slow to reply")
    if hot:
        add(10, "wants to move fast")
    if handover_reason == "abroad_cannot_visit":
        add(-5, "abroad")
    if last_inbound_at is not None:
        quiet = now - last_inbound_at
        if quiet >= QUIET_LONG:
            add(-20, f"quiet {quiet.days} days")
        elif quiet >= QUIET_AFTER:
            add(-10, f"quiet {quiet.days} days")
    return Score(max(0, min(100, points)), tuple(reasons))


def _budget_known(facts: dict) -> bool:
    amount = facts.get("budget_aed")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount > 0:
        return True
    return bool(str(facts.get("budget") or "").strip())


# ---- the chat ------------------------------------------------------------------------------------------------------------


def reply_minutes_for(conversation, limit: int = RECENT_EXCHANGES) -> list[int]:
    """How many minutes the customer took to answer each of our last ``limit`` messages they did answer (an outbound
    followed by an inbound; reactions and system rows skipped), oldest first."""
    from apps.inbox.models import Message

    rows = list(
        Message.objects.filter(conversation=conversation)
        .exclude(kind__in=("reaction", "system"))
        .order_by("-created_at", "-pk")
        .values_list("direction", "created_at")[: limit * 8]
    )
    rows.reverse()
    minutes: list[int] = []
    last_ours = None
    for direction, created_at in rows:
        if direction == Message.Direction.OUTBOUND:
            last_ours = created_at
        elif direction == Message.Direction.INBOUND and last_ours is not None:
            minutes.append(max(0, int((created_at - last_ours).total_seconds() // 60)))
            last_ours = None
    return minutes[-limit:]


def last_inbound_at(conversation):
    from apps.inbox.models import Message

    return (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.INBOUND)
        .exclude(kind__in=("reaction", "system"))
        .order_by("-created_at", "-pk")
        .values_list("created_at", flat=True)
        .first()
    )


def update(conversation, state, *, now, hot: bool = False) -> tuple[Score, bool]:
    """The chat's score computed and stored on ``state`` (score, score_reasons, scored_at; saved): (the score, whether
    the value changed). Reads the chat's latest appointment and their reply times itself."""
    from ..models import LeadAiAppointment

    appointment = LeadAiAppointment.objects.filter(conversation=conversation).order_by("-pk").first()
    scored = compute(
        facts=state.facts or {},
        track=state.track or "",
        unit=state.unit or "",
        now=now,
        last_inbound_at=last_inbound_at(conversation),
        reply_minutes=reply_minutes_for(conversation),
        appointment=appointment,
        hot=hot,
        handover_reason=state.handover_reason or "",
        not_interested=state.not_interested_at is not None,
        stopped=state.stopped_at is not None,
    )
    changed = state.score != scored.value
    state.score = scored.value
    state.score_reasons = scored.text
    state.scored_at = now
    state.save(update_fields=["score", "score_reasons", "scored_at", "updated_at"])
    return scored, changed


def writes(scored: Score) -> list:
    """The two lead fields' writes for crm_fields.queue (the number and the reasons; the tool's allow-list, C65)."""
    from . import crm_fields

    return [(crm_fields.FIELD_AI_SCORE, scored.value, {}), (crm_fields.FIELD_AI_SCORE_WHY, scored.text, {})]


def rescore_quiet(now) -> int:
    """The chats scored above 0 whose customer has been quiet for QUIET_AFTER, scored again (the quiet cools them) and
    written to the lead when the value moved: once a day from the digest's sweep (tasks._daily_digest). How many moved."""
    from ..models import LeadAiChat, LeadAiChatState
    from . import crm_fields

    moved = 0
    rows = (
        LeadAiChatState.objects.filter(score__gt=0, conversation__last_message_at__lt=now - QUIET_AFTER)
        .exclude(scored_at__gte=now - dt.timedelta(hours=20))
        .select_related("conversation")
        .order_by("scored_at", "pk")[:RESCORE_AT_MOST]
    )
    for state in rows:
        conversation = state.conversation
        scored, changed = update(conversation, state, now=now)
        if not changed:
            continue
        moved += 1
        chat = LeadAiChat.objects.filter(conversation=conversation, active=True).first()
        if chat is not None:
            crm_fields.queue(conversation, chat, writes(scored))
    if moved:
        logger.info("Lead AI score: %s quiet chat(s) cooled down", moved)
    return moved
