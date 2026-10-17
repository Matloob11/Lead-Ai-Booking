"""Bitrix writes for the Lead AI assistant (owner's choice 2026-10-09: stage + comment).

- A CONFIRMED booking (or its move, or its cancel) on the lead the agent sent
  the campaign from goes through the Lead fields tool's "booking" action
  (board C9, T55; crm_fields.post), never a REST crm.lead.update: Bitrix's Lead
  Automation (BP 235) runs on every REST edit, wipes the Meeting Date & Time and
  plans a to-do due "now" (board C4, C7). The tool writes with business
  processes and automation off: confirmed / rescheduled set stage '10'
  "Meeting/Viewing Scheduled", the Meeting Date & Time, Mode Offline (42) and
  Bot Status "Viewing booked", and create or move ONE "Viewing/Meeting" to-do
  for the lead's responsible at the meeting time (it answers with its id);
  cancelled closes that to-do and leaves the stage. The event's timeline
  comment rides in the same call, and the business activity and licence go
  along where the lead's own are still empty (``booking_body``).
- The tool's booking action moves (or, for a cancel, closes) the lead's NEWEST
  open "Viewing/Meeting" to-do, whoever planned it. So it is used only while
  that newest one is the assistant's own (the id the tool answered with,
  ``crm_todo_id``) or there is none (``open_meeting_todos``, a REST read).
  Otherwise a person's to-do, or the "due now" one BP 235 plans when a person
  edits a lead in stage 10, would be moved or closed in place of ours: then
  the assistant's own to-do is moved or closed with crm.activity (an activity
  write runs no lead business process), the meeting time goes on the lead
  through the tool's plain fields, and a lead the booking would have had to
  move to stage 10 stays in its stage, with a line for the agents (our
  60-minute heads-up then covers the meeting).
- A lead already in stage '10' that the assistant did not book holds a
  person's own booking and to-do: it gets the comment only.
- A NEW lead (the lead-shift intake picks only NEW), a lead held by the
  admin user, a closed lead, or a record found only by phone gets the
  comment only, and the agents are told to act.
- Everything else (tentative, running late, on my way, deals, Owner Data,
  contacts): one timeline comment, which runs no business process.
"""

from __future__ import annotations

import datetime as dt
import logging

from apps.crmlink import client

from . import calls, crm_facts, hours

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
FIELD_ACTIVITY = "UF_CRM_A7_AI_BUSINESS_ACTIVITY"  # text
FIELD_LICENCE = "UF_CRM_A7_AI_TRADE_LICENSE_STATUS"  # enum
LICENCE_IDS = {"yes": 2159, "no": 2160}
# The booking events the Lead fields tool's "booking" action takes.
BOOKING_EVENTS = ("confirmed", "rescheduled", "cancelled")
# The subject of the one to-do the tool plans for a booking (and of BP 235's own).
TODO_SUBJECT = "Viewing/Meeting"
TODO_LENGTH = dt.timedelta(hours=1)
# The tool keeps 1000 characters of a comment.
TOOL_COMMENT_MAX = 1000
ACTIVITY_MAX = 200

COMMENT_ENTITY = {
    "lead": "lead",
    "deal": "deal",
    "contact": "contact",
    "owner_data": f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}",
}


_UNSAFE = str.maketrans({"[": "(", "]": ")", "<": "‹", ">": "›"})


def safe(value) -> str:
    """Customer or model text for a Bitrix comment: no BB-code or HTML, no control characters."""
    return safe_line(value, 255)


def safe_line(value, limit: int) -> str:
    """``safe`` with its own length."""
    text = " ".join(str(value or "").split())
    return text.translate(_UNSAFE)[:limit]


# The "Questions for the viewing" line of a comment holds this much (ten short questions, shops.NOTES_KEPT).
NOTES_LINE_MAX = 600


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


def booking_body(lead_id: int, appointment, event: str, comment: str = "") -> dict:
    """The Lead fields tool's body for one booking event (pure; tested).

    confirmed / rescheduled carry the meeting's start in Dubai time and Mode
    Offline (the tool then sets stage 10, the Meeting Date & Time, Bot Status
    "Viewing booked" and the one "Viewing/Meeting" to-do), with the business
    activity and the licence the lead does not have yet (``only_if_empty``: an
    agent's own entry always wins). cancelled closes that to-do and leaves the
    stage. ``comment`` goes on the lead's timeline in the same call.
    """
    booking: dict = {"event": event}
    body: dict = {"lead_id": int(lead_id), "booking": booking}
    if event != "cancelled":
        booking["meeting_at"] = appointment.starts_at.astimezone(hours.DUBAI).isoformat()
        booking["mode"] = MODE_OFFLINE
        details = appointment.details or {}
        fields = {}
        activity = safe(details.get("business_activity"))[:ACTIVITY_MAX]
        if activity and crm_facts.is_business(activity):
            # Never a home they want nor a sentence (crm_facts.is_business; launch review issue 26).
            fields[FIELD_ACTIVITY] = activity
        licence = _licence_id(details)
        if licence:
            fields[FIELD_LICENCE] = licence
        if fields:
            body["fields"] = fields
            body["only_if_empty"] = list(fields)
    # A buyer's sales call (batch 2e slice C, C40): Mode Online 43 and the to-do "Sales call", on its move and cancel too.
    booking.update(calls.booking_fields(appointment, event))
    # The CRM review of batch 2e: the subject always named ("Viewing/Meeting" for a visit, its cancel too: never the tool's
    # newest to-do of either subject), and the to-do that is ours by its id (C33), so the tool moves or closes exactly that one.
    booking.setdefault("todo_subject", TODO_SUBJECT)
    todo_id = getattr(appointment, "crm_todo_id", None)
    if todo_id:
        booking["crm_todo_id"] = int(todo_id)
    if comment:
        body["comment"] = comment[:TOOL_COMMENT_MAX]
    return body


def _licence_id(details: dict) -> int | None:
    """The Trade license status the details give: the shops' kind when known, else yes or no."""
    from .crm_fields import licence_value

    return licence_value(details or {})


def todo_of(answer: dict) -> int | None:
    """The "Viewing/Meeting" to-do id the tool answered with, else None."""
    value = (answer or {}).get("todo_id")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def meeting_fields_body(lead_id: int, appointment, comment: str = "") -> dict:
    """The Lead fields tool's body for the meeting time alone (pure; tested): a lead whose newest
    "Viewing/Meeting" to-do is not ours, so the booking action (which would move that one) is
    not used. No stage, no to-do, and no Bot Status: a person may have changed it since."""
    body: dict = {"lead_id": int(lead_id), "fields": {FIELD_MEETING_AT: appointment.starts_at.astimezone(hours.DUBAI).isoformat()}}
    if comment:
        body["comment"] = comment[:TOOL_COMMENT_MAX]
    return body


def open_meeting_todos(lead_id: int, subject: str = TODO_SUBJECT) -> list[int]:
    """The ids of the lead's open "Viewing/Meeting" to-dos (``subject``: "Sales call" for a buyer's call, C40), newest
    first: the first is the one the tool's booking action would move or close. A REST read, nothing written. Raises
    BitrixError."""
    rows = client.call(
        "crm.activity.list",
        {
            "filter": {"OWNER_TYPE_ID": 1, "OWNER_ID": int(lead_id), "PROVIDER_ID": "CRM_TODO", "SUBJECT": subject, "COMPLETED": "N"},
            "order": {"ID": "DESC"},
            "select": ["ID"],
        },
    )
    ids = set()
    for row in rows if isinstance(rows, list) else []:
        try:
            ids.add(int((row or {}).get("ID")))
        except (TypeError, ValueError, AttributeError):
            continue
    return sorted((pk for pk in ids if pk > 0), reverse=True)


def move_todo(todo_id: int, lead_id: int, start: dt.datetime) -> str:
    """Move the assistant's own to-do to the meeting time (an activity write: no lead business
    process runs). Returns the method that worked. Raises BitrixError."""
    at = start.astimezone(hours.DUBAI)
    iso = at.isoformat()
    try:
        client.call("crm.activity.todo.updateDeadline", {"id": int(todo_id), "ownerTypeId": 1, "ownerId": int(lead_id), "value": iso})
        return "crm.activity.todo.updateDeadline"
    except client.BitrixError as exc:
        logger.info("Lead AI: todo.updateDeadline unavailable (%s); using crm.activity.update", exc)
    end = (at + TODO_LENGTH).isoformat()
    client.call("crm.activity.update", {"id": int(todo_id), "fields": {"DEADLINE": iso, "START_TIME": iso, "END_TIME": end}})
    return "crm.activity.update"


def complete_todo(todo_id: int) -> None:
    """Close the assistant's own to-do (the meeting was cancelled). Raises BitrixError."""
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
    ("licence_kind", "Licence"),
    ("shop_type", "Shop type wanted"),
    ("opening_when", "Opening"),
    ("licence_copy", "Licence copy"),
    ("preapproval", "Initial approval"),
    # A shops customer who wants no shop to rent: what our agent prepares for the visit (assistant/needs.py).
    ("wanted", "Wants"),
    # A shops chat keeps a list here: the questions our agent answers at the viewing.
    ("notes", "Notes"),
)
# How a shops fact reads on the record ("type_1" is "Type 1").
DETAIL_VALUES = {
    "shop_type": {"type_1": "Type 1", "type_2": "Type 2", "type_3": "Type 3", "not_sure": "Not sure"},
    "licence_kind": {"ded": "DED", "trakhees": "Trakhees", "new": "New licence", "none": "None"},
}


def detail_value(key: str, value) -> str:
    """One detail as the record shows it: a list joined, a shops enum spelt out."""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return DETAIL_VALUES.get(key, {}).get(str(value), str(value))

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
        if key == "notes" and isinstance(value, list):
            # Their own questions only (crm_facts.own_notes), and all of them: up to NOTES_LINE_MAX characters, never
            # safe()'s 255 (launch chat 95 asked nine).
            value = crm_facts.own_notes(value)
            if value:
                lines.append(f"Questions for the viewing: {safe_line(detail_value(key, value), NOTES_LINE_MAX)}")
            continue
        if value in (None, "", []):
            continue
        if key == "business_activity" and not crm_facts.is_business(value):
            continue  # a home they want or a sentence, kept by a chat from before (crm_facts.is_business)
        lines.append(f"{label}: {safe(detail_value(key, value))}")
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
    "spam": "MESSAGE LOOKS LIKE SPAM",
    # A shops customer who wants no shop to rent (engine.wanted_note_lines): the lead stays open.
    "wanted": "CUSTOMER WANTS SOMETHING OTHER THAN A SHOP",
    # A customer asked for a call, with the time they gave (people.call_note_lines; launch chat 88).
    "call": "CUSTOMER ASKED FOR A CALL",
}


def note_text(kind: str, customer: str, wa_id: str, lines=None) -> str:
    """A timeline note; ``lines`` (already safe) replace the closing line, as for "wanted". ``customer``: the chat's
    name for them (engine._customer_name: their own, the campaign's, the contact's); with none, no "Customer:" line
    at all, never "Customer: -" (launch review issue 26: seven leads' notes read so)."""
    tail = [str(line)[:400] for line in lines or () if str(line or "").strip()]
    if not tail:
        tail = ["The assistant stopped inviting this customer." if kind == "not_interested" else "The assistant stopped in this chat."]
    name = safe(customer)
    return "\n".join(
        [
            f"WhatsApp Lead AI · {NOTE_TITLES.get(kind, safe(kind).upper())}",
            *([f"Customer: {name}"] if name else []),
            f"Mobile: +{safe(wa_id).lstrip('+')}",
            *tail,
        ]
    )


def voice_note_text(sent_at, heard: str) -> str:
    """A customer's voice note as the lead's timeline should have read it, with what it says (launch review issue 26:
    the mirror's line for one is "[audio]", and chat 96's eight voice notes told the agents nothing)."""
    from django.utils import timezone

    stamp = timezone.localtime(sent_at).strftime("%d %b %H:%M") if sent_at else ""
    head = " · ".join(part for part in ("WhatsApp", "Customer", stamp, "voice note") if part)
    return f"{head}\n{safe_line(heard, 1500)}"


def add_comment(entity: str, crm_id: int, text: str) -> None:
    client.add_comment(COMMENT_ENTITY[entity], int(crm_id), text)
