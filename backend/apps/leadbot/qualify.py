"""Deterministic qualification (v9 rules, Phase 1)."""

from __future__ import annotations

from .bitrix_sync import STATUS_ASSIGNED, STATUS_BROKER, STATUS_JUNK, STATUS_QUALIFIED


def decide(output: dict, *, confirmed: dict | None = None) -> dict:
    """Return {qualified, status_id, reason, stop}.

    AI's ``qualified`` flag is advisory; this function is final.
    """
    out = output or {}
    confirmed = confirmed or {}
    merged = {**confirmed, **{k: v for k, v in out.items() if v not in (None, "")}}

    if _truthy(out.get("broker_flag")) or _brokerish(merged):
        return {
            "qualified": True,
            "status_id": STATUS_BROKER,
            "reason": "Broker / agent signals — handover without owner details.",
            "stop": True,
        }

    if _opt_out(merged, out):
        return {
            "qualified": False,
            "status_id": STATUS_JUNK,
            "reason": "Customer not interested or opted out.",
            "stop": True,
        }

    if _truthy(out.get("handover_to_human")) or _asks_human(out):
        return {
            "qualified": True,
            "status_id": STATUS_ASSIGNED,
            "reason": "Customer requested a human / specialist.",
            "stop": True,
        }

    purpose = str(merged.get("for_self_or_client") or "").lower()
    if "client" in purpose and "self" not in purpose.split("client")[0]:
        return {
            "qualified": True,
            "status_id": STATUS_QUALIFIED,
            "reason": "Qualified for immediate specialist handover: enquiry is for a client.",
            "stop": True,
        }
    if purpose.strip() in {"client", "for a client", "for my client", "agent", "broker"}:
        return {
            "qualified": True,
            "status_id": STATUS_QUALIFIED,
            "reason": "Qualified for immediate specialist handover: enquiry is for a client.",
            "stop": True,
        }

    licence = str(merged.get("trade_license_status") or "").lower()
    pre = str(merged.get("business_preapproval_status") or "").lower()
    if licence in {"no", "none", "not yet"} and pre in {"no", "none", "not yet"}:
        return {
            "qualified": True,
            "status_id": STATUS_QUALIFIED,
            "reason": "Qualified for commercial guidance handover: licence and pre-approval are not ready.",
            "stop": True,
        }

    if merged.get("viewing_time") and (
        merged.get("for_self_or_client")
        or merged.get("lead_type")
        or merged.get("move_in_date")
    ):
        return {
            "qualified": True,
            "status_id": STATUS_QUALIFIED,
            "reason": "Qualified: customer provided viewing availability.",
            "stop": True,
        }

    if _route_minimum(merged):
        return {
            "qualified": True,
            "status_id": STATUS_QUALIFIED,
            "reason": "Qualified: the route-specific minimum customer answers were confirmed.",
            "stop": True,
        }

    if _truthy(out.get("qualified")):
        return {
            "qualified": True,
            "status_id": STATUS_QUALIFIED,
            "reason": str(out.get("qualification_reason") or "AI marked qualified.")[:255],
            "stop": True,
        }

    return {"qualified": False, "status_id": "", "reason": "", "stop": False}


def _route_minimum(merged: dict) -> bool:
    lead_type = str(merged.get("lead_type") or merged.get("sop_route") or "rental").lower()
    useful = sum(
        1
        for k in (
            "for_self_or_client",
            "move_in_date",
            "cheques",
            "occupancy",
            "viewing_time",
            "buyer_type",
            "unit_preference",
            "community_flexibility",
        )
        if merged.get(k)
    )
    if "buy" in lead_type or "sale" in lead_type:
        return bool(
            merged.get("buyer_type")
            and (merged.get("move_in_date") or merged.get("viewing_time"))
            and useful >= 3
        )
    if "sell" in lead_type or "owner" in lead_type:
        return bool(
            merged.get("for_self_or_client")
            and (merged.get("move_in_date") or merged.get("budget") or merged.get("viewing_time"))
        )
    # General rental / default
    return bool(
        merged.get("move_in_date")
        and (merged.get("for_self_or_client") or merged.get("cheques") or merged.get("viewing_time"))
        and useful >= 3
    )


def _opt_out(merged, out) -> bool:
    if _truthy(out.get("not_interested")) or _truthy(out.get("opt_out")):
        return True
    blob = " ".join(
        str(x).lower()
        for x in (
            out.get("summary"),
            out.get("reply"),
            merged.get("last_customer_text"),
        )
        if x
    )
    return any(
        phrase in blob
        for phrase in (
            "not interested",
            "no longer required",
            "stop messaging",
            "unsubscribe",
            "do not contact",
        )
    )


def _asks_human(out) -> bool:
    reason = str(out.get("qualification_reason") or "").lower()
    return "human" in reason or "specialist" in reason or "agent" in reason


def _brokerish(merged) -> bool:
    text = " ".join(str(v).lower() for v in merged.values() if v)
    hits = sum(
        1
        for w in ("broker", "agency", "commission", "my client", "i am an agent")
        if w in text
    )
    return hits >= 2


def _truthy(val) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in {"1", "true", "yes", "y"}
