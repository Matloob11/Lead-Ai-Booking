"""Batch 2b review: the findings the review of stages A and B confirmed, each pinned here.

- A. the per-chat reply caps count replies, not the rows a reply is made of (a type's video,
  photos and card are one reply);
- B. the follow-up sweep never lets chats that cannot be due hide one that is;
- C. a Template B or nudge refused for "Insufficient credits" is tried again once credit is back;
- D. the check-back's Template B goes only while nothing happened since the customer asked for it;
- E. a booking moves or closes only the assistant's own "Viewing/Meeting" to-do (board C9, T55).

The fakes are test_assistant's; the shops chat is test_shops_playbook's (lead 555; its
campaign's template went out Monday 12 October 2026 at 12:00 Dubai; the clock moves).
"""

import datetime as dt
import shutil
import tempfile
from unittest.mock import patch

from django.test import override_settings

from apps.campaigns.models import CampaignRecipient
from apps.gateway.client import AlotsError
from apps.gateway.models import CreditState
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import followups, shop_media, tasks
from apps.leadai.assistant import engine, rules, transcript
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiCrmStep, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, TUESDAY_5PM, _outbound, fake_send_template, fake_send_text
from apps.leadai.tests.test_follow_ups import CHECK_DAY, THURSDAY, FollowUpBase, NudgeBase, at, failed_send, template_b
from apps.leadai.tests.test_reminders_crm import T2, CrmBase, FakeBitrix, todo
from apps.leadai.tests.test_shop_flow import button_reply, list_reply
from apps.leadai.tests.test_shop_media import jpeg, mp4
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, ShopsBase, shop_answer

CLIENT = "apps.gateway.client.AlotsClient"


# A. The reply caps ------------------------------------------------------------------------------------


class CapCountsRepliesTests(ShopsBase):
    """A type tapped sends its video, its photos and its card: one reply, not six rows of the cap."""

    def setUp(self):
        super().setUp()
        media_root = tempfile.mkdtemp(prefix="leadai-review-")
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media_root)
        override.enable()
        self.addCleanup(override.disable)
        for target in ("apps.inbox.events.publish_message", "apps.inbox.events.publish_status", "apps.inbox.services.publish_message"):
            self.stub(target)
        pause = patch.object(shop_media, "SEND_PAUSE", 0)
        pause.start()
        self.addCleanup(pause.stop)
        # Type 2 as the build pack has it: one video and four photos.
        shop_media.add("type_2", "tour.mp4", mp4("avc1", "mp4a"))
        for seed in range(1, 5):
            shop_media.add("type_2", f"{seed}.jpg", jpeg(seed))
        self.wamid = 0

    def gateway(self):
        def answer(*args, **kwargs):
            self.wamid += 1
            return {"messages": [{"id": f"wamid.review{self.wamid}"}]}

        def upload(client, phone_number_id, file_obj, filename, mime_type):
            return f"media-{filename}"

        return patch.multiple(CLIENT, upload_media=upload, send_media=answer, send_interactive=answer)

    def test_book_viewing_after_a_types_media_is_still_answered(self):
        self.set_state(facts={"for_client": False})
        tap = list_reply(self, "type_2", "Type 2 – Medium")
        self.turn(tap, [])
        turn = LeadAiTurn.objects.get(inbound=tap)
        with self.gateway():
            sent = shop_media.send_type(self.conversation.pk, "type_2", turn.pk, "en")
        self.assertEqual((sent["files"], sent["stopped"]), (5, ""))
        self.assertEqual(Message.objects.filter(direction="out", payload__source=transcript.ASSISTANT).count(), 6)
        self.later(2)
        outcome, calls, _, _ = self.turn(button_reply(self, "lai-shop:book:type_2", "Book viewing"), [])
        self.assertEqual(outcome.reason, "")
        self.assertIn("which is better?", self.body(outcome))
        self.assertFalse(LeadAiAlert.objects.filter(kind="cap").exists())

    def test_the_cap_still_counts_every_reply(self):
        for minutes in range(engine.CAP_PER_HOUR):
            self.ours("Sure.", minutes_ago=50 - minutes, turn=9000 + minutes)
        outcome, calls, _, _ = self.turn(self.inbound("and?"), [shop_answer("ok")])
        self.assertEqual((outcome.reason, calls), ("reply limit reached", []))


# B. The sweep looks past chats that cannot be due -----------------------------------------------------


class SweepStarvationTests(FollowUpBase):
    """Chats that stay not due for days never fill the sweep's window (followups.SCAN)."""

    def setUp(self):
        super().setUp()
        scan = patch.object(followups, "SCAN", 3)
        scan.start()
        self.addCleanup(scan.stop)
        self.go(THURSDAY)

    def shops_chat(self, wa_id, number=None, status=Message.Status.DELIVERED, **state):
        """Another quiet chat of the same shops campaign, its template sent with ours on Monday."""
        conversation = Conversation.objects.create(
            number=number or self.number, contact=Contact.objects.create(wa_id=wa_id), last_message_at=self.campaign_message.created_at
        )
        LeadAiChat.objects.create(conversation=conversation, active=True, crm_entity="lead", crm_id=556)
        CampaignRecipient.objects.create(campaign=self.campaign, phone=wa_id, name="Sara Ali", conversation=conversation, crm_lead_id=556)
        Message.objects.create(
            conversation=conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, template=self.template,
            body="Hi Sara, shops are available in International City. Interested?", status=status,
            created_at=self.campaign_message.created_at,
        )
        if state:
            LeadAiChatState.objects.create(conversation=conversation, **state)
        return conversation

    def other_number(self):
        from apps.catalog.models import WabaNumber

        return WabaNumber.objects.create(phone_number="971500000009", phone_number_id="pn9", waba_business_id="waba9")

    def test_chats_on_a_number_without_template_b_never_hide_a_due_one(self):
        pending = self.other_number()
        for index in range(4):
            self.shops_chat(f"9715022200{index:02d}", number=pending)
        due = self.shops_chat("971502229999")
        found = dict(followups.due_now())
        self.assertEqual(found, {self.conversation.pk: followups.REENGAGE, due.pk: followups.REENGAGE})

    def test_campaign_templates_that_failed_never_hide_a_due_one(self):
        for index in range(4):
            self.shops_chat(f"9715033300{index:02d}", status=Message.Status.FAILED)
        due = self.shops_chat("971503339999")
        self.assertIn(due.pk, dict(followups.due_now()))

    def test_paused_or_stopped_chats_never_hide_a_due_check_back(self):
        # They said "Not now" and yes to the check-back on Monday; a month on, a broker's chat
        # stays paused (its date is never cleared) and a stopped one too.
        self.go(CHECK_DAY)
        for index in range(2):
            self.shops_chat(f"9715044400{index:02d}", paused_at=NOW, followup_due_at=CHECK_DAY)
            self.shops_chat(f"9715044410{index:02d}", handed_over_at=NOW, followup_due_at=CHECK_DAY)
        due = self.shops_chat("971504449999", followup_due_at=CHECK_DAY)
        self.assertEqual(followups.due_now(), [(due.pk, followups.CHECK_BACK)])

    def test_the_sweep_reads_on_past_a_window_of_chats_it_turned_down(self):
        # A reaction to the campaign's template is a reply of sorts: those chats are never due.
        for index in range(4):
            chat = self.shops_chat(f"9715055500{index:02d}")
            Message.objects.filter(conversation=chat).update(reactions={"x": "👍"})
        due = self.shops_chat("971505559999")
        self.assertIn(due.pk, dict(followups.due_now()))


# C. "Insufficient credits" is tried again ------------------------------------------------------------


def no_credit(conversation, agent, template, values, *args, payload=None, **kwargs):
    """What inbox.services.send_template leaves when the wallet is empty: the row, FAILED, and
    the chat's last message stamped with it (services._touch)."""
    from django.utils import timezone

    failed_send(conversation, template, payload)
    Message.objects.filter(conversation=conversation, payload__attempt=(payload or {}).get("attempt")).update(created_at=timezone.now())
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=timezone.now())
    raise AlotsError("Insufficient credits. Available credits are 1.8829")


class NoCreditTemplateBTests(FollowUpBase):
    def test_template_b_refused_for_credit_is_due_again_once_credit_is_back(self):
        self.go(THURSDAY)
        result, _ = self.send(send_template=no_credit)
        self.assertTrue(result.startswith("not sent"), result)
        self.go(THURSDAY + dt.timedelta(hours=1))  # topped up meanwhile
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.REENGAGE)])
        result, sent = self.send()
        self.assertEqual(result, "sent")
        sent.assert_called_once()


class NoCreditNudgeTests(NudgeBase):
    def test_a_nudge_refused_for_credit_is_due_again(self):
        self.go(at(12, 15, 1))

        def refused(conversation, agent, body, reply_to=None, payload=None):
            from django.utils import timezone

            Message.objects.create(
                conversation=conversation, direction="out", kind="text", body=body, payload=payload or {}, status=Message.Status.FAILED
            )
            Conversation.objects.filter(pk=conversation.pk).update(last_message_at=timezone.now())
            raise AlotsError("Insufficient credits. Available credits are 0.2")

        result, _ = self.nudge(send_text=refused)
        self.assertTrue(result.startswith("not sent"), result)
        self.go(at(12, 15, 30))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])
        self.assertEqual(self.nudge()[0], "sent")


# D. The check-back goes only into a chat nothing happened in ----------------------------------------


class CheckBackSinceTests(FollowUpBase):
    def setUp(self):
        super().setUp()
        self.tap("Not now", seconds_ago=60 * 60)
        self.ours(rules.line("check_back", "en"), minutes_ago=59)
        self.inbound("Yes", seconds_ago=55 * 60)
        self.ours(rules.line("check_back_yes", "en"), minutes_ago=54)
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=NOW - dt.timedelta(minutes=54), last_inbound_at=NOW)
        self.set_state(followup_due_at=CHECK_DAY, language="en")

    def test_a_colleague_handling_the_chat_since_gets_no_template_b_in_it(self):
        self.go(at(22, 12))
        self.inbound("Is the Type 2 shop still free?", seconds_ago=0)
        _outbound(self.conversation, self.agent, Message.Kind.TEXT, "Yes it is, Nabiha here.", {}, created_at=at(22, 12, 5))
        self.go(CHECK_DAY)
        self.assertEqual(followups.due_now(), [])
        result, sent = self.send(followups.CHECK_BACK)
        self.assertEqual(result, "not due")
        sent.assert_not_called()

    def test_a_thank_you_after_the_yes_keeps_the_check_back(self):
        self.inbound("ok thanks 👍", seconds_ago=-5 * 60)  # five minutes after the check-back was planned
        self.go(CHECK_DAY)
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.CHECK_BACK)])
        self.assertEqual(self.send(followups.CHECK_BACK)[0], "sent")

    def test_the_customer_coming_back_by_themselves_ends_the_wait_and_lets_a_nudge_go(self):
        self.go(at(26, 13))
        message = self.inbound("Actually, what does Type 3 cost?", seconds_ago=0)
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=at(27, 13))
        self.turn(message, [shop_answer("Type 3 is from AED 80,000 a year. What business is it for?")])
        self.assertIsNone(self.state().followup_due_at)
        self.go(at(26, 15, 1))
        self.assertEqual(dict(followups.due_now()).get(self.conversation.pk), followups.NUDGE_1)


# E. The assistant's own to-do --------------------------------------------------------------------------


class OwnTodoTests(CrmBase):
    """The tool's booking action moves or closes the lead's NEWEST open "Viewing/Meeting" to-do:
    it is used only while that to-do is the assistant's own (or there is none)."""

    def test_a_reschedule_moves_the_assistants_own_todo_not_the_newest(self):
        bitrix = FakeBitrix()
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)  # the tool moves the lead to 10 and plans 901
        self.assertEqual((bitrix.stage, appointment.crm_todo_id), ("10", 901))
        # A person edits the lead while it sits in 10: BP 235 plans 902, due now (board C4).
        bitrix.todos[902] = todo(days_old=0)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(starts_at=T2)
        self.sync(bitrix, appointment, "rescheduled", revision=2)
        self.assertEqual(bitrix.todos[901]["deadline"], T2.isoformat())
        self.assertEqual(bitrix.todos[902]["deadline"], "now")
        self.assertEqual(appointment.crm_todo_id, 901)
        moved = bitrix.posted[-1]
        self.assertNotIn("booking", moved)  # the meeting time alone: the tool's booking action would take 902
        self.assertEqual(moved["fields"], {"UF_CRM_1731838813769": T2.isoformat()})
        self.assertIn("MEETING RESCHEDULED", moved["comment"])
        # The customer cancels: our own to-do is closed, the one BP 235 planned is left alone.
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(status="cancelled")
        self.sync(bitrix, appointment, "cancelled", revision=3)
        self.assertTrue(bitrix.todos[901]["done"])
        self.assertFalse(bitrix.todos[902]["done"])
        self.assertIsNone(appointment.crm_todo_id)
        self.assertIn("MEETING CANCELLED", bitrix.comments[-1])

    def test_an_older_todo_is_never_taken_for_the_one_our_booking_plans(self):
        bitrix = FakeBitrix(todos={700: todo("2026-10-15T15:00:00+04:00")})
        appointment = self.make()
        self.sync(bitrix, appointment, "confirmed", revision=1)
        self.assertEqual(bitrix.todos[700]["deadline"], "2026-10-15T15:00:00+04:00")
        # The meeting time alone, with the comment; no booking action, so no stage move and no to-do.
        self.assertEqual([("booking" in body, body.get("fields")) for body in bitrix.posted], [(False, {"UF_CRM_1731838813769": TUESDAY_5PM.isoformat()})])
        self.assertEqual(bitrix.stage, "IN_PROCESS")
        self.assertIsNone(appointment.crm_todo_id)  # our heads-up an hour before covers the meeting
        self.assertIn("did not plan", bitrix.comments[-1])
        self.assertFalse(LeadAiCrmStep.objects.filter(step__startswith=tasks.BOOKING_STEP).exists())
        self.assertFalse(tasks._booked_by_us(appointment))

    def test_a_booking_whose_answer_never_came_is_ours_and_sent_again(self):
        bitrix = FakeBitrix()
        appointment = self.make()
        calls = []

        def saved_then_timed_out(body):
            calls.append(body)
            answer = FakeBitrix.tool(bitrix, body)
            if len(calls) == 1:
                from apps.leadai.assistant import crm_fields

                raise crm_fields.FieldsError("Lead fields tool unreachable: ReadTimeout")
            return answer

        with patch("apps.crmlink.client.call", side_effect=bitrix), patch("apps.leadai.assistant.crm_fields.post", side_effect=saved_then_timed_out):
            result = tasks.sync_appointment_crm.apply(args=[appointment.pk, "confirmed", False, 1])
        self.assertTrue(result.successful())
        appointment.refresh_from_db()
        self.assertEqual([body["booking"]["event"] for body in calls], ["confirmed", "confirmed"])
        self.assertEqual(appointment.crm_todo_id, 901)
        self.assertEqual([i for i, t in bitrix.todos.items() if not t["done"]], [901])
        self.assertTrue(tasks._booked_by_us(appointment))


# F. The script correction may fail; the first answer still goes (correctness-F4) --------------------


class ScriptCorrectionFailsTests(ShopsBase):
    def test_a_correction_cut_off_never_fails_the_turn(self):
        from apps.leadai.assistant import openai_client

        message = self.inbound("مجھے انٹرنیشنل سٹی میں دکان چاہیے۔")
        first = shop_answer("Is the shop for yourself, or are you checking for a client?", language="ur_latin")
        calls = []

        def model(messages, schema_, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return first
            raise openai_client.AssistantError("too_long", "the answer was cut off", kind="content")

        with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model), patch(
            "apps.inbox.services.send_text", side_effect=fake_send_text
        ), self.captureOnCommitCallbacks(execute=True):
            outcome = engine.run_turn(message.pk, first_queued_at=(NOW - dt.timedelta(minutes=1)).isoformat())
        self.assertEqual(len(calls), 2)
        self.assertEqual(outcome.status, LeadAiTurn.Status.REPLIED)
        self.assertEqual(self.body(outcome), "Is the shop for yourself, or are you checking for a client?")
        self.assertEqual(self.actions(message)["script_fix"], "failed")
        self.assertEqual(LeadAiTurn.objects.get(inbound=message).calls, 1)
        self.assertFalse(LeadAiAlert.objects.filter(kind="ai_error").exists())


# G. The licence copy promised for later (correctness-F5) -------------------------------------------


class LicenceLaterTests(ShopsBase):
    def setUp(self):
        super().setUp()
        from apps.leadai.assistant import shop_flow

        self.set_state(facts={"for_client": False, "licence_kind": "ded", "trade_licence": "yes"}, licence_asked_at=NOW - dt.timedelta(minutes=5))
        self.ours(rules.line("licence_copy", "en"), minutes_ago=5, shop_step=shop_flow.LICENCE_ASK)

    def photo(self, seconds_ago=20):
        from apps.inbox.models import MediaAsset

        asset = MediaAsset.objects.create(mime_type="image/jpeg", file_name="licence.jpg", size_bytes=10, downloaded=False)
        return self.inbound("", kind=Message.Kind.IMAGE, media=asset, seconds_ago=seconds_ago)

    def test_ill_send_it_later_keeps_the_request_open_for_the_copy(self):
        message = self.inbound("Sure, I'll send it later")
        outcome, calls, _, _ = self.turn(message, [shop_answer("No problem, send it whenever you are ready.")])
        self.assertEqual(len(calls), 1)  # the model's, no deferral line and no "Not now" rule
        self.assertEqual(self.body(outcome), "No problem, send it whenever you are ready.")
        state = self.state()
        self.assertIsNone(state.licence_closed_at)
        self.assertNotIn("licence_copy", state.facts)
        self.assertEqual(self.actions(message)["licence"], "later")
        self.assertFalse(LeadAiAppointment.objects.exists())
        # An hour on, the photo comes: it is the licence, thanked for, and goes to the lead.
        self.later(60)
        photo = self.photo()
        outcome, calls, _, _ = self.turn(photo, [])
        self.assertEqual(calls, [])
        self.assertTrue(self.body(outcome).startswith(rules.line("licence_thanks", "en")))
        state = self.state()
        self.assertEqual(state.facts["licence_copy"], "received")
        self.assertIsNone(state.handed_over_at)
        self.licence_delay.assert_called_once()

    def test_a_second_page_minutes_later_is_no_media_handover(self):
        self.turn(self.photo(), [])
        self.later(3)
        second = self.photo()
        outcome, calls, _, _ = self.turn(second, [shop_answer("", handover="media_received")])
        self.assertEqual((calls, outcome.reason), ([], "another page of the licence copy"))
        self.assertIsNone(self.state().handed_over_at)
        self.licence_delay.assert_called_once()  # the lead keeps the first file
        # Later on, a photo is an ordinary photo again.
        self.later(30)
        third = self.photo()
        outcome, calls, _, _ = self.turn(third, [shop_answer("", handover="media_received")])
        self.assertEqual(len(calls), 1)


# H. The inbox-wide opt-out reads "الغاء" as a stop only in answer to a campaign ----------------------


class InboxOptOutWordsTests(FollowUpBase):
    """correctness-F6, regressions-F8, safety-F4, and the transferred Lead AI chat (regressions-F3,
    safety-F1, correctness-F9)."""

    def setUp(self):
        super().setUp()
        for target in ("apps.leadai.tasks.assistant_turn.apply_async", "apps.leadai.tasks.handle_reminder_tap.apply_async"):
            self.stub(target)

    def customer(self, conversation, body, kind="text", payload=None):
        with self.captureOnCommitCallbacks(execute=True):
            return Message.objects.create(conversation=conversation, direction="in", kind=kind, body=body, payload=payload or {}, status="received")

    def agents_chat(self, wa_id):
        return Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id=wa_id))

    def test_a_bare_cancel_to_an_agents_message_blocks_nothing(self):
        from apps.leadai import optout

        chat = self.agents_chat("971507770001")
        _outbound(chat, self.agent, Message.Kind.TEXT, "Your viewing is confirmed for tomorrow at 5 PM.", {})
        for word in ("إلغاء", "الغاء", "block", "band karo", "please الغاء"):
            with self.subTest(word):
                self.customer(chat, word)
                self.assertFalse(optout.is_blocked("971507770001"))
        self.customer(chat, "STOP")  # never ambiguous
        self.assertTrue(optout.is_blocked("971507770001"))

    def test_a_bare_cancel_answering_a_campaign_is_its_unsubscribe(self):
        from apps.leadai import optout

        chat = self.agents_chat("971507770002")
        CampaignRecipient.objects.create(campaign=self.campaign, phone="971507770002", conversation=chat)
        Message.objects.create(
            conversation=chat, direction="out", kind=Message.Kind.TEMPLATE, template=self.template, body="Hi, shops are available.",
            status=Message.Status.DELIVERED,
        )
        self.customer(chat, "الغاء")
        self.assertTrue(optout.is_blocked("971507770002"))

    def test_a_cancel_to_the_reminder_of_a_chat_moved_to_the_inbox_blocks_nothing(self):
        from apps.leadai import optout

        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)
        _outbound(self.conversation, None, Message.Kind.INTERACTIVE, "Reminder: your viewing is at 5 PM.", {"source": "leadai_reminder"})
        self.customer(self.conversation, "الغاء")
        self.assertFalse(optout.is_blocked(self.contact.wa_id))

    def test_a_stop_in_a_transferred_lead_ai_chat_reaches_the_registry(self):
        from apps.leadai import optout

        Conversation.objects.filter(pk=self.conversation.pk).update(linked_conversation=self.other())
        self.customer(self.conversation, "STOP")
        self.assertTrue(optout.is_blocked(self.contact.wa_id))

    def test_a_stop_messages_tap_in_any_lead_ai_chat_reaches_the_registry(self):
        from apps.leadai import lane, optout

        lane.mark_campaign(self.campaign, playbook=lane.GENERAL)  # a general chat: there the tap is the model's
        self.customer(self.conversation, "Stop messages", kind="button", payload={"button": {"text": "Stop messages"}})
        self.assertTrue(optout.is_blocked(self.contact.wa_id))

    def test_typed_words_in_an_active_lead_ai_chat_are_still_the_turns(self):
        from apps.leadai import optout

        self.customer(self.conversation, "STOP")
        self.assertFalse(optout.is_blocked(self.contact.wa_id))


class OptOutImportTests(FollowUpBase):
    """safety-F3, correctness-F10, and typed versus tapped in the dry run."""

    def said(self, conversation, body, kind="text", payload=None, at=None):
        # Stored inside the test's transaction: the inbox signal's after-commit write never runs.
        return Message.objects.create(
            conversation=conversation, direction="in", kind=kind, body=body, payload=payload or {}, status="received", created_at=at or NOW
        )

    def run_import(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("leadai_optout_import", *args, stdout=out)
        return out.getvalue()

    def test_what_was_said_before_the_chat_came_onto_the_screen_counts(self):
        from apps.leadai import optout

        LeadAiChat.objects.filter(pk=self.chat.pk).update(created_at=NOW - dt.timedelta(days=30))
        self.said(self.conversation, "Unsubscribe", kind="button", payload={"button": {"text": "Unsubscribe"}}, at=NOW - dt.timedelta(days=120))
        text = self.run_import("--dry-run")
        self.assertIn("tapped: 1", text)
        self.run_import()
        self.assertTrue(optout.is_blocked(self.contact.wa_id))

    def test_typed_before_counts_typed_since_is_the_turns(self):
        from apps.leadai.models import LeadAiOptOut

        LeadAiChat.objects.filter(pk=self.chat.pk).update(created_at=NOW - dt.timedelta(days=30))
        self.said(self.conversation, "stop", at=NOW - dt.timedelta(days=1))  # since: the turn judged it (not stopped)
        self.assertIn("would add 0 phone(s)", self.run_import("--dry-run"))
        self.said(self.conversation, "STOP", at=NOW - dt.timedelta(days=60))  # before it was a Lead AI chat
        text = self.run_import("--dry-run")
        self.assertIn("typed: 1", text)
        self.run_import()
        self.assertEqual(LeadAiOptOut.objects.get().reason, "Typed: STOP")

    def test_a_transferred_chat_is_read_like_any_other(self):
        from apps.leadai import optout

        Conversation.objects.filter(pk=self.conversation.pk).update(linked_conversation=self.other())
        self.said(self.conversation, "Stop sending")
        self.run_import()
        self.assertTrue(optout.is_blocked(self.contact.wa_id))

    def test_a_bare_cancel_counts_only_as_the_answer_to_a_campaign(self):
        from apps.leadai import optout

        answered = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971508880001"))
        CampaignRecipient.objects.create(campaign=self.campaign, phone="971508880001", conversation=answered)
        Message.objects.create(conversation=answered, direction="out", kind="template", template=self.template, body="Hi", status="delivered")
        self.said(answered, "الغاء")
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971508880002"))
        _outbound(other, self.agent, Message.Kind.TEXT, "Your renewal is due next week.", {})
        self.said(other, "الغاء")
        text = self.run_import("--dry-run")
        self.assertIn("typed, answering a campaign: 1", text)
        self.run_import()
        self.assertTrue(optout.is_blocked("971508880001"))
        self.assertFalse(optout.is_blocked("971508880002"))


# I. What the Bitrix lead says holds a follow-up (regressions-F4, safety-F2) --------------------------


@override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
class BitrixHoldsFollowUpsTests(FollowUpBase):
    def lead(self, **fields):
        row = {"ID": "555", "STATUS_ID": "IN_PROCESS", "ASSIGNED_BY_ID": "88", **fields}
        return patch("apps.crmlink.client.call", side_effect=lambda method, payload=None: row if method == "crm.lead.get" else True)

    def test_a_persons_opt_out_in_bitrix_holds_template_b_and_blocks_the_phone(self):
        from apps.leadai import optout

        self.go(THURSDAY)
        with self.lead(UF_CRM_A7_WA_OPT_OUT="2482"), self.captureOnCommitCallbacks(execute=True):
            result, sent = self.send()
        self.assertEqual(result, "the Bitrix lead says stop")
        sent.assert_not_called()
        self.assertIsNotNone(self.state().stopped_at)
        self.assertTrue(optout.is_blocked(self.contact.wa_id))
        self.assertIsNone(self.state().template_b_sent_at)

    def test_handed_to_an_agent_in_bitrix_holds_it_too(self):
        self.go(THURSDAY)
        with self.lead(UF_CRM_A7_BOT_STATUS="2478"), self.captureOnCommitCallbacks(execute=True):
            result, sent = self.send()
        self.assertEqual(result, "the Bitrix lead says handed")
        sent.assert_not_called()
        self.assertIsNotNone(self.state().paused_at)

    def test_a_lead_that_cannot_be_read_holds_it_until_the_next_sweep(self):
        from apps.crmlink import client

        self.go(THURSDAY)
        with patch("apps.crmlink.client.call", side_effect=client.BitrixError("crm.lead.get: timed out")):
            result, sent = self.send()
        self.assertIn("tried again later", result)
        sent.assert_not_called()
        self.assertFalse(LeadAiChatState.objects.filter(conversation=self.conversation, template_b_sent_at__isnull=False).exists())  # nothing claimed
        with self.lead(UF_CRM_A7_BOT_STATUS="2476"):  # Qualifying: ours, nothing against it
            result, sent = self.send()
        self.assertEqual(result, "sent")


# J. The smaller ones ------------------------------------------------------------------------------------


class SmallFollowUpTests(NudgeBase):
    def test_invited_twice_no_nudge_invites_a_third_time(self):  # correctness-F7
        self.go(at(12, 15, 1))
        self.set_state(invites=2)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.nudge()[0], "not due")
        self.set_state(invites=1)
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])


class TemplateBAsTheCampaignTests(FollowUpBase):
    def test_a_campaign_sent_with_template_b_gets_no_second_copy(self):  # regressions-F10
        Message.objects.filter(pk=self.campaign_message.pk).update(template=self.template_b)
        self.campaign.template = self.template_b
        self.campaign.save(update_fields=["template"])
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.send()[0], "not due")


class ResumeReleasesSpamTests(ShopsBase):
    def test_resume_on_a_spam_stop_takes_the_phone_off_the_registry(self):  # correctness-F12
        from apps.leadai import optout

        self.turn(self.inbound("Join our crypto group now, forward to 10 friends"), [shop_answer("", send=False, opt_out="spam")])
        self.assertTrue(optout.is_blocked(self.contact.wa_id))
        alert = LeadAiAlert.objects.get(kind="opt_out")
        self.assertIn("opt-out registry", alert.text)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.conversation.pk}/resume-ai/").status_code, 200)
        self.assertFalse(optout.is_blocked(self.contact.wa_id))
        self.assertIsNone(self.state().stopped_at)

    def test_resume_never_lifts_a_stop_the_customer_asked_for(self):
        from apps.leadai import optout

        self.turn(self.inbound("STOP"), [])
        self.client.force_login(self.agent)
        self.client.post(f"/api/leadai/chats/{self.conversation.pk}/resume-ai/")
        self.assertTrue(optout.is_blocked(self.contact.wa_id))


class ShopStepsThatNeverWentTests(ShopsBase):  # correctness-F13
    def test_a_list_the_gateway_refused_goes_again(self):
        Message.objects.create(
            conversation=self.conversation, direction="out", kind="interactive", body="Great! We have 3 types",
            payload={"source": "leadai_ai", "shop_list": True}, status=Message.Status.FAILED, created_at=NOW - dt.timedelta(minutes=10),
        )
        self.ours(rules.line("for_whom", "en"), minutes_ago=5)
        self.turn(self.inbound("For myself"), [shop_answer("Great. What business will the shop be for?", facts={"for_client": False})])
        self.assertEqual(self.sent_lists.call_count, 1)

    def test_a_type_whose_files_never_went_is_sent_whole_again(self):
        tap = list_reply(self, "type_2", "Type 2 – Medium")
        self.turn(tap, [])
        LeadAiTurn.objects.filter(inbound=tap).update(created_at=NOW)
        turn = self.media_delay.call_args.args[2]
        # The media task's video was refused (no credit) and nothing else went.
        self.ours("", minutes_ago=-1, turn=turn, shop_media="type_2", shop_media_id=1)
        Message.objects.filter(payload__shop_media_id=1).update(status=Message.Status.FAILED)
        self.later(40)
        self.turn(list_reply(self, "type_2", "Type 2 – Medium"), [])
        self.assertEqual(self.media_delay.call_args.args[4], True)


class BotStatusHeadersTests(ShopsBase):  # safety-F5
    def test_odd_signature_headers_are_refused_never_a_server_error(self):
        import time as clock

        from django.test import Client

        http = Client(enforce_csrf_checks=True)
        fresh = str(int(clock.time()))
        cases = (
            {"HTTP_X_LEADAI_TS": "²", "HTTP_X_LEADAI_SIGN": "0" * 64},
            {"HTTP_X_LEADAI_TS": "9" * 5000, "HTTP_X_LEADAI_SIGN": "0" * 64},
            {"HTTP_X_LEADAI_TS": fresh, "HTTP_X_LEADAI_SIGN": "é" * 64},
            {"HTTP_X_LEADAI_TS": fresh, "HTTP_X_LEADAI_SIGN": "0" * 64},
        )
        for headers in cases:
            with self.subTest(headers={key: value[:8] for key, value in headers.items()}):
                response = http.post("/api/leadai/bitrix/bot-status/", data=b'{"lead_id": 555}', content_type="application/json", **headers)
                self.assertEqual(response.status_code, 401)


# K. The customer's script: fixed phrases and the language kept (regressions-F5) ---------------------


class FixedPhrasesTests(ShopsBase):
    playbook = "general"

    def test_phrases_every_language_types_in_arabic_script_say_nothing_of_the_script(self):
        from apps.leadai.assistant import script

        for text in ("ان شاء الله", "إن شاء الله", "انشاءاللہ", "السلام عليكم", "السلام علیکم", "الحمد لله", "ماشاء الله", "جزاك الله خير", "جزاک اللہ", "شكرا جزيلا"):
            with self.subTest(text):
                # The English message before it decides: English letters (batch 2b gate: script.LATIN).
                self.assertEqual(script.customer_script(["I need a shop", text]), script.LATIN)
                self.assertEqual(script.customer_script([text]), "")  # alone, it says nothing of any script
        self.assertEqual(script.script_of("السلام عليكم I need a shop in International City"), "")
        self.assertEqual(script.script_of("السلام عليكم، أبحث عن محل في المدينة العالمية"), script.ARABIC)
        self.assertEqual(script.script_of("السلام علیکم، مجھے دکان چاہیے"), script.URDU)
        self.assertTrue(script.has_script("ان شاء الله", script.ARABIC))  # a reply in it is still in the script

    def test_inshallah_to_our_confirmation_keeps_the_chat_english(self):
        self.set_state(language="en")
        self.ours("Great, see you tomorrow at 5 PM at our office.", minutes_ago=3)
        message = self.inbound("ان شاء الله")
        outcome, calls, _, _ = self.turn(message, [shop_answer("See you tomorrow, Ahmed!")])
        self.assertEqual(len(calls), 1)  # nothing asked again in Arabic
        self.assertNotIn("line_language", self.actions(message))
        self.assertEqual(self.state().language, "en")

    def test_a_reply_that_stayed_english_keeps_the_chat_english(self):
        from apps.leadai.tests.test_script import ARABIC

        self.set_state(language="en")
        message = self.inbound(ARABIC)
        outcome, calls, _, _ = self.turn(message, [shop_answer("Welcome! What business will the shop be for?"), shop_answer("Welcome again!")])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.actions(message)["script_fix"], "kept")
        self.assertEqual(self.state().language, "en")  # what they read; code's own lines in this turn followed their script
