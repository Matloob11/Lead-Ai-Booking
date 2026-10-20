"""The co-pilot (assistant/copilot.py; Matloob 2026-10-20): the model's own words kept as a draft while a person has the
chat, the agent's Ask AI, the draft's fate, and the ordinary draft that goes out by itself after the setting's minutes."""

import datetime as dt
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.inbox.models import Message
from apps.leadai.assistant import copilot, engine
from apps.leadai.models import LeadAiChatState, LeadAiDraftOutcome, LeadAiSettings
from apps.leadai.tests.test_assistant import NOW, Base, answer


class DraftTextTests(TestCase):
    def test_a_figure_the_chat_lacks_and_an_availability_claim_go(self):
        text = copilot.draft_text(
            "The deposit is AED 5,000. We have a vacant studio in Spain Cluster ready for you. Our agent will confirm the rest.",
            "customer: what is the deposit?",
        )
        self.assertNotIn("5,000", text)
        self.assertNotIn("vacant studio", text)
        self.assertIn("Our agent will confirm the rest.", text)

    def test_kinds(self):
        for reason in ("customer_asked_human", "call_requested", "complaint_or_upset", "legal_visa_licence_contract", engine.BROKER):
            self.assertEqual(copilot.kind_for(reason), copilot.PERSON, reason)
        for reason in ("unclear", "", "media_received", "question_not_in_facts"):
            self.assertEqual(copilot.kind_for(reason), copilot.ORDINARY, reason)

    def test_remember_keeps_the_models_words_and_not_what_went_out(self):
        answer_dict = {"copilot_draft": "Our commission is one month's rent.", "copilot_context": "", "reply": "Let me connect you to our agent."}
        draft = copilot.remember(answer_dict, NOW, reason="unclear", language="en")
        self.assertEqual((draft["text"], draft["kind"], draft["by"]), ("Our commission is one month's rent.", copilot.ORDINARY, "assistant"))
        same = {"copilot_draft": "Let me connect you to our agent.", "copilot_context": "", "reply": "Let me connect you to our agent."}
        self.assertIsNone(copilot.remember(same, NOW, reason="unclear", language="en"))
        self.assertIsNone(copilot.remember({"copilot_draft": "", "reply": "x"}, NOW, reason="unclear", language="en"))


class DraftInTurnsTests(Base):
    def state(self):
        return LeadAiChatState.objects.get(conversation=self.conversation)

    def test_the_handover_turn_whose_words_went_out_keeps_no_draft(self):
        # The model's reply itself went to the customer: a draft of the same words would be noise for the agent.
        message = self.inbound("What is your commission for a shop?")
        self.turn(message, [answer("Our commission is one month's rent, paid at signing.", handover="unclear")])
        state = self.state()
        self.assertIsNotNone(state.handed_over_at)
        self.assertIsNone(state.draft)

    def test_a_turn_while_a_person_has_the_chat_keeps_the_models_answer_as_the_draft(self):
        first = self.inbound("I want to talk to a person", seconds_ago=120)
        self.turn(first, [answer("Sure, our agent will be with you.", handover="customer_asked_human")])
        self.assertIsNone(self.state().draft)
        second = self.inbound("Also, is parking included?")
        self.turn(second, [answer("Parking depends on the building; our agent confirms it at the viewing.")])
        draft = self.state().draft
        self.assertIsNotNone(draft)
        self.assertIn("Parking depends on the building", draft["text"])
        self.assertEqual(draft["kind"], copilot.PERSON)  # the chat's handover reason decides, not the question
        self.assertEqual(draft["reason"], "customer_asked_human")

    def test_the_draft_goes_when_an_agent_takes_the_chat_back(self):
        first = self.inbound("What is your commission?", seconds_ago=180)
        self.turn(first, [answer("One month's rent.", handover="unclear")])
        second = self.inbound("And the deposit?", seconds_ago=120)
        self.turn(second, [answer("The deposit is one month of rent.")])
        self.assertIsNotNone(self.state().draft)
        self.assertEqual(self.state().draft["kind"], copilot.ORDINARY)
        # An agent writes two minutes after the handover; the customer answers them; the clock moves on.
        Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEXT, body="Hi, Nabiha here. One month.",
            sent_by=self.agent, status=Message.Status.SENT, created_at=NOW + dt.timedelta(minutes=2),
        )
        self.clock.return_value = NOW + dt.timedelta(minutes=5)
        third = self.inbound("Ok thanks, noted")
        self.turn(third, [answer("You are welcome.")])
        state = self.state()
        self.assertIsNone(state.handed_over_at)
        self.assertIsNone(state.draft)


class DraftApiTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.agent)
        self.state = LeadAiChatState.for_conversation(self.conversation)
        self.draft = {"text": "One month's rent.", "at": NOW.isoformat(), "reason": "unclear", "kind": "ordinary", "language": "en", "question": "", "by": "assistant"}
        LeadAiChatState.objects.filter(pk=self.state.pk).update(draft=self.draft, handed_over_at=NOW, handover_reason="unclear")

    def test_the_chat_carries_the_draft(self):
        data = self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()
        self.assertEqual(data["lead_ai_ai"]["draft"]["text"], "One month's rent.")

    def test_used_as_it_was_and_edited(self):
        data = self.client.post(f"/api/leadai/chats/{self.conversation.pk}/draft/used/", {"text": "One month's rent."}, format="json").json()
        self.assertIsNone(data["lead_ai_ai"]["draft"])
        row = LeadAiDraftOutcome.objects.get()
        self.assertEqual((row.kind, row.agent_id, row.sent_text), (LeadAiDraftOutcome.Kind.SENT, self.agent.pk, "One month's rent."))
        LeadAiChatState.objects.filter(pk=self.state.pk).update(draft=self.draft)
        self.client.post(f"/api/leadai/chats/{self.conversation.pk}/draft/used/", {"text": "It is one month's rent, sir."}, format="json")
        self.assertEqual(LeadAiDraftOutcome.objects.latest("pk").kind, LeadAiDraftOutcome.Kind.EDITED)

    def test_dismiss_and_ask(self):
        data = self.client.post(f"/api/leadai/chats/{self.conversation.pk}/draft/dismiss/", {}, format="json").json()
        self.assertIsNone(data["lead_ai_ai"]["draft"])
        self.assertEqual(LeadAiDraftOutcome.objects.get().kind, LeadAiDraftOutcome.Kind.DISMISSED)
        with patch("apps.leadai.tasks.copilot_ask.delay") as delay, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/leadai/chats/{self.conversation.pk}/draft/ask/", {"question": "Is the deposit refundable?"}, format="json")
        self.assertEqual(response.status_code, 200)
        delay.assert_called_once_with(self.conversation.pk, "Is the deposit refundable?", self.agent.pk)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.conversation.pk}/draft/ask/", {"question": " "}, format="json").status_code, 400)

    def test_resume_ai_clears_the_draft(self):
        self.client.post(f"/api/leadai/chats/{self.conversation.pk}/resume-ai/", {}, format="json")
        self.assertIsNone(LeadAiChatState.objects.get(pk=self.state.pk).draft)

    def test_the_auto_send_minutes_are_an_ai_setting(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/leadai/settings/").json()["copilot_auto_send_minutes"], 15)
        response = self.client.put("/api/leadai/settings/", {"copilot_auto_send_minutes": "30"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(LeadAiSettings.load().copilot_auto_send_minutes, 30)
        response = self.client.put("/api/leadai/settings/", {"copilot_auto_send_minutes": "500"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("copilot_auto_send_minutes", response.json().get("errors", response.json()))


class AskTests(Base):
    def test_the_agents_question_becomes_a_draft_with_the_question_kept(self):
        self.inbound("Is the deposit refundable?", seconds_ago=60)
        completion = answer("Yes, the deposit is refundable at the end of the tenancy.")
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion) as call:
            draft = copilot.ask(self.conversation, "Is the deposit refundable?", self.agent.pk)
        self.assertEqual(call.call_args.kwargs["name"], "leadai_copilot")
        self.assertIn("THE AGENT ASKS: Is the deposit refundable?", call.call_args.args[0][1]["content"])
        self.assertEqual((draft["kind"], draft["by"], draft["question"]), (copilot.PERSON, "agent", "Is the deposit refundable?"))
        self.assertEqual(LeadAiChatState.objects.get(conversation=self.conversation).draft["text"], draft["text"])


class AutoSendTests(Base):
    def setUp(self):
        super().setUp()
        self.state = LeadAiChatState.for_conversation(self.conversation)
        self.settings_row = LeadAiSettings.load()
        self.sent = []
        patcher = patch("apps.inbox.services.send_text", side_effect=self.fake_send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_send(self, conversation, agent, body, reply_to=None, payload=None):
        self.sent.append((body, payload))
        return Message.objects.create(
            conversation=conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEXT, body=body, status=Message.Status.SENT,
            payload=payload or {}, created_at=timezone.now(),
        )

    def set_draft(self, minutes_ago=20, kind="ordinary", handed=True):
        draft = {"text": "The deposit is one month.", "at": (NOW - dt.timedelta(minutes=minutes_ago)).isoformat(), "reason": "unclear", "kind": kind, "language": "en", "question": "", "by": "assistant"}
        LeadAiChatState.objects.filter(pk=self.state.pk).update(
            draft=draft, handed_over_at=NOW - dt.timedelta(minutes=minutes_ago) if handed else None, handover_reason="unclear" if handed else ""
        )

    def test_an_ordinary_draft_nobody_touched_goes_out_after_the_minutes(self):
        self.set_draft(minutes_ago=20)
        self.assertEqual(copilot.sweep(NOW), 1)
        self.assertEqual(self.sent[0][0], "The deposit is one month.")
        self.assertEqual(self.sent[0][1]["copilot"], "auto")
        self.assertIsNone(LeadAiChatState.objects.get(pk=self.state.pk).draft)
        self.assertEqual(LeadAiDraftOutcome.objects.get().kind, LeadAiDraftOutcome.Kind.AUTO)

    def test_too_fresh_a_persons_draft_or_the_setting_off_hold_it(self):
        self.set_draft(minutes_ago=5)
        self.assertEqual(copilot.sweep(NOW), 0)
        self.set_draft(minutes_ago=20, kind="person")
        self.assertEqual(copilot.sweep(NOW), 0)
        self.set_draft(minutes_ago=20)
        LeadAiSettings.objects.filter(pk=1).update(copilot_auto_send_minutes=0)
        self.assertEqual(copilot.sweep(NOW), 0)
        self.assertEqual(self.sent, [])

    def test_somebody_writing_since_the_draft_holds_it(self):
        self.set_draft(minutes_ago=20)
        Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEXT, body="Nabiha here.",
            sent_by=self.agent, status=Message.Status.SENT, created_at=NOW - dt.timedelta(minutes=10),
        )
        self.assertEqual(copilot.sweep(NOW), 0)
        self.assertEqual(self.sent, [])
