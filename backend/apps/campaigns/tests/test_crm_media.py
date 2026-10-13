"""CRM header media: the signed upload from the Bitrix tool, and the token the send checks."""

import base64
import hashlib
import hmac
import json
import struct
import time
import zlib
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase, TestCase, override_settings

from apps.accounts.models import Agent
from apps.campaigns import crm_media
from apps.campaigns.crm_leads import CrmLeadSendError, send_from_leads
from apps.campaigns.models import Campaign
from apps.campaigns.renewals import send_renewals
from apps.catalog.models import WabaNumber, WaTemplate
from apps.gateway.client import AlotsError

URL = "/api/campaigns/crm-header-media/"
SECRET = "test-crm-secret"
MB = 1024 * 1024


def tiny_png():
    """A real 1x1 PNG, so the byte check passes without a fixture file."""

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def signed_headers(body, meta, *, secret=SECRET, ts=None):
    """What a7_lead_wa.php sends: HMAC over "ts.meta." followed by the raw bytes."""
    stamp = str(int(time.time()) if ts is None else ts)
    meta_b64 = base64.b64encode(json.dumps(meta).encode("utf-8")).decode("ascii")
    sig = hmac.new(
        secret.encode("utf-8"), f"{stamp}.{meta_b64}.".encode("ascii") + body, hashlib.sha256
    ).hexdigest()
    return {"HTTP_X_CRM_TS": stamp, "HTTP_X_CRM_SIGN": sig, "HTTP_X_CRM_META": meta_b64}


def signed_json(payload, *, secret=SECRET):
    """What a7_lead_wa.php / a7_renewals_wa.php send to the JSON send routes."""
    body = json.dumps(payload).encode("utf-8")
    stamp = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), f"{stamp}.".encode("ascii") + body, hashlib.sha256).hexdigest()
    return body, {"HTTP_X_CRM_TS": stamp, "HTTP_X_CRM_SIGN": sig}


class Fake:
    def __init__(self, pk):
        self.pk = pk


class FakeTemplate:
    def __init__(self, fmt):
        self.header = {"format": fmt, "text": "", "variable_count": 0} if fmt else None
        self.requires_header_media = fmt in {"IMAGE", "VIDEO", "DOCUMENT"}


def media_template(waba, name, fmt, body="Hello {{1}}"):
    return WaTemplate.objects.create(
        waba_business_id=waba,
        name=name,
        language="en",
        category="MARKETING",
        status=WaTemplate.Status.APPROVED,
        components=[{"type": "HEADER", "format": fmt}, {"type": "BODY", "text": body}],
    )


class TokenTests(SimpleTestCase):
    def token(self, agent=7, number=3, fmt="IMAGE", media_id="m-1"):
        return crm_media.issue_media_token(
            agent=Fake(agent), number=Fake(number), header_format=fmt, media_id=media_id
        )

    def check(self, token, fmt="IMAGE", agent=7, number=3, side=""):
        return crm_media.header_media_id_for(
            token, agent=Fake(agent), number=Fake(number), template=FakeTemplate(fmt), side=side
        )

    def test_round_trip(self):
        self.assertEqual(self.check(self.token()), "m-1")

    def test_a_text_header_needs_no_file(self):
        self.assertEqual(self.check("garbage", fmt="TEXT"), "")
        self.assertEqual(
            crm_media.header_media_id_for("", agent=Fake(7), number=Fake(3), template=None), ""
        )

    def test_missing_file_names_the_kind(self):
        with self.assertRaises(CrmLeadSendError) as raised:
            self.check("", fmt="VIDEO")
        self.assertEqual(str(raised.exception), "Choose the video for the header.")

    def test_the_side_is_named_in_renewals(self):
        with self.assertRaises(CrmLeadSendError) as raised:
            self.check("", fmt="DOCUMENT", side="owner")
        self.assertEqual(str(raised.exception), "Choose the document for the header for the owner template.")

    def test_a_file_for_another_number_is_refused(self):
        with self.assertRaises(CrmLeadSendError) as raised:
            self.check(self.token(number=4))
        self.assertIn("another WhatsApp number", str(raised.exception))

    def test_a_file_from_another_agent_is_refused(self):
        with self.assertRaises(CrmLeadSendError):
            self.check(self.token(agent=8))

    def test_an_image_never_goes_in_a_document_header(self):
        with self.assertRaises(CrmLeadSendError) as raised:
            self.check(self.token(fmt="IMAGE"), fmt="DOCUMENT")
        self.assertEqual(
            str(raised.exception),
            "This template's header is a document, but the file chosen is an image. Choose a document.",
        )

    def test_a_tampered_token_is_refused(self):
        token = self.token()
        with self.assertRaises(CrmLeadSendError) as raised:
            self.check(token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb"))
        self.assertIn("could not be checked", str(raised.exception))

    def test_an_old_token_is_refused(self):
        with patch("django.core.signing.time.time", return_value=time.time() - 2 * 24 * 3600):
            token = self.token()
        with self.assertRaises(CrmLeadSendError) as raised:
            self.check(token)
        self.assertIn("more than a day ago", str(raised.exception))

    def test_a_token_signed_under_another_salt_is_refused(self):
        # Signed, not encrypted: the payload is readable, the signature is what binds it.
        forged = signing.dumps({"a": 7, "n": 3, "f": "IMAGE", "m": "x"}, salt="another-salt")
        with self.assertRaises(CrmLeadSendError):
            self.check(forged)


class TypeTests(SimpleTestCase):
    def test_a_png_is_a_png(self):
        self.assertEqual(crm_media.resolve_type("image/png", "a.png", "IMAGE", tiny_png()), "image/png")

    def test_a_renamed_page_is_not_an_image(self):
        self.assertEqual(crm_media.resolve_type("image/png", "a.png", "IMAGE", b"<html>hi</html>"), "")

    def test_a_video_never_fills_an_image_header(self):
        head = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16
        self.assertEqual(crm_media.resolve_type("video/mp4", "a.mp4", "IMAGE", head), "")
        self.assertEqual(crm_media.resolve_type("video/mp4", "a.mp4", "VIDEO", head), "video/mp4")
        self.assertEqual(crm_media.resolve_type("", "clip.3gp", "VIDEO", head), "video/3gpp")

    def test_a_document_header_takes_a_pdf_and_nothing_else(self):
        self.assertEqual(
            crm_media.resolve_type("", "plan.pdf", "DOCUMENT", b"%PDF-1.7\n..."), "application/pdf"
        )
        docx = b"PK\x03\x04" + b"\x00" * 26
        self.assertEqual(crm_media.resolve_type("application/zip", "Brochure.docx", "DOCUMENT", docx), "")
        self.assertEqual(crm_media.resolve_type("text/plain", "notes.txt", "DOCUMENT", b"hello"), "")

    def test_jpeg_bytes_count_even_when_the_name_is_wrong(self):
        self.assertEqual(
            crm_media.resolve_type("application/octet-stream", "shot.webp", "IMAGE", b"\xff\xd8\xff\xe0"),
            "image/jpeg",
        )
        self.assertEqual(
            crm_media.resolve_type("", "photo.jpg", "IMAGE", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8),
            "image/png",
        )

    def test_jpg_alias(self):
        self.assertEqual(
            crm_media.resolve_type("image/jpg", "a.jpg", "IMAGE", b"\xff\xd8\xff\xe0"), "image/jpeg"
        )

    def test_filename_loses_its_folder_and_control_characters(self):
        self.assertEqual(crm_media.clean_filename("C:\\fakepath\\villa\x07.png", "image/png"), "villa.png")
        self.assertEqual(crm_media.clean_filename("../../etc/passwd", "application/pdf"), "passwd")
        self.assertEqual(crm_media.clean_filename("", "application/pdf"), "header.pdf")
        self.assertEqual(crm_media.clean_filename("..", "image/png"), "header.png")

    def test_a_long_name_keeps_its_extension(self):
        name = crm_media.clean_filename("B" * 200 + " (English).pdf", "application/pdf")
        self.assertEqual(len(name), 120)
        self.assertTrue(name.endswith(" (English).pdf") or name.endswith(".pdf"))


@override_settings(CRM_LEAD_WA_SECRET=SECRET)
class UploadViewTests(TestCase):
    def setUp(self):
        self.agent = Agent.objects.create_user(
            username="crm-agent", password="x", bitrix_user_id="77", can_official_api=True, is_wa_admin=True
        )
        self.number = WabaNumber.objects.create(
            phone_number="971500000001", phone_number_id="pn1", waba_business_id="waba1"
        )
        self.meta = {
            "bitrix_user_id": "77",
            "number_id": self.number.pk,
            "format": "IMAGE",
            "filename": "villa.png",
            "mime": "image/png",
        }
        self.seen = {}
        gateway = patch("apps.campaigns.crm_media.AlotsClient")
        self.gateway = gateway.start()
        self.addCleanup(gateway.stop)
        self.gateway.return_value.upload_media.side_effect = self.fake_upload

    def fake_upload(self, phone_number_id, file_obj, filename, mime_type):
        self.seen.update(pnid=phone_number_id, name=filename, mime=mime_type, data=file_obj.read())
        return "wa-media-1"

    def post(self, body, meta=None, sent=None, extra=None, **sign):
        headers = signed_headers(body, meta or self.meta, **sign)
        headers.update(extra or {})
        return self.client.post(
            URL, data=sent if sent is not None else body, content_type="application/octet-stream", **headers
        )

    def assert_no_upload(self):
        self.gateway.return_value.upload_media.assert_not_called()

    def test_a_png_is_uploaded_for_that_number_and_a_token_comes_back(self):
        response = self.post(tiny_png())
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(
            {k: body[k] for k in ("format", "name", "size", "mime", "number_id")},
            {"format": "IMAGE", "name": "villa.png", "size": len(tiny_png()), "mime": "image/png", "number_id": self.number.pk},
        )
        self.assertNotIn("media_id", body)
        self.assertEqual(self.seen, {"pnid": "pn1", "name": "villa.png", "mime": "image/png", "data": tiny_png()})
        media_id = crm_media.header_media_id_for(
            body["media_token"], agent=self.agent, number=self.number, template=FakeTemplate("IMAGE")
        )
        self.assertEqual(media_id, "wa-media-1")

    def test_a_wrong_secret_is_forbidden(self):
        response = self.post(tiny_png(), secret="not-the-secret")
        self.assertEqual(response.status_code, 403)
        self.assert_no_upload()

    def test_a_non_hex_signature_is_forbidden_not_a_server_error(self):
        response = self.post(tiny_png(), extra={"HTTP_X_CRM_SIGN": "\u00e9" * 64})
        self.assertEqual(response.status_code, 403)
        self.assert_no_upload()

    def test_bytes_changed_after_signing_are_forbidden(self):
        response = self.post(tiny_png(), sent=tiny_png() + b"x")
        self.assertEqual(response.status_code, 403)
        self.assert_no_upload()

    def test_metadata_changed_after_signing_is_forbidden(self):
        headers = signed_headers(tiny_png(), self.meta)
        forged = dict(self.meta, number_id=self.number.pk + 1)
        headers["HTTP_X_CRM_META"] = base64.b64encode(json.dumps(forged).encode()).decode()
        response = self.client.post(URL, data=tiny_png(), content_type="application/octet-stream", **headers)
        self.assertEqual(response.status_code, 403)
        self.assert_no_upload()

    def test_an_old_request_is_refused(self):
        response = self.post(tiny_png(), ts=int(time.time()) - 3600)
        self.assertEqual(response.status_code, 400)
        self.assertIn("expired", response.json()["detail"])

    def test_a_declared_size_over_100_mb_is_refused_before_reading(self):
        response = self.post(tiny_png(), extra={"CONTENT_LENGTH": str(101 * MB)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("larger than 100 MB", response.json()["detail"])
        self.assert_no_upload()

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_a_page_named_png_is_refused_before_any_upload(self):
        response = self.post(b"<html>not a picture</html>")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "That file is not a JPEG or PNG up to 5 MB.")
        self.assert_no_upload()

    def test_a_png_is_not_a_video_header(self):
        response = self.post(tiny_png(), meta=dict(self.meta, format="VIDEO"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "That file is not an MP4 or 3GP video up to 16 MB.")
        self.assert_no_upload()

    def test_an_image_over_five_megabytes_is_refused(self):
        response = self.post(tiny_png() + b"\x00" * (5 * MB))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "That file is too large. WhatsApp takes a JPEG or PNG up to 5 MB.")
        self.assert_no_upload()

    def test_an_unknown_kind_is_refused(self):
        response = self.post(tiny_png(), meta=dict(self.meta, format="AUDIO"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Say whether the header is an image, a video or a document.")

    def test_garbled_metadata_is_refused(self):
        stamp = str(int(time.time()))
        meta_b64 = "!!not-base64!!"
        sig = hmac.new(SECRET.encode(), f"{stamp}.{meta_b64}.".encode() + tiny_png(), hashlib.sha256).hexdigest()
        response = self.client.post(
            URL, data=tiny_png(), content_type="application/octet-stream",
            HTTP_X_CRM_TS=stamp, HTTP_X_CRM_SIGN=sig, HTTP_X_CRM_META=meta_b64,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("could not be read", response.json()["detail"])

    def test_a_bitrix_user_without_an_inbox_login_is_refused(self):
        response = self.post(tiny_png(), meta=dict(self.meta, bitrix_user_id="999"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("no WhatsApp inbox login", response.json()["detail"])

    def test_a_number_the_agent_does_not_cover_is_refused(self):
        self.agent.is_wa_admin = False
        self.agent.save(update_fields=["is_wa_admin"])
        response = self.post(tiny_png())
        self.assertEqual(response.status_code, 400)
        self.assertIn("not available to you", response.json()["detail"])
        self.assert_no_upload()

    def test_a_gateway_refusal_is_a_502(self):
        self.gateway.return_value.upload_media.side_effect = AlotsError("(#131053) Media upload error")
        response = self.post(tiny_png())
        self.assertEqual(response.status_code, 502)
        self.assertIn("Media upload error", response.json()["detail"])

    def test_no_media_id_is_a_502(self):
        self.gateway.return_value.upload_media.side_effect = None
        self.gateway.return_value.upload_media.return_value = ""
        response = self.post(tiny_png())
        self.assertEqual(response.status_code, 502)


@override_settings(CRM_LEAD_WA_SECRET=SECRET)
class SendWithMediaTests(TestCase):
    def setUp(self):
        self.agent = Agent.objects.create_user(
            username="crm-agent", password="x", bitrix_user_id="77", can_official_api=True, is_wa_admin=True
        )
        self.number = WabaNumber.objects.create(
            phone_number="971500000001", phone_number_id="pn1", waba_business_id="waba1"
        )
        self.image = media_template("waba1", "villa_offer", "IMAGE")
        self.document = media_template("waba1", "brochure", "DOCUMENT")

    def token(self, fmt="IMAGE", media_id="wa-media-1"):
        return crm_media.issue_media_token(
            agent=self.agent, number=self.number, header_format=fmt, media_id=media_id
        )

    def deals(self):
        return [
            {
                "id": 11,
                "tenant_phone": "971501111111",
                "tenant_name": "Sara",
                "owner_phone": "971502222222",
                "owner_name": "Ali",
            }
        ]

    def test_a_leads_campaign_carries_the_media_id(self):
        with patch("apps.campaigns.crm_leads.run_campaign") as run:
            result = send_from_leads(
                agent=self.agent,
                template_id=self.image.pk,
                leads=[{"id": 5, "phone": "971501234567", "name": "Ali"}],
                number_id=self.number.pk,
                entity="contact",
                header_media_token=self.token(),
            )
        campaign = Campaign.objects.get(pk=result["campaign_id"])
        self.assertEqual(campaign.header_media_id, "wa-media-1")
        self.assertEqual(campaign.total, 1)
        run.delay.assert_called_once_with(campaign.pk)

    def test_a_leads_campaign_without_the_file_is_refused(self):
        with patch("apps.campaigns.crm_leads.run_campaign") as run:
            with self.assertRaises(CrmLeadSendError) as raised:
                send_from_leads(
                    agent=self.agent,
                    template_id=self.image.pk,
                    leads=[{"id": 5, "phone": "971501234567", "name": "Ali"}],
                    number_id=self.number.pk,
                )
        self.assertEqual(str(raised.exception), "Choose the image for the header.")
        self.assertEqual(Campaign.objects.count(), 0)
        run.delay.assert_not_called()

    def test_the_leads_send_route_reads_the_token(self):
        body, headers = signed_json(
            {
                "bitrix_user_id": "77",
                "entity": "contact",
                "template_id": self.image.pk,
                "number_id": self.number.pk,
                "leads": [{"id": 5, "phone": "971501234567", "name": "Ali"}],
                "variables": {},
                "header_media_token": self.token(),
            }
        )
        with patch("apps.campaigns.crm_leads.run_campaign"):
            response = self.client.post(
                "/api/campaigns/crm-leads/send/", data=body, content_type="application/json", **headers
            )
        self.assertEqual(response.status_code, 201, response.content)
        campaign = Campaign.objects.get(pk=response.json()["campaign_id"])
        self.assertEqual(campaign.header_media_id, "wa-media-1")

    def test_the_leads_send_route_refuses_a_forged_signature_cleanly(self):
        body, headers = signed_json({"bitrix_user_id": "77"})
        headers["HTTP_X_CRM_SIGN"] = "\u00e9" * 64
        response = self.client.post(
            "/api/campaigns/crm-leads/send/", data=body, content_type="application/json", **headers
        )
        self.assertEqual(response.status_code, 403)

    def test_renewals_check_both_files_before_queuing_either(self):
        with patch("apps.campaigns.renewals.run_campaign") as run:
            with self.assertRaises(CrmLeadSendError) as raised:
                send_renewals(
                    agent=self.agent,
                    number_id=self.number.pk,
                    deals=self.deals(),
                    tenant_template_id=self.image.pk,
                    owner_template_id=self.document.pk,
                    tenant_header_media_token=self.token(),
                )
        self.assertEqual(
            str(raised.exception), "Choose the document for the header for the owner template."
        )
        self.assertEqual(Campaign.objects.count(), 0)
        run.delay.assert_not_called()

    def test_renewals_give_each_side_its_own_file(self):
        with patch("apps.campaigns.renewals.run_campaign") as run:
            result = send_renewals(
                agent=self.agent,
                number_id=self.number.pk,
                deals=self.deals(),
                tenant_template_id=self.image.pk,
                owner_template_id=self.document.pk,
                tenant_header_media_token=self.token("IMAGE", "img-1"),
                owner_header_media_token=self.token("DOCUMENT", "doc-1"),
            )
        by_role = {item["role"]: Campaign.objects.get(pk=item["campaign_id"]) for item in result["campaigns"]}
        self.assertEqual(by_role["tenant"].header_media_id, "img-1")
        self.assertEqual(by_role["owner"].header_media_id, "doc-1")
        self.assertEqual(run.delay.call_count, 2)

    def test_the_renewals_send_route_reads_both_tokens(self):
        body, headers = signed_json(
            {
                "bitrix_user_id": "77",
                "number_id": self.number.pk,
                "deals": self.deals(),
                "tenant_template_id": self.image.pk,
                "owner_template_id": self.document.pk,
                "tenant_variables": {},
                "owner_variables": {},
                "tenant_header_media_token": self.token("IMAGE", "img-2"),
                "owner_header_media_token": self.token("DOCUMENT", "doc-2"),
            }
        )
        with patch("apps.campaigns.renewals.run_campaign"):
            response = self.client.post(
                "/api/campaigns/crm-renewals/send/", data=body, content_type="application/json", **headers
            )
        self.assertEqual(response.status_code, 201, response.content)
        media = sorted(Campaign.objects.values_list("header_media_id", flat=True))
        self.assertEqual(media, ["doc-2", "img-2"])
