"""The handover desk (apps/leadai/handover_desk.py; Matloob 2026-10-22): a Lead AI chat handed to a person is its Bitrix
responsible's to see, on their own screen, and nothing else is; they read, reply, send a template from the chat's
number, say Done; the chat stays theirs once they wrote; a Bitrix reassignment moves it; Move to inbox ends it; the
engine and a person's Bot Status put a chat on the desk; the sweep reads the responsible again every hour."""

import datetime as dt
import importlib
from unittest.mock import patch

from django.apps import apps as django_apps
from django.utils import timezone

from apps.accounts.models import Agent
from apps.catalog.models import NumberAssignment
from apps.inbox import events
from apps.inbox.events import group_for_agent
from apps.inbox.models import Conversation, Message
from apps.inbox.serializers import serialize_conversation
from apps.leadai import bitrix_status, handover_desk, lane, tasks
from apps.leadai.assistant import engine
from apps.leadai.models import LeadAiAlert, LeadAiChatState
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

    def backup(self):
        """An agent who holds the chats' number as a backup (never their owner), no admin rights, no Lead AI access."""
        agent = Agent.objects.create_user(username="backup", password="x", bitrix_user_id="2600", can_official_api=True, display_name="Backup")
        NumberAssignment.objects.create(number=self.number, agent=agent)
        return agent


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
        # A's pause is the handover's own (Bitrix's Handed to agent: paused by nobody): Done ends it with the handover.
        LeadAiChatState.objects.filter(conversation=self.a).update(draft={"text": "x"}, paused_at=timezone.now(), paused_by=None)
        self.client.force_login(self.plain)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.a.pk}/desk/done/").status_code, 200)
        state = LeadAiChatState.objects.get(conversation=self.a)
        self.assertIsNone(state.desk_at)
        self.assertIsNone(state.handed_over_at)
        self.assertIsNone(state.draft)
        self.assertIsNone(state.paused_at)
        self.assertEqual(state.desk_done_by, self.plain)
        self.assertEqual(self.mine(self.plain)["results"], [])
        self.assertEqual(self.client.get(f"/api/leadai/chats/{self.a.pk}/").status_code, 404)
        # Not another responsible's chat; an admin's Done on anyone's. B's pause is Omar's own choice: it stays.
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.b.pk}/desk/done/").status_code, 404)
        LeadAiChatState.objects.filter(conversation=self.b).update(paused_at=timezone.now(), paused_by=self.second)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f"/api/leadai/chats/{self.b.pk}/desk/done/").status_code, 200)
        state = LeadAiChatState.objects.get(conversation=self.b)
        self.assertIsNone(state.desk_at)
        self.assertEqual((state.paused_by, state.paused_at is not None), (self.second, True))
        # A broker's pause stays too: the assistant never talks to a broker (Q11; Resume is the admins').
        now = timezone.now()
        broker = self.chat(
            handed_over_at=now, handover_reason=engine.BROKER, desk_at=now, desk_reason=engine.BROKER, paused_at=now,
            responsible_bitrix_user_id="2500",
        )
        handover_desk.done(broker, self.plain)
        state = LeadAiChatState.objects.get(conversation=broker)
        self.assertEqual((state.desk_at, state.handed_over_at), (None, None))
        self.assertEqual(state.paused_at, now)

    def test_done_keeps_a_brokers_pause_set_after_another_handover(self):
        # A was handed over for a person asked for; the customer then declared themselves a broker (engine._apply pauses
        # the chat and labels it Broker; the desk's reason stays the stay's first): Done keeps that pause (Q11).
        now = timezone.now()
        LeadAiChatState.objects.filter(conversation=self.a).update(paused_at=now, paused_by=None)
        self.a.labels.add(engine.broker_label())
        state = handover_desk.done(self.a, self.plain)
        self.assertEqual((state.desk_at, state.handed_over_at, state.paused_at), (None, None, now))
        self.assertTrue(handover_desk.is_broker(self.a, state))
        self.assertFalse(handover_desk.is_broker(self.c, LeadAiChatState.for_conversation(self.c)))

    def test_the_list_and_the_post_endpoints_are_trimmed_too(self):
        row = self.rows(self.plain)["results"][0]
        self.assertEqual(row["id"], self.a.pk)
        self.assertIsNone(row["assigned_agent"])
        self.assertEqual(set(row["number"]), {"id", "phone_number"})
        self.assertEqual((row["lead_ai_info"], row["leadbot"]), (None, None))
        self.client.force_login(self.plain)
        row = self.client.post(f"/api/leadai/chats/{self.a.pk}/pause-ai/").json()
        self.assertEqual((row["assigned_agent"], row["lead_ai_info"], row["lead_ai_ai"]["paused_by"]), (None, None, ""))
        self.assertEqual(LeadAiChatState.objects.get(conversation=self.a).paused_by, self.plain)
        # A desk agent's list keeps the team.
        row = self.rows(self.desker)["results"][0]
        self.assertEqual(row["assigned_agent"]["display_name"], "Matloob")

    def test_the_desk_rows_name_no_colleague_on_a_call(self):
        now = timezone.now()
        self.appointment(self.a, starts_at=now + dt.timedelta(days=1), taken_by=self.owner, taken_at=now)
        self.assertEqual(self.mine(self.plain)["results"][0]["appointment"]["taken_by"], "")
        self.assertEqual(self.mine(self.admin, "?agent=2500")["results"][0]["appointment"]["taken_by"], "Matloob")

    def test_bitrix_users_0_and_1_hold_no_desk(self):
        now = timezone.now()
        self.chat(handed_over_at=now, handover_reason="unclear", desk_at=now, desk_reason="unclear", responsible_bitrix_user_id="1")
        self.assertEqual(handover_desk.bitrix_id(self.admin), "")  # the admin's own Bitrix id is 1
        self.assertFalse(handover_desk.may_use(self.admin))
        self.assertEqual(handover_desk.count_for(self.admin), 0)
        self.assertEqual(Conversation.objects.filter(handover_desk.desk_q("1")).count(), 0)
        self.assertEqual(self.mine(self.admin)["results"], [])
        self.assertEqual(self.mine(self.admin, "?agent=1")["results"], [])

    def test_the_detail_is_the_chat_and_the_customer_for_the_responsible(self):
        self.client.force_login(self.plain)
        row = self.client.get(f"/api/leadai/chats/{self.a.pk}/").json()
        self.assertIsNone(row["assigned_agent"])
        self.assertEqual(set(row["number"]), {"id", "phone_number"})
        self.assertEqual(row["number"]["phone_number"], self.number.phone_number)
        self.assertIsNone(row["lead_ai_info"])
        self.assertIsNone(row["leadbot"])  # the badge names the Bitrix lead
        self.assertEqual((row["lead_ai_ai"]["memory"], row["lead_ai_ai"]["paused_by"]), ([], ""))
        self.assertEqual(row["contact"]["wa_id"], self.a.contact.wa_id)
        # A desk agent (and an admin) keeps the whole row.
        self.client.force_login(self.desker)
        row = self.client.get(f"/api/leadai/chats/{self.a.pk}/").json()
        self.assertEqual(row["assigned_agent"]["display_name"], "Matloob")
        self.assertIn("title", row["number"])
        self.assertEqual(row["lead_ai_info"]["crm_id"], 77)
        self.assertFalse(handover_desk.only_through_desk(self.desker, self.a))
        self.assertFalse(handover_desk.only_through_desk(self.owner, self.a))  # the chat's owner
        self.assertTrue(handover_desk.only_through_desk(self.plain, self.a))

    def test_live_frames_reach_the_responsible_trimmed(self):
        LeadAiChatState.objects.filter(conversation=self.a).update(responsible_agent=self.plain)
        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append((group, message["event"], message["data"]))

        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            events.publish(self.a, "message.new", {"conversation": serialize_conversation(self.a)})
        by_group = {group: data for group, _, data in sent}
        self.assertEqual(by_group[lane.DESK_GROUP]["conversation"]["assigned_agent"]["display_name"], "Matloob")
        mine = by_group[group_for_agent(self.plain.pk)]
        self.assertEqual((mine["number_id"], mine["conversation"]["id"]), (self.number.pk, self.a.pk))
        self.assertIsNone(mine["conversation"]["assigned_agent"])
        self.assertEqual(set(mine["conversation"]["number"]), {"id", "phone_number"})
        self.assertEqual([group for group, *_ in sent].count(group_for_agent(self.plain.pk)), 1)
        self.assertTrue(all(event == "leadai.message.new" for _, event, _ in sent))
        # A message's author goes with the trim; a backup holder of the number, B's responsible, gets the full frame on
        # their own channel (they join no number group: inbox.consumers).
        backup = self.backup()
        LeadAiChatState.objects.filter(conversation=self.b).update(responsible_agent=backup, responsible_bitrix_user_id="2600")
        sent.clear()
        message = {"id": 1, "direction": "out", "sent_by": {"id": self.owner.pk, "display_name": "Matloob"}}
        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            events.publish(self.a, "message.new", {"conversation": serialize_conversation(self.a), "message": message})
            events.publish(self.b, "message.new", {"conversation": serialize_conversation(self.b), "message": message})
        frames = {(group, data["conversation"]["id"]): data for group, _, data in sent}
        self.assertIsNone(frames[(group_for_agent(self.plain.pk), self.a.pk)]["message"]["sent_by"])
        self.assertEqual(frames[(lane.DESK_GROUP, self.a.pk)]["message"]["sent_by"]["display_name"], "Matloob")
        full = frames[(group_for_agent(backup.pk), self.b.pk)]
        self.assertEqual((full["conversation"]["assigned_agent"]["display_name"], "title" in full["conversation"]["number"]), ("Matloob", True))
        self.assertEqual(full["message"]["sent_by"]["display_name"], "Matloob")
        self.assertNotIn((group_for_agent(backup.pk), self.a.pk), frames)  # not their chat

    def test_the_desk_changes_reach_the_screens(self):
        LeadAiChatState.objects.filter(conversation=self.a).update(responsible_agent=self.plain)
        with patch("apps.inbox.events.publish_to_agent") as publish, self.captureOnCommitCallbacks(execute=True):
            handover_desk.done(self.a, self.plain)
        publish.assert_called_once_with(self.plain.pk, handover_desk.DESK_CHANGED, {"conversation_id": self.a.pk, "on_desk": False, "count": 0})
        # Omar's chat B, its responsible read for the first time: Omar hears it with his count.
        with patch("apps.inbox.events.publish_to_agent") as publish, self.captureOnCommitCallbacks(execute=True):
            tasks._remember_responsible(self.b, "2401")
        publish.assert_called_once_with(self.second.pk, handover_desk.DESK_CHANGED, {"conversation_id": self.b.pk, "on_desk": True, "count": 1})
        # Reassigned in Bitrix to Plain: both hear it, each with their count after the move.
        with patch("apps.inbox.events.publish_to_agent") as publish, self.captureOnCommitCallbacks(execute=True):
            tasks._remember_responsible(self.b, "2500")
        self.assertEqual(
            [call.args for call in publish.call_args_list],
            [
                (self.second.pk, handover_desk.DESK_CHANGED, {"conversation_id": self.b.pk, "on_desk": False, "count": 0}),
                (self.plain.pk, handover_desk.DESK_CHANGED, {"conversation_id": self.b.pk, "on_desk": True, "count": 1}),
            ],
        )
        # Read again with the same responsible: nothing to tell. Move to inbox: the responsible hears it leave.
        with patch("apps.inbox.events.publish_to_agent") as publish, self.captureOnCommitCallbacks(execute=True):
            tasks._remember_responsible(self.b, "2500")
            lane.move_to_inbox(self.b, self.admin)
        publish.assert_called_once_with(self.plain.pk, handover_desk.DESK_CHANGED, {"conversation_id": self.b.pk, "on_desk": False, "count": 0})

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
        LeadAiChatState.objects.filter(conversation=self.c).update(responsible_agent=self.plain)  # known from an earlier handover
        state = LeadAiChatState.for_conversation(self.c)
        fields = []
        now = timezone.now()
        with patch("apps.inbox.events.publish_to_agent") as publish, self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(handover_desk.mark(state, now, "call_requested", fields))
            state.save(update_fields=sorted(set(fields)) + ["updated_at"])
        self.resolve_responsible.assert_called_once_with(self.c.pk)
        publish.assert_called_once_with(self.plain.pk, handover_desk.DESK_CHANGED, {"conversation_id": self.c.pk, "on_desk": True, "count": 2})
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
        self.assertEqual(handover_desk.live_groups(self.a), ([], [group_for_agent(self.plain.pk)]))
        self.assertEqual(handover_desk.live_groups(self.b), ([], []))  # Omar's row names no Agent yet
        # A desk agent (Omar) hears the desk's group, an admin the number's, the owner their own: no channel more.
        for responsible in (self.second, self.admin, self.owner):
            LeadAiChatState.objects.filter(conversation=self.b).update(responsible_agent=responsible)
            self.assertEqual(handover_desk.live_groups(self.b), ([], []), responsible.username)
        # A holder of the chat's number who does not own it hears nothing otherwise: their own channel, in full.
        backup = self.backup()
        LeadAiChatState.objects.filter(conversation=self.b).update(responsible_agent=backup, responsible_bitrix_user_id="2600")
        self.assertEqual(handover_desk.live_groups(self.b), ([group_for_agent(backup.pk)], []))
        self.assertEqual(lane.desk_event_groups("leadai.message.new", self.a), [lane.DESK_GROUP])
        self.assertEqual(lane.desk_scoped_groups("leadai.message.new", self.a), [group_for_agent(self.plain.pk)])
        self.assertEqual(lane.desk_groups_for("leadai.message.new", self.b), ([lane.DESK_GROUP, group_for_agent(backup.pk)], []))
        self.assertEqual(lane.desk_groups_for("message.new", self.a), ([], []))
        self.assertEqual(lane.desk_event_groups("leadai.message.new"), [lane.DESK_GROUP])
        # B is the backup's now (above), so Omar's desk is empty and the backup's holds one.
        self.assertEqual((handover_desk.count_for(self.second), handover_desk.count_for(backup)), (0, 1))
        LeadAiChatState.objects.filter(conversation=self.b).update(responsible_agent=None, responsible_bitrix_user_id="2401")
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get("/api/auth/me/").json()["handover_desk"], {"count": 1})
        self.assertIsNone(handover_desk.mine_q(Agent.objects.create_user(username="nobody", password="x", can_official_api=True)))
        self.assertEqual(handover_desk.count_for(self.second), 1)


class BackfillTests(GrantBase):
    def test_the_migration_puts_the_chats_handed_over_before_it_on_their_desks(self):
        now = timezone.now()
        handed = self.chat(handed_over_at=now - dt.timedelta(days=3), handover_reason="customer_asked_human", responsible_bitrix_user_id="2500")
        unclear = self.chat(handed_over_at=now, handover_reason="")
        answered = self.chat(handed_over_at=None, responsible_bitrix_user_id="2500")
        moved = self.chat(active=False, handed_over_at=now, handover_reason="call_requested")
        LeadAiChatState.objects.filter(conversation__in=(handed, unclear, moved)).update(desk_at=None)
        migration = importlib.import_module("apps.leadai.migrations.0019_handover_desk")
        migration.backfill(django_apps, None)
        states = {chat.pk: LeadAiChatState.objects.get(conversation=chat) for chat in (handed, unclear, answered, moved, self.a)}
        self.assertEqual((states[handed.pk].desk_at, states[handed.pk].desk_reason), (now - dt.timedelta(days=3), "customer_asked_human"))
        self.assertEqual((states[unclear.pk].desk_at, states[unclear.pk].desk_reason), (now, "unclear"))
        self.assertIsNone(states[answered.pk].desk_at)
        self.assertIsNone(states[moved.pk].desk_at)
        self.assertEqual(states[self.a.pk].desk_reason, "customer_asked_human")  # on a desk already: as it was
        self.assertEqual(self.ids(self.mine(self.plain)), sorted([self.a.pk, handed.pk]))


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

    def test_a_reread_of_the_lead_does_not_undo_done(self):
        with patch("apps.leadai.tasks.resolve_responsible.delay"), patch("apps.leadai.tasks.deliver_alert.delay"), self.captureOnCommitCallbacks(execute=True):
            chat = self.chat(responsible_bitrix_user_id="2500")
            bitrix_status.apply(77, bot_status=2478)
            handover_desk.done(chat, self.plain)
            alerts_before = LeadAiAlert.objects.filter(kind="bitrix_status").count()  # one row per recipient of the person's change
            # The lead still says Handed to agent when the next nudge reads it (followups.bitrix_blocks): nothing applied again.
            self.assertEqual(bitrix_status.apply(77, bot_status=2478, reread=True), 1)
            state = LeadAiChatState.objects.get(conversation=chat)
            self.assertEqual((state.desk_at, state.handed_over_at, state.paused_at), (None, None, None))
            self.assertIsNotNone(state.desk_done_at)
            self.assertEqual(LeadAiAlert.objects.filter(kind="bitrix_status").count(), alerts_before)  # no "set in Bitrix" nobody set
            # A person sets it again in Bitrix (C12's call): applied, and the desk's Done forgotten with it.
            bitrix_status.apply(77, bot_status=2478)
            state = LeadAiChatState.objects.get(conversation=chat)
            self.assertEqual((state.desk_at is not None, state.paused_at is not None, state.desk_done_at), (True, True, None))
            # A re-read while the chat is handed over changes nothing either.
            self.assertEqual(bitrix_status.apply(77, bot_status=2478, reread=True), 1)
            self.assertEqual(LeadAiChatState.objects.get(conversation=chat).desk_done_at, None)
