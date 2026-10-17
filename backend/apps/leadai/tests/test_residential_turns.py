"""Batch 2e slice B, the rent flow end to end in engine._run_claimed (spec §1.4, §2, §6.3; board T92):

- A. the opener of a track entered, code's with no model (the launch's studio seekers re-routed), and what goes to the model;
- B. the residential path to the model: its prompt, schema, cache key and context; two questions; amounts from 100; code's
  commission and VAT lines; charge questions answered, never handed over; the segment forced; the guards live; the model's
  tag moving the chat; the not-known track's neutral invitation;
- C. the full-name gate: the time held and the name asked; the name booking the held time; a refusal; the CRM's full name;
  a held slot taken meanwhile; a hold that lapses;
- D. handovers and special cases: our team's line, a call, a broker, an Emirates ID, "delete my data", rented elsewhere, the
  owner's number, paying now;
- E. the settings API's residential facts;
- F. the eval: the re-routed launch chats are code's, and fail without the opener.

Each test fails without the rule it proves (the scratchpad's rent_guards_off.py). The shops chat is test_shops_playbook's
(lead 555, Monday 12 October 2026, 14:00 Dubai); the fakes are test_assistant's.
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import optout, tasks
from apps.leadai.assistant import crm_fields, engine, openai_client, people, prompt, residential, rules, schema
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiCrmField, LeadAiSettings
from apps.leadai.tests.test_assistant import NOW, answer
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_first_chat_fixes import FirstChatBase
from apps.leadai.tests.test_lead_context import LEAD, READ
from apps.leadai.tests.test_tracks_turns import MixedBase
from apps.leadai.tests.test_who_the_customer_is import MAPS, NotAShopBase

STUDIO = {"need": "home", "wanted": "a studio", "property_type": "studio", "intent": "rent"}
KNOWN = {**STUDIO, "for_client": False, "balcony": "yes", "move_in": "next month"}
OPENER_44 = "Sure! Studios in International City are generally around AED 29,000–33,000 a year. Are you looking for yourself or for a client?"
INVITE_4_6 = (
    "Perfect. Our agent will meet you at our office in Russia Cluster and take you to the available apartments. I can hold a slot "
    "for you today at 4:00 PM or 6:00 PM — which is better?"
)
SIX_PM = dt.datetime(2026, 10, 12, 18, 0, tzinfo=NOW.tzinfo)


def res_answer(reply, **extra):
    """A model answer in the residential schema (RES_SCHEMA's facts)."""
    facts = extra.pop("facts", {})
    extra.setdefault("segment", "residential_tenant")
    tag = extra.pop("need_tag", None)
    completion = answer(reply, **extra)
    completion.data["facts"] = {**{key: None for key in schema.RES_FACT_KEYS}, "notes": [], "clusters": [], **facts}
    if tag:
        completion.data["need_tag"] = tag
    return completion


class RentBase(NotAShopBase):
    """A shops chat whose customer is on the rent track (a studio), as earlier turns left it."""

    def rent(self, **facts):
        self.set_state(track="rent", unit="studio", facts={**KNOWN, **facts})

    def outbound(self):
        return list(Message.objects.filter(conversation=self.conversation, direction=Message.Direction.OUTBOUND).order_by("pk"))


# A. The opener -------------------------------------------------------------------------------------------------------


class OpenerTurnTests(RentBase):
    def test_chat_44_gets_the_rent_opener_with_no_model(self):
        message = self.inbound("I need an apartment studio")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), OPENER_44)
        state = self.state()
        self.assertEqual((state.track, state.unit, state.facts["need"], state.facts["wanted"]), ("rent", "studio", "home", "a studio"))
        self.assertEqual(self.actions(message)["rule"], "res_rule:open")
        self.assertIn("wants a studio", self.wanted_alerts().first().title)  # the team hears of the studio seeker, as in 2d
        self.assertNotEqual(self.outbound()[-1].kind, Message.Kind.LOCATION)  # an opener carries no pin

    def test_a_one_bedroom_in_england_cluster_gets_the_european_band(self):
        outcome, _, _, _ = self.turn(self.inbound("I need room\n1bhk Englund x cluster"), [])
        self.assertEqual(
            self.body(outcome),
            "Sure! One-bedrooms in England Cluster are generally around AED 42,000–43,000 a year. Are you looking for yourself or for a client?",
        )

    def test_an_apology_when_we_talked_shops_to_them(self):
        self.ours(rules.line("for_whom", "en"), minutes_ago=30)
        outcome, calls, _, _ = self.turn(self.inbound("Actually I need a studio"), [])
        self.assertEqual((calls, self.body(outcome)), ([], f"Sorry for the confusion! {OPENER_44}"))

    def test_a_question_goes_to_the_model_with_the_rent_prompt(self):
        message = self.inbound("I need a studio, how much is it?")
        reply = "Studios in International City are generally around AED 29,000–33,000 a year. Are you looking for yourself or for a client?"
        outcome, calls, _, _ = self.turn(message, [res_answer(reply)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0]["content"], prompt.RES_SYSTEM)
        self.assertEqual(self.body(outcome), reply)

    def test_a_request_for_a_person_goes_to_the_model_and_is_handed_over(self):
        message = self.inbound("I need a studio, I want to talk to a person")
        outcome, calls, _, _ = self.turn(message, [res_answer("Sure.", handover="customer_asked_human")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), residential.handover_line("en"))
        self.assertEqual(self.state().handover_reason, "customer_asked_human")

    def test_the_kill_switch_sends_them_back_to_2d(self):
        with patch.object(residential, "RENT_LIVE", False):
            outcome, calls, _, _ = self.turn(self.inbound("I need an apartment studio"), [res_answer("Great! What business will the shop be for?")])
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.body(outcome).startswith("Thank you for letting us know. We have many options for a studio apartment"))


# B. The residential path to the model ---------------------------------------------------------------------------------


class ModelPathTests(RentBase):
    def test_its_prompt_schema_cache_key_and_context(self):
        self.rent(for_client=None)
        self.turn(self.inbound("For myself"), [res_answer("Perfect. Do you prefer a balcony, and when are you planning to move?")])
        messages, schema_, kwargs = self.requests[0]
        self.assertEqual(messages[0]["content"], prompt.RES_SYSTEM)
        self.assertIs(schema_, schema.RES_SCHEMA)
        self.assertEqual(kwargs["cache_key"], openai_client.RES_CACHE_KEY)
        context = messages[1]["content"]
        for line in (
            "BRAND: AR Properties", "TRACK: rent (unit: studio; clusters: not known yet)",
            "RES FACTS (quote only these; rents are per year, in AED):\n- Studios to rent: AED 29,000–33,000 a year",
            "CHARGE LINES (say them in the customer's language; the system writes the commission and VAT lines):",
            "FULL NAME KNOWN: no", "FREE SLOTS (", "TAKEN SLOTS (",
        ):
            self.assertIn(line, context)
        self.assertNotIn("SHOP FACTS", context)
        self.assertNotIn("One-bedrooms to rent", context)

    def test_two_questions_go_out_on_the_rent_track(self):
        self.rent(for_client=None)
        reply = "Perfect. Do you prefer a balcony? And when are you planning to move?"
        outcome, _, _, _ = self.turn(self.inbound("For myself"), [res_answer(reply)])
        self.assertEqual(self.body(outcome), reply)

    def test_an_invented_small_amount_is_cut(self):
        self.rent()
        reply = "Ejari is AED 250, and we handle it. Shall I hold a slot for you?"
        outcome, _, _, _ = self.turn(self.inbound("What about Ejari?"), [res_answer(reply)])
        self.assertEqual(self.body(outcome), "Shall I hold a slot for you?")

    def test_the_commission_line_is_codes(self):
        self.rent()
        outcome, _, _, _ = self.turn(self.inbound("Is there any commission?"), [res_answer("No commission at all! Shall I hold a slot for you?")])
        self.assertEqual(
            self.body(outcome),
            "Our normal agency commission applies once you choose an apartment you like. The exact amount depends on the unit. Shall I "
            "hold a slot for you?",
        )

    def test_charge_questions_are_answered_never_handed_over(self):
        # Launch chats 59 and 78 asked these about a shop; 2d hands a shop's must-answer questions to a person. Here the rent
        # flow answers them (people.settle with a need set, spec §1.4.7).
        self.rent()
        reply = "Normally the security deposit in International City is around AED 2,500–3,000, depending on the owner and the unit."
        outcome, _, _, _ = self.turn(self.inbound("is there VAT and deposit?"), [res_answer(reply)])
        self.assertEqual(self.body(outcome), f"{reply} {residential.vat_line('en')}")
        state = self.state()
        self.assertIsNone(state.handed_over_at)
        self.assertFalse(LeadAiAlert.objects.filter(kind=people.QUESTIONS).exists())

    def test_the_segment_is_forced_so_a_booking_is_no_holding_handover(self):
        self.rent(full_name="Ahmed Khan")
        self.ours(INVITE_4_6)
        message = self.inbound("6 PM")
        outcome, _, _, _ = self.turn(message, [res_answer("", action="confirm", place="office", date="2026-10-12", time="18:00", segment="other")])
        self.assertTrue(self.body(outcome).startswith("Perfect, Ahmed Khan! Your viewing is confirmed ✅"))
        self.assertIsNone(self.state().handed_over_at)

    def test_shop_words_and_availability_are_cut_live(self):
        self.rent(for_client=None)
        reply = "We have a studio available in Spain Cluster. Our shops are near Dragon Mart. Are you looking for yourself or for a client?"
        outcome, _, _, _ = self.turn(self.inbound("is it still there"), [res_answer(reply)])
        self.assertEqual(self.body(outcome), "Are you looking for yourself or for a client?")

    def test_the_448_chats_move_onto_the_rent_flow(self):
        # A chat of campaign 448 holding 2d's want (no track stored before batch 2e): its question goes to RES_SYSTEM.
        self.set_state(facts={"need": "home", "wanted": "a studio apartment", "property_type": "studio apartment", "for_client": False})
        reply = "Studios in International City are generally around AED 29,000–33,000 a year. Would you like to see one?"
        outcome, calls, _, _ = self.turn(self.inbound("how much?"), [res_answer(reply)])
        self.assertEqual(calls[0][0]["content"], prompt.RES_SYSTEM)
        self.assertEqual(self.body(outcome), reply)
        self.assertEqual((self.state().track, self.state().unit), ("rent", "studio"))


class MixedPathTests(MixedBase):
    def test_the_models_tag_moves_a_not_known_chat_to_shops(self):
        self.ours(rules.line("res_what_need", "en"))
        message = self.inbound("something for my business")
        outcome, calls, _, _ = self.turn(message, [res_answer("Sure! What kind of business?", need_tag="wants_shop", segment="other")])
        self.assertEqual(calls[0][0]["content"], prompt.RES_SYSTEM)
        self.assertEqual(self.body(outcome), "Sure! We have shops in International City too. Is the shop for yourself, or are you checking for a client?")
        self.assertEqual(self.state().track, "shop")

    def test_a_charge_question_before_the_need_is_known_is_answered_never_handed_over(self):
        # No want recorded yet (the not-known track): people.settle still gets a need (residential.RES_NEED), so the deposit and
        # VAT are answered, never a shop's must-answer handover with its alert.
        self.ours(rules.line("res_what_need", "en"))
        reply = "Good question. What are you looking for: a shop, a studio or a one-bedroom?"
        outcome, _, _, _ = self.turn(self.inbound("Is there VAT and deposit?"), [res_answer(reply, segment="other")])
        self.assertEqual(self.body(outcome), f"Good question. {residential.vat_line('en')} What are you looking for: a shop, a studio or a one-bedroom?")
        self.assertFalse(LeadAiAlert.objects.filter(kind=people.QUESTIONS).exists())
        self.assertIsNone(self.state().handed_over_at)

    def test_a_second_unclear_answer_gets_the_neutral_invitation(self):
        self.ours(rules.line("res_what_need", "en"), minutes_ago=20)
        self.ours("Could you tell me a little more about what you need?", minutes_ago=10)
        outcome, calls, _, _ = self.turn(self.inbound("not really sure"), [])
        self.assertEqual(calls, [])
        self.assertTrue(self.body(outcome).startswith("We have many options in International City and across Dubai. Visit our office"))
        self.assertIn("I can hold a slot for you today at 3:00 PM or 5:00 PM", self.body(outcome))


# C. The full-name gate -----------------------------------------------------------------------------------------------


class FullNameTurnTests(RentBase):
    def hold(self):
        self.rent()
        self.ours(INVITE_4_6)
        message = self.inbound("6 PM")
        outcome, _, _, _ = self.turn(message, [res_answer("", action="confirm", place="office", date="2026-10-12", time="18:00")])
        return message, outcome

    def held(self):
        return LeadAiAppointment.objects.get(conversation=self.conversation)

    def test_a_booking_with_no_full_name_holds_the_time_and_asks(self):
        message, outcome = self.hold()
        self.assertEqual(self.body(outcome), "Great! May I have your full name for the booking?")
        held = self.held()
        self.assertEqual((held.status, held.starts_at, held.place), (LeadAiAppointment.Status.TENTATIVE, SIX_PM, "office"))
        self.assertEqual((held.details["held_for_name"], held.details["name_asks"]), (True, 1))
        self.assertEqual(Message.objects.get(pk=outcome.reply_message_id).payload["res_step"], "full_name")
        self.assertEqual(self.actions(message)["full_name"], "asked")
        # No other chat takes the time held for them (one client per slot, Q6).
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509990011"))
        self.assertIn(SIX_PM, engine.taken_slots(other, NOW))

    def test_their_name_books_the_held_time(self):
        self.hold()
        self.later(2)
        outcome, _, _, _ = self.turn(self.inbound("Ahmed Khan", seconds_ago=10), [res_answer("Thank you!")])
        body = self.body(outcome)
        self.assertTrue(body.startswith("Perfect, Ahmed Khan! Your viewing is confirmed ✅\nDate: Monday 12 October\nTime: 6:00 PM"), body)
        self.assertIn(MAPS, body)
        held = self.held()
        self.assertEqual((held.status, held.starts_at), (LeadAiAppointment.Status.CONFIRMED, SIX_PM))
        self.assertNotIn("held_for_name", held.details)
        self.assertEqual(self.state().facts["full_name"], "Ahmed Khan")
        self.assertEqual(self.outbound()[-1].kind, Message.Kind.LOCATION)  # the office pin follows the booking

    def test_a_refusal_keeps_the_hold_and_alerts(self):
        self.hold()
        self.later(2)
        outcome, _, _, _ = self.turn(self.inbound("Why do you need my name?", seconds_ago=10), [res_answer("It is for the booking.")])
        self.assertEqual(self.body(outcome), "No problem — I've noted today at 6:00 PM for you, and our agent will confirm it with you here.")
        held = self.held()
        self.assertEqual((held.status, held.details["name_refused"]), (LeadAiAppointment.Status.TENTATIVE, True))
        alert = LeadAiAlert.objects.filter(kind="tentative", priority="high", title__contains="no full name").first()
        self.assertIsNotNone(alert)

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
    def test_a_crm_full_name_books_at_once(self):
        self.rent()
        self.ours(INVITE_4_6)
        with patch(READ, return_value=LEAD):
            outcome, _, _, _ = self.turn(self.inbound("6 PM"), [res_answer("", action="confirm", place="office", date="2026-10-12", time="18:00")])
        self.assertTrue(self.body(outcome).startswith("Perfect, Ahmed Khan! Your viewing is confirmed ✅"))
        self.assertEqual(self.held().status, LeadAiAppointment.Status.CONFIRMED)

    def test_a_held_slot_taken_meanwhile_gets_the_two_nearest_free(self):
        self.hold()
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509990012"))
        LeadAiAppointment.objects.create(conversation=other, status=LeadAiAppointment.Status.CONFIRMED, place="office", starts_at=SIX_PM)
        self.later(2)
        outcome, _, _, _ = self.turn(self.inbound("Ahmed Khan", seconds_ago=10), [res_answer("Thank you!")])
        self.assertTrue(self.body(outcome).startswith("Sorry, that time is already booked. I can hold a slot for you"), self.body(outcome))
        self.assertEqual(self.held().status, LeadAiAppointment.Status.TENTATIVE)

    def test_an_unanswered_hold_lapses_thirty_minutes_after_the_ask(self):
        self.hold()
        tasks._lapse_shops_tentatives(NOW + dt.timedelta(minutes=29))
        self.assertEqual(self.held().status, LeadAiAppointment.Status.TENTATIVE)
        with self.captureOnCommitCallbacks(execute=False):
            tasks._lapse_shops_tentatives(NOW + dt.timedelta(minutes=31))
        held = self.held()
        self.assertEqual(held.status, LeadAiAppointment.Status.DONE)
        self.assertEqual(held.history[-1]["why"], tasks.LAPSED_NO_NAME)


# D. Handovers and special cases ---------------------------------------------------------------------------------------


class SpecialTurnTests(RentBase):
    def test_a_handover_gets_our_rental_teams_line(self):
        self.rent()
        outcome, _, _, _ = self.turn(self.inbound("I want to talk to a real person"), [res_answer("Sure, Shoaib will call you.", handover="customer_asked_human")])
        self.assertEqual(self.body(outcome), residential.handover_line("en"))
        self.assertEqual(self.state().handover_reason, "customer_asked_human")

    def test_a_call_request_is_peoples(self):
        self.rent()
        outcome, _, _, _ = self.turn(self.inbound("please call me"), [res_answer("Sure, our agent will call you shortly.", handover="call_requested")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_ASK, "en", shops=True))
        self.assertEqual(self.state().handover_reason, "call_requested")

    def test_a_broker_gets_the_line_the_label_and_the_pause(self):
        self.rent(for_client=None)
        outcome, _, _, _ = self.turn(self.inbound("For my client"), [res_answer("", handover="broker_or_for_client", facts={"for_client": True})])
        self.assertEqual(self.body(outcome), rules.line("broker", "en"))
        self.assertIsNotNone(self.state().paused_at)
        self.assertTrue(self.conversation.labels.filter(name__iexact="Broker").exists())

    def test_an_emirates_id_gets_the_documents_line_before_any_model(self):
        self.rent()
        message = self.inbound("My Emirates ID is 784-1990-1234567-1")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual((calls, self.body(outcome)), ([], residential.line("res_no_documents", "en")))

    def test_a_yes_to_a_shops_template_on_the_rent_track_is_no_shop_question(self):
        # A 448 chat on the rent track answering a shops template again: never "Is the shop for yourself ...?" (spec §1.4.2).
        self.rent(for_client=None)
        outcome, calls, _, _ = self.turn(self.inbound("Yes"), [res_answer("Great! Are you looking for yourself or for a client?")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), "Great! Are you looking for yourself or for a client?")

    def test_delete_my_data_stops_every_number_and_alerts_the_admins(self):
        self.rent()
        outcome, calls, _, _ = self.turn(self.inbound("Please delete my data"), [])
        self.assertEqual((calls, self.body(outcome)), ([], residential.line("res_deleted", "en")))
        self.assertEqual(self.state().stop_reason, "stop_all")
        self.assertTrue(optout.is_blocked(self.contact.wa_id))
        # The panel admins hear it, and so do the chat's own people (the CRM review of batch 2e: 2311 never did).
        alerted = set(LeadAiAlert.objects.filter(kind="data_deletion").values_list("agent", flat=True))
        self.assertIn(self.admin.pk, alerted)
        self.assertGreater(len(alerted), 1)

    def test_rented_elsewhere_is_lost_on_the_rent_track(self):
        self.rent()
        outcome, _, _, _ = self.turn(self.inbound("We already found a flat, thanks"), [res_answer("Congratulations!")])
        self.assertEqual(self.body(outcome), residential.line("res_already_rented", "en"))
        self.assertIsNotNone(self.state().not_interested_at)
        # Lost "rented elsewhere" (Q10): never 2d's NEVER_LOST on the rent track.
        lost = LeadAiCrmField.objects.get(conversation=self.conversation, field=crm_fields.LOST)
        self.assertEqual(lost.payload["reason"], "rented elsewhere")

    def test_the_owners_number_gets_none_and_our_office(self):
        self.rent()
        outcome, _, _, _ = self.turn(self.inbound("Give me the owner's number please"), [res_answer("The owner is Mr Ali, 0509998888.")])
        settings_row = LeadAiSettings.load()
        self.assertEqual(self.body(outcome), residential.no_number_text("en", settings_row.office_address, MAPS))

    def test_paying_now_is_handed_over_with_the_official_process(self):
        self.rent()
        outcome, _, _, _ = self.turn(self.inbound("Can I pay the deposit online now?"), [res_answer("Sure, here are our bank details.")])
        self.assertEqual(self.body(outcome), residential.line("res_pay_online", "en"))
        self.assertEqual(self.state().handover_reason, "legal_visa_licence_contract")


# E. The settings API --------------------------------------------------------------------------------------------------


class ResidentialSettingsTests(FirstChatBase):
    def put(self, body):
        return self.client.put("/api/leadai/settings/", body, content_type="application/json")

    def test_the_facts_are_read_validated_and_kept(self):
        self.client.force_login(self.admin)
        data = self.client.get("/api/leadai/settings/").json()
        self.assertEqual(data["residential_facts"]["rent"]["studio"], {"from": 29000, "to": 33000, "average": 31000})
        facts = residential.facts_of(None)
        facts["rent"]["one_br"] = {"from": 41000, "to": 46000}
        self.assertEqual(self.put({"residential_facts": facts}).status_code, 200)
        self.assertEqual(LeadAiSettings.load().residential_facts["rent"]["one_br"], {"from": 41000, "to": 46000})
        facts["rent"]["studio"]["to"] = 1
        response = self.put({"residential_facts": facts})
        self.assertEqual(response.status_code, 400)
        self.assertIn("residential_facts.rent.studio.to", response.json()["errors"])

    def test_only_panel_admins_change_them(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.put({"residential_facts": residential.facts_of(None)}).status_code, 403)


# F. The eval ----------------------------------------------------------------------------------------------------------

REROUTED = (
    "shops-want-studio-44", "shops-want-1bhk-49", "shops-studio-monthly-57", "shops-not-now-studio-68", "shops-studio-balcony-107",
    "shops-asked-for-studio-132", "shops-studio-capitals-136",
)


class EvalReroutedTests(SimpleTestCase):
    def run_scenario(self, scenario_id):
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=RIGHT[scenario_id]):
            return leadai_eval.run_once(scenario, scenario_id)

    @override_settings(LEADAI_OPENAI_API_KEY="test")
    def test_the_launchs_studio_seekers_get_the_opener_and_fail_without_it(self):
        for scenario_id in REROUTED:
            with self.subTest(scenario_id):
                run = self.run_scenario(scenario_id)
                self.assertEqual(run.failures, [])
                self.assertEqual((run.out_by, (run.answer.get("res_line") or {}).get("kind")), (leadai_eval.CODE, "open"))
        with patch.object(residential, "pre_model_rule", return_value=None):
            for scenario_id in REROUTED:
                with self.subTest(scenario_id):
                    self.assertNotEqual(self.run_scenario(scenario_id).failures, [])

    def test_the_rent_flow_scenarios_are_in_the_list(self):
        ids = {s.id for s in leadai_eval.SCENARIOS}
        for wanted in ("shops-res-full-name-given", "shops-res-full-name-refused", "shops-res-commission-figure", "shops-res-delete-my-data"):
            self.assertIn(wanted, ids)
        # The merge's one questions_at_most (the rent and sale lanes each wrote one): what goes out, its own kind, so a
        # scenario that counts its questions itself drops the default count.
        self.assertIs(leadai_eval.RES_REPLY_CHECKS[2], leadai_eval.TWO_QUESTIONS)
        self.assertEqual(leadai_eval.RES_REPLY_CHECKS[2].kinds, frozenset({"questions_count"}))
