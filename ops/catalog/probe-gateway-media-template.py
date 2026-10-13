# One throwaway IMAGE-header template through the real routes, run through
# `ops/wa.sh probe-gateway-media-template`: forced-login admin, a 1x1 PNG
# sample minted at /api/catalog/templates/header-media/, then a UTILITY
# template created at /api/catalog/templates/create/ on ONE business account
# (the number the 2026-09-22 panel-session probe used). This is the proof that
# a handle minted through the gateway is one Meta accepts. The template is
# hidden from the panel at once; delete it in WhatsApp Manager when done.
import json
import struct
import zlib

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Agent
from apps.catalog.models import WabaNumber, WaTemplateHide
from apps.gateway.client import AlotsClient
from apps.gateway.models import ApiCall

WABA = "1426351832653450"
HM_URL = "/api/catalog/templates/header-media/"
CREATE_URL = "/api/catalog/templates/create/"


def tiny_png():
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


number = WabaNumber.objects.filter(waba_business_id=WABA, is_active=True).first()
print("waba:", WABA, "number:", number.phone_number if number else "NOT ACTIVE - stopping")
if number is None:
    raise SystemExit(1)

host = next((h for h in settings.ALLOWED_HOSTS if h and "*" not in h), "testserver")
admin = (
    Agent.objects.filter(is_active=True, is_superuser=True).order_by("id").first()
    or Agent.objects.filter(is_active=True, is_wa_admin=True).order_by("id").first()
)
c = Client(HTTP_HOST=host)
c.force_login(admin)
print("login as:", admin.username)

r = c.post(HM_URL, {"format": "IMAGE", "file": SimpleUploadedFile("probe-1x1.png", tiny_png(), content_type="image/png")})
body = r.json()
handle = str(body.get("header_handle") or "")
via = str(body.get("via") or "")
print("sample:", r.status_code, "via=", via, "handle_len=", len(handle), "detail=", body.get("detail"))
if r.status_code != 200 or not handle:
    print("PROBE_FAIL (no handle)")
    raise SystemExit(1)

name = "zz_probe_gateway_media_delete_me_" + timezone.now().strftime("%Y%m%d_%H%M")
payload = {
    "waba_business_id": WABA,
    "name": name,
    "category": "UTILITY",
    "language": "en",
    "body_text": "Your document is attached. Reply to this message if anything in it looks wrong.",
    "header_format": "IMAGE",
    "header_handle": handle,
    "header_handle_via": via,
}
last_id = ApiCall.objects.order_by("-id").values_list("id", flat=True).first() or 0
r = c.post(CREATE_URL, data=json.dumps(payload), content_type="application/json")
body = r.json()
print("create:", r.status_code, {k: body.get(k) for k in ("id", "name", "status", "category", "language")} if r.status_code == 201 else body.get("detail"))
for row in ApiCall.objects.filter(id__gt=last_id, path__endswith="/message_templates").order_by("id"):
    answer = row.response_body if isinstance(row.response_body, dict) else {}
    print("  apicall:", row.method, row.path, row.status_code, str(row.duration_ms) + "ms", "meta_status=", answer.get("status"), "meta_id=", answer.get("id"))

if r.status_code == 201:
    WaTemplateHide.hide_from_panel(WABA, name, agent=admin)
    print("hidden from the panel:", name)

rows = [t for t in (AlotsClient().list_templates(WABA) or []) if t.get("name") == name]
for t in rows:
    headers = [comp.get("format") for comp in t.get("components", []) if comp.get("type") == "HEADER"]
    print("meta lists it:", t.get("status"), t.get("category"), "header=", headers)
print("PROBE_OK" if r.status_code == 201 and rows else "PROBE_FAIL")
