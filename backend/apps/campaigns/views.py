from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.models import WaTemplate

from .crm_leads import CrmLeadSendError, agent_for_bitrix_user, context_for_agent, send_from_leads, verify_signed_request
from .renewals import RenewalSendError, renewals_context, send_renewals
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

    # A retry of a Lead AI campaign keeps its chats in the Lead AI screen.
    from apps.leadai.lane import inherit_campaign

    inherit_campaign(campaign, new_campaign)
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


def _flag(raw) -> bool:
    """A JSON true from the Bitrix tool; "0", "false" and "" stay false."""
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _crm_lead_status(exc: CrmLeadSendError) -> int:
    text = str(exc)
    if "not configured" in text:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if text == "Forbidden.":
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST


def _signed_crm_payload(request):
    verify_signed_request(
        timestamp=request.headers.get("X-Crm-Ts", ""),
        signature=request.headers.get("X-Crm-Sign", ""),
        body=request.body,
    )
    return request.data if isinstance(request.data, dict) else {}


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
@csrf_exempt
def crm_leads_context(request):
    """Templates + From number for the Bitrix Leads toolbar. HMAC, no session."""
    try:
        data = _signed_crm_payload(request)
        agent = agent_for_bitrix_user(data.get("bitrix_user_id"))
        return Response(context_for_agent(agent))
    except CrmLeadSendError as exc:
        return Response({"detail": str(exc)}, status=_crm_lead_status(exc))


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
@csrf_exempt
def crm_leads_send(request):
    """Queue one campaign for the selected CRM leads. HMAC, no session."""
    try:
        data = _signed_crm_payload(request)
        agent = agent_for_bitrix_user(data.get("bitrix_user_id"))
        result = send_from_leads(
            agent=agent,
            template_id=data.get("template_id"),
            leads=data.get("leads") or data.get("items") or [],
            extra_body=_parse_variables(data.get("variables") or data.get("extra_body")),
            header_variables=_parse_variables(data.get("header_variables")),
            button_variables=_parse_variables(data.get("button_variables")),
            number_id=data.get("number_id"),
            entity=data.get("entity") or "lead",
            header_media_token=str(data.get("header_media_token") or ""),
            lead_ai=_flag(data.get("lead_ai")),
            field_map=data.get("variable_fields") if isinstance(data.get("variable_fields"), dict) else {},
        )
        return Response(result, status=status.HTTP_201_CREATED)
    except CrmLeadSendError as exc:
        return Response({"detail": str(exc)}, status=_crm_lead_status(exc))
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


def _renewal_variables(data, key):
    raw = data.get(key) if isinstance(data, dict) else None
    return raw if isinstance(raw, dict) else {}


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
@csrf_exempt
def crm_renewals_context(request):
    """Templates, From number, and the tenant/owner split. HMAC, no session."""
    try:
        data = _signed_crm_payload(request)
        agent = agent_for_bitrix_user(data.get("bitrix_user_id"))
        return Response(renewals_context(agent, data.get("deals") or []))
    except CrmLeadSendError as exc:
        return Response({"detail": str(exc)}, status=_crm_lead_status(exc))


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
@csrf_exempt
def crm_renewals_send(request):
    """Queue the tenant campaign and the owner campaign. HMAC, no session."""
    try:
        data = _signed_crm_payload(request)
        agent = agent_for_bitrix_user(data.get("bitrix_user_id"))
        result = send_renewals(
            agent=agent,
            number_id=data.get("number_id"),
            deals=data.get("deals") or [],
            tenant_template_id=data.get("tenant_template_id"),
            owner_template_id=data.get("owner_template_id"),
            tenant_variables=_renewal_variables(data, "tenant_variables"),
            owner_variables=_renewal_variables(data, "owner_variables"),
            tenant_header_variables=_renewal_variables(data, "tenant_header_variables"),
            owner_header_variables=_renewal_variables(data, "owner_header_variables"),
            tenant_button_variables=_renewal_variables(data, "tenant_button_variables"),
            owner_button_variables=_renewal_variables(data, "owner_button_variables"),
            tenant_header_media_token=str(data.get("tenant_header_media_token") or ""),
            owner_header_media_token=str(data.get("owner_header_media_token") or ""),
            lead_ai=_flag(data.get("lead_ai")),
            tenant_field_map=data.get("tenant_variable_fields") if isinstance(data.get("tenant_variable_fields"), dict) else {},
            owner_field_map=data.get("owner_variable_fields") if isinstance(data.get("owner_variable_fields"), dict) else {},
        )
        return Response(result, status=status.HTTP_201_CREATED)
    except (CrmLeadSendError, RenewalSendError) as exc:
        return Response({"detail": str(exc)}, status=_crm_lead_status(exc))
    except CampaignError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
