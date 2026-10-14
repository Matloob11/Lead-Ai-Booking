"""Batch 2b: the global WhatsApp opt-out registry (board T60, owner's choice Q8: a phone that
asked us to stop is blocked on every number and every campaign).

- the registry itself (optout.py) and the campaigns' own hook that reads it
  (campaigns.crm_leads.phones_blocked_by_registry, used read-only here);
- who writes it: a Lead AI stop, spam or wrong number in every playbook, an inbound
  STOP or Unsubscribe / Stop / Stop messages / Stop promotions anywhere in the inbox;
- the back-fill command and the Django admin (list and delete, nothing else).
"""

import datetime as dt
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.models import Agent
from apps.campaigns import crm_leads
from apps.campaigns.models import Campaign
from apps.catalog.models import WabaNumber
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import lane, optout
from apps.leadai.assistant import engine, rules
from apps.leadai.models import LeadAiChat, LeadAiChatState, LeadAiOptOut, LeadAiSettings
from apps.leadai.tests.test_assistant import NOW, Base


class RegistryTests(TestCase):
    def test_a_phone_is_kept_as_whatsapp_ids_are(self):
        cases = {
            "+971 50 123 4567": "971501234567",
            "0501234567": "971501234567",
            "501234567": "971501234567",
            "00971501234567": "971501234567",
            "447723356623": "447723356623",
            "123": "",
            "": "",
        }
        for raw, phone in cases.items():
            with self.subTest(raw):
                self.assertEqual(optout.canonical(raw), phone)

    def test_the_first_reason_stays_and_a_bad_phone_is_nobody(self):
        self.assertTrue(optout.record("+971 50 123 4567", reason="STOP <b>now</b>", source=optout.Source.INBOX_TAP))
        self.assertFalse(optout.record("0501234567", reason="Unsubscribe", source=optout.Source.BITRIX))
        row = LeadAiOptOut.objects.get()
        self.assertEqual((row.phone, row.source, row.reason), ("971501234567", "inbox_tap", "STOP ‹b›now‹/b›"))
        self.assertFalse(optout.record("12", reason="x"))
        self.assertTrue(optout.record("971509999999", source="made-up"))
        self.assertEqual(LeadAiOptOut.objects.get(phone="971509999999").source, "leadai_stop")
        self.assertTrue(optout.is_blocked("+971509999999"))
        self.assertFalse(optout.is_blocked("971500000000"))

    def test_the_campaigns_hook_finds_every_spelling_of_a_blocked_phone(self):
        optout.record("971501234567", reason="STOP")
        phones = {"+971 50 123 4567", "0501234567", "971509999999"}
        self.assertEqual(optout.phones_blocked(phones), {"971501234567", "0501234567"})
        # Exactly as Cursor's hook calls it, and what the campaign paths then leave out.
        self.assertEqual(crm_leads.phones_blocked_by_registry(phones), {"971501234567", "0501234567"})
        self.assertEqual(crm_leads.phones_opted_out(phones), {"971501234567"})
        kept, skipped = crm_leads.drop_opted_out_rows([{"phone": "0501234567"}, {"phone": "971509999999"}])
        self.assertEqual((kept, skipped), ([{"phone": "971509999999"}], [{"phone": "0501234567", "reason": "Opted out."}]))
        self.assertEqual(optout.phones_blocked(set()), set())
        self.assertEqual(optout.phones_blocked({"abc"}), set())

    def test_which_inbound_messages_are_an_opt_out(self):
        def message(kind, body="", payload=None, direction="in"):
            return Message(kind=kind, body=body, payload=payload or {}, direction=direction)

        cases = [
            (message("text", "STOP"), rules.STOP_ALL),
            (message("text", "please stop"), rules.STOP_ALL),
            (message("text", "Wrong number"), rules.WRONG_NUMBER),
            (message("text", "Not interested"), ""),  # declines one offer, never a stop
            (message("text", "stop sending 1BR, I need a 2BR"), ""),
            (message("button", "Unsubscribe", {"button": {"text": "Unsubscribe"}}), rules.STOP_ALL),
            (message("button", "Stop promotions", {"button": {"text": "Stop promotions"}}), rules.STOP_ALL),
            (message("button", "Stop messages", {"button": {"text": "Stop messages"}}), rules.STOP_ALL),
            (message("interactive", "Stop", {"interactive": {"button_reply": {"id": "x", "title": "Stop"}}}), rules.STOP_ALL),
            (message("button", "Not Interested", {"button": {"text": "Not Interested"}}), ""),
            (message("text", "STOP", direction="out"), ""),
            (message("image", "stop"), ""),
        ]
        for item, kind in cases:
            with self.subTest(item.kind, body=item.body, direction=item.direction):
                self.assertEqual(optout.message_opt_out(item), kind)


class InboxSignalTests(Base):
    """Any chat, any number: the receiver in apps.leadai, no inbox code changed."""

    def setUp(self):
        super().setUp()
        for target in ("apps.leadai.tasks.assistant_turn.apply_async", "apps.leadai.tasks.handle_reminder_tap.apply_async"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        number = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba2")
        self.inbox_chat = Conversation.objects.create(number=number, contact=Contact.objects.create(wa_id="971502223333"), session_expires_at=NOW + dt.timedelta(hours=5))

    def customer(self, conversation, body, kind="text", payload=None):
        with self.captureOnCommitCallbacks(execute=True):
            return Message.objects.create(conversation=conversation, direction="in", kind=kind, body=body, payload=payload or {}, status="received")

    def test_a_stop_or_an_unsubscribe_tap_in_the_inbox_blocks_the_phone(self):
        self.customer(self.inbox_chat, "Stop")
        row = LeadAiOptOut.objects.get()
        self.assertEqual((row.phone, row.source, row.reason, row.conversation_id), ("971502223333", "inbox_tap", "Stop", self.inbox_chat.pk))
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971504445555"))
        self.customer(other, "Unsubscribe", kind="button", payload={"button": {"text": "Unsubscribe"}})
        self.assertTrue(optout.is_blocked("971504445555"))
        wrong = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971506667777"))
        self.customer(wrong, "wrong number")
        self.assertEqual(LeadAiOptOut.objects.get(phone="971506667777").source, "wrong_number")

    def test_what_is_not_a_stop_changes_nothing(self):
        self.customer(self.inbox_chat, "Not interested")
        self.customer(self.inbox_chat, "Can you stop by tomorrow with the keys?")
        self.assertFalse(LeadAiOptOut.objects.exists())

    def test_a_lead_ai_chat_is_left_to_the_assistant(self):
        # Its turn knows a STOP from "الغاء" cancelling a booked meeting, and writes the registry itself.
        self.customer(self.conversation, "Stop")
        self.assertFalse(LeadAiOptOut.objects.exists())
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)  # moved back to the inbox
        self.customer(self.conversation, "STOP")
        self.assertTrue(optout.is_blocked(self.contact.wa_id))

    def test_storing_the_message_never_fails_for_the_registry(self):
        with patch("apps.leadai.optout.message_opt_out", side_effect=RuntimeError("boom")):
            message = self.customer(self.inbox_chat, "Stop")
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())


class AssistantWritesTests(Base):
    """Every playbook: a STOP, a wrong number or spam is blocked everywhere, not only in this chat."""

    def test_a_general_chats_stop_and_wrong_number(self):
        engine.record_opt_out(self.conversation, rules.STOP_ALL, by="rule", words="STOP")
        row = LeadAiOptOut.objects.get()
        self.assertEqual((row.phone, row.source, row.reason, row.conversation_id), ("971501234567", "leadai_stop", "STOP", self.conversation.pk))
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971508889999"))
        LeadAiChat.objects.create(conversation=other, active=True)
        engine.record_opt_out(other, rules.WRONG_NUMBER, by="model", words="wrong number")
        self.assertEqual(LeadAiOptOut.objects.get(phone="971508889999").source, "wrong_number")

    def test_not_interested_declines_one_offer_and_blocks_nothing(self):
        engine.record_opt_out(self.conversation, rules.NOT_INTERESTED, by="model", words="no thanks")
        self.assertFalse(LeadAiOptOut.objects.exists())

    def test_a_shops_spam_is_blocked_too(self):
        lane.mark_campaign(Campaign.objects.get(), playbook=lane.IC_SHOPS)
        with patch("apps.leadai.tasks.write_crm_fields.delay"), self.captureOnCommitCallbacks(execute=True):
            engine.record_opt_out(self.conversation, rules.SPAM, by="rule", words="Earn money daily", playbook=lane.IC_SHOPS)
        self.assertEqual(LeadAiOptOut.objects.get().source, "leadai_spam")

    def test_a_chat_stopped_already_still_reaches_the_registry(self):
        # Stopped for an automatic reply earlier (or a STOP from before the registry existed).
        LeadAiChatState.objects.create(conversation=self.conversation, stopped_at=NOW, stop_reason="auto_reply")
        self.assertFalse(engine.record_opt_out(self.conversation, rules.STOP_ALL, by="rule", words="STOP"))
        self.assertTrue(optout.is_blocked(self.contact.wa_id))

    def test_a_typed_stop_turn_writes_it_whatever_the_switch(self):
        LeadAiSettings.objects.filter(pk=1).update(assistant_enabled=False)
        message = self.inbound("STOP")
        with patch("apps.leadai.tasks.record_crm_note.delay"), self.captureOnCommitCallbacks(execute=True):
            engine.run_turn(message.pk, first_queued_at=(NOW - dt.timedelta(minutes=1)).isoformat())
        self.assertTrue(optout.is_blocked(self.contact.wa_id))


class ImportTests(Base):
    def new_chat(self, wa_id, *, lead_ai=False):
        conversation = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id=wa_id))
        if lead_ai:
            LeadAiChat.objects.create(conversation=conversation, active=True)
        return conversation

    def said(self, conversation, body, kind="text", payload=None):
        # Stored inside the test's transaction, so the inbox signal's after-commit write never runs:
        # these are the messages from before the registry existed.
        return Message.objects.create(conversation=conversation, direction="in", kind=kind, body=body, payload=payload or {}, status="received")

    def test_the_back_fill_uses_the_same_rules_and_counts_a_dry_run(self):
        self.said(self.new_chat("971501110001"), "STOP")
        self.said(self.new_chat("971501110002"), "Unsubscribe", kind="button", payload={"button": {"text": "Unsubscribe"}})
        self.said(self.new_chat("971501110003"), "Not interested")
        self.said(self.new_chat("971501110004"), "wrong number sorry")
        lead_ai = self.new_chat("971501110005", lead_ai=True)
        self.said(lead_ai, "stop")  # the assistant's chat: its own record counts, not the words
        LeadAiChatState.objects.create(conversation=lead_ai, stopped_at=NOW, stop_reason="stop_all")
        optout.record("971501110002", reason="already", source=optout.Source.BITRIX)
        out = StringIO()
        call_command("leadai_optout_import", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertIn("4 phone(s) asked us to stop; 1 already in the registry", text)
        self.assertIn("would add 3 phone(s); nothing stored", text)
        self.assertEqual(LeadAiOptOut.objects.count(), 1)
        out = StringIO()
        call_command("leadai_optout_import", stdout=out)
        self.assertIn("added 3 phone(s)", out.getvalue())
        rows = {row.phone: row for row in LeadAiOptOut.objects.all()}
        self.assertEqual(set(rows), {"971501110001", "971501110002", "971501110004", "971501110005"})
        self.assertEqual({rows[p].source for p in ("971501110001", "971501110004", "971501110005")}, {"import"})
        self.assertEqual(rows["971501110001"].reason, "Typed: STOP")
        self.assertEqual(rows["971501110005"].reason, "Lead AI: Customer asked us to stop")
        self.assertEqual(rows["971501110002"].source, "bitrix")  # never overwritten
        out = StringIO()
        call_command("leadai_optout_import", stdout=out)
        self.assertIn("added 0 phone(s)", out.getvalue())


class AdminTests(Base):
    def test_a_person_may_list_and_delete_a_row_and_nothing_else(self):
        staff = Agent.objects.create_user(username="boss", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        optout.record("971501234567", reason="STOP", source=optout.Source.INBOX_TAP)
        row = LeadAiOptOut.objects.get()
        listing = self.client.get("/admin/leadai/leadaioptout/")
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "971501234567")
        self.assertEqual(self.client.get("/admin/leadai/leadaioptout/add/").status_code, 403)
        with patch("apps.crmlink.client.call", side_effect=AssertionError("Bitrix written")):
            response = self.client.post(f"/admin/leadai/leadaioptout/{row.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LeadAiOptOut.objects.exists())
