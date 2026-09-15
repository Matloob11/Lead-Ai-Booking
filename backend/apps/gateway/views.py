"""Inbound webhook surface for alots.io.

The handler does as little as possible: authenticate, persist the raw body,
hand it to Celery, answer 200. Anything slower risks alots timing out and
redelivering, and any parsing done here would be lost on a crash.
"""

import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import WebhookEvent
from .parse import is_alots_flat_outbound
from .tasks import process_webhook_event

logger = logging.getLogger(__name__)


def _authorised(request):
    """Check the shared secret configured per number in the alots panel."""
    expected = settings.ALOTS_WEBHOOK_TOKEN
    if not expected:
        # Refuse rather than accept anonymous callbacks: an unauthenticated
        # webhook lets anyone write messages into agents' inboxes.
        logger.error("ALOTS_WEBHOOK_TOKEN is not configured; rejecting webhook")
        return False

    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return hmac.compare_digest(header[7:].strip(), expected)

    api_key = request.headers.get("X-Webhook-Token") or request.headers.get("X-API-KEY", "")
    return bool(api_key) and hmac.compare_digest(api_key.strip(), expected)


def _extract_routing(payload):
    """Pull the phone number id and a dedupe key out of a Meta-shaped body."""
    phone_number_id = ""
    dedupe_key = ""
    try:
        # Alots flat outbound-with-body (2026-08): top-level phone_number_id + id.
        if is_alots_flat_outbound(payload):
            return str(payload.get("phone_number_id") or ""), str(payload.get("id") or "")

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_number_id = value.get("metadata", {}).get("phone_number_id", "") or phone_number_id
                for key in ("messages", "smb_message_echoes", "message_echoes", "echoes"):
                    for message in value.get(key) or []:
                        dedupe_key = message.get("id", "") or dedupe_key
                for status in value.get("statuses") or []:
                    if status.get("id"):
                        dedupe_key = f"{status['id']}:{status.get('status', '')}"
    except AttributeError:
        pass
    return phone_number_id, dedupe_key


@csrf_exempt
@require_http_methods(["GET", "POST"])
def alots_webhook(request):
    # Meta-style subscription handshake. alots may not use it, but answering
    # costs nothing and makes the endpoint reusable if we ever go direct.
    if request.method == "GET":
        challenge = request.GET.get("hub.challenge")
        if challenge and request.GET.get("hub.verify_token") == settings.ALOTS_WEBHOOK_TOKEN:
            return HttpResponse(challenge, content_type="text/plain")
        return JsonResponse({"status": "ok"})

    if not _authorised(request):
        return HttpResponseForbidden("invalid webhook credentials")

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        logger.warning("Webhook body was not valid JSON (%d bytes)", len(request.body or b""))
        return JsonResponse({"status": "ignored", "reason": "invalid json"}, status=200)

    phone_number_id, dedupe_key = _extract_routing(payload)

    if dedupe_key and WebhookEvent.objects.filter(dedupe_key=dedupe_key).exists():
        # A redelivery of something already recorded. Acknowledge so alots stops.
        return JsonResponse({"status": "duplicate"})

    event = WebhookEvent.objects.create(
        payload=payload,
        phone_number_id=phone_number_id,
        dedupe_key=dedupe_key,
    )
    process_webhook_event.delay(event.pk)
    return JsonResponse({"status": "accepted", "event": event.pk})


def _inspect_event_classification(payload):
    """Determine human-friendly classification of a webhook payload."""
    if not isinstance(payload, dict):
        return "unknown", False, "Invalid payload", "", ""

    if is_alots_flat_outbound(payload):
        text = (
            payload.get("text", {}).get("body", "")
            if isinstance(payload.get("text"), dict)
            else str(payload.get("text") or "")
        )
        to_num = payload.get("to") or ""
        from_num = payload.get("from") or ""
        return "outbound_flat_with_body", True, f"Outbound with Body to {to_num}: {text[:80]}", from_num, to_num

    entries = payload.get("entry") or []
    for entry in entries:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            display_num = metadata.get("display_phone_number") or ""
            phone_id = metadata.get("phone_number_id") or ""

            messages = value.get("messages") or []
            if messages:
                msg = messages[0]
                kind = msg.get("type") or "text"
                sender = msg.get("from") or ""
                body = ""
                if kind == "text":
                    body = (msg.get("text") or {}).get("body") or ""
                elif kind in ("image", "video", "audio", "document", "sticker"):
                    body = f"[{kind}]"
                return "inbound_message", True, f"Inbound Message from {sender}: {body[:80]}", display_num or phone_id, sender

            for echo_key in ("smb_message_echoes", "message_echoes", "echoes"):
                echoes = value.get(echo_key) or []
                if echoes:
                    echo = echoes[0]
                    text = (
                        echo.get("text", {}).get("body", "")
                        if isinstance(echo.get("text"), dict)
                        else str(echo.get("text") or "")
                    )
                    to_num = echo.get("to") or ""
                    return "outbound_echo_with_body", True, f"Echo Outbound with body to {to_num}: {text[:80]}", display_num or phone_id, to_num

            statuses = value.get("statuses") or []
            if statuses:
                st = statuses[0]
                status_name = st.get("status") or "status"
                recipient = st.get("recipient_id") or ""
                return "status_only_no_body", False, f"Status: {status_name.upper()} to {recipient} (⚠️ NO BODY in Webhook)", display_num or phone_id, recipient

    return "other", False, "Other webhook structure", "", ""


@api_view(["GET"])
def inspector_webhook_events(request):
    """Real-time JSON inspector API for testing incoming gateway webhooks.

    Admin session only — the payload dump includes customer numbers and bodies.
    """
    if not getattr(request.user, "has_admin_rights", False):
        return Response({"detail": "Admins only"}, status=status.HTTP_403_FORBIDDEN)

    from apps.catalog.models import WabaNumber

    limit = min(int(request.GET.get("limit", 40)), 150)
    since_id = request.GET.get("since_id")
    filter_phone = request.GET.get("phone", "").strip()
    filter_kind = request.GET.get("kind", "").strip()

    qs = WebhookEvent.objects.all().order_by("-id")
    if since_id and since_id.isdigit():
        qs = qs.filter(id__gt=int(since_id))

    # Fast catalog map
    catalog_map = {w.phone_number_id: w for w in WabaNumber.objects.all()}
    phone_map = {w.phone_number: w for w in WabaNumber.objects.all()}

    raw_events = list(qs[:limit])
    results = []

    for ev in raw_events:
        payload = ev.payload or {}
        kind, has_body, summary, channel_hint, peer = _inspect_event_classification(payload)

        # Match WABA
        waba = catalog_map.get(ev.phone_number_id) or catalog_map.get(channel_hint) or phone_map.get(channel_hint)
        waba_phone = waba.phone_number if waba else (channel_hint or "")
        waba_label = waba.label or waba.display_name if waba else (waba_phone or "Unknown")

        if filter_phone:
            if filter_phone not in (waba_phone, ev.phone_number_id, channel_hint, peer):
                continue

        if filter_kind == "body_only" and not has_body:
            continue
        if filter_kind == "status_only" and has_body:
            continue

        results.append({
            "id": ev.id,
            "received_at": ev.received_at.isoformat() if ev.received_at else "",
            "phone_number_id": ev.phone_number_id,
            "dedupe_key": ev.dedupe_key,
            "status": ev.status,
            "kind": kind,
            "has_body": has_body,
            "summary": summary,
            "waba_phone": waba_phone,
            "waba_label": waba_label,
            "peer": peer,
            "payload": payload,
        })

    channels = [
        {"phone": w.phone_number, "label": w.label or w.display_name or w.phone_number, "community": w.community}
        for w in WabaNumber.objects.filter(is_active=True).order_by("phone_number")
    ]

    return Response({
        "status": "ok",
        "count": len(results),
        "events": results,
        "channels": channels,
    })

