# Run through `ops/wa.sh probe-bitrix-methods`: which CRM activity / to-do REST
# methods the backend's Bitrix webhook may call, so the Lead AI can move the
# meeting to-do that Bitrix's Lead Automation plans at the wrong time.
# Read-only: the REST method "methods" lists names and changes nothing. Never
# prints the webhook URL or its token.
from apps.crmlink import client

WANTED = (
    "crm.activity.list",
    "crm.activity.get",
    "crm.activity.update",
    "crm.activity.todo.add",
    "crm.activity.todo.update",
    "crm.activity.todo.updateDeadline",
    "crm.activity.todo.updateDescription",
    "crm.timeline.comment.add",
    "crm.lead.update",
    "crm.item.get",
    "crm.deal.get",
)

try:
    available = set(client.call("methods", {"scope": "crm"}) or [])
    for name in WANTED:
        print(("yes " if name.lower() in {m.lower() for m in available} else "no  ") + name)
    print(f"total crm methods: {len(available)}")
except client.BitrixError as exc:
    print("error=" + str(exc)[:200])
print("PROBE_OK")
