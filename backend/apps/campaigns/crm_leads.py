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
import logging
import re
import time

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.catalog.models import WaTemplate, WaTemplateHide
from apps.catalog.views import serialize_template
from apps.inbox.transfer import official_number_for
from apps.inbox.serializers import serialize_number

from .services import CampaignError, create_campaign
from .tasks import run_campaign

logger = logging.getLogger(__name__)

MAX_LEADS = 500
MAX_SKEW_SEC = 300


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


def detail_value(row: dict, key: str) -> str:
    """One lead's value for a mapped variable. Blank, untitled, or missing → ``?``."""
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    raw = details.get(key)
    if raw is None or not str(raw).strip():
        if key == "name":
            raw = lead_display_name(row)
        elif key == "phone":
            raw = "".join(ch for ch in str(row.get("phone") or "") if ch.isdigit())
    text = " ".join(str(raw or "").split())
    if not text or text.lower() in {"untitled", "unentitled", "none", "field is empty"}:
        return "?"
    return text[:200]


def lead_display_name(row: dict) -> str:
    title = str(row.get("name") or row.get("title") or "").strip()
    if title and title.lower() not in {"untitled", "unentitled"}:
        return title[:200]
    first = str(row.get("first_name") or "").strip()
    last = str(row.get("last_name") or "").strip()
    joined = " ".join(part for part in (first, last) if part)
    if joined:
        return joined[:200]
    return ""


def _item_id(raw: dict) -> int:
    for key in ("id", "lead_id", "owner_data_id"):
        try:
            value = int(raw.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def build_recipients(
    *,
    template: WaTemplate,
    leads: list,
    extra_body: dict,
    entity: str = "lead",
    field_map: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    kind = crm_entity(entity)
    extra = _meta_body_vars(extra_body)
    mapped = parse_field_map(field_map)
    needed = int(template.variable_count or 0)
    rows: list[dict] = []
    seen: set[str] = set()
    skipped: list[dict] = []
    noun, plural, _label = ENTITY_NOUNS[kind]

    for raw in leads or []:
        if not isinstance(raw, dict):
            continue
        item_id = _item_id(raw)
        phone = "".join(ch for ch in str(raw.get("phone") or "") if ch.isdigit())
        name = lead_display_name(raw)
        if item_id <= 0:
            skipped.append({"id": item_id, "reason": f"Invalid {noun}."})
            continue
        if len(phone) < 8:
            skipped.append({"id": item_id, "reason": f"No phone number on this {noun}."})
            continue
        if phone in seen:
            skipped.append({"id": item_id, "reason": "Duplicate phone."})
            continue
        seen.add(phone)
        body = dict(extra)
        if mapped:
            # A mapped {{n}} is that lead's detail (blank → "?").
            # A typed value in extra wins for that slot and is the same for everyone.
            for slot in range(1, needed + 1):
                key = str(slot)
                field = mapped.get(key) or ""
                written = str(body.get(key) or "").strip()
                if field and not written:
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
                # Agent may override {{1}} with one value for everyone. Empty → each card/lead name.
                override_one = str(body.get("1") or "").strip()
                body["1"] = override_one or (name or "Customer")
            if needed > 1:
                missing = [str(i) for i in range(2, needed + 1) if str(i) not in body]
                if missing:
                    raise CrmLeadSendError(
                        f"This template needs body values {', '.join('{{' + n + '}}' for n in missing)}."
                    )
        entry = {
            "phone": phone,
            "name": name or f"{noun[0].upper()}{noun[1:]} {item_id}",
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

    if not rows:
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
    if lead_ai:
        # The popup's "Lead AI" box: these chats go to the Lead AI screen, not
        # the main inbox. Marked before the send task can pick the campaign up.
        from apps.leadai.lane import mark_campaign

        mark_campaign(campaign)
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
    }
