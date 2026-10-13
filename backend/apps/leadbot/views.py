"""Bitrix robot → Official leadbot outreach."""

from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .auth import AuthError, verify_signed_request
from .models import LeadAutomation
from .outreach import OutreachError, run_outreach


def _payload(request):
    verify_signed_request(
        timestamp=request.headers.get("X-Crm-Ts", ""),
        signature=request.headers.get("X-Crm-Sign", ""),
        body=request.body,
    )
    return request.data if isinstance(request.data, dict) else {}


def _public(row: LeadAutomation) -> dict:
    badge = row.panel_badge() or {}
    return {
        "lead_id": row.bitrix_lead_id,
        "state": row.state,
        "badge": badge.get("label") or "",
        "conversation_id": row.conversation_id,
        "number": row.number.phone_number if row.number_id else "",
        "error": row.last_error,
        "reason": row.qualification_reason,
    }


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def outreach(request):
    """HMAC POST {leadId}. Idempotent once outreach is already in flight."""
    try:
        data = _payload(request)
    except AuthError as exc:
        code = 503 if "not configured" in str(exc) else 403
        return Response({"detail": str(exc)}, status=code)
    raw = data.get("leadId") or data.get("lead_id")
    try:
        lead_id = int(raw)
    except (TypeError, ValueError):
        return Response({"detail": "leadId is required."}, status=400)
    try:
        row = run_outreach(lead_id)
    except OutreachError as exc:
        return Response({"detail": exc.detail}, status=exc.http_status)
    return Response(_public(row))


@api_view(["GET"])
def board(request):
    """Lead AI list for the panel. Agents see their own rows; admins see all."""
    qs = LeadAutomation.objects.select_related("number", "agent").order_by("-updated_at")
    user = request.user
    if not getattr(user, "is_wa_admin", False) and not user.is_superuser:
        qs = qs.filter(agent=user)
    rows = []
    for row in qs[:200]:
        badge = row.panel_badge() or {}
        snap = row.snapshot if isinstance(row.snapshot, dict) else {}
        rows.append(
            {
                "id": row.pk,
                "lead_id": row.bitrix_lead_id,
                "title": snap.get("title") or "",
                "state": row.state,
                "badge": badge.get("label") or row.state,
                "kind": badge.get("kind") or "",
                "phone": row.customer_phone,
                "number": row.number.phone_number if row.number_id else "",
                "agent": (row.agent.display_name or row.agent.get_username()) if row.agent_id else "",
                "conversation_id": row.conversation_id,
                "error": row.last_error,
                "reason": row.qualification_reason,
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
        )
    return Response({"results": rows})
