"""Rotate campaign endpoints. The sheet is sent only when an admin starts it."""

import csv
import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .bulk import BulkError, create_batch, parse_mapped_rows, serialize_batch, serialize_batch_list
from .models import Campaign, CampaignBatch, CampaignRecipient, CrmTarget
from .rotate import NAME_PREFIX, plan_pool, pool_snapshot, seed_template
from .services import CampaignError
from .tasks import run_campaign


def _admin(request):
    if not getattr(request.user, "has_admin_rights", False):
        return Response(
            {"detail": "Only an admin can run a rotate campaign."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _json_field(request, key, default):
    raw = request.data.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _string_map(raw):
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if str(value).strip()}


def _rotate_batches():
    return CampaignBatch.objects.filter(name__startswith=NAME_PREFIX).order_by("-created_at")


def _batch_or_404(pk):
    return get_object_or_404(_rotate_batches(), pk=pk)


@api_view(["GET"])
def rotate_pool(request):
    denied = _admin(request)
    if denied:
        return denied
    rows = pool_snapshot()
    ready = [row for row in rows if row["can_send"]]
    return Response(
        {
            "template": "aldardso",
            "language": "en",
            "per_number_cap": 300,
            "ready": len(ready),
            "capacity": len(ready) * 300,
            "numbers": rows,
        }
    )


@api_view(["GET"])
def rotate_history(request):
    denied = _admin(request)
    if denied:
        return denied
    return Response(serialize_batch_list(_rotate_batches()[:50]))


@api_view(["GET"])
def rotate_detail(request, pk):
    denied = _admin(request)
    if denied:
        return denied
    return Response(serialize_batch(_batch_or_404(pk)))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def rotate_start(request):
    denied = _admin(request)
    if denied:
        return denied
    template = seed_template()
    if template is None:
        return Response(
            {"detail": "No approved aldardso template to send."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    upload = request.FILES.get("file") or request.FILES.get("csv")
    if not upload:
        return Response({"detail": "Upload the recipient file."}, status=status.HTTP_400_BAD_REQUEST)

    mapping = _json_field(request, "mapping", {"phone": 0})
    media = _string_map(_json_field(request, "header_media_ids", {}))
    try:
        recipients, stats, warnings = parse_mapped_rows(
            upload.read(), upload.name or "", mapping=mapping, template=template
        )
        plan = plan_pool(recipients, number_ids=media.keys())
        batch, children = create_batch(
            agent=request.user,
            template=template,
            recipients=recipients,
            plan=plan,
            mapping=mapping,
            name=NAME_PREFIX,
            crm_target=CrmTarget.NONE,
            header_media_ids=media,
            source_filename=upload.name or "",
            warnings=warnings,
        )
    except (CampaignError, BulkError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    for child_id in children:
        run_campaign.delay(child_id)

    payload = serialize_batch(batch)
    payload["stats"] = stats
    return Response(payload, status=status.HTTP_201_CREATED)


def _failed_rows(batch):
    return (
        CampaignRecipient.objects.filter(
            campaign__batch=batch,
            status__in=(CampaignRecipient.Status.FAILED, CampaignRecipient.Status.EXHAUSTED),
        )
        .select_related("campaign__number")
        .order_by("id")
    )


@api_view(["GET"])
def rotate_failed(request, pk):
    denied = _admin(request)
    if denied:
        return denied
    batch = _batch_or_404(pk)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="rotate-{batch.pk}-failed.csv"'
    writer = csv.writer(response)
    writer.writerow(["phone", "name", "error", "from_number"])
    for row in _failed_rows(batch):
        writer.writerow([row.phone, row.name, row.error_detail, row.campaign.number.phone_number])
    return response


def _header_media_map() -> dict:
    media = {}
    rows = (
        Campaign.objects.filter(batch__name__startswith=NAME_PREFIX)
        .exclude(header_media_id="")
        .order_by("-id")
        .values_list("number_id", "header_media_id")
    )
    for number_id, media_id in rows:
        media.setdefault(str(number_id), media_id)
    return media


@api_view(["POST"])
def rotate_resend(request, pk):
    """One new rotation of the numbers that failed, reusing each line's header file."""
    denied = _admin(request)
    if denied:
        return denied
    batch = _batch_or_404(pk)
    seen = set()
    recipients = []
    for row in _failed_rows(batch):
        if row.phone in seen:
            continue
        seen.add(row.phone)
        recipients.append({"phone": row.phone, "name": row.name or ""})
    if not recipients:
        return Response(
            {"detail": "This campaign has no failed numbers to send again."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    template = seed_template()
    if template is None:
        return Response(
            {"detail": "No approved aldardso template to send."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    media = _header_media_map()
    plan = plan_pool(recipients, number_ids=media.keys())
    if not any(lane["count"] for lane in plan["lanes"]):
        return Response(
            {"detail": "No number with a header picture can take these rows."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if template.requires_header_media:
        missing = [
            lane["phone"]
            for lane in plan["lanes"]
            if lane["count"] and not media.get(str(lane["number_id"]))
        ]
        if missing:
            return Response(
                {
                    "detail": "These numbers have no header picture yet: "
                    + ", ".join(f"+{phone}" for phone in missing)
                    + ". Start a new rotate campaign and choose the picture."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        new_batch, children = create_batch(
            agent=request.user,
            template=template,
            recipients=recipients,
            plan=plan,
            mapping=batch.column_map or {"phone": 0},
            name=f"{NAME_PREFIX} · resend",
            crm_target=CrmTarget.NONE,
            header_media_ids=media,
            source_filename=batch.source_filename,
        )
    except (CampaignError, BulkError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    for child_id in children:
        run_campaign.delay(child_id)
    return Response(serialize_batch(new_batch), status=status.HTTP_201_CREATED)
