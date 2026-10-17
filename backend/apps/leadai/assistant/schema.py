"""The answer the model must give on every turn (OpenAI structured outputs, strict).

Keys are generated in schema order, so every decision comes before the words:
language, segment, facts, appointment, handover, opt_out, flags, send, the
reply, and last its English translation for our agents (written after the
reply, so it translates the reply instead of planning it). Strict mode wants
every property in ``required`` and ``additionalProperties: false``;
"unknown" is null through a type list, and a nullable enum lists null in both
its type and its values. ``normalize`` then cleans whatever came back: the
schema shapes the answer, code is the gate.

A shops chat (the International City shops playbook) answers SHOPS_SCHEMA: the
same answer, with the shop facts the build pack collects (shop_type,
licence_kind, opening_when, already_rented), ``notes`` as the list of questions
our agent must answer at the viewing, "spam" as an opt-out, and the handover
reasons of a customer who wants no shop to rent (NOT_A_SHOP_REASONS: a home or
another property, to buy, to sell, never asked about a shop, another area). Those
reasons tag the chat and alert our team; they never hand it over or pause it
(assistant/needs.py, the owner's rule of 2026-10-15). SCHEMA itself is left
exactly as it was, so a general chat's request does not change.
"""

from __future__ import annotations

import copy
import re

LANGUAGES = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi", "other")
SEGMENTS = (
    "owner",
    "commercial_tenant",
    "residential_tenant",
    "buyer",
    "renewal_tenant",
    "renewal_owner",
    "other",
)
INTENTS = ("sell", "rent_out", "rent", "buy", "renew", "move_out", "other")
YES_NO_PROGRESS = ("yes", "no", "in_progress")
BUDGET_BASIS = ("per_year", "per_month", "total")
PAYMENT = ("cash", "mortgage", "cheques")
OCCUPANCY_STATUS = ("vacant", "tenanted")
OCCUPANCY = ("family", "bachelor", "company")
ACTIONS = ("none", "tentative", "confirm", "reschedule", "running_late", "on_my_way", "cancel")
PLACES = ("office", "customer_property", "call")
HANDOVER_REASONS = (
    "customer_asked_human",
    "call_requested",
    "price_or_details_insisted",
    "complaint_or_upset",
    "legal_visa_licence_contract",
    "broker_or_for_client",
    "tenancy_issue",
    "renewal_terms",
    "media_received",
    "abroad_cannot_visit",
    "owner_viewing_slot",
    "unclear",
)
OPT_OUT = ("none", "not_interested", "stop_all", "wrong_number")

TEXT_FACTS = (
    "customer_name",
    "property_type",
    "community",
    "building_unit",
    "bedrooms",
    "available_from",
    "move_in",
    "business_activity",
    "notes",
)
NUMBER_FACTS = ("size_sqft", "budget_aed", "asking_price_aed")
BOOL_FACTS = ("for_client", "abroad")
ENUM_FACTS = {
    "intent": INTENTS,
    "budget_basis": BUDGET_BASIS,
    "payment": PAYMENT,
    "occupancy_status": OCCUPANCY_STATUS,
    "occupancy": OCCUPANCY,
    "trade_licence": YES_NO_PROGRESS,
    "preapproval": YES_NO_PROGRESS,
}
FACT_KEYS = (
    "customer_name",
    "intent",
    "for_client",
    "abroad",
    "property_type",
    "community",
    "building_unit",
    "bedrooms",
    "size_sqft",
    "budget_aed",
    "budget_basis",
    "asking_price_aed",
    "payment",
    "occupancy_status",
    "available_from",
    "move_in",
    "occupancy",
    "business_activity",
    "trade_licence",
    "preapproval",
    "notes",
)

REPLY_MAX = 600
TEXT_MAX = 200
DATE_PATTERN = "^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"
TIME_PATTERN = "^([01][0-9]|2[0-3]):[0-5][0-9]$"


def _text(description: str) -> dict:
    return {"type": ["string", "null"], "description": description}


def _enum(values, description: str = "") -> dict:
    node = {"type": ["string", "null"], "enum": [*values, None]}
    if description:
        node["description"] = description
    return node


def _number(description: str) -> dict:
    return {"type": ["number", "null"], "description": description}


def _bool(description: str) -> dict:
    return {"type": ["boolean", "null"], "description": description}


FACTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "customer_name": _text("The customer's name as they gave it or as the CRM has it, else null."),
        "intent": _enum(INTENTS),
        "for_client": _bool("True if they ask for someone else (a client), else null."),
        "abroad": _bool("True if they are outside the UAE or cannot visit, else null."),
        "property_type": _text("shop, office, warehouse, studio, 1BR, villa, ... in English, else null."),
        "community": _text("Area, community or cluster, else null."),
        "building_unit": _text("Building and unit number, else null."),
        "bedrooms": _text("Number of bedrooms as said, else null."),
        "size_sqft": _number("Size in square feet as a number, else null."),
        "budget_aed": _number("Budget in AED as a number, else null."),
        "budget_basis": _enum(BUDGET_BASIS),
        "asking_price_aed": _number("Owner's expected price or rent in AED, else null."),
        "payment": _enum(PAYMENT),
        "occupancy_status": _enum(OCCUPANCY_STATUS),
        "available_from": _text("When the owner's property is available, else null."),
        "move_in": _text("When they need it, e.g. 'this week', else null."),
        "occupancy": _enum(OCCUPANCY),
        "business_activity": _text("Commercial: the business activity, in English, else null."),
        "trade_licence": _enum(YES_NO_PROGRESS),
        "preapproval": _enum(YES_NO_PROGRESS),
        "notes": _text("Anything else useful for the specialist, in English, under 200 characters, else null."),
    },
    "required": list(FACT_KEYS),
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "language": {"type": "string", "enum": list(LANGUAGES)},
        "segment": {"type": "string", "enum": list(SEGMENTS)},
        "facts": FACTS_SCHEMA,
        "appointment": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS)},
                "place": _enum(PLACES),
                "date": {"type": ["string", "null"], "pattern": DATE_PATTERN},
                "time": {"type": ["string", "null"], "pattern": TIME_PATTERN},
                "customer_words": _text("The customer's own words about the time, else null."),
            },
            "required": ["action", "place", "date", "time", "customer_words"],
        },
        "handover": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "needed": {"type": "boolean"},
                "reason": _enum(HANDOVER_REASONS),
            },
            "required": ["needed", "reason"],
        },
        "opt_out": {"type": "string", "enum": list(OPT_OUT)},
        "hot_lead": {"type": "boolean"},
        "invited_to_meeting": {"type": "boolean"},
        "share_office_location": {"type": "boolean"},
        "send": {"type": "boolean"},
        "reply": {"type": "string", "description": "The WhatsApp message to send; empty when send is false."},
        "reply_en": {
            "type": "string",
            "description": 'A faithful sentence-by-sentence English translation of reply, for our agents; "" when language is en.',
        },
    },
    "required": [
        "language",
        "segment",
        "facts",
        "appointment",
        "handover",
        "opt_out",
        "hot_lead",
        "invited_to_meeting",
        "share_office_location",
        "send",
        "reply",
        "reply_en",
    ],
}


# The shops playbook's answer ---------------------------------------------------------------

SHOP_TYPES = ("type_1", "type_2", "type_3", "not_sure")
LICENCE_KINDS = ("ded", "trakhees", "new", "none")
SHOPS_OPT_OUT = (*OPT_OUT, "spam")
# A shops customer who wants no shop to rent (assistant/needs.py, launch 2026-10-15): a flat, studio,
# room, other home or another kind of property; to buy; to sell; they never asked about a shop; or
# another area. A shops answer only, and a tag, never a pause: code takes these off the handover.
WRONG_NEED = "wrong_need"
WANTS_TO_BUY = "wants_to_buy"
WANTS_TO_SELL = "wants_to_sell"
NEVER_ASKED = "never_asked"
OTHER_AREA = "other_area"
NOT_A_SHOP_REASONS = (WRONG_NEED, WANTS_TO_BUY, WANTS_TO_SELL, NEVER_ASKED, OTHER_AREA)
SHOPS_HANDOVER_REASONS = (*HANDOVER_REASONS, *NOT_A_SHOP_REASONS)
# A turn's questions for our agent: launch chat 95 asked nine, and lost four to a cap of five (launch review issue 15).
NOTES_MAX = 10
NOTE_MAX = 120
SHOPS_TEXT_FACTS = (*(key for key in TEXT_FACTS if key != "notes"), "opening_when")
SHOPS_BOOL_FACTS = (*BOOL_FACTS, "already_rented")
SHOPS_ENUM_FACTS = {**ENUM_FACTS, "shop_type": SHOP_TYPES, "licence_kind": LICENCE_KINDS}
SHOPS_FACT_KEYS = (
    *(key for key in FACT_KEYS if key not in ("preapproval", "notes")),
    "licence_kind",
    "shop_type",
    "opening_when",
    "already_rented",
    "preapproval",
    "notes",
)


def _shops_schema() -> dict:
    node = copy.deepcopy(SCHEMA)
    facts = node["properties"]["facts"]
    old = facts["properties"]
    properties = {key: old[key] for key in SHOPS_FACT_KEYS if key in old and key != "notes"}
    properties["for_client"] = _bool(
        "True if the shop is for a client of theirs (a broker or agent), false if it is for themselves, null until they say."
    )
    properties["licence_kind"] = _enum(
        LICENCE_KINDS, "ded (Dubai mainland), trakhees, new (they will open a new licence) or none, as they said; else null."
    )
    properties["shop_type"] = _enum(SHOP_TYPES, "The shop type they chose or you recommended from MATCH; else null.")
    properties["opening_when"] = _text("When they want to open the shop, e.g. 'next month', else null.")
    properties["already_rented"] = _bool("True if they say they already rented a shop, else null.")
    properties["business_activity"] = _text(
        "The business the shop is for, in English, else null; never a home or property they want (a studio or a room is property_type)."
    )
    properties["notes"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Only the questions the customer asked in this message that our agent must answer, in English, "
        "a few words each; never your own questions, the discovery items or anything they did not ask; [] when there are none.",
    }
    facts["properties"] = {key: properties[key] for key in SHOPS_FACT_KEYS}
    facts["required"] = list(SHOPS_FACT_KEYS)
    node["properties"]["opt_out"] = {"type": "string", "enum": list(SHOPS_OPT_OUT)}
    node["properties"]["handover"]["properties"]["reason"] = _enum(SHOPS_HANDOVER_REASONS)
    return node


SHOPS_SCHEMA = _shops_schema()


# The residential answer (batch 2e, spec Appendix B) ------------------------------------------------------------------
# A rent, sale or not-known chat of the International City campaign (assistant/residential.py): SHOPS_SCHEMA without the
# shop facts, with what the rental brief collects (occupancy, balcony, clusters, the full name, the buyer's questions),
# the model's need_tag (never a handover: code reads it, tracks.decide), and two more handovers (meet_at_building,
# complex_occupancy). SCHEMA and SHOPS_SCHEMA stay exactly as they were.

RES_OCCUPANCY = ("myself", "family", "company_staff", "sharing")  # there is no "bachelor" (brief rule 7)
RES_OCCUPANCY_STATUS = ("vacant", "tenanted", "either")
BALCONY = ("yes", "no", "either")
CONTRACT = ("individual", "company")
PURPOSE = ("investment", "personal")
NEED_TAGS = ("wants_shop", "wants_rent", "wants_buy", "other_need", "other_area")
RES_HANDOVER_REASONS = (*HANDOVER_REASONS, "meet_at_building", "complex_occupancy")
RES_PLACES = ("office", "call")
FULL_NAME_MAX = 80
CLUSTERS_MAX = 5
CLUSTER_MAX = 40
OCCUPANTS_MAX = 50
RES_TEXT_FACTS = ("customer_name", "property_type", "community", "bedrooms", "move_in", "buy_timeline")
RES_NUMBER_FACTS = ("budget_aed", "occupants")
RES_BOOL_FACTS = ("for_client", "abroad", "in_dubai", "cluster_flexible", "already_rented")
RES_ENUM_FACTS = {
    "intent": INTENTS,
    "budget_basis": BUDGET_BASIS,
    "payment": PAYMENT,
    "occupancy": RES_OCCUPANCY,
    "occupancy_status": RES_OCCUPANCY_STATUS,
    "balcony": BALCONY,
    "contract": CONTRACT,
    "purpose": PURPOSE,
}
RES_FACT_KEYS = (
    "customer_name",
    "full_name",
    "intent",
    "for_client",
    "abroad",
    "in_dubai",
    "property_type",
    "bedrooms",
    "community",
    "clusters",
    "cluster_flexible",
    "balcony",
    "budget_aed",
    "budget_basis",
    "payment",
    "occupancy",
    "occupants",
    "contract",
    "move_in",
    "occupancy_status",
    "buy_timeline",
    "purpose",
    "email",
    "already_rented",
    "notes",
)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$")


def _res_schema() -> dict:
    node = copy.deepcopy(SHOPS_SCHEMA)
    shops_facts = node["properties"]["facts"]["properties"]
    properties = {
        "customer_name": _text("The customer's name as they gave it, else null."),
        "full_name": {
            "type": ["string", "null"],
            "description": "Their full name (first and last) exactly as they wrote it in this chat, at most 80 characters; "
            "never from CUSTOMER NAME or LEAD CONTEXT; else null.",
        },
        "intent": _enum(INTENTS),
        "for_client": _bool("True if they look for a client of theirs (a broker or an agent), false if for themselves, null until they say."),
        "abroad": _bool("True if they are outside the UAE or cannot visit, else null."),
        "in_dubai": _bool("True if they are in Dubai now, false if they are coming from abroad, else null."),
        "property_type": _text("studio, 1BR, apartment, ... in English, else null."),
        "bedrooms": _text("Number of bedrooms as said, else null."),
        "community": _text("The area or community they want, else null."),
        "clusters": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The International City clusters they want, by name (\"Spain\"); [] when none.",
        },
        "cluster_flexible": _bool("True if any cluster is fine for them, else null."),
        "balcony": _enum(BALCONY, "yes, no or either, as they said; else null."),
        "budget_aed": _number("Their own budget in AED as a number, never one of our prices; else null."),
        "budget_basis": _enum(BUDGET_BASIS),
        "payment": _enum(PAYMENT),
        "occupancy": _enum(RES_OCCUPANCY, "myself, family, company_staff or sharing, as they said; else null."),
        "occupants": _number("How many people would stay, as a number; else null."),
        "contract": _enum(CONTRACT, "individual or company: whose name the contract would be in; else null."),
        "move_in": _text("When they plan to move in, e.g. 'next month', else null."),
        "occupancy_status": _enum(RES_OCCUPANCY_STATUS, "A buyer's choice: a vacant unit, a tenanted (rented) one, or either; else null."),
        "buy_timeline": _text("How soon a buyer plans to buy, e.g. 'within 3 months', else null."),
        "purpose": _enum(PURPOSE, "A buyer's purpose: investment or personal use; else null."),
        "email": _text("An e-mail address only when they give one, else null; never ask for it."),
        "already_rented": _bool("True if they already rented or found a place, else null."),
        "notes": shops_facts["notes"],
    }
    node["properties"]["facts"]["properties"] = {key: properties[key] for key in RES_FACT_KEYS}
    node["properties"]["facts"]["required"] = list(RES_FACT_KEYS)
    node["properties"]["handover"]["properties"]["reason"] = _enum(RES_HANDOVER_REASONS)
    node["properties"]["appointment"]["properties"]["place"] = _enum(RES_PLACES)
    # The model's tag for what the customer wants, right after the facts: code reads it (tracks.decide), never a handover.
    ordered = {}
    for key, value in node["properties"].items():
        ordered[key] = value
        if key == "facts":
            ordered["need_tag"] = _enum(
                NEED_TAGS,
                "What they say they want when it is not the TRACK's: wants_shop, wants_rent, wants_buy, other_need (a bigger "
                "home, a villa, a room or bed space, selling or letting their own, buying a shop) or other_area; else null.",
            )
    node["properties"] = ordered
    node["required"] = [key for key in ordered]
    return node


RES_SCHEMA = _res_schema()


def schema_for(shops: bool, residential: bool = False) -> dict:
    if residential:
        return RES_SCHEMA
    return SHOPS_SCHEMA if shops else SCHEMA


def _clusters(value) -> list[str]:
    """The clusters a residential answer recorded: short names, letters and spaces only, at most CLUSTERS_MAX, each once."""
    items = value if isinstance(value, list) else []
    out: list[str] = []
    for item in items:
        text = _clean(item, CLUSTER_MAX) if isinstance(item, str) else None
        if text and re.fullmatch(r"[^\W\d_][^\W\d_ '\-]*", text) and text.casefold() not in {name.casefold() for name in out}:
            out.append(text)
    return out[:CLUSTERS_MAX]


def _full_name(value):
    text = _clean(value, FULL_NAME_MAX + 1)
    if not text or len(text) > FULL_NAME_MAX or any(ch.isdigit() for ch in text) or "@" in text:
        return None
    return text


def _email(value):
    text = str(value or "").strip().lower()
    return text if _EMAIL.match(text) else None


def _normalize_res_facts(facts_in: dict) -> dict:
    facts = {}
    for key in RES_FACT_KEYS:
        value = facts_in.get(key)
        if key == "notes":
            facts[key] = _notes(value)
        elif key == "clusters":
            facts[key] = _clusters(value)
        elif key == "full_name":
            facts[key] = _full_name(value)
        elif key == "email":
            facts[key] = _email(value)
        elif key in RES_TEXT_FACTS:
            facts[key] = _clean(value)
        elif key in RES_NUMBER_FACTS:
            number = _number_value(value)
            if key == "occupants" and number is not None and (number > OCCUPANTS_MAX or not float(number).is_integer()):
                number = None
            facts[key] = number
        elif key in RES_BOOL_FACTS:
            facts[key] = value if isinstance(value, bool) else None
        else:
            facts[key] = _enum_value(value, RES_ENUM_FACTS[key])
    return facts


def _notes(value) -> list[str]:
    """The questions for our agent: short English strings, at most NOTES_MAX, no repeats."""
    items = value if isinstance(value, list) else []
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        text = _clean(item, NOTE_MAX)
        if text and text.casefold() not in {note.casefold() for note in out}:
            out.append(text)
    return out[:NOTES_MAX]


def clean_note(value) -> str:
    """One question for our agent, cleaned as a model's note is (_notes): one line, no brackets, NOTE_MAX characters."""
    return _clean(value, NOTE_MAX) or ""


def _clean(value, limit: int = TEXT_MAX):
    if value is None:
        return None
    text = " ".join(str(value).split())
    # Square brackets would open BB-code, angle brackets HTML, in Bitrix
    # comments and notifications.
    text = text.replace("[", "(").replace("]", ")").replace("<", "(").replace(">", ")")
    if not text or text.lower() in ("null", "none", "unknown", "n/a", "-"):
        return None
    return text[:limit]


def _enum_value(value, allowed):
    text = str(value or "").strip().lower()
    return text if text in allowed else None


def _number_value(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 1e12 else None


def normalize(data: dict, shops: bool = False, residential: bool = False) -> dict:
    """The model's answer with every value cleaned, bounded and checked.

    ``shops``: the answer follows SHOPS_SCHEMA (a shops chat); ``residential``: RES_SCHEMA (a rent, sale or not-known chat
    of the International City campaign, batch 2e), whose answer also carries ``need_tag``.
    """
    data = data if isinstance(data, dict) else {}
    facts_in = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    facts = {}
    keys, texts, bools, enums = (
        (SHOPS_FACT_KEYS, SHOPS_TEXT_FACTS, SHOPS_BOOL_FACTS, SHOPS_ENUM_FACTS) if shops else (FACT_KEYS, TEXT_FACTS, BOOL_FACTS, ENUM_FACTS)
    )
    if residential:
        facts = _normalize_res_facts(facts_in)
    else:
        for key in keys:
            value = facts_in.get(key)
            if shops and key == "notes":
                facts[key] = _notes(value)
            elif key in texts:
                facts[key] = _clean(value)
            elif key in NUMBER_FACTS:
                facts[key] = _number_value(value)
            elif key in bools:
                facts[key] = value if isinstance(value, bool) else None
            else:
                facts[key] = _enum_value(value, enums[key])

    appointment_in = data.get("appointment") if isinstance(data.get("appointment"), dict) else {}
    action = _enum_value(appointment_in.get("action"), ACTIONS) or "none"
    appointment = {
        "action": action,
        "place": _enum_value(appointment_in.get("place"), RES_PLACES if residential else PLACES),
        "date": _clean(appointment_in.get("date"), 10),
        "time": _clean(appointment_in.get("time"), 5),
        "customer_words": _clean(appointment_in.get("customer_words"), 255),
    }

    handover_in = data.get("handover") if isinstance(data.get("handover"), dict) else {}
    reasons = RES_HANDOVER_REASONS if residential else (SHOPS_HANDOVER_REASONS if shops else HANDOVER_REASONS)
    reason = _enum_value(handover_in.get("reason"), reasons)
    needed = handover_in.get("needed") is True
    send = data.get("send") is not False
    reply = str(data.get("reply") or "").strip() if send else ""
    answer = {
        "language": _enum_value(data.get("language"), LANGUAGES) or "en",
        "segment": _enum_value(data.get("segment"), SEGMENTS) or "other",
        "facts": facts,
        "appointment": appointment,
        "handover": {"needed": needed, "reason": reason if needed else None},
        "opt_out": _enum_value(data.get("opt_out"), SHOPS_OPT_OUT if (shops or residential) else OPT_OUT) or "none",
        "hot_lead": data.get("hot_lead") is True,
        "invited_to_meeting": data.get("invited_to_meeting") is True,
        "share_office_location": data.get("share_office_location") is True,
        "send": send and bool(reply),
        "reply_en": str(data.get("reply_en") or "").strip()[:REPLY_MAX],
        "reply": reply,
    }
    if residential:
        tag = _enum_value(data.get("need_tag"), NEED_TAGS)
        if tag:
            answer["need_tag"] = tag
    return answer
