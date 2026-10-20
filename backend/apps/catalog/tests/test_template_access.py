"""Which business accounts an agent may write templates for (views._covered_waba_ids): the numbers whose chats they may
open, and, with Lead AI access, the accounts of the numbers that carry an active Lead AI chat — the desk opens every
Lead AI chat on any number, and its Send-template dialog's New template writes for that chat's account (Matloob
2026-10-20: a Lead AI agent got "That WhatsApp Business account is not one of yours")."""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Agent
from apps.catalog import views
from apps.catalog.models import WabaNumber, WaTemplate
from apps.inbox.models import Contact, Conversation
from apps.leadai.models import LeadAiChat


class LeadAiDeskTemplateAccessTests(TestCase):
    def setUp(self):
        self.desk = Agent.objects.create_user(username="desk", password="x", bitrix_user_id="454", can_official_api=True, can_lead_ai=True)
        self.plain = Agent.objects.create_user(username="plain", password="x", bitrix_user_id="455", can_official_api=True)
        self.lead_ai_number = WabaNumber.objects.create(phone_number="971581058726", phone_number_id="pn-la", waba_business_id="waba-leadai", is_active=True)
        self.other_number = WabaNumber.objects.create(phone_number="971500000009", phone_number_id="pn-o", waba_business_id="waba-other", is_active=True)
        contact = Contact.objects.create(wa_id="971528157350", display_name="Customer")
        conversation = Conversation.objects.create(number=self.lead_ai_number, contact=contact, session_expires_at=timezone.now())
        LeadAiChat.objects.create(conversation=conversation, active=True)

    def test_a_desk_agent_covers_the_lead_ai_chats_accounts_and_no_other(self):
        self.assertEqual(views._covered_waba_ids(self.desk), {"waba-leadai"})
        self.assertEqual(views._covered_waba_ids(self.plain), set())
        # The chat moved back to the inbox: the account goes with it.
        LeadAiChat.objects.update(active=False)
        self.assertEqual(views._covered_waba_ids(self.desk), set())

    def test_create_on_the_lead_ai_chats_account_is_allowed_and_another_refused(self):
        self.client.force_login(self.desk)
        template = WaTemplate.objects.create(waba_business_id="waba-leadai", name="visit_reminder", language="en", category="UTILITY", components=[])
        body = {"name": "visit_reminder", "category": "UTILITY", "language": "en", "body_text": "Hello, have you done with the meeting?", "waba_business_id": "waba-leadai"}
        with patch.object(views, "_submit_template_to_waba", return_value=(template, "", [])) as submit:
            response = self.client.post("/api/catalog/templates/create/", body, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(submit.call_args.args[0], "waba-leadai")
        with patch.object(views, "_submit_template_to_waba") as submit:
            response = self.client.post("/api/catalog/templates/create/", {**body, "waba_business_id": "waba-other"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        submit.assert_not_called()
        # No Lead AI access: the same request is refused on the Lead AI chat's account too.
        self.client.force_login(self.plain)
        with patch.object(views, "_submit_template_to_waba") as submit:
            response = self.client.post("/api/catalog/templates/create/", body, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        submit.assert_not_called()
