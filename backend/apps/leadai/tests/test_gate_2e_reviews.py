"""Batch 2e, the reviews of 2026-10-17 that ran beside the real-model gate's round 1 (review-customer-replay,
review-eval-integrity) and the CRM-safety review: each finding on the words or the state that broke it.

- A. what their words say (tracks, needs): a buyer of a one-bedroom never read as a renter; a buyer's own rent words keep the
  sale track; "Not shops" keeps the home the chat is on; "flat" the adjective and the shop's own room stay a shop's; an old
  shop lead's cluster is no home's; a tap on the shop list is the shop track; our office's cluster and one turned down are
  nobody's wish;
- B. the rent flow's guards (residential): rented elsewhere only with a place; no name out of "Insha Allah"; no monthly
  figure; the commission in code's words only; the price before the full name; no colleague named; the claims, availability,
  screening and PDPL guards widened;
- C. whole turns: the not-known track's neutral confirmation; a broker books nothing; a move needs the full name; the shop
  list tap; the mixed template's opener records the want; a sales call moved stays a call; photos with a call booked; the
  price before the name; "delete my data" plans 2311's to-do;
- D. Bitrix: a Client Type never posted unread; a place change closes the old to-do; a person's edit of the C39 fields kept;
  Lead AI access only from a panel admin;
- E. the nudge words off the shop track; the queued photos stop once a person was asked for;
- F. the eval: the gate's every-run rule and the shop baseline, the checks' own patterns, the scenarios' promised checks,
  CODE scenarios that hold against the model's own handover, a mirror of each fix, and each scenario failing with its fix off;
- G. the guard-off runs on the merged branch: the one guard they found with no test of its own (offer_slots after the five
  questions);
- H. what those guards must never cut, found by probing them before the commit: "Yes, our agent will meet you" (no name),
  a yearly band beside "today at 5 PM" (no monthly figure), "Is the deposit one month's rent?" (no commission question), "a
  bedroom set" (no home), a move's hold that lapsed, and a value another chat of ours wrote on the lead (no person's edit).
"""

import copy
import datetime as dt
import types
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from apps.accounts.models import Agent
from apps.catalog.models import WabaNumber
from apps.inbox.models import Conversation, Message
from apps.leadai import followups, tasks, unit_media
from apps.leadai.assistant import calls, crm, crm_fields, engine, needs, openai_client, residential, rules, sales, tracks
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import (
    LeadAiAlert, LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiCrmField, LeadAiTurn, LeadAiUnitMediaSet,
)
from apps.leadai.tests.test_assistant import NOW, fake_send_text
from apps.leadai.tests.test_crm_writes import IDLE_LEAD, CrmWritesBase, FakeBitrix
from apps.leadai.tests.test_desk import DeskBase
from apps.leadai.tests.test_eval_command import MODEL, RIGHT
from apps.leadai.tests.test_followups_mixed import MixedFollowUpBase
from apps.leadai.tests.test_follow_up_holds import at as fat
from apps.leadai.tests.test_lead_context import LEAD, READ
from apps.leadai.tests.test_reminders_crm import BITRIX, RcBase, todo
from apps.leadai.tests.test_residential_turns import INVITE_4_6, KNOWN, RentBase, res_answer
from apps.leadai.tests.test_sales_calls import BUYER, BUYER_LINE, FULL_NAME_ASK, NAMED, SLOTS_3_5, SubjectBitrix, model
from apps.leadai.tests.test_sales_calls import normal as sale_normal
from apps.leadai.tests.test_shop_media import CLIENT, MediaBase
from apps.leadai.tests.test_shops_playbook import at
from apps.leadai.tests.test_tracks_turns import MixedBase
from apps.leadai.tests.test_unit_media import STUDIO_1722, ImportTests

F = crm_fields
RENT, SALE, SHOP, OTHER = tracks.RENT, tracks.SALE, tracks.SHOP, tracks.OTHER
EMPTY_ONLY = {"only_if_empty": True}


def decide(words, **kwargs):
    return tracks.decide(words=list(words), **kwargs)


def normal(completion):
    """A model answer as the guards read it (RES_SCHEMA's, normalised)."""
    from apps.leadai.assistant import schema

    return schema.normalize(copy.deepcopy(completion.data), shops=True, residential=True)


def scenario(scenario_id):
    return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)


def run_eval(scenario_id, completion=None):
    with patch(MODEL, return_value=completion or RIGHT[scenario_id]), override_settings(LEADAI_OPENAI_API_KEY="test"):
        return leadai_eval.run_once(scenario(scenario_id), scenario_id)


# A. What their words say -------------------------------------------------------------------------------------------------


class TrackReadingTests(SimpleTestCase):
    def test_a_buyer_of_a_one_bedroom_is_never_told_the_rent(self):
        # review-customer-replay (OneBedroomBuyer): _PROPERTY had no bedroom form, and "studio, to buy" broke "<unit> to buy".
        for words, unit in (
            ("I want to buy a one-bedroom", "one_br"), ("one-bedroom, to buy", "one_br"), ("1BR, to buy", "one_br"),
            ("studio, to buy", "studio"), ("Looking to buy a one-bedroom", "one_br"), ("I want to purchase 1BR flat", "one_br"),
            ("Interested in buying a one bedroom apartment", "one_br"), ("buy, studio", "studio"), ("to buy 1BR", "one_br"),
            ("1br kharidna hai", "one_br"),
        ):
            with self.subTest(words):
                self.assertEqual(needs.detect([words]).kind, needs.BUY)
                decision = decide([words], template_kind="mixed")
                self.assertEqual((decision.track, decision.unit, decision.deal), (SALE, unit, SALE))
        # Never furniture, and their own unit let out is no purchase.
        self.assertIsNone(needs.detect(["I want to buy a bed"]))
        self.assertEqual(needs.detect(["I want to rent out my 1BR"]).kind, needs.SELL)
        self.assertEqual(decide(["I need a one bedroom"], template_kind="mixed").track, RENT)

    def test_a_buyers_own_rent_words_keep_the_sale_track(self):
        # review-customer-replay (BuyerToRent): any rent word switched a stored sale track to rent.
        for words in (
            "No, not for rent. Vacant, own use", "Rented one is fine, I will lease it out anyway", "Investment. What is the rental yield?",
            "how much rent can I get from it", "a studio with good rental income", "I will rent it out",
        ):
            with self.subTest(words):
                self.assertEqual(decide([words], stored=SALE, stored_unit="studio").track, SALE)
        for words in ("I want to rent instead", "Actually I am looking to rent", "rent, not buy", "Not buying, rent", "I want a studio for rent"):
            with self.subTest(words):
                self.assertEqual(decide([words], stored=SALE, stored_unit="studio").track, RENT)
        # Off the sale track a rent word still decides rent over a sale lead; a buyer's income words never do.
        self.assertTrue(tracks.said_rent(["I need a studio to rent"]))
        self.assertFalse(tracks.said_rent(["What is the rental yield?"]))

    def test_never_asked_keeps_the_home_the_chat_is_on(self):
        # review-customer-replay (NeverAskedAgain, chats 68 and 132): a bare denial outranked the stored rent track.
        for words in ("Not shops", "No shop!", "I never asked for any shop"):
            with self.subTest(words):
                decision = decide([words], stored=RENT, stored_unit="studio")
                self.assertEqual((decision.track, decision.unit, decision.sorry), (RENT, "studio", True))
        kept = decide(["Not shops"], facts={"need": "home", "wanted": "a studio", "property_type": "studio"})
        self.assertEqual((kept.track, kept.unit, kept.sorry), (RENT, "studio", True))
        sale = decide(["No shop"], stored=SALE, stored_unit="one_br")
        self.assertEqual((sale.track, sale.unit), (SALE, "one_br"))
        # With nothing known, 2d's other track as before.
        self.assertEqual(decide(["Not shops"]).track, OTHER)

    def test_a_shop_customers_words_about_the_shop_stay_on_the_shop_track(self):
        # review-customer-replay (ShopPulledOff): "flat" the adjective, the flats above it, the shop's own room.
        for words in (
            "Is the rent flat or negotiable?", "Can you give it flat 30k?", "30k flat final", "flats above the shop?",
            "Does it have a small room inside?", "is there a room for my staff to sleep?",
        ):
            with self.subTest(words):
                self.assertIsNone(needs.detect([words]))
                self.assertEqual(decide([words], stored=SHOP).track, SHOP)
        # On a shop track, a home named with no wish for it moves nothing; a wish does.
        self.assertEqual(decide(["Is there an apartment above the shop? Is it rented?"], stored=SHOP).track, SHOP)
        self.assertEqual(decide(["Actually I need a flat for my family"], stored=SHOP).track, RENT)
        self.assertEqual(decide(["I need rent flat"]).track, RENT)
        self.assertEqual(needs.detect(["I need a room for my staff"]).noun, "room")  # their wish: a room, the other track

    def test_an_old_shop_leads_cluster_is_no_homes(self):
        # review-customer-replay (ShopLeadCluster): a France Cluster shop lead's "I need a 1BR" got the European band.
        shop_lead = {"source": "Bayut", "property": "shop", "cluster": "France"}
        decision = decide(["I need a 1BR"], lead=shop_lead)
        self.assertEqual((decision.track, decision.unit, decision.clusters), (RENT, "one_br", ()))
        flat_lead = {"source": "Bayut", "property": "apartment", "unit": "one_br", "cluster": "France", "deal": "rent"}
        self.assertEqual(decide(["I need a 1BR"], lead=flat_lead).clusters, ("France",))
        self.assertEqual(unit_media.lead_clusters(shop_lead), ())
        self.assertEqual(unit_media.lead_clusters(flat_lead), ("France",))
        self.assertNotIn("Cluster: France", residential.summary_lines({}, shop_lead, track=RENT, unit="one_br"))

    def test_a_tap_on_the_shop_list_is_the_shop_track(self):
        # review-customer-replay (OldShopListTap): a studio seeker's tap on 2d's shop list got the type's media on rent.
        self.assertTrue(engine.flow_taps([("Type 2 – Medium", "type_2")]))
        self.assertTrue(engine.flow_taps([("Book viewing", "")]))
        self.assertFalse(engine.flow_taps([("Yes, book a viewing", "")]))  # Template B's button is no card's
        self.assertFalse(engine.flow_taps([("", "")]))
        decision = decide(["Type 2 – Medium"], stored=RENT, stored_unit="studio", shop_tap=True)
        self.assertEqual((decision.track, decision.switched), (SHOP, True))

    def test_our_offices_cluster_and_one_turned_down_are_nobodys_wish(self):
        # The CRM review: "see you at the Russia cluster office" and "I dont want China cluster" named clusters.
        self.assertEqual(tracks.clusters_in(["Ok see you at the Russia cluster office at 5"]), ())
        self.assertEqual(tracks.clusters_in(["Is your office in Russia cluster?"]), ())
        self.assertEqual(tracks.clusters_in(["I dont want China cluster"]), ())
        self.assertEqual(tracks.clusters_in(["I don't want China cluster"]), ())
        self.assertEqual(tracks.clusters_in(["Not Spain cluster, I want England cluster"]), ("England",))
        self.assertEqual(tracks.clusters_in(["a studio in Russia cluster near your office"]), ("Russia",))
        self.assertEqual(tracks.clusters_in(["no preference, Spain cluster or France cluster"]), ("Spain", "France"))


# B. The rent flow's guards --------------------------------------------------------------------------------------------


class GuardTests(SimpleTestCase):
    def test_rented_elsewhere_needs_a_place_and_a_fact(self):
        # review-customer-replay (LostByMistake): any object, a condition, "mil gaya" alone read as rented elsewhere.
        for words in (
            "I already got the location, thanks. What should I bring?", "Already got your message. Can I come 30 min early?",
            "For myself. I already moved to Dubai last week, what are the options?", "If the owner gives 30k, deal done", "Ok mil gaya, thanks",
            "Did you already rent a flat?",
        ):
            with self.subTest(words):
                self.assertFalse(residential.rented_elsewhere([words]))
        for words in (
            "We already found a flat, thanks", "Already rented, thanks", "I found another place", "not looking anymore", "flat mil gaya",
            "I took a studio in JVC", "found one already",
        ):
            with self.subTest(words):
                self.assertTrue(residential.rented_elsewhere([words]))
        # Never a confirmed viewing cancelled from the reading alone.
        answer = normal(res_answer("Great!"))
        residential.settle(answer, [], ["We already found a flat, thanks"], track=RENT, unit="studio", visit_open=True)
        self.assertEqual(answer["opt_out"], "none")
        answer = normal(res_answer("Great!"))
        residential.settle(answer, [], ["We already found a flat, thanks"], track=RENT, unit="studio")
        self.assertEqual((answer["opt_out"], answer["lost_reason"]), (rules.NOT_INTERESTED, residential.RENTED_REASON))

    def test_no_name_out_of_words_of_conversation(self):
        # review-customer-replay (NameFallback): "Perfect, Insha Allah! Your viewing is confirmed".
        for words in ("Same as WhatsApp", "Insha Allah", "Khuda hafiz", "Myself only", "Jazak Allah Khair", "Masha Allah"):
            with self.subTest(words):
                self.assertEqual(residential.name_from_reply(words), "")
        self.assertEqual(residential.name_from_reply("Ahmed Khan"), "Ahmed Khan")
        self.assertEqual(residential.name_from_reply("my name is amin qureshi"), "Amin Qureshi")

    def test_no_monthly_figure_on_the_rent_track(self):
        # review-customer-replay (Charges): the deposit's figure let "roughly AED 2,500 a month" through.
        for sentence in ("Studios here are around AED 29,000–33,000 a year, so roughly AED 2,500 a month.", "about AED 3,500 a month", "a monthly rent of AED 2,500"):
            with self.subTest(sentence):
                self.assertTrue(residential.monthly_figure(sentence))
        for sentence in ("Rent here is paid yearly, in 1 to 4 cheques depending on the owner.", "There is no monthly option.", "Ejari is AED 350."):
            with self.subTest(sentence):
                self.assertFalse(residential.monthly_figure(sentence))
        answer = normal(res_answer("Studios here are around AED 29,000–33,000 a year, so roughly AED 2,500 a month."))
        residential.settle(answer, [], ["how much per month?"], track=RENT, unit="studio")
        self.assertEqual(
            answer["reply"],
            "Studios in International City are generally around AED 29,000–33,000 a year. Rent here is paid yearly, in 1 to 4 cheques depending on the owner.",
        )

    def test_the_commission_by_any_name_is_code_s(self):
        # review-customer-replay (CommissionWords): "any agent fee?", "your fee", "5% of the annual rent", "one month's rent".
        for words in ("any agent fee?", "what is your fee?", "broker charges?", "is it 5% of the rent?"):
            with self.subTest(words):
                self.assertTrue(residential.asks_commission([words]))
        answer = normal(res_answer("Usually it's around one month's rent, paid when you sign."))
        residential.settle(answer, [], ["any agent fee?"], track=RENT, unit="studio")
        self.assertEqual(answer["reply"], residential.line("res_commission_first", "en"))
        # A figure asked right after code's first line: the figure line, never the model's words.
        earlier = [("customer", "Is there any commission?"), ("assistant", residential.line("res_commission_first", "en"))]
        answer = normal(res_answer("It's usually 5% of the annual rent."))
        residential.settle(answer, earlier, ["how much exactly?"], track=RENT, unit="studio")
        self.assertEqual(answer["reply"], residential.commission_figure_line("en", "studio"))
        self.assertFalse(residential.asks_commission_figure(earlier, ["how much is the rent?"]))

    def test_the_price_goes_before_the_full_name(self):
        # review-customer-replay (PriceAndBook): only the full-name ask went, the band dropped.
        spec = residential.price_spec(["Just tell me the price and book a call today at 5"], SALE, "studio")
        answer = normal(model("", action="confirm", place="call", date="2026-10-12", time="17:00"))
        residential.hold_for_name(answer, at(12, 17), price=spec)
        text = residential.render(answer["res_line"], "en")
        self.assertEqual(text, f"{sales.price_line('en', 'studio')} {FULL_NAME_ASK}")
        rent = residential.price_spec(["How much is the rent? book me today 6 pm"], RENT, "studio", ("Spain",))
        self.assertEqual(
            residential.price_text(rent, "en"), "Studios in Spain Cluster are generally around AED 29,000–33,000 a year."
        )
        self.assertIsNone(residential.price_spec(["book me today 6 pm"], RENT, "studio"))

    def test_no_colleague_named(self):
        # review-customer-replay (PeopleAndNumbers): "Our agent Shoaib will meet you", "Manhial from our team will get back".
        for sentence in ("Our agent Shoaib will meet you at the office.", "Manhial from our team will get back to you here shortly.", "Imran, our agent, will call you."):
            with self.subTest(sentence):
                self.assertTrue(residential.names_colleague(sentence))
        for sentence in ("Our agent will meet you at the office.", "Our agent will meet you at our office in Russia Cluster.", "Thanks, Ahmed!"):
            with self.subTest(sentence):
                self.assertFalse(residential.names_colleague(sentence))
        self.assertEqual(residential.staff_names(["Manhial told me already, ask him"]), {"manhial"})
        self.assertEqual(residential.staff_names(["he told me already, ask him", "the owner said 30k"]), set())
        answer = normal(res_answer("Manhial will reply to you here. Do you prefer a balcony?"))
        residential.settle(answer, [], ["Manhial told me already, ask him"], track=RENT, unit="studio")
        self.assertEqual(answer["reply"], "Do you prefer a balcony?")

    def test_the_claims_guard_reads_a_booking_in_other_words(self):
        # review-customer-replay (AllSet): "Here are some photos", "Sending you the photos now", "set for 4 PM", "all set".
        for sentence in (
            "Sure! Here are some photos of our apartments.", "Here are a few pictures.", "Sending you the photos now.",
            "Your viewing is set for 4 PM.", "You're all set for 4 PM tomorrow.", "It's locked in.", "See you at 4 PM!",
        ):
            with self.subTest(sentence):
                self.assertTrue(residential.claims_done(sentence))
        booked = dt.datetime(2026, 10, 12, 16, 0, tzinfo=NOW.tzinfo)
        self.assertFalse(residential.claims_done("See you at 4 PM!", booked))  # the time they have
        self.assertFalse(residential.claims_done("See you at the viewing!", booked))
        self.assertTrue(residential.claims_done("See you at 5 PM!", booked))
        self.assertTrue(residential.photo_claim_only("Here are some photos of our apartments."))

    def test_the_guards_widened_by_the_eval_review(self):
        self.assertTrue(residential.claims_availability("There is a vacant studio in Spain Cluster right now."))
        self.assertTrue(residential.claims_availability("We currently have two studios in France Cluster."))
        self.assertFalse(residential.claims_availability("Do you prefer a vacant unit or a tenanted one?"))
        # A buyer's own wish said back reads as a claim to the policy check (leadai_eval.no_availability_claim), so since the
        # gate's round 5 the guard cuts it too (availability_talk); their next question still goes.
        self.assertTrue(residential.claims_availability("Got it, a vacant unit for your own use."))
        self.assertTrue(residential.screens("The owner prefers families."))
        self.assertTrue(residential.asks_private("Please WhatsApp me a photo of your Emirates ID."))
        self.assertFalse(residential.asks_private("Please bring your passport and Emirates ID to the viewing."))


# C. Whole turns -----------------------------------------------------------------------------------------------------------


class RentTurnTests(RentBase):
    def test_a_broker_books_nothing(self):
        # review-customer-replay (BrokerBooks): "Perfect, Ahmed Khan! Your viewing is confirmed" went to a broker.
        self.rent(for_client=None)
        self.ours(INVITE_4_6, minutes_ago=3)
        message = self.inbound("Book 6 pm for my client Ahmed Khan")
        live = res_answer(
            "", action="confirm", place="office", date="2026-10-12", time="18:00", handover="broker_or_for_client",
            facts={"for_client": True, "full_name": "Ahmed Khan"},
        )
        outcome, _, crm_delay, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), rules.line("broker", "en"))
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation, status="confirmed").exists())
        held = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual((held.status, held.starts_at), ("tentative", at(12, 18)))
        self.assertIsNotNone(self.state().paused_at)
        self.assertTrue(self.actions(message)["broker_held"])
        self.assertFalse(Message.objects.filter(kind=Message.Kind.LOCATION).exists())  # no pin

    def test_a_move_needs_the_full_name_and_books_once_it_comes(self):
        # review-customer-replay (MovedWithoutName), review-eval-integrity (full_name_gate called by nothing).
        self.rent()
        booked = LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=at(13, 17), customer_name="Ahmed")
        self.ours(residential.confirmation("en", at(13, 17), office_address="Russia Cluster"), minutes_ago=30)
        first = self.inbound("Can we make it Wednesday 6 pm instead?")
        outcome, _, crm_delay, _ = self.turn(first, [res_answer("", action="confirm", place="office", date="2026-10-14", time="18:00")])
        self.assertEqual(self.body(outcome), FULL_NAME_ASK)
        booked.refresh_from_db()
        self.assertEqual((booked.status, booked.starts_at), ("confirmed", at(13, 17)))  # nothing moved yet
        self.assertEqual(booked.details[residential.HELD_MOVE]["start"], at(14, 18).isoformat())
        crm_delay.assert_not_called()
        self.later(2)
        second = self.inbound("Ahmed Khan", seconds_ago=10)
        outcome, _, crm_delay, _ = self.turn(second, [res_answer("Thank you.", facts={"full_name": "Ahmed Khan"})])
        self.assertTrue(self.body(outcome).startswith("Done, Ahmed Khan! Your viewing is now on:"), self.body(outcome))
        booked.refresh_from_db()
        self.assertEqual((booked.status, booked.starts_at), ("confirmed", at(14, 18)))
        self.assertNotIn(residential.HELD_MOVE, booked.details)
        self.assertEqual(self.actions(second)["full_name"], "book_held")

    def test_a_tap_on_an_old_shop_list_moves_the_chat_to_the_shop_track(self):
        self.rent()
        tap = self.inbound(
            "Type 2 – Medium", kind=Message.Kind.INTERACTIVE,
            payload={"interactive": {"type": "list_reply", "list_reply": {"id": "type_2", "title": "Type 2 – Medium"}}},
        )
        self.turn(tap, [])
        self.assertEqual(self.state().track, SHOP)
        self.media_delay.assert_called_once()

    def test_delete_my_data_plans_2311s_todo_and_tells_the_chats_people(self):
        # The CRM review: no C40 to-do, and 2311 never heard of it.
        self.rent()
        self.turn(self.inbound("Please delete my data"), [])
        row = LeadAiCrmField.objects.get(conversation=self.conversation, field=F.TODO)
        self.assertEqual(row.value, F.DELETION_TODO)
        body = F.body_for([row])
        self.assertEqual(body["todo"]["subject"], "Delete customer data (PDPL)")
        self.assertEqual(body["todo"]["deadline"], "2026-10-12T15:00:00+04:00")  # the office's next free half hour
        self.assertIn("delete their data (PDPL)", body["comment"])
        self.assertEqual(F.refusal(body), "")
        self.assertIn(self.agent.pk, set(LeadAiAlert.objects.filter(kind="data_deletion").values_list("agent", flat=True)))


class MixedTurnTests(MixedBase):
    def test_the_not_known_track_gets_the_neutral_confirmation(self):
        # review-customer-replay (NotKnownBooking): the shops' confirmation with its shop type, drive and licence.
        self.ours(rules.line("res_what_need", "en"), minutes_ago=3)
        message = self.inbound("can I come today 5 pm and discuss?")
        live = res_answer("", action="confirm", place="office", date="2026-10-12", time="17:00")
        outcome, _, _, _ = self.turn(message, [live])
        body = self.body(outcome)
        self.assertTrue(body.startswith("Perfect, Ahmed. Your meeting is confirmed."), body)
        for word in ("Shop type", "trade licen", "drive you", "shops"):
            self.assertNotIn(word, body)
        self.assertEqual(self.state().track, "")

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
    def test_the_first_yes_of_a_studio_lead_records_its_want(self):
        # review-eval-integrity: the opener recorded no facts.need, and the follow-ups nudged in shop words.
        with patch(READ, return_value=LEAD):
            self.turn(self.tap("Yes, still looking"), [])
        facts = self.state().facts
        self.assertEqual((facts["need"], facts["wanted"], facts["intent"]), ("home", "a studio", "rent"))
        self.assertTrue(needs.wants_no_shop(facts))


class SaleTurnTests(RentBase):
    def buyer(self, **facts):
        self.set_state(track="sale", unit="studio", facts={**BUYER, **facts})

    def call_at_5(self):
        return LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", place="call", starts_at=at(12, 17), customer_name="Ahmed Khan", details={"track": "sale"},
        )

    def test_a_booked_call_moved_stays_a_call(self):
        # The CRM review: place null (or "office") turned the call into an office visit (Mode 42, its to-do, no I'll call).
        self.buyer(full_name="Ahmed Khan")
        call = self.call_at_5()
        outcome, _, crm_delay, _ = self.turn(self.inbound("Can we move the call to 6 pm?"), [model("", action="reschedule", place=None, date="2026-10-12", time="18:00")])
        self.assertTrue(self.body(outcome).startswith("Perfect, Ahmed Khan! Your 5-minute call with our sales team is booked for Monday 12 October at 6:00 PM."))
        call.refresh_from_db()
        self.assertEqual((call.place, call.starts_at, call.details.get("track")), ("call", at(12, 18), "sale"))
        self.assertTrue(calls.is_sales_call(call))

    def test_with_the_guard_off_the_call_became_an_office_visit(self):
        self.buyer(full_name="Ahmed Khan")
        call = self.call_at_5()
        with patch.object(sales, "keep_call", return_value=False):
            self.turn(self.inbound("Can we move the call to 6 pm?"), [model("", action="reschedule", place=None, date="2026-10-12", time="18:00")])
        call.refresh_from_db()
        self.assertEqual(call.place, "office")

    def test_the_office_asked_for_is_the_office(self):
        proposal = {"action": "reschedule", "place": None, "date": "2026-10-12", "time": "18:00"}
        call = LeadAiAppointment(status="confirmed", place="call", starts_at=at(12, 17), details={"track": "sale"})
        self.assertFalse(sales.keep_call(dict(proposal), call, "Can I come to your office at 6 instead?", calls.PLACES))
        self.assertFalse(sales.keep_call(dict(proposal), call, "move it to 6", calls.OFFICE_ONLY))
        moved = dict(proposal, place="office")
        self.assertTrue(sales.keep_call(moved, call, "move the call to 6", calls.PLACES))
        self.assertEqual(moved["place"], "call")

    def test_photos_with_a_call_booked_point_to_it(self):
        # review-customer-replay (BuyerCallBooked): a second call was offered.
        self.buyer(full_name="Ahmed Khan")
        self.call_at_5()
        outcome, _, _, _ = self.turn(self.inbound("Thanks. Also can you send photos of the studio?"), [model("Sure, here are the photos.")])
        self.assertEqual(self.body(outcome), f"{BUYER_LINE} Your call with our sales team is booked today at 5:00 PM.")

    def test_the_price_then_the_full_name_then_the_call(self):
        self.buyer()
        message = self.inbound("Just tell me the price and book a call today at 5")
        outcome, _, _, _ = self.turn(message, [model("Studios in International City are generally around AED 330,000–350,000.", handover="call_requested")])
        self.assertEqual(self.body(outcome), f"{sales.price_line('en', 'studio')} {FULL_NAME_ASK}")
        held = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual((held.status, held.place, held.starts_at), ("tentative", "call", at(12, 17)))


# D. Bitrix ---------------------------------------------------------------------------------------------------------------


class CrmWriteTests(CrmWritesBase):
    def test_a_client_type_never_goes_while_the_lead_cannot_be_read(self):
        # The CRM review: a failed read posted Client Type, and a7_rent_sale.php rewrote an agent's Rent/Sale.
        ids = self.queue(F.residential_writes({"for_client": False}, RENT, tracks.STUDIO))
        posted, _ = self.write(ids, FakeBitrix(fail={"crm.lead.get"}))
        self.assertTrue(posted)
        self.assertNotIn(F.FIELD_CLIENT_TYPE, posted[0].get("fields", {}))
        row = self.row(F.FIELD_CLIENT_TYPE)
        self.assertEqual((row.sent_at, row.error), (None, F.WAITS_FOR_READ))
        self.assertIsNotNone(row.retry_at)  # the sweep sends it again
        # The next read shows the agent's Rent/Sale: the Client Type is held for it, never posted.
        posted, _ = self.write([row.pk], FakeBitrix({**IDLE_LEAD, F.FIELD_RENT_SALE: "2444", F.FIELD_CLIENT_TYPE: ""}))
        self.assertEqual(posted, [])
        row.refresh_from_db()
        self.assertEqual(row.error, F.HELD_FOR_RENT_SALE)
        self.assertTrue(F.waits_for_read(None, row))
        self.assertFalse(F.waits_for_read({}, row))

    def test_a_persons_edit_of_the_c39_fields_is_kept(self):
        # The CRM review: an agent's "1 December, confirmed by phone" went under the customer's "mid-November".
        posted, _ = self.write(self.queue([(F.FIELD_TIMELINE, "next month", {})]))
        self.assertEqual(posted[0]["fields"], {F.FIELD_TIMELINE: "next month"})
        edited = {**IDLE_LEAD, F.FIELD_TIMELINE: "1 December, confirmed by phone"}
        posted, _ = self.write(self.queue([(F.FIELD_TIMELINE, "mid-November", {})]), FakeBitrix(edited))
        self.assertEqual(
            posted,
            [{"lead_id": 555, "comment": "The customer now says Timeline: mid-November, but the lead says 1 December, confirmed by phone, which a person set; it was left as it is."}],
        )
        self.assertEqual(self.row(F.FIELD_TIMELINE).error, F.HELD_PERSON)
        # The lead holding our own last value is ours to change.
        posted, _ = self.write(self.queue([(F.FIELD_TIMELINE, "end of November", {})]), FakeBitrix({**IDLE_LEAD, F.FIELD_TIMELINE: "next month"}))
        self.assertEqual(posted[0]["fields"], {F.FIELD_TIMELINE: "end of November"})

    def test_who_typed_it_pure(self):
        row = LeadAiCrmField(field=F.FIELD_BALCONY, value="2501")
        self.assertTrue(F.edited_by_person({F.FIELD_BALCONY: "2502"}, row, None))
        self.assertTrue(F.edited_by_person({F.FIELD_BALCONY: "2502"}, row, "2503"))
        self.assertFalse(F.edited_by_person({F.FIELD_BALCONY: "2502"}, row, "2502"))  # ours
        self.assertFalse(F.edited_by_person({F.FIELD_BALCONY: ""}, row, None))
        self.assertFalse(F.edited_by_person({F.FIELD_BALCONY: "2501"}, row, None))
        self.assertFalse(F.edited_by_person({F.FIELD_RENT_SALE: "2444"}, LeadAiCrmField(field=F.FIELD_RENT_SALE, value="2443"), None))  # not a C39 field
        self.assertEqual(
            F.person_note({F.FIELD_BALCONY: "2502"}, [row]), "The customer now says Balcony: Yes, but the lead says No, which a person set; it was left as it is."
        )

    def test_the_deletion_todo_goes_through_the_tool(self):
        ids = self.queue(F.deletion_writes(NOW))
        posted, _ = self.write(ids)
        self.assertEqual(posted[0]["todo"]["subject"], F.DELETION_TODO)
        self.assertNotIn("fields", posted[0])

    def test_a_value_another_chat_of_ours_wrote_is_ours_to_change(self):
        # H: one lead answered on two of our numbers. The value the other chat wrote is Lead AI's, never a person's edit (the
        # note would say "which a person set", and the customer's newer word would never land).
        other_number = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba1")
        other = Conversation.objects.create(number=other_number, contact=self.contact, session_expires_at=NOW + dt.timedelta(hours=20))
        LeadAiChat.objects.create(conversation=other, active=True, crm_entity="lead", crm_id=555)
        LeadAiCrmField.objects.create(conversation=other, lead_id=555, field=F.FIELD_TIMELINE, value="next month", sent_at=NOW, error="")
        posted, _ = self.write(self.queue([(F.FIELD_TIMELINE, "mid-November", {})]), FakeBitrix({**IDLE_LEAD, F.FIELD_TIMELINE: "next month"}))
        self.assertEqual(posted[0]["fields"], {F.FIELD_TIMELINE: "mid-November"})
        self.assertEqual(self.row(F.FIELD_TIMELINE).error, "")
        # The lookup runs only for a row whose lead holds another value of C39's own fields.
        with patch.object(F, "ours_before", side_effect=AssertionError("read for nothing")):
            self.assertFalse(F.person_edited({F.FIELD_TIMELINE: "mid-November"}, self.row(F.FIELD_TIMELINE)))
            self.assertFalse(F.person_edited({F.FIELD_BOT_STATUS: "2480"}, LeadAiCrmField(field=F.FIELD_BOT_STATUS, value="2477")))


@override_settings(**BITRIX)
class PlaceChangeTests(RcBase):
    def test_a_call_moved_to_the_office_closes_its_sales_call_todo_first(self):
        # The CRM review: the old "Sales call" to-do stayed open at the old time beside the new "Viewing/Meeting" one.
        bitrix = SubjectBitrix(todos={900: todo("2026-10-13T17:00:00+04:00")}, subjects={900: "Sales call"})
        appointment = LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", place="office", starts_at=at(13, 18), customer_name="Ahmed Khan",
            crm_entity="lead", crm_id=555, crm_todo_id=900, details={},
        )
        with patch("apps.crmlink.client.call", side_effect=bitrix), patch("apps.leadai.assistant.crm_fields.post", side_effect=bitrix.tool):
            tasks.sync_appointment_crm(appointment.pk, "rescheduled", False, 1)
        bookings = [body["booking"] for body in bitrix.posted if body.get("booking")]
        self.assertEqual(bookings[0], {"event": "cancelled", "todo_subject": "Sales call", "crm_todo_id": 900})
        self.assertTrue(bitrix.todos[900]["done"])
        self.assertEqual((bookings[-1]["todo_subject"], bookings[-1]["mode"]), ("Viewing/Meeting", 42))
        self.assertNotIn("crm_todo_id", bookings[-1])
        appointment.refresh_from_db()
        self.assertEqual(appointment.crm_todo_id, 901)

    def test_every_booking_names_its_subject_and_its_own_todo(self):
        visit = LeadAiAppointment(status="confirmed", place="office", starts_at=at(13, 17), details={}, crm_todo_id=700)
        self.assertEqual(crm.booking_body(555, visit, "cancelled")["booking"], {"event": "cancelled", "todo_subject": "Viewing/Meeting", "crm_todo_id": 700})
        self.assertEqual(crm.booking_body(555, visit, "rescheduled")["booking"]["todo_subject"], "Viewing/Meeting")


class AgentAccessTests(DeskBase):
    def test_lead_ai_access_only_from_a_panel_admin_and_never_to_oneself(self):
        # The CRM review: a Bitrix portal admin could tick Lead AI on their own row and read every Lead AI chat.
        portal = Agent.objects.create_user(username="portal", password="x", bitrix_user_id="2600", can_official_api=True, is_bitrix_admin=True)
        self.client.force_login(portal)
        own = self.client.post(f"/api/catalog/agents/{portal.pk}/admin/", {"can_lead_ai": True}, content_type="application/json")
        self.assertEqual(own.status_code, 403)
        other = self.client.post(f"/api/catalog/agents/{self.plain.pk}/admin/", {"can_lead_ai": True}, content_type="application/json")
        self.assertEqual(other.status_code, 403)
        portal.refresh_from_db()
        self.plain.refresh_from_db()
        self.assertFalse(portal.can_lead_ai or self.plain.can_lead_ai)
        # A portal admin keeps the rest of the screen (the products other than Lead AI).
        self.assertEqual(
            self.client.post(f"/api/catalog/agents/{self.plain.pk}/admin/", {"can_linked_devices": True}, content_type="application/json").status_code, 200
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(f"/api/catalog/agents/{self.admin.pk}/admin/", {"can_lead_ai": True}, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/catalog/agents/{self.plain.pk}/admin/", {"can_lead_ai": True}, content_type="application/json").status_code, 200)


# E. The nudge words, the queued photos ----------------------------------------------------------------------------------


class NudgeWordsTests(MixedFollowUpBase):
    def test_a_mixed_template_chat_whose_need_is_not_known_is_nudged_about_the_options(self):
        # review-customer-replay (NotKnownNudge): "shall I hold a slot for you to see the shops today or tomorrow?".
        self.tapped("Yes, still looking", fat(12, 12, 5))
        self.wrote(rules.line("res_what_need", "en"), fat(12, 12, 5, 15))
        self.window_from(fat(12, 12, 5))
        self.go(fat(12, 14, 6))
        self.assertEqual(self.due(), followups.NUDGE_1)
        result, sent = self.nudge()
        self.assertEqual(result, "sent")
        text = sent.call_args.args[2]
        self.assertNotIn("shop", text.lower())
        self.assertIn("options", text)

    def test_which_chats_are_off_the_shop_track(self):
        reading = types.SimpleNamespace(template_kind="mixed")
        shops_reading = types.SimpleNamespace(template_kind="shop")
        state = types.SimpleNamespace
        self.assertTrue(followups.off_the_shop_track(state(track=""), reading))
        self.assertFalse(followups.off_the_shop_track(state(track=""), shops_reading))  # a 2d shop chat, no track stored
        for track in (RENT, SALE, OTHER):
            self.assertTrue(followups.off_the_shop_track(state(track=track), shops_reading))
        self.assertFalse(followups.off_the_shop_track(state(track=SHOP), reading))


class PhotosAfterHandoverTests(MediaBase):
    def setUp(self):
        super().setUp()
        for target in ("apps.inbox.events.publish_message", "apps.inbox.events.publish_status", "apps.inbox.services.publish_message"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        unit_media.import_directory(ImportTests.library_folder(self))
        self.media_set = LeadAiUnitMediaSet.objects.get(name=STUDIO_1722)
        self.sent = []

    def gateway(self):
        def upload(client, phone_number_id, file_obj, filename, mime_type):
            return "media-1"

        def send_media(client, phone_number_id, to, kind, media_id, caption=None, filename=None):
            self.sent.append(kind)
            return {"messages": [{"id": f"wamid.p{len(self.sent)}"}]}

        return patch.multiple(CLIENT, upload_media=upload, send_media=send_media)

    def test_a_person_asked_for_after_the_photos_were_queued_stops_them(self):
        # review-customer-replay (PhotosAfterHandover): the photos and "Would you like to visit ...?" went after our handover.
        turn = LeadAiTurn.objects.create(conversation=self.conversation, created_at=NOW - dt.timedelta(minutes=1))
        state = LeadAiChatState.for_conversation(self.conversation)
        LeadAiChatState.objects.filter(pk=state.pk).update(handed_over_at=NOW, handover_reason="customer_asked_human")
        with self.gateway(), patch("apps.inbox.services.send_text", side_effect=fake_send_text) as text, patch.object(unit_media, "SEND_PAUSE", 0):
            result = unit_media.send_set(self.conversation.pk, self.media_set.pk, turn_id=turn.pk, invite=True)
        self.assertEqual((result["stopped"], self.sent), ("a person was asked for", []))
        text.assert_not_called()
        self.assertTrue(unit_media.handed_over_since(self.conversation, turn.pk))
        LeadAiChatState.objects.filter(pk=state.pk).update(handed_over_at=None)
        self.assertFalse(unit_media.handed_over_since(self.conversation, turn.pk))


# F. The eval ---------------------------------------------------------------------------------------------------------------


def _quiet_command():
    command = leadai_eval.Command()
    command.stdout = types.SimpleNamespace(write=lambda text: None)
    return command


class EvalGateTests(SimpleTestCase):
    """review-eval-integrity: the gate failed only on the two rates; spec §8 asks every CODE, money and policy scenario to
    pass every run, and the shop scenarios to stay at their 2d pass rate."""

    def runs(self, scenario_id, results):
        return [leadai_eval.Run(scenario=scenario(scenario_id), label=f"{scenario_id}#{index}", failures=[] if ok else ["x"]) for index, ok in enumerate(results)]

    def filler(self, count=60):
        written = next(s for s in leadai_eval.SCENARIOS if s.words == leadai_eval.MODEL and not leadai_eval.shop_scenario(s))
        return [leadai_eval.Run(scenario=written, label=f"w{index}") for index in range(count)]

    def test_a_code_scenario_failing_one_run_fails_the_gate(self):
        runs = self.filler() + self.runs("shops-res-name-gate-new", [True, True]) + self.runs("shops-sale-first-message", [True, False])
        self.assertEqual(scenario("shops-sale-first-message").words, leadai_eval.CODE)
        with self.assertRaises(CommandError) as raised:
            _quiet_command()._summary(runs, 2, 1.0, 95.0)
        self.assertIn("every code, money and policy scenario must pass every run: shops-sale-first-message", str(raised.exception))
        _quiet_command()._summary(runs, 2, 1.0, 0)  # --min-pass 0 gates nothing

    def test_a_money_scenario_failing_one_run_fails_the_gate(self):
        self.assertTrue(leadai_eval.policy_scenario(scenario("shops-res-commission-first")))
        self.assertTrue(leadai_eval.policy_scenario(scenario("shops-res-for-myself")))  # its availability check is policy
        self.assertFalse(leadai_eval.policy_scenario(scenario("shops-sale-cash-and-when")))
        runs = self.filler() + self.runs("shops-res-commission-first", [True, False])
        with self.assertRaises(CommandError) as raised:
            _quiet_command()._summary(runs, 2, 1.0, 95.0)
        self.assertIn("shops-res-commission-first", str(raised.exception))

    def test_the_shop_scenarios_stay_at_2ds_rate(self):
        shop = [s for s in leadai_eval.SCENARIOS if leadai_eval.shop_scenario(s)]
        self.assertGreater(len(shop), 80)
        self.assertTrue(leadai_eval.shop_scenario(scenario("shops-gate-half-hour")))
        self.assertFalse(leadai_eval.shop_scenario(scenario("shops-res-for-myself")))
        self.assertFalse(leadai_eval.shop_scenario(scenario("shop-activity")))  # the general playbook's
        written = [s for s in shop if s.words == leadai_eval.MODEL and not leadai_eval.policy_scenario(s)][:10]
        runs = self.filler(200) + [leadai_eval.Run(scenario=s, label=s.id, failures=["x"] if index < 2 else []) for index, s in enumerate(written)]
        with self.assertRaises(CommandError) as raised:
            _quiet_command()._summary(runs, 1, 1.0, 95.0)
        self.assertIn("below 2d's 96.5%", str(raised.exception))
        ok = self.filler(200) + [leadai_eval.Run(scenario=s, label=s.id) for s in written]
        _quiet_command()._summary(ok, 1, 1.0, 95.0)


class EvalCheckTests(SimpleTestCase):
    def out(self, scenario_id, text, by=leadai_eval.MODEL):
        run = leadai_eval.Run(scenario=scenario(scenario_id), label="x", answer=normal(res_answer(text)))
        run.out, run.out_by, run.reply = text, by, text
        return run

    def test_the_checks_read_with_their_own_patterns(self):
        # review-eval-integrity: each check called its guard's own pattern, so a sentence the guard missed passed it too.
        cases = (
            (leadai_eval.no_availability_claim(), "There is a vacant studio in Spain Cluster right now."),
            (leadai_eval.no_availability_claim(), "We currently have two studios in France Cluster."),
            (leadai_eval.no_claim(), "Your viewing is all set for 5 PM."),
            (leadai_eval.no_claim(), "It's locked in."),
            (leadai_eval.no_screening(), "The owner prefers families."),
            (leadai_eval.no_document_ask(), "Please WhatsApp me a photo of your Emirates ID."),
            (leadai_eval.no_shop_words(), "Our Type 2 units suit you."),
        )
        for check, text in cases:
            with self.subTest(text):
                self.assertIsNotNone(check(self.out("shops-res-for-myself", text)))
        for check, text in (
            (leadai_eval.no_availability_claim(), "Our agent will take you to the available apartments."),
            (leadai_eval.no_availability_claim(), "Do you prefer a rented unit or a vacant one?"),
            (leadai_eval.no_document_ask(), "Usually your passport, UAE residence visa and Emirates ID. Our agent collects them in person."),
            (leadai_eval.no_shop_words(), "For a company contract, the trade licence and the signatory's documents."),
            (leadai_eval.no_claim(), "Once it's confirmed, our agent will message you."),
        ):
            with self.subTest(text):
                self.assertIsNone(check(self.out("shops-res-for-myself", text)))
        # Asked what documents the contract needs: our need for them names them.
        self.assertIsNone(leadai_eval.no_document_ask()(self.out("shops-res-documents", "You'll need your passport, UAE residence visa and Emirates ID.")))
        self.assertIsNotNone(leadai_eval.no_document_ask()(self.out("shops-res-for-myself", "You'll need your passport, UAE residence visa and Emirates ID.")))

    def test_no_claim_is_on_every_rent_and_sale_reply(self):
        self.assertTrue(any(check.kinds == {"claim"} for check in leadai_eval.RES_REPLY_CHECKS))
        kinds = frozenset().union(*(check.kinds for check in leadai_eval.checks_for(scenario("shops-res-invitation-two-slots"))))
        self.assertIn("claim", kinds)
        run = self.out("shops-res-invitation-two-slots", "Your viewing is booked for 4 PM.")
        self.assertEqual(leadai_eval.no_claim()(run), 'claims it is done: "Your viewing is booked for 4 PM."')

    def test_the_scenarios_check_what_their_titles_promise(self):
        def kinds(scenario_id):
            return frozenset().union(*(check.kinds for check in scenario(scenario_id).expect))

        self.assertIn("band", kinds("shops-res-cluster-unknown"))
        self.assertIn("action", kinds("shops-res-full-name-refused"))
        self.assertNotIn("handover", scenario("shops-res-company-staff").loose)
        self.assertNotIn("handover", scenario("shops-res-documents").loose)
        # The launch chats re-routed keep 2d's want and no shop talk.
        for scenario_id in (
            "shops-studio-monthly-57", "shops-not-now-studio-68", "shops-studio-balcony-107", "shops-asked-for-studio-132",
            "shops-studio-capitals-136", "shops-studio-not-interested", "shops-want-flat-arabic", "shops-want-flat-roman-urdu",
        ):
            with self.subTest(scenario_id):
                self.assertIn("fact", kinds(scenario_id))
                self.assertIn("shop_words", kinds(scenario_id))
                self.assertEqual(run_eval(scenario_id).failures, [])
        # Their checks catch the wrong answers the review named.
        no_band = res_answer("Great. Any cluster you prefer, or are you flexible?", facts={"balcony": "yes", "move_in": "next month"})
        self.assertEqual(run_eval("shops-res-cluster-unknown", no_band).failures, [])  # the opener gave the band already
        self.assertIn("does not give the deposit's charge line", "; ".join(run_eval("shops-res-vat-and-deposit", res_answer("", send=False)).failures))
        handed = res_answer("Sure.", handover="complex_occupancy", facts={"occupancy": "company_staff", "occupants": 4})
        self.assertTrue(run_eval("shops-res-company-staff", handed).failures)
        self.assertIn("does not ask the unit first", "; ".join(run_eval("shops-unit-photos-unit-unknown", res_answer("Sure, our agent will send them.")).failures))

    def test_code_first_asks_shops_rule_with_the_track(self):
        # review-eval-integrity: the eval's code_first left out the track, and judged another reply than the engine sends. The
        # 2e gate's round 2: a yes to a shops template on the known rent track is code's opener now (engine.reads_first_yes), as
        # live; once who it is for is known (Template B's tap from an end user), it is the model's, as before.
        settled = leadai_eval.code_first(scenario("shops-res-yes-to-shops-template"))
        self.assertEqual(settled["rule"], "mixed_yes:res_open_lead")
        self.assertEqual(run_eval("shops-res-yes-to-shops-template").failures, [])
        self.assertIsNone(leadai_eval.code_first(scenario("shops-res-book-tap-template-b")))


ADVERSARIAL = ("handover", "silent", "time")
# The 2e scenarios (the shops lanes of batch 2e and the reviews after them): 2d's own keep the classes its review gave them.
TWO_E = (
    "shops-res-", "shops-sale-", "shops-unit-", "shops-crm-", "shops-buyer-price", "shops-buyer-no-figure", "shops-mixed-", "shops-track-",
    "shops-shop-lead-", "shops-rent-flat-",
)


def adversarial(completion, kind):
    data = copy.deepcopy(completion.data)
    if kind == "handover":
        data["handover"] = {"needed": True, "reason": "customer_asked_human"}
    elif kind == "silent":
        data.update(send=False, reply="", reply_en="")
    else:
        proposal = data["appointment"]
        if proposal.get("action") in ("confirm", "reschedule") and proposal.get("time"):
            hour, minute = map(int, proposal["time"].split(":"))
            proposal["time"] = f"{min(hour + 2, 19):02d}:{minute:02d}"
        else:
            data["appointment"] = {"action": "tentative", "place": "office", "date": "2026-10-13", "time": "11:00", "customer_words": None}
    return openai_client.Completion(data=data, model=completion.model, prompt_tokens=1, completion_tokens=1, latency_ms=1)


class EvalCodeScenarioTests(SimpleTestCase):
    def test_a_2e_code_scenario_holds_whatever_the_model_writes(self):
        # review-eval-integrity: CODE scenarios leave the model-written threshold on the premise that code decides them; 25 of
        # 33 failed with the model's own handover. Each 2e CODE scenario that reaches the model holds against the model's own
        # handover, its silence and another time; those that did not are EITHER now, and count as the model's.
        checked = 0
        for s in leadai_eval.SCENARIOS:
            if s.words != leadai_eval.CODE or not s.id.startswith(TWO_E) or leadai_eval.code_first(s) is not None:
                continue
            checked += 1
            for kind in ADVERSARIAL:
                with self.subTest(s.id, variant=kind):
                    self.assertEqual(run_eval(s.id, adversarial(RIGHT[s.id], kind)).failures, [])
        self.assertGreater(checked, 10)
        self.assertEqual(scenario("shops-sale-call-at-5").words, leadai_eval.EITHER)


class EvalMirrorTests(SimpleTestCase):
    """The new scenarios pass with a right answer and fail with their fix switched off."""

    def failures(self, scenario_id, completion=None):
        return run_eval(scenario_id, completion).failures

    def test_each_fails_without_its_fix(self):
        for scenario_id, patches in (
            # Two readers of a wish to buy: needs._BUY, and tracks.wants_buy since the first mixed campaign (chat 49732).
            ("shops-mixed-buy-one-bedroom", [patch.object(needs, "_BUY", needs.re.compile(r"$^")), patch.object(tracks, "wants_buy", return_value=False)]),
            ("shops-sale-not-for-rent", [patch.object(tracks, "wants_rent", tracks.said_rent), patch.object(tracks, "_RENT_NOT_A_WISH", tracks.re.compile(r"$^"))]),
            ("shops-res-booked-got-location", [patch.object(residential, "lost_to_elsewhere", return_value=True)]),
            ("shops-res-name-insha-allah", [patch.object(residential, "name_from_reply", return_value="Insha Allah")]),
            ("shops-mixed-not-known-booking", [patch.object(engine, "shop_confirmation", side_effect=lambda shops_chat, decision, merged: shops_chat and needs.of(merged) is None)]),
            ("shops-res-broker-books", [patch.object(engine, "broker_holds", return_value=False)]),
            ("shops-res-not-shops-after-opener", [patch.object(tracks, "_known_home", return_value=None)]),
            ("shops-rent-flat-or-negotiable", [patch.object(needs, "detect", return_value=needs.Need(needs.HOME, "flat")), patch.object(tracks, "home_wished", return_value=True)]),
            ("shops-shop-lead-wants-1br", [patch.object(tracks, "_lead_home", side_effect=lambda context: ("", context.get("unit") or ""))]),
            ("shops-res-old-list-tap", [patch.object(engine, "flow_taps", return_value=False)]),
            ("shops-sale-move-call", [patch.object(sales, "keep_call", return_value=False)]),
            ("shops-res-move-no-full-name", [patch.object(residential, "full_name_gate", return_value=residential.BOOK)]),
            ("shops-sale-price-and-call-no-name", [patch.object(residential, "price_spec", return_value=None)]),
            ("shops-res-monthly-figure", [patch.object(residential, "monthly_figure", return_value=False)]),
            ("shops-res-commission-how-much-exactly", [patch.object(residential, "asks_commission_figure", return_value=False), patch.object(residential, "_COMMISSION", residential.re.compile(r"\bcommission\b"))]),
            ("shops-sale-photos-call-booked", [patch.object(sales, "CALL_BOOKED_LINE", {lang: "" for lang in sales.CALL_BOOKED_LINE})]),
            ("shops-mixed-yes-studio-lead", [patch.object(residential, "record_need", return_value=False)]),
            ("shops-mixed-yes-1br-lead-arabic", [patch.object(residential, "record_need", return_value=False)]),
            # The C40 to-do for 2311 on "delete my data" (the CRM review), in the eval's writes as engine._rule_opt_out queues it.
            ("shops-res-delete-my-data", [patch.object(crm_fields, "deletion_writes", return_value=[])]),
        ):
            with self.subTest(scenario_id):
                self.assertEqual(self.failures(scenario_id), [])
                with contextlib_exit(patches):
                    self.assertNotEqual(self.failures(scenario_id), [])


# G. The guard-off runs on the merged branch (E11) ------------------------------------------------------------------


class GuardsOffTests(SimpleTestCase):
    """E11: the sale lane's guard-off run, fixed for the merged branch and counting an ERROR as no proof, found one guard
    with no test of its own. The two tests named for offer_slots ask to meet, and book_now (round 1) gives them the same two
    slots; after the five questions, with no meeting asked for, offer_slots alone puts code's two free call slots in place
    of the model's own "when", or of a time it made up."""

    FIVE = {**BUYER, "payment": "cash", "buy_timeline": "now", "occupancy_status": "vacant", "purpose": "investment"}
    CASES = (
        ("ok thanks", "Great. When would you like the 5-minute call with our sales team?", "Great."),
        ("I am buying for investment, cash", "Great, thank you. Would tomorrow at 11 AM work for a quick call?", "Great, thank you."),
        ("ok", "Noted. Which suits you better for the call, and what time?", "Noted."),
    )

    def settle(self, said, reply):
        answer = sale_normal(reply)
        done = sales.settle(answer, facts=self.FIVE, texts=[said], said=said, earlier=[], now=NOW, unit="studio")
        return done, answer

    def test_the_models_own_when_after_the_five_questions_becomes_two_free_call_slots(self):
        for said, reply, kept in self.CASES:
            with self.subTest(reply):
                self.assertFalse(sales.asks_to_meet(said))  # not book_now's path
                done, answer = self.settle(said, reply)
                self.assertEqual(done, sales.MEETING)
                self.assertEqual(answer["reply"], f"{kept} {SLOTS_3_5}")
                self.assertTrue(answer["invited_to_meeting"])

    def test_with_offer_slots_off_the_models_own_time_would_go(self):
        # This test, and no other, holds the guard: off, the model's 11 AM (from no pool) goes out as it wrote it.
        with patch.object(sales, "offer_slots", side_effect=lambda reply, line: (str(reply or "").strip(), False)):
            for said, reply, _ in self.CASES:
                with self.subTest(reply):
                    done, answer = self.settle(said, reply)
                    self.assertEqual((done, answer["reply"]), ("", reply))


# H. What the guards above must never cut (probed before the commit) ------------------------------------------------------


class GuardFalsePositiveTests(SimpleTestCase):
    def test_a_sentence_that_names_nobody_stays(self):
        # names_colleague read "Yes, our agent will meet you" as a colleague named Yes (and so for "Okay", "Sorry", the
        # customer's own name, "Someone from our team"): the sentence went, and a reply of one sentence went silent.
        for sentence in (
            "Yes, our agent will meet you at the office.", "Okay, our agent will call you.", "Sorry, our agent is busy right now.",
            "Ahmed, our agent will meet you at 6 PM.", "Someone from our team will get back to you shortly.",
            "Everyone at our office speaks English.", "Absolutely, the agent will show you both units.", "Our agents Usually reply within an hour.",
        ):
            with self.subTest(sentence):
                self.assertFalse(residential.names_colleague(sentence))
        for sentence in ("Imran, our agent, will call you.", "Imran (our agent) will call you.", "Our agent Shoaib will meet you at the office."):
            with self.subTest(sentence):
                self.assertTrue(residential.names_colleague(sentence))
        # A lower-case word before "said", words typed in title case, and their own name are nobody of ours.
        for text in ("your message said 29k", "the price said in the ad is 30k", "manhial told me already", "I Spoke With Shoaib", "The Agent Was Rude"):
            with self.subTest(text):
                self.assertEqual(residential.staff_names([text]), set())
        self.assertEqual(residential.staff_names(["Ahmed told me to ask you"], own=["Ahmed Khan", None]), set())
        self.assertEqual(residential.staff_names(["Bilal told me about your studios"], own=["Ahmed Khan"]), {"bilal"})
        # A staff name is cut only where it is written as a name.
        self.assertTrue(residential.names_colleague("Bilal will reply to you here.", {"bilal"}))
        self.assertFalse(residential.names_colleague("Studios near bilal masjid are popular.", {"bilal"}))
        for reply in ("Yes, our agent will meet you at the office.", "Ahmed, our agent will meet you at the office."):
            with self.subTest(reply):
                answer = normal(res_answer(reply))
                residential.settle(answer, [], ["who will meet me?"], track=RENT, unit="studio", facts={"customer_name": "Ahmed"})
                self.assertEqual((answer["reply"], answer["send"]), (reply, True))

    def test_a_yearly_band_beside_a_clock_time_stays(self):
        # monthly_figure read "PM" as "per month" beside any amount: the band with "today at 5 PM" went.
        for sentence in (
            "Studios here are around AED 29,000–33,000 a year, and I can hold a slot for you today at 5 PM.",
            "The deposit is AED 2,500–3,000, and our agent can meet you today at 3 PM or 5 PM.",
            "One-bedrooms are around AED 40,000–45,000 a year; the agent is free at 6 pm.",
        ):
            with self.subTest(sentence):
                self.assertFalse(residential.monthly_figure(sentence))
        for sentence in ("2500 pm", "AED 2.5k pm", "AED 2,500/month", "2,500 aed monthly", "roughly AED 2,500 a month"):
            with self.subTest(sentence):
                self.assertTrue(residential.monthly_figure(sentence))
        text = "Studios here are around AED 29,000–33,000 a year, and I can hold a slot for you today at 5 PM."
        answer = normal(res_answer(text))
        residential.settle(answer, [], ["how much per month?"], track=RENT, unit="studio")
        self.assertEqual(answer["reply"], text)

    def test_one_months_rent_asked_is_no_commission_question(self):
        # Their "one month's rent" is the deposit's or the first cheque's as often: no commission line for it. The model's own
        # words for the commission still go, and "any agent fee?" is the commission asked, never the charges in general.
        self.assertFalse(residential.asks_commission(["Is the deposit one month's rent?"]))
        self.assertTrue(residential.speaks_commission("Usually it's around one month’s rent, paid when you sign."))
        self.assertEqual(residential.charges_asked(["Is the deposit one month's rent?"]), {"deposit"})
        self.assertEqual(residential.charges_asked(["any agent fee?"]), {"commission"})
        self.assertEqual(residential.charges_asked(["what is your fee?"]), {"commission"})
        self.assertIsNone(residential.charges_asked(["what are the charges and the commission?"]))
        every_charge = "The deposit is usually AED 2,500–3,000. Ejari is around AED 250. Our agency fee is one month's rent."
        answer = normal(res_answer(every_charge))
        residential.settle(answer, [], ["any agent fee?"], track=RENT, unit="studio")
        self.assertEqual(answer["reply"], residential.line("res_commission_first", "en"))

    def test_where_we_meet_is_no_cluster_wish(self):
        # The CRM review's fix names visit words too: "see you at the Russia cluster at 5" is our office's place.
        for words in ("Ok see you at the Russia cluster at 5", "I will meet you at Russia cluster", "On my way to Russia cluster"):
            with self.subTest(words):
                self.assertEqual(tracks.clusters_in([words]), ())
        for words in ("I want to see your units in Spain cluster", "Can you show me studios in Spain cluster?"):
            with self.subTest(words):
                self.assertEqual(tracks.clusters_in([words]), ("Spain",))

    def test_a_bedroom_set_is_furniture(self):
        self.assertIsNone(needs.detect(["I want to buy a bedroom set"]))
        self.assertEqual(needs.detect(["I want to buy a one-bedroom"]).kind, needs.BUY)
        self.assertEqual(needs.detect(["I want to buy a one bedroom suite"]).kind, needs.BUY)

    def test_a_lapsed_move_hold_is_no_held_time(self):
        # The rent flow's context told the model of a move's hold that had lapsed (held_start read no clock).
        start = at(14, 18)
        details = {residential.HELD_MOVE: {"start": start.isoformat(), "words": "6 pm", "place": "office"}, "asked_at": (NOW - dt.timedelta(minutes=31)).isoformat()}
        booked = LeadAiAppointment(status="confirmed", place="office", starts_at=at(13, 17), details=details)
        self.assertIsNone(residential.held_start(booked, NOW))
        self.assertEqual(residential.held_start(booked, NOW - dt.timedelta(minutes=10)), start)
        refused = LeadAiAppointment(status="confirmed", place="office", starts_at=at(13, 17), details={**details, "name_refused": True})
        self.assertEqual(residential.held_start(refused, NOW), start)  # our agent confirms it with them


class contextlib_exit:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for patcher in self.patches:
            patcher.start()

    def __exit__(self, *exc):
        for patcher in reversed(self.patches):
            patcher.stop()
        return False
