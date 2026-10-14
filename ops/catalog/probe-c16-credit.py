"""One-shot C16 live check: poll wallet, park exhausted credit rows, probe the panel API.

Prints only yes/no and counts — never the balance.
"""
from django.contrib.auth import get_user_model
from django.test import Client

from apps.gateway.credit import poll_gateway_credit, reclaim_credit_failures
from apps.gateway.models import CreditState
from apps.campaigns.models import CampaignRecipient

status = poll_gateway_credit()
row = CreditState.objects.filter(pk=1).first()
# Only reclaim while the wallet is still out — reclaiming after a recovery
# would park rows again with no next_retry_at.
reclaimed = reclaim_credit_failures() if (row and row.out) else 0
waiting = CampaignRecipient.objects.filter(error_detail__istartswith="no credit:").count()

host = "wa.srv1802669.hstgr.cloud"
anon = Client(HTTP_HOST=host).get("/api/gateway/credit/")
admin = get_user_model().objects.filter(is_wa_admin=True).order_by("id").first()
authed = None
if admin is not None:
    c = Client(HTTP_HOST=host)
    c.force_login(admin)
    authed = c.get("/api/gateway/credit/")

print(
    "c16",
    f"poll={status}",
    f"out={bool(row and row.out)}",
    f"reclaimed={reclaimed}",
    f"waiting={waiting}",
    f"anon={anon.status_code}",
    f"auth={getattr(authed, 'status_code', None)}",
    f"body={getattr(authed, 'json', lambda: None)() if authed is not None and authed.status_code == 200 else None}",
)
