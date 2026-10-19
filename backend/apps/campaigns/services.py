"""Campaign orchestration: Owner Data ensure + template send + auto-retry bookkeeping."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.catalog.models import WaTemplate, WabaNumber
from apps.crmlink import client as bitrix
from apps.gateway.client import AlotsError
from apps.inbox import services as inbox_services
from apps.inbox.services import SendBlocked

from .failures import (
    MARKETING_CAP_PAUSE_AFTER,
    PERMANENT_FAIL_CODES,
    is_permanent_send_failure,
    permanent_fail_label,
)
from .models import MAX_SEND_ATTEMPTS, RETRY_AFTER_MINUTES, Campaign, CampaignRecipient, CrmTarget
from .phones import (
    SpreadsheetFormatError,
    is_spreadsheet_workbook,
    parse_campaign_spreadsheet,
    parse_recipients_csv,
    parse_recipients_text,
)

logger = logging.getLogger(__name__)


class CampaignError(Exception):
    pass


# Re-export for tests / callers that historically imported from services.
__all__ = [
    "CampaignError",
    "MARKETING_CAP_PAUSE_AFTER",
    "PERMANENT_FAIL_CODES",
    "is_permanent_send_failure",
    "permanent_fail_label",
    "create_campaign",
    "parse_recipient_inputs",
    "recipient_counts",
    "refresh_campaign_counts",
    "campaign_has_work_left",
    "process_recipient",
    "mark_recipient_undelivered",
    "requeue_due_retries",
    "ensure_owner_data",
    "should_resend_recipient",
    "matching_template_on_number",
    "resend_skipped_on_number",
]

def should_resend_recipient(status: str, error_detail: str = "") -> bool:
    """Skipped rows, plus marketing-cap exhausts — not undeliverable numbers.

    C25: a row skipped because the phone opted out while waiting is never
    picked again by resend-skipped.
    """
    if status == CampaignRecipient.Status.SKIPPED:
        note = (error_detail or "").lower()
        if "opted out" in note:
            return False
        return True
    if status != CampaignRecipient.Status.EXHAUSTED:
        return False
    note = (error_detail or "").lower()
    return "131049" in note or "marketing daily cap" in note


def matching_template_on_number(template: WaTemplate, number: WabaNumber) -> WaTemplate:
    """Same template name on the destination number's WABA, or a clear error."""
    qs = WaTemplate.objects.filter(
        waba_business_id=number.waba_business_id,
        name=template.name,
        status=WaTemplate.Status.APPROVED,
    )
    match = qs.filter(language=template.language).order_by("id").first() or qs.order_by("id").first()
    if not match:
        raise CampaignError(
            f"Number +{number.phone_number} has no approved template named "
            f"'{template.name}'. Pick a number that already has this template."
        )
    return match


def resend_skipped_on_number(*, agent, campaign: Campaign, number: WabaNumber) -> Campaign:
    """New campaign: skipped + 131049 rows, same or different WhatsApp number."""
    same_number = int(number.pk) == int(campaign.number_id)
    rows: list[dict] = []
    for row in campaign.recipients.order_by("id"):
        if not should_resend_recipient(row.status, row.error_detail):
            continue
        entry = {"phone": row.phone, "name": row.name or ""}
        if row.variables:
            entry["variables"] = _filled_vars(row.variables)
        if row.crm_lead_id:
            entry["crm_lead_id"] = row.crm_lead_id
        if row.crm_deal_id:
            entry["crm_deal_id"] = row.crm_deal_id
        if row.crm_role:
            entry["crm_role"] = row.crm_role
        if row.owner_data_id:
            entry["owner_data_id"] = row.owner_data_id
        rows.append(entry)
    if not rows:
        raise CampaignError("No skipped or marketing-cap numbers left to resend.")

    if same_number:
        template = campaign.template
        media_id = (campaign.header_media_id or "").strip()
        if template.requires_header_media and not media_id:
            raise CampaignError(
                "This template needs a media header, but the original campaign "
                "has no media id to reuse."
            )
        suffix = " · retry"
    else:
        template = matching_template_on_number(campaign.template, number)
        media_id = ""
        if template.requires_header_media:
            raise CampaignError(
                "This template has a media header. Meta media files stay on the original "
                "number — retry from the same line, or start a new campaign and re-upload."
            )
        suffix = " · another number"

    new_name = (campaign.name or template.name).strip()[:160]
    if suffix.lower() not in new_name.lower():
        new_name = f"{new_name}{suffix}"

    return create_campaign(
        agent=agent,
        number=number,
        template=template,
        recipients=rows,
        name=new_name[:200],
        variables=campaign.variables,
        header_variables=campaign.header_variables,
        button_variables=campaign.button_variables,
        header_media_id=media_id,
    )


def _filled_vars(raw: dict | None) -> dict[str, str]:
    """Keep only non-empty string values, keyed as Meta expects ("1", "2", …)."""
    return _meta_body_vars(raw)


def _meta_body_vars(raw: dict | None) -> dict[str, str]:
    """Digit keys only — a CRM lead id must never become a Meta parameter."""
    out: dict[str, str] = {}
    for key, value in (raw or {}).items():
        if not str(key).isdigit():
            continue
        text = str(value or "").strip()
        if text:
            out[str(key)] = text
    return out


def _crm_lead_id(row: dict) -> int | None:
    raw = row.get("crm_lead_id")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _crm_deal_id(row: dict) -> int | None:
    raw = row.get("crm_deal_id")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _crm_role(row: dict) -> str:
    role = str(row.get("crm_role") or "").strip().lower()
    return role if role in {"tenant", "owner"} else ""


def _owner_data_id(row: dict) -> int | None:
    raw = row.get("owner_data_id")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def ensure_owner_data(
    phone: str,
    name: str = "",
    *,
    category_id: int | None = None,
    stage_id: str | None = None,
) -> tuple[dict, bool]:
    """Return (Owner Data record dict, created?). Never creates a CRM Lead.

    An existing card carrying the number wins whatever board it sits on; a new
    one lands on Availability unless the caller names another category.
    """
    matches = bitrix._owner_data_matches(phone)
    if matches:
        return matches[0], False
    if not bitrix.configured():
        raise CampaignError("Bitrix CRM is not configured — cannot create Owner Data.")
    record = bitrix.create_owner_data(
        phone,
        name=name,
        stage_id=stage_id or bitrix.OWNER_DATA_STAGE_NEW_AVAILABILITY,
        category_id=bitrix.OWNER_DATA_CATEGORY_AVAILABILITY if category_id is None else category_id,
    )
    return record, True


def crm_destination(target: str) -> tuple[int, str] | None:
    """(category id, new-stage id) for a CRM target, or None when no card is wanted.

    Empty is every campaign made before the Excel screen existed, and keeps
    filing Availability cards exactly as it always did.
    """
    if target == CrmTarget.NONE:
        return None
    if target == CrmTarget.OWNER_DATA:
        return bitrix.OWNER_DATA_CATEGORY_CALLING, bitrix.OWNER_DATA_STAGE_NEW_CALLING
    return bitrix.OWNER_DATA_CATEGORY_AVAILABILITY, bitrix.OWNER_DATA_STAGE_NEW_AVAILABILITY


def _validate_global_template_fields(
    template: WaTemplate,
    *,
    variables: dict | None,
    header_variables: dict | None,
    button_variables: dict | None,
    header_media_id: str,
) -> dict[str, str]:
    body_vars = _filled_vars(variables)
    header_vars = _filled_vars(header_variables)
    button_vars = _filled_vars(button_variables)
    media_id = (header_media_id or "").strip()

    expected = template.variable_count
    if len(body_vars) != expected or any(str(i) not in body_vars for i in range(1, expected + 1)):
        raise CampaignError(f"Template needs {expected} body value(s), got {len(body_vars)}.")

    header = template.header
    if template.requires_header_media and not media_id:
        raise CampaignError(f"Template '{template.name}' needs a header media file.")
    if header and header["format"] == "TEXT" and header["variable_count"]:
        needed = header["variable_count"]
        if len(header_vars) != needed or any(str(i) not in header_vars for i in range(1, needed + 1)):
            raise CampaignError(f"Template needs {needed} header value(s).")

    for button in template.buttons:
        if not button["variable_count"]:
            continue
        key = str(button["index"])
        if key not in button_vars:
            raise CampaignError(f'Fill in the link for "{button["text"] or "Button"}".')

    return body_vars


def _validate_per_row_variables(template: WaTemplate, recipients: list[dict]) -> None:
    expected = template.variable_count
    for row in recipients:
        body_vars = _filled_vars(row.get("variables"))
        phone = row.get("phone") or "?"
        if len(body_vars) != expected or any(str(i) not in body_vars for i in range(1, expected + 1)):
            raise CampaignError(
                f"Recipient +{phone} is missing one or more template values from the spreadsheet."
            )


def create_campaign(
    *,
    agent,
    number: WabaNumber,
    template: WaTemplate,
    recipients: list[dict],
    name: str = "",
    variables: dict | None = None,
    header_variables: dict | None = None,
    button_variables: dict | None = None,
    header_media_id: str = "",
    crm_target: str = "",
) -> Campaign:
    if template.status != WaTemplate.Status.APPROVED:
        raise CampaignError(f"Template '{template.name}' is not approved.")
    if template.waba_business_id != number.waba_business_id:
        raise CampaignError("That template belongs to a different WhatsApp number.")
    if not recipients:
        raise CampaignError("Add at least one phone number.")

    seen: set[str] = set()
    clean: list[dict] = []
    for row in recipients:
        phone = (row.get("phone") or "").strip()
        if not phone or phone in seen:
            continue
        seen.add(phone)
        entry = {"phone": phone, "name": (row.get("name") or "")[:200]}
        if row.get("variables"):
            entry["variables"] = _meta_body_vars(row["variables"])
        lead_id = _crm_lead_id(row)
        if lead_id:
            entry["crm_lead_id"] = lead_id
        deal_id = _crm_deal_id(row)
        if deal_id:
            entry["crm_deal_id"] = deal_id
        role = _crm_role(row)
        if role:
            entry["crm_role"] = role
        owner_id = _owner_data_id(row)
        if owner_id:
            entry["owner_data_id"] = owner_id
        clean.append(entry)

    if not clean:
        raise CampaignError("No valid phone numbers found.")
    if len(clean) > 500:
        raise CampaignError("Max 500 recipients per campaign.")

    per_row = template.variable_count > 0 and all(r.get("variables") for r in clean)
    if per_row:
        _validate_per_row_variables(template, clean)
        body_vars: dict[str, str] = {}
    else:
        body_vars = _validate_global_template_fields(
            template,
            variables=variables,
            header_variables=header_variables,
            button_variables=button_variables,
            header_media_id=header_media_id,
        )

    header_vars = _filled_vars(header_variables)
    button_vars = _filled_vars(button_variables)
    media_id = (header_media_id or "").strip()

    if not per_row:
        header = template.header
        if template.requires_header_media and not media_id:
            raise CampaignError(f"Template '{template.name}' needs a header media file.")
        if header and header["format"] == "TEXT" and header["variable_count"]:
            needed = header["variable_count"]
            if len(header_vars) != needed or any(str(i) not in header_vars for i in range(1, needed + 1)):
                raise CampaignError(f"Template needs {needed} header value(s).")
        for button in template.buttons:
            if not button["variable_count"]:
                continue
            key = str(button["index"])
            if key not in button_vars:
                raise CampaignError(f'Fill in the link for "{button["text"] or "Button"}".')
    else:
        header = template.header
        if template.requires_header_media and not media_id:
            raise CampaignError(f"Template '{template.name}' needs a header media file.")
        if header and header["format"] == "TEXT" and header["variable_count"]:
            needed = header["variable_count"]
            if len(header_vars) != needed or any(str(i) not in header_vars for i in range(1, needed + 1)):
                raise CampaignError(f"Template needs {needed} header value(s).")
        for button in template.buttons:
            if not button["variable_count"]:
                continue
            key = str(button["index"])
            if key not in button_vars:
                raise CampaignError(f'Fill in the link for "{button["text"] or "Button"}".')

    allowed_targets = {"", CrmTarget.NONE, CrmTarget.OWNER_DATA, CrmTarget.AVAILABILITY}
    target = crm_target if crm_target in allowed_targets else ""

    with transaction.atomic():
        campaign = Campaign.objects.create(
            name=(name or "").strip()[:200] or f"{template.name} · {timezone.localdate()}",
            number=number,
            template=template,
            created_by=agent,
            status=Campaign.Status.QUEUED,
            variables=body_vars,
            header_variables=header_vars,
            button_variables=button_vars,
            header_media_id=media_id,
            total=len(clean),
            crm_target=target,
        )
        CampaignRecipient.objects.bulk_create(
            [
                CampaignRecipient(
                    campaign=campaign,
                    phone=r["phone"],
                    name=r.get("name") or "",
                    variables=r.get("variables") or {},
                    crm_lead_id=_crm_lead_id(r),
                    crm_deal_id=_crm_deal_id(r),
                    crm_role=_crm_role(r),
                    owner_data_id=_owner_data_id(r),
                )
                for r in clean
            ]
        )
    return campaign


def _without_opt_outs(rows: list[dict], warnings: list[str]) -> tuple[list[dict], list[str]]:
    from .crm_leads import drop_opted_out_rows, left_out_sentence

    kept, skipped = drop_opted_out_rows(rows)
    sentence = left_out_sentence(skipped)
    if sentence:
        warnings = [sentence, *warnings]
    return kept, warnings


def parse_recipient_inputs(
    *,
    text: str = "",
    csv_bytes: bytes | None = None,
    filename: str = "",
    template: WaTemplate | None = None,
) -> tuple[list[dict], list[str]]:
    """Parse paste and/or spreadsheet upload.

    Templates with body placeholders require the fixed Excel layout. Plain
    paste/legacy CSV still works for templates with no variables. Excel
    (.xlsx) always goes through the spreadsheet reader — treating the ZIP
    bytes as CSV raises and used to 500 the preview endpoint.
    """
    warnings: list[str] = []
    body_vars = int(template.variable_count) if template else 0

    if csv_bytes and is_spreadsheet_workbook(csv_bytes, filename):
        try:
            rows, warnings = parse_campaign_spreadsheet(
                csv_bytes,
                filename=filename,
                body_var_count=body_vars,
            )
            return _without_opt_outs(rows, warnings)
        except SpreadsheetFormatError as exc:
            if body_vars:
                raise CampaignError(str(exc)) from exc
            raise CampaignError(str(exc)) from exc

    if csv_bytes and body_vars:
        try:
            rows, warnings = parse_campaign_spreadsheet(
                csv_bytes,
                filename=filename,
                body_var_count=body_vars,
            )
            return _without_opt_outs(rows, warnings)
        except SpreadsheetFormatError as exc:
            raise CampaignError(str(exc)) from exc

    if body_vars and not csv_bytes:
        raise CampaignError(
            "Upload the Excel file — this template needs per-recipient values from "
            'columns {{1}}, {{2}}, … and Number. Paste-only lists cannot fill the template.'
        )

    rows: list[dict] = []
    if text:
        rows.extend(parse_recipients_text(text))
    if csv_bytes:
        try:
            rows.extend(parse_recipients_csv(csv_bytes))
        except Exception as exc:
            # Binary Excel mistaken for CSV, or a broken delimiter sniff.
            raise CampaignError(
                "Could not read that recipients file. Upload .xlsx or .csv with "
                "a Number column (and {{1}}… when the template needs them)."
            ) from exc

    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if row["phone"] in seen:
            continue
        seen.add(row["phone"])
        out.append(row)
    return _without_opt_outs(out, warnings)


def recipient_counts(campaign: Campaign) -> dict[str, int]:
    """Aggregate recipient statuses for API + campaign counters."""
    rows = (
        campaign.recipients.values("status")
        .annotate(n=Count("id"))
    )
    by = {r["status"]: r["n"] for r in rows}
    sent = by.get(CampaignRecipient.Status.SENT, 0)
    pending = by.get(CampaignRecipient.Status.PENDING, 0)
    skipped = by.get(CampaignRecipient.Status.SKIPPED, 0)
    exhausted = by.get(CampaignRecipient.Status.EXHAUSTED, 0)
    failed_rows = by.get(CampaignRecipient.Status.FAILED, 0)
    # "retrying" = failed but still has attempts left (next_retry_at may be in the future).
    retrying = campaign.recipients.filter(
        status=CampaignRecipient.Status.FAILED,
        attempt_count__lt=MAX_SEND_ATTEMPTS,
    ).count()
    # Permanent failures shown as failed: exhausted + (failed with no attempts left, defensive).
    permanent_failed = exhausted + campaign.recipients.filter(
        status=CampaignRecipient.Status.FAILED,
        attempt_count__gte=MAX_SEND_ATTEMPTS,
    ).count()
    return {
        "sent": sent,
        "pending": pending,
        "skipped": skipped,
        "retrying": retrying,
        "failed": permanent_failed,
        "failed_awaiting_retry": failed_rows,  # legacy alias for UI
    }


def refresh_campaign_counts(campaign: Campaign) -> None:
    counts = recipient_counts(campaign)
    campaign.sent = counts["sent"]
    # Store permanent fails + still-retrying fails so the progress bar stays honest.
    campaign.failed = counts["failed"] + counts["retrying"]
    campaign.skipped = counts["skipped"]
    campaign.save(update_fields=["sent", "failed", "skipped"])


def campaign_has_work_left(campaign: Campaign) -> bool:
    return campaign.recipients.filter(
        Q(status=CampaignRecipient.Status.PENDING)
        | Q(
            status=CampaignRecipient.Status.FAILED,
            attempt_count__lt=MAX_SEND_ATTEMPTS,
        )
    ).exclude(
        # Permanent Meta failures must never count as "work left".
        Q(error_detail__icontains="131049")
        | Q(error_detail__icontains="131026")
        | Q(error_detail__icontains="130472")
        | Q(error_detail__icontains="marketing daily cap")
        | Q(error_detail__icontains="undeliverable")
        | Q(error_detail__icontains="RECIPIENT_MISMATCH")
        | Q(error_detail__icontains="Gateway resolved")
        # Parked credit holds wait as FAILED. PENDING rows must still count as work
        # even if they still carry the old "no credit:" prefix for one beat.
        | Q(
            status=CampaignRecipient.Status.FAILED,
            error_detail__istartswith="no credit:",
        )
    ).exists()


def process_recipient(recipient_id: int) -> None:
    """Send one recipient: ensure Owner Data, start/send template. Schedules auto-retry on fail."""
    with transaction.atomic():
        recipient = (
            CampaignRecipient.objects.select_related(
                "campaign__number", "campaign__template", "campaign__created_by"
            )
            .select_for_update()
            .filter(pk=recipient_id, status=CampaignRecipient.Status.PENDING)
            .first()
        )
        if not recipient:
            return

        from apps.gateway.credit import credit_is_out, is_no_credit, park_recipient

        # A credit hold is not a failed number. Wait, and do not burn a try.
        if is_no_credit(recipient.error_detail or ""):
            if credit_is_out():
                park_recipient(recipient, recipient.error_detail)
                refresh_campaign_counts(recipient.campaign)
                return
            recipient.error_detail = ""
            recipient.attempt_count = 0
        elif credit_is_out():
            park_recipient(recipient, "waiting for gateway credit")
            refresh_campaign_counts(recipient.campaign)
            return

        # Heal rows that were re-queued after a permanent Meta failure (old bug).
        permanent, label = is_permanent_send_failure("", recipient.error_detail or "")
        if permanent or (recipient.attempt_count or 0) >= MAX_SEND_ATTEMPTS:
            recipient.status = CampaignRecipient.Status.EXHAUSTED
            recipient.next_retry_at = None
            if permanent and label:
                recipient.error_detail = label[:2000]
            recipient.save(update_fields=["status", "error_detail", "next_retry_at"])
            campaign = recipient.campaign
            refresh_campaign_counts(campaign)
            return

        # C25: opt-out holds at send time, not only when the list was built.
        # One indexed registry query; no Bitrix REST per row.
        from .crm_leads import phones_blocked_by_registry

        phone_digits = "".join(ch for ch in str(recipient.phone or "") if ch.isdigit())
        if phone_digits and phone_digits in phones_blocked_by_registry({phone_digits}):
            recipient.status = CampaignRecipient.Status.SKIPPED
            recipient.error_detail = "Opted out while waiting."
            recipient.next_retry_at = None
            recipient.save(update_fields=["status", "error_detail", "next_retry_at"])
            refresh_campaign_counts(recipient.campaign)
            return

        recipient.attempt_count = (recipient.attempt_count or 0) + 1
        recipient.last_attempt_at = timezone.now()
        recipient.next_retry_at = None
        recipient.save(update_fields=["attempt_count", "last_attempt_at", "next_retry_at"])

    campaign = recipient.campaign
    body_vars = _filled_vars(recipient.variables) or campaign.variables
    destination = crm_destination(campaign.crm_target or CrmTarget.AVAILABILITY)

    try:
        record = None
        if recipient.owner_data_id:
            record = {
                "type": f"DYNAMIC_{bitrix.OWNER_DATA_TYPE_ID}",
                "id": int(recipient.owner_data_id),
            }
        elif destination is not None:
            category_id, stage_id = destination
            record, created = ensure_owner_data(
                recipient.phone, recipient.name, category_id=category_id, stage_id=stage_id
            )
            recipient.owner_data_id = int(record["id"])
            recipient.owner_data_created = created
            recipient.save(update_fields=["owner_data_id", "owner_data_created"])

        # A Lead AI campaign (apps/leadai) puts the chat in the Lead AI screen
        # before its first message is broadcast, so the main inbox never sees
        # it. One transaction with the send: if the send fails, the mark (and a
        # new customer's empty chat) roll back with it, exactly as before.
        from apps.leadai.lane import before_campaign_send

        with transaction.atomic():
            before_campaign_send(campaign, recipient)
            batch = campaign.batch
            hide_new = bool(batch and str(batch.name or "").startswith("Rotate ·"))
            conversation = inbox_services.start_conversation(
                campaign.number,
                campaign.created_by,
                recipient.phone,
                campaign.template,
                body_vars,
                campaign.header_variables,
                campaign.header_media_id,
                campaign.button_variables,
                hide_new_from_inbox=hide_new,
            )
        recipient.conversation = conversation
        recipient.status = CampaignRecipient.Status.SENT
        recipient.sent_at = timezone.now()
        recipient.error_detail = ""
        recipient.next_retry_at = None
        recipient.save(
            update_fields=["conversation", "status", "sent_at", "error_detail", "next_retry_at"]
        )

        if record is not None:
            try:
                bitrix.add_comment(
                    record["type"],
                    record["id"],
                    _lead_timeline_comment(campaign, recipient, body_vars),
                )
            except bitrix.BitrixError as exc:
                logger.warning("Campaign Owner Data comment failed: %s", exc)

        if recipient.crm_lead_id:
            try:
                bitrix.add_comment(
                    "lead",
                    recipient.crm_lead_id,
                    _lead_timeline_comment(campaign, recipient, body_vars),
                )
            except bitrix.BitrixError as exc:
                logger.warning("Campaign lead comment failed: %s", exc)

        if recipient.crm_deal_id:
            try:
                from .renewals import post_deal_timeline

                post_deal_timeline(recipient, conversation)
            except Exception as exc:  # noqa: BLE001 - timeline must not fail the send
                logger.warning("Campaign renewal deal comment failed: %s", exc)

    except (CampaignError, SendBlocked, bitrix.BitrixError, AlotsError) as exc:
        code = _error_code_from_exc(exc)
        _mark_send_failed(recipient, str(exc), error_code=code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Campaign recipient %s failed", recipient_id)
        _mark_send_failed(recipient, str(exc))

    refresh_campaign_counts(campaign)
    _maybe_pause_for_marketing_cap(campaign)


def _lead_timeline_comment(campaign: Campaign, recipient: CampaignRecipient, body_vars: dict) -> str:
    """What the selected CRM lead's timeline should show after a list send."""
    filled = campaign.template.body_text or ""
    for key, value in (body_vars or {}).items():
        filled = filled.replace("{{" + str(key) + "}}", str(value))
    filled = filled.strip() or f"[{campaign.template.name}]"
    return (
        f"WhatsApp message\n"
        f"Template: {campaign.template.name}\n"
        f"From: +{campaign.number.phone_number}\n"
        f"To: +{recipient.phone}\n\n"
        f"{filled}\n\n"
        f"Campaign: {campaign.name}"
    )


def _error_code_from_exc(exc: Exception) -> str:
    if isinstance(exc, SendBlocked):
        text = str(exc)
        permanent, _ = is_permanent_send_failure("", text)
        if "RECIPIENT_MISMATCH" in text or "Gateway resolved" in text:
            return "RECIPIENT_MISMATCH"
        if permanent:
            if "131049" in text:
                return "131049"
            if "undeliverable" in text.lower():
                return "131026"
        return ""
    payload = getattr(exc, "payload", None)
    if isinstance(payload, dict):
        err = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        if isinstance(err, dict) and err.get("code") is not None:
            return str(err.get("code"))
    text = str(exc)
    for code in PERMANENT_FAIL_CODES:
        if code in text:
            return code
    return ""


def _mark_send_failed(recipient: CampaignRecipient, detail: str, *, error_code: str = "") -> None:
    from apps.gateway.credit import is_no_credit, mark_credit_out, park_recipient

    if is_no_credit(detail):
        park_recipient(recipient, detail, undo_attempt=True)
        mark_credit_out()
        return

    permanent, label = is_permanent_send_failure(error_code, detail)
    if permanent:
        recipient.status = CampaignRecipient.Status.EXHAUSTED
        recipient.error_detail = (label or detail or "")[:2000]
        recipient.next_retry_at = None
        recipient.save(update_fields=["status", "error_detail", "next_retry_at"])
        return

    recipient.error_detail = (detail or "")[:2000]
    if recipient.attempt_count >= MAX_SEND_ATTEMPTS:
        recipient.status = CampaignRecipient.Status.EXHAUSTED
        recipient.next_retry_at = None
    else:
        recipient.status = CampaignRecipient.Status.FAILED
        recipient.next_retry_at = timezone.now() + timedelta(minutes=RETRY_AFTER_MINUTES)
    recipient.save(update_fields=["status", "error_detail", "next_retry_at"])


def _maybe_pause_for_marketing_cap(campaign: Campaign) -> int:
    """Skip remaining PENDING when Meta's marketing cap is clearly exhausted for today."""
    caps = campaign.recipients.filter(
        status=CampaignRecipient.Status.EXHAUSTED,
    ).filter(
        Q(error_detail__icontains="131049") | Q(error_detail__icontains="marketing daily cap")
    ).count()
    if caps < MARKETING_CAP_PAUSE_AFTER:
        return 0
    note = (
        "Skipped: Meta marketing daily cap already hit repeatedly on this campaign. "
        "Retry these numbers tomorrow, or use a UTILITY template."
    )
    updated = campaign.recipients.filter(status=CampaignRecipient.Status.PENDING).update(
        status=CampaignRecipient.Status.SKIPPED,
        error_detail=note[:2000],
        next_retry_at=None,
    )
    if updated:
        logger.warning(
            "Campaign %s paused remaining %s recipients after %s marketing-cap fails",
            campaign.pk,
            updated,
            caps,
        )
        refresh_campaign_counts(campaign)
    return updated


def mark_recipient_undelivered(conversation_id: int, *, detail: str, error_code: str = "") -> None:
    """
    Template was accepted by the gateway but Meta later reported failed delivery.

    Also updates FAILED (awaiting retry) rows: an early webhook sometimes arrives
    without a Meta code, we schedule a retry, then a later webhook carries 131049 /
    131026 — those must become EXHAUSTED, not keep retrying.
    """
    if not conversation_id:
        return
    recipient = (
        CampaignRecipient.objects.select_related("campaign")
        .filter(
            conversation_id=conversation_id,
            status__in=(
                CampaignRecipient.Status.SENT,
                CampaignRecipient.Status.FAILED,
            ),
        )
        .order_by("-id")
        .first()
    )
    if not recipient:
        return

    code = str(error_code or "")
    note = (detail or "Undelivered after send").strip()
    permanent, label = is_permanent_send_failure(code, note)

    if permanent:
        recipient.status = CampaignRecipient.Status.EXHAUSTED
        recipient.error_detail = (label or note)[:2000]
        recipient.next_retry_at = None
    elif recipient.attempt_count >= MAX_SEND_ATTEMPTS:
        recipient.status = CampaignRecipient.Status.EXHAUSTED
        recipient.error_detail = note[:2000]
        recipient.next_retry_at = None
    else:
        recipient.status = CampaignRecipient.Status.FAILED
        recipient.error_detail = note[:2000]
        recipient.next_retry_at = timezone.now() + timedelta(minutes=RETRY_AFTER_MINUTES)

    recipient.save(update_fields=["status", "error_detail", "next_retry_at"])
    refresh_campaign_counts(recipient.campaign)
    if permanent and (code == "131049" or "131049" in (label or note)):
        _maybe_pause_for_marketing_cap(recipient.campaign)


def requeue_due_retries(*, limit: int = 200) -> list[int]:
    """
    Flip due FAILED rows back to PENDING and return campaign ids that need a runner.
    Beat calls this, then enqueues run_campaign for each id.
    """
    from apps.gateway.credit import credit_is_out

    if credit_is_out():
        return []

    now = timezone.now()
    due = list(
        CampaignRecipient.objects.filter(
            status=CampaignRecipient.Status.FAILED,
            attempt_count__lt=MAX_SEND_ATTEMPTS,
            next_retry_at__isnull=False,
            next_retry_at__lte=now,
        )
        .exclude(campaign__status=Campaign.Status.CANCELLED)
        .order_by("next_retry_at")
        .values_list("id", "campaign_id", "error_detail")[:limit]
    )
    if not due:
        return []

    campaign_ids: list[int] = []
    seen: set[int] = set()
    for rid, cid, err in due:
        permanent, label = is_permanent_send_failure("", err or "")
        if permanent:
            CampaignRecipient.objects.filter(pk=rid, status=CampaignRecipient.Status.FAILED).update(
                status=CampaignRecipient.Status.EXHAUSTED,
                error_detail=(label or err or "")[:2000],
                next_retry_at=None,
            )
            continue
        # Clear a parked "no credit:" prefix so PENDING rows stay visible to
        # campaign_has_work_left and are not mistaken for a still-held failure.
        clear_detail = ""
        if (err or "").lower().startswith("no credit:"):
            clear_detail = ""
            updates = {
                "status": CampaignRecipient.Status.PENDING,
                "next_retry_at": None,
                "error_detail": clear_detail,
            }
        else:
            updates = {
                "status": CampaignRecipient.Status.PENDING,
                "next_retry_at": None,
            }
        updated = CampaignRecipient.objects.filter(
            pk=rid,
            status=CampaignRecipient.Status.FAILED,
        ).update(**updates)
        if updated and cid not in seen:
            seen.add(cid)
            campaign_ids.append(cid)

    if campaign_ids:
        Campaign.objects.filter(pk__in=campaign_ids).exclude(
            status=Campaign.Status.CANCELLED
        ).update(status=Campaign.Status.RETRYING, finished_at=None)

    return campaign_ids
