"""Read-only: NABIHA-44 send 500 / Matloob test 923078633218."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.catalog.models import WabaNumber
from apps.gateway.client import AlotsError, _is_transient_send_failure, _payload_without_plus_to
from apps.gateway.models import ApiCall
from apps.inbox.models import Contact, Conversation, Message

PNID = "1268836452972273"
MSISDN = "447360267436"
WA = "923078633218"

print("LIVE_STRIP", _payload_without_plus_to({"to": "+923078633218"})["to"], flush=True)
print("LIVE_TRANSIENT_500", _is_transient_send_failure(AlotsError("internal", status_code=500)), flush=True)

for n in WabaNumber.objects.filter(phone_number__contains=MSISDN) | WabaNumber.objects.filter(phone_number_id=PNID):
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
        flush=True,
    )

c = Contact.objects.filter(wa_id__contains="3078633218").first()
print("contact", None if not c else (c.pk, c.wa_id, c.profile_name, c.display_name), flush=True)
if c:
    for conv in Conversation.objects.filter(contact=c).select_related("number").order_by("-id")[:8]:
        print(
            "conv",
            conv.pk,
            "num=" + conv.number.phone_number,
            "pnid=" + conv.number.phone_number_id,
            "label=" + (conv.number.label or ""),
            "open=" + str(conv.is_session_open),
            "last=" + (conv.last_message_at.isoformat() if conv.last_message_at else ""),
            flush=True,
        )

since = timezone.now() - timedelta(hours=6)
msgs = list(
    Message.objects.filter(created_at__gte=since, error_detail__icontains="internal")
    .select_related("conversation__number", "conversation__contact")
    .order_by("-id")[:20]
)
print("internal_fail_6h", len(msgs), flush=True)
for m in msgs:
    print(
        "fail",
        m.id,
        m.created_at.isoformat(),
        "conv=" + str(m.conversation_id),
        "to=" + m.conversation.contact.wa_id,
        "from=" + m.conversation.number.phone_number,
        "pnid=" + m.conversation.number.phone_number_id,
        "body=" + (m.body or "")[:40],
        (m.error_detail or "")[:120],
        flush=True,
    )

calls = list(ApiCall.objects.filter(path__icontains=PNID, created_at__gte=since).order_by("-id")[:25])
print("apicalls_nabiha_6h", len(calls), flush=True)
for c in calls:
    to = ""
    if isinstance(c.request_body, dict):
        to = str(c.request_body.get("to") or "")
        typ = str(c.request_body.get("type") or "")
    else:
        typ = ""
    print(
        "call",
        c.id,
        c.created_at.isoformat(),
        "http=" + str(c.status_code),
        "to=" + to,
        "type=" + typ,
        "err=" + (c.error or "")[:80],
        "resp=" + str(c.response_body)[:160],
        flush=True,
    )

from collections import Counter
from django.db.models import Count

hour = timezone.now() - timedelta(hours=2)
print(
    "status_counts_2h",
    list(
        ApiCall.objects.filter(path__endswith="/messages", created_at__gte=hour)
        .values("status_code")
        .annotate(n=Count("id"))
        .order_by("-n")
    ),
    flush=True,
)
print(
    "status_counts_nabiha_6h",
    list(
        ApiCall.objects.filter(path__icontains=PNID, created_at__gte=since)
        .values("status_code")
        .annotate(n=Count("id"))
        .order_by("-n")
    ),
    flush=True,
)

fives = list(
    ApiCall.objects.filter(path__endswith="/messages", status_code=500, created_at__gte=hour).order_by("-id")[:80]
)
tos = Counter()
pnids = Counter()
for row in fives:
    if isinstance(row.request_body, dict):
        tos[str(row.request_body.get("to") or "")] += 1
    pnids[row.path] += 1
print("500_to", tos.most_common(12), flush=True)
print("500_path", pnids.most_common(12), flush=True)

week = timezone.now() - timedelta(days=7)
print(
    "nabiha_week",
    list(
        ApiCall.objects.filter(path__icontains=PNID, created_at__gte=week)
        .values("status_code")
        .annotate(n=Count("id"))
        .order_by("-n")
    ),
    flush=True,
)
print(
    "to_matloob_plus_week",
    list(
        ApiCall.objects.filter(
            path__endswith="/messages",
            created_at__gte=week,
            request_body__to="+923078633218",
        )
        .values("status_code")
        .annotate(n=Count("id"))
        .order_by("-n")
    ),
    flush=True,
)
print(
    "to_matloob_bare_week",
    list(
        ApiCall.objects.filter(
            path__endswith="/messages",
            created_at__gte=week,
            request_body__to="923078633218",
        )
        .values("status_code")
        .annotate(n=Count("id"))
        .order_by("-n")
    ),
    flush=True,
)
ok_to = list(
    ApiCall.objects.filter(path__endswith="/messages", status_code=200, created_at__gte=hour)
    .exclude(request_body__to__isnull=True)
    .values_list("request_body", flat=True)[:40]
)
from collections import Counter as C2
prefs = C2()
for body in ok_to:
    if isinstance(body, dict):
        t = str(body.get("to") or "")
        prefs[t[:4]] += 1
print("ok_to_prefix_sample", prefs.most_common(15), flush=True)

ever = list(
    ApiCall.objects.filter(request_body__to__icontains="3078633218")
    .values("status_code")
    .annotate(n=Count("id"))
    .order_by("-n")
)
print("ever_matloob_digits", ever, flush=True)

last_nabiha_ok = (
    ApiCall.objects.filter(path__icontains=PNID, status_code=200).order_by("-id").values("id", "created_at").first()
)
print("last_nabiha_200", last_nabiha_ok, flush=True)

day2 = timezone.now() - timedelta(days=2)
print(
    "pk_plus_2d",
    list(
        ApiCall.objects.filter(path__endswith="/messages", created_at__gte=day2, request_body__to__startswith="+92")
        .values("status_code")
        .annotate(n=Count("id"))
        .order_by("-n")
    ),
    flush=True,
)

print("PROBE_DONE", flush=True)
