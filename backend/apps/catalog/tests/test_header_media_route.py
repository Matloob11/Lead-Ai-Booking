"""The header-media route: the gateway first, Meta's own token after it, refusals before any upload."""

import struct
import zlib
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.models import Agent
from apps.catalog.models import WabaNumber
from apps.gateway.client import AlotsError

URL = "/api/catalog/templates/header-media/"


def tiny_png():
    """A real 1x1 PNG, so the magic-byte check passes without a fixture file."""

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def png_upload(name="villa.png", payload=None):
    return {"format": "IMAGE", "file": SimpleUploadedFile(name, payload or tiny_png(), content_type="image/png")}


@override_settings(ALOTS_API_KEY="key", META_GRAPH_ACCESS_TOKEN="", ALOTS_UI_COOKIE="")
class HeaderMediaRouteTests(TestCase):
    def setUp(self):
        self.admin = Agent.objects.create_user(
            username="admin", password="pw", is_wa_admin=True, can_official_api=True
        )
        WabaNumber.objects.create(phone_number="971500000001", phone_number_id="pn1", waba_business_id="waba1")
        self.client.force_login(self.admin)

    def test_anonymous_is_refused(self):
        self.client.logout()
        self.assertIn(self.client.get(URL).status_code, (401, 403))

    def test_get_says_the_gateway_route_is_available(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"configured": True, "via": "gateway", "detail": ""})

    @override_settings(ALOTS_API_KEY="")
    def test_get_with_no_route_says_so(self):
        body = self.client.get(URL).json()
        self.assertFalse(body["configured"])
        self.assertEqual(body["via"], "")
        self.assertTrue(body["detail"])

    def test_a_png_is_minted_through_the_gateway(self):
        with patch("apps.gateway.client.AlotsClient.upload_sample", return_value="4:HANDLE") as mint:
            response = self.client.post(URL, png_upload())
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["header_handle"], "4:HANDLE")
        self.assertEqual(body["via"], "gateway")
        self.assertEqual(body["format"], "IMAGE")
        self.assertEqual(body["mime"], "image/png")
        mint.assert_called_once()
        self.assertEqual(mint.call_args.args, (tiny_png(), "villa.png", "image/png"))

    def test_a_gateway_refusal_is_a_502_with_metas_sentence(self):
        with patch(
            "apps.gateway.client.AlotsClient.upload_sample",
            side_effect=AlotsError("(#100) Invalid file type"),
        ):
            response = self.client.post(URL, png_upload())
        self.assertEqual(response.status_code, 502)
        detail = response.json()["detail"]
        self.assertTrue(detail.startswith("The sample was not accepted: "), detail)
        self.assertIn("Invalid file type", detail)

    @override_settings(META_GRAPH_ACCESS_TOKEN="tok", META_APP_ID="1")
    def test_metas_own_token_is_the_fallback_when_the_gateway_fails(self):
        with patch("apps.gateway.client.AlotsClient.upload_sample", side_effect=AlotsError("gateway down")):
            with patch("apps.gateway.graph.MetaGraphClient.upload_sample", return_value="4:GRAPH") as graph:
                response = self.client.post(URL, png_upload())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["via"], "graph")
        self.assertEqual(response.json()["header_handle"], "4:GRAPH")
        graph.assert_called_once()

    @override_settings(META_GRAPH_ACCESS_TOKEN="tok", META_APP_ID="1")
    def test_the_gateway_still_goes_first_when_metas_token_is_set(self):
        with patch("apps.gateway.client.AlotsClient.upload_sample", return_value="4:GW") as mint:
            with patch("apps.gateway.graph.MetaGraphClient.upload_sample") as graph:
                response = self.client.post(URL, png_upload())
        self.assertEqual(response.json()["via"], "gateway")
        mint.assert_called_once()
        graph.assert_not_called()

    def test_a_fake_png_is_refused_before_any_upload(self):
        with patch("apps.gateway.client.AlotsClient.upload_sample") as mint:
            response = self.client.post(URL, png_upload(payload=b"<html>not a png</html>"))
        self.assertEqual(response.status_code, 400)
        mint.assert_not_called()

    def test_an_unknown_kind_is_refused(self):
        with patch("apps.gateway.client.AlotsClient.upload_sample") as mint:
            response = self.client.post(URL, {"format": "AUDIO", "file": SimpleUploadedFile("a.png", tiny_png(), content_type="image/png")})
        self.assertEqual(response.status_code, 400)
        mint.assert_not_called()
