"""The customer memory: what the assistant remembers of one customer across chats and numbers (Matloob, 2026-10-20:
"a memory system"; the advance plan's workstream E1, v1).

One conversation is one (our number, customer) pair, so a campaign from another number opens a new chat that knows
nothing of the last one. LeadAiCustomer keeps, by the phone's digits, one entry per conversation — its number, when it
ran, the facts it learned (unit, clusters, deal, budget, for whom, move-in), its bookings and how they ended — and the
latest merge of the facts.

- ``remember`` (engine._apply, after every turn that stored facts or a booking): the entry of this conversation upserted.
- ``recall`` + ``lines`` (engine._run_claimed): the OTHER conversations' entries as PREVIOUS CHATS lines in the model's
  context — data, with the prompt's own rule: confirm as a question ("You asked about a studio in Spain Cluster in
  July — still that one?"), never state it (the issue list's I12). Nothing is copied into the chat's facts: code's
  track decision reads the customer's words and the lead, as before.
- ``forget`` (a PDPL deletion, engine._rule_opt_out): the row goes.
Opt-outs are not kept here (optout.py's registry is the record of those); a stopped customer is simply never written to.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone

from ..models import LeadAiCustomer

logger = logging.getLogger(__name__)

# The facts worth remembering, in the order a line names them (the rest is a chat's own business).
KEPT = ("need", "wanted", "property_type", "unit", "intent", "clusters", "budget_aed", "budget_basis", "for_client", "move_in", "full_name")
MAX_CHATS = 12
MAX_LINES = 4
BLOCK_HEAD = "PREVIOUS CHATS (our records of this customer from earlier chats; confirm as a question, never state as fact):"


def digits(wa_id: str) -> str:
    return "".join(ch for ch in str(wa_id or "") if ch.isdigit())


def _kept(facts: dict) -> dict:
    out = {}
    for key in KEPT:
        value = (facts or {}).get(key)
        if value not in (None, "", [], {}):
            out[key] = value
    return out


def remember(conversation, facts: dict, language: str, now=None, *, booking: dict | None = None) -> LeadAiCustomer | None:
    """This conversation's entry upserted: its facts (the kept ones), its number, its moments, a booking event when one
    happened ({"event": "confirmed"|"rescheduled"|"tentative"|"cancelled"|"visited"|"missed", "starts_at": iso}).
    Nothing when there is nothing to keep."""
    phone = digits(getattr(getattr(conversation, "contact", None), "wa_id", ""))
    kept = _kept(facts or {})
    if not phone or (not kept and booking is None):
        return None
    now = now or timezone.now()
    row, _ = LeadAiCustomer.objects.get_or_create(phone=phone, defaults={"first_seen_at": now})
    chats = [entry for entry in (row.chats or []) if isinstance(entry, dict)]
    entry = next((entry for entry in chats if entry.get("conversation") == conversation.pk), None)
    if entry is None:
        entry = {
            "conversation": conversation.pk,
            "number": str(getattr(getattr(conversation, "number", None), "phone_number", "") or "")[-4:],
            "first_at": now.isoformat(),
            "bookings": [],
        }
        chats.append(entry)
    entry["last_at"] = now.isoformat()
    entry["facts"] = {**(entry.get("facts") or {}), **kept}
    if booking:
        bookings = [item for item in (entry.get("bookings") or []) if isinstance(item, dict)]
        same = next((item for item in bookings if item.get("starts_at") == booking.get("starts_at")), None)
        if same is None:
            bookings.append({"event": booking.get("event"), "starts_at": booking.get("starts_at"), "at": now.isoformat()})
        else:
            same["event"] = booking.get("event")
            same["at"] = now.isoformat()
        entry["bookings"] = bookings[-6:]
    chats.sort(key=lambda item: str(item.get("last_at") or ""))
    row.chats = chats[-MAX_CHATS:]
    row.facts = {**(row.facts or {}), **kept}
    if language:
        row.language = str(language)[:16]
    row.last_seen_at = now
    if row.first_seen_at is None:
        row.first_seen_at = now
    row.save(update_fields=["chats", "facts", "language", "first_seen_at", "last_seen_at", "updated_at"])
    return row


def recall(wa_id: str, *, exclude_conversation: int | None = None) -> list[dict]:
    """The customer's other conversations' entries, newest last; none when nothing is known."""
    phone = digits(wa_id)
    if not phone:
        return []
    row = LeadAiCustomer.objects.filter(phone=phone).first()
    if row is None:
        return []
    return [
        entry for entry in (row.chats or [])
        if isinstance(entry, dict) and entry.get("conversation") != exclude_conversation and (entry.get("facts") or entry.get("bookings"))
    ]


def _when(value: str) -> str:
    try:
        moment = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return ""
    return moment.strftime("%B %Y")


def describe(entry: dict) -> str:
    """One entry as one line: when, what they wanted, what was booked and how it ended."""
    facts = entry.get("facts") or {}
    parts = []
    unit = facts.get("unit") or facts.get("property_type") or facts.get("wanted")
    if unit:
        parts.append(f"asked about {unit}")
    clusters = facts.get("clusters")
    if isinstance(clusters, list) and clusters:
        parts.append("in " + ", ".join(str(c) for c in clusters[:3]))
    elif isinstance(clusters, str) and clusters:
        parts.append(f"in {clusters}")
    deal = facts.get("intent")
    if deal in ("rent", "buy", "sale"):
        parts.append("to " + ("buy" if deal in ("buy", "sale") else "rent"))
    budget = facts.get("budget_aed")
    if budget:
        try:
            parts.append(f"budget AED {int(float(budget)):,}" + (" a month" if facts.get("budget_basis") == "per_month" else ""))
        except (TypeError, ValueError):
            pass
    if facts.get("for_client") is True:
        parts.append("for a client")
    if facts.get("move_in"):
        parts.append(f"moving {facts['move_in']}")
    for item in (entry.get("bookings") or [])[-2:]:
        event = str(item.get("event") or "")
        when = ""
        try:
            when = dt.datetime.fromisoformat(str(item.get("starts_at"))).strftime("%d %b %Y")
        except (TypeError, ValueError):
            pass
        if event in ("confirmed", "rescheduled"):
            parts.append(f"booked a visit for {when}".strip())
        elif event == "visited":
            parts.append(f"visited on {when}".strip())
        elif event in ("missed", "cancelled"):
            parts.append(f"a visit for {when} was {event}".strip())
    when = _when(entry.get("last_at") or entry.get("first_at") or "")
    number = entry.get("number") or ""
    head = f"- {when}" if when else "- earlier"
    if number:
        head += f" (our number ending {number})"
    return head + ": " + ("; ".join(parts) if parts else "a chat with no details kept")


def lines(entries) -> list[str]:
    entries = [entry for entry in (entries or []) if isinstance(entry, dict)][-MAX_LINES:]
    if not entries:
        return []
    return [BLOCK_HEAD, *(describe(entry) for entry in entries)]


def forget(wa_id: str) -> int:
    """A PDPL deletion: the memory row goes. How many rows went."""
    phone = digits(wa_id)
    if not phone:
        return 0
    deleted, _ = LeadAiCustomer.objects.filter(phone=phone).delete()
    return int(deleted)
