"""Batch 2e slice A, end to end in engine._run_claimed (spec §1.4, §1.6, §6.1; board T90, T91).

- A. the track in shadow: every shops turn stores its track and unit (state.track, state.unit, track_changed_at, the
  turn's actions), and no reply changes: a shop customer, 2d's studio seeker, a turn code answers, a general chat;
- B. the lead context in a turn: read only when a step needs it, once, shared with lead_history's read;
- C. the mixed template's first answer: never the shops' for-whom line by default; the opener for the lead's studio or
  one-bedroom; the for-whom line for a shop lead; "Not now" and "Stop messages" as the shops' own; a known end user's
  next step;
- D. migration 0008: the defaults, and rows the old code inserts during a deploy.

Each test fails without the rule it proves (the scratchpad's guards_off.py). The fakes are test_assistant's; the shops chat
is test_shops_playbook's (lead 555, Monday 12 October 2026, 14:00 Dubai).
"""

import datetime as dt
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.catalog.models import WaTemplate
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import ic_templates
from apps.leadai.assistant import rules, tracks
from apps.leadai.assistant import residential
from apps.leadai.models import DEFAULT_RESIDENTIAL_FACTS, LeadAiChatState, LeadAiSettings
from apps.leadai.tests.test_assistant import NOW, answer
from apps.leadai.tests.test_lead_context import CONTEXT, LEAD, READ, ROW
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, shop_answer
from apps.leadai.tests.test_who_the_customer_is import MAPS, NotAShopBase, line

FOR_WHOM = rules.line("for_whom", "en")
WHAT_NEED = "Great! What are you looking for: a shop, a studio or a one-bedroom, to rent or to buy?"
SPAIN_OPENER = "Great! Is the studio in Spain Cluster for yourself, or are you checking for a client?"


# A. The track in shadow ------------------------------------------------------------------------------------------------


class ShadowTrackTests(NotAShopBase):
    def test_a_shop_customer_is_the_shop_track_and_the_reply_is_the_models(self):
        message = self.inbound("I need a shop for my mobile phone business")
        reply = "A mobile phone shop, got it. Is the shop for yourself, or are you checking for a client?"
        outcome, calls, _, _ = self.turn(message, [shop_answer(reply, facts={"business_activity": "mobile phones"})])
        self.assertEqual((len(calls), self.body(outcome)), (1, reply))
        state = self.state()
        self.assertEqual((state.track, state.unit, state.track_changed_at), ("shop", "", NOW))
        self.assertEqual(self.actions(message)["track"], {"track": "shop", "unit": "", "reason": tracks.WORDS})

    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_2ds_studio_seeker_is_the_rent_track_and_still_gets_2ds_line(self):
        # Launch chat 44, exactly as test_who_the_customer_is replays it: the same words go out.
        message = self.inbound("I need an apartment studio")
        live = shop_answer(
            "Great! What business will the shop be for?",
            facts={"for_client": False, "property_type": "shop", "business_activity": "apartment studio", "intent": "rent"},
        )
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), f"{line('We have many options for a studio apartment across Dubai.')}\nOur office location: {MAPS}")
        state = self.state()
        self.assertEqual((state.track, state.unit), ("rent", "studio"))
        self.assertEqual(state.facts["need"], "home")  # 2d's own facts stay (followups.holds, the nudges, panel_note read them)
        self.assertEqual(self.actions(message)["track"], {"track": "rent", "unit": "studio", "reason": tracks.WORDS, "deal": "rent"})

    def test_the_track_moves_and_its_moment_is_kept(self):
        first = self.inbound("I need a shop for my salon")
        self.turn(first, [shop_answer("A salon, got it. Is the shop for yourself, or are you checking for a client?")])
        self.assertEqual((self.state().track, self.state().track_changed_at), ("shop", NOW))
        self.later(5)
        second = self.inbound("Sorry, actually I need a 1BR to rent", seconds_ago=10)
        self.turn(second, [shop_answer("Great! What business will the shop be for?")])
        state = self.state()
        self.assertEqual((state.track, state.unit, state.track_changed_at), ("rent", "one_br", NOW + dt.timedelta(minutes=5)))
        actions = self.actions(second)
        self.assertEqual(actions["track_changed"], {"from": "shop", "to": "rent"})
        self.assertTrue(actions["track"]["switched"])
        # A new unit on the same track refines it: the unit moves, the track's moment stays.
        self.later(10)
        third = self.inbound("A studio is also fine", seconds_ago=10)
        self.turn(third, [shop_answer("Great! What business will the shop be for?")])
        state = self.state()
        self.assertEqual((state.track, state.unit, state.track_changed_at), ("rent", "studio", NOW + dt.timedelta(minutes=5)))
        self.assertNotIn("track_changed", self.actions(third))
        # Said again, nothing moves.
        self.later(15)
        fourth = self.inbound("ok", seconds_ago=10)
        self.turn(fourth, [shop_answer("Great, I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", invited=True)])
        self.assertEqual((self.state().unit, self.state().track_changed_at), ("studio", NOW + dt.timedelta(minutes=5)))

    def test_the_models_tag_decides_when_their_words_do_not(self):
        # Their words name nothing; the model hands over as "wrong need" with a studio recorded (2d takes the handover off):
        # the track is decided again after the model, with its tag (spec §1.4, hook point 5).
        message = self.inbound("Not this one, I need something else")
        tagged = shop_answer("I see. Our team will help.", handover="wrong_need", facts={"property_type": "studio"})
        self.turn(message, [tagged])
        state = self.state()
        self.assertEqual((state.track, state.unit, state.handed_over_at), ("rent", "studio", None))
        self.assertEqual(self.actions(message)["track"]["reason"], tracks.TAG)

    def test_a_turn_code_answers_stores_its_track_too(self):
        message = self.tap("Yes, show me shops")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual((calls, self.body(outcome)), ([], FOR_WHOM))  # as before
        self.assertEqual((self.state().track, self.actions(message)["track"]["reason"]), ("shop", tracks.WORDS))

    def test_a_turn_a_person_holds_still_learns_the_track(self):
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=30), handover_reason="customer_asked_human", holding_line_at=NOW)
        message = self.inbound("I need a studio")
        self.turn(message, [shop_answer("", send=False)])
        self.assertEqual((self.state().track, self.state().unit), ("rent", "studio"))


class GeneralNoTrackTests(GeneralBase):
    def test_a_general_chat_has_no_track(self):
        message = self.inbound("I need a studio")
        self.turn(message, [answer("Sure. Which area do you prefer?")])
        state = self.state()
        self.assertEqual((state.track, state.unit, state.track_changed_at), ("", "", None))
        self.assertNotIn("track", self.actions(message))


# B. The lead context in a turn ------------------------------------------------------------------------------------------


@override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
class LeadContextTurnTests(ShopsBase):
    def test_a_plain_shops_turn_reads_the_lead_once_for_both(self):
        # lead_history reads it for the model's context; the same read keeps the lead context: one read in all.
        with patch(READ, return_value=LEAD) as read:
            self.turn(self.inbound("How much is the rent?"), [shop_answer("Type 1 is from AED 33,000 a year. What business is it for?")])
        read.assert_called_once_with("lead", 555)
        self.assertEqual(self.state().lead_context, CONTEXT)

    def test_a_turn_code_answers_reads_nothing(self):
        with patch(READ, return_value=LEAD) as read:
            self.turn(self.tap("Yes, show me shops"), [])
            self.turn(self.tap("Not now", seconds_ago=5), [])
        read.assert_not_called()
        self.assertIsNone(self.state().lead_context_at)

    def test_a_home_need_on_a_sale_listing_is_a_buyer(self):
        # "is the studio still there?" on a sale lead (spec §8's trap): the lead says sale, no rent word was said.
        sale = {**ROW, "UF_CRM_A7_RENT_SALE": "2444"}
        with patch(READ, return_value={**LEAD, "fields": sale}) as read:
            message = self.inbound("is the studio still there?")
            self.turn(message, [shop_answer("Great! What business will the shop be for?")])
        read.assert_called_once()
        state = self.state()
        self.assertEqual((state.track, state.unit, state.lead_context["deal"]), ("other", "studio", "sale"))
        self.assertEqual(self.actions(message)["track"]["deal_from"], tracks.LEAD)


# C. The mixed template's first answer -----------------------------------------------------------------------------------


class MixedBase(ShopsBase):
    """The chat's campaign went out with the mixed template (intl_city_property_reconnect)."""

    def setUp(self):
        super().setUp()
        WaTemplate.objects.filter(pk=self.template.pk).update(name=ic_templates.MIXED_NAME)
        self.template.refresh_from_db()


class MixedFirstAnswerTests(MixedBase):
    def test_the_tap_with_nothing_known_asks_what_they_want(self):
        message = self.tap("Yes, still looking")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(calls, [])  # code's, before any model
        self.assertEqual(self.body(outcome), WHAT_NEED)
        self.assertNotEqual(self.body(outcome), FOR_WHOM)
        actions = self.actions(message)
        self.assertEqual((actions["rule"], actions["track"]["track"]), ("mixed_yes:res_what_need", ""))
        self.assertEqual((self.state().track, self.state().invites), ("", 0))

    def test_a_typed_yes_in_any_language(self):
        for text, expected in (("Yes", WHAT_NEED), ("نعم", rules.line("res_what_need", "ar")), ("جی ہاں", rules.line("res_what_need", "ur"))):
            with self.subTest(text=text):
                Message.objects.filter(conversation=self.conversation, direction=Message.Direction.INBOUND).delete()
                Message.objects.filter(conversation=self.conversation, payload__source="leadai_ai").delete()
                LeadAiChatState.objects.filter(conversation=self.conversation).delete()
                outcome, calls, _, _ = self.turn(self.inbound(text), [])
                self.assertEqual((calls, self.body(outcome)), ([], expected))

    def test_the_shops_template_keeps_the_for_whom_line(self):
        WaTemplate.objects.filter(pk=self.template.pk).update(name="intl_city_shops_reconnect")
        outcome, _, _, _ = self.turn(self.tap("Yes, show me shops"), [])
        self.assertEqual(self.body(outcome), FOR_WHOM)

    def test_not_now_and_stop_messages_are_the_shops_own(self):
        message = self.tap("Not now")
        outcome, _, _, _ = self.turn(message, [])
        self.assertEqual(self.body(outcome), rules.line("check_back", "en"))
        self.assertEqual(self.state().followup_asked_at, NOW)
        self.later(5)
        stop = self.tap("Stop messages", seconds_ago=10)
        outcome, _, _, _ = self.turn(stop, [])
        self.assertEqual(self.body(outcome), rules.line("shops_stop_all", "en"))
        self.assertEqual(self.state().stop_reason, "stop_all")

    def test_a_known_shop_end_user_gets_the_shop_types(self):
        self.set_state(track="shop", facts={"for_client": False, "property_type": "shop", "business_activity": "mobile phone shop"})
        self.turn(self.tap("Yes, still looking"), [])
        self.assertEqual(self.sent_lists.call_count, 1)

    def test_a_chat_known_to_want_a_studio_gets_its_opener(self):
        self.set_state(track="rent", unit="studio")
        outcome, calls, _, _ = self.turn(self.inbound("Yes"), [])
        self.assertEqual((calls, self.body(outcome)), ([], "Great! Is the studio for yourself, or are you checking for a client?"))

    def test_who_it_is_for_known_leaves_the_rest_to_the_model(self):
        self.set_state(track="rent", unit="studio", facts={"for_client": False})
        outcome, calls, _, _ = self.turn(self.inbound("Yes"), [shop_answer("Great! Do you need a balcony, and when do you want to move in?")])
        self.assertEqual(len(calls), 1)


@override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
class MixedLeadTests(MixedBase):
    def test_a_studio_lead_gets_the_opener_for_its_studio(self):
        with patch(READ, return_value=LEAD) as read:
            message = self.tap("Yes, still looking")
            outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual((calls, self.body(outcome)), ([], SPAIN_OPENER))
        read.assert_called_once_with("lead", 555)
        state = self.state()
        self.assertEqual((state.track, state.unit, state.lead_context), ("rent", "studio", CONTEXT))
        self.assertEqual(self.actions(message)["track"]["reason"], tracks.LEAD)

    def test_a_shop_lead_gets_the_for_whom_line(self):
        shop = {"ID": "555", "SOURCE_ID": "UC_KQ0WO3", "UF_CRM_1760707292": "760"}
        with patch(READ, return_value={**LEAD, "fields": shop}):
            outcome, _, _, _ = self.turn(self.tap("Yes, still looking"), [])
        self.assertEqual(self.body(outcome), FOR_WHOM)
        self.assertEqual(self.state().track, "shop")

    def test_a_lead_bitrix_cannot_read_asks_what_they_want(self):
        from apps.crmlink import client

        with patch(READ, side_effect=client.BitrixError("down")):
            outcome, _, _, _ = self.turn(self.tap("Yes, still looking"), [])
        self.assertEqual(self.body(outcome), WHAT_NEED)
        self.assertEqual(self.state().lead_context_tries, 1)


# D. Migration 0008 -------------------------------------------------------------------------------------------------------


class MigrationTests(ShopsBase):
    def test_the_settings_row_has_the_residential_defaults(self):
        row = LeadAiSettings.load()
        self.assertEqual(row.residential_facts, DEFAULT_RESIDENTIAL_FACTS)
        self.assertEqual(row.residential_facts["rent"]["studio"], {"from": 29000, "to": 33000, "average": 31000})  # Q41
        row.residential_facts["clusters"].append("Mars")
        self.assertNotIn("Mars", DEFAULT_RESIDENTIAL_FACTS["clusters"])  # a fresh copy per row
        self.assertEqual(LeadAiChatState._meta.get_field("track").db_default, "")
        self.assertEqual(LeadAiChatState._meta.get_field("unit").db_default, "")
        self.assertEqual(LeadAiChatState._meta.get_field("lead_context_tries").db_default, 0)

    def test_rows_the_old_code_inserts_during_a_deploy_get_the_defaults(self):
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509990004"))
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {LeadAiChatState._meta.db_table} (conversation_id, facts, language, stop_reason, handover_reason, "
                "invites, responsible_bitrix_user_id, updated_at) VALUES (%s, %s, '', '', '', 0, '', %s)",
                [other.pk, "{}", timezone.now()],
            )
        state = LeadAiChatState.objects.get(conversation=other)
        self.assertEqual((state.track, state.unit, state.lead_context_tries), ("", "", 0))
        self.assertEqual((state.track_changed_at, state.lead_context, state.lead_context_at), (None, None, None))
