"""Bitrix field writes + timeline for leadbot."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.crmlink.client import BitrixError, add_comment, call, update_fields

logger = logging.getLogger(__name__)

# v9 UF names (portal must already have these; missing fields are skipped).
UF_FIRST_OUTREACH_AT = "UF_CRM_A7_WA_FIRST_OUTREACH_AT"
UF_REMINDER_DUE_AT = "UF_CRM_A7_WA_REMINDER_DUE_AT"
UF_AUTOMATION_STATE = "UF_CRM_A7_WA_AUTOMATION_STATE"
UF_LAST_OUTBOUND_ID = "UF_CRM_A7_WA_LAST_OUTBOUND_MESSAGE_ID"

STATE_AWAITING = "2186"
STATE_SEND_FAILED = "2191"

STATUS_QUALIFIED = "12"
STATUS_ASSIGNED = "UC_MJDO60"
STATUS_BROKER = "3"
STATUS_JUNK = "JUNK"

ALLOW_TO_QUALIFIED = {"NEW", "UC_MJDO60", "IN_PROCESS"}
ALLOW_TO_ASSIGNED = {"NEW"}
ALLOW_TO_BROKER = {"NEW", "UC_MJDO60", "IN_PROCESS", "12"}
ALLOW_TO_JUNK = {"NEW", "UC_MJDO60", "IN_PROCESS"}

# AI → Bitrix UF map (main Phase 1 fields from v9 guide).
AI_UF_MAP = {
    "for_self_or_client": "UF_CRM_LEAD_1737031634747",
    "move_in_date": "UF_CRM_A7_AI_MOVE_IN_DATE",
    "cheques": "UF_CRM_A7_AI_CHEQUE_COUNT",
    "occupancy": "UF_CRM_A7_AI_OCCUPANCY_TYPE",
    "lead_type": "UF_CRM_1756638760279",
    "property_segment": "UF_CRM_A7_AI_PROPERTY_SEGMENT",
    "business_activity": "UF_CRM_A7_AI_BUSINESS_ACTIVITY",
    "trade_license_status": "UF_CRM_A7_AI_TRADE_LICENSE_STATUS",
    "business_preapproval_status": "UF_CRM_A7_AI_BUSINESS_PREAPPROVAL_STATUS",
    "unit_preference": "UF_CRM_A7_AI_UNIT_PREFERENCE",
    "community_flexibility": "UF_CRM_A7_AI_COMMUNITY_FLEXIBILITY",
    "buyer_type": "UF_CRM_A7_AI_BUYER_TYPE",
    "mortgage_preapproval": "UF_CRM_A7_AI_MORTGAGE_PREAPPROVAL_STATUS",
}


def get_lead(lead_id: int) -> dict:
    result = call("crm.lead.get", {"id": int(lead_id)})
    if not isinstance(result, dict):
        raise BitrixError(f"crm.lead.get returned nothing for {lead_id}")
    return result


def timeline(lead_id: int, text: str) -> None:
    try:
        add_comment("lead", int(lead_id), text[:2000])
    except BitrixError as exc:
        logger.warning("leadbot timeline lead=%s: %s", lead_id, exc)


def stamp_outreach_ok(lead_id: int, *, wamid: str = "") -> None:
    now = timezone.now()
    fields = {
        UF_FIRST_OUTREACH_AT: now.isoformat(),
        UF_REMINDER_DUE_AT: (now + timedelta(hours=3)).isoformat(),
        UF_AUTOMATION_STATE: STATE_AWAITING,
    }
    if wamid:
        fields[UF_LAST_OUTBOUND_ID] = wamid
    _safe_update(lead_id, fields)


def stamp_outreach_fail(lead_id: int, *, wamid: str = "") -> None:
    fields = {UF_AUTOMATION_STATE: STATE_SEND_FAILED}
    if wamid:
        fields[UF_LAST_OUTBOUND_ID] = wamid
    _safe_update(lead_id, fields)


def apply_ai_fields(lead_id: int, output: dict) -> None:
    fields = {}
    for key, uf in AI_UF_MAP.items():
        val = output.get(key)
        if val is None or val == "":
            continue
        fields[uf] = str(val)[:500]
    if fields:
        _safe_update(lead_id, fields)


def apply_stage(lead_id: int, *, status_id: str, current_status: str) -> bool:
    """Move stage only when current stage allows. Never touches ASSIGNED_BY_ID."""
    current = str(current_status or "").strip()
    target = str(status_id or "").strip()
    if not target:
        return False
    allow = {
        STATUS_QUALIFIED: ALLOW_TO_QUALIFIED,
        STATUS_ASSIGNED: ALLOW_TO_ASSIGNED,
        STATUS_BROKER: ALLOW_TO_BROKER,
        STATUS_JUNK: ALLOW_TO_JUNK,
    }.get(target)
    if allow is not None and current and current not in allow:
        logger.info(
            "leadbot skip stage lead=%s current=%s target=%s",
            lead_id,
            current,
            target,
        )
        return False
    _safe_update(lead_id, {"STATUS_ID": target})
    return True


def _safe_update(lead_id: int, fields: dict) -> None:
    try:
        update_fields("lead", int(lead_id), fields)
    except BitrixError as exc:
        # UF missing on portal should not kill the send path.
        logger.warning("leadbot update lead=%s fields=%s: %s", lead_id, list(fields), exc)


def template_name() -> str:
    return (
        getattr(settings, "LEADBOT_OUTREACH_TEMPLATE", "") or "a7_lead_enquiry_confirm"
    ).strip()
