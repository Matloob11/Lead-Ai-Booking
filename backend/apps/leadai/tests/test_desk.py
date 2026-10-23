"""The agent desk on the Lead AI screen (batch 2e spec §2.12 and §3.3; board T100, T94; Q30, Q37, Q39).

- Q37 (Matloob, 2026-10-17): the chats are not assigned; the agents with Lead AI access follow them on the Lead AI screen.
  Lead AI access is a product access in Agents & access (Agent.can_lead_ai): such an agent opens every Lead AI chat on
  any number, with no number assigned, gets its alerts and hears its live events; one without still gets 404, and the
  main inbox list still leaves Lead AI chats out;
- the track chip and ?track=, read as the engine will (a shops chat nobody answered since 2e is a shop; 2d's stored
  studio need is "Rent · Studio"; the mixed template's silent chat is "Not known yet");
- Needs a person (?needs=1): handed over or paused for a broker with nobody from the team writing since, and the open
  tentatives that hold a time or a full name; the longest wait first;
- Today (?today=1): every open visit and call of today, Dubai time, by start time, with who took a call;
- I'll call: the first agent wins under a row lock, a second gets 409 with the first one's name;
- Q39: a heads-up 15 minutes before a booked call nobody took and an urgent alert 10 minutes after its start, to
  everyone on the chat, never a word to the customer;
- a rent or sale chat's alert title starts with its track.
"""

import datetime as dt
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Agent
from apps.campaigns.models import CrmTarget
from apps.campaigns.services import create_campaign
from apps.catalog.models import NumberAssignment, WabaNumber, WaTemplate
from apps.inbox.models import Contact, Conversation, Label, Message
from apps.inbox.visibility import visible_conversation_q
from apps.leadai import bitrix_status, desk, ic_templates, lane
from apps.leadai.assistant import alerts, engine, hours
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiOptOut, LeadAiSettings

UTC = dt.timezone.utc


def today_at(hour: int, minute: int = 0) -> dt.datetime:
    """A moment of today in Dubai time, whatever the clock says now (the Today list holds the whole day)."""
    day = hours.now_dubai().date()
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=hours.DUBAI)


class DeskBase(TestCase):
    def setUp(self):
        self.admin = Agent.objects.create_user(
            username="admin", password="x", bitrix_user_id="1", can_official_api=True, is_wa_admin=True, display_name="Admin"
        )
        # The campaign sender: every Lead AI chat is his today (2311).
        self.owner = Agent.objects.create_user(
            username="matloob", password="x", bitrix_user_id="2311", can_official_api=True, display_name="Matloob"
        )
        # Lead AI access, no number assigned (Q37).
        self.desker = Agent.objects.create_user(
            username="sara", password="x", bitrix_user_id="2400", can_official_api=True, can_lead_ai=True, display_name="Sara Khan"
        )
        self.second = Agent.objects.create_user(
            username="omar", password="x", bitrix_user_id="2401", can_official_api=True, can_lead_ai=True, display_name="Omar"
        )
        # No Lead AI access; holds another number.
        self.plain = Agent.objects.create_user(
            username="plain", password="x", bitrix_user_id="2500", can_official_api=True, display_name="Plain"
        )
        self.number = WabaNumber.objects.create(phone_number="971581058725", phone_number_id="pn1", waba_business_id="waba1")
        self.other_number = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba2")
        NumberAssignment.objects.create(number=self.other_number, agent=self.plain)
        self.shops_template = self.template("ic_shops_followup")
        self.mixed_template = self.template(ic_templates.MIXED_NAME)
        self.shops_campaign = self.campaign(self.shops_template, playbook=lane.IC_SHOPS)
        self.mixed_campaign = self.campaign(self.mixed_template, playbook=lane.IC_SHOPS)
        self.general_campaign = self.campaign(self.shops_template, playbook=lane.GENERAL)
        self.phones = iter(f"9715012{n:05d}" for n in range(1, 99999))

    def template(self, name):
        return WaTemplate.objects.create(
            waba_business_id="waba1", name=name, language="en", category="MARKETING", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "Hello {{1}}"}],
        )

    def campaign(self, template, *, playbook):
        campaign = create_campaign(
            agent=self.owner, number=self.number, template=template,
            recipients=[{"phone": "971509999999", "name": "Ali", "variables": {"1": "Ali"}}],
            name="CRM Leads · desk", variables={}, crm_target=CrmTarget.NONE,
        )
        lane.mark_campaign(campaign, playbook=playbook)
        return campaign

    def chat(self, *, campaign=None, active=True, name="", **state):
        contact = Contact.objects.create(wa_id=next(self.phones), profile_name=name)
        conversation = Conversation.objects.create(number=self.number, contact=contact, assigned_agent=self.owner)
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=timezone.now(), last_message_preview="Hi")
        LeadAiChat.objects.create(conversation=conversation, active=active, campaign=campaign or self.shops_campaign, crm_entity="lead", crm_id=77)
        if state:
            LeadAiChatState.objects.create(conversation=conversation, **state)
        return conversation

    def appointment(self, conversation, *, status="confirmed", place="office", starts_at=None, **fields):
        return LeadAiAppointment.objects.create(
            conversation=conversation, status=status, place=place, starts_at=starts_at, customer_name=fields.pop("customer_name", "Ahmed Khan"),
            **fields,
        )

    def say(self, conversation, body, *, direction="out", minutes_ago=0, **payload):
        return Message.objects.create(
            conversation=conversation, direction=direction, kind="text", body=body, payload=payload,
            created_at=timezone.now() - dt.timedelta(minutes=minutes_ago),
        )

    def rows(self, user, query=""):
        self.client.force_login(user)
        response = self.client.get(f"/api/leadai/chats/{query}")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


# Q37: who may open the Lead AI chats --------------------------------------------------------------------------------


class AccessTests(DeskBase):
    def test_lead_ai_access_opens_every_lead_ai_chat_with_no_number_assigned(self):
        chat = self.chat()
        self.assertFalse(NumberAssignment.objects.filter(agent=self.desker).exists())
        self.assertEqual([row["id"] for row in self.rows(self.desker)["results"]], [chat.pk])
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get(f"/api/leadai/chats/{chat.pk}/").status_code, 200)
        # Reading and answering go through the inbox's own thread endpoints.
        self.assertEqual(self.client.get(f"/api/inbox/conversations/{chat.pk}/messages/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/inbox/conversations/{chat.pk}/read/").status_code, 200)

    def test_and_answers_it_from_the_lead_ai_screen(self):
        chat = self.chat()

        def sent(conversation, agent, body, **kwargs):
            return Message.objects.create(conversation=conversation, direction="out", kind="text", body=body, sent_by=agent)

        self.client.force_login(self.desker)
        with patch("apps.inbox.services.send_text", side_effect=sent):
            response = self.client.post(
                f"/api/inbox/conversations/{chat.pk}/send/", {"kind": "text", "body": "Hello, this is Sara from our team."},
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.client.force_login(self.plain)
        with patch("apps.inbox.services.send_text", side_effect=sent):
            refused = self.client.post(
                f"/api/inbox/conversations/{chat.pk}/send/", {"kind": "text", "body": "Hi"}, content_type="application/json"
            )
        self.assertEqual(refused.status_code, 404)

    def test_an_agent_without_lead_ai_access_still_gets_404(self):
        chat = self.chat()
        self.assertEqual(self.rows(self.plain)["results"], [])
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get(f"/api/leadai/chats/{chat.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/inbox/conversations/{chat.pk}/messages/").status_code, 404)

    def test_holding_the_number_alone_is_no_lead_ai_access(self):
        # Q37: access never depends on number assignments; an agent put on a campaign number sees what they saw before.
        chat = self.chat()
        NumberAssignment.objects.create(number=self.number, agent=self.plain)
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get(f"/api/leadai/chats/{chat.pk}/").status_code, 404)

    def test_the_main_inbox_list_still_leaves_lead_ai_chats_out(self):
        lead_ai = self.chat()
        contact = Contact.objects.create(wa_id="971501111111")
        mine = Conversation.objects.create(number=self.other_number, contact=contact, assigned_agent=self.desker)
        self.client.force_login(self.desker)
        ids = [row["id"] for row in self.client.get("/api/inbox/conversations/").json()["results"]]
        self.assertIn(mine.pk, ids)
        self.assertNotIn(lead_ai.pk, ids)

    def test_a_chat_moved_back_to_the_inbox_is_no_desk_chat(self):
        moved = self.chat(active=False)
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get(f"/api/inbox/conversations/{moved.pk}/messages/").status_code, 404)

    def test_lead_ai_access_needs_the_official_api_inbox_too(self):
        chat = self.chat()
        Agent.objects.filter(pk=self.desker.pk).update(can_official_api=False)
        self.desker.refresh_from_db()
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get(f"/api/leadai/chats/{chat.pk}/").status_code, 404)
        self.assertFalse(lane.has_desk_access(self.desker))

    def test_nobody_else_pays_a_query_for_the_desk(self):
        self.assertIsNone(lane.desk_q(self.plain))
        with self.assertNumQueries(0):
            lane.desk_q(self.plain)
            # The handover desk's clause (handover_desk.mine_q) is a Subquery: built, never run here.
            clause = visible_conversation_q(self.plain, held=WabaNumber.objects.none())
        self.assertNotIn("LeadAiChat", str(clause))
        # An agent who is no Bitrix user cannot have a handover desk: no clause at all.
        nobody = Agent.objects.create_user(username="nobody", password="x", can_official_api=True)
        with self.assertNumQueries(0):
            self.assertNotIn("lead_ai_chat", str(visible_conversation_q(nobody, held=WabaNumber.objects.none())))

    def test_a_panel_admin_grants_lead_ai_access_in_agents_and_access(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.post(f"/api/catalog/agents/{self.desker.pk}/admin/", {"can_lead_ai": False}, content_type="application/json").status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(f"/api/catalog/agents/{self.plain.pk}/admin/", {"can_lead_ai": True}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["can_lead_ai"])
        self.plain.refresh_from_db()
        self.assertTrue(self.plain.can_lead_ai)
        rows = {row["id"]: row for row in self.client.get("/api/catalog/agents/").json()}
        self.assertTrue(rows[self.plain.pk]["can_lead_ai"])
        self.assertFalse(rows[self.owner.pk]["can_lead_ai"])

    def test_the_settings_name_who_has_lead_ai_access(self):
        self.client.force_login(self.plain)
        names = [row["name"] for row in self.client.get("/api/leadai/settings/").json()["desk_agents"]]
        self.assertEqual(names, ["Sara Khan", "Omar"])


class AlertTests(DeskBase):
    def raise_booked(self, conversation, kind="booked"):
        return alerts.raise_alert(kind=kind, conversation=conversation, title="Meeting booked: Ahmed", text="Ahmed is booked.")

    def test_the_agents_with_lead_ai_access_get_the_chats_alerts(self):
        chat = self.chat()
        rows = self.raise_booked(chat)
        self.assertEqual({row.agent_id for row in rows}, {self.owner.pk, self.desker.pk, self.second.pk})
        self.assertNotIn(self.plain.pk, {row.agent_id for row in rows})

    def test_and_see_it_in_the_panel_since_they_can_open_the_chat(self):
        chat = self.chat()
        row = next(row for row in self.raise_booked(chat) if row.agent_id == self.desker.pk)
        with patch("apps.inbox.events.publish_to_agent") as panel, patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True}):
            alerts.deliver(row)
        panel.assert_called_once()
        self.assertEqual(panel.call_args.args[0], self.desker.pk)

    def test_one_row_per_person_when_the_list_names_a_desk_agent_too(self):
        LeadAiSettings.objects.update_or_create(pk=1, defaults={"alert_bitrix_user_ids": ["2400", "2311"]})
        rows = self.raise_booked(self.chat())
        agents = [row.agent_id for row in rows]
        self.assertEqual(sorted(agents), sorted(set(agents)))
        self.assertEqual(agents.count(self.desker.pk), 1)

    def test_a_chat_back_in_the_main_inbox_alerts_its_own_people_only(self):
        rows = self.raise_booked(self.chat(active=False))
        self.assertEqual({row.agent_id for row in rows}, {self.owner.pk})

    def test_a_kind_off_the_list_stays_with_the_chats_own_people(self):
        rows = self.raise_booked(self.chat(), kind="reminder_failed")
        self.assertEqual({row.agent_id for row in rows}, {self.owner.pk})

    def test_system_alerts_still_go_to_the_panel_admins(self):
        rows = alerts.raise_alert(kind="ai_down", conversation=self.chat(), title="OpenAI is down", text="x", admins=True)
        self.assertEqual({row.agent_id for row in rows}, {self.admin.pk})

    def test_a_rent_or_sale_chats_alert_title_starts_with_its_track(self):
        rent = self.chat(track="rent", unit="studio")
        shop = self.chat(track="shop")
        self.assertTrue(self.raise_booked(rent)[0].title.startswith("Rent · Studio · Meeting booked"))
        self.assertEqual(self.raise_booked(shop)[0].title, "Meeting booked: Ahmed")
        sale = self.chat(track="sale", unit="one_br")
        self.assertTrue(self.raise_booked(sale)[0].title.startswith("Sale · 1BR · "))

    def test_a_title_that_names_the_track_itself_is_left_alone(self):
        rent = self.chat(track="rent", unit="studio")
        row = alerts.raise_alert(kind="booked", conversation=rent, title="Rent · Studio: viewing booked for Ahmed", text="x")[0]
        self.assertEqual(row.title, "Rent · Studio: viewing booked for Ahmed")
        sale = self.chat(track="sale", unit="studio")
        row = alerts.raise_alert(kind="booked", conversation=sale, title="Sales call: Ahmed, 4:30 PM", text="x")[0]
        self.assertEqual(row.title, "Sale · Studio · Sales call: Ahmed, 4:30 PM")

    def test_an_alert_raised_again_for_the_responsible_names_its_track_once(self):
        rent = self.chat(track="rent", unit="studio")
        since = timezone.now() - dt.timedelta(minutes=1)
        self.raise_booked(rent)
        responsible = Agent.objects.create_user(username="resp", password="x", bitrix_user_id="2298", can_official_api=True)
        LeadAiChatState.objects.filter(conversation=rent).update(responsible_bitrix_user_id="2298", responsible_agent=responsible)
        alerts.reach_responsible(rent, since)
        row = LeadAiAlert.objects.get(conversation=rent, agent=responsible)
        self.assertEqual(row.title.count("Rent · Studio"), 1)


class LiveTests(DeskBase):
    def test_a_desk_agent_who_is_no_panel_admin_listens_on_the_desk_group(self):
        self.assertEqual(lane.desk_groups(self.desker), [lane.DESK_GROUP])
        self.assertEqual(lane.desk_groups(self.plain), [])
        Agent.objects.filter(pk=self.admin.pk).update(can_lead_ai=True)
        self.admin.refresh_from_db()
        self.assertEqual(lane.desk_groups(self.admin), [])  # the number groups carry it already

    def test_the_consumer_joins_it(self):
        from apps.inbox.consumers import InboxConsumer

        # The plain method, not the database_sync_to_async wrapper: the wrapper closes the thread's connection first
        # (close_old_connections), which inside a TestCase's transaction is the test's own, and since round 25 the
        # desk access is a query (access.of).
        self.assertIn(lane.DESK_GROUP, InboxConsumer()._groups_for(self.desker))
        self.assertNotIn(lane.DESK_GROUP, InboxConsumer()._groups_for(self.plain))

    def test_a_lead_ai_chats_events_reach_the_desk_group_and_no_other_chats_do(self):
        from apps.inbox import events

        lead_ai = self.chat()
        contact = Contact.objects.create(wa_id="971502222222")
        normal = Conversation.objects.create(number=self.number, contact=contact, assigned_agent=self.owner)
        sent = []

        class Layer:
            async def group_send(self, group, message):
                sent.append((group, message["event"]))

        with patch("apps.inbox.events.get_channel_layer", return_value=Layer()):
            events.publish(lead_ai, "message.new", {})
            events.publish(normal, "message.new", {})
        self.assertIn((lane.DESK_GROUP, "leadai.message.new"), sent)
        self.assertNotIn((lane.DESK_GROUP, "message.new"), sent)


# The track chip and ?track= -----------------------------------------------------------------------------------------


class TrackTests(DeskBase):
    def label_of(self, conversation, user=None):
        rows = {row["id"]: row for row in self.rows(user or self.desker)["results"]}
        return rows[conversation.pk]["lead_ai_ai"]["track_label"]

    def test_the_stored_track_and_unit(self):
        chat = self.chat(track="rent", unit="studio")
        self.assertEqual(self.label_of(chat), "Rent · Studio")
        self.client.force_login(self.desker)
        detail = self.client.get(f"/api/leadai/chats/{chat.pk}/").json()["lead_ai_ai"]
        self.assertEqual((detail["track"], detail["unit"], detail["track_label"]), ("rent", "studio", "Rent · Studio"))

    def test_a_shops_chat_nobody_answered_since_2e_is_a_shop_not_unknown(self):
        self.assertEqual(self.label_of(self.chat()), "Shop")

    def test_the_mixed_templates_silent_chat_is_not_known_yet(self):
        self.assertEqual(self.label_of(self.chat(campaign=self.mixed_campaign)), "Not known yet")

    def test_2ds_stored_studio_need_reads_as_rent_studio(self):
        # Campaigns 448/449: "I need an apartment studio" got 2d's office invitation; no 2e turn has run yet.
        chat = self.chat(facts={"need": "home", "wanted": "a studio apartment"})
        self.assertEqual(self.label_of(chat), "Rent · Studio")

    def test_a_general_chat_has_no_track_chip(self):
        chat = self.chat(campaign=self.general_campaign, track="")
        self.assertEqual(self.label_of(chat), "")

    def test_the_track_filters(self):
        shop = self.chat()
        rent = self.chat(track="rent", unit="one_br")
        sale = self.chat(track="sale", unit="studio")
        other = self.chat(facts={"need": "home", "wanted": "a 2 bedroom apartment"})
        unknown = self.chat(campaign=self.mixed_campaign)
        general = self.chat(campaign=self.general_campaign)
        ids = lambda track: {row["id"] for row in self.rows(self.desker, f"?track={track}")["results"]}  # noqa: E731
        self.assertEqual(ids("shop"), {shop.pk})
        self.assertEqual(ids("rent"), {rent.pk})
        self.assertEqual(ids("sale"), {sale.pk})
        self.assertEqual(ids("other"), {other.pk})
        self.assertEqual(ids("unknown"), {unknown.pk})
        self.assertNotIn(general.pk, ids("shop") | ids("unknown"))
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get("/api/leadai/chats/?track=villa").status_code, 400)

    def test_a_shops_chat_that_moved_to_a_general_campaign_drops_its_track(self):
        chat = self.chat(campaign=self.general_campaign, track="rent", unit="studio")
        self.assertEqual(self.label_of(chat), "")
        self.assertEqual(self.rows(self.desker, "?track=rent")["results"], [])


# Needs a person -----------------------------------------------------------------------------------------------------


class NeedsTests(DeskBase):
    def needs(self, user=None, query=""):
        body = self.rows(user or self.desker, f"?needs=1{query}")
        return body, [row["id"] for row in body["results"]]

    def test_a_handover_nobody_answered_is_listed_with_why(self):
        # "Can you call me at 5?": the model handed the chat over for a call, and nobody from the team has written since.
        chat = self.chat(handed_over_at=timezone.now() - dt.timedelta(minutes=40), handover_reason="call_requested")
        self.say(chat, "Can you call me at 5?", direction="in", minutes_ago=41)
        self.say(chat, "Sure, our agent will call you.", minutes_ago=39, source="leadai_ai")
        body, ids = self.needs()
        self.assertEqual(ids, [chat.pk])
        self.assertEqual(body["results"][0]["lead_ai_desk"]["reasons"], ["Handed over: asked for a call"])
        self.assertEqual(body["results"][0]["lead_ai_desk"]["kinds"], ["handover"])

    def test_once_a_person_writes_it_leaves_the_list(self):
        chat = self.chat(handed_over_at=timezone.now() - dt.timedelta(minutes=40), handover_reason="customer_asked_human")
        self.say(chat, "Hello, this is Omar from our team. How can I help?", minutes_ago=5)
        self.assertEqual(self.needs()[1], [])

    def test_our_reminder_and_the_campaigns_own_template_are_no_person(self):
        chat = self.chat(handed_over_at=timezone.now() - dt.timedelta(minutes=40), handover_reason="customer_asked_human")
        self.say(chat, "Reminder: your meeting is today at 5 PM.", minutes_ago=10, source="leadai_reminder")
        from apps.campaigns.models import CampaignRecipient

        CampaignRecipient.objects.filter(campaign=self.shops_campaign).update(conversation=chat)
        Message.objects.create(
            conversation=chat, direction="out", kind="template", template=self.shops_template, body="",
            created_at=timezone.now() - dt.timedelta(minutes=5),
        )
        self.assertEqual(self.needs()[1], [chat.pk])

    def test_a_brokers_pause_is_listed_until_a_person_writes(self):
        chat = self.chat(paused_at=timezone.now() - dt.timedelta(hours=2))
        body, ids = self.needs()
        self.assertEqual(ids, [chat.pk])
        self.assertEqual(body["results"][0]["lead_ai_desk"]["reasons"], ["Broker: waiting for a person"])
        self.say(chat, "Hi, which unit is your client looking for?", minutes_ago=1)
        self.assertEqual(self.needs()[1], [])

    def test_an_agents_own_pause_or_bitrix_handover_is_taken_already(self):
        self.chat(paused_at=timezone.now(), paused_by=self.owner, handed_over_at=timezone.now(), handover_reason="call_requested")
        self.chat(paused_at=timezone.now(), handed_over_at=timezone.now(), handover_reason=bitrix_status.HANDED_REASON)
        self.assertEqual(self.needs()[1], [])

    def test_a_broker_set_in_bitrix_is_taken_already(self):
        chat = self.chat(paused_at=timezone.now() - dt.timedelta(minutes=5), handed_over_at=timezone.now() - dt.timedelta(minutes=5), handover_reason=engine.BROKER)
        LeadAiAlert.objects.create(kind="bitrix_status", conversation=chat, title="Broker set in Bitrix", text="x", dedupe_key="bitrix_status:x")
        self.assertEqual(self.needs()[1], [])

    def test_held_tentatives_a_time_or_a_full_name(self):
        held_time = self.chat()
        self.appointment(held_time, status="tentative", starts_at=today_at(17))
        held_name = self.chat()
        self.appointment(held_name, status="tentative", starts_at=today_at(16), details={"held_for_name": True})
        no_time = self.chat()
        self.appointment(no_time, status="tentative", note="may come")
        body, ids = self.needs()
        self.assertEqual(set(ids), {held_time.pk, held_name.pk})
        reasons = {row["id"]: row["lead_ai_desk"]["reasons"] for row in body["results"]}
        self.assertEqual(reasons[held_time.pk], ["Held 5:00 PM"])
        self.assertEqual(reasons[held_name.pk], ["Held 4:00 PM: no full name yet"])

    def test_the_longest_wait_first_and_a_stopped_chat_left_out(self):
        newer = self.chat(handed_over_at=timezone.now() - dt.timedelta(minutes=10), handover_reason="complaint_or_upset")
        older = self.chat(handed_over_at=timezone.now() - dt.timedelta(hours=3), handover_reason="call_requested")
        self.chat(handed_over_at=timezone.now() - dt.timedelta(hours=5), handover_reason="call_requested", stopped_at=timezone.now())
        # "No thanks, not interested" after the handover: nobody chases them.
        said_no = self.chat(handed_over_at=timezone.now() - dt.timedelta(hours=4), handover_reason="call_requested", not_interested_at=timezone.now())
        self.appointment(said_no, status="tentative", starts_at=today_at(18))
        self.assertEqual(self.needs()[1], [older.pk, newer.pk])

    def test_only_the_chats_the_agent_may_open_and_the_count(self):
        chat = self.chat(handed_over_at=timezone.now(), handover_reason="call_requested")
        self.assertEqual(self.needs(self.plain)[1], [])
        body = self.rows(self.desker)
        self.assertEqual(body["desk_counts"], {"needs": 1, "today": 0})
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get("/api/leadai/desk/").json(), {"needs": 1, "today": 0})
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get("/api/leadai/desk/").json(), {"needs": 0, "today": 0})
        self.assertTrue(chat.pk)

    def test_needs_and_today_together_is_refused(self):
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get("/api/leadai/chats/?needs=1&today=1").status_code, 400)


# Today --------------------------------------------------------------------------------------------------------------


class TodayTests(DeskBase):
    def test_every_open_visit_and_call_of_today_by_time(self):
        visit = self.chat()
        self.appointment(visit, starts_at=today_at(16))
        call = self.chat()
        self.appointment(call, place="call", starts_at=today_at(16, 30), details={"track": "sale"}, taken_by=self.second, taken_at=timezone.now())
        held = self.chat()
        self.appointment(held, status="tentative", starts_at=today_at(17))
        early = self.chat()
        self.appointment(early, starts_at=today_at(10))
        tomorrow = self.chat()
        self.appointment(tomorrow, starts_at=today_at(16) + dt.timedelta(days=1))
        cancelled = self.chat()
        self.appointment(cancelled, status="cancelled", starts_at=today_at(12))
        body = self.rows(self.desker, "?today=1")
        self.assertEqual([row["id"] for row in body["results"]], [early.pk, visit.pk, call.pk, held.pk])
        lines = {row["id"]: row["lead_ai_desk"] for row in body["results"]}
        self.assertEqual(lines[visit.pk]["label"], "Visit 4:00 PM")
        self.assertEqual((lines[call.pk]["label"], lines[call.pk]["taken_by"]), ("Call 4:30 PM", "Omar"))
        self.assertEqual(lines[held.pk]["label"], "Held 5:00 PM")
        self.assertEqual(body["desk_counts"]["today"], 4)


# I'll call ----------------------------------------------------------------------------------------------------------


class TakeTests(DeskBase):
    def setUp(self):
        super().setUp()
        self.conversation = self.chat(track="sale", unit="studio")
        self.call = self.appointment(
            self.conversation, place="call", starts_at=timezone.now() + dt.timedelta(hours=1), details={"track": "sale"}
        )

    def take(self, user, pk=None):
        self.client.force_login(user)
        return self.client.post(f"/api/leadai/chats/{pk or self.conversation.pk}/appointment/take/")

    def test_the_card_offers_ill_call_until_someone_takes_it(self):
        self.client.force_login(self.desker)
        card = self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()["lead_ai_appointment"]
        self.assertEqual((card["call_label"], card["takeable"], card["taken_by"]), ("Sales call", True, ""))

    def test_the_first_agent_takes_it_and_a_second_gets_409_with_the_name(self):
        before = Message.objects.filter(conversation=self.conversation).count()
        first = self.take(self.desker)
        self.assertEqual(first.status_code, 200)
        card = first.json()["lead_ai_appointment"]
        self.assertEqual((card["taken_by"], card["taken_by_id"], card["takeable"]), ("Sara Khan", self.desker.pk, False))
        second = self.take(self.second)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["taken_by"], "Sara Khan")
        self.assertIn("Sara Khan has already taken this call", second.json()["detail"])
        self.call.refresh_from_db()
        self.assertEqual(self.call.taken_by, self.desker)
        self.assertIsNotNone(self.call.taken_at)
        self.assertEqual([entry["event"] for entry in self.call.history], ["taken"])
        # The customer is never told who.
        self.assertEqual(Message.objects.filter(conversation=self.conversation).count(), before)

    def test_taking_it_again_changes_nothing(self):
        self.take(self.desker)
        taken_at = LeadAiAppointment.objects.get(pk=self.call.pk).taken_at
        self.assertEqual(self.take(self.desker).status_code, 200)
        self.assertEqual(LeadAiAppointment.objects.get(pk=self.call.pk).taken_at, taken_at)

    def test_no_open_call_is_409_and_a_chat_one_cannot_open_is_404(self):
        LeadAiAppointment.objects.filter(pk=self.call.pk).update(status="cancelled")
        self.assertEqual(self.take(self.desker).status_code, 409)
        visit = self.chat()
        self.appointment(visit, starts_at=timezone.now() + dt.timedelta(hours=2))
        self.assertEqual(self.take(self.desker, visit.pk).status_code, 409)
        self.assertEqual(self.take(self.plain).status_code, 404)

    def test_the_chats_owner_without_desk_access_may_take_it_too(self):
        self.assertEqual(self.take(self.owner).status_code, 200)


# Q39: a booked call nobody has taken --------------------------------------------------------------------------------


class CallAlertTests(DeskBase):
    def setUp(self):
        super().setUp()
        self.now = timezone.now().replace(microsecond=0)
        self.conversation = self.chat(track="sale", unit="one_br")
        LeadAiAppointment.objects.filter(conversation=self.conversation).delete()

    def call(self, start, booked_ago=dt.timedelta(hours=2), **fields):
        row = self.appointment(self.conversation, place="call", starts_at=start, details={"track": "sale"}, **fields)
        LeadAiAppointment.objects.filter(pk=row.pk).update(created_at=self.now - booked_ago)
        return LeadAiAppointment.objects.get(pk=row.pk)

    def sent(self, kind):
        return list(LeadAiAlert.objects.filter(kind=kind).order_by("pk"))

    def test_a_heads_up_15_minutes_before_to_everyone_on_the_chat(self):
        self.call(self.now + dt.timedelta(minutes=12))
        desk.call_alerts(self.now)
        rows = self.sent(desk.CALL_SOON)
        self.assertEqual({row.agent_id for row in rows}, {self.owner.pk, self.desker.pk, self.second.pk})
        self.assertEqual({row.priority for row in rows}, {"normal"})
        self.assertTrue(rows[0].title.startswith("Sale · 1BR · Call at "))
        self.assertIn("nobody has taken it yet", rows[0].text)
        # Once.
        desk.call_alerts(self.now + dt.timedelta(minutes=1))
        self.assertEqual(len(self.sent(desk.CALL_SOON)), len(rows))

    def test_not_earlier_and_not_for_a_call_booked_inside_the_window(self):
        self.call(self.now + dt.timedelta(minutes=20))
        desk.call_alerts(self.now)
        self.assertEqual(self.sent(desk.CALL_SOON), [])
        LeadAiAppointment.objects.all().delete()
        self.call(self.now + dt.timedelta(minutes=10), booked_ago=dt.timedelta(minutes=2))
        desk.call_alerts(self.now)
        self.assertEqual(self.sent(desk.CALL_SOON), [])

    def test_an_urgent_alert_10_minutes_after_the_start(self):
        row = self.call(self.now - dt.timedelta(minutes=8))
        desk.call_alerts(self.now)
        self.assertEqual(self.sent(desk.CALL_UNTAKEN), [])
        desk.call_alerts(self.now + dt.timedelta(minutes=3))
        rows = self.sent(desk.CALL_UNTAKEN)
        self.assertTrue(rows)
        self.assertEqual({r.priority for r in rows}, {"high"})
        self.assertIn("Nobody has taken the call with Ahmed Khan yet", rows[0].title)
        self.assertEqual({r.appointment_id for r in rows}, {row.pk})
        desk.call_alerts(self.now + dt.timedelta(minutes=9))
        self.assertEqual(len(self.sent(desk.CALL_UNTAKEN)), len(rows))

    def test_nothing_for_a_taken_call_nor_a_word_to_the_customer(self):
        self.call(self.now + dt.timedelta(minutes=10), taken_by=self.desker, taken_at=self.now)
        before = Message.objects.count()
        desk.call_alerts(self.now)
        desk.call_alerts(self.now + dt.timedelta(minutes=25))
        self.assertEqual(LeadAiAlert.objects.filter(kind__in=(desk.CALL_SOON, desk.CALL_UNTAKEN)).count(), 0)
        self.assertEqual(Message.objects.count(), before)

    def test_a_call_moved_later_gets_its_heads_up_again(self):
        row = self.call(self.now + dt.timedelta(minutes=10))
        desk.call_alerts(self.now)
        first = len(self.sent(desk.CALL_SOON))
        later = self.now + dt.timedelta(hours=2)
        LeadAiAppointment.objects.filter(pk=row.pk).update(starts_at=later)
        desk.call_alerts(later - dt.timedelta(minutes=10))
        self.assertEqual(len(self.sent(desk.CALL_SOON)), 2 * first)

    def test_nobody_is_alerted_to_call_a_customer_who_said_stop(self):
        LeadAiChatState.objects.filter(conversation=self.conversation).update(stopped_at=self.now)
        self.call(self.now + dt.timedelta(minutes=10))
        desk.call_alerts(self.now)
        self.assertEqual(self.sent(desk.CALL_SOON), [])
        LeadAiChatState.objects.filter(conversation=self.conversation).update(stopped_at=None)
        LeadAiOptOut.objects.create(phone=self.conversation.contact.wa_id, source=LeadAiOptOut.Source.LEADAI_STOP)
        desk.call_alerts(self.now)
        self.assertEqual(self.sent(desk.CALL_SOON), [])

    def test_an_office_visit_never_gets_call_alerts_and_a_call_no_office_heads_up(self):
        from apps.leadai import tasks

        visit = self.chat()
        self.appointment(visit, starts_at=self.now + dt.timedelta(minutes=10))
        desk.call_alerts(self.now)
        self.assertFalse(LeadAiAlert.objects.filter(kind__in=(desk.CALL_SOON, desk.CALL_UNTAKEN)).exists())
        call = self.call(timezone.now() + dt.timedelta(minutes=30))
        tasks._agent_heads_up()
        self.assertFalse(LeadAiAlert.objects.filter(kind="upcoming", appointment=call).exists())

    def test_the_sweep_runs_it(self):
        from apps.leadai import tasks

        self.call(timezone.now() + dt.timedelta(minutes=10))
        with patch("apps.leadai.tasks._reminders"), patch("apps.leadai.tasks._follow_ups"):
            tasks.send_due_reminders()
        self.assertTrue(LeadAiAlert.objects.filter(kind=desk.CALL_SOON).exists())
