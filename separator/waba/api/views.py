import logging
import json
import requests
import redis

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.mixins import CreateModelMixin
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from separator.waba.models import (
    App,
    PartnerApp,
    Waba,
    Phone,
    Template,
    SessionWindow,
    normalize_msisdn,
)
from separator.waba import tasks as waba_tasks
from separator.waba.utils import (
    build_embedded_signup_link,
    build_hosted_embedded_signup_link,
    build_popup_embedded_signup_config,
    event_processing,
    get_api_credentials,
    messages_processing,
    send_message_from_phone,
)

logger = logging.getLogger("waba")
redis_client = redis.StrictRedis.from_url(settings.REDIS_URL)


PARTNER_PROXY_ROUTES = {
    "messages": "phone",
    "marketing_messages": "phone",
    "media": "phone",
    "settings": "phone",
    "register": "phone",
    "deregister": "phone",
    "request_code": "phone",
    "verify_code": "phone",
    "call_permissions": "phone",
    "block_users": "phone",
    "calls": "phone",
    "groups": "phone",
    "official_business_account": "phone",
    "whatsapp_business_profile": "phone",
    "message_templates": "waba",
    "phone_numbers": "waba",
    "subscribed_apps": "waba",
    "schedules": "waba",
    "dataset": "waba",
    "events": "dataset",
}


def _resolve_partner_proxy_waba(user, object_id, endpoint=None):
    if not endpoint:
        waba = Waba.objects.select_related("app", "partner_app").filter(
            waba_id=object_id,
            partner_app__owner=user,
            partner_app__active=True,
        ).first()
        if waba:
            return waba, "", None
        phone = Phone.objects.select_related("waba", "waba__app", "waba__partner_app").filter(
            phone_id=object_id,
            waba__partner_app__owner=user,
            waba__partner_app__active=True,
        ).first()
        return (phone.waba if phone else None), "", phone

    edge = (endpoint or "").strip("/").split("/", 1)[0]
    entity = PARTNER_PROXY_ROUTES.get(edge)
    if entity == "phone":
        phone = Phone.objects.select_related("waba", "waba__app", "waba__partner_app").filter(
            phone_id=object_id,
            waba__partner_app__owner=user,
            waba__partner_app__active=True,
        ).first()
        return (phone.waba if phone else None), edge, phone
    if entity == "waba":
        waba = Waba.objects.select_related("app", "partner_app").filter(
            waba_id=object_id,
            partner_app__owner=user,
            partner_app__active=True,
        ).first()
        return waba, edge, None
    if entity == "dataset":
        waba = Waba.objects.select_related("app", "partner_app").filter(
            dataset=object_id,
            partner_app__owner=user,
            partner_app__active=True,
        ).first()
        return waba, edge, None
    return None, edge, None


class WabaWebhook(GenericViewSet, CreateModelMixin):
    queryset = Phone.objects.all()
    authentication_classes = []
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        signature = request.headers.get("X-Hub-Signature-256")
        app_id = request.query_params.get('app_id')
        host = request.get_host()
        
        # Pass raw body for signature verification in the task
        raw_body = request.body.decode('utf-8')

        task = event_processing
        if settings.WABA_EVENTS_SEPARATOR:
            try:
                data = json.loads(raw_body)
                entry = data.get("entry", [{}])[0]
                changes = entry.get("changes", [{}])
                if changes:
                    change = changes[0]
                    field = change.get("field")
                    value = change.get("value", {})
                    if (field == "messages" and value.get("messages")) or field == "smb_message_echoes":
                        task = messages_processing
            except Exception:
                pass

        task.delay(
            raw_body=raw_body, 
            signature=signature, 
            app_id=app_id, 
            host=host
        )
        return HttpResponse("Mark, call me!")

    def list(self, request, *args, **kwargs):
        hub_mode = request.query_params.get("hub.mode")
        hub_challenge = request.query_params.get("hub.challenge")
        hub_verify_token = request.query_params.get("hub.verify_token")

        if hub_mode == "subscribe" and hub_verify_token:
            try:
                app = App.objects.get(
                    verify_token=hub_verify_token,
                    # owner=request.user.id,
                )
                return HttpResponse(hub_challenge, content_type="text/plain")
            except App.DoesNotExist:
                logger.error(
                    f"Verification token not found or does not belong to the user {request.query_params}",
                )
                return HttpResponse(
                    "token not found",
                    status=403,
                    content_type="text/plain",
                )
        return HttpResponse("Bad Request", status=400, content_type="text/plain")


@extend_schema(
    tags=["waba"],
    summary="Proxy partner request to Meta Graph API",
    description=(
        "Proxies partner requests to Meta using the stored WABA access token. "
        "Use the same JSON body as Meta Cloud API, but send it to this endpoint "
        "without Graph API version and without Meta token."
    ),
    request={
        "application/json": {
            "type": "object",
            "additionalProperties": True,
            "description": "Raw JSON payload that will be forwarded to Meta.",
        }
    },
    responses={
        200: OpenApiResponse(description="Raw Meta response."),
        400: OpenApiResponse(description="Meta or proxy error."),
        404: OpenApiResponse(description="Unsupported endpoint or object not found."),
    },
)
@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def partner_graph_proxy(request, object_id, endpoint=""):
    waba, edge, phone = _resolve_partner_proxy_waba(request.user, object_id, endpoint)
    if not waba or not waba.app:
        return Response({"error": "unsupported endpoint or object not found", "edge": edge}, status=404)
    if phone and phone.date_end and phone.date_end <= timezone.now():
        return Response({"error": "phone tariff expired"}, status=402)

    endpoint = (endpoint or "").strip("/")
    graph_path = f"{object_id}/{endpoint}" if endpoint else object_id
    meta_app, access_token = get_api_credentials(waba=waba)
    graph_url = f"{settings.FACEBOOK_API_URL}/v{meta_app.api_version}.0/{graph_path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    content_type = request.headers.get("Content-Type")
    if content_type:
        headers["Content-Type"] = content_type
    accept = request.headers.get("Accept")
    if accept:
        headers["Accept"] = accept

    query_params = request.query_params.copy()
    query_params.pop("api-key", None)

    meta_response = requests.request(
        request.method,
        graph_url,
        params=query_params,
        data=request._request.body if request.method in {"POST", "DELETE"} else None,
        headers=headers,
    )
    response = HttpResponse(
        meta_response.content,
        status=meta_response.status_code,
        content_type=meta_response.headers.get("Content-Type", "application/json"),
    )
    return response


@extend_schema(
    tags=["waba"],
    summary="Create WhatsApp Embedded Signup authorization link",
    description=(
        "Returns a Facebook Embedded Signup URL. Auth is required via session, "
        "`Authorization: Token <token>`, or `?api-key=<token>`. "
        "For partner onboarding pass `partner_app_id` as a query parameter for GET "
        "or in the JSON body for POST."
    ),
    parameters=[
        OpenApiParameter(
            name="partner_app_id",
            location=OpenApiParameter.QUERY,
            required=False,
            type=str,
            description="UUID of an active partner app owned by the authenticated integrator.",
        ),
        OpenApiParameter(
            name="api-key",
            location=OpenApiParameter.QUERY,
            required=False,
            type=str,
            description="DRF token alternative to the Authorization header.",
        ),
    ],
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "partner_app_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "UUID of an active partner app owned by the authenticated integrator.",
                }
            },
        }
    },
    responses={
        200: OpenApiResponse(
            response={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "format": "uri",
                    }
                },
            },
            description="Facebook authorization URL.",
        ),
        403: OpenApiResponse(description="Authenticated user is not an integrator."),
        404: OpenApiResponse(description="Partner app or WABA app was not found."),
    },
    examples=[
        OpenApiExample(
            "Partner GET",
            value={"url": "https://www.facebook.com/v25.0/dialog/oauth?..."},
            response_only=True,
        ),
        OpenApiExample(
            "Partner POST body",
            value={"partner_app_id": "00000000-0000-0000-0000-000000000000"},
            request_only=True,
        ),
    ],
)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def embedded_signup_link(request):
    partner_app = None
    partner_app_id = request.query_params.get("partner_app_id") or request.data.get("partner_app_id")
    if partner_app_id:
        if not getattr(request.user, "integrator", False):
            return Response({"error": "permission denied"}, status=403)
        partner_app = PartnerApp.objects.select_related("app").filter(
            id=partner_app_id,
            owner=request.user,
            active=True,
        ).first()
        if not partner_app:
            return Response({"error": "Partner app not found"}, status=404)

    try:
        domain = request.get_host().split(':')[0]
        app = partner_app.app if partner_app else App.objects.filter(sites__domain__iexact=domain).first()
        if not app:
            raise App.DoesNotExist

        if partner_app:
            url = build_embedded_signup_link(request, request.user, partner_app=partner_app)
            return Response({"url": url})

        if app.auth_flow == App.AuthFlow.HOSTED:
            return Response({
                "flow": app.auth_flow,
                "url": build_hosted_embedded_signup_link(app),
            })
        if app.auth_flow == App.AuthFlow.POPUP:
            data = build_popup_embedded_signup_config(request, request.user, partner_app=partner_app)
            data["flow"] = app.auth_flow
            return Response(data)

        url = build_embedded_signup_link(request, request.user, partner_app=partner_app)
    except App.DoesNotExist:
        domain = request.get_host().split(':')[0]
        return Response({"error": f"App not found for domain {domain}"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
    return Response({"flow": App.AuthFlow.MANUAL, "url": url})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def embedded_signup_popup_message(request):
    message = request.data.get("message") or _("Embedded Signup was cancelled.")
    messages.error(request, message)
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def embedded_signup_popup_callback(request):
    request_id = request.data.get("request_id")
    code = request.data.get("code")
    session = request.data.get("session") or {}
    logger.info(
        "Popup callback received: request_id=%s user_id=%s has_code=%s waba_id=%s phone_number_id=%s business_id=%s",
        request_id,
        getattr(request.user, "id", None),
        bool(code),
        session.get("waba_id"),
        session.get("phone_number_id"),
        session.get("business_id"),
    )
    if not request_id:
        return Response({"error": "Request ID is missing"}, status=400)
    if not code:
        return Response({"error": "Authorization code is missing"}, status=400)
    if not session.get("waba_id") or not session.get("phone_number_id"):
        return Response({"error": "Popup session data is missing"}, status=400)

    existing = redis_client.json().get(request_id)
    if not existing:
        return Response({"error": "Request data is missing"}, status=404)
    if str(existing.get("user")) != str(request.user.id):
        return Response({"error": "permission denied"}, status=403)

    app_id = existing.get("app")
    app = App.objects.filter(client_id=app_id, auth_flow=App.AuthFlow.POPUP).first()
    if not app:
        return Response({"error": "Popup app not found"}, status=404)

    state_lock_key = f"{request_id}:used"
    if not redis_client.set(state_lock_key, "1", nx=True, ex=7200):
        return Response({"error": "Request has already been used"}, status=400)

    redis_client.json().set(request_id, "$.code", code)
    redis_client.json().set(request_id, "$.popup_session", session)
    waba_tasks.add_popup_phone.delay(request_id, app_id)
    messages.success(request, _('The number has been successfully added. It will appear here in a few minutes.'))

    logger.info(
        "Popup callback scheduled: request_id=%s user_id=%s waba_id=%s phone_number_id=%s",
        request_id,
        getattr(request.user, "id", None),
        session.get("waba_id"),
        session.get("phone_number_id"),
    )
    return Response({
        "ok": True,
        "scheduled": True,
        "waba_id": session.get("waba_id"),
        "phone_number_id": session.get("phone_number_id"),
    })


# ---------------------------------------------------------------------------
# BE-05: Agent widget API (consumed by the Bitrix side-panel widget, Session 2)
# ---------------------------------------------------------------------------


def _resolve_agent_phone(user, phone_id):
    """
    Resolves a WABA phone the user is allowed to operate.

    Mirrors the access rules in `separator.waba.views.phone_details`: owner, superuser,
    or a Bitrix portal admin when the number is shared with B24 admins.
    Returns (phone, error_response); exactly one is non-None.
    """
    if not phone_id:
        return None, Response({"error": "phone_id is required"}, status=400)

    phone = Phone.objects.select_related(
        "waba", "waba__app", "line", "line__portal", "line__connector",
    ).filter(phone_id=phone_id).first()
    if not phone:
        return None, Response({"error": "phone not found"}, status=404)

    if user.is_superuser or phone.owner_id == user.id:
        return phone, None

    portal_id = phone.line.portal_id if phone.line_id and phone.line else None
    if phone.owner_id and portal_id and phone.availabletoB24admins:
        from separator.bitrix.models import User as BitrixUser

        if BitrixUser.objects.filter(
            owner=user, bitrix_id=portal_id, admin=True, active=True,
        ).exists():
            return phone, None

    return None, Response({"error": "permission denied"}, status=403)


def _serialize_window(phone, customer_phone, window):
    open_now = bool(window and window.is_open)
    return {
        "phone_id": phone.phone_id,
        "customer_phone": customer_phone,
        "open": open_now,
        "window_hours": settings.WABA_SESSION_WINDOW_HOURS,
        "enforced": settings.WABA_ENFORCE_SESSION_WINDOW,
        "last_inbound_at": window.last_inbound_at.isoformat() if window else None,
        "expires_at": window.expires_at.isoformat() if window else None,
        "remaining_seconds": window.remaining_seconds if window else 0,
        # Free-form is only permitted inside the window; outside it, only templates.
        "can_send_freeform": open_now,
        "can_send_template": True,
    }


@extend_schema(
    tags=["waba"],
    summary="24-hour session window status for a customer",
    description=(
        "Returns whether the Meta 24-hour customer service window is open for a given "
        "(business phone, customer) pair, plus the remaining seconds for a countdown timer. "
        "A customer who has never messaged this number is reported as closed."
    ),
    parameters=[
        OpenApiParameter("phone_id", str, OpenApiParameter.QUERY, required=True,
                         description="Meta Phone Number ID of the business number."),
        OpenApiParameter("customer_phone", str, OpenApiParameter.QUERY, required=True,
                         description="Customer MSISDN, with or without a leading '+'."),
    ],
    responses={
        200: OpenApiResponse(description="Window status."),
        400: OpenApiResponse(description="Missing parameter."),
        403: OpenApiResponse(description="Phone belongs to another user."),
        404: OpenApiResponse(description="Phone not found."),
    },
    examples=[
        OpenApiExample(
            "Open window",
            value={
                "phone_id": "123456789", "customer_phone": "+77001234567", "open": True,
                "window_hours": 24, "enforced": False,
                "last_inbound_at": "2026-08-02T09:00:00+00:00",
                "expires_at": "2026-08-03T09:00:00+00:00", "remaining_seconds": 60840,
                "can_send_freeform": True, "can_send_template": True,
            },
            response_only=True,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def session_window_status(request):
    phone, error = _resolve_agent_phone(request.user, request.query_params.get("phone_id"))
    if error:
        return error

    customer_phone = request.query_params.get("customer_phone")
    if not customer_phone:
        return Response({"error": "customer_phone is required"}, status=400)

    _open, window = SessionWindow.status_for(phone, customer_phone)
    return Response(_serialize_window(phone, normalize_msisdn(customer_phone), window))


@extend_schema(
    tags=["waba"],
    summary="Approved templates available to the agent widget",
    description=(
        "Lists Meta message templates for the WABA that owns this phone, including the "
        "named and positional parameters each component expects so the widget can render "
        "inputs for `{{1}}`, `{{2}}` and named placeholders. Defaults to APPROVED templates "
        "that are marked available in Bitrix24."
    ),
    parameters=[
        OpenApiParameter("phone_id", str, OpenApiParameter.QUERY, required=True,
                         description="Meta Phone Number ID of the business number."),
        OpenApiParameter("status", str, OpenApiParameter.QUERY, required=False,
                         description="Template status filter. Defaults to APPROVED; pass 'all' to disable."),
    ],
    responses={
        200: OpenApiResponse(description="Template list."),
        403: OpenApiResponse(description="Phone belongs to another user."),
        404: OpenApiResponse(description="Phone not found."),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_templates(request):
    phone, error = _resolve_agent_phone(request.user, request.query_params.get("phone_id"))
    if error:
        return error

    if not phone.waba_id:
        return Response({"phone_id": phone.phone_id, "count": 0, "templates": []})

    templates = Template.objects.filter(waba=phone.waba).prefetch_related(
        "components__named_params",
        "components__positional_params",
        "components__buttons__named_params",
        "components__buttons__positional_params",
    )

    status_filter = (request.query_params.get("status") or "APPROVED").strip()
    if status_filter.lower() != "all":
        templates = templates.filter(status__iexact=status_filter, availableInB24=True)

    results = []
    for template in templates.order_by("name", "lang"):
        named, positional, components = [], [], []
        for component in template.components.order_by("index", "id"):
            comp_named = [p.name for p in component.named_params.all()]
            comp_positional = [p.position for p in component.positional_params.all()]
            named.extend(comp_named)
            positional.extend(comp_positional)

            buttons = []
            for button in component.buttons.order_by("index", "id"):
                buttons.append({
                    "type": button.type,
                    "text": button.text,
                    "url": button.url,
                    "phone_number": button.phone_number,
                    "index": button.index,
                    "named_params": [p.name for p in button.named_params.all()],
                    "positional_params": [p.position for p in button.positional_params.all()],
                })

            components.append({
                "type": component.type,
                "format": component.format,
                "text": component.text,
                "index": component.index,
                "named_params": comp_named,
                "positional_params": sorted(comp_positional),
                "buttons": buttons,
            })

        results.append({
            "id": template.id,
            "name": template.name,
            "language": template.lang,
            "category": template.category,
            "status": template.status,
            "content": template.content,
            "components": components,
            "params": {
                "named": sorted(set(named)),
                "positional": sorted(set(positional)),
            },
        })

    return Response({"phone_id": phone.phone_id, "count": len(results), "templates": results})


def _build_template_shortcode(template_id, named_params, positional_params):
    """
    Renders the `template+<id>+name:value|value` shortcode consumed by
    `separator.bitrix.utils.parse_template_code`, so the Meta payload is built by the
    same code path Bitrix agents already use rather than a second implementation.
    """
    segments = []
    for key, value in (named_params or {}).items():
        segments.append(f"{key}:{value}")
    segments.extend(str(value) for value in (positional_params or []))

    code = f"template+{template_id}"
    if segments:
        code = f"{code}+{'|'.join(segments)}"
    return code


@extend_schema(
    tags=["waba"],
    summary="Send an approved template to a customer",
    description=(
        "Sends a Meta-approved template from a business number to a customer. This is the "
        "sanctioned way to reach a customer whose 24-hour window has closed.\n\n"
        "Provide parameters either as `params` (named), `positional` (ordered `{{1}}`, `{{2}}` "
        "values), or `components` for a raw Meta-format passthrough that overrides both.\n\n"
        "Note: sending a template does NOT reopen the 24-hour window. Only an inbound "
        "customer message does, so the window status in the response is unchanged by this call."
    ),
    request={
        "application/json": {
            "type": "object",
            "required": ["phone_id", "customer_phone", "template_id"],
            "properties": {
                "phone_id": {"type": "string"},
                "customer_phone": {"type": "string"},
                "template_id": {"type": "string"},
                "params": {"type": "object", "additionalProperties": {"type": "string"}},
                "positional": {"type": "array", "items": {"type": "string"}},
                "components": {"type": "array", "items": {"type": "object"}},
            },
        }
    },
    responses={
        200: OpenApiResponse(description="Meta send response plus post-send window status."),
        400: OpenApiResponse(description="Validation error or Meta rejection."),
        403: OpenApiResponse(description="Phone belongs to another user."),
        404: OpenApiResponse(description="Phone or template not found."),
    },
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_template(request):
    phone, error = _resolve_agent_phone(request.user, request.data.get("phone_id"))
    if error:
        return error

    customer_phone = request.data.get("customer_phone")
    template_id = request.data.get("template_id")
    if not customer_phone:
        return Response({"error": "customer_phone is required"}, status=400)
    if not template_id:
        return Response({"error": "template_id is required"}, status=400)

    template = Template.objects.filter(id=template_id, waba=phone.waba).first()
    if not template:
        return Response({"error": "template not found for this phone's WABA"}, status=404)

    to = normalize_msisdn(customer_phone)
    if not to:
        return Response({"error": "customer_phone is not a valid number"}, status=400)

    message = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
    }

    raw_components = request.data.get("components")
    if raw_components:
        message["type"] = "template"
        message["template"] = {
            "name": template.name,
            "language": {"code": template.lang},
            "components": raw_components,
        }
    else:
        named_params = request.data.get("params") or {}
        positional_params = request.data.get("positional") or []
        if not isinstance(named_params, dict):
            return Response({"error": "params must be an object"}, status=400)
        if not isinstance(positional_params, list):
            return Response({"error": "positional must be an array"}, status=400)

        # The shortcode is '|'-separated and ':'-delimited, so those characters cannot
        # survive a round trip. Reject rather than silently corrupt the message.
        for value in list(named_params.values()) + list(positional_params):
            if "|" in str(value):
                return Response(
                    {"error": "parameter values cannot contain '|'; use the 'components' field instead"},
                    status=400,
                )
        for key in named_params:
            if ":" in str(key):
                return Response(
                    {"error": "parameter names cannot contain ':'; use the 'components' field instead"},
                    status=400,
                )

        from separator.bitrix.utils import parse_template_code

        try:
            message.update(parse_template_code(
                _build_template_shortcode(template.id, named_params, positional_params)
            ))
        except Exception as e:
            logger.warning("Template payload build failed for %s: %s", template.id, e)
            return Response({"error": f"failed to build template payload: {e}"}, status=400)

    if message.get("type") != "template":
        return Response({"error": "could not resolve template payload"}, status=400)

    send_result = send_message_from_phone(phone, message, template=template)
    if isinstance(send_result, dict) and send_result.get("error"):
        return Response({"error": send_result.get("message", "send failed"), "meta": send_result}, status=400)

    # Deliberately no SessionWindow.touch() here: under Meta's rules an outbound template
    # does not open the customer service window; only an inbound customer message does.
    _open, window = SessionWindow.status_for(phone, to)
    return Response({
        "ok": True,
        "template": {"id": template.id, "name": template.name, "language": template.lang},
        "meta": send_result,
        "window": _serialize_window(phone, to, window),
    })
