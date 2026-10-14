"""Batch 2b stage B, board T61: the International City shops templates and the command that
submits them (submit_shops_templates) to the sending numbers' WABAs through the Template
Center's own create, with the Type 1 video of the media library as Template A's header
sample. The gateway is a fake; nothing leaves the test.
"""

import copy
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.catalog.models import WabaNumber, WaTemplate, WaTemplateHide
from apps.catalog.views import _parse_template_form
from apps.gateway.client import AlotsError
from apps.leadai import shop_media, shop_templates
from apps.leadai.management.commands import submit_shops_templates
from apps.leadai.models import DEFAULT_SHOPS_FACTS, LeadAiSettings, LeadAiShopMedia
from apps.leadai.tests.test_shop_media import MediaBase, mp4

CREATE = "apps.gateway.client.AlotsClient.create_template"
UPLOAD = "apps.gateway.client.AlotsClient.upload_sample"
FOLLOWUP_TEXT = (
    "Hi {{1}}, just a quick follow-up. Shops in International City are moving fast. Small shops from AED 33,000, "
    "medium from AED 48,000, large from AED 80,000 per year. Would you like to see them this week?"
)
RECONNECT_TEXT = (
    "Hi {{1}}, this is {{2}} from AR Properties. Some time ago you asked us about a shop in International City. We now "
    "have new shops available in France, England, China, Russia, Morocco and Persia clusters, from AED 33,000 per year, "
    "payable in 1 to 4 cheques. Are you still looking for a shop?"
)


class ShopTemplateTextTests(SimpleTestCase):
    def test_the_bodies_carry_the_shops_facts_from_prices(self):
        self.assertEqual(shop_templates.followup_body(DEFAULT_SHOPS_FACTS), FOLLOWUP_TEXT)
        self.assertEqual(shop_templates.reconnect_body(DEFAULT_SHOPS_FACTS), RECONNECT_TEXT)
        facts = copy.deepcopy(DEFAULT_SHOPS_FACTS)
        facts["types"][0].update(rent_from=35000, cheapest=35000)
        facts["types"][2].update(cheapest=95000)
        self.assertIn("Small shops from AED 35,000, medium from AED 48,000, large from AED 95,000 per year.", shop_templates.followup_body(facts))
        self.assertIn("from AED 35,000 per year, payable", shop_templates.reconnect_body(facts))
        self.assertEqual(shop_templates.rendered(FOLLOWUP_TEXT, {"1": "Sumon"})[:9], "Hi Sumon,")

    def test_the_template_centers_composer_takes_them_as_they_are(self):
        followup, error = _parse_template_form(shop_templates.followup_form(DEFAULT_SHOPS_FACTS))
        self.assertIsNone(error)
        self.assertEqual((followup["clean_name"], followup["category"], followup["language"], followup["via_graph"]), ("intl_city_shops_followup", "MARKETING", "en", False))
        self.assertEqual(
            followup["components"],
            [
                {"type": "BODY", "text": FOLLOWUP_TEXT, "example": {"body_text": [["Sumon"]]}},
                {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Yes, book a viewing"}, {"type": "QUICK_REPLY", "text": "Not now"}]},
            ],
        )
        reconnect, error = _parse_template_form(shop_templates.reconnect_form(DEFAULT_SHOPS_FACTS, "4::aGFuZGxl"))
        self.assertIsNone(error)
        self.assertFalse(reconnect["via_graph"])  # the handle is the gateway's: so is the create
        self.assertEqual(
            reconnect["components"],
            [
                {"type": "HEADER", "format": "VIDEO", "example": {"header_handle": ["4::aGFuZGxl"]}},
                {"type": "BODY", "text": RECONNECT_TEXT, "example": {"body_text": [["Sumon", "Malik"]]}},
                {
                    "type": "BUTTONS",
                    "buttons": [
                        {"type": "QUICK_REPLY", "text": "Yes, show me shops"},
                        {"type": "QUICK_REPLY", "text": "Not now"},
                        {"type": "QUICK_REPLY", "text": "Stop messages"},
                    ],
                },
            ],
        )

    def test_the_numbers_it_takes(self):
        parse = submit_shops_templates.parse_numbers
        self.assertEqual(parse(""), list(submit_shops_templates.SENDING_NUMBERS))
        self.assertEqual(len(submit_shops_templates.SENDING_NUMBERS), 8)
        self.assertEqual(parse("+971581058719, 971581058725,971581058719"), ["971581058719", "971581058725"])
        for bad in ("abc", "97158;rm -rf", "12345", "9715810587190000000"):
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                parse(bad)


class SubmitShopsTemplatesTests(MediaBase):
    def setUp(self):
        super().setUp()
        WabaNumber.objects.create(phone_number="971581058719", phone_number_id="p719", waba_business_id="wabaA")
        WabaNumber.objects.create(phone_number="+971581058720", phone_number_id="p720", waba_business_id="wabaA")
        WabaNumber.objects.create(phone_number="971581058721", phone_number_id="p721", waba_business_id="wabaB")
        WabaNumber.objects.create(phone_number="971581058722", phone_number_id="p722", waba_business_id="wabaC", is_active=False)
        self.video_bytes = mp4("avc1", "mp4a", pad=64)
        self.video, _ = shop_media.add(LeadAiShopMedia.Shop.TYPE_1, "Type 1 tour.mp4", self.video_bytes)

    def call(self, *args):
        out = StringIO()
        call_command("submit_shops_templates", *args, stdout=out, stderr=StringIO(), no_color=True)
        return out.getvalue()

    def made(self, create):
        """{(waba, name): payload} of the fake create's calls."""
        return {(call.args[0], call.args[1]["name"]): call.args[1] for call in create.call_args_list}

    def test_a_dry_run_says_what_would_go_and_uploads_and_submits_nothing(self):
        with patch(CREATE) as create, patch(UPLOAD) as upload:
            text = self.call("--dry-run")
        create.assert_not_called()
        upload.assert_not_called()
        self.assertIn(f"intl_city_shops_followup: {FOLLOWUP_TEXT}", text)
        self.assertIn("buttons: Yes, book a viewing | Not now", text)
        self.assertIn("buttons: Yes, show me shops | Not now | Stop messages", text)
        self.assertIn("WABA wabaA (+971581058719, +971581058720)\n  intl_city_shops_followup: would be submitted\n  intl_city_shops_reconnect: would be submitted", text)
        self.assertIn("WABA wabaB (+971581058721)", text)
        self.assertIn("header sample: Type 1 tour.mp4", text)
        self.assertIn("+971581058722: the number is not active, left out", text)
        for number in ("971581058723", "971581058724", "971581058725", "971581058726"):
            self.assertIn(f"+{number}: no such number here, left out", text)
        self.assertIn("would submit=4 skipped=0 failed=0", text)
        self.assertFalse(WaTemplate.objects.filter(name__in=shop_templates.NAMES).exists())

    def test_both_go_to_each_waba_that_lacks_them_with_one_upload_of_the_type_1_video(self):
        with patch(CREATE, return_value={"id": "777", "status": "PENDING"}) as create, patch(UPLOAD, return_value="4::aGFuZGxl") as upload:
            text = self.call()
        upload.assert_called_once()
        data, name, mime = upload.call_args.args
        self.assertEqual((data, name, mime), (self.video_bytes, "Type 1 tour.mp4", "video/mp4"))
        made = self.made(create)
        self.assertEqual(set(made), {("wabaA", "intl_city_shops_followup"), ("wabaA", "intl_city_shops_reconnect"), ("wabaB", "intl_city_shops_followup"), ("wabaB", "intl_city_shops_reconnect")})
        followup = made[("wabaA", "intl_city_shops_followup")]
        self.assertEqual((followup["category"], followup["language"]), ("MARKETING", "en"))
        self.assertEqual(followup["components"][0], {"type": "BODY", "text": FOLLOWUP_TEXT, "example": {"body_text": [["Sumon"]]}})
        reconnect = made[("wabaB", "intl_city_shops_reconnect")]
        self.assertEqual(reconnect["components"][0], {"type": "HEADER", "format": "VIDEO", "example": {"header_handle": ["4::aGFuZGxl"]}})
        self.assertEqual(reconnect["components"][1]["example"], {"body_text": [["Sumon", "Malik"]]})
        self.assertEqual([b["text"] for b in reconnect["components"][2]["buttons"]], ["Yes, show me shops", "Not now", "Stop messages"])
        self.assertEqual(WaTemplate.objects.filter(name__in=shop_templates.NAMES, status=WaTemplate.Status.PENDING).count(), 4)
        self.assertIn("intl_city_shops_followup: submitted, PENDING at Meta", text)
        self.assertIn("submitted=4 skipped=0 failed=0", text)
        # Run again: every WABA has both now (pending), and nothing is touched.
        with patch(CREATE) as create, patch(UPLOAD) as upload:
            text = self.call()
        create.assert_not_called()
        upload.assert_not_called()
        self.assertIn("intl_city_shops_reconnect: already PENDING (en), left alone", text)
        self.assertIn("submitted=0 skipped=4 failed=0", text)

    def test_an_existing_template_in_any_status_or_language_or_one_hidden_is_left_alone(self):
        WaTemplate.objects.create(waba_business_id="wabaA", name="intl_city_shops_followup", language="en_US", status=WaTemplate.Status.REJECTED)
        WaTemplateHide.objects.create(waba_business_id="wabaB", name="intl_city_shops_reconnect")
        with patch(CREATE, return_value={"id": "1", "status": "PENDING"}) as create, patch(UPLOAD, return_value="4::h"):
            text = self.call()
        self.assertEqual(set(self.made(create)), {("wabaA", "intl_city_shops_reconnect"), ("wabaB", "intl_city_shops_followup")})
        self.assertIn("intl_city_shops_followup: already REJECTED (en_US), left alone", text)
        self.assertIn("intl_city_shops_reconnect: already hidden in the panel, left alone", text)
        self.assertEqual(WaTemplate.objects.get(waba_business_id="wabaA", name="intl_city_shops_followup").status, WaTemplate.Status.REJECTED)

    def test_meta_saying_it_has_it_already_is_left_alone(self):
        with patch(CREATE, side_effect=AlotsError("Template name already exists in this language")), patch(UPLOAD, return_value="4::h"):
            text = self.call("--numbers", "971581058721")
        self.assertIn("intl_city_shops_followup: Meta has it already (PENDING), left alone", text)
        self.assertIn("submitted=0 skipped=2 failed=0", text)

    def test_without_a_type_1_video_template_a_is_not_submitted_and_template_b_still_goes(self):
        shop_media.delete(self.video)
        with patch(CREATE, return_value={"id": "1", "status": "PENDING"}) as create, patch(UPLOAD) as upload:
            text = self.call("--numbers", "971581058721")
        upload.assert_not_called()
        self.assertEqual(set(self.made(create)), {("wabaB", "intl_city_shops_followup")})
        self.assertIn("intl_city_shops_reconnect: the media library has no Type 1 video (Lead AI > Shop media), so it is not submitted", text)
        self.assertIn("submitted=1 skipped=0 failed=1", text)

    def test_an_upload_the_gateway_refuses_keeps_template_a_back(self):
        with patch(CREATE, return_value={"id": "1", "status": "PENDING"}) as create, patch(UPLOAD, side_effect=AlotsError("HTTP 500")):
            text = self.call("--numbers", "971581058721")
        self.assertEqual(set(self.made(create)), {("wabaB", "intl_city_shops_followup")})
        self.assertIn("the header sample did not upload (HTTP 500), so it is not submitted", text)

    def test_a_refusal_is_reported_and_the_rest_goes_on(self):
        def create(waba, payload):
            if payload["name"] == "intl_city_shops_followup":
                raise AlotsError("(#100) Invalid parameter")
            return {"id": "2", "status": "PENDING"}

        with patch(CREATE, side_effect=create), patch(UPLOAD, return_value="4::h"):
            text = self.call("--numbers", "971581058721")
        self.assertIn("intl_city_shops_followup: FAILED", text)
        self.assertIn("intl_city_shops_reconnect: submitted, PENDING at Meta", text)
        self.assertIn("submitted=1 skipped=0 failed=1", text)

    def test_the_rents_are_the_settings_as_they_are_now(self):
        facts = copy.deepcopy(DEFAULT_SHOPS_FACTS)
        facts["types"][1].update(rent_from=50000, cheapest=50000)
        LeadAiSettings.objects.filter(pk=1).update(shops_facts=facts)
        with patch(CREATE, return_value={"id": "1", "status": "PENDING"}) as create, patch(UPLOAD, return_value="4::h"):
            self.call("--numbers", "971581058721")
        body = self.made(create)[("wabaB", "intl_city_shops_followup")]["components"][0]["text"]
        self.assertIn("medium from AED 50,000", body)

    def test_numbers_none_of_which_can_take_it_stop_the_command(self):
        with self.assertRaises(CommandError):
            self.call("--numbers", "971581058722,971581058799")
        with self.assertRaises(CommandError):
            self.call("--numbers", "not-a-number")
