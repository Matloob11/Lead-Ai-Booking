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

    def test_no_nudge_follows_the_offer(self):
        from apps.leadai import followups

        self.turn(self.inbound(AREA_NO), [closing()])
        state = self.state()
        self.assertTrue(followups.other_areas_pending(followups.read_since(self.conversation)))
        for kind in (followups.NUDGE_1, followups.NUDGE_2, followups.REENGAGE):
            self.assertEqual(followups.holds(self.conversation, state, leadai_eval.NOW, kind), followups.HELD_DECLINED, kind)

    def test_a_booked_visit_is_never_closed_by_code_s_reading(self):
        from apps.leadai.models import LeadAiAppointment
        from apps.leadai.tests.test_assistant import TUESDAY_5PM

        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=TUESDAY_5PM)
        reply = "Great, see you tomorrow!"
        self.turn(self.inbound("No, not looking for anything else in that area. See you tomorrow."), [shop_answer(reply)])
        self.assertIsNone(self.state().not_interested_at)
        self.assertTrue(LeadAiAppointment.objects.filter(conversation=self.conversation, status="confirmed").exists())

    def test_the_reconnect_list_holds_the_offer_too(self):
        from apps.leadai import followups

        self.turn(self.inbound(AREA_NO), [closing()])
        reading = followups.read_since(self.conversation)
        self.assertTrue(followups.other_areas_pending(reading))
        # The customer answers it: no longer pending.
        self.inbound("Maybe JVC, a studio", seconds_ago=5)
        self.assertFalse(followups.other_areas_pending(followups.read_since(self.conversation)))

    def test_a_backstop_turn_with_codes_own_step_keeps_it(self):
        # Settle marks the model's none over an area decline; a later step of code's own (here a fixed line, which
        # "converted" marks) lands on the same turn: plain_turn refuses, so code's line goes, never the offer over it.
        # (A time the model proposed that the customer never named is no step of code's: own_offer clears it, and the offer
        # rightly replaces a viewing pitch to someone who just said no.)
        real = engine.settle
        marked = []

        def settle_then_codes_line(answer, *args, **kwargs):
            out = real(answer, *args, **kwargs)
            marked.append(answer.get("backstop"))
            answer["converted"] = "holding"
            answer["reply"] = rules.line("holding", "en")
            return out

        with patch.object(engine, "settle", side_effect=settle_then_codes_line):
            outcome, _, _, _ = self.turn(self.inbound(AREA_NO), [shop_answer("Noted, thank you.")])
        self.assertEqual(marked, [engine.AREA_BACKSTOP])  # the turn reached the dispatch's gate marked
        self.assertIsNone(self.state().facts.get("other_areas_offered"))
        self.assertEqual(self.body(outcome), rules.line("holding", "en"))

    def test_plain_turn_refuses_every_step_of_codes(self):
        bare = {"handover": {"needed": False, "reason": None}, "appointment": {"action": "none"}}
        self.assertTrue(engine.plain_turn(dict(bare)))
        for key, value in (
            ("converted", "check_back"), ("res_line", {"kind": "res_open"}), ("shop_step", {"kind": "list"}),
            ("not_a_shop", {"kind": "home"}), ("slot_taken", True), ("broker", True),
        ):
            self.assertFalse(engine.plain_turn({**bare, key: value}), key)
        self.assertFalse(engine.plain_turn({**bare, "handover": {"needed": True, "reason": "customer_asked_human"}}))
        self.assertFalse(engine.plain_turn({**bare, "appointment": {"action": "tentative"}}))
        self.assertFalse(engine.plain_turn(dict(bare), when=leadai_eval.NOW))
        self.assertFalse(engine.plain_turn(dict(bare), still_invalid=True))

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

    def test_a_2d_need_chat_keeps_its_never_lost_no_and_the_rent_track_gets_the_offer(self):
        from apps.leadai.assistant import residential

        need = {"need": "home", "wanted": "a studio"}
        off_track = types.SimpleNamespace(facts=need, stopped_at=None, handed_over_at=None, track="")
        self.assertFalse(engine.offers_other_areas(off_track, rules.NOT_INTERESTED, None, "no thanks"))
        with patch.object(residential, "RENT_LIVE", True):
            for track in ("rent", "sale"):
                on_track = types.SimpleNamespace(facts=need, stopped_at=None, handed_over_at=None, track=track)
                self.assertTrue(engine.offers_other_areas(on_track, rules.NOT_INTERESTED, None, "no thanks"), track)
        with patch.object(residential, "RENT_LIVE", False):
            on_track = types.SimpleNamespace(facts=need, stopped_at=None, handed_over_at=None, track="rent")
            self.assertFalse(engine.offers_other_areas(on_track, rules.NOT_INTERESTED, None, "no thanks"))
        # A shop lead (chat 54622's facts) is no 2d need chat: the offer.
        shop = types.SimpleNamespace(facts={"intent": "rent", "community": "International City", "property_type": "shop"}, stopped_at=None, handed_over_at=None, track="")
        self.assertTrue(engine.offers_other_areas(shop, rules.NOT_INTERESTED, None, AREA_NO))

    def test_the_offer_names_no_community_the_chat_is_on(self):
        packs = [types.SimpleNamespace(name="Mudon"), types.SimpleNamespace(name="JVC"), types.SimpleNamespace(name="Al Furjan")]
        with patch("apps.leadai.assistant.communities.named_packs", return_value=packs):
            names = engine._other_area_names(types.SimpleNamespace(campaign=None), types.SimpleNamespace(community="Mudon"))
            self.assertEqual(names, ["JVC", "Al Furjan"])
            self.assertEqual(engine._other_area_names(types.SimpleNamespace(campaign=None)), ["Mudon", "JVC", "Al Furjan"])

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
        for text in (AREA_NO, "No longer looking", "Not interested in that location anymore", "we are not searching there anymore"):
            self.assertTrue(engine.area_decline(text), text)
        for text in (
            "Not looking in International City anymore, I am looking in JVC for a studio",
            "Not interested in a shop, is there a studio?",
            "Not interested in that area, do you have anything in JVC?",
            "We are not looking there, we need a bigger place",
            # The second review: a yes, or a choice among our shops, is never a no.
            "No, not looking for anything else. See you there tomorrow.",
            "Not interested in the corner shop there, the one near the entrance is fine",
            # The third: a unit turned down is no area.
            "Not interested in that place, it's too small",
        ):
            self.assertFalse(engine.area_decline(text), text)

    def test_a_place_said_beside_a_plain_no_is_a_place(self):
        for words in (
            "We moved into a new apartment last week, not looking anymore",
            "We rented in Silicon Oasis, no longer looking",
            "we're settled in JLT now, not looking anymore",
        ):
            self.assertTrue(engine.place_found(words), words)
            self.assertFalse(engine.offers_other_areas(self.state(), rules.NOT_INTERESTED, {"facts": {"already_rented": True}}, words), words)
        self.assertTrue(engine.plain_no("We are no longer looking, thanks"))
        self.assertTrue(engine.plain_no(AREA_NO))
        self.assertTrue(engine.place_found("we are sorted in JLT, no longer looking"))
        self.assertFalse(engine.plain_no("we are sorted in JLT, no longer looking"))
        self.assertFalse(engine.place_found("We are no longer looking, thanks"))
        # The third review: a greeting beside a plain no is still one (the rent flow read it as rented elsewhere).
        for words in (
            "Hi, we are not looking anymore", "All good, not looking anymore", "We're fine, no longer looking",
            "Thanks for reaching out, not looking anymore", "No I'm good thanks " + AREA_NO,
        ):
            self.assertTrue(engine.plain_no(words), words)
            self.assertTrue(engine.offers_other_areas(self.state(), rules.NOT_INTERESTED, {"facts": {"already_rented": True}}, words), words)
        # The fourth: anything else said beside it keeps the reading of a place found elsewhere (the close).
        for words in ("No longer looking, I bought property in Dubai Hills", "Not looking anymore, my company arranged a flat for me"):
            self.assertFalse(engine.plain_no(words), words)
            self.assertFalse(engine.offers_other_areas(self.state(), rules.NOT_INTERESTED, {"facts": {"already_rented": True}}, words), words)
            self.assertTrue(engine.offers_other_areas(self.state(), rules.NOT_INTERESTED, {"facts": {}}, words), words)

    def test_a_stale_handover_is_no_hold_for_the_rule_path(self):
        held = types.SimpleNamespace(facts={}, stopped_at=None, handed_over_at=leadai_eval.NOW)
        self.assertFalse(engine.offers_other_areas(held, rules.NOT_INTERESTED, None, "no thanks"))
        self.assertTrue(engine.offers_other_areas(held, rules.NOT_INTERESTED, None, "no thanks", held=False))

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
