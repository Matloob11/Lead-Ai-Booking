"""Lead AI access per Bitrix user (apps/leadai/access.py; Matloob 2026-10-23, round 25): three grants on their own —
every chat, the Today list, the Needs a person list — each opening only its chats; all_chats and Agents & access's
Lead AI access kept in step both ways; a panel admin's screen listing the portal's users live with the panel's
accounts; the sign-in payload and the agent's panel told; the portal's list paged and cached."""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.accounts.models import Agent
from apps.leadai import access, lane
from apps.leadai.assistant import alerts
from apps.leadai.desk import today_window
from apps.leadai.models import LeadAiAccess, LeadAiChatState
from apps.leadai.tests.test_desk import DeskBase

USERS = [
    {"bitrix_user_id": "2500", "name": "Plain Person", "position": "Leasing agent", "email": ""},
    {"bitrix_user_id": "2777", "name": "Bitrix Only", "position": "Agent", "email": ""},
    {"bitrix_user_id": "2900", "name": "Boss Person", "position": "Manager", "email": ""},
]


class AccessBase(DeskBase):
    def setUp(self):
        super().setUp()
        for target in ("apps.leadai.tasks.resolve_responsible.delay", "apps.leadai.tasks.deliver_alert.delay"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.boss = Agent.objects.create_user(
            username="boss", password="x", bitrix_user_id="2900", can_official_api=True, is_wa_admin=True, display_name="Boss"
        )
        users = patch("apps.leadai.access.bitrix_users", return_value=list(USERS))
        users.start()
        self.addCleanup(users.stop)
        now = timezone.now()
        start, end = today_window(now)
        self.booked = self.chat(name="Booked")
        self.appointment(self.booked, starts_at=start + (end - start) / 2)  # a visit today, Dubai time
        self.handed = self.chat(
            name="Handed", handed_over_at=now, handover_reason="call_requested", desk_at=now, desk_reason="call_requested",
            responsible_bitrix_user_id="2401",
        )
        self.quiet = self.chat(name="Quiet")

    def status(self, user, chat) -> int:
        self.client.force_login(user)
        return self.client.get(f"/api/leadai/chats/{chat.pk}/").status_code

    def me(self, user) -> dict:
        self.client.force_login(user)
        return self.client.get("/api/auth/me/").json()["lead_ai_access"]


class GrantTests(AccessBase):
    def test_nothing_granted_keeps_what_they_had(self):
        self.assertEqual(access.of(self.plain), {"admin": False, "all_chats": False, "today": False, "needs": False, "any": False})
        self.assertIsNone(lane.desk_q(self.plain))
        for chat in (self.booked, self.handed, self.quiet):
            self.assertEqual(self.status(self.plain, chat), 404)
        self.assertEqual(self.me(self.plain), {"admin": False, "all_chats": False, "today": False, "needs": False, "any": False})
        self.assertEqual(self.me(self.admin), {"admin": True, "all_chats": True, "today": True, "needs": True, "any": True})
        self.assertIsNone(lane.desk_q(self.admin))  # the inbox's own visibility is an admin's

    def test_today_opens_the_days_booked_chats_only(self):
        access.grant("2500", {"today": True}, by=self.admin)
        self.assertEqual((self.status(self.plain, self.booked), self.status(self.plain, self.handed), self.status(self.plain, self.quiet)), (200, 404, 404))
        self.assertEqual(self.me(self.plain), {"admin": False, "all_chats": False, "today": True, "needs": False, "any": True})
        rows = self.rows(self.plain, "?today=1")["results"]
        self.assertEqual([row["id"] for row in rows], [self.booked.pk])
        self.assertFalse(lane.has_desk_access(self.plain))
        self.assertEqual(lane.desk_groups(self.plain), [])

    def test_needs_opens_the_waiting_chats_only(self):
        access.grant("2500", {"needs": True}, by=self.admin)
        self.assertEqual((self.status(self.plain, self.handed), self.status(self.plain, self.booked), self.status(self.plain, self.quiet)), (200, 404, 404))
        self.assertEqual([row["id"] for row in self.rows(self.plain, "?needs=1")["results"]], [self.handed.pk])

    def test_all_chats_is_lead_ai_access_both_ways(self):
        with patch("apps.inbox.events.publish_to_agent") as publish, self.captureOnCommitCallbacks(execute=True):
            access.grant("2500", {"all_chats": True}, by=self.admin)
        # The payload is the effective grants, the sign-in payload's shape (access.tell).
        publish.assert_called_once_with(self.plain.pk, access.CHANGED, {"access": {"admin": False, "all_chats": True, "today": True, "needs": True, "any": True}})
        self.plain.refresh_from_db()
        self.assertTrue(self.plain.can_lead_ai)  # Agents & access shows it too
        for chat in (self.booked, self.handed, self.quiet):
            self.assertEqual(self.status(self.plain, chat), 200)
        self.assertTrue(lane.has_desk_access(self.plain))
        self.assertEqual(lane.desk_groups(self.plain), [lane.DESK_GROUP])
        self.assertIn(self.plain, alerts.desk_agents())
        self.assertEqual(LeadAiAccess.objects.get(bitrix_user_id="2500").history[-1]["changes"], {"all_chats": [False, True]})
        # Agents & access takes it off: the row follows, and so does everything else.
        self.client.force_login(self.admin)
        response = self.client.post(f"/api/catalog/agents/{self.plain.pk}/admin/", {"can_lead_ai": False}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(LeadAiAccess.objects.get(bitrix_user_id="2500").all_chats)
        self.assertEqual(self.status(self.plain, self.quiet), 404)
        self.assertNotIn(self.plain, alerts.desk_agents())
        # A row granted to a Bitrix user with no account yet holds from their first sign-in.
        access.grant("2777", {"all_chats": True}, by=self.admin)
        newcomer = Agent.objects.create_user(username="newcomer", password="x", bitrix_user_id="2777", can_official_api=True)
        self.assertTrue(lane.has_desk_access(newcomer))
        self.assertIn(newcomer, alerts.desk_agents())
        self.assertEqual(self.status(newcomer, self.quiet), 200)

    def test_the_open_socket_follows_the_grant(self):
        """inbox.consumers: on leadai.access.changed the groups are read again from the row as it is now, not from
        the socket's copy of the agent (whose can_lead_ai and memo are the old ones)."""
        from apps.inbox.consumers import InboxConsumer

        fresh_groups = vars(InboxConsumer)["_fresh_groups"].func
        stale = Agent.objects.get(pk=self.plain.pk)
        self.assertNotIn(lane.DESK_GROUP, InboxConsumer()._groups_for(stale))
        access.grant("2500", {"all_chats": True}, by=self.admin)
        self.assertNotIn(lane.DESK_GROUP, InboxConsumer()._groups_for(stale))  # the memo and the old flag
        self.assertIn(lane.DESK_GROUP, fresh_groups(InboxConsumer(), stale))
        access.grant("2500", {"all_chats": False}, by=self.admin)
        self.assertNotIn(lane.DESK_GROUP, fresh_groups(InboxConsumer(), stale))
        Agent.objects.filter(pk=self.plain.pk).update(is_active=False)
        self.assertEqual(fresh_groups(InboxConsumer(), stale), [])

    def test_an_inactive_account_or_no_official_inbox_gets_nothing(self):
        access.grant("2500", {"all_chats": True, "today": True, "needs": True}, by=self.admin)
        Agent.objects.filter(pk=self.plain.pk).update(can_official_api=False)
        self.assertFalse(access.of(Agent.objects.get(pk=self.plain.pk))["any"])
        Agent.objects.filter(pk=self.plain.pk).update(can_official_api=True, is_active=False)
        self.assertFalse(access.of(Agent.objects.get(pk=self.plain.pk))["any"])


class ScreenTests(AccessBase):
    def test_the_screen_lists_bitrix_users_and_accounts_for_admins(self):
        access.grant("2500", {"today": True}, by=self.admin)
        self.client.force_login(self.admin)
        payload = self.client.get("/api/leadai/access/").json()
        rows = {row["bitrix_user_id"]: row for row in payload["results"]}
        self.assertNotIn("1", rows)  # the hold user (the test admin's id)
        plain = rows["2500"]
        self.assertEqual((plain["name"], plain["position"], plain["in_bitrix"], plain["admin"], plain["handovers"]), ("Plain Person", "Leasing agent", True, False, 0))
        self.assertEqual((plain["access"], plain["effective"]), ({"all_chats": False, "today": True, "needs": False}, {"all_chats": False, "today": True, "needs": False}))
        self.assertEqual(plain["account"]["display_name"], "Plain")
        only = rows["2777"]
        self.assertEqual((only["in_bitrix"], only["account"], only["access"]["today"]), (True, None, False))
        omar = rows["2401"]  # a panel account with Lead AI access, not in the portal's list today
        self.assertEqual((omar["in_bitrix"], omar["access"]["all_chats"], omar["effective"]["needs"], omar["handovers"]), (False, True, True, 1))
        self.assertEqual(payload["flags"], ["all_chats", "today", "needs"])
        boss = rows["2900"]  # a panel admin: everything, whatever the switches say; first in the list
        everything = {"all_chats": True, "today": True, "needs": True}
        self.assertEqual((boss["admin"], boss["effective"], boss["access"]["today"], boss["name"]), (True, everything, False, "Boss Person"))
        self.assertEqual(payload["results"][0]["bitrix_user_id"], "2900")
        self.assertEqual([row["admin"] for row in payload["results"]], sorted((row["admin"] for row in payload["results"]), reverse=True))
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get("/api/leadai/access/").status_code, 403)

    def test_a_panel_admin_sets_the_grants_and_the_guards_hold(self):
        self.client.force_login(self.admin)
        put = lambda pk, body: self.client.put(f"/api/leadai/access/{pk}/", body, content_type="application/json")
        response = put("2777", {"today": True, "needs": "yes"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["access"], {"all_chats": False, "today": True, "needs": True})
        self.assertEqual(LeadAiAccess.objects.get(bitrix_user_id="2777").flags(), {"all_chats": False, "today": True, "needs": True})
        self.assertEqual(put("2777", {}).status_code, 400)
        self.assertEqual(put("1", {"today": True}).status_code, 400)  # a hold user
        self.assertEqual(put("2500", {"all_chats": "false"}).json()["access"]["all_chats"], False)  # a word for a boolean
        self.assertEqual(put("2500", {"today": 1}).json()["access"]["today"], True)
        self.assertEqual(put("2500", {"today": "maybe"}).status_code, 400)  # not one: no grant, no revoke
        self.assertEqual(LeadAiAccess.objects.get(bitrix_user_id="2500").flags(), {"all_chats": False, "today": True, "needs": False})
        boss = self.boss  # a panel admin with a real Bitrix id
        self.client.force_login(boss)
        self.assertEqual(put("2900", {"today": True}).status_code, 400)  # never one's own
        self.assertEqual(put("2500", {"all_chats": True}).status_code, 200)
        self.client.force_login(self.desker)
        self.assertEqual(put("2500", {"today": True}).status_code, 403)


class AgentsAndAccessTests(AccessBase):
    """The grant that lives on the account's flag alone (Agents & access, before this screen existed), and a grant
    made before the account existed: the two never disagree, whichever side moves."""

    def test_a_revoke_clears_a_grant_made_in_agents_and_access(self):
        sara = Agent.objects.get(bitrix_user_id="2400")  # can_lead_ai from Agents & access, no row
        omar = Agent.objects.get(bitrix_user_id="2401")
        self.assertTrue(sara.can_lead_ai and omar.can_lead_ai)
        self.assertIsNone(access.row_for("2400"))
        self.client.force_login(self.admin)
        put = lambda pk, body: self.client.put(f"/api/leadai/access/{pk}/", body, content_type="application/json")
        # A Today change alone leaves the grant on, and the row now says what the flag said.
        response = put("2401", {"today": True})
        self.assertEqual(response.json()["effective"], {"all_chats": True, "today": True, "needs": True})
        self.assertTrue(Agent.objects.get(pk=omar.pk).can_lead_ai)
        self.assertTrue(LeadAiAccess.objects.get(bitrix_user_id="2401").all_chats)
        self.assertEqual(LeadAiAccess.objects.get(bitrix_user_id="2401").history[-1]["changes"], {"today": [False, True]})
        # Off clears both.
        response = put("2400", {"all_chats": False})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["access"]["all_chats"], response.json()["effective"]["all_chats"]), (False, False))
        self.assertFalse(Agent.objects.get(pk=sara.pk).can_lead_ai)
        self.assertFalse(LeadAiAccess.objects.get(bitrix_user_id="2400").all_chats)
        self.assertEqual(LeadAiAccess.objects.get(bitrix_user_id="2400").history[-1]["changes"], {"all_chats": [True, False]})
        sara = Agent.objects.get(pk=sara.pk)
        self.assertFalse(access.of(sara)["any"])
        self.assertNotIn(sara, alerts.desk_agents())
        self.assertFalse(lane.has_desk_access(sara))

    def test_the_migration_backfills_the_rows(self):
        from importlib import import_module

        from django.apps import apps as registry

        backfill = import_module("apps.leadai.migrations.0021_lead_ai_access").backfill
        LeadAiAccess.objects.all().delete()
        backfill(registry, None)
        granted = sorted(LeadAiAccess.objects.filter(all_chats=True).values_list("bitrix_user_id", flat=True))
        flagged = sorted(Agent.objects.filter(can_lead_ai=True).exclude(bitrix_user_id__in=["", "0", "1"]).values_list("bitrix_user_id", flat=True))
        self.assertEqual(granted, flagged)
        self.assertIn("2400", granted)
        self.assertFalse(LeadAiAccess.objects.filter(bitrix_user_id="1").exists())
        self.assertEqual(LeadAiAccess.objects.get(bitrix_user_id="2400").history[-1]["by"], "migration 0021 (Agents & access)")
        backfill(registry, None)  # again: nothing doubles
        self.assertEqual(LeadAiAccess.objects.filter(bitrix_user_id="2400").count(), 1)
        self.assertEqual(len(LeadAiAccess.objects.get(bitrix_user_id="2400").history), 1)

    def test_a_grant_before_the_first_sign_in_reaches_the_account(self):
        access.grant("2777", {"all_chats": True}, by=self.admin)
        newcomer = Agent.objects.create_user(username="newcomer", password="x", bitrix_user_id="2777", can_official_api=True, display_name="New")
        self.assertFalse(newcomer.can_lead_ai)
        self.client.force_login(newcomer)
        payload = self.client.get("/api/auth/me/").json()
        self.assertEqual((payload["can_lead_ai"], payload["lead_ai_access"]), (True, {"admin": False, "all_chats": True, "today": True, "needs": True, "any": True}))
        self.assertTrue(Agent.objects.get(pk=newcomer.pk).can_lead_ai)  # the account's own flag follows the row

    def test_the_panel_is_told_the_effective_grants(self):
        with patch("apps.inbox.events.publish_to_agent") as told, self.captureOnCommitCallbacks(execute=True):
            access.grant("2500", {"today": True}, by=self.admin)
        told.assert_called_once_with(self.plain.pk, access.CHANGED, {"access": {"admin": False, "all_chats": False, "today": True, "needs": False, "any": True}})
        with patch("apps.inbox.events.publish_to_agent") as told, self.captureOnCommitCallbacks(execute=True):
            access.grant("2500", {"all_chats": True}, by=self.admin)
        told.assert_called_once_with(self.plain.pk, access.CHANGED, {"access": {"admin": False, "all_chats": True, "today": True, "needs": True, "any": True}})
        with patch("apps.inbox.events.publish_to_agent") as told, self.captureOnCommitCallbacks(execute=True):
            access.grant("2500", {"today": True}, by=self.admin)  # nothing changes: nothing told
        told.assert_not_called()
        with patch("apps.inbox.events.publish_to_agent") as told, self.captureOnCommitCallbacks(execute=True):
            access.grant("2777", {"today": True}, by=self.admin)  # no account yet: nobody to tell
        told.assert_not_called()

    def test_a_bitrix_admin_who_is_no_panel_admin_is_no_admin_here(self):
        manager = Agent.objects.create_user(
            username="manager", password="x", bitrix_user_id="2600", can_official_api=True, is_bitrix_admin=True, display_name="Manager"
        )
        self.assertTrue(manager.has_admin_rights)
        self.assertFalse(access.of(manager)["any"])
        row = access.row("2600")
        self.assertEqual((row["admin"], row["effective"], row["account"]["is_wa_admin"]), (False, {"all_chats": False, "today": False, "needs": False}, False))
        access.grant("2600", {"today": True}, by=self.admin)
        self.assertEqual(access.row("2600")["effective"], {"all_chats": False, "today": True, "needs": False})
        self.client.force_login(manager)
        payload = self.client.get("/api/auth/me/").json()
        self.assertEqual((payload["is_wa_admin"], payload["lead_ai_access"]["admin"], payload["lead_ai_access"]["today"]), (True, False, True))
        self.assertEqual(self.client.get("/api/leadai/access/").status_code, 403)


class GrantedAgentTests(AccessBase):
    """A Today or Needs a person grant: the chats in full (nothing trimmed as for a responsible through the desk
    alone), and their live frames on the agent's own channel."""

    def test_a_granted_agent_sees_the_team_on_their_chats(self):
        from apps.inbox.events import group_for_agent
        from apps.leadai import handover_desk

        LeadAiChatState.objects.filter(conversation=self.handed).update(responsible_bitrix_user_id="2500", responsible_agent=self.plain)
        self.assertTrue(handover_desk.only_through_desk(self.plain, self.handed))
        self.assertEqual(handover_desk.live_groups(self.handed), ([], [group_for_agent(self.plain.pk)]))
        access.grant("2500", {"needs": True}, by=self.admin)
        plain = Agent.objects.get(pk=self.plain.pk)
        self.assertFalse(handover_desk.only_through_desk(plain, self.handed))
        self.assertFalse(handover_desk.only_through_desk(plain, self.booked))
        self.assertEqual(handover_desk.live_groups(self.handed), ([group_for_agent(plain.pk)], []))
        self.client.force_login(plain)
        rows = self.client.get("/api/leadai/chats/?needs=1").json()["results"]
        row = next(item for item in rows if item["id"] == self.handed.pk)
        self.assertTrue(set(row["number"]) - {"id", "phone_number"}, row["number"])  # the number as the team sees it

    def test_live_frames_reach_a_granted_agents_own_channel(self):
        from apps.inbox.events import group_for_agent

        mine = group_for_agent(self.plain.pk)
        self.assertNotIn(mine, lane.desk_groups_for("leadai.message.new", self.booked)[0])
        access.grant("2500", {"today": True}, by=self.admin)
        self.assertEqual(lane.desk_groups_for("leadai.message.new", self.booked), ([lane.DESK_GROUP, mine], []))
        self.assertNotIn(mine, lane.desk_groups_for("leadai.message.new", self.quiet)[0])
        self.assertNotIn(mine, lane.desk_groups_for("leadai.message.new", self.handed)[0])  # Needs a person: not granted
        self.assertEqual(lane.desk_groups_for("message.new", self.booked), ([], []))  # a plain event: no desk chat
        access.grant("2500", {"today": False, "needs": True}, by=self.admin)
        self.assertIn(mine, lane.desk_groups_for("leadai.message.new", self.handed)[0])
        self.assertNotIn(mine, lane.desk_groups_for("leadai.message.new", self.booked)[0])
        self.assertEqual(access.event_groups(self.handed), [mine])
        # The granted responsible of the chat: their channel once, in full.
        LeadAiChatState.objects.filter(conversation=self.handed).update(responsible_bitrix_user_id="2500", responsible_agent=self.plain)
        self.assertEqual(lane.desk_groups_for("leadai.message.new", self.handed), ([lane.DESK_GROUP, mine], []))
        # An agent with Lead AI access hears the desk's group instead; an inactive one nothing.
        access.grant("2500", {"all_chats": True}, by=self.admin)
        self.assertEqual(access.event_groups(self.handed), [])
        access.grant("2500", {"all_chats": False}, by=self.admin)
        self.assertEqual(access.event_groups(self.handed), [mine])
        Agent.objects.filter(pk=self.plain.pk).update(is_active=False)
        self.assertEqual(access.event_groups(self.handed), [])


class SecondReviewTests(AccessBase):
    """The second review's findings: a chat on a desk stays with the agent who answered until Done; the frames that take
    a chat out of a list still reach the agent as an id-only resync; My handovers shows a granted responsible who took
    the call."""

    def test_a_chat_on_a_desk_stays_in_needs_until_done(self):
        from apps.inbox.models import Conversation

        LeadAiChatState.objects.filter(conversation=self.handed).update(handed_over_at=None)  # a person wrote: the assistant is back
        self.assertTrue(Conversation.objects.filter(pk=self.handed.pk).filter(access.needs_q()).exists())
        access.grant("2500", {"needs": True}, by=self.admin)
        self.assertEqual(self.status(Agent.objects.get(pk=self.plain.pk), self.handed), 200)
        LeadAiChatState.objects.filter(conversation=self.handed).update(desk_done_at=timezone.now())
        self.assertFalse(Conversation.objects.filter(pk=self.handed.pk).filter(access.needs_q()).exists())
        self.assertEqual(self.status(Agent.objects.get(pk=self.plain.pk), self.handed), 404)

    def test_a_chat_out_of_the_lists_pings_the_granted_agents(self):
        from apps.inbox.events import group_for_agent

        mine = group_for_agent(self.plain.pk)
        self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet), [])
        access.grant("2500", {"today": True}, by=self.admin)
        self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet), [mine])  # not in their list: the ping
        self.assertEqual(lane.ping_groups("leadai.message.new", self.booked), [])  # in their list: the frame itself
        self.assertEqual(lane.ping_groups("message.new", self.quiet), [])  # a plain event: no desk chat
        self.assertEqual(lane.ping_groups("leadai.message.new", None), [])
        access.grant("2500", {"all_chats": True}, by=self.admin)
        self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet), [])  # the desk's group carries it

    def test_the_resync_ping_is_published_with_the_id_only(self):
        from apps.inbox import events

        access.grant("2500", {"today": True}, by=self.admin)
        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append((group, message))

        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            events.publish(self.quiet, "conversation.updated", {"id": self.quiet.pk, "secret": "the chat"})
        pings = [(group, message) for group, message in sent if message["event"] == "leadai.access.resync"]
        self.assertEqual(pings, [(events.group_for_agent(self.plain.pk), {"type": "inbox.event", "event": "leadai.access.resync", "data": {"id": self.quiet.pk, "number_id": self.quiet.number_id}})])
        self.assertNotIn(events.group_for_agent(self.plain.pk), [group for group, message in sent if message["event"] != "leadai.access.resync"])

    def test_my_handovers_shows_a_granted_responsible_who_took_the_call(self):
        from apps.leadai.models import LeadAiAppointment

        LeadAiChatState.objects.filter(conversation=self.handed).update(responsible_bitrix_user_id="2500", responsible_agent=self.plain)
        start, end = today_window(timezone.now())
        appointment = self.appointment(self.handed, starts_at=start + (end - start) / 2)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(taken_by=self.owner)
        self.client.force_login(self.plain)
        row = next(item for item in self.client.get("/api/leadai/desk/mine/").json()["results"] if item["id"] == self.handed.pk)
        self.assertEqual(row["appointment"]["taken_by"], "")  # through the desk alone: no colleague's name
        access.grant("2500", {"needs": True}, by=self.admin)
        self.client.force_login(Agent.objects.get(pk=self.plain.pk))
        row = next(item for item in self.client.get("/api/leadai/desk/mine/").json()["results"] if item["id"] == self.handed.pk)
        self.assertTrue(row["appointment"]["taken_by"])  # granted: the team as it is


    def test_a_granted_agent_may_write_templates_for_their_chats_accounts(self):
        from apps.catalog.views import _covered_waba_ids

        held = set(self.plain.visible_numbers.values_list("waba_business_id", flat=True))
        self.assertNotIn(self.booked.number.waba_business_id, held)
        self.assertEqual(_covered_waba_ids(self.plain), held)
        access.grant("2500", {"today": True}, by=self.admin)
        self.assertEqual(_covered_waba_ids(Agent.objects.get(pk=self.plain.pk)), held | {self.booked.number.waba_business_id})
        access.grant("2500", {"today": False}, by=self.admin)
        self.assertEqual(_covered_waba_ids(Agent.objects.get(pk=self.plain.pk)), held)


class ThirdReviewTests(AccessBase):
    """The third review's findings: the publisher hands the covered groups over (one routing pass); a chatter event
    sends no ping; a stopped chat with a tentative is no Needs chat; a chat moved to the inbox pings the desk and the
    granted agents."""

    def test_the_covered_groups_are_passed_through_and_chatter_sends_no_ping(self):
        from apps.inbox.events import group_for_agent

        mine = group_for_agent(self.plain.pk)
        access.grant("2500", {"today": True}, by=self.admin)
        self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet), [mine])
        self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet, covered=[mine]), [])
        self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet, covered=[]), [mine])
        with patch("apps.leadai.lane.desk_groups_for") as routing:
            self.assertEqual(lane.ping_groups("leadai.message.new", self.quiet, covered=[]), [mine])
        routing.assert_not_called()  # the caller's list is used as it is
        for event in ("leadai.message.status", "leadai.ai.state", "leadai.message.reaction"):
            self.assertEqual(lane.ping_groups(event, self.quiet), [], event)

    def test_a_stopped_chat_with_a_tentative_is_no_needs_chat(self):
        from apps.inbox.models import Conversation

        self.appointment(self.quiet, status="tentative", starts_at=None)
        self.assertTrue(Conversation.objects.filter(pk=self.quiet.pk).filter(access.needs_q()).exists())
        LeadAiChatState.objects.update_or_create(conversation=self.quiet, defaults={"stopped_at": timezone.now()})  # the customer said STOP
        self.assertFalse(Conversation.objects.filter(pk=self.quiet.pk).filter(access.needs_q()).exists())
        access.grant("2500", {"needs": True}, by=self.admin)
        self.assertEqual(self.status(Agent.objects.get(pk=self.plain.pk), self.quiet), 404)
        self.assertEqual(access.event_groups(self.quiet), [])

    def test_a_chat_moved_to_the_inbox_pings_the_desk_and_the_granted_agents(self):
        from apps.inbox import events

        access.grant("2500", {"today": True}, by=self.admin)
        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append((group, message))

        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            self.assertTrue(lane.move_to_inbox(self.booked, self.admin))
        pings = sorted(group for group, message in sent if message["event"] == "leadai.access.resync")
        self.assertEqual(pings, sorted([lane.DESK_GROUP, events.group_for_agent(self.plain.pk)]))
        self.assertTrue(all(message["data"] == {"id": self.booked.pk, "number_id": self.booked.number_id} for _, message in sent if message["event"] == "leadai.access.resync"))
        self.assertIn("conversation.updated", [message["event"] for _, message in sent])  # the plain frame still goes


class BitrixUsersTests(SimpleTestCase):
    def test_the_portals_users_are_paged_and_cached(self):
        access._users_cache.update(at=0.0, read_at=None, rows=[], error="")
        pages = [[{"ID": str(100 + n), "NAME": "A", "LAST_NAME": f"B{n}", "WORK_POSITION": "Agent"} for n in range(50)], [{"ID": "7", "NAME": "C", "LAST_NAME": "D"}]]
        with patch("apps.crmlink.client.configured", return_value=True), patch("apps.crmlink.client.call", side_effect=pages) as call:
            rows = access.bitrix_users()
            self.assertEqual(len(rows), 51)
            self.assertEqual(rows[-1], {"bitrix_user_id": "7", "name": "C D", "position": "", "email": ""})
            self.assertEqual([c.args[1]["start"] for c in call.call_args_list], [0, 50])
            self.assertEqual(len(access.bitrix_users()), 51)  # the cache, within the minute
            self.assertEqual(call.call_count, 2)
        self.assertEqual(access.bitrix_state()["users"], 51)
        access._users_cache.update(at=0.0, read_at=None, rows=[], error="")
