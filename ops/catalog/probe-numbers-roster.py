# Read-only: dump Official numbers + active assignments as CSV for the Excel export.
import csv
import io

from apps.catalog.models import NumberAssignment, WabaNumber

buf = io.StringIO()
w = csv.writer(buf)
w.writerow(
    [
        "phone_number",
        "number_label",
        "display_name",
        "community",
        "account",
        "is_active",
        "webhook_configured",
        "source",
        "agent_name",
        "agent_username",
        "bitrix_user_id",
        "role",
    ]
)

numbers = WabaNumber.objects.all().order_by("-is_active", "phone_number")
assigns = {
    a.number_id: a
    for a in NumberAssignment.objects.filter(is_active=True).select_related("agent")
}

for n in numbers:
    a = assigns.get(n.pk)
    agent = a.agent if a else None
    w.writerow(
        [
            n.phone_number,
            n.label or n.display_name or "",
            n.display_name or "",
            n.community or "",
            n.account_username or "",
            "yes" if n.is_active else "no",
            "yes" if n.webhook_configured else "no",
            n.source or "",
            (agent.display_name if agent else "") or "",
            (agent.username if agent else "") or "",
            (agent.bitrix_user_id if agent else "") or "",
            (a.role if a else "") or "",
        ]
    )

print(buf.getvalue(), end="")
print("PROBE_OK")
