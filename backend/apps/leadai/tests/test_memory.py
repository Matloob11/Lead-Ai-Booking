"""The customer memory (assistant/memory.py): one customer across chats and numbers — remembered after a turn, recalled
as PREVIOUS CHATS lines in the next chat's context, confirmed as a question, gone with a PDPL deletion."""

import datetime as dt

from django.test import TestCase

from apps.catalog.models import WabaNumber
from apps.inbox.models import Conversation
from apps.leadai.assistant import memory
from apps.leadai.models import LeadAiChat, LeadAiCustomer
from apps.leadai.tests.test_assistant import NOW, Base, answer

JULY = dt.datetime(2026, 7, 14, 10, 0, tzinfo=dt.timezone.utc)


class RememberRecallTests(Base):
    def test_a_chat_is_remembered_by_the_phone_and_recalled_for_another_conversation(self):
        row = memory.remember(self.conversation, {"unit": "studio", "clusters": ["Spain"], "intent": "rent", "budget_aed": 30000, "cheque_count": "4"}, "en", JULY)
        self.assertEqual(row.phone, "971501234567")
        self.assertEqual(row.facts, {"unit": "studio", "clusters": ["Spain"], "intent": "rent", "budget_aed": 30000})
        self.assertEqual(len(row.chats), 1)
        self.assertEqual(row.chats[0]["number"], "0001")
        memory.remember(self.conversation, {"move_in": "next month"}, "en", JULY + dt.timedelta(hours=1), booking={"event": "confirmed", "starts_at": "2026-07-15T17:00:00+04:00"})
        row.refresh_from_db()
        self.assertEqual(len(row.chats), 1)
        self.assertEqual(row.chats[0]["bookings"][0]["event"], "confirmed")
        self.assertEqual(row.chats[0]["facts"]["move_in"], "next month")
        # The same conversation sees nothing of itself; another conversation of this customer sees the lines.
        self.assertEqual(memory.recall("971501234567", exclude_conversation=self.conversation.pk), [])
        lines = memory.lines(memory.recall("971501234567", exclude_conversation=999))
        self.assertEqual(lines[0], memory.BLOCK_HEAD)
        self.assertEqual(lines[1], "- July 2026 (our number ending 0001): asked about studio; in Spain; to rent; budget AED 30,000; moving next month; booked a visit for 15 Jul 2026")
        self.assertEqual(memory.recall("", exclude_conversation=None), [])
        self.assertEqual(memory.lines([]), [])

    def test_nothing_worth_keeping_writes_nothing(self):
        self.assertIsNone(memory.remember(self.conversation, {"cheque_count": "4"}, "en", NOW))
        self.assertFalse(LeadAiCustomer.objects.exists())

    def test_forget_removes_the_row(self):
        memory.remember(self.conversation, {"unit": "studio"}, "en", NOW)
        self.assertEqual(memory.forget("+971 50 123 4567"), 1)
        self.assertFalse(LeadAiCustomer.objects.exists())


class InTheTurnTests(Base):
    def test_a_turn_remembers_and_the_next_chat_on_another_number_reads_it(self):
        message = self.inbound("I want a studio in Spain cluster to rent")
        self.turn(message, [answer("Great. Are you looking for yourself or for a client?", segment="residential_tenant", facts={"property_type": "studio", "clusters": ["Spain"], "intent": "rent"})])
        row = LeadAiCustomer.objects.get(phone="971501234567")
        self.assertEqual(row.chats[0]["conversation"], self.conversation.pk)
        # The same customer on another of our numbers: a new conversation, a new Lead AI chat, and the memory in its context.
        other_number = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba2")
        second = Conversation.objects.create(number=other_number, contact=self.contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=20))
        LeadAiChat.objects.create(conversation=second, active=True, crm_entity="lead", crm_id=556)
        self.conversation = second
        message = self.inbound("Hi, do you have studios?")
        outcome, calls, _, _ = self.turn(message, [answer("Welcome back! Still Spain Cluster, or another one?", segment="residential_tenant")])
        context = calls[0][1]["content"]
        self.assertIn(memory.BLOCK_HEAD, context)
        self.assertIn("asked about studio; to rent", context)  # the shops schema keeps no clusters fact; the rest is remembered
        self.assertIn("our number ending 0001", context)

    def test_the_chat_api_lists_the_customers_earlier_chats(self):
        other_number = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba2")
        second = Conversation.objects.create(number=other_number, contact=self.contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=20))
        memory.remember(second, {"unit": "one_br", "intent": "rent"}, "en", JULY)
        self.client.force_login(self.agent)
        data = self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()
        self.assertEqual(data["lead_ai_ai"]["memory"], ["- July 2026 (our number ending 0002): asked about one_br; to rent"])
