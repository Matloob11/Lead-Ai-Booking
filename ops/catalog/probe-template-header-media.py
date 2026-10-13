# Forced-login checks of /api/catalog/templates/header-media/ on the live
# stack, run through `ops/wa.sh probe-template-header-media`. The refusals
# first, then one real 1x1 PNG: that mints one throwaway sample handle through
# the gateway. Prints statuses, the route used and the audit rows; never a key.
import struct
import zlib

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import Agent
from apps.gateway.models import ApiCall

URL = "/api/catalog/templates/header-media/"


def tiny_png():
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def upload(name, payload, mime="image/png", fmt="IMAGE"):
    return {"format": fmt, "file": SimpleUploadedFile(name, payload, content_type=mime)}


host = next((h for h in settings.ALLOWED_HOSTS if h and "*" not in h), "testserver")
admin = (
    Agent.objects.filter(is_active=True, is_superuser=True).order_by("id").first()
    or Agent.objects.filter(is_active=True, is_wa_admin=True).order_by("id").first()
)
print("login as:", admin.username, "(admin)" if admin.has_admin_rights else "(NOT admin)")

anon = Client(HTTP_HOST=host)
print("anon GET:", anon.get(URL).status_code)

c = Client(HTTP_HOST=host)
c.force_login(admin)
r = c.get(URL)
print("admin GET:", r.status_code, r.json())

r = c.post(URL, upload("a.png", tiny_png(), fmt="AUDIO"))
print("format AUDIO:", r.status_code, r.json().get("detail"))
r = c.post(URL, upload("a.png", b"<html>not a png</html>"))
print("HTML as PNG:", r.status_code, r.json().get("detail"))

last_id = ApiCall.objects.order_by("-id").values_list("id", flat=True).first() or 0
r = c.post(URL, upload("probe-1x1.png", tiny_png()))
body = r.json()
handle = str(body.get("header_handle") or "")
print(
    "real PNG:", r.status_code,
    "via=", body.get("via"), "format=", body.get("format"), "size=", body.get("size"),
    "handle_len=", len(handle), "handle_prefix=", handle[:6],
)
if r.status_code != 200:
    print("detail:", body.get("detail"))
for row in ApiCall.objects.filter(id__gt=last_id).order_by("id"):
    print(
        "  apicall:", row.method, row.path, row.status_code, str(row.duration_ms) + "ms",
        "sig_in_path=" + ("yes" if "sig=" in (row.path or "") else "no"),
        "request_body=" + ("logged" if row.request_body else "none"),
    )
print("PROBE_OK" if r.status_code == 200 and handle else "PROBE_FAIL")
