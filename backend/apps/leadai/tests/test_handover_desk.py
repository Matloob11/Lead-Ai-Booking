"""The handover desk (apps/leadai/handover_desk.py; Matloob 2026-10-22): a Lead AI chat handed to a person is its Bitrix
responsible's to see, on their own screen, and nothing else is; they read, reply, send a template from the chat's
number, say Done; the chat stays theirs once they wrote; a Bitrix reassignment moves it; Move to inbox ends it; the
engine and a person's Bot Status put a chat on the desk; the sweep reads the responsible again every hour."""

import datetime as dt
from unittest.mock import patch

from django.utils import timezone

from apps.accounts.models import Agent
from apps.inbox.events import group_for_agent
from apps.inbox.models import Message
from apps.leadai import bitrix_status, handover_desk, lane
from apps.leadai.models import LeadAiChatState
from apps.leadai.tests.test_desk import DeskBase
from apps.leadai.tests.test_shops_playbook import ShopsBase, shop_answer

ROW_KEYS = {
    "id", "number_id", "contact", "last_message_at", "last_message_preview", "last_message_kind", "unread_count", "is_session_open",
    "session_expires_at", "desk", "ai", "appointment",
}


class GrantBase(DeskBase):
    def setUp(self):
        super().setUp()
        for target in ("apps.leadai.tasks.resolve_responsible.delay", "apps.leadai.tasks.deliver_alert.delay"):
            patcher = patch(target)
            setattr(self, target.rsplit(".", 2)[-2], patcher.start())
            self.addCleanup(patcher.stop)
        now = timezone.now()
        # Plain (Bitrix 2500) is the responsible of A (handed over, on the desk) and C (never handed over); B is Omar's
        # (2401); D was handed over, then moved to the main inbox.
        self.a = self.chat(handed_over_at=now, handover_reason="customer_asked_human", desk_at=now, desk_reason="customer_asked_human", responsible_bitrix_user_id="2500")
        self.b = self.chat(handed_over_at=now, handover_reason="call_requested", desk_at=now, desk_reason="call_requested", responsible_bitrix_user_id="2401")
        self.c = self.chat(responsible_bitrix_user_id="2500")
        self.d = self.chat(active=False, handed_over_at=now, desk_at=now, desk_reason="unclear", responsible_bitrix_user_id="2500")

    def mine(self, user, query=""):
        self.client.force_login(user)
        response = self.client.get(f"/api/leadai/desk/mine/{query}")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def ids(self, payload):
        return sorted(row["id"] for row in payload["results"])


class GrantTests(GrantBase):
    def test_the_responsible_sees_their_handed_over_chats_and_nothing_else(self):
        payload = self.mine(self.plain)
        self.assertEqual(self.ids(payload), [self.a.pk])
        row = payload["results"][0]
        self.assertEqual((row["desk"]["reason"], row["ai"]["quiet"], row["appointment"]), ("customer_asked_human", True, None))
        self.assertEqual(row["desk"]["reason_text"], handover_desk.reason_text("customer_asked_human"))
        self.assertEqual(set(row), ROW_KEYS)  # the chat and the customer: no other agent, no campaign, no number's title
        self.client.force_login(self.plain)
        for url in (f"/api/leadai/chats/{self.a.pk}/", f"/api/inbox/conversations/{self.a.pk}/messages/", f"/api/inbox/conversations/{self.a.pk}/templates/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        for other in (self.b, self.c, self.d):
            self.assertEqual(self.client.get(f"/api/leadai/chats/{other.pk}/").status_code, 404)
            self.assertEqual(self.client.get(f"/api/inbox/conversations/{other.pk}/messages/").status_code, 404)
        # The Lead AI list, should they call it, is their desk and nothing more; the main inbox leaves Lead AI chats out.
        self.assertEqual(self.ids(self.rows(self.plain)), [self.a.pk])
        self.assertNotIn(self.a.pk, [row["id"] for row in self.client.get("/api/inbox/conversations/").json()["results"]])
        # Omar's desk is B alone; a desk agent and an admin keep every chat; an admin may look at a desk.
        self.assertEqual(self.ids(self.mine(self.second)), [self.b.pk])
        self.assertEqual(self.ids(self.rows(self.desker)), sorted([self.a.pk, self.b.pk, self.c.pk]))
        self.assertEqual(self.ids(self.mine(self.admin, "?agent=2500")), [self.a.pk])
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get("/api/leadai/desk/mine/?agent=2401").status_code, 403)

    def test_the_responsible_answers_and_sends_a_template_from_the_chats_number(self):
        def sent(conversation, agent, body, **kwargs):
            return Message.objects.create(conversation=conversation, direction="out", kind="text", body=body, sent_by=agent)

        def sent_template(conversation, agent, template, variables, *args, **kwargs):
            return Message.objects.create(conversation=conversation, direction="out", kind="template", body="Hello", template=template, sent_by=agent)

        self.client.force_login(self.plain)
        with patch("apps.inbox.services.send_text", side_effect=sent):
            response = self.client.post(
                f"/api/inbox/conversations/{self.a.pk}/send/", {"kind": "text", "body": "Hello, this is Plain from our team."}, content_type="application/json"
            )
        self.assertEqual(response.status_code, 201, response.content)
        with patch("apps.inbox.services.send_template", side_effect=sent_template):
            response = self.client.post(
                f"/api/inbox/conversations/{self.a.pk}/send-template/", {"template_id": self.shops_template.pk, "variables": {"1": "Ali"}},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        # Their reply keeps the chat on their desk, whatever the engine does with handed_over_at.
        LeadAiChatState.objects.filter(conversation=self.a).update(handed_over_at=None, handover_reason="")
        payload = self.mine(self.plain)
        self.assertEqual(self.ids(payload), [self.a.pk])
        self.assertTrue(payload["results"][0]["desk"]["person_wrote"])
        self.assertFalse(payload["results"][0]["ai"]["quiet"])
        with patch("apps.inbox.services.send_text", side_effect=sent):
            refused = self.client.post(f"/api/inbox/conversations/{self.b.pk}/send/", {"kind": "text", "body": "Hi"}, content_type="application/json")
        self.assertEqual(refused.status_code, 404)

    def test_done_takes_the_chat_off_the_desk_and_ends_the_handover(self):
        LeadAiChatState.objects.filter(conversation=self.a).update(draft={"text": "x"}, paused_at=timezone.now())
        self.client.force_login(self.plain)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.a.pk}/desk/done/").status_code, 200)
        state = LeadAiChatState.objects.get(conversation=self.a)
        self.assertIsNone(state.desk_at)
        self.assertIsNone(state.handed_over_at)
        self.assertIsNone(state.draft)
        self.assertEqual(state.desk_done_by, self.plain)
        self.assertIsNotNone(state.paused_at)  # a pause is a person's choice, not the desk's
        self.assertEqual(self.mine(self.plain)["results"], [])
        self.assertEqual(self.client.get(f"/api/leadai/chats/{self.a.pk}/").status_code, 404)
        # Not another responsible's chat; an admin's Done on anyone's.
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.b.pk}/desk/done/").status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.b.pk}/desk/done/").status_code, 200)
        self.assertIsNone(LeadAiChatState.objects.get(conversation=self.b).desk_at)

    def test_a_bitrix_reassignment_moves_the_chat_between_desks(self):
        LeadAiChatState.objects.filter(conversation=self.a).update(responsible_bitrix_user_id="2401")
        self.assertEqual(self.mine(self.plain)["results"], [])
        self.assertEqual(self.ids(self.mine(self.second)), sorted([self.a.pk, self.b.pk]))

    def test_move_to_inbox_takes_it_off_the_desk(self):
        self.assertTrue(lane.move_to_inbox(self.a, self.admin))
        state = LeadAiChatState.objects.get(conversation=self.a)
        self.assertIsNone(state.desk_at)
        self.assertEqual(state.desk_done_by, self.admin)

    def test_mark_once_and_the_responsible_read_after_the_commit(self):
        state = LeadAiChatState.for_conversation(self.c)
        fields = []
        now = timezone.now()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(handover_desk.mark(state, now, "call_requested", fields))
            state.save(update_fields=sorted(set(fields)) + ["updated_at"])
        self.resolve_responsible.assert_called_once_with(self.c.pk)
        self.assertEqual(sorted(fields), ["desk_at", "desk_done_at", "desk_done_by", "desk_reason"])
        self.assertEqual((state.desk_at, state.desk_reason), (now, "call_requested"))
        self.assertFalse(handover_desk.mark(state, now, "unclear", fields))  # on a desk already: nothing changes
        self.assertEqual(self.ids(self.mine(self.plain)), sorted([self.a.pk, self.c.pk]))

    def test_the_sweep_reads_the_responsible_again_every_hour(self):
        self.assertEqual(handover_desk.refresh_responsibles(), 2)  # A and B were never read; C is on no desk; D left the screen
        self.assertEqual(sorted(call.args[0] for call in self.resolve_responsible.call_args_list), sorted([self.a.pk, self.b.pk]))
        self.assertEqual(handover_desk.refresh_responsibles(), 0)
        LeadAiChatState.objects.filter(conversation=self.a).update(responsible_checked_at=timezone.now() - dt.timedelta(hours=2))
        self.assertEqual(handover_desk.refresh_responsibles(), 1)

    def test_live_events_and_the_sign_in_payload(self):
        LeadAiChatState.objects.filter(conversation=self.a).update(responsible_agent=self.plain)
        self.assertEqual(handover_desk.live_groups(self.a), [group_for_agent(self.plain.pk)])
        self.assertEqual(handover_desk.live_groups(self.b), [])  # Omar's row names no Agent yet
        self.assertEqual(lane.desk_event_groups("leadai.message.new", self.a), [lane.DESK_GROUP, group_for_agent(self.plain.pk)])
        self.assertEqual(lane.desk_event_groups("message.new", self.a), [])
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get("/api/auth/me/").json()["handover_desk"], {"count": 1})
        self.assertIsNone(handover_desk.mine_q(Agent.objects.create_user(username="nobody", password="x", can_official_api=True)))
        self.assertEqual(handover_desk.count_for(self.second), 1)


class EngineDeskTests(ShopsBase):
    def test_a_handover_puts_the_chat_on_the_desk(self):
        self.turn(self.inbound("Can your agent call me please?"), [shop_answer("Sure, our agent will call you.", handover="call_requested")])
        state = self.state()
        self.assertIsNotNone(state.handed_over_at)
        self.assertEqual((state.desk_at, state.desk_reason), (state.handed_over_at, state.handover_reason))


class BitrixDeskTests(DeskBase):
    def test_a_persons_handed_to_agent_puts_the_chat_on_the_desk(self):
        with patch("apps.leadai.tasks.resolve_responsible.delay") as resolve, patch("apps.leadai.tasks.deliver_alert.delay"), self.captureOnCommitCallbacks(execute=True):
            chat = self.chat(responsible_bitrix_user_id="2500")
            self.assertEqual(bitrix_status.apply(77, bot_status=2478), 1)
        state = LeadAiChatState.objects.get(conversation=chat)
        self.assertIsNotNone(state.desk_at)
        self.assertEqual(state.desk_reason, bitrix_status.HANDED_REASON)
        self.assertIsNotNone(state.paused_at)
        resolve.assert_called_with(chat.pk)
