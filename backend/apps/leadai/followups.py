"""The shops playbook's automatic follow-ups (board T63, T25, T29; owner's choice Q7, 2026-10-14).

Matloob sends every campaign himself; what follows it is automatic, in chats whose playbook is
ic_shops (lane.playbook_for), and only while the chat is the assistant's: on the Lead AI screen,
not transferred, the assistant answering this customer, not stopped, paused, handed to a person
or "not interested", and the phone not on the opt-out registry (optout.py). Nothing goes while
the gateway's credit is out (gateway.credit, board C16): it waits.

- Template B, once (T63): intl_city_shops_followup from the chat's own number, when the shops
  campaign's template went out (sent, delivered or read) 72 hours to 14 days ago and nothing
  happened in the chat since: no word, tap or reaction from the customer, no message of ours or
  a colleague's. It is the second message after that send and the last one
  (``template_b_sent_at``); only a campaign sent to the lead again later has its own.
- The check-back (T25): the same Template B once, on the day a customer who said "Not now" asked
  us to check back (``followup_due_at``, cleared then; ``followup_sent_at``), and only while
  nothing happened in the chat since our "I'll check back with you": no word from the customer
  but a "thanks" or an emoji, and nothing from a colleague or from us (``engaged_since``). A
  chat taken up again is no longer waiting: its date is cleared (here, and by the turn that
  answers the customer, engine._apply), and the nudges may follow it.
- Both go only from 11:00 to 18:00 Dubai, Monday to Saturday, never on a closed date, and only
  where the template is APPROVED on the chat's own WABA; otherwise they wait, and the sweep
  looks again every minute. While the template is not approved the chat's row on the Lead AI
  screen says so (``panel_note``): a note, never an alert. A campaign sent with Template B
  itself gets no second copy of it.
- The nudges (T29, assistant/nudges.py): free-form, inside the 24-hour window with ten minutes
  to spare, when the assistant's own message is the last in the chat, reached WhatsApp, and
  asked something or invited them, nothing is booked, they were not invited twice already, and
  the customer has been silent two hours: the first nudge; the morning after at 10:30, still
  silent, the last one. Never more than two in a chat, and none after "Not now" or "I already
  rented". A customer who wants no shop to rent (assistant/needs.py, the owner's rule of
  2026-10-15) is nudged only about the visit ("to see the options"), and never gets Template B.
  Our "for yourself, or for a client?" still open is asked again, never skipped by an invitation.
- What holds every follow-up for good (``holds``; launch review 2026-10-15, issues 9 and 23), read
  from the chat since its newest campaign template or Template B: a decline of our offer, a "Not
  now" (answered check-back or not), a shop rented elsewhere (until they say yes to a second one), a
  reply-cap skip still pending. Only a later yes of theirs to an offer of ours (a template's yes tap
  after anything), or a day or an hour they name to come (no hedge), takes a decline or a "Not now"
  back, as does a customer who came back by themselves after "I'll check back with you then". And for
  the nudges, first, a question of theirs our last words left to a colleague ("I'll have our agent
  confirm that at the viewing", ``question_left``): no push, a person is alerted instead, once for
  those words (OPEN_QUESTION). Handed over, paused, stopped: ``blocked`` as ever. A check-back
  question nobody answered gets nothing (CHECK_BACK_SILENCE, Matloob's open question).
- Before any of them goes, the chat's Bitrix lead is read once (``bitrix_blocks``): a Bot Status
  a person set (Handed to agent, Broker, Lost, Opted out) or WhatsApp Opt-out Yes holds it, and
  is applied as if Bitrix had told us (bitrix_status.apply), because that call from Bitrix is
  made once and never retried (board C12). A meeting on the lead or a closed stage holds it too,
  and for a customer who wants no shop to rent a person's work on the lead in the last days
  (review 2d). A lead that cannot be read now: the send waits.
- Template B and the check-back follow a shops template only (batch 2e spec §6.1, ic_templates.kind):
  Template B is all shops, so a chat whose newest campaign template is the mixed one never gets it
  (``reengage_due``; ``holds``: HELD_NOT_SHOP_TEMPLATE), nobody who never answered the mixed template
  gets anything (the brief, Part 12.5), a check-back planned there is dropped on its day until slice B
  sends the mixed template instead, and its row shows no "waits for approval" note (``panel_note``).

The sweep (tasks.send_due_reminders, every minute) only finds who is due and queues one task per
chat (tasks.send_follow_up), at most PER_SWEEP at a time. What keeps a chat from being due for
days (stopped, paused, handed over, not interested, on the registry, the template not approved
on its number, the campaign's template failed, a check-back nothing waits for) is filtered in
the query itself, and the rest is read a page at a time until PER_SWEEP are found, so chats
turned down never hide a due one further on. The task decides again, claims the chat's state
with one conditional update (two tasks never both send), sends outside any transaction, and
gives the claim back only when nothing reached the gateway or the gateway was out of credit: a
send that may have gone out is never repeated. A send refused for credit leaves its row FAILED;
that row is marked (payload ``attempt_failed``) and read past from then on, so the chat is due
again once the wallet is topped up. Template B is stored as ours (payload source
transcript.FOLLOW_UP) and read like the campaign it follows up (transcript.who): [Yes, book a
viewing] is a first answer, [Not now] the check-back's question. A nudge is the assistant's own
message (source leadai_ai, ``nudge`` 1 or 2).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from functools import cached_property

from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import CharField, DateTimeField, Exists, F, OuterRef, Q, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from apps.inbox.models import Message

from . import ic_templates, lane, shop_templates
from .assistant import hours, needs, nudges, rules, shops, transcript
from .models import LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiOptOut, LeadAiSettings, LeadAiTurn

logger = logging.getLogger(__name__)

TEMPLATE_B = shop_templates.FOLLOWUP_NAME
SOURCE = transcript.FOLLOW_UP
AFTER_CAMPAIGN = dt.timedelta(hours=72)
# Older than this, a campaign nobody answered gets no "quick follow-up" any more.
NOT_AFTER = dt.timedelta(days=14)
SEND_FROM = dt.time(11, 0)
SEND_UNTIL = dt.time(18, 0)
PER_SWEEP = 30
# The sweep reads its candidates this many at a time ...
SCAN = 200
# ... and at most this many of one kind in a minute (a safety valve: the query leaves hardly
# any that are not due).
READ_AT_MOST = 2000
# A conversation's last_message_at is stamped a moment after its message is stored.
SLACK = dt.timedelta(minutes=5)
SENT_STATUSES = (Message.Status.SENT, Message.Status.DELIVERED, Message.Status.READ)
# Invited twice and refused: no third invitation, in any words (engine.settle), so no nudge.
INVITED_TWICE = 2
# Our "I'll check back with you" goes in the turn that plans the check-back, a moment after
# that turn's own clock: within this long it is that confirmation, not a message since.
CONFIRM_SLACK = dt.timedelta(minutes=5)
# A row a send refused for "Insufficient credits" left behind (payload key): read past.
ATTEMPT_FAILED = "attempt_failed"
NO_CREDIT = "no_credit"

REENGAGE = "template_b"
CHECK_BACK = "check_back"
NUDGE_1 = "nudge_1"
NUDGE_2 = "nudge_2"
# The first nudge's moment, with a question of theirs left to a colleague: an alert to a person instead.
OPEN_QUESTION = "open_question"
KINDS = (REENGAGE, CHECK_BACK, NUDGE_1, NUDGE_2, OPEN_QUESTION)

# Why a follow-up never goes to a chat (holds).
HELD_RENTED = "they rented a shop elsewhere"
HELD_NO_SHOP = "they want no shop to rent (Template B is all shops)"
HELD_DECLINED = "they turned our offer down"
HELD_NOT_NOW = "they said not now"
HELD_CAPPED = "their message waits for the reply cap"
HELD_QUESTION = "a question of theirs waits for a colleague's answer"
# Batch 2e (spec §6.1): Template B is all shops, so it follows a shops campaign template only, never the mixed one.
HELD_NOT_SHOP_TEMPLATE = "the campaign template was not a shops one (Template B is all shops)"
# The guard, one constant: Template B and the check-back only after a shops template.
TEMPLATE_B_AFTER_SHOPS_ONLY = True
# A follow-up reads back at most this many of the chat's newest messages (a shops chat has far fewer).
READ_BACK = 200
# How much of their words an open-question alert carries (a person answers them: chat 95 asked nine).
QUESTION_WORDS_MAX = 900
# A "Not now" whose check-back question ("Should I check back with you in a month?") was never answered
# (launch chat 87; Matloob's open question, 2026-10-15), once CHECK_BACK_SILENT_FOR has passed: None,
# nothing follows, no nudge and no Template B (the safe default); SILENCE_IS_YES, the silence counts as a
# yes and Template B goes a month after the question, as for a yes (shops.FOLLOW_UP_AFTER);
# SILENCE_IS_LOST, the lead closes as Lost (engine.record_opt_out, reason SILENT_LOST_REASON).
SILENCE_IS_YES = "template_b"
SILENCE_IS_LOST = "lost"
CHECK_BACK_SILENCE = None
CHECK_BACK_SILENT_FOR = shops.FOLLOW_UP_AFTER
SILENT_LOST_REASON = "no answer to the check-back question"


# The rules ------------------------------------------------------------------------------------


def send_hours(now, closed_dates=()) -> bool:
    """Template B's hours: 11:00 to 18:00 Dubai, Monday to Saturday, not a closed date."""
    local = hours.now_dubai(now)
    return hours.is_open_day(local.date(), closed_dates) and SEND_FROM <= local.time() < SEND_UNTIL


def _sendable(template) -> bool:
    """Template B as it was submitted: one value ({{1}}, the first name) and no media header."""
    return template.variable_count == 1 and not template.requires_header_media


def _approved_rows():
    from apps.catalog.models import WaTemplate

    return WaTemplate.objects.filter(name=TEMPLATE_B, status=WaTemplate.Status.APPROVED)


def approved_template(number):
    """Template B, APPROVED on this number's WABA as it was submitted (English first), else None."""
    waba = str(getattr(number, "waba_business_id", "") or "")
    if not waba:
        return None
    rows = sorted(_approved_rows().filter(waba_business_id=waba), key=lambda row: (row.language != shop_templates.LANGUAGE, -row.pk))
    return next((row for row in rows if _sendable(row)), None)


def approved_wabas() -> set[str]:
    """The WABAs Template B can go from (one query for a whole page of the list)."""
    return {row.waba_business_id for row in _approved_rows() if _sendable(row)}


def credit_out() -> bool:
    """The gateway's wallet is out (board C16): nothing goes until it is topped up."""
    from apps.gateway.credit import credit_is_out

    return credit_is_out()


def blocked(conversation, chat, state, settings_row) -> str:
    """Why nothing automatic may go to this chat now, else ''."""
    from . import optout

    if chat is None or not chat.active:
        return "not on the Lead AI screen"
    if conversation.linked_conversation_id:
        return "transferred to another agent"
    if not settings_row.answers(conversation.contact.wa_id):
        return "the assistant is switched off"
    if state is not None:
        if state.stopped_at is not None:
            return "stopped"
        if state.paused_at is not None:
            return "paused"
        if state.handed_over_at is not None:
            return "handed to a person"
        if state.not_interested_at is not None:
            return "not interested"
    if optout.is_blocked(conversation.contact.wa_id):
        return "on the opt-out registry"
    return ""


def _real(messages):
    """The messages that are one: no system note, no copy from a linked chat, and no row of a
    follow-up the gateway refused for credit (it is tried again: ``_set_aside``)."""
    return messages.exclude(kind=Message.Kind.SYSTEM).exclude(mirrored_from__isnull=False).exclude(payload__has_key=ATTEMPT_FAILED)


def last_message(conversation):
    """The chat's newest message that is one (``_real``), read past our office's pin (transcript.is_our_pin): the
    reply it follows is our last word (review 2d: the owner's not-a-shop line and its pin got no options nudge)."""
    rows = list(_real(Message.objects.filter(conversation=conversation)).order_by("-pk")[:5])
    return next((row for row in rows if not transcript.is_our_pin(row)), rows[0] if rows else None)


def campaign_template(conversation):
    """The newest template a campaign of this chat sent (its CampaignRecipient rows say which)."""
    templates = transcript.campaign_template_ids(conversation)
    if not templates:
        return None
    return (
        Message.objects.filter(
            conversation=conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template_id__in=templates
        )
        .order_by("-pk")
        .first()
    )


def reengage_due(conversation, state, now) -> bool:
    """T63: the campaign's template went out 72 hours to 14 days ago, is still the last thing in
    the chat (no reaction to it either), and no Template B followed it: one per campaign send
    (a lead sent the campaign again a month later gets its own). A campaign sent with Template B
    itself (Matloob may pick it in the popup) gets no second copy of it. Never to a chat ``holds``
    turns down: what an earlier round of it told us (no shop wanted, a shop rented elsewhere, a
    "Not now" whose check-back question is still open) stands, and never after the mixed template
    (batch 2e: HELD_NOT_SHOP_TEMPLATE)."""
    campaign = campaign_template(conversation)
    if campaign is None or campaign.status not in SENT_STATUSES or campaign.reactions:
        return False
    if campaign.template is not None and campaign.template.name == TEMPLATE_B:
        return False
    if state is not None and state.template_b_sent_at is not None and state.template_b_sent_at >= campaign.created_at:
        return False
    if not now - NOT_AFTER <= campaign.created_at <= now - AFTER_CAMPAIGN:
        return False
    last = last_message(conversation)
    return last is not None and last.pk == campaign.pk and not holds(conversation, state, now, REENGAGE)


def engaged_since(conversation, since) -> bool:
    """Anything happened in the chat after ``since`` (when the check-back was planned): a word or a
    tap from the customer that is more than a "thanks" or an emoji, or any message of a
    colleague's or ours, except our own "I'll check back with you" sent in that same turn."""
    rows = _real(Message.objects.filter(conversation=conversation, created_at__gt=since)).exclude(kind="reaction").exclude(transcript.REVOKED)
    for row in rows.only("direction", "kind", "body", "payload", "created_at").order_by("pk"):
        if row.direction == Message.Direction.OUTBOUND:
            if transcript.source(row) == transcript.ASSISTANT and row.created_at <= since + CONFIRM_SLACK:
                continue  # the confirmation itself
            return True
        if row.kind == "sticker" or (row.kind == "text" and rules.is_acknowledgement(row.body or "")):
            continue
        return True
    return False


# What holds every follow-up (launch review 2026-10-15, issues 9 and 23) ---------------------------------
#
# Of the first 12 nudges, 7 asked people who wanted a studio or a room to see the shops, one after "Not
# now" and "Not shops"; one went to "No I didnt look for shop" and a STOP followed; one pushed a visit over
# nine questions the bot had left "to the viewing". A "Not now" left unanswered and an "already rented"
# were never closed. So, read from the chat since its newest campaign template or Template B, none of
# them goes after a decline, a "Not now", a shop rented elsewhere or a reply-cap skip still pending, and
# no nudge over a question left to a colleague; Template B never to someone who wants no shop to rent.


@dataclass
class Burst:
    """The customer's messages between two of ours, with the message of ours before them."""

    before: str  # its words (the campaign's, Template B's, ours or a colleague's)
    offer: bool  # it put a shop or a visit on the table: the campaign, Template B, an invitation, times, a nudge
    words: list = field(default_factory=list)  # what they said: a tap by its label, a voice note by what it says


@dataclass
class Reading:
    """The chat since its newest campaign template or Template B (transcript.campaign_message)."""

    bursts: list
    ours_since: list  # the words of our side's messages after the customer's newest words
    customer_newest: Message | None = None
    ours_newest: Message | None = None
    template_kind: str = ic_templates.SHOP  # ic_templates.kind of the template it reads from (batch 2e)

    @cached_property
    def words(self) -> list:
        return [text for burst in self.bursts for text in burst.words]

    @cached_property
    def need(self):
        """What they want instead of a shop to rent, in their own words since then (needs.detect), else None."""
        return needs.detect(self.words)


def _their_words(row) -> str:
    """As engine.need_texts: a tap by its label, a voice note by its stored transcript, else the body."""
    from .assistant import engine

    label = engine._tap_label(row)
    if label:
        return label
    if row.kind == "audio":
        return transcript.transcript_text(row) or ""
    return row.body or ""


def _boundary(conversation, templates):
    """Where a follow-up starts reading: the newest campaign template or Template B, as
    transcript.campaign_message finds it, but never a Template B the gateway refused for credit
    (``_real``: it is tried again, and the chat reads as it did before it)."""
    rows = _real(Message.objects.filter(conversation=conversation, kind=Message.Kind.TEMPLATE, direction=Message.Direction.OUTBOUND))
    if templates:
        rows = rows.filter(Q(template_id__in=templates) | Q(payload__source=SOURCE))
    return rows.select_related("template").order_by("-pk").first()


def _rows_since(conversation, boundary):
    rows = _real(Message.objects.filter(conversation=conversation)).exclude(kind__in=transcript.SKIP_KINDS).exclude(transcript.REVOKED)
    return rows.filter(pk__gt=boundary.pk) if boundary is not None else rows


def read_since(conversation) -> Reading:
    """The chat since its newest campaign template or Template B, as ``holds`` reads it."""
    from .assistant import engine

    templates = transcript.campaign_template_ids(conversation)
    boundary = _boundary(conversation, templates)
    rows = list(_rows_since(conversation, boundary).select_related("lead_ai_transcript", "template").order_by("-pk")[:READ_BACK])
    rows.reverse()
    reading = Reading(bursts=[], ours_since=[], ours_newest=boundary, template_kind=ic_templates.kind_of(boundary))
    before = transcript.outbound_text(boundary) if boundary is not None else ""
    offer = boundary is not None
    current = None
    for row in rows:
        if transcript.is_our_pin(row):
            continue  # our office's pin after the reply of its turn: what they answer is that reply (its offer)
        if row.direction == Message.Direction.INBOUND:
            if current is None:
                current = Burst(before=before, offer=offer)
                reading.bursts.append(current)
            text = _their_words(row)
            if text.strip():
                current.words.append(text)
            reading.customer_newest = row
            reading.ours_since = []
            continue
        current = None
        before = transcript.outbound_text(row)
        offer = transcript.who(row, templates) == "campaign" or engine.visit_offered(before)
        reading.ours_newest = row
        reading.ours_since.append(before)
    return reading


# "Not now" anywhere in what they say ("not now, maybe next month"), besides the template's own tap and
# a whole message of it (rules.is_not_now).
_NOT_NOW_SAID = re.compile(
    r"\bnot\s+(?:now|right\s+now|at\s+the\s+moment|for\s+now|at\s+present|this\s+time)\b|\bmaybe\s+later\b|\blater\s+maybe\b"
    r"|\b(?:abhi|abi)\s+(?:nahi|nahin|nhi|nai)\b|\bfil\s?haa?l\s+(?:nahi|nahin|nhi)\b"
    r"|ليس\s+الآن|ليس\s+الان|مش\s+الحين|مو\s+الحين|مش\s+دلوقتي|مش\s+هلق|ابھی\s+نہیں|فی\s+الحال\s+نہیں|अभी\s+नहीं",
    re.IGNORECASE,
)
# A no to our offer, anywhere in what they say (a whole "No" is rules.is_refusal's). Never "not interested
# in Type 3": a choice among our shops; nor "no need to send photos" / "no need for parking": what they
# need, not a no.
_DECLINE_SAID = re.compile(
    r"\bnot\s+interested\b(?!\s+in\s+(?:type|the|a|this|that|big|bigger|large|larger|small|smaller|medium)\b)"
    r"|\bno\s+(?:thanks|thank\s*you|thankyou)\b|\bno\s+need\b(?!\s+(?:to|for|of)\b)"
    r"|\b(?:nahi|nahin|nhi)\s+chahiye\b|\bzaroo?rat\s+(?:nahi|nahin|nhi)\b"
    r"|\binterested\s+(?:nahi|nahin|nhi)\b"
    r"|غير\s+مهتم|مش\s+مهتم|مو\s+مهتم|لا\s+شكرا|دلچسپی\s+نہیں|نہیں\s+چاہیے|ضرورت\s+نہیں"
    r"|रुचि\s+नहीं|दिलचस्पी\s+नहीं|नहीं\s+चाहिए|ज़रूरत\s+नहीं|जरूरत\s+नहीं",
    re.IGNORECASE,
)
# Our lines that a "Not now" and a shop rented elsewhere lead to (code's own words, in every language).
CHECK_BACK_PLANNED = frozenset(rules.LINES["check_back_yes"].values())
SECOND_SHOP_ASKED = frozenset(rules.LINES["rented_second_shop"].values())


def _says_not_now(text: str) -> bool:
    return rules.is_not_now(text) or bool(_NOT_NOW_SAID.search(" ".join(str(text or "").split())))


def _says_no(text: str) -> bool:
    """A no to our offer: a plain refusal, "not interested", "no thanks" (a "Not now" is _says_not_now's)."""
    if _says_not_now(text):
        return False
    return rules.is_refusal(text) or rules.opt_out_from_text(text) == rules.NOT_INTERESTED or bool(_DECLINE_SAID.search(text or ""))


def _says_yes(words) -> bool:
    from .assistant import engine

    return engine.opens_with_yes(words) or any(rules.is_positive_tap(text) for text in words)


def _tapped_yes(burst: Burst) -> bool:
    """A positive tap ([Yes, show me shops], [Yes, book a viewing], "Interested"): the template's buttons
    stay tappable, so it may come after anything."""
    return any(rules.is_positive_tap(text) for text in burst.words)


def _takes_it_up(burst: Burst, now) -> bool:
    """Their answer to an offer of ours takes it up: a yes, or a day or an hour they name to come that is no
    hedge ("Tomorrow at 5", never "maybe next month"), with no no and no "Not now" in it; or a positive tap,
    after anything. It takes back a decline or a "Not now" they said before it (turned_down, said_not_now)."""
    from .assistant import engine

    if not burst.words or any(_says_no(text) or _says_not_now(text) for text in burst.words):
        return False
    if _tapped_yes(burst):
        return True
    if not burst.offer:
        return False
    joined = " ".join(burst.words)
    return _says_yes(burst.words) or (engine.comes(joined, now) and not hours.hedged(joined))


def turned_down(reading: Reading, now) -> bool:
    """They turned our offer down since the campaign (the campaign itself, Template B, an invitation or
    times offered): a no in the words that answered it, with no other want named ("No shop, looking for a
    room" is a need: needs.py), no shop rented elsewhere and no visit of theirs ("No, tomorrow is better"),
    and nothing since that took an offer of ours up (_takes_it_up: "No" to today, then "Yes" to tomorrow)."""
    from .assistant import engine

    declined = False
    for burst in reading.bursts:
        if _takes_it_up(burst, now):
            declined = False
            continue
        if not burst.offer or not burst.words:
            continue
        if needs.detect(burst.words) is not None or needs.rented_already(burst.words):
            continue
        if not engine.comes(" ".join(burst.words), now) and any(_says_no(text) for text in burst.words):
            declined = True
    return declined


def said_not_now(state, reading: Reading, now=None) -> bool:
    """They said "Not now" since the campaign, whether or not they answered the check-back question (a
    question still open, a check-back planned, or the words themselves: the marker goes when any other
    reply of ours does, chat 68's with the shop list). Only a customer who came back by themselves after
    our "Great, I'll check back with you then." (board T25, batch 2b), or took an offer of ours up since
    (_takes_it_up), is under way again."""
    if state is not None and (state.followup_asked_at is not None or state.followup_due_at is not None):
        return True
    now = now or timezone.now()
    said = False
    for burst in reading.bursts:
        if said and burst.before in CHECK_BACK_PLANNED and any(
            not rules.is_acknowledgement(text) and not _says_not_now(text) for text in burst.words
        ):
            said = False
        if said and _takes_it_up(burst, now):
            said = False
        if any(_says_not_now(text) for text in burst.words):
            said = True
    return said


def rented_still(facts: dict, reading: Reading) -> bool:
    """They told us they rented a shop elsewhere (facts.already_rented, or their words since the campaign),
    and said no yes since to our second-shop question ("Yes, I need one more for my brother" is a shop
    lead again: the nudges may follow it), nor tapped a template's yes after saying it in their words. A
    burst that says they rented is no yes ("Yes, we got one already"). A yes to the campaign itself never
    outweighs facts.already_rented: the model may have learned it later in the same chat."""
    rented_at = -1 if (facts or {}).get("already_rented") is True else None
    yes_at = None
    for index, burst in enumerate(reading.bursts):
        if needs.rented_already(burst.words):
            rented_at = index
        elif burst.before in SECOND_SHOP_ASKED and _says_yes(burst.words):
            yes_at = index
        elif _tapped_yes(burst) and rented_at is not None and rented_at >= 0:
            yes_at = index
    return rented_at is not None and (yes_at is None or yes_at < rented_at)


def cap_pending(conversation, reading: Reading) -> bool:
    """Their newest message is not answered yet because the reply cap held its turn back."""
    from .assistant import engine

    newest = reading.customer_newest
    if newest is None or (reading.ours_newest is not None and reading.ours_newest.pk > newest.pk):
        return False
    after = reading.ours_newest.pk if reading.ours_newest is not None else 0
    return LeadAiTurn.objects.filter(
        conversation=conversation, status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON, inbound__pk__gt=after
    ).exists()


def wants_no_shop(facts: dict, reading: Reading) -> bool:
    """The owner's rule (needs.py): what the chat knows, or their own words since the campaign."""
    return needs.wants_no_shop(facts) or reading.need is not None


def off_the_shop_track(state, reading: Reading) -> bool:
    """A chat off the shop track (batch 2e spec §6.2: its nudges use 2d's "options" words): code put it on the rent, sale or
    other track, or it answers a template that is no shops one and its need is not known yet (the mixed template's "Yes,
    still looking", answered with "What are you looking for ...?": the 2e review found it nudged "to see the shops")."""
    from .assistant import tracks

    track = (getattr(state, "track", "") or "") if state is not None else ""
    if track in (tracks.RENT, tracks.SALE, tracks.OTHER):
        return True
    return not track and reading.template_kind != ic_templates.SHOP


def question_left(conversation, reading: Reading | None = None) -> bool:
    """Our words since their newest message (this campaign's) told them a colleague will confirm or answer
    what they asked (nudges.defers_question): their question is still open. Without ``reading``, two small
    queries: the nudge sweep asks it of every silent chat whose nudge moment came."""
    if reading is not None:
        return reading.customer_newest is not None and any(nudges.defers_question(text) for text in reading.ours_since)
    boundary = _boundary(conversation, transcript.campaign_template_ids(conversation))
    rows = _rows_since(conversation, boundary)
    newest = rows.filter(direction=Message.Direction.INBOUND).order_by("-pk").values_list("pk", flat=True).first()
    if newest is None:
        return False
    ours = rows.filter(direction=Message.Direction.OUTBOUND, pk__gt=newest).select_related("template").order_by("pk")[:READ_BACK]
    return any(nudges.defers_question(transcript.outbound_text(row)) for row in ours)


def holds(conversation, state, now, kind: str, reading: Reading | None = None) -> str:
    """Why this follow-up never goes to this chat, else '' (blocked() still decides the rest: a stop, a
    pause, a handover, "not interested", the registry). ``kind``: the follow-up (the check-back answers
    the "Not now" itself, so that one never holds it). The nudges read our last words first: a question
    of theirs left to a colleague is told to a person whatever else holds the chat (nudge_due)."""
    facts = (state.facts if state is not None else None) or {}
    reading = reading if reading is not None else read_since(conversation)
    if kind in (NUDGE_1, NUDGE_2, OPEN_QUESTION) and question_left(conversation, reading):
        return HELD_QUESTION
    if TEMPLATE_B_AFTER_SHOPS_ONLY and kind in (REENGAGE, CHECK_BACK) and reading.template_kind != ic_templates.SHOP:
        return HELD_NOT_SHOP_TEMPLATE
    if rented_still(facts, reading):
        return HELD_RENTED
    if kind in (REENGAGE, CHECK_BACK) and wants_no_shop(facts, reading):
        return HELD_NO_SHOP
    if turned_down(reading, now):
        return HELD_DECLINED
    if kind != CHECK_BACK and said_not_now(state, reading, now):
        return HELD_NOT_NOW
    if cap_pending(conversation, reading):
        return HELD_CAPPED
    return ""


def check_back_due(conversation, state, now) -> bool:
    """T25: the day the customer asked us to check back has come, and nothing happened since they
    asked (``engaged_since``): a customer who came back by themselves, or a colleague who took
    the chat, is not "checked back" with a marketing template on top of it. Never for a customer
    who wants no shop to rent (Template B is all shops: needs.py), nor one ``holds`` turns down (a
    shop rented elsewhere, a decline): check_back_moot clears those."""
    return _check_back_moot_why(conversation, state, now) == ""


def _check_back_moot_why(conversation, state, now) -> str | None:
    """None: no check-back is due today; '' it is; else why nothing waits for it any more."""
    if state is None or state.followup_due_at is None or state.followup_due_at > now:
        return None
    if needs.wants_no_shop(state.facts):
        return "the customer wants no shop to rent"
    if engaged_since(conversation, state.followup_due_at - shops.FOLLOW_UP_AFTER):
        return "the chat was taken up again since"
    return holds(conversation, state, now, CHECK_BACK)


def check_back_moot(conversation, state, now) -> bool:
    """The check-back's day came for a chat taken up again since, for a customer who wants no shop
    to rent (Template B would offer them shops), or for one a follow-up never goes to (``holds``):
    nothing waits for it any more, so its date is cleared (the chat's row stops showing it, and the
    nudges may follow a chat taken up again). True when it was."""
    why = _check_back_moot_why(conversation, state, now)
    if not why or why == HELD_CAPPED:
        return False  # due, not yet, or waiting for the capped turn to answer them: the date stays
    cleared = LeadAiChatState.objects.filter(pk=state.pk, followup_due_at=state.followup_due_at).update(followup_due_at=None)
    if cleared:
        logger.info("Lead AI check-back of conversation %s dropped: %s", conversation.pk, why)
        _changed(conversation.pk)
    return bool(cleared)


def _check_back_silence(rows, now) -> None:
    """A check-back question nobody answered for CHECK_BACK_SILENT_FOR, when CHECK_BACK_SILENCE says what
    that silence means (None: nothing, and this never runs). SILENCE_IS_YES: a yes; its date becomes the
    question's day plus shops.FOLLOW_UP_AFTER (today or before), and the check-back takes it like any
    other (check_back_due, holds). SILENCE_IS_LOST: the lead closes as Lost (engine.record_opt_out, as a
    shops no: Bot Status Lost with SILENT_LOST_REASON; never for a customer who wants no shop to rent).
    A chat taken up since only loses the question's marker."""
    from .assistant import engine

    since = now - CHECK_BACK_SILENT_FOR
    candidates = rows.filter(lead_ai_state__followup_asked_at__lte=since, lead_ai_state__followup_due_at__isnull=True)
    for conversation in candidates.order_by("pk")[:PER_SWEEP]:
        state = LeadAiChatState.objects.filter(conversation=conversation).first()
        if state is None or state.followup_asked_at is None:
            continue
        rows_now = LeadAiChatState.objects.filter(pk=state.pk, followup_asked_at=state.followup_asked_at, followup_due_at__isnull=True)
        if engaged_since(conversation, state.followup_asked_at):
            rows_now.update(followup_asked_at=None)  # they wrote since: the question is no longer what waits
            continue
        if CHECK_BACK_SILENCE == SILENCE_IS_YES:
            rows_now.update(followup_asked_at=None, followup_due_at=state.followup_asked_at + shops.FOLLOW_UP_AFTER)
        elif CHECK_BACK_SILENCE == SILENCE_IS_LOST and rows_now.update(followup_asked_at=None):
            engine.record_opt_out(conversation, rules.NOT_INTERESTED, by="check_back_silence", playbook=lane.IC_SHOPS, reason=SILENT_LOST_REASON)


def _open_appointment(conversation) -> bool:
    return LeadAiAppointment.objects.filter(conversation=conversation, status__in=LeadAiAppointment.OPEN).exists()


def nudge_due(conversation, state, now, settings_row) -> str:
    """T29: NUDGE_1 or NUDGE_2 when that nudge may go now, else ''. Never to a chat ``holds`` turns down
    (a shop rented elsewhere among them: a yes to a second one is a lead again). OPEN_QUESTION at the first
    nudge's moment when our last words left a question of theirs to a colleague (question_left: no push, a
    person is alerted instead, once for those words), whatever ``holds`` would say and before it reads the
    whole chat (only when a nudge would go)."""
    if state is None or state.nudges >= nudges.MOST:
        return ""
    if state.invites >= INVITED_TWICE:
        return ""  # invited twice and not taken up: both nudges invite, so neither goes
    if state.followup_asked_at is not None or state.followup_due_at is not None:
        return ""  # they said "Not now": the check-back answers that, never a nudge
    if _open_appointment(conversation):
        return ""  # a visit is open (a shops tentative lapses: tasks._lapse_shops_tentatives)
    last = last_message(conversation)
    if (
        last is None
        or last.direction != Message.Direction.OUTBOUND
        or transcript.source(last) != transcript.ASSISTANT
        or last.status not in SENT_STATUSES
    ):
        return ""
    window, closed = conversation.session_expires_at, settings_row.closed_dates
    if transcript.payload(last).get("nudge") is None:
        # Our own reply is the last word: the first nudge's moment, two hours on.
        if not nudges.first_due(now, last.created_at, window, closed):
            return ""
        if question_left(conversation):
            return "" if question_alerted(conversation, last) else OPEN_QUESTION
        step = str(transcript.payload(last).get("shop_step") or "")
        if state.nudges != 0 or not nudges.asks_or_invites(transcript.outbound_text(last), last.kind, step):
            return ""
        return "" if holds(conversation, state, now, NUDGE_1) else NUDGE_1
    # The first one went: the last one only while it is still the last word in the chat.
    if transcript.payload(last).get("nudge") != 1 or not nudges.second_due(now, state.nudged_at, window, closed):
        return ""
    if holds(conversation, state, now, NUDGE_2):
        return ""
    from .assistant import engine

    return NUDGE_2 if nudges.today_slots(now, closed, engine.taken_slots(conversation, now)) else ""


def _question_key(conversation, last) -> str:
    return f"{OPEN_QUESTION}:{conversation.pk}:{last.pk}"


def question_alerted(conversation, last) -> bool:
    """The team was told already that the question these words of ours left open waits for them."""
    key = f"{_question_key(conversation, last)}:"
    return LeadAiAlert.objects.filter(conversation=conversation, kind=OPEN_QUESTION, dedupe_key__startswith=key).exists()


def panel_note(conversation, state, approved: set) -> str:
    """Why this shops chat's Template B cannot go, for its row on the Lead AI screen: '' when the
    template is approved on its number, or the chat is not waiting for one."""
    if str(conversation.number.waba_business_id or "") in approved:
        return ""
    if state is not None and (state.stopped_at or state.paused_at or state.handed_over_at or state.not_interested_at):
        return ""
    if state is not None and (needs.wants_no_shop(state.facts) or (state.facts or {}).get("already_rented") is True):
        return ""  # Template B never goes to them (holds), approved or not
    check_back = state is not None and state.followup_due_at is not None
    never_answered = (state is None or state.template_b_sent_at is None) and conversation.last_inbound_at is None
    if not (check_back or never_answered):
        return ""
    if TEMPLATE_B_AFTER_SHOPS_ONLY and ic_templates.kind_of(campaign_template(conversation)) != ic_templates.SHOP:
        return ""  # the mixed template's chats never get Template B (holds), approved or not (batch 2e)
    return f"{TEMPLATE_B} is not approved on this number yet, so the automatic follow-up waits until Meta approves it."


# The sweep ---------------------------------------------------------------------------------------


def _shops_chats() -> set[int]:
    """The conversations of the active, not transferred Lead AI chats that follow the shops playbook."""
    ids = list(
        LeadAiChat.objects.filter(active=True, conversation__linked_conversation__isnull=True).values_list("conversation_id", flat=True)
    )
    return {pk for pk, playbook in lane.playbooks(ids).items() if playbook == lane.IC_SHOPS}


def messageable(conversations, settings_row):
    """These conversations without the ones ``blocked`` turns down for days, in the query itself:
    stopped, paused, handed to a person or not interested, the phone on the registry, the
    assistant not answering this customer. ``blocked`` still decides each one."""
    rows = conversations.filter(
        Q(lead_ai_state__isnull=True)
        | Q(
            lead_ai_state__stopped_at__isnull=True,
            lead_ai_state__paused_at__isnull=True,
            lead_ai_state__handed_over_at__isnull=True,
            lead_ai_state__not_interested_at__isnull=True,
        )
    ).filter(~Exists(LeadAiOptOut.objects.filter(phone=OuterRef("contact__wa_id"))))
    if not settings_row.assistant_enabled:
        tested = {"".join(ch for ch in str(number) if ch.isdigit()) for number in settings_row.test_numbers or []}
        rows = rows.filter(contact__wa_id__in=[number for number in tested if number])
    return rows


def due_now(now=None) -> list[tuple[int, str]]:
    """[(conversation id, kind)] of the shops chats that are due a follow-up now (the sweep's look;
    the task decides again)."""
    from apps.inbox.models import Conversation

    now = now or timezone.now()
    settings_row = LeadAiSettings.load()
    shops_ids = _shops_chats()
    if not shops_ids:
        return []
    found: list[tuple[int, str]] = []
    seen: set[int] = set()

    def consider(conversation, kind_of) -> None:
        if conversation.pk in seen or len(found) >= PER_SWEEP:
            return
        chat = getattr(conversation, "lead_ai_chat", None)
        state = LeadAiChatState.objects.filter(conversation=conversation).first()
        if blocked(conversation, chat, state, settings_row):
            return
        kind = kind_of(conversation, state)
        if kind:
            seen.add(conversation.pk)
            found.append((conversation.pk, kind))

    def walk(rows, kind_of, label: str) -> None:
        """Every candidate, in pk order and a page at a time, until PER_SWEEP are found: the ones
        turned down here never hide a due chat further on."""
        after = read = 0
        while len(found) < PER_SWEEP:
            if read >= READ_AT_MOST:
                logger.warning("Lead AI follow-up sweep read %s %s candidates and stopped; the rest wait a minute", read, label)
                return
            page = list(rows.filter(pk__gt=after).order_by("pk")[:SCAN])
            for conversation in page:
                consider(conversation, kind_of)
            if len(page) < SCAN:
                return
            read += len(page)
            after = page[-1].pk

    base = messageable(Conversation.objects.select_related("contact", "number", "lead_ai_chat").filter(pk__in=shops_ids), settings_row)
    if CHECK_BACK_SILENCE in (SILENCE_IS_YES, SILENCE_IS_LOST):
        _check_back_silence(base, now)
    if send_hours(now, settings_row.closed_dates):
        approved = approved_wabas()
        # Template B waits for Meta's approval on the chat's own number; its row on the screen says so.
        on_approved = base.filter(number__waba_business_id__in=sorted(approved))

        def template_kind(kind):
            def decide(conversation, state):
                if str(conversation.number.waba_business_id or "") not in approved:
                    return ""
                if kind == REENGAGE:
                    return kind if reengage_due(conversation, state, now) else ""
                if check_back_due(conversation, state, now):
                    return kind
                check_back_moot(conversation, state, now)  # taken up again since: nothing waits for it
                return ""

            return decide

        walk(on_approved.filter(lead_ai_state__followup_due_at__lte=now), template_kind(CHECK_BACK), "check-back")
        # Only chats whose newest message is a template that reached WhatsApp 72 hours to 14 days ago,
        # not Template B itself, with no Template B since (reengage_due decides the rest).
        quiet = (
            _with_last(on_approved.filter(last_message_at__gte=now - NOT_AFTER - SLACK))
            .filter(
                last_direction=Message.Direction.OUTBOUND,
                last_kind=Message.Kind.TEMPLATE,
                last_status__in=SENT_STATUSES,
                last_created__lte=now - AFTER_CAMPAIGN + SLACK,
                last_created__gte=now - NOT_AFTER - SLACK,
            )
            .exclude(last_template=TEMPLATE_B)
            .filter(
                Q(lead_ai_state__isnull=True)
                | Q(lead_ai_state__template_b_sent_at__isnull=True)
                | Q(lead_ai_state__template_b_sent_at__lt=F("last_created") - SLACK)
            )
        )
        if TEMPLATE_B_AFTER_SHOPS_ONLY:
            # The mixed template's non-repliers get nothing (reengage_due says so too): never read here every minute.
            quiet = quiet.exclude(last_template__in=ic_templates.NOT_SHOP_NAMES)
        walk(quiet, template_kind(REENGAGE), "Template B")
    # Only chats whose newest message is the assistant's own, delivered, two hours old, with nothing
    # booked, no "Not now" and no second refusal (nudge_due decides the rest: the nudges, and the alert
    # for a question of theirs our last words left to a colleague).
    silent = (
        _with_last(
            base.filter(
                session_expires_at__gte=now + nudges.WINDOW_MARGIN,
                lead_ai_state__nudges__lt=nudges.MOST,
                lead_ai_state__invites__lt=INVITED_TWICE,
                lead_ai_state__followup_asked_at__isnull=True,
                lead_ai_state__followup_due_at__isnull=True,
            )
        )
        .filter(
            last_direction=Message.Direction.OUTBOUND,
            last_source=transcript.ASSISTANT,
            last_status__in=SENT_STATUSES,
            last_created__lte=now - nudges.SILENT_FOR + SLACK,
        )
        .filter(~Exists(LeadAiAppointment.objects.filter(conversation=OuterRef("pk"), status__in=LeadAiAppointment.OPEN)))
    )
    walk(silent, lambda conversation, state: nudge_due(conversation, state, now, settings_row), "nudge")
    return found


def _with_last(conversations):
    """The conversations with their newest message's direction, kind, payload source, status, time
    and template name (as last_message reads it: ``_real``), in one query."""
    newest = _real(Message.objects.filter(conversation=OuterRef("pk"))).order_by("-pk")
    return conversations.annotate(
        last_direction=Subquery(newest.values("direction")[:1]),
        last_kind=Subquery(newest.values("kind")[:1]),
        last_source=Subquery(
            newest.annotate(source_key=KeyTextTransform("source", "payload")).values("source_key")[:1], output_field=CharField()
        ),
        last_status=Subquery(newest.values("status")[:1]),
        last_created=Subquery(newest.values("created_at")[:1], output_field=DateTimeField()),
        last_template=Subquery(newest.values("template__name")[:1], output_field=CharField()),
    )


def sweep(now=None) -> int:
    """Queue the due follow-ups (one task per chat); how many were queued. Nothing while credit is out."""
    from .tasks import send_follow_up

    if credit_out():
        return 0
    due = due_now(now)
    for conversation_id, kind in due:
        send_follow_up.delay(conversation_id, kind)
    return len(due)


# Sending -------------------------------------------------------------------------------------------


def _nothing_sent(conversation, attempt: str) -> bool:
    """No message of this attempt was stored: the send stopped before the gateway."""
    return not Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__attempt=attempt).exists()


def _no_credit(exc) -> bool:
    from apps.gateway.credit import is_no_credit

    return is_no_credit(str(exc))


def _set_aside(conversation, attempt: str) -> None:
    """The rows of an attempt the gateway refused for credit: marked, so that the chat reads as it
    did before (``_real``) and the follow-up is due again once the wallet is topped up. The row
    stays in the thread, FAILED, as the agents saw it."""
    for row in Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__attempt=attempt):
        row.payload = {**(row.payload if isinstance(row.payload, dict) else {}), ATTEMPT_FAILED: NO_CREDIT}
        row.save(update_fields=["payload"])


def _enum_id(value) -> int | None:
    """A Bitrix enumeration field as crm.lead.get returns it ("2481", 2481, ["2481"], "", None)."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def bitrix_blocks(conversation, chat, facts: dict | None = None) -> str:
    """What the chat's Bitrix lead says against an automatic send, else ''.

    A person's Bot Status (Handed to agent, Broker, Lost, Opted out) or WhatsApp Opt-out Yes
    reaches us through one call from Bitrix (board C12) that is never retried: a lost call must
    not let a marketing template or a nudge go to someone a person stopped or took over. So the
    lead is read once here (a REST read, nothing written) and what it says is applied as if
    Bitrix had sent it (bitrix_status.apply, which changes nothing twice). A lead that cannot be
    read now holds the send until the next sweep. No Bitrix, or no lead: nothing to read.

    A person past the assistant on the lead holds it too (review 2d: chat 119's agent booked him at 6 pm in
    Bitrix, and the options nudges went on): a meeting stage or a meeting time, or a closed stage
    (lost.judge_stage); and for a customer who wants no shop to rent (``facts``: the chat's), whom a person
    prepares options for, a person's work on the lead in the last days (lost.judge_touch)."""
    from apps.crmlink import client

    from . import bitrix_status
    from .assistant import crm, crm_fields, lost

    if not client.configured():
        return ""
    lead = crm_fields.lead_of(chat, conversation)
    if lead is None:
        return ""
    try:
        row = crm.read_record("lead", lead)["fields"] or {}
    except client.BitrixError as exc:
        logger.info("Lead AI could not read lead %s before a follow-up: %s", lead, exc)
        return "the Bitrix lead could not be read; tried again later"
    except Exception:  # noqa: BLE001 - nothing goes on a read we cannot trust
        logger.exception("Lead AI could not read lead %s before a follow-up", lead)
        return "the Bitrix lead could not be read; tried again later"
    bot = _enum_id(row.get(crm_fields.FIELD_BOT_STATUS)) if isinstance(row, dict) else None
    opt = _enum_id(row.get(crm_fields.FIELD_OPT_OUT)) if isinstance(row, dict) else None
    wanted = bitrix_status.effects(bot, opt)
    if wanted:
        bitrix_status.apply(lead, bot_status=bot, wa_opt_out=opt)
        return f"the Bitrix lead says {', '.join(wanted)}"
    if not isinstance(row, dict):
        return ""
    now = timezone.now()
    why = lost.judge_stage(row, now)
    if not why and needs.wants_no_shop(facts):
        why = lost.judge_touch(row, now, lost.system_users())
    return f"the Bitrix lead shows a person has it: {why}" if why else ""


def _first_name(conversation, state) -> str:
    from .assistant import engine, filters

    return filters.first_name(engine._customer_name(conversation, (state.facts if state is not None else None) or {}))


def send(conversation_id: int, kind: str) -> str:
    """One chat's follow-up of this kind, if it is still due now: "sent", or why not."""
    from apps.inbox.models import Conversation

    now = timezone.now()
    conversation = Conversation.objects.select_related("contact", "number").filter(pk=conversation_id).first()
    if conversation is None or kind not in KINDS:
        return "no such chat"
    if lane.playbook_for(conversation) != lane.IC_SHOPS:
        return "not a shops chat"
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    state = LeadAiChatState.objects.filter(conversation=conversation).first()
    settings_row = LeadAiSettings.load()
    why = blocked(conversation, chat, state, settings_row)
    if why:
        return why
    if kind == OPEN_QUESTION:
        # Nothing goes to the customer: the team hears that a question of theirs waits for an answer.
        if nudge_due(conversation, state, now, settings_row) != OPEN_QUESTION:
            return "not due"
        return _alert_open_question(conversation, chat, state)
    if credit_out():
        return "the gateway is out of credit"
    if kind in (REENGAGE, CHECK_BACK):
        if not send_hours(now, settings_row.closed_dates):
            return "outside Template B's hours"
        if approved_template(conversation.number) is None:
            return "Template B is not approved on this number"
        if kind == REENGAGE and not reengage_due(conversation, state, now):
            return "not due"
        if kind == CHECK_BACK and not check_back_due(conversation, state, now):
            check_back_moot(conversation, state, now)
            return "not due"
    elif nudge_due(conversation, state, now, settings_row) != kind:
        return "not due"
    why = bitrix_blocks(conversation, chat, (state.facts if state is not None else None) or {})
    if why:
        return why
    if kind in (REENGAGE, CHECK_BACK):
        return _send_template_b(conversation, state, settings_row, kind, now)
    return _send_nudge(conversation, state, settings_row, kind, now)


def _send_template_b(conversation, state, settings_row, kind: str, now) -> str:
    from apps.inbox import services as inbox_services

    from .assistant import reminders

    template = approved_template(conversation.number)
    if template is None:
        return "Template B is not approved on this number"
    state = state or LeadAiChatState.for_conversation(conversation)
    rows = LeadAiChatState.objects.filter(pk=state.pk)
    if kind == REENGAGE:
        sent_for = campaign_template(conversation).created_at  # reengage_due found it just now
        before = state.template_b_sent_at
        claimed = rows.filter(Q(template_b_sent_at__isnull=True) | Q(template_b_sent_at__lt=sent_for)).update(template_b_sent_at=now)

        def undo():
            rows.filter(template_b_sent_at=now).update(template_b_sent_at=before)

    else:
        due, before = state.followup_due_at, state.followup_sent_at
        claimed = rows.filter(followup_due_at=due).update(followup_due_at=None, followup_sent_at=now)

        def undo():
            rows.filter(followup_due_at__isnull=True, followup_sent_at=now).update(followup_due_at=due, followup_sent_at=before)

    if not claimed:
        return "another task has it"
    attempt = f"{kind}:{now.isoformat()}"
    values = {"1": reminders.template_value(_first_name(conversation, state) or "there")}
    try:
        inbox_services.send_template(conversation, None, template, values, payload={"source": SOURCE, "followup": kind, "attempt": attempt})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded; the agents see the failed message in the chat
        if _nothing_sent(conversation, attempt) or _no_credit(exc):
            _set_aside(conversation, attempt)
            undo()
            logger.info("Lead AI Template B for conversation %s did not go (%s); it waits", conversation.pk, exc)
            return f"not sent ({type(exc).__name__}); tried again later"
        logger.warning("Lead AI Template B for conversation %s failed: %s", conversation.pk, exc)
        return f"failed ({type(exc).__name__})"
    _changed(conversation.pk)
    return "sent"


def _send_nudge(conversation, state, settings_row, kind: str, now) -> str:
    from apps.inbox import services as inbox_services

    from .assistant import engine, shop_flow

    facts = state.facts or {}
    language = state.language or "en"
    name = _first_name(conversation, state)
    closed = settings_row.closed_dates
    # A customer who wants no shop to rent hears only about the visit, never about shops (needs.py): what
    # the chat knows, or what they said since the campaign (a chat whose facts predate who_they_are); and so does every chat
    # off the shop track (batch 2e spec §6.2: off_the_shop_track).
    reading = read_since(conversation)
    options = wants_no_shop(facts, reading) or off_the_shop_track(state, reading)
    if kind == NUDGE_1:
        last = last_message(conversation)
        text = nudges.first_text(
            language, name, shop_type=shop_flow.type_in_view({}, facts, settings_row.shops_facts),
            business=facts.get("business_activity") or "", now=now, closed_dates=closed, options=options,
            # Our "for yourself, or for a client?" still open is asked again, never skipped (chats 103, 78).
            for_whom=last is not None and nudges.asks_for_whom(transcript.outbound_text(last)),
        )
    else:
        text = nudges.second_text(language, name, nudges.today_slots(now, closed, engine.taken_slots(conversation, now)), options=options)
    number = 1 if kind == NUDGE_1 else 2
    before = state.nudged_at
    rows = LeadAiChatState.objects.filter(pk=state.pk)
    if not rows.filter(nudges=number - 1).update(nudges=number, nudged_at=now):
        return "another task has it"
    attempt = f"{kind}:{now.isoformat()}"
    try:
        inbox_services.send_text(conversation, None, text, payload={"source": transcript.ASSISTANT, "nudge": number, "attempt": attempt})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - the chat shows the failed message
        if _nothing_sent(conversation, attempt) or _no_credit(exc):
            _set_aside(conversation, attempt)
            rows.filter(nudges=number, nudged_at=now).update(nudges=number - 1, nudged_at=before)
            logger.info("Lead AI nudge %s for conversation %s did not go (%s)", number, conversation.pk, exc)
            return f"not sent ({type(exc).__name__})"
        logger.warning("Lead AI nudge %s for conversation %s failed: %s", number, conversation.pk, exc)
        return f"failed ({type(exc).__name__})"
    return "sent"


def _alert_open_question(conversation, chat, state) -> str:
    """Their question our last words left to a colleague, two hours on and unanswered: the chat's own
    people and the Lead AI alert list are told (alerts.LISTED_KINDS), once for those words; the customer
    gets nothing (no nudge pushes a visit over it: launch chat 95's nine questions, 59's rent security)."""
    from .assistant import alerts, crm, engine

    last = last_message(conversation)
    reading = read_since(conversation)
    said = " / ".join(reading.bursts[-1].words) if reading.bursts else ""
    # Their questions in full, as far as an alert holds them (chat 95's nine), on one line with no BB-code or HTML.
    words = " ".join(said.split()).translate(crm._UNSAFE)[:QUESTION_WORDS_MAX]
    who = engine._customer_name(conversation, (state.facts if state is not None else None) or {}) or "A Lead AI customer"
    lines = [
        f"{who} (WhatsApp +{conversation.contact.wa_id}) asked something the assistant could not answer: it said a colleague "
        f"would confirm it, and they have said nothing since {transcript.stamp(last.created_at)}.",
        f"Their words: {words}" if words else "",
        "The assistant sent them no reminder (it never pushes a visit over an open question): please answer them here.",
    ]
    rows = alerts.raise_alert(
        kind=OPEN_QUESTION,
        conversation=conversation,
        title=f"{who} is waiting for an answer"[:200],
        text="\n".join(line for line in lines if line),
        dedupe_key=_question_key(conversation, last),
        crm_url=engine._crm_url(chat),
    )
    return "alerted" if rows else "nobody to alert"


def _changed(conversation_id: int) -> None:
    from .assistant import live

    live.appointment_changed(conversation_id)
