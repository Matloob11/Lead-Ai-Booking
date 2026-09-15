"""Inspect failed sends for 971559298388 (error 131026)."""

from apps.catalog.models import WabaNumber
from apps.inbox.models import Contact, Conversation, Message

contact = Contact.objects.filter(wa_id__endswith="559298388").first()
print(f"contact={contact}", flush=True)
if not contact:
    raise SystemExit(0)

convs = Conversation.objects.filter(contact=contact).select_related("number")
for c in convs:
    print(
        f"conv={c.pk} number={c.number.phone_number} pnid={c.number.phone_number_id} "
        f"status={c.status} window={c.session_expires_at} last_in={c.last_inbound_at}",
        flush=True,
    )
    for m in Message.objects.filter(conversation=c).order_by("-id")[:12]:
        print(
            f"  msg={m.pk} dir={m.direction} kind={m.kind} status={m.status} "
            f"err={m.error_code} detail={str(m.error_detail or '')[:180]} "
            f"body={str(m.body or '')[:80]!r} tpl={m.template_id} "
            f"wamid={m.wamid}",
            flush=True,
        )
        if m.payload:
            keys = list((m.payload or {}).keys())
            print(f"    payload_keys={keys}", flush=True)
            if m.kind == "template" or m.error_code:
                print(f"    payload={str(m.payload)[:400]}", flush=True)
