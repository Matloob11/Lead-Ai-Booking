"""Where a number lives in the CRM, answered once for the panel.

The panel could ask Bitrix itself — it runs inside the portal and has BX24 —
but the answer now takes several REST calls: the duplicate search for leads,
another for contacts, a read of each candidate to reject the phone-list record,
and two filtered queries against Owner Data. Doing that from the browser on
every click would be slow and would repeat logic that already exists here, in
the one place that also has to get it right for the background mirror.
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import client

# What the portal calls each record in a URL, so the panel can open one without
# knowing anything about Bitrix's naming.
PATHS = {
    "lead": "/crm/lead/details/{id}/",
    "contact": "/crm/contact/details/{id}/",
    f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}": f"/crm/type/{client.OWNER_DATA_TYPE_ID}/details/{{id}}/",
}

LABELS = {
    "lead": "Lead",
    "contact": "Contact",
    f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}": "Owner Data",
}


@api_view(["GET"])
def whereis(request):
    """GET /api/crm/whereis/?phone= — every CRM record carrying this number."""
    phone = request.GET.get("phone", "")
    if not client.configured():
        return Response({"records": [], "detail": "No CRM connection is configured."})

    records = client.find_records(phone)
    return Response(
        {
            "phone": "".join(ch for ch in phone if ch.isdigit()),
            "records": [
                {
                    "type": record["type"],
                    "id": record["id"],
                    "label": LABELS.get(record["type"], record["type"]),
                    "path": PATHS.get(record["type"], "").format(id=record["id"]),
                }
                for record in records
                if PATHS.get(record["type"])
            ],
        }
    )
