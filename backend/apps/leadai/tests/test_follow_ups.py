"""Batch 2b stage B: the shops chats' automatic follow-ups (board T63 Template B, T25 the
check-back, T29 the nudges), what the assistant makes of an answer to Template B, the
"Follow-up waits" note on the chat's row, and that a general chat gets none of it.

- A. the nudges' words and times, Template B's hours (plain data);
- B. Template B, once, 72 hours after a campaign nobody answered;
- C. the check-back's Template B on the day the customer asked for;
- D. the nudges to a customer who went quiet after our question;
- E. the customer's answer to Template B.

The fakes are test_assistant's; the shops chat is test_shops_playbook's (lead 555; its
campaign's template went out Monday 12 October 2026 at 12:00 Dubai; the clock moves).
"""

import datetime as dt
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.catalog.models import WaTemplate
from apps.gateway.client import AlotsError
from apps.gateway.models import CreditState
from apps.inbox.models import Conversation, Message
from apps.inbox.services import SendBlocked
from apps.leadai import followups, optout, shop_templates, tasks
from apps.leadai.assistant import engine, hours, nudges, rules, transcript
from apps.leadai.models import DEFAULT_SHOPS_FACTS, LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings
from apps.leadai.tests.test_assistant import NOW, _outbound, fake_send_template, fake_send_text
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, shop_answer

DUBAI = hours.DUBAI


def at(day, hour, minute=0, month=10):
    return dt.datetime(2026, month, day, hour, minute, tzinfo=DUBAI)


THURSDAY = at(15, 14)  # 74 hours after the campaign's template (Monday 12:00)
CHECK_DAY = at(11, 14, month=11)  # a Wednesday, 30 days after NOW
FIRST_NUDGE = "Hi Ahmed, I picked 2 Type 1 shops that would work well for a vape shop. Shall I book you for this evening?"


def failed_send(conversation, template, payload):
    """What inbox.services.send_template leaves when the gateway refuses: the row, FAILED."""
    return Message.objects.create(
        conversation=conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, body="x",
        template=template, payload=payload or {}, status=Message.Status.FAILED, created_at=NOW,
    )


def template_b(status=WaTemplate.Status.APPROVED, body="", waba="waba1"):
    return WaTemplate.objects.create(
        waba_business_id=waba,
        name=shop_templates.FOLLOWUP_NAME,
        language="en",
        category="MARKETING",
        status=status,
        components=[
            {"type": "BODY", "text": body or shop_templates.followup_body(DEFAULT_SHOPS_FACTS)},
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": label} for label in shop_templates.FOLLOWUP_BUTTONS]},
        ],
    )


# A. Plain data ---------------------------------------------------------------------------------------


class NudgeWordsTests(SimpleTestCase):
    def test_the_first_nudge_names_the_type_and_their_business(self):
        first = nudges.first_text
        self.assertEqual(
            first("en", "Md Sumon", shop_type="type_2", business="vape shop", now=NOW),
            "Hi Sumon, I picked 2 Type 2 shops that would work well for a vape shop. Shall I book you for this evening?",
        )
        self.assertIn("for your ice cream business.", first("en", "Sumon", shop_type="type_1", business="ice cream", now=NOW))
        self.assertIn("for a restaurant.", first("en", "Sumon", shop_type="type_1", business="restaurant (shawarma and juice)", now=NOW))
        self.assertEqual(
            first("ur_latin", "Sumon", shop_type="type_2", business="vape shop", now=NOW),
            "Hi Sumon, maine aap ke vape shop ke liye Type 2 ki 2 shops chuni hain. Kya main aap ke liye aaj shaam ka slot book kar doon?",
        )
        self.assertIn("aapke salon ke liye", first("hi_latin", "Sumon", shop_type="type_1", business="salon", now=NOW))
        self.assertIn("aapke ice cream business ke liye", first("hi_latin", "Sumon", shop_type="type_1", business="ice cream", now=NOW))
        arabic = first("ar", "Sumon", shop_type="type_3", business="vape shop", now=NOW)
        self.assertTrue(arabic.startswith("مرحباً Sumon، اخترت لك محلّين من Type 3 يناسبان نشاطك (vape shop)."), arabic)
        self.assertIn("آپ کے کاروبار (vape shop) کے لیے Type 1", first("ur", "Sumon", shop_type="type_1", business="vape shop", now=NOW))
        self.assertIn("आपके बिज़नेस (vape shop) के लिए Type 1", first("hi", "", shop_type="type_1", business="vape shop", now=NOW))
        self.assertTrue(first("xx", "Sumon", shop_type="type_1", business="vape", now=NOW).startswith("Hi Sumon, I picked"))

    def test_the_generic_nudge_when_the_type_or_the_business_is_unknown(self):
        first = nudges.first_text
        generic = "Hi Sumon, just checking in — shall I hold a slot for you to see the shops today or tomorrow?"
        self.assertEqual(first("en", "Sumon", business="vape shop", now=NOW), generic)
        self.assertEqual(first("en", "Sumon", shop_type="type_1", now=NOW), generic)
        self.assertEqual(first("en", "", shop_type="type_1", now=NOW), generic.replace("Hi Sumon", "Hi there"))
        # Tomorrow is closed (a Saturday, or a holiday): the next open day by name.
        saturday = at(17, 12)
        self.assertTrue(first("en", "Sumon", now=saturday).endswith("see the shops today or on Monday?"))
        self.assertIn("اليوم أو يوم الاثنين", first("ar", "Sumon", now=saturday))
        self.assertIn("آج یا پیر کو", first("ur", "Sumon", now=saturday))
        self.assertIn("aaj ya Monday ko", first("ur_latin", "Sumon", now=saturday))
        self.assertTrue(first("en", "Sumon", now=NOW, closed_dates=["2026-10-13"]).endswith("today or on Wednesday?"))
        # A business with markup, or too long to say, is not named.
        self.assertEqual(first("en", "Sumon", shop_type="type_1", business="<b>vape</b>", now=NOW), generic)
        self.assertEqual(first("en", "Sumon", shop_type="type_1", business="x" * 60, now=NOW), generic)

    def test_the_morning_nudge_offers_todays_free_slots(self):
        tuesday = at(13, 10, 30)
        slots = nudges.today_slots(tuesday)
        self.assertEqual(slots, [at(13, 11, 30), at(13, 13, 30)])  # an hour ahead at least (hours.OFFER_LEAD)
        self.assertEqual(
            nudges.second_text("en", "Ahmed Khan", slots),
            "Good morning Ahmed, would today suit you to see the shops? I can hold a slot at 11:30 AM or 1:30 PM.",
        )
        self.assertEqual(nudges.second_text("en", "", slots[:1]), "Good morning, would today suit you to see the shops? I can hold a slot at 11:30 AM.")
        self.assertIn("11:30 AM یا 1:30 PM", nudges.second_text("ur", "Ahmed", slots))
        self.assertIn("الساعة 11:30 AM أو 1:30 PM", nudges.second_text("ar", "Ahmed", slots))
        # Another client's slot is never one of them; none left today, or a closed day: no nudge.
        self.assertEqual(nudges.today_slots(tuesday, taken=[at(13, 13, 30)]), [at(13, 11, 30), at(13, 14)])
        self.assertEqual(nudges.today_slots(at(18, 10, 30)), [])  # a Sunday
        self.assertEqual(nudges.today_slots(at(13, 19, 20)), [])
        self.assertEqual(nudges.today_slots(tuesday, closed_dates=["2026-10-13"]), [])

    def test_what_counts_as_our_question(self):
        self.assertTrue(nudges.asks_or_invites("What size do you need?"))
        self.assertTrue(nudges.asks_or_invites("Would you like to visit our office."))
        self.assertTrue(nudges.asks_or_invites("Great! We have 3 types of shops available in International City:", "interactive"))
        self.assertFalse(nudges.asks_or_invites("Perfect! Please share a copy of your trade license here (photo or PDF)."))
        self.assertFalse(nudges.asks_or_invites("Great, I'll check back with you then."))


class NudgeTimingTests(SimpleTestCase):
    def test_the_first_nudge_two_hours_on_inside_the_window_between_10_and_18(self):
        asked, window = at(12, 13, 1), at(13, 13)
        due = nudges.first_due
        self.assertTrue(due(at(12, 15, 1), asked, window))
        self.assertFalse(due(at(12, 15, 0), asked, window))  # not two hours yet
        self.assertFalse(due(at(12, 15, 1), asked, at(12, 15, 10)))  # nine minutes of window left
        self.assertTrue(due(at(12, 15, 1), asked, at(12, 15, 11)))
        self.assertFalse(due(at(12, 18, 0), asked, window))
        self.assertTrue(due(at(13, 10, 0), asked, window))  # the next morning, still inside the window
        self.assertFalse(due(at(13, 9, 59), asked, window))
        self.assertFalse(due(at(18, 12), at(18, 9), at(19, 9)))  # a Sunday
        self.assertFalse(due(at(12, 15, 1), asked, window, ["2026-10-12"]))
        self.assertFalse(due(at(12, 15, 1), None, window))

    def test_the_last_nudge_the_next_morning_from_10_30_to_noon(self):
        first, window = at(12, 15, 1), at(13, 13)
        due = nudges.second_due
        self.assertFalse(due(at(13, 10, 29), first, window))
        self.assertTrue(due(at(13, 10, 30), first, window))
        self.assertTrue(due(at(13, 11, 59), first, window))
        self.assertFalse(due(at(13, 12, 0), first, window))
        self.assertFalse(due(at(14, 10, 30), first, at(15, 10)))  # the day after next
        self.assertFalse(due(at(13, 10, 30), first, at(13, 10, 35)))  # five minutes of window left
        self.assertFalse(due(at(13, 10, 30), first, window, ["2026-10-13"]))
        self.assertFalse(due(at(13, 10, 30), None, window))


class TemplateBTapRuleTests(SimpleTestCase):
    def rule(self, text, **flags):
        options = {"tapped": True, "first_answer": True}
        options.update(flags)
        return engine.shops_rule(text, **options)

    def test_a_templates_yes_is_the_first_yes_and_from_an_end_user_the_list_or_two_slots(self):
        self.assertEqual(self.rule("Yes, book a viewing"), engine.FOR_WHOM)
        self.assertEqual(self.rule("Yes, show me shops"), engine.FOR_WHOM)
        known = {"for_client_known": True, "end_user": True}
        self.assertEqual(self.rule("Yes, book a viewing", **known), f"{engine.BOOK_TAP}:")
        self.assertEqual(self.rule("Yes, show me shops", **known), engine.TYPES_TAP)
        self.assertEqual(self.rule("Interested", **known), engine.TYPES_TAP)
        # Not a broker's (for a client), not typed, not with a visit open, not after our own reply.
        self.assertEqual(self.rule("Yes, book a viewing", for_client_known=True), "")
        self.assertEqual(self.rule("Yes", tapped=False, **known), "")
        self.assertEqual(self.rule("Yes, book a viewing", meeting_open=True, **known), "")
        self.assertEqual(self.rule("Yes, book a viewing", first_answer=False, **known), "")
        self.assertEqual(self.rule("Not now", **known), engine.NOT_NOW)
        self.assertTrue(rules.is_book_tap("Yes, book a viewing") and not rules.is_book_tap("Yes, show me shops"))


class TemplateBHoursTests(SimpleTestCase):
    def test_11_to_18_dubai_monday_to_saturday_never_a_closed_date(self):
        hours_ok = followups.send_hours
        self.assertFalse(hours_ok(at(15, 10, 59)))
        self.assertTrue(hours_ok(at(15, 11, 0)))
        self.assertTrue(hours_ok(at(15, 17, 59)))
        self.assertFalse(hours_ok(at(15, 18, 0)))
        self.assertTrue(hours_ok(at(17, 14)))  # Saturday
        self.assertFalse(hours_ok(at(18, 14)))  # Sunday
        self.assertFalse(hours_ok(at(16, 14), ["2026-10-16"]))
        self.assertTrue(hours_ok(dt.datetime(2026, 10, 15, 8, 0, tzinfo=dt.timezone.utc)))  # 12:00 in Dubai


# B. Template B (T63) ---------------------------------------------------------------------------------


class FollowUpBase(ShopsBase):
    def setUp(self):
        super().setUp()
        self.template_b = template_b()
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=self.campaign_message.created_at)
        self.queued = self.stub("apps.leadai.tasks.send_follow_up.delay")

    def go(self, moment):
        self.clock.return_value = moment

    def send(self, kind=followups.REENGAGE, send_template=None):
        with patch("apps.inbox.services.send_template", side_effect=send_template or fake_send_template) as sent:
            result = followups.send(self.conversation.pk, kind)
        return result, sent

    def row(self):
        self.client.force_login(self.agent)
        return self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()

    def other(self, wa_id="971509990777"):
        """Another customer's chat on the same number."""
        from apps.inbox.models import Contact

        return Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id=wa_id))


class TemplateBTests(FollowUpBase):
    def test_72_hours_after_a_campaign_nobody_answered_template_b_goes_once(self):
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.REENGAGE)])
        tasks._follow_ups()
        self.queued.assert_called_once_with(self.conversation.pk, followups.REENGAGE)
        result, sent = self.send()
        self.assertEqual(result, "sent")
        conversation, agent, template, values = sent.call_args.args[:4]
        self.assertEqual((conversation.pk, agent, template.pk, values), (self.conversation.pk, None, self.template_b.pk, {"1": "Ahmed"}))
        payload = sent.call_args.kwargs["payload"]
        self.assertEqual((payload["source"], payload["followup"]), (transcript.FOLLOW_UP, followups.REENGAGE))
        self.assertEqual(self.state().template_b_sent_at, THURSDAY)
        # Never a third message: due no more, and a second task sends nothing.
        self.go(THURSDAY + dt.timedelta(hours=1))
        self.assertEqual(followups.due_now(), [])
        result, sent = self.send()
        self.assertEqual(result, "not due")
        sent.assert_not_called()
        # Read as the campaign it follows up, never as a colleague's message.
        message = Message.objects.get(payload__source=transcript.FOLLOW_UP)
        self.assertEqual(transcript.who(message, set()), "campaign")
        self.assertEqual(transcript.campaign_message(self.conversation, transcript.campaign_template_ids(self.conversation)), message)

    def test_a_campaign_sent_again_later_gets_its_own_template_b(self):
        self.go(THURSDAY)
        self.send()
        # Five weeks on (C10 leaves the same template out for 30 days) Matloob sends the campaign again.
        again = at(16, 12, month=11)  # a Monday
        Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE,
            template=self.template, body="Hi Ahmed, shops are available in International City. Interested?",
            status=Message.Status.DELIVERED, created_at=again,
        )
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=again)
        self.go(again + dt.timedelta(hours=71))
        self.assertEqual(followups.due_now(), [])
        self.go(at(19, 14, month=11))  # Thursday, 74 hours on
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.REENGAGE)])
        self.assertEqual(self.send()[0], "sent")
        self.assertEqual(self.state().template_b_sent_at, at(19, 14, month=11))
        self.assertEqual(Message.objects.filter(payload__source=transcript.FOLLOW_UP).count(), 2)
        self.assertEqual(followups.due_now(), [])

    def test_not_before_72_hours_and_not_after_14_days(self):
        self.go(at(15, 11, 59))
        self.assertEqual(followups.due_now(), [])
        self.go(at(15, 12, 0))
        self.assertEqual(len(followups.due_now()), 1)
        self.go(at(26, 11, 59))
        self.assertEqual(len(followups.due_now()), 1)
        self.go(at(26, 12, 1))
        self.assertEqual(followups.due_now(), [])

    def test_only_from_11_to_18_dubai_monday_to_saturday_and_never_on_a_closed_date(self):
        for moment in (at(15, 10, 59), at(15, 18, 0), at(18, 14)):
            with self.subTest(moment=moment):
                self.go(moment)
                self.assertEqual(followups.due_now(), [])
        LeadAiSettings.objects.filter(pk=1).update(closed_dates=["2026-10-16"])
        self.go(at(16, 14))
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "outside Template B's hours")
        self.go(at(17, 14))  # Saturday
        self.assertEqual(len(followups.due_now()), 1)

    def test_not_once_the_customer_answered(self):
        self.inbound("ok", seconds_ago=60)  # Monday 13:59
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "not due")

    def test_not_once_a_colleague_wrote(self):
        _outbound(self.conversation, self.agent, Message.Kind.TEXT, "Hello, are you still looking?", {}, created_at=NOW)
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [])

    def test_not_after_a_reaction_nor_when_the_template_never_went(self):
        Message.objects.filter(pk=self.campaign_message.pk).update(reactions={"971501234567": "👍"})
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [])
        Message.objects.filter(pk=self.campaign_message.pk).update(reactions={}, status=Message.Status.FAILED)
        self.assertEqual(followups.due_now(), [])
        Message.objects.filter(pk=self.campaign_message.pk).update(status=Message.Status.READ)
        self.assertEqual(len(followups.due_now()), 1)

    def test_never_in_a_chat_the_assistant_may_not_message(self):
        self.go(THURSDAY)
        state = LeadAiChatState.for_conversation(self.conversation)
        for field in ("stopped_at", "paused_at", "handed_over_at", "not_interested_at"):
            with self.subTest(field=field):
                LeadAiChatState.objects.filter(pk=state.pk).update(**{field: NOW})
                self.assertEqual(followups.due_now(), [])
                self.assertEqual(self.send()[1].call_count, 0)
                LeadAiChatState.objects.filter(pk=state.pk).update(**{field: None})
        self.assertEqual(len(followups.due_now()), 1)
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)  # moved to the inbox
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "not a shops chat")  # no longer on the Lead AI screen at all
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=True)
        Conversation.objects.filter(pk=self.conversation.pk).update(linked_conversation=self.other())  # transferred
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "transferred to another agent")
        Conversation.objects.filter(pk=self.conversation.pk).update(linked_conversation=None)
        LeadAiSettings.objects.filter(pk=1).update(assistant_enabled=False)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "the assistant is switched off")
        LeadAiSettings.objects.filter(pk=1).update(assistant_enabled=True)
        optout.record(self.contact.wa_id, reason="STOP", source=optout.Source.INBOX_TAP)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "on the opt-out registry")

    def test_not_approved_it_waits_with_a_note_on_the_chats_row_and_no_alert(self):
        WaTemplate.objects.filter(pk=self.template_b.pk).update(status=WaTemplate.Status.PENDING)
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "Template B is not approved on this number")
        note = self.row()["lead_ai_ai"]["followup_note"]
        self.assertIn("intl_city_shops_followup is not approved on this number", note)
        listed = self.client.get("/api/leadai/chats/").json()["results"][0]
        self.assertEqual(listed["lead_ai_ai"]["followup_note"], note)
        self.assertFalse(LeadAiAlert.objects.exists())
        # One created with other placeholders (or a media header) is not Template B as submitted.
        WaTemplate.objects.filter(pk=self.template_b.pk).update(
            status=WaTemplate.Status.APPROVED, components=[{"type": "BODY", "text": "Hi {{1}}, from {{2}}."}]
        )
        self.assertEqual(followups.due_now(), [])
        WaTemplate.objects.filter(pk=self.template_b.pk).update(components=self.template_b.components)
        self.assertEqual(len(followups.due_now()), 1)
        self.assertEqual(self.row()["lead_ai_ai"]["followup_note"], "")

    def test_no_note_for_a_chat_that_waits_for_no_template_b(self):
        WaTemplate.objects.filter(pk=self.template_b.pk).update(status=WaTemplate.Status.PENDING)
        Conversation.objects.filter(pk=self.conversation.pk).update(last_inbound_at=NOW)
        self.assertEqual(self.row()["lead_ai_ai"]["followup_note"], "")  # answered: no Template B to wait for
        LeadAiChatState.objects.update_or_create(conversation=self.conversation, defaults={"followup_due_at": CHECK_DAY})
        self.assertIn("not approved", self.row()["lead_ai_ai"]["followup_note"])  # the check-back waits for it
        LeadAiChatState.objects.filter(conversation=self.conversation).update(stopped_at=NOW)
        self.assertEqual(self.row()["lead_ai_ai"]["followup_note"], "")

    def test_nothing_goes_while_the_gateway_is_out_of_credit(self):
        CreditState.objects.create(pk=1, out=True)
        self.go(THURSDAY)
        tasks._follow_ups()
        self.queued.assert_not_called()
        self.assertEqual(self.send()[0], "the gateway is out of credit")

    def test_a_send_that_never_reached_the_gateway_or_had_no_credit_is_tried_again(self):
        self.go(THURSDAY)
        result, _ = self.send(send_template=SendBlocked("Template 'intl_city_shops_followup' needs 1 value(s), got 0."))
        self.assertTrue(result.startswith("not sent"), result)
        self.assertIsNone(self.state().template_b_sent_at)
        self.assertEqual(len(followups.due_now()), 1)

        def no_credit(conversation, agent, template, values, *args, payload=None, **kwargs):
            failed_send(conversation, template, payload)
            raise AlotsError("Insufficient credits. Available credits are 1.8829")

        result, _ = self.send(send_template=no_credit)
        self.assertTrue(result.startswith("not sent"), result)
        self.assertIsNone(self.state().template_b_sent_at)

    def test_a_send_that_may_have_gone_out_is_never_repeated(self):
        self.go(THURSDAY)

        def refused(conversation, agent, template, values, *args, payload=None, **kwargs):
            failed_send(conversation, template, payload)
            raise AlotsError("POST /v1/messages -> HTTP 400: (#131026) Message undeliverable")

        result, _ = self.send(send_template=refused)
        self.assertTrue(result.startswith("failed"), result)
        self.assertEqual(self.state().template_b_sent_at, THURSDAY)
        self.assertEqual(followups.due_now(), [])

    def test_two_tasks_at_once_send_it_once(self):
        self.go(THURSDAY)
        inner = []

        def first(conversation, agent, template, values, *args, payload=None, **kwargs):
            # A second task for the same chat runs while this one sends.
            with patch("apps.inbox.services.send_template", side_effect=AssertionError("sent twice")):
                inner.append(followups.send(conversation.pk, followups.REENGAGE))
            return fake_send_template(conversation, agent, template, values, payload=payload)

        self.assertEqual(self.send(send_template=first)[0], "sent")
        self.assertEqual(inner, ["not due"])
        self.assertEqual(Message.objects.filter(payload__source=transcript.FOLLOW_UP).count(), 1)

    def test_whatsapp_not_delivering_it_alerts_nobody_and_sends_nothing_again(self):
        self.go(THURSDAY)
        self.send()
        message = Message.objects.get(payload__source=transcript.FOLLOW_UP)
        Message.objects.filter(pk=message.pk).update(status=Message.Status.FAILED, error_code="131049")
        with patch("apps.inbox.services.send_template") as resend:
            tasks.outbound_failed(message.pk)
        resend.assert_not_called()
        self.assertFalse(LeadAiAlert.objects.exists())
        self.assertEqual(followups.due_now(), [])


class OldImageRowsTests(FollowUpBase):
    def test_rows_the_old_code_inserts_during_a_deploy_get_the_new_fields_defaults(self):
        from django.db import connection
        from django.utils import timezone

        from apps.inbox.models import Contact

        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509990003"))
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {LeadAiChatState._meta.db_table} (conversation_id, facts, language, stop_reason, handover_reason, "
                "invites, responsible_bitrix_user_id, updated_at) VALUES (%s, %s, '', '', '', 0, '', %s)",
                [other.pk, "{}", timezone.now()],
            )
        state = LeadAiChatState.objects.get(conversation=other)
        self.assertEqual((state.nudges, state.lead_notes, state.lead_info_tries), (0, "", 0))
        self.assertEqual((state.template_b_sent_at, state.followup_sent_at, state.nudged_at, state.lead_asked_on, state.lead_info_at), (None,) * 5)


class GeneralFollowUpTests(GeneralBase):
    """A general chat: no Template B, no check-back template, no nudge."""

    def setUp(self):
        super().setUp()
        template_b()
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=self.campaign_message.created_at)

    def test_a_general_chat_never_gets_template_b_a_check_back_or_a_nudge(self):
        self.clock.return_value = THURSDAY
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(followups.send(self.conversation.pk, followups.REENGAGE), "not a shops chat")
        LeadAiChatState.objects.update_or_create(conversation=self.conversation, defaults={"followup_due_at": THURSDAY})
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(followups.send(self.conversation.pk, followups.NUDGE_1), "not a shops chat")
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()["lead_ai_ai"]["followup_note"], "")


# C. The check-back's Template B (T25) ----------------------------------------------------------------


class CheckBackTests(FollowUpBase):
    def setUp(self):
        super().setUp()
        self.tap("Not now", seconds_ago=60 * 60)
        self.ours(rules.line("check_back", "en"), minutes_ago=59)
        self.inbound("Yes", seconds_ago=55 * 60)
        self.ours(rules.line("check_back_yes", "en"), minutes_ago=54)
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=NOW - dt.timedelta(minutes=54), last_inbound_at=NOW)
        self.set_state(followup_due_at=CHECK_DAY, language="en")

    def test_on_the_day_they_asked_for_template_b_goes_once_and_the_date_is_cleared(self):
        self.go(CHECK_DAY - dt.timedelta(minutes=1))
        self.assertEqual(followups.due_now(), [])
        self.go(CHECK_DAY)
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.CHECK_BACK)])
        result, sent = self.send(followups.CHECK_BACK)
        self.assertEqual(result, "sent")
        self.assertEqual(sent.call_args.kwargs["payload"]["followup"], followups.CHECK_BACK)
        state = self.state()
        self.assertEqual((state.followup_due_at, state.followup_sent_at, state.template_b_sent_at), (None, CHECK_DAY, None))
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send(followups.CHECK_BACK)[0], "not due")

    def test_it_waits_outside_the_hours_and_for_the_approval(self):
        self.go(at(15, 14, month=11))  # a Sunday
        self.assertEqual(followups.due_now(), [])
        self.go(CHECK_DAY)
        WaTemplate.objects.filter(pk=self.template_b.pk).update(status=WaTemplate.Status.PENDING)
        self.assertEqual(followups.due_now(), [])
        self.assertIn("not approved", self.row()["lead_ai_ai"]["followup_note"])
        self.assertEqual(self.state().followup_due_at, CHECK_DAY)  # still planned

    def test_not_once_they_stopped_or_an_agent_paused_it(self):
        self.go(CHECK_DAY)
        for field in ("stopped_at", "paused_at"):
            with self.subTest(field=field):
                self.set_state(**{field: NOW})
                self.assertEqual(followups.due_now(), [])
                self.set_state(**{field: None})

    def test_a_send_that_did_not_go_gives_the_date_back(self):
        self.go(CHECK_DAY)
        result, _ = self.send(followups.CHECK_BACK, send_template=SendBlocked("The template is PAUSED, not approved."))
        self.assertTrue(result.startswith("not sent"), result)
        state = self.state()
        self.assertEqual((state.followup_due_at, state.followup_sent_at), (CHECK_DAY, None))


# D. The nudges (T29) ------------------------------------------------------------------------------------


class NudgeBase(FollowUpBase):
    """The customer wrote at 13:00 on Monday; our question went at 13:01; then silence."""

    def setUp(self):
        super().setUp()
        self.inbound("Yes I need a shop", seconds_ago=60 * 60)
        self.question = self.ours("A vape shop, got it. What size do you need?", minutes_ago=59)
        Conversation.objects.filter(pk=self.conversation.pk).update(
            last_message_at=self.question.created_at, last_inbound_at=at(12, 13), session_expires_at=at(13, 13)
        )
        self.set_state(language="en", facts={"for_client": False, "business_activity": "vape shop", "shop_type": "type_1"})

    def nudge(self, kind=followups.NUDGE_1, send_text=None):
        with patch("apps.inbox.services.send_text", side_effect=send_text or fake_send_text) as sent:
            result = followups.send(self.conversation.pk, kind)
        return result, sent


class NudgeTests(NudgeBase):
    def test_two_hours_after_our_question_one_nudge_built_from_the_facts(self):
        self.go(at(12, 15, 0))
        self.assertEqual(followups.due_now(), [])
        self.go(at(12, 15, 1))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])
        result, sent = self.nudge()
        self.assertEqual(result, "sent")
        self.assertEqual(sent.call_args.args[2], FIRST_NUDGE)
        payload = sent.call_args.kwargs["payload"]
        self.assertEqual((payload["source"], payload["nudge"]), (transcript.ASSISTANT, 1))
        state = self.state()
        self.assertEqual((state.nudges, state.nudged_at), (1, at(12, 15, 1)))
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.nudge()[0], "not due")

    def test_in_the_customers_language_and_generic_when_the_type_or_business_is_unknown(self):
        self.go(at(12, 15, 1))
        self.set_state(language="ar")
        self.assertIn("اخترت لك محلّين من Type 1 يناسبان نشاطك (vape shop)", self.nudge()[1].call_args.args[2])
        # Again from the start: the nudge taken back, nothing known of the type or the business.
        Message.objects.filter(payload__nudge=1).delete()
        self.set_state(nudges=0, nudged_at=None, language="en", facts={"for_client": False})
        self.assertEqual(
            self.nudge()[1].call_args.args[2], "Hi Ahmed, just checking in — shall I hold a slot for you to see the shops today or tomorrow?"
        )

    def test_inside_the_window_only_and_between_10_and_18(self):
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=at(12, 15, 10))
        self.go(at(12, 15, 1))
        self.assertEqual(followups.due_now(), [])
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=at(13, 13))
        self.go(at(12, 18, 5))
        self.assertEqual(followups.due_now(), [])
        self.go(at(13, 10, 0))  # the next morning, the window still open
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])
        self.go(at(13, 12, 51))  # nine minutes of window left
        self.assertEqual(followups.due_now(), [])

    def test_only_after_the_assistants_own_question_that_reached_whatsapp(self):
        self.go(at(12, 15, 1))
        Message.objects.filter(pk=self.question.pk).update(status=Message.Status.FAILED)
        self.assertEqual(followups.due_now(), [])
        Message.objects.filter(pk=self.question.pk).update(status=Message.Status.SENT, body="Great, see you then.")
        self.assertEqual(followups.due_now(), [])
        Message.objects.filter(pk=self.question.pk).update(body="A vape shop, got it. What size do you need?")
        self.assertEqual(len(followups.due_now()), 1)
        _outbound(self.conversation, self.agent, Message.Kind.TEXT, "Hi, Nabiha here. What size do you need?", {}, created_at=at(12, 13, 2))
        self.assertEqual(followups.due_now(), [])  # a colleague wrote since

    def test_not_with_a_visit_open_after_not_now_or_after_already_rented(self):
        self.go(at(12, 15, 1))
        appointment = LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", note="may come")
        self.assertEqual(followups.due_now(), [])
        appointment.delete()
        self.set_state(followup_asked_at=at(12, 13, 1))
        self.assertEqual(followups.due_now(), [])
        self.set_state(followup_asked_at=None, facts={"already_rented": True})
        self.assertEqual(followups.due_now(), [])
        self.set_state(facts={})
        self.assertEqual(len(followups.due_now()), 1)

    def test_the_morning_after_one_last_nudge_with_todays_two_free_slots_then_nothing(self):
        self.go(at(12, 15, 1))
        self.nudge()
        self.go(at(13, 10, 29))
        self.assertEqual(followups.due_now(), [])
        self.go(at(13, 10, 30))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_2)])
        result, sent = self.nudge(followups.NUDGE_2)
        self.assertEqual(result, "sent")
        self.assertEqual(
            sent.call_args.args[2], "Good morning Ahmed, would today suit you to see the shops? I can hold a slot at 11:30 AM or 1:30 PM."
        )
        self.assertEqual(sent.call_args.kwargs["payload"]["nudge"], 2)
        self.assertEqual(self.state().nudges, 2)
        self.go(at(13, 10, 45))
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.nudge(followups.NUDGE_2)[0], "not due")

    def test_no_last_nudge_once_they_answered_at_noon_or_with_no_slot_left(self):
        self.go(at(12, 15, 1))
        self.nudge()
        self.go(at(13, 12, 0))
        self.assertEqual(followups.due_now(), [])  # "good morning" no longer holds
        self.go(at(13, 10, 30))
        # Every slot of Tuesday is another client's: the office is full today.
        for index, slot in enumerate(hours.slot_grid(dt.date(2026, 10, 13))):
            LeadAiAppointment.objects.create(conversation=self.other(f"97150999{index:04d}"), status="confirmed", starts_at=slot)
        self.assertEqual(followups.due_now(), [])
        LeadAiAppointment.objects.all().delete()
        self.assertEqual(len(followups.due_now()), 1)
        self.inbound("Will tell you", seconds_ago=0)
        self.assertEqual(followups.due_now(), [])  # they answered

    def test_a_nudge_that_did_not_go_is_given_back(self):
        self.go(at(12, 15, 1))
        result, _ = self.nudge(send_text=SendBlocked("The 24-hour window is closed."))
        self.assertTrue(result.startswith("not sent"), result)
        self.assertEqual((self.state().nudges, self.state().nudged_at), (0, None))

    def test_never_while_stopped_paused_or_handed_to_a_person(self):
        self.go(at(12, 15, 1))
        for field in ("stopped_at", "paused_at", "handed_over_at", "not_interested_at"):
            with self.subTest(field=field):
                self.set_state(**{field: NOW})
                self.assertEqual(followups.due_now(), [])
                self.set_state(**{field: None})


class GeneralNudgeTests(GeneralBase):
    def test_a_general_chat_is_never_nudged(self):
        self.inbound("Yes I need a flat", seconds_ago=60 * 60)
        self.ours("Sure. What size do you need?", minutes_ago=59)
        Conversation.objects.filter(pk=self.conversation.pk).update(
            last_message_at=NOW - dt.timedelta(minutes=59), session_expires_at=at(13, 13)
        )
        LeadAiChatState.for_conversation(self.conversation)
        self.clock.return_value = at(12, 15, 1)
        self.assertEqual(followups.due_now(), [])


# E. The customer's answer to Template B ----------------------------------------------------------------


class TemplateBAnswerTests(FollowUpBase):
    def setUp(self):
        super().setUp()
        self.go(THURSDAY)
        self.send()
        self.go(THURSDAY + dt.timedelta(minutes=5))
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=THURSDAY + dt.timedelta(hours=24))

    def test_yes_book_a_viewing_from_someone_new_gets_for_yourself_or_a_client(self):
        outcome, calls, _, _ = self.turn(self.tap("Yes, book a viewing"), [])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), rules.line("for_whom", "en"))

    def test_yes_book_a_viewing_from_an_end_user_gets_two_free_slots(self):
        self.set_state(facts={"for_client": False, "business_activity": "vape shop"})
        message = self.tap("Yes, book a viewing")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(calls, [])
        # An hour ahead at least (hours.OFFER_LEAD): it is 2:05 PM.
        self.assertEqual(self.body(outcome), "I can hold a slot for you today at 3:30 PM or 5:30 PM — which is better?")
        self.assertEqual((self.actions(message)["rule"], self.actions(message)["shop_step"]), ("book_tap:", "slots"))

    def test_not_now_asks_to_check_back(self):
        outcome, calls, _, _ = self.turn(self.tap("Not now"), [])
        self.assertEqual((calls, self.body(outcome)), ([], rules.line("check_back", "en")))
        self.assertIsNotNone(self.state().followup_asked_at)

    def test_a_question_to_it_reads_template_b_as_the_campaign_message(self):
        self.turn(self.inbound("How much is a medium shop?"), [shop_answer("Type 2 is from AED 48,000 a year. What business is it for?")])
        context = self.requests[0][0][1]["content"]
        self.assertIn("CAMPAIGN MESSAGE: (sent Thu 15 Oct 2:00 PM) Hi {{1}}, just a quick follow-up.", context)
        self.assertIn("campaign template: intl_city_shops_followup (MARKETING)", context)
        conversation = context.split("CONVERSATION (oldest first):\n", 1)[1].split("\n\nNEW SINCE", 1)[0]
        rows = [json.loads(line) for line in conversation.splitlines()]
        self.assertEqual([row["from"] for row in rows if "quick follow-up" in row["text"]], ["campaign"])
