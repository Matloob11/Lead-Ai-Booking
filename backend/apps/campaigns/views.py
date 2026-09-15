from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.catalog.models import WaTemplate

from .models import Campaign
from .serializers import serialize_campaign, serialize_recipient
from .services import CampaignError, create_campaign, parse_recipient_inputs, resend_skipped_on_number
from .tasks import run_campaign


def _parse_variables(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    # Form field may be JSON string
    import json

    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            return {}
    return {}


def _upload_name(request) -> str:
    upload = request.FILES.get("csv") or request.FILES.get("file")
    return upload.name if upload else ""


def _load_template(request) -> WaTemplate | None:
    raw = request.data.get("template_id")
    if not raw:
        return None
    return WaTemplate.objects.filter(pk=raw).first()


@api_view(["GET", "POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def campaign_list(request):
    if request.method == "GET":
        rows = (
            Campaign.objects.filter(created_by=request.user)
            .select_related("number", "template")
            .order_by("-created_at")[:100]
        )
        return Response([serialize_campaign(c) for c in rows])

    number = get_object_or_404(request.user.visible_numbers, pk=request.data.get("number_id"))
    template = get_object_or_404(WaTemplate, pk=request.data.get("template_id"))

    text = request.data.get("recipients_text") or request.data.get("phones") or ""
    csv_bytes = None
    upload = request.FILES.get("csv") or request.FILES.get("file")
    if upload:
        csv_bytes = upload.read()

    try:
        recipients, _warnings = parse_recipient_inputs(
            text=text,
            csv_bytes=csv_bytes,
            filename=_upload_name(request),
            template=template,
        )
        campaign = create_campaign(
            agent=request.user,
            number=number,
            template=template,
            recipients=recipients,
            name=request.data.get("name") or "",
            variables=_parse_variables(request.data.get("variables")),
            header_variables=_parse_variables(request.data.get("header_variables")),
            button_variables=_parse_variables(request.data.get("button_variables")),
            header_media_id=request.data.get("header_media_id") or "",
        )
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    run_campaign.delay(campaign.pk)
    campaign = Campaign.objects.select_related("number", "template").get(pk=campaign.pk)
    return Response(serialize_campaign(campaign), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@parser_classes([JSONParser])
def campaign_resend_skipped(request, pk):
    """Queue skipped + marketing-cap rows on the same or another WhatsApp number."""
    campaign = get_object_or_404(
        Campaign.objects.select_related("number", "template"),
        pk=pk,
        created_by=request.user,
    )
    number_id = request.data.get("number_id") or campaign.number_id
    number = get_object_or_404(request.user.visible_numbers, pk=number_id)
    try:
        new_campaign = resend_skipped_on_number(
            agent=request.user,
            campaign=campaign,
            number=number,
        )
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    run_campaign.delay(new_campaign.pk)
    new_campaign = Campaign.objects.select_related("number", "template").get(pk=new_campaign.pk)
    return Response(serialize_campaign(new_campaign), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def campaign_detail(request, pk):
    campaign = get_object_or_404(
        Campaign.objects.select_related("number", "template"),
        pk=pk,
        created_by=request.user,
    )
    payload = serialize_campaign(campaign)
    payload["recipients"] = [
        serialize_recipient(r) for r in campaign.recipients.order_by("id")[:500]
    ]
    return Response(payload)


@api_view(["POST"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def campaign_preview(request):
    """Parse paste/Excel and return count + sample without sending."""
    text = request.data.get("recipients_text") or request.data.get("phones") or ""
    csv_bytes = None
    upload = request.FILES.get("csv") or request.FILES.get("file")
    if upload:
        csv_bytes = upload.read()

    template = _load_template(request)
    try:
        recipients, warnings = parse_recipient_inputs(
            text=text,
            csv_bytes=csv_bytes,
            filename=_upload_name(request),
            template=template,
        )
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "count": len(recipients),
            "sample": recipients[:20],
            "warnings": warnings[:20],
        }
    )
