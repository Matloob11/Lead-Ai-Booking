"""What the first real Lead AI chat (conversation 35283, 2026-10-12) got wrong, and
the owner's 2026-10-13 decisions:

- the address went out three times: once per chat now, and the turn says so;
- "I will massage you" (message) got another invitation: a deferral rule;
- a plain "Yes" made a third invitation, which the cap then cut: no longer;
- an "English:" gloss under English replies, and a gloss that was a plan;
- "Bayut WhatsApp | Md Sumon" greeted as "Bayut";
- a playbook per Lead AI campaign; bookings, handovers and unanswered
  messages reach the Bitrix users the settings list (Matloob);
- a broker's chat is labelled Broker and stays silent until Resume;
- the reminder template goes to every active number;
- and what the review of these found: the deferral rule only for an office
  visit still tentative and only when nothing else was said, judged on what
  we sent rather than the model's flag; "I'll let u know"; the address cut
  when the model types it again, and sent again when asked for; "there", a
  lone "Md" and "Al" greet nobody; a broker after Resume is an ordinary
  handover; a refusal and an "ok" is no yes.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Agent
from apps.campaigns.models import Campaign, CampaignRecipient, CrmTarget
from apps.catalog.models import NumberAssignment, WabaNumber, WaTemplate
from apps.inbox.models import Contact, Conversation, Label, Message
from apps.leadai import lane
from apps.leadai.assistant import alerts, engine, filters, prompt, reminders, rules, schema
from apps.leadai.management.commands import leadai_eval, submit_leadai_reminder_template
from apps.leadai.models import DEFAULT_OFFICE_ADDRESS, LeadAiAlert, LeadAiAppointment, LeadAiCampaign, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, TUESDAY_5PM, Base, _outbound, answer
from apps.leadai.tests.test_eval_command import answer as eval_answer

ADDRESS = DEFAULT_OFFICE_ADDRESS
INVITATION = "Thank you. Would you like to visit our office in International City to see the shops?"
TIME_OFFER = "Great. Would 11 AM, 2 PM or 5 PM tomorrow work for you?"
MAPS = "https://maps.app.goo.gl/abc123"


class FirstChatBase(Base):
    def setUp(self):
        super().setUp()
        self.campaign = Campaign.objects.get()
        self.matloob = Agent.objects.create_user(
            username="matloob", password="x", bitrix_user_id="2311", can_official_api=True, display_name="Matloob"
        )

    def ours(self, body, minutes_ago=3, **payload):
        return _outbound(
            self.conversation, None, Message.Kind.TEXT, body, {"source": "leadai_ai", **payload},
            created_at=NOW - dt.timedelta(minutes=minutes_ago),
        )

    def set_state(self, **fields):
        state = LeadAiChatState.for_conversation(self.conversation)
        LeadAiChatState.objects.filter(pk=state.pk).update(**fields)

    def body(self, outcome):
        return Message.objects.get(pk=outcome.reply_message_id).body

    def actions(self, message):
        return LeadAiTurn.objects.get(inbound=message).actions

    def list_matloob(self):
        LeadAiSettings.objects.filter(pk=1).update(alert_bitrix_user_ids=["2311"])


# A. Playbook per Lead AI campaign -------------------------------------------------------


class PlaybookTests(FirstChatBase):
    def test_mark_campaign_takes_a_playbook_and_an_unknown_one_is_general(self):
        row = lane.mark_campaign(self.campaign)
        self.assertEqual(row.playbook, "general")
        other = Campaign.objects.create(name="CRM Leads · Lead AI · shops", number=self.number, template=self.template, created_by=self.agent)
        self.assertEqual(lane.mark_campaign(other, playbook="ic_shops").playbook, "ic_shops")
        third = Campaign.objects.create(name="CRM Leads · Lead AI · x", number=self.number, template=self.template, created_by=self.agent)
        self.assertEqual(lane.mark_campaign(third, playbook="villas<script>").playbook, "general")

    def test_a_marked_campaign_keeps_its_playbook_unless_another_is_passed(self):
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        self.assertEqual(lane.mark_campaign(self.campaign).playbook, "ic_shops")
        self.assertEqual(lane.mark_campaign(self.campaign, playbook="general").playbook, "general")
        self.assertEqual(LeadAiCampaign.objects.get(campaign=self.campaign).playbook, "general")
        self.assertEqual(LeadAiCampaign.objects.count(), 1)

    def test_a_retry_inherits_the_playbook(self):
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        retry = Campaign.objects.create(name="CRM Leads · Lead AI · ic_shops · retry", number=self.number, template=self.template, created_by=self.agent)
        lane.inherit_campaign(self.campaign, retry)
        self.assertEqual(LeadAiCampaign.objects.get(campaign=retry).playbook, "ic_shops")
        plain = Campaign.objects.create(name="plain", number=self.number, template=self.template, created_by=self.agent)
        lane.inherit_campaign(plain, Campaign.objects.create(name="plain retry", number=self.number, template=self.template, created_by=self.agent))
        self.assertEqual(LeadAiCampaign.objects.count(), 2)

    def test_the_chat_follows_the_newest_lead_ai_campaign_that_reached_it(self):
        self.assertEqual(lane.playbook_for(self.conversation), "general")  # the campaign is not a Lead AI one
        general = Campaign.objects.create(name="CRM Leads · Lead AI · old", number=self.number, template=self.template, created_by=self.agent)
        lane.mark_campaign(general)
        LeadAiChat.objects.filter(pk=self.chat.pk).update(campaign=general)
        self.assertEqual(lane.playbook_for(self.conversation), "general")
        # The shops campaign then reaches the same chat (the 16 chats of campaign #395).
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        self.assertEqual(lane.playbook_for(self.conversation), "ic_shops")
        self.assertEqual(lane.playbooks([self.conversation.pk, 999999]), {self.conversation.pk: "ic_shops"})
        LeadAiChat.objects.filter(pk=self.chat.pk).update(active=False)
        self.assertEqual(lane.playbook_for(self.conversation), "general")
        self.assertEqual(lane.playbook_for(None), "general")

    def test_a_chat_with_no_send_on_record_follows_the_campaign_that_put_it_here(self):
        CampaignRecipient.objects.all().delete()
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        LeadAiChat.objects.filter(pk=self.chat.pk).update(campaign=self.campaign)
        self.assertEqual(lane.playbook_for(self.conversation), "ic_shops")

    def test_rows_inserted_by_code_that_knows_no_playbook_are_general(self):
        # The old image keeps running for a few minutes after the migration.
        other = Campaign.objects.create(name="old code", number=self.number, template=self.template, created_by=self.agent)
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {LeadAiCampaign._meta.db_table} (campaign_id, created_at) VALUES (%s, %s)", [other.pk, timezone.now()]
            )
        self.assertEqual(LeadAiCampaign.objects.get(campaign=other).playbook, "general")

    def test_the_api_rows_carry_the_playbook(self):
        self.client.force_login(self.agent)
        row = self.client.get("/api/leadai/chats/").json()["results"][0]
        self.assertEqual((row["lead_ai_info"]["playbook"], row["lead_ai_info"]["playbook_label"]), ("general", "General"))
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        row = self.client.get("/api/leadai/chats/").json()["results"][0]
        self.assertEqual((row["lead_ai_info"]["playbook"], row["lead_ai_info"]["playbook_label"]), ("ic_shops", "International City shops"))
        detail = self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()
        self.assertEqual(detail["lead_ai_info"]["playbook"], "ic_shops")

    def test_the_turn_records_a_playbook_other_than_general(self):
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        message = self.inbound("I need a shop")
        self.turn(message, [answer()])
        self.assertEqual(self.actions(message)["playbook"], "ic_shops")


# B. Alert recipients ----------------------------------------------------------------------------


class AlertRecipientTests(FirstChatBase):
    def make_responsible(self, agent=None, bitrix_id="88"):
        self.set_state(responsible_bitrix_user_id=bitrix_id, responsible_agent=agent or self.responsible)

    def test_bookings_handovers_and_unanswered_messages_reach_the_listed_users(self):
        self.list_matloob()
        self.make_responsible()
        for kind in ("booked", "hot_lead", "tentative", "rescheduled", "cancelled", "on_my_way", "running_late",
                     "reschedule_requested", "handover", "stale"):
            with self.subTest(kind=kind):
                rows = alerts.raise_alert(kind=kind, conversation=self.conversation, title="t", text="b", dedupe_key=f"k-{kind}")
                self.assertEqual(
                    [(a.agent_id, a.bitrix_user_id) for a in rows],
                    [(self.agent.pk, "77"), (self.responsible.pk, "88"), (self.matloob.pk, "2311")],
                )

    def test_system_faults_keep_their_own_recipients(self):
        self.list_matloob()
        self.make_responsible()
        for kind in ("ai_error", "send_failed", "cap", "reminder_failed", "booking_unrecorded", "price_question", "opt_out"):
            with self.subTest(kind=kind):
                rows = alerts.raise_alert(kind=kind, conversation=self.conversation, title="t", text="b", dedupe_key=f"f-{kind}")
                self.assertEqual({a.agent_id for a in rows}, {self.agent.pk, self.responsible.pk})
        rows = alerts.raise_alert(kind="ai_down", conversation=self.conversation, title="t", text="b", dedupe_key="sys", admins=True)
        self.assertEqual([a.agent_id for a in rows], [self.admin.pk])

    def test_one_row_per_person(self):
        self.list_matloob()
        # Matloob owns the chat (he sent campaign #395): he is not alerted twice.
        Conversation.objects.filter(pk=self.conversation.pk).update(assigned_agent=self.matloob)
        self.conversation.refresh_from_db()
        rows = alerts.raise_alert(kind="booked", conversation=self.conversation, title="t", text="b", dedupe_key="own")
        self.assertEqual([a.agent_id for a in rows], [self.matloob.pk])
        # The CRM responsible is Matloob's Bitrix id, cached with no agent: listed as well, he still gets one row.
        Conversation.objects.filter(pk=self.conversation.pk).update(assigned_agent=self.agent)
        self.conversation.refresh_from_db()
        self.set_state(responsible_bitrix_user_id="2311", responsible_agent=None)
        rows = alerts.raise_alert(kind="booked", conversation=self.conversation, title="t", text="b", dedupe_key="resp")
        self.assertEqual([(a.agent_id, a.bitrix_user_id) for a in rows], [(self.agent.pk, "77"), (None, "2311")])

    def test_an_id_with_no_active_agent_is_nobody_and_a_hold_user_gets_the_panel_only(self):
        Agent.objects.filter(pk=self.matloob.pk).update(is_active=False)
        LeadAiSettings.objects.filter(pk=1).update(alert_bitrix_user_ids=["2311", "424242", "1"])
        rows = alerts.raise_alert(kind="handover", conversation=self.conversation, title="t", text="b", dedupe_key="h")
        self.assertEqual([(a.agent_id, a.bitrix_user_id) for a in rows], [(self.agent.pk, "77"), (self.admin.pk, "")])

    def test_a_booking_turn_tells_the_owner_the_responsible_and_matloob(self):
        self.list_matloob()
        self.make_responsible()
        self.turn(self.inbound("Tomorrow at 5 pm"), [answer(action="confirm", place="office", date="2026-10-13", time="17:00")])
        booked = LeadAiAlert.objects.filter(kind="booked")
        self.assertEqual({a.agent_id for a in booked}, {self.agent.pk, self.responsible.pk, self.matloob.pk})
        self.assertEqual(sorted(a.bitrix_user_id for a in booked), ["2311", "77", "88"])

    def test_the_crm_comment_still_names_the_chats_own_agents(self):
        self.list_matloob()
        self.assertEqual([a for a, _ in alerts.recipients(self.conversation)], [self.agent])

    def test_a_value_the_admin_site_wrote_unchecked_alerts_nobody_extra_and_breaks_nothing(self):
        # The Django admin does not run the panel's validation: 2311 (a number) or "2311" (a string).
        for stored, ids in ((2311, []), ("2311", []), ({"id": "2311"}, []), (["2311", 42, "x", None], ["2311", "42"])):
            with self.subTest(stored=stored):
                LeadAiSettings.objects.filter(pk=1).update(alert_bitrix_user_ids=stored)
                self.assertEqual(LeadAiSettings.load().alert_user_ids(), ids)
                rows = alerts.raise_alert(kind="booked", conversation=self.conversation, title="t", text="b", dedupe_key=f"bad-{stored!r}")
                expected = {self.agent.pk, self.matloob.pk} if ids else {self.agent.pk}
                self.assertEqual({a.agent_id for a in rows}, expected)
        self.client.force_login(self.agent)
        LeadAiSettings.objects.filter(pk=1).update(alert_bitrix_user_ids=2311)
        response = self.client.get("/api/leadai/settings/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["alert_bitrix_user_ids"], response.json()["alert_recipients"]), ([], []))

    def test_the_admin_site_shows_the_ids_and_leaves_them_to_the_panel(self):
        from django.contrib import admin as django_admin

        model_admin = django_admin.site._registry[LeadAiSettings]
        self.assertIn("alert_bitrix_user_ids", model_admin.readonly_fields)


class AlertSettingsApiTests(FirstChatBase):
    def put(self, body):
        return self.client.put("/api/leadai/settings/", body, content_type="application/json")

    def test_admins_set_the_ids_and_everyone_sees_who_they_are(self):
        self.client.force_login(self.admin)
        response = self.put({"alert_bitrix_user_ids": "2311, 2311; 424242"})
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["alert_bitrix_user_ids"], ["2311", "424242"])
        self.assertEqual(data["alert_recipients"], [{"bitrix_user_id": "2311", "name": "Matloob"}, {"bitrix_user_id": "424242", "name": ""}])
        row = LeadAiSettings.load()
        self.assertEqual(row.alert_bitrix_user_ids, ["2311", "424242"])
        self.assertIn("alert_bitrix_user_ids", row.history[-1]["changes"])
        self.assertEqual(self.put({"alert_bitrix_user_ids": ["2311"]}).json()["alert_bitrix_user_ids"], ["2311"])
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get("/api/leadai/settings/").json()["alert_recipients"], [{"bitrix_user_id": "2311", "name": "Matloob"}])

    def test_digits_only_at_most_ten_and_only_panel_admins(self):
        self.client.force_login(self.admin)
        for bad in ("23a1", "+2311", "٢٣١١", "2311 <b>", [" 1.5"]):
            with self.subTest(bad=bad):
                response = self.put({"alert_bitrix_user_ids": bad})
                self.assertEqual(response.status_code, 400)
                self.assertIn("digits only", response.json()["errors"]["alert_bitrix_user_ids"])
        eleven = ", ".join(str(1000 + n) for n in range(11))
        self.assertIn("at most 10", self.put({"alert_bitrix_user_ids": eleven}).json()["errors"]["alert_bitrix_user_ids"])
        self.assertEqual(self.put({"alert_bitrix_user_ids": ", ".join(str(1000 + n) for n in range(10))}).status_code, 200)
        self.assertEqual(self.put({"alert_bitrix_user_ids": ""}).json()["alert_bitrix_user_ids"], [])
        portal_admin = Agent.objects.create_user(username="padmin", password="x", bitrix_user_id="5", is_bitrix_admin=True)
        for user in (self.agent, portal_admin):
            self.client.force_login(user)
            self.assertEqual(self.put({"alert_bitrix_user_ids": "2311"}).status_code, 403)
        self.assertEqual(LeadAiSettings.load().alert_bitrix_user_ids, [])


# C. The address and the Maps link once per chat --------------------------------------------------


class LocationOnceTests(FirstChatBase):
    def ask_location(self, share=True, reply="Our office is in International City.", **extra):
        message = self.inbound("Where is your office?")
        outcome, calls, _, _ = self.turn(message, [answer(reply, share_location=share, **extra)])
        return message, outcome, calls

    def test_the_address_goes_out_the_first_time_and_the_turn_says_so(self):
        message, outcome, calls = self.ask_location()
        self.assertEqual(self.body(outcome), f"Our office is in International City.\nOur office location: {ADDRESS}")
        self.assertIn("LOCATION ALREADY SENT: no", calls[0][1]["content"])
        actions = self.actions(message)
        self.assertEqual(
            {key: actions[key] for key in ("invited_to_meeting", "share_office_location", "language", "location_appended")},
            {"invited_to_meeting": False, "share_office_location": True, "language": "en", "location_appended": True},
        )

    def test_never_again_once_one_of_our_messages_carried_it(self):
        # The model typed it from the OFFICE line in an earlier reply, in its own casing.
        self.ours(f"Sure, our office is at {ADDRESS.lower().replace(',', '')}.")
        message, outcome, calls = self.ask_location(reply="You can find us at the location above.")
        self.assertEqual(self.body(outcome), "You can find us at the location above.")
        self.assertIn("LOCATION ALREADY SENT: yes", calls[0][1]["content"])
        actions = self.actions(message)
        self.assertTrue(actions["share_office_location"])
        self.assertNotIn("location_appended", actions)

    def test_a_reminder_or_the_pin_counts_and_a_colleagues_message_does_not(self):
        _outbound(self.conversation, self.agent, Message.Kind.TEXT, f"We are at {ADDRESS}", {}, created_at=NOW - dt.timedelta(minutes=5))
        self.assertFalse(engine.location_sent(self.conversation, ADDRESS, ""))
        _outbound(self.conversation, None, Message.Kind.LOCATION, "Our office", {"source": "leadai_ai", "location": {}})
        self.assertTrue(engine.location_sent(self.conversation, ADDRESS, ""))
        Message.objects.filter(kind=Message.Kind.LOCATION).delete()
        _outbound(self.conversation, None, Message.Kind.INTERACTIVE, f"Hi Ahmed, a reminder:\n{MAPS}", {"source": "leadai_reminder"})
        self.assertTrue(engine.location_sent(self.conversation, "Somewhere else", MAPS))
        self.assertFalse(engine.location_sent(self.conversation, "Somewhere else", ""))

    def test_the_maps_link_goes_out_once(self):
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url=MAPS)
        _, outcome, _ = self.ask_location()
        self.assertEqual(self.body(outcome), f"Our office is in International City.\nOur office location: {MAPS}")
        later = self.inbound("Ok, which day is best?", seconds_ago=10)
        self.clock.return_value = NOW + dt.timedelta(minutes=1)
        outcome, calls, _, _ = self.turn(later, [answer("Would 11 AM or 5 PM tomorrow work for you?", share_location=True)])
        self.assertEqual(self.body(outcome), "Would 11 AM or 5 PM tomorrow work for you?")
        self.assertIn("LOCATION ALREADY SENT: yes", calls[0][1]["content"])

    def test_asked_for_again_it_goes_again(self):
        # A booked customer on the way asks for it: the confirmation had it, three hours ago.
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url=MAPS)
        self.ours(filters.confirmation("en", "Ahmed Khan", TUESDAY_5PM, ADDRESS, MAPS, True), minutes_ago=180)
        message = self.inbound("Please send me the location again")
        outcome, calls, _, _ = self.turn(message, [answer("Sure, here it is.", share_location=True)])
        self.assertEqual(self.body(outcome), f"Sure, here it is.\nOur office location: {MAPS}")
        self.assertIn("LOCATION ALREADY SENT: no", calls[0][1]["content"])

    def test_a_day_later_it_may_go_again(self):
        self.ours(f"Our office is here:\n{ADDRESS}", minutes_ago=25 * 60)
        self.assertFalse(engine.location_sent(self.conversation, ADDRESS, "", since=NOW - engine.LOCATION_FRESH))
        _, outcome, calls = self.ask_location()
        self.assertEqual(self.body(outcome), f"Our office is in International City.\nOur office location: {ADDRESS}")
        self.assertIn("LOCATION ALREADY SENT: no", calls[0][1]["content"])

    def test_the_address_typed_again_by_the_model_is_cut(self):
        # Turns 9 and 10 of the first real chat: the model retyped it from its OFFICE line.
        self.ours(f"Our office is here:\n{ADDRESS}\nWould you like to visit us?", minutes_ago=5)
        message = self.inbound("نعم", seconds_ago=20)
        reply = f"مكتبنا في {ADDRESS}. متى تود زيارتنا؟"
        outcome, _, _, _ = self.turn(message, [answer(reply, language="ar", reply_en=f"Our office is in {ADDRESS}. When would you like to visit us?")])
        self.assertEqual(self.body(outcome), "متى تود زيارتنا؟")
        self.assertNotIn("reply_en", Message.objects.get(pk=outcome.reply_message_id).payload)  # cut, so no gloss
        self.assertEqual(self.actions(message)["trimmed"], ["location"])
        # A reply that is nothing but the address stays: a repeat beats no answer.
        self.assertEqual(filters.drop_location(f"{ADDRESS}.", ADDRESS), (f"{ADDRESS}.", False))

    def test_asks_for_the_location(self):
        for text in ("Please send the location", "Send location pls", "what is your address", "share google map", "الموقع من فضلك", "لوکیشن بھیج دیں"):
            with self.subTest(text=text):
                self.assertTrue(filters.asks_for_location(text))
        for text in ("How do I reach there?", "Ok see you", "Mujhe pata nahi", ""):
            with self.subTest(text=text):
                self.assertFalse(filters.asks_for_location(text))

    def test_what_counts_as_carrying_the_address(self):
        carries = filters.carries_location
        self.assertTrue(carries(f"Our office: {ADDRESS}", ADDRESS))
        self.assertTrue(carries("russia cluster building v03 shop 20 dubai international city", ADDRESS))
        self.assertTrue(carries("We are at Russia Cluster (Building V03), Shop #20, International City.", ADDRESS))
        # The address before 2026-10-15 ("V02/V03") still reads as our office in an old message of ours.
        self.assertTrue(carries("Russia Cluster, Building V02/V03, Shop 20, Dubai International City", ADDRESS))
        self.assertEqual(ADDRESS, "Russia Cluster, Building V03, Shop 20, Dubai International City")
        self.assertFalse(carries("Our office is in Russia Cluster, International City.", ADDRESS))
        self.assertFalse(carries("A shop 200 sq ft in Russia Cluster, Building V03.", ADDRESS))
        self.assertTrue(carries(f"Here: {MAPS}", ADDRESS, MAPS))
        self.assertFalse(carries("Here.", ADDRESS, MAPS))
        self.assertTrue(carries("Shop 20, International City", "Shop 20, International City"))
        self.assertFalse(carries("Shop 20", "Shop 20, International City"))
        self.assertFalse(carries("anything", ""))
        # The model's own shortenings and orders: the words that tell this address apart are all there.
        self.assertTrue(carries("Russia Cluster, Bldg V03, Shop 20, Dubai International City", ADDRESS))
        self.assertTrue(carries("Our office: Russia Cluster, V03, Shop 20, International City, Dubai", ADDRESS))
        self.assertTrue(carries("Shop No. 20, Building V03, Russia Cluster.", ADDRESS))
        self.assertFalse(carries("Russia Cluster, V03, International City", ADDRESS))  # no shop number
        # An address only numbers tell apart is matched part by part, never by a time offer.
        self.assertFalse(carries("Would 3 PM or 5 PM work for you?", "Shop 5, Building 3, Dubai"))
        self.assertTrue(carries("We are at Shop 5, Building 3.", "Shop 5, Building 3, Dubai"))

    def test_the_prompt_says_what_to_do_when_it_was_sent(self):
        self.assertIn('If LOCATION ALREADY SENT is yes, do not repeat the address: refer to "the location above" instead.', prompt.SYSTEM)


# D. The English gloss ---------------------------------------------------------------------------


class GlossTests(FirstChatBase):
    ARABIC = "أهلاً بك. هل لديك رخصة تجارية؟"

    def reply_payload(self, completion, text="مرحبا، أحتاج محل"):
        outcome, _, _, _ = self.turn(self.inbound(text), [completion])
        return Message.objects.get(pk=outcome.reply_message_id).payload

    def test_an_english_reply_gets_none(self):
        payload = self.reply_payload(answer("Sure. What size do you need?", reply_en="Sure. What size do you need?"), "I need a shop")
        self.assertNotIn("reply_en", payload)
        payload = self.reply_payload(answer("Sure. What is the shop for?", reply_en="Planning to ask the activity."), "Hello?")
        self.assertNotIn("reply_en", payload)

    def test_a_reply_in_another_language_gets_its_translation(self):
        payload = self.reply_payload(answer(self.ARABIC, language="ar", reply_en="Welcome. Do you have a trade licence?"))
        self.assertEqual(payload["reply_en"], "Welcome. Do you have a trade licence?")

    def test_no_gloss_that_only_repeats_the_reply_or_lost_sentences(self):
        same = "Shukriya. Kya aap ke paas trade licence hai?"
        self.assertNotIn("reply_en", self.reply_payload(answer(same, language="ur_latin", reply_en=same), "Shop chahiye"))
        # The filter cut the second question: the translation of both no longer holds.
        two = "أهلاً بك. هل لديك رخصة؟ ما هو نشاطك؟"
        self.assertNotIn("reply_en", self.reply_payload(answer(two, language="ar", reply_en="Welcome. Licence? Activity?")))

    def test_sentences_settle_cut_take_the_gloss_with_them(self):
        self.set_state(invites=2)
        payload = self.reply_payload(
            answer("حسناً. يمكنك زيارة مكتبنا في أي وقت.", language="ar", reply_en="OK. You can visit our office any time."),
            "لا أستطيع الحضور",
        )
        self.assertEqual(payload.get("reply_en"), None)

    def test_the_line_code_adds_is_in_the_gloss_too(self):
        payload = self.reply_payload(answer("مكتبنا في المدينة العالمية.", language="ar", reply_en="Our office is in International City.", share_location=True))
        self.assertEqual(payload["reply_en"], f"Our office is in International City.\nOur office location: {ADDRESS}")

    def test_the_schema_and_the_prompt_ask_for_a_translation_after_the_reply(self):
        self.assertIn("sentence-by-sentence English translation of reply", schema.SCHEMA["properties"]["reply_en"]["description"])
        self.assertIn('reply_en, written after reply, is a faithful sentence-by-sentence English translation of reply', prompt.SYSTEM)
        self.assertIn("reply comes after every decision, and reply_en after reply", prompt.SYSTEM)


# E. Deferrals --------------------------------------------------------------------------------------


class DeferralRuleTests(TestCase):
    def test_whole_short_messages_that_put_the_visit_off(self):
        for text in (
            "I will message you", "I will massage you", "i will msg you", "I'll message you", "Ill message you",
            "will message you later", "I will message you later", "Ok I will message you", "ok, I will text you",
            "I will let you know", "Let you know", "I will inform you sir", "I will call you", "I will contact you",
            "Later", "later bro", "Baad mein batata hoon", "Main batata hoon", "Inform kar dunga", "I will let you know 🙏",
        ):
            with self.subTest(text=text):
                self.assertTrue(rules.is_deferral(text))
        for text in (
            "I will come later", "call me later", "I will message you my budget and the size I need tomorrow morning",
            "Yes", "I will come tomorrow at 5", "let me know the rent", "", "I confirm", "Confirm", "ok",
        ):
            with self.subTest(text=text):
                self.assertFalse(rules.is_deferral(text))

    def test_contractions_and_texting_forms(self):
        # normalize_text drops the apostrophe: "I'll" reads "ill" (the first real chat's kind of reply).
        for text in (
            "I'll let you know", "I'll text you", "I'll call you", "will let you know", "I will let u know",
            "i will msg u", "I let you know", "I'll get back to you", "Will update you", "I ll message you later",
            "ok i'll let u know", "Bata dunga", "baad me batata hun", "msg kar dunga",
        ):
            with self.subTest(text=text):
                self.assertTrue(rules.is_deferral(text))

    def test_plain_acceptances(self):
        for text in ("Yes", "yes sir", "Ok", "Sure", "okay", "Haan", "ji", "Ji haan", "نعم", "ہاں", "हाँ", "Yes please"):
            with self.subTest(text=text):
                self.assertTrue(rules.is_acceptance(text))
        for text in ("Yes but what is the rent?", "no", "International city.", "maybe"):
            with self.subTest(text=text):
                self.assertFalse(rules.is_acceptance(text))

    def test_the_fixed_line_in_every_language(self):
        self.assertEqual(rules.line("let_me_know", "en"), "Sure. Once you know the time, let me know and I'll reserve a slot for you.")
        for language in ("ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language=language):
                self.assertNotEqual(rules.line("let_me_know", language), rules.line("let_me_know", "en"))
        self.assertEqual(rules.guess_language("Baad mein batata hoon"), "ur_latin")

    def test_a_deferral_counts_only_for_a_visit_we_put_on_the_table(self):
        defer = engine.deferral
        self.assertEqual(defer(["I will message you"]), "")
        self.assertEqual(defer(["I will message you"], invites=1), "I will message you")
        self.assertEqual(defer(["Later"], offered=True), "Later")
        self.assertEqual(defer(["I will message you", ""], invites=1), "")  # a voice note last
        # The deferral alone: a question sent with it is the model's to answer.
        self.assertEqual(defer(["Where is your office? Send location", "I will let you know"], invites=1), "")
        # A person has the chat, they declined, or they are no customer of ours.
        self.assertEqual(defer(["I will message you"], invites=1, quiet=True), "")

    def test_only_an_office_visit_still_tentative_is_the_rules(self):
        defer = engine.deferral
        office = LeadAiAppointment(status="tentative", place="office")
        self.assertEqual(defer(["I will message you"], appointment=office), "I will message you")
        for status, place in (("confirmed", "office"), ("tentative", "customer_property"), ("tentative", "call")):
            with self.subTest(status=status, place=place):
                self.assertEqual(defer(["I will message you"], appointment=LeadAiAppointment(status=status, place=place), invites=1), "")

    def test_what_puts_a_visit_on_the_table(self):
        self.assertTrue(engine.visit_offered(INVITATION))
        self.assertTrue(engine.visit_offered(TIME_OFFER))  # times, with no word of a visit
        self.assertTrue(engine.visit_offered("Kal 5 baje theek rahega?"))
        self.assertTrue(engine.visit_offered("هل يناسبك الساعة 5 مساءً غداً؟"))
        self.assertFalse(engine.visit_offered("Thank you. Do you already have a trade licence for it?"))
        self.assertFalse(engine.visit_offered("Your shop of 400 sq ft, on 13 October?"))
        self.assertFalse(engine.visit_offered(""))

    def test_the_prompt_no_longer_lists_a_deferral_as_a_vague_time(self):
        self.assertNotIn("weekend, I will let you know)", prompt.SYSTEM)
        self.assertIn("A deferral is not a vague time: when they put the visit off (I will message you, I will let you know", prompt.SYSTEM)
        self.assertIn("reply only \"Sure. Once you know the time, let me know and I'll reserve a slot for you.\"", prompt.SYSTEM)


class DeferralTurnTests(FirstChatBase):
    def offered_times(self, invites=1):
        self.ours(INVITATION, minutes_ago=10)
        self.ours(TIME_OFFER, minutes_ago=3)
        self.set_state(invites=invites)

    def test_i_will_massage_you_is_a_tentative_visit_with_the_fixed_line_and_no_model(self):
        self.list_matloob()
        self.offered_times()
        message = self.inbound("I will massage you")
        outcome, calls, crm_delay, _ = self.turn(message, [answer("When would you like to come?", invited=True)])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), rules.line("let_me_know", "en"))
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual(
            (appointment.status, appointment.place, appointment.starts_at, appointment.note, appointment.customer_words),
            ("tentative", "office", None, "I will massage you", "I will massage you"),
        )
        crm_delay.assert_called_once_with(appointment.pk, "tentative", False, 1)
        tentative = LeadAiAlert.objects.filter(kind="tentative")
        self.assertEqual({a.agent_id for a in tentative}, {self.agent.pk, self.matloob.pk})
        self.assertIn("Tentative at our office: I will massage you", tentative[0].text)
        actions = self.actions(message)
        self.assertEqual(actions["rule"], "deferral")
        self.assertEqual((actions["invited_to_meeting"], actions["share_office_location"]), (False, False))
        self.assertEqual(actions["appointment"]["event"], "tentative")
        self.assertEqual(self.state().invites, 1)
        turn = LeadAiTurn.objects.get(inbound=message)
        self.assertEqual((turn.calls, turn.status), (0, "replied"))

    def test_roman_urdu_gets_roman_urdu(self):
        self.offered_times()
        message = self.inbound("baad mein batata hoon", seconds_ago=35)
        outcome, calls, _, _ = self.turn(message, [answer()])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), rules.line("let_me_know", "ur_latin"))

    def test_anything_else_said_with_it_goes_to_the_model(self):
        # A question sent in the same breath must still be answered (and its location sent).
        self.offered_times()
        self.inbound("Where exactly is your office? Send location", seconds_ago=40)
        message = self.inbound("I will let you know", seconds_ago=35)
        outcome, calls, _, _ = self.turn(message, [answer("It is in International City.", share_location=True)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), f"It is in International City.\nOur office location: {ADDRESS}")
        self.assertFalse(LeadAiAppointment.objects.exists())

    def test_the_35283_replay_with_no_invitation_counted(self):
        # Live, the model left invited_to_meeting off one invitation, and the
        # time offer after "Yes" names no visit: what we sent decides.
        self.ours(INVITATION, minutes_ago=10)
        self.inbound("International city.", seconds_ago=8 * 60)
        self.inbound("Yes", seconds_ago=7 * 60)
        self.ours(TIME_OFFER, minutes_ago=5)
        self.set_state(invites=0)
        message = self.inbound("I will massage you")
        outcome, calls, _, _ = self.turn(message, [answer("We are ready to assist when you want to visit our office. When would you like to come?")])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), rules.line("let_me_know", "en"))
        self.assertEqual(LeadAiAppointment.objects.get().status, "tentative")

    def test_a_pure_time_offer_is_a_visit_on_the_table(self):
        self.ours(TIME_OFFER)
        _, calls, _, _ = self.turn(self.inbound("I'll let you know"), [answer()])
        self.assertEqual(calls, [])
        self.assertEqual(LeadAiAppointment.objects.get().note, "I'll let you know")

    def test_a_later_to_a_campaign_that_invites_is_not_a_visit_on_the_table(self):
        # The campaign's own words ("Visit our office...") are not ours: the model answers it.
        Message.objects.filter(pk=self.campaign_message.pk).update(
            body="Hi Ahmed, shops are available in International City. Visit our office to see them. Interested?"
        )
        _, calls, _, _ = self.turn(self.inbound("Later"), [answer("Sure. What is the shop for?")])
        self.assertEqual(len(calls), 1)
        self.assertFalse(LeadAiAppointment.objects.exists())

    def assert_left_to_the_model(self):
        _, calls, _, _ = self.turn(self.inbound("ok later"), [answer("", send=False)])
        self.assertEqual(len(calls), 1)
        self.assertFalse(LeadAiAppointment.objects.exists())

    def test_not_once_they_declined(self):
        # "ok later" after the not-interested line is no visit to record or alert.
        self.offered_times()
        self.set_state(not_interested_at=NOW - dt.timedelta(minutes=2))
        self.assert_left_to_the_model()

    def test_not_while_a_person_has_the_chat(self):
        self.offered_times()
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=2), handover_reason="unclear")
        self.assert_left_to_the_model()

    def test_not_for_someone_outside_our_segments(self):
        # A job applicant (the model's last judgement): no visit is booked for them, not even tentatively.
        self.offered_times()
        LeadAiTurn.objects.create(conversation=self.conversation, calls=1, actions={"segment": "other"})
        self.assert_left_to_the_model()

    def test_an_owners_viewing_slot_or_a_call_keeps_its_place_and_time(self):
        self.offered_times()
        viewing = LeadAiAppointment.objects.create(
            conversation=self.conversation, status="tentative", place="customer_property", starts_at=TUESDAY_5PM,
            note="Tuesday 5 pm at my villa", customer_words="Tuesday 5 pm at my villa",
        )
        _, calls, crm_delay, _ = self.turn(self.inbound("I will let you know", seconds_ago=40), [answer("Sure.")])
        self.assertEqual(len(calls), 1)  # the model, which sees the OPEN APPOINTMENT
        viewing.refresh_from_db()
        self.assertEqual((viewing.place, viewing.starts_at, viewing.note), ("customer_property", TUESDAY_5PM, "Tuesday 5 pm at my villa"))
        crm_delay.assert_not_called()
        LeadAiAppointment.objects.filter(pk=viewing.pk).update(place="call", note="call me tuesday")
        _, calls, _, _ = self.turn(self.inbound("ok I will call you", seconds_ago=20), [answer("Sure.")])
        self.assertEqual(len(calls), 1)
        viewing.refresh_from_db()
        self.assertEqual((viewing.place, viewing.note), ("call", "call me tuesday"))

    def test_an_office_tentative_keeps_its_day_and_time(self):
        self.offered_times()
        wednesday = dt.datetime(2026, 10, 14, 17, 0, tzinfo=TUESDAY_5PM.tzinfo)
        visit = LeadAiAppointment.objects.create(
            conversation=self.conversation, status="tentative", place="office", starts_at=wednesday, note="Wednesday 5pm maybe"
        )
        _, calls, crm_delay, _ = self.turn(self.inbound("ok I will let you know"), [answer()])
        self.assertEqual(calls, [])
        visit.refresh_from_db()
        self.assertEqual((visit.place, visit.starts_at, visit.note), ("office", wednesday, "ok I will let you know"))
        crm_delay.assert_called_once()

    def test_a_deferral_with_a_booked_meeting_or_no_visit_offered_goes_to_the_model(self):
        self.offered_times()
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=TUESDAY_5PM)
        _, calls, _, _ = self.turn(self.inbound("I will let you know", seconds_ago=40), [answer("", send=False)])
        self.assertEqual(len(calls), 1)
        LeadAiAppointment.objects.all().delete()
        Message.objects.filter(payload__source="leadai_ai").delete()
        self.set_state(invites=0)
        # The campaign's own question ("Interested?") invites to nothing yet.
        _, calls, _, _ = self.turn(self.inbound("Later", seconds_ago=20), [answer("Sure. What is the shop for?")])
        self.assertEqual(len(calls), 1)
        self.assertFalse(LeadAiAppointment.objects.exists())

    def test_an_open_tentative_is_updated_by_the_same_path(self):
        self.offered_times()
        appointment = LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", note="Tomorrow", customer_words="Tomorrow")
        self.turn(self.inbound("I will message you"), [answer()])
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.note), ("tentative", "I will message you"))
        self.assertEqual(LeadAiAppointment.objects.count(), 1)


# F. The invitation counter ----------------------------------------------------------------------------


class InvitationCounterTests(FirstChatBase):
    def test_agreed_to_come(self):
        agreed = engine.agreed_to_come
        self.assertTrue(agreed(visit_open=True, our_last="", texts=["anything"]))
        self.assertTrue(agreed(visit_open=False, our_last=INVITATION, texts=["International city.", "Yes"]))
        self.assertFalse(agreed(visit_open=False, our_last="What is the shop for?", texts=["Yes"]))
        self.assertFalse(agreed(visit_open=False, our_last=INVITATION, texts=["Yes but what is the rent?"]))
        # The last thing said decides, acknowledgements aside: a refusal and an "ok" is a refusal.
        self.assertFalse(agreed(visit_open=False, our_last=INVITATION, texts=["No, I am travelling", "ok"]))
        self.assertFalse(agreed(visit_open=False, our_last=INVITATION, texts=["Yes", ""]))  # a voice note last
        self.assertTrue(agreed(visit_open=False, our_last=INVITATION, texts=["ok"]))
        self.assertTrue(agreed(visit_open=False, our_last=INVITATION, texts=["Sure", "👍"]))
        self.assertTrue(agreed(visit_open=False, our_last=TIME_OFFER, texts=["Yes"]))  # times offered are an invitation

    def test_the_prompt_offers_times_to_a_yes_only_when_no_time_was_named(self):
        # A yes to the one exact slot proposed is a booking (BOOKING), not a reason to offer times again.
        self.assertIn("A plain yes (yes, ok, sure, haan, ji) to an invitation that named no time means they will come", prompt.SYSTEM)
        self.assertIn("a yes to the one exact slot you proposed confirms it", prompt.SYSTEM)

    def test_a_refusal_and_an_ok_still_meets_the_cap(self):
        self.set_state(invites=2)
        self.ours("Would you like to visit our office next week instead?")
        self.inbound("No, I am travelling", seconds_ago=40)
        outcome, _, _, _ = self.turn(
            self.inbound("ok", seconds_ago=35), [answer("No problem. You are welcome to visit our office when you are back.")]
        )
        self.assertEqual(self.body(outcome), "No problem.")

    def test_settle_neither_counts_nor_cuts_once_they_agreed(self):
        offer = "Would 11 AM or 5 PM tomorrow suit you for a visit to our office?"
        agreed = engine.settle(schema.normalize(answer(offer, invited=True).data), [], ["Yes"], 2, agreed=True)
        self.assertEqual((agreed["reply"], agreed["invited_to_meeting"], agreed.get("trimmed")), (offer, False, None))
        refused = engine.settle(schema.normalize(answer(offer, invited=True).data), [], ["No"], 2)
        self.assertEqual((refused["reply"], refused["send"], refused["trimmed"]), ("", False, ["invitation"]))
        once = engine.settle(schema.normalize(answer(INVITATION, invited=True).data), [], ["I need a shop"], 1)
        self.assertTrue(once["invited_to_meeting"])

    def test_the_35283_sequence_keeps_its_time_offer(self):
        # Live, the chat already stood at two "invitations" when the customer said Yes.
        self.set_state(invites=2)
        self.ours(INVITATION, minutes_ago=4)
        self.inbound("International city.", seconds_ago=40)
        yes = self.inbound("Yes", seconds_ago=35)
        offer = "Great. Would 11 AM, 2 PM or 5 PM tomorrow work for you to visit our office?"
        outcome, calls, _, _ = self.turn(yes, [answer(offer, invited=True)])
        self.assertEqual(len(calls), 1)
        self.assertIn('"text": "International city."', calls[0][1]["content"])
        self.assertEqual(self.body(outcome), offer)
        self.assertEqual(self.state().invites, 2)
        actions = self.actions(yes)
        self.assertEqual((actions["agreed"], actions["invited_to_meeting"]), (True, False))

    def test_a_yes_to_the_first_invitation_is_not_a_second_one(self):
        self.set_state(invites=1)
        self.ours(INVITATION)
        self.turn(self.inbound("Yes"), [answer(TIME_OFFER, invited=True)])
        self.assertEqual(self.state().invites, 1)

    def test_an_open_tentative_visit_is_agreement_too(self):
        self.set_state(invites=2)
        LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", note="tomorrow")
        self.ours("Would 11 AM or 5 PM tomorrow work for you?")
        outcome, _, _, _ = self.turn(self.inbound("Which one is better to visit your office?"), [answer("Both are fine. Would you like to visit at 5 PM?", invited=True)])
        self.assertEqual(self.body(outcome), "Both are fine. Would you like to visit at 5 PM?")
        self.assertEqual(self.state().invites, 2)

    def test_a_real_refusal_still_meets_the_cap(self):
        self.set_state(invites=2)
        self.ours(INVITATION)
        outcome, _, _, _ = self.turn(self.inbound("No, I can't come"), [answer("No problem. If you change your mind, you can visit our office.")])
        self.assertEqual(self.body(outcome), "No problem.")


# G. The customer's name -----------------------------------------------------------------------------


class CustomerNameTests(FirstChatBase):
    def test_the_person_in_a_portal_title(self):
        cases = {
            "Bayut WhatsApp | Md Sumon": "Md Sumon",
            "Property Finder Call |  Ahmed  Khan ": "Ahmed Khan",
            "A | B | Sara Ali": "Sara Ali",
            "Bayut WhatsApp | ": "",
            "Missed Call | +971 50 123 4567": "",
            "Missed Call from Dubai": "",
            "Call 0501234567": "",
            "+971 (50) 123-4567": "",
            "Callum Smith": "Callum Smith",
            "Ahmed": "Ahmed",
            None: "",
            # The campaign's own greeting when a lead has no usable name (crm_leads.lead_display_name).
            "there": "",
            "There": "",
            "Customer": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(filters.person_name(raw), expected)

    def test_first_names(self):
        cases = {
            "Bayut WhatsApp | Md Sumon": "Sumon",
            "Md Sumon": "Sumon",
            "MD. SUMON": "Sumon",
            "Mr. Md Sumon": "Sumon",
            "Muhammad Asif Khan": "Asif",
            "Mohd. Imran": "Imran",
            # Before a particle the prefix is the name: never "Al" or "Bin".
            "Mohammed Al Mansouri": "Mohammed",
            "Muhammad Bin Rashid": "Muhammad",
            "Mohammad Abdul Karim": "Mohammad",
            # An abbreviation or a particle alone greets nobody; a lone Muhammad is a name.
            "Md": "",
            "Md.": "",
            "Mohd": "",
            "Md Al Amin": "",
            "Al": "",
            "Bin": "",
            "Muhammad": "Muhammad",
            "there": "",
            "Bayut WhatsApp": "",
            "Property Finder WhatsApp": "",
            "Missed Call | 971501234567": "",
            "Ahmed Khan": "Ahmed",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(filters.first_name(raw), expected)

    def test_the_assistant_greets_the_person_not_the_lead_title(self):
        CampaignRecipient.objects.update(name="Bayut WhatsApp | Md Sumon")
        message = self.inbound("Tomorrow at 5 pm")
        outcome, calls, _, _ = self.turn(message, [answer(action="confirm", place="office", date="2026-10-13", time="17:00")])
        self.assertIn("CUSTOMER NAME (from our records, may be wrong): Md Sumon\n", calls[0][1]["content"])
        self.assertTrue(self.body(outcome).startswith("Perfect, Sumon. Your meeting is confirmed."))
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual(appointment.customer_name, "Md Sumon")
        settings_row = LeadAiSettings.load()
        self.assertTrue(reminders.reminder_text(appointment, self.conversation, settings_row).startswith("Hi Sumon,"))
        self.assertTrue(LeadAiAlert.objects.filter(kind="booked", title__contains="Md Sumon").exists())

    def test_a_title_in_the_facts_or_naming_nobody_falls_back(self):
        self.assertEqual(engine._customer_name(self.conversation, {"customer_name": "Bayut WhatsApp | Md Sumon"}), "Md Sumon")
        CampaignRecipient.objects.update(name="Missed Call | +971501234567")
        self.assertEqual(engine._customer_name(self.conversation, {}), "Ahmed Khan")  # the contact's own name
        # What the campaign records now (crm_leads.lead_display_name): a first word, or "there".
        for recorded in ("there", "Md", "Al"):
            with self.subTest(recorded=recorded):
                CampaignRecipient.objects.update(name=recorded)
                self.assertEqual(engine._customer_name(self.conversation, {}), "Ahmed Khan")
                # The model copies CUSTOMER NAME into its facts: that copy names nobody either.
                self.assertEqual(engine._customer_name(self.conversation, {"customer_name": recorded}), "Ahmed Khan")
        Contact.objects.filter(pk=self.contact.pk).update(display_name="")
        self.conversation.contact.refresh_from_db()
        self.assertEqual(engine._customer_name(self.conversation, {}), "")

    def test_a_lead_with_no_name_is_greeted_by_none(self):
        CampaignRecipient.objects.update(name="there")
        Contact.objects.filter(pk=self.contact.pk).update(display_name="")
        self.conversation.contact.refresh_from_db()
        message = self.inbound("Tomorrow at 5 pm")
        outcome, calls, _, _ = self.turn(message, [answer(action="confirm", place="office", date="2026-10-13", time="17:00")])
        self.assertIn("CUSTOMER NAME (from our records, may be wrong): not known\n", calls[0][1]["content"])
        self.assertTrue(self.body(outcome).startswith("Perfect. Your meeting is confirmed."))
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual(appointment.customer_name, "")
        self.assertTrue(reminders.reminder_text(appointment, self.conversation, LeadAiSettings.load()).startswith("Hi there,"))
        self.assertEqual(reminders.first_name(appointment, self.conversation), "there")  # the template's {{1}} is never empty


# I. Brokers ------------------------------------------------------------------------------------------


class BrokerTests(FirstChatBase):
    BROKER = "I am a broker, I have a client looking for a shop around 300 sqft"

    def broker_turn(self, completion=None):
        message = self.inbound(self.BROKER)
        completion = completion or answer("Thank you. Our specialist will reply to you here.", handover="broker_or_for_client")
        outcome, calls, _, _ = self.turn(message, [completion])
        return message, outcome, calls

    def test_a_broker_is_labelled_alerted_and_answered_with_the_models_words(self):
        self.list_matloob()
        LeadAiChat.objects.filter(pk=self.chat.pk).update(campaign=self.campaign)
        message, outcome, _ = self.broker_turn()
        self.assertEqual(self.body(outcome), "Thank you. Our specialist will reply to you here.")
        self.assertEqual(list(self.conversation.labels.values_list("name", flat=True)), ["Broker"])
        state = self.state()
        self.assertIsNotNone(state.paused_at)
        self.assertIsNone(state.paused_by)
        self.assertEqual(state.handover_reason, "broker_or_for_client")
        handover = LeadAiAlert.objects.filter(kind="handover")
        self.assertEqual({a.agent_id for a in handover}, {self.agent.pk, self.matloob.pk})
        self.assertIn("is a broker or asks for a client", handover[0].text)
        self.assertIn(f"Campaign: {self.campaign.name}", handover[0].text)
        self.assertIn("stays silent in it until someone presses Resume AI", handover[0].text)
        self.assertTrue(self.actions(message)["broker"])

    def test_silent_until_resume_whatever_the_time_or_a_colleague_writes(self):
        self.broker_turn()
        later = self.inbound("Hello? What is the commission?", seconds_ago=10)
        self.assertEqual(engine.run_turn(later.pk).reason, "paused until an agent presses Resume")
        self.clock.return_value = NOW + dt.timedelta(hours=13)
        _outbound(self.conversation, self.agent, Message.Kind.TEXT, "Hi, Sapna here.", {}, created_at=NOW + dt.timedelta(hours=12))
        again = self.inbound("Any update?", seconds_ago=10)
        outcome, calls, _, _ = self.turn(again, [answer("Sure.")])
        self.assertEqual((outcome.reason, calls), ("paused until an agent presses Resume", []))
        self.assertEqual(self.state().silent_reason, "paused until an agent presses Resume")
        # Resume: the assistant answers again; the label stays for the team.
        self.client.force_login(self.agent)
        row = self.client.post(f"/api/leadai/chats/{self.conversation.pk}/resume-ai/").json()
        self.assertEqual(row["lead_ai_ai"]["mode"], "on")
        self.assertEqual([label["name"] for label in row["labels"]], ["Broker"])
        last = self.inbound("Can I see the shop with my client?", seconds_ago=5)
        outcome, calls, _, _ = self.turn(last, [answer("Sure, when would you like to come?")])
        self.assertEqual(len(calls), 1)

    def test_after_resume_a_broker_is_an_ordinary_handover(self):
        # The agent pressed Resume on purpose: no second pause, label, shops line or broker alert.
        self.list_matloob()
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        self.broker_turn()
        self.client.force_login(self.agent)
        self.client.post(f"/api/leadai/chats/{self.conversation.pk}/resume-ai/")
        self.clock.return_value = NOW + dt.timedelta(minutes=5)
        again = self.inbound("When can my client see the shop?", seconds_ago=10)
        outcome, calls, _, _ = self.turn(again, [answer("Thank you. Our specialist will reply to you here.", handover="broker_or_for_client")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), "Thank you. Our specialist will reply to you here.")
        state = self.state()
        self.assertIsNone(state.paused_at)
        self.assertIsNotNone(state.handed_over_at)  # quiet until a colleague writes, as any handover
        self.assertEqual(self.conversation.labels.count(), 1)
        alerts_sent = list(LeadAiAlert.objects.filter(kind="handover", agent=self.agent).order_by("pk"))
        self.assertEqual(len(alerts_sent), 2)
        self.assertIn("stays silent in it until someone presses Resume AI", alerts_sent[0].text)
        self.assertIn("The assistant is now quiet in this chat until someone from the team writes.", alerts_sent[1].text)
        self.assertNotIn("broker", self.actions(again))

    def test_a_shops_campaign_gets_the_build_packs_line(self):
        lane.mark_campaign(self.campaign, playbook="ic_shops")
        _, outcome, _ = self.broker_turn()
        self.assertEqual(
            self.body(outcome),
            "Thank you for your interest. Let me pass your details to the concerned agent and he will come back to you.",
        )
        self.assertEqual(engine.settle(schema.normalize(answer("x", handover="broker_or_for_client").data), [], ["x"], 0, playbook="general").get("converted"), None)

    def test_an_existing_broker_label_is_reused(self):
        existing = Label.objects.create(name="broker", colour="#123456")
        self.broker_turn()
        self.assertEqual(list(self.conversation.labels.all()), [existing])
        self.assertEqual(Label.objects.filter(name__iexact="broker").count(), 1)

    def test_a_broker_after_another_handover_is_still_labelled_paused_and_told(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=30), handover_reason="price_or_details_insisted")
        self.broker_turn(answer("", send=False, handover="broker_or_for_client"))
        self.assertIsNotNone(self.state().paused_at)
        self.assertTrue(self.conversation.labels.filter(name="Broker").exists())
        self.assertTrue(LeadAiAlert.objects.filter(kind="handover", text__contains="is a broker").exists())

    def test_the_list_filters_by_label_and_rows_carry_the_labels(self):
        self.broker_turn()
        contact = Contact.objects.create(wa_id="971509990001", display_name="Other")
        other = Conversation.objects.create(number=self.number, contact=contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=3))
        LeadAiChat.objects.create(conversation=other, active=True)
        self.client.force_login(self.agent)
        self.assertEqual(self.client.get("/api/leadai/chats/").json()["count"], 2)
        for label in ("Broker", "broker"):
            with self.subTest(label=label):
                body = self.client.get("/api/leadai/chats/", {"label": label}).json()
                self.assertEqual([row["id"] for row in body["results"]], [self.conversation.pk])
                self.assertEqual(body["results"][0]["labels"][0]["name"], "Broker")
                self.assertEqual(body["results"][0]["lead_ai_ai"]["mode"], "paused")
        self.assertEqual(self.client.get("/api/leadai/chats/", {"label": "Hot"}).json()["count"], 0)
        self.client.raise_request_exception = False
        self.assertEqual(self.client.get("/api/leadai/chats/", {"label": "x" * 65}).status_code, 400)


# J. The reminder template on every active number ---------------------------------------------------


class ReminderTemplateCommandTests(TestCase):
    def setUp(self):
        WabaNumber.objects.update(is_active=False)  # the numbers the catalog migrations seed
        self.agent = Agent.objects.create_user(username="agent", password="x", bitrix_user_id="77")
        self.assigned = WabaNumber.objects.create(phone_number="971500000001", phone_number_id="p1", waba_business_id="wA")
        self.coastline = WabaNumber.objects.create(phone_number="971581058725", phone_number_id="p2", waba_business_id="wC")
        self.coastline_2 = WabaNumber.objects.create(phone_number="971581058726", phone_number_id="p3", waba_business_id="wC")
        self.done = WabaNumber.objects.create(phone_number="971500000004", phone_number_id="p4", waba_business_id="wD")
        WabaNumber.objects.create(phone_number="971500000005", phone_number_id="p5", waba_business_id="wE", is_active=False)
        NumberAssignment.objects.create(number=self.assigned, agent=self.agent)
        WaTemplate.objects.create(
            waba_business_id="wD", name=reminders.TEMPLATE_NAME, language="en", category="UTILITY",
            status=WaTemplate.Status.PENDING, components=[],
        )

    def test_every_active_number_without_the_template_and_nothing_else(self):
        self.assertEqual(
            submit_leadai_reminder_template.active_wabas(),
            {"wA": {"971500000001"}, "wC": {"971581058725", "971581058726"}},
        )
        out = StringIO()
        with patch.object(submit_leadai_reminder_template, "_submit_template_to_waba") as submit:
            call_command("submit_leadai_reminder_template", "--dry-run", stdout=out)
        submit.assert_not_called()
        self.assertIn("wC (971581058725,971581058726) would be submitted", out.getvalue())
        self.assertNotIn("wD", out.getvalue())

    def test_a_run_submits_to_each_and_reports(self):
        made = WaTemplate(name=reminders.TEMPLATE_NAME, status=WaTemplate.Status.PENDING)
        out = StringIO()
        with patch.object(submit_leadai_reminder_template, "_submit_template_to_waba", return_value=(made, None, False)) as submit:
            call_command("submit_leadai_reminder_template", stdout=out)
        self.assertEqual(sorted(call.args[0] for call in submit.call_args_list), ["wA", "wC"])
        self.assertIn("submitted=2 skipped=0 failed=0", out.getvalue())
        WaTemplate.objects.create(waba_business_id="wA", name=reminders.TEMPLATE_NAME, language="en", category="UTILITY", status="REJECTED", components=[])
        WaTemplate.objects.create(waba_business_id="wC", name=reminders.TEMPLATE_NAME, language="en", category="UTILITY", status="APPROVED", components=[])
        out = StringIO()
        call_command("submit_leadai_reminder_template", stdout=out)
        self.assertIn("Every active number's WABA has the template already.", out.getvalue())


class MissingTemplateNoteTests(FirstChatBase):
    def test_the_settings_dialog_names_unassigned_numbers_too(self):
        WabaNumber.objects.exclude(pk=self.number.pk).update(is_active=False)  # the ones the catalog migrations seed
        self.client.force_login(self.admin)
        # Base's number has no agent, like the Coastline line the campaigns use.
        self.assertIn("971500000001", self.client.get("/api/leadai/settings/").json()["numbers_without_reminder_template"])
        WaTemplate.objects.create(
            waba_business_id="waba1", name=reminders.TEMPLATE_NAME, language="en", category="UTILITY",
            status=WaTemplate.Status.APPROVED, components=[],
        )
        self.assertEqual(self.client.get("/api/leadai/settings/").json()["numbers_without_reminder_template"], [])


# The eval mirrors the engine ------------------------------------------------------------------------


def scenario(scenario_id):
    return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)


class EvalMirrorTests(TestCase):
    def run_with(self, scenario_id, completion):
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion) as model:
            run = leadai_eval.run_once(scenario(scenario_id), scenario_id)
        return run, model

    def test_the_address_is_added_once_as_live(self):
        run, _ = self.run_with("location-request", eval_answer("Our office is in International City.", share_location=True))
        self.assertEqual(run.out, f"Our office is in International City.\nOur office location: {ADDRESS}")
        self.assertEqual(run.failures, [])
        self.assertIn("LOCATION ALREADY SENT: no", leadai_eval.build(scenario("location-request")).context)
        run, _ = self.run_with("location-again", eval_answer("It is in the message above.", share_location=True))
        self.assertEqual(run.out, "It is in the message above.")
        self.assertIn("LOCATION ALREADY SENT: yes", leadai_eval.build(scenario("location-again")).context)
        # As live, the address typed again is cut (engine.settle) and code's line points to it
        # (engine.point_to_location); a reply that is only the address becomes that line.
        pointer = rules.line("location_above", "en")
        run, _ = self.run_with("location-again", eval_answer(f"Sure, we are at {ADDRESS}. See you soon."))
        self.assertEqual((run.out, run.failures), (f"{pointer} See you soon.", []))
        self.assertEqual(run.answer["trimmed"], ["location"])
        run, _ = self.run_with("location-again", eval_answer(f"We are at {ADDRESS}."))
        self.assertEqual((run.out, run.failures, run.answer["pointed"]), (pointer, [], "location"))
        # The model's own times, with no word of the location (two of batch 2a's runs): the line opens it.
        run, _ = self.run_with("location-again", eval_answer("Would you like to visit us tomorrow at 10 AM, 2 PM or 5 PM?"))
        self.assertEqual((run.out, run.failures), (f"{pointer} Would you like to visit us tomorrow at 10 AM, 2 PM or 5 PM?", []))

    def test_asked_for_again_the_location_goes_again_as_live(self):
        again = leadai_eval.Scenario(
            "x", "x", new=["Please send the location again"], chat=scenario("location-again").chat, expect=[leadai_eval.sends_location()]
        )
        self.assertFalse(leadai_eval.build(again).location_sent)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=eval_answer("Sure.", share_location=True)):
            run = leadai_eval.run_once(again, "x")
        self.assertEqual(run.out, f"Sure.\nOur office location: {ADDRESS}")

    def test_an_english_reply_with_a_gloss_is_noted_not_counted(self):
        # The engine drops reply_en for English replies, so it does not hold the 95% gate.
        run, _ = self.run_with("shop-activity", eval_answer(reply_en="Asking for the business activity."))
        self.assertEqual(run.failures, [])
        self.assertIn('reply_en is set for an English reply: "Asking for the business activity."', run.notes)

    def test_deferrals_are_settled_by_code_with_the_fixed_line(self):
        for scenario_id in ("defer-message", "defer-massage"):
            with self.subTest(scenario_id):
                run, model = self.run_with(scenario_id, eval_answer("When would you like to come?"))
                model.assert_not_called()
                self.assertEqual(run.failures, [])
                self.assertEqual((run.action, run.out_by, run.out), ("tentative", leadai_eval.CODE, rules.line("let_me_know", "en")))

    def test_a_bare_yes_needs_exact_times_and_no_repeated_address(self):
        run, _ = self.run_with("yes-to-invite", eval_answer("Great! When would you like to come?"))
        self.assertIn("offers 0 exact time(s), expected at least 2", run.failures)
        run, _ = self.run_with("yes-to-invite", eval_answer(f"Great. Would 11 AM or 5 PM tomorrow work? We are at {ADDRESS}."))
        self.assertEqual((run.out, run.failures), ("Great. Would 11 AM or 5 PM tomorrow work?", []))  # the repeat is cut
        run, _ = self.run_with("yes-to-invite", eval_answer(TIME_OFFER, invited=True))
        self.assertEqual(run.failures, [])
        self.assertFalse(run.answer["invited_to_meeting"])  # settled: agreement is no new invitation

    def test_a_yes_to_the_one_slot_proposed_is_a_booking(self):
        run, _ = self.run_with("yes-to-slot", eval_answer("", action="confirm", place="office", date="2026-10-13", time="17:00"))
        self.assertEqual(run.failures, [])
        run, _ = self.run_with("yes-to-slot", eval_answer(TIME_OFFER))
        self.assertIn("nothing booked (action none), expected Tue 13 Oct 17:00", run.failures)

    def test_the_new_scenarios_are_listed(self):
        ids = {s.id for s in leadai_eval.SCENARIOS}
        self.assertLessEqual({"location-request", "location-again", "yes-to-invite", "yes-to-slot", "defer-message", "defer-massage"}, ids)
        context = leadai_eval.build(scenario("defer-massage")).context
        rows = [json.loads(row) for row in context.split("CONVERSATION (oldest first):\n", 1)[1].split("\n\nNEW SINCE", 1)[0].splitlines()]
        self.assertEqual([row["text"] for row in rows[-4:]], ["International city.", "Yes", TIME_OFFER, "I will massage you"])
