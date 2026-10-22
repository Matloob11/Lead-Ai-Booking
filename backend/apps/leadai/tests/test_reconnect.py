"""Reconnect again (apps/leadai/reconnect.py; Matloob 2026-10-22): the mixed campaign's customers who never said no get
one more template, inside their chat when the campaign reached them, as a fresh Lead AI campaign when it never did; a
chat that said no, a dead number, a booked viewing, a customer who wrote lately stay out. Plus the "AI auto reply" label
on the chats the new-lead greet opened (newlead.label_greeted, the sweep)."""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.campaigns.models import Campaign, CampaignRecipient, CrmTarget
from apps.catalog.models import WaTemplate
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import ic_templates, lane, reconnect
from apps.leadai.assistant import newlead, transcript
from apps.leadai.models import LeadAiAppointment, LeadAiChat, LeadAiChatState
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_shops_playbook import ShopsBase

AGAIN_BODY = "Hi {{1}}, this is AR Properties. You asked us about a property in International City a while ago. Are you still looking?"


class KindTests(SimpleTestCase):
    def test_the_reconnect_again_template_reads_as_the_mixed_one(self):
        self.assertEqual(ic_templates.kind(ic_templates.AGAIN_NAME), ic_templates.MIXED)
        self.assertEqual(ic_templates.kind(ic_templates.MIXED_NAME), ic_templates.MIXED)
        self.assertIn(ic_templates.AGAIN_NAME, ic_templates.NOT_SHOP_NAMES)
        form = ic_templates.again_form("AR Properties")
        self.assertEqual((form["name"], form["category"], form["language"]), (ic_templates.AGAIN_NAME, "MARKETING", "en"))
        self.assertIn("this is AR Properties.", form["body_text"])
        self.assertEqual(form["body_text"].count("{{1}}"), 1)
        self.assertNotIn("{{2}}", form["body_text"])
        self.assertEqual([button["text"] for button in form["buttons"]], list(ic_templates.MIXED_BUTTONS))
        self.assertEqual(form["body_examples"], {"1": "Sumon"})


class ReconnectBase(ShopsBase):
    """The shops campaign's chat (ShopsBase: a Lead AI campaign on ic_shops, its recipient linked to the chat), the
    reconnect-again template approved on the number's WABA, and more recipients made to order."""

    def setUp(self):
        super().setUp()
        self.again = WaTemplate.objects.create(
            waba_business_id="waba1", name=ic_templates.AGAIN_NAME, language="en", category="MARKETING", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": AGAIN_BODY}],
        )
        CampaignRecipient.objects.filter(conversation=self.conversation).update(status=CampaignRecipient.Status.SENT)
        self.counter = 0

    def recipient(self, campaign=None, phone=None, status="sent", error="", lead_id=None, chat=True, **state):
        """Another recipient of the campaign: with its own chat on the Lead AI screen (``chat``), or none; ``state`` sets
        the chat's state fields (stopped_at, handed_over_at, ...). Returns the conversation, or None."""
        self.counter += 1
        phone = phone or f"9715099900{self.counter:02d}"
        lead_id = lead_id or 700 + self.counter
        conversation = None
        if chat:
            contact = Contact.objects.create(wa_id=phone, display_name=f"Customer {self.counter}")
            conversation = Conversation.objects.create(
                number=self.number, contact=contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=20)
            )
            LeadAiChat.objects.create(conversation=conversation, active=True, crm_entity="lead", crm_id=lead_id)
            if state:
                LeadAiChatState.objects.filter(pk=LeadAiChatState.for_conversation(conversation).pk).update(**state)
        CampaignRecipient.objects.create(
            campaign=campaign or self.campaign, phone=phone, name="x", conversation=conversation, crm_lead_id=lead_id, status=status, error_detail=error
        )
        return conversation

    def rows(self, *campaigns):
        return {row.phone: row for row in reconnect.audience([campaign.pk for campaign in campaigns] or [self.campaign.pk], NOW)}


class AudienceTests(ReconnectBase):
    def test_who_goes_where(self):
        quiet = self.recipient()
        Conversation.objects.filter(pk=quiet.pk).update(last_inbound_at=NOW - dt.timedelta(days=3))
        recent = self.recipient()
        Conversation.objects.filter(pk=recent.pk).update(last_inbound_at=NOW - dt.timedelta(hours=5))
        stopped = self.recipient(stopped_at=NOW - dt.timedelta(days=1))
        handed = self.recipient(handed_over_at=NOW - dt.timedelta(days=1))
        no = self.recipient(not_interested_at=NOW - dt.timedelta(days=1))
        booked = self.recipient()
        LeadAiAppointment.objects.create(conversation=booked, status=LeadAiAppointment.Status.CONFIRMED, starts_at=NOW + dt.timedelta(days=1))
        capped = self.recipient(status="exhausted", error="Meta marketing daily cap (131049): This message was not delivered")
        dead = self.recipient(status="exhausted", error="Message undeliverable")
        self.recipient(chat=False, status="skipped", error="Skipped: Meta marketing daily cap already hit", phone="971509990099", lead_id=999)
        self.recipient(chat=False, status="exhausted", error="Message undeliverable", phone="971509990098", lead_id=998)
        off = self.recipient()
        LeadAiChat.objects.filter(conversation=off).update(active=False)
        done = self.recipient()
        Message.objects.create(
            conversation=done, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template=self.again, body="x", status=Message.Status.SENT
        )
        rows = self.rows()
        self.assertEqual(rows[self.contact.wa_id].path, reconnect.CHAT)  # the campaign's own chat: never wrote back
        self.assertEqual(rows[quiet.contact.wa_id].path, reconnect.CHAT)
        self.assertEqual(rows[recent.contact.wa_id].why, "wrote to us in the last 48 hours")
        self.assertEqual(rows[stopped.contact.wa_id].why, "stopped")
        self.assertEqual(rows[handed.contact.wa_id].why, "handed to a person")
        self.assertEqual(rows[no.contact.wa_id].why, "not interested")
        self.assertEqual(rows[booked.contact.wa_id].why, "a viewing is booked or held")
        self.assertEqual(rows[capped.contact.wa_id].path, reconnect.CHAT)
        self.assertTrue(rows[dead.contact.wa_id].why.startswith("the number cannot receive"), rows[dead.contact.wa_id].why)
        self.assertEqual(rows["971509990099"].path, reconnect.FRESH)
        self.assertTrue(rows["971509990098"].why.startswith("the number cannot receive"))
        self.assertEqual(rows[off.contact.wa_id].why, "not on the Lead AI screen")
        self.assertEqual(rows[done.contact.wa_id].why, "sent already")
        counts = reconnect.summary(list(rows.values()))
        self.assertEqual((counts["recipients"], counts[reconnect.CHAT], counts[reconnect.FRESH]), (13, 3, 1))
        self.assertEqual(counts["out"]["stopped"], 1)
        # A failed reconnect-again message does not count as sent: the next run tries that chat again.
        Message.objects.filter(conversation=done, template=self.again).update(status=Message.Status.FAILED)
        self.assertEqual(self.rows()[done.contact.wa_id].path, reconnect.CHAT)

    def test_a_phone_in_two_campaigns_goes_once(self):
        other = Campaign.objects.create(name="other", number=self.number, template=self.template, created_by=self.agent, crm_target=CrmTarget.NONE)
        lane.mark_campaign(other, playbook=lane.IC_SHOPS)
        self.recipient(campaign=other, phone=self.contact.wa_id, chat=False, status="skipped")
        rows = [row for row in reconnect.audience([self.campaign.pk, other.pk], NOW) if row.phone == self.contact.wa_id]
        self.assertEqual([(row.path, row.why) for row in rows], [(reconnect.CHAT, ""), ("", "the phone is in these campaigns already")])


class SendTests(ReconnectBase):
    def test_the_chat_gets_the_template_as_template_b_goes(self):
        row = self.rows()[self.contact.wa_id]
        with patch("apps.inbox.services.send_template") as send:
            self.assertEqual(reconnect.send_in_chat(row, NOW), "sent")
        conversation, agent, template, values = send.call_args.args[:4]
        self.assertEqual((conversation.pk, agent, template.pk, values), (self.conversation.pk, None, self.again.pk, {"1": "Ahmed"}))
        self.assertEqual(send.call_args.kwargs["payload"]["source"], transcript.FOLLOW_UP)
        self.assertEqual(send.call_args.kwargs["payload"]["followup"], reconnect.FOLLOWUP_KIND)
        # Meta refused it: said so; nothing counts as sent, so the next run tries again.
        with patch("apps.inbox.services.send_template", side_effect=RuntimeError("131049")):
            self.assertTrue(reconnect.send_in_chat(row, NOW).startswith("failed (RuntimeError"))
        self.assertFalse(reconnect.sent_already(self.conversation))
        # No approved template on the number: nothing goes.
        WaTemplate.objects.filter(pk=self.again.pk).update(status=WaTemplate.Status.PENDING)
        self.assertEqual(reconnect.send_in_chat(row, NOW), "no approved reconnect-again template on this number")

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/x/")
    def test_the_never_messaged_get_a_fresh_campaign_through_the_popups_path(self):
        self.recipient(chat=False, status="skipped", error="Skipped: Meta marketing daily cap already hit", phone="971509990099", lead_id=999)
        rows = [row for row in reconnect.audience([self.campaign.pk], NOW) if row.path == reconnect.FRESH]
        self.assertEqual([row.lead_id for row in rows], [999])
        lead = {"ID": "999", "NAME": "SARA", "LAST_NAME": "ALI", "TITLE": "Bayut WhatsApp | SARA ALI", "PHONE": [{"VALUE": "+971509990099"}], "STATUS_ID": "NEW"}

        def bitrix(method, payload=None):
            # Our read of the leads by id; the popup's own read of the opted-out leads (crm_leads.phones_opted_out) finds none.
            return [lead] if method == "crm.lead.list" and "ID" in (payload or {}).get("filter", {}) else []

        with patch("apps.crmlink.client.call", side_effect=bitrix) as call, patch("apps.campaigns.tasks.run_campaign.delay") as run:
            reports = reconnect.send_fresh(rows, self.admin, NOW)
        ours = [item for item in call.call_args_list if item.args[0] == "crm.lead.list" and "ID" in item.args[1].get("filter", {})]
        self.assertEqual(len(ours), 1)
        self.assertEqual(ours[0].args[1]["filter"], {"ID": [999]})
        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertEqual((report["sent"], report["skipped"], report["error"]), (1, [], ""))
        campaign = Campaign.objects.get(pk=report["campaign_id"])
        self.assertEqual(campaign.name, f"Reconnect again · Lead AI · {ic_templates.AGAIN_NAME}")
        self.assertEqual((campaign.lead_ai.playbook, campaign.number_id, campaign.template_id), ("ic_shops", self.number.pk, self.again.pk))
        recipient = CampaignRecipient.objects.get(campaign=campaign)
        self.assertEqual((recipient.phone, recipient.crm_lead_id, recipient.variables), ("971509990099", 999, {"1": "Sara"}))
        run.assert_called_once_with(campaign.pk)
        self.assertEqual(rows[0].result, "sent")
        # A second run minutes later: the lead is in a reconnect-again campaign already (queued), so it stays out.
        again = {row.phone: row for row in reconnect.audience([self.campaign.pk], NOW)}["971509990099"]
        self.assertEqual((again.path, again.why), ("", "in a reconnect-again campaign already"))
        # ... until that campaign's send failed for good for the cap: then it may go again (the runner's own retry aside).
        CampaignRecipient.objects.filter(campaign=campaign).update(status=CampaignRecipient.Status.EXHAUSTED, error_detail="131049")
        self.assertEqual({row.phone: row for row in reconnect.audience([self.campaign.pk], NOW)}["971509990099"].path, reconnect.FRESH)

    def test_send_takes_the_chats_first_within_the_limit(self):
        quiet = self.recipient()
        Conversation.objects.filter(pk=quiet.pk).update(last_inbound_at=NOW - dt.timedelta(days=3))
        self.recipient(chat=False, status="skipped", phone="971509990099", lead_id=999)
        rows = reconnect.audience([self.campaign.pk], NOW)
        with patch("apps.inbox.services.send_template") as send, patch("apps.leadai.reconnect.send_fresh", return_value=[]) as fresh:
            counts = reconnect.send(rows, self.admin, limit=1, now=NOW, pause=0)
        self.assertEqual((counts["chat_sent"], counts["chat_failed"], send.call_count), (1, 0, 1))
        fresh.assert_not_called()  # the limit was used up by the chats


class LabelTests(ReconnectBase):
    def test_the_greeted_chats_get_the_label_once(self):
        greet = Campaign.objects.create(
            name=f"{newlead.NAME_PREFIX} · portal_enquiry_reply", number=self.number, template=self.template, created_by=self.admin, crm_target=CrmTarget.NONE
        )
        lane.mark_campaign(greet, playbook=lane.IC_SHOPS)
        conversation = self.recipient(campaign=greet)
        self.assertEqual(newlead.label_greeted(), 1)
        self.assertEqual([label.name for label in conversation.labels.all()], [newlead.AUTO_REPLY_LABEL])
        self.assertEqual(newlead.label_greeted(), 0)
        self.assertFalse(self.conversation.labels.exists())  # a campaign's chat gets no such label
