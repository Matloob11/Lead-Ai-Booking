"""Read-only: why POST /v23.0/772479489292535/messages returns HTTP 404."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from apps.catalog.models import WabaNumber
from apps.gateway.client import AlotsClient, AlotsError, _is_transient_send_failure
from apps.gateway.models import ApiCall, WebhookEvent
from apps.inbox.models import Message

PNID = "772479489292535"
MSISDN = "447428322124"

print("ALOTS_VERSION", getattr(settings, "ALOTS_VERSION", ""), flush=True)
print("LIVE_TRANSIENT_RETRY", _is_transient_send_failure(AlotsError("x", status_code=404, payload=None)), flush=True)
print("ALOTS_KEY_SET", bool((getattr(settings, "ALOTS_API_KEY", "") or "").strip()), flush=True)
print("GRAPH_TOKEN_SET", bool((getattr(settings, "META_GRAPH_ACCESS_TOKEN", "") or "").strip()), flush=True)

rows = list(
    WabaNumber.objects.filter(phone_number_id=PNID)
    | WabaNumber.objects.filter(phone_number__contains=MSISDN)
)
print("catalog_rows", len(rows), flush=True)
for n in rows:
    print(
        "number",
        n.pk,
        n.phone_number,
        "pnid=" + n.phone_number_id,
        "waba=" + n.waba_business_id,
        "label=" + (n.label or ""),
        "acct=" + (n.account_username or ""),
        "src=" + n.source,
        "active=" + str(n.is_active),
        "community=" + (n.community or ""),
        "terr=" + (n.template_sync_error or "")[:120],
        flush=True,
    )

calls = list(
    ApiCall.objects.filter(path__icontains=PNID).order_by("-id")[:12]
)
print("apicalls_for_pnid", len(calls), flush=True)
for c in calls:
    print(
        "call",
        c.id,
        c.created_at.isoformat(),
        c.method,
        c.path,
        "http=" + str(c.status_code),
        "err=" + (c.error or "")[:80],
        "resp=" + str(c.response_body)[:180],
        flush=True,
    )

recent_404 = list(
    ApiCall.objects.filter(path__endswith="/messages", status_code=404).order_by("-id")[:15]
)
print("recent_message_404s", len(recent_404), flush=True)
for c in recent_404:
    print(
        "m404",
        c.id,
        c.created_at.isoformat(),
        c.path,
        "resp=" + str(c.response_body)[:160],
        flush=True,
    )

ok_paths = list(
    ApiCall.objects.filter(path__endswith="/messages", status_code__lt=400)
    .values("path")
    .annotate(n=Count("id"))
    .order_by("-n")[:8]
)
print("ok_message_paths", ok_paths, flush=True)

hooks = list(WebhookEvent.objects.filter(phone_number_id=PNID).order_by("-id")[:5])
print("webhooks_exact_pnid", WebhookEvent.objects.filter(phone_number_id=PNID).count(), flush=True)
for h in hooks:
    print("hook", h.id, h.status, h.received_at.isoformat(), flush=True)

since = timezone.now() - timedelta(days=3)
failed = list(
    Message.objects.filter(
        error_detail__icontains="772479489292535",
        created_at__gte=since,
    )
    .select_related("conversation__number")
    .order_by("-id")[:8]
)
print("failed_msgs_3d", len(failed), flush=True)
for m in failed:
    num = m.conversation.number
    print(
        "failmsg",
        m.id,
        m.created_at.isoformat(),
        "conv=" + str(m.conversation_id),
        "num=" + num.phone_number,
        "pnid=" + num.phone_number_id,
        (m.error_detail or "")[:160],
        flush=True,
    )

print("--- alots channels ---", flush=True)
try:
    channels = AlotsClient().list_channels() or []
except AlotsError as exc:
    print("channels_error", str(exc)[:300], flush=True)
    channels = []
print("channel_count", len(channels), flush=True)
hit = None
for ch in channels:
    pid = str(ch.get("id") or ch.get("phone_number_id") or "")
    display = str(ch.get("display_phone_number") or ch.get("phone_number") or "")
    if PNID in pid or MSISDN in display.replace(" ", "").replace("+", ""):
        hit = ch
        print("channel_hit", ch, flush=True)
if hit is None:
    print("channel_hit", "NONE", flush=True)
    sample = []
    for ch in channels[:6]:
        sample.append(
            {
                "id": ch.get("id") or ch.get("phone_number_id"),
                "phone": ch.get("display_phone_number") or ch.get("phone_number"),
                "waba": ch.get("waba_id") or ch.get("waba_business_id"),
            }
        )
    print("channel_sample", sample, flush=True)

print("PROBE_DONE", flush=True)
