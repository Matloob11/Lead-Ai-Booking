"""The new-lead greet (assistant/newlead.py; round 22): a lead created in Bitrix (the C67 webhook, bitrix_views.new_lead)
gets the greet template through the campaign popup's own path, once, with the Lead AI on; the portal's listing in the
lead's comment reaches the inventory (lead_context.listing_id, inventory.enquired) and the first turn's INVENTORY block."""

import datetime as dt
import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import WaTemplate
from apps.leadai.assistant import inventory, lead_context, newlead
from apps.leadai.models import LeadAiCampaign, LeadAiSettings, LeadAiUnit
from apps.leadai.tests.test_assistant import NOW, TEST_SETTINGS, Base
from apps.leadai.tests.test_residential_turns import RentBase, res_answer

URL = "/api/leadai/bitrix/new-lead/"
SECRET = TEST_SETTINGS["CRM_LEAD_WA_SECRET"]
LISTING_ID = "FYS8JPQCB4FA92YB0GWQV5H39G"


def lead_row(**extra) -> dict:
    row = {
        "ID": "900",
        "STATUS_ID": "NEW",
        "DATE_CREATE": (NOW - dt.timedelta(minutes=3)).isoformat(),
        "NAME": "Ahmed",
        "LAST_NAME": "Khan",
        "TITLE": "Property Finder WhatsApp | Ahmed Khan",
        "PHONE": [{"VALUE": "+971 50 999 8888", "VALUE_TYPE": "WORK"}],
        "SOURCE_ID": "UC_KQ0WO3",
        "COMMENTS": f"Listing ID: {LISTING_ID}",
        "UF_CRM_1731838126127": 28,  # 2 B/R
        "UF_CRM_1770537051525": "Serena",
    }
    row.update(extra)
    return row


class ContextTests(SimpleTestCase):
    def test_the_comments_listing_id_ref_and_link_are_read(self):
        context = lead_context.parse({"SOURCE_ID": "UC_KQ0WO3", "COMMENTS": f"Listing ID: {LISTING_ID}\nListing reference: a7group-1789"})
        self.assertEqual((context["listing_id"], context["listing_ref"], context["source"]), (LISTING_ID, "a7group-1789", "Property Finder"))
        context = lead_context.parse({"COMMENTS": "Hi, I am interested in your property on Bayut. Link: https://www.bayut.com/property/details-123.html"})
        self.assertEqual(context["listing_url"], "https://www.bayut.com/property/details-123.html")
        self.assertNotIn("listing_id", context)
        # The fields win over the comment; a short token is no listing id.
        context = lead_context.parse({"UF_CRM_1760707563281": "a7group-1633", "COMMENTS": "Listing reference: a7group-1789. Listing ID: ABC"})
        self.assertEqual(context["listing_ref"], "a7group-1633")
        self.assertNotIn("listing_id", context)
        self.assertNotIn("listing_id", lead_context.CONTEXT_KEYS)  # data for the inventory, never a line of the model's

    def test_the_listing_in_words(self):
        self.assertEqual(newlead.listing_words({"unit": "two_plus", "community": "Serena"}), "the apartment in Serena")
        self.assertEqual(newlead.listing_words({"unit": "studio", "cluster": "Spain Cluster"}), "the studio in Spain Cluster")
        self.assertEqual(newlead.listing_words({"property": "villa"}), "the villa")
        self.assertEqual(newlead.listing_words({"community": "Mudon"}), "the home in Mudon")
        # A villa or a townhouse names the home whatever the bedrooms field says.
        self.assertEqual(newlead.listing_words({"unit": "two_plus", "property": "townhouse", "community": "Mudon"}), "the townhouse in Mudon")
        self.assertEqual(newlead.listing_words({"unit": "two_plus", "property": "villa", "community": "Serena"}), "the villa in Serena")
        self.assertEqual(newlead.listing_words({}), "your enquiry")
        unit = LeadAiUnit(unit="townhouse", bedrooms="3", community="Mudon")
        self.assertEqual(newlead.listing_words({}, unit), "the 3-bedroom townhouse in Mudon")


class EnquiredTests(TestCase):
    def test_the_enquired_unit_is_found_by_ref_or_listing_id_and_marked(self):
        gone = LeadAiUnit.objects.create(source="pf", source_id=LISTING_ID, reference="a7group-1789", community="Serena", unit="two_plus", bedrooms="2", deal="rent", price=95000, active=False)
        live = LeadAiUnit.objects.create(source="pf", source_id="other", reference="a7group-1800", community="Serena", unit="two_plus", bedrooms="2", deal="rent", price=99000)
        self.assertEqual(inventory.enquired({"listing_ref": "A7GROUP-1789"}), gone)
        self.assertEqual(inventory.enquired({"listing_id": LISTING_ID.lower()}), gone)
        self.assertIsNone(inventory.enquired({"listing_ref": "a7group-1"}))
        self.assertIsNone(inventory.enquired({}))
        lines = inventory.lines([gone, live], enquired=gone)
        self.assertIn("(the listing they enquired about; no longer listed, offer the others)", lines[1])
        self.assertNotIn("enquired", lines[2])
        self.assertIn("(the listing they enquired about)", inventory.lines([live], enquired=live)[1])


class GreetTests(Base):
    def setUp(self):
        super().setUp()
        LeadAiSettings.objects.filter(pk=1).update(greet_enabled=True, greet_agent=self.admin, greet_number=self.number, greet_template="ic_shops")
        self.rows = {900: lead_row()}
        patcher = patch("apps.campaigns.tasks.run_campaign.delay")
        self.run = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("apps.crmlink.client.call", side_effect=self.call)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, method, payload=None):
        if method == "crm.lead.get":
            row = self.rows.get(int((payload or {}).get("id") or 0))
            if row is None:
                from apps.crmlink import client

                raise client.BitrixError("crm.lead.get: Not found")
            return dict(row)
        return []

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/x/")
    def test_a_new_lead_gets_the_greet_once_through_the_popups_path(self):
        result = newlead.greet(900, now=NOW)
        self.assertTrue(result.get("sent"), result)
        campaign = Campaign.objects.get(pk=result["campaign_id"])
        self.assertEqual(campaign.name, "New lead · Lead AI · ic_shops")
        recipient = CampaignRecipient.objects.get(campaign=campaign)
        self.assertEqual((recipient.phone, recipient.crm_lead_id, recipient.variables), ("971509998888", 900, {"1": "Ahmed"}))
        self.assertEqual((campaign.lead_ai.playbook, campaign.lead_ai.community), ("ic_shops", "Serena"))
        self.run.assert_called_once_with(campaign.pk)
        self.assertEqual(result["words"], "the apartment in Serena")
        # Once: the same lead again is left alone.
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "greeted already"})
        self.assertEqual(Campaign.objects.count(), 2)  # the fixture's and the greet's

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/x/")
    def test_the_listing_names_the_second_variable_when_the_template_has_one(self):
        WaTemplate.objects.create(
            waba_business_id="waba1", name="portal_enquiry_reply", language="en", category="UTILITY", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "Hi {{1}}, thank you for your enquiry about {{2}}."}],
        )
        LeadAiSettings.objects.filter(pk=1).update(greet_template="portal_enquiry_reply")
        LeadAiUnit.objects.create(source="pf", source_id=LISTING_ID, reference="a7group-1789", community="Serena", unit="two_plus", bedrooms="2", deal="rent", price=95000)
        result = newlead.greet(900, now=NOW)
        self.assertTrue(result.get("sent"), result)
        recipient = CampaignRecipient.objects.get(campaign_id=result["campaign_id"])
        self.assertEqual(recipient.variables, {"1": "Ahmed", "2": "the 2-bedroom apartment in Serena"})
        # The lead with no Community field: the enquired listing's community is the chat's (the first live greet, 2026-10-22).
        self.rows[903] = lead_row(ID="903", PHONE=[{"VALUE": "+971509997777"}], UF_CRM_1770537051525="")
        result = newlead.greet(903, now=NOW)
        self.assertTrue(result.get("sent"), result)
        self.assertEqual(Campaign.objects.get(pk=result["campaign_id"]).lead_ai.community, "Serena")

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/x/")
    def test_what_is_left_alone(self):
        LeadAiSettings.objects.filter(pk=1).update(greet_enabled=False)
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "greet off"})
        LeadAiSettings.objects.filter(pk=1).update(greet_enabled=True, greet_template="")
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "no greet template"})
        LeadAiSettings.objects.filter(pk=1).update(greet_template="ic_shops")
        for extra, why in (
            ({"STATUS_ID": "IN_PROCESS"}, "not a new lead (IN_PROCESS)"),
            ({"SOURCE_ID": "OTHER"}, "not a portal lead (OTHER)"),  # the inbox's "Create lead", a hand-made or a test lead
            ({"DATE_CREATE": (NOW - dt.timedelta(days=3)).isoformat()}, "too old"),
            ({"PHONE": []}, "no phone"),
            ({"UF_CRM_A7_BOT_STATUS": 2479}, "broker"),
            ({"UF_CRM_A7_WA_OPT_OUT": 2482}, "opted out"),
        ):
            with self.subTest(why=why):
                self.rows[900] = lead_row(**extra)
                self.assertEqual(newlead.greet(900, now=NOW), {"skipped": why})
        self.rows[900] = lead_row()
        self.assertEqual(newlead.greet(901, now=NOW), {"skipped": "lead not read"})
        LeadAiSettings.objects.filter(pk=1).update(greet_template="no_such_template")
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "no approved template on the greet number"})
        # The agent must be able to send from the greet number; the template carries no media and two variables at most.
        LeadAiSettings.objects.filter(pk=1).update(greet_template="ic_shops", greet_agent=self.agent)
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "greet number not the greet agent's"})
        LeadAiSettings.objects.filter(pk=1).update(greet_agent=self.admin)
        WaTemplate.objects.create(
            waba_business_id="waba1", name="with_image", language="en", category="MARKETING", status=WaTemplate.Status.APPROVED,
            components=[{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Hi {{1}}"}],
        )
        LeadAiSettings.objects.filter(pk=1).update(greet_template="with_image")
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "greet template has a media header"})
        WaTemplate.objects.create(
            waba_business_id="waba1", name="three_vars", language="en", category="MARKETING", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "Hi {{1}}, {{2}} and {{3}}"}],
        )
        LeadAiSettings.objects.filter(pk=1).update(greet_template="three_vars")
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "greet template needs more than {{1}} and {{2}}"})
        self.assertEqual(Campaign.objects.count(), 1)
        self.run.assert_not_called()

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/x/")
    def test_a_customer_talking_to_us_or_greeted_today_is_left_alone(self):
        from apps.inbox.models import Contact, Conversation

        contact = Contact.objects.create(wa_id="971509998888", display_name="Ahmed")
        chat = Conversation.objects.create(number=self.number, contact=contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=20))
        Conversation.objects.filter(pk=chat.pk).update(last_inbound_at=NOW - dt.timedelta(hours=1))
        self.assertEqual(newlead.greet(900, now=NOW), {"skipped": "talking to us already"})
        chat.delete()
        contact.delete()
        self.assertTrue(newlead.greet(900, now=NOW).get("sent"))
        # A second enquiry from the same phone a minute later makes a second lead: one greet.
        self.rows[902] = lead_row(ID="902", COMMENTS="Listing ID: ABCDEFGHIJKLMNOPQRST12")
        self.assertEqual(newlead.greet(902, now=NOW + dt.timedelta(minutes=1)), {"skipped": "greeted this phone today"})
        self.assertEqual(Campaign.objects.count(), 2)

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/x/")
    def test_the_english_template_is_preferred(self):
        WaTemplate.objects.create(
            waba_business_id="waba1", name="portal_enquiry_reply", language="en", category="UTILITY", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "Hi {{1}}, about {{2}}."}],
        )
        WaTemplate.objects.create(
            waba_business_id="waba1", name="portal_enquiry_reply", language="ar", category="UTILITY", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "مرحبا {{1}}، بخصوص {{2}}."}],
        )
        LeadAiSettings.objects.filter(pk=1).update(greet_template="portal_enquiry_reply")
        result = newlead.greet(900, now=NOW)
        self.assertEqual(Campaign.objects.get(pk=result["campaign_id"]).template.language, "en")


@override_settings(**TEST_SETTINGS)
class EndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.http = Client(enforce_csrf_checks=True)
        patcher = patch("apps.leadai.tasks.greet_new_lead.apply_async")
        self.queued = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, body, *, secret=SECRET, ts=None, prefix=b"leadai-newlead."):
        raw = body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
        ts = str(int(time.time()) if ts is None else ts)
        sign = hmac.new(secret.encode(), prefix + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
        return self.http.post(URL, data=raw, content_type="application/json", HTTP_X_A7_SIGNATURE=sign, HTTP_X_A7_TS=ts)

    def test_the_contract_and_the_greet_queued_once(self):
        body = {"event": "add", "id": 900, "ts": int(time.time())}
        self.assertEqual(self.http.get(URL).status_code, 405)
        self.assertEqual(self.http.post(URL, data=json.dumps(body), content_type="application/json").status_code, 401)
        self.assertEqual(self.post(body, prefix=b"leadai-inventory.").status_code, 401)
        self.assertEqual(self.post(body, ts=int(time.time()) - 400).status_code, 401)
        self.assertEqual(self.post({"event": "add", "id": 0}).status_code, 400)
        self.assertEqual(self.post(b"[" * 16000).status_code, 400)
        self.queued.assert_not_called()
        response = self.post(body)
        self.assertEqual((response.status_code, response.json()), (200, {"ok": True, "queued": True, "id": 900}))
        self.queued.assert_called_once_with(args=[900], countdown=60)
        self.assertEqual(self.post(body).json()["queued"], False)  # the handler repeated itself: one greet
        self.assertEqual(self.queued.call_count, 1)


class FirstTurnTests(RentBase):
    def test_the_enquired_listing_leads_the_inventory_block_and_says_when_it_went(self):
        LeadAiUnit.objects.create(source="pf", source_id=LISTING_ID, reference="a7group-1789", community="International City", sub_area="Spain Cluster", unit="studio", bedrooms="studio", deal="rent", price=31000, active=False)
        LeadAiUnit.objects.create(source="pf", source_id="live1", reference="a7group-1800", community="International City", sub_area="France Cluster", unit="studio", bedrooms="studio", deal="rent", price=29000)
        self.rent(clusters=["Spain"])
        self.set_state(lead_context={"source": "Property Finder", "listing_id": LISTING_ID, "unit": "studio", "deal": "rent"}, lead_context_at=NOW)
        self.turn(self.inbound("Is the studio I enquired about still available?"), [res_answer("That studio in Spain Cluster is no longer listed; a similar one in France Cluster is AED 29,000 a year.")])
        context = self.requests[0][0][1]["content"]
        self.assertIn("a7group-1789", context)
        self.assertIn("(the listing they enquired about; no longer listed, offer the others)", context)
        self.assertLess(context.index("a7group-1789"), context.index("a7group-1800"))
        # The gone listing is never quoted as available by code's own line, nor its photos sent.
        body = self.outbound()[-1].body
        self.assertNotIn("(ref a7group-1789)", body)
        self.assertNotIn("still available", body.split("a7group-1800")[0] if "a7group-1800" in body else body)

    def test_a_price_question_on_a_gone_listing_quotes_a_live_one_or_nothing(self):
        LeadAiUnit.objects.create(source="pf", source_id=LISTING_ID, reference="a7group-1789", community="International City", sub_area="Spain Cluster", unit="studio", bedrooms="studio", deal="rent", price=31000, active=False)
        self.rent(clusters=["Spain"])
        self.set_state(lead_context={"source": "Property Finder", "listing_id": LISTING_ID, "unit": "studio", "deal": "rent"}, lead_context_at=NOW)
        self.turn(self.inbound("How much is it?"), [res_answer("That studio is no longer listed. Would you like similar studios in Spain Cluster?")])
        body = self.outbound()[-1].body
        self.assertNotIn("a7group-1789", body)
        self.assertNotIn("still available", body)
