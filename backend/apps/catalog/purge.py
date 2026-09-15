"""Admin-only delete of a template on Meta.

Panel hide stays on DELETE /templates/<pk>/. This path actually calls the
gateway (and Graph on 405) so the name can be reused.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.gateway.client import AlotsClient, AlotsError

from .models import WaTemplate, WaTemplateHide


@api_view(["POST"])
def purge_template_meta(request, pk):
    """Delete this template name on Meta, then hide it locally so sync cannot revive it."""
    from .views import _covered_waba_ids, _meta_error_detail, _require_admin

    denied = _require_admin(request)
    if denied:
        return denied

    template = get_object_or_404(WaTemplate, pk=pk)
    if template.waba_business_id not in _covered_waba_ids(request.user):
        return Response(
            {"detail": "That WhatsApp Business account is not one of yours."},
            status=status.HTTP_403_FORBIDDEN,
        )

    waba_id = template.waba_business_id
    name = template.name
    meta_id = template.meta_template_id or ""

    try:
        AlotsClient().delete_template(waba_id, name, meta_template_id=meta_id)
    except AlotsError as exc:
        code = exc.status_code or status.HTTP_502_BAD_GATEWAY
        if code < 400 or code > 599:
            code = status.HTTP_502_BAD_GATEWAY
        return Response({"detail": _meta_error_detail(exc)}, status=code)

    WaTemplateHide.hide_from_panel(waba_id, name, agent=request.user)
    return Response({"status": "ok", "hidden": True})
