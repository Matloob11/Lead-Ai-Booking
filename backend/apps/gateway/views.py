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

from .models import WebhookEvent
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
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_number_id = value.get("metadata", {}).get("phone_number_id", "") or phone_number_id
                for message in value.get("messages", []):
                    dedupe_key = message.get("id", "") or dedupe_key
                for status in value.get("statuses", []):
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
