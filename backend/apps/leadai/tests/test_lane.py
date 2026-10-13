"""Lead AI screen: which chats it holds, and that the main inbox never shows them."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Agent
from apps.campaigns.crm_leads import send_from_leads
from apps.campaigns.models import Campaign, CampaignRecipient, CrmTarget
from apps.campaigns.services import create_campaign, process_recipient
from apps.catalog.models import NumberAssignment, WabaNumber, WaTemplate
from apps.inbox.models import Contact, Conversation
from apps.leadai import lane
from apps.leadai.models import LeadAiCampaign, LeadAiChat

SECRET = "test-crm-secret"


def template_on(waba, name="villa_offer"):
    return WaTemplate.objects.create(
        waba_business_id=waba,
        name=name,
        language="en",
        category="UTILITY",
        status=WaTemplate.Status.APPROVED,
        components=[{"type": "BODY", "text": "Hello {{1}}"}],
    )


class LeadAiBase(TestCase):
    def setUp(self):
        self.admin = Agent.objects.create_user(
            username="admin", password="x", bitrix_user_id="1", can_official_api=True, is_wa_admin=True
        )
        self.agent = Agent.objects.create_user(
            username="agent", password="x", bitrix_user_id="77", can_official_api=True
        )
        self.number = WabaNumber.objects.create(
            phone_number="971500000001", phone_number_id="pn1", waba_business_id="waba1"
        )
        self.other_number = WabaNumber.objects.create(
            phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba2"
        )
        NumberAssignment.objects.create(number=self.number, agent=self.agent)
        self.template = template_on("waba1")

    def conversation(self, phone="971501234567", number=None, agent=None, with_history=True):
        contact, _ = Contact.objects.get_or_create(wa_id=phone)
        conversation = Conversation.objects.create(
            number=number or self.number, contact=contact, assigned_agent=agent or self.agent
        )
        if with_history:
            Conversation.objects.filter(pk=conversation.pk).update(
                last_message_at="2026-10-01T10:00:00Z", last_message_preview="Hi"
            )
            conversation.refresh_from_db()
        return conversation

    def campaign(self, phones=("971501234567",), lead_ai=True, number=None):
        campaign = create_campaign(
            agent=self.agent,
            number=number or self.number,
            template=self.template,
            recipients=[{"phone": p, "name": "Ali", "variables": {"1": "Ali"}, "crm_lead_id": 5} for p in phones],
            name="CRM Leads · test",
            variables={},
            crm_target=CrmTarget.NONE,
        )
        if lead_ai:
            lane.mark_campaign(campaign)
        return campaign


class ListTests(LeadAiBase):
    def test_the_main_inbox_list_leaves_lead_ai_chats_out(self):
        shown = self.conversation("971501111111")
        hidden = self.conversation("971502222222")
        LeadAiChat.objects.create(conversation=hidden, active=True)
        self.client.force_login(self.agent)
        ids = [row["id"] for row in self.client.get("/api/inbox/conversations/").json()["results"]]
        self.assertIn(shown.pk, ids)
        self.assertNotIn(hidden.pk, ids)

    def test_a_moved_chat_is_back_in_the_main_inbox(self):
        moved = self.conversation()
        LeadAiChat.objects.create(conversation=moved, active=False)
        self.client.force_login(self.agent)
        ids = [row["id"] for row in self.client.get("/api/inbox/conversations/").json()["results"]]
        self.assertIn(moved.pk, ids)

    def test_the_lead_ai_list_holds_only_lead_ai_chats_the_agent_may_open(self):
        mine = self.conversation("971501111111")
        other = self.conversation("971502222222", number=self.other_number, agent=self.admin)
        normal = self.conversation("971503333333")
        LeadAiChat.objects.create(conversation=mine, active=True, crm_entity="lead", crm_id=5)
        LeadAiChat.objects.create(conversation=other, active=True)
        self.client.force_login(self.agent)
        body = self.client.get("/api/leadai/chats/").json()
        self.assertEqual([row["id"] for row in body["results"]], [mine.pk])
        self.assertEqual(body["results"][0]["lead_ai_info"]["crm_entity"], "lead")
        self.assertTrue(body["results"][0]["lead_ai"])
        self.assertNotIn(normal.pk, [row["id"] for row in body["results"]])
        self.client.force_login(self.admin)
        admin_ids = {row["id"] for row in self.client.get("/api/leadai/chats/").json()["results"]}
        self.assertEqual(admin_ids, {mine.pk, other.pk})

    def test_lead_ai_search_matches_the_phone(self):
        chat = self.conversation("971504444444")
        LeadAiChat.objects.create(conversation=chat, active=True)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get("/api/leadai/chats/?q=4444444").json()["count"], 1)
        self.assertEqual(self.client.get("/api/leadai/chats/?q=999999").json()["count"], 0)

    def test_messages_of_a_lead_ai_chat_still_open_through_the_inbox_api(self):
        chat = self.conversation()
        LeadAiChat.objects.create(conversation=chat, active=True)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(f"/api/inbox/conversations/{chat.pk}/messages/").status_code, 200)


class MoveTests(LeadAiBase):
    def test_move_to_inbox_tells_the_main_inbox_it_is_back(self):
        chat = self.conversation()
        LeadAiChat.objects.create(conversation=chat, active=True)
        self.client.force_login(self.agent)
        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append(message)

        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f"/api/leadai/chats/{chat.pk}/move-to-inbox/")
        self.assertEqual(response.status_code, 200)
        row = LeadAiChat.objects.get(conversation=chat)
        self.assertFalse(row.active)
        self.assertEqual(row.moved_by, self.agent)
        # A plain event whose payload says lead_ai False: the main inbox lists it again.
        self.assertTrue(sent)
        self.assertTrue(all(m["event"] == "conversation.updated" for m in sent))
        self.assertTrue(all(m["data"]["conversation"]["lead_ai"] is False for m in sent))
        again = self.client.post(f"/api/leadai/chats/{chat.pk}/move-to-inbox/")
        self.assertEqual(again.status_code, 409)

    def test_an_agent_cannot_move_a_chat_they_cannot_open(self):
        theirs = self.conversation("971505555555", number=self.other_number, agent=self.admin)
        LeadAiChat.objects.create(conversation=theirs, active=True)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{theirs.pk}/move-to-inbox/").status_code, 404)
        self.assertTrue(LeadAiChat.objects.get(conversation=theirs).active)


class EventTests(LeadAiBase):
    def test_live_events_of_a_lead_ai_chat_carry_the_prefix(self):
        normal = self.conversation("971501111111")
        special = self.conversation("971502222222")
        LeadAiChat.objects.create(conversation=special, active=True)
        self.assertEqual(lane.event_name(normal, "message.new"), "message.new")
        self.assertEqual(lane.event_name(special, "message.new"), "leadai.message.new")
        self.assertEqual(lane.event_name(special, "leadai.message.new"), "leadai.message.new")

    def test_publish_sends_the_prefixed_event(self):
        from apps.inbox import events

        special = self.conversation()
        LeadAiChat.objects.create(conversation=special, active=True)
        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append((group, message["event"]))

        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            events.publish(special, "conversation.updated", {})
        self.assertTrue(sent)
        self.assertTrue(all(event == "leadai.conversation.updated" for _group, event in sent))


class CampaignSendTests(LeadAiBase):
    def recipient(self, campaign):
        return campaign.recipients.order_by("id").first()

    def test_a_new_customer_is_marked_before_the_first_message_goes_out(self):
        campaign = self.campaign()
        seen = {}

        def fake_send(conversation, *args, **kwargs):
            seen["lead_ai_at_send"] = lane.is_lead_ai(conversation)
            seen["event"] = lane.event_name(conversation, "message.new")

        with patch("apps.inbox.services.send_template", side_effect=fake_send):
            process_recipient(self.recipient(campaign).pk)
        self.assertTrue(seen["lead_ai_at_send"])
        self.assertEqual(seen["event"], "leadai.message.new")
        recipient = self.recipient(campaign)
        self.assertEqual(recipient.status, CampaignRecipient.Status.SENT)
        chat = LeadAiChat.objects.get(conversation=recipient.conversation)
        self.assertTrue(chat.active)
        self.assertTrue(chat.confirmed)
        self.assertEqual((chat.crm_entity, chat.crm_id), ("lead", 5))

    def test_an_existing_chat_on_the_same_number_moves_with_its_history(self):
        existing = self.conversation("971501234567")
        campaign = self.campaign()
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(campaign).pk)
        self.assertEqual(Conversation.objects.filter(contact__wa_id="971501234567").count(), 1)
        self.assertTrue(LeadAiChat.objects.get(conversation=existing).active)

    def test_the_same_customer_on_another_number_stays_where_it_is(self):
        elsewhere = self.conversation("971501234567", number=self.other_number, agent=self.admin)
        campaign = self.campaign()
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(campaign).pk)
        self.assertFalse(LeadAiChat.objects.filter(conversation=elsewhere).exists())
        self.assertTrue(
            LeadAiChat.objects.filter(
                conversation__number=self.number, conversation__contact__wa_id="971501234567", active=True
            ).exists()
        )

    def test_a_chat_moved_to_the_inbox_comes_back_with_a_new_lead_ai_campaign(self):
        existing = self.conversation("971501234567")
        LeadAiChat.objects.create(conversation=existing, active=False, confirmed=True)
        campaign = self.campaign()
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(campaign).pk)
        chat = LeadAiChat.objects.get(conversation=existing)
        self.assertTrue(chat.active)
        self.assertEqual(chat.campaign_id, campaign.pk)

    def test_a_retry_of_the_same_campaign_does_not_undo_a_manual_move(self):
        existing = self.conversation("971501234567")
        campaign = self.campaign()
        LeadAiChat.objects.create(
            conversation=existing, active=False, confirmed=True, campaign=campaign,
            moved_by=self.agent, moved_at=timezone.now(),
        )
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(campaign).pk)
        self.assertFalse(LeadAiChat.objects.get(conversation=existing).active)
        # A different Lead AI campaign does bring it back.
        other = self.campaign()
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(other).pk)
        chat = LeadAiChat.objects.get(conversation=existing)
        self.assertTrue(chat.active)
        self.assertEqual(chat.campaign_id, other.pk)

    def test_a_normal_campaign_leaves_chats_alone(self):
        existing = self.conversation("971501234567")
        campaign = self.campaign(lead_ai=False)
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(campaign).pk)
        self.assertFalse(LeadAiChat.objects.filter(conversation=existing).exists())

    def test_a_normal_campaign_does_not_pull_a_lead_ai_chat_back(self):
        existing = self.conversation("971501234567")
        LeadAiChat.objects.create(conversation=existing, active=True, confirmed=True)
        campaign = self.campaign(lead_ai=False)
        with patch("apps.inbox.services.send_template"):
            process_recipient(self.recipient(campaign).pk)
        self.assertTrue(LeadAiChat.objects.get(conversation=existing).active)

    def test_a_send_that_fails_for_good_leaves_an_existing_chat_in_the_inbox(self):
        from apps.inbox.services import SendBlocked

        existing = self.conversation("971501234567")
        campaign = self.campaign()
        with patch(
            "apps.inbox.services.send_template",
            side_effect=SendBlocked("(#131026) Message undeliverable"),
        ):
            process_recipient(self.recipient(campaign).pk)
        recipient = self.recipient(campaign)
        self.assertEqual(recipient.status, CampaignRecipient.Status.EXHAUSTED)
        self.assertFalse(LeadAiChat.objects.filter(conversation=existing, active=True).exists())

    def test_a_failed_send_leaves_no_ghost_chat_and_a_retry_marks_it(self):
        from apps.gateway.client import AlotsError

        campaign = self.campaign()
        with patch("apps.inbox.services.send_template", side_effect=AlotsError("Gateway timeout", status_code=503)):
            process_recipient(self.recipient(campaign).pk)
        recipient = self.recipient(campaign)
        self.assertEqual(recipient.status, CampaignRecipient.Status.FAILED)
        # Rolled back with the send, exactly as a failed start_conversation always was.
        self.assertFalse(Conversation.objects.filter(contact__wa_id="971501234567").exists())
        self.assertFalse(LeadAiChat.objects.exists())

        CampaignRecipient.objects.filter(pk=recipient.pk).update(status=CampaignRecipient.Status.PENDING)
        with patch("apps.inbox.services.send_template"):
            process_recipient(recipient.pk)
        chat = LeadAiChat.objects.get(conversation__contact__wa_id="971501234567")
        self.assertTrue(chat.active)
        self.assertTrue(chat.confirmed)

    def test_send_from_leads_marks_the_campaign_only_when_asked(self):
        with patch("apps.campaigns.crm_leads.run_campaign"):
            plain = send_from_leads(
                agent=self.agent, template_id=self.template.pk, number_id=self.number.pk,
                leads=[{"id": 5, "phone": "971501234567", "name": "Ali"}],
            )
            special = send_from_leads(
                agent=self.agent, template_id=self.template.pk, number_id=self.number.pk,
                leads=[{"id": 6, "phone": "971507654321", "name": "Sara"}], lead_ai=True,
            )
        self.assertFalse(LeadAiCampaign.objects.filter(campaign_id=plain["campaign_id"]).exists())
        self.assertTrue(LeadAiCampaign.objects.filter(campaign_id=special["campaign_id"]).exists())
        self.assertIn("Lead AI", Campaign.objects.get(pk=special["campaign_id"]).name)
        self.assertTrue(special["lead_ai"])

    @override_settings(CRM_LEAD_WA_SECRET=SECRET)
    def test_the_crm_send_route_reads_the_box(self):
        body = json.dumps(
            {
                "bitrix_user_id": "77",
                "entity": "lead",
                "template_id": self.template.pk,
                "number_id": self.number.pk,
                "leads": [{"id": 5, "phone": "971501234567", "name": "Ali"}],
                "lead_ai": True,
            }
        ).encode()
        stamp = str(int(time.time()))
        sig = hmac.new(SECRET.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
        with patch("apps.campaigns.crm_leads.run_campaign"):
            response = self.client.post(
                "/api/campaigns/crm-leads/send/", data=body, content_type="application/json",
                HTTP_X_CRM_TS=stamp, HTTP_X_CRM_SIGN=sig,
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(LeadAiCampaign.objects.filter(campaign_id=response.json()["campaign_id"]).exists())

    def test_a_retry_of_a_lead_ai_campaign_stays_lead_ai(self):
        source = self.campaign()
        target = self.campaign(phones=("971509999999",), lead_ai=False)
        lane.inherit_campaign(source, target)
        self.assertTrue(lane.is_lead_ai_campaign(target))


class PayloadTests(LeadAiBase):
    def test_every_conversation_payload_says_whether_it_is_lead_ai(self):
        from apps.inbox.serializers import serialize_conversation

        normal = self.conversation("971501111111")
        special = self.conversation("971502222222")
        LeadAiChat.objects.create(conversation=special, active=True)
        self.assertFalse(serialize_conversation(normal)["lead_ai"])
        self.assertTrue(serialize_conversation(Conversation.objects.get(pk=special.pk))["lead_ai"])
        LeadAiChat.objects.filter(conversation=special).update(active=False)
        self.assertFalse(serialize_conversation(Conversation.objects.get(pk=special.pk))["lead_ai"])

    def test_the_closing_window_warning_of_a_lead_ai_chat_goes_to_lead_ai(self):
        from apps.inbox import tasks

        special = self.conversation("971502222222")
        Conversation.objects.filter(pk=special.pk).update(
            session_expires_at=timezone.now() + timezone.timedelta(minutes=30)
        )
        LeadAiChat.objects.create(conversation=special, active=True)
        with patch("apps.inbox.tasks.publish_to_agent") as push:
            tasks.warn_closing_windows()
        events = [call.args[1] for call in push.call_args_list]
        self.assertEqual(events, ["leadai.session.closing"])


class NoAutoReplyTests(LeadAiBase):
    def test_sara_stays_silent_on_a_lead_ai_chat(self):
        from apps.inbox.models import Message
        from apps.leadbot.models import LeadAutomation
        from apps.leadbot.tasks import reply_to_inbound

        chat = self.conversation()
        Conversation.objects.filter(pk=chat.pk).update(session_expires_at="2099-01-01T00:00:00Z")
        LeadAutomation.objects.create(
            bitrix_lead_id=5, conversation=chat, agent=self.agent, state=LeadAutomation.State.ACTIVE
        )
        LeadAiChat.objects.create(conversation=chat, active=True)
        with patch("apps.leadai.signals.recipient_saved"):
            inbound = Message.objects.create(
                conversation=chat, direction=Message.Direction.INBOUND, kind="text", body="Hi"
            )
        with patch("apps.leadbot.tasks.draft") as draft:
            reply_to_inbound(inbound.pk)
        draft.assert_not_called()
