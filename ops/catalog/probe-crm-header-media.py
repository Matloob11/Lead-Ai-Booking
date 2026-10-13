# Live checks of POST /api/campaigns/crm-header-media/, run through
# `ops/wa.sh probe-crm-header-media`. Signs requests exactly the way
# ops/bitrix-aws/a7_lead_wa.php does (HMAC over "ts.meta." + raw bytes), as
# Bitrix user 1 for number 971524077268. The refusals first, then one real
# 1x1 PNG, which uploads one throwaway media file to the gateway for that
# number. Finally the token goes through send_from_leads inside a transaction
# that is rolled back, with the Celery hand-off stubbed: nothing is sent and
# no campaign row survives. Prints statuses and lengths, never the secret.
import base64
import hashlib
import hmac
import json
import struct
import time
import zlib
from unittest.mock import patch

from django.conf import settings
from django.db import transaction
from django.test import Client

from apps.accounts.models import Agent
from apps.campaigns.crm_leads import send_from_leads
from apps.campaigns.crm_media import header_media_id_for
from apps.campaigns.models import Campaign
from apps.catalog.models import WabaNumber, WaTemplate
from apps.gateway.models import ApiCall

URL = "/api/campaigns/crm-header-media/"
BITRIX_USER = "1"
PHONE = "971524077268"


def tiny_png():
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def headers_for(body, meta, secret=None):
    ts = str(int(time.time()))
    meta_b64 = base64.b64encode(json.dumps(meta).encode("utf-8")).decode("ascii")
    key = (secret if secret is not None else settings.CRM_LEAD_WA_SECRET).encode("utf-8")
    sig = hmac.new(key, f"{ts}.{meta_b64}.".encode("ascii") + body, hashlib.sha256).hexdigest()
    return {"HTTP_X_CRM_TS": ts, "HTTP_X_CRM_SIGN": sig, "HTTP_X_CRM_META": meta_b64}


host = next((h for h in settings.ALLOWED_HOSTS if h and "*" not in h), "testserver")
client = Client(HTTP_HOST=host)
agent = Agent.objects.get(bitrix_user_id=BITRIX_USER, is_active=True)
number = WabaNumber.objects.get(phone_number=PHONE)
print("secret set:", bool((settings.CRM_LEAD_WA_SECRET or "").strip()), "| agent:", agent.username, "| number:", number.pk, PHONE)
meta = {"bitrix_user_id": BITRIX_USER, "number_id": number.pk, "format": "IMAGE", "filename": "probe-1x1.png", "mime": "image/png"}


def post(body, meta_value, secret=None, sent=None):
    return client.post(
        URL,
        data=sent if sent is not None else body,
        content_type="application/octet-stream",
        **headers_for(body, meta_value, secret),
    )


r = client.get(URL)
print("GET:", r.status_code)
r = post(tiny_png(), meta, secret="wrong-secret")
print("wrong secret:", r.status_code, r.json().get("detail"))
r = post(tiny_png(), meta, sent=tiny_png() + b"x")
print("bytes changed after signing:", r.status_code, r.json().get("detail"))
r = post(b"<html>not a picture</html>", meta)
print("HTML as PNG:", r.status_code, r.json().get("detail"))
r = post(tiny_png(), dict(meta, format="VIDEO"))
print("PNG as VIDEO:", r.status_code, r.json().get("detail"))
r = post(tiny_png(), dict(meta, bitrix_user_id="999999"))
print("unknown Bitrix user:", r.status_code, r.json().get("detail"))

last = ApiCall.objects.order_by("-id").values_list("id", flat=True).first() or 0
r = post(tiny_png(), meta)
body = r.json()
token = str(body.get("media_token") or "")
print(
    "real PNG:", r.status_code,
    {k: body.get(k) for k in ("format", "name", "size", "mime", "number_id")},
    "token_len=", len(token), "media_id_in_answer=", "media_id" in body,
)
if r.status_code != 201:
    print("detail:", body.get("detail"))
for row in ApiCall.objects.filter(id__gt=last).order_by("id"):
    print("  apicall:", row.method, row.path, row.status_code, str(row.duration_ms) + "ms")

template = (
    WaTemplate.objects.filter(
        waba_business_id=number.waba_business_id, status=WaTemplate.Status.APPROVED
    )
    .order_by("-id")
)
template = next((t for t in template if t.header and t.header["format"] == "IMAGE"), None)
print("IMAGE template on this WABA:", template.name if template else None, "| body values:", template.variable_count if template else "-")
media_id = header_media_id_for(token, agent=agent, number=number, template=template) if token and template else ""
print("token -> media id:", "ok, len=%d" % len(media_id) if media_id else "NONE")

if token and template:
    with transaction.atomic():
        with patch("apps.campaigns.crm_leads.run_campaign") as run:
            values = {str(i): "probe" for i in range(2, template.variable_count + 1)}
            result = send_from_leads(
                agent=agent,
                template_id=template.pk,
                leads=[{"id": 1, "phone": "971500000000", "name": "Probe"}],
                extra_body=values,
                number_id=number.pk,
                entity="contact",
                header_media_token=token,
            )
            campaign = Campaign.objects.get(pk=result["campaign_id"])
            print(
                "campaign (rolled back):", campaign.status, "total=", campaign.total,
                "header_media_id matches token:", campaign.header_media_id == media_id,
                "celery hand-off called:", run.delay.called,
            )
        transaction.set_rollback(True)
    print("campaign row survived rollback:", Campaign.objects.filter(pk=result["campaign_id"]).exists())
    try:
        send_from_leads(
            agent=agent,
            template_id=template.pk,
            leads=[{"id": 1, "phone": "971500000000", "name": "Probe"}],
            extra_body={str(i): "probe" for i in range(2, template.variable_count + 1)},
            number_id=number.pk,
            entity="contact",
            header_media_token="",
        )
        print("send without token: NOT REFUSED")
    except Exception as exc:  # noqa: BLE001
        print("send without token refused:", type(exc).__name__, str(exc))

print("PROBE_OK" if r.status_code == 201 and media_id else "PROBE_FAIL")
