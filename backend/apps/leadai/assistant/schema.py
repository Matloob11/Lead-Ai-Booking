"""The answer the model must give on every turn (OpenAI structured outputs, strict).

Keys are generated in schema order, so every decision comes before the words:
language, segment, facts, appointment, handover, opt_out, flags, send, and
the reply last. Strict mode wants every property in ``required`` and
``additionalProperties: false``; "unknown" is null through a type list, and a
nullable enum lists null in both its type and its values. ``normalize`` then
cleans whatever came back: the schema shapes the answer, code is the gate.
"""

from __future__ import annotations

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
        "reply_en": {"type": "string", "description": "English meaning of reply for our agents; empty when reply is English."},
        "reply": {"type": "string", "description": "The WhatsApp message to send; empty when send is false."},
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
        "reply_en",
        "reply",
    ],
}


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


def normalize(data: dict) -> dict:
    """The model's answer with every value cleaned, bounded and checked."""
    data = data if isinstance(data, dict) else {}
    facts_in = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    facts = {}
    for key in FACT_KEYS:
        value = facts_in.get(key)
        if key in TEXT_FACTS:
            facts[key] = _clean(value)
        elif key in NUMBER_FACTS:
            facts[key] = _number_value(value)
        elif key in BOOL_FACTS:
            facts[key] = value if isinstance(value, bool) else None
        else:
            facts[key] = _enum_value(value, ENUM_FACTS[key])

    appointment_in = data.get("appointment") if isinstance(data.get("appointment"), dict) else {}
    action = _enum_value(appointment_in.get("action"), ACTIONS) or "none"
    appointment = {
        "action": action,
        "place": _enum_value(appointment_in.get("place"), PLACES),
        "date": _clean(appointment_in.get("date"), 10),
        "time": _clean(appointment_in.get("time"), 5),
        "customer_words": _clean(appointment_in.get("customer_words"), 255),
    }

    handover_in = data.get("handover") if isinstance(data.get("handover"), dict) else {}
    reason = _enum_value(handover_in.get("reason"), HANDOVER_REASONS)
    needed = handover_in.get("needed") is True
    send = data.get("send") is not False
    reply = str(data.get("reply") or "").strip() if send else ""
    return {
        "language": _enum_value(data.get("language"), LANGUAGES) or "en",
        "segment": _enum_value(data.get("segment"), SEGMENTS) or "other",
        "facts": facts,
        "appointment": appointment,
        "handover": {"needed": needed, "reason": reason if needed else None},
        "opt_out": _enum_value(data.get("opt_out"), OPT_OUT) or "none",
        "hot_lead": data.get("hot_lead") is True,
        "invited_to_meeting": data.get("invited_to_meeting") is True,
        "share_office_location": data.get("share_office_location") is True,
        "send": send and bool(reply),
        "reply_en": str(data.get("reply_en") or "").strip()[:REPLY_MAX],
        "reply": reply,
    }
