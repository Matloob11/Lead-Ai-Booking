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

Who a shops customer is (launch 2026-10-15; needs.py): someone who wants no shop to rent (a flat,
studio, room, BHK or villa, to buy or to sell, or "I never asked about a shop") is never lost, by
Matloob's rule of that day: the model's tag or "unclear" for it is no handover (untag_need), its
"not interested" with that want is no decline (not_lost_for, who_they_are), they never get a shop
step, and the first time code answers them with the owner's line: thanks (and sorry), many options
for exactly that across Dubai, "Visit our office and we'll give you the best option." with two free
slots, our Maps link and pin; the team hears what they want (_wanted_alert, the timeline note), and
their visit is booked and confirmed in words about no shop. Someone who rented a shop already ("we
got one") gets the second-shop question from code; and no shops reply says the shops are only for
rent or not for sale.

Where a person must act (launch 2026-10-15; caps.py, people.py): a shops chat may send 12 replies an hour
and 30 a day, and a message the cap held back is answered by its own turn once the cap frees (run_turn's
``requeued``); a call request is never promised a time (code's words pass it on, with the time they gave,
to the handover alert and the lead's timeline); while a person has the chat, a goodbye gets nothing, a
chase an apology and an urgent alert, a call's time is passed on (people.quiet_reply, _quiet_alert); a
shops customer's must-answer questions go to a person before any visit; no reply sends the customer to
a colleague; the CRM responsible is looked up before an opt-out, and alerts raised before it was known
reach them (alerts.reach_responsible).

Facts, slots and booking (launch 2026-10-15; claims.py, offers.py): a shops reply never states a fact SHOP
FACTS lacks (a shop's building, side or unit, a food business allowed, a sale, the deposit, another cost;
our office's address is never a shop's), and the commission is Matloob's line (Q24); the size and price
table goes once. Every slot is an hour ahead and an hour from the other, never past, in code's lines and
the model's own words (fix_times); a same-day window of theirs ("12-12:30") is booked at its start
(book_window); "cheaper" or "too expensive" gets our lowest type, honestly, and a budget below it a
colleague (claims.price_turn); a tap sent with typed words keeps its step (tap_with_words); the business,
then the licence, are asked before a second invitation (discovery_first); code's slots count as an
invitation, one cut as a second question does not, and our location goes labelled as our office's.

Batch 2d's review (2026-10-16): our office's pin after a reply is no last word of ours (_last_outbound reads past
it: an "OK" to the owner's two slots is answered); must-answer questions go to a person while the chat goes on
(people.MUST_ANSWER_PAUSES, _questions_alert); a call in their own words beats the owner's line, a "no shop" never
replaces a want they named, a buyer hears no word of renting and no third invitation, an apology alone left by the
cuts becomes the owner's line (bare_need_reply), a request for a shop forgets a want read wrong, and such a chat is
handed over only for a person, a call, a complaint or a broker (untag_need, NEED_HANDOVERS); "No, I told you I need
another one" is no no to a second shop (second_shop_no); a buyer only the model recorded is never Lost.

What the record keeps (launch 2026-10-15; crm_facts.py, lost.py): a shops answer's notes are the customer's own
questions, its budget one they gave and its business activity a business (crm_facts.settle, first in settle);
a shops "no" writes Bot Status Lost and tells the lead's owner and the Lead AI alert list, and its lead moves
to Not Interested only when nobody works it and it has no open to-do (record_opt_out; tasks.write_crm_fields
asks lost.may_move); a name is greeted with its case put right and never a job title (name_from).

The launch gate (2026-10-16, batch 2d's real-model eval): a plain yes to our nudge gets code's two free slots, never a time
of the model's held for them (nudge_yes); their own exact day and hour is booked over another time the model recorded
(own_time), and no reply says our slots start on the hour (claims); "need one more" records no shop rented elsewhere
(who_they_are); their must-answer questions stay noted in their own words (crm_facts.their_questions); a known end user who
asks where we are gets code's invitation when the reply has none (location_invitation); "Who is this? Why did you call me?"
is no handover (settle_handover); the old lead's CRM notes are never quoted (lead_history.drop_quoted).

The gate's review (2026-10-16): own_time replaces only the model's confirm, at an hour said as one ("slot 2" is none),
never the hour work ends or a flight lands (hours.no_promise, T18 too) nor a time of ours they took (their_time); a
"Who is this?" reply that says a colleague will reply keeps its "unclear" (settle_handover); a reply the hourly claim
emptied gets code's two free slots from their hour (hourly_slots); only words that ask where we are get code's
invitation, never with their own day or hour, on their way, another area or the distance (location_invitation); a yes
to the morning nudge is asked about its own two slots again (nudge_yes); "I already rented another shop" stays rented
(needs.wants_another); the chat's facts are no ground for a figure of the CRM notes, and the notes' budget is not kept
as theirs (crm_facts.budget_of_notes).

A broker is never served as an end user (2026-10-17, brokers.py; eval shops-broker): a shops answer that records
facts.for_client true and hands the chat to nobody, or a burst whose own words say they are an agent or a broker or source
the shop for a client, is handed over as broker_or_for_client right after the model (live and in the eval), so the
hand-off line, the Broker label and the pause follow as for the model's own tag; never for a business owner's own
customers, family or a partner, or "client" in words about us, nor in a chat that carries the Broker label already.
Its review (2026-10-17): in a chat a person holds, or one whose answer or facts say they are the end user (for_client
false, their business known, "for myself"), only "I am / we are a broker" counts; our agent ("agent not here", "Office
mein agent hai?"), an owner's own client ("I have a client at 3"), a no or a fee ("not as an agent", "as broker
commission") never; a bare "Agent" answers our for-whom question only.

One bot for every need, batch 2e slice A (2026-10-17; tracks.py, lead_context.py): a shops chat's track (shop, rent, sale,
other, or not known yet) and unit are code's, decided before the model from the burst's words, the stored track, 2d's
facts.need, the lead context (read from Bitrix only when a step needs it, once per chat) and the campaign template's kind
(ic_templates), and again after the model with its tag; _apply stores them (state.track, state.unit, track_changed_at) and
the turn's actions carry them, in shadow: no reply changes, except the first yes to the mixed template, which is never the
shops' for-whom line by default (shops_rule's MIXED_YES: the opener for the studio or one-bedroom the lead asked about, or
"What are you looking for ...?"; a shop lead keeps the for-whom line).

Batch 2e slice C, the sales flow (2026-10-17; sales.py, calls.py; spec §3): a buyer of a studio or a one-bedroom (the sale
track, tracks.SALE_LIVE) may book a 5-minute call with our sales team in the call pool (calls.taken: one call per half hour,
no office slot, Q40), as a visit is booked: check_proposal and _shape take place "call" on the sale track only (``places``),
their own day and hour for a call books it and a call with no time gets two free call slots, never 2d's call_requested
handover (sales.call_step, right after the model); the full name comes first (the rent flow's residential.name_turn, before
_slot_gone, which reads the call pool for a call: a call is held and booked at its own place); the shops' own guards stay off
a buyer's answer (settle's ``track``), and after residential.settle (the sale track's commission line, Q33, among its guards)
sales.settle takes who_they_are's place: the questions in their order, the price never hidden, no media first, the call
slots, a buyer abroad called, negotiation, the mortgage process, DLD fees and legal questions to our sales team. The sale
flow rides on the residential path (RES_SYSTEM's sale section): residential.RENT_LIVE off turns it off too. A call's row is
marked (place "call", details.track "sale"), its alert says "Sales call", it gets no office pin, and its booking text is
res_call_booked (residential.confirmation, kind "call").
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
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

from .. import ic_templates, lane, unit_media
from ..models import DEFAULT_SHOPS_FACTS, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn
from . import (
    alerts,
    brokers,
    calls,
    caps,
    claims,
    communities,
    copilot,
    crm,
    crm_facts,
    crm_fields,
    filters,
    hours,
    inventory,
    lead_context,
    lead_history,
    live,
    lost,
    memory,
    needs,
    nudges,
    offers,
    openai_client,
    people,
    prompt,
    residential,
    reminders,
    rules,
    sales,
    schema,
    script,
    shop_buyer,
    shop_flow,
    shops,
    tracks,
    transcribe,
    transcript,
    turn_lock,
)

logger = logging.getLogger(__name__)

SOURCE = transcript.ASSISTANT
# A general chat's caps; a shops chat's are caps.SHOPS_PER_HOUR and caps.SHOPS_PER_DAY (caps.limits).
CAP_PER_DAY = 20
CAP_PER_HOUR = 6
# A turn the per-chat caps held back is skipped for this reason (followups.cap_pending reads it; a shops
# chat's is taken up again once the cap frees: caps.to_answer, caps.reclaim).
CAPPED_REASON = "reply limit reached"
STALE_AFTER = dt.timedelta(minutes=15)
# A message nobody answered is still answered up to this long after it came (run_turn): past it, a person decides.
LATE_UNTIL = dt.timedelta(hours=20)
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
# They want to come as soon as they can ("Can I come now?", "asap", "abhi aa sakta hoon?"): a slot sooner than the
# lead may be offered them (offers.fix_times).
_COME_NOW = re.compile(
    r"(?<!not\s)(?<!n't\s)\b(?:right\s+)?now\b|\basap\b|\bas\s+soon\s+as\s+possible\b|\bimmediately\b|\b(?:foran|fauran)\b"
    r"|\b(?:abhi|abhee)\b(?!\s+(?:nahi|nahin|nhi|nai)\b)|الآن|الان|حالا|فورا|ابھی(?!\s*نہیں)|फ़ौरन|अभी(?!\s*नहीं)",
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


# The opt-outs by weight: a stop anywhere in the burst outranks a softer word after it.
_OPT_OUT_RANK = {rules.STOP_ALL: 4, rules.WRONG_NUMBER: 3, rules.NOT_INTERESTED: 2}


def _burst_opt_out(burst, meeting_open: bool, shops_chat: bool = False) -> str | None:
    """An opt-out is the last thing the customer said ("STOP" then "🙏" is still a
    STOP; "Stop" then "sending studios, I need a 2BR" is not), except that a stop
    anywhere in the burst wins: the first mixed campaign (2026-10-19, chat 50108)
    delivered "Stop messages" and "Not now" out of order, the last item read as
    "Not now", and the studio price went to a customer who had just said stop."""
    said = _said(burst)
    key = said[-1] if said else burst[-1]
    found = _item_opt_out(key, meeting_open, shops_chat)
    # Taps only: typed words after a stop may take it back ("Stop" then "sending me studios, I need a 2BR"), a tap
    # on the template's button never does.
    for item in said or burst:
        if item.kind not in ("button", "interactive"):
            continue
        other = _item_opt_out(item, meeting_open, shops_chat)
        if other and _OPT_OUT_RANK.get(other, 1) > _OPT_OUT_RANK.get(found, 0):
            found = other
    return found


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


def name_from(*candidates) -> str:
    """The first candidate that names someone to greet, its case put right (filters.cased: "kamalraafat" is
    Kamalraafat), else '' (live and in the eval). Never a portal lead's title ("Bayut WhatsApp | Md Sumon" is "Md
    Sumon", filters.person_name), the campaign's "there", a lone "Md" (filters.first_name), nor a job title or a
    word of an address ("MANAGER", "Road": launch review issue 26)."""
    for candidate in candidates:
        name = filters.person_name(candidate)
        if filters.first_name(name):
            return filters.cased(name)
    return ""


def _customer_name(conversation, facts: dict) -> str:
    """The customer's name: the first of the facts, the campaign's recipient and the
    contact that names someone to greet (name_from)."""
    name = name_from((facts or {}).get("customer_name"))
    if name:
        return name
    from apps.campaigns.models import CampaignRecipient

    recipient = (
        CampaignRecipient.objects.filter(conversation=conversation)
        .exclude(name="")
        .order_by("-pk")
        .values_list("name", flat=True)
        .first()
    )
    return name_from(recipient, conversation.contact.display_name)


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
    """Our side's newest message, read past our office's pin (transcript.is_our_pin): the pin follows the reply of
    its turn and asks nothing, so the reply is what the customer answers, an "OK" to the owner's two slots among it."""
    rows = list(
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND)
        .select_related("template")
        .order_by("-pk")[:5]
    )
    return next((row for row in rows if not transcript.is_our_pin(row)), rows[0] if rows else None)


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


def turn_action(action: str, appointment: LeadAiAppointment | None, when, still_invalid: bool = False) -> str:
    """The action a turn takes (live and in the eval): effective_action, with the engine's own readings: the time already
    booked said again (reconfirm: nothing moves), a move with no new time (reschedule_requested), a late arrival at the
    booked time itself (on_time)."""
    action = effective_action(action, appointment)
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if action == "reschedule" and when is not None and confirmed and appointment.starts_at == when:
        return "reconfirm"
    if action == "reschedule" and when is None and not still_invalid:
        return "reschedule_requested"
    if action == "running_late" and when is not None and confirmed and appointment.starts_at == when:
        return "on_time"
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
    proposal: dict, appointment, now, closed_dates=(), *, grounding=None, segment: str = "", taken=(), said: str = "",
    places=calls.OFFICE_ONLY, call_taken=(),
) -> dt.datetime | None:
    """The validated start (or arrival), None when the action needs no time. Raises SlotError.

    ``grounding`` is (customer words, our last words); when given, a new time
    must be one the customer named or agreed to. ``taken``: the starts of the
    other chats' open office visits; the office takes one client per 30-minute
    slot, so a time one of them holds is refused with the two nearest free ones
    (never the time this chat already has booked). The time already booked, said
    again, and a walk-in (``said``, the burst's own words: "I'm outside") are
    never refused. ``places``: what this turn may book (calls.places_for: a buyer's call on the sale track, batch 2e
    slice C, checked against the call pool, ``call_taken``: one call per slot, never an office slot, Q40).
    """
    action = effective_action(proposal["action"], appointment)
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    if action in ("confirm", "reschedule"):
        if proposal["action"] == "reschedule" and confirmed and not proposal.get("date") and not proposal.get("time"):
            return None  # they want to move it and have not said when: recorded, and asked
        place = proposal.get("place")
        call = calls.allowed(place, places)  # SALE (slice C): a buyer's 5-minute call, booked in the call pool
        if place is None and segment == "owner":
            raise hours.SlotError(
                "no_place",
                "Say where the meeting is: place office for our office. A viewing at their property is "
                "tentative at customer_property with handover owner_viewing_slot.",
            )
        if (place or "office") != "office" and not call:
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
        taken = calls.pool(call, taken, call_taken)  # a call's own pool: one sales call per half hour, no office slot (Q40)
        walk_in = not call and _walk_in(start, said, now)
        if taken and not unchanged and not walk_in and hours.is_taken(start, taken):
            # A move offers neither another client's slot nor the one they are moving from.
            own = [appointment.starts_at] if confirmed and appointment.starts_at else []
            nearest = hours.nearest_free(start, now, closed_dates, [*taken, *own])
            offer = " and ".join(hours.describe(slot) for slot in nearest) or "none in the next three weeks"
            booked = (
                "That call time is already booked for another buyer: our sales team takes one call per 30-minute slot. "
                if call else "That time is already booked by another client: the office takes one client per 30-minute slot. "
            )
            raise hours.SlotError(
                "taken",
                f"{booked}The nearest free times are {offer}. Say it is taken and offer those two, asking which is better.",
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


def _shape(answer: dict, places=calls.OFFICE_ONLY) -> dict:
    """A confirm the office cannot take becomes what it is, handed to a person and
    never confirmed: a viewing at the owner's property or a call is tentative, and
    so is anything for someone outside our segments (a job applicant's interview).

    The model wrote its reply for a confirmation, so the words that go out are
    then a fixed line (``answer["converted"]``), never its "you are confirmed".
    A buyer's call on the sale track (``places``, calls.allowed) is booked like a visit, never handed over.
    """
    proposal = answer["appointment"]
    if proposal["action"] not in ("confirm", "reschedule"):
        return answer
    if calls.allowed(proposal["place"], places):
        return answer  # SALE (slice C): the call pool books it (check_proposal), the bot keeps answering the chat
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
# A shops chat may quote the rents, so only a discount is a price question there. "Cheaper", "lower" and
# "lowest" are no discount (launch review issue 12): they get the honest price line, our lowest type
# (claims.price_turn); "discount", "best price" and "negotiate" keep the discount line.
_DISCOUNT = re.compile(
    r"discount|best price|last price|final price|reduce|reduction|negotia|kam kar|kuch kam|rebate"
    r"|خصم|تخفيض|تنزيل|ڈسکاؤنٹ|رعایت|کم کر|छूट|डिस्काउंट|कम कर",
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


# What answer["trimmed"] says when a reply to "Who is this?" lost its promise of a colleague's reply (settle_handover).
COLLEAGUE_REPLY = "colleague_reply"
# The model's handovers that a burst asking only who we are takes off (settle_handover): it asks for nobody. The 2d gate's
# runs of review-why-did-you-call handed "Who is this? Why did you call me?" over as "unclear" ("Our specialist will reply
# here to assist you further") and as "customer_asked_human" ("A team member can assist you here if you want").
WHO_WE_ARE_HANDOVERS = ("unclear", "customer_asked_human")


def who_we_are_reply(reply: str) -> str:
    """The reply to "Who is this? Why did you call me?" without its sentences that say a colleague will reply to them
    (people.says_colleague_replies), '' when nothing else is left: settle_handover takes the model's handover off such a
    burst (WHO_WE_ARE_HANDOVERS), so no colleague is told. The deployed gate's eval review-why-did-you-call, both runs: "This
    is A7 Real Estate regarding shops for rent in International City near Dragon Mart. Our specialist will reply here to
    assist you further." handed over as "unclear" goes as its first sentence, handed to nobody."""
    return " ".join(sentence for sentence in people.sentences(reply) if not people.says_colleague_replies(sentence))


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


def settle_handover(
    answer: dict, earlier: list, new_texts: list | None = None, shops_chat: bool = False, *, invites: int = 0
) -> dict:
    """The model's handover, corrected where code knows better: a renewal's price
    question is renewal_terms; the first price question is no handover; asking
    for the price again after our answer is one (with the holding line, never
    a second copy of the deflection). A shops chat has its own (discounts).
    Every playbook: an "unclear" or a "customer_asked_human" (WHO_WE_ARE_HANDOVERS)
    for a burst that only asks who we are or why we wrote (rules.asks_who_we_are:
    "Who is this? Why did you call me?") is none; both prompts answer it with the
    company and the campaign, and it asks for nobody (eval review-why-did-you-call:
    handed over in one run of two, then as "customer_asked_human" too). A reply
    that says a colleague will reply to them (people.says_colleague_replies: "Our
    specialist will reply here to assist you further") loses that sentence with the
    handover: without it no colleague is told, so nobody would reply (the deployed
    gate's eval, both runs: who_we_are_reply). Only while the reply has words of its
    own left (who we are); a reply that only promises the colleague keeps the
    handover, and so does any reply after two invitations (``invites``), where both
    prompts hand the chat over as "unclear". answer["trimmed"] then names
    COLLEAGUE_REPLY (the English gloss no longer holds)."""
    if (
        answer["handover"]["needed"] and answer["handover"]["reason"] in WHO_WE_ARE_HANDOVERS and invites < 2
        and rules.asks_who_we_are(new_texts)
    ):
        promised = people.says_colleague_replies(answer["reply"])
        kept = who_we_are_reply(answer["reply"]) if promised else answer["reply"]
        if not promised or kept:
            answer["handover"] = {"needed": False, "reason": None}
            if promised:
                answer["reply"] = kept
                answer["trimmed"] = [*(answer.get("trimmed") or []), COLLEAGUE_REPLY]
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
# The lost reason of a no to the second-shop question (Bitrix reads it as the lead's reason).
RENTED_REASON = "already rented"
NOT_NOW = "not_now"
FOR_WHOM = "for_whom"
SPAM_RULE = "spam"
# The mixed template's first yes (batch 2e, spec §1.4.2): "mixed_yes:res_open_lead" or "mixed_yes:res_what_need".
MIXED_YES = "mixed_yes"
# What a lead in discovery has told us, in the build pack's order (business, size or budget,
# licence): with two of these, spam words are the model's to judge, never code's.
_DISCOVERY = (("business_activity",), ("size_sqft",), ("budget_aed",), ("licence_kind", "trade_licence"))


def _discovery_facts(facts: dict | None) -> int:
    """How many of the business, the size, the budget and the licence the chat's facts hold."""
    facts = facts or {}
    return sum(1 for keys in _DISCOVERY if any(facts.get(key) not in (None, "", []) for key in keys))


# A no to "Do you need a second shop, or do you know someone who does?" in other words than a plain no
# (launch chat 63: "if anything will let you know", "will definitely reach out if we need anything in the
# future"; it stayed Qualifying for good): the lead closes as already rented, as for "No" (board T27, launch
# review issue 23). Never a yes ("Yes, I need one more for my brother"), a question, or someone else who
# needs one ("my friend needs one"): those are the model's.
_LATER_IF_NEEDED = re.compile(
    r"\bif\s+(?:anything|any\s+thing|something|needed|required|we\s+need|i\s+need|need\s+be|there\s+is\s+any\s+need)\b"
    r"|\bin\s+(?:the\s+)?future\b|\breach\s+out\b|\bget\s+in\s+touch\b|\ball\s+good\b"
    r"|\b(?:we'?re|we\s+are|i'?m|i\s+am)\s+(?:good|fine|all\s+set|sorted|settled|ok|okay)\b"
    r"|\bjab\s+zaroo?rat\b|\bzaroo?rat\s+(?:hui|ho|pari|padi|hogi)\b",
    re.IGNORECASE,
)
_SOMEONE_ELSE = re.compile(
    r"\b(?:friend|friends|brother|sister|cousin|relative|partner|colleague|client|someone|somebody|uncle|father|son|wife)\b", re.IGNORECASE
)
# What a no to the second shop never says (review 2d): a want or a request of theirs ("No, I told you I need another one",
# "All good, send me the list", "I'm ok with one more if the price is good", "No we did not take it, I am asking your best
# rent"), or that they have not rented after all ("no not rented yet"). An "if we need anything" asks nothing.
_STILL_WANTS = re.compile(
    r"\b(?:i|we)\s+(?:still\s+|really\s+|do\s+)?(?:need|want|would\s+like|will\s+take|'?ll\s+take|am\s+asking|are\s+asking)\b"
    r"|\b(?:another|one\s+more|second|bigger|smaller|send|list|price|prices|rent|cheaper|discount|show|interested|take|asking)\b"
    r"|\b(?:not|never|did\s*n'?t|did\s+not|have\s*n'?t|have\s+not)\s+(?:\w+\s+)?(?:rented|taken|took|got|found)\b|\bnot\s+yet\b",
    re.IGNORECASE,
)
_IF_CLAUSE = re.compile(r"\bif\b[^.,;!?\n]*", re.IGNORECASE)


def second_shop_no(text: str) -> bool:
    """Their answer to our second-shop question turns it down, in any words: a whole no ("No", "No thanks"), "not now",
    a deferral ("if anything will let you know"), "we will reach out if we need anything". shops_rule's RENTED_NO takes
    it, as a plain no (rules.is_refusal): a check-back for a second shop would never go (followups.holds holds every
    follow-up of a chat that rented elsewhere). Never a message that wants or asks for something, nor one that says
    they have not rented after all (_STILL_WANTS): those are the model's to answer."""
    words = " ".join(str(text or "").replace("’", "'").split())
    if not words or rules.asks_question(words) or opens_with_yes([words]) or _SOMEONE_ELSE.search(words):
        return False
    if rules.is_refusal(words):
        return True  # "No", "No thanks", "not interested", "nahi chahiye": the whole message
    if _STILL_WANTS.search(_IF_CLAUSE.sub(" ", words)):
        return False
    return bool(rules.is_not_now(words) or rules.mentions_deferral(words) or _LATER_IF_NEEDED.search(words))


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
    template_kind: str = ic_templates.SHOP,
    mixed: str = "",
    track: str | None = None,
) -> str:
    """Which of the shops rules settles this burst without the model, else ''.

    ``text`` is the last thing the customer said (a tap's label, ``tapped``),
    ``single`` that nothing else was said with it. ``followup_open``: our last
    message asked "Should I check back with you in a month?"; ``rented_open``:
    they said they already rented a shop and our last message asked about a
    second one, whose no in any words (second_shop_no) closes the lead as already
    rented; ``first_answer``: nobody from our side wrote since the campaign
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

    The mixed template's yes ([Yes, still looking], a typed yes; ``template_kind``
    not a shops one, batch 2e) is never the for-whom line by default: ``mixed`` is
    tracks.first_yes of the chat's track, the opener for the studio or one-bedroom
    the lead asked about (MIXED_YES), "What are you looking for ...?", the shops'
    own rules for a shop chat, or nothing (the model) for a need the chat knows.
    So is any template's yes on a known rent or sale track (reads_first_yes): the
    opener for its studio or one-bedroom, or the model once who it is for is known.

    ``track``: the chat's track (tracks.decide, batch 2e). On the rent, sale and
    not-known tracks (residential.live_track) only the rules of every track apply
    (spam, the check-back, "Not now", the mixed template's yes): never the shops'
    for-whom line, their second-shop no, nor a known end user's shop step (spec
    §1.4.2). None: a caller that names no track, as before.
    """
    words = (text or "").strip()
    if quiet or not single or not words:
        return ""
    shop_rules = track is None or not residential.live_track(track)
    if not tapped and not meeting_open and _discovery_facts(facts) < 2 and rules.looks_like_spam(words):
        return SPAM_RULE
    if followup_open:
        if rules.is_acceptance(words):
            return CHECK_BACK_YES
        return CHECK_BACK_NO if rules.is_refusal(words) else ""
    if shop_rules and rented_open and (rules.is_refusal(words) or second_shop_no(words)):
        return RENTED_NO
    if ((tapped and not meeting_open) or not visit_on_table) and rules.is_not_now(words):
        return NOT_NOW
    # The first yes to the mixed template, or to any template on a known rent or sale track (spec §1.4.2: "A template 'yes'
    # on a track that is already known gets that track's next step"): ``mixed`` is tracks.first_yes of the chat's track.
    home_yes = not shop_rules and track in (tracks.RENT, tracks.SALE)
    if (
        first_answer and (template_kind != ic_templates.SHOP or home_yes) and mixed != tracks.FOR_WHOM
        and (rules.is_positive_tap(words) or rules.is_acceptance(words))
    ):
        return f"{MIXED_YES}:{mixed}" if mixed else ""
    if not shop_rules:
        return ""
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


def flow_taps(taps) -> bool:
    """Every item is a tap on our shop types list or a type's card ((label, id) pairs; the eval has the label alone): a shop
    wish in so many words, which tracks.decide reads as the shop track (batch 2e review: a studio seeker's tap on the shop
    list 2d once sent them got the type's media on the rent track)."""
    pairs = [(str(label or ""), str(tap_id or "")) for label, tap_id in taps or ()]
    return bool(pairs) and all(label and tap_rule_name(shop_flow.tap_rule(label, tap_id)) for label, tap_id in pairs)


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
    confirm of a time the customer neither gave nor took (unasked_confirm), or of a plain yes to
    our nudge (nudge_yes). None when the model's words go.

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
    # A tap sent with typed words: the words say what they ask for, never the tap's own label (launch review issue 13).
    typed = shop_flow.typed_words(said)
    requested = (
        not plain and effective == "tentative" and not (answer.get("unasked") or answer.get("nudge_yes"))
        and (shop_flow.asks_media(typed) or shop_flow.asks_types(typed))
        and step_plain(answer, still_invalid=still_invalid, when=when, effective="none", quiet=quiet, said=said)
        # No shop step for someone who wants no shop to rent: their tentative stays as the model left it.
        and not shop_flow.shops_unwanted(answer["facts"], known, said)
    )
    invitation = (
        not plain and effective == "tentative" and appointment is None and not agreed and not answer.get("theirs")
        and step_plain(answer, still_invalid=still_invalid, when=when, effective="none", quiet=quiet, said=said)
        and not wants_to_come(said, now)
    )
    step = shop_flow.after_model(
        answer,
        known,
        typed,
        plain=plain,
        invitation=invitation,
        requested=requested,
        asked=customer_asks(typed, now),
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
    unasked = answer.get("unasked") or answer.get("nudge_yes")
    if step is None and unasked and answer["opt_out"] == "none" and not answer["handover"]["needed"] and not answer.get("converted"):
        step = {"kind": shop_flow.SLOTS, "slots": list(unasked["slots"])}
        if unasked.get("again"):
            step["again"] = True  # our nudge's own two, asked about again (nudge_yes)
    if step is not None:
        answer["shop_step"] = step
    return step


def burst_tap(said, heard: dict | None = None) -> tuple[str, str] | None:
    """The tap of a burst that holds words of theirs too (shop_flow.burst_tap), read from its messages: a text, or
    a voice note heard, beside the taps."""
    taps = [(_tap_label(item), _tap_id(item)) for item in said if _tap_label(item)]
    typed = any(
        not _tap_label(item)
        and ((item.kind == "text" and (item.body or "").strip()) or (item.kind == "audio" and (heard or {}).get(item.pk)))
        for item in said
    )
    return shop_flow.burst_tap(taps, typed)


def price_plain(answer: dict, known: dict, need, said: str, *, when=None, still_invalid: bool = False, quiet: bool = False) -> bool:
    """Nothing must go out instead of the price line (claims.price_turn): no person on the chat, booking or time to
    refuse, opt-out, handover, fixed line, taken slot, broker or shop step, no customer who wants no shop to rent,
    and no location or way asked for (that answer goes as it always did)."""
    if quiet or when is not None or still_invalid:
        return False
    if answer["opt_out"] != "none" or answer["handover"]["needed"] or answer.get("converted") or answer.get("not_a_shop"):
        return False
    if answer.get("slot_taken") or answer.get("broker") or answer.get("shop_step"):
        return False
    if need is not None or needs.of({**(known or {}), **answer["facts"]}) is not None:
        return False
    if filters.asks_the_way(said):
        return False
    # "no good location" beside a price objection names the location and asks for nothing (launch chat 100).
    location = filters.asks_for_location(said) and (
        not claims.objects_to_price([said]) or rules.asks_question(said) or offers.requests_location(said)
    )
    return not location


def _step_words(reply: str, *, types: bool) -> str:
    """The model's words that go before a tap's step (a type's media or the list): its answers, without its
    questions and invitations (the step asks its own), and without its words on our types (``types``: the
    card or the list that follows gives them)."""
    kept = [
        sentence for sentence in filters.split_sentences(reply)
        if not rules.asks_question(sentence) and not _inviting(sentence) and not (types and shop_flow.names_types(sentence))
    ]
    return " ".join(kept)


def tap_with_words(
    answer: dict,
    tap: tuple[str, str] | None,
    known: dict,
    said: str,
    now,
    *,
    first_answer: bool,
    appointment=None,
    when=None,
    still_invalid: bool = False,
    quiet: bool = False,
    media_recent=(),
    media_today=(),
    closed_dates=(),
    taken=(),
) -> str:
    """A tap sent together with typed words keeps its build-pack step, and the model answers the words (live and in
    the eval, after people.settle; launch review issue 13). Returns what was done ('' for nothing).

    ``tap``: shop_flow.burst_tap's (the burst's last tap, when it holds words of theirs too); ``first_answer``: our
    last message is the campaign's. Only when nothing else must go out instead (step_plain: an opt-out, a handover
    or a person on the chat, a booking or a time to refuse, a fixed line, a taken slot, a broker, the location asked
    for) and never for someone who wants no shop to rent (shop_flow.shops_unwanted):

    - a template's yes on their first answer, while who the shop is for is not known (chat 81): the model's
      answer, then the build pack's "Is the shop for yourself, or are you checking for a client?" as the reply's
      one question;
    - a row of our list (chat 88): that type's video, photos and card (shop_flow.media_step), the model's answers
      first, without its questions, invitations or words on the types (answer["step_words"]);
    - [See other types], or a known end user's [Yes, show me shops]: the list, the same way;
    - [Book viewing], or a known end user's [Yes, book a viewing]: two free slots, when the reply offers none."""
    if tap is None or answer.get("shop_step"):
        return ""
    effective = effective_action(answer["appointment"]["action"], appointment)
    typed = shop_flow.typed_words(said)
    # Their location asked for goes as it always did; "Preferable Location - France" (chat 88) asks for nothing.
    if not step_plain(answer, still_invalid=still_invalid, when=when, effective=effective, quiet=quiet, said="") or offers.asks_location_now(typed):
        return ""
    if shop_flow.shops_unwanted(answer["facts"], known, typed):
        return ""
    kind, value = tap
    known = known or {}
    facts = {**known, **{key: v for key, v in answer["facts"].items() if v not in (None, "", [])}}
    language = answer["language"]
    reply = answer["reply"] or ""
    if kind != shop_flow.TAP_YES and (shop_flow.asks_types(typed) or (shop_flow.asks_media(typed) and kind != shop_flow.TAP_TYPE)):
        return ""  # their words ask for the shop types or photos themselves: model_step's step, as for words alone
    if kind == shop_flow.TAP_YES:
        if facts.get("for_client") is None and first_answer:
            if shop_flow.asks_for_whom(reply):
                return ""
            kept = [sentence for sentence in filters.split_sentences(reply) if not rules.asks_question(sentence) and not _inviting(sentence)]
            question = shop_flow.for_whom_question(language) if kept else rules.line("for_whom", language)
            answer["reply"] = " ".join([*kept, question])
            answer["send"] = True
            answer["invited_to_meeting"] = answer["share_office_location"] = False
            answer["trimmed"] = [*(answer.get("trimmed") or []), "tap_step"]  # its English gloss no longer holds
            return "for_whom"
        if facts.get("for_client") is not False or not first_answer:
            return ""
        kind = shop_flow.TAP_BOOK if value == "book" else shop_flow.TAP_TYPES
    if kind == shop_flow.TAP_TYPE:
        # A request for its photos or video in their words: the files again, as a typed request gets them.
        step = shop_flow.media_step(value, typed=shop_flow.asks_media(typed), recent=media_recent, today=media_today)
        if step is None:
            return ""
        answer["facts"]["shop_type"] = value
        answer["shop_step"] = step
        answer["step_words"] = _step_words(reply, types=True)
        return "media"
    if kind == shop_flow.TAP_TYPES:
        answer["shop_step"] = {"kind": shop_flow.LIST}
        answer["step_words"] = _step_words(reply, types=True)
        return "list"
    if kind == shop_flow.TAP_BOOK:
        if value in shop_flow.TYPE_KEYS:
            answer["facts"]["shop_type"] = value
        if offers.offers_slots(reply):
            return ""
        own = [appointment.starts_at] if appointment is not None and appointment.starts_at else []
        pair = hours.offer_pair(now, closed_dates, [*taken, *own])
        if not pair:
            return ""
        kept = [sentence for sentence in filters.split_sentences(reply) if not rules.asks_question(sentence) and not _inviting(sentence)]
        answer["reply"] = " ".join([*kept, shops.slot_offer(language, pair, now)])
        answer["send"] = True
        answer["invited_to_meeting"] = False  # their own request to come, as [Book viewing] alone (step_flags)
        answer["trimmed"] = [*(answer.get("trimmed") or []), "tap_step"]
        return "slots"
    return ""


def reads_first_yes(template_kind: str, decision) -> bool:
    """The first yes to this campaign template reads the chat's track (tracks.first_yes; live and in the eval): the mixed
    template's always, and any template's on a known rent or sale track (spec §1.4.2: "A template 'yes' on a track that is
    already known gets that track's next step"; §1.2: what the chat knows decides before the template does). The 2e
    real-model gate, round 2: a studio seeker's "Yes" to a shops template went to the model, which tagged wants_shop in both
    runs of shops-res-yes-to-shops-template, and the chat moved to the shop track with the shops' for-whom line (once a
    broker's hand-off). Never with the rent flow off (residential.live_track): 2d's own rules then."""
    if decision is None:
        return False
    return template_kind != ic_templates.SHOP or (decision.track in (tracks.RENT, tracks.SALE) and residential.live_track(decision.track))


def _mixed_answer(line_kind: str, language: str, decision, known: dict | None = None) -> dict:
    """The mixed template's first yes (MIXED_YES): code's opener for the studio or one-bedroom we know (``open_lead``:
    tracks.open_lead_text, in the language code writes in), else "What are you looking for ...?" (rules). The opener records
    2d's want of the lead's studio or one-bedroom too (residential.record_need, as every rent and sale turn does: spec
    §1.4.10), so the follow-ups read the chat as one that wants no shop (the 2e eval review: its nudges spoke of shops)."""
    if line_kind != tracks.OPEN_LEAD or decision is None or decision.unit not in tracks.UNITS:
        line_kind = tracks.WHAT_NEED
    segment = "other"
    if line_kind == tracks.OPEN_LEAD:
        segment = "buyer" if decision.deal == tracks.SALE else "residential_tenant"
    answer = schema.normalize({"language": language, "segment": segment, "send": True, "reply": "-"}, shops=True)
    answer["rule"] = f"{MIXED_YES}:{line_kind}"
    answer["converted"] = line_kind
    if line_kind == tracks.OPEN_LEAD:
        answer["open_lead"] = {"unit": decision.unit, "clusters": list(decision.clusters)}
        answer["reply"] = tracks.open_lead_text(language, decision.unit, decision.clusters)
        residential.record_need(answer, known or {}, decision)
    else:
        answer["reply"] = rules.line(line_kind, language)
    return answer


def shops_answer(rule: str, language: str, words: str = "", known: dict | None = None, decision=None) -> dict:
    """What code answers for a shops rule, shaped like a model's answer: a fixed line
    (``converted``), or for a no the not-interested opt-out with the reason
    (``lost_reason``). ``followup`` tells _apply what to do with the check-back:
    "ask", "schedule" (in a month) or "clear". A tap on the shops list or a card, and
    the licence copy, get a step (``shop_step``; _flow_answer); ``known`` is the chat's facts.
    The mixed template's first yes reads the chat's track (``decision``: tracks.decide)."""
    if rule.partition(":")[0] == MIXED_YES:
        return _mixed_answer(rule.partition(":")[2], language, decision, known)
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
        answer["lost_reason"] = RENTED_REASON if rule == RENTED_NO else (words or "not interested")
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


def licence_first(answer: dict, known: dict, earlier: list, new_texts: list, now=None, *, invites: int = 0) -> bool:
    """A shops reply that invites while the licence, the build pack's next discovery
    item, is still unknown, rewritten to ask it (rules "ask_licence"), without the
    location the invitation would have carried; True when it was.

    The build pack: business, size or budget, licence, then the viewing (SHOPS_SYSTEM's
    THE VIEWING says the same; the model invited instead in eval shops-35283, after
    "I have vape business."). Only for a known end user whose size or budget is known,
    while no slot is on the table, our last line did not ask about the licence already
    (no loop on an answer the model could not read), and the customer's own words this
    time neither ask anything nor ask to come, see or book, nor ask where we are, nor
    name a day or an hour: those still get the invitation straight away. ``known``: the
    chat's facts before the turn; ``earlier``: the conversation before the burst, as
    (author, text); ``invites``: INVITES SO FAR.

    The first invitation waits for the licence whatever the business (discovery_first:
    it may go at once when a location is asked for, or a size and a licence are known);
    a later one asks the business first (discovery_first), so only a later one needs
    the business known here (recorded, or answering our question about it). Where we
    are is asked in so many words only (offers.asks_where_we_are, as
    location_invitation reads it). The deployed gate's eval shops-invitation-cut-88,
    both runs: launch chat 88's "Preferable Location - France (P24 P23 P26 P22) / Size
    - 400sqft", his business and licence never asked, got "Type 1 is perfect ... I can
    hold a slot for you today at 12:00 PM or 1:00 PM" with our location under it: the
    word "Location" read as asking where we are, and the business unknown.
    """
    known = known or {}
    facts = dict(known)
    facts.update({key: value for key, value in answer["facts"].items() if value not in (None, "", [])})
    ours = [text for author, text in earlier if author in ("assistant", "agent")]
    last = ours[-1] if ours else ""
    if facts.get("for_client") is not False or facts.get("licence_kind") or facts.get("trade_licence"):
        return False
    if needs.of(known) is not None or needs.wants_no_shop(facts) or needs.detect(new_texts or []) is not None:
        # Someone who wants no shop to rent, known, recorded now (a home, to buy or to sell) or said now, is never asked for a
        # shop licence (who_they_are; batch 2e's rent and sale tracks, whose budget is a rent's or a price).
        return False
    if not (facts.get("size_sqft") or facts.get("budget_aed")):
        return False
    # The business, for a later invitation: recorded, or what they answer now to our question about it (size or budget
    # known before). The first one waits for the licence alone.
    answering_business = bool(_BUSINESS_WORDS.search(last)) and bool(known.get("size_sqft") or known.get("budget_aed"))
    if invites and not (facts.get("business_activity") or answering_business):
        return False
    if filters.offers_time(last) or _LICENCE_WORDS.search(last):
        return False
    said = " ".join(new_texts or [])
    if (
        rules.asks_question(said) or offers.asks_where_we_are(new_texts) or filters.asks_the_way(said) or _VISIT_WORDS.search(said)
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


def discovery_first(answer: dict, known: dict, earlier: list, new_texts: list, invites: int, *, agreed: bool = False, now=None) -> bool:
    """A shops reply that would invite them again while their business or their licence is still unknown,
    rewritten to ask it (rules "ask_business", then "ask_licence"), without the invitation and the location it
    would have carried; True when it was (launch review issue 22: chats 88, 91, 96 and 62 were invited without
    being asked their business or licence, though the confirmation asks them to bring the licence).

    The build pack's DISCOVERY comes before THE VIEWING; the first invitation may still go at once (a location
    asked for, a size and a licence known), and the second waits for the business and the licence: an
    invitation counted already (``invites``), whether this one is new or our slots offered again. Only for a
    known end user who wants a shop, when they did not agree to come (``agreed``) nor book (the answer confirms or
    moves a visit: code's T18 or window upgrade among them) and their words now neither ask to come, see or book,
    nor ask the location or the way, nor name a day or an hour, and when our last line did not ask that item
    already (no loop on an answer the model could not read). A question of theirs is still answered: the reply's
    other sentences stay."""
    if agreed or invites < 1 or answer["appointment"]["action"] in ("confirm", "reschedule"):
        return False
    known = known or {}
    facts = {**known, **{key: value for key, value in answer["facts"].items() if value not in (None, "", [])}}
    if facts.get("for_client") is not False or needs.of(known) is not None or needs.detect(new_texts or []) is not None:
        return False
    business = bool(facts.get("business_activity"))
    licence = bool(facts.get("licence_kind") or facts.get("trade_licence"))
    if business and licence:
        return False
    said = " ".join(new_texts or [])
    if (
        filters.asks_for_location(said) or filters.asks_the_way(said) or _VISIT_WORDS.search(said)
        or hours.named_days(said, now) or hours.named_times(said)
    ):
        return False
    sentences = filters.split_sentences(answer["reply"])
    if not (answer["invited_to_meeting"] or any(_inviting(sentence) for sentence in sentences)):
        return False
    ours = [text for author, text in earlier if author in ("assistant", "agent")]
    last = ours[-1] if ours else ""
    line = "ask_business" if not business else "ask_licence"
    if _BUSINESS_WORDS.search(last) if line == "ask_business" else _LICENCE_WORDS.search(last):
        return False
    kept = [sentence for sentence in sentences if not _inviting(sentence) and not rules.asks_question(sentence)]
    answer["reply"] = " ".join([*kept, rules.line(line, answer["language"])])
    answer["invited_to_meeting"] = False
    answer["share_office_location"] = False
    return True


def plans_or_elsewhere(said: str, now) -> bool:
    """Their words carry a plan of their own (a day or an hour: "Send location, I will come at 6"; a walk-in or coming now:
    "I am at Dragon Mart now, send location I will come"), or want another area or object to the distance
    (offers.elsewhere: "Location is too far for me"): code's invitation answers none of them (location_invitation)."""
    said = str(said or "").replace("’", "'")
    return bool(
        hours.named_days(said, now) or hours.named_times(said) or _WALK_IN_WORDS.search(said) or _COME_NOW.search(said)
        or offers.elsewhere(said)
    )


def location_invitation(
    answer: dict, known: dict, new_texts: list, slots, now, *, agreed: bool = False, reoffer: bool = False, office_address: str = "",
    before: str = "",
) -> bool:
    """A shops reply that answers where we are and names no slot, to a known end user who asks for our location (or the
    way to us) now: code's invitation with the two free ``slots`` (settle's: the chat may still be invited) closes it, as
    the build pack invites "straight away when they ... ask where we are", and every invitation names two concrete free
    slots ("Our office is in ..." offers none). Live and in the eval, from settle. The reply's own questions go (the
    invitation is its one question: the launch gate's eval shops-location-counted-81 asked a known end user "Is the shop
    for yourself, or are you checking for a client?" again, with no slots, in one run of two; launch chat 100's "Send me
    address first" got "Would you like to book a viewing?"), its answers stay, and our location goes with it when the
    reply does not give it. Not after a yes (``agreed``: a visit open, or a yes to our offer), with a no, "not now" or
    another day in their words (turns_down), for a booking, an opt-out, a handover or a fixed line, nor for someone who
    wants no shop to rent (their line is who_they_are's). ``before``: our side's last words (the same sentence is never
    said twice). Code's slots are an invitation, unless they are our offer said again (``reoffer``). True when the reply
    changed.

    Only a clause that itself asks where we are (offers.asks_where_we_are: "Location", "Send me address first"), never
    the word with a "?" anywhere in the burst; and never with a day or an hour of their own ("Send location, I will come at
    6"), a walk-in or coming now ("I am at Dragon Mart now, send location I will come"), another area or the distance
    objected to (offers.elsewhere): the launch gate's review found "Is the location good for a restaurant?" and "Do you
    have shops in another location like Al Quoz?" answered with our slots and location, the model's own question gone."""
    if agreed or not slots or not answer["reply"] or not answer["send"] or answer.get("converted"):
        return False
    if answer["opt_out"] != "none" or answer["handover"]["needed"] or answer["appointment"]["action"] not in ("none", "tentative"):
        return False
    said = " ".join(str(text or "") for text in new_texts or ())
    if not offers.asks_where_we_are(new_texts) or turns_down(new_texts):
        return False  # where we are, asked without a no, "not now" or another day said with it
    if plans_or_elsewhere(said, now):
        return False  # their own day or hour, on their way, another area or too far: the model's answer to it stands
    known = known or {}
    facts = {**known, **{key: value for key, value in answer["facts"].items() if value not in (None, "", [])}}
    if facts.get("for_client") is not False or needs.of(known) is not None or needs.detect(new_texts or []) is not None:
        return False
    sentences = filters.split_sentences(answer["reply"])
    if any(filters.offers_time(sentence) for sentence in sentences):
        return False  # it names a time already: offers.fix_times keeps it valid
    line = shops.slot_offer(answer["language"], list(slots), now)
    if before and filters.said_before(line, [before]):
        again = shops.slot_offer(answer["language"], list(slots), now, again=True)
        line = line if filters.said_before(again, [before]) else again
    kept = [sentence for sentence in sentences if not rules.asks_question(sentence)]
    answer["reply"] = " ".join([*kept, line])
    if not reoffer:
        answer["invited_to_meeting"] = True  # code's two slots are an invitation (launch review issue 24)
    if not filters.carries_location(answer["reply"], office_address):
        answer["share_office_location"] = True  # they asked where we are: our location goes with the slots
    return True


# What answer["trimmed"] says when code's slots answered a reply that only said our slots start on the hour.
HOURLY_SLOTS = "hourly_slots"


def hourly_slots(answer: dict, new_texts: list, earlier: list, now, closed_dates=(), taken=(), *, booked=None) -> bool:
    """A shops reply that claims.settle left empty, its only words a claim that our slots start on the hour (claims.HOURLY:
    "Our office slots start on the hour, so please choose 4:00 PM or 5:00 PM." to "Can I come today at 4:30?"): code's two
    free slots instead, from the hour they named (shops.yes_slots with named_hour: "I can hold a slot for you today at 4:30
    PM or 6:30 PM — which is better?"), else the next free pair, in other words when our side said that very sentence
    lately. The launch gate's review: the turn was skipped as "no reply needed", and their visit request went unanswered.
    Never for a booking, a handover, an opt-out or a fixed line, whose own words go. Live and in the eval, from settle.
    ``booked``: the open visit's start, never offered. True when the reply changed."""
    if now is None or answer["reply"] or answer.get("converted") or answer["opt_out"] != "none" or answer["handover"]["needed"]:
        return False
    if answer["appointment"]["action"] not in ("none", "tentative"):
        return False
    said = " ".join(str(text or "") for text in new_texts or ()).replace("’", "'")
    ours = [text for author, text in earlier if author in ("assistant", "agent", "campaign", "reminder")]
    pair = shops.yes_slots(said, ours[-1] if ours else "", now, closed_dates, [*taken, *([booked] if booked else [])], at=named_hour(said, now))
    if not pair:
        return False
    line = shops.slot_offer(answer["language"], pair, now)
    before = "\n".join([text for author, text in earlier if author == "assistant"][-3:])
    if before and filters.said_before(line, [before]):
        again = shops.slot_offer(answer["language"], pair, now, again=True)
        line = line if filters.said_before(again, [before]) else again  # never the same sentence twice in a chat
    answer["reply"] = line
    answer["send"] = True
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
    closed_dates=(),
    taken=(),
    booked=None,
    shops_facts=None,
    office_address: str = "",
    crm_notes: str = "",
    residential: bool = False,
    residential_facts=None,
    track: str = "",
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
    A shops reply also states no fact SHOP FACTS lacks (claims.settle: a shop's building or side, a food
    business allowed, a sale, the commission, the deposit), never gives the size and price table again
    unasked (claims.drop_table_repeat), asks the business and the licence before a second invitation
    (discovery_first), offers only valid slots (offers.fix_times: an hour ahead and an hour apart at least,
    never past, never taken: ``closed_dates``, ``taken``, ``booked`` the open visit's start) and counts every
    slot pair it offers as an invitation (offers.count_invitation). ``shops_facts``: the settings' facts;
    ``office_address``: our office's (a reply may give it as ours, never as a shop's). ``crm_notes``: the old lead's
    CRM notes as the context showed them, whose figures a shops reply never quotes (lead_history.drop_quoted); a
    location asked for gets code's invitation with ``slots`` when the reply has none (location_invitation).
    ``residential``: a shops chat on the rent, sale or not-known track (batch 2e): none of the shops' own guards (the
    business, SHOP FACTS' claims and table, the licence and discovery steps); its notes, budget, quoted CRM notes,
    repeats (code's residential lines kept), slots and times as a shops chat's; residential.settle then cuts the rest.
    What is cut or rewritten in the reply is listed in ``answer["trimmed"]``, so
    its English gloss no longer holds; ``answer["broker"]`` asks _apply to label
    and pause the chat; ``answer["pointed"]`` says the reply now points to the
    location (its gloss got the same line). ``track``: the chat's (tracks.decide); a buyer's (the sale track, batch 2e
    slice C) gets none of the shops' claims, discovery, licence or office-slot guards: sales.settle follows instead.
    """
    shops_chat = playbook == lane.IC_SHOPS
    # The residential path (batch 2e: rent, sale, not known) and a buyer's answer (SALE, slice C) get none of the shops' own
    # guards: residential.settle and, on the sale track, sales.settle follow with theirs.
    residential = residential or (shops_chat and track == tracks.SALE)
    shop_guards = shops_chat and not residential
    shop_facts = shops_facts or DEFAULT_SHOPS_FACTS
    untagged = ""
    if shops_chat and residential and not broker_labelled:
        # The 2e real-model gate, round 4 (shops-res-owner-number): the model's broker tag over a number ask alone, in a chat
        # that said for themselves, comes off before settle_handover and the broker line read it (brokers.backstop has run
        # already), so the turn goes as one with no handover: residential.settle answers the number (res_no_number, Q38).
        # Any other word of theirs keeps it (residential.unasked_broker); a chat labelled Broker is the agents'.
        from . import residential as res_broker

        untagged = res_broker.unasked_broker(answer, new_texts, earlier, known=facts, track=track)
    # A no opening their last message with the reason they are done after it ("No thank you, I already rented a shop
    # last month") is not interested whatever the model tagged (the 2e real-model gate, round 10, declines #1: unclear),
    # set before the handover and the rest read the answer, as the model's own tag would be. Past opt_out_from_text's
    # whole-message limit on purpose: the turn still reads the words (a shops chat asks about a second shop first,
    # who_they_are, board T27).
    last_said = next((text for text in reversed(new_texts or ()) if not rules.is_acknowledgement(text)), "")
    declined = answer["opt_out"] == "none" and rules.declines(last_said)
    if declined:
        answer["opt_out"] = rules.NOT_INTERESTED
    settle_handover(answer, earlier, new_texts, shops_chat=shops_chat, invites=invites)
    if shops_chat:
        # Launch review issues 15 and 26: only what is theirs goes on the record, before code adds notes of its own
        # (crm_facts): their own questions as notes, never ours or the prompt's examples; a budget they gave, never our
        # price; a business, never a home they want or a sentence.
        dropped = crm_facts.settle(answer, earlier, new_texts, shop_facts, crm_notes=crm_notes)
        if dropped:
            answer["facts_dropped"] = dropped
    # language names the script the reply is written in (Urdu script is ur, never ur_latin).
    written = rules.guess_language(answer["reply"]) if answer["reply"] else ""
    if written in ("ar", "ur", "hi") and answer["language"] != written:
        answer["language"] = written
    trimmed = []
    if untagged:
        trimmed.append("unasked_broker")  # the broker tag came off, with its words that hand them to a person
    if declined:
        trimmed.append("declines")  # their no with its reason: code's not interested over the model's none
    if shops_chat and residential and answer["reply"] and not answer.get("converted"):
        # The rent flow: the old lead's CRM notes are never quoted, as in a shops chat; the residential facts are ours.
        from . import residential as res_facts

        theirs = "\n".join(
            [
                *(text for author, text in earlier if author in ("customer", "campaign", "agent")), *(new_texts or []),
                res_facts.facts_block("rent", "", (), residential_facts), res_facts.facts_block("sale", "", (), residential_facts),
            ]
        )
        answer["reply"], quoted = lead_history.drop_quoted(answer["reply"], crm_notes, theirs)
        if quoted:
            trimmed.append(lead_history.QUOTED)
    elif shop_guards and answer["reply"] and not answer.get("converted"):
        # Board T56: the prompt's old MATCH example ("For a mobile shop, Type 1 is perfect") went to
        # a vape shop. A recommendation names the customer's own business, or none (never a home: crm_facts).
        business = answer["facts"].get("business_activity") or (facts or {}).get("business_activity") or ""
        business = business if crm_facts.is_business(business) else ""
        answer["reply"], filled = shop_flow.fill_placeholders(answer["reply"], business)
        answer["reply"], renamed = shop_flow.own_business(answer["reply"], business, " ".join(new_texts or []))
        if renamed or filled:
            trimmed.append("business")
        # OLD-LEAD MODE: the old lead's CRM notes are never quoted; a figure only they hold goes before the reply filter would cut
        # it as an amount nobody wrote (eval shops-old-lead: "with a budget around AED 40,000 a year", the notes' "40k").
        # Known: what the chat's people wrote and SHOP FACTS, never the chat's facts, which may hold the notes' own figure
        # (the gate's review: a budget the model took from them on one turn was said back on the next).
        theirs = "\n".join(
            [
                *(text for author, text in earlier if author in ("customer", "campaign", "agent")), *(new_texts or []),
                shops.facts_block(shop_facts),
            ]
        )
        answer["reply"], quoted = lead_history.drop_quoted(answer["reply"], crm_notes, theirs)
        if quoted:
            trimmed.append(lead_history.QUOTED)
        # Launch review issue 5: no fact SHOP FACTS lacks (a shop's building or side, a food business allowed, a
        # sale, the commission, the deposit, another cost); Matloob's commission line (Q24) for any word on it.
        wants_other = needs.of(facts) is not None or needs.detect(new_texts or []) is not None
        # What may be said again: SHOP FACTS, and our campaign's own words ("You may repeat its facts word for word").
        known = "\n".join([shops.facts_block(shop_facts), *(text for author, text in earlier if author == "campaign")])
        cut = claims.settle(answer, new_texts, known=known, office=office_address, options=wants_other)
        if cut:
            trimmed.append(claims.COMMISSION if cut == [claims.COMMISSION] else claims.CUT)
        if claims.HOURLY in cut and hourly_slots(answer, new_texts, earlier, now, closed_dates, taken, booked=booked):
            # Its only words said our slots start on the hour, and went: code's two free slots from their hour instead.
            trimmed.append(HOURLY_SLOTS)
    if agreed or reoffer:
        # They said yes to coming, or turned down nothing of the times we just
        # offered: the times offered now are no new invitation, so they are
        # neither counted nor cut (the first real chat lost its time offer to the
        # cap below after a plain "Yes").
        answer["invited_to_meeting"] = False
    elif invites >= 2:
        # Invited twice and refused: no third invitation, in any words. In a shops chat that means its slots too,
        # in the model's words or code's, which name no visit ("I can hold a slot for you today at 4:00 PM or
        # 6:00 PM — which is better?"), and offers.fix_times would only have put them right: unless they ask to
        # come or see now, or the time is one they named (offers.pushes_visit).
        answer["invited_to_meeting"] = False
        if answer["reply"]:
            pushed = None
            if shops_chat and now is not None and not _VISIT_WORDS.search(" ".join(new_texts or [])):
                theirs = offers.theirs_from([*[text for author, text in earlier if author == "customer"][-6:], *(new_texts or [])], now)
                pushed = lambda sentence: offers.pushes_visit(sentence, theirs)  # noqa: E731
            answer["reply"], dropped = filters.drop_invitations(answer["reply"], also=pushed)
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
        # question of ours, one of the build pack's fixed answers or an apology (launch
        # chat 114's second reply lost its "Sorry for the confusion.": people.is_apology).
        answer["reply"], repeated = filters.drop_repeats(
            answer["reply"], [text for author, text in earlier if author == "assistant"],
            keep=lambda sentence: (
                shops.is_fixed_line(sentence) or claims.is_code_line(sentence) or people.is_apology(sentence) or sales.is_fixed_line(sentence)
                or (residential and _residential_line(sentence))
            ),
        )
        if repeated:
            trimmed.append("repeat")
    if shop_guards and answer["reply"] and not answer.get("converted") and claims.drop_table_repeat(
        answer, [text for author, text in earlier if author == "assistant"], new_texts, shop_facts
    ):
        # Launch review issue 16: the size and price table our messages gave already, said again unasked.
        trimmed.append(claims.TABLE)
    if shop_guards and answer["reply"] and not answer.get("converted"):
        # No stock claimed on the shops track either (the first mixed campaign, 2026-10-19, chat 49958: "The Type 3 large
        # shops are available in all clusters including China" went out; there is no inventory, D13): claims.claims_stock,
        # sentence by sentence; the shops' own fixed lines never pass through it.
        sentences = filters.split_sentences(answer["reply"])
        kept = [s for s in sentences if shops.is_fixed_line(s) or not claims.claims_stock(s)]
        if len(kept) != len(sentences):
            answer["reply"] = " ".join(kept)
            trimmed.append("availability")
    plain_shops = (
        shop_guards and answer["reply"] and not answer.get("converted") and answer["opt_out"] == "none"
        and not answer["handover"]["needed"] and not agreed
    )
    if plain_shops and licence_first(answer, facts or {}, earlier, new_texts, now, invites=invites):
        trimmed.append("licence_first")
    elif plain_shops and (reoffer or invites < 2) and discovery_first(answer, facts or {}, earlier, new_texts, invites, agreed=agreed, now=now):
        trimmed.append("discovery")
    if shops_chat and slots and answer["reply"] and not answer.get("converted"):
        # The build pack's assumptive close: never "when are you free?", always two slots.
        answer["reply"], rewritten = filters.offer_slots(answer["reply"], shops.slot_offer(answer["language"], slots, now))
        if rewritten:
            trimmed.append("slots")
            # Code's pair closes the message: the model's own pair beside it goes (the first mixed campaign, 2026-10-19,
            # chat 49818: "I can offer 3:00 PM or 4:00 PM today" and then code's "3:00 PM or 5:00 PM" in one message).
            timed = {sentence for sentence, _, _ in offers.offered(answer["reply"], now)} if now is not None else set()
            line = shops.slot_offer(answer["language"], slots, now)
            timed.discard(line)
            if timed:
                answer["reply"] = " ".join(s for s in filters.split_sentences(answer["reply"]) if s not in timed)
                trimmed.append(offers.TIMES)
            if len(answer["reply"]) > filters.REPLY_MAX:
                # Over the limit with code's pair last, clean_reply's cut would take the pair: the model's sentences go
                # instead, its statements from the last one up and then its questions, never the pair (the 2e real-model
                # gate, round 10: shops-res-invitation-two-slots #1 was 698 characters, the charges paragraph plus the
                # invitation, and "offers 0 exact time(s)" went out).
                from . import residential as res_fit

                answer["reply"] = res_fit._fit(answer["reply"], [line])
                trimmed.append("length")
            if not (agreed or reoffer):
                answer["invited_to_meeting"] = True  # code's two slots are an invitation (launch review issue 24)
    if shops_chat and slots and location_invitation(
        answer, facts or {}, new_texts, slots, now, agreed=agreed, reoffer=reoffer, office_address=office_address,
        before="\n".join([text for author, text in earlier if author == "assistant"][-3:]),
    ):
        # Where we are, asked by a known end user, answered with no invitation: code's two slots close it (the launch gate's
        # eval shops-location-counted-81).
        trimmed.append("location_invitation")
    # Batch 2e: the rent track's invitation is the model's words with code's slots (spec §2.1 step 4, §2.5), as a shops
    # chat's: its own times checked and an offer of two counted as the invitation it is (the 2e real-model gate, round 1:
    # shops-res-invitation-two-slots offered "today at 3:00 PM or 4:00 PM" with invited_to_meeting false, both runs). The
    # sale track's meeting is sales.settle's (the call slots).
    rent_slots = shops_chat and residential and track in (tracks.RENT, tracks.UNKNOWN)
    if (shop_guards or rent_slots) and answer["reply"] and not answer.get("converted") and now is not None:
        # Launch review issue 17: the model's own times, an hour ahead and an hour apart at least, never past or taken;
        # a time they named stands (unless it has passed), and so does any time ahead when they want to come now.
        lately = [text for author, text in earlier if author == "customer"][-6:]
        theirs = offers.theirs_from([*lately, *(new_texts or [])], now)
        said = " ".join(new_texts or []).replace("’", "'")
        soon = bool(_WALK_IN_WORDS.search(said) or _COME_NOW.search(said))
        before = "\n".join([text for author, text in earlier if author == "assistant"][-3:])
        if offers.fix_times(answer, now, closed_dates, taken, theirs=theirs, booked=booked, soon=soon, before=before):
            trimmed.append(offers.TIMES)
        if invites < 2 or agreed or reoffer:
            offers.count_invitation(answer, agreed=agreed, reoffer=reoffer)
    # Last, so neither the no-repeat guard nor the slots rewrite takes the pointer out again.
    pointed = point_to_location(answer, new_texts, address_sent)
    if pointed:
        answer["pointed"] = pointed
    if trimmed:
        # After settle_handover's own (COLLEAGUE_REPLY), never in its place.
        answer["trimmed"] = [*(answer.get("trimmed") or []), *trimmed]
        if not answer["reply"]:
            answer["send"] = False
    handover = answer["handover"]
    if handover["needed"] and handover["reason"] == BROKER and not broker_labelled:
        answer["broker"] = True
        if playbook == lane.IC_SHOPS:
            # The shops build pack's own hand-off line, never the model's words.
            answer["converted"] = "broker"
    return answer


def shop_confirmation(shops_chat: bool, decision, merged: dict) -> bool:
    """The booking message is the build pack's shops confirmation (shop type, the drive to the shops, the licence to bring):
    the shop track's only, for a customer who wants no other thing (live and in the eval). Batch 2e review: a mixed-template
    chat whose need nobody knew yet was told a shop type, the drive to the shops, its trade licence and an agent's name."""
    return shops_chat and decision is not None and decision.track == tracks.SHOP and needs.of(merged) is None


def broker_holds(answer: dict) -> bool:
    """A broker's booking is none (Q11: the broker line, the Broker label and a pause; batch 2e review: "Book 6 pm for my
    client Ahmed Khan" was confirmed under the client's name, with the pin and the booked alert, and the broker line never
    went): the time asked for stays a tentative with their words, for our agent. Live and in the eval, right after settle.
    True when it changed the answer (the caller then drops the time it checked: nothing is booked)."""
    handover = answer["handover"]
    if not (answer.get("broker") or (handover["needed"] and handover["reason"] == BROKER)):
        return False
    proposal = answer["appointment"]
    if proposal["action"] not in ("confirm", "reschedule"):
        return False
    proposal["action"] = "tentative"
    answer["broker_held"] = True
    return True


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
    need_segment: str = "",
    residential: bool = False,
    places=calls.OFFICE_ONLY,
    call_taken=(),
    pack: bool = False,
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
    (script.has_script). ``need_segment``: a shops customer who wants no shop to rent
    (needs.py; said now, or known) is in this segment whenever the model says "other", so
    their booking is never _shape's "holding" (the owner's rule: they are invited and booked
    like anyone). ``residential``: a rent, sale or not-known chat of the International City
    campaign (batch 2e): RES_SCHEMA and its own prompt cache key (the caller passes RES_SYSTEM),
    its segment forced by the track (``need_segment``). ``places`` / ``call_taken``: a buyer's
    call on the sale track (batch 2e slice C), which _shape leaves a confirm and check_proposal
    books in the call pool.

    A slot another client has is offered around by code (``answer["slot_taken"]``,
    shops.slot_taken with ``alternatives``) when the answer keeps the visit
    tentative at it (taken_tentative), or when a confirm refused as taken was
    corrected with a reply that does not name the two free starts; never where
    code would not book the visit itself (_code_may_act), and never while a person
    has the chat (_run_claimed).
    """
    codes = codes if codes is not None else []
    alternatives = alternatives if alternatives is not None else []
    answer_schema = schema.schema_for(shops_chat, residential)
    if residential:
        cache_key = openai_client.PACK_CACHE_KEY if pack else openai_client.RES_CACHE_KEY  # the packs' prompt is its own (round 17)
    else:
        cache_key = openai_client.SHOPS_CACHE_KEY if shops_chat else openai_client.CACHE_KEY
    # RES_SCHEMA's answer is the longest (openai_client.RES_MAX_TOKENS); the other playbooks' requests stay as they were.
    limit = {"max_tokens": openai_client.RES_MAX_TOKENS} if residential else {}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": context}]
    completions = []
    first = openai_client.complete_json(messages, answer_schema, user=user, deadline=deadline, cache_key=cache_key, **limit)
    completions.append(first)

    def shaped(data) -> dict:
        normal = schema.normalize(data, shops=shops_chat, residential=residential)
        if need_segment and normal["segment"] == "other":
            normal["segment"] = need_segment
        # A booked sales call moved stays a call (place null or "office" unless they ask for the office: sales.keep_call).
        sales.keep_call(normal["appointment"], appointment, said, places)
        return _shape(normal, places)

    answer = shaped(first.data)

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
            again = openai_client.complete_json(asked, answer_schema, user=user, deadline=deadline, cache_key=cache_key, **limit)
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
        fixed = schema.normalize(again.data, shops=shops_chat, residential=residential)
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
            said=said, places=places, call_taken=call_taken,
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
    second = openai_client.complete_json(messages, answer_schema, user=user, deadline=deadline, cache_key=cache_key, **limit)
    completions.append(second)
    answer = shaped(second.data)
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
    then?", "my duty finishes at 5 pm, then I will come"), nor one put off
    ("Tomorrow at 5 pm, I will let you know"), an
    owner's day and hour with no place (a viewing at their property, or our
    office? check_proposal's no_place), a call, someone outside our segments or a
    fixed line. Never while a person has the chat (``handed_over``) or after a
    colleague's message (``agent_last``): their plan is not overridden. Returns
    the checked start, with the answer changed to a confirm; else None, untouched.

    A tentative on their day with no hour, or at the slot beside theirs, is their own
    hour all the same when the reply offered only the slots either side of it
    (passed_over_hour: "Can I come today at 4:30?" got "The closest available slot is
    4:00 PM or 5:00 PM" and a tentative for today with no hour, in every run of the
    deployed gate's eval shops-gate-half-hour).
    """
    proposal = answer["appointment"]
    if proposal["action"] != "tentative" or not proposal.get("date"):
        return None
    # A fixed line, someone outside our segments, a handover in this answer or a call (_code_may_act).
    if proposal.get("place") not in (None, "office") or not _code_may_act(answer, said):
        return None
    # Handed to a person earlier (a call, an owner's viewing, someone abroad), or a colleague's plan: theirs to agree, not ours.
    if handed_over or agent_last:
        return None
    if hours.no_promise(said) or rules.mentions_deferral(said):
        return None
    day, at = hours.parse_date(proposal["date"]), hours.parse_time(proposal.get("time"))
    days, times = hours.named_days(said, now), hours.named_times(said)
    # One day and one hour: "Wednesday at 5 or 6" or "Tuesday or Wednesday at 5" is a choice, not a booking.
    one_day = len({value for value in days if value - dt.timedelta(days=7) not in days}) == 1
    if day is None or day not in days or not one_day:
        return None
    upgraded = {**proposal, "action": "confirm"}
    if at is None or times != {at}:
        # No hour of the model's, or one beside theirs: their own, when the reply offered only the slots either side of it,
        # with their own words for the agents (as own_time), never the model's (which may name the time it picked).
        at = passed_over_hour(answer, said, day, at, now)
        if at is None:
            return None
        upgraded.update(time=f"{at:%H:%M}", customer_words=(said or "").strip()[:255] or proposal.get("customer_words"))
    # Checked with the model's own place: an owner's time with none is refused (no_place).
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


def passed_over_hour(answer: dict, said: str, day: dt.date, model_at: dt.time | None, now) -> dt.time | None:
    """The one hour of their own that a tentative on their day (``day``) left out (``model_at`` None) or put beside it,
    when the reply offers only the slots either side of it, or the nearest ones on one side of it; else None
    (upgrade_exact_time books it when it is free).

    FREE SLOTS lists starts an hour apart, so a half hour they ask for looks taken to the model: the deployed gate's eval
    shops-gate-half-hour answered "Can I come today at 4:30?" with "The closest available slot is 4:00 PM or 5:00 PM" (or
    "4:00 PM today" alone) and a tentative for today with no hour, in every run. Their hour is the one their words say as
    an hour (hours.spoken_times: never a bare number, "slot 2"); every other start the reply names (offers.offered: their
    own may be named, as taken) is on their day within half an hour of it, and the model's own hour, if any, is beside it
    too. So the hour of something else in their words is never read as the visit's: "My shop closes at 10, I can come
    tomorrow" answered with tomorrow's 11:00 AM or 5:00 PM offers more than the slots beside 10.

    A reply that says itself why their half hour was passed over, our slots starting on the hour (claims.says_hourly: never
    true, cut by claims.settle after this), makes their own hour the visit's whatever else it offers on their day, or nothing:
    the 2e real-model gate, round 11 (shops-gate-half-hour #1), "viewings start on the hour. I can hold a slot for you at
    4:00 PM or 6:00 PM", a shape the rules below read as no passing-over. Their time on the hour has no such reason."""
    spoken = hours.spoken_times(said)
    if len(spoken) != 1:
        return None
    theirs = next(iter(spoken))
    start = dt.datetime.combine(day, theirs, tzinfo=hours.DUBAI)
    if model_at is not None and abs(dt.datetime.combine(day, model_at, tzinfo=hours.DUBAI) - start) > hours.SLOT:
        return None
    others = {
        dt.datetime.combine(on, at, tzinfo=hours.DUBAI)
        for _, days, times in offers.offered(answer["reply"] or "", now)
        for on in days
        for at in times
    } - {start}
    if any(slot.date() != day for slot in others):
        return None
    if theirs.minute and claims.says_hourly(answer["reply"] or ""):
        return theirs
    if not others:
        return None
    if all(abs(slot - start) <= hours.SLOT for slot in others):
        return theirs
    # ... or the nearest slots on one side of it, the first beside theirs and each next an hour on at most: the 2e real-model
    # gate (round 1, shops-gate-half-hour #2) answered "Can I come today at 4:30?" with "The closest available slot is 4:00
    # PM. I can hold that for you or 3:00 PM if you prefer." and a tentative for today with no hour. A slot on the other side
    # an hour off ("4:00 PM or 6:00 PM") is no such offer, nor one after a gap.
    ordered = sorted(others, key=lambda slot: abs(slot - start))
    one_side = len({slot < start for slot in ordered}) == 1
    steps = all(abs(later - sooner) <= hours.MIN_GAP for sooner, later in zip(ordered, ordered[1:]))
    if one_side and steps and abs(ordered[0] - start) <= hours.SLOT:
        return theirs
    return None


def own_time(
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
    grounding=None,
    handed_over: bool = False,
    agent_last: bool = False,
) -> dt.datetime | None:
    """A shops visit the model confirmed at another time than the one exact day and hour the customer named in plain
    words: theirs is booked instead, when it is free and inside hours (live and in the eval, right after the model). The
    launch gate's eval shops-not-a-shop-booked: "4:30 PM today is fine" was confirmed at 4:00 PM ("Our office slots start
    on the hour, so I booked you for 4:00 PM today": they are every 30 minutes), and unasked_confirm then offered 4:30 PM
    or 6:30 PM instead of booking the 4:30 PM they gave.

    Only the model's confirm (``when``; a tentative at another time stays the model's, and T18, upgrade_exact_time, books
    one at their own time), at an office visit, where code acts on a visit itself (_code_may_act), with no person on the
    chat, no colleague's plan, no taken slot and no move of a confirmed visit. Their words name one day (hours.named_days)
    and one hour said as an hour (hours.spoken_times: "4:30 PM", "at 6", "kal saade 5 baje", "at five"; never a bare
    number: "Tomorrow slot 2", "I am in Al Nahda 2", "we are 2"; two readings, or none, leave the model's), as a plan to
    come at it (hours.no_promise: no hedge, condition, "no", range, question whether we are open, nor the hour of
    something else they come after, "I finish work at 6, I can come after that"; nor a deferral). The model's time stands
    when it is on their day and theirs or taken from us (their_time: "Tomorrow slot 2" after our "tomorrow at 11:00 AM or
    1:00 PM", "the first one", an hour they said before; ``words``, ``our_last`` and ``ours`` as there). The launch gate's
    review: "Tomorrow slot 2" was booked at 2:00 PM, "Tomorrow I finish work at 6, I can come after that" at 6:00 PM.
    Returns their checked start, the answer changed to a confirm at it (``answer["own_time"]`` keeps both times for the
    turn's log); else None, untouched."""
    proposal = answer["appointment"]
    if when is None or effective_action(proposal["action"], appointment) != "confirm" or proposal.get("place") not in (None, "office"):
        return None
    if handed_over or agent_last or answer.get("slot_taken") or not _code_may_act(answer, said):
        return None
    if appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED:
        return None  # a move stays the model's, as in unasked_confirm
    model_start = when
    if hours.no_promise(said) or rules.mentions_deferral(said):
        return None
    named = hours.named_days(said, now)
    days = {day for day in named if day - dt.timedelta(days=7) not in named}
    times = hours.spoken_times(said)
    if len(days) != 1 or len(times) != 1:
        return None
    day, at = next(iter(days)), next(iter(times))
    if dt.datetime.combine(day, at, tzinfo=hours.DUBAI) == model_start:
        return None
    if model_start.astimezone(hours.DUBAI).date() == day and their_time(
        model_start, said=said, words=words, our_last=our_last, ours=ours, now=now
    ):
        return None  # on their day, a time they gave or took from us: the model's reading stands
    theirs = {
        **proposal, "action": "confirm", "place": "office", "date": f"{day:%Y-%m-%d}", "time": f"{at:%H:%M}",
        # Their own words for the agents, never the model's (which may name the time it picked).
        "customer_words": (said or "").strip()[:255] or proposal.get("customer_words"),
    }
    try:
        start = check_proposal(theirs, appointment, now, closed_dates, grounding=grounding, segment=answer["segment"], taken=taken, said=said)
    except hours.SlotError:
        return None
    if start is None:
        return None
    answer["appointment"] = theirs
    answer["own_time"] = {"start": start, "model": model_start}
    return start


# The playbooks in which a same-day window of the customer's own is booked (launch review issue 6; a general
# chat's prompt reads only an exact hour as a booking).
WINDOW_PLAYBOOKS = (lane.IC_SHOPS,)


def book_window(
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
    playbook: str = lane.GENERAL,
) -> dt.datetime | None:
    """A shops customer's own window of time today ("I will come at 12-12:30", chat 96's voice note "barah saadhay
    barah baje ja ke check kar loon ga"), which the model kept tentative: booked at the window's start, or the
    first free half hour inside it, as T18 books one exact hour (upgrade_exact_time; live and in the eval).

    Only where T18 would act (an office visit kept tentative, our segments, no fixed line, handover or call, no
    person on the chat, no colleague's plan), for a window today (no other day named) that is still ahead, said
    as a plan to come (hours.window_promise: no hedge, condition, "no", deferral or "are you open?"), and never
    over a confirmed visit. Returns the checked start with the answer changed to a confirm; else None, untouched."""
    if playbook not in WINDOW_PLAYBOOKS:
        return None
    proposal = answer["appointment"]
    if proposal["action"] != "tentative" or proposal.get("place") not in (None, "office") or answer.get("slot_taken"):
        return None
    if not _code_may_act(answer, said) or handed_over or agent_last:
        return None
    if appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED:
        return None
    if not hours.window_promise(said) or rules.mentions_deferral(said):
        return None
    window = hours.named_window(said)
    if window is None:
        return None
    today = hours.now_dubai(now).date()
    named = hours.named_days(said, now)
    days = {day for day in named if day - dt.timedelta(days=7) not in named}
    if days and days != {today}:
        return None  # another day: the model's to offer slots for
    start = dt.datetime.combine(today, window[0], tzinfo=hours.DUBAI)
    end = dt.datetime.combine(today, window[1], tzinfo=hours.DUBAI)
    candidates = [start, *[slot for slot in hours.slot_grid(today) if start < slot <= end]]
    for candidate in candidates:
        if candidate < now - hours.WALK_IN_GRACE:
            continue
        upgraded = {**proposal, "action": "confirm", "place": "office", "date": f"{today:%Y-%m-%d}", "time": f"{candidate:%H:%M}"}
        try:
            when = check_proposal(upgraded, appointment, now, closed_dates, grounding=grounding, segment=answer["segment"], taken=taken, said=said)
        except hours.SlotError:
            continue
        if when is None:
            continue
        answer["appointment"] = upgraded
        answer.pop("unasked", None)
        answer["window"] = {"start": window[0].strftime("%H:%M"), "end": window[1].strftime("%H:%M")}
        return when
    return None


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


def plain_yes(texts) -> bool:
    """All they said is a plain yes ("Yes", "ok", "haan ji", "Yes" and a thumbs up): every message of the burst is text,
    and acknowledgements aside each one is rules.is_acceptance (an "ok" alone is one). ``texts``: the burst, a message
    that is not text as ''."""
    words = [str(text or "").strip() for text in texts or ()]
    if not words or not all(words):
        return False
    said = [text for text in words if not rules.is_acknowledgement(text)]
    return all(rules.is_acceptance(text) for text in said) if said else any(rules.is_acceptance(text) for text in words)


def nudge_yes(
    answer: dict,
    *,
    our_last: str,
    texts,
    appointment,
    when,
    still_invalid: bool,
    said: str,
    now,
    closed_dates=(),
    taken=(),
    handed_over: bool = False,
) -> bool:
    """A plain yes to our nudge (nudges.is_nudge: "shall I hold a slot for you to see the options today or tomorrow?",
    "Shall I book you for this evening?"): code's two free slots for it (shops.yes_slots, for the day and the part of it
    the nudge named), which model_step sends as the step (``answer["nudge_yes"]``), never a time of the model's held
    for them. The launch gate's eval shops-options-nudge-yes: "Great, I held the 3:00 PM slot for you today ..." in both
    runs, a time nobody named that own_offer then kept as no time at all, so nothing was held where the reply said it
    was (the follow-ups package's open item: a plain yes to a nudge gets two free slots from code). Live and in the eval,
    after own_offer. Not with a visit open, a booking made or a time refused, a person on the chat, a confirm
    unasked_confirm already turned into slots, a taken slot, an opt-out, or where code would not act on a visit itself
    (_code_may_act). A nudge that named two exact starts ("I can hold a slot at 4:00 PM or 6:00 PM.", the morning one)
    is asked about those two again while both may still be offered (offers.offered_again; ``answer["nudge_yes"]["again"]``:
    in other words), never a fresh pair (the launch gate's review: a "Yes" to 4 or 6 was asked to choose 3 or 5). True
    when the slots were set."""
    if when is not None or still_invalid or appointment is not None or handed_over:
        return False
    if answer.get("unasked") or answer.get("slot_taken") or answer["opt_out"] != "none" or not _code_may_act(answer, said):
        return False
    if not nudges.is_nudge(our_last) or not plain_yes(texts):
        return False
    slots = offers.offered_again(our_last, now, closed_dates, taken)
    if slots:
        answer["nudge_yes"] = {"slots": slots, "again": True}
        return True
    slots = shops.yes_slots(said, our_last, now, closed_dates, taken)
    if not slots:
        return False
    answer["nudge_yes"] = {"slots": slots}
    return True


# Who the customer is (launch 2026-10-15) -----------------------------------------------------------
# 13 of the first 32 shops customers wanted something else (a studio, a room, a flat, to buy) or never
# asked about a shop. Matloob's rule the same day: no customer is ever lost (assistant/needs.py).

WHO_NOT_A_SHOP = needs.CONVERTED
WHO_RENTED = "rented"


def need_texts(items, heard: dict | None = None) -> list[str]:
    """The customer's own words in these messages, a tap by its label and a voice note by what it says:
    what needs.detect reads."""
    out = []
    for item in items:
        label = _tap_label(item)
        if label:
            out.append(label)
        elif item.kind == "audio":
            out.append((heard or {}).get(item.pk) or "")
        else:
            out.append(item.body or "")
    return [text for text in out if text.strip()]


def not_lost_for(kind: str, texts) -> bool:
    """A shops opt-out code found in the burst ("not interested", "wrong number") that is no opt-out:
    the same burst says what they want instead ("I need a studio" + "not interested", "Wrong number, I
    am looking for a flat"), and no customer is ever lost (the owner's rule). A STOP is always one;
    a wrong number with no other want named ("Wrong number, I never asked for a shop") stays one: it
    may be another person. Live and in the eval (code_first)."""
    if kind not in (rules.NOT_INTERESTED, rules.WRONG_NUMBER):
        return False
    need = needs.detect(texts)
    return need is not None and (kind == rules.NOT_INTERESTED or need.kind != needs.NEVER_ASKED)


# The only handovers of a chat that wants no shop to rent (the owner's rule, 2026-10-15): a person or a call asked
# for, a complaint, a broker. Any other the model gives (a visa question, a photo sent, a price insisted on) is no pause.
NEED_HANDOVERS = ("customer_asked_human", "call_requested", "complaint_or_upset", BROKER)


def untag_need(answer: dict, known: dict, texts) -> needs.Need | None:
    """A shops answer, right after the model (live and in the eval): what the customer wants instead of
    a shop to rent, else None, with the model's handover for it taken off. The owner's rule
    (2026-10-15): such a chat is tagged and alerted, never handed over or paused, unless they ask for a
    person or a call, complain, or are a broker (NEED_HANDOVERS). Their own words in this burst decide
    first (needs.detect), then the model's tag (schema.NOT_A_SHOP_REASONS, kept as
    ``answer["need_tag"]``). Any other handover goes as well in a chat that wants no shop (said now, or
    known): live, chats 105, 114 and 136 were handed over as "unclear" for a studio or a room, with nobody
    to answer them for hours, and review 2d found a buyer's golden-visa question and a seller's photo
    (legal_visa_licence_contract, media_received) paused the chat the same way. The reason taken off is
    kept (``answer["need_dropped"]``, but for "unclear") for the team's alert (_wanted_alert)."""
    handover = answer["handover"]
    now = needs.detect(texts)
    tagged = None
    # The chat's own want, unless they ask for a shop now (who_they_are then forgets it): a shop customer's handover stays.
    known_need = needs.of(known) if now is None and not needs.wants_a_shop(texts) else None
    if handover["needed"] and handover["reason"] in needs.REASON_KINDS:
        tagged = needs.from_reason(handover["reason"], answer["facts"])
        answer["need_tag"] = handover["reason"]
        answer["handover"] = {"needed": False, "reason": None}
    elif handover["needed"] and handover["reason"] not in NEED_HANDOVERS and (now is not None or known_need is not None):
        if handover["reason"] and handover["reason"] != "unclear":
            answer["need_dropped"] = handover["reason"]
        answer["handover"] = {"needed": False, "reason": None}
    return now or tagged


# An invitation of code's own past this many is the owner's line with no new slots (review 2d: chat 42's buyer got the
# full invitation four times, its invites counted 2, 3, 4): the settle's own limit (no third invitation).
NOT_A_SHOP_INVITES = 2


def _not_a_shop_line(answer: dict, need: needs.Need, slots, *, sorry: bool, ask: bool = True) -> None:
    """The answer becomes the owner's line (not_a_shop_text): code's words, an invitation with our location.
    ``ask`` False: they were invited already, so the line goes with no slots and no question for a time, and
    counts as no new invitation."""
    invite = ask or bool(slots)
    answer["converted"] = needs.CONVERTED
    answer["not_a_shop"] = {
        "kind": need.kind, "noun": need.noun, "denies": need.denies, "sorry": bool(sorry), "slots": list(slots or []) if invite else [],
        "ask": invite,
    }
    answer["invited_to_meeting"] = invite
    answer["share_office_location"] = True
    answer["send"] = True
    answer.pop("shop_step", None)


def not_a_shop_text(spec: dict, language: str, now) -> str:
    """What the line says (live and in the eval): thanks (and sorry), the options for what they want
    across Dubai, "Visit our office and we'll give you the best option." and two free slots, or the
    question for a day and time when none is free (none at all when they were invited already: ``ask``
    False). Code adds our location (engine, outgoing)."""
    need = needs.Need(spec.get("kind") or needs.NEVER_ASKED, spec.get("noun") or "", bool(spec.get("denies")))
    slots = list(spec.get("slots") or [])
    if slots:
        offer = shops.slot_offer(language, slots, now)
    else:
        offer = rules.line("ask_time", language) if spec.get("ask", True) else ""
    if spec.get("price"):
        return shop_buyer.price_line(spec, language, offer)  # Q43: a shop buyer's price question (shop_buyer.py)
    return needs.line(language, need, offer, sorry=bool(spec.get("sorry")))


def who_they_are(
    answer: dict,
    known: dict,
    texts,
    need: needs.Need | None,
    *,
    when=None,
    still_invalid: bool = False,
    appointment=None,
    quiet: bool = False,
    slots=(),
    misread: bool = False,
    shop_facts: str = "",
    invites: int = 0,
    office_address: str = "",
) -> str:
    """A shops answer after settle (live and in the eval, with the same values): what the customer is.
    Returns WHO_NOT_A_SHOP or WHO_RENTED when code's words go instead of the model's, else ''.
    ``office_address``: our office's, whose words and unit ("Shop 20") needs.drop_shop_pitch never reads as shop talk.

    - Someone who wants no shop to rent (``need``: untag_need's, said now; or the chat's own,
      facts.need): never lost. Their want is recorded (facts.need, facts.wanted; a home as
      property_type, never as business_activity; intent buy or sell), and a "not interested" said with
      it is no decline; a want less specific than the chat's ("Not shops" after "a studio") changes
      nothing (needs.replaces). The first time (or when the model would have lost them), while nothing
      must go instead (a person has the chat, a booking or a time to refuse, a fixed line, a handover
      that stays, an open visit, a call asked for in their own words: people.settle's), the reply is
      the owner's line with two free ``slots`` and our location (not_a_shop_text); ``misread``: we
      talked shops to them already, so the line says sorry too. Past ``invites`` NOT_A_SHOP_INVITES
      it goes with no slots (no third invitation). Later, the model's own words go without any word of
      shop types, the for-yourself question, the drive, their business or licence (a home), or renting
      (a buyer) (needs.drop_shop_pitch), or the line again, with no new slots, when nothing is left.
    - Someone who says they already rented a shop elsewhere ("we got one", "found one already"), the
      first time: facts.already_rented, never a "not interested" yet, and the build pack's
      congratulation with its second-shop question (rules "rented_second_shop"), whose no then closes
      the lead as already rented (shops_rule's RENTED_NO). Live, chat 63's "we got one" got the
      shop types list instead. A burst that asks for another shop ("We already have a shop, need one
      more": needs.wants_another) records none, and the model's facts.already_rented for it goes.
    - Every shops reply: no sentence saying our shops are only for rent or not for sale, unless SHOP
      FACTS (``shop_facts``) speaks of a sale (needs.drop_sale_claims): chat 42, a buyer, was told so.
    """
    known = known or {}
    facts = answer["facts"]
    had = needs.of(known)
    trimmed = list(answer.get("trimmed") or [])
    if answer["reply"] and not answer.get("converted"):
        answer["reply"], cut = needs.drop_sale_claims(answer["reply"], shop_facts)
        if cut:
            trimmed.append("sale_claim")
    # A "not interested" said with what they want instead is no decline (chat 42: "Sorry nobody / I want to purchase
    # shop"), and the model's "wrong number" for "I never asked about a shop" none either: a plain wrong number is
    # code's before any model (rules.opt_out_from_text, not_lost_for).
    lost = need is not None and answer["opt_out"] in (rules.NOT_INTERESTED, rules.WRONG_NUMBER)
    if lost:
        answer["opt_out"] = "none"
    done = ""
    if need is not None and not need.noun and need.kind in (needs.BUY, needs.SELL):
        # "To buy", answering our shops template: what they buy is what the chat is about ("to buy a shop").
        named = needs.noun_of(facts.get("property_type") or known.get("property_type"))
        if named:
            need = needs.Need(need.kind, named, need.denies)
    if need is None and had is not None and had.kind in (needs.HOME, needs.NEVER_ASKED, needs.OTHER) and needs.wants_a_shop(texts):
        # They ask for a shop after all ("No, I want a SHOP for my salon"): the chat read them wrong, and its want is
        # forgotten, so no shop step stays blocked for good (review 2d; engine._apply drops the keys).
        forget = [needs.NEED, needs.WANTED]
        if needs.is_home_type(known.get("property_type")) and not facts.get("property_type"):
            forget.append("property_type")
        answer["forget"] = forget
        had = None
    # The chat's want: the one said now, unless it is less specific than the one the chat knows (needs.replaces).
    chat_need = need if needs.replaces(need, had) else (had or need)
    # A call they ask for in their own words is people.settle's (a handover with code's call line), never the
    # owner's line over it (review 2d: "I need a studio flat, please call me" lost the call).
    called = people.asks_for_call(" ".join(str(text or "") for text in texts or ()))
    if facts.get("already_rented") is True and known.get("already_rented") is not True and needs.wants_another(texts):
        # "We already have a shop, need one more" asks for another shop of ours: no shop rented elsewhere is recorded, as
        # needs.rented_already reads it (the launch gate's eval shops-review-rented-one-more: the model set it in both runs).
        # Recorded, their next "No, ..." would close the lead as already rented (_shops_rule_for's rented_open), and every
        # follow-up would hold (followups.holds).
        facts["already_rented"] = None
    if chat_need is not None:
        merged = {**known, **{key: value for key, value in facts.items() if value not in (None, "", [])}}
        if need is not None and needs.replaces(need, had) and (had is None or (need.kind, need.noun) != (had.kind, had.noun)):
            facts[needs.NEED] = need.kind
            facts[needs.WANTED] = needs.summary(need, merged)
            answer["need_words"] = " ".join(texts or ())[:200]
        activity = facts.get("business_activity")
        if chat_need.kind in (needs.HOME, needs.NEVER_ASKED) or (activity and needs.detect([activity]) is not None):
            facts["business_activity"] = None  # a studio or a room is no business (chats 44, 49, 57, 68 wrote it so)
        if chat_need.kind == needs.HOME and chat_need.noun and not needs.is_home_type(facts.get("property_type") or known.get("property_type")):
            facts["property_type"] = needs.property_words(chat_need.noun)
        if chat_need.kind in (needs.BUY, needs.SELL):
            facts["intent"] = chat_need.kind
        plain = not (
            quiet or when is not None or still_invalid or answer.get("converted") or answer.get("slot_taken") or answer.get("broker")
            or answer["handover"]["needed"] or appointment is not None or answer["opt_out"] != "none" or called
        )
        if need is not None and (had is None or lost) and plain:
            # The first time with all its slots; a "no" the model read in a want said again, past two invitations, with none.
            again = had is not None and invites >= NOT_A_SHOP_INVITES
            _not_a_shop_line(answer, chat_need, () if again else slots, sorry=need.denies or misread, ask=not again)
            done = WHO_NOT_A_SHOP
        elif answer["send"] and answer["reply"] and not answer.get("converted"):
            answer["reply"], cut = needs.drop_shop_pitch(answer["reply"], chat_need, office_address)
            if cut:
                trimmed.append("shop_pitch")
                if not answer["reply"] and plain:
                    # Nothing left: the owner's line again, with no new slots once they were invited.
                    _not_a_shop_line(answer, chat_need, () if invites else slots, sorry=misread, ask=not invites)
                    done = WHO_NOT_A_SHOP
    elif needs.rented_already(texts) and known.get("already_rented") is not True:
        facts["already_rented"] = True
        if answer["opt_out"] == rules.NOT_INTERESTED:
            answer["opt_out"] = "none"  # asked about a second shop first (board T27); its no closes the lead
        plain = not (
            quiet or when is not None or still_invalid or answer.get("converted") or answer.get("slot_taken") or answer.get("broker")
            or answer["handover"]["needed"] or answer["opt_out"] != "none" or called
        )
        if plain:
            answer["converted"] = needs.RENTED_LINE
            answer["invited_to_meeting"] = answer["share_office_location"] = False
            answer["send"] = True
            answer.pop("shop_step", None)
            done = WHO_RENTED
    if trimmed:
        answer["trimmed"] = trimmed
        if not answer["reply"] and not answer.get("converted"):
            answer["send"] = False
    return done


def bare_need_reply(answer: dict, need, slots=(), *, invites: int = 0, misread: bool = False, plain: bool = True) -> bool:
    """A shops answer to someone who wants no shop to rent (``need``), after who_they_are and people.settle cut its words
    (shop talk, "please contact Manhial"), live and in the eval: when all that is left is an apology or a filler, or
    nothing ("Sorry for the confusion.", "I see, a studio."), the owner's line goes instead, with no new slots once they
    were invited (``invites``). Review 2d: chat 114's "I did not say any thing about shop.i just requesting only apartment
    rent" got "Sorry for the confusion." alone. ``plain``: no person on the chat, no booking or time to refuse, no open
    visit. Never over code's two free slots (unasked_confirm's or nudge_yes's: model_step sends them instead of the words
    the cuts emptied; the launch gate's "Our office slots start on the hour, so I booked you for 4:00 PM today." went that
    way). True when it changed the answer."""
    if need is None or not plain or not answer.get("trimmed"):
        return False
    if answer.get("converted") or answer["opt_out"] != "none" or answer["handover"]["needed"] or answer.get("broker") or answer.get("shop_step"):
        return False
    if answer.get("unasked") or answer.get("nudge_yes"):
        return False
    reply = answer["reply"] if answer["send"] else ""
    if reply and not needs.only_filler(reply):
        return False
    _not_a_shop_line(answer, need, () if invites else slots, sorry=misread or bool(reply and people.is_apology(reply)), ask=not invites)
    return True


# Batch 2e slice B: the rent flow on the engine's side (assistant/residential.py holds its facts, words and guards) ----------

# The rule name of the rent flow's words before any model (shops_rule_name "res_rule:<kind>").
RES_RULE = "res_rule"


def _residential_line(sentence: str) -> bool:
    return residential.is_fixed_line(sentence)


def residential_plain(
    said: str, now, *, words=(), agreed: bool = False, appointment_open: bool = False, handed_over: bool = False
) -> bool:
    """A burst code may answer with the rent flow's opener, with no model (spec §1.4.3): no question, no time or day, no
    location or way asked, no wish to come, no call or person asked for, no complaint, no broker's words; no yes to our
    invitation, no visit open, no person on the chat (live and in the eval). ``words``: the burst as engine.need_texts
    reads it (``said`` when none)."""
    return not (
        agreed or appointment_open or handed_over or customer_asks(said, now) or wants_to_come(said, now) or people.asks_for_call(said)
        or residential.needs_model(list(words) or [said])
    )


def residential_rule(
    decision, facts, burst, said, heard, now, *, entered: bool, agreed: bool = False, appointment_open: bool = False,
    handed_over: bool = False, ours: int = 0, closed_dates=(), taken=(), talked_shops: bool = False, pack: bool = False,
) -> dict | None:
    """The rent flow's words before any model, else None (residential.pre_model_rule, with the burst read as the engine
    reads it): a voice note nobody could hear, an ID, IBAN or card number typed, the opener of a track just entered, the
    neutral invitation after a second unclear answer on the not-known track."""
    items = said or burst
    words = need_texts(items, heard)
    joined = " ".join(transcript.inbound_text(item, (heard or {}).get(item.pk)) for item in items)
    typed = [item.body or "" for item in items if item.kind == "text"]
    unheard = bool(items) and all(item.kind == "audio" and not (heard or {}).get(item.pk) for item in items)
    plain = residential_plain(joined, now, words=words, agreed=agreed, appointment_open=appointment_open, handed_over=handed_over)
    return residential.pre_model_rule(
        decision, facts, words=words, typed=typed, unheard=unheard and not handed_over, entered=entered, plain=plain, ours=ours,
        slots=lambda: hours.offer_pair(now, closed_dates, taken), handed_over=handed_over, talked_shops=talked_shops, pack=pack,
    )


def residential_switch(answer: dict, before, after, facts: dict, texts, said: str, now, closed_dates=(), taken=(), invites: int = 0) -> str:
    """The model's tag moved a residential chat to another track (spec §1.4.5, §1.5): the new track's words are code's.
    A shop: "Sure! We have shops in International City too." with the shops' for-whom question, or the shop types list
    once we know who it is for; anything else: 2d's office invitation (_not_a_shop_line) with the want recorded; a rent or
    sale track: its opener. Never with a handover of the model's (residential.settle answers that). Returns what it did."""
    if after is None or before is None or after.track == before.track or answer["handover"]["needed"] or answer["opt_out"] != "none":
        return ""
    if answer.get("broker"):
        return ""
    known = {**(facts or {}), **{key: value for key, value in answer["facts"].items() if value not in (None, "", [])}}
    for_client_known = known.get("for_client") is not None
    answer["appointment"] = dict(NO_TIME)
    if after.track == tracks.SHOP:
        if for_client_known:
            answer["shop_step"] = {"kind": shop_flow.LIST}
            answer["step_words"] = residential.switch_shop_text(answer["language"], ask_for_whom=False)
            answer["converted"] = "res_switch_shop"
            answer.pop("res_line", None)
        else:
            residential.code_line({"kind": "res_switch_shop", "ask_for_whom": True}, answer)
        return "shop"
    if after.track == tracks.OTHER:
        need = needs.detect(texts) or needs.from_reason("wrong_need", answer["facts"]) or needs.Need(needs.OTHER)
        answer["facts"][needs.NEED] = need.kind
        answer["facts"][needs.WANTED] = needs.summary(need, known)
        answer["need_words"] = " ".join(str(text or "") for text in texts or ())[:200]
        slots = shops.yes_slots(said, "", now, closed_dates, taken)
        _not_a_shop_line(answer, need, () if invites >= NOT_A_SHOP_INVITES else slots, sorry=False, ask=invites < NOT_A_SHOP_INVITES)
        return "other"
    if after.track in (tracks.RENT, tracks.SALE):
        residential.code_line(residential.opener_spec(after, known, sorry=after.sorry), answer)
        return after.track
    return ""


def residential_slots_step(answer: dict) -> dict | None:
    """The rent flow's only step: code's two free slots for a confirm of a time nobody named (unasked_confirm) or a plain
    yes to our nudge (nudge_yes), as model_step sends them in a shops chat; never a shop step."""
    unasked = answer.get("unasked") or answer.get("nudge_yes")
    if not unasked or answer["opt_out"] != "none" or answer["handover"]["needed"] or answer.get("converted"):
        return None
    step = {"kind": shop_flow.SLOTS, "slots": list(unasked["slots"])}
    if unasked.get("again"):
        step["again"] = True
    answer["shop_step"] = step
    return step


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
    questions for our agent) are added to, never replaced, and never keep a question of
    ours (crm_facts.own_notes: a chat's notes from before launch review issue 15 too)."""
    merged = dict(old or {})
    for key, value in (new or {}).items():
        if key == "notes" and isinstance(value, list):
            if value or isinstance(merged.get(key), list):
                merged[key] = crm_facts.own_notes(shops.merge_notes(merged.get(key), value))
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


def run_turn(message_id: int, *, attempt: int = 0, first_queued_at: str = "", requeued: bool = False) -> Outcome:
    """``requeued``: the sweep queued this message again because its turn was one the reply cap held back
    and the cap has freed (caps.to_answer): that same turn row is taken up (caps.reclaim) and answers the
    burst however old it is, if nobody wrote since."""
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
    requeued = requeued and caps.is_capped(message)
    if not requeued and LeadAiTurn.objects.filter(inbound=message).exists():
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
    answers = settings_row.answers(conversation.contact.wa_id)
    if answers and state.responsible_checked_at is None:
        # Look up the CRM record's responsible person once, early, so the first
        # booking's alert already reaches them (owner's choice), and before an
        # opt-out: a STOP as the first answer reaches the lead's owner too (launch
        # chat 112: its owner sent two templates and called three times after it).
        # An alert raised before the lookup answers reaches them once it does
        # (tasks.resolve_responsible, alerts.reach_responsible).
        LeadAiChatState.objects.filter(pk=state.pk).update(responsible_checked_at=now)
        from ..tasks import resolve_responsible

        transaction.on_commit(lambda pk=conversation.pk: resolve_responsible.delay(pk))
    opt = _burst_opt_out(burst, meeting_open=_open_appointment(conversation) is not None, shops_chat=playbook == lane.IC_SHOPS)
    if opt and playbook == lane.IC_SHOPS and not_lost_for(opt, need_texts(_said(burst) or burst)):
        opt = None  # they want something else: never lost or junk (who_they_are answers them)
    deletion = False
    if not opt and playbook == lane.IC_SHOPS and residential.RENT_LIVE and residential.asks_deletion(" ".join(need_texts(_said(burst) or burst))):
        # "Delete my data" (PDPL, batch 2e spec §6.3): a stop on every number, res_deleted, and the admins told.
        opt, deletion = rules.STOP_ALL, True
    if opt:
        return _rule_opt_out(message, conversation, chat, state, settings_row, burst, opt, playbook=playbook, deletion=deletion)

    if not answers:
        return _skip("assistant switched off")
    if not openai_client.configured():
        return _skip("no Lead AI key")
    if settings_row.paused_until and settings_row.paused_until > now:
        return _skip("assistant paused after OpenAI errors")
    if state.stopped_at is not None:
        return _skip(f"stopped: {state.stop_reason}")
    if state.paused_at is not None:
        # No agent behind it: the assistant paused itself for a broker (_apply).
        return _skip("paused by an agent" if state.paused_by_id else "paused until an agent presses Resume")
    if requeued:
        # Held back by the reply cap and taken up again now: never too old, unless someone wrote since.
        if Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, pk__gt=message.pk).exclude(kind="system").exists():
            return _skip("answered since the reply cap held it back")
    elif now - message.created_at > STALE_AFTER:
        if Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, pk__gt=message.pk).exists():
            return _skip("the message is too old to answer")
        # Nobody answered since: the customer still waits, so the turn goes on late rather than drop them (the first
        # mixed campaign, 2026-10-19: 92 replies in the burst after the send waited past the limit on a two-slot worker
        # and were dropped; 86 were answered by hand-run turns hours later and read fine). The agents still hear that
        # it was late. Older than LATE_UNTIL, it is history: a person decides.
        if now - message.created_at > LATE_UNTIL:
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
        alerts.raise_alert(
            kind="stale",
            conversation=conversation,
            title="Lead AI answered late",
            text=f"A message from {_who(conversation)} waited over {int(STALE_AFTER.total_seconds() // 60)} minutes for the "
            "assistant (the system was busy). It is answered now; please read the chat.",
            dedupe_key=f"stale:{conversation.pk}:{message.pk}",
            crm_url=_crm_url(chat),
        )

    heard: dict[int, str] = {}
    give_up = attempt >= len(AUDIO_WAITS)
    for item in burst:
        if item.kind != "audio":
            continue
        text = transcribe.transcript_for(item, give_up=give_up, deadline=deadline)
        if text is None:
            raise NotReady(AUDIO_WAITS[min(attempt, len(AUDIO_WAITS) - 1)], "voice note downloading")
        heard[item.pk] = text

    # One turn at a time in a chat (turn_lock, issue I02): a second one waits and comes back to a chat that has the
    # first reply in it already. Taken before the turn row exists, so a waiting turn claims nothing.
    with turn_lock.leased(conversation.pk) as mine:
        if mine is False:
            raise NotReady(turn_lock.RETRY_IN, turn_lock.WAITING)
        turn = caps.reclaim(message, now) if requeued else _claim(message)
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


def _rule_opt_out(
    message, conversation, chat, state, settings_row, burst, kind: str, *, playbook: str = lane.GENERAL, deletion: bool = False,
) -> Outcome:
    """A STOP, wrong number or "not interested" found by code: recorded whatever the
    assistant's state; the polite line only when the assistant may speak now.
    ``deletion``: they asked us to delete their data (batch 2e, PDPL): a stop on every
    number, the admins alerted (data_deletion), and res_deleted as the line."""
    turn = _claim(message)
    if turn is None:
        return _skip("already handled")
    # Switched off for this customer (the dark launch): the state is kept, so no
    # reminder or later reply reaches them, but nobody is alerted about a chat
    # the assistant is not part of.
    answers = settings_row.answers(conversation.contact.wa_id)
    if deletion:
        _deletion_alert(conversation, chat, _their_words(burst))
        memory.forget(conversation.contact.wa_id)  # the customer memory goes with the data (memory.py)
        # A C40 to-do for 2311 on the lead (spec §2.10, §6.3), with retries like the lead's fields: someone acts on it.
        crm_fields.queue(conversation, chat, crm_fields.deletion_writes(timezone.now(), settings_row.closed_dates))
    recorded = record_opt_out(
        conversation, kind, by="rule", quiet=not answers, words=_their_words(burst), playbook=playbook,
        reason="asked to delete their data" if deletion else "",
    )
    actions = {"opt_out": kind, "by": "rule", **({"deletion": True} if deletion else {})}
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
        words_out = residential.line("res_deleted", language) if deletion else rules.line_for(kind, language, shops=playbook == lane.IC_SHOPS)
        sent = _send(conversation, words_out, turn)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - the opt-out is recorded either way
        logger.warning("Lead AI opt-out line failed on conversation %s: %s", conversation.pk, exc)
        return _finish(turn, Outcome(LeadAiTurn.Status.FAILED, "opt-out line not sent", actions=actions))
    return _finish(turn, Outcome(LeadAiTurn.Status.REPLIED, f"opt-out ({kind})", reply_message_id=sent.pk, actions=actions))


STOP_KINDS = (rules.STOP_ALL, rules.WRONG_NUMBER, rules.SPAM)


def _deletion_alert(conversation, chat, words: str) -> None:
    """A customer asked us to delete their data (PDPL, batch 2e spec §6.3): the panel admins hear it (data_deletion), so a
    person deletes their details from the CRM and the inbox; the assistant has stopped on every number."""
    who = _who(conversation)
    lines = [
        f"{who} (WhatsApp +{conversation.contact.wa_id}) asked us to delete their data.",
        people.words_line(residential.mask(words)),
        "The assistant stopped in this chat and the phone is on the opt-out registry: no campaign on any number reaches it. "
        "Please delete their details from Bitrix and the inbox as the company's process requires.",
    ]
    for to_admins in (True, False):
        # The panel admins, and the chat's own people with the Lead AI alert list (2311 owns these leads: the CRM review of
        # batch 2e found he never heard of it); one row per person (the dedupe key skips whoever has it already).
        alerts.raise_alert(
            kind="data_deletion",
            conversation=conversation,
            priority="high",
            title=f"{who} asked us to delete their data"[:200],
            text="\n".join(line for line in lines if line),
            dedupe_key=f"data_deletion:{conversation.pk}",
            crm_url=_crm_url(chat),
            admins=to_admins,
            listed=None if to_admins else True,
        )


def record_opt_out(
    conversation, kind: str, *, by: str, quiet: bool = False, words: str = "", playbook: str | None = None, reason: str = "",
    lost_ok: bool = False,
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
    lost_written = False
    if (playbook if playbook is not None else lane.playbook_for(conversation)) == lane.IC_SHOPS:
        # Data, not an alert: written even for a chat the switched-off assistant is not part of. Bot Status Lost goes
        # always; the lead moves to its lost stage only when nobody works it and it has no open to-do (assistant/lost.py,
        # decided when the rows are posted: launch review issue 1).
        writes = crm_fields.opt_out_writes(kind, reason or words)
        # The rent and sale tracks follow the shops' lost rule (Q10, batch 2e): their no is Lost like a shop customer's.
        residential_no = lost_ok or (residential.RENT_LIVE and state.track in (tracks.RENT, tracks.SALE))
        if kind == rules.NOT_INTERESTED and needs.NEVER_LOST and needs.wants_no_shop(state.facts) and not residential_no:
            # The owner's rule (2026-10-15): a customer who wants no shop to rent is never Lost. Their no
            # stops the invitations here; the lead stays open in Bitrix for the team's other options. Read as the
            # follow-ups read it (needs.wants_no_shop: facts.need, or intent buy or sell, or a home as property_type):
            # review 2d found a buyer whose want only the model recorded (intent buy) written Lost.
            writes = []
        crm_fields.queue(conversation, chat, writes)
        lost_written = kind == rules.NOT_INTERESTED and bool(writes)
    if quiet:
        return True
    if lost_written:
        # A shops "no": the lead's owner and the Lead AI alert list hear it, with their words (launch review issue 1:
        # agents were working five of the eight leads closed on the launch day, and nobody was told).
        who = _customer_name(conversation, state.facts or {}) or _who(conversation)
        alerts.raise_alert(
            kind="lost",
            conversation=conversation,
            appointment=appointment,
            title=f"{who} said no to the shops offer",
            text="\n".join(
                line for line in (
                    f"{who} (WhatsApp +{conversation.contact.wa_id}) said no to the shops offer.",
                    *people.where_lines(conversation, chat),
                    *lost.alert_lines(words or reason, rented=reason == RENTED_REASON),
                ) if line
            ),
            dedupe_key=f"lost:{conversation.pk}:{now:%Y%m%d%H%M%S}",
            crm_url=_crm_url(chat),
            listed=True,
        )
    # A shops chat's opt-out reaches the Lead AI alert list too, with the lead and where the chat is (launch chat
    # 112: the lead's owner kept messaging and calling a customer who had tapped Stop): the lead's owner hears it
    # once the lookup answers, if it had not (alerts.reach_responsible).
    shops_chat = (playbook if playbook is not None else lane.playbook_for(conversation)) == lane.IC_SHOPS
    where = "\n" + "\n".join(people.where_lines(conversation, chat)) if shops_chat else ""
    if kind == rules.SPAM:
        alerts.raise_alert(
            kind="opt_out",
            conversation=conversation,
            appointment=appointment,
            title=f"{_who(conversation)} sent what looks like spam",
            text="The assistant read the customer's message as spam (a chain message, a scam or an advert), sent nothing "
            "and stopped in this chat. The phone is now on the opt-out registry: no campaign on any number reaches it."
            + (
                " In Bitrix its Bot Status is Lost, and the lead goes to Junk Lead only if nobody from the team worked it in the "
                f"last {lost.TOUCH_WINDOW.days} days and it has no open to-do. If that is wrong, press Resume AI (it restarts "
                "the assistant and takes the phone off the registry again) and move the lead back in Bitrix by hand."
                if crm_fields.lead_of(chat, conversation) is not None
                else " If that is wrong, press Resume AI: it restarts the assistant and takes the phone off the registry again."
            )
            + where,
            dedupe_key=f"opt_out:{conversation.pk}:{now:%Y%m%d}",
            crm_url=_crm_url(chat),
            listed=True if shops_chat else None,
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
            )
            + (" Please do not message them again from any number." if shops_chat and kind == rules.STOP_ALL else "")
            + where,
            dedupe_key=f"opt_out:{conversation.pk}:{now:%Y%m%d}",
            crm_url=_crm_url(chat),
            listed=True if shops_chat else None,
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
            # The rent flow's own words for a place rented elsewhere (residential.settle: res_already_rented).
            words_out = residential.line(answer["opt_out_line"], language) if answer.get("opt_out_line") else ""
            sent = _send(conversation, words_out or rules.line_for(kind, language, shops=playbook == lane.IC_SHOPS), turn)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lead AI opt-out line failed on conversation %s: %s", conversation.pk, exc)
    record_opt_out(
        conversation, kind, by=by, words=words, playbook=playbook, reason=answer.get("lost_reason") or "", lost_ok=bool(answer.get("lost_ok"))
    )
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


def _slot_gone(conversation, when, appointment, now, closed_dates, said: str, place: str = "office") -> list | None:
    """Another chat's visit took this slot while the model was thinking: the free starts
    nearest it (to offer instead), else None (still free, the time they already have, or
    a walk-in). ``place`` "call": a buyer's call, looked up in the call pool (calls.taken; batch 2e slice C)."""
    confirmed = appointment is not None and appointment.status == LeadAiAppointment.Status.CONFIRMED
    call = place == calls.PLACE
    if (confirmed and appointment.starts_at == when) or (not call and _walk_in(when, said, now)):
        return None
    taken = calls.taken(conversation, now) if call and calls.OWN_POOL else taken_slots(conversation, now)
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
    licence_reply: bool = False, template_kind: str = ic_templates.SHOP, decision=None,
) -> tuple[str, str, str]:
    """(rule, its line's language, the customer's words) when a shops rule settles this burst.

    ``licence_alone``: the licence copy came, with nothing else said (LICENCE_RECEIVED);
    ``licence_reply``: they answered our request for it with a no, which is the
    model's to answer: no shops rule reads it as "Not now" or a decline of the offer.
    ``template_kind`` / ``decision``: the campaign template's kind and the chat's track (batch 2e), which the mixed
    template's first yes reads (tracks.first_yes).
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
    mixed = ""
    if reads_first_yes(template_kind, decision):
        mixed = tracks.first_yes(decision, for_client_known=facts.get("for_client") is not None)
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
        template_kind=template_kind,
        mixed=mixed,
        track=decision.track if decision is not None else None,
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
        LeadAiChatState.objects.filter(pk=state.pk).update(handed_over_at=None, handover_reason="", holding_line_at=None, draft=None)
        state.handed_over_at = None
        state.handover_reason = ""
        state.draft = None  # the co-pilot's draft went with the handover (copilot.py)

    # The per-chat caps (caps.limits: a shops chat may send more); a shops chat's capped message is answered
    # once the cap frees (caps.to_answer), and its alert says so.
    which = caps.reached(conversation, playbook, now)
    if which and people.asks_for_call(" ".join(need_texts(_said(burst) or burst))):
        which = ""  # a call asked for is handed to a person now, never held by the cap (the first mixed campaign: 20 min)
    if which:
        caps.alert(conversation, chat, playbook, _their_words(burst, heard), now, which)
        return _skip(CAPPED_REASON)
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
    # Who the customer is (launch 2026-10-15): what they want instead of a shop to rent, in their own
    # words this burst (needs.detect), or as the chat knows it (facts.need).
    words_now = need_texts(said or burst, heard) if shops_chat else []
    need_seen = (needs.detect(words_now) or needs.of(facts)) if shops_chat else None
    # Which need the chat serves (batch 2e, assistant/tracks.py): code decides the track and the unit; slice A stores them in
    # shadow (_apply) and only the mixed template's first yes reads them. The lead context is read only when a step needs it.
    template_kind = ic_templates.kind_of(campaign_msg) if shops_chat else ic_templates.SHOP
    track_inputs = {
        "stored": state.track, "stored_unit": state.unit, "template_kind": template_kind,
        "first_answer": last_ours is not None and transcript.who(last_ours, campaign_templates) == "campaign",
        "lead": tracks.lazy(lambda: lead_context.for_turn(conversation, chat, state, now)), "clusters": tracks.cluster_names(settings_row),
        # Taps on our shop types list or a type's card: the shop track's own (spec §1.4.2), so a tap on another track moves it.
        "shop_tap": shops_chat and flow_taps([(_tap_label(item), _tap_id(item)) for item in (said or burst[-1:])]),
        # The community packs (communities.py, round 17): a home in Mudon, Villanova, ... is that pack's rent or sale track.
        "packs": communities.named_packs() if shops_chat else (),
        # The chat's own community, else the one its campaign sells (LeadAiCampaign.community, Cursor's C44).
        "stored_community": state.community or communities.campaign_community(chat),
    }
    decision = tracks.decide(words=words_now, facts=facts, **track_inputs) if shops_chat else None
    # SALE (slice C, sales.py, calls.py): a buyer's turn may book a 5-minute call in the call pool (spec §3.3). The sale flow
    # rides on the residential path (RES_SYSTEM's sale section, residential.settle): off with it (residential.RENT_LIVE).
    sale = decision is not None and decision.track == tracks.SALE and residential.live_track(decision.track)
    call_taken = calls.taken(conversation, now) if sale else []
    called = sold = ""  # what the sale steps did (the turn's actions "sale")
    need = None
    brokered = ""  # what handed a broker over that the model did not (brokers.backstop)
    shops_rule_name, shops_words = "", ""
    if shops_chat:
        shops_rule_name, rule_language, shops_words = _shops_rule_for(
            conversation, state, burst, said, appointment, last_ours, campaign_templates,
            licence_alone=licence_alone, licence_reply=licence_reply, template_kind=template_kind, decision=decision,
        )
    # Batch 2e slice B, the rent flow (assistant/residential.py): a rent, sale or not-known chat takes the residential path,
    # with its own rules before the model (residential_rule), prompt, schema, context, guards, full-name gate and lines.
    res = shops_chat and decision is not None and residential.live_track(decision.track)
    # The community packs' flow (communities.py, round 17): a residential chat about a community with a pack reads the
    # pack's facts and INVENTORY in International City's place, with its own prompt (PACK_SYSTEM) and no opener of code's.
    pack = communities.by_name(decision.community) if (decision is not None and decision.community) else None
    pack_flow = bool(res and pack is not None and not pack.default)
    if pack_flow:
        # A pack's buyer gets the office visit, like its tenant (Matloob 2026-10-20): none of the sale flow's call pool,
        # price steps or International City's sales lines.
        sale, call_taken = False, []
    res_decision = decision  # the track the residential path was chosen for (the model's tag may move it: res_switch)
    res_spec = None  # the rent flow's words before any model (residential_rule)
    if res and not shops_rule_name and not licence_reply:
        ours_sent = sum(1 for row in rows if row.direction == Message.Direction.OUTBOUND and transcript.who(row, campaign_templates) == "assistant")
        spec = residential_rule(
            decision, facts, burst, said, heard, now, entered=(state.track or "") != decision.track,
            agreed=agreed, appointment_open=appointment is not None, handed_over=state.handed_over_at is not None,
            ours=ours_sent, closed_dates=settings_row.closed_dates, taken=taken,
            # We talked shops to them already (a shops template's chat with a reply of ours): the opener apologises.
            talked_shops=template_kind == ic_templates.SHOP and (state.track or "") in ("", tracks.SHOP) and ours_sent > 0,
            pack=pack_flow,
        )
        if spec:
            shops_rule_name = f"{RES_RULE}:{spec['kind']}"
            rule_language = shops_language(_their_words(burst, heard), False, state.language)
            shops_words = _their_words(burst, heard)
            res_spec = spec
    deferred = "" if shops_rule_name or licence_reply else deferral(
        [(item.body or "") if item.kind == "text" else "" for item in said],
        appointment=appointment,
        offered=visit_offered(ours),
        invites=state.invites,
        # A person has the chat, they declined, or they are no customer of ours.
        quiet=state.handed_over_at is not None or state.not_interested_at is not None or segment == "other",
    )
    units = []  # the inventory's units the model path reads (inventory.matches); none on code's own paths
    if shops_rule_name.startswith(f"{RES_RULE}:"):
        # The rent flow's own words before any model (residential_rule): an opener, a document or voice-note line, the
        # neutral invitation; shaped like the model's answer, so the same path sends and stores it.
        answer = residential.rule_answer(res_spec, rule_language, decision, facts=facts, words=words_now)
        when, completions, rejected, still_invalid = None, [], "", False
    elif shops_rule_name:
        # The shops playbook's fixed words (the yes, "Not now", the check-back's
        # answer, a no after "already rented"), and its steps (a tap on the shop
        # types list or a type's card, the licence copy arriving): settled like a
        # deferral, before the model, and shaped like its answer, so the same path
        # sends and stores it.
        answer = shops_answer(shops_rule_name, rule_language, shops_words, facts, decision=decision)
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
        res_context = None
        if res:
            # The rent flow's block (spec §2.3): the lead context is read for it (once per chat, lead_context.for_turn).
            lead_now = track_inputs["lead"].get()
            # The chat's community (communities.py: what it stored, the lead context, their words, else International
            # City), stored on the state for the panel and the next turn; code's own, never the model's.
            pack_now = pack if pack_flow else communities.default_pack()
            if pack_now.name != (state.community or ""):
                LeadAiChatState.objects.filter(pk=state.pk).update(community=pack_now.name)
                state.community = pack_now.name
                logger.info("Lead AI chat %s is about %s (%s)", conversation.pk, pack_now.name, decision.reason)
            # The real units the bot may quote (inventory.py): the chat's community, clusters, unit and deal; none, and
            # the band answers as before (a pack chat: the unit as named, two bedrooms or more being a villa or a townhouse too).
            if inventory.LIVE:
                units = inventory.matches(
                    pack_now.name, decision.clusters, inventory.pack_units(decision.unit) if pack_flow else decision.unit, inventory.deal_of(decision.track),
                )
            # SALE (slice C): the buyer's next questions (SALE STEP) and the call pool's free slots (CALL SLOTS).
            sale_parts = sales.context_parts(
                facts, decision.unit, decision.clusters,
                [(transcript.who(row, campaign_templates), transcript.outbound_text(row)) for row in rows if row.direction == Message.Direction.OUTBOUND],
                now, settings_row.closed_dates, call_taken, settings_row.residential_facts,
            ) if sale else {}
            res_context = residential.context(
                settings_row, decision.track, decision.unit, decision.clusters, now, taken, lead=lead_now,
                full_name=residential.full_name_known(facts, lead_now), history=history, held=residential.held_start(appointment, now),
                inventory=inventory.lines(units),
                # A pack chat: the pack's facts in RES FACTS' place, its COMMUNITY lines, no International City charge lines.
                facts_override=communities.facts_block(pack, units) if pack_flow else "",
                community=communities.lines(pack) if pack_flow else (),
                charges=not pack_flow,
                **sale_parts,
            )
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
            shops=shops.context(settings_row, facts, now, taken, history=history) if shops_chat and not res else None,
            residential=res_context,
            # The customer's earlier chats on our other numbers (memory.py), as data to confirm as a question.
            memory=memory.lines(memory.recall(conversation.contact.wa_id, exclude_conversation=conversation.pk)),
        )
        answer, when, completions, rejected, still_invalid = ask_model(
            prompt.system_prompt(playbook, residential=res, pack=pack_flow),
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
            need_segment=residential.segment_of(decision.track) if res else (needs.SEGMENTS[need_seen.kind] if need_seen is not None else ""),
            residential=res,
            pack=pack_flow,
            # SALE (slice C): a buyer may book a call (calls.PLACES), checked against the call pool.
            places=calls.places_for(tracks.SALE if sale else ""),
            call_taken=call_taken,
        )
        # The co-pilot's draft (copilot.py): the model's own reply, before any guard rewrites or replaces it; _apply keeps
        # it for the agent when a person has the chat.
        answer["copilot_draft"] = answer["reply"]
        if (licence_media is not None or licence_page) and answer["handover"]["needed"] and answer["handover"]["reason"] == "media_received":
            answer["handover"] = {"needed": False, "reason": None}  # the photo is the licence we asked for
        if shops_chat:
            # A customer who wants no shop to rent is tagged, never handed over (the owner's rule). Not on the residential
            # path: its handovers are the rent flow's own (residential.settle), and its need tag is never one.
            need = untag_need(answer, facts, words_now) if not res else None
            # A broker is never served as an end user (Q11; the launch gate's eval shops-broker: facts.for_client true and
            # no handover): handed over as the model's own tag would be, before anything else reads the answer. Not in a
            # chat that carries the Broker label already (Resume AI): one query, asked only when it would act. In a chat a
            # person holds, only "I am / we are a broker" counts ("agent not picking up" is ours); a bare "Agent" answers
            # our for-whom question only (our_last).
            brokered = brokers.backstop(
                answer, facts, words_now, labelled=lambda: conversation.labels.filter(name__iexact=BROKER_LABEL).exists(),
                held=state.handed_over_at is not None, our_last=our_last,
                # On the rent and sale tracks a client of theirs is someone else's (2e gate, round 2: a broker's viewing booked).
                track=decision.track if decision is not None else "",
            )
            # The track again, with the model's tag and what it recorded this turn (spec §1.4, hook point 5).
            decision = tracks.decide(
                words=words_now, facts=facts, model_tag=answer.get("need_tag") or "", fresh=answer["facts"], **track_inputs
            )
            switched = res and residential_switch(
                answer, res_decision, decision, facts, words_now, said_words, now, settings_row.closed_dates, taken, state.invites,
            )
            if switched:
                # The model's tag moved the chat (spec §1.4.5): the new track's words are code's, and no time of the model's.
                when, still_invalid = None, False
            # SALE (slice C): the sale steps follow the track as the model's tag leaves it, on the residential path only.
            if res and decision.track == tracks.SALE and not sale:
                call_taken = calls.taken(conversation, now)
            sale = res and decision.track == tracks.SALE and not pack_flow
            if sale and not switched:
                # SALE (slice C): a buyer's call: booked at their own day and hour, else two free call slots; never 2d's
                # call_requested handover, and a buyer abroad gets the call (sales.call_step).
                when, called = sales.call_step(
                    answer, when, appointment=appointment, said=said_words, words=grounding[0], our_last=our_last, ours=ours, now=now,
                    closed_dates=settings_row.closed_dates, taken=call_taken, still_invalid=still_invalid,
                    handed_over=state.handed_over_at is not None, grounding=grounding,
                )
        if shops_chat and not still_invalid:
            # Their own exact day and hour, which the model confirmed at another time ("4:30 PM today is fine" booked at 4:00 PM).
            mine = own_time(
                answer, when, appointment, now, settings_row.closed_dates, taken=taken, said=said_words, words=grounding[0],
                our_last=our_last, ours=ours, grounding=grounding, handed_over=state.handed_over_at is not None,
                agent_last=_agent_spoke_last(conversation, campaign_templates),
            )
            if mine is not None:
                when, upgraded = mine, True
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
        if when is None and not still_invalid:
            # Their own window today ("I will come at 12-12:30"), which the model left tentative: its start, if free.
            window = book_window(
                answer, said_words, appointment, now, settings_row.closed_dates, taken=taken, grounding=grounding,
                handed_over=state.handed_over_at is not None, agent_last=_agent_spoke_last(conversation, campaign_templates),
                playbook=playbook,
            )
            if window is not None:
                when, upgraded = window, True
        if shops_chat and when is None and not still_invalid:
            # The model's own slot offer is no visit of theirs: none recorded, or one in their words alone.
            own = own_offer(answer, appointment=appointment, said=said_words, words=grounding[0], our_last=our_last, yes=yes, now=now)
        if shops_chat:
            # A plain yes to our nudge: code's two free slots for it, never a time of the model's held for them.
            nudge_yes(
                answer, our_last=our_last, texts=texts, appointment=appointment, when=when, still_invalid=still_invalid,
                said=said_words, now=now, closed_dates=settings_row.closed_dates, taken=taken, handed_over=state.handed_over_at is not None,
            )
        turn.model = completions[-1].model[:64]
        turn.calls = len(completions)
        turn.prompt_tokens = sum(c.prompt_tokens for c in completions)
        turn.completion_tokens = sum(c.completion_tokens for c in completions)
        turn.latency_ms = sum(c.latency_ms for c in completions)
    in_hand = {item.pk for item in burst}
    # Their earlier voice notes as heard (the transcripts the context showed the model): their own words, which settle
    # reads, as the eval writes them ("[voice note] ..."); a note's question for our agent stands on them (crm_facts).
    earlier = [
        (
            transcript.who(row, campaign_templates),
            transcript.inbound_text(row, transcript.transcript_text(row)) if row.direction == Message.Direction.INBOUND else transcript.outbound_text(row),
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
        if shops_chat and not sale
        else None,
        now=now,
        facts=facts,
        closed_dates=settings_row.closed_dates,
        taken=taken,
        booked=appointment.starts_at if appointment is not None else None,
        shops_facts=settings_row.shops_facts,
        office_address=settings_row.office_address,
        # The old lead's notes as the context showed them (lead_history.for_turn keeps them on the state).
        crm_notes=(state.lead_notes or "") if shops_chat else "",
        residential=res,
        residential_facts=settings_row.residential_facts,
        # The track as the model's tag leaves it, on the residential path (a shop chat's turn stays 2d's: shops guards on).
        track=decision.track if res else "",
    )
    if shops_chat and broker_holds(answer):
        # A broker books nothing (Q11): the broker line goes, the time stays a tentative for our agent.
        when, still_invalid = None, False
    if res and not shops_rule_name and not deferred:
        # The rent flow's guards (spec §2.9, hook point 7): figures by unit and deal, code's commission and VAT lines, no
        # shop words, no availability or booking claimed, no document asks, no screening; and its special cases' lines.
        # The rent track's photos going this turn (unit_media's set, slice E): the model's "Here are the photos." stays.
        photos_going = bool(unit_media.turn_step(
            answer, conversation, decision, words=words_now, earlier=earlier, known=facts, lead=track_inputs["lead"], now=now,
            quiet=state.handed_over_at is not None, when=when, still_invalid=still_invalid, appointment=appointment,
            may_invite=may_invite, dry_run=True,
        ))
        res_cut = residential.settle(
            answer, earlier, [transcript.inbound_text(item, heard.get(item.pk)) for item in burst], track=decision.track,
            unit=decision.unit, clusters=decision.clusters, facts=facts, residential_facts=settings_row.residential_facts,
            shops_facts=settings_row.shops_facts, when=when, still_invalid=still_invalid, sending=photos_going,
            visit_open=appointment is not None, booked_at=appointment.starts_at if confirmed else None,
            office_address=settings_row.office_address, pack=pack_flow, units=units,
        )
        # 2d's facts.need and facts.wanted stay set on the rent and sale tracks (followups.holds, the nudges, panel_note).
        residential.record_need(answer, facts, decision, words_now)
    if licence_media is not None:
        answer["licence"] = "received"
        answer["licence_media"] = licence_media
    elif licence_answer:
        # "declined" closes the request (_apply); "later" leaves it open for the copy to come.
        answer["licence"] = licence_answer
    who = ""
    need_slots = ()
    misread = False
    if sale and not shops_rule_name and not deferred:
        # SALE (slice C): a buyer's steps in place of who_they_are, after residential.settle: the questions in their order,
        # the price never hidden, no media first, the call slots, the sales handovers (sales.settle).
        sold = sales.settle(
            answer, facts=facts, texts=words_now, said=said_words, earlier=earlier, now=now, closed_dates=settings_row.closed_dates,
            office_taken=taken, call_taken=call_taken, residential_facts=settings_row.residential_facts, unit=decision.unit,
            clusters=decision.clusters, when=when, still_invalid=still_invalid, quiet=state.handed_over_at is not None,
            may_invite=may_invite, appointment=appointment,
        )
    elif shops_chat and not res and not shops_rule_name and not deferred:
        # Who the customer is: someone who wants no shop to rent gets the owner's line (never the shop
        # list, never lost), someone who rented one already the second-shop question (who_they_are).
        wants = need is not None or needs.of(facts) is not None
        need_slots = shops.yes_slots(said_words, "", now, settings_row.closed_dates, taken) if wants else ()
        misread = any(author == "assistant" for author, _ in earlier) or needs.misread(words_now)
        who = who_they_are(
            answer, facts, words_now, need, when=when, still_invalid=still_invalid, appointment=appointment,
            quiet=state.handed_over_at is not None, slots=need_slots, misread=misread,
            shop_facts=shops.known_amounts(settings_row), invites=state.invites, office_address=settings_row.office_address,
        )
        if answer.get("forget"):
            # They want a shop after all: the rest of the turn reads the chat without the want it read wrong.
            facts = {key: value for key, value in facts.items() if key not in answer["forget"]}
    acted = ""
    if not shops_rule_name and not deferred:
        # Where a person must act (people.py, launch review issues 4, 14 and 21): a call request gets code's words
        # and its time is passed on, never a promise of a call; a shops customer's must-answer questions go to a
        # person before any visit; no reply sends them to chase a colleague. Live and in the eval.
        acted = people.settle(
            answer, words_now, said_words, shops_chat=shops_chat, when=when, still_invalid=still_invalid,
            quiet=state.handed_over_at is not None,
            # The residential path sets a need, so its charge questions are answered, never handed over (spec §1.4.7).
            need=need or (needs.of({**facts, **answer["facts"]}) if shops_chat else None) or (residential.RES_NEED if res else None),
            now=now,
        )
    if shops_chat and not res and not shops_rule_name and not deferred and bare_need_reply(
        # The chat's want as this turn leaves it (who_they_are wrote it when it replaced the one known), else the one said now.
        answer, needs.of({**facts, **answer["facts"]}) or need, need_slots, invites=state.invites, misread=misread,
        plain=not (state.handed_over_at is not None or when is not None or still_invalid or appointment is not None),
    ):
        # The cuts left them an apology or nothing (review 2d: chat 114's "Sorry for the confusion."): the owner's line.
        who = WHO_NOT_A_SHOP
    if shops_chat and not res and not shops_rule_name and not deferred and shop_buyer.settle(
        # Q43 (shop_buyer.py): a shop buyer hears no figure; their price question gets code's answer, the invitation, an alert.
        # Off the residential path, as who_they_are and bare_need_reply (a shop buyer is on the other track).
        answer, needs.of({**facts, **answer["facts"]}) or need, facts, words_now,
        track=decision.track if decision is not None else "", invites=state.invites, slots=need_slots,
        plain=not (state.handed_over_at is not None or when is not None or still_invalid or appointment is not None),
    ) == shop_buyer.PRICE_LINE:
        shop_buyer.alert(conversation, chat, _their_words(burst, heard))
    priced = tapped = ""
    if shops_chat and not res and not shops_rule_name and not deferred:
        # The price (launch review issue 12): a price objection, or a budget below our lowest, gets code's honest line.
        priced = claims.price_turn(
            answer, words_now, facts, our_last=our_last, sent=[text for author, text in earlier if author == "assistant"],
            facts=settings_row.shops_facts, yes=opens_with_yes(texts),
            plain=price_plain(answer, facts, need, said_words, when=when, still_invalid=still_invalid, quiet=state.handed_over_at is not None),
        )
        # A tap sent with typed words keeps its step, and the model answers the words (launch review issue 13).
        tapped = tap_with_words(
            answer, burst_tap(said, heard), facts, said_words, now,
            first_answer=last_ours is not None and transcript.who(last_ours, campaign_templates) == "campaign",
            appointment=appointment, when=when, still_invalid=still_invalid, quiet=state.handed_over_at is not None,
            media_recent=_media_recent(conversation, now), media_today=_media_today(conversation, now),
            closed_dates=settings_row.closed_dates, taken=taken,
        )
    if res and not answer.get("shop_step") and not shops_rule_name and not deferred:
        # The rent flow takes no shop step: only code's two free slots for a time nobody named (unasked_confirm, nudge_yes).
        residential_slots_step(answer)
    elif shops_chat and not answer.get("shop_step") and not shops_rule_name and not deferred:
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
    # Batch 2e slice E (unit_media.py, spec §4): on the rent track, photos asked for (or a unit and cluster confirmed by a
    # direct customer) get their unit's set after the model's statements, then its question or code's two free slots; with
    # no set imported, "I don't have approved pictures for this one yet ...". Never over a line code writes.
    unit_media.turn_step(
        answer, conversation, decision, words=words_now, earlier=earlier, known=facts,
        lead=track_inputs["lead"] if shops_chat else None, now=now, quiet=state.handed_over_at is not None, when=when,
        still_invalid=still_invalid, appointment=appointment, may_invite=may_invite, ruled=bool(shops_rule_name or deferred),
        slots=lambda: hours.offer_pair(now, settings_row.closed_dates, taken),
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
    if answer.get("nudge_yes"):
        plan["nudge_yes"] = True  # a plain yes to our nudge: code's two free slots (nudge_yes)
    if answer.get("own_time"):
        # Their own exact time booked over the model's other one (own_time).
        plan["own_time"] = {"start": answer["own_time"]["start"].isoformat(), "model": answer["own_time"]["model"].isoformat()}
    if answer.get("notes_added"):
        plan["notes_added"] = len(answer["notes_added"])  # their must-answer questions noted in their words (crm_facts)
    if who:
        plan["who"] = who  # code's words for who they are: the owner's not-a-shop line, or the second-shop question
    if need is not None:
        plan["need"] = need.kind  # they want no shop to rent (needs.py)
    if answer.get("need_tag"):
        plan["need_tag"] = answer["need_tag"]  # the model's tag for it, taken off the handover
    if answer.get("need_dropped"):
        plan["need_dropped"] = answer["need_dropped"]  # another handover of the model's, taken off a chat that wants no shop
    if answer.get("forget"):
        plan["forgot"] = answer["forget"]  # they asked for a shop after all: the want the chat read wrong is forgotten
    if acted:
        plan["people"] = acted  # code's words where a person must act (people.settle)
    if answer.get("must_answer"):
        plan["must_answer"] = answer["must_answer"]  # the questions a person answers before any visit
    if answer.get("questions_waiting"):
        plan["questions_waiting"] = True  # ... while the chat goes on (people.MUST_ANSWER_PAUSES False)
    if priced:
        plan["price"] = answer["price"]["kind"] if answer.get("price") else priced  # code's price line, or a colleague's handover
    if tapped:
        plan["tap_step"] = tapped  # a tap sent with typed words kept its step (tap_with_words)
    if answer.get("window"):
        plan["window"] = answer["window"]  # their own window today, booked at its start (book_window)
    if brokered and answer.get("broker_backstop"):
        # A broker the model served as an end user, handed over by code (brokers.py); residential.unasked_broker drops the
        # record with the tag it takes off (round 6's review).
        plan["broker_backstop"] = brokered
    if answer.get("broker_held"):
        plan["broker_held"] = True  # a broker's booking kept as a tentative for our agent (broker_holds, Q11)
    if decision is not None:
        plan["track"] = decision.as_dict()  # the chat's track and unit as code decided them (batch 2e, tracks.py; shadow)
    if called or sold:
        plan["sale"] = {key: value for key, value in (("call", called), ("step", sold)) if value}  # the sale steps (sales.py)
    # Their words, for the alerts a person must act on (a handover, a chase, a call's time); in a shops chat an Emirates ID,
    # an IBAN or a card number in them is masked (PDPL, batch 2e spec §6.3), and so it is in the facts this turn stores.
    answer["their_words"] = residential.mask(_their_words(burst, heard)) if shops_chat else _their_words(burst, heard)
    if shops_chat and isinstance(answer.get("facts"), dict):
        residential.mask_facts(answer["facts"])
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
    if answer.get("facts_dropped"):
        plan["facts_dropped"] = answer["facts_dropped"]  # facts that were not theirs (crm_facts.settle)
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
    # The rent and sale tracks book under the customer's full name (spec §2.6): their words, the lead's NAME and LAST_NAME,
    # or a bare name right after our ask; a time held for it is booked once it comes, and a no keeps it for our agent. A
    # buyer's call (SALE, slice C) is held and booked at its own place, in the call pool (spec §3.3.2).
    res_book = res and decision is not None and decision.track in (tracks.RENT, tracks.SALE)
    full_name = ""
    if res_book:
        held = residential.held_of(appointment, now)
        name_step = residential.name_turn(
            answer, facts, track_inputs["lead"].get(), held=held,
            asked=last_ours is not None and transcript.payload(last_ours).get("res_step") == residential.FULL_NAME_STEP,
            texts=words_now, said=said_words, when=when, still_invalid=still_invalid, rule=bool(shops_rule_name or deferred), now=now,
            closed_dates=settings_row.closed_dates, taken=call_taken if held is not None and held["place"] == calls.PLACE else taken,
        )
        full_name = name_step.full_name
        if name_step.when is not None:
            when = name_step.when
        if name_step.kind:
            plan["full_name"] = name_step.kind
    # The time already booked said again is a reconfirm (nothing moves); a move with no time is asked for (turn_action).
    action = turn_action(answer["appointment"]["action"], appointment, when, still_invalid)
    gate = residential.full_name_gate(
        track=decision.track, action=action, when=when, facts=_merge_facts(facts, answer["facts"]), lead=track_inputs["lead"].get(),
    ) if res_book else residential.BOOK
    if gate == residential.ASK and not full_name:
        # A booking, or a move to a new time, with no full name is none (brief Part 5, step 5; spec §2.6): the time is held
        # (a tentative, or on the booking it would move: residential.mark_move_hold) and code asks for the name; a price they
        # asked in the same words goes first (spec §3.1: the price, the full name, then the booking). Before _slot_gone.
        residential.hold_for_name(answer, when, price=residential.price_spec(words_now, decision.track, decision.unit, decision.clusters))
        plan["full_name"] = "asked"
        when, action = None, "tentative"
    if action in ("confirm", "reschedule") and when is not None:
        # One client per slot, looked at again under the office lock (held until the
        # booking is stored): another chat may have booked it while the model thought.
        if hold is not None:
            hold.enter_context(office_lock())
        gone = _slot_gone(
            conversation, when, appointment, now, settings_row.closed_dates, said_words, place=answer["appointment"].get("place") or "office"
        )
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
    if res:
        # A residential reply may quote that track's and unit's figures only (spec §2.9.1), and the inventory's units'.
        # A pack chat never carries International City's figures: the amount filter cuts them (the 2e gate, round 17).
        ic_amounts = residential.known_amounts(settings_row, decision.track, decision.unit, decision.clusters) if not pack_flow else communities.known_amounts(pack)
        rows_context = f"{rows_context} {ic_amounts} {inventory.known_amounts(units)}"
    elif shops_chat:
        # A shops reply may quote SHOP FACTS' own figures, and no other new one.
        rows_context = f"{rows_context} {shops.known_amounts(settings_row)}"
    answer["copilot_context"] = rows_context  # the draft's amount filter reads the same words (copilot.draft_text)
    maps = settings_row.office_maps_url
    text = ""
    holding = False
    booking = None
    filtered = []
    gloss = False  # the model's own words go out whole, so its English translation (reply_en) holds
    appended = ""  # the Maps link or the address code added to the reply
    media_type = ""  # a shop type whose video, photos and card go out (tasks.send_shop_media)
    media_files = True  # False: its card alone (its files went out today)
    media_unit = None  # a studio or one-bedroom set whose photos go out (unit_media.deliver; batch 2e slice E)
    list_step = False  # the shop types list goes out instead of a text
    step_marker = ""  # a shops step our message is (payload "shop_step"), read back by a later turn
    res_step = ""  # the rent flow's step our message is (payload "res_step": the full-name ask), read back by the next turn
    model_words = False  # the model's own words go out (not a line code writes)
    pin_now = False  # our office's pin follows the reply (a booking, or the not-a-shop line)

    def booking_text(rescheduled: bool) -> str:
        if res_book:
            # The rent viewing's (or the sale office meeting's) confirmation, or a buyer's call (SALE, slice C:
            # res_call_booked), under their full name (spec §2.7, §3.3.3).
            place = answer["appointment"].get("place") or (appointment.place if appointment is not None else "")
            return residential.confirmation(
                language, when, kind=residential.CALL if place == calls.PLACE else residential.VISIT,
                full_name=full_name or residential.full_name_known(merged, track_inputs["lead"].get()),
                unit=decision.unit, clusters=decision.clusters, office_address=settings_row.office_address, maps_url=maps,
                track=decision.track, rescheduled=rescheduled,
            )
        shop_track = decision is not None and decision.track == tracks.SHOP
        if shop_confirmation(shops_chat, decision, merged):
            # The build pack's confirmation: date, time, shop type, place, who they meet, what to bring. The shop track's
            # only (batch 2e review: a mixed-template chat whose need nobody knew yet was told its shop type, the drive to
            # the shops and its trade licence, and an agent's name).
            return shops.confirmation(
                language,
                when,
                shop_type=merged.get("shop_type"),
                facts=settings_row.shops_facts,
                office_address=settings_row.office_address,
                maps_url=maps,
                agent=shops.agent_of(settings_row),
            )
        # A general chat's, a shops customer's who wants no shop to rent, and a chat whose need is not known yet: no shop
        # type, no drive to the shops, no trade licence, "our specialist" (the owner's rule, 2026-10-15).
        if rescheduled:
            return filters.rescheduled(language, name, when, settings_row.office_address, maps)
        commercial = _is_commercial(answer["segment"], merged) and needs.of(merged) is None and (decision is None or shop_track)
        return filters.confirmation(language, name, when, settings_row.office_address, maps, commercial)

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
        # SALE (slice C): a buyer's call moves within the call pool (calls.taken), a visit within the office's.
        pool = calls.taken(conversation, now) if calls.is_sales_call(appointment) else taken
        text = shop_flow.reschedule_text(language, hours.offer_pair(now, settings_row.closed_dates, [*pool, *own]), now)
        plan["fallback"] = "reschedule_slots"
    elif answer.get("sale") and state.handed_over_at is None:
        # SALE (slice C): a sale step's own words (sales.text): the buyer media line, the call slots, the sales handover.
        text = sales.text(answer["sale"], language, now)
        holding = answer["sale"].get("kind") == sales.HANDOVER
    elif state.handed_over_at is not None and not residential.name_gate_line(answer):
        # A person has the chat (people.quiet_reply, launch review issues 4 and 21): a thanks or a goodbye gets
        # nothing; a chase, an apology and the team alerted again (_apply); a call asked for or its time, passed
        # on; anything else the holding line, at most every two hours, as before. The full-name gate's own words
        # (the name asked, the time noted) go even then, as the booking they stand for would (spec §2.6).
        lately = state.holding_line_at is not None and now - state.holding_line_at <= people.QUIET_LINE_EVERY
        quiet_kind, text = people.quiet_reply(
            need_texts(said or burst, heard), language, shops=shops_chat, reason=state.handover_reason, answer=answer,
            said=said_words, now=now, line_due=not lately,
            holding_due=not state.holding_line_at or now - state.holding_line_at > HOLDING_EVERY,
        )
        plan["quiet"] = quiet_kind
        if quiet_kind in (people.QUIET_CHASE, people.QUIET_CALL):
            answer["quiet"] = {
                "kind": quiet_kind, "reason": state.handover_reason, "since": state.handed_over_at.isoformat(), "message": message.pk,
            }
        if quiet_kind == people.QUIET_CALL:
            # The call's time is theirs only as an hour in their own words (people.settle reads it the same way).
            start = people.call_time(answer, said_words, now) if people.call_hour(said_words, now) else None
            answer["call"] = {"start": start.isoformat() if start else None, "words": " ".join(said_words.split())[:255]}
        holding = bool(text)
    elif answer.get("not_a_shop"):
        # Someone who wants no shop to rent (the owner's rule): thanks, the options across Dubai, the
        # invitation with two free slots, and our office's location: the Maps link and the pin, once a day.
        text = not_a_shop_text(answer["not_a_shop"], language, now)
        if not location:
            if maps and maps not in text:
                appended = maps
            elif not maps and not filters.carries_location(text, settings_row.office_address):
                appended = settings_row.office_address
            pin_now = needs.SEND_PIN
    elif answer.get("price"):
        # The price line (claims.price_turn, launch review issue 12): our lowest type, honestly, or a colleague offered.
        text = claims.price_text(answer["price"], language, settings_row.shops_facts)
    elif answer.get("open_lead"):
        # The mixed template's first yes from a lead whose studio or one-bedroom we know (batch 2e, tracks.first_yes):
        # code's opener, in the language code writes in.
        text = tracks.open_lead_text(language, answer["open_lead"].get("unit", ""), answer["open_lead"].get("clusters") or ())
    elif answer.get("res_line"):
        # The rent flow's lines (residential.render): an opener, the full-name ask or hold, the handover, a special case's.
        spec = answer["res_line"]
        text = residential.render(
            spec, language, now=now, office_address=settings_row.office_address, maps_url=maps, facts=settings_row.residential_facts,
        )
        if spec.get("kind") == "res_full_name":
            res_step = residential.FULL_NAME_STEP
        holding = spec.get("kind") == "res_handover"
        if spec.get("location") and not location:
            if maps and maps not in text:
                appended = maps
            elif not maps and not filters.carries_location(text, settings_row.office_address):
                appended = settings_row.office_address
            pin_now = needs.SEND_PIN
    elif answer.get("converted") and not answer.get("shop_step"):
        # A fixed line, never the model's words: a confirmation the office could
        # not take (_shape, written as a confirmation), a deferral, a shops broker,
        # a call request or must-answer questions handed to a person (people.settle).
        # Not over a shop step: a rent chat the model's tag moved to the shop track, whose end user gets "Sure! We have shops
        # in International City too." and the shop types list (residential_switch: converted "res_switch_shop", which no table
        # of lines holds; found by the 2e gate's round 2 tests, where it raised a KeyError).
        text = people.converted_line(answer["converted"], language, shops=shops_chat)
        if answer["converted"] == people.MUST_ANSWER and answer.get("must_answer_kept"):
            # Must-answer questions while the chat goes on (people.MUST_ANSWER_PAUSES False): the line goes with what the
            # model may say of the rest, cleaned as its own words are (no amount nobody wrote, no link, one question).
            kept, kept_filtered = filters.clean_reply(answer["must_answer_kept"], rows_context)
            text = people.with_kept(text, kept)
            if kept_filtered:
                plan["filtered"] = kept_filtered
        holding = answer["converted"] in (people.HOLDING, people.CALL_PASSED, people.CALL_ASK, people.MUST_ANSWER) and (
            answer["converted"] != people.MUST_ANSWER or answer["handover"]["needed"]
        )
    elif answer.get(unit_media.STEP):
        # Batch 2e slice E (unit_media.py): their unit's set goes from its own task (below); with none imported, code's
        # "I don't have approved pictures for this one yet, but we can show you in person." and two free slots, now.
        if answer[unit_media.STEP].get("set"):
            media_unit = answer[unit_media.STEP]
        else:
            text = unit_media.text_without_set(
                answer[unit_media.STEP], language, now, clean=lambda words: filters.clean_reply(words, rows_context)[0], ours=f"{ours}\n{our_last}"
            )
            answer["invited_to_meeting"] = bool(answer.get("invited_to_meeting") or answer[unit_media.STEP].get("slots"))
            plan["invited_to_meeting"] = answer["invited_to_meeting"]
            plan["unit_media"] = unit_media.plan_of(answer[unit_media.STEP])
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
            text = shop_flow.slots_text(language, pair, now, f"{ours}\n{our_last}", again=bool(step.get("again")))
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
            if res:
                # Two questions at most on the rent and sale tracks (a buyer's go two to a message: brief Part 5B), and
                # amounts checked from 100 up (spec §1.4.9).
                text, filtered = filters.clean_reply(
                    answer["reply"], rows_context, max_questions=residential.max_questions(decision.track), amount_floor=residential.AMOUNT_FLOOR,
                )
            else:
                text, filtered = filters.clean_reply(answer["reply"], rows_context)
            model_words = bool(text)
            gloss = bool(text) and not filtered and not answer.get("trimmed")
            if filtered:
                plan["filtered"] = filtered
            if "second_question" in filtered and offers.invitation_cut(answer, answer["reply"], text, asked):
                # The invitation went as a second question: none is counted, and no Maps link under what is left
                # (launch review issue 24: chat 88 counted twice after one, chat 119's bare link).
                plan["invitation_cut"] = True
                plan["invited_to_meeting"] = answer["invited_to_meeting"]
                plan["share_office_location"] = answer["share_office_location"]
            if not text and "amount" in filtered:
                text = rules.line("deflect", language)
                _price_alert(conversation, chat, name)
        if not text:
            fallback = {"reschedule_requested": "ask_new_time", "running_late": "ask_eta"}.get(action)
            if fallback:
                text = rules.line(fallback, language)
            elif answer["handover"]["needed"]:
                # Handed to a person and nothing usable to say: they still hear it (a shops chat's "our agent").
                text = people.line(people.HOLDING, language, shops=shops_chat)
                holding = True
        if text and answer["share_office_location"] and not location:
            # Once per chat: not when one of our messages gave it already
            # (location_sent), nor when the reply itself carries it.
            if maps and maps not in text:
                appended = maps
            elif not maps and not filters.carries_location(text, settings_row.office_address):
                appended = settings_row.office_address
    if appended:
        # Labelled as our office's (launch review issue 24): a bare link read as the shops' location.
        text = offers.with_location(text, appended, language)
        plan["location_appended"] = True
    # A tap sent with typed words (tap_with_words): the model's answer to the words goes before the tap's step.
    step_words = ""
    if (media_type or list_step) and answer.get("step_words"):
        step_words, _ = filters.clean_reply(answer["step_words"], rows_context)
        if step_words:
            plan["step_words"] = True

    if media_unit is not None:
        # Batch 2e slice E (unit_media.py): the model's statements now, then the set's photos (the caption on the first)
        # and the question after them from their own task (tasks.send_unit_media), as a shop type's media go.
        answer["invited_to_meeting"] = bool(answer.get("invited_to_meeting") and media_unit.get("after")) or bool(media_unit.get("slots"))
        answer["share_office_location"] = False
        plan["invited_to_meeting"] = answer["invited_to_meeting"]
        plan["unit_media"] = unit_media.plan_of(media_unit)
        done = _apply(
            conversation, chat, state, answer, action, when, appointment, now, sent=True, holding=False, playbook=playbook,
            taken=taken, decision=decision,
        )
        done.update(plan)
        words_sent = unit_media.deliver(conversation, media_unit, turn.pk, language, clean=lambda words: filters.clean_reply(words, rows_context)[0])
        LeadAiTurn.objects.filter(pk=turn.pk).update(
            actions={**(turn.actions or {}), **done}, **({"reply_message": words_sent} if words_sent is not None else {})
        )
        return Outcome(
            LeadAiTurn.Status.REPLIED, f"unit photos queued ({media_unit.get('name')})", reply_message_id=words_sent.pk if words_sent else None,
            actions=done,
        )

    if media_type:
        # Nothing goes out in this turn: the video, the photos and the detail card follow from
        # their own task, outside the turn's time (shop_media.send_type), which never fails it.
        answer["invited_to_meeting"] = answer["share_office_location"] = False
        words_sent = None
        if step_words:
            try:
                words_sent = _send(conversation, step_words, turn)
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - the type's media still go
                logger.warning("Lead AI could not send the words before the shop media on conversation %s: %s", conversation.pk, exc)
        done = _apply(
            conversation, chat, state, answer, action, when, appointment, now, sent=True, holding=False, playbook=playbook,
            taken=taken, decision=decision,
        )
        done.update(plan)
        LeadAiTurn.objects.filter(pk=turn.pk).update(
            actions={**(turn.actions or {}), **done}, **({"reply_message": words_sent} if words_sent is not None else {})
        )
        from ..tasks import send_shop_media

        transaction.on_commit(
            lambda pk=conversation.pk, kind=media_type, turn_pk=turn.pk, lang=language, files=media_files: send_shop_media.delay(
                pk, kind, turn_pk, lang, files
            )
        )
        what = "media" if media_files else "card"
        return Outcome(
            LeadAiTurn.Status.REPLIED, f"shop {what} queued ({media_type})", reply_message_id=words_sent.pk if words_sent else None,
            actions=done,
        )

    if not text and not list_step:
        done = _apply(
            conversation, chat, state, answer, action, when, appointment, now, sent=False, holding=False, playbook=playbook,
            taken=taken, decision=decision,
        )
        done.update(plan)
        return _skip("no reply needed", **done)

    try:
        extra = {}
        reply_en = answer["reply_en"].strip()
        if gloss and answer["language"] != "en" and reply_en and not _same_words(reply_en, answer["reply"]):
            # For the agents, what the customer reads in English: only for a reply
            # in another language, sent whole, with the line code added to it.
            extra["reply_en"] = (offers.with_location(reply_en, appended, "en") if appended else reply_en)[:600]
        if booking:
            extra["booking"] = booking
        if step_marker:
            extra["shop_step"] = step_marker
        if res_step:
            extra["res_step"] = res_step
        if list_step:
            from .. import shop_media

            if step_words:
                _send(conversation, step_words, turn)
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
    answer["copilot_sent"] = text  # what went out: the co-pilot keeps the model's words only when they differ (copilot.remember)
    done = _apply(
        conversation, chat, state, answer, action, when, appointment, now, sent=True, holding=holding, playbook=playbook,
        taken=taken, decision=decision,
    )
    if hold is not None:
        hold.close()  # the booking is stored: the next one may look at the slots
    done.update(plan)
    if pack_flow and units and state.handed_over_at is None and residential._quotes_a_unit(text, units):
        # The community packs' flow (round 17): the listed unit the reply quoted gets its Property Finder photos, once per
        # unit per chat, from its own task after the commit (pack_photos.queue).
        from .. import pack_photos

        quoted = inventory.by_reference(units, text)
        if quoted is not None and pack_photos.queue(conversation, state, quoted, turn.pk, language):
            done["pack_photos"] = quoted.reference or str(quoted.pk)
    # The booking is stored: the turn row says so before the slower pin goes out.
    turn.reply_message_id = sent.pk
    LeadAiTurn.objects.filter(pk=turn.pk).update(reply_message=sent, actions={**(turn.actions or {}), **done})

    # SALE (slice C): a buyer's call needs no office pin (our sales team calls them on this number).
    if (done.get("appointment", {}).get("event") in ("confirmed", "rescheduled") or pin_now) and settings_row.has_pin and calls.needs_pin(answer):
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
    taken=(), decision=None,
) -> dict:
    """Store what this turn decided, after the reply went out (or when none was needed).

    ``action`` is the effective action, including the engine's own
    "reconfirm", "reschedule_requested" and "on_time". A shops chat's
    check-back ("Should I check back with you in a month?") is opened, answered
    (a follow-up a month from now) or closed by any other reply we send, and its
    lead's fields go to Bitrix (crm_fields). The reply of the turn that learned
    they already rented a shop is marked ("rented_asked"): a plain no to it, and
    only to it, closes the lead (_shops_rule_for). ``taken``: the other chats'
    office starts; a tentative visit never keeps one of those as its time. A shops
    customer who wants no shop to rent, or now wants something else (facts.wanted
    new or changed: who_they_are), is told to the team (_wanted_alert) and written on
    the lead's timeline, whatever went out. A shops chat's track and unit (``decision``:
    tracks.decide, batch 2e) are stored whatever went out, and when the track moves,
    its moment (track_changed_at).
    """
    from ..tasks import record_crm_note, sync_appointment_crm

    done: dict = {}
    shops_chat = playbook == lane.IC_SHOPS
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        facts_before = dict(fresh.facts or {})
        fresh.facts = _merge_facts(fresh.facts, answer["facts"])
        for key in answer.get("forget") or ():
            # A want the chat read wrong (who_they_are): they asked for a shop after all.
            fresh.facts.pop(key, None)
            done["forgot"] = list(answer["forget"])
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
        # The co-pilot (copilot.py): from the turn that hands the chat over, and on every turn while a person has it,
        # the model's own words — the ones code did not send — wait for the agent as a draft.
        if answer.get("copilot_draft") and (handover["needed"] or fresh.handed_over_at is not None or answer.get("broker")):
            reason = fresh.handover_reason or str(handover.get("reason") or "") or (BROKER if answer.get("broker") else "unclear")
            draft = copilot.remember(
                answer, now, reason=reason, language=str(answer.get("line_language") or answer.get("language") or fresh.language or "")
            )
            if draft:
                fresh.draft = draft
                fields.append("draft")
                done["draft"] = draft["kind"]
        if sent and action in ("confirm", "reschedule") and when is not None and fresh.not_interested_at is not None:
            fresh.not_interested_at = None  # they declined once, and have now booked
            fields.append("not_interested_at")
        if decision is not None and (decision.track, decision.unit) != (fresh.track or "", fresh.unit or ""):
            # Which need the chat serves (tracks.decide): code's own, stored in shadow in slice A.
            if decision.track != (fresh.track or ""):
                fresh.track_changed_at = now
                fields.append("track_changed_at")
                done["track_changed"] = {"from": fresh.track or "", "to": decision.track}
            fresh.track, fresh.unit = decision.track, decision.unit
            fields += ["track", "unit"]
        fresh.save(update_fields=sorted(set(fields)))
        facts = fresh.facts
        if shops_chat and sent and facts.get("already_rented") is True and facts_before.get("already_rented") is not True:
            # This reply congratulated them and asked about a second shop (SHOPS_SYSTEM).
            done["rented_asked"] = True
        if shops_chat and facts.get(needs.WANTED) and facts.get(needs.WANTED) != facts_before.get(needs.WANTED):
            # They want no shop to rent, or now want something else again: the team is told (who_they_are).
            done["wanted"] = facts[needs.WANTED]

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
            if proposal.get("place") == calls.PLACE:
                # SALE (slice C): a buyer's call, booked in the call pool (only the sale track ever confirms one).
                calls.mark(current)
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
                # A time held for the full name keeps its marks while it stays a tentative (residential.held_details), and a
                # buyer's call held for it is the call pool's (SALE, slice C: sales.mark_hold).
                current.details = {**_details(facts), **(residential.held_details(current.details) if not is_new else {})}
                sales.mark_hold(current, answer)
                current.log("tentative", note=note, place=place, start=start.isoformat() if start else None)
                current.save()
                crm_event = "tentative"
                done["appointment"] = {"id": current.pk, "event": "tentative", "place": place, "new": is_new}
        elif action == "tentative" and confirmed and answer.get("hold_for_name"):
            # A move to a new time with no full name (spec §2.6): the booking keeps its time, the new one is held on it while
            # code asks for the name (residential.mark_move_hold), and booked once it comes (residential.name_turn).
            if residential.mark_move_hold(current, answer, now, sent=sent):
                current.log("move_held", start=(current.details or {}).get(residential.HELD_MOVE, {}).get("start"))
                current.save(update_fields=["details", "history", "updated_at"])
                done["appointment"] = {"id": current.pk, "event": "move_held"}
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
                # A full-name hold keeps its marks (residential.held_details), a buyer's call its own (SALE: calls.kept_details).
                current.details = calls.kept_details({**_details(facts), **residential.held_details(current.details)}, current)
                current.save(update_fields=["details", "updated_at"])
        if shops_chat and current is not None and current.pk and current.status == LeadAiAppointment.Status.TENTATIVE:
            # The rent flow's full-name hold (spec §2.6): the tentative that keeps their time from other chats, how often we
            # asked, and their no (the team is alerted: Needs a person on the Lead AI screen until the hold lapses).
            if residential.mark_hold(current, answer, now, sent=sent):
                current.save(update_fields=["details", "updated_at"])
                if answer.get("name_refused"):
                    done["name_refused"] = True
                    _name_hold_alert(conversation, chat, current, name, facts)
        elif (
            shops_chat and current is not None and current.pk and current.status == LeadAiAppointment.Status.CONFIRMED
            and answer.get("hold_for_name") is not True and (answer.get("hold_for_name") or answer.get("name_refused"))
            and (current.details or {}).get(residential.HELD_MOVE)
        ):
            # A move held for the full name: our ask repeated, or their no (the booking keeps its time; the team is alerted).
            if residential.mark_move_hold(current, answer, now, sent=sent):
                current.save(update_fields=["details", "updated_at"])
                if answer.get("name_refused"):
                    done["name_refused"] = True
                    _name_hold_alert(conversation, chat, current, name, facts)

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
            # A new tentative with a handover is in the handover's alert, and a call's time while a person has the
            # chat in its own (_quiet_alert): one alert each.
            quiet_call = (answer.get("quiet") or {}).get("kind") == people.QUIET_CALL
            if not (crm_event == "tentative" and ((done.get("appointment", {}).get("new") and done.get("handover")) or quiet_call)):
                appointment_alert(conversation, chat, current, crm_event, hot, name, revision)
        if done.get("handover"):
            moment = fresh.paused_at if done.get("broker") else fresh.handed_over_at
            _handover_alert(
                conversation, chat, current, done["handover"], name, facts, moment, broker=bool(done.get("broker")),
                words=str(answer.get("their_words") or ""), questions=answer.get("must_answer") or (),
                question_words=str(answer.get("must_answer_words") or ""), call=answer.get("call"),
            )
            if done["handover"] == "call_requested" or answer.get("call"):
                # The lead's timeline says a call was asked for, and the time they gave (launch chat 88: the team
                # never got the time, and nobody called).
                note = people.call_note_lines(answer.get("call"), current)
                transaction.on_commit(lambda pk=conversation.pk, lines=note: record_crm_note.delay(pk, "call", lines))
        if answer.get("questions_waiting") and not done.get("handover"):
            # Must-answer questions while the chat goes on (people.MUST_ANSWER_PAUSES False): a person answers them, and is
            # told now; people.escalate_waiting tells them again if nobody did in ESCALATE_AFTER of office time.
            done["questions_alert"] = list(answer.get("must_answer") or ())
            _questions_alert(conversation, chat, name, facts, answer, now)
        if answer.get("quiet"):
            # A person has the chat, and they chased us or gave their call's time: the team hears it again, now.
            done["quiet_alert"] = answer["quiet"]["kind"]
            _quiet_alert(conversation, chat, fresh, answer, name, facts, current)
        if done.get("wanted"):
            words = str(answer.get("need_words") or "")
            invited = bool(sent and answer.get("not_a_shop"))
            _wanted_alert(conversation, chat, name, facts, words, invited=invited, also=str(answer.get("need_dropped") or ""))
            lines = wanted_note_lines(facts, words, invited=invited)
            transaction.on_commit(lambda pk=conversation.pk, note=lines: record_crm_note.delay(pk, "wanted", note))
        elif shops_chat and answer.get("need_dropped") and needs.of(facts) is not None:
            # A handover taken off a chat that wants no shop (untag_need: a visa question, a photo, a price insisted on):
            # the chat goes on, and the team hears what they asked, so it is answered (review 2d).
            done["need_dropped"] = answer["need_dropped"]
            _wanted_alert(
                conversation, chat, name, facts, str(answer.get("their_words") or ""), invited=False, also=answer["need_dropped"], moment=now,
            )
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
            # A studio or a one-bedroom to rent or buy (batch 2e, spec §5): its own fields in the same batch (RES_FIELDS_LIVE).
            writes += crm_fields.residential_writes(
                facts, fresh.track, fresh.unit, words=str(answer.get("their_words") or ""), besides=writes
            )
            if crm_fields.queue(conversation, chat, writes):
                done["crm_fields"] = [field for field, _, _ in writes]
    # The customer memory (memory.py): this chat's facts and bookings kept by the phone, for the chats on other numbers.
    try:
        memory.remember(conversation, fresh.facts, fresh.language, now, booking=done.get("appointment"))
    except Exception as exc:  # noqa: BLE001 - the reply went out; the memory is a record
        logger.warning("Lead AI memory not kept for conversation %s: %s", conversation.pk, exc)
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
        # A shops customer who wants no shop to rent (needs.py).
        (needs.WANTED, "Wants"),
    )
    out = []
    for key, label in labels:
        value = facts.get(key)
        if key == "business_activity" and value and not crm_facts.is_business(value):
            continue  # a home they want or a sentence, kept by a chat from before (crm_facts.is_business)
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
    # A shops chat's questions for the viewing, never one of ours (crm_facts.own_notes; a general chat's notes are
    # text, not shown here).
    notes = crm_facts.own_notes(facts.get("notes")) if isinstance(facts.get("notes"), list) else None
    if notes:
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
    if calls.alert(conversation, appointment, event, who, details, stamp=stamp, crm_url=crm_url):
        return  # SALE (slice C): a buyer's call booked, moved or held: "Sales call: {name}, {when}" (spec §3.3.4)
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
    # Set by code: a shops customer's must-answer questions (people.settle), never the model's own reason.
    people.MUST_ANSWER_REASON: "asked questions a person must answer before any visit",
}


_WANTED_HEAD = {
    needs.HOME: "wants {what}, not a shop",
    needs.BUY: "wants {what}",
    needs.SELL: "wants {what}",
    needs.NEVER_ASKED: "says they never asked about a shop and want none",
    needs.OTHER: "wants {what}, not one of these shops",
}


def _wanted_line(facts: dict) -> str:
    need = needs.of(facts) or needs.Need(needs.OTHER)
    return _WANTED_HEAD.get(need.kind, "wants {what}").format(what=str(facts.get(needs.WANTED) or need.what))


def _wanted_alert(
    conversation, chat, name: str, facts: dict, words: str, *, invited: bool, also: str = "", moment=None
) -> None:
    """The team hears what a shops customer wants instead of a shop to rent (the owner's rule,
    2026-10-15): the Lead AI alert list (LISTED_KINDS) and the lead's owner, so a person can prepare
    options. The chat goes on: the assistant keeps arranging their visit to the office. ``also``: a
    handover reason untag_need took off (a visa question, a photo sent), said in the alert so a person
    answers it; with ``moment``, the alert is that question's alone (the want was alerted before)."""
    who = name or "A Lead AI customer"
    asked = HANDOVER_TEXT.get(also, "") if also else ""
    lines = [f"{who} (WhatsApp +{conversation.contact.wa_id}) {_wanted_line(facts)}."]
    if asked:
        lines.append(f"They also {asked}: please answer them here (the assistant did not hand the chat over, by the owner's rule).")
    if words:
        lines.append(f"Their words: {crm.safe(words)[:200]}")
    lines += [line for line in _detail_lines(facts) if not line.startswith("Wants:")]
    lines.append(
        "No customer is lost (owner's rule): the assistant sent our office location and invited them to visit for options, "
        "and keeps arranging the visit here. Please prepare options for them."
        if invited
        else "No customer is lost (owner's rule): please prepare options for them; the assistant keeps arranging their visit here."
    )
    key = f"wanted:{conversation.pk}:{hashlib.sha1(str(facts.get(needs.WANTED) or '').encode()).hexdigest()[:12]}"
    if moment is not None:
        key = f"{key}:{also}:{moment:%Y%m%d%H%M%S}"
    alerts.raise_alert(
        kind="wanted",
        conversation=conversation,
        priority=needs.ALERT_PRIORITY,
        title=(f"{who} {_wanted_line(facts)}" if moment is None else f"{who} ({_wanted_line(facts)}) {asked or 'needs a person'}")[:200],
        text="\n".join(lines),
        dedupe_key=key,
        crm_url=_crm_url(chat),
    )


def wanted_note_lines(facts: dict, words: str, *, invited: bool = True) -> list[str]:
    """The lead's timeline note for what they want (tasks.record_crm_note, crm.note_text)."""
    lines = [f"Wants: {crm.safe(facts.get(needs.WANTED) or '')}"]
    if words:
        lines.append(f"Customer's words: {crm.safe(words)[:200]}")
    lines.append(
        "Not a shop lead for this campaign: the assistant invited them to our office for options (the lead stays open)."
        if invited
        else "Not a shop lead for this campaign: please prepare options for them (the lead stays open)."
    )
    return lines


def broker_label():
    """The inbox label of a broker's chat: one named "Broker" in any case, made the way the inbox makes labels."""
    from apps.inbox.models import Label

    label = Label.objects.filter(name__iexact=BROKER_LABEL).order_by("pk").first()
    if label is None:
        label, _ = Label.objects.get_or_create(name=BROKER_LABEL, defaults={"colour": BROKER_COLOUR})
    return label


def _handover_alert(
    conversation, chat, appointment, reason: str, name: str, facts: dict, handed_over_at, *, broker: bool = False, words: str = "",
    questions=(), question_words: str = "", call: dict | None = None,
) -> None:
    """``broker``: the chat was labelled and paused for a broker just now (_apply). The alert carries their last
    words (``words``), the lead and where the chat is (people.where_lines, launch review issue 3), a call's time
    as they gave it (``call``, people.call_lines; issue 4) and must-answer questions listed (``questions``, with
    ``question_words`` in full; issue 14). It reaches the Lead AI alert list too (kind handover, LISTED_KINDS)."""
    who = name or "A Lead AI customer"
    # Where they are comes right after the headline: Bitrix shows the first MESSAGE_MAX characters only.
    lines = [f"{who} (WhatsApp +{conversation.contact.wa_id}) {HANDOVER_TEXT.get(reason, 'needs a person')}.", *people.where_lines(conversation, chat)]
    quoted = ""
    if reason == "owner_viewing_slot" and appointment is not None:
        if appointment.starts_at:
            lines.append(f"Offered: {hours.describe(appointment.starts_at)}")
        if appointment.customer_words:
            lines.append(f"Their words: {appointment.customer_words}")
            quoted = appointment.customer_words
    if reason == "call_requested" or call:
        # A call asked for (with a complaint or a request for a person too): the time they gave, never ours.
        call_appointment = appointment if appointment is not None and appointment.place == LeadAiAppointment.Place.CALL else None
        lines += [line for line in people.call_lines(call, call_appointment) if line]
        quoted = (call or {}).get("words") or (call_appointment.customer_words if call_appointment is not None else "")
    if questions:
        lines.append("Questions to answer before any visit: " + "; ".join(questions))
        lines.append(people.words_line(question_words or words, "Their questions", people.MUST_ANSWER_WORDS_MAX))
        quoted = question_words or words
    if words and not _same_words(words, quoted) and not questions:
        lines.append(people.words_line(words))
    lines += _detail_lines(facts)
    if broker:
        campaign = chat.campaign if chat is not None and chat.campaign_id else None
        if campaign is not None:
            lines.append(f"Campaign: {campaign.name}")
        lines.append(
            f'The chat is labelled "{BROKER_LABEL}", and the assistant stays silent in it until someone presses Resume AI.'
        )
    elif reason == "call_requested":
        timed = bool((call or {}).get("start")) or people.call_hour((call or {}).get("words") or "")
        lines.append(
            "The assistant promised no time: "
            + ("it told them our agent will confirm the call here" if timed else "it asked them which time suits them for the call")
            + ", and is now quiet in this chat until someone from the team writes. Please call them."
        )
    elif questions:
        lines.append(
            "The assistant told them our agent will answer these here before any visit, and is now quiet in this chat until "
            "someone from the team writes."
        )
    else:
        lines.append("The assistant is now quiet in this chat until someone from the team writes.")
    lines = [line for line in lines if line]
    # One alert per handover (the moment it began), not one per reason and day:
    # a second request for a person later the same day is alerted again.
    moment = f"{handed_over_at:%Y%m%d%H%M%S}" if handed_over_at else f"{timezone.now():%Y%m%d%H%M%S}"
    alerts.raise_alert(
        kind="handover",
        conversation=conversation,
        appointment=appointment,
        priority="high" if reason in HIGH_HANDOVER or reason == people.MUST_ANSWER_REASON else "normal",
        title=f"{who}: {HANDOVER_TEXT.get(reason, 'needs a person')}",
        text="\n".join(lines),
        dedupe_key=f"handover:{conversation.pk}:{moment}",
        crm_url=_crm_url(chat),
    )


def _name_hold_alert(conversation, chat, appointment, name: str, facts: dict) -> None:
    """A rent or sale customer wants a time and will not give their full name (spec §2.6): no booking, the time is held,
    and a person confirms it with them (high priority, the chat's people and the Lead AI alert list)."""
    who = name or "A Lead AI customer"
    held = residential.held_start(appointment) or appointment.starts_at
    when = hours.describe(held) if held else "a time"
    move = appointment.status == LeadAiAppointment.Status.CONFIRMED and appointment.starts_at and held != appointment.starts_at
    lines = [
        f"{who} (WhatsApp +{conversation.contact.wa_id}) wants {when} and gave no full name, so the assistant did not "
        + (f"move their booking of {hours.describe(appointment.starts_at)} to it." if move else "book it."),
        *people.where_lines(conversation, chat),
        *_detail_lines(facts),
        "Their booking keeps its time. Please confirm the new one with them in the chat." if move else
        "The time is held for them (no other chat can take it) until the hold lapses. Please confirm it with them in the chat.",
    ]
    alerts.raise_alert(
        kind="tentative",
        conversation=conversation,
        appointment=appointment,
        priority="high",
        title=f"{who} wants {when}: no full name yet"[:200],
        text="\n".join(line for line in lines if line),
        dedupe_key=f"name_hold:{conversation.pk}:{appointment.pk}",
        crm_url=_crm_url(chat),
    )


def _questions_alert(conversation, chat, name: str, facts: dict, answer: dict, now) -> None:
    """A shops customer's must-answer questions, while the assistant goes on with the chat (people.MUST_ANSWER_PAUSES
    False): the chat's people and the Lead AI alert list (people.QUESTIONS is listed), high priority, with the questions
    listed and their words in full (chat 95 asked nine). Once per turn that asked them."""
    who = name or "A Lead AI customer"
    lines = [
        f"{who} (WhatsApp +{conversation.contact.wa_id}) asked questions a person must answer before any visit.",
        *people.where_lines(conversation, chat),
        "Questions to answer before any visit: " + "; ".join(answer.get("must_answer") or ()),
        people.words_line(str(answer.get("must_answer_words") or answer.get("their_words") or ""), "Their questions", people.MUST_ANSWER_WORDS_MAX),
        *_detail_lines(facts),
        "The assistant told them our agent will answer these here before the visit, and keeps arranging the visit meanwhile. "
        "Please answer them in the chat.",
    ]
    alerts.raise_alert(
        kind=people.QUESTIONS,
        conversation=conversation,
        priority="high",
        title=f"{who}: questions to answer before any visit"[:200],
        text="\n".join(line for line in lines if line),
        dedupe_key=f"{people.QUESTIONS}:{conversation.pk}:{now:%Y%m%d%H%M%S}",
        crm_url=_crm_url(chat),
    )


def _quiet_alert(conversation, chat, state, answer: dict, name: str, facts: dict, appointment) -> None:
    """A person has the chat and nobody wrote yet, and the customer chased us ("will i get any call??") or gave
    the time of the call they asked for: the chat's people and the Lead AI alert list hear it now, high priority
    (launch chat 88's chase got only the holding line, and nobody heard of it). A call's time also goes on the
    lead's timeline (tasks.record_crm_note "call"). Once per message of theirs."""
    from ..tasks import record_crm_note

    quiet = answer.get("quiet") or {}
    who = name or "A Lead AI customer"
    reason = quiet.get("reason") or state.handover_reason
    since = state.handed_over_at
    words = str(answer.get("their_words") or "")
    call_appointment = appointment if appointment is not None and appointment.place == LeadAiAppointment.Place.CALL else None
    if quiet.get("kind") == people.QUIET_CHASE and alerts_recent(conversation, people.QUIET_CHASE, people.CHASE_ALERT_EVERY):
        return  # "Hello?", "??", "anyone there?" a minute apart: one urgent alert, not one each (review 2d)
    if quiet.get("kind") == people.QUIET_CHASE:
        lines = [
            f"{who} (WhatsApp +{conversation.contact.wa_id}) is still waiting for us: they {HANDOVER_TEXT.get(reason, 'need a person')} "
            f"at {transcript.stamp(since)}, and nobody from the team has written in the chat since." if since
            else f"{who} (WhatsApp +{conversation.contact.wa_id}) is still waiting for us.",
            *people.where_lines(conversation, chat),
            people.words_line(words),
        ]
        if call_appointment is not None or reason == "call_requested":
            lines += [line for line in people.call_lines(None, call_appointment) if not line.startswith("Their words")]
        lines.append("The assistant apologised and said our agent will reply here. Please reply or call them now.")
        kind, title = people.QUIET_CHASE, f"{who} is still waiting for us"
    else:
        call = answer.get("call") or {}
        lines = [
            f"{who} (WhatsApp +{conversation.contact.wa_id}) "
            + ("gave the time for the call they asked for." if call.get("start") or people.call_hour(call.get("words") or "") else "asked for a call."),
            *people.where_lines(conversation, chat),
            *[line for line in people.call_lines(call, call_appointment) if line],
            "The assistant promised no time: it said our agent will confirm the call here. Please call them.",
        ]
        kind, title = "call_time", f"{who}: a call to make"
        note = people.call_note_lines(call, call_appointment, again=True)
        transaction.on_commit(lambda pk=conversation.pk, lines=note: record_crm_note.delay(pk, "call", lines))
    alerts.raise_alert(
        kind=kind,
        conversation=conversation,
        appointment=appointment,
        priority="high",
        title=title[:200],
        text="\n".join(line for line in lines if line),
        dedupe_key=f"{kind}:{conversation.pk}:{quiet.get('message') or f'{timezone.now():%Y%m%d%H%M%S}'}",
        crm_url=_crm_url(chat),
    )


def alerts_recent(conversation, kind: str, within: dt.timedelta) -> bool:
    """An alert of this kind went for this chat in the last ``within``."""
    from ..models import LeadAiAlert

    return LeadAiAlert.objects.filter(conversation=conversation, kind=kind, created_at__gte=timezone.now() - within).exists()


def person_wrote_since(conversation, since) -> bool:
    """Someone from our team wrote in this chat since then (panel, phone app, anything but ours or the campaign's
    own templates): what human_after reads, for a moment instead of a message (people.escalate_waiting)."""
    campaign_templates = transcript.campaign_template_ids(conversation)
    rows = (
        Message.objects.filter(conversation_id=conversation.pk, direction=Message.Direction.OUTBOUND, mirrored_from__isnull=True)
        .exclude(kind="system")
        .filter(created_at__gte=since)
    )
    for row in rows.only("pk", "kind", "payload", "template_id"):
        if transcript.is_ours(row):
            continue
        if row.kind == Message.Kind.TEMPLATE and row.template_id in campaign_templates:
            continue
        return True
    return False
