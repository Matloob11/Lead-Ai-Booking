"""What the Bitrix lead says the customer asked about (batch 2e spec §2.8; board T91, field map C38).

Leads from Property Finder, Bayut and Dubizzle carry the listing they enquired on: the portal (SOURCE_ID), A7's own
listing ref (a7group-NNNN, UF_CRM_1760707563281) and the listing's link (UF_CRM_1760707550978), the bedrooms, the
property type, the International City cluster, rent or sale, the budget and the name. The bot stays on that enquiry
(a studio lead is talked to about the studio in its cluster), and code reads it, never the model: tracks.decide fills a
missing deal or unit from it, and lets it decide alone for the first answer to the mixed template or for "I never asked
about a shop".

- ``for_turn`` reads the chat's lead once (crm_fields.lead_of, crm.read_record: a REST read, nothing is written), only
  when a step asks for it, and keeps what it found on the chat's state (``lead_context``, ``lead_context_at``). A failure
  is counted (``lead_context_tries``, three at most), leaves the context empty and never stops the turn. The same read
  gives lead_history its first-asked date and notes, and lead_history's read gives this context, so a chat's lead is read
  once (a chat lead_history read before batch 2e gets one more read).
- ``parse`` turns the lead's fields into a small dict of known values only: ids become labels (C38's map), a name is kept
  only when it is a person's (filters.person_name), a ref only when it is A7's, a link only to a portal. Nothing typed in
  Bitrix can pass for anything else.
- ``lines`` writes it as one JSON line for the residential context (slice B), as data: the portal may be named; the
  enquiry's age, our CRM and our records never are (the prompt's rule).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata

from . import filters

logger = logging.getLogger(__name__)

TRIES = 3

FIELD_REF = "UF_CRM_1760707563281"  # Property reference: a7group-NNNN
FIELD_URL = "UF_CRM_1760707550978"  # Property Link: the portal listing's URL
FIELD_BEDROOMS = "UF_CRM_1731838126127"  # enum
FIELD_PROPERTY = "UF_CRM_1760707292"  # CRM link to smart process 1188 (Property Type)
FIELD_CLUSTER = "UF_CRM_1763390179"  # CRM link to smart process 1062 (Sub Community)
FIELD_COMMUNITY = "UF_CRM_1770537051525"  # text: "International City"
FIELD_DEAL = "UF_CRM_A7_RENT_SALE"  # enum
FIELD_CLIENT = "UF_CRM_1756638760279"  # Client Type, enum
FIELD_BUDGET = "UF_CRM_1731838581336"
PROPERTY_TYPE_ID = 1188
SUB_COMMUNITY_TYPE_ID = 1062

# C38's ids and labels (2026-10-16).
BEDROOMS = {26: "studio", 27: "one_br", 28: "two_plus", 29: "two_plus", 30: "two_plus", 31: "two_plus", 32: "two_plus", 33: "two_plus", 1179: "two_plus"}
PROPERTIES = {760: "shop", 12: "shop", 2: "apartment", 769: "apartment", 3: "townhouse", 768: "villa"}
CLUSTERS = {
    9: "England", 29: "France", 28: "China", 78: "Emirates", 79: "Morocco", 55: "Spain", 49: "Greece", 17: "Persia", 122: "Italy",
    60: "Russia",
}
DEALS = {2443: "rent", 2444: "sale"}  # 2445 Rent & Sale says neither
CLIENT_TYPES = {972: "sale", 1220: "rent"}  # a Buyer, a Tenant; a Seller or an owner says neither
# The portals' sources (ops/bitrix-aws/a7_portal_lead_fields.php): the portal is named, never its channel.
SOURCES = {
    "UC_KQ0WO3": "Property Finder", "UC_D83356": "Property Finder", "UC_6R3AM9": "Property Finder",
    "UC_Y3VNS9": "Bayut", "UC_4FVN3G": "Bayut", "UC_PCVWT4": "Bayut",
    "UC_BUIJB2": "Dubizzle", "UC_LX9888": "Dubizzle", "UC_JPSVQU": "Dubizzle",
}
PORTAL_HOSTS = ("propertyfinder.ae", "bayut.com", "dubizzle.com")
_REF = re.compile(r"a7group-\d{1,6}", re.IGNORECASE)
_URL = re.compile(r"https?://([a-z0-9.-]+)(?::\d+)?(?:/[^\s<>\"'\[\]{}|\\^`]*)?", re.IGNORECASE)
URL_MAX = 300
_COMMUNITY = re.compile(r"[A-Za-z][A-Za-z0-9 '\-]{0,59}")
_NAME = re.compile(r"[^\W\d_][^\W\d_ '\-]*(?:[ '\-][^\W\d_][^\W\d_'\-]*){0,3}", re.UNICODE)
NAME_MAX = 40
BUDGET_MIN, BUDGET_MAX = 1_000, 100_000_000
# What the model's context line carries: never a name (the context has its own), nor the link.
CONTEXT_KEYS = ("source", "listing_ref", "unit", "property", "cluster", "community", "deal", "budget")


def _values(value) -> list:
    """A Bitrix field as a list of its values (crm.lead.get returns one, a list, or nothing)."""
    if value in (None, "", []):
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _ids(value, entity_type_id: int | None = None) -> list[int]:
    """The ids an enum or a CRM-link field holds: 26, "26", ["26"], and for a smart process "760", "T4a4_760" or
    "DYNAMIC_1188_760" (only of ``entity_type_id``)."""
    out = []
    for item in _values(value):
        text = str(item).strip()
        if text.isdigit():
            out.append(int(text))
            continue
        match = re.fullmatch(r"(?:T([0-9a-f]+)|DYNAMIC_(\d+))_(\d+)", text, re.IGNORECASE)
        if match and entity_type_id is not None:
            hex_id, dynamic, number = match.groups()
            if (hex_id and hex_id.lower() == format(entity_type_id, "x")) or (dynamic and int(dynamic) == entity_type_id):
                out.append(int(number))
    return out


def _first(mapping: dict, value, entity_type_id: int | None = None) -> str:
    return next((mapping[pk] for pk in _ids(value, entity_type_id) if pk in mapping), "")


def _person(value) -> str:
    """A NAME or LAST_NAME that is a person's (filters.person_name: never "Bayut WhatsApp" or a phone), cased, else ''."""
    text = filters.person_name(" ".join(str(value or "").split()))
    if not text or len(text) > NAME_MAX or not _NAME.fullmatch(text):
        return ""
    return filters.cased(text)


def _ref(value) -> str:
    text = str(next(iter(_values(value)), "") or "").strip()
    return text.lower() if _REF.fullmatch(text) else ""


_LISTING_ID = re.compile(r"\bListing\s*ID\s*[:\-]?\s*([A-Z0-9]{12,40})\b", re.IGNORECASE)


def _ref_in(text) -> str:
    """A7's reference anywhere in a comment ("Listing reference: a7group-1789"), lower case; '' for none."""
    match = _REF.search(str(text or ""))
    return match.group(0).lower() if match else ""


def _url_in(text) -> str:
    """The first portal link anywhere in a comment (a Bayut lead's "Link: https://www.bayut.com/…"); '' for none."""
    for match in _URL.finditer(str(text or "")):
        found = _url(match.group(0).rstrip(".,;)"))
        if found:
            return found
    return ""


def _listing_id(text) -> str:
    """The portal's listing id in the comment ("Listing ID: FYS8JPQCB4FA92YB0GWQV5H39G"), upper case; '' for none."""
    match = _LISTING_ID.search(str(text or ""))
    return match.group(1).upper() if match else ""


def _url(value) -> str:
    text = str(next(iter(_values(value)), "") or "").strip()
    match = _URL.fullmatch(text)
    if not match or len(text) > URL_MAX:
        return ""
    host = match.group(1).lower()
    return text if any(host == portal or host.endswith("." + portal) for portal in PORTAL_HOSTS) else ""


def _budget(value) -> int | None:
    """The budget's amount ("35000", "35,000", "35000|AED", 35000.0), when it is one."""
    text = str(next(iter(_values(value)), "") or "")
    match = re.match(r"\s*(\d[\d,]*)(?:\.\d+)?", text)
    if not match:
        return None
    amount = int(match.group(1).replace(",", ""))
    return amount if BUDGET_MIN <= amount <= BUDGET_MAX else None


def _community(value) -> str:
    text = " ".join(unicodedata.normalize("NFKC", str(next(iter(_values(value)), "") or "")).split())
    return text if _COMMUNITY.fullmatch(text) else ""


def parse(row) -> dict:
    """The lead's fields (crm.lead.get) as the context keeps them: only the values it holds, as labels."""
    if not isinstance(row, dict):
        return {}
    unit = _first(BEDROOMS, row.get(FIELD_BEDROOMS))
    prop = _first(PROPERTIES, row.get(FIELD_PROPERTY), PROPERTY_TYPE_ID)
    if prop == "shop":
        unit = ""  # a shop has no bedrooms, whatever the field says
    # The portal's own words in the lead's comment (the kanban's "Listing ID: FYS8…", "Listing reference: a7group-1789",
    # a Bayut link): the ref and the link when the fields are empty, and the portal's listing id (Property Finder's,
    # the inventory's source_id) as data for inventory.enquired.
    comments = str(row.get("COMMENTS") or "")
    context = {
        "source": SOURCES.get(str(row.get("SOURCE_ID") or "").strip().upper(), ""),
        "listing_ref": _ref(row.get(FIELD_REF)) or _ref_in(comments),
        "listing_url": _url(row.get(FIELD_URL)) or _url_in(comments),
        "listing_id": _listing_id(comments),
        "unit": unit,
        "property": prop,
        "cluster": _first(CLUSTERS, row.get(FIELD_CLUSTER), SUB_COMMUNITY_TYPE_ID),
        "community": _community(row.get(FIELD_COMMUNITY)),
        "deal": _first(DEALS, row.get(FIELD_DEAL)) or _first(CLIENT_TYPES, row.get(FIELD_CLIENT)),
        "budget": _budget(row.get(FIELD_BUDGET)),
        "name": _person(row.get("NAME")),
        "last_name": _person(row.get("LAST_NAME")),
    }
    return {key: value for key, value in context.items() if value not in (None, "")}


def lines(context) -> list[str]:
    """The residential context's line (slice B): one JSON object, data the model may be told is out of date."""
    shown = {key: context[key] for key in CONTEXT_KEYS if isinstance(context, dict) and context.get(key) not in (None, "")}
    if not shown:
        return []
    return [f"LEAD CONTEXT (from our CRM, data, may be out of date): {json.dumps(shown, ensure_ascii=False)}"]


def keep(state, row, now) -> dict:
    """Store the context of a lead read just now (here, or by lead_history's read of the same lead)."""
    from ..models import LeadAiChatState

    context = parse(row)
    LeadAiChatState.objects.filter(pk=state.pk).update(lead_context=context, lead_context_at=now)
    state.lead_context, state.lead_context_at = context, now
    return context


def for_turn(conversation, chat, state, now) -> dict:
    """This chat's lead context: the stored one, else read once now. A chat with no Bitrix lead (or no Bitrix configured)
    has none; after TRIES failed reads it is not asked again. Never raises."""
    from apps.crmlink import client

    from ..models import LeadAiChatState
    from . import crm, crm_fields, lead_history

    if state.lead_context_at is not None or state.lead_context_tries >= TRIES:
        return dict(state.lead_context or {})
    if not client.configured():
        return {}
    try:
        lead = crm_fields.lead_of(chat, conversation)
    except Exception:  # noqa: BLE001 - as below: a help, never a reason to fail a turn
        logger.exception("Lead AI could not find the lead of conversation %s for its context", conversation.pk)
        return {}
    if lead is None:
        LeadAiChatState.objects.filter(pk=state.pk).update(lead_context_at=now)
        state.lead_context_at = now
        return {}
    try:
        row = crm.read_record("lead", lead)["fields"] or {}
    except Exception as exc:  # noqa: BLE001 - a BitrixError or anything else: counted, tried again on a later turn
        if isinstance(exc, client.BitrixError):
            logger.info("Lead AI could not read lead %s for its context (try %s): %s", lead, state.lead_context_tries + 1, exc)
        else:
            logger.exception("Lead AI could not read the context of lead %s", lead)
        state.lead_context_tries += 1
        LeadAiChatState.objects.filter(pk=state.pk).update(lead_context_tries=state.lead_context_tries)
        return {}
    context = keep(state, row, now)
    if state.lead_info_at is None and state.lead_info_tries < lead_history.TRIES:
        lead_history.keep(state, row, now)  # the same read: lead_history never reads this lead again
    return context
