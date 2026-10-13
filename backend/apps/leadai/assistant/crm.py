"""Bitrix writes for the Lead AI assistant (owner's choice 2026-10-09: stage + comment).

- A CONFIRMED booking on the lead the agent sent the campaign from: ONE
  crm.lead.update to stage '10' "Meeting/Viewing Scheduled" with the Meeting
  Date & Time (required for that stage), mode Offline and, when empty, the
  office link and the details the lead does not have yet. Bitrix's Lead
  Automation (BP 235) then plans the agent's "Viewing/Meeting" to-do, but it
  erases the meeting time first, so the to-do is due "now"; the assistant
  then moves that to-do to the real meeting time, so the agent's Bitrix
  reminders ring at the right moment. BP 235 itself is not touched.
- The lead is updated at most once per appointment (every update plans
  another to-do). Later, only the assistant's own to-do is moved: the one it
  stored, while it is still open. A to-do that was there before the
  assistant's own update (an agent's own booking, an older BP 235 one) is
  never moved or completed; a lead already in stage '10' at the first
  booking keeps its to-dos, and our 60-minute heads-up covers the meeting.
- A NEW lead (the lead-shift intake picks only NEW), a lead held by the
  admin user, a closed lead, or a record found only by phone gets the
  comment only, and the agents are told to act.
- Everything else (tentative, running late, on my way, cancel, deals, Owner
  Data, contacts): one timeline comment, which runs no business process.
"""

from __future__ import annotations

import datetime as dt
import logging

from apps.crmlink import client

from . import hours

logger = logging.getLogger(__name__)

# Open stages a booking may move a lead out of.
MOVABLE_STAGES = frozenset(
    {
        "UC_MJDO60",  # Assigned
        "12",  # AI Qualified leads
        "UC_RYQD1Z",  # Not interested (still open)
        "IN_PROCESS",  # Contacted/In Progress
        "UC_UGUOZX",  # No Answer
        "UC_PVKGEG",  # Old Leads Before 6 Month
        "UC_ZQMREH",  # Option Sent
        "11",  # Meeting/Viewing Done (a new visit)
        "UC_3YEFW6",  # Future Prospect
    }
)
STAGE_MEETING = "10"
STAGE_NEW = "NEW"
HOLD_USERS = {"", "0", "1"}

FIELD_MEETING_AT = "UF_CRM_1731838813769"  # Meeting Date & Time (required for stage 10)
FIELD_MODE = "UF_CRM_1731838790184"  # Mode of Meeting
MODE_OFFLINE = 42
FIELD_LOCATION = "UF_CRM_1731838831905"  # Meeting Location/Link (url)
FIELD_BUDGET = "UF_CRM_1731838581336"  # Budget (number)
FIELD_SIZE = "UF_CRM_1760707482053"  # Property Size (text)
FIELD_ACTIVITY = "UF_CRM_A7_AI_BUSINESS_ACTIVITY"  # text
FIELD_LICENCE = "UF_CRM_A7_AI_TRADE_LICENSE_STATUS"  # enum
LICENCE_IDS = {"yes": 2159, "no": 2160}
TODO_SUBJECT = "Viewing/Meeting"
# Our server's clock and Bitrix's may differ a little: a to-do BP 235 planned
# during our own lead update must not be missed for it.
CLOCK_SKEW = dt.timedelta(minutes=2)

COMMENT_ENTITY = {
    "lead": "lead",
    "deal": "deal",
    "contact": "contact",
    "owner_data": f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}",
}


_UNSAFE = str.maketrans({"[": "(", "]": ")", "<": "‹", ">": "›"})


def safe(value) -> str:
    """Customer or model text for a Bitrix comment: no BB-code or HTML, no control characters."""
    text = " ".join(str(value or "").split())
    return text.translate(_UNSAFE)[:255]


def record_for(chat, conversation):
    """(entity, id, chosen): the CRM record for this chat, and whether the agent chose it.

    The campaign's own record first (the lead, deal or Owner Data card the
    agent sent from); otherwise a lookup by the customer's number, which is
    never trusted enough to move a stage.
    """
    if chat is not None and chat.crm_entity in COMMENT_ENTITY and chat.crm_id:
        return chat.crm_entity, int(chat.crm_id), True
    try:
        records = client.find_records(conversation.contact.wa_id)
    except client.BitrixError as exc:
        logger.warning("Lead AI CRM lookup failed for conversation %s: %s", conversation.pk, exc)
        return "", None, False
    for wanted in ("lead", "contact"):
        for record in records:
            if record.get("type") == wanted:
                return wanted, int(record["id"]), False
    for record in records:
        if record.get("kind") == "owner data":
            return "owner_data", int(record["id"]), False
    return "", None, False


def read_record(entity: str, crm_id: int) -> dict:
    """The record's responsible user, stage and fields. Raises BitrixError."""
    if entity == "lead":
        row = client.call("crm.lead.get", {"id": int(crm_id)}) or {}
        return {"assigned": str(row.get("ASSIGNED_BY_ID") or ""), "stage": str(row.get("STATUS_ID") or ""), "fields": row}
    if entity == "deal":
        row = client.call("crm.deal.get", {"id": int(crm_id)}) or {}
        return {"assigned": str(row.get("ASSIGNED_BY_ID") or ""), "stage": str(row.get("STAGE_ID") or ""), "fields": row}
    if entity == "contact":
        row = client.call("crm.contact.get", {"id": int(crm_id)}) or {}
        return {"assigned": str(row.get("ASSIGNED_BY_ID") or ""), "stage": "", "fields": row}
    if entity == "owner_data":
        result = client.call("crm.item.get", {"entityTypeId": client.OWNER_DATA_TYPE_ID, "id": int(crm_id)}) or {}
        item = (result.get("item") if isinstance(result, dict) else None) or {}
        return {"assigned": str(item.get("assignedById") or ""), "stage": str(item.get("stageId") or ""), "fields": item}
    return {"assigned": "", "stage": "", "fields": {}}


def stage_decision(entity: str, chosen: bool, record: dict) -> str:
    """'move', 'already', or why not ('found by phone', 'new lead', 'held by admin', 'closed')."""
    if entity != "lead":
        return "not a lead"
    if not chosen:
        return "found by phone"
    stage = record.get("stage") or ""
    if stage == STAGE_MEETING:
        return "already"
    if record.get("assigned", "") in HOLD_USERS:
        return "held by admin"
    if stage == STAGE_NEW:
        return "new lead"
    if stage in MOVABLE_STAGES:
        return "move"
    return "closed" if stage else "unknown stage"


def _empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict)):
        return not value
    return str(value).strip() in ("", "0", "0.00")


def booking_fields(current: dict, appointment, maps_url: str = "") -> dict:
    """The one lead update for a confirmed booking (pure; tested).

    ``current`` is the lead as Bitrix returned it. Details are written only
    where the lead is still empty: an agent's own entry always wins.
    """
    fields = {
        "STATUS_ID": STAGE_MEETING,
        FIELD_MEETING_AT: appointment.starts_at.astimezone(hours.DUBAI).isoformat(),
        FIELD_MODE: MODE_OFFLINE,
    }
    if maps_url and maps_url.lower().startswith("https://") and _empty(current.get(FIELD_LOCATION)):
        fields[FIELD_LOCATION] = maps_url
    details = appointment.details or {}
    budget = details.get("budget_aed")
    basis = details.get("budget_basis")
    if isinstance(budget, (int, float)) and budget > 0 and basis in ("per_year", "total") and _empty(current.get(FIELD_BUDGET)):
        fields[FIELD_BUDGET] = float(budget)
    size = details.get("size_sqft")
    if isinstance(size, (int, float)) and size > 0 and _empty(current.get(FIELD_SIZE)):
        fields[FIELD_SIZE] = f"{int(size)} sq ft"
    activity = safe(details.get("business_activity"))
    if activity and _empty(current.get(FIELD_ACTIVITY)):
        fields[FIELD_ACTIVITY] = activity
    licence = LICENCE_IDS.get(str(details.get("trade_licence") or "").lower())
    if licence and _empty(current.get(FIELD_LICENCE)):
        fields[FIELD_LICENCE] = licence
    return fields


def _created(row: dict) -> dt.datetime | None:
    try:
        created = dt.datetime.fromisoformat(str(row.get("CREATED") or ""))
    except ValueError:
        return None
    return created if created.tzinfo else created.replace(tzinfo=hours.DUBAI)


def find_meeting_todo(lead_id: int, *, todo_id: int | None = None, created_since: dt.datetime | None = None) -> dict | None:
    """The newest open "Viewing/Meeting" to-do on the lead: ``todo_id`` itself while
    it is still open, and/or one created at or after ``created_since`` (the
    assistant's own lead update). Raises BitrixError."""
    flt = {
        "OWNER_TYPE_ID": 1,
        "OWNER_ID": int(lead_id),
        "PROVIDER_ID": "CRM_TODO",
        "SUBJECT": TODO_SUBJECT,
        "COMPLETED": "N",
    }
    if todo_id:
        flt["ID"] = int(todo_id)
    rows = client.call(
        "crm.activity.list",
        {
            "filter": flt,
            "order": {"ID": "DESC"},
            "select": ["ID", "DEADLINE", "START_TIME", "END_TIME", "RESPONSIBLE_ID", "CREATED"],
        },
    )
    rows = rows if isinstance(rows, list) else []
    if created_since is not None:
        # Compared here, not in the filter: CREATED comes back with its own
        # offset, whatever time zone the portal reads a filter value in.
        since = created_since - CLOCK_SKEW
        rows = [row for row in rows if _created(row) is None or _created(row) >= since]
    return rows[0] if rows else None


def move_todo(todo_id: int, lead_id: int, start: dt.datetime) -> str:
    """Move a to-do's deadline to the meeting time. Returns the method that worked. Raises BitrixError."""
    at = start.astimezone(hours.DUBAI)
    iso = at.isoformat()
    try:
        client.call(
            "crm.activity.todo.updateDeadline",
            {"id": int(todo_id), "ownerTypeId": 1, "ownerId": int(lead_id), "value": iso},
        )
        return "crm.activity.todo.updateDeadline"
    except client.BitrixError as exc:
        logger.info("Lead AI: todo.updateDeadline unavailable (%s); using crm.activity.update", exc)
    end = (at + dt.timedelta(hours=1)).isoformat()
    client.call("crm.activity.update", {"id": int(todo_id), "fields": {"DEADLINE": iso, "START_TIME": iso, "END_TIME": end}})
    return "crm.activity.update"


def complete_todo(todo_id: int) -> None:
    client.call("crm.activity.update", {"id": int(todo_id), "fields": {"COMPLETED": "Y"}})


DETAIL_LABELS = (
    ("intent", "Looking to"),
    ("property_type", "Property type"),
    ("community", "Area"),
    ("building_unit", "Unit"),
    ("bedrooms", "Bedrooms"),
    ("size_sqft", "Size (sq ft)"),
    ("budget_aed", "Budget (AED)"),
    ("budget_basis", "Budget basis"),
    ("asking_price_aed", "Asking (AED)"),
    ("payment", "Payment"),
    ("occupancy_status", "Vacant or tenanted"),
    ("available_from", "Available from"),
    ("move_in", "Move-in"),
    ("occupancy", "Occupancy"),
    ("business_activity", "Business activity"),
    ("trade_licence", "Trade licence"),
    ("preapproval", "Initial approval"),
    ("notes", "Notes"),
)

EVENT_TITLES = {
    "confirmed": "MEETING CONFIRMED",
    "tentative": "MEETING TENTATIVE",
    "rescheduled": "MEETING RESCHEDULED",
    "running_late": "CUSTOMER RUNNING LATE",
    "running_late_tap": "CUSTOMER RUNNING LATE",
    "on_my_way": "CUSTOMER ON THE WAY",
    "reschedule_requested": "CUSTOMER WANTS TO RESCHEDULE",
    "cancelled": "MEETING CANCELLED",
}


def comment_text(appointment, event: str, *, office_address: str = "", agents: str = "", extra: str = "", hot: bool = False) -> str:
    """The timeline comment for one appointment event (pure; tested).

    ``hot``: a same-day booking by a customer who needs the space soon (owner's
    rule 60), marked so it stays on the record after the alert is dismissed.
    """
    title = EVENT_TITLES.get(event, safe(event).upper())
    hot = hot and event == "confirmed"
    lines = [f"WhatsApp Lead AI · HOT LEAD · {title}" if hot else f"WhatsApp Lead AI · {title}"]
    if hot:
        lines.append("Needs the space soon and is visiting today.")
    if appointment.customer_name:
        lines.append(f"Customer: {safe(appointment.customer_name)}")
    if appointment.mobile:
        lines.append(f"Mobile: +{safe(appointment.mobile).lstrip('+')}")
    if appointment.starts_at:
        lines.append(f"When: {hours.describe(appointment.starts_at)}")
    if event in ("running_late", "running_late_tap") and not appointment.eta_at:
        lines.append("They have not said yet when they will arrive.")
    if appointment.place and appointment.place != "office":
        lines.append(f"Where: {appointment.get_place_display()}")
    elif office_address and event in ("confirmed", "rescheduled"):
        lines.append(f"Where: {safe(office_address)}")
    if appointment.customer_words:
        lines.append(f"Customer's words: {safe(appointment.customer_words)}")
    details = appointment.details or {}
    for key, label in DETAIL_LABELS:
        value = details.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        lines.append(f"{label}: {safe(value)}")
    if agents:
        lines.append(f"Agents: {safe(agents)}")
    lines.append(f"Appointment status: {appointment.get_status_display().upper()}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)[:4000]


NOTE_TITLES = {
    "stop_all": "CUSTOMER ASKED US TO STOP MESSAGING",
    "wrong_number": "CUSTOMER SAYS WRONG NUMBER",
    "not_interested": "CUSTOMER NOT INTERESTED",
}


def note_text(kind: str, customer: str, wa_id: str) -> str:
    return "\n".join(
        [
            f"WhatsApp Lead AI · {NOTE_TITLES.get(kind, safe(kind).upper())}",
            f"Customer: {safe(customer) or '-'}",
            f"Mobile: +{safe(wa_id).lstrip('+')}",
            "The assistant stopped inviting this customer." if kind == "not_interested" else "The assistant stopped in this chat.",
        ]
    )


def add_comment(entity: str, crm_id: int, text: str) -> None:
    client.add_comment(COMMENT_ENTITY[entity], int(crm_id), text)


def update_lead(crm_id: int, fields: dict) -> None:
    client.update_fields("lead", int(crm_id), fields)
