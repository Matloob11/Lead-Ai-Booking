"""Leads-list bulk template send: Bitrix toolbar → Official campaign.

The CRM page has a Bitrix session, not a Django cookie. The PHP tool on the
portal signs the JSON body; we check that HMAC and then act as the Agent
matched on ``bitrix_user_id``. The From number defaults to that agent's primary Official assignment.
The studio can pick any number on ``agent.visible_numbers`` (same rule as
the Campaigns screen). A template with an image, video or document header
travels with a token from ``crm_media`` for the file the popup uploaded.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import logging
import re
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import WaTemplate, WaTemplateHide
from apps.catalog.views import serialize_template
from apps.inbox.transfer import official_number_for
from apps.inbox.serializers import serialize_number

from .models import CampaignRecipient
from .services import CampaignError, create_campaign
from .tasks import run_campaign

logger = logging.getLogger(__name__)

MAX_LEADS = 500
MAX_SKEW_SEC = 300
# Live Bitrix enums (C3). Lead AI must not message these.
BOT_STATUS_BROKER = 2479
BOT_STATUS_LOST = 2480
BOT_STATUS_OPTED_OUT = 2481
WA_OPT_OUT_YES = 2482
TEMPLATE_REPEAT_DAYS = 30
# Stable skip reasons. The popup counts the same words.
_LEFT_OUT = (
    ("Opted out.", "opted out"),
    ("Broker.", "broker"),
    ("Lost.", "lost"),
    ("Already talking to Lead AI.", "already talking to Lead AI"),
    ("Sent this template in the last 30 days.", "already sent"),
)


class CrmLeadSendError(CampaignError):
    pass


def shared_secret() -> str:
    """Same value the Bitrix PHP tool keeps in a7_lead_wa.config.php."""
    return (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()


def verify_signed_request(*, timestamp: str, signature: str, body: bytes) -> None:
    secret = shared_secret()
    if not secret:
        raise CrmLeadSendError("CRM lead WhatsApp send is not configured.")
    try:
        ts = int(str(timestamp or "").strip())
    except (TypeError, ValueError) as exc:
        raise CrmLeadSendError("Missing request timestamp.") from exc
    if abs(int(time.time()) - ts) > MAX_SKEW_SEC:
        raise CrmLeadSendError("Request expired. Refresh the page and try again.")
    presented = (signature or "").strip().lower()
    # Shape first: compare_digest raises on non-ASCII header bytes, which
    # turned a forged request into a 500 instead of a 403.
    if not re.fullmatch(r"[0-9a-f]{64}", presented):
        raise CrmLeadSendError("Forbidden.")
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("ascii") + (body or b""),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(presented, expected):
        raise CrmLeadSendError("Forbidden.")


def agent_for_bitrix_user(bitrix_user_id) -> object:
    bitrix_id = str(bitrix_user_id or "").strip()
    if not bitrix_id.isdigit():
        raise CrmLeadSendError("Bitrix user is missing.")
    Agent = get_user_model()
    agent = Agent.objects.filter(bitrix_user_id=bitrix_id, is_active=True).first()
    if not agent:
        raise CrmLeadSendError(
            "This Bitrix user has no WhatsApp inbox login. Open the WhatsApp "
            "panel once, then ask an admin to assign your Official number."
        )
    if not agent.can_official_api:
        raise CrmLeadSendError("Official WhatsApp is not enabled for this agent.")
    return agent


def assigned_official_number(agent):
    number = official_number_for(agent)
    if number is None:
        raise CrmLeadSendError(
            "No Official WhatsApp number is assigned to you. Ask an admin."
        )
    return number


def official_numbers_for(agent) -> list:
    """Numbers this agent may send a CRM-lead campaign from.

    Same visibility as the Official Campaigns screen: assigned numbers for
    agents, every active Official number for admins.
    """
    primary = official_number_for(agent)
    numbers = list(agent.visible_numbers.order_by("phone_number"))
    if primary and all(n.pk != primary.pk for n in numbers):
        numbers.insert(0, primary)
    if primary:
        numbers.sort(key=lambda n: (0 if n.pk == primary.pk else 1, n.phone_number or ""))
    return numbers


def number_for_agent(agent, number_id=None):
    if number_id in (None, "", 0, "0"):
        numbers = official_numbers_for(agent)
        if not numbers:
            raise CrmLeadSendError(
                "No Official WhatsApp number is assigned to you. Ask an admin."
            )
        return official_number_for(agent) or numbers[0]
    try:
        pk = int(number_id)
    except (TypeError, ValueError) as exc:
        raise CrmLeadSendError("Pick a WhatsApp number to send from.") from exc
    number = agent.visible_numbers.filter(pk=pk).first()
    if number is None:
        primary = official_number_for(agent)
        if primary is None or primary.pk != pk:
            raise CrmLeadSendError("That WhatsApp number is not available to you.")
        return primary
    return number


def _meta_body_vars(raw) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (raw or {}).items():
        if not str(key).isdigit():
            continue
        text = str(value or "").strip()
        if text:
            out[str(key)] = text
    return out


ENTITY_NOUNS = {
    "lead": ("lead", "leads", "CRM Leads"),
    "owner_data": ("Owner Data card", "Owner Data cards", "Owner Data"),
    "deal": ("deal", "deals", "CRM Deals"),
    "contact": ("contact", "contacts", "CRM Contacts"),
}


def crm_entity(raw) -> str:
    text = str(raw or "lead").strip().lower()
    if text in {"owner_data", "1042", "dynamic_1042", "dynamic1042"}:
        return "owner_data"
    if text in {"deal", "contact"}:
        return text
    return "lead"


# What the CRM campaign popup may map a template {{n}} onto. Empty → "?".
DETAIL_FIELDS = (
    "name",
    "phone",
    "source",
    "stage",
    "community",
    "sub_community",
    "bedrooms",
    "client_type",
    "deal_amount",
    "property_reference",
)


def parse_field_map(raw) -> dict[str, str]:
    """``{"1": "community"}`` — only known lead details, digit keys."""
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    allowed = set(DETAIL_FIELDS)
    for key, value in raw.items():
        slot = str(key).strip()
        field = str(value or "").strip()
        if slot.isdigit() and field in allowed:
            out[slot] = field
    return out


# A portal title ("Bayut WhatsApp | Md Sumon") is not a greeting. Neither is a
# phone, a missed-call row, or an empty Bitrix name.
_BAD_GREETING = re.compile(r"^(untitled|unentitled|none|field is empty)$", re.IGNORECASE)
_MISSED_CALL = re.compile(r"^missed\s+call\b", re.IGNORECASE)
_GREETING_FALLBACK = "there"
_HONORIFICS = frozenset({
    "md", "mohd", "muhammad", "mohammad", "mohammed", "muhammed", "mohamed",
    "dr", "mr", "mrs", "ms", "miss", "engr", "eng",
})
# Own copy of apps.leadai.assistant.filters._NOT_NAMES portal words, plus call.
_PORTAL_WORDS = frozenset({
    "bayut", "property", "propertyfinder", "dubizzle", "portal", "whatsapp",
    "call",
})


def _squash(value) -> str:
    return " ".join(str(value or "").split())


def _bad_greeting(text: str) -> bool:
    if not text or _BAD_GREETING.match(text) or _MISSED_CALL.match(text):
        return True
    letters = sum(ch.isalpha() for ch in text)
    digits = sum(ch.isdigit() for ch in text)
    # No letters at all, or a full phone hiding in the field.
    return letters == 0 or digits >= 8


def _portal_candidate(text: str) -> bool:
    """First word is a portal/channel word, or the whole string is a missed call."""
    text = _squash(text)
    if not text or _MISSED_CALL.match(text):
        return True
    word = text.split()[0].casefold().rstrip(".")
    return word in _PORTAL_WORDS


def _after_pipe(text: str) -> str:
    if "|" not in text:
        return text
    return _squash(text.rsplit("|", 1)[-1])


def _honorific(word: str) -> bool:
    return word.casefold().rstrip(".") in _HONORIFICS


def _skip_honorific(text: str) -> str:
    """Md / Mr / Dr and the rest, with or without a dot, are not the given name."""
    parts = text.split()
    if len(parts) >= 2 and _honorific(parts[0]) and not _bad_greeting(parts[1]):
        return parts[1]
    return text


def _try_greeting(text: str, *, first_word: bool = False) -> str:
    """One candidate: reject portal words, then C8 honorific, then maybe first word."""
    text = _squash(text)
    if not text or _portal_candidate(text) or _bad_greeting(text):
        return ""
    text = _skip_honorific(text)
    if not text or _portal_candidate(text) or _bad_greeting(text):
        return ""
    if first_word:
        word = text.split()[0]
        if _portal_candidate(word) or _bad_greeting(word):
            return ""
        return word[:200]
    return text[:200]


def detail_value(row: dict, key: str) -> str:
    """One lead's value for a mapped variable.

    Name is the greeting from ``lead_display_name`` (never "?"). Every other
    blank, untitled, or missing detail is "?".
    """
    if key == "name":
        return lead_display_name(row)
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    raw = details.get(key)
    if (raw is None or not str(raw).strip()) and key == "phone":
        raw = "".join(ch for ch in str(row.get("phone") or "") if ch.isdigit())
    text = " ".join(str(raw or "").split())
    if not text or text.lower() in {"untitled", "unentitled", "none", "field is empty"}:
        return "?"
    return text[:200]


def lead_display_name(row: dict) -> str:
    """First name for {{1}} and ``CampaignRecipient.name``.

    Candidates in order (C23): Bitrix NAME (``first_name`` or ``name``); the
    part after NAME's last ``|`` when it has one; TITLE after its last ``|``
    when it has one. A candidate whose first word is a portal/channel word
    (bayut, property, whatsapp, call, …) is skipped. Each surviving candidate
    goes through the C8 honorific rule. NAME uses its first usable word;
    after-pipe / TITLE keep the person string. A phone, "Missed Call…",
    "untitled", or nothing usable becomes "there". A completely blank row is
    "" so a caller can apply its own fallback.
    """
    if not isinstance(row, dict):
        return _GREETING_FALLBACK
    first = _squash(row.get("first_name"))
    title = _squash(row.get("title"))
    name = _squash(row.get("name"))
    bitrix_name = first or name
    if not bitrix_name and not title:
        return ""
    # Deal contact name kept when it is not the deal title.
    if (
        not first
        and name
        and title
        and name.casefold() != title.casefold()
    ):
        picked = _try_greeting(name, first_word=False)
        if picked:
            return picked
    if bitrix_name:
        picked = _try_greeting(bitrix_name, first_word=True)
        if picked:
            return picked
        if "|" in bitrix_name:
            picked = _try_greeting(_after_pipe(bitrix_name), first_word=False)
            if picked:
                return picked
    if title:
        source = _after_pipe(title) if "|" in title else title
        picked = _try_greeting(source, first_word=False)
        if picked:
            return picked
    return _GREETING_FALLBACK


def _item_id(raw: dict) -> int:
    for key in ("id", "lead_id", "owner_data_id"):
        try:
            value = int(raw.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _enum_id(value) -> int:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def opt_out_reason(raw: dict) -> str:
    """WhatsApp Opt-out Yes or Bot Status Opted out. Every campaign, box on or off."""
    opt = _enum_id(raw.get("wa_opt_out"))
    bot = _enum_id(raw.get("bot_status"))
    if opt == WA_OPT_OUT_YES or bot == BOT_STATUS_OPTED_OUT:
        return "Opted out."
    return ""


def lead_ai_skip_reason(raw: dict) -> str:
    """Broker and Lost. Lead AI only; an opt-out is ``opt_out_reason``."""
    if opt_out_reason(raw):
        return "Opted out."
    bot = _enum_id(raw.get("bot_status"))
    if bot == BOT_STATUS_BROKER:
        return "Broker."
    if bot == BOT_STATUS_LOST:
        return "Lost."
    return ""


def left_out_sentence(skipped: list[dict]) -> str:
    """``3 left out: opted out 1, broker 1, lost 1``. Empty when none of these reasons."""
    counts = {reason: 0 for reason, _label in _LEFT_OUT}
    for row in skipped or []:
        reason = str((row or {}).get("reason") or "")
        if reason in counts:
            counts[reason] += 1
    parts = []
    total = 0
    for reason, label in _LEFT_OUT:
        count = counts[reason]
        if count:
            total += count
            parts.append(f"{label} {count}")
    if not total:
        return ""
    return f"{total} left out: {', '.join(parts)}"


def _canon_phone(value) -> str:
    from .phones import normalize_phone

    return normalize_phone(str(value or "")) or ""


def _lead_phones(row: dict) -> set[str]:
    raw = row.get("PHONE") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    elif isinstance(raw, str):
        raw = [raw]
    found: set[str] = set()
    for item in raw or []:
        if isinstance(item, dict):
            item = item.get("VALUE")
        phone = _canon_phone(item)
        if phone:
            found.add(phone)
    return found


def bitrix_opted_out_phones(phones: set[str]) -> set[str]:
    """Phones on leads whose WhatsApp Opt-out is Yes or Bot Status is Opted out.

    Empty when no webhook is configured, or the portal cannot be asked.
    """
    if not phones:
        return set()
    from apps.crmlink import client as bitrix

    if not bitrix.configured():
        return set()
    wanted = {phone for phone in (_canon_phone(raw) for raw in phones) if phone}
    if not wanted:
        return set()
    found: set[str] = set()
    try:
        for field, value in (
            ("UF_CRM_A7_WA_OPT_OUT", WA_OPT_OUT_YES),
            ("UF_CRM_A7_BOT_STATUS", BOT_STATUS_OPTED_OUT),
        ):
            start = 0
            for _page in range(40):
                result = bitrix.call(
                    "crm.lead.list",
                    {
                        "filter": {field: value},
                        "select": ["ID", "PHONE"],
                        "start": start,
                    },
                )
                rows = result if isinstance(result, list) else []
                if not rows:
                    break
                for row in rows:
                    if isinstance(row, dict):
                        found |= _lead_phones(row) & wanted
                if found >= wanted or len(rows) < 50:
                    break
                start += 50
            if found >= wanted:
                break
    except bitrix.BitrixError:
        logger.warning("Could not read opted-out leads from Bitrix")
        return found
    return found


def phones_opted_out(phones: set[str]) -> set[str]:
    """Phones no campaign may message.

    The T60 registry (``phones_blocked_by_registry``) and leads marked
    WhatsApp Opt-out Yes or Bot Status Opted out. Broker and Lost are not
    in this set.
    """
    if not phones:
        return set()
    blocked = set(phones_blocked_by_registry(phones))
    blocked |= bitrix_opted_out_phones(phones)
    return {phone for phone in (_canon_phone(raw) for raw in blocked) if phone}


def drop_opted_out_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Take opted-out phones out of a sheet or a pasted list. Same reason string."""
    phones = {
        str(row.get("phone") or "")
        for row in rows or []
        if isinstance(row, dict) and row.get("phone")
    }
    blocked = phones_opted_out(phones)
    kept: list[dict] = []
    skipped: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        phone = str(row.get("phone") or "")
        canon = _canon_phone(phone)
        if phone in blocked or (canon and canon in blocked):
            skipped.append({"phone": phone, "reason": "Opted out."})
            continue
        kept.append(row)
    return kept, skipped


def phones_blocked_by_registry(phones: set[str]) -> set[str]:
    """Phones the global WhatsApp opt-out registry refuses.

    T60 adds ``apps.leadai.optout.phones_blocked``. Until that module exists,
    this returns an empty set and campaigns are unchanged.
    """
    if not phones:
        return set()
    try:
        from apps.leadai import optout as registry
    except ImportError:
        return set()
    blocked = getattr(registry, "phones_blocked", None)
    if not callable(blocked):
        return set()
    found = blocked(phones)
    out: set[str] = set()
    for raw in found or []:
        digits = _digits(raw)
        if digits:
            out.add(digits)
    return out


def phones_in_active_lead_ai(phones: set[str]) -> set[str]:
    """Phones that already have an active Lead AI chat on any of our numbers.

    Lazy import of ``LeadAiChat`` (same pattern as ``mark_lead_ai``): 2b adds
    fields there. Reading existing fields only.
    """
    if not phones:
        return set()
    try:
        from apps.leadai.models import LeadAiChat
    except ImportError:
        return set()
    digits = {p for p in phones if p}
    if not digits:
        return set()
    found = LeadAiChat.objects.filter(
        active=True,
        conversation__contact__wa_id__in=list(digits),
    ).values_list("conversation__contact__wa_id", flat=True)
    return {str(p) for p in found if p}


def phones_sent_same_template(template: WaTemplate, phones: set[str]) -> set[str]:
    """Phones this template already reached in the last 30 days."""
    if not phones:
        return set()
    name = str(getattr(template, "name", "") or "").strip()
    language = str(getattr(template, "language", "") or "")
    pk = getattr(template, "pk", None)
    if not name and not pk:
        return set()
    since = timezone.now() - timedelta(days=TEMPLATE_REPEAT_DAYS)
    sent = CampaignRecipient.objects.filter(
        phone__in=phones,
        status=CampaignRecipient.Status.SENT,
    ).filter(Q(sent_at__gte=since) | Q(sent_at__isnull=True, created_at__gte=since))
    if name:
        sent = sent.filter(campaign__template__name=name, campaign__template__language=language)
    else:
        sent = sent.filter(campaign__template_id=pk)
    return set(sent.values_list("phone", flat=True))


def build_recipients(
    *,
    template: WaTemplate,
    leads: list,
    extra_body: dict,
    entity: str = "lead",
    field_map: dict | None = None,
    lead_ai: bool = False,
    allow_empty: bool = False,
) -> tuple[list[dict], list[dict]]:
    kind = crm_entity(entity)
    extra = _meta_body_vars(extra_body)
    mapped = parse_field_map(field_map)
    needed = int(template.variable_count or 0)
    rows: list[dict] = []
    seen: set[str] = set()
    skipped: list[dict] = []
    noun, plural, _label = ENTITY_NOUNS[kind]
    phones = {
        _digits(raw.get("phone"))
        for raw in (leads or [])
        if isinstance(raw, dict) and len(_digits(raw.get("phone"))) >= 8
    }
    # Opt-out holds on every send. The 30-day template rule stays Lead AI only.
    # C22: a phone already in an active Lead AI chat must not get another.
    blocked = phones_opted_out(phones)
    recent = phones_sent_same_template(template, phones) if lead_ai else set()
    busy = phones_in_active_lead_ai(phones) if lead_ai else set()

    for raw in leads or []:
        if not isinstance(raw, dict):
            continue
        item_id = _item_id(raw)
        phone = _digits(raw.get("phone"))
        name = lead_display_name(raw) or _GREETING_FALLBACK
        if item_id <= 0:
            skipped.append({"id": item_id, "reason": f"Invalid {noun}."})
            continue
        if opt_out_reason(raw):
            skipped.append({"id": item_id, "reason": "Opted out."})
            continue
        if lead_ai:
            reason = lead_ai_skip_reason(raw)
            if reason:
                skipped.append({"id": item_id, "reason": reason})
                continue
        if len(phone) < 8:
            skipped.append({"id": item_id, "reason": f"No phone number on this {noun}."})
            continue
        canon = _canon_phone(phone)
        if phone in blocked or (canon and canon in blocked):
            skipped.append({"id": item_id, "reason": "Opted out."})
            continue
        if lead_ai and (phone in busy or (canon and canon in busy)):
            skipped.append({"id": item_id, "reason": "Already talking to Lead AI."})
            continue
        if lead_ai and phone in recent:
            skipped.append({"id": item_id, "reason": "Sent this template in the last 30 days."})
            continue
        if phone in seen:
            skipped.append({"id": item_id, "reason": "Duplicate phone."})
            continue
        seen.add(phone)
        body = dict(extra)
        if mapped:
            # A mapped {{n}} is that lead's own detail (blank → "?").
            # A typed value is used only for a slot that has no field picked.
            for slot in range(1, needed + 1):
                key = str(slot)
                field = mapped.get(key) or ""
                written = str(body.get(key) or "").strip()
                if field:
                    body[key] = detail_value(raw, field)
                elif written:
                    body[key] = written
                elif key == "1":
                    body[key] = detail_value(raw, "name")
                else:
                    raise CrmLeadSendError(
                        f"Choose a lead detail for {{{{{key}}}}}, or type a value."
                    )
        else:
            if needed >= 1:
                # Agent may override {{1}} with one value for everyone. Empty → each person's name.
                override_one = str(body.get("1") or "").strip()
                body["1"] = override_one or name
            if needed > 1:
                missing = [str(i) for i in range(2, needed + 1) if str(i) not in body]
                if missing:
                    raise CrmLeadSendError(
                        f"This template needs body values {', '.join('{{' + n + '}}' for n in missing)}."
                    )
        entry = {
            "phone": phone,
            "name": name,
        }
        # Link the recipient to the record it came from, so the reply mirror and
        # the Owner Data card logic address the right CRM object. A contact has
        # no column of its own: its timeline is found by phone, like any record.
        if kind == "owner_data":
            entry["owner_data_id"] = item_id
        elif kind == "deal":
            entry["crm_deal_id"] = item_id
        elif kind == "lead":
            entry["crm_lead_id"] = item_id
        if needed:
            entry["variables"] = {str(i): body[str(i)] for i in range(1, needed + 1)}
        rows.append(entry)

    if not rows and not allow_empty:
        sentence = left_out_sentence(skipped)
        if sentence:
            raise CrmLeadSendError(sentence)
        raise CrmLeadSendError(f"None of the selected {plural} have a usable phone number.")
    if len(rows) > MAX_LEADS:
        raise CrmLeadSendError(f"Select at most {MAX_LEADS} {plural}.")
    return rows, skipped


def context_for_agent(agent) -> dict:
    numbers = official_numbers_for(agent)
    if not numbers:
        raise CrmLeadSendError(
            "No Official WhatsApp number is assigned to you. Ask an admin."
        )
    default = official_number_for(agent) or numbers[0]
    waba_ids = {n.waba_business_id for n in numbers if n.waba_business_id}
    templates = WaTemplateHide.visible(
        WaTemplate.objects.filter(
            waba_business_id__in=waba_ids,
            status=WaTemplate.Status.APPROVED,
        )
    ).order_by("name", "language")
    return {
        "number": serialize_number(default),
        "numbers": [serialize_number(n) for n in numbers],
        "templates": [serialize_template(t) for t in templates],
        "agent": {
            "id": agent.pk,
            "display_name": agent.display_name or agent.get_username(),
            "bitrix_user_id": agent.bitrix_user_id or "",
        },
    }


PLAYBOOKS = frozenset({"general", "ic_shops"})


def campaign_playbook(raw) -> str:
    """The popup's Script choice. Anything else is general."""
    value = str(raw or "").strip().lower()
    return value if value in PLAYBOOKS else "general"


def mark_lead_ai(campaign, playbook: str, community: str = "") -> str:
    """Mark a Lead AI campaign and pass the script (and community) when the lane accepts them.

    T20a adds ``playbook`` to ``mark_campaign``; round 19 adds ``community``
    (C44b). Until that code is what the process imported, the older function is
    called with only the kwargs it knows so a send still reaches the Lead AI
    screen. Unknown / International City communities are stored as '' by the lane.
    """
    from apps.leadai.lane import mark_campaign

    chosen = campaign_playbook(playbook)
    params = inspect.signature(mark_campaign).parameters
    kwargs = {}
    if "playbook" in params:
        kwargs["playbook"] = chosen
    if "community" in params:
        kwargs["community"] = str(community or "").strip()
    if kwargs:
        mark_campaign(campaign, **kwargs)
    else:
        mark_campaign(campaign)
    return chosen


def send_from_leads(
    *,
    agent,
    template_id,
    leads: list,
    extra_body: dict | None = None,
    header_variables: dict | None = None,
    button_variables: dict | None = None,
    number_id=None,
    entity: str = "lead",
    header_media_token: str = "",
    lead_ai: bool = False,
    lead_ai_playbook: str = "",
    community: str = "",
    field_map: dict | None = None,
) -> dict:
    number = number_for_agent(agent, number_id)
    template = WaTemplate.objects.filter(pk=template_id).first()
    if not template:
        raise CrmLeadSendError("Template not found.")
    if template.status != WaTemplate.Status.APPROVED:
        raise CrmLeadSendError(f"Template '{template.name}' is not approved.")
    if template.waba_business_id != number.waba_business_id:
        raise CrmLeadSendError("That template is not on the WhatsApp number you picked.")
    # An image, video or document header: the popup uploaded the file for this
    # number first (crm_media) and sends back the token, checked here against
    # this agent, this number and this template's header kind.
    from .crm_media import header_media_id_for

    header_media_id = header_media_id_for(
        header_media_token, agent=agent, number=number, template=template
    )

    kind = crm_entity(entity)
    recipients, skipped = build_recipients(
        template=template,
        leads=leads,
        extra_body=extra_body or {},
        entity=kind,
        field_map=field_map,
        lead_ai=lead_ai,
    )
    label = ENTITY_NOUNS[kind][2]
    campaign = create_campaign(
        agent=agent,
        number=number,
        template=template,
        recipients=recipients,
        name=f"{label} · {'Lead AI · ' if lead_ai else ''}{template.name}",
        variables={},
        header_variables=header_variables or {},
        button_variables=button_variables or {},
        header_media_id=header_media_id,
    )
    playbook = ""
    if lead_ai:
        # The popup's "Lead AI" box: these chats go to the Lead AI screen, not
        # the main inbox. Marked before the send task can pick the campaign up.
        # C44b: popup community → LeadAiCampaign.community (round 19).
        playbook = mark_lead_ai(campaign, lead_ai_playbook, community=community)
    run_campaign.delay(campaign.pk)
    return {
        "campaign_id": campaign.pk,
        "name": campaign.name,
        "queued": campaign.total,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "from_number": number.phone_number,
        "from_label": number.title,
        "template": template.name,
        "lead_ai": bool(lead_ai),
        "playbook": playbook,
    }
