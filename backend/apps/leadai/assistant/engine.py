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
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field

from celery.exceptions import SoftTimeLimitExceeded
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inbox.models import Message

from .. import lane
from ..models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn
from . import alerts, filters, hours, live, openai_client, prompt, reminders, rules, schema, transcribe, transcript

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


def _item_opt_out(item, meeting_open: bool) -> str | None:
    text = (item.body or "").strip()
    data = transcript.payload(item)
    if item.kind == "button":
        return rules.opt_out_from_button((data.get("button") or {}).get("text") or text)
    if item.kind == "interactive":
        reply = (data.get("interactive") or {}).get("button_reply") or (data.get("interactive") or {}).get("list_reply") or {}
        return rules.opt_out_from_button(reply.get("title") or text)
    if item.kind == "text":
        if meeting_open and rules.is_meeting_cancel(text):
            # "الغاء" / "cancel" with a meeting booked: the model records a cancel.
            return None
        return rules.opt_out_from_text(text)
    return None


def _burst_opt_out(burst, meeting_open: bool) -> str | None:
    """An opt-out is the last thing the customer said ("STOP" then "🙏" is still a
    STOP; "Stop" then "sending studios, I need a 2BR" is not)."""
    said = _said(burst)
    key = said[-1] if said else burst[-1]
    return _item_opt_out(key, meeting_open)


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
    return Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        payload__source=SOURCE,
        created_at__gte=since,
    ).count()


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
    """Our last message asked something (in any script) or offered buttons to tap."""
    if last is None:
        return False
    if rules.asks_question(last.body):
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


def check_proposal(proposal: dict, appointment, now, closed_dates=(), *, grounding=None, segment: str = "") -> dt.datetime | None:
    """The validated start (or arrival), None when the action needs no time. Raises SlotError.

    ``grounding`` is (customer words, our last words); when given, a new time
    must be one the customer named or agreed to.
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


def settle_handover(answer: dict, earlier: list, new_texts: list | None = None) -> dict:
    """The model's handover, corrected where code knows better: a renewal's price
    question is renewal_terms; the first price question is no handover; asking
    for the price again after our answer is one (with the holding line, never
    a second copy of the deflection)."""
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
    right after our last message invited them or offered times, the last thing
    they said (acknowledgements aside) is a plain yes: "No, I am travelling" and
    then "ok" is no yes. ``texts``: the burst, a message that is not text as ''."""
    if visit_open:
        return True
    if not (filters.is_invitation(our_last) or filters.offers_time(our_last)):
        return False
    said = [text for text in texts if not rules.is_acknowledgement(text)]
    return rules.is_acceptance(said[-1]) if said else any(rules.is_acceptance(text) for text in texts)


def visit_offered(ours: str) -> bool:
    """Our side's recent words (ours or a colleague's, never the campaign's) invited
    them or offered exact times: a visit is on the table, whatever the model flagged."""
    return filters.is_invitation(ours) or filters.offers_time(ours)


def deferral(said: list, *, appointment=None, offered: bool = False, invites: int = 0, quiet: bool = False) -> str:
    """The customer's words when all they said (acknowledgements aside) puts off a
    visit we put on the table, else ''.

    ``said`` is the burst without its acknowledgements, a message that is not
    text as '': a question sent with the deferral is the model's to answer.
    On the table: ``offered`` (visit_offered), an invitation counted
    (``invites``), or ``appointment``, the open one, being an office visit
    still tentative. Any other open one stays the model's, which sees it: a
    confirmed meeting, an owner's viewing at their property, a call. ``quiet``:
    a person has the chat, they declined, or they are no customer of ours (a
    job applicant): nothing to book.
    """
    words = (said[0] if len(said) == 1 else "").strip()
    if quiet or not words or not rules.is_deferral(words):
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


def settle(
    answer: dict,
    earlier: list,
    new_texts: list,
    invites: int,
    *,
    agreed: bool = False,
    playbook: str = lane.GENERAL,
    broker_labelled: bool = False,
    address_sent: str = "",
) -> dict:
    """Everything code corrects in the model's answer before it is used (live and in the eval).

    ``agreed``: the customer has agreed to come (agreed_to_come); ``playbook``:
    the chat's script (lane.playbook_for); ``broker_labelled``: the chat carries
    the Broker label already, so an agent pressed Resume on it (or labelled it):
    a broker is then an ordinary handover; ``address_sent``: the office
    address, when one of our messages gave the location already. What is cut
    from the reply is listed in ``answer["trimmed"]``, so its English gloss no
    longer holds; ``answer["broker"]`` asks _apply to label and pause the chat.
    """
    settle_handover(answer, earlier, new_texts)
    # language names the script the reply is written in (Urdu script is ur, never ur_latin).
    script = rules.guess_language(answer["reply"]) if answer["reply"] else ""
    if script in ("ar", "ur", "hi") and answer["language"] != script:
        answer["language"] = script
    trimmed = []
    if agreed:
        # They said yes to coming: the times offered now are no new invitation,
        # so they are neither counted nor cut (the first real chat lost its
        # time offer to the cap below after a plain "Yes").
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
):
    """(answer, validated time, completions, rejection reason, still_invalid).

    ``codes`` collects the SlotError code of each refused proposal.
    """
    codes = codes if codes is not None else []
    messages = [{"role": "system", "content": system}, {"role": "user", "content": context}]
    completions = []
    first = openai_client.complete_json(messages, schema.SCHEMA, user=user, deadline=deadline)
    completions.append(first)
    answer = _shape(schema.normalize(first.data))
    try:
        when = check_proposal(answer["appointment"], appointment, now, closed_dates, grounding=grounding, segment=answer["segment"])
        return answer, when, completions, "", False
    except hours.SlotError as exc:
        reason = exc.message
        codes.append(exc.code)
    if deadline is not None and deadline - time.monotonic() < CORRECTION_NEEDS:
        answer["appointment"] = dict(NO_TIME)
        return answer, None, completions, f"{reason} / no time for a second try", True
    messages += [
        {"role": "assistant", "content": json.dumps(first.data, ensure_ascii=False)},
        {"role": "user", "content": prompt.CORRECTION.format(reason=reason)},
    ]
    second = openai_client.complete_json(messages, schema.SCHEMA, user=user, deadline=deadline)
    completions.append(second)
    answer = _shape(schema.normalize(second.data))
    try:
        when = check_proposal(answer["appointment"], appointment, now, closed_dates, grounding=grounding, segment=answer["segment"])
        return answer, when, completions, reason, False
    except hours.SlotError as exc:
        codes.append(exc.code)
        answer["appointment"] = dict(NO_TIME)
        return answer, None, completions, f"{reason} / {exc.message}", True


def _same_words(left: str, right: str) -> bool:
    return " ".join(str(left or "").split()).casefold() == " ".join(str(right or "").split()).casefold()


def _merge_facts(old: dict, new: dict) -> dict:
    merged = dict(old or {})
    for key, value in (new or {}).items():
        if value not in (None, "", []):
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
    opt = _burst_opt_out(burst, meeting_open=_open_appointment(conversation) is not None)
    if opt:
        return _rule_opt_out(message, conversation, chat, state, settings_row, burst, opt)

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
    try:
        outcome = _run_claimed(turn, message, conversation, chat, state, settings_row, burst, heard, now, revoked, deadline)
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


def _rule_opt_out(message, conversation, chat, state, settings_row, burst, kind: str) -> Outcome:
    """A STOP, wrong number or "not interested" found by code: recorded whatever the
    assistant's state; the polite line only when the assistant may speak now."""
    turn = _claim(message)
    if turn is None:
        return _skip("already handled")
    # Switched off for this customer (the dark launch): the state is kept, so no
    # reminder or later reply reaches them, but nobody is alerted about a chat
    # the assistant is not part of.
    answers = settings_row.answers(conversation.contact.wa_id)
    recorded = record_opt_out(conversation, kind, by="rule", quiet=not answers)
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
    try:
        sent = _send(conversation, rules.line(kind, language), turn)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - the opt-out is recorded either way
        logger.warning("Lead AI opt-out line failed on conversation %s: %s", conversation.pk, exc)
        return _finish(turn, Outcome(LeadAiTurn.Status.FAILED, "opt-out line not sent", actions=actions))
    return _finish(turn, Outcome(LeadAiTurn.Status.REPLIED, f"opt-out ({kind})", reply_message_id=sent.pk, actions=actions))


def record_opt_out(conversation, kind: str, *, by: str, quiet: bool = False) -> bool:
    """Record a customer's opt-out once; True only the first time. Sends nothing.

    STOP and wrong number stop the assistant and drop the open meeting's
    reminder (the meeting itself stays: they may still come). "Not
    interested" cancels the open meeting, so nobody is reminded of, or waits
    for, a visit the customer has declined. The agents are told; the CRM gets
    a note; ``quiet`` skips both (a chat the switched-off assistant is not
    part of). ``by`` is "rule", "model" or "reminder_check".
    """
    now = timezone.now()
    state = LeadAiChatState.for_conversation(conversation)
    if kind in (rules.STOP_ALL, rules.WRONG_NUMBER):
        updated = LeadAiChatState.objects.filter(pk=state.pk, stopped_at__isnull=True).update(stopped_at=now, stop_reason=kind)
    elif kind == rules.NOT_INTERESTED:
        updated = LeadAiChatState.objects.filter(pk=state.pk, not_interested_at__isnull=True).update(not_interested_at=now)
    else:
        return False
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
    if quiet:
        return True
    if kind in (rules.STOP_ALL, rules.WRONG_NUMBER):
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
            + ".",
            dedupe_key=f"opt_out:{conversation.pk}:{now:%Y%m%d}",
            crm_url=_crm_url(chat),
        )
    transaction.on_commit(lambda pk=conversation.pk, k=kind: record_crm_note.delay(pk, k))
    transaction.on_commit(lambda pk=conversation.pk: live.appointment_changed(pk))
    return True


def _opt_out(turn, conversation, chat, state, kind: str, language: str, answer: dict) -> Outcome:
    """The model found an opt-out: one fixed polite line, then record it."""
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        fresh.facts = _merge_facts(fresh.facts, answer["facts"])
        fresh.language = answer["language"][:16]
        fresh.save(update_fields=["facts", "language", "updated_at"])
    try:
        sent = _send(conversation, rules.line(kind, language), turn)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Lead AI opt-out line failed on conversation %s: %s", conversation.pk, exc)
        sent = None
    record_opt_out(conversation, kind, by="model")
    actions = {"opt_out": kind, "by": "model"}
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


def _run_claimed(turn, message, conversation, chat, state, settings_row, burst, heard, now, revoked, deadline) -> Outcome:
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
    # The location went out already: not again unasked, and not for a day. Asked
    # for, it goes again (a booked customer on the way, whatever the
    # confirmation carried).
    asked = " ".join(transcript.inbound_text(item, heard.get(item.pk)) for item in burst if item.kind in ("text", "audio"))
    location = not filters.asks_for_location(asked) and location_sent(
        conversation, settings_row.office_address, settings_row.office_maps_url, since=now - LOCATION_FRESH
    )
    codes: list = []
    segment = _last_segment(conversation)
    deferred = deferral(
        [(item.body or "") if item.kind == "text" else "" for item in said],
        appointment=appointment,
        offered=visit_offered(ours),
        invites=state.invites,
        # A person has the chat, they declined, or they are no customer of ours.
        quiet=state.handed_over_at is not None or state.not_interested_at is not None or segment == "other",
    )
    if deferred:
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
        context = prompt.context_message(
            now=now,
            closed_dates=settings_row.closed_dates,
            office_address=settings_row.office_address,
            segment_hint=_segment_hint(conversation, chat, campaign_msg),
            campaign_line=_campaign_line(campaign_msg),
            customer_name=_customer_name(conversation, facts),
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
        )
        answer, when, completions, rejected, still_invalid = ask_model(
            prompt.system_prompt(),
            context,
            appointment,
            now,
            settings_row.closed_dates,
            openai_client.safety_id(conversation.pk),
            deadline=deadline,
            grounding=(_customer_words(rows, heard, burst), ours),
            codes=codes,
        )
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
    agreed = agreed_to_come(
        visit_open=appointment is not None,
        our_last=our_last,
        texts=[(item.body or "").strip() if item.kind == "text" else "" for item in burst if item.kind != "sticker"],
    )
    playbook = lane.playbook_for(conversation)
    settle(
        answer,
        earlier,
        [transcript.inbound_text(item, heard.get(item.pk)) for item in burst],
        state.invites,
        agreed=agreed,
        playbook=playbook,
        # Only a broker's turn asks (settle_handover never makes one).
        broker_labelled=answer["handover"]["reason"] == BROKER and conversation.labels.filter(name__iexact=BROKER_LABEL).exists(),
        address_sent=settings_row.office_address if location else "",
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
    if agreed:
        plan["agreed"] = True
    if answer.get("trimmed"):
        plan["trimmed"] = answer["trimmed"]
    if playbook != lane.GENERAL:
        plan["playbook"] = playbook
    if rejected:
        plan["rejected"] = rejected[:300]
        plan["codes"] = codes

    # Still ours? -------------------------------------------------------------------------------
    why_not = still_ours(message, chat.pk, campaign_templates, settings_row.pk)
    if why_not:
        return _skip(why_not, **plan)
    # From here the reply goes out: "if you send first, it drops its reply" no longer holds.
    live.thinking(conversation, False)

    if answer["opt_out"] != "none":
        return _opt_out(turn, conversation, chat, state, answer["opt_out"], answer["language"], answer)

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
    language = answer["language"]
    action = effective_action(answer["appointment"]["action"], appointment)
    if action == "reschedule" and when is not None and confirmed and appointment.starts_at == when:
        action = "reconfirm"  # the time already booked: said again, nothing moves
    elif action == "reschedule" and when is None and not still_invalid:
        action = "reschedule_requested"
    elif action == "running_late" and when is not None and confirmed and appointment.starts_at == when:
        action = "on_time"
    plan["effective"] = action
    merged = _merge_facts(facts, answer["facts"])
    name = _customer_name(conversation, merged)
    rows_context = _context_words(rows, campaign_msg, burst, heard, facts, campaign_templates)
    maps = settings_row.office_maps_url
    text = ""
    holding = False
    booking = None
    filtered = []
    gloss = False  # the model's own words go out whole, so its English translation (reply_en) holds
    appended = ""  # the Maps link or the address code added to the reply
    if still_invalid:
        if "no_appointment_otw" in codes:
            text = filters.on_my_way(language)
            _walk_in_alert(conversation, chat, name)
        else:
            text = rules.line("ask_time", language)
        plan["fallback"] = "ask_time"
    elif action in ("confirm", "reschedule") and when is not None:
        if action == "confirm":
            text = filters.confirmation(language, name, when, settings_row.office_address, maps, _is_commercial(answer["segment"], merged))
        else:
            text = filters.rescheduled(language, name, when, settings_row.office_address, maps)
        booking = {
            "event": "confirmed" if action == "confirm" else "rescheduled",
            "starts_at": when.isoformat(),
            "appointment": appointment.pk if appointment is not None else None,
        }
    elif action == "reconfirm":
        text = filters.confirmation(language, name, when, settings_row.office_address, maps, _is_commercial(answer["segment"], merged))
    elif action == "running_late" and when is not None:
        text = filters.arrival(language, when)
    elif action == "on_time" or (action == "on_my_way" and confirmed):
        text = filters.on_my_way(language)
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
    else:
        if answer["send"]:
            text, filtered = filters.clean_reply(answer["reply"], rows_context)
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

    if not text:
        done = _apply(conversation, chat, state, answer, action, when, appointment, now, sent=False, holding=False)
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

    done = _apply(conversation, chat, state, answer, action, when, appointment, now, sent=True, holding=holding)
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


def _details(facts: dict) -> dict:
    return {k: v for k, v in (facts or {}).items() if v not in (None, "")}


def _apply(conversation, chat, state, answer, action, when, appointment, now, *, sent: bool, holding: bool) -> dict:
    """Store what this turn decided, after the reply went out (or when none was needed).

    ``action`` is the effective action, including the engine's own
    "reconfirm", "reschedule_requested" and "on_time".
    """
    from ..tasks import sync_appointment_crm

    done: dict = {}
    with transaction.atomic():
        fresh = LeadAiChatState.objects.select_for_update().get(pk=state.pk)
        fresh.facts = _merge_facts(fresh.facts, answer["facts"])
        fresh.language = answer["language"][:16]
        fields = ["facts", "language", "updated_at"]
        if sent and answer["invited_to_meeting"]:
            fresh.invites = min(fresh.invites + 1, 99)
            fields.append("invites")
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
        fresh.save(update_fields=fields)
        facts = fresh.facts

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
            if {k: v for k, v in _details(facts).items() if k in BOOKING_DETAILS} != {
                k: v for k, v in (current.details or {}).items() if k in BOOKING_DETAILS
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
        if crm_event or done.get("handover"):
            transaction.on_commit(lambda pk=conversation.pk: live.appointment_changed(pk))
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
    )
    out = []
    for key, label in labels:
        value = facts.get(key)
        if value not in (None, ""):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            out.append(f"{label}: {value}")
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
