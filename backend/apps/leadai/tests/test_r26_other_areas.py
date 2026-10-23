"""Round 26 (Matloob 2026-10-23, chat 54622 / lead 73988): the AI must not give up on a first "not interested". A typed
no that is no stop, no wrong number, no tap and no place found elsewhere gets ONE offer of the other areas
(rules.LINES other_areas) instead of the close, the chat stays open, nothing is Lost; a second no closes it as before.
Live in both sinks (engine._opt_out for the model's tag, engine._rule_opt_out for code's own "No thanks") and mirrored
by the eval (leadai_eval: code_first, run_once, outgoing).

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import types
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai.assistant import crm_fields, engine, rules
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiTurn
from apps.leadai.tests.test_eval_guard_fixes import run_scenario
from apps.leadai.tests.test_eval_guards import scenario
from apps.leadai.tests.test_first_chat_fixes import FirstChatBase
from apps.leadai.tests.test_shops_playbook import ShopsBase, shop_answer

AREA_NO = "We are not looking for properties in that area anymore"
CLOSE = "No problem, thank you for letting us know."


def closing(reply=CLOSE):
    return shop_answer(reply, opt_out="not_interested")


class FirstNoTests(ShopsBase):
    def test_the_models_not_interested_gets_the_offer_not_the_close(self):
        outcome, calls, _, _ = self.turn(self.inbound(AREA_NO), [closing()])
        self.assertEqual(len(calls), 1)
        body = self.body(outcome)
        self.assertIn("Which area are you looking in", body)
        self.assertIn("other areas of Dubai", body)
        state = self.state()
        self.assertIsNone(state.not_interested_at)
        self.assertIs(state.facts.get("other_areas_offered"), True)
        self.assertNotIn(crm_fields.LOST, [field for field, _ in self.fields()])
        self.assertEqual(outcome.actions.get("offer"), "other_areas")

    def test_the_models_own_no_tag_still_gets_the_offer_for_an_area_decline(self):
        # The model answered as a plain reply (no opt-out): "not looking in that area anymore" is a no with its reason.
        outcome, _, _, _ = self.turn(self.inbound(AREA_NO), [shop_answer("Understood. Thank you.")])
        self.assertIn("Which area are you looking in", self.body(outcome))
        self.assertIsNone(self.state().not_interested_at)

    def test_a_second_no_closes_the_lead(self):
        self.set_state(facts={"other_areas_offered": True})
        outcome, _, _, _ = self.turn(self.inbound("No thanks, we are not interested in any area"), [closing()])
        self.assertEqual(self.body(outcome), rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertIsNotNone(self.state().not_interested_at)

    def test_a_place_found_elsewhere_gets_no_offer(self):
        # The shops flow's own reading (board T27): the second-shop question first, never the offer; its no is the close.
        outcome, _, _, _ = self.turn(self.inbound("No thank you, I already rented a shop last month"), [closing()])
        self.assertNotIn("Which area", self.body(outcome))
        self.assertIsNone(self.state().facts.get("other_areas_offered"))
        outcome, calls, _, _ = self.turn(self.inbound("No"), [])
        self.assertEqual(len(calls), 0)
        self.assertEqual(self.body(outcome), rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertIsNotNone(self.state().not_interested_at)
        self.assertIsNone(self.state().facts.get("other_areas_offered"))

    def test_a_pending_check_back_keeps_its_no_as_the_close(self):
        self.set_state(followup_asked_at=leadai_eval.NOW)
        outcome, calls, _, _ = self.turn(self.inbound("No thankyou"), [])
        self.assertEqual(len(calls), 0)
        self.assertEqual(self.body(outcome), rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertIsNotNone(self.state().not_interested_at)

    def test_a_plain_no_thanks_is_codes_offer_before_any_model(self):
        outcome, calls, _, _ = self.turn(self.inbound("No thanks"), [])
        self.assertEqual(len(calls), 0)
        self.assertIn("Which area are you looking in", self.body(outcome))
        state = self.state()
        self.assertIsNone(state.not_interested_at)
        self.assertIs(state.facts.get("other_areas_offered"), True)
        self.assertEqual(outcome.actions.get("by"), "rule")
        # The second no, code's too ("not interested" is a whole-message phrase): the close.
        outcome, calls, _, _ = self.turn(self.inbound("not interested"), [])
        self.assertEqual(len(calls), 0)
        self.assertEqual(self.body(outcome), rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertIsNotNone(self.state().not_interested_at)

    def test_a_lead_closed_already_gets_no_offer(self):
        self.set_state(not_interested_at=leadai_eval.NOW)
        outcome, calls, _, _ = self.turn(self.inbound("No thanks"), [])
        self.assertEqual(len(calls), 0)
        self.assertIsNone(outcome.reply_message_id)  # recorded already: nothing goes, as before round 26
        self.assertIsNone(self.state().facts.get("other_areas_offered"))

    def test_a_not_interested_tap_then_typed_words_is_the_close(self):
        self.tap("Not interested", seconds_ago=40)
        outcome, calls, _, _ = self.turn(self.inbound("Good luck with your business", seconds_ago=30), [])
        self.assertEqual(len(calls), 0)
        self.assertEqual(self.body(outcome), rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertIsNone(self.state().facts.get("other_areas_offered"))

    def test_a_failed_send_leaves_the_offer_for_the_next_no(self):
        with patch.object(engine, "_send", side_effect=RuntimeError("gateway down")):
            outcome, _, _, _ = self.turn(self.inbound(AREA_NO), [closing()])
        self.assertEqual(outcome.status, LeadAiTurn.Status.FAILED)
        state = self.state()
        self.assertIsNone(state.facts.get("other_areas_offered"))
        self.assertIsNone(state.not_interested_at)

    def test_a_decline_beside_another_area_is_no_close(self):
        reply = "Great, we have options in JVC too. Would you like to visit our office to go through them?"
        words = "Not looking in International City anymore, I am looking in JVC for a studio"
        outcome, _, _, _ = self.turn(self.inbound(words), [shop_answer(reply)])
        self.assertIsNone(self.state().not_interested_at)
        self.assertNotIn(self.body(outcome), (CLOSE, rules.line_for(rules.NOT_INTERESTED, "en", shops=True)))

    def test_after_the_offer_their_answer_is_never_read_as_a_no(self):
        self.set_state(facts={"other_areas_offered": True})
        reply = "Noted. Would you like to visit our office to go through the options in Al Nahda?"
        self.turn(self.inbound("Not looking in that area anymore, maybe Al Nahda"), [shop_answer(reply)])
        self.assertIsNone(self.state().not_interested_at)

    def test_a_stop_tap_and_a_stop_word_still_stop(self):
        outcome, calls, _, _ = self.turn(self.tap("Stop messages"), [])
        self.assertEqual(len(calls), 0)
        self.assertNotIn("Which area", self.body(outcome) or "")
        self.assertIsNotNone(self.state().stopped_at)

    def test_a_person_holding_the_chat_keeps_the_close(self):
        self.set_state(handed_over_at=leadai_eval.NOW, handover_reason="customer_asked_human")
        self.turn(self.inbound("No thanks"), [])
        self.assertIs(self.state().facts.get("other_areas_offered", None), None)


class GeneralFirstNoTests(FirstChatBase):
    """The general playbook: a typed "No thanks" is code's before any model (no never-lost reading there)."""

    def test_codes_plain_no_thanks_is_the_offer_then_the_close(self):
        outcome, calls, _, _ = self.turn(self.inbound("No thanks"), [])
        self.assertEqual(len(calls), 0)
        self.assertIn("Which area are you looking in", self.body(outcome))
        state = self.state()
        self.assertIsNone(state.not_interested_at)
        self.assertIs(state.facts.get("other_areas_offered"), True)
        self.assertEqual(outcome.actions.get("by"), "rule")
        outcome, calls, _, _ = self.turn(self.inbound("not interested"), [])
        self.assertEqual(len(calls), 0)
        self.assertEqual(self.body(outcome), rules.line("not_interested", "en"))
        self.assertIsNotNone(self.state().not_interested_at)


class GuardTests(SimpleTestCase):
    def state(self, **facts):
        return types.SimpleNamespace(facts=facts, stopped_at=None, handed_over_at=None)

    def test_the_guard_itself(self):
        state = self.state()
        self.assertTrue(engine.offers_other_areas(state, rules.NOT_INTERESTED, None, "No I'm good thanks"))
        self.assertTrue(engine.offers_other_areas(state, rules.NOT_INTERESTED, {"facts": {}}, AREA_NO))
        for kind, answer, words, extra in (
            (rules.STOP_ALL, None, "stop", {}),
            (rules.WRONG_NUMBER, None, "wrong number", {}),
            (rules.NOT_INTERESTED, None, "No, I already rented a shop", {}),
            (rules.NOT_INTERESTED, None, "found a flat already thanks", {}),
            (rules.NOT_INTERESTED, None, "we got one already", {}),
            (rules.NOT_INTERESTED, {"facts": {"already_rented": True}}, "no", {}),
            (rules.NOT_INTERESTED, {"rule": "check_back_no"}, "no", {}),
            (rules.NOT_INTERESTED, None, "no thanks", {"tapped": True}),
            (rules.NOT_INTERESTED, None, "no thanks", {"visit_open": True}),
        ):
            self.assertFalse(engine.offers_other_areas(state, kind, answer, words, **extra), (kind, words, extra))
        self.assertFalse(engine.offers_other_areas(self.state(other_areas_offered=True), rules.NOT_INTERESTED, None, "no thanks"))
        self.assertFalse(engine.offers_other_areas(self.state(already_rented=True), rules.NOT_INTERESTED, None, "no thanks"))
        held = types.SimpleNamespace(facts={}, stopped_at=None, handed_over_at=leadai_eval.NOW)
        self.assertFalse(engine.offers_other_areas(held, rules.NOT_INTERESTED, None, "no thanks"))

    def test_the_line_names_the_other_communities(self):
        self.assertEqual(engine.other_areas_text("en", ["JVC", "Discovery Gardens", "Dubai Silicon Oasis", "Extra"]), ", for example JVC, Discovery Gardens and Dubai Silicon Oasis")
        self.assertEqual(engine.other_areas_text("en", ["JVC"]), ", for example JVC")
        self.assertEqual(engine.other_areas_text("ar", ["JVC", "Al Furjan"]), " (JVC, Al Furjan)")
        self.assertEqual(engine.other_areas_text("en", []), "")
        line = rules.line(rules.OTHER_AREAS, "en").replace("{areas}", engine.other_areas_text("en", ["JVC"]))
        self.assertEqual(line, "No problem. We also have options in other areas of Dubai, for example JVC. Which area are you looking in, and what kind of unit? We can show you there.")
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            self.assertIn("{areas}", rules.line(rules.OTHER_AREAS, language), language)

    def test_the_answer_turned_into_the_offer(self):
        answer = {"opt_out": "not_interested", "send": True, "reply": CLOSE, "handover": {"needed": False, "reason": None}, "facts": {"x": 1}, "lost_reason": "no"}
        engine.other_areas_answer(answer, "en", ["JVC"])
        self.assertEqual((answer["opt_out"], answer["send"], answer["other_areas"], answer["facts"]["other_areas_offered"]), ("none", True, True, True))
        self.assertIn("for example JVC", answer["reply"])
        self.assertNotIn("lost_reason", answer)

    def test_an_area_decline_is_a_no_with_its_reason(self):
        for text in (AREA_NO, "Not interested in that location", "No longer looking", "we are not searching there anymore"):
            self.assertTrue(engine.AREA_DECLINE.search(text), text)
        for text in ("Not that one, the other shop", "I am interested in the area near Dragon Mart", "Is the area quiet?"):
            self.assertFalse(engine.AREA_DECLINE.search(text), text)

    def test_the_backstop_reads_the_gist_only(self):
        for text in (AREA_NO, "No longer looking", "Not interested in that location anymore"):
            self.assertTrue(engine.area_decline(text), text)
        for text in (
            "Not looking in International City anymore, I am looking in JVC for a studio",
            "Not interested in a shop, is there a studio?",
            "Not interested in that area, do you have anything in JVC?",
            "We are not looking there, we need a bigger place",
        ):
            self.assertFalse(engine.area_decline(text), text)

    def test_a_lead_closed_already_or_a_place_in_urdu_or_hindi_gets_no_offer(self):
        closed = types.SimpleNamespace(facts={}, stopped_at=None, handed_over_at=None, not_interested_at=leadai_eval.NOW)
        self.assertFalse(engine.offers_other_areas(closed, rules.NOT_INTERESTED, None, "no thanks"))
        for words in ("Sorry, jagah mil gayi, nahi chahiye", "flat le li hai", "گھر مل گیا، شکریہ", "मकान मिल गया"):
            self.assertTrue(engine.place_found(words), words)
            self.assertFalse(engine.offers_other_areas(self.state(), rules.NOT_INTERESTED, None, words), words)
        self.assertFalse(engine.place_found("We are no longer looking, thanks"))
        self.assertFalse(engine.place_found(AREA_NO))

    def test_the_rent_flows_plain_no_gets_the_offer_and_a_place_the_close(self):
        from apps.leadai.tests.test_residential import settle as res_settle

        words = "We are no longer looking, thanks"
        answer, cut = res_settle("Thanks for letting us know.", [words])
        self.assertIn("already_rented", cut)
        self.assertEqual((answer["opt_out"], answer.get("opt_out_line"), answer["facts"].get("already_rented")), ("not_interested", "res_already_rented", True))
        self.assertTrue(engine.offers_other_areas(self.state(), answer["opt_out"], answer, words))
        engine.other_areas_answer(answer, "en")
        self.assertEqual(
            (answer["opt_out"], answer.get("opt_out_line"), answer.get("lost_reason"), answer["facts"].get("already_rented")), ("none", None, None, None)
        )
        found = "We already found a flat, thanks"
        answer, _ = res_settle("Congrats!", [found])
        self.assertFalse(engine.offers_other_areas(self.state(), answer["opt_out"], answer, found))
        # The model's own reading of a place, in words that are no plain no, is trusted: the close.
        self.assertFalse(engine.offers_other_areas(self.state(), rules.NOT_INTERESTED, {"facts": {"already_rented": True}}, "we are sorted, thanks"))


class EvalMirrorTests(ShopsBase):
    """The eval's scenarios run with a right answer: the offer as live, code's words."""

    def test_the_models_close_becomes_the_offer(self):
        run, calls = run_scenario(scenario("shops-area-decline"), closing())
        self.assertEqual(calls, 1)
        self.assertEqual((run.answer["opt_out"], run.out_by), ("none", leadai_eval.CODE))
        self.assertIn("Which area are you looking in", run.out)
        self.assertIs(run.answer["facts"].get("other_areas_offered"), True)
        self.assertEqual(run.failures, [], run.failures)

    def test_a_plain_no_thanks_is_codes_offer(self):
        run, calls = run_scenario(scenario("shops-no-thanks-offer"))
        self.assertEqual(calls, 0)
        self.assertEqual((run.answer["opt_out"], run.out_by), ("none", leadai_eval.CODE))
        self.assertIn("Which area are you looking in", run.out)
        self.assertEqual(run.failures, [], run.failures)

    def test_the_second_no_closes(self):
        run, calls = run_scenario(scenario("shops-area-decline-again"))
        self.assertEqual(calls, 0)
        self.assertEqual(run.answer["opt_out"], "not_interested")
        self.assertEqual(run.out, rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertEqual(run.failures, [], run.failures)
