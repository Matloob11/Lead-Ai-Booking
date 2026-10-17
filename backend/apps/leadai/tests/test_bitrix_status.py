"""Batch 2b: Bot Status (or WhatsApp Opt-out) set by a person in Bitrix reaches the assistant
(board T52, Cursor's C12 contract).

POST /api/leadai/bitrix/bot-status/, signed "leadai-botstatus." + ts + "." + body with
CRM_LEAD_WA_SECRET: 405 for any other method, 401 for a missing, wrong or old signature,
400 for a body that is not the contract, else 200 {"ok": true, "chats": N}. Its effects on
every active Lead AI chat of the lead; it never writes back to Bitrix.
"""

import datetime as dt
import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.test import Client

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.inbox.models import Contact, Conversation
from apps.leadai import bitrix_status, optout
from apps.leadai.assistant import engine
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiCrmField, LeadAiOptOut
from apps.leadai.tests.test_assistant import NOW, TEST_SETTINGS
from apps.leadai.tests.test_first_chat_fixes import FirstChatBase

URL = "/api/leadai/bitrix/bot-status/"
SECRET = TEST_SETTINGS["CRM_LEAD_WA_SECRET"]


def signed(body, *, secret=SECRET, ts=None, prefix=b"leadai-botstatus."):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    ts = str(int(time.time()) if ts is None else ts)
    sign = hmac.new(secret.encode(), prefix + ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"HTTP_X_LEADAI_TS": ts, "HTTP_X_LEADAI_SIGN": sign}


class BotStatusBase(FirstChatBase):
    """The chat of lead 555 (its campaign row and its LeadAiChat both say so); 2311 listed."""

    def setUp(self):
        super().setUp()
        self.list_matloob()
        # Nothing here may write to Bitrix: a person's own save sent this, a write back would loop.
        for target in ("apps.crmlink.client.call", "apps.leadai.assistant.crm_fields.post"):
            patcher = patch(target, side_effect=AssertionError(f"{target}: wrote back to Bitrix"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.http = Client(enforce_csrf_checks=True)  # no session, no CSRF token: the signature is the key

    def post(self, body, **options):
        raw, headers = signed(body, **options)
        with self.captureOnCommitCallbacks(execute=True):
            return self.http.post(URL, data=raw, content_type="application/json", **headers)

    def change(self, bot_status=None, wa_opt_out=None, lead_id=555, at="2026-10-14T12:00:00+04:00"):
        return self.post({"lead_id": lead_id, "bot_status": bot_status, "wa_opt_out": wa_opt_out, "changed_by": 2311, "at": at})


class ContractTests(BotStatusBase):
    def test_method_signature_and_body_are_checked_first(self):
        self.assertEqual(self.http.get(URL).status_code, 405)
        self.assertEqual(self.http.put(URL, data=b"{}", content_type="application/json").status_code, 405)
        body = {"lead_id": 555, "bot_status": 2478, "wa_opt_out": None, "changed_by": 2311, "at": "x"}
        raw = json.dumps(body).encode()
        self.assertEqual(self.http.post(URL, data=raw, content_type="application/json").status_code, 401)  # unsigned
        for options in ({"secret": "another"}, {"ts": int(time.time()) - 301}, {"ts": int(time.time()) + 301}, {"prefix": b"leadai-fields."}, {"prefix": b"leadai-notify."}):
            with self.subTest(options=options):
                self.assertEqual(self.post(body, **options).status_code, 401)
        raw, headers = signed(body)
        headers["HTTP_X_LEADAI_SIGN"] = headers["HTTP_X_LEADAI_SIGN"].upper()  # the same hex, any case
        self.assertEqual(self.http.post(URL, data=raw, content_type="application/json", **headers).status_code, 200)
        self.assertEqual(self.http.post(URL, data=raw + b" ", content_type="application/json", **headers).status_code, 401)  # body changed
        self.assertFalse(LeadAiOptOut.objects.exists())

    def test_a_body_that_is_not_the_contract_is_400(self):
        cases = [
            b"not json",
            b"[1, 2]",
            json.dumps({"bot_status": 2478}).encode(),
            json.dumps({"lead_id": "abc", "bot_status": 2478}).encode(),
            json.dumps({"lead_id": 555, "bot_status": True}).encode(),
            json.dumps({"lead_id": 555, "bot_status": -1}).encode(),
            json.dumps({"lead_id": 555, "at": 5}).encode(),
            b"",
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(self.post(raw).status_code, 400)
        huge, headers = signed(b"{" + b" " * (20 * 1024) + b"}")
        self.assertEqual(self.http.post(URL, data=huge, content_type="application/json", **headers).status_code, 400)

    def test_no_chat_of_the_lead_is_still_ok(self):
        response = self.change(2478, lead_id=999)
        self.assertEqual((response.status_code, response.json()), (200, {"ok": True, "chats": 0}))
        # A Bot Status the assistant has nothing to do with (Qualifying) changes nothing.
        self.assertEqual(self.change(2476).json(), {"ok": True, "chats": 0})
        self.assertFalse(LeadAiChatState.objects.filter(paused_at__isnull=False).exists())


class EffectTests(BotStatusBase):
    def state(self):
        return LeadAiChatState.objects.get(conversation=self.conversation)

    def test_handed_to_agent_hands_over_and_pauses_until_resume(self):
        response = self.change(2478)
        self.assertEqual(response.json(), {"ok": True, "chats": 1})
        state = self.state()
        self.assertIsNotNone(state.paused_at)
        self.assertIsNone(state.paused_by)
        self.assertIsNotNone(state.handed_over_at)
        self.assertEqual(state.handover_reason, "Bitrix: handed to agent")
        self.assertEqual(state.silent_reason, "paused until an agent presses Resume")
        alert = LeadAiAlert.objects.get(kind="bitrix_status", agent=self.matloob)
        self.assertIn("Bitrix user 2311 set Bot Status Handed to agent on lead 555", alert.text)
        self.assertIn("paused in this chat until someone presses Resume AI", alert.text)
        message = self.inbound("Hello?")
        self.assertEqual(engine.run_turn(message.pk, first_queued_at=(NOW - dt.timedelta(minutes=1)).isoformat()).reason, "paused until an agent presses Resume")
        # The same change again changes nothing, and alerts nobody twice.
        alerts = LeadAiAlert.objects.count()
        self.assertEqual(self.change(2478, at="2026-10-14T12:05:00+04:00").json(), {"ok": True, "chats": 1})
        self.assertEqual(LeadAiAlert.objects.count(), alerts)

    def test_broker_labels_and_pauses_the_chat(self):
        self.change(2479)
        state = self.state()
        self.assertIsNotNone(state.paused_at)
        self.assertEqual(state.handover_reason, engine.BROKER)
        self.assertTrue(self.conversation.labels.filter(name="Broker").exists())

    def test_lost_ends_the_invitations_and_cancels_the_open_visit_without_writing_back(self):
        appointment = LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=NOW + dt.timedelta(days=1))
        self.change(2480)
        state = self.state()
        self.assertIsNotNone(state.not_interested_at)
        self.assertIsNone(state.stopped_at)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "cancelled")
        self.assertEqual(appointment.history[-1]["by"], "bitrix")
        # No lost move back to Bitrix: the person's Lost is only kept as the lead's newest value, never posted
        # (bitrix_status.remember, launch review issue 19).
        self.assertFalse(LeadAiCrmField.objects.filter(sent_at__isnull=True).exists())
        self.assertFalse(LeadAiCrmField.objects.filter(field="lost").exists())
        self.assertEqual(
            list(LeadAiCrmField.objects.values_list("field", "value", "error")), [("UF_CRM_A7_BOT_STATUS", "2480", bitrix_status.SET_IN_BITRIX)]
        )
        self.assertFalse(LeadAiOptOut.objects.exists())

    def test_opted_out_stops_the_chat_and_blocks_the_phone_everywhere(self):
        self.change(2481)
        state = self.state()
        self.assertEqual((state.stop_reason, state.stopped_at is not None), ("stop_all", True))
        row = LeadAiOptOut.objects.get()
        self.assertEqual((row.phone, row.source, row.reason), ("971501234567", "bitrix", "Set in Bitrix on lead 555"))

    def test_whatsapp_opt_out_yes_with_any_bot_status_beside_it_is_a_stop(self):
        appointment = LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", starts_at=NOW + dt.timedelta(days=1), reminder_due_at=NOW + dt.timedelta(hours=23)
        )
        self.change(2476, wa_opt_out=2482)
        self.assertEqual(self.state().stop_reason, "stop_all")
        self.assertTrue(optout.is_blocked("971501234567"))
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.reminder_due_at), ("confirmed", None))  # they may come; no reminder
        alert = LeadAiAlert.objects.filter(kind="bitrix_status").first()
        self.assertIn("WhatsApp Opt-out Yes", alert.title)

    def test_the_registry_holds_even_with_no_chat_on_the_screen(self):
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)  # moved back to the inbox
        self.assertEqual(self.change(2481).json(), {"ok": True, "chats": 0})
        self.assertTrue(optout.is_blocked("971501234567"))
        self.assertIsNone(LeadAiChatState.objects.filter(conversation=self.conversation, stopped_at__isnull=False).first())

    def test_a_chat_the_campaign_sent_from_the_lead_is_found_too(self):
        # Came onto the screen from a deal, but a campaign sent from lead 777 reached it.
        contact = Contact.objects.create(wa_id="971507770000")
        conversation = Conversation.objects.create(number=self.number, contact=contact, session_expires_at=NOW + dt.timedelta(hours=5))
        LeadAiChat.objects.create(conversation=conversation, active=True, crm_entity="deal", crm_id=31)
        CampaignRecipient.objects.create(campaign=Campaign.objects.get(), phone="971507770000", conversation=conversation, crm_lead_id=777)
        self.assertEqual(self.change(2478, lead_id=777).json(), {"ok": True, "chats": 1})
        self.assertIsNotNone(LeadAiChatState.objects.get(conversation=conversation).paused_at)
        self.assertFalse(LeadAiChatState.objects.filter(conversation=self.conversation, paused_at__isnull=False).exists())
