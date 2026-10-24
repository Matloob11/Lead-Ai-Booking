"""Prove Lead AI Campaigns history API on live data (counts only, nothing sent).

Run: ops/wa.sh probe-leadai-campaigns
"""

from django.contrib.auth import get_user_model
from django.test import Client

from apps.campaigns.models import Campaign
from apps.leadai import campaign_history

Agent = get_user_model()
HOST = "wa.srv1802669.hstgr.cloud"

desk = Agent.objects.filter(is_active=True, can_lead_ai=True, can_official_api=True).order_by("id").first()
plain = (
    Agent.objects.filter(is_active=True, can_lead_ai=False, is_wa_admin=False, can_official_api=True)
    .order_by("id")
    .first()
)
assert desk is not None, "no Lead AI agent"
assert campaign_history.can_view(desk), "desk agent cannot view campaigns"

client = Client(HTTP_HOST=HOST)
client.force_login(desk)
listed = client.get("/api/leadai/campaigns/?limit=5", secure=True)
print("list", listed.status_code, "count", listed.json().get("count") if listed.status_code == 200 else listed.content[:200])
assert listed.status_code == 200, listed.content
body = listed.json()
results = body.get("results") or []
assert results, "no Lead AI campaigns in DB"
row = results[0]
print(
    "newest",
    row["id"],
    "status",
    row["status"],
    "sent",
    row["sent"],
    "delivered",
    row["delivered"],
    "read",
    row["read"],
    "failed",
    row["failed"],
    "skipped",
    row["skipped"],
)
detail = client.get(f"/api/leadai/campaigns/{row['id']}/", secure=True)
print(
    "detail",
    detail.status_code,
    "playbook",
    detail.json().get("playbook"),
    "template",
    detail.json().get("template_name"),
)
assert detail.status_code == 200
data = detail.json()
assert "delivered" in data and "read" in data
ids = [r["id"] for r in results]
assert Campaign.objects.filter(pk__in=ids, lead_ai__isnull=True).count() == 0
if plain is not None:
    other = Client(HTTP_HOST=HOST)
    other.force_login(plain)
    denied = other.get("/api/leadai/campaigns/", secure=True)
    print("plain", plain.username, denied.status_code)
    assert denied.status_code == 403
print("PROBE_OK")
