"""The shops playbook's Bitrix lead fields, written through the Lead fields tool (board C6).

The tool is POST /bitrix/tools/a7_leadai_fields.php on the CRM box
(settings.LEADAI_BITRIX_FIELDS_URL), signed like the notify tool but with its
own prefix: X-Leadai-Ts (unix seconds) and X-Leadai-Sign = hex HMAC-SHA256 of
"leadai-fields." + ts + "." + body, with CRM_LEAD_WA_SECRET. It writes through
Bitrix's CRM factory with business processes and automation off, and accepts
only the allow-listed codes and enum ids of the board's field map.

REST crm.lead.update is never used for these: Bitrix BP 235 runs on every REST
edit, rewrites the title and wipes the meeting time (board C4, C7). A booking's
stage, meeting time and to-do go through the same tool's "booking" action
(crm.booking_body, from tasks.sync_appointment_crm; board C9, T55), and the
customer's trade licence copy as its ``license_file`` (licence_body, from
tasks.write_licence_file; board T34).

What a shops chat with a Bitrix lead (LeadAiChat.crm_entity "lead") writes:
- Bot Status: Qualifying on the first answered turn; Viewing booked on a
  confirmed booking; Handed to agent on a handover; Broker; Opted out; Lost;
- Shop Type Wanted when facts.shop_type changes;
- Business activity, only while the lead's own is empty, and only a business:
  never a home they want nor a sentence (crm_facts.is_business; launch chats 44,
  49, 57 and 68 wrote "apartment studio", "room" and "studio" there);
- Trade license status from facts.licence_kind (DED, Trakhees, New licence),
  or Yes / No when only that is known;
- Purpose = Broker for a broker, WhatsApp Opt-out = Yes for a STOP;
- the lost move: Not Interested ("1") for a no, Junk ("JUNK") for a wrong
  number or spam, with the reason (the customer's words), only for a lead
  nobody is working (assistant/lost.py, decided when the rows are posted).

Before a call the lead is read (tasks.write_crm_fields): a value it holds already
is not posted (``holds``), so a write never edits a field to what it was, and the
lead's change log gets no line for it (launch review issue 26).

The lead is the one the newest Lead AI campaign that reached the chat was sent
from (the campaign whose playbook the chat follows, lane.playbooks), else the
record the chat came onto the screen with.

Each value is a LeadAiCrmField row first, queued only when it is not what this
chat last queued for that lead and field: the same value is never posted twice
in a row, and one that comes back (Lost, then a booking, then Lost again) is
posted again. The rows of one turn go in one call, from a Celery task on the
leadai queue (tasks.write_crm_fields) that retries a passing failure; while
Bitrix stays down, the sweep sends them again (tasks._retry_crm_fields). A
failure is logged, never shown to the customer. A Bot Status a person set in
Bitrix is a row too, sent already (bitrix_status.remember): nothing of ours
queued before it goes over it, and the next value of ours that differs goes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import httpx
from django.conf import settings
from django.db import transaction

from ..models import LeadAiChatState, LeadAiCrmField
from . import crm, crm_facts

logger = logging.getLogger(__name__)

SIGN_PREFIX = b"leadai-fields."

FIELD_SHOP_TYPE = "UF_CRM_A7_SHOP_TYPE"
FIELD_BOT_STATUS = "UF_CRM_A7_BOT_STATUS"
FIELD_OPT_OUT = "UF_CRM_A7_WA_OPT_OUT"
FIELD_PURPOSE = "UF_CRM_LEAD_1737031634747"
FIELD_ACTIVITY = crm.FIELD_ACTIVITY
FIELD_LICENCE = crm.FIELD_LICENCE
# Not a field: the move to a lost stage, with its reason.
LOST = "lost"
# Not a field either: the customer's trade licence copy (``value`` is the inbound message's id).
LICENCE_FILE = "license_file"
LICENCE_MAX = 5 * 1024 * 1024
LICENCE_FORMATS = {"pdf": "licence.pdf", "jpeg": "licence.jpg", "png": "licence.png"}

SHOP_TYPE_IDS = {"type_1": 2471, "type_2": 2472, "type_3": 2473, "not_sure": 2474}
STATUS_QUALIFYING = 2476
STATUS_BOOKED = 2477
STATUS_HANDED = 2478
STATUS_BROKER = 2479
STATUS_LOST = 2480
STATUS_OPTED_OUT = 2481
OPT_OUT_YES = 2482
PURPOSE_BROKER = 2467
LICENCE_KIND_IDS = {"ded": 2455, "trakhees": 2456, "new": 2457, "none": 2160}
LICENCE_YES_NO = {"yes": 2159, "no": 2160}
LOST_NOT_INTERESTED = "1"
LOST_JUNK = "JUNK"
REASON_MAX = 255
ACTIVITY_MAX = 200
# A row the lead held already when it was to be posted (holds): marked done, never posted.
HELD_ALREADY = "Not sent: the lead holds this value already."
# The Bot Status ids a person may set in Bitrix (bitrix_status.py records them as the lead's newest value).
STATUSES = frozenset({2475, STATUS_QUALIFYING, STATUS_BOOKED, STATUS_HANDED, STATUS_BROKER, STATUS_LOST, STATUS_OPTED_OUT})


class FieldsError(Exception):
    """The tool could not be reached, or answered 5xx / 429: the task retries."""


def lead_of(chat, conversation=None) -> int | None:
    """The Bitrix lead these fields belong to, else None (nothing is written).

    The lead the newest Lead AI campaign that reached ``conversation`` was sent from:
    a shops campaign sent to a chat an older campaign brought here (from another
    lead, a deal or an Owner Data card) writes to its own lead, never the older
    record. A chat with no such send on record uses the record it came with.
    """
    if conversation is not None:
        from apps.campaigns.models import CampaignRecipient

        newest = list(
            CampaignRecipient.objects.filter(conversation=conversation, campaign__lead_ai__isnull=False)
            .order_by("-pk")
            .values_list("crm_lead_id", flat=True)[:1]
        )
        if newest:
            return int(newest[0]) if newest[0] else None
    if chat is None or chat.crm_entity != "lead" or not chat.crm_id:
        return None
    return int(chat.crm_id)


def licence_value(facts: dict) -> int | None:
    """The Trade license status the facts give: the kind when known, else yes or no."""
    facts = facts or {}
    kind = LICENCE_KIND_IDS.get(str(facts.get("licence_kind") or ""))
    return kind or LICENCE_YES_NO.get(str(facts.get("trade_licence") or ""))


def has_status(conversation, chat=None) -> bool:
    """A Bot Status was written (or queued) for this chat's lead already."""
    rows = LeadAiCrmField.objects.filter(conversation=conversation, field=FIELD_BOT_STATUS)
    lead = lead_of(chat, conversation)
    return (rows.filter(lead_id=lead) if lead is not None else rows).exists()


def turn_writes(before: dict, after: dict, *, answered: bool, first: bool, handover: bool, broker: bool, booked: bool) -> list:
    """[(field, value, payload)] for one turn of a shops chat (pure; tested).

    ``first``: no Bot Status was written yet, so an answered turn is the first
    one (Qualifying). One Bot Status per turn: a broker before a booking before a
    handover before Qualifying.
    """
    before, after = before or {}, after or {}
    writes = []
    if broker:
        writes += [(FIELD_PURPOSE, PURPOSE_BROKER, {}), (FIELD_BOT_STATUS, STATUS_BROKER, {})]
    elif booked:
        writes.append((FIELD_BOT_STATUS, STATUS_BOOKED, {}))
    elif handover:
        writes.append((FIELD_BOT_STATUS, STATUS_HANDED, {}))
    elif answered and first:
        writes.append((FIELD_BOT_STATUS, STATUS_QUALIFYING, {}))
    shop = SHOP_TYPE_IDS.get(str(after.get("shop_type") or ""))
    if shop and after.get("shop_type") != before.get("shop_type"):
        writes.append((FIELD_SHOP_TYPE, shop, {}))
    activity = crm.safe(after.get("business_activity"))[:ACTIVITY_MAX]
    if activity and after.get("business_activity") != before.get("business_activity") and crm_facts.is_business(activity):
        # Never a home they want, nor a sentence (crm_facts.is_business): "apartment studio" went to the lead live.
        writes.append((FIELD_ACTIVITY, activity, {"only_if_empty": True}))
    licence = licence_value(after)
    if licence and licence != licence_value(before):
        writes.append((FIELD_LICENCE, licence, {}))
    return writes


def opt_out_writes(kind: str, reason: str = "") -> list:
    """[(field, value, payload)] for an opt-out of a shops chat: a STOP is Opted out; a
    no, a wrong number and spam close the lead with the reason."""
    from . import rules

    text = crm.safe(reason)[:REASON_MAX] or {
        rules.NOT_INTERESTED: "not interested",
        rules.WRONG_NUMBER: "wrong number",
        rules.SPAM: "spam",
    }.get(kind, kind)
    if kind == rules.STOP_ALL:
        return [(FIELD_OPT_OUT, OPT_OUT_YES, {}), (FIELD_BOT_STATUS, STATUS_OPTED_OUT, {})]
    if kind == rules.NOT_INTERESTED:
        return [(FIELD_BOT_STATUS, STATUS_LOST, {}), (LOST, LOST_NOT_INTERESTED, {"reason": text})]
    if kind in (rules.WRONG_NUMBER, rules.SPAM):
        return [(FIELD_BOT_STATUS, STATUS_LOST, {}), (LOST, LOST_JUNK, {"reason": text})]
    return []


def last_values(conversation, lead: int) -> dict:
    """{field: value} of the newest row this chat queued for each field of this lead."""
    rows = LeadAiCrmField.objects.filter(conversation=conversation, lead_id=lead).order_by("pk").values_list("field", "value")
    return dict(rows)  # oldest first: the newest of each field is the one kept


def changed(field: str, value: str, last: dict) -> bool:
    """Is ``value`` news for this lead (pure; tested)? A value is, when the chat last queued
    another (or none) for that field. The lost move is, unless the lead was last told
    Lost with that same move: after a booking or a handover it goes again."""
    if field == LOST:
        return not (last.get(LOST) == value and last.get(FIELD_BOT_STATUS) == str(STATUS_LOST))
    return last.get(field) != value


def queue(conversation, chat, writes) -> list[int]:
    """Record each write that is news for the chat's lead, and post them in one task after the commit.

    One chat's writes are queued one at a time (its state row is locked), so two
    turns never both queue the same value. Returns the new rows' ids; nothing when
    the chat has no Bitrix lead.
    """
    from ..tasks import write_crm_fields

    lead = lead_of(chat, conversation)
    if lead is None or not writes:
        return []
    ids = []
    with transaction.atomic():
        LeadAiChatState.objects.select_for_update().filter(conversation=conversation).first()
        last = last_values(conversation, lead)  # what Bitrix last heard, before this batch
        for field, value, payload in writes:
            text = str(value)[:255]
            if not changed(field, text, last):
                continue  # this value went (or is going) already
            row = LeadAiCrmField.objects.create(conversation=conversation, lead_id=lead, field=field, value=text, payload=payload or {})
            ids.append(row.pk)
    if ids:
        transaction.on_commit(lambda pks=list(ids): write_crm_fields.delay(pks))
    return ids


def licence_format(data: bytes) -> str:
    """'pdf', 'jpeg' or 'png' by the file's first bytes (what the tool accepts), else ''."""
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return ""


def licence_body(lead_id: int, data: bytes) -> dict:
    """The tool's body for the customer's licence copy (pure; tested). Raises ValueError
    for a file the tool would refuse: not a PDF, JPEG or PNG, or over 5 MB."""
    import base64

    found = licence_format(data)
    if not found:
        raise ValueError("not a PDF, JPEG or PNG")
    if len(data) > LICENCE_MAX:
        raise ValueError("larger than 5 MB")
    return {
        "lead_id": int(lead_id),
        "license_file": {"name": LICENCE_FORMATS[found], "content_base64": base64.b64encode(data).decode("ascii")},
        "comment": "The customer shared their trade licence on WhatsApp; it is on the Trade License File field.",
    }


def queue_licence(conversation, chat, message) -> int | None:
    """Record that this inbound photo or PDF is the customer's licence copy, and post it to the
    lead after the commit (tasks.write_licence_file, which waits for the download). Returns the
    row's id; None when the chat has no Bitrix lead or this message was queued already."""
    from ..tasks import write_licence_file

    lead = lead_of(chat, conversation)
    if lead is None:
        return None
    if LeadAiCrmField.objects.filter(conversation=conversation, field=LICENCE_FILE, value=str(message.pk)).exists():
        return None
    row = LeadAiCrmField.objects.create(
        conversation=conversation, lead_id=lead, field=LICENCE_FILE, value=str(message.pk), payload={"message": message.pk}
    )
    transaction.on_commit(lambda pk=row.pk: write_licence_file.delay(pk))
    return row.pk


def _blank(value) -> bool:
    """A lead field with no value, as the tool reads one (a7_leadai_fields_empty: '' and '0' are empty)."""
    if value is None or value is False:
        return True
    if isinstance(value, list):
        return not [item for item in value if not _blank(item)]
    return str(value).strip() in ("", "0")


def holds(current: dict | None, row) -> bool:
    """The lead holds this row's value already (``current``: crm.lead.get's answer, None when it could not be read):
    posting it would edit the field to what it is, and the lead's change log would get a line for nothing (launch
    review issue 26). A field written only while the lead's own is empty holds whenever it has one. Never the lost
    move, nor a licence copy (pure; tested)."""
    if not isinstance(current, dict) or row.field in (LOST, LICENCE_FILE) or row.field not in current:
        return False
    value = current.get(row.field)
    if (row.payload or {}).get("only_if_empty"):
        return not _blank(value)
    if isinstance(value, list):
        return str(row.value) in {str(item).strip() for item in value}
    return str(value if value is not None else "").strip() == str(row.value).strip()


def body_for(rows, lead_id=None) -> dict:
    """The tool's body for some rows of one lead (pure; tested). A licence copy is never one
    of them: it goes on its own (licence_body). ``lead_id``: the lead's, for a body that may
    carry no row at all (only the timeline comment of a lead kept in its stage: lost.py)."""
    rows = [row for row in rows if row.field != LICENCE_FILE]
    body: dict = {"lead_id": rows[0].lead_id if rows else lead_id, "fields": {}}
    empty_only = []
    for row in rows:
        if row.field == LOST:
            body["lost"] = {"status_id": row.value, "reason": str((row.payload or {}).get("reason") or "")[:REASON_MAX]}
            continue
        # Enum ids go as numbers, the business activity as the text it is.
        value = int(row.value) if row.field != FIELD_ACTIVITY and row.value.isdigit() else row.value
        body["fields"][row.field] = value
        if (row.payload or {}).get("only_if_empty") and row.field not in empty_only:
            empty_only.append(row.field)
    if empty_only:
        body["only_if_empty"] = empty_only
    if not body["fields"]:
        del body["fields"]
    return body


def sign(raw: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), SIGN_PREFIX + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()


def post(body: dict) -> dict:
    """POST one signed body to the tool. Raises FieldsError when a retry may help;
    a refusal (400 field, 401 signature, 404 lead) comes back as {"ok": False, ...}."""
    endpoint = (getattr(settings, "LEADAI_BITRIX_FIELDS_URL", "") or "").strip()
    secret = (getattr(settings, "CRM_LEAD_WA_SECRET", "") or "").strip()
    if not endpoint or not secret:
        return {"ok": False, "error": "The Lead fields tool is not configured."}
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    try:
        response = httpx.post(
            endpoint,
            content=raw,
            headers={"Content-Type": "application/json", "X-Leadai-Ts": ts, "X-Leadai-Sign": sign(raw, ts, secret)},
            timeout=httpx.Timeout(20, connect=5),
        )
    except httpx.HTTPError as exc:
        raise FieldsError(f"Bitrix unreachable: {type(exc).__name__}") from None
    if response.status_code >= 500 or response.status_code == 429:
        raise FieldsError(f"Bitrix answered {response.status_code}")
    try:
        answer = response.json()
    except ValueError:
        if response.status_code >= 400:
            return {"ok": False, "error": f"Bitrix answered {response.status_code}"}
        raise FieldsError(f"Bitrix answered {response.status_code} without JSON") from None
    if not isinstance(answer, dict):
        return {"ok": False, "error": "Unexpected answer"}
    if response.status_code >= 400 and answer.get("ok") is not False:
        answer = {**answer, "ok": False}
    return answer
