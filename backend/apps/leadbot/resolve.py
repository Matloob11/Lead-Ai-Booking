"""Map Bitrix ASSIGNED_BY_ID → Agent → Official 971 number."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.catalog.models import NumberAssignment, WabaNumber


class ResolveError(Exception):
    pass


def digits_only(raw) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def phone_from_lead(lead: dict) -> str:
    """Best WORK/MOBILE phone on a crm.lead.get payload."""
    phones = lead.get("PHONE") or []
    if isinstance(phones, dict):
        phones = list(phones.values())
    best = ""
    for row in phones:
        if not isinstance(row, dict):
            continue
        value = digits_only(row.get("VALUE"))
        if len(value) < 8:
            continue
        typ = str(row.get("VALUE_TYPE") or "").upper()
        if typ in {"WORK", "MOBILE", ""} and len(value) > len(best):
            best = value
        elif not best:
            best = value
    return best


def agent_for_bitrix_owner(assigned_by_id) -> object:
    bitrix_id = str(assigned_by_id or "").strip()
    if not bitrix_id.isdigit():
        raise ResolveError("Lead has no responsible person.")
    Agent = get_user_model()
    agent = Agent.objects.filter(bitrix_user_id=bitrix_id, is_active=True).first()
    if not agent:
        raise ResolveError(
            f"Bitrix user {bitrix_id} has no WhatsApp inbox login. "
            "Open the Official panel once and assign a 971 number."
        )
    if not getattr(agent, "can_official_api", True):
        raise ResolveError("Official WhatsApp is not enabled for this agent.")
    return agent


def official_971_for(agent) -> WabaNumber:
    """Prefer PRIMARY if it is 971; else any active 971 assignment."""
    rows = list(
        NumberAssignment.objects.filter(
            agent=agent, is_active=True, number__is_active=True
        )
        .select_related("number")
        .order_by("id")
    )
    n971 = [
        row
        for row in rows
        if digits_only(row.number.phone_number).startswith("971")
    ]
    if not n971:
        raise ResolveError(
            "No Official +971 WhatsApp number is assigned to this agent."
        )
    primary = next(
        (row for row in n971 if row.role == NumberAssignment.Role.PRIMARY), None
    )
    return (primary or n971[0]).number
