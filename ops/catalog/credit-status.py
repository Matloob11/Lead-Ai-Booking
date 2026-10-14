"""Read-only gateway credit status (C29). Never parks, releases or starts a campaign.

Prints out/low/waiting counts and the panel API codes — never the balance figure.
"""
from django.contrib.auth import get_user_model
from django.test import Client

from apps.gateway.credit import poll_gateway_credit
from apps.gateway.models import CreditState
from apps.campaigns.models import CampaignRecipient

status = poll_gateway_credit()
row = CreditState.objects.filter(pk=1).first()
waiting = CampaignRecipient.objects.filter(error_detail__istartswith="no credit:").count()

host = "wa.srv1802669.hstgr.cloud"
anon = Client(HTTP_HOST=host).get("/api/gateway/credit/")
admin = get_user_model().objects.filter(is_wa_admin=True).order_by("id").first()
authed = None
if admin is not None:
    c = Client(HTTP_HOST=host)
    c.force_login(admin)
    authed = c.get("/api/gateway/credit/")
body = None
if authed is not None and authed.status_code == 200:
    body = authed.json()
    # Never print the balance — only the flags the panel uses.
    body = {k: body.get(k) for k in ("out", "low") if k in (body or {})}

print(
    "credit-status",
    f"poll={status}",
    f"out={bool(row and row.out)}",
    f"low={bool(row and row.low)}",
    f"waiting={waiting}",
    f"anon={anon.status_code}",
    f"auth={getattr(authed, 'status_code', None)}",
    f"flags={body}",
)
