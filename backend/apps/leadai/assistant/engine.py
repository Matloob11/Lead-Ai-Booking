"""One assistant turn: from a customer's message in a Lead AI chat to our reply.

The order matters, and each step can end the turn:
1. gates      a Lead AI chat, not transferred, the message not deleted by the
              customer and not handled already;
2. debounce   a newer customer message exists (a reminder tap does not count:
              its own handler answers it), or the customer is still typing
              -> the newest message's turn answers the whole burst;
3. opt-out    a STOP, wrong number or "not interested" as the last thing the
              customer said is recorded at once, whatever else is true (the
              assistant off, paused, at its limits), so no reminder follows;
              the polite line goes out only when the assistant may speak;
4. gates      the assistant on (or the customer is a test number), the key
              set, no OpenAI breaker, not stopped or paused, not stale;
5. voices     voice notes are transcribed BEFORE the claim, waiting for the
              gateway's download (15/30/60/90 s), so a retry is not blocked
              by its own claim;
6. claim      a LeadAiTurn row unique on the inbound message;
7. people     anyone from our team who wrote after this message (panel OR the
              WhatsApp Business app, which leaves no sender) has answered it;
8. limits     window open, per-chat caps, the global daily ceiling;
9. rules      unsupported messages, automatic replies and plain
              acknowledgements, judged on the whole burst, need no model;
10. model     one structured answer, checked by hours.py and against the
              customer's own words; one corrective retry, time permitting;
11. re-check  still ours right before sending (no agent reply, no newer
              message, not moved, paused, stopped or switched off);
12. send      the reply; booking messages are written by code (filters.py);
13. apply     after the send: facts, state, appointment, then the CRM work
              and the agents' alerts.
No OpenAI, gateway or Bitrix call ever runs inside a database transaction.

The office takes one client per 30-minute slot (hours.free_slots): a time
another chat's open office visit holds is refused with the two nearest free
ones, whatever the playbook, and so is a tentative visit kept at such a time;
those two come from code when the model would offer others. A shops chat
(lane.IC_SHOPS) has its own rules before the model (the yes, "Not now",
"Should I check back in a month?", a no after "already rented", "Stop
messages", a plain chain message or scam), its own prompt, schema and context,
guards that turn an open "when would you like to come?" into two free slots
and an invitation made before the licence is known into the licence question,
its own booking message (shops.confirmation) and its Bitrix fields
(crm_fields.py). A shops chat also has its steps (shop_flow.py): the list of the
three shop types, a type's video, photos and detail card (sent by their own
task), the two free slots for [Book viewing] and for "Need to reschedule", the
request for a copy of a DED or Trakhees licence and that copy arriving; and its
recommendation names the customer's own business. A shops chat's Template B (the
automatic follow-up, followups.py) is answered like the campaign: its [Yes, book a
viewing] is the first yes, and from someone we know is an end user it gets two free
slots; its context also carries the old lead's first inquiry date and CRM notes, as
data (lead_history.py; board T28). In a shops chat a confirm of a time the customer
neither gave nor took (a yes to a nudge's "Shall I book you for this evening?") is
no booking but the two free slots for it (unasked_confirm; their own hour in any
form, a walk-in or a pick from our slots stands: their_time), and the licence copy is
asked for even when the model's own invitation recorded a tentative visit, never
over one in the customer's own words (model_step, wants_to_come); that request is
answered and nudged like a question. A shops chat records no visit for the model's
own slot offer: a tentative at a day and hour the customer neither gave nor took is
none, unless they said yes or say they will come, and then it keeps their words and
never our time (own_offer); slots offered again after words that turn nothing down
are that same invitation, neither counted nor cut (reoffered); and a request for
photos, a video or the shop types gets its step over a tentative that is not theirs,
which then changes nothing (model_step, comes). Every chat: a deferral said
with a day or an hour is still a deferral, and "How do I reach there?" once the
location went out gets a line pointing to it; a reply not in the script the
customer types in, English letters included, is asked for once more, and code's
lines follow that script (script.py); the time already booked, said again, changes
nothing and is not confirmed a second time unless they ask for it (_said_again,
asks_for_booking); a STOP, a wrong number or spam blocks the phone on every campaign
(optout.py). A general chat otherwise keeps every rule it had.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field

from celery.exceptions import SoftTimeLimitExceeded
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inbox.models import Message

from .. import lane
from ..models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn
from . import (
    alerts,
    crm_fields,
    filters,
    hours,
    lead_history,
    live,
    nudges,
    openai_client,
    prompt,
    reminders,
    rules,
    schema,
    script,
    shop_flow,
    shops,
    transcribe,
    transcript,
)

logger = logging.getLogger(__name__)

SOURCE = transcript.ASSISTANT
CAP_PER_DAY = 20
CAP_PER_HOUR = 6
STALE_AFTER = dt.timedelta(minutes=15)
STILL_TYPING = dt.timedelta(seconds=8)
MAX_DEBOUNCE = dt.timedelta(seconds=40)
WINDOW_MARGIN = dt.timedelta(minutes=2)
AUDIO_WAITS = (15, 30, 60, 90)
HANDOVER_QUIET = dt.timedelta(hours=12)
HOLDING_EVERY = dt.timedelta(hours=2)
# The office's address or Maps link goes out once in this long, unless the customer asks for it.
LOCATION_FRESH = dt.timedelta(hours=24)
BREAKER_FAILURES = 3
BREAKER_PAUSE = dt.timedelta(minutes=5)
# Seconds of OpenAI time one turn may use, inside the task's 180 s soft limit;
# the corrective second call is made only with this much still left.
TURN_BUDGET = 140
CORRECTION_NEEDS = 35
SKIP_KINDS = ("reaction", "system")
HIGH_HANDOVER = ("customer_asked_human", "call_requested", "complaint_or_upset", "owner_viewing_slot")
# A broker, or someone asking for a client (owner's choice 2026-10-13): the chat
# gets the inbox label BROKER_LABEL, and the assistant stays silent in it until
# an agent presses Resume.
BROKER = "broker_or_for_client"
BROKER_LABEL = "Broker"
BROKER_COLOUR = "#d97706"
# A slot refused for the office's hours: only a colleague can agree one.
HOURS_CODES = ("sunday", "closed", "before_open", "after_latest")
NO_TIME = {"action": "none", "place": None, "date": None, "time": None, "customer_words": None}
WALK_IN = dt.timedelta(minutes=45)

_URGENT = re.compile(
    r"\b(today|tomorrow|this week|asap|urgent(ly)?|immediately|right away|right now|as soon as possible|"
    r"within (a|one|two|three|a few|few) (day|days|week))\b",
    re.IGNORECASE,
)
_NOT_URGENT = re.compile(r"\b(not|no|don'?t|dont|never|maybe|later|next (month|year))\b", re.IGNORECASE)
# What tells us the customer named an hour: digits in any script, or the words for one.
_HOUR_WORDS = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon|midday|"
    r"ek|teen|char|chaar|panch|paanch|chhe|chay|saat|aath|nau|das|gyarah|giyarah|barah|baarah|baje|bajay|bjy)\b"
    r"|الواحدة|الثانية|الثالثة|الرابعة|الخامسة|السادسة|السابعة|الثامنة|التاسعة|العاشرة|عشرة|الظهر"
    r"|خمسة|ستة|سبعة|ثمانية|تسعة|أربعة|اربعة|ثلاثة"
    r"|ایک|تین|چار|پانچ|چھ|سات|آٹھ|گیارہ|بارہ|بجے"
    r"|एक|दो|तीन|चार|पांच|पाँच|छह|सात|आठ|नौ|दस|ग्यारह|बारह|बजे",
    re.IGNORECASE,
)
_NOW_WORDS = re.compile(
    r"(\b(now|right now|asap|outside|downstairs|on my way|on the way|coming|abhi|abhee)\b|الآن|الان|ابھی|अभी)",
    re.IGNORECASE,
)
# A time for a call, not a visit ("Call me Wednesday at 5 pm").
_CALL_WORDS = re.compile(
    r"\b(call|calls|calling|phone|ring|video)\b|اتصل|اتصال|مكالمة|كلمني|کال|فون|कॉल|फ़ोन|फोन",
    re.IGNORECASE,
)
# They are coming to us now ("I'm outside", "on my way", "coming now"): read in the
# burst alone, never in the chat's history ("I need a shop right now" an hour ago).
_WALK_IN_WORDS = re.compile(
    r"\b(?:on my way|on the way|outside|downstairs|in front of|i'?m here|i am here|we'?re here|we are here|"
    r"(?:i'?m|i am|we'?re|we are) coming|reached|arrived|almost there|(?:coming|come|leaving|left) (?:right )?now|"
    r"(?:coming|reaching|reach|be there|there) in \d+ ?(?:min|mins|minutes))\b"
    r"|\babhi (?:aa|aaya|aata|aati|nikal|pahunch)|\b(?:raste|raaste) (?:mein|main|me)\b|\b(?:pahunch|pohanch) gaya\b"
    r"|في الطريق|بالطريق|وصلت|انا برا|أنا برا|راستے میں|پہنچ گیا|ابھی آ|रास्ते में|पहुँच गया|पहुंच गया|अभी आ",
    re.IGNORECASE,
)
# The pg_advisory_lock key of the office's booking slots (engine.office_lock): any fixed number.
OFFICE_LOCK = 7_301_202_610
OFFICE_LOCK_WAIT = 20  # seconds; a booking then goes ahead on its own (and says so in the log)


class NotReady(Exception):
    """Wait and run the turn again (a voice note downloading, the customer typing)."""

    def __init__(self, countdown: int, reason: str = ""):
        super().__init__(reason or "not ready")
        self.countdown = countdown
        self.reason = reason


@dataclass
class Outcome:
    status: str
    reason: str = ""
    reply_message_id: int | None = None
    actions: dict = field(default_factory=dict)


def _skip(reason: str, **actions) -> Outcome:
    return Outcome(LeadAiTurn.Status.SKIPPED, reason, actions=actions)


def _who(conversation) -> str:
    return conversation.contact.display_name or f"+{conversation.contact.wa_id}"


def _crm_url(chat) -> str:
    return alerts.crm_path(chat.crm_entity, chat.crm_id) if chat is not None else ""


# Looking at the chat --------------------------------------------------------------


def _load(message_id: int):
    return (
        Message.objects.select_related(
            "conversation",
            "conversation__contact",
            "conversation__number",
            "conversation__assigned_agent",
            "media",
            "reply_to",
        )
        .filter(pk=message_id)
        .first()
    )


def _answerable(rows):
    return rows.exclude(kind__in=SKIP_KINDS).exclude(mirrored_from__isnull=False).exclude(transcript.REVOKED)


def _newer_inbound(message) -> Message | None:
    """The newest customer message after this one. A tap on our reminder does not
    count: its own handler answers it, and what was typed before it still needs us."""
    rows = _answerable(
        Message.objects.filter(
            conversation_id=message.conversation_id,
            direction=Message.Direction.INBOUND,
            pk__gt=message.pk,
        )
    ).order_by("-pk")[:10]
    for row in rows:
        if not reminders.looks_like_tap(row):
            return row
    return None


def _is_deleted(message) -> bool:
    """The customer deleted this message for everyone (a later revoke row names it)."""
    if not message.wamid:
        return False
    return (
        Message.objects.filter(conversation_id=message.conversation_id, direction=Message.Direction.INBOUND)
        .filter(transcript.REVOKED)
        .filter(payload__revoke__original_message_id=message.wamid)
        .exists()
    )


def _burst(conversation, message, revoked: set[str]) -> list:
    """The customer's messages since anyone from our side last wrote, up to this one,
    without deleted ones and without taps on our reminder (their handler answers those)."""
    last_out = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND)
        .order_by("-pk")
        .values_list("pk", flat=True)
        .first()
    )
    rows = _answerable(
        Message.objects.filter(conversation=conversation, direction=Message.Direction.INBOUND, pk__lte=message.pk)
    )
    if last_out:
        rows = rows.filter(pk__gt=last_out)
    rows = list(rows.select_related("media", "reply_to").order_by("-pk")[:10])
    rows.reverse()
    rows = [
        row
        for row in rows
        if not transcript.is_deleted(row, revoked) and (row.pk == message.pk or not reminders.looks_like_tap(row))
    ]
    return rows or [message]


def _is_ack(item) -> bool:
    return item.kind == "sticker" or (item.kind == "text" and rules.is_acknowledgement((item.body or "").strip()))


def _said(burst) -> list:
    """What the customer actually said: the burst without its trailing "ok", emoji or sticker."""
    return [item for item in burst if not _is_ack(item)]


def _tap_label(item) -> str:
    """The button a customer tapped (a template quick reply or one of our buttons), else ''."""
    data = transcript.payload(item)
    if item.kind == "button":
        return str((data.get("button") or {}).get("text") or item.body or "").strip()
    if item.kind == "interactive":
        reply = (data.get("interactive") or {}).get("button_reply") or (data.get("interactive") or {}).get("list_reply") or {}
        return str(reply.get("title") or item.body or "").strip()
    return ""


def _tap_id(item) -> str:
    """The id of an interactive reply (our list's row, our card's button), else ''."""
    if item.kind != "interactive":
        return ""
    interactive = transcript.payload(item).get("interactive") or {}
    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
    return str(reply.get("id") or "")


def _media_of(item) -> tuple[str, str]:
    """(mime type, file name) of an inbound attachment: the stored asset's, else the webhook's."""
    asset = getattr(item, "media", None)
    part = transcript.payload(item).get(item.kind) or {}
    part = part if isinstance(part, dict) else {}
    mime = (asset.mime_type if asset is not None else "") or part.get("mime_type") or ""
    name = (asset.file_name if asset is not None else "") or part.get("filename") or ""
    return str(mime), str(name)


def _licence_copy(item) -> bool:
    """A photo or a PDF: what may be the customer's licence copy."""
    return shop_flow.is_licence_media(item.kind, *_media_of(item))


def _is_licence_ask(message) -> bool:
    """Our message is the request for the licence copy (shop_flow LICENCE_ASK)."""
    return message is not None and transcript.payload(message).get("shop_step") == shop_flow.LICENCE_ASK


def _item_opt_out(item, meeting_open: bool, shops_chat: bool = False) -> str | None:
    """``shops_chat``: a shops chat also takes "Stop messages" (its template's button)."""
    text = (item.body or "").strip()
    if item.kind in ("button", "interactive"):
        label = _tap_label(item)
        return rules.opt_out_from_button(label) or (rules.shops_opt_out(label) if shops_chat else None)
    if item.kind == "text":
        if meeting_open and rules.is_meeting_cancel(text):
            # "الغاء" / "cancel" with a meeting booked: the model records a cancel.
            return None
        return rules.opt_out_from_text(text) or (rules.shops_opt_out(text) if shops_chat else None)
    return None


def _burst_opt_out(burst, meeting_open: bool, shops_chat: bool = False) -> str | None:
    """An opt-out is the last thing the customer said ("STOP" then "🙏" is still a
    STOP; "Stop" then "sending studios, I need a 2BR" is not)."""
    said = _said(burst)
    key = said[-1] if said else burst[-1]
    return _item_opt_out(key, meeting_open, shops_chat)


def _their_words(burst, heard: dict | None = None) -> str:
    """What the customer said in this burst, acknowledgements aside: a lost lead's
    reason ("Not Interested" for that button, a voice note's words)."""
    said = _said(burst) or burst
    words = [_tap_label(item) or transcript.inbound_text(item, (heard or {}).get(item.pk)) for item in said]
    return " ".join(word for word in words if word).strip()[:255]


def human_after(message, campaign_templates: set[int], since=None) -> bool:
    """Did anyone from our team write after this message? Panel, phone app or not.

    Ours (payload.source 'leadai...') and the campaign's own templates do not
    count; everything else does, whatever its sender column says.
    """
    rows = Message.objects.filter(
        conversation_id=message.conversation_id,
        direction=Message.Direction.OUTBOUND,
        mirrored_from__isnull=True,
    ).exclude(kind="system")
    if since is not None:
        rows = rows.filter(created_at__gte=since)
    else:
        rows = rows.filter(Q(pk__gt=message.pk) | Q(created_at__gt=message.created_at))
    for row in rows.only("pk", "kind", "payload", "template_id"):
        if transcript.is_ours(row):
            continue
        if row.kind == Message.Kind.TEMPLATE and row.template_id in campaign_templates:
            continue
        return True
    return False


def _agent_spoke_last(conversation, campaign_templates: set[int]) -> bool:
    """Of our side's messages, the newest is a colleague's, not the assistant's."""
    rows = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, mirrored_from__isnull=True)
        .exclude(kind="system")
        .order_by("-pk")
        .only("pk", "kind", "payload", "template_id")[:20]
    )
    for row in rows:
        if transcript.is_ours(row):
            return False
        if row.kind == Message.Kind.TEMPLATE and row.template_id in campaign_templates:
            continue
        return True
    return False


def _ours_since(conversation, since: dt.datetime) -> int:
    """How many replies the assistant sent here since then (the per-chat caps): the messages of
    one turn are one reply (a type's video, its photos and its card; a booking and its pin), and a
    message of no turn (a nudge) is one each."""
    payloads = Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        payload__source=SOURCE,
        created_at__gte=since,
    ).values_list("payload", flat=True)
    turns: set = set()
    alone = 0
    for payload in payloads:
        turn = payload.get("turn") if isinstance(payload, dict) else None
        if turn is None:
            alone += 1
        else:
            turns.add(str(turn))
    return len(turns) + alone


def _open_appointment(conversation) -> LeadAiAppointment | None:
    return (
        LeadAiAppointment.objects.filter(conversation=conversation, status__in=LeadAiAppointment.OPEN)
        .order_by("-pk")
        .first()
    )


def _customer_name(conversation, facts: dict) -> str:
    """The customer's name: the first of the facts, the campaign's recipient and the
    contact that names someone to greet, never a portal lead's title ("Bayut
    WhatsApp | Md Sumon" is "Md Sumon", filters.person_name), the campaign's
    "there" for a lead with no name, or a lone "Md" (filters.first_name)."""
    name = filters.person_name(facts.get("customer_name"))
    if filters.first_name(name):
        return name
    from apps.campaigns.models import CampaignRecipient

    recipient = (
        CampaignRecipient.objects.filter(conversation=conversation)
        .exclude(name="")
        .order_by("-pk")
        .values_list("name", flat=True)
        .first()
    )
    for candidate in (recipient, conversation.contact.display_name):
        name = filters.person_name(candidate)
        if filters.first_name(name):
            return name
    return ""


def _last_segment(conversation) -> str:
    """The segment the model judged last in this chat ('' before its first answer)."""
    actions = (
        LeadAiTurn.objects.filter(conversation=conversation, calls__gt=0)
        .order_by("-pk")
        .values_list("actions", flat=True)
        .first()
    )
    return str(actions.get("segment") or "") if isinstance(actions, dict) else ""


def _segment_hint(conversation, chat, campaign_msg) -> str:
    from apps.campaigns.models import CampaignRecipient

    from ..lane import _owner_data_chosen

    recipient = CampaignRecipient.objects.filter(conversation=conversation).select_related("campaign").order_by("-pk").first()
    parts = []
    if recipient is not None:
        # Every send fills owner_data_id (with whatever card carries the phone):
        # only a campaign from the Owner Data popup is about an owner's card.
        if recipient.owner_data_id and _owner_data_chosen(recipient.campaign):
            parts.append("record: Owner Data card (a property owner)")
        if recipient.crm_deal_id:
            parts.append("record: deal")
        if recipient.crm_lead_id:
            parts.append("record: lead")
        if recipient.crm_role:
            parts.append(f"renewal role: {recipient.crm_role}")
    elif chat.crm_entity:
        parts.append(f"record: {chat.crm_entity}")
    if campaign_msg is not None and campaign_msg.template_id:
        template = campaign_msg.template
        parts.append(f"campaign template: {template.name} ({template.category or 'unknown category'})")
    return "; ".join(parts) or "unknown"


def _campaign_line(campaign_msg) -> str:
    if campaign_msg is None:
        return ""
    return f"(sent {transcript.stamp(campaign_msg.created_at)}) {transcript.outbound_text(campaign_msg)}"[:900]


def _last_outbound(conversation) -> Message | None:
    return (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND)
        .select_related("template")
        .order_by("-pk")
        .first()
    )


def _pending_question(last) -> bool:
    """Our last message asked something (in any script), offered buttons to tap, or asked for the
    licence's copy (shop_flow LICENCE_ASK, which has no question mark): an "ok" to it is answered,
    or the chat would stall there, with neither an invitation nor a nudge to follow."""
    if last is None:
        return False
    if rules.asks_question(last.body) or _is_licence_ask(last):
        return True
    if last.kind == Message.Kind.INTERACTIVE:
        return True
    return last.kind == Message.Kind.TEMPLATE and last.template_id is not None and bool(last.template.buttons)


def location_sent(conversation, office_address: str, maps_url: str, since=None) -> bool:
    """One of our own messages here (a reply, a booking, a reminder, the pin), since
    ``since`` when given, already gave the office's address or Maps link: it is not
    sent again unasked (the first real chat got the address three times)."""
    rows = Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND).only("kind", "body", "payload")
    if since is not None:
        rows = rows.filter(created_at__gte=since)
    for row in rows.order_by("-pk")[:200]:
        if transcript.is_ours(row) and (
            row.kind == Message.Kind.LOCATION or filters.carries_location(row.body, office_address, maps_url)
        ):
            return True
    return False


def _seconds_after_ours(conversation, message) -> float | None:
    previous = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, pk__lt=message.pk)
        .order_by("-pk")
        .values_list("created_at", flat=True)
        .first()
    )
    if previous is None:
        return None
    return (message.created_at - previous).total_seconds()


# Deciding ----------------------------------------------------------------------------


def effective_action(action: str, appointment: LeadAiAppointment | None) -> str:
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if action == "confirm" and confirmed:
        return "reschedule"
    if action == "reschedule" and not confirmed:
        return "confirm"
    return action


def _time_is_grounded(start: dt.datetime, words: str, ours: str, now: dt.datetime) -> bool:
    """The customer named the hour, or agreed to one we offered (rules 46, 59).

    ``words`` is what the customer wrote (and said in voice notes) lately;
    ``ours`` is what our side wrote last. "Evening" or "after work" grounds
    nothing, so a time the model picked for them is refused.
    """
    if any(ch.isdigit() for ch in words) or _HOUR_WORDS.search(words):
        return True
    if start - now <= WALK_IN and _NOW_WORDS.search(words):
        return True
    local = start.astimezone(hours.DUBAI)
    hour12 = local.hour % 12 or 12
    offered = rf"(?<![\d:])({hour12}(:{local.minute:02d})?|{local.hour:02d}:{local.minute:02d})(?![\d])"
    return bool(re.search(offered, ours or ""))


def _walk_in(start: dt.datetime, said: str, now) -> bool:
    """They are coming now ("I'm outside", "on my way"), in this burst's own words: no slot
    to refuse them for."""
    return start - now <= WALK_IN and bool(_WALK_IN_WORDS.search((said or "").replace("’", "'")))


def check_proposal(
    proposal: dict, appointment, now, closed_dates=(), *, grounding=None, segment: str = "", taken=(), said: str = ""
) -> dt.datetime | None:
    """The validated start (or arrival), None when the action needs no time. Raises SlotError.

    ``grounding`` is (customer words, our last words); when given, a new time
    must be one the customer named or agreed to. ``taken``: the starts of the
    other chats' open office visits; the office takes one client per 30-minute
    slot, so a time one of them holds is refused with the two nearest free ones
    (never the time this chat already has booked). The time already booked, said
    again, and a walk-in (``said``, the burst's own words: "I'm outside") are
    never refused.
    """
    action = effective_action(proposal["action"], appointment)
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if action in ("confirm", "reschedule"):
        if proposal["action"] == "reschedule" and confirmed and not proposal.get("date") and not proposal.get("time"):
            return None  # they want to move it and have not said when: recorded, and asked
        place = proposal.get("place")
        if place is None and segment == "owner":
            raise hours.SlotError(
                "no_place",
                "Say where the meeting is: place office for our office. A viewing at their property is "
                "tentative at customer_property with handover owner_viewing_slot.",
            )
        if (place or "office") != "office":
            raise hours.SlotError(
                "not_office",
                "Only meetings at our office can be confirmed here. Record a viewing at their property "
                "or a call as tentative, with handover owner_viewing_slot or call_requested.",
            )
        start = hours.check_slot(proposal["date"], proposal["time"], now=now, closed_dates=closed_dates)
        unchanged = confirmed and appointment.starts_at == start
        if grounding is not None and not unchanged and not _time_is_grounded(start, *grounding, now):
            raise hours.SlotError(
                "vague",
                "The customer has not named that time or agreed to it. Offer one or two exact times and ask "
                "them to pick.",
            )
        if taken and not unchanged and not _walk_in(start, said, now) and hours.is_taken(start, taken):
            # A move offers neither another client's slot nor the one they are moving from.
            own = [appointment.starts_at] if confirmed and appointment.starts_at else []
            nearest = hours.nearest_free(start, now, closed_dates, [*taken, *own])
            offer = " and ".join(hours.describe(slot) for slot in nearest) or "none in the next three weeks"
            raise hours.SlotError(
                "taken",
                "That time is already booked by another client: the office takes one client per 30-minute slot. "
                f"The nearest free times are {offer}. Say it is taken and offer those two, asking which is better.",
                alternatives=nearest,
            )
        return start
    if action == "running_late":
        if not confirmed or not appointment.starts_at:
            raise hours.SlotError(
                "no_appointment", "There is no confirmed meeting to move. Ask which day and exact time they want to come."
            )
        if not proposal.get("time"):
            return None
        return hours.check_late_arrival(appointment.starts_at, proposal["time"], now=now)
    if action == "on_my_way" and not confirmed:
        raise hours.SlotError(
            "no_appointment_otw",
            "There is no confirmed meeting. If they are coming now or are on their way, confirm today at the "
            "time they will arrive, place office.",
        )
    return None


def _code_may_act(answer: dict, said: str) -> bool:
    """Code may act on this answer's visit by itself (upgrade_exact_time books the
    customer's own time; taken_tentative, and a correction refused as taken in
    ask_model, offer the two nearest free slots): no fixed line goes out instead
    (_shape), the customer is in our segments, nothing is handed to a person in this
    answer, and no call is asked for ("Call me Wednesday at 5 pm": a time for a call)."""
    return not (
        answer.get("converted") or answer["segment"] == "other" or answer["handover"]["needed"] or _CALL_WORDS.search(said or "")
    )


def _at_office(proposal: dict, segment: str) -> bool:
    """The visit is at our office: "office", or no place outside the owner segment (an
    owner's day and hour with none may be a viewing at their property: check_proposal's
    no_place). The model's tentatives in eval shops-taken named no place."""
    place = proposal.get("place")
    return place == "office" or (place is None and segment != "owner")


def taken_tentative(answer: dict, appointment, now, closed_dates=(), taken=(), said: str = "") -> list:
    """The free starts nearest a time another client has, when the answer keeps the visit
    tentative at it and the customer named it themselves ("Tomorrow at 5 pm is better for
    me", 5 PM taken); else []. One client per slot holds for a tentative too: the reply
    is then code's, the two nearest free slots (shops.slot_taken), as for a confirm the
    office refused twice, and the tentative keeps their words, not the time (_apply).
    The model answered eval shops-taken this way in every run, offering other times or
    the taken one. Only where code would book the visit itself (upgrade_exact_time's
    exclusions, _code_may_act): an office visit (_at_office), never a fixed line,
    someone outside our segments, a handover in this answer or a call. A walk-in ("I'm
    outside") is never refused (check_proposal)."""
    proposal = answer["appointment"]
    if not taken or proposal["action"] != "tentative" or not _at_office(proposal, answer["segment"]):
        return []
    if not _code_may_act(answer, said):
        return []
    day, at = hours.parse_date(proposal.get("date")), hours.parse_time(proposal.get("time"))
    if day is None or at is None or at not in hours.named_times(said):
        return []
    start = dt.datetime.combine(day, at, tzinfo=hours.DUBAI)
    if not hours.is_taken(start, taken) or _walk_in(start, said, now):
        return []
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    own = [appointment.starts_at] if confirmed and appointment.starts_at else []
    return hours.nearest_free(start, now, closed_dates, [*taken, *own])


def offers_starts(reply: str, starts) -> bool:
    """The reply names the hour of every one of these starts ("4:30 PM or 5:30 PM")."""
    named = hours.named_times(reply or "")
    return bool(starts) and all(start.astimezone(hours.DUBAI).time() in named for start in starts)


def _shape(answer: dict) -> dict:
    """A confirm the office cannot take becomes what it is, handed to a person and
    never confirmed: a viewing at the owner's property or a call is tentative, and
    so is anything for someone outside our segments (a job applicant's interview).

    The model wrote its reply for a confirmation, so the words that go out are
    then a fixed line (``answer["converted"]``), never its "you are confirmed".
    """
    proposal = answer["appointment"]
    if proposal["action"] not in ("confirm", "reschedule"):
        return answer
    viewing = answer["handover"]["needed"] and answer["handover"]["reason"] == "owner_viewing_slot"
    if proposal["place"] in ("customer_property", "call") or viewing:
        place = proposal["place"] if proposal["place"] in ("customer_property", "call") else "customer_property"
        proposal["action"] = "tentative"
        proposal["place"] = place
        if not answer["handover"]["needed"]:
            answer["handover"] = {
                "needed": True,
                "reason": "owner_viewing_slot" if place == "customer_property" else "call_requested",
            }
        answer["converted"] = "viewing_noted" if place == "customer_property" else "holding"
    elif answer["segment"] == "other":
        proposal["action"] = "tentative"
        proposal["place"] = "office"
        if not answer["handover"]["needed"]:
            answer["handover"] = {"needed": True, "reason": "unclear"}
        answer["converted"] = "holding"
    return answer


def first_price_question(earlier: list) -> bool:
    """No earlier price question of the customer's was answered by us yet.

    ``earlier`` is the conversation before the messages in hand, as (author,
    text) pairs with the authors transcript.who gives. The first question
    about a price is deflected, never handed over (the prompt says so, and the
    model does not always follow it); only asking again after our answer is.
    """
    asked = False
    for author, text in earlier:
        if author == "customer" and filters.mentions_price(text):
            asked = True
        elif asked and author in ("assistant", "agent"):
            return False
    return True


_ASKING = re.compile(r"[?؟]|\b(tell|how much|kitna|kitne|batao|bataiye|bata do|first)\b|كم", re.IGNORECASE)
# A shops chat may quote the rents, so only a discount is a price question there.
_DISCOUNT = re.compile(
    r"discount|best price|last price|final price|lowest|\blower\b|reduce|reduction|cheaper|negotia|kam kar|kuch kam|rebate"
    r"|خصم|تخفيض|تنزيل|أرخص|ارخص|ڈسکاؤنٹ|رعایت|کم کر|छूट|डिस्काउंट|कम कर",
    re.IGNORECASE,
)


def first_discount_question(earlier: list) -> bool:
    """No earlier discount question of the customer's was answered by us yet (shops)."""
    asked = False
    for author, text in earlier:
        if author == "customer" and _DISCOUNT.search(text or ""):
            asked = True
        elif asked and author in ("assistant", "agent"):
            return False
    return True


def _settle_shops_handover(answer: dict, earlier: list, new_texts: list | None) -> dict:
    """A shops chat quotes the rents, so a price question is never a handover there; a
    discount is: not the first time (our agent discusses the best price at the
    viewing), but when they insist on a figure after that line."""
    handover = answer["handover"]
    if handover["needed"] and handover["reason"] == "owner_viewing_slot":
        answer["handover"] = handover = {"needed": False, "reason": None}
    if handover["needed"] and handover["reason"] == "price_or_details_insisted":
        if first_discount_question(earlier):
            answer["handover"] = {"needed": False, "reason": None}
    elif not handover["needed"] and new_texts and not first_discount_question(earlier):
        asked = " ".join(new_texts)
        if _DISCOUNT.search(asked) and _ASKING.search(asked):
            answer["handover"] = {"needed": True, "reason": "price_or_details_insisted"}
            answer["converted"] = answer.get("converted") or "holding"
    return answer


def settle_handover(answer: dict, earlier: list, new_texts: list | None = None, shops_chat: bool = False) -> dict:
    """The model's handover, corrected where code knows better: a renewal's price
    question is renewal_terms; the first price question is no handover; asking
    for the price again after our answer is one (with the holding line, never
    a second copy of the deflection). A shops chat has its own (discounts)."""
    if shops_chat:
        return _settle_shops_handover(answer, earlier, new_texts)
    handover = answer["handover"]
    renewal = answer["segment"] in ("renewal_tenant", "renewal_owner")
    if handover["needed"] and handover["reason"] == "owner_viewing_slot" and answer["segment"] != "owner":
        # Only an owner offers a slot at their own property.
        answer["handover"] = handover = {"needed": False, "reason": None}
    if renewal and not handover["needed"] and filters.mentions_price(" ".join(new_texts or [])):
        # The owner's choice: a renewal's rent or terms always go to a person.
        answer["handover"] = handover = {"needed": True, "reason": "renewal_terms"}
    if handover["needed"] and handover["reason"] == "price_or_details_insisted":
        if answer["segment"] in ("renewal_tenant", "renewal_owner"):
            handover["reason"] = "renewal_terms"
        elif first_price_question(earlier):
            answer["handover"] = {"needed": False, "reason": None}
    elif not handover["needed"] and new_texts and not first_price_question(earlier):
        asked = " ".join(new_texts)
        if filters.mentions_price(asked) and _ASKING.search(asked):
            reason = "renewal_terms" if answer["segment"] in ("renewal_tenant", "renewal_owner") else "price_or_details_insisted"
            answer["handover"] = {"needed": True, "reason": reason}
            answer["converted"] = answer.get("converted") or "holding"
    return answer


def agreed_to_come(*, visit_open: bool, our_last: str, texts: list) -> bool:
    """The customer has agreed to come: a visit is open (tentative or confirmed), or
    right after our last message invited them (a nudge too: visit_offered) or offered
    times, the last thing they said (acknowledgements aside) is a plain yes: "No, I am
    travelling" and then "ok" is no yes. ``texts``: the burst, a message that is not
    text as ''."""
    if visit_open:
        return True
    if not visit_offered(our_last):
        return False
    said = [text for text in texts if not rules.is_acknowledgement(text)]
    return rules.is_acceptance(said[-1]) if said else any(rules.is_acceptance(text) for text in texts)


# The words a yes opens a message with ("Yes please, send me the location"); "ok" opens many a message
# that agrees to nothing ("ok how much sqf"), so only alone is it a yes (rules.is_acceptance).
_YES_FIRST = frozenset(
    rules.normalize_text(word)
    for word in ("yes", "yeah", "yep", "sure", "haan", "han", "ji", "jee", "نعم", "أكيد", "اكيد", "ہاں", "جی", "हाँ", "हां", "जी")
)


def opens_with_yes(texts) -> bool:
    """A message of the burst is a plain yes, or opens with one ("Yes please, send me the location", "Sure,
    where is it?", "haan ji location bhej do"): right after our offer (visit_offered), a yes to it, which
    agreed_to_come reads only when it is the whole of their last message. ``texts``: the burst, a message
    that is not text as ''."""
    for text in texts or ():
        words = rules.normalize_text(text).split()
        if rules.is_acceptance(text) or (words and words[0] in _YES_FIRST):
            return True
    return False


def visit_offered(ours: str) -> bool:
    """Our side's recent words (ours or a colleague's, never the campaign's) invited
    them or offered exact times: a visit is on the table, whatever the model flagged.
    A shops nudge invites too ("Shall I book you for this evening?"), in words
    filters.is_invitation does not read (nudges.is_nudge)."""
    return filters.is_invitation(ours) or filters.offers_time(ours) or nudges.is_nudge(ours)


# Our offer turned down or put off, anywhere in a message: a no ("No, I told you I can't come"), "busy",
# "not today", another day. A "no problem" says yes (hours.without_no_problem).
_TURNS_DOWN = re.compile(
    r"^\W*(?:no|nope|nah|nahi|nahin|nhi|nai)\b"
    r"|\b(?:can'?t|cannot|can\s+not|won'?t|unable|busy|not\s+(?:today|tomorrow|now|this\s+week|possible|free|coming|able|interested))\b"
    r"|\b(?:another|other|different)\s+(?:day|time)\b|\bnext\s+week\b"
    r"|\b(?:nahi|nahin|nhi)\s+(?:aa|aana|aaunga|aa\s+sakta|aa\s+sakti|ho\s+sakta)\b|\bmasroof\b|\bmushkil\b"
    r"|^\W*لا(?![\u0621-\u064a])|ما\s*(?:أقدر|اقدر|أستطيع|استطيع|بقدر)|مشغول|مصروف|نہیں\s*آ|नहीं\s*आ|व्यस्त",
    re.IGNORECASE,
)


def turns_down(texts) -> bool:
    """Something the customer said turns our offer down or puts it off: a no, "not now", a deferral,
    "I can't", "busy", another day (_TURNS_DOWN). A question ("How much sqf"), a request for photos,
    or a day asked for ("Tomorrow?") turns nothing down. ``texts``: the burst, a message that is
    not text as ''."""
    for text in texts or ():
        raw = str(text or "")
        if rules.is_refusal(raw) or rules.is_not_now(raw) or rules.is_deferral(raw) or rules.mentions_deferral(raw):
            return True
        if _TURNS_DOWN.search(hours.without_no_problem(raw.replace("’", "'")).strip()):
            return True
    return False


def reoffered(*, agreed: bool, our_last: str, texts) -> bool:
    """A shops chat: our last message invited them or offered times (visit_offered), and what they said
    since turns nothing down (turns_down): slots offered now are that same invitation again, neither a
    new one counted nor one the cap cuts (settle), live and in the eval. Invitations are counted and
    capped as they are refused ("Invite at most twice ... After two refusals"): live, a question
    after our own two slots ("How much sqf") made the model offer them again, and that counted as
    the second invitation once our offer recorded no visit of its own (own_offer), so the third
    reply lost its slots. A yes is agreed_to_come's."""
    return not agreed and visit_offered(our_last) and not turns_down(texts)


def deferral(said: list, *, appointment=None, offered: bool = False, invites: int = 0, quiet: bool = False) -> str:
    """The customer's words when all they said (acknowledgements aside) puts off a
    visit we put on the table, else ''.

    ``said`` is the burst without its acknowledgements, a message that is not
    text as '': a question sent with the deferral is the model's to answer.
    A day or an hour said with it ("Tomorrow at 5 pm, I will let you know",
    rules.is_dated_deferral) is still a deferral: no promise, so no time is
    kept (their words are). On the table: ``offered`` (visit_offered), an
    invitation counted (``invites``), or ``appointment``, the open one, being
    an office visit still tentative. Any other open one stays the model's,
    which sees it: a confirmed meeting, an owner's viewing at their property, a
    call. ``quiet``: a person has the chat, they declined, or they are no
    customer of ours (a job applicant): nothing to book.
    """
    words = (said[0] if len(said) == 1 else "").strip()
    if quiet or not words or not (rules.is_deferral(words) or rules.is_dated_deferral(words)):
        return ""
    if appointment is not None:
        office = (appointment.place or LeadAiAppointment.Place.OFFICE) == LeadAiAppointment.Place.OFFICE
        return words if appointment.status == LeadAiAppointment.Status.TENTATIVE and office else ""
    return words if offered or invites > 0 else ""


def deferral_answer(words: str, language: str, appointment=None, segment: str = "other") -> dict:
    """What code answers to a deferral, shaped like a model's answer: the visit is
    tentative in the customer's words, and the reply is the fixed line. An open
    office visit keeps its day and time; only their words change."""
    date = time = None
    if appointment is not None and appointment.starts_at:
        local = appointment.starts_at.astimezone(hours.DUBAI)
        date, time = f"{local:%Y-%m-%d}", f"{local:%H:%M}"
    answer = schema.normalize(
        {
            "language": language,
            "segment": segment,
            "appointment": {"action": "tentative", "place": "office", "date": date, "time": time, "customer_words": words},
            "send": True,
            "reply": rules.line("let_me_know", language),
        }
    )
    answer["converted"] = "let_me_know"
    return answer


# The shops playbook's rules before the model -----------------------------------------------------
# (owner's choice 2026-10-13: the build pack's OLD-LEAD MODE, in code where the words are fixed)

CHECK_BACK_YES = "check_back_yes"
CHECK_BACK_NO = "check_back_no"
RENTED_NO = "rented_no"
NOT_NOW = "not_now"
FOR_WHOM = "for_whom"
SPAM_RULE = "spam"
# What a lead in discovery has told us, in the build pack's order (business, size or budget,
# licence): with two of these, spam words are the model's to judge, never code's.
_DISCOVERY = (("business_activity",), ("size_sqft",), ("budget_aed",), ("licence_kind", "trade_licence"))


def _discovery_facts(facts: dict | None) -> int:
    """How many of the business, the size, the budget and the licence the chat's facts hold."""
    facts = facts or {}
    return sum(1 for keys in _DISCOVERY if any(facts.get(key) not in (None, "", []) for key in keys))


def shops_rule(
    text: str,
    *,
    tapped: bool = False,
    single: bool = True,
    followup_open: bool = False,
    rented_open: bool = False,
    first_answer: bool = False,
    for_client_known: bool = False,
    visit_on_table: bool = False,
    meeting_open: bool = False,
    quiet: bool = False,
    facts: dict | None = None,
    end_user: bool = False,
) -> str:
    """Which of the shops rules settles this burst without the model, else ''.

    ``text`` is the last thing the customer said (a tap's label, ``tapped``),
    ``single`` that nothing else was said with it. ``followup_open``: our last
    message asked "Should I check back with you in a month?"; ``rented_open``:
    they said they already rented a shop and our last message asked about a
    second one; ``first_answer``: nobody from our side wrote since the campaign
    (or since its Template B: transcript.who); ``visit_on_table``: a visit is
    open or our last message offered times, so a typed "not now" means another
    time (the model's); ``meeting_open``: a visit is open, so even the
    template's "Not now" is the model's, which sees it; ``quiet``: a person has
    the chat; ``facts``: the chat's facts; ``end_user``: they told us the shop
    is for themselves (facts.for_client false). A plain chain message, scam or
    advert (rules.looks_like_spam) is spam whatever our last line asked, and
    nothing goes out; but not with a visit open, nor from a lead who told us
    two of their business, size, budget and licence: those are the model's to
    judge (it can still call them spam).

    The templates' positive taps ([Yes, show me shops], [Yes, book a viewing],
    "Interested") are the first yes: "for yourself, or a client?" while we do
    not know; from an end user, [Yes, book a viewing] gets the two free slots
    and the others the shop types list, never that question again.
    """
    words = (text or "").strip()
    if quiet or not single or not words:
        return ""
    if not tapped and not meeting_open and _discovery_facts(facts) < 2 and rules.looks_like_spam(words):
        return SPAM_RULE
    if followup_open:
        if rules.is_acceptance(words):
            return CHECK_BACK_YES
        return CHECK_BACK_NO if rules.is_refusal(words) else ""
    if rented_open and rules.is_refusal(words):
        return RENTED_NO
    if ((tapped and not meeting_open) or not visit_on_table) and rules.is_not_now(words):
        return NOT_NOW
    if first_answer and not for_client_known and (rules.is_positive_tap(words) or rules.is_acceptance(words)):
        return FOR_WHOM
    if first_answer and tapped and end_user and not meeting_open and rules.is_positive_tap(words):
        # A known end user's yes to a template (a check-back's Template B): no "for yourself?" again.
        return f"{BOOK_TAP}:" if rules.is_book_tap(words) else TYPES_TAP
    return ""


# Taps on the shops list and on a type's detail card (shop_flow.tap_rule), and the licence
# copy arriving while it was asked for: code's, before the model. "type_tap:type_1" names its type.
TYPE_TAP = "type_tap"
BOOK_TAP = "book_tap"
TYPES_TAP = "types_tap"
LICENCE_RECEIVED = "licence_received"
_TAP_RULES = {shop_flow.TAP_TYPE: TYPE_TAP, shop_flow.TAP_BOOK: BOOK_TAP, shop_flow.TAP_TYPES: TYPES_TAP}


def tap_rule_name(tap: tuple[str, str] | None) -> str:
    """The rule a tap on our list or card is ("type_tap:type_2", "book_tap:", "types_tap"), else ''."""
    if not tap:
        return ""
    kind, shop_type = tap
    name = _TAP_RULES[kind]
    return name if kind == shop_flow.TAP_TYPES else f"{name}:{shop_type}"


def _flow_answer(rule: str, language: str, known: dict | None) -> dict:
    """A shops step's answer: none of the model's words, the step (shop_flow) instead."""
    answer = schema.normalize({"language": language, "segment": "commercial_tenant", "send": False, "reply": ""}, shops=True)
    answer["rule"] = rule
    name, _, shop_type = rule.partition(":")
    if name == TYPE_TAP:
        # The type they picked is the one they want (Bitrix Shop Type Wanted follows).
        answer["facts"]["shop_type"] = shop_type
        answer["shop_step"] = {"kind": shop_flow.MEDIA, "type": shop_type}
    elif name == BOOK_TAP:
        chosen = shop_type or (known or {}).get("shop_type")
        if chosen in shop_flow.TYPE_KEYS:
            answer["facts"]["shop_type"] = chosen
        answer["shop_step"] = {"kind": shop_flow.SLOTS}
    elif name == TYPES_TAP:
        answer["shop_step"] = {"kind": shop_flow.LIST}
    elif name == LICENCE_RECEIVED:
        answer["shop_step"] = {"kind": shop_flow.LICENCE_THANKS}
        answer["licence"] = "received"
    return answer


def customer_asks(said: str, now) -> bool:
    """The burst asks something the model should answer: a question, the location or the way,
    to come or see, a day or an hour (a shops step then leaves the words to the model)."""
    return bool(
        rules.asks_question(said) or filters.asks_for_location(said) or filters.asks_the_way(said)
        or _VISIT_WORDS.search(said or "") or hours.named_days(said, now) or hours.named_times(said)
    )


# They will come, in words customer_asks does not read: "shaam ko aaunga", "I'll drop by", "Evening
# works for me", "ممكن أمر عليكم بعد الدوام", "कल आऊँगा". A greeting ("Good morning", "صباح الخير")
# names no part of the day they come in.
_COMING = re.compile(
    r"\b(?:drop\s+(?:by|in)|pass\s+by|stop\s+by|swing\s+by|pop\s+(?:in|by|over)|come\s+by|coming"
    r"|aa?(?:u|o|oo)n?ga|aaungi|aayenge|aaenge|aayega|aaega|aa\s+ja(?:unga|oonga|enge|yenge|ungi)|aata\s+hoon|aati\s+hoon"
    r"|morning|afternoon|evening|tonight|night|weekend|after\s+(?:work|office|duty|my\s+work)|subah|sham|shaam|dopahar|raat)\b"
    r"|(?<![\u0621-\u064a\u0671-\u06d3])(?:أمر\s*عليكم|امر\s*عليكم|بمر|نمر\s*عليكم|أعدي\s*عليكم|اعدي\s*عليكم|باجي|بجي|راح\s*اجي"
    r"|بزوركم|أزوركم|ازوركم|أحضر|احضر|بحضر|المساء|مساء|الصبح|الصباح|صباحا|الظهر|العصر|المغرب|الليلة|بالليل|بعد\s*الدوام"
    r"|بعد\s*العمل|آؤں|آؤنگا|آ\s*جاؤں|آجاؤں|آئیں\s*گے|آجائیں|شام|صبح|دوپہر|رات)(?![\u0621-\u064a\u0671-\u06d3])"
    r"|आऊँ|आऊं|आ\s*जाऊँ|आ\s*जाऊं|आएँगे|आएंगे|आ\s*जाएँगे|शाम|सुबह|दोपहर|रात",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"\bgood\s+(?:morning|afternoon|evening|night)\b|صباح\s*(?:الخير|النور)|مساء\s*(?:الخير|النور)|صبح\s*بخیر|शुभ\s*(?:प्रभात|संध्या)",
    re.IGNORECASE,
)


def wants_to_come(said: str, now) -> bool:
    """The burst says they will come, in any way: what customer_asks reads (a visit asked for, a
    day, an hour), and the words it does not (_COMING: "shaam ko aaunga", "Evening works for me",
    "I'll drop by"), a hedge ("maybe 7", "I'll try", "shayad") or an hour in any form
    (hours.said_times, hours.hours_ahead, hours.marks_hour)."""
    words = _GREETING.sub(" ", str(said or "").replace("’", "'"))
    return bool(
        customer_asks(words, now) or _COMING.search(words) or hours.hedged(words) or hours.said_times(words)
        or hours.hours_ahead(words) or hours.marks_hour(words)
    )


# The visit words of _VISIT_WORDS that never ask for a photo: "can I see them?" and "show me" may.
_COME_WORDS = re.compile(
    r"\b(?:visit|come|meet|appointment|book|viewing|slot)\b|\bmil(?:na|ne|en)\b|\baa\s+(?:sakta|sakte|jaun|jaunga)"
    r"|زيارة|أزور|ازور|أجي|اجي|موعد|معاينة|ملاقات|آ\s+سکت|आ\s+सकत",
    re.IGNORECASE,
)
# A burst's clauses: a request for photos or for the shop types is one of them ("photos bhej do, shaam ko aaunga").
_CLAUSES = re.compile(r"[.!?؟,;،\n]+|\s+(?:and|then|but|also|aur|phir)\s+", re.IGNORECASE)


def without_requests(said: str) -> str:
    """The burst without its requests for photos, a video or the shop types (shop_flow.asks_media,
    asks_types), clause by clause: "If possible to send me photo first" leaves nothing, "photos bhej
    do, shaam ko aaunga" leaves "shaam ko aaunga"."""
    clauses = [clause.strip() for clause in _CLAUSES.split(str(said or "")) if clause and clause.strip()]
    return " ".join(clause for clause in clauses if not (shop_flow.asks_media(clause) or shop_flow.asks_types(clause)))


def comes(said: str, now) -> bool:
    """They say they will (or may) come, in their own words outside a request for photos, a video or
    the shop types (without_requests): a day or an hour of theirs in any form, a word of coming
    (_COMING: "shaam ko aaunga", "I'll drop by", "بعد الدوام"; _COME_WORDS: "I'll come", "can I
    visit", "book me"), or a hedge that asks nothing ("Maybe", "I'll try"). Narrower than
    wants_to_come, which also reads any question and "see" or "show": "If possible to send me photo
    first", "New. Is the rent yearly?" and "can I see type 2 first" say nothing of coming."""
    words = without_requests(_GREETING.sub(" ", str(said or "").replace("’", "'")))
    return bool(
        _COMING.search(words) or _COME_WORDS.search(words) or hours.named_days(words, now) or hours.said_times(words)
        or hours.hours_ahead(words) or hours.marks_hour(words) or (hours.hedged(words) and not rules.asks_question(words))
    )


def step_plain(answer: dict, *, still_invalid: bool, when, effective: str, quiet: bool, said: str) -> bool:
    """An answer a shops step may replace: nothing in it that must go out instead (an opt-out,
    a handover, a booking or a time to refuse, a fixed line), no person on the chat, and no
    request for the location or the way (that goes as it always did)."""
    return not (
        answer["opt_out"] != "none" or answer["handover"]["needed"] or answer.get("converted") or answer.get("slot_taken")
        or answer.get("broker") or still_invalid or when is not None or effective != "none" or quiet
        or filters.asks_for_location(said) or filters.asks_the_way(said)
    )


def model_step(
    answer: dict,
    known: dict,
    said: str,
    now,
    *,
    appointment,
    agreed: bool,
    still_invalid: bool,
    when,
    quiet: bool,
    list_sent: bool,
    licence_asked: bool,
    media_recent=(),
    media_today=(),
    shops_facts=None,
) -> dict | None:
    """The shops step that goes instead of the model's words, set on the answer (live and in the
    eval, which pass the same values): shop_flow.after_model's, else the two free slots of a
    confirm of a time the customer neither gave nor took (unasked_confirm). None when the
    model's words go.

    A tentative visit only the model's own invitation recorded (no visit open, no yes of theirs
    to an invitation, nothing in the burst that says they will come: wants_to_come) keeps no
    step from going, and goes with that invitation: the build pack asks for a DED or Trakhees
    licence's copy before it invites, and the model answered "Yes I have a DED licence" with a
    tentative and two slots in every run of eval shops-licence-ask. Only the licence request is
    taken over such a tentative (shop_flow.after_model). A tentative in their own words ("DED
    hai, shaam ko aaunga", "I have a DED licence, maybe 7", "ممكن أمر عليكم بعد الدوام") is
    theirs, whatever the model's words for it: it stays, with the model's reply.

    Photos, a video or the shop types asked for (shop_flow.asks_media, asks_types) get their step
    over any tentative of the model's, open visit or not, when nothing else must go instead (an
    opt-out, a handover or a person on the chat, a booking or a time to refuse, a fixed line, a
    taken slot, a broker: step_plain), and never over the two free slots of a yes that named no
    time (unasked_confirm: "Yes, book me for this evening and send me photos"). Live, "If possible
    to send me photo first" got the model's "Photos help, but seeing 2-3 shops side by side is much
    easier" and two slots, and no photos, because the model answered it tentative (2026-10-15,
    appointment 16, which its own invitation had opened). Unless they say they will come in words
    of their own beside the request (comes: "photos bhej do, shaam ko aaunga", "send pics, will
    come around 8"), or own_offer found the tentative theirs (a yes to our offer, their day or
    hour), that tentative goes with the words the step replaces: an open visit stays exactly as it
    was (no revision, no CRM event, no alert), and the card's [Book viewing] brings the visit back.
    """
    effective = effective_action(answer["appointment"]["action"], appointment)
    plain = step_plain(answer, still_invalid=still_invalid, when=when, effective=effective, quiet=quiet, said=said)
    requested = (
        not plain and effective == "tentative" and not answer.get("unasked")
        and (shop_flow.asks_media(said) or shop_flow.asks_types(said))
        and step_plain(answer, still_invalid=still_invalid, when=when, effective="none", quiet=quiet, said=said)
    )
    invitation = (
        not plain and effective == "tentative" and appointment is None and not agreed and not answer.get("theirs")
        and step_plain(answer, still_invalid=still_invalid, when=when, effective="none", quiet=quiet, said=said)
        and not wants_to_come(said, now)
    )
    step = shop_flow.after_model(
        answer,
        known,
        said,
        plain=plain,
        invitation=invitation,
        requested=requested,
        asked=customer_asks(said, now),
        list_sent=list_sent,
        licence_asked=licence_asked,
        media_recent=media_recent,
        media_today=media_today,
        booked=appointment is not None,
        facts=shops_facts,
    )
    if requested and not answer.get("theirs") and not comes(said, now):
        # Only the model's tentative (its invitation said again, or the open visit's in words that ask for
        # photos): it goes with the words the step replaces, so nothing is written for the visit.
        answer["appointment"] = dict(NO_TIME)
    elif step is not None and invitation:
        answer["appointment"] = dict(NO_TIME)  # the tentative went with the invitation the step replaces
    unasked = answer.get("unasked")
    if step is None and unasked and answer["opt_out"] == "none" and not answer["handover"]["needed"] and not answer.get("converted"):
        step = {"kind": shop_flow.SLOTS, "slots": list(unasked["slots"])}
    if step is not None:
        answer["shop_step"] = step
    return step


def shops_answer(rule: str, language: str, words: str = "", known: dict | None = None) -> dict:
    """What code answers for a shops rule, shaped like a model's answer: a fixed line
    (``converted``), or for a no the not-interested opt-out with the reason
    (``lost_reason``). ``followup`` tells _apply what to do with the check-back:
    "ask", "schedule" (in a month) or "clear". A tap on the shops list or a card, and
    the licence copy, get a step (``shop_step``; _flow_answer); ``known`` is the chat's facts."""
    if rule.partition(":")[0] in (TYPE_TAP, BOOK_TAP, TYPES_TAP, LICENCE_RECEIVED):
        return _flow_answer(rule, language, known)
    answer = schema.normalize({"language": language, "segment": "commercial_tenant", "send": True, "reply": "-"}, shops=True)
    answer["rule"] = rule
    if rule == SPAM_RULE:
        # As the model's spam (_opt_out): no line at all, the chat stops, the lead is Junk
        # with the words that were sent, so an agent can tell whether it really was spam.
        answer.update(opt_out=rules.SPAM, send=False, reply="", segment="other")
        return answer
    if rule in (CHECK_BACK_NO, RENTED_NO):
        answer["opt_out"] = rules.NOT_INTERESTED
        answer["lost_reason"] = "already rented" if rule == RENTED_NO else (words or "not interested")
        answer["followup"] = "clear"
        answer["reply"] = rules.line_for(rules.NOT_INTERESTED, language, shops=True)
        return answer
    line = {CHECK_BACK_YES: "check_back_yes", NOT_NOW: "check_back", FOR_WHOM: "for_whom"}[rule]
    answer["converted"] = line
    answer["reply"] = rules.line(line, language)
    if rule == CHECK_BACK_YES:
        answer["followup"] = "schedule"
    elif rule == NOT_NOW:
        answer["followup"] = "ask"
    return answer


def shops_language(text: str, tapped: bool, so_far: str) -> str:
    """The language of a fixed shops line: a tap, or a plain yes or no in English
    letters, keeps the language so far; anything else is read from the words."""
    guess = "en" if tapped else rules.guess_language(text)
    return guess if guess != "en" else (so_far or "en")


def point_to_location(answer: dict, new_texts: list, address_sent: str) -> str:
    """The reply made to answer "How do I reach there?" (filters.asks_the_way) once our
    location went out: "" when nothing changes, "pointer" when the line pointing to it
    (rules "location_above") opens the reply, "location" when the reply was only the
    address again and the line replaces it. The model was told to refer to "the
    location above" and did not, in any run of eval location-again: it offered times
    instead, or retyped the address, which drop_location cuts and leaves no answer.
    ``address_sent``: the office address, '' when the location was not sent (or they
    asked for the location itself: it goes again, filters.asks_for_location)."""
    if not address_sent or answer["opt_out"] != "none" or answer.get("converted"):
        return ""
    if not filters.asks_the_way(" ".join(new_texts or [])):
        return ""
    reply = answer["reply"]
    pointer, pointer_en = rules.line("location_above", answer["language"]), rules.line("location_above", "en")
    if reply and filters.carries_location(reply, address_sent):
        # Nothing but the address again (drop_location keeps such a reply whole): the line instead.
        answer["reply_en"] = pointer_en if answer["reply_en"] else ""
        answer["reply"] = pointer
        answer["send"] = True
        return "location"
    if filters.points_to_location(reply):
        return ""
    answer["reply"] = f"{pointer} {reply}".strip()
    if answer["reply_en"]:
        answer["reply_en"] = f"{pointer_en} {answer['reply_en']}"
    answer["send"] = True
    return "pointer"


# Our last line asked about the licence, or the business, already.
_LICENCE_WORDS = re.compile(r"licen[cs]e|\bDED\b|trakhees|رخصة|لائسنس|लाइसेंस", re.IGNORECASE)
_BUSINESS_WORDS = re.compile(r"\bbusiness\b|\bactivity\b|\bkaam\b|\bkaro?bar\b|نشاط|عمل|کاروبار|کام|व्यापार|बिज़नेस|बिजनेस|काम", re.IGNORECASE)
# The customer asks to see the shops, to come or to book: an invitation is then the answer.
_VISIT_WORDS = re.compile(
    r"\b(?:visit|view|viewing|see|show|come|meet|appointment|book|booking|slot)\b|\bdekh\w*|\bmil(?:na|ne|en)\b|\baa\s+(?:sakta|sakte|jaun|jaunga)"
    r"|زيارة|أزور|ازور|أشوف|اشوف|أجي|اجي|موعد|معاينة|دیکھ|ملاقات|آ\s+سکت|देख|मिल|आ\s+सकत",
    re.IGNORECASE,
)


def _inviting(sentence: str) -> bool:
    return filters.offers_time(sentence) or filters.is_open_when(sentence) or filters.is_invitation(sentence)


def licence_first(answer: dict, known: dict, earlier: list, new_texts: list, now=None) -> bool:
    """A shops reply that invites while the licence, the build pack's next discovery
    item, is still unknown, rewritten to ask it (rules "ask_licence"), without the
    location the invitation would have carried; True when it was.

    The build pack: business, size or budget, licence, then the viewing (SHOPS_SYSTEM's
    THE VIEWING says the same; the model invited instead in eval shops-35283, after
    "I have vape business."). Only for a known end user whose business (known, or
    answering our question about it) and size or budget are known, while no slot is
    on the table, our last line did not ask about the licence already (no loop on an
    answer the model could not read), and the customer's own words this time neither
    ask anything nor ask to come, see or book, nor name a day or an hour: those
    still get the invitation straight away. ``known``: the chat's facts before the
    turn; ``earlier``: the conversation before the burst, as (author, text).
    """
    known = known or {}
    facts = dict(known)
    facts.update({key: value for key, value in answer["facts"].items() if value not in (None, "", [])})
    ours = [text for author, text in earlier if author in ("assistant", "agent")]
    last = ours[-1] if ours else ""
    if facts.get("for_client") is not False or facts.get("licence_kind") or facts.get("trade_licence"):
        return False
    if not (facts.get("size_sqft") or facts.get("budget_aed")):
        return False
    # The business: recorded, or what they answer now to our question about it (size or budget known before).
    answering_business = bool(_BUSINESS_WORDS.search(last)) and bool(known.get("size_sqft") or known.get("budget_aed"))
    if not (facts.get("business_activity") or answering_business):
        return False
    if filters.offers_time(last) or _LICENCE_WORDS.search(last):
        return False
    said = " ".join(new_texts or [])
    if (
        rules.asks_question(said) or filters.asks_for_location(said) or filters.asks_the_way(said) or _VISIT_WORDS.search(said)
        or hours.named_days(said, now) or hours.named_times(said)
    ):
        return False
    sentences = filters.split_sentences(answer["reply"])
    if not (answer["invited_to_meeting"] or any(_inviting(sentence) for sentence in sentences)):
        return False
    # Its reaction and its MATCH stay; the invitation and any other question go.
    kept = [sentence for sentence in sentences if not _inviting(sentence) and not rules.asks_question(sentence)]
    answer["reply"] = " ".join([*kept, rules.line("ask_licence", answer["language"])])
    answer["invited_to_meeting"] = False
    # The location went with the invitation: no address or Maps link under the licence
    # question. (A message asking for the location never gets here: it is invited at once.)
    answer["share_office_location"] = False
    return True


def settle(
    answer: dict,
    earlier: list,
    new_texts: list,
    invites: int,
    *,
    agreed: bool = False,
    reoffer: bool = False,
    playbook: str = lane.GENERAL,
    broker_labelled: bool = False,
    address_sent: str = "",
    slots: list | None = None,
    now=None,
    facts: dict | None = None,
) -> dict:
    """Everything code corrects in the model's answer before it is used (live and in the eval).

    ``agreed``: the customer has agreed to come (agreed_to_come); ``reoffer``: a
    shops chat's slots offered again after words that turn our offer down in no
    way (reoffered), which are no new invitation either; ``playbook``:
    the chat's script (lane.playbook_for); ``broker_labelled``: the chat carries
    the Broker label already, so an agent pressed Resume on it (or labelled it):
    a broker is then an ordinary handover; ``address_sent``: the office
    address, when one of our messages gave the location already (asked the way
    then, the reply points to it: point_to_location); ``slots``: in a shops chat
    that may still be invited, the two free starts an open "when would you like
    to come?" is turned into (invitation_slots, at ``now``); ``facts``: the
    chat's facts before this turn (a shops chat asks the licence before it
    invites: licence_first; its recommendation names their business, never
    another one: shop_flow.own_business, board T56).
    What is cut or rewritten in the reply is listed in ``answer["trimmed"]``, so
    its English gloss no longer holds; ``answer["broker"]`` asks _apply to label
    and pause the chat; ``answer["pointed"]`` says the reply now points to the
    location (its gloss got the same line).
    """
    shops_chat = playbook == lane.IC_SHOPS
    settle_handover(answer, earlier, new_texts, shops_chat=shops_chat)
    # language names the script the reply is written in (Urdu script is ur, never ur_latin).
    written = rules.guess_language(answer["reply"]) if answer["reply"] else ""
    if written in ("ar", "ur", "hi") and answer["language"] != written:
        answer["language"] = written
    trimmed = []
    if shops_chat and answer["reply"] and not answer.get("converted"):
        # Board T56: the prompt's old MATCH example ("For a mobile shop, Type 1 is perfect") went to
        # a vape shop. A recommendation names the customer's own business, or none.
        business = answer["facts"].get("business_activity") or (facts or {}).get("business_activity") or ""
        answer["reply"], filled = shop_flow.fill_placeholders(answer["reply"], business)
        answer["reply"], renamed = shop_flow.own_business(answer["reply"], business, " ".join(new_texts or []))
        if renamed or filled:
            trimmed.append("business")
    if agreed or reoffer:
        # They said yes to coming, or turned down nothing of the times we just
        # offered: the times offered now are no new invitation, so they are
        # neither counted nor cut (the first real chat lost its time offer to the
        # cap below after a plain "Yes").
        answer["invited_to_meeting"] = False
    elif invites >= 2:
        # Invited twice and refused: no third invitation, in any words.
        answer["invited_to_meeting"] = False
        if answer["reply"]:
            answer["reply"], dropped = filters.drop_invitations(answer["reply"])
            if dropped:
                trimmed.append("invitation")
    if address_sent and answer["reply"]:
        # The model typing the address again from its OFFICE line (two of the
        # three copies in the first real chat): the location went out already.
        answer["reply"], repeated = filters.drop_location(answer["reply"], address_sent)
        if repeated:
            trimmed.append("location")
    if shops_chat and answer["reply"] and not answer.get("converted") and not rules.asks_question(" ".join(new_texts or [])):
        # The build pack: never the same sentence twice in a chat. Not when they asked
        # something (the same question can have the same answer), and never a
        # question of ours or one of the build pack's fixed answers.
        answer["reply"], repeated = filters.drop_repeats(
            answer["reply"], [text for author, text in earlier if author == "assistant"], keep=shops.is_fixed_line
        )
        if repeated:
            trimmed.append("repeat")
    if (
        shops_chat and answer["reply"] and not answer.get("converted") and answer["opt_out"] == "none"
        and not answer["handover"]["needed"] and not agreed and licence_first(answer, facts or {}, earlier, new_texts, now)
    ):
        trimmed.append("licence_first")
    if shops_chat and slots and answer["reply"] and not answer.get("converted"):
        # The build pack's assumptive close: never "when are you free?", always two slots.
        answer["reply"], rewritten = filters.offer_slots(answer["reply"], shops.slot_offer(answer["language"], slots, now))
        if rewritten:
            trimmed.append("slots")
    # Last, so neither the no-repeat guard nor the slots rewrite takes the pointer out again.
    pointed = point_to_location(answer, new_texts, address_sent)
    if pointed:
        answer["pointed"] = pointed
    if trimmed:
        answer["trimmed"] = trimmed
        if not answer["reply"]:
            answer["send"] = False
    handover = answer["handover"]
    if handover["needed"] and handover["reason"] == BROKER and not broker_labelled:
        answer["broker"] = True
        if playbook == lane.IC_SHOPS:
            # The shops build pack's own hand-off line, never the model's words.
            answer["converted"] = "broker"
    return answer


def invitation_slots(answer: dict, appointment, said: str, now, closed_dates=(), taken=(), *, may_invite: bool = True) -> list | None:
    """The two free slots a shops reply's open "when would you like to come?" becomes
    (settle's ``slots``; live and in the eval), or None when the reply is no invitation
    to rewrite: the chat may not be invited any more, they are running late, on the
    way or cancelling, or a booked customer is not moving the viewing (a question then
    is about something else: "Approximately what time will you reach?"). A move never
    offers the time they already have; the pair follows the day they asked for
    (shops.invitation_slots)."""
    if not may_invite:
        return None
    action = effective_action(answer["appointment"]["action"], appointment)
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if action in ("running_late", "on_my_way", "cancel") or (confirmed and action != "reschedule"):
        return None
    if confirmed and appointment.starts_at:
        taken = [*taken, appointment.starts_at]
    asked = [sentence for sentence in filters.split_sentences(answer["reply"]) if filters.is_open_when(sentence)]
    return shops.invitation_slots(said, asked, now, closed_dates, taken)


# The customer asks for the booking itself, in words with no question mark: to confirm it, send it
# again or its details ("Please confirm my visit tomorrow at 5", "Send me the confirmation again",
# "We are still on for 5 right", "kal 5 baje confirm hai na", "أكد لي الموعد", "पक्का है ना").
_ASKS_BOOKING = re.compile(
    r"\b(?:re-?)?confirm\b|\bconfirmation\s+(?:please|pls|plz|again)\b|\b(?:need|want|get)\s+(?:the\s+|a\s+)?confirmation\b"
    r"|\b(?:re-?send\w*|remind\s+(?:me|us)|still\s+on|are\s+we\s+on|is\s+it\s+on)\b"
    r"|\b(?:send|share|forward|give)\b[^.!?]{0,30}\b(?:again|once more|booking|appointment|meeting|viewing|time|details?|confirmation)\b"
    r"|(?<!all )\b(?:right|correct|na|naa|na\s+ji)\s*[.!]*\s*$"
    r"|أكد|اكد|تأكيد|تاكيد|تأكد|تاكد|مؤكد|موكد|تفاصيل|أرسل|ارسل|ابعث|ابعت|ذكرني|ذكّرني"
    r"|کنفرم|تصدیق|تفصیل|بھیج|یاد\s*دلا"
    r"|कन्फर्म|कनफर्म|पक्का|पुष्टि|डिटेल|भेज|याद\s*दिला",
    re.IGNORECASE,
)


def asks_for_booking(said: str) -> bool:
    """The burst asks for the booking itself (_ASKS_BOOKING), for the place it is at (the location,
    the way), or asks anything at all: the booking goes out again."""
    said = str(said or "").replace("’", "'")
    return bool(
        rules.asks_question(said) or _ASKS_BOOKING.search(said) or filters.asks_for_location(said) or filters.asks_the_way(said)
    )


def _said_again(answer: dict, when, appointment, said: str) -> bool:
    """A confirm or move to the very time already booked, with nothing asked and no move asked
    for before it ("see you tomorrow at 5", "ان شاء الله" to the confirmation): nothing changes,
    and no second confirmation goes (ask_model makes it "none"; the answer's own words, if any,
    are the reply). Every playbook (eval booked-same-time, lang-inshallah-english). Asked for
    (asks_for_booking: "Is it still at 5?", "Please confirm my visit tomorrow at 5", "Send me
    the location"), or after "I need to reschedule", it is the booking said again (_run_claimed's
    "reconfirm"), as before: the prompt tells the model to leave a confirm's reply empty, so
    only that message answers them."""
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if not confirmed or when is None or appointment.starts_at != when:
        return False
    if effective_action(answer["appointment"]["action"], appointment) != "reschedule":
        return False  # running late at the booked time is "on time" (_run_claimed)
    return appointment.customer_state != LeadAiAppointment.CustomerState.RESCHEDULE and not asks_for_booking(said)


def ask_model(
    system: str,
    context: str,
    appointment,
    now,
    closed_dates,
    user: str = "",
    *,
    deadline: float | None = None,
    grounding=None,
    codes: list | None = None,
    taken=(),
    shops_chat: bool = False,
    alternatives: list | None = None,
    said: str = "",
    customer_script: str = "",
    name: str = "",
):
    """(answer, validated time, completions, rejection reason, still_invalid).

    ``codes`` collects the SlotError code of each refused proposal, and
    ``alternatives`` the free slots offered for a taken one. ``shops_chat``: the
    shops schema and its own prompt cache key (the caller passes its prompt).
    ``said``: the burst's own words (check_proposal's walk-in). The time already
    booked, said again with no question, comes back as no time and action "none"
    (_said_again).
    ``customer_script``: the script of the customer's latest typed message
    (script.customer_script: LATIN for English letters, '' when nothing typed
    says anything). A reply of the model's own words written in another script is
    asked for once more in theirs (prompt.SCRIPT_CORRECTION, or LATIN_CORRECTION
    for a reply in Arabic script or Devanagari to English letters; time
    permitting; board T19, every playbook), and only its words are taken from that
    answer, when they are in the script; otherwise the reply goes as it was
    (``answer["script_fix"]`` says which: "fixed", "kept", "no time", or "failed"
    when that second call itself failed, which never fails the turn: the first
    answer is a usable one). One such call at most in a turn. ``name``: the
    customer's name as the context gives it; written as their profile has it
    ("Hi محمد" to English letters), it says nothing of the reply's script
    (script.has_script).

    A slot another client has is offered around by code (``answer["slot_taken"]``,
    shops.slot_taken with ``alternatives``) when the answer keeps the visit
    tentative at it (taken_tentative), or when a confirm refused as taken was
    corrected with a reply that does not name the two free starts; never where
    code would not book the visit itself (_code_may_act), and never while a person
    has the chat (_run_claimed).
    """
    codes = codes if codes is not None else []
    alternatives = alternatives if alternatives is not None else []
    answer_schema = schema.schema_for(shops_chat)
    cache_key = openai_client.SHOPS_CACHE_KEY if shops_chat else openai_client.CACHE_KEY
    messages = [{"role": "system", "content": system}, {"role": "user", "content": context}]
    completions = []
    first = openai_client.complete_json(messages, answer_schema, user=user, deadline=deadline, cache_key=cache_key)
    completions.append(first)
    answer = _shape(schema.normalize(first.data, shops=shops_chat))

    def in_their_script(answer, when, last):
        """The script correction (T19) on a usable answer whose own words go out. With no words of
        its own to send, its language only follows their script, as code's lines do (script.follow):
        nothing said to "ان شاء الله" in an English chat is still an English answer."""
        if not customer_script or when is not None:
            return answer
        if not answer["send"] or not answer["reply"]:
            answer["language"] = script.follow(answer["language"], customer_script)
            return answer
        if answer["opt_out"] != "none" or answer.get("converted") or answer.get("slot_taken"):
            return answer  # code writes those words
        if script.has_script(answer["reply"], customer_script, name):
            return answer
        if deadline is not None and deadline - time.monotonic() < CORRECTION_NEEDS:
            answer["script_fix"] = "no time"
            return answer
        if customer_script == script.LATIN:
            check = prompt.LATIN_CORRECTION
        else:
            check = prompt.SCRIPT_CORRECTION.format(script=script.NAMES[customer_script])
        asked = messages + [
            {"role": "assistant", "content": json.dumps(last.data, ensure_ascii=False)},
            {"role": "user", "content": check},
        ]
        try:
            again = openai_client.complete_json(asked, answer_schema, user=user, deadline=deadline, cache_key=cache_key)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - the first answer is usable: it goes as it was (SPEC A, T19)
            # Cut off (Urdu script reaches max_tokens sooner), refused, unreachable, throttled: never the turn's end.
            if isinstance(exc, openai_client.AssistantError):
                logger.info("Lead AI script correction failed (%s); the first answer goes", exc.code)
            else:
                logger.exception("Lead AI script correction failed; the first answer goes")
            answer["script_fix"] = "failed"
            return answer
        completions.append(again)
        fixed = schema.normalize(again.data, shops=shops_chat)
        if fixed["send"] and fixed["reply"] and script.has_script(fixed["reply"], customer_script, name):
            answer["reply"], answer["reply_en"] = fixed["reply"], fixed["reply_en"]
            # The language its words are written in: an English-letter reply is never "ar".
            answer["language"] = script.follow(fixed["language"], customer_script)
            answer["script_fix"] = "fixed"
        else:
            answer["script_fix"] = "kept"  # no better: the first words go out as they were
        return answer

    def checked(answer):
        when = check_proposal(
            answer["appointment"], appointment, now, closed_dates, grounding=grounding, segment=answer["segment"], taken=taken,
            said=said,
        )
        if _said_again(answer, when, appointment, said):
            answer["appointment"] = dict(NO_TIME)
            return None
        return when

    def held_by_another(answer) -> bool:
        free = taken_tentative(answer, appointment, now, closed_dates, taken, said)
        if free:
            codes.append("taken")
            alternatives[:] = free
            answer["slot_taken"] = True
        return bool(free)

    try:
        when = checked(answer)
    except hours.SlotError as exc:
        reason = exc.message
        codes.append(exc.code)
        if exc.alternatives:
            alternatives[:] = exc.alternatives
    else:
        held_by_another(answer)
        return in_their_script(answer, when, first), when, completions, "", False
    if deadline is not None and deadline - time.monotonic() < CORRECTION_NEEDS:
        answer["appointment"] = dict(NO_TIME)
        return answer, None, completions, f"{reason} / no time for a second try", True
    messages += [
        {"role": "assistant", "content": json.dumps(first.data, ensure_ascii=False)},
        {"role": "user", "content": prompt.CORRECTION.format(reason=reason)},
    ]
    second = openai_client.complete_json(messages, answer_schema, user=user, deadline=deadline, cache_key=cache_key)
    completions.append(second)
    answer = _shape(schema.normalize(second.data, shops=shops_chat))
    try:
        when = checked(answer)
    except hours.SlotError as exc:
        codes.append(exc.code)
        if exc.alternatives:
            alternatives[:] = exc.alternatives
        answer["appointment"] = dict(NO_TIME)
        return answer, None, completions, f"{reason} / {exc.message}", True
    # Not where code would not book the visit itself either (_code_may_act): a correction that
    # hands the chat to a person, or answers a call, keeps its own words.
    refused_as_taken = codes[-1:] == ["taken"] and bool(alternatives) and _code_may_act(answer, said)
    if not held_by_another(answer) and refused_as_taken and when is None and not offers_starts(answer["reply"], alternatives):
        # The slot was refused as taken and the correction offers other times (or none):
        # the two nearest free ones come from code, never another guess.
        answer["slot_taken"] = True
    return in_their_script(answer, when, second), when, completions, reason, False


def upgrade_exact_time(
    answer: dict,
    said: str,
    appointment,
    now,
    closed_dates=(),
    *,
    taken=(),
    grounding=None,
    handed_over: bool = False,
    agent_last: bool = False,
) -> dt.datetime | None:
    """The customer's own exact day and time, free and inside hours, which the model
    recorded only as tentative: confirmed after all (board T18; every playbook).

    ``said`` is the burst's own words. Only an office visit the customer stated
    plainly is upgraded: never a time said as no promise (hours.no_promise: "I
    may come", "if I finish early", "I can't come", "after 5 pm", "are you open
    then?"), nor one put off ("Tomorrow at 5 pm, I will let you know"), an
    owner's day and hour with no place (a viewing at their property, or our
    office? check_proposal's no_place), a call, someone outside our segments or a
    fixed line. Never while a person has the chat (``handed_over``) or after a
    colleague's message (``agent_last``): their plan is not overridden. Returns
    the checked start, with the answer changed to a confirm; else None, untouched.
    """
    proposal = answer["appointment"]
    if proposal["action"] != "tentative" or not proposal.get("date") or not proposal.get("time"):
        return None
    # A fixed line, someone outside our segments, a handover in this answer or a call (_code_may_act).
    if proposal.get("place") not in (None, "office") or not _code_may_act(answer, said):
        return None
    # Handed to a person earlier (a call, an owner's viewing, someone abroad), or a colleague's plan: theirs to agree, not ours.
    if handed_over or agent_last:
        return None
    if hours.no_promise(said) or rules.mentions_deferral(said):
        return None
    day, at = hours.parse_date(proposal["date"]), hours.parse_time(proposal["time"])
    days, times = hours.named_days(said, now), hours.named_times(said)
    # One day and one hour: "Wednesday at 5 or 6" or "Tuesday or Wednesday at 5" is a choice, not a booking.
    one_day = len({value for value in days if value - dt.timedelta(days=7) not in days}) == 1
    if day is None or at is None or day not in days or not one_day or times != {at}:
        return None
    # Checked with the model's own place: an owner's time with none is refused (no_place).
    upgraded = {**proposal, "action": "confirm"}
    try:
        start = check_proposal(
            upgraded, appointment, now, closed_dates, grounding=grounding, segment=answer["segment"], taken=taken, said=said
        )
    except hours.SlotError:
        return None
    booked = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if start is None or (booked and appointment.starts_at == start):
        return None  # the time already booked, said again: nothing to send
    answer["appointment"] = {**upgraded, "place": "office"}
    return start


def _offered(text: str, start: dt.datetime, now) -> set:
    """The exact starts our words offered (hours.offered_starts), when they name no day or this
    start's day."""
    days = hours.named_days(text or "", now)
    if days and start.astimezone(hours.DUBAI).date() not in days:
        return set()
    return hours.offered_starts(text)


def their_time(
    start: dt.datetime, *, said: str, words: str = "", our_last: str = "", ours: str = "", appointment=None, now=None
) -> bool:
    """The customer gave this start themselves, or took it from us.

    Gave it: its hour in this burst's words, in any form they write one (hours.said_times: "5
    pm", a bare "5", "at five", "half past 5", "kal saade 5 baje", "الساعة الخامسة مساءً"; or
    hours.hours_ahead: "in 1 hour"), or an hour said in a way not read there (hours.marks_hour:
    "8 baje"), which stays the model's reading, as the live grounding left it; this start's
    hour in what they wrote before as hours.spoken_times reads it ("Tomorrow at 5" or "at
    five" an answer ago; not "450 sq ft", nor a bare number); coming now, read as
    check_proposal reads a walk-in ("I'm here", "Almost there", "وصلت"); the open visit's own
    time. Took it: one of the exact times our side offered (hours.offered_starts, on a day it
    named): the only one our last message offered ("Would tomorrow at 5 PM work?", "Does 5 work
    for you tomorrow?" "Yes"), or one they picked with more than a plain yes ("the earlier
    one"); from the ones before it (``ours``: our side's last three, the live grounding's own)
    only when our last message offered no time ("Ok the first one" after our location). A plain
    "Yes" or "ok" to two slots picks neither. ``words``: what the customer wrote lately (the
    live grounding's own)."""
    local = start.astimezone(hours.DUBAI)
    if appointment is not None and appointment.starts_at == start:
        return True
    heard, ahead = hours.said_times(said), hours.hours_ahead(said)
    if local.time() in heard or (now is not None and any(abs(start - (now + gap)) <= hours.SLOT for gap in ahead)):
        return True
    if not heard and not ahead and hours.marks_hour(said):
        return True  # an hour they said in a way not read here: as the model read it
    if local.time() in hours.spoken_times(words or ""):
        return True  # an answer ago
    if now is not None and (_walk_in(start, said, now) or (start - now <= WALK_IN and _NOW_WORDS.search(said or ""))):
        return True
    plain = rules.is_acceptance(said) or rules.is_acknowledgement(said)
    offered = hours.offered_starts(our_last)
    if offered:
        # Our last message offered times: only those can be taken.
        last = _offered(our_last, start, now)
        return local.time() in last and (len(offered) == 1 or not plain)
    return not plain and local.time() in _offered(ours, start, now)


def named_hour(said: str, now) -> dt.time | None:
    """The one hour the customer's words name (hours.said_times, or a time from now), else None:
    what code's two free slots start from when the model booked another time."""
    heard = set(hours.said_times(said))
    if now is not None:
        heard |= {(now + gap).astimezone(hours.DUBAI).time() for gap in hours.hours_ahead(said)}
    return next(iter(heard)) if len(heard) == 1 else None


def unasked_confirm(
    answer: dict,
    when,
    appointment,
    now,
    closed_dates=(),
    *,
    taken=(),
    said: str = "",
    words: str = "",
    our_last: str = "",
    ours: str = "",
    handed_over: bool = False,
) -> bool:
    """A shops confirm of a time the customer neither gave nor took (their_time): no booking,
    the two free slots instead. True when the answer was changed; the caller drops ``when``.

    The model booked "Yes, book me for this evening" (the first nudge's "Shall I book you for
    this evening?") at 4 PM, a time nobody named, in every run of eval shops-nudge-yes, and the
    live grounding let it through (any digit the customer ever wrote, "450 sq ft", grounds an
    hour). The visit becomes tentative in their words, and the step is the two free slots for
    the day and the part of it they or our message named (shops.yes_slots, answer["unasked"];
    model_step sends them unless the licence request or a fixed line goes first), from the hour
    they named when the model booked another one ("4 works", booked 4:30: named_hour). Not for a
    move (a visit already confirmed), nor while a person has the chat (the booking texts stay
    theirs: F1), nor where code would not act on a visit itself (_code_may_act). The time T18
    confirms (upgrade_exact_time) is always their own. ``ours``: our side's last three messages
    (their_time)."""
    if when is None or handed_over:
        return False
    if effective_action(answer["appointment"]["action"], appointment) != "confirm" or not _code_may_act(answer, said):
        return False
    if their_time(when, said=said, words=words, our_last=our_last, ours=ours, appointment=appointment, now=now):
        return False
    slots = shops.yes_slots(said, our_last, now, closed_dates, taken, at=named_hour(said, now))
    if not slots:
        return False
    # Their own words for the agents, never the model's (which may name the time it picked).
    words_of_theirs = (said or "").strip()[:255] or answer["appointment"].get("customer_words") or None
    answer["appointment"] = {"action": "tentative", "place": "office", "date": None, "time": None, "customer_words": words_of_theirs}
    answer["unasked"] = {"start": when, "slots": slots}
    return True


# What own_offer did to the model's tentative (the turn's "own_offer").
OWN_DROPPED = "dropped"
OWN_UNTIMED = "untimed"


def own_offer(answer: dict, *, appointment, said: str, words: str = "", our_last: str = "", yes: bool = False, now=None) -> str:
    """A shops chat's tentative visit that is only the model's own slot offer records no visit: ""
    when the answer stays as it was, else what was done to it (live and in the eval). A tentative
    judged theirs is marked (``answer["theirs"]``), so a request for photos with it keeps it
    (model_step).

    Live, the model answered "New" "One" (a new licence) with two slots of its own, today at 11:00
    AM or 11:30 AM, and a tentative at 11:00 (2026-10-15, appointment 16): the chat's banner showed
    "Time mentioned: 11:00 AM", the lead got a MEETING TENTATIVE comment and the agents an alert, for
    a time the customer never named. Only the model's tentative office visit while none is open (an
    open one is the model's to keep, and the deferral rule's never comes here), with nothing that
    must go instead (a handover, a fixed line, a taken slot, an opt-out). unasked_confirm's, made of
    a confirm of a slot nobody took, stays only after a yes or words of coming (its two free slots
    go either way). Any other stays as it is when:

    - its day and time are theirs (their_time: the hour said this burst in any form, or an answer
      ago, or coming now); taken from us only as a yes to the one slot we offered, never as
      "anything but a plain yes" to two (unasked_confirm's reading of a confirm): a tentative at one
      of our slots after "How much sqf" is our offer said again;
    - it has a day and no time, and that day is theirs (hours.named_days of what they wrote);
    - it has neither, and the reply invites no one (a deferral said in two messages, which the
      deferral rule leaves to the model).

    Otherwise, when they said yes to our offer (``yes``: agreed_to_come, or a message that opens
    with a yes: opens_with_yes), named the day, or say they will come (comes: "Maybe tomorrow",
    "I'll come around 5", "shaam ko aaunga"), the visit stays tentative in their words, at no day or
    hour of ours (OWN_UNTIMED); else it was our invitation alone: action none, the invitation kept
    for _apply to count, and no appointment, banner, CRM tentative or alert (OWN_DROPPED).
    ``words``: what they wrote lately (the live grounding's own); ``our_last``: our last message."""
    proposal = answer["appointment"]
    if appointment is not None or proposal["action"] != "tentative" or proposal.get("place") not in (None, "office"):
        return ""
    if answer.get("slot_taken") or answer.get("converted") or answer["opt_out"] != "none" or answer["handover"]["needed"]:
        return ""
    coming = yes or comes(said, now)
    if answer.get("unasked"):
        # unasked_confirm's visit in their words, for a confirm of a slot nobody took: theirs after a yes or
        # words of coming ("Yes, book me for this evening"); after "New" "One" it was our own slot, and its two
        # free slots still go (model_step), with no visit recorded.
        if coming:
            answer["theirs"] = True
            return ""
        answer["appointment"] = dict(NO_TIME)
        return OWN_DROPPED
    day, at = hours.parse_date(proposal.get("date")), hours.parse_time(proposal.get("time"))
    day_theirs = day is not None and day in hours.named_days(f"{words} {said}", now)
    if day is not None and at is not None:
        start = dt.datetime.combine(day, at, tzinfo=hours.DUBAI)
        single = our_last if yes and len(hours.offered_starts(our_last)) == 1 else ""
        theirs = their_time(start, said=said, words=words, our_last=single, ours="", now=now)
    elif day is not None:
        theirs = day_theirs
    else:
        theirs = not (answer["invited_to_meeting"] or filters.offers_time(answer["reply"] or ""))
    if theirs:
        answer["theirs"] = True
        return ""
    if coming or day_theirs:
        answer["appointment"] = {
            "action": "tentative",
            "place": "office",
            "date": proposal.get("date") if day_theirs else None,
            "time": None,
            # Their own words for the agents, never the model's (which may name the time it picked).
            "customer_words": (said or "").strip()[:255] or proposal.get("customer_words") or None,
        }
        answer["theirs"] = True
        return OWN_UNTIMED
    answer["appointment"] = dict(NO_TIME)
    return OWN_DROPPED


def asked_location(text: str, asked: str, office_address: str, maps_url: str = "") -> str:
    """What code's own slots (shop_flow.slots_text) go out with when the customer asked for the
    location in the same burst ("Yes please, send me the location"): the Maps link, else the
    address, unless the text has it already; '' when they did not ask (live and in the eval)."""
    if not filters.asks_for_location(asked):
        return ""
    if maps_url:
        return "" if maps_url in (text or "") else maps_url
    return "" if filters.carries_location(text, office_address) else office_address


def _same_words(left: str, right: str) -> bool:
    return " ".join(str(left or "").split()).casefold() == " ".join(str(right or "").split()).casefold()


def _merge_facts(old: dict, new: dict) -> dict:
    """The known facts with the new ones over them; a shops chat's notes (a list of
    questions for our agent) are added to, never replaced."""
    merged = dict(old or {})
    for key, value in (new or {}).items():
        if key == "notes" and isinstance(value, list):
            if value:
                merged[key] = shops.merge_notes(merged.get(key), value)
        elif value not in (None, "", []):
            merged[key] = value
    return merged


def _urgent(facts: dict) -> bool:
    move_in = str(facts.get("move_in") or "")
    return bool(_URGENT.search(move_in)) and not _NOT_URGENT.search(move_in)


def _is_commercial(segment: str, facts: dict) -> bool:
    kind = str(facts.get("property_type") or "").lower()
    return segment == "commercial_tenant" or any(word in kind for word in ("shop", "office", "warehouse", "commercial"))


# The turn ------------------------------------------------------------------------------


def run_turn(message_id: int, *, attempt: int = 0, first_queued_at: str = "") -> Outcome:
    deadline = time.monotonic() + TURN_BUDGET
    message = _load(message_id)
    if message is None or message.direction != Message.Direction.INBOUND:
        return _skip("not an inbound message")
    if message.kind in SKIP_KINDS or message.mirrored_from_id or transcript.is_revoke(message):
        return _skip("nothing to answer")
    conversation = message.conversation
    chat = LeadAiChat.objects.filter(conversation=conversation, active=True).first()
    if chat is None:
        return _skip("not a Lead AI chat")
    if conversation.linked_conversation_id:
        return _skip("the chat was transferred to another agent")
    if LeadAiTurn.objects.filter(inbound=message).exists():
        return _skip("already handled")
    if _is_deleted(message):
        return _skip("the customer deleted this message")
    if _newer_inbound(message) is not None:
        return _skip("a newer message will be answered")
    if reminders.tap_on_reminder(message)[0] is not None:
        return _skip("a reminder tap is answered by its own handler")
    now = timezone.now()
    # The customer may still be typing: wait a little, within a ceiling.
    try:
        first = dt.datetime.fromisoformat(first_queued_at) if first_queued_at else message.created_at
    except ValueError:
        first = message.created_at
    if now - message.created_at < STILL_TYPING and now - first < MAX_DEBOUNCE:
        raise NotReady(10, "customer may still be typing")

    revoked = transcript.revoked_wamids(conversation)
    burst = _burst(conversation, message, revoked)
    settings_row = LeadAiSettings.load()
    state = LeadAiChatState.for_conversation(conversation)
    playbook = lane.playbook_for(conversation)
    opt = _burst_opt_out(burst, meeting_open=_open_appointment(conversation) is not None, shops_chat=playbook == lane.IC_SHOPS)
    if opt:
        return _rule_opt_out(message, conversation, chat, state, settings_row, burst, opt, playbook=playbook)

    if not settings_row.answers(conversation.contact.wa_id):
        return _skip("assistant switched off")
    if not openai_client.configured():
        return _skip("no Lead AI key")
    if settings_row.paused_until and settings_row.paused_until > now:
        return _skip("assistant paused after OpenAI errors")
    if state.responsible_checked_at is None:
        # Look up the CRM record's responsible person once, early, so the
        # first booking's alert already reaches them (owner's choice).
        LeadAiChatState.objects.filter(pk=state.pk).update(responsible_checked_at=now)
        from ..tasks import resolve_responsible

        transaction.on_commit(lambda pk=conversation.pk: resolve_responsible.delay(pk))
    if state.stopped_at is not None:
        return _skip(f"stopped: {state.stop_reason}")
    if state.paused_at is not None:
        # No agent behind it: the assistant paused itself for a broker (_apply).
        return _skip("paused by an agent" if state.paused_by_id else "paused until an agent presses Resume")
    if now - message.created_at > STALE_AFTER:
        if Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, pk__gt=message.pk).exists():
            return _skip("the message is too old to answer")
        alerts.raise_alert(
            kind="stale",
            conversation=conversation,
            title="Lead AI did not answer an old message",
            text=f"A message from {_who(conversation)} waited too long for the assistant (the system was busy). "
            "Please reply by hand.",
            dedupe_key=f"stale:{conversation.pk}:{message.pk}",
            crm_url=_crm_url(chat),
        )
        return _skip("the message is too old to answer")

    heard: dict[int, str] = {}
    give_up = attempt >= len(AUDIO_WAITS)
    for item in burst:
        if item.kind != "audio":
            continue
        text = transcribe.transcript_for(item, give_up=give_up, deadline=deadline)
        if text is None:
            raise NotReady(AUDIO_WAITS[min(attempt, len(AUDIO_WAITS) - 1)], "voice note downloading")
        heard[item.pk] = text

    turn = _claim(message)
    if turn is None:
        return _skip("already handled")

    live.thinking(conversation, True)
    # What a booking holds until it is stored (the office lock); let go however the turn ends.
    hold = contextlib.ExitStack()
    try:
        outcome = _run_claimed(
            turn, message, conversation, chat, state, settings_row, burst, heard, now, revoked, deadline, playbook=playbook,
            hold=hold,
        )
        if turn.calls:
            _breaker_ok(settings_row)
    except SoftTimeLimitExceeded:
        outcome = Outcome(LeadAiTurn.Status.FAILED, "interrupted: time limit")
        turn.error = "SoftTimeLimitExceeded"
        _alert_interrupted(conversation, chat)
    except openai_client.AssistantError as exc:
        outcome = Outcome(LeadAiTurn.Status.FAILED, f"OpenAI: {exc.code}")
        turn.error = str(exc)[:2000]
        if _error_kind(exc) == "content":
            # OpenAI answered, just not usefully: this chat's agent is told; no outage.
            _alert_failure(conversation, chat, exc.code)
        else:
            _breaker_failed(settings_row, exc, conversation, chat)
    except Exception as exc:  # noqa: BLE001 - recorded on the turn, told to the agent
        logger.exception("Lead AI turn failed on message %s", message_id)
        outcome = Outcome(LeadAiTurn.Status.FAILED, type(exc).__name__)
        turn.error = str(exc)[:2000]
        _alert_failure(conversation, chat, type(exc).__name__)
    finally:
        hold.close()
        live.thinking(conversation, False)
    return _finish(turn, outcome)


def _finish(turn, outcome: Outcome) -> Outcome:
    turn.status = outcome.status
    turn.reason = outcome.reason[:255]
    turn.actions = {**(turn.actions or {}), **(outcome.actions or {})}
    if outcome.reply_message_id:
        turn.reply_message_id = outcome.reply_message_id
    turn.finished_at = timezone.now()
    turn.save()
    return outcome


def _claim(message) -> LeadAiTurn | None:
    try:
        with transaction.atomic():
            return LeadAiTurn.objects.create(conversation_id=message.conversation_id, inbound=message)
    except IntegrityError:
        return None


def _error_kind(exc) -> str:
    kind = getattr(exc, "kind", None)
    if kind:
        return kind
    return "final" if getattr(exc, "final", False) else "transport"


def _alert_failure(conversation, chat, code: str) -> None:
    alerts.raise_alert(
        kind="ai_error",
        conversation=conversation,
        title="Lead AI could not reply",
        text=f"The assistant could not answer {_who(conversation)} ({code}). Please reply by hand.",
        dedupe_key=f"ai_error:{conversation.pk}:{timezone.now():%Y%m%d%H}",
        crm_url=_crm_url(chat),
    )


def _alert_interrupted(conversation, chat) -> None:
    alerts.raise_alert(
        kind="ai_error",
        conversation=conversation,
        title="Lead AI was interrupted",
        text=f"The assistant ran out of time while answering {_who(conversation)}. Please check the chat: "
        "its reply may or may not have gone out, and reply by hand if needed.",
        dedupe_key=f"ai_interrupted:{conversation.pk}:{timezone.now():%Y%m%d%H}",
        crm_url=_crm_url(chat),
    )


def _breaker_ok(settings_row) -> None:
    if settings_row.consecutive_failures:
        LeadAiSettings.objects.filter(pk=settings_row.pk).update(consecutive_failures=0, paused_until=None)


def _breaker_failed(settings_row, exc, conversation, chat) -> None:
    now = timezone.now()
    if _error_kind(exc) == "final":
        # A wrong key or no credit: the admins once a day, the chat's agent once an hour.
        alerts.raise_alert(
            kind="ai_quota",
            conversation=conversation,
            title="Lead AI is not working: OpenAI refused the request",
            text=f"OpenAI answered {exc.code} {exc.detail}. The assistant cannot reply until the key, its credit "
            "or the request is fixed.",
            dedupe_key=f"ai_quota:{now:%Y%m%d}",
            admins=True,
        )
        _alert_failure(conversation, chat, exc.code)
        return
    failures = settings_row.consecutive_failures + 1
    update = {"consecutive_failures": failures}
    if failures >= BREAKER_FAILURES:
        update["paused_until"] = now + BREAKER_PAUSE
        alerts.raise_alert(
            kind="ai_down",
            conversation=conversation,
            title="Lead AI paused: OpenAI is failing",
            text=f"{failures} OpenAI calls failed in a row ({exc.code}). The assistant pauses for 5 minutes, "
            "then tries again.",
            dedupe_key=f"ai_down:{now:%Y%m%d%H}",
            admins=True,
        )
    LeadAiSettings.objects.filter(pk=settings_row.pk).update(**update)
    _alert_failure(conversation, chat, exc.code)


def _calls_today() -> int:
    since = timezone.now() - dt.timedelta(hours=24)
    return LeadAiTurn.objects.filter(created_at__gte=since).aggregate(n=Sum("calls"))["n"] or 0


def _window_open(conversation, now) -> bool:
    conversation.refresh_from_db(fields=["session_expires_at"])
    return bool(conversation.session_expires_at and conversation.session_expires_at - now >= WINDOW_MARGIN)


def still_ours(message, chat_pk, campaign_templates, settings_pk) -> str:
    """'' when the reply may still go out, else why not."""
    chat = LeadAiChat.objects.filter(pk=chat_pk).select_related("conversation", "conversation__contact").first()
    if chat is None or not chat.active:
        return "moved to the inbox while thinking"
    if chat.conversation.linked_conversation_id:
        return "transferred while thinking"
    state = LeadAiChatState.objects.filter(conversation_id=chat.conversation_id).first()
    if state is not None and (state.stopped_at or state.paused_at):
        return "stopped or paused while thinking"
    if not LeadAiSettings.objects.get(pk=settings_pk).answers(chat.conversation.contact.wa_id):
        return "switched off while thinking"
    if _newer_inbound(message) is not None:
        return "a newer message arrived while thinking"
    if human_after(message, campaign_templates):
        return "an agent answered while thinking"
    if not _window_open(chat.conversation, timezone.now()):
        return "the 24-hour window closed"
    return ""


def _send(conversation, text: str, turn, extra: dict | None = None):
    from apps.inbox import services as inbox_services

    payload = {"source": SOURCE, "turn": turn.pk}
    payload.update(extra or {})
    return inbox_services.send_text(conversation, None, text, payload=payload)


# Opt-outs ------------------------------------------------------------------------------


def _rule_opt_out(message, conversation, chat, state, settings_row, burst, kind: str, *, playbook: str = lane.GENERAL) -> Outcome:
    """A STOP, wrong number or "not interested" found by code: recorded whatever the
    assistant's state; the polite line only when the assistant may speak now."""
    turn = _claim(message)
    if turn is None:
        return _skip("already handled")
    # Switched off for this customer (the dark launch): the state is kept, so no
    # reminder or later reply reaches them, but nobody is alerted about a chat
    # the assistant is not part of.
    answers = settings_row.answers(conversation.contact.wa_id)
    recorded = record_opt_out(conversation, kind, by="rule", quiet=not answers, words=_their_words(burst), playbook=playbook)
    actions = {"opt_out": kind, "by": "rule"}
    if not recorded:
        return _finish(turn, Outcome(LeadAiTurn.Status.SKIPPED, f"opt-out ({kind}) already recorded", actions=actions))
    campaign_templates = transcript.campaign_template_ids(conversation)
    may_speak = (
        answers
        and openai_client.configured()
        and state.paused_at is None
        and state.stopped_at is None
        and _window_open(conversation, timezone.now())
        and not human_after(message, campaign_templates)
    )
    if not may_speak:
        return _finish(turn, Outcome(LeadAiTurn.Status.SKIPPED, f"opt-out ({kind}) recorded, no line sent", actions=actions))
    language = state.language or rules.guess_language(" ".join((item.body or "") for item in burst))
    # The line follows the script they type in ("توقف" after an English chat is answered in Arabic; T19).
    language = script.follow(language, script.customer_script([item.body or "" for item in burst if item.kind == "text"]))
    try:
        sent = _send(conversation, rules.line_for(kind, language, shops=playbook == lane.IC_SHOPS), turn)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - the opt-out is recorded either way
        logger.warning("Lead AI opt-out line failed on conversation %s: %s", conversation.pk, exc)
        return _finish(turn, Outcome(LeadAiTurn.Status.FAILED, "opt-out line not sent", actions=actions))
    return _finish(turn, Outcome(LeadAiTurn.Status.REPLIED, f"opt-out ({kind})", reply_message_id=sent.pk, actions=actions))


STOP_KINDS = (rules.STOP_ALL, rules.WRONG_NUMBER, rules.SPAM)


def record_opt_out(
    conversation, kind: str, *, by: str, quiet: bool = False, words: str = "", playbook: str | None = None, reason: str = ""
) -> bool:
    """Record a customer's opt-out once; True only the first time. Sends nothing.

    STOP and wrong number (and, in a shops chat, spam) stop the assistant and
    drop the open meeting's reminder (the meeting itself stays: they may still
    come). "Not interested" cancels the open meeting, so nobody is reminded of,
    or waits for, a visit the customer has declined. Either way no follow-up is
    left planned. The agents are told; the CRM gets a note; ``quiet`` skips both
    (a chat the switched-off assistant is not part of). ``by`` is "rule",
    "model" or "reminder_check". A shops chat's lead also gets its fields
    (crm_fields.opt_out_writes): Opted out, or Lost with ``reason`` (else the
    customer's ``words``), quiet or not: those fields are what keeps every later
    campaign away from someone who asked us to stop (board C10, C11). A STOP, a
    wrong number or spam also puts the phone on the opt-out registry, in every
    playbook, which blocks it on every number and campaign (optout.py; T60).
    """
    now = timezone.now()
    state = LeadAiChatState.for_conversation(conversation)
    no_follow_up = {"followup_asked_at": None, "followup_due_at": None}
    if kind in STOP_KINDS:
        updated = LeadAiChatState.objects.filter(pk=state.pk, stopped_at__isnull=True).update(
            stopped_at=now, stop_reason=kind, **no_follow_up
        )
    elif kind == rules.NOT_INTERESTED:
        updated = LeadAiChatState.objects.filter(pk=state.pk, not_interested_at__isnull=True).update(
            not_interested_at=now, **no_follow_up
        )
    else:
        return False
    if kind in STOP_KINDS:
        # Every number and every campaign, not only this chat (board T60, Q8): the registry
        # the campaign paths ask (optout.phones_blocked), quiet or not, like the fields below,
        # and also when the chat was stopped already (an automatic reply, a STOP before the
        # registry existed): the registry keeps the first reason and never raises.
        from .. import optout

        optout.record(conversation.contact.wa_id, reason=reason or words or kind, source=optout.source_for(kind), conversation=conversation)
    if not updated:
        return False
    from ..tasks import record_crm_note, sync_appointment_crm

    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    appointment = _open_appointment(conversation)
    if appointment is not None and kind == rules.NOT_INTERESTED:
        with transaction.atomic():
            current = (
                LeadAiAppointment.objects.select_for_update()
                .filter(pk=appointment.pk, status__in=LeadAiAppointment.OPEN)
                .first()
            )
            if current is not None:
                current.status = LeadAiAppointment.Status.CANCELLED
                current.reminder_due_at = None
                current.log("cancelled", by="customer", reason="not interested", source=by)
                current.save(update_fields=["status", "reminder_due_at", "history", "updated_at"])
                revision = len(current.history or [])
                transaction.on_commit(
                    lambda pk=current.pk, rev=revision: sync_appointment_crm.delay(pk, "cancelled", False, rev)
                )
                appointment_alert(conversation, chat, current, "cancelled", False, _customer_name(conversation, state.facts or {}), revision)
    elif appointment is not None:
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(reminder_due_at=None)
    if (playbook if playbook is not None else lane.playbook_for(conversation)) == lane.IC_SHOPS:
        # Data, not an alert: written even for a chat the switched-off assistant is not part of.
        crm_fields.queue(conversation, chat, crm_fields.opt_out_writes(kind, reason or words))
    if quiet:
        return True
    if kind == rules.SPAM:
        alerts.raise_alert(
            kind="opt_out",
            conversation=conversation,
            appointment=appointment,
            title=f"{_who(conversation)} sent what looks like spam",
            text="The assistant read the customer's message as spam (a chain message, a scam or an advert), sent nothing "
            "and stopped in this chat. The phone is now on the opt-out registry: no campaign on any number reaches it."
            + (
                " In Bitrix the lead goes to Junk Lead with Bot Status Lost. If that is wrong, press Resume AI (it restarts "
                "the assistant and takes the phone off the registry again) and move the lead back in Bitrix by hand."
                if crm_fields.lead_of(chat, conversation) is not None
                else " If that is wrong, press Resume AI: it restarts the assistant and takes the phone off the registry again."
            ),
            dedupe_key=f"opt_out:{conversation.pk}:{now:%Y%m%d}",
            crm_url=_crm_url(chat),
        )
    elif kind in (rules.STOP_ALL, rules.WRONG_NUMBER):
        alerts.raise_alert(
            kind="opt_out",
            conversation=conversation,
            appointment=appointment,
            title=f"{_who(conversation)} asked us to stop",
            text="The customer asked us to stop messaging"
            + (" (wrong number)" if kind == rules.WRONG_NUMBER else "")
            + ". The assistant stopped in this chat"
            + (
                f"; their meeting on {hours.describe(appointment.starts_at)} will not be reminded"
                if appointment is not None and appointment.starts_at
                else ""
            )
            + ". The phone is now on the opt-out registry: no campaign on any number reaches it."
            + (
                " If it was no wrong number, press Resume AI: it restarts the assistant and takes the phone off the registry again."
                if kind == rules.WRONG_NUMBER
                else " Only an admin can take it off again (Django admin, Lead AI opt-outs)."
            ),
            dedupe_key=f"opt_out:{conversation.pk}:{now:%Y%m%d}",
            crm_url=_crm_url(chat),
        )
    transaction.on_commit(lambda pk=conversation.pk, k=kind: record_crm_note.delay(pk, k))
    transaction.on_commit(lambda pk=conversation.pk: live.appointment_changed(pk))
    return True


def _opt_out(turn, conversation, chat, state, kind: str, language: str, answer: dict, *, playbook: str = lane.GENERAL, words: str = "") -> Outcome:
    """The model (or a shops rule, ``answer["rule"]``) found an opt-out: one fixed
    polite line, then record it. Spam gets no line at all."""
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        fresh.facts = _merge_facts(fresh.facts, answer["facts"])
        fresh.language = (answer.get("line_language") or answer["language"])[:16]
        fresh.save(update_fields=["facts", "language", "updated_at"])
    by = "rule" if answer.get("rule") else "model"
    sent = None
    if kind != rules.SPAM:
        try:
            sent = _send(conversation, rules.line_for(kind, language, shops=playbook == lane.IC_SHOPS), turn)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lead AI opt-out line failed on conversation %s: %s", conversation.pk, exc)
    record_opt_out(conversation, kind, by=by, words=words, playbook=playbook, reason=answer.get("lost_reason") or "")
    actions = {"opt_out": kind, "by": by}
    if answer.get("rule"):
        actions["rule"] = answer["rule"]
    if kind == rules.SPAM:
        return Outcome(LeadAiTurn.Status.SKIPPED, "opt-out (spam) recorded, no line sent", actions=actions)
    if sent is None:
        return Outcome(LeadAiTurn.Status.FAILED, "opt-out line not sent", actions=actions)
    return Outcome(LeadAiTurn.Status.REPLIED, f"opt-out ({kind})", reply_message_id=sent.pk, actions=actions)


# The claimed turn -------------------------------------------------------------------------


def _customer_words(rows, heard: dict, burst) -> str:
    """What the customer wrote and said lately: the ground a booked hour must stand on."""
    texts = [
        transcript.inbound_text(row, heard.get(row.pk) or transcript.transcript_text(row))
        for row in rows
        if row.direction == Message.Direction.INBOUND and not getattr(row, "lead_ai_deleted", False)
    ]
    texts += [transcript.inbound_text(item, heard.get(item.pk)) for item in burst]
    return " ".join(texts)


def _our_words(rows, campaign_templates) -> str:
    """Our side's last few messages (assistant or colleague): what the customer may be agreeing to."""
    ours = [row for row in rows if row.direction == Message.Direction.OUTBOUND and transcript.who(row, campaign_templates) in ("assistant", "agent")]
    return " ".join(transcript.outbound_text(row) for row in ours[-3:])


def _context_words(rows, campaign_msg, burst, heard, facts, campaign_templates) -> str:
    """Everything the customer, the campaign and our colleagues wrote, never the
    assistant's own replies: the amounts a reply may repeat (filters.clean_reply)."""
    texts = [str(campaign_msg.body if campaign_msg else "")]
    for row in rows:
        author = transcript.who(row, campaign_templates)
        if author == "customer":
            texts.append(transcript.inbound_text(row, transcript.transcript_text(row)))
        elif author in ("agent", "campaign"):
            texts.append(transcript.outbound_text(row))
    texts += [transcript.inbound_text(item, heard.get(item.pk)) for item in burst]
    texts.append(json.dumps(facts, ensure_ascii=False))
    return " ".join(texts)


def taken_slots(conversation, now=None) -> list:
    """The starts of every OTHER chat's open office visit with a time (confirmed, or
    tentative with a time): the slots the office has no room in."""
    now = now or timezone.now()
    return list(
        LeadAiAppointment.objects.filter(
            status__in=LeadAiAppointment.OPEN,
            place=LeadAiAppointment.Place.OFFICE,
            starts_at__gte=now - hours.SLOT,
            starts_at__lte=now + hours.MAX_AHEAD + dt.timedelta(days=1),
        )
        .exclude(conversation=conversation)
        .values_list("starts_at", flat=True)
    )


@contextlib.contextmanager
def office_lock():
    """Office bookings one at a time across the workers: a Postgres advisory lock, held
    from the last look at the taken slots until the booking is stored (two customers of
    one campaign answering the same offered slot seconds apart). Elsewhere (the tests'
    SQLite) nothing. Never inside a transaction: the session holds it, not a query."""
    held = False
    if connection.vendor == "postgresql":
        deadline = time.monotonic() + OFFICE_LOCK_WAIT
        try:
            with connection.cursor() as cursor:
                while True:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [OFFICE_LOCK])
                    held = bool(cursor.fetchone()[0])
                    if held or time.monotonic() > deadline:
                        break
                    time.sleep(0.25)
        except DatabaseError:
            logger.exception("Lead AI could not take the office booking lock")
        if not held:
            logger.warning("Lead AI is booking without the office lock (waited %s s)", OFFICE_LOCK_WAIT)
    try:
        yield held
    finally:
        if held:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [OFFICE_LOCK])
            except DatabaseError:
                logger.exception("Lead AI could not release the office booking lock")


def _slot_gone(conversation, when, appointment, now, closed_dates, said: str) -> list | None:
    """Another chat's visit took this slot while the model was thinking: the free starts
    nearest it (to offer instead), else None (still free, the time they already have, or
    a walk-in)."""
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if (confirmed and appointment.starts_at == when) or _walk_in(when, said, now):
        return None
    taken = taken_slots(conversation, now)
    if not hours.is_taken(when, taken):
        return None
    own = [appointment.starts_at] if confirmed and appointment.starts_at else []
    return hours.nearest_free(when, now, closed_dates, [*taken, *own])


# A second request for the same type's media this soon is the same request (a double tap).
MEDIA_AGAIN_AFTER = dt.timedelta(minutes=10)


def _list_sent(conversation) -> bool:
    """Our shop types list went out in this chat already (shop_media.send_list); one the gateway
    refused (no credit, an error) did not, so it goes again when they ask again."""
    return (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__shop_list=True)
        .exclude(status=Message.Status.FAILED)
        .exists()
    )


def _media_recent(conversation, now) -> set[str]:
    """The shop types whose media a turn of this chat queued in the last few minutes."""
    actions = LeadAiTurn.objects.filter(conversation=conversation, created_at__gte=now - MEDIA_AGAIN_AFTER).values_list("actions", flat=True)
    return {
        str(item.get("shop_type")) for item in actions if isinstance(item, dict) and item.get("shop_step") == shop_flow.MEDIA
    }


def _media_today(conversation, now) -> set[str]:
    """The shop types whose files (a video or a photo, not the card alone) went out in this chat
    today, Dubai time, as the media task stored them (shop_media.send_file; one the gateway
    refused does not count): once a day per chat and type, unless the customer asks for them
    again (shop_flow.media_step). A task that sent nothing (no credit, the gateway down) leaves
    the next tap the files again."""
    local = hours.now_dubai(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    payloads = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, created_at__gte=midnight)
        .filter(payload__has_key="shop_media_id")
        .exclude(status=Message.Status.FAILED)
        .values_list("payload", flat=True)
    )
    return {str(item.get("shop_media")) for item in payloads if isinstance(item, dict) and item.get("shop_media")}


def _record_licence(conversation, chat, state, media, now) -> None:
    """The licence copy came (board T34) and no reply goes (a colleague answered meanwhile, the
    chat moved): the request is closed and the copy goes to the lead all the same, as _apply
    does when the turn goes on."""
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        if fresh.licence_closed_at is None:
            fresh.licence_closed_at = now
            fresh.facts = {**(fresh.facts or {}), "licence_copy": "received"}
            fresh.save(update_fields=["licence_closed_at", "facts", "updated_at"])
        crm_fields.queue_licence(conversation, chat, media)


def _asked_second_shop(message) -> bool:
    """Our message is the reply of the turn that learned they already rented a shop (_apply's
    "rented_asked"): the one that congratulated them and asked about a second shop."""
    actions = LeadAiTurn.objects.filter(reply_message=message).values_list("actions", flat=True).first()
    return isinstance(actions, dict) and actions.get("rented_asked") is True


def _shops_rule_for(
    conversation, state, burst, said, appointment, last_ours, campaign_templates, *, licence_alone: bool = False,
    licence_reply: bool = False,
) -> tuple[str, str, str]:
    """(rule, its line's language, the customer's words) when a shops rule settles this burst.

    ``licence_alone``: the licence copy came, with nothing else said (LICENCE_RECEIVED);
    ``licence_reply``: they answered our request for it with a no, which is the
    model's to answer: no shops rule reads it as "Not now" or a decline of the offer.
    """
    key = said[-1] if said else burst[-1]
    label = _tap_label(key)
    tapped = bool(label)
    text = label or ((key.body or "").strip() if key.kind == "text" else "")
    ours_last = last_ours is not None and transcript.who(last_ours, campaign_templates) == "assistant"
    facts = state.facts or {}
    quiet = state.handed_over_at is not None
    if not quiet and tapped:
        # A row of our shop types list, or a button of a type's detail card (shop_flow). Taps
        # only (a double tap is one burst of two): the last one is their choice.
        flows = [tap_rule_name(shop_flow.tap_rule(_tap_label(item), _tap_id(item))) for item in said or [key]]
        if all(flows):
            return flows[-1], shops_language(label, True, state.language), _their_words(burst)
    if not quiet and licence_alone:
        return LICENCE_RECEIVED, state.language or "en", ""
    if licence_reply:
        return "", state.language or "en", ""
    rule = shops_rule(
        text,
        tapped=tapped,
        single=len(said) <= 1,
        followup_open=state.followup_asked_at is not None and ours_last,
        # Only the reply right after "I already rented": not every later "no" in the chat.
        rented_open=(
            facts.get("already_rented") is True and ours_last and state.not_interested_at is None
            and _asked_second_shop(last_ours)
        ),
        first_answer=last_ours is not None and transcript.who(last_ours, campaign_templates) == "campaign",
        for_client_known=facts.get("for_client") is not None,
        visit_on_table=appointment is not None or (last_ours is not None and filters.offers_time(transcript.outbound_text(last_ours))),
        meeting_open=appointment is not None,
        quiet=quiet,
        facts=facts,
        end_user=facts.get("for_client") is False,
    )
    return rule, shops_language(text, tapped, state.language), _their_words(burst)


def _run_claimed(
    turn, message, conversation, chat, state, settings_row, burst, heard, now, revoked, deadline, *, playbook: str = lane.GENERAL,
    hold: contextlib.ExitStack | None = None,
) -> Outcome:
    """``hold``: where a booking keeps the office lock until it is stored (run_turn lets go of it)."""
    shops_chat = playbook == lane.IC_SHOPS
    campaign_templates = transcript.campaign_template_ids(conversation)
    if human_after(message, campaign_templates):
        return _skip("an agent already answered this message")
    if not _window_open(conversation, now):
        return _skip("the 24-hour window is closed")

    # An agent who wrote after the handover took it over: the assistant is back.
    if state.handed_over_at and (
        now - state.handed_over_at > HANDOVER_QUIET or human_after(message, campaign_templates, since=state.handed_over_at)
    ):
        LeadAiChatState.objects.filter(pk=state.pk).update(handed_over_at=None, handover_reason="", holding_line_at=None)
        state.handed_over_at = None
        state.handover_reason = ""

    if _ours_since(conversation, now - dt.timedelta(hours=1)) >= CAP_PER_HOUR or _ours_since(
        conversation, now - dt.timedelta(hours=24)
    ) >= CAP_PER_DAY:
        alerts.raise_alert(
            kind="cap",
            conversation=conversation,
            title="Lead AI paused in one chat",
            text=f"The assistant reached its reply limit with {_who(conversation)}. Please take over.",
            dedupe_key=f"cap:{conversation.pk}:{now:%Y%m%d}",
            crm_url=_crm_url(chat),
        )
        return _skip("reply limit reached")
    if _calls_today() >= settings_row.daily_call_limit:
        alerts.raise_alert(
            kind="global_cap",
            conversation=conversation,
            title="Lead AI reached its daily limit",
            text=f"The assistant made {settings_row.daily_call_limit} model calls in 24 hours and stopped answering. "
            "An admin can raise the limit in the Lead AI settings.",
            dedupe_key=f"global_cap:{now:%Y%m%d}",
            admins=True,
        )
        return _skip("daily model-call limit reached")

    newest = burst[-1]
    language = state.language or rules.guess_language(newest.body or "")
    said = _said(burst)

    # Rules that need no model, judged on the whole burst --------------------------------
    if said and all(item.kind == "unknown" and transcript.inbound_type(item) != "edit" for item in said):
        if state.unsupported_notice_at and state.unsupported_notice_at.date() == now.date():
            return _skip("unsupported message, already told today")
        sent = _send(conversation, rules.line("unsupported", language), turn)
        LeadAiChatState.objects.filter(pk=state.pk).update(unsupported_notice_at=now)
        return Outcome(LeadAiTurn.Status.REPLIED, "unsupported message", reply_message_id=sent.pk)
    if newest.kind == "text" and _auto_reply(conversation, newest):
        LeadAiChatState.objects.filter(pk=state.pk).update(stopped_at=now, stop_reason=LeadAiChatState.StopReason.AUTO_REPLY)
        alerts.raise_alert(
            kind="auto_reply",
            conversation=conversation,
            title="Lead AI stopped: the customer's side is an automatic reply",
            text=f"{_who(conversation)} answers with automatic messages, so the assistant stopped in this chat. "
            "Resume it from the Lead AI screen if that is wrong.",
            dedupe_key=f"auto_reply:{conversation.pk}",
            crm_url=_crm_url(chat),
        )
        return _skip("automatic reply on the customer's side")
    if not said and (all(item.kind == "sticker" for item in burst) or not _pending_question(_last_outbound(conversation))):
        return _skip("an acknowledgement needs no answer")

    # The model -----------------------------------------------------------------------------
    appointment = _open_appointment(conversation)
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    events = []
    if appointment is not None and appointment.customer_state:
        events.append(f"The customer told us: {appointment.get_customer_state_display().lower()}.")
    rows = transcript.conversation_rows(conversation, revoked=revoked)
    campaign_msg = transcript.campaign_message(conversation, campaign_templates)
    facts = state.facts or {}
    last_ours = _last_outbound(conversation)
    our_last = transcript.outbound_text(last_ours) if last_ours is not None else ""
    ours = _our_words(rows, campaign_templates)
    # They agreed to come (a visit open, or a plain yes to our invitation); in a shops chat, a message
    # that opens with a yes to it is one too for own_offer, and when our last message offered times and
    # nothing they said turns them down, slots offered again are no new invitation (reoffered).
    texts = [(item.body or "").strip() if item.kind == "text" else "" for item in burst if item.kind != "sticker"]
    agreed = agreed_to_come(visit_open=appointment is not None, our_last=our_last, texts=texts)
    yes = agreed or (shops_chat and visit_offered(our_last) and opens_with_yes(texts))
    reoffer = shops_chat and reoffered(agreed=agreed, our_last=our_last, texts=texts)
    own = ""  # what own_offer did to the model's tentative
    # The location went out already: not again unasked, and not for a day. Asked
    # for, it goes again (a booked customer on the way, whatever the
    # confirmation carried).
    asked = " ".join(transcript.inbound_text(item, heard.get(item.pk)) for item in burst if item.kind in ("text", "audio"))
    location = not filters.asks_for_location(asked) and location_sent(
        conversation, settings_row.office_address, settings_row.office_maps_url, since=now - LOCATION_FRESH
    )
    codes: list = []
    alternatives: list = []
    upgraded = False
    segment = _last_segment(conversation)
    # The other chats' office visits: one client per 30-minute slot, whatever the playbook.
    taken = taken_slots(conversation, now)
    # What the customer said in this burst (voice notes as heard): a walk-in, an exact time, the day they want.
    said_words = " ".join(transcript.inbound_text(item, heard.get(item.pk)) for item in burst)
    # The script they type in (T19, every playbook): their latest typed message that says something.
    customer_script = script.customer_script(
        [row.body or "" for row in rows if row.direction == Message.Direction.INBOUND and row.kind == "text" and not getattr(row, "lead_ai_deleted", False)]
    )
    # A shops chat whose licence copy we asked for (T34): a photo or a PDF now is that copy,
    # never a "media received" handover; a no to the request closes it, and a promise to send
    # it later keeps it open (shop_flow.copy_reply). Either answer is the model's to reply to.
    licence_media = None
    licence_alone = licence_reply = False
    licence_answer = ""
    if shops_chat and shop_flow.licence_open(state.licence_asked_at, state.licence_closed_at, now):
        copies = [item for item in burst if _licence_copy(item)]
        if copies:
            licence_media = copies[-1]
            licence_alone = not [item for item in said if not _licence_copy(item)]
        elif len(said) == 1 and said[0].kind == "text" and _is_licence_ask(last_ours):
            licence_answer = shop_flow.copy_reply(said[0].body)
            licence_reply = bool(licence_answer)
    # A second page of the copy that just came (board review 2b): no "media received" handover either.
    licence_page = (
        shops_chat and licence_media is None and shop_flow.another_page(state.licence_closed_at, (state.facts or {}).get("licence_copy"), now)
        and any(_licence_copy(item) for item in burst)
    )
    if licence_page and not [item for item in said if not _licence_copy(item)]:
        return _skip("another page of the licence copy", licence="page")
    shops_rule_name, shops_words = "", ""
    if shops_chat:
        shops_rule_name, rule_language, shops_words = _shops_rule_for(
            conversation, state, burst, said, appointment, last_ours, campaign_templates,
            licence_alone=licence_alone, licence_reply=licence_reply,
        )
    deferred = "" if shops_rule_name or licence_reply else deferral(
        [(item.body or "") if item.kind == "text" else "" for item in said],
        appointment=appointment,
        offered=visit_offered(ours),
        invites=state.invites,
        # A person has the chat, they declined, or they are no customer of ours.
        quiet=state.handed_over_at is not None or state.not_interested_at is not None or segment == "other",
    )
    if shops_rule_name:
        # The shops playbook's fixed words (the yes, "Not now", the check-back's
        # answer, a no after "already rented"), and its steps (a tap on the shop
        # types list or a type's card, the licence copy arriving): settled like a
        # deferral, before the model, and shaped like its answer, so the same path
        # sends and stores it.
        answer = shops_answer(shops_rule_name, rule_language, shops_words, facts)
        when, completions, rejected, still_invalid = None, [], "", False
        tapped_media = answer.get("shop_step") or {}
        if tapped_media.get("kind") == shop_flow.MEDIA:
            # A row tapped: nothing when the same type was asked for a moment ago (its files are on
            # their way), the card alone when its files went out today (shop_flow.media_step).
            answer["shop_step"] = shop_flow.media_step(
                tapped_media.get("type"), typed=False, recent=_media_recent(conversation, now), today=_media_today(conversation, now)
            )
    elif deferred:
        # A deferral of a visit we offered is settled here, before the model, not
        # by a settle() backstop: the words are fixed and the decision needs
        # nothing the model knows, so there is no call to pay for or to get wrong
        # (the first real chat was asked "When would you like to come?" again).
        # The answer is shaped like the model's and goes the same way from here
        # (still ours, the send, _apply), so the tentative visit, its alert and
        # its CRM comment are exactly those of a tentative the model proposed.
        answer = deferral_answer(deferred, rules.guess_language(deferred), appointment, segment or "other")
        when, completions, rejected, still_invalid = None, [], "", False
    else:
        grounding = (_customer_words(rows, heard, burst), ours)
        # An old shop lead's first inquiry and CRM notes (T28): read from Bitrix once, then kept;
        # a failure leaves them out and never stops the turn.
        history = lead_history.lines(*lead_history.for_turn(conversation, chat, state, now)) if shops_chat else []
        greeted = _customer_name(conversation, facts)
        context = prompt.context_message(
            now=now,
            closed_dates=settings_row.closed_dates,
            office_address=settings_row.office_address,
            segment_hint=_segment_hint(conversation, chat, campaign_msg),
            campaign_line=_campaign_line(campaign_msg),
            customer_name=greeted,
            facts=facts,
            language=language,
            handed_over=f"yes ({state.handover_reason})" if state.handed_over_at else "no",
            not_interested=state.not_interested_at is not None,
            invites=state.invites,
            appointment=appointment,
            events=events,
            conversation=[transcript.line(row, campaign_templates, transcript.transcript_text(row)) for row in rows],
            new_lines=[transcript.line(item, campaign_templates, heard.get(item.pk)) for item in burst],
            map_link=bool(settings_row.office_maps_url),
            location_sent=location,
            shops=shops.context(settings_row, facts, now, taken, history=history) if shops_chat else None,
        )
        answer, when, completions, rejected, still_invalid = ask_model(
            prompt.system_prompt(playbook),
            context,
            appointment,
            now,
            settings_row.closed_dates,
            openai_client.safety_id(conversation.pk),
            deadline=deadline,
            grounding=grounding,
            codes=codes,
            taken=taken,
            shops_chat=shops_chat,
            alternatives=alternatives,
            said=said_words,
            # While a person has the chat the model's words never go out (the holding line does).
            customer_script=customer_script if state.handed_over_at is None else "",
            name=greeted,
        )
        if (licence_media is not None or licence_page) and answer["handover"]["needed"] and answer["handover"]["reason"] == "media_received":
            answer["handover"] = {"needed": False, "reason": None}  # the photo is the licence we asked for
        if when is None and not still_invalid and answer["appointment"]["action"] == "tentative" and not answer.get("slot_taken"):
            # The customer's own exact day and time, which the model left tentative.
            exact = upgrade_exact_time(
                answer,
                said_words,
                appointment,
                now,
                settings_row.closed_dates,
                taken=taken,
                grounding=grounding,
                handed_over=state.handed_over_at is not None,
                agent_last=_agent_spoke_last(conversation, campaign_templates),
            )
            if exact is not None:
                when, upgraded = exact, True
        if shops_chat and unasked_confirm(
            answer, when, appointment, now, settings_row.closed_dates, taken=taken, said=said_words, words=grounding[0],
            our_last=our_last, ours=ours, handed_over=state.handed_over_at is not None,
        ):
            when = None  # a time nobody named or took (the nudge's "this evening"): the two free slots instead
        if shops_chat and when is None and not still_invalid:
            # The model's own slot offer is no visit of theirs: none recorded, or one in their words alone.
            own = own_offer(answer, appointment=appointment, said=said_words, words=grounding[0], our_last=our_last, yes=yes, now=now)
        turn.model = completions[-1].model[:64]
        turn.calls = len(completions)
        turn.prompt_tokens = sum(c.prompt_tokens for c in completions)
        turn.completion_tokens = sum(c.completion_tokens for c in completions)
        turn.latency_ms = sum(c.latency_ms for c in completions)
    in_hand = {item.pk for item in burst}
    earlier = [
        (
            transcript.who(row, campaign_templates),
            transcript.inbound_text(row) if row.direction == Message.Direction.INBOUND else transcript.outbound_text(row),
        )
        for row in rows
        if row.pk not in in_hand
    ]
    # A shops chat that may still be invited: the two free slots an open "when" becomes.
    may_invite = state.handed_over_at is None and state.not_interested_at is None and (agreed or reoffer or state.invites < 2)
    settle(
        answer,
        earlier,
        [transcript.inbound_text(item, heard.get(item.pk)) for item in burst],
        state.invites,
        agreed=agreed,
        reoffer=reoffer,
        playbook=playbook,
        # Only a broker's turn asks (settle_handover never makes one).
        broker_labelled=answer["handover"]["reason"] == BROKER and conversation.labels.filter(name__iexact=BROKER_LABEL).exists(),
        address_sent=settings_row.office_address if location else "",
        slots=invitation_slots(answer, appointment, said_words, now, settings_row.closed_dates, taken, may_invite=may_invite)
        if shops_chat
        else None,
        now=now,
        facts=facts,
    )
    if licence_media is not None:
        answer["licence"] = "received"
        answer["licence_media"] = licence_media
    elif licence_answer:
        # "declined" closes the request (_apply); "later" leaves it open for the copy to come.
        answer["licence"] = licence_answer
    if shops_chat and not answer.get("shop_step") and not shops_rule_name and not deferred:
        # The shops list, a type's media or the licence request, in place of the model's words (shop_flow),
        # or the two free slots for a time nobody named (unasked_confirm).
        model_step(
            answer,
            facts,
            said_words,
            now,
            appointment=appointment,
            agreed=agreed,
            still_invalid=still_invalid,
            when=when,
            quiet=state.handed_over_at is not None,
            list_sent=_list_sent(conversation),
            licence_asked=state.licence_asked_at is not None or state.not_interested_at is not None or licence_reply,
            media_recent=_media_recent(conversation, now),
            media_today=_media_today(conversation, now),
            shops_facts=settings_row.shops_facts,
        )
    # A step's words replace the model's, and its invitation and location with them.
    shop_flow.step_flags(answer)
    # The licence copy came with other words: the thanks opens the model's reply, when its words go out.
    licence_thanked = (
        licence_media is not None and when is None and not still_invalid and state.handed_over_at is None
        and shop_flow.thank_first(answer, answer["language"])
    )
    # What the model (or the rule) decided, so the turn can be traced afterwards.
    plan = {
        "segment": answer["segment"],
        "action": answer["appointment"]["action"],
        "send": answer["send"],
        "language": answer["language"],
        "invited_to_meeting": answer["invited_to_meeting"],
        "share_office_location": answer["share_office_location"],
    }
    if deferred:
        plan["rule"] = "deferral"
    elif shops_rule_name:
        plan["rule"] = shops_rule_name
    if answer.get("shop_step"):
        plan["shop_step"] = answer["shop_step"]["kind"]
        if answer["shop_step"].get("type"):
            plan["shop_type"] = answer["shop_step"]["type"]
        if answer["shop_step"].get("files") is False:
            plan["shop_files"] = False  # the type's card alone: its files went out today (_media_today)
    if answer.get("licence"):
        plan["licence"] = answer["licence"]
    if licence_thanked:
        plan["licence_thanked"] = True
    if answer.get("script_fix"):
        plan["script_fix"] = answer["script_fix"]
    if answer.get("unasked"):
        plan["unasked"] = answer["unasked"]["start"].isoformat()  # the time the model booked and code did not
    # Lines code writes follow the script the customer types in (T19): "توقف" or a booking
    # after an English chat gets Arabic words, and a booking after "ان شاء الله" in an English
    # chat English ones, whatever language the model named.
    line_language = script.follow(answer["language"], customer_script)
    if line_language != answer["language"]:
        answer["line_language"] = line_language
        plan["line_language"] = line_language
    if upgraded:
        plan["upgraded"] = True
    if agreed:
        plan["agreed"] = True
    if reoffer:
        plan["reoffer"] = True
    if own:
        plan["own_offer"] = own  # the model's tentative for its own slots: dropped, or kept in their words alone
    if answer.get("trimmed"):
        plan["trimmed"] = answer["trimmed"]
    if answer.get("pointed"):
        plan["pointed"] = answer["pointed"]
    if playbook != lane.GENERAL:
        plan["playbook"] = playbook
    if rejected:
        plan["rejected"] = rejected[:300]
        plan["codes"] = codes

    # Still ours? -------------------------------------------------------------------------------
    why_not = still_ours(message, chat.pk, campaign_templates, settings_row.pk)
    if why_not:
        if licence_media is not None:
            # No reply goes, but the licence copy they sent is still theirs: on the lead, the request closed.
            _record_licence(conversation, chat, state, licence_media, now)
        return _skip(why_not, **plan)
    # From here the reply goes out: "if you send first, it drops its reply" no longer holds.
    live.thinking(conversation, False)

    if answer["opt_out"] != "none":
        outcome = _opt_out(
            turn, conversation, chat, state, answer["opt_out"], line_language, answer,
            playbook=playbook, words=_their_words(burst, heard),
        )
        if shops_chat:
            # The shops rule that decided it, and the playbook, stay on the turn.
            outcome.actions = {**plan, **outcome.actions}
        return outcome

    # A time only a colleague can agree, after a colleague spoke: leave it to them.
    if set(codes) & set(HOURS_CODES) and _agent_spoke_last(conversation, campaign_templates):
        alerts.raise_alert(
            kind="handover",
            conversation=conversation,
            priority="high",
            title=f"{_who(conversation)} wants a time outside office hours",
            text=f"{_who(conversation)} answered your message with a time outside office hours "
            f"({answer['appointment'].get('customer_words') or 'see the chat'}). Only a person can book it; "
            "the assistant did not reply.",
            dedupe_key=f"out_of_hours:{conversation.pk}:{message.pk}",
            crm_url=_crm_url(chat),
        )
        return _skip("an out-of-hours time after a colleague's message", **plan)

    # What happens, and the words ---------------------------------------------------------
    language = line_language
    action = effective_action(answer["appointment"]["action"], appointment)
    if action == "reschedule" and when is not None and confirmed and appointment.starts_at == when:
        action = "reconfirm"  # the time already booked: said again, nothing moves
    elif action == "reschedule" and when is None and not still_invalid:
        action = "reschedule_requested"
    elif action == "running_late" and when is not None and confirmed and appointment.starts_at == when:
        action = "on_time"
    if action in ("confirm", "reschedule") and when is not None:
        # One client per slot, looked at again under the office lock (held until the
        # booking is stored): another chat may have booked it while the model thought.
        if hold is not None:
            hold.enter_context(office_lock())
        gone = _slot_gone(conversation, when, appointment, now, settings_row.closed_dates, said_words)
        if gone is not None:
            codes.append("taken")
            alternatives[:] = gone
            plan["codes"] = codes
            plan["rejected"] = "booked by another chat while the assistant was answering"
            answer["appointment"] = dict(NO_TIME)
            when, still_invalid, action = None, True, "none"
    plan["effective"] = action
    merged = _merge_facts(facts, answer["facts"])
    name = _customer_name(conversation, merged)
    rows_context = _context_words(rows, campaign_msg, burst, heard, facts, campaign_templates)
    if shops_chat:
        # A shops reply may quote SHOP FACTS' own figures, and no other new one.
        rows_context = f"{rows_context} {shops.known_amounts(settings_row)}"
    maps = settings_row.office_maps_url
    text = ""
    holding = False
    booking = None
    filtered = []
    gloss = False  # the model's own words go out whole, so its English translation (reply_en) holds
    appended = ""  # the Maps link or the address code added to the reply
    media_type = ""  # a shop type whose video, photos and card go out (tasks.send_shop_media)
    media_files = True  # False: its card alone (its files went out today)
    list_step = False  # the shop types list goes out instead of a text
    step_marker = ""  # a shops step our message is (payload "shop_step"), read back by a later turn
    model_words = False  # the model's own words go out (not a line code writes)

    def booking_text(rescheduled: bool) -> str:
        if shops_chat:
            # The build pack's confirmation: date, time, shop type, place, who they meet, what to bring.
            return shops.confirmation(
                language,
                when,
                shop_type=merged.get("shop_type"),
                facts=settings_row.shops_facts,
                office_address=settings_row.office_address,
                maps_url=maps,
                agent=shops.agent_of(settings_row),
            )
        if rescheduled:
            return filters.rescheduled(language, name, when, settings_row.office_address, maps)
        return filters.confirmation(language, name, when, settings_row.office_address, maps, _is_commercial(answer["segment"], merged))

    # Code's two free slots for a taken one, never while a person has the chat: that keeps
    # what it had before them (the booking texts, else the holding line; refused twice, ask_time).
    offer_free = state.handed_over_at is None
    if still_invalid:
        if "no_appointment_otw" in codes:
            text = filters.on_my_way(language)
            _walk_in_alert(conversation, chat, name)
            plan["fallback"] = "ask_time"
        elif "taken" in codes and alternatives and offer_free:
            # Another client has that slot: the two nearest free ones instead.
            text = shops.slot_taken(language, alternatives, now)
            plan["fallback"] = "slot_taken"
        elif shops_chat and offer_free and "vague" in codes and (
            pair := shops.yes_slots(
                said_words, our_last, now, settings_row.closed_dates, [*taken, *([appointment.starts_at] if confirmed and appointment.starts_at else [])]
            )
        ):
            # A shops chat's time nobody named, refused twice (the grounding's "vague"): the two free
            # slots for what they said, as unasked_confirm offers them, never "which day and time?";
            # with the location when they asked for it.
            text = shop_flow.slots_text(language, pair, now, f"{ours}\n{our_last}")
            appended = asked_location(text, asked, settings_row.office_address, maps)
            plan["fallback"] = "slots"
        else:
            text = rules.line("ask_time", language)
            plan["fallback"] = "ask_time"
    elif answer.get("slot_taken") and alternatives and offer_free:
        # Kept tentative at another client's time, or a correction that offered other
        # times (ask_model): the two nearest free ones, from code; the tentative keeps
        # their words, not that time (_apply).
        text = shops.slot_taken(language, alternatives, now)
        plan["fallback"] = "slot_taken"
        plan["codes"] = codes
    elif action in ("confirm", "reschedule") and when is not None:
        text = booking_text(rescheduled=action == "reschedule")
        booking = {
            "event": "confirmed" if action == "confirm" else "rescheduled",
            "starts_at": when.isoformat(),
            "appointment": appointment.pk if appointment is not None else None,
        }
    elif action == "reconfirm":
        text = booking_text(rescheduled=False)
    elif action == "running_late" and when is not None:
        text = filters.arrival(language, when)
    elif action == "on_time" or (action == "on_my_way" and confirmed):
        text = filters.on_my_way(language)
    elif action == "reschedule_requested" and shops_chat and offer_free and len(hours.named_times(answer["reply"] or "")) < 2:
        # "Need to reschedule" with no new time (T44): the two nearest free slots, never an
        # open question, and never the slot they are moving from. A reply that names two
        # times already (the day they asked for, settle's slots) goes as it is.
        own = [appointment.starts_at] if confirmed and appointment.starts_at else []
        text = shop_flow.reschedule_text(language, hours.offer_pair(now, settings_row.closed_dates, [*taken, *own]), now)
        plan["fallback"] = "reschedule_slots"
    elif state.handed_over_at is not None:
        # Quiet after a request for a person: at most one holding line every two hours.
        if not state.holding_line_at or now - state.holding_line_at > HOLDING_EVERY:
            text = rules.line("holding", language)
            holding = True
    elif answer.get("converted"):
        # A fixed line, never the model's words: a confirmation the office could
        # not take (_shape, written as a confirmation), a deferral, a shops broker.
        text = rules.line(answer["converted"], language)
        holding = answer["converted"] == "holding"
    elif answer.get("shop_step"):
        # The shops steps (shop_flow): the list of types, a type's media (sent by its
        # task, outside this turn), the two slots for [Book viewing], the licence.
        step = answer["shop_step"]
        if step["kind"] == shop_flow.MEDIA:
            media_type = step["type"]
            media_files = step.get("files", True) is not False
        elif step["kind"] == shop_flow.LIST:
            list_step = True
        elif step["kind"] == shop_flow.SLOTS:
            # [Book viewing]'s two free slots, or the ones fitted to a yes that named no time (unasked_confirm),
            # never in the words our side just used for them, and with the location when they asked for it.
            own = [appointment.starts_at] if confirmed and appointment.starts_at else []
            pair = step.get("slots") or hours.offer_pair(now, settings_row.closed_dates, [*taken, *own])
            text = shop_flow.slots_text(language, pair, now, f"{ours}\n{our_last}")
            appended = asked_location(text, asked, settings_row.office_address, maps)
        elif step["kind"] == shop_flow.LICENCE_ASK:
            text = rules.line("licence_copy", language)
            step_marker = shop_flow.LICENCE_ASK
        elif step["kind"] == shop_flow.LICENCE_THANKS:
            # The copy came: thanks, and the two free slots while a visit is still to book.
            pair = hours.offer_pair(now, settings_row.closed_dates, taken) if appointment is None and may_invite else []
            text = shop_flow.thanks_text(language, pair, now)
            if pair:
                answer["invited_to_meeting"] = True
                plan["invited_to_meeting"] = True
    else:
        if answer["send"]:
            text, filtered = filters.clean_reply(answer["reply"], rows_context)
            model_words = bool(text)
            gloss = bool(text) and not filtered and not answer.get("trimmed")
            if filtered:
                plan["filtered"] = filtered
            if not text and "amount" in filtered:
                text = rules.line("deflect", language)
                _price_alert(conversation, chat, name)
        if not text:
            fallback = {"reschedule_requested": "ask_new_time", "running_late": "ask_eta"}.get(action)
            if fallback:
                text = rules.line(fallback, language)
            elif answer["handover"]["needed"]:
                # Handed to a person and nothing usable to say: they still hear it.
                text = rules.line("holding", language)
                holding = True
        if text and answer["share_office_location"] and not location:
            # Once per chat: not when one of our messages gave it already
            # (location_sent), nor when the reply itself carries it.
            if maps and maps not in text:
                appended = maps
            elif not maps and not filters.carries_location(text, settings_row.office_address):
                appended = settings_row.office_address
    if appended:
        text = f"{text}\n{appended}"
        plan["location_appended"] = True

    if media_type:
        # Nothing goes out in this turn: the video, the photos and the detail card follow from
        # their own task, outside the turn's time (shop_media.send_type), which never fails it.
        answer["invited_to_meeting"] = answer["share_office_location"] = False
        done = _apply(
            conversation, chat, state, answer, action, when, appointment, now, sent=True, holding=False, playbook=playbook,
            taken=taken,
        )
        done.update(plan)
        LeadAiTurn.objects.filter(pk=turn.pk).update(actions={**(turn.actions or {}), **done})
        from ..tasks import send_shop_media

        transaction.on_commit(
            lambda pk=conversation.pk, kind=media_type, turn_pk=turn.pk, lang=language, files=media_files: send_shop_media.delay(
                pk, kind, turn_pk, lang, files
            )
        )
        what = "media" if media_files else "card"
        return Outcome(LeadAiTurn.Status.REPLIED, f"shop {what} queued ({media_type})", actions=done)

    if not text and not list_step:
        done = _apply(
            conversation, chat, state, answer, action, when, appointment, now, sent=False, holding=False, playbook=playbook,
            taken=taken,
        )
        done.update(plan)
        return _skip("no reply needed", **done)

    try:
        extra = {}
        reply_en = answer["reply_en"].strip()
        if gloss and answer["language"] != "en" and reply_en and not _same_words(reply_en, answer["reply"]):
            # For the agents, what the customer reads in English: only for a reply
            # in another language, sent whole, with the line code added to it.
            extra["reply_en"] = (f"{reply_en}\n{appended}" if appended else reply_en)[:600]
        if booking:
            extra["booking"] = booking
        if step_marker:
            extra["shop_step"] = step_marker
        if list_step:
            from .. import shop_media

            sent = shop_media.send_list(conversation, language, settings_row.shops_facts, turn_id=turn.pk)
        else:
            sent = _send(conversation, text, turn, extra or None)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - nothing was booked; the agent is told
        logger.warning("Lead AI send failed on conversation %s: %s", conversation.pk, exc)
        alerts.raise_alert(
            kind="send_failed",
            conversation=conversation,
            priority="high" if booking else "normal",
            title="Lead AI reply was not delivered",
            text=f"The assistant's reply to {name or _who(conversation)} could not be sent ({type(exc).__name__}). "
            "Nothing was booked. Please reply by hand.",
            dedupe_key=f"send_failed:{turn.pk}",
            crm_url=_crm_url(chat),
        )
        return Outcome(LeadAiTurn.Status.FAILED, f"send failed: {type(exc).__name__}", actions=plan)

    if (
        model_words and answer.get("line_language") and customer_script != script.LATIN
        and not script.has_script(text, customer_script, name)
    ):
        # The model's own words went out in another script than the customer's (asked once more and
        # still not, or no time): the chat goes on in the language they read, so a reminder or a
        # tap's answer later is not written in a script nobody wrote to them in (board review 2b).
        # A customer who types English letters reads them, whatever went out once: their lines stay so.
        answer.pop("line_language", None)
    done = _apply(
        conversation, chat, state, answer, action, when, appointment, now, sent=True, holding=holding, playbook=playbook,
        taken=taken,
    )
    if hold is not None:
        hold.close()  # the booking is stored: the next one may look at the slots
    done.update(plan)
    # The booking is stored: the turn row says so before the slower pin goes out.
    turn.reply_message_id = sent.pk
    LeadAiTurn.objects.filter(pk=turn.pk).update(reply_message=sent, actions={**(turn.actions or {}), **done})

    if done.get("appointment", {}).get("event") in ("confirmed", "rescheduled") and settings_row.has_pin:
        try:
            from apps.inbox import services as inbox_services

            inbox_services.send_location(
                conversation,
                None,
                float(settings_row.office_latitude),
                float(settings_row.office_longitude),
                name="Our office",
                address=settings_row.office_address,
                payload={"source": SOURCE, "turn": turn.pk},
            )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - the confirmation already went out
            logger.warning("Lead AI could not send the office pin on conversation %s: %s", conversation.pk, exc)
    return Outcome(LeadAiTurn.Status.REPLIED, "", reply_message_id=sent.pk, actions=done)


def _auto_reply(conversation, newest) -> bool:
    text = (newest.body or "").strip()
    gap = _seconds_after_ours(conversation, newest)
    if rules.looks_like_auto_reply(text, gap):
        return True
    # The same text again and again, each time right after ours: a bot in a loop with us.
    if len(text) <= 15 or rules.asks_question(text) or gap is None or gap > 30:
        return False
    recent = list(
        Message.objects.filter(conversation=conversation, direction=Message.Direction.INBOUND, kind="text")
        .order_by("-pk")
        .values_list("body", flat=True)[:3]
    )
    return len(recent) == 3 and len({(body or "").strip().lower() for body in recent}) == 1


def _walk_in_alert(conversation, chat, name: str) -> None:
    who = name or _who(conversation)
    alerts.raise_alert(
        kind="on_my_way",
        conversation=conversation,
        priority="high",
        title=f"{who} says they are on the way",
        text=f"{who} (WhatsApp +{conversation.contact.wa_id}) says they are on the way to the office, "
        "but no meeting is booked. Please be ready, or check the chat.",
        dedupe_key=f"walk_in:{conversation.pk}:{timezone.now():%Y%m%d%H}",
        crm_url=_crm_url(chat),
    )


def _price_alert(conversation, chat, name: str) -> None:
    who = name or _who(conversation)
    alerts.raise_alert(
        kind="price_question",
        conversation=conversation,
        title=f"{who} asked about prices",
        text=f"{who} (WhatsApp +{conversation.contact.wa_id}) asked about a price or detail the assistant may not "
        "give. It said our specialist will confirm; please answer in the chat.",
        dedupe_key=f"price_question:{conversation.pk}:{timezone.now():%Y%m%d}",
        crm_url=_crm_url(chat),
    )


# Storing what the turn decided -------------------------------------------------------------

BOOKING_DETAILS = (
    "customer_name", "intent", "property_type", "community", "building_unit", "bedrooms", "size_sqft",
    "budget_aed", "budget_basis", "move_in", "business_activity", "trade_licence",
)
# A shops chat's booking also follows its own facts, and its questions for the viewing.
SHOPS_BOOKING_DETAILS = (*BOOKING_DETAILS, "licence_kind", "shop_type", "opening_when", "notes", "licence_copy")


def _details(facts: dict) -> dict:
    return {k: v for k, v in (facts or {}).items() if v not in (None, "")}


def _apply(
    conversation, chat, state, answer, action, when, appointment, now, *, sent: bool, holding: bool, playbook: str = lane.GENERAL,
    taken=(),
) -> dict:
    """Store what this turn decided, after the reply went out (or when none was needed).

    ``action`` is the effective action, including the engine's own
    "reconfirm", "reschedule_requested" and "on_time". A shops chat's
    check-back ("Should I check back with you in a month?") is opened, answered
    (a follow-up a month from now) or closed by any other reply we send, and its
    lead's fields go to Bitrix (crm_fields). The reply of the turn that learned
    they already rented a shop is marked ("rented_asked"): a plain no to it, and
    only to it, closes the lead (_shops_rule_for). ``taken``: the other chats'
    office starts; a tentative visit never keeps one of those as its time.
    """
    from ..tasks import sync_appointment_crm

    done: dict = {}
    shops_chat = playbook == lane.IC_SHOPS
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        facts_before = dict(fresh.facts or {})
        fresh.facts = _merge_facts(fresh.facts, answer["facts"])
        # The language the customer is answered in, following the script they type (T19).
        fresh.language = (answer.get("line_language") or answer["language"])[:16]
        fields = ["facts", "language", "updated_at"]
        if sent and answer["invited_to_meeting"]:
            fresh.invites = min(fresh.invites + 1, 99)
            fields.append("invites")
        step = answer.get("shop_step") or {}
        if sent and step.get("kind") == shop_flow.LICENCE_ASK and fresh.licence_asked_at is None:
            fresh.licence_asked_at = now  # asked once, never again
            fields.append("licence_asked_at")
            done["licence_asked"] = True
        if answer.get("licence") in ("received", "declined") and fresh.licence_closed_at is None:
            fresh.licence_closed_at = now
            fresh.facts = {**fresh.facts, "licence_copy": answer["licence"]}
            fields.append("licence_closed_at")
        if answer.get("licence_media") is not None:
            # Whatever the reply, the copy goes to the lead (tasks.write_licence_file).
            crm_fields.queue_licence(conversation, chat, answer["licence_media"])
        follow = answer.get("followup")
        if sent and follow == "ask":
            fresh.followup_asked_at = now
            fields.append("followup_asked_at")
        elif sent and follow == "schedule":
            fresh.followup_asked_at = None
            fresh.followup_due_at = now + shops.FOLLOW_UP_AFTER
            fields += ["followup_asked_at", "followup_due_at"]
            done["followup_due_at"] = fresh.followup_due_at.isoformat()
        elif sent and fresh.followup_asked_at is not None:
            # Anything else we said is now the last word: the question is no longer open.
            fresh.followup_asked_at = None
            fields.append("followup_asked_at")
        if sent and follow != "schedule" and fresh.followup_due_at is not None:
            # They came back by themselves after "check back with me in a month": the chat is
            # under way again, so no check-back template lands in it later (followups.check_back_due),
            # and a silence from here on may be nudged like any other.
            fresh.followup_due_at = None
            fields.append("followup_due_at")
            done["followup_cleared"] = True
        if holding:
            fresh.holding_line_at = now
            fields.append("holding_line_at")
        handover = answer["handover"]
        if handover["needed"] and fresh.handed_over_at is None:
            fresh.handed_over_at = now
            fresh.handover_reason = handover["reason"] or "unclear"
            fields += ["handed_over_at", "handover_reason"]
            done["handover"] = fresh.handover_reason
        if answer.get("broker") and fresh.paused_at is None:
            # A broker: labelled for the team, and silent until an agent presses
            # Resume. A pause, not only a handover, so neither the 12-hour clear
            # nor a colleague's message lets the assistant back in. Once (settle):
            # after Resume, the label stays and a broker is an ordinary handover.
            fresh.paused_at = now
            fields.append("paused_at")
            conversation.labels.add(broker_label())
            done["handover"] = BROKER
            done["broker"] = True
        if sent and action in ("confirm", "reschedule") and when is not None and fresh.not_interested_at is not None:
            fresh.not_interested_at = None  # they declined once, and have now booked
            fields.append("not_interested_at")
        fresh.save(update_fields=sorted(set(fields)))
        facts = fresh.facts
        if shops_chat and sent and facts.get("already_rented") is True and facts_before.get("already_rented") is not True:
            # This reply congratulated them and asked about a second shop (SHOPS_SYSTEM).
            done["rented_asked"] = True

        name = _customer_name(conversation, facts)
        proposal = answer["appointment"]
        crm_event = ""
        current = None
        if appointment is not None:
            current = LeadAiAppointment.objects.select_for_update().filter(pk=appointment.pk).first()
            if current is not None and current.status not in LeadAiAppointment.OPEN:
                current = None
        confirmed = current is not None and current.status == LeadAiAppointment.Status.CONFIRMED

        if sent and action in ("confirm", "reschedule") and when is not None:
            if current is None:
                current = LeadAiAppointment(conversation=conversation, crm_entity=chat.crm_entity, crm_id=chat.crm_id)
            previous = current.starts_at if current.status == LeadAiAppointment.Status.CONFIRMED else None
            current.status = LeadAiAppointment.Status.CONFIRMED
            current.place = LeadAiAppointment.Place.OFFICE
            current.starts_at = when
            current.note = ""
            current.customer_words = (proposal["customer_words"] or "")[:255]
            current.customer_name = name[:200]
            current.mobile = conversation.contact.wa_id[:32]
            current.details = _details(facts)
            current.customer_state = ""
            current.eta_at = None
            current.reminder_due_at = hours.reminder_due(when, now)
            current.reminder_claimed_at = None
            current.reminder_sent_at = None
            current.reminder_message = None
            current.reminder_error = ""
            current.agent_reminded_at = None
            crm_event = "rescheduled" if previous else "confirmed"
            current.log(crm_event, starts_at=when.isoformat(), previous=previous.isoformat() if previous else None)
            current.save()
            done["appointment"] = {"id": current.pk, "event": crm_event, "starts_at": when.isoformat()}
        elif action == "tentative" and (current is None or current.status == LeadAiAppointment.Status.TENTATIVE):
            place = proposal["place"] or LeadAiAppointment.Place.OFFICE
            note = (proposal["customer_words"] or "may come")[:255]
            start = None
            day, at = hours.parse_date(proposal["date"]), hours.parse_time(proposal["time"])
            if day and at:
                start = dt.datetime.combine(day, at, tzinfo=hours.DUBAI)
                if place == LeadAiAppointment.Place.OFFICE:
                    # An office visit, even a tentative one, is only ever an open
                    # day within hours ("Sunday 9 PM" is not kept as a time).
                    try:
                        hours.check_slot(proposal["date"], proposal["time"], now=now)
                    except hours.SlotError as exc:
                        if exc.code != "too_far":
                            start = None
                    if start is not None and hours.is_taken(start, taken):
                        # Another client's slot (just refused as taken): their words are kept,
                        # not the time, or this tentative would block that slot for everyone.
                        start = None
            changed = current is None or (current.starts_at, current.place, current.note) != (start, place, note)
            if changed:
                is_new = current is None
                if current is None:
                    current = LeadAiAppointment(
                        conversation=conversation,
                        status=LeadAiAppointment.Status.TENTATIVE,
                        crm_entity=chat.crm_entity,
                        crm_id=chat.crm_id,
                    )
                current.place = place
                current.note = note
                current.customer_words = note
                current.starts_at = start
                current.customer_name = name[:200]
                current.mobile = conversation.contact.wa_id[:32]
                current.details = _details(facts)
                current.log("tentative", note=note, place=place, start=start.isoformat() if start else None)
                current.save()
                crm_event = "tentative"
                done["appointment"] = {"id": current.pk, "event": "tentative", "place": place, "new": is_new}
        elif action == "reschedule_requested" and confirmed:
            if current.customer_state != LeadAiAppointment.CustomerState.RESCHEDULE:
                current.customer_state = LeadAiAppointment.CustomerState.RESCHEDULE
                if current.reminder_sent_at is None and current.reminder_claimed_at is None:
                    current.reminder_due_at = None  # held until a new time is agreed
                current.log("reschedule_requested")
                current.save(update_fields=["customer_state", "reminder_due_at", "history", "updated_at"])
                crm_event = "reschedule_requested"
                done["appointment"] = {"id": current.pk, "event": "reschedule_requested"}
        elif action == "running_late" and confirmed:
            if when is not None and sent:
                current.eta_at = when
                current.starts_at = when
                current.customer_state = LeadAiAppointment.CustomerState.RUNNING_LATE
                fields_late = ["eta_at", "starts_at", "customer_state", "history", "updated_at"]
                if current.reminder_sent_at is None and current.reminder_claimed_at is None:
                    # Not reminded yet: the 30-minute reminder follows the new time (rule 52).
                    current.reminder_due_at = hours.reminder_due(when, now)
                    current.reminder_error = ""
                    fields_late += ["reminder_due_at", "reminder_error"]
                current.log("running_late", arrival=when.isoformat())
                current.save(update_fields=fields_late)
                crm_event = "running_late"
                done["appointment"] = {"id": current.pk, "event": "running_late", "arrival": when.isoformat()}
            elif when is None and current.customer_state != LeadAiAppointment.CustomerState.RUNNING_LATE:
                current.customer_state = LeadAiAppointment.CustomerState.RUNNING_LATE
                current.log("running_late", arrival=None)
                current.save(update_fields=["customer_state", "history", "updated_at"])
                crm_event = "running_late"
                done["appointment"] = {"id": current.pk, "event": "running_late", "arrival": None}
        elif sent and action == "on_my_way" and confirmed:
            if current.customer_state != LeadAiAppointment.CustomerState.ON_MY_WAY:
                current.customer_state = LeadAiAppointment.CustomerState.ON_MY_WAY
                current.log("on_my_way")
                current.save(update_fields=["customer_state", "history", "updated_at"])
                crm_event = "on_my_way"
            done["appointment"] = {"id": current.pk, "event": "on_my_way"}
        elif action == "cancel" and current is not None:
            # Applied even when no line went out (a handover's quiet period):
            # the customer said they will not come.
            current.status = LeadAiAppointment.Status.CANCELLED
            current.reminder_due_at = None
            current.log("cancelled", by="customer")
            current.save(update_fields=["status", "reminder_due_at", "history", "updated_at"])
            crm_event = "cancelled"
            done["appointment"] = {"id": current.pk, "event": "cancelled"}

        if not crm_event and current is not None and current.pk and current.status in LeadAiAppointment.OPEN:
            # Facts given after the booking reach the appointment (the CRM timeline
            # already has them from the WhatsApp mirror).
            keys = SHOPS_BOOKING_DETAILS if shops_chat else BOOKING_DETAILS
            if {k: v for k, v in _details(facts).items() if k in keys} != {
                k: v for k, v in (current.details or {}).items() if k in keys
            }:
                current.details = _details(facts)
                current.save(update_fields=["details", "updated_at"])

        hot = bool(
            crm_event == "confirmed"
            and current is not None
            and current.starts_at
            and hours.is_today(current.starts_at, now)
            and (answer["hot_lead"] or _urgent(facts))
        )
        if crm_event and current is not None:
            revision = len(current.history or [])
            done["crm_event"] = crm_event
            done["hot_lead"] = hot
            done["revision"] = revision
            transaction.on_commit(
                lambda pk=current.pk, event=crm_event, is_hot=hot, rev=revision: sync_appointment_crm.delay(pk, event, is_hot, rev)
            )
            if not (crm_event == "tentative" and done.get("appointment", {}).get("new") and done.get("handover")):
                appointment_alert(conversation, chat, current, crm_event, hot, name, revision)
        if done.get("handover"):
            moment = fresh.paused_at if done.get("broker") else fresh.handed_over_at
            _handover_alert(conversation, chat, current, done["handover"], name, facts, moment, broker=bool(done.get("broker")))
        if crm_event or done.get("handover") or done.get("followup_due_at") or done.get("followup_cleared"):
            transaction.on_commit(lambda pk=conversation.pk: live.appointment_changed(pk))
        if shops_chat:
            # The lead's shops fields, through the Lead fields tool (never a REST update).
            writes = crm_fields.turn_writes(
                facts_before,
                facts,
                answered=sent,
                first=not crm_fields.has_status(conversation, chat),
                handover=bool(done.get("handover")) and not done.get("broker"),
                broker=bool(done.get("broker")),
                booked=crm_event in ("confirmed", "rescheduled"),
            )
            if crm_fields.queue(conversation, chat, writes):
                done["crm_fields"] = [field for field, _, _ in writes]
    return done


def _detail_lines(facts: dict) -> list[str]:
    labels = (
        ("intent", "Looking to"),
        ("property_type", "Property"),
        ("community", "Area"),
        ("building_unit", "Unit"),
        ("bedrooms", "Bedrooms"),
        ("size_sqft", "Size (sq ft)"),
        ("budget_aed", "Budget (AED)"),
        ("asking_price_aed", "Asking (AED)"),
        ("move_in", "Move-in"),
        ("available_from", "Available from"),
        ("business_activity", "Business activity"),
        ("trade_licence", "Trade licence"),
        # A shops chat's own (a general chat never has these).
        ("licence_kind", "Licence"),
        ("shop_type", "Shop type wanted"),
        ("opening_when", "Opening"),
        ("licence_copy", "Licence copy"),
    )
    out = []
    for key, label in labels:
        value = facts.get(key)
        if value not in (None, ""):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if key == "shop_type":
                value = shops.type_label(value)
            elif key == "licence_kind":
                value = shops.licence_label(value)
            out.append(f"{label}: {value}")
    if facts.get("already_rented") is True:
        out.append("Already rented a shop")
    notes = facts.get("notes")
    if isinstance(notes, list) and notes:
        # A shops chat's questions for the viewing (a general chat's notes are text, not shown here).
        out.append("Questions for the viewing: " + "; ".join(str(note) for note in notes))
    return out


def appointment_alert(conversation, chat, appointment, event: str, hot: bool, name: str, revision: int | None = None) -> None:
    """The agents' alert for an appointment event.

    The dedupe key is the appointment and its revision (the length of its
    history after the event), so the same event raised again (from the CRM
    sync, once the CRM responsible is known) reaches only who did not have it.
    """
    who = name or "A Lead AI customer"
    phone = f"WhatsApp +{conversation.contact.wa_id}"
    crm_url = alerts.crm_path(
        appointment.crm_entity or (chat.crm_entity if chat is not None else ""),
        appointment.crm_id or (chat.crm_id if chat is not None else None),
    )
    if revision is not None:
        stamp = f"r{revision}"
    else:
        stamp = f"{appointment.starts_at:%Y%m%d%H%M}" if appointment.starts_at else "none"
    details = _detail_lines(appointment.details or {})
    when = hours.describe(appointment.starts_at) if appointment.starts_at else ""
    at = hours.time_label(appointment.starts_at) if appointment.starts_at else ""
    if event == "confirmed" and hot:
        alerts.raise_alert(
            kind="hot_lead",
            conversation=conversation,
            appointment=appointment,
            priority="high",
            title=f"HOT LEAD: {who} is visiting today at {at}",
            text="\n".join([f"{who} ({phone})", *details, f"Meeting: Today {at}"]),
            dedupe_key=f"hot_lead:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "confirmed":
        soon = appointment.starts_at is not None and hours.is_soon(appointment.starts_at)
        alerts.raise_alert(
            kind="booked",
            conversation=conversation,
            appointment=appointment,
            priority="high" if soon else "normal",
            title=(f"Visit soon: {who} at {at}" if soon else f"Meeting booked: {who}, {when}"),
            text="\n".join([f"{who} ({phone})", *details, f"Meeting: {when}", "Booked by the Lead AI assistant."]),
            dedupe_key=f"booked:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "rescheduled":
        alerts.raise_alert(
            kind="rescheduled",
            conversation=conversation,
            appointment=appointment,
            title=f"{who} moved the meeting to {when}",
            text="\n".join([f"{who} ({phone})", *details, f"New time: {when}"]),
            dedupe_key=f"rescheduled:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "tentative":
        place = appointment.get_place_display().lower() if appointment.place else "our office"
        alerts.raise_alert(
            kind="tentative",
            conversation=conversation,
            appointment=appointment,
            title=f"{who}: tentative {'viewing' if appointment.place == 'customer_property' else 'visit'}"
            + (f", {when}" if when else ""),
            text="\n".join(
                [f"{who} ({phone})", *details, f"Tentative at {place}: {when or appointment.note or 'no time yet'}",
                 "Not confirmed: please confirm it with the customer."]
            ),
            dedupe_key=f"tentative:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "running_late":
        alerts.raise_alert(
            kind="running_late",
            conversation=conversation,
            appointment=appointment,
            priority="high",
            title=f"{who} is running late",
            text=(
                f"{who} will now arrive at {at} ({phone})."
                if appointment.eta_at
                else f"{who} is running late for the {at} meeting and has not said when they will arrive ({phone})."
            ),
            dedupe_key=f"running_late:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "on_my_way":
        alerts.raise_alert(
            kind="on_my_way",
            conversation=conversation,
            appointment=appointment,
            priority="high",
            title=f"{who} is on the way",
            text=f"{who} is on the way for the {at} meeting ({phone}).",
            dedupe_key=f"on_my_way:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "reschedule_requested":
        alerts.raise_alert(
            kind="reschedule_requested",
            conversation=conversation,
            appointment=appointment,
            title=f"{who} wants to reschedule",
            text=f"{who} wants to move the {when} meeting and has not chosen a new time yet ({phone}). "
            "Its reminder is held until a new time is agreed.",
            dedupe_key=f"reschedule_requested:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )
    elif event == "cancelled":
        alerts.raise_alert(
            kind="cancelled",
            conversation=conversation,
            appointment=appointment,
            title=f"{who} cancelled the meeting",
            text=f"{who} cancelled the meeting" + (f" of {when}" if when else "") + f" ({phone}).",
            dedupe_key=f"cancelled:{appointment.pk}:{stamp}",
            crm_url=crm_url,
        )


_appointment_alert = appointment_alert  # the name earlier code and tests use


HANDOVER_TEXT = {
    "customer_asked_human": "asked to talk to a person",
    "call_requested": "asked for a call",
    "price_or_details_insisted": "insists on prices or details",
    "complaint_or_upset": "is upset or complaining",
    "legal_visa_licence_contract": "asked about legal, visa, licence or contract matters",
    "broker_or_for_client": "is a broker or asks for a client",
    "tenancy_issue": "raised a tenancy problem",
    "renewal_terms": "asked about renewal rent or terms",
    "media_received": "sent a photo, document, contact or location",
    "abroad_cannot_visit": "is abroad or cannot visit",
    "owner_viewing_slot": "offered a viewing slot at their property",
    "unclear": "needs a person to take over",
    # Set by a person in Bitrix (Bot Status "Handed to agent"; bitrix_status.py).
    "Bitrix: handed to agent": "was handed to an agent in Bitrix",
}


def broker_label():
    """The inbox label of a broker's chat: one named "Broker" in any case, made the way the inbox makes labels."""
    from apps.inbox.models import Label

    label = Label.objects.filter(name__iexact=BROKER_LABEL).order_by("pk").first()
    if label is None:
        label, _ = Label.objects.get_or_create(name=BROKER_LABEL, defaults={"colour": BROKER_COLOUR})
    return label


def _handover_alert(conversation, chat, appointment, reason: str, name: str, facts: dict, handed_over_at, *, broker: bool = False) -> None:
    """``broker``: the chat was labelled and paused for a broker just now (_apply)."""
    who = name or "A Lead AI customer"
    lines = [f"{who} (WhatsApp +{conversation.contact.wa_id}) {HANDOVER_TEXT.get(reason, 'needs a person')}."]
    if reason == "owner_viewing_slot" and appointment is not None:
        if appointment.starts_at:
            lines.append(f"Offered: {hours.describe(appointment.starts_at)}")
        if appointment.customer_words:
            lines.append(f"Their words: {appointment.customer_words}")
    lines += _detail_lines(facts)
    if broker:
        campaign = chat.campaign if chat is not None and chat.campaign_id else None
        if campaign is not None:
            lines.append(f"Campaign: {campaign.name}")
        lines.append(
            f'The chat is labelled "{BROKER_LABEL}", and the assistant stays silent in it until someone presses Resume AI.'
        )
    else:
        lines.append("The assistant is now quiet in this chat until someone from the team writes.")
    # One alert per handover (the moment it began), not one per reason and day:
    # a second request for a person later the same day is alerted again.
    moment = f"{handed_over_at:%Y%m%d%H%M%S}" if handed_over_at else f"{timezone.now():%Y%m%d%H%M%S}"
    alerts.raise_alert(
        kind="handover",
        conversation=conversation,
        appointment=appointment,
        priority="high" if reason in HIGH_HANDOVER else "normal",
        title=f"{who}: {HANDOVER_TEXT.get(reason, 'needs a person')}",
        text="\n".join(lines),
        dedupe_key=f"handover:{conversation.pk}:{moment}",
        crm_url=_crm_url(chat),
    )
