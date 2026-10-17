"""Batch 2e slice A (spec §6.1): Template B and the check-back follow a shops template only.

Template B (intl_city_shops_followup) is all shops. Before the mixed template can be sent, the follow-ups learn which
template a chat answers (ic_templates.kind): nobody who never answered the mixed template gets anything (the brief, Part
12.5); a check-back planned after it waits for slice B (the mixed template on its day) and is dropped meanwhile; its row
shows no "waits for approval" note; and the sweep never reads those chats every minute. Nudges are not Template B: a
customer who answered the mixed template and fell silent is still nudged. A later shops campaign gets its Template B
again. Each test fails without the guard it proves (followups.TEMPLATE_B_AFTER_SHOPS_ONLY off, guards_off.py).

The fakes are test_assistant's; the shops chat is test_follow_ups' (lead 555; the campaign's template went out Monday 12
October 2026 at 12:00 Dubai; the clock moves).
"""

from unittest.mock import patch

from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import WaTemplate
from apps.inbox.models import Conversation, Message
from apps.leadai import followups, ic_templates
from apps.leadai.assistant import rules
from apps.leadai.tests.test_follow_up_holds import LaunchBase, at
from apps.leadai.tests.test_follow_ups import CHECK_DAY, THURSDAY


class MixedFollowUpBase(LaunchBase):
    """The chat's campaign went out with the mixed template (intl_city_property_reconnect) on Monday at 12:00."""

    def setUp(self):
        super().setUp()
        WaTemplate.objects.filter(pk=self.template.pk).update(name=ic_templates.MIXED_NAME)
        self.template.refresh_from_db()


class MixedTemplateBTests(MixedFollowUpBase):
    def test_nobody_who_never_answered_the_mixed_template_gets_template_b(self):
        self.go(THURSDAY)  # 74 hours on, nothing in the chat since: a shops template's Template B would be due now
        self.assertFalse(followups.reengage_due(self.conversation, self.state_or_none(), THURSDAY))
        self.assertEqual(followups.due_now(), [])
        result, sent = self.send()
        self.assertEqual(result, "not due")
        sent.assert_not_called()

    def test_the_sweep_never_reads_them(self):
        self.go(THURSDAY)
        with patch.object(followups, "reengage_due", wraps=followups.reengage_due) as asked:
            self.assertEqual(followups.due_now(), [])
        asked.assert_not_called()  # the query leaves them out (a mixed campaign's non-repliers every minute for 14 days)

    def test_holds_template_b_and_the_check_back_never_the_nudges(self):
        self.tapped("Yes, still looking", at(12, 12, 5))
        self.wrote(rules.line("res_what_need", "en"), at(12, 12, 5, 15))
        self.window_from(at(12, 12, 5))
        self.assertEqual(self.holds(followups.REENGAGE), followups.HELD_NOT_SHOP_TEMPLATE)
        self.assertEqual(self.holds(followups.CHECK_BACK), followups.HELD_NOT_SHOP_TEMPLATE)
        self.assertEqual(self.holds(followups.NUDGE_1), "")  # they answered and went quiet: Q7's nudges still go
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), followups.NUDGE_1)

    def test_a_check_back_planned_after_the_mixed_template_is_dropped_on_its_day(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Yes", at(12, 12, 6))
        self.wrote(rules.line("check_back_yes", "en"), at(12, 12, 6, 15))
        self.set_state(followup_due_at=CHECK_DAY)
        self.go(CHECK_DAY)
        self.assertEqual(followups.due_now(), [])
        self.assertIsNone(self.state().followup_due_at)  # moot until slice B sends the mixed template on its day
        self.set_state(followup_due_at=CHECK_DAY)
        result, sent = self.send(followups.CHECK_BACK)
        self.assertEqual(result, "not due")
        sent.assert_not_called()

    def test_no_waits_for_approval_note_on_its_row(self):
        # Template B not approved on the chat's number: a shops chat says so (test_follow_ups), a mixed one never.
        self.assertEqual(followups.panel_note(self.conversation, self.state_or_none(), set()), "")
        self.set_state(followup_due_at=CHECK_DAY)
        self.assertEqual(followups.panel_note(self.conversation, self.state(), set()), "")
        WaTemplate.objects.filter(pk=self.template.pk).update(name="ic_shops")
        self.assertIn("is not approved on this number yet", followups.panel_note(self.conversation, self.state(), set()))

    def state_or_none(self):
        from apps.leadai.models import LeadAiChatState

        return LeadAiChatState.objects.filter(conversation=self.conversation).first()


class CampaignOrderTests(MixedFollowUpBase):
    """Two campaigns reach the chat: the newest template decides."""

    def second_campaign(self, name, moment):
        template = WaTemplate.objects.create(
            waba_business_id="waba1", name=name, language="en", category="MARKETING", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "Hi {{1}}, are you still looking?"}],
        )
        campaign = Campaign.objects.create(name=f"CRM Leads · Lead AI · {name}", number=self.number, template=template, created_by=self.agent)
        CampaignRecipient.objects.create(campaign=campaign, phone="971501234567", name="Ahmed Khan", conversation=self.conversation, crm_lead_id=555)
        Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template=template,
            body="Hi Ahmed, are you still looking?", status=Message.Status.DELIVERED, created_at=moment,
        )
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=moment)

    def test_a_shops_campaign_after_the_mixed_one_gets_its_template_b(self):
        self.second_campaign("intl_city_shops_reconnect", at(13, 12))
        self.go(at(16, 13))  # 73 hours after the shops campaign
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.REENGAGE)])

    def test_a_mixed_campaign_after_a_shops_one_gets_none(self):
        WaTemplate.objects.filter(pk=self.template.pk).update(name="ic_shops")
        self.second_campaign(ic_templates.MIXED_NAME, at(13, 12))
        self.go(at(16, 13))
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.holds(followups.REENGAGE), followups.HELD_NOT_SHOP_TEMPLATE)
