"""The agent desk on the Lead AI screen (batch 2e spec §2.12 and §3.3; board T100, T94; Q30, Q37, Q39).

Nobody is named (Q30). The agents with Lead AI access follow the Lead AI chats on the Lead AI screen (Q37,
Matloob 2026-10-17: the chats are not assigned; lane.has_desk_access), so the desk is the record that stays: a
panel alert shows for seconds. What it adds to the Lead AI list (views.chat_list):

- the track of each shops-playbook chat ("Rent · Studio", "Shop", "Not known yet", chat_track): code's stored
  track, else what tracks.decide reads from what the chat knows with no new words (2d's facts.need, a lead context
  read already, the campaign template). A shops chat nobody has answered since 2e went live is a shop, as the engine
  will read it, never "Not known yet". ``?track=`` lists the chats of one track (track_ids);
- Needs a person (``?needs=1``, needs_rows): chats handed over, or paused for a broker, in which nobody from our team
  has written since (engine.person_wrote_since, as one SQL subquery), and the open tentatives that hold a time or
  wait for a full name (spec §2.6). The longest wait first, each row with why;
- Today (``?today=1``, today_rows): every open visit and call that starts today, Dubai time, by start time;
- the counts on those two buttons (counts);
- I'll call (take_call): the first agent to take a chat's call holds it, under a row lock; a second gets the first
  one's name back. The customer is never told who;
- the alerts for a booked call nobody has taken (call_alerts, the sweep): 15 minutes before it, and an urgent one
  10 minutes after its start, to everyone on the chat (alerts.LISTED_KINDS). Nothing goes to the customer (Q39).

It writes only the take (taken_by, taken_at) and raises the call alerts: no customer reply, no engine path and no
Bitrix write depends on this module.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from . import ic_templates, lane
from .models import LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState

logger = logging.getLogger(__name__)

# The list's ?track= values: the four filters, and the shops chats whose need nobody knows yet.
TRACK_FILTERS = ("shop", "rent", "sale", "other", "unknown")
UNKNOWN_FILTER = "unknown"

# Q39 (Matloob, 2026-10-17): a heads-up this long before a booked call nobody has taken, and an urgent alert this
# long after its start. Past CALL_LATE_UNTIL a call nobody took is history (the sweep closes it three hours on).
CALL_HEADS_UP = dt.timedelta(minutes=15)
CALL_LATE = dt.timedelta(minutes=10)
CALL_LATE_UNTIL = dt.timedelta(hours=2)
CALL_SOON = "call_soon"
CALL_UNTAKEN = "call_untaken"
# The most calls one sweep looks at.
CALL_PAGE = 100

# Why take_call took nothing.
NO_CALL = "no_call"
TAKEN = "taken"

# Why a chat needs a person (NeedRow.kinds), in the order a row names them.
HANDOVER = "handover"
BROKER = "broker"
HELD = "held"
_NEED_ORDER = {BROKER: 0, HANDOVER: 1, HELD: 2}


def agent_name(agent) -> str:
    return (agent.display_name or agent.get_username()) if agent is not None else ""


# The track ----------------------------------------------------------------------------------------------------------


def template_kinds(conversation_ids) -> dict:
    """{conversation id: ic_templates.kind} of the newest Lead AI campaign that reached each chat, else the campaign
    that put it on the screen: the template the chat answers, as lane.playbooks reads the playbook."""
    from apps.campaigns.models import CampaignRecipient

    ids = [int(pk) for pk in conversation_ids if pk]
    if not ids:
        return {}
    out = {
        conversation_id: ic_templates.kind(name)
        for conversation_id, name in LeadAiChat.objects.filter(conversation_id__in=ids, active=True).values_list(
            "conversation_id", "campaign__template__name"
        )
    }
    if out:
        sends = (
            CampaignRecipient.objects.filter(conversation_id__in=list(out), campaign__lead_ai__isnull=False)
            .order_by("pk")
            .values_list("conversation_id", "campaign__template__name")
        )
        for conversation_id, name in sends:  # oldest first: the newest is the one kept
            out[conversation_id] = ic_templates.kind(name)
    return out


def chat_track(playbook: str, state, template_kind: str = ic_templates.SHOP) -> tuple[str, str]:
    """(track, unit) of a chat for the desk. Off the shops playbook: ('', ''), since tracks run there only. On it:
    code's stored track (state.track, state.unit); while there is none, what tracks.decide reads from what the chat
    knows with no new words: 2d's facts.need, a lead context read already (never a Bitrix read here), the template."""
    from .assistant import tracks

    if playbook != lane.IC_SHOPS:
        return "", ""
    stored = str(getattr(state, "track", "") or "")
    unit = str(getattr(state, "unit", "") or "")
    if stored in tracks.TRACKS:
        return stored, unit
    facts = getattr(state, "facts", None)
    context = getattr(state, "lead_context", None)
    try:
        decision = tracks.decide(
            words=(),
            facts=facts if isinstance(facts, dict) else {},
            stored_unit=unit,
            lead=context if isinstance(context, dict) else {},
            template_kind=template_kind or ic_templates.SHOP,
        )
    except Exception:  # noqa: BLE001 - a chip is never worth failing the list
        logger.exception("Lead AI desk could not read the track of conversation %s", getattr(state, "conversation_id", None))
        return "", ""
    return decision.track, decision.unit


def track_part(playbook: str, state, template_kind: str = ic_templates.SHOP) -> dict:
    """The row's track for the panel: track, unit and the chip's words ("Rent · Studio", "Not known yet"); all '' off
    the shops playbook (no chip)."""
    from .assistant import tracks

    if playbook != lane.IC_SHOPS:
        return {"track": "", "unit": "", "track_label": ""}
    track, unit = chat_track(playbook, state, template_kind)
    return {"track": track, "unit": unit, "track_label": tracks.label(track, unit)}


def needs_template_kind(playbook: str, state) -> bool:
    """chat_track reads the template only for a shops chat with no stored track."""
    from .assistant import tracks

    return playbook == lane.IC_SHOPS and str(getattr(state, "track", "") or "") not in tracks.TRACKS


def track_ids(queryset, wanted: str) -> list[int]:
    """The ids among these chats whose desk track is ``wanted`` (TRACK_FILTERS; "unknown": a shops chat whose need
    nobody knows yet). The stored track decides in the query; only the chats with none are read further."""
    from .assistant import tracks

    target = "" if wanted == UNKNOWN_FILTER else wanted
    rows = list(queryset.order_by().values_list("pk", "lead_ai_state__track").distinct())
    scripts = lane.playbooks(pk for pk, _ in rows)
    out, pending = [], []
    for pk, stored in rows:
        if scripts.get(pk) != lane.IC_SHOPS:
            continue
        if stored in tracks.TRACKS:
            if stored == target:
                out.append(pk)
        else:
            pending.append(pk)
    if pending:
        kinds = template_kinds(pending)
        states = {
            state.conversation_id: state
            for state in LeadAiChatState.objects.filter(conversation_id__in=pending).only(
                "conversation_id", "track", "unit", "facts", "lead_context"
            )
        }
        for pk in pending:
            if chat_track(lane.IC_SHOPS, states.get(pk), kinds.get(pk, ic_templates.SHOP))[0] == target:
                out.append(pk)
    return out


# Needs a person -----------------------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class NeedRow:
    conversation_id: int
    since: dt.datetime | None
    reasons: tuple = ()  # why, in English for the agents ("Handed over: asked for a call", "Held 5:00 PM")
    kinds: tuple = ()  # HANDOVER, BROKER, HELD
    draft: bool = False  # the co-pilot's draft reply waits for the agent (assistant/copilot.py)

    def as_dict(self) -> dict:
        return {
            "view": "needs",
            "since": self.since.isoformat() if self.since else None,
            "reasons": list(self.reasons),
            "kinds": list(self.kinds),
            "draft": self.draft,
        }


def _person_since(field: str):
    """Someone from our team wrote in the chat since the state's ``field``: engine.person_wrote_since as a subquery.
    Anything outbound counts but our own (a payload source "leadai..."), a transfer's mirror, a system line and the
    chat's campaign templates."""
    from apps.campaigns.models import CampaignRecipient
    from apps.inbox.models import Message

    campaign_templates = (
        CampaignRecipient.objects.filter(conversation_id=OuterRef(OuterRef("conversation_id")))
        .exclude(campaign__template_id__isnull=True)
        .values("campaign__template_id")
    )
    rows = (
        Message.objects.filter(
            conversation_id=OuterRef("conversation_id"),
            direction=Message.Direction.OUTBOUND,
            mirrored_from__isnull=True,
            created_at__gte=OuterRef(field),
        )
        .exclude(kind="system")
        .exclude(Q(payload__has_key="source") & Q(payload__source__startswith="leadai"))
        .exclude(kind=Message.Kind.TEMPLATE, template_id__in=campaign_templates)
    )
    return Exists(rows)


def _set_in_bitrix_since(field: str):
    """A person set a Bot Status in Bitrix since the state's ``field`` (Handed to agent, Broker): they have the chat,
    as people.escalate_waiting reads it."""
    return Exists(LeadAiAlert.objects.filter(conversation_id=OuterRef("conversation_id"), kind="bitrix_status", created_at__gte=OuterRef(field)))


def when_label(start: dt.datetime, now: dt.datetime | None = None) -> str:
    """'5:00 PM' today (Dubai time), 'Mon 19 Oct, 5:00 PM' on any other day."""
    from .assistant import hours

    local = start.astimezone(hours.DUBAI)
    if hours.is_today(start, now):
        return hours.time_label(start)
    return f"{local:%a} {local.day} {local:%b}, {hours.time_label(start)}"


def _held_for_name(details) -> bool:
    """The full-name gate holds this tentative's time (spec §2.6: details.held_for_name, any value that says so)."""
    return isinstance(details, dict) and bool(details.get("held_for_name"))


def needs_rows(queryset, now: dt.datetime | None = None) -> list[NeedRow]:
    """The chats among these that need a person (spec §2.12.4), the longest wait first:

    - handed over, or paused for a broker, and nobody from our team has written since (the "Handed over" marker alone
      stays until the customer writes again, so it is not read on its own). Not one an agent paused, nor a handover
      or a Broker a person set in Bitrix: they have it;
    - an open tentative that holds a time, or waits for the customer's full name (a held name).

    A chat whose customer asked us to stop, or said no, is left out (as people.escalate_waiting leaves it)."""
    from . import bitrix_status
    from .assistant import engine

    now = now or timezone.now()
    chats = queryset.order_by().values("pk")
    states = LeadAiChatState.objects.filter(conversation_id__in=chats, stopped_at__isnull=True, not_interested_at__isnull=True)
    found: dict[int, list[tuple[str, dt.datetime | None, str]]] = {}

    handed = (
        states.filter(handed_over_at__isnull=False, paused_by__isnull=True)
        .exclude(handover_reason=bitrix_status.HANDED_REASON)
        .annotate(person=_person_since("handed_over_at"), bitrix=_set_in_bitrix_since("handed_over_at"))
        .filter(person=False, bitrix=False)
        .values_list("conversation_id", "handed_over_at", "handover_reason", "draft")
    )
    drafted: set[int] = set()
    for conversation_id, since, reason, draft in handed:
        if draft:
            drafted.add(conversation_id)  # the co-pilot's draft waits for the agent (copilot.py)
        if reason == engine.BROKER:
            found.setdefault(conversation_id, []).append((BROKER, since, "Broker: waiting for a person"))
        else:
            what = engine.HANDOVER_TEXT.get(reason, "needs a person")
            found.setdefault(conversation_id, []).append((HANDOVER, since, f"Handed over: {what}"))

    # The assistant's own pause for a broker, after its handover cleared (it stays paused until someone presses Resume).
    paused = (
        states.filter(paused_at__isnull=False, paused_by__isnull=True, handed_over_at__isnull=True)
        .annotate(person=_person_since("paused_at"), bitrix=_set_in_bitrix_since("paused_at"))
        .filter(person=False, bitrix=False)
        .values_list("conversation_id", "paused_at")
    )
    for conversation_id, since in paused:
        found.setdefault(conversation_id, []).append((BROKER, since, "Broker: waiting for a person"))

    held = (
        LeadAiAppointment.objects.filter(conversation_id__in=chats, status=LeadAiAppointment.Status.TENTATIVE)
        .exclude(conversation__lead_ai_state__stopped_at__isnull=False)
        .exclude(conversation__lead_ai_state__not_interested_at__isnull=False)
        .values_list("conversation_id", "starts_at", "details", "created_at")
    )
    for conversation_id, start, details, created in held:
        name_held = _held_for_name(details)
        if start is None and not name_held:
            continue
        when = when_label(start, now) if start is not None else ""
        if name_held:
            text = f"Held {when}: no full name yet" if when else "Waiting for their full name"
        else:
            text = f"Held {when}"
        found.setdefault(conversation_id, []).append((HELD, created, text))

    rows = []
    for conversation_id, items in found.items():
        items.sort(key=lambda item: _NEED_ORDER[item[0]])
        sinces = [since for _, since, _ in items if since is not None]
        rows.append(
            NeedRow(
                conversation_id=conversation_id,
                since=min(sinces) if sinces else None,
                reasons=tuple(dict.fromkeys(text for _, _, text in items)),
                kinds=tuple(dict.fromkeys(kind for kind, _, _ in items)),
                draft=conversation_id in drafted,
            )
        )
    far = now + dt.timedelta(days=3650)
    rows.sort(key=lambda row: (row.since or far, row.conversation_id))
    return rows


# Today --------------------------------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TodayRow:
    conversation_id: int
    appointment_id: int
    starts_at: dt.datetime
    label: str  # "Visit 4:00 PM", "Call 4:30 PM", "Held 5:00 PM"
    kind: str  # "visit", "call", "viewing", "held"
    taken_by: str = ""
    taken_by_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "view": "today",
            "appointment_id": self.appointment_id,
            "starts_at": self.starts_at.isoformat(),
            "label": self.label,
            "kind": self.kind,
            "taken_by": self.taken_by,
            "taken_by_id": self.taken_by_id,
        }


def today_window(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """Today in Dubai time, midnight to midnight."""
    from .assistant import hours

    start = dt.datetime.combine(hours.now_dubai(now).date(), dt.time.min, tzinfo=hours.DUBAI)
    return start, start + dt.timedelta(days=1)


def appointment_kind(appointment) -> str:
    """'held' for a tentative; else 'call', 'viewing' (at the customer's property) or 'visit' (our office)."""
    if appointment.status == LeadAiAppointment.Status.TENTATIVE:
        return "held"
    return {LeadAiAppointment.Place.CALL: "call", LeadAiAppointment.Place.CUSTOMER_PROPERTY: "viewing"}.get(appointment.place, "visit")


_KIND_WORDS = {"held": "Held", "call": "Call", "viewing": "Viewing", "visit": "Visit"}


def today_rows(queryset, now: dt.datetime | None = None) -> list[TodayRow]:
    """Every open visit and call among these chats that starts today, Dubai time, by start time (spec §2.12.5)."""
    from .assistant import hours

    start, end = today_window(now)
    rows = (
        LeadAiAppointment.objects.filter(
            conversation_id__in=queryset.order_by().values("pk"),
            status__in=LeadAiAppointment.OPEN,
            starts_at__gte=start,
            starts_at__lt=end,
        )
        .select_related("taken_by")
        .order_by("starts_at", "pk")
    )
    out = []
    for row in rows:
        kind = appointment_kind(row)
        out.append(
            TodayRow(
                conversation_id=row.conversation_id,
                appointment_id=row.pk,
                starts_at=row.starts_at,
                label=f"{_KIND_WORDS[kind]} {hours.time_label(row.starts_at)}",
                kind=kind,
                taken_by=agent_name(row.taken_by),
                taken_by_id=row.taken_by_id,
            )
        )
    return out


def counts(queryset, now: dt.datetime | None = None) -> dict:
    """The numbers on the Needs a person and Today buttons, for these chats."""
    return {"needs": len(needs_rows(queryset, now)), "today": len(today_rows(queryset, now))}


# The call card ------------------------------------------------------------------------------------------------------


def call_label(appointment) -> str:
    """'Sales call' for a buyer's call slot (details.track sale), 'Call' for any other call, '' for a visit."""
    if appointment is None or appointment.place != LeadAiAppointment.Place.CALL:
        return ""
    details = appointment.details if isinstance(appointment.details, dict) else {}
    return "Sales call" if details.get("track") == "sale" else "Call"


def takeable(appointment) -> bool:
    """An open call nobody has taken yet: the card offers I'll call."""
    return bool(
        appointment is not None
        and appointment.place == LeadAiAppointment.Place.CALL
        and appointment.status in LeadAiAppointment.OPEN
        and appointment.taken_by_id is None
    )


@dataclasses.dataclass(frozen=True)
class Take:
    appointment: LeadAiAppointment | None
    error: str = ""  # NO_CALL, TAKEN, or '' when this agent holds the call now
    taken_by: str = ""  # who holds it


def take_call(conversation, agent, now: dt.datetime | None = None) -> Take:
    """``agent`` takes the chat's open call (I'll call; spec §3.3 step 5): first come, first served, under a row lock.
    Already theirs: nothing changes. Someone else's: TAKEN, with that agent's name. No open call: NO_CALL. Nothing goes
    to the customer."""
    now = now or timezone.now()
    with transaction.atomic():
        row = (
            LeadAiAppointment.objects.select_for_update()
            .filter(conversation=conversation, status__in=LeadAiAppointment.OPEN, place=LeadAiAppointment.Place.CALL)
            .order_by("-pk")
            .first()
        )
        if row is None:
            return Take(None, NO_CALL)
        if row.taken_by_id is not None:
            holder = agent_name(row.taken_by)
            return Take(row, "" if row.taken_by_id == agent.pk else TAKEN, holder)
        row.taken_by = agent
        row.taken_at = now
        row.log("taken", by=agent_name(agent))
        row.save(update_fields=["taken_by", "taken_at", "history", "updated_at"])
    return Take(row, "", agent_name(agent))


# A booked call nobody has taken (Q39) -------------------------------------------------------------------------------


def _booked_at(appointment) -> dt.datetime:
    """When the call was booked at its current time: its newest booking line in the history, else when it was made."""
    newest = appointment.created_at
    for entry in reversed(appointment.history or []):
        if not isinstance(entry, dict) or entry.get("event") not in ("confirmed", "rescheduled", "booked", "call_booked", "moved"):
            continue
        try:
            said = dt.datetime.fromisoformat(str(entry.get("at") or ""))
        except ValueError:
            break
        said = said if said.tzinfo is not None else said.replace(tzinfo=dt.timezone.utc)
        return max(said, newest) if newest else said
    return newest


def call_due(appointment, now: dt.datetime) -> str:
    """CALL_SOON in the 15 minutes before an untaken call (not for one booked inside them: its booking alert is the
    heads-up), CALL_UNTAKEN from 10 minutes after its start (for two hours), else ''."""
    start = appointment.starts_at
    if start is None:
        return ""
    if start > now:
        if start - now > CALL_HEADS_UP:
            return ""
        booked = _booked_at(appointment)
        return CALL_SOON if booked is None or booked <= start - CALL_HEADS_UP else ""
    if CALL_LATE <= now - start < CALL_LATE_UNTIL:
        return CALL_UNTAKEN
    return ""


def _gone_quiet(conversation) -> bool:
    """The customer asked us to stop, declined, or is on the opt-out registry: nobody is to call them."""
    from . import optout

    state = LeadAiChatState.objects.filter(conversation=conversation).only("stopped_at", "not_interested_at").first()
    if state is not None and (state.stopped_at is not None or state.not_interested_at is not None):
        return True
    return optout.is_blocked(conversation.contact.wa_id)


def _call_alert_text(appointment, kind: str, now: dt.datetime) -> tuple[str, str]:
    from .assistant import hours

    conversation = appointment.conversation
    wa = conversation.contact.wa_id
    who = (appointment.customer_name or conversation.contact.display_name or "").strip() or f"+{wa}"
    when = hours.time_label(appointment.starts_at)
    what = "a 5-minute call with our sales team" if call_label(appointment) == "Sales call" else "a call"
    if kind == CALL_SOON:
        title = f"Call at {when}, nobody has taken it yet: {who}"
        text = (
            f"{who} (WhatsApp +{wa}) is booked for {what} at {when}, and nobody has taken it yet. "
            f"Press I'll call on the Lead AI screen, then call them on +{wa}."
        )
    else:
        minutes = max(int((now - appointment.starts_at).total_seconds() // 60), int(CALL_LATE.total_seconds() // 60))
        title = f"Nobody has taken the call with {who} yet"
        text = (
            f"{who} (WhatsApp +{wa}) was booked for {what} at {when}, {minutes} minutes ago, and nobody has pressed "
            f"I'll call. Take it on the Lead AI screen and call them on +{wa}: apologise for the wait, or offer a new time. "
            "The assistant has written nothing to them about it."
        )
    return title, text


def call_alerts(now: dt.datetime | None = None) -> int:
    """The sweep (tasks.send_due_reminders): a heads-up 15 minutes before a booked call nobody has taken, and an urgent
    alert 10 minutes after its start, once each per call and start time, to everyone on the chat (Q39). Nothing goes to
    the customer. How many alerts went."""
    from .assistant import alerts

    now = now or timezone.now()
    rows = (
        LeadAiAppointment.objects.filter(
            status=LeadAiAppointment.Status.CONFIRMED,
            place=LeadAiAppointment.Place.CALL,
            taken_by__isnull=True,
            starts_at__gt=now - CALL_LATE_UNTIL,
            starts_at__lte=now + CALL_HEADS_UP,
        )
        .select_related("conversation__contact")
        .order_by("starts_at", "pk")[:CALL_PAGE]
    )
    sent = 0
    for row in rows:
        kind = call_due(row, now)
        if not kind:
            continue
        key = f"{kind}:{row.pk}:{row.starts_at:%Y%m%d%H%M}"
        if LeadAiAlert.objects.filter(appointment_id=row.pk, kind=kind, dedupe_key__startswith=f"{key}:").exists():
            continue
        if _gone_quiet(row.conversation):
            continue
        title, text = _call_alert_text(row, kind, now)
        created = alerts.raise_alert(
            kind=kind,
            conversation=row.conversation,
            appointment=row,
            title=title,
            text=text,
            priority=LeadAiAlert.Priority.HIGH if kind == CALL_UNTAKEN else LeadAiAlert.Priority.NORMAL,
            dedupe_key=key,
            crm_url=alerts.crm_path(row.crm_entity, row.crm_id),
        )
        sent += len(created)
    return sent
