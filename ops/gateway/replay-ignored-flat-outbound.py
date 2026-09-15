"""Re-queue ignored Alots flat outbound-with-body webhooks (no phone_number_id).

Run once after deploying the from-MSISDN resolver. Prints counts only.
"""

from datetime import timedelta

from django.utils import timezone

from apps.gateway.models import WebhookEvent
from apps.gateway.parse import is_alots_flat_outbound
from apps.gateway.tasks import process_webhook_event

since = timezone.now() - timedelta(hours=48)
queued = 0
skipped = 0
for event in (
    WebhookEvent.objects.filter(
        status=WebhookEvent.Status.IGNORED,
        received_at__gte=since,
    )
    .order_by("id")
    .iterator(chunk_size=100)
):
    payload = event.payload or {}
    if not is_alots_flat_outbound(payload):
        skipped += 1
        continue
    if not (payload.get("text") or payload.get("type") in ("image", "video", "audio", "document", "sticker")):
        skipped += 1
        continue
    event.status = WebhookEvent.Status.PENDING
    event.error = ""
    event.save(update_fields=["status", "error"])
    process_webhook_event.delay(event.pk)
    queued += 1

print(f"replay-ignored-flat queued={queued} skipped={skipped}")
