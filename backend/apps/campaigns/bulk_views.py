"""Endpoints for Excel batches. Separate from the single-number campaign views."""

import json

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.catalog.models import WaTemplate

from .bulk import (
    BulkError,
    cancel_batch,
    create_batch,
    inspect_sheet,
    parse_mapped_rows,
    plan_lanes,
    serialize_batch,
    serialize_batch_list,
)
from .models import CampaignBatch, CrmTarget
from .services import CampaignError
from .tasks import run_campaign


def _upload(request):
    return request.FILES.get("file") or request.FILES.get("csv")


def _json_field(request, key, default):
    """A JSON-encoded form field, or the value itself when the body was JSON."""
    raw = request.data.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _string_map(raw) -> dict:
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _covered_waba_ids(user):
    return set(user.visible_numbers.exclude(waba_business_id="").values_list("waba_business_id", flat=True))


def _template_or_error(request):
    template = WaTemplate.objects.filter(pk=request.data.get("template_id") or 0).first()
    if template is None:
        return None, Response({"detail": "Pick an approved template."}, status=status.HTTP_400_BAD_REQUEST)
    if template.waba_business_id not in _covered_waba_ids(request.user):
        return None, Response(
            {"detail": "That template belongs to a business account that is not yours."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if template.status != WaTemplate.Status.APPROVED:
        return None, Response({"detail": f"Template '{template.name}' is not approved."}, status=status.HTTP_400_BAD_REQUEST)
    return template, None


def _rows_and_plan(request, template):
    upload = _upload(request)
    if not upload:
        raise BulkError("Upload the Excel file first.")
    file_bytes = upload.read()
    recipients, stats, warnings = parse_mapped_rows(
        file_bytes,
        upload.name or "",
        mapping=_json_field(request, "mapping", {}),
        template=template,
    )
    plan = plan_lanes(
        agent=request.user,
        template=template,
        number_ids=_json_field(request, "number_ids", []),
        recipients=recipients,
        per_number_cap=request.data.get("per_number_cap"),
    )
    return upload, recipients, stats, warnings, plan


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def batch_inspect(request):
    """Columns, sample values and a first guess at phone/name — for the mapping screen."""
    upload = _upload(request)
    if not upload:
        return Response({"detail": "Choose an Excel or CSV file."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(inspect_sheet(upload.read(), upload.name or ""))
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def batch_preview(request):
    """Parse the mapped sheet and show the split — nothing is created."""
    template, error = _template_or_error(request)
    if error:
        return error
    try:
        _upload_obj, recipients, stats, warnings, plan = _rows_and_plan(request, template)
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        {
            "stats": stats,
            "warnings": warnings,
            "sample": recipients[:8],
            "plan": plan,
            "template": {"id": template.pk, "name": template.name, "language": template.language},
        }
    )


@api_view(["GET", "POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def batch_list(request):
    if request.method == "GET":
        batches = CampaignBatch.objects.filter(created_by=request.user).order_by("-created_at")[:50]
        return Response(serialize_batch_list(batches))

    template, error = _template_or_error(request)
    if error:
        return error
    crm_target = str(request.data.get("crm_target") or CrmTarget.NONE).strip().lower()
    if crm_target not in CrmTarget.values:
        return Response({"detail": "Choose where the CRM cards should go, or none."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        upload, recipients, stats, warnings, plan = _rows_and_plan(request, template)
        batch, children = create_batch(
            agent=request.user,
            template=template,
            recipients=recipients,
            plan=plan,
            mapping=_json_field(request, "mapping", {}),
            name=str(request.data.get("name") or ""),
            crm_target=crm_target,
            header_variables=_string_map(_json_field(request, "header_variables", {})),
            button_variables=_string_map(_json_field(request, "button_variables", {})),
            header_media_ids=_string_map(_json_field(request, "header_media_ids", {})),
            source_filename=upload.name or "",
            warnings=warnings,
        )
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # After the commit, one runner per lane — the worker runs them side by side.
    for child_id in children:
        run_campaign.delay(child_id)

    payload = serialize_batch(batch)
    payload["stats"] = stats
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def batch_detail(request, pk):
    batch = get_object_or_404(CampaignBatch, pk=pk, created_by=request.user)
    return Response(serialize_batch(batch))


@api_view(["POST"])
def batch_cancel(request, pk):
    batch = get_object_or_404(CampaignBatch, pk=pk, created_by=request.user)
    cancel_batch(batch)
    return Response(serialize_batch(batch))
