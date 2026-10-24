"""Lead AI Campaigns history API (Tools → Campaigns): list/detail for Lead AI campaigns only."""

import datetime as dt

from django.utils import timezone

from apps.campaigns.models import CampaignRecipient, CrmTarget
from apps.campaigns.services import create_campaign
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import lane
from apps.leadai.tests.test_desk import DeskBase


class CampaignHistoryApiTests(DeskBase):
    def setUp(self):
        super().setUp()
        # A second Lead AI campaign by another agent so list is not creator-scoped.
        self.other_campaign = create_campaign(
            agent=self.desker,
            number=self.number,
            template=self.mixed_template,
            recipients=[{"phone": "971509888888", "name": "Sara", "variables": {"1": "Sara"}}],
            name="CRM Leads · Lead AI · intl_city_property_reconnect",
            variables={},
            crm_target=CrmTarget.NONE,
        )
        lane.mark_campaign(self.other_campaign, playbook=lane.IC_SHOPS)
        # Official (non–Lead AI) campaign must stay out of the list.
        self.official = create_campaign(
            agent=self.owner,
            number=self.number,
            template=self.shops_template,
            recipients=[{"phone": "971509777777", "name": "X", "variables": {"1": "X"}}],
            name="Official only",
            variables={},
            crm_target=CrmTarget.NONE,
        )

    def test_list_is_lead_ai_only_and_all_creators(self):
        self.client.force_login(self.desker)
        response = self.client.get("/api/leadai/campaigns/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        ids = [row["id"] for row in body["results"]]
        self.assertIn(self.shops_campaign.pk, ids)
        self.assertIn(self.other_campaign.pk, ids)
        self.assertNotIn(self.official.pk, ids)
        self.assertGreaterEqual(body["count"], 2)
        newest = body["results"][0]
        self.assertIn("delivered", newest)
        self.assertIn("read", newest)
        self.assertIn("playbook", newest)
        self.assertEqual(newest["id"], self.other_campaign.pk)

    def test_plain_agent_gets_403(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get("/api/leadai/campaigns/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/leadai/campaigns/{self.shops_campaign.pk}/").status_code, 403)

    def test_detail_404_for_non_lead_ai(self):
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get(f"/api/leadai/campaigns/{self.official.pk}/").status_code, 404)

    def test_delivered_and_read_from_matched_message(self):
        now = timezone.now()
        contact = Contact.objects.create(wa_id="971501234567", profile_name="Ali")
        conversation = Conversation.objects.create(number=self.number, contact=contact, assigned_agent=self.owner)
        recipient = self.other_campaign.recipients.get()
        CampaignRecipient.objects.filter(pk=recipient.pk).update(
            status=CampaignRecipient.Status.SENT,
            conversation=conversation,
            sent_at=now,
        )
        Message.objects.create(
            conversation=conversation,
            direction=Message.Direction.OUTBOUND,
            kind=Message.Kind.TEMPLATE,
            template=self.mixed_template,
            status=Message.Status.READ,
            body="Hi",
            created_at=now - dt.timedelta(seconds=2),
            delivered_at=now,
            read_at=now,
        )

        self.client.force_login(self.desker)
        detail = self.client.get(f"/api/leadai/campaigns/{self.other_campaign.pk}/").json()
        self.assertEqual(detail["sent"], 1)
        self.assertEqual(detail["delivered"], 1)
        self.assertEqual(detail["read"], 1)
        self.assertEqual(detail["playbook"], lane.IC_SHOPS)
        self.assertEqual(detail["template_name"], self.mixed_template.name)

    def test_admin_without_lead_ai_flag_may_still_read(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/leadai/campaigns/").status_code, 200)
