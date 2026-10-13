"""Start Official WhatsApp outreach for a Bitrix lead."""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import WaTemplate
from apps.crmlink.client import BitrixError
from apps.inbox.models import Contact, Conversation
from apps.inbox.services import SendBlocked, send_template

from . import bitrix_sync
from .models import LeadAutomation
from .resolve import (
    ResolveError,
    agent_for_bitrix_owner,
    official_971_for,
    phone_from_lead,
)

logger = logging.getLogger(__name__)

AI_SOURCE = "leadbot_ai"
OUTREACH_SOURCE = "leadbot_outreach"


class OutreachError(Exception):
    def __init__(self, detail: str, *, http_status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.http_status = http_status


def _lead_name(lead: dict) -> str:
    for key in ("NAME", "TITLE"):
        val = str(lead.get(key) or "").strip()
        if val:
            return val.split()[0][:40]
    return "there"


def _requirement(lead: dict) -> str:
    title = str(lead.get("TITLE") or "").strip()
    if title:
        return title[:120]
    comments = str(lead.get("COMMENTS") or "").strip()
    return (comments[:120] if comments else "your property enquiry")


def _budget(lead: dict) -> str:
    opp = lead.get("OPPORTUNITY")
    if opp not in (None, "", 0, "0"):
        return str(opp)
    return "not recorded"


def _source(lead: dict) -> str:
    return str(lead.get("SOURCE_DESCRIPTION") or lead.get("SOURCE_ID") or "our website")[:80]


def _template_for_number(number) -> WaTemplate:
    name = bitrix_sync.template_name()
    tpl = (
        WaTemplate.objects.filter(
            waba_business_id=number.waba_business_id,
            name=name,
            status=WaTemplate.Status.APPROVED,
        )
        .order_by("-id")
        .first()
    )
    if tpl is None:
        raise OutreachError(
            f"Template '{name}' is not APPROVED on WABA {number.waba_business_id} "
            f"for number {number.phone_number}."
        )
    return tpl


def _variables_for(template: WaTemplate, lead: dict) -> dict:
    """Fill {{1}}…{{n}} in body order."""
    values = [
        _lead_name(lead),
        _source(lead),
        _requirement(lead),
        _budget(lead),
        f"L{lead.get('ID') or ''}",
    ]
    count = int(getattr(template, "variable_count", 0) or 0)
    if count <= 0:
        return {}
    return {str(i + 1): values[i] if i < len(values) else "" for i in range(count)}


@transaction.atomic
def run_outreach(lead_id: int) -> LeadAutomation:
    lead_id = int(lead_id)
    row, created = LeadAutomation.objects.select_for_update().get_or_create(
        bitrix_lead_id=lead_id,
        defaults={"state": LeadAutomation.State.PENDING},
    )
    if not created and row.state in {
        LeadAutomation.State.AWAITING_REPLY,
        LeadAutomation.State.ACTIVE,
        LeadAutomation.State.QUALIFIED,
    }:
        return row

    try:
        lead = bitrix_sync.get_lead(lead_id)
    except BitrixError as exc:
        raise OutreachError(str(exc), http_status=502) from exc

    phone = phone_from_lead(lead)
    if not phone:
        return _fail(row, lead_id, "Lead has no phone number.")

    try:
        agent = agent_for_bitrix_owner(lead.get("ASSIGNED_BY_ID"))
        number = official_971_for(agent)
        template = _template_for_number(number)
    except (ResolveError, OutreachError) as exc:
        return _fail(row, lead_id, str(exc))

    contact, _ = Contact.objects.get_or_create(wa_id=phone)
    conversation, _ = Conversation.objects.get_or_create(
        number=number,
        contact=contact,
        defaults={"assigned_agent": agent},
    )
    if conversation.assigned_agent_id is None:
        conversation.assigned_agent = agent
        conversation.save(update_fields=["assigned_agent"])

    variables = _variables_for(template, lead)
    try:
        message = send_template(conversation, agent, template, variables=variables)
    except (SendBlocked, Exception) as exc:
        logger.exception("leadbot template send failed lead=%s", lead_id)
        bitrix_sync.stamp_outreach_fail(lead_id)
        bitrix_sync.timeline(
            lead_id,
            f"A7 WhatsApp outreach from Official API failed: {exc}",
        )
        return _fail(row, lead_id, str(exc)[:2000], conversation=conversation, agent=agent, number=number)

    # Mark outbound as leadbot for history labelling.
    payload = dict(message.payload or {})
    payload["source"] = OUTREACH_SOURCE
    payload["bitrix_lead_id"] = lead_id
    message.payload = payload
    message.save(update_fields=["payload"])

    wamid = message.wamid or ""
    row.conversation = conversation
    row.number = number
    row.agent = agent
    row.customer_phone = phone
    row.outreach_template_name = template.name
    row.outreach_message_id = wamid
    row.state = LeadAutomation.State.AWAITING_REPLY
    row.last_error = ""
    row.snapshot = {
        "title": lead.get("TITLE") or "",
        "status_id": lead.get("STATUS_ID") or "",
        "assigned_by_id": str(lead.get("ASSIGNED_BY_ID") or ""),
        "source_id": lead.get("SOURCE_ID") or "",
        "opportunity": lead.get("OPPORTUNITY"),
    }
    row.save()

    bitrix_sync.stamp_outreach_ok(lead_id, wamid=wamid)
    bitrix_sync.timeline(
        lead_id,
        "A7 WhatsApp outreach from Official API "
        f"(template={template.name}, from={number.phone_number}, wamid={wamid or 'n/a'})",
    )
    return row


def _fail(row, lead_id, detail, *, conversation=None, agent=None, number=None):
    row.state = LeadAutomation.State.FAILED
    row.last_error = detail[:2000]
    if conversation is not None:
        row.conversation = conversation
    if agent is not None:
        row.agent = agent
    if number is not None:
        row.number = number
    row.updated_at = timezone.now()
    row.save()
    bitrix_sync.stamp_outreach_fail(lead_id)
    bitrix_sync.timeline(lead_id, f"A7 WhatsApp outreach failed: {detail}")
    return row
