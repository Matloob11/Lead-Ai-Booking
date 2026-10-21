"""The shops playbook's Bitrix lead fields, written through the Lead fields tool (board C6).

The tool is POST /bitrix/tools/a7_leadai_fields.php on the CRM box
(settings.LEADAI_BITRIX_FIELDS_URL), signed like the notify tool but with its
own prefix: X-Leadai-Ts (unix seconds) and X-Leadai-Sign = hex HMAC-SHA256 of
"leadai-fields." + ts + "." + body, with CRM_LEAD_WA_SECRET. It writes through
Bitrix's CRM factory with business processes and automation off, and accepts
only the allow-listed codes and enum ids of the board's field map.

REST crm.lead.update is never used for these: Bitrix BP 235 runs on every REST
edit, rewrites the title and wipes the meeting time (board C4, C7). A booking's
stage, meeting time and to-do go through the same tool's "booking" action
(crm.booking_body, from tasks.sync_appointment_crm; board C9, T55), and the
customer's trade licence copy as its ``license_file`` (licence_body, from
tasks.write_licence_file; board T34).

What a shops chat with a Bitrix lead (LeadAiChat.crm_entity "lead") writes:
- Bot Status: Qualifying on the first answered turn; Viewing booked on a
  confirmed booking; Handed to agent on a handover; Broker; Opted out; Lost;
- Shop Type Wanted when facts.shop_type changes;
- Business activity, only while the lead's own is empty, and only a business:
  never a home they want nor a sentence (crm_facts.is_business; launch chats 44,
  49, 57 and 68 wrote "apartment studio", "room" and "studio" there);
- Trade license status from facts.licence_kind (DED, Trakhees, New licence),
  or Yes / No when only that is known;
- Purpose = Broker for a broker, WhatsApp Opt-out = Yes for a STOP;
- the lost move: Not Interested ("1") for a no, Junk ("JUNK") for a wrong
  number or spam, with the reason (the customer's words), only for a lead
  nobody is working (assistant/lost.py, decided when the rows are posted).

Before a call the lead is read (tasks.write_crm_fields): a value it holds already
is not posted (``holds``), so a write never edits a field to what it was, and the
lead's change log gets no line for it (launch review issue 26).

The lead is the one the newest Lead AI campaign that reached the chat was sent
from (the campaign whose playbook the chat follows, lane.playbooks), else the
record the chat came onto the screen with.

Each value is a LeadAiCrmField row first, queued only when it is not what this
chat last queued for that lead and field: the same value is never posted twice
in a row, and one that comes back (Lost, then a booking, then Lost again) is
posted again. The rows of one turn go in one call, from a Celery task on the
leadai queue (tasks.write_crm_fields) that retries a passing failure; while
Bitrix stays down, the sweep sends them again (tasks._retry_crm_fields). A
failure is logged, never shown to the customer. A Bot Status a person set in
Bitrix is a row too, sent already (bitrix_status.remember): nothing of ours
queued before it goes over it, and the next value of ours that differs goes.

Batch 2e (spec §5, board T95; C39's fields, live since 2026-10-16): a chat on the
rent or the sale track (a studio or a one-bedroom in International City,
tracks.py) also writes its own fields (``residential_writes``, behind
RES_FIELDS_LIVE), in the same batch as its Bot Status:
- Rent/Sale, Client Type and Bedrooms from the track and unit code decided, and
  Purpose ("I want for myself" on rent; investor or own use on sale) and Budget,
  all only while the lead's own are empty (an agent's or the portal's value
  stays). A Rent/Sale, Client Type or Bedrooms the lead holds otherwise than the
  customer now says is left as it is, and the lead's timeline says so, once
  (``held_notes``, from the read just before the post). A Client Type goes only
  while the lead has no Rent/Sale: a7_rent_sale.php derives Rent/Sale from a
  Client Type written without it;
- C39's own fields (Clusters, Balcony, Occupancy, Timeline, Vacant or rented,
  Payment, Full name), the bot's record like Shop Type Wanted: written when
  they change. Text stays text (TEXT_FIELDS: a timeline of "2027" is no number);
- the customer's e-mail, which the tool adds only while the lead has none.
Every id is on the tool's allow-list (ALLOWED, held to the PHP by
test_residential_crm): one it does not know refuses the whole batch.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
import re
import time

import httpx
from django.conf import settings
from django.db import transaction

from ..models import LeadAiChatState, LeadAiCrmField
from . import crm, crm_facts, filters, tracks

logger = logging.getLogger(__name__)

SIGN_PREFIX = b"leadai-fields."

FIELD_SHOP_TYPE = "UF_CRM_A7_SHOP_TYPE"
FIELD_BOT_STATUS = "UF_CRM_A7_BOT_STATUS"
FIELD_OPT_OUT = "UF_CRM_A7_WA_OPT_OUT"
FIELD_PURPOSE = "UF_CRM_LEAD_1737031634747"
FIELD_ACTIVITY = crm.FIELD_ACTIVITY
FIELD_LICENCE = crm.FIELD_LICENCE
# Not a field: the move to a lost stage, with its reason.
LOST = "lost"
# Not a field either: the customer's trade licence copy (``value`` is the inbound message's id).
LICENCE_FILE = "license_file"
LICENCE_MAX = 5 * 1024 * 1024
LICENCE_FORMATS = {"pdf": "licence.pdf", "jpeg": "licence.jpg", "png": "licence.png"}

SHOP_TYPE_IDS = {"type_1": 2471, "type_2": 2472, "type_3": 2473, "not_sure": 2474}
STATUS_QUALIFYING = 2476
STATUS_BOOKED = 2477
STATUS_HANDED = 2478
STATUS_BROKER = 2479
STATUS_LOST = 2480
STATUS_OPTED_OUT = 2481
OPT_OUT_YES = 2482
PURPOSE_BROKER = 2467
LICENCE_KIND_IDS = {"ded": 2455, "trakhees": 2456, "new": 2457, "none": 2160}
LICENCE_YES_NO = {"yes": 2159, "no": 2160}
LOST_NOT_INTERESTED = "1"
LOST_JUNK = "JUNK"
REASON_MAX = 255
ACTIVITY_MAX = 200
# A row the lead held already when it was to be posted (holds): marked done, never posted.
HELD_ALREADY = "Not sent: the lead holds this value already."
# The Bot Status ids a person may set in Bitrix (bitrix_status.py records them as the lead's newest value).
STATUSES = frozenset({2475, STATUS_QUALIFYING, STATUS_BOOKED, STATUS_HANDED, STATUS_BROKER, STATUS_LOST, STATUS_OPTED_OUT})

# Batch 2e: a studio or one-bedroom chat's own fields (spec §5; C38's map, C39's new fields) -----------------------------

# The fields C39 allow-listed are queued only while this is on: one field the tool does not know refuses the whole batch
# (400), Bot Status included (spec §5). C39 is live (2026-10-16, proved on lead 79752), so it is on.
RES_FIELDS_LIVE = True

FIELD_RENT_SALE = "UF_CRM_A7_RENT_SALE"  # enum: 2443 Rent, 2444 Sale, 2445 Rent & Sale
FIELD_CLIENT_TYPE = "UF_CRM_1756638760279"  # enum: 972 Buyer, 973 Seller, 1220 Tenant, 2410 owner
FIELD_BEDROOMS = "UF_CRM_1731838126127"  # enum: 26 0 B/R (studio), 27 1 B/R, ...
FIELD_BUDGET = "UF_CRM_1731838581336"  # money; the tool takes a number (C32)
FIELD_CLUSTERS = "UF_CRM_A7_CLUSTERS"  # C39, text
FIELD_TIMELINE = "UF_CRM_A7_TIMELINE"  # C39, text
FIELD_FULL_NAME = "UF_CRM_A7_FULL_NAME"  # C39, text
FIELD_BALCONY = "UF_CRM_A7_BALCONY"  # C39, enum
FIELD_VACANT_RENTED = "UF_CRM_A7_VACANT_RENTED"  # C39, enum
FIELD_PAYMENT = "UF_CRM_A7_PAYMENT"  # C39, enum
FIELD_OCCUPANCY = "UF_CRM_A7_OCCUPANCY"  # C39, enum
# The lead score (assistant/score.py, F1; Cursor's C50 fields 2696 and 2697, on the tool's allow-list since C65).
FIELD_AI_SCORE = "UF_CRM_A7_AI_SCORE"  # number, 0–100
FIELD_AI_SCORE_WHY = "UF_CRM_A7_AI_SCORE_WHY"  # text: "Hot 82: visit booked; unit known"
# Not a field: the lead's EMAIL, a key of the tool's body of its own, added only while the lead has none (C39).
EMAIL = "email"

RENT_SALE_IDS = {tracks.RENT: 2443, tracks.SALE: 2444}
CLIENT_TYPE_IDS = {tracks.RENT: 1220, tracks.SALE: 972}  # Tenant, Buyer
BEDROOMS_IDS = {tracks.STUDIO: 26, tracks.ONE_BR: 27}  # never a bigger home: the tool takes 26 and 27 only
PURPOSE_INVESTOR = 804
PURPOSE_MYSELF = 805
PURPOSE_IDS = {"investment": PURPOSE_INVESTOR, "investor": PURPOSE_INVESTOR, "personal": PURPOSE_MYSELF, "own_use": PURPOSE_MYSELF}
BALCONY_IDS = {"yes": 2501, "no": 2502, "either": 2503}
VACANT_RENTED_IDS = {"vacant": 2504, "tenanted": 2505, "rented": 2505, "either": 2506}
PAYMENT_IDS = {"cash": 2507, "mortgage": 2508, "finance": 2508}  # "cheques" is how rent is paid: no value of this field
# Never "bachelor": brief rule 7 (no screening); RES_SCHEMA has no such value, 2d's shops schema had.
OCCUPANCY_IDS = {"myself": 2509, "family": 2510, "company_staff": 2511, "company": 2511, "sharing": 2512}
# Text, whatever its characters: the tool refuses a number in a text field, and with it the whole batch.
TEXT_FIELDS = frozenset({FIELD_ACTIVITY, FIELD_CLUSTERS, FIELD_TIMELINE, FIELD_FULL_NAME, FIELD_AI_SCORE_WHY})
FULL_NAME_MAX = 80
TIMELINE_MAX = 200
# A budget the lead may keep (lead_context's own bounds); a yearly rent below this is a monthly figure said with no basis.
BUDGET_MIN, BUDGET_MAX = 1_000, 100_000_000
RENT_YEARLY_MIN = 10_000
# An e-mail the tool's FILTER_VALIDATE_EMAIL always takes (it refuses the whole batch for one it does not): plain ASCII,
# no dot at either end of the local part nor two in a row, labels of letters, digits and inner hyphens.
_EMAIL = re.compile(r"[a-z0-9_%+-]+(?:\.[a-z0-9_%+-]+)*@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}")
EMAIL_MAX = 254
_NAME_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*\.?")
_CLUSTER_WORD = re.compile(r"\s*\bclust(?:e|o)r\b\s*", re.IGNORECASE)

# The agents' own fields, written only while empty: one the lead holds otherwise than the customer now says is left as it
# is, and the lead's timeline says so (spec §1.5, §5; held_notes). Rent & Sale (2445) holds both.
NOTE_FIELDS = (FIELD_RENT_SALE, FIELD_CLIENT_TYPE, FIELD_BEDROOMS)
RENT_AND_SALE = 2445
_HELD_LABELS = {
    FIELD_RENT_SALE: ("Rent/Sale", {2443: "Rent", 2444: "Sale", 2445: "Rent & Sale"}),
    FIELD_CLIENT_TYPE: ("Client Type", {972: "Buyer", 973: "Seller", 1220: "Tenant", 2410: "Owner"}),
    FIELD_BEDROOMS: (
        "Bedrooms",
        {26: "0 B/R (studio)", 27: "1 B/R", 28: "2 B/R", 29: "3 B/R", 30: "4 B/R", 31: "5 B/R", 32: "6 B/R", 33: "7 B/R", 1179: "7+ B/R", 1278: "Plot"},
    ),
}
_WANTS = {
    FIELD_RENT_SALE: {2443: "to rent", 2444: "to buy"},
    FIELD_CLIENT_TYPE: {1220: "to rent", 972: "to buy"},
    FIELD_BEDROOMS: {26: "a studio", 27: "a one-bedroom"},
}
HELD_OTHER = "Not sent: the lead holds another value; its timeline says what the customer wants."
HELD_FOR_RENT_SALE = "Not sent: the lead has a Rent/Sale, which a Client Type would change (a7_rent_sale.php derives it)."
# The CRM review of batch 2e: a Client Type posted while the lead could not be read (a 429, the limiter) made
# a7_rent_sale.php derive Rent/Sale over an agent's value. It waits, unsent, for a read that shows the lead's Rent/Sale
# (the sweep sends it again: tasks._retry_crm_fields).
WAITS_FOR_READ = "Waiting for the lead to be read: a Client Type is sent only once the lead's Rent/Sale is known."
# C39's own fields a person edited on the lead since this chat last wrote them (the lead's value is neither ours nor the new
# one): left as they are, and the lead's timeline says what the customer now says, once (person_note).
OWN_FIELDS = (FIELD_CLUSTERS, FIELD_BALCONY, FIELD_TIMELINE, FIELD_FULL_NAME, FIELD_OCCUPANCY, FIELD_VACANT_RENTED, FIELD_PAYMENT)
HELD_PERSON = "Not sent: a person changed this field on the lead since our last write; its timeline says what the customer now says."
_OWN_LABELS = {
    FIELD_CLUSTERS: ("Clusters", {}),
    FIELD_TIMELINE: ("Timeline", {}),
    FIELD_FULL_NAME: ("Full name", {}),
    FIELD_BALCONY: ("Balcony", {2501: "Yes", 2502: "No", 2503: "Either"}),
    FIELD_VACANT_RENTED: ("Vacant or rented", {2504: "Vacant", 2505: "Rented", 2506: "Either"}),
    FIELD_PAYMENT: ("Payment", {2507: "Cash", 2508: "Mortgage"}),
    FIELD_OCCUPANCY: ("Occupancy", {2509: "Myself", 2510: "Family", 2511: "Company staff", 2512: "Sharing"}),
}
# Not a field: a plain to-do for 2311 (C40's "todo" action), with its deadline in the row's payload; never beside a booking.
TODO = "todo"
DELETION_TODO = "Delete customer data (PDPL)"

# The Lead fields tool's allow-list (ops/bitrix-aws/a7_leadai_fields.php, a7_leadai_fields_allow; C3, C6, C32, C39): every
# code a body may name, with its enum ids or the kind of value it takes. test_residential_crm holds this to the PHP.
TEXT, NUMBER, DATETIME, HTTPS_URL = "text", "number", "datetime", "https_url"
ALLOWED = {
    FIELD_PURPOSE: frozenset({PURPOSE_BROKER, PURPOSE_INVESTOR, PURPOSE_MYSELF}),
    FIELD_RENT_SALE: frozenset({2443, 2444, RENT_AND_SALE}),
    FIELD_BEDROOMS: frozenset(BEDROOMS_IDS.values()),
    FIELD_CLIENT_TYPE: frozenset(CLIENT_TYPE_IDS.values()),
    FIELD_CLUSTERS: TEXT,
    FIELD_TIMELINE: TEXT,
    FIELD_FULL_NAME: TEXT,
    FIELD_BALCONY: frozenset(BALCONY_IDS.values()),
    FIELD_VACANT_RENTED: frozenset(VACANT_RENTED_IDS.values()),
    FIELD_PAYMENT: frozenset(PAYMENT_IDS.values()),
    FIELD_OCCUPANCY: frozenset(OCCUPANCY_IDS.values()),
    FIELD_ACTIVITY: TEXT,
    FIELD_LICENCE: frozenset({*LICENCE_YES_NO.values(), *LICENCE_KIND_IDS.values()}),
    crm.FIELD_MEETING_AT: DATETIME,
    "UF_CRM_1731838831905": HTTPS_URL,  # Meeting Location/Link (C32)
    FIELD_BUDGET: NUMBER,
    "UF_CRM_1760707482053": TEXT,  # Property Size (C32)
    FIELD_SHOP_TYPE: frozenset(SHOP_TYPE_IDS.values()),
    FIELD_BOT_STATUS: STATUSES,
    FIELD_OPT_OUT: frozenset({OPT_OUT_YES, 2483}),
    FIELD_AI_SCORE: NUMBER,  # C65
    FIELD_AI_SCORE_WHY: TEXT,
}


class FieldsError(Exception):
    """The tool could not be reached, or answered 5xx / 429: the task retries."""


def lead_of(chat, conversation=None) -> int | None:
    """The Bitrix lead these fields belong to, else None (nothing is written).

    The lead the newest Lead AI campaign that reached ``conversation`` was sent from:
    a shops campaign sent to a chat an older campaign brought here (from another
    lead, a deal or an Owner Data card) writes to its own lead, never the older
    record. A chat with no such send on record uses the record it came with.
    """
    if conversation is not None:
        from apps.campaigns.models import CampaignRecipient

        newest = list(
            CampaignRecipient.objects.filter(conversation=conversation, campaign__lead_ai__isnull=False)
            .order_by("-pk")
            .values_list("crm_lead_id", flat=True)[:1]
        )
        if newest:
            return int(newest[0]) if newest[0] else None
    if chat is None or chat.crm_entity != "lead" or not chat.crm_id:
        return None
    return int(chat.crm_id)


def licence_value(facts: dict) -> int | None:
    """The Trade license status the facts give: the kind when known, else yes or no."""
    facts = facts or {}
    kind = LICENCE_KIND_IDS.get(str(facts.get("licence_kind") or ""))
    return kind or LICENCE_YES_NO.get(str(facts.get("trade_licence") or ""))


def has_status(conversation, chat=None) -> bool:
    """A Bot Status was written (or queued) for this chat's lead already."""
    rows = LeadAiCrmField.objects.filter(conversation=conversation, field=FIELD_BOT_STATUS)
    lead = lead_of(chat, conversation)
    return (rows.filter(lead_id=lead) if lead is not None else rows).exists()


def turn_writes(before: dict, after: dict, *, answered: bool, first: bool, handover: bool, broker: bool, booked: bool) -> list:
    """[(field, value, payload)] for one turn of a shops chat (pure; tested).

    ``first``: no Bot Status was written yet, so an answered turn is the first
    one (Qualifying). One Bot Status per turn: a broker before a booking before a
    handover before Qualifying.
    """
    before, after = before or {}, after or {}
    writes = []
    if broker:
        writes += [(FIELD_PURPOSE, PURPOSE_BROKER, {}), (FIELD_BOT_STATUS, STATUS_BROKER, {})]
    elif booked:
        writes.append((FIELD_BOT_STATUS, STATUS_BOOKED, {}))
    elif handover:
        writes.append((FIELD_BOT_STATUS, STATUS_HANDED, {}))
    elif answered and first:
        writes.append((FIELD_BOT_STATUS, STATUS_QUALIFYING, {}))
    shop = SHOP_TYPE_IDS.get(str(after.get("shop_type") or ""))
    if shop and after.get("shop_type") != before.get("shop_type"):
        writes.append((FIELD_SHOP_TYPE, shop, {}))
    activity = crm.safe(after.get("business_activity"))[:ACTIVITY_MAX]
    if activity and after.get("business_activity") != before.get("business_activity") and crm_facts.is_business(activity):
        # Never a home they want, nor a sentence (crm_facts.is_business): "apartment studio" went to the lead live.
        writes.append((FIELD_ACTIVITY, activity, {"only_if_empty": True}))
    licence = licence_value(after)
    if licence and licence != licence_value(before):
        writes.append((FIELD_LICENCE, licence, {}))
    return writes


def opt_out_writes(kind: str, reason: str = "") -> list:
    """[(field, value, payload)] for an opt-out of a shops chat: a STOP is Opted out; a
    no, a wrong number and spam close the lead with the reason."""
    from . import rules

    text = crm.safe(reason)[:REASON_MAX] or {
        rules.NOT_INTERESTED: "not interested",
        rules.WRONG_NUMBER: "wrong number",
        rules.SPAM: "spam",
    }.get(kind, kind)
    if kind == rules.STOP_ALL:
        return [(FIELD_OPT_OUT, OPT_OUT_YES, {}), (FIELD_BOT_STATUS, STATUS_OPTED_OUT, {})]
    if kind == rules.NOT_INTERESTED:
        return [(FIELD_BOT_STATUS, STATUS_LOST, {}), (LOST, LOST_NOT_INTERESTED, {"reason": text})]
    if kind in (rules.WRONG_NUMBER, rules.SPAM):
        return [(FIELD_BOT_STATUS, STATUS_LOST, {}), (LOST, LOST_JUNK, {"reason": text})]
    return []


def deletion_writes(now, closed_dates=()) -> list:
    """[(field, value, payload)] for a customer who asked us to delete their data (spec §2.10, §6.3: a C40 to-do for 2311):
    a plain to-do due at the office's next free half hour, with the reason on the lead's timeline (pure; tested)."""
    from . import hours

    slots = hours.free_slots(now, closed_dates, (), count=1)
    deadline = (slots[0] if slots else now + dt.timedelta(hours=1)).astimezone(hours.DUBAI)
    comment = (
        "The customer asked us on WhatsApp to delete their data (PDPL). The assistant stopped and their number is on the "
        "opt-out registry. Please delete their details as the company's process requires."
    )
    return [(TODO, DELETION_TODO, {"deadline": deadline.isoformat(), "comment": comment})]


def residential_writes(facts, track: str, unit: str = "", *, words: str = "", besides=()) -> list:
    """[(field, value, payload)] of a studio or one-bedroom chat's own lead fields (batch 2e spec §5; pure, tested).

    ``facts``: the chat's facts as the turn leaves them; ``track`` / ``unit``: the track and unit code decided
    (state.track, state.unit: tracks.decide); ``words``: their own words this turn (the clusters they name). Each turn
    gives them all, as they stand, and queue() keeps only what is news, so what a chat knew before RES_FIELDS_LIVE went
    on reaches the lead at its next turn. A field ``besides`` (the turn's other writes, turn_writes) already carries is
    left to it: Purpose Broker never gives way to a Purpose of ours.

    - The rent and sale tracks only, and only while RES_FIELDS_LIVE: a shop, a bigger home, another area or a buyer before
      the sale flow is live (tracks.SALE_LIVE) writes none of these.
    - Only while the lead's own are empty (an agent or the portal may have set them): Rent/Sale, Client Type (Tenant or
      Buyer), Bedrooms (a studio or a one-bedroom: the tool takes no other); Purpose, on rent "I want for myself" (805) for
      an end user, on sale investor (804) or own use (805) from their purpose and never from "for myself" alone (their use
      is asked after it), never for someone who buys or rents for a client (Broker is theirs, turn_writes); Budget, a
      yearly rent (a monthly one times twelve) or a sale price.
    - C39's own fields, written when they change: Clusters ("England, France"; "Spain (flexible)"; "Any (flexible)"),
      Balcony, Full name (two words at least, no digits; NAME and LAST_NAME are never touched: BP 235 builds the title from
      them); on rent the Occupancy (never "bachelor": brief rule 7) and the move-in as the Timeline; on sale the buying
      timeline, Vacant or rented, and Payment (cash or mortgage).
    - The e-mail they gave, one the tool takes (``email_of``); it adds it only while the lead has none.
    """
    if not RES_FIELDS_LIVE or track not in (tracks.RENT, tracks.SALE):
        return []
    facts = facts or {}
    empty_only = {"only_if_empty": True}
    writes = [(FIELD_RENT_SALE, RENT_SALE_IDS[track], empty_only), (FIELD_CLIENT_TYPE, CLIENT_TYPE_IDS[track], empty_only)]
    if unit in BEDROOMS_IDS:
        writes.append((FIELD_BEDROOMS, BEDROOMS_IDS[unit], empty_only))
    purpose = purpose_of(facts, track)
    if purpose:
        writes.append((FIELD_PURPOSE, purpose, empty_only))
    budget = budget_of(facts, track)
    if budget:
        writes.append((FIELD_BUDGET, budget, empty_only))
    own = [
        (FIELD_CLUSTERS, clusters_text(facts, words)),
        (FIELD_BALCONY, BALCONY_IDS.get(_word(facts.get("balcony")))),
        (FIELD_TIMELINE, timeline_text(facts, track)),
        (FIELD_FULL_NAME, full_name(facts.get("full_name"))),
    ]
    if track == tracks.RENT:
        own.append((FIELD_OCCUPANCY, OCCUPANCY_IDS.get(_word(facts.get("occupancy")))))
    else:
        own.append((FIELD_VACANT_RENTED, VACANT_RENTED_IDS.get(_word(facts.get("occupancy_status")))))
        own.append((FIELD_PAYMENT, PAYMENT_IDS.get(_word(facts.get("payment")))))
    writes += [(field, value, {}) for field, value in own if value]
    email = email_of(facts.get("email"))
    if email:
        writes.append((EMAIL, email, {}))
    taken = {field for field, _, _ in besides or ()}
    return [write for write in writes if write[0] not in taken]


def _word(value) -> str:
    """An enum fact as one lower-case word ("Company staff" company_staff); a yes/no given as true/false too."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return re.sub(r"[\s-]+", "_", str(value or "").strip().lower())


def purpose_of(facts: dict, track: str) -> int | None:
    """The Purpose a residential chat's facts give (residential_writes), else None."""
    if facts.get("for_client") is True:
        return None  # for a client: the customer type is Broker (turn_writes), never ours
    if track == tracks.SALE:
        return PURPOSE_IDS.get(_word(facts.get("purpose")))
    if track == tracks.RENT and facts.get("for_client") is False:
        return PURPOSE_MYSELF
    return None


def budget_of(facts: dict, track: str) -> int | None:
    """The Budget a residential chat's facts give: on rent a yearly figure (a monthly one times twelve; none said with no
    basis below RENT_YEARLY_MIN, which reads as monthly), on sale a price; else None."""
    amount = facts.get("budget_aed")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None
    basis = str(facts.get("budget_basis") or "")
    if track == tracks.RENT:
        if basis == "total":
            return None
        amount = amount * 12 if basis == "per_month" else amount
        if amount < RENT_YEARLY_MIN:
            return None
    elif basis in ("per_month", "per_year"):
        return None
    amount = int(round(amount))
    return amount if BUDGET_MIN <= amount <= BUDGET_MAX else None


def _cluster_name(item, names) -> str:
    """One cluster as the facts name it ("Spain", "spain cluster"), as the settings spell it; '' for anything else."""
    text = " ".join(_CLUSTER_WORD.sub(" ", str(item or "")).split()).casefold()
    return next((name for name in names if name.casefold() == text), "") if text else ""


def clusters_text(facts: dict, words: str = "", names=tracks.DEFAULT_CLUSTERS) -> str:
    """The clusters they want, as C39's Clusters field keeps them: "England, France", "Spain (flexible)", "Any
    (flexible)", else ''. Only International City's own names, never a nationality or another area: the facts' clusters
    (RES_SCHEMA, the model's reading of what they want), else the ones their own words name this turn as a place
    (``words``, read by code: tracks.clusters_in, "1bhk Englund x cluster" England, "I am from China" none, never our
    office's own cluster nor one they turn down: the CRM review of batch 2e, "see you at the Russia cluster office" wrote
    Russia over Spain), else the community the model recorded when it names one as a place ("Spain Cluster"; never a bare
    "China", which may be where they are from)."""
    given = facts.get("clusters")
    items = given if isinstance(given, (list, tuple)) else re.split(r"[,;/&]|\band\b|\bor\b", str(given or ""))
    found = list(dict.fromkeys(name for name in (_cluster_name(item, names) for item in items) if name))
    if not found and str(words or "").strip():
        found = list(tracks.clusters_in([words], names))
    if not found and not given:
        found = list(tracks.clusters_in([str(facts.get("community") or "")], names))
    flexible = facts.get("cluster_flexible") is True
    if found:
        return ", ".join(found) + (" (flexible)" if flexible else "")
    return "Any (flexible)" if flexible else ""


def timeline_text(facts: dict, track: str) -> str:
    """The Timeline: the move-in on rent, the buying timeline on sale, as text (crm.safe_line), else ''."""
    return crm.safe_line(facts.get("move_in" if track == tracks.RENT else "buy_timeline"), TIMELINE_MAX).strip()


def full_name(value) -> str:
    """The full name they gave, as Full name keeps it: two words of two letters at least, any script, no digits, no
    markup, at most FULL_NAME_MAX characters, never a placeholder or a job title (filters.person_name), its case put
    right (filters.cased); else ''."""
    text = " ".join(str(value or "").split())
    if not text or len(text) > FULL_NAME_MAX or any(ch.isdigit() for ch in text):
        return ""
    words = text.split(" ")
    if not all(_NAME_WORD.fullmatch(word) for word in words) or not filters.person_name(text):
        return ""
    if sum(1 for word in words if len(re.sub(r"[\W\d_]", "", word)) >= 2) < 2:
        return ""
    return filters.cased(text)


def email_of(value) -> str:
    """The e-mail they gave, in lower case, when the tool's FILTER_VALIDATE_EMAIL takes it (one it refuses refuses the
    whole batch); else ''."""
    text = str(value or "").strip().lower()
    if not text or len(text) > EMAIL_MAX or not _EMAIL.fullmatch(text):
        return ""
    local, _, domain = text.partition("@")
    return text if len(local) <= 64 and len(domain) <= 190 else ""


def last_values(conversation, lead: int) -> dict:
    """{field: value} of the newest row this chat queued for each field of this lead."""
    rows = LeadAiCrmField.objects.filter(conversation=conversation, lead_id=lead).order_by("pk").values_list("field", "value")
    return dict(rows)  # oldest first: the newest of each field is the one kept


def changed(field: str, value: str, last: dict) -> bool:
    """Is ``value`` news for this lead (pure; tested)? A value is, when the chat last queued
    another (or none) for that field. The lost move is, unless the lead was last told
    Lost with that same move: after a booking or a handover it goes again."""
    if field == LOST:
        return not (last.get(LOST) == value and last.get(FIELD_BOT_STATUS) == str(STATUS_LOST))
    return last.get(field) != value


def queue(conversation, chat, writes) -> list[int]:
    """Record each write that is news for the chat's lead, and post them in one task after the commit.

    One chat's writes are queued one at a time (its state row is locked), so two
    turns never both queue the same value. Returns the new rows' ids; nothing when
    the chat has no Bitrix lead.
    """
    from ..tasks import write_crm_fields

    lead = lead_of(chat, conversation)
    if lead is None or not writes:
        return []
    ids = []
    with transaction.atomic():
        LeadAiChatState.objects.select_for_update().filter(conversation=conversation).first()
        last = last_values(conversation, lead)  # what Bitrix last heard, before this batch
        for field, value, payload in writes:
            text = str(value)[:255]
            if not changed(field, text, last):
                continue  # this value went (or is going) already
            row = LeadAiCrmField.objects.create(conversation=conversation, lead_id=lead, field=field, value=text, payload=payload or {})
            ids.append(row.pk)
    if ids:
        transaction.on_commit(lambda pks=list(ids): write_crm_fields.delay(pks))
    return ids


def licence_format(data: bytes) -> str:
    """'pdf', 'jpeg' or 'png' by the file's first bytes (what the tool accepts), else ''."""
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return ""


def licence_body(lead_id: int, data: bytes) -> dict:
    """The tool's body for the customer's licence copy (pure; tested). Raises ValueError
    for a file the tool would refuse: not a PDF, JPEG or PNG, or over 5 MB."""
    import base64

    found = licence_format(data)
    if not found:
        raise ValueError("not a PDF, JPEG or PNG")
    if len(data) > LICENCE_MAX:
        raise ValueError("larger than 5 MB")
    return {
        "lead_id": int(lead_id),
        "license_file": {"name": LICENCE_FORMATS[found], "content_base64": base64.b64encode(data).decode("ascii")},
        "comment": "The customer shared their trade licence on WhatsApp; it is on the Trade License File field.",
    }


def queue_licence(conversation, chat, message) -> int | None:
    """Record that this inbound photo or PDF is the customer's licence copy, and post it to the
    lead after the commit (tasks.write_licence_file, which waits for the download). Returns the
    row's id; None when the chat has no Bitrix lead or this message was queued already."""
    from ..tasks import write_licence_file

    lead = lead_of(chat, conversation)
    if lead is None:
        return None
    if LeadAiCrmField.objects.filter(conversation=conversation, field=LICENCE_FILE, value=str(message.pk)).exists():
        return None
    row = LeadAiCrmField.objects.create(
        conversation=conversation, lead_id=lead, field=LICENCE_FILE, value=str(message.pk), payload={"message": message.pk}
    )
    transaction.on_commit(lambda pk=row.pk: write_licence_file.delay(pk))
    return row.pk


def _blank(value) -> bool:
    """A lead field with no value, as the tool reads one (a7_leadai_fields_empty: '' and '0' are empty)."""
    if value is None or value is False:
        return True
    if isinstance(value, list):
        return not [item for item in value if not _blank(item)]
    return str(value).strip() in ("", "0")


def _has_email(current: dict) -> bool:
    """The lead as read has an e-mail (crm.lead.get's EMAIL list, else its HAS_EMAIL)."""
    emails = current.get("EMAIL")
    if isinstance(emails, list) and any(isinstance(item, dict) and str(item.get("VALUE") or "").strip() for item in emails):
        return True
    return str(current.get("HAS_EMAIL") or "").upper() == "Y"


def waits_for_read(current: dict | None, row) -> bool:
    """A Client Type while the lead could not be read (``current`` None: a 429, the limiter): never posted then, since the
    lead's Rent/Sale is not known, and a7_rent_sale.php would derive Rent/Sale from it over an agent's value; it stays
    unsent for the sweep, which reads the lead again (the CRM review of batch 2e; pure, tested)."""
    return not isinstance(current, dict) and row.field == FIELD_CLIENT_TYPE


def _values(value) -> set[str]:
    """A lead field's value as the strings it holds (an enum list, or one value)."""
    if isinstance(value, (list, tuple)):
        return {str(item).strip() for item in value if not _blank(item)}
    return {str(value).strip()} if not _blank(value) else set()


def ours_before(row):
    """The value Lead AI last wrote to this field of the lead before ``row`` (posted, or found there already), else None:
    from any of its chats with the lead (one lead answered on two of our numbers), so a value another chat of ours wrote is
    never taken for a person's."""
    return (
        LeadAiCrmField.objects.filter(
            lead_id=row.lead_id, field=row.field, pk__lt=row.pk, sent_at__isnull=False, error__in=("", HELD_ALREADY),
        )
        .order_by("-pk")
        .values_list("value", flat=True)
        .first()
    )


def edited_by_person(current: dict | None, row, ours) -> bool:
    """One of C39's own fields (OWN_FIELDS) the lead holds with a value that is neither this row's nor the one this chat
    last wrote (``ours``, None when it never did): a person typed it, and our write would replace it (the CRM review of
    batch 2e: an agent's "1 December, confirmed by phone" went under the customer's "mid-November"; pure, tested)."""
    if not isinstance(current, dict) or row.field not in OWN_FIELDS or row.field not in current:
        return False
    held = _values(current.get(row.field))
    if not held or str(row.value).strip() in held:
        return False
    return ours is None or str(ours).strip() not in held


def person_edited(current: dict | None, row) -> bool:
    """edited_by_person, with the value Lead AI last wrote (ours_before) read only when the lead holds another value of one
    of C39's own fields (one query, for the rare row that needs it)."""
    if not isinstance(current, dict) or row.field not in OWN_FIELDS or row.field not in current:
        return False
    held = _values(current.get(row.field))
    if not held or str(row.value).strip() in held:
        return False
    return edited_by_person(current, row, ours_before(row))


def person_note(current: dict | None, rows) -> str:
    """The lead's timeline line for edited_by_person's rows ('' for none; the tool puts "Lead AI: " before it): "The customer
    now says Timeline: mid-November, but the lead says 1 December, confirmed by phone, which a person set; it was left as it
    is." (pure)."""
    says = []
    for row in rows:
        name, labels = _OWN_LABELS.get(row.field, (row.field, {}))
        ours = labels.get(int(row.value), row.value) if str(row.value).isdigit() else row.value
        theirs = ", ".join(sorted(labels.get(int(value), value) if value.isdigit() else value for value in _values((current or {}).get(row.field))))
        says.append(f"{name}: {ours}, but the lead says {theirs}")
    if not says:
        return ""
    left = "it was left as it is" if len(says) == 1 else "these were left as they are"
    return f"The customer now says {'; '.join(says)}, which a person set; {left}."


def holds(current: dict | None, row) -> bool:
    """The lead holds this row's value already (``current``: crm.lead.get's answer, None when it could not be read):
    posting it would edit the field to what it is, and the lead's change log would get a line for nothing (launch
    review issue 26). A field written only while the lead's own is empty holds whenever it has one; an e-mail whenever
    the lead has one (the tool adds one only then); a Client Type whenever the lead has a Rent/Sale (a7_rent_sale.php
    derives Rent/Sale from a Client Type written without it, over what an agent chose). Never the lost move, a licence
    copy, nor a to-do (pure; tested)."""
    if not isinstance(current, dict) or row.field in (LOST, LICENCE_FILE, TODO):
        return False
    if row.field == EMAIL:
        return _has_email(current)
    if row.field == FIELD_CLIENT_TYPE and not _blank(current.get(FIELD_RENT_SALE)):
        return True
    if row.field not in current:
        return False
    value = current.get(row.field)
    if (row.payload or {}).get("only_if_empty"):
        return not _blank(value)
    if isinstance(value, list):
        return str(row.value) in {str(item).strip() for item in value}
    return str(value if value is not None else "").strip() == str(row.value).strip()


def _enum_id(value) -> int | None:
    """The one enum id a lead's field holds ("2444", 2444, ["2444"]), else None."""
    if isinstance(value, (list, tuple)):
        value = next((item for item in value if not _blank(item)), None)
    text = str(value if value is not None else "").strip()
    return int(text) if text.isdigit() and text != "0" else None


def differences(current: dict | None, rows) -> list:
    """The rows written only while empty whose field the lead holds with another value (NOTE_FIELDS: Rent/Sale, Client
    Type, Bedrooms; Rent & Sale holds both), in NOTE_FIELDS' order (pure; tested)."""
    if not isinstance(current, dict):
        return []
    out = []
    for row in rows:
        if row.field not in NOTE_FIELDS or not (row.payload or {}).get("only_if_empty") or not str(row.value).isdigit():
            continue
        held = _enum_id(current.get(row.field))
        if held is None or held == int(row.value) or (row.field == FIELD_RENT_SALE and held == RENT_AND_SALE):
            continue
        out.append(row)
    return sorted(out, key=lambda row: NOTE_FIELDS.index(row.field))


def difference_note(current: dict | None, rows) -> str:
    """The lead's timeline line for ``differences``' rows (the tool puts "Lead AI: " before it), '' for none (pure):
    "The customer wants to rent a studio, but the lead says Rent/Sale: Sale, Bedrooms: 1 B/R; these were left as they are." """
    deal, unit, says = "", "", []
    for row in rows:
        ours = int(row.value)
        name, labels = _HELD_LABELS[row.field]
        if row.field == FIELD_BEDROOMS:
            unit = _WANTS[row.field].get(ours, "")
        else:
            deal = deal or _WANTS[row.field].get(ours, "")
        says.append(f"{name}: {labels.get(_enum_id((current or {}).get(row.field)), 'another value')}")
    wants = " ".join(part for part in (deal, unit) if part)
    if not says or not wants:
        return ""
    left = "it was left as it is" if len(says) == 1 else "these were left as they are"
    return f"The customer wants {wants}, but the lead says {', '.join(says)}; {left}."


def held_notes(current: dict | None, held) -> str:
    """For tasks.write_crm_fields, once the rows the lead holds are marked: those it holds with another value get their
    own reason (HELD_OTHER), a Client Type kept for the lead's Rent/Sale its own (HELD_FOR_RENT_SALE), and the note for
    the lead's timeline comes back ('' for none). Said once: a row an earlier try posted is never noted again."""
    rows = [row for row in differences(current, held) if not row.attempts]
    if rows:
        LeadAiCrmField.objects.filter(pk__in=[row.pk for row in rows]).update(error=HELD_OTHER)
    kept = [
        row.pk for row in held if row.field == FIELD_CLIENT_TYPE and not row.attempts and _blank((current or {}).get(FIELD_CLIENT_TYPE))
    ]
    if kept:
        LeadAiCrmField.objects.filter(pk__in=kept).update(error=HELD_FOR_RENT_SALE)
    return difference_note(current, rows)


def body_for(rows, lead_id=None) -> dict:
    """The tool's body for some rows of one lead (pure; tested). A licence copy is never one
    of them: it goes on its own (licence_body). ``lead_id``: the lead's, for a body that may
    carry no row at all (only the timeline comment of a lead kept in its stage: lost.py)."""
    rows = [row for row in rows if row.field != LICENCE_FILE]
    body: dict = {"lead_id": rows[0].lead_id if rows else lead_id, "fields": {}}
    empty_only = []
    for row in rows:
        if row.field == LOST:
            body["lost"] = {"status_id": row.value, "reason": str((row.payload or {}).get("reason") or "")[:REASON_MAX]}
            continue
        if row.field == EMAIL:
            body[EMAIL] = row.value  # a key of the body, not a field (C39)
            continue
        if row.field == TODO:
            # C40's plain to-do for 2311 (a deletion request): its subject and deadline, its reason on the timeline.
            body["todo"] = {"subject": row.value, "deadline": str((row.payload or {}).get("deadline") or "")}
            if (row.payload or {}).get("comment"):
                body["comment"] = "\n".join(part for part in (body.get("comment"), str(row.payload["comment"])) if part)
            continue
        # Enum ids and amounts go as numbers; a text field as the text it is, digits and all (TEXT_FIELDS).
        value = int(row.value) if row.field not in TEXT_FIELDS and row.value.isdigit() else row.value
        body["fields"][row.field] = value
        if (row.payload or {}).get("only_if_empty") and row.field not in empty_only:
            empty_only.append(row.field)
    if empty_only:
        body["only_if_empty"] = empty_only
    if not body["fields"]:
        del body["fields"]
    return body


def refusal(body: dict) -> str:
    """Why the Lead fields tool would refuse this body with 400 ('' when it takes it), by its own checks of the fields,
    ``only_if_empty`` and ``email`` (a7_leadai_fields.php, against ALLOWED; pure, tested). One bad value refuses the whole
    batch, Bot Status included."""
    fields = body.get("fields") or {}
    if not isinstance(fields, dict):
        return "fields must be an object"
    for code in body.get("only_if_empty") or ():
        if code not in ALLOWED and code != "UF_CRM_A7_TRADE_LICENSE_FILE":
            return f"{code}: unknown field (only_if_empty)"
    for code, value in fields.items():
        rule = ALLOWED.get(code)
        if rule is None:
            return f"{code}: unknown field"
        if rule == TEXT:
            if not isinstance(value, str) or not value.strip():
                return f"{code}: {value!r} is not text"
        elif rule == NUMBER:
            number = value
            if isinstance(value, str) and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value):
                number = float(value)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or number < 0:
                return f"{code}: {value!r} is not a number"
        elif rule == HTTPS_URL:
            if not isinstance(value, str) or not re.match(r"(?i)^https://[^\s<>\"']+", value.strip()):
                return f"{code}: {value!r} is not an https link"
        elif rule == DATETIME:
            if not isinstance(value, str) or not value.strip():
                return f"{code}: {value!r} is not a date and time"
        else:
            number = int(value) if isinstance(value, str) and value.isdigit() else value
            if isinstance(number, bool) or not isinstance(number, int) or number not in rule:
                return f"{code}: {value!r} is not one of its values"
    email = body.get(EMAIL)
    if email not in (None, "") and (not isinstance(email, str) or email_of(email) != email.strip().lower()):
        return f"email: {email!r} is not one the tool takes"
    return ""


def sign(raw: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), SIGN_PREFIX + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def post(body: dict) -> dict:
    """POST one signed body to the tool. Raises FieldsError when a retry may help;
    a refusal (400 field, 401 signature, 404 lead) comes back as {"ok": False, ...}."""
    endpoint = (getattr(settings, "LEADAI_BITRIX_FIELDS_URL", "") or "").strip()
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    if not endpoint or not secret:
        return {"ok": False, "error": "The Lead fields tool is not configured."}
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    try:
        response = httpx.post(
            endpoint,
            content=raw,
            headers={"Content-Type": "application/json", "X-Leadai-Ts": ts, "X-Leadai-Sign": sign(raw, ts, secret)},
            timeout=httpx.Timeout(20, connect=5),
        )
    except httpx.HTTPError as exc:
        raise FieldsError(f"Bitrix unreachable: {type(exc).__name__}") from None
    if response.status_code >= 500 or response.status_code == 429:
        raise FieldsError(f"Bitrix answered {response.status_code}")
    try:
        answer = response.json()
    except ValueError:
        if response.status_code >= 400:
            return {"ok": False, "error": f"Bitrix answered {response.status_code}"}
        raise FieldsError(f"Bitrix answered {response.status_code} without JSON") from None
    if not isinstance(answer, dict):
        return {"ok": False, "error": "Unexpected answer"}
    if response.status_code >= 400 and answer.get("ok") is not False:
        answer = {**answer, "ok": False}
    return answer
