"""Excel batches: one sheet, many numbers.

Kept apart from the single-number campaign on purpose — that screen, its
runner and its history are not touched. This module reads the sheet the way
the agent mapped it (which column is the phone, which column or fixed value
fills each ``{{n}}``), splits the rows across the numbers they ticked, so many
per number, and hands each number its share as an ordinary ``Campaign``. From
there retries, webhook reconciliation and cancellation work as they always
did; the batch only remembers which campaigns belong together.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.catalog.models import WabaNumber, WaTemplate
from apps.inbox.send_health import with_send_health

from .models import Campaign, CampaignBatch, CampaignRecipient, CrmTarget
from .phones import (
    SpreadsheetFormatError,
    _read_spreadsheet_rows,
    _trim_trailing_blank_rows,
    normalize_phone,
)
from .serializers import serialize_campaign
from .services import (
    CampaignError,
    create_campaign,
    matching_template_on_number,
    refresh_campaign_counts,
)

logger = logging.getLogger(__name__)

MAX_ROWS = 10_000
#: The single-campaign cap. A lane *is* one campaign, so it cannot take more.
MAX_PER_NUMBER = 500
DEFAULT_PER_NUMBER = 300
SAMPLE_VALUES = 3
MAX_WARNINGS = 12

PHONE_HINTS = ("phone", "mobile", "whatsapp", "number", "msisdn", "contact", "cell", "tel")
NAME_HINTS = ("name", "title", "owner", "client", "customer", "lead")


class BulkError(CampaignError):
    """Something the agent can fix from the screen."""


def column_letter(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA — how the sheet itself labels the column."""
    letters = ""
    number = index + 1
    while number:
        number, rem = divmod(number - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell(row, index) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def _blank(row) -> bool:
    return not any(str(cell or "").strip() for cell in row)


def load_sheet(file_bytes: bytes, filename: str = "") -> tuple[list[str], list[list[str]], bool]:
    """(header, data rows, has_header) from .xlsx or CSV bytes.

    A sheet whose first filled row already holds a phone number has no header
    row; the columns are then named by letter so the mapping still has
    something to point at, and that row is data. Blank rows are kept in
    ``data`` (skipped later) so row numbers in warnings match the sheet.
    """
    try:
        rows = _trim_trailing_blank_rows(_read_spreadsheet_rows(file_bytes, filename))
    except SpreadsheetFormatError as exc:
        raise BulkError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - openpyxl and csv raise many things
        raise BulkError("Could not read that file. Upload .xlsx or .csv.") from exc

    while rows and _blank(rows[0]):
        rows.pop(0)
    if not rows:
        raise BulkError("The file is empty.")

    width = max(len(row) for row in rows)
    first = rows[0]
    has_header = not any(normalize_phone(cell) for cell in first if str(cell or "").strip())
    if has_header:
        header = [_cell(first, i) or f"Column {column_letter(i)}" for i in range(width)]
        data = rows[1:]
    else:
        header = [f"Column {column_letter(i)}" for i in range(width)]
        data = rows

    if len(data) > MAX_ROWS:
        raise BulkError(f"Max {MAX_ROWS:,} rows per upload — this sheet has {len(data):,}.")
    return header, data, has_header


def _guess_columns(columns: list[dict], probed: int) -> dict:
    """Best guess at the phone and name columns: headers first, then content."""
    phone = None
    name = None
    for column in columns:
        title = column["header"].lower()
        if phone is None and column["phone_like"] and any(k in title for k in PHONE_HINTS):
            phone = column["index"]
        if name is None and not column["phone_like"] and any(k in title for k in NAME_HINTS):
            name = column["index"]
    if phone is None:
        best = max(columns, key=lambda c: c["phone_like"], default=None)
        if best and best["phone_like"] >= max(1, probed // 2):
            phone = best["index"]
    if name is None:
        for column in columns:
            if column["index"] != phone and column["filled"] and not column["phone_like"]:
                name = column["index"]
                break
    return {"phone": phone, "name": name}


def inspect_sheet(file_bytes: bytes, filename: str = "") -> dict:
    """What the sheet contains, for the mapping screen: columns, samples, guesses."""
    header, data, has_header = load_sheet(file_bytes, filename)
    probe = [row for row in data[:200] if not _blank(row)]
    columns = []
    for index, title in enumerate(header):
        values = [_cell(row, index) for row in data]
        samples: list[str] = []
        for value in values:
            if value and value not in samples:
                samples.append(value[:60])
            if len(samples) >= SAMPLE_VALUES:
                break
        columns.append(
            {
                "index": index,
                "letter": column_letter(index),
                "header": title,
                "samples": samples,
                "filled": sum(1 for value in values if value),
                "phone_like": sum(1 for row in probe if normalize_phone(_cell(row, index))),
            }
        )
    return {
        "columns": columns,
        "rows": sum(1 for row in data if not _blank(row)),
        "has_header": has_header,
        "guesses": _guess_columns(columns, len(probe)),
    }


def _as_index(value):
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_mapping(raw, template: WaTemplate) -> dict:
    """The agent's column choices as ints, checked against the template's holes."""
    mapping = raw if isinstance(raw, dict) else {}
    phone = _as_index(mapping.get("phone"))
    if phone is None:
        raise BulkError("Choose the column that holds the phone numbers.")

    raw_vars = mapping.get("vars") if isinstance(mapping.get("vars"), dict) else {}
    variables: dict[str, dict] = {}
    for number in range(1, int(template.variable_count or 0) + 1):
        key = str(number)
        entry = raw_vars.get(key) if isinstance(raw_vars.get(key), dict) else {}
        column = _as_index(entry.get("column"))
        value = str(entry.get("value") or "").strip()
        if column is not None:
            variables[key] = {"column": column}
        elif value:
            variables[key] = {"value": value[:1024]}
        else:
            raise BulkError(f"Map {{{{{number}}}}} to a column, or type one value for everyone.")

    return {"phone": phone, "name": _as_index(mapping.get("name")), "vars": variables}


def parse_mapped_rows(
    file_bytes: bytes, filename: str, *, mapping, template: WaTemplate
) -> tuple[list[dict], dict, list[str]]:
    """Recipients from the sheet as mapped. Returns (recipients, stats, warnings).

    The chat name and CRM card title come from the name column, or failing
    that from whatever column fills ``{{1}}`` — which is a name more often
    than not.
    """
    header, data, has_header = load_sheet(file_bytes, filename)
    width = len(header)
    clean = normalize_mapping(mapping, template)

    if not 0 <= clean["phone"] < width:
        raise BulkError("The phone column is not in this file.")
    for key, entry in clean["vars"].items():
        if "column" in entry and not 0 <= entry["column"] < width:
            raise BulkError(f"The column chosen for {{{{{key}}}}} is not in this file.")

    name_col = clean["name"] if clean["name"] is not None and 0 <= clean["name"] < width else None
    if name_col is None:
        first = clean["vars"].get("1")
        if first and "column" in first:
            name_col = first["column"]

    recipients: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()
    stats = {"rows": 0, "valid": 0, "invalid_phone": 0, "duplicate": 0, "empty_value": 0}

    def note(text):
        if len(warnings) < MAX_WARNINGS:
            warnings.append(text)

    for offset, row in enumerate(data):
        if _blank(row):
            continue
        stats["rows"] += 1
        row_no = offset + (2 if has_header else 1)

        phone = normalize_phone(_cell(row, clean["phone"]))
        if not phone:
            stats["invalid_phone"] += 1
            note(f"Row {row_no}: no valid phone number.")
            continue
        if phone in seen:
            stats["duplicate"] += 1
            note(f"Row {row_no}: +{phone} appears again — skipped.")
            continue

        variables: dict[str, str] = {}
        empty = ""
        for key, entry in clean["vars"].items():
            value = _cell(row, entry["column"]) if "column" in entry else entry["value"]
            if not value:
                empty = key
                break
            variables[key] = value[:1024]
        if empty:
            stats["empty_value"] += 1
            note(f"Row {row_no}: {{{{{empty}}}}} is empty.")
            continue

        seen.add(phone)
        name = _cell(row, name_col) if name_col is not None else ""
        if normalize_phone(name) == phone:
            name = ""
        recipients.append({"phone": phone, "name": name[:200], "variables": variables})

    stats["valid"] = len(recipients)
    if not recipients:
        detail = "No usable rows found."
        if warnings:
            detail += " " + " ".join(warnings[:4])
        raise BulkError(detail)
    return recipients, stats, warnings


def plan_lanes(*, agent, template: WaTemplate, number_ids, recipients: list[dict], per_number_cap) -> dict:
    """Which number takes which rows — worked out before anything is created.

    Numbers go in the order the agent ticked them. Each takes up to the cap;
    a number the provider has banned, or one whose business account has no
    approved copy of this template, is skipped with a reason rather than the
    whole start being refused. Rows beyond the last number's share are
    reported as leftover, not silently dropped.
    """
    try:
        cap = int(per_number_cap or DEFAULT_PER_NUMBER)
    except (TypeError, ValueError):
        cap = DEFAULT_PER_NUMBER
    cap = max(1, min(cap, MAX_PER_NUMBER))

    ordered: list[int] = []
    for raw in number_ids if isinstance(number_ids, (list, tuple)) else []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value not in ordered:
            ordered.append(value)
    if not ordered:
        raise BulkError("Tick at least one WhatsApp number.")

    allowed = with_send_health(agent.visible_numbers).in_bulk(ordered)
    lanes: list[dict] = []
    skipped: list[dict] = []
    cursor = 0
    for pk in ordered:
        number = allowed.get(pk)
        if number is None:
            skipped.append({"number_id": pk, "phone": "", "label": "", "reason": "Not one of your numbers."})
            continue
        base = {"number_id": number.pk, "phone": number.phone_number, "label": number.title}
        if getattr(number, "_send_blocked", False):
            skipped.append({**base, "reason": "The provider banned this number recently — it cannot send."})
            continue
        try:
            match = matching_template_on_number(template, number)
        except CampaignError:
            skipped.append({**base, "reason": f"No approved template '{template.name}' on this number."})
            continue
        take = recipients[cursor : cursor + cap]
        lanes.append(
            {
                **base,
                "template_id": match.pk,
                "language": match.language,
                "count": len(take),
                "first_row": cursor + 1 if take else 0,
                "last_row": cursor + len(take),
            }
        )
        cursor += len(take)

    return {
        "cap": cap,
        "lanes": lanes,
        "skipped_numbers": skipped,
        "assigned": cursor,
        "leftover": max(0, len(recipients) - cursor),
    }


def create_batch(
    *,
    agent,
    template: WaTemplate,
    recipients: list[dict],
    plan: dict,
    mapping,
    name: str = "",
    crm_target: str = CrmTarget.NONE,
    header_variables=None,
    button_variables=None,
    header_media_ids=None,
    source_filename: str = "",
    warnings=None,
) -> tuple[CampaignBatch, list[int]]:
    """The batch and one child campaign per lane, in one transaction.

    Returns the batch and the child ids to enqueue — enqueuing is the caller's
    job, after the commit, so a worker never picks up a campaign that a
    rollback is about to remove.
    """
    lanes = [lane for lane in plan["lanes"] if lane["count"]]
    if not lanes:
        raise BulkError("No ticked number can take any rows — check the template on those numbers.")

    media = header_media_ids if isinstance(header_media_ids, dict) else {}
    if template.requires_header_media:
        kind = (template.header or {}).get("format", "media").lower()
        for lane in lanes:
            if not str(media.get(str(lane["number_id"])) or "").strip():
                raise BulkError(
                    f"Upload the header {kind} for +{lane['phone']} first — Meta media files are per number."
                )

    target = crm_target if crm_target in CrmTarget.values else CrmTarget.NONE
    label = (name or "").strip()[:160] or f"{template.name} · {timezone.localdate()}"

    with transaction.atomic():
        batch = CampaignBatch.objects.create(
            name=label,
            template_name=template.name,
            template_language=template.language,
            created_by=agent,
            source_filename=(source_filename or "")[:255],
            column_map=mapping if isinstance(mapping, dict) else {},
            per_number_cap=plan["cap"],
            crm_target=target,
            total=plan["assigned"],
            leftover=plan["leftover"],
            skipped_numbers=plan["skipped_numbers"],
            warnings=list(warnings or [])[:MAX_WARNINGS],
        )
        children: list[int] = []
        cursor = 0
        for lane in lanes:
            rows = recipients[cursor : cursor + lane["count"]]
            cursor += lane["count"]
            number = WabaNumber.objects.get(pk=lane["number_id"])
            lane_template = WaTemplate.objects.get(pk=lane["template_id"])
            campaign = create_campaign(
                agent=agent,
                number=number,
                template=lane_template,
                recipients=rows,
                name=f"{label} · +{number.phone_number}",
                header_variables=header_variables,
                button_variables=button_variables,
                header_media_id=str(media.get(str(number.pk)) or ""),
            )
            campaign.batch = batch
            campaign.crm_target = target
            campaign.save(update_fields=["batch", "crm_target"])
            children.append(campaign.pk)
    return batch, children


def cancel_batch(batch: CampaignBatch) -> CampaignBatch:
    """Stop every lane. Rows not yet sent become skipped, so the counts settle."""
    now = timezone.now()
    if not batch.cancelled_at:
        batch.cancelled_at = now
        batch.save(update_fields=["cancelled_at"])
    Campaign.objects.filter(batch=batch).exclude(
        status__in=(Campaign.Status.DONE, Campaign.Status.CANCELLED)
    ).update(status=Campaign.Status.CANCELLED, finished_at=now)
    CampaignRecipient.objects.filter(
        campaign__batch=batch,
        status__in=(CampaignRecipient.Status.PENDING, CampaignRecipient.Status.FAILED),
    ).update(
        status=CampaignRecipient.Status.SKIPPED,
        error_detail="Cancelled before sending.",
        next_retry_at=None,
    )
    for campaign in batch.campaigns.all():
        refresh_campaign_counts(campaign)
    return batch


LIVE = {Campaign.Status.QUEUED, Campaign.Status.RUNNING, Campaign.Status.RETRYING}


def batch_status(batch: CampaignBatch, child_statuses) -> str:
    statuses = list(child_statuses)
    if batch.cancelled_at:
        return "cancelled"
    if not statuses:
        return "empty"
    if any(status in LIVE for status in statuses):
        return "running"
    if all(status == Campaign.Status.FAILED for status in statuses):
        return "failed"
    return "done"


def _empty_totals():
    return {"sent": 0, "failed": 0, "retrying": 0, "pending": 0, "skipped": 0, "total": 0}


def totals_by_batch(batch_ids) -> dict:
    """Recipient counts per batch in one query — for the list, where exact
    per-lane retry maths would cost hundreds of queries."""
    rows = (
        CampaignRecipient.objects.filter(campaign__batch_id__in=list(batch_ids))
        .values("campaign__batch_id", "status")
        .annotate(n=Count("id"))
    )
    out = defaultdict(_empty_totals)
    for row in rows:
        bucket = out[row["campaign__batch_id"]]
        status = row["status"]
        count = row["n"]
        bucket["total"] += count
        if status == CampaignRecipient.Status.SENT:
            bucket["sent"] += count
        elif status == CampaignRecipient.Status.EXHAUSTED:
            bucket["failed"] += count
        elif status == CampaignRecipient.Status.FAILED:
            bucket["retrying"] += count
        elif status == CampaignRecipient.Status.PENDING:
            bucket["pending"] += count
        elif status == CampaignRecipient.Status.SKIPPED:
            bucket["skipped"] += count
    return out


def _batch_row(batch: CampaignBatch, statuses, totals, lane_count) -> dict:
    return {
        "id": batch.pk,
        "name": batch.name,
        "status": batch_status(batch, statuses),
        "template_name": batch.template_name,
        "template_language": batch.template_language,
        "crm_target": batch.crm_target,
        "per_number_cap": batch.per_number_cap,
        "total": batch.total,
        "leftover": batch.leftover,
        "lane_count": lane_count,
        "counts": totals,
        "source_filename": batch.source_filename,
        "created_at": batch.created_at.isoformat(),
        "cancelled_at": batch.cancelled_at.isoformat() if batch.cancelled_at else None,
    }


def serialize_batch_list(batches) -> list[dict]:
    batches = list(batches)
    ids = [b.pk for b in batches]
    totals = totals_by_batch(ids)
    statuses = defaultdict(list)
    for batch_id, status in Campaign.objects.filter(batch_id__in=ids).values_list("batch_id", "status"):
        statuses[batch_id].append(status)
    return [
        _batch_row(batch, statuses.get(batch.pk, []), totals.get(batch.pk, _empty_totals()), len(statuses.get(batch.pk, [])))
        for batch in batches
    ]


def serialize_batch(batch: CampaignBatch) -> dict:
    """The batch with every lane's exact counts — for the detail pane."""
    children = list(batch.campaigns.select_related("number", "template").order_by("id"))
    lanes = []
    totals = _empty_totals()
    for campaign in children:
        row = serialize_campaign(campaign)
        row["label"] = campaign.number.title
        lanes.append(row)
        for key in totals:
            totals[key] += int(row.get(key) or 0)
    payload = _batch_row(batch, [c.status for c in children], totals, len(children))
    payload["lanes"] = lanes
    payload["skipped_numbers"] = batch.skipped_numbers or []
    payload["warnings"] = batch.warnings or []
    payload["column_map"] = batch.column_map or {}
    return payload
