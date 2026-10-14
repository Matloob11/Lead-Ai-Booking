"""The code guards behind batch 2a's failing eval scenarios (each mirrored by leadai_eval):

- A. "How do I reach there?" after our location went out: a line points to it
  (engine.point_to_location; eval location-again);
- B. a deferral said with a day or an hour is still a deferral, settled by code
  (rules.is_dated_deferral; eval defer-with-time);
- C. one client per slot holds for a tentative visit too, and a slot refused as
  taken is offered around with the two nearest free starts, from code
  (engine.taken_tentative, engine.offers_starts; eval shops-taken);
- D. a shops reply that invites before the licence is known asks the licence
  (engine.licence_first; eval shops-35283);
- E. a plain chain message or scam in a shops chat is spam, settled by code
  (rules.looks_like_spam; eval shops-spam).

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import lane
from apps.leadai.assistant import engine, filters, hours, prompt, rules, schema, shops
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAppointment, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, TUESDAY_5PM, answer
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_first_chat_fixes import ADDRESS, INVITATION, FirstChatBase
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, at, shop_answer

POINTER = rules.line("location_above", "en")
ASK_LICENCE = rules.line("ask_licence", "en")
TAKEN_LINE = "Sorry, that time is already booked. I can hold a slot for you tomorrow at 4:30 PM or 5:30 PM — which is better?"
SPAM = "🔥 Earn money daily from home! Join our crypto investment group now, limited seats, forward to 10 friends 🔥"
VAPE_INVITE = (
    "A vape shop, got it. For a vape business, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. "
    "I can hold a slot for you today at 2:30 PM or 3:00 PM — which is better?"
)
VAPE_LICENCE = (
    "A vape shop, got it. For a vape business, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. " + ASK_LICENCE
)
VAPE_KNOWN = {"for_client": False, "property_type": "shop", "size_sqft": 450, "budget_aed": 35000, "budget_basis": "per_year"}
ASKED_BUSINESS = [("campaign", "Hi Sumon, A7 Real Estate here."), ("assistant", f"Here is our office:\n{ADDRESS}\nWhat business will the shop be for?")]


def scenario(scenario_id):
    return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)


def run_eval(scenario_id, *completions):
    """The scenario as the eval runs it, with these model answers; (run, the number of model calls)."""
    calls = []

    def model(messages, schema_, **kwargs):
        calls.append(messages)
        return completions[min(len(calls) - 1, len(completions) - 1)]

    with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
        run = leadai_eval.run_once(scenario(scenario_id), scenario_id)
    return run, len(calls)


def normal(completion, shops_chat=False):
    return schema.normalize(completion.data, shops=shops_chat)


# A. The location already sent ---------------------------------------------------------------------


class AsksTheWayTests(SimpleTestCase):
    def test_what_asks_the_way(self):
        for text in (
            "How do I reach there?", "how to reach", "How can I come there?", "How do I get to your office?", "How will I find you",
            "Where is your office?", "where r u", "Where exactly?", "I can’t find your office", "kaise aaun?", "Aap ka office kahan hai",
            "كيف أصل؟", "وين مكتبكم؟", "آفس کہاں ہے؟", "ऑफिस कहाँ है?",
        ):
            with self.subTest(text=text):
                self.assertTrue(filters.asks_the_way(text))
        for text in ("How do I get a licence?", "How much is the rent?", "Please send the location", "I will come tomorrow", "", "Where do you want to open?"):
            with self.subTest(text=text):
                self.assertFalse(filters.asks_the_way(text))

    def test_what_points_to_it(self):
        for text in (
            POINTER, "You can find us at the location above.", "It is in the message above.", "I already shared it", "We sent the address earlier",
            "Upar wala message dekhein", "الموقع أعلاه", "اوپر والے میسج میں دیکھیں", "ऊपर वाले मैसेज में है",
        ):
            with self.subTest(text=text):
                self.assertTrue(filters.points_to_location(text))
        for text in (
            "Would 11 AM or 5 PM tomorrow work?", "", "Our office is in International City.", "Shops above 400 sq ft are available.",
            "400 sq ft se upar ki shop", "Our specialist will share directions with you at the meeting.",
        ):
            with self.subTest(text=text):
                self.assertFalse(filters.points_to_location(text))
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language=language):
                self.assertTrue(filters.points_to_location(rules.line("location_above", language)))

    def test_the_line_in_every_language(self):
        self.assertEqual(POINTER, "Our office location is in my message above.")
        for language in ("ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language=language):
                self.assertNotEqual(rules.line("location_above", language), POINTER)
        self.assertTrue(filters.points_to_location(POINTER))


class PointToLocationTests(SimpleTestCase):
    def point(self, completion, said="How do I reach there?", address=ADDRESS):
        out = normal(completion)
        return out, engine.point_to_location(out, [said], address)

    def test_a_reply_that_does_not_point_gets_the_line_first(self):
        out, pointed = self.point(answer("Would you like to come by today at 4 PM or tomorrow at 11 AM?"))
        self.assertEqual((pointed, out["reply"], out["send"]), ("pointer", f"{POINTER} Would you like to come by today at 4 PM or tomorrow at 11 AM?", True))

    def test_a_reply_that_points_already_stays(self):
        out, pointed = self.point(answer("You can find us at the location above. Would 11 AM work?"))
        self.assertEqual((pointed, out["reply"]), ("", "You can find us at the location above. Would 11 AM work?"))

    def test_a_reply_that_is_only_the_address_again_becomes_the_line(self):
        out, pointed = self.point(answer(f"We are at {ADDRESS}."))
        self.assertEqual((pointed, out["reply"], out["reply_en"]), ("location", POINTER, ""))
        out, pointed = self.point(answer(f"نحن في {ADDRESS}.", language="ar", reply_en=f"We are at {ADDRESS}."), said="كيف أصل؟")
        self.assertEqual((pointed, out["reply"], out["reply_en"]), ("location", rules.line("location_above", "ar"), POINTER))

    def test_an_empty_reply_is_the_line_alone(self):
        out, pointed = self.point(answer("", send=False))
        self.assertEqual((pointed, out["reply"], out["send"]), ("pointer", POINTER, True))

    def test_its_language_and_its_gloss(self):
        out, _ = self.point(answer("هل يناسبك الحضور غداً؟", language="ar", reply_en="Would tomorrow suit you?"), said="كيف أصل؟")
        self.assertEqual(out["reply"], f"{rules.line('location_above', 'ar')} هل يناسبك الحضور غداً؟")
        self.assertEqual(out["reply_en"], f"{POINTER} Would tomorrow suit you?")

    def test_nothing_changes_otherwise(self):
        cases = (
            (answer("Sure. What size do you need?"), "I have a salon", ADDRESS),  # no way asked
            (answer("Sure."), "How do I reach there?", ""),  # not sent, or they asked for the location itself
            (answer("Understood.", opt_out="stop_all"), "How do I reach there? Stop", ADDRESS),
        )
        for completion, said, address in cases:
            with self.subTest(said=said, address=address):
                out, pointed = self.point(completion, said=said, address=address)
                self.assertEqual((pointed, out["reply"]), ("", normal(completion)["reply"]))
        converted = normal(answer("x"))
        converted["converted"] = "holding"
        self.assertEqual(engine.point_to_location(converted, ["How do I reach there?"], ADDRESS), "")

    def test_settle_points_last_so_the_no_repeat_guard_keeps_it(self):
        # Asked again with no question mark, the shops no-repeat guard runs; the line said before still goes.
        earlier = [("assistant", f"Our office is here:\n{ADDRESS}"), ("assistant", POINTER)]
        out = engine.settle(normal(shop_answer("Great. What size do you need?"), True), earlier, ["how do i reach there"], 1, playbook=lane.IC_SHOPS, address_sent=ADDRESS)
        self.assertEqual((out["reply"], out["pointed"]), (f"{POINTER} Great. What size do you need?", "pointer"))


class PointToLocationTurnTests(FirstChatBase):
    def test_how_do_i_reach_there_gets_the_line_and_never_the_address_again(self):
        self.ours(f"Our office is here:\n{ADDRESS}", minutes_ago=5)
        message = self.inbound("How do I reach there?")
        outcome, calls, _, _ = self.turn(message, [answer("Would 11 AM or 5 PM tomorrow work for you?", share_location=True)])
        self.assertEqual(self.body(outcome), f"{POINTER} Would 11 AM or 5 PM tomorrow work for you?")
        self.assertIn("LOCATION ALREADY SENT: yes", calls[0][1]["content"])
        actions = self.actions(message)
        self.assertEqual(actions["pointed"], "pointer")
        self.assertNotIn("location_appended", actions)

    def test_the_retyped_address_is_cut_and_the_line_takes_its_place(self):
        self.ours(f"Our office is here:\n{ADDRESS}", minutes_ago=5)
        message = self.inbound("كيف أصل؟")
        reply = f"مكتبنا في {ADDRESS}. هل يناسبك الحضور غداً؟"
        outcome, _, _, _ = self.turn(message, [answer(reply, language="ar", reply_en=f"Our office is in {ADDRESS}. Would tomorrow suit you?")])
        self.assertEqual(self.body(outcome), f"{rules.line('location_above', 'ar')} هل يناسبك الحضور غداً؟")
        actions = self.actions(message)
        self.assertEqual((actions["trimmed"], actions["pointed"]), (["location"], "pointer"))
        self.assertNotIn("reply_en", Message.objects.get(pk=outcome.reply_message_id).payload)  # a sentence was cut: no gloss

    def test_the_gloss_carries_the_line(self):
        self.ours(f"Our office is here:\n{ADDRESS}", minutes_ago=5)
        outcome, _, _, _ = self.turn(self.inbound("كيف أصل؟"), [answer("هل يناسبك الحضور غداً؟", language="ar", reply_en="Would tomorrow suit you?")])
        payload = Message.objects.get(pk=outcome.reply_message_id).payload
        self.assertEqual(payload["reply_en"], f"{POINTER} Would tomorrow suit you?")

    def test_asked_for_the_location_itself_it_goes_again_and_a_day_later_too(self):
        self.ours(f"Our office is here:\n{ADDRESS}", minutes_ago=5)
        outcome, _, _, _ = self.turn(self.inbound("How do I reach there? Send the location please"), [answer("Sure, here it is.", share_location=True)])
        self.assertEqual(self.body(outcome), f"Sure, here it is.\n{ADDRESS}")
        Message.objects.filter(payload__source="leadai_ai").update(created_at=NOW - dt.timedelta(hours=25))
        self.clock.return_value = NOW + dt.timedelta(minutes=1)
        outcome, _, _, _ = self.turn(self.inbound("How do I reach there?", seconds_ago=10), [answer("Our office is in International City.", share_location=True)])
        self.assertEqual(self.body(outcome), f"Our office is in International City.\n{ADDRESS}")


class PointToLocationEvalTests(TestCase):
    def test_location_again_passes_with_the_answers_the_model_gave(self):
        for completion in (
            eval_answer("Would you like to visit us tomorrow at 10 AM, 2 PM or 5 PM?"),
            eval_answer("Our specialist will share directions with you at the meeting. When would you like to visit our office?"),
            eval_answer(f"Our office is in {ADDRESS}, near Dragon Mart. Would you like to come by today at 4 PM or tomorrow at 11 AM?"),
        ):
            with self.subTest(reply=completion.data["reply"][:40]):
                run, _ = run_eval("location-again", completion)
                self.assertEqual(run.failures, [])
                self.assertTrue(run.out.startswith(POINTER))


# B. A deferral with a day or an hour ----------------------------------------------------------------


class DatedDeferralTests(SimpleTestCase):
    def test_a_deferral_with_a_day_or_an_hour(self):
        for text in (
            "Tomorrow at 5 pm, I will let you know", "Tomorrow 5pm I'll confirm", "kal 5 baje bata dunga", "Maybe Wednesday, I will message you",
            "Saturday morning I'll let u know", "I will let you know by tomorrow evening", "5:30 tomorrow, will confirm",
        ):
            with self.subTest(text=text):
                self.assertTrue(rules.is_dated_deferral(text))
        for text in (
            "I will come tomorrow at 5", "Tomorrow at 5 pm", "Tomorrow at 5? I will let you know", "Can I come tomorrow at 5 pm? I will let you know",
            "Tomorrow at 5 pm is fine, I will let you know if anything changes", "I will message you", "let me know the rent tomorrow", "",
            "Tomorrow at 5 pm or maybe Wednesday at 6 pm or Thursday morning, I will let you know for sure",
            "Tomorrow evening, later",  # a bare "later" puts nothing off (test_eval_guard_fixes, F2)
        ):
            with self.subTest(text=text):
                self.assertFalse(rules.is_dated_deferral(text))

    def test_the_rule_takes_it_only_for_a_visit_on_the_table(self):
        text = "Tomorrow at 5 pm, I will let you know"
        self.assertEqual(engine.deferral([text], invites=1), text)
        self.assertEqual(engine.deferral([text], offered=True), text)
        self.assertEqual(engine.deferral([text]), "")
        self.assertEqual(engine.deferral([text], invites=1, quiet=True), "")
        self.assertEqual(engine.deferral(["I will come tomorrow at 5"], invites=1), "")

    def test_its_answer_keeps_their_words_never_a_time(self):
        out = engine.deferral_answer("Tomorrow at 5 pm, I will let you know", "en")
        self.assertEqual(
            (out["appointment"], out["converted"], out["reply"]),
            (
                {"action": "tentative", "place": "office", "date": None, "time": None, "customer_words": "Tomorrow at 5 pm, I will let you know"},
                "let_me_know",
                rules.line("let_me_know", "en"),
            ),
        )


class DatedDeferralTurnTests(FirstChatBase):
    def test_tomorrow_at_5_i_will_let_you_know_is_settled_by_code(self):
        self.ours(INVITATION, minutes_ago=10)
        self.set_state(invites=1)
        message = self.inbound("Tomorrow at 5 pm, I will let you know")
        outcome, calls, crm_delay, _ = self.turn(message, [answer("Noted. Here is our office location.", invited=True, share_location=True)])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), rules.line("let_me_know", "en"))
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.place, appointment.starts_at, appointment.note), ("tentative", "office", None, "Tomorrow at 5 pm, I will let you know"))
        crm_delay.assert_called_once()
        self.assertEqual(self.actions(message)["rule"], "deferral")
        self.assertEqual(self.state().invites, 1)


class DatedDeferralShopsTurnTests(ShopsBase):
    def test_a_shops_chat_gets_the_same_rule(self):
        self.ours(TWO_SLOTS_NOW)
        self.set_state(invites=1, facts={"for_client": False})
        message = self.inbound("Tomorrow at 5 pm, I'll let you know")
        outcome, calls, _, _ = self.turn(message, [shop_answer("Noted.")])
        self.assertEqual((calls, self.body(outcome)), ([], rules.line("let_me_know", "en")))
        self.assertEqual(LeadAiAppointment.objects.get().starts_at, None)


class DatedDeferralEvalTests(TestCase):
    def test_defer_with_time_is_code_first_as_live(self):
        bad = eval_answer(
            "Sure. Once you know the time, let me know and I'll reserve a slot for you. Here is our office location.",
            action="tentative", place="office", date="2026-10-13", time="17:00", invited=True, share_location=True,
        )
        run, calls = run_eval("defer-with-time", bad)
        self.assertEqual((calls, run.failures), (0, []))
        self.assertEqual((run.action, run.out_by, run.out), ("tentative", leadai_eval.CODE, rules.line("let_me_know", "en")))


# C. One client per slot, for a tentative too ---------------------------------------------------------


class TakenTentativeTests(SimpleTestCase):
    def tentative(self, said="Tomorrow at 5 pm is better for me", taken=(TUESDAY_5PM,), appointment=None, **extra):
        completion = answer("Noted.", action="tentative", place=extra.pop("place", "office"), date=extra.pop("date", "2026-10-13"), time=extra.pop("time", "17:00"), **extra)
        return engine.taken_tentative(normal(completion), appointment, NOW, (), list(taken), said)

    def test_their_own_time_another_client_has_is_offered_around(self):
        self.assertEqual(self.tentative(), [at(13, 16, 30), at(13, 17, 30)])
        self.assertEqual(self.tentative(place=None), [at(13, 16, 30), at(13, 17, 30)])  # no place is our office
        self.assertEqual(self.tentative(time="17:10", said="Tomorrow 5:10 pm"), [at(13, 16, 30), at(13, 17, 30)])

    def test_not_otherwise(self):
        self.assertEqual(self.tentative(taken=()), [])
        self.assertEqual(self.tentative(taken=(at(13, 18, 0),)), [])  # free
        self.assertEqual(self.tentative(said="Tomorrow I will come"), [])  # a time they did not name
        self.assertEqual(self.tentative(place="customer_property"), [])
        self.assertEqual(self.tentative(segment="other"), [])
        walk_in = self.tentative(date="2026-10-12", time="14:20", said="I'm outside your office now, 2:20", taken=(at(12, 14, 30),))
        self.assertEqual(walk_in, [])
        none = engine.taken_tentative(normal(answer("Sure.")), None, NOW, (), [TUESDAY_5PM], "Tomorrow at 5 pm")
        self.assertEqual(none, [])

    def test_a_move_never_offers_the_slot_it_leaves(self):
        mine = LeadAiAppointment(status="confirmed", starts_at=at(13, 16, 30))
        self.assertEqual(self.tentative(appointment=mine), [at(13, 16, 0), at(13, 17, 30)])

    def test_the_reply_names_the_starts(self):
        starts = [at(13, 16, 30), at(13, 17, 30)]
        self.assertTrue(engine.offers_starts("Sorry, 5 PM is taken. Would 4:30 PM or 5:30 PM work?", starts))
        self.assertTrue(engine.offers_starts("هل يناسبك 4:30 مساءً أو 5:30 مساءً؟", starts))
        self.assertFalse(engine.offers_starts("Would 11 AM or 5:30 PM work?", starts))
        self.assertFalse(engine.offers_starts("", starts))
        self.assertFalse(engine.offers_starts("Would 4:30 PM work?", []))


class TakenAskModelTests(SimpleTestCase):
    def ask(self, *completions, taken=(TUESDAY_5PM,), said="Tomorrow at 5 pm is better for me"):
        codes, alternatives, calls = [], [], []

        def model(messages, schema_, **kwargs):
            calls.append(messages)
            return completions[min(len(calls) - 1, len(completions) - 1)]

        with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
            out, when, _, rejected, invalid = engine.ask_model(
                prompt.SYSTEM, "context", None, NOW, (), codes=codes, taken=list(taken), alternatives=alternatives, said=said
            )
        return out, when, rejected, invalid, codes, alternatives, len(calls)

    def test_a_tentative_at_a_taken_time_is_code_offered_with_no_second_call(self):
        out, when, rejected, invalid, codes, alternatives, calls = self.ask(answer("Tomorrow 5 PM is taken, would 11 AM work?", action="tentative", date="2026-10-13", time="17:00"))
        self.assertEqual((when, rejected, invalid, calls), (None, "", False, 1))
        self.assertEqual((out["slot_taken"], codes, alternatives), (True, ["taken"], [at(13, 16, 30), at(13, 17, 30)]))

    def test_a_correction_that_offers_other_times_is_code_offered(self):
        confirm = answer("", action="confirm", place="office", date="2026-10-13", time="17:00")
        out, when, _, invalid, codes, _, calls = self.ask(confirm, answer("Sorry, that is taken. Would 11 AM or 6 PM work?"))
        self.assertEqual((when, invalid, calls, codes, out.get("slot_taken")), (None, False, 2, ["taken"], True))
        out, _, _, _, _, _, _ = self.ask(confirm, answer("Sorry, that is taken. Would 4:30 PM or 5:30 PM work?"))
        self.assertNotIn("slot_taken", out)  # the right two: the model's words go
        out, _, _, _, codes, _, _ = self.ask(confirm, answer("Sorry.", action="tentative", place="office", date="2026-10-13", time="17:00"))
        self.assertEqual((out["slot_taken"], codes), (True, ["taken", "taken"]))

    def test_a_correction_after_another_refusal_is_left_alone(self):
        sunday = answer("", action="confirm", place="office", date="2026-10-18", time="17:00")
        out, _, _, invalid, codes, _, _ = self.ask(sunday, answer("We are closed on Sunday. Would Monday at 11 AM work?"), said="Sunday 5 pm")
        self.assertEqual((invalid, codes), (False, ["sunday"]))
        self.assertNotIn("slot_taken", out)


class TakenTurnTests(ShopsBase):
    def other_visit(self, start=TUESDAY_5PM, status="confirmed"):
        contact = Contact.objects.create(wa_id="971509992222")
        other = Conversation.objects.create(number=self.number, contact=contact)
        return LeadAiAppointment.objects.create(conversation=other, status=status, place="office", starts_at=start)

    def test_a_tentative_at_another_clients_time_gets_the_two_nearest_free_from_code(self):
        self.other_visit()
        message = self.inbound("Tomorrow at 5 pm is better for me")
        wrong = shop_answer(
            "Tomorrow at 5 PM is taken. I can hold a slot for you tomorrow at 11:00 AM or 5:30 PM — which is better?",
            action="tentative", date="2026-10-13", time="17:00", words="Tomorrow at 5 pm",
        )
        outcome, calls, _, _ = self.turn(message, [wrong])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), TAKEN_LINE)
        mine = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual((mine.status, mine.starts_at, mine.note), ("tentative", None, "Tomorrow at 5 pm"))
        actions = self.actions(message)
        self.assertEqual((actions["fallback"], actions["codes"]), ("slot_taken", ["taken"]))
        self.assertNotIn("upgraded", actions)

    def test_a_tentative_held_by_another_chat_counts_too(self):
        self.other_visit(status="tentative")
        outcome, _, _, _ = self.turn(self.inbound("Tomorrow at 5 pm"), [shop_answer("Noted.", action="tentative", date="2026-10-13", time="17:00")])
        self.assertEqual(self.body(outcome), TAKEN_LINE)


class TakenGeneralTurnTests(GeneralBase):
    def test_every_playbook_and_a_wrong_correction_too(self):
        contact = Contact.objects.create(wa_id="971509993333")
        other = Conversation.objects.create(number=self.number, contact=contact)
        LeadAiAppointment.objects.create(conversation=other, status="confirmed", place="office", starts_at=TUESDAY_5PM)
        message = self.inbound("Tomorrow at 5 pm")
        confirm = answer(action="confirm", place="office", date="2026-10-13", time="17:00")
        outcome, calls, crm_delay, _ = self.turn(message, [confirm, answer("Sorry, 5 PM is taken. Would 11 AM or 6 PM work?")])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.body(outcome), TAKEN_LINE)
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation).exists())
        crm_delay.assert_not_called()


class TakenEvalTests(TestCase):
    def test_shops_taken_passes_with_the_answers_the_model_gave(self):
        for completion in (
            eval_answer(
                "Tomorrow at 5 PM is booked by another client. I can offer you 11:00 AM or 4:30 PM tomorrow instead. Which works better for you?",
                action="tentative", date="2026-10-13", time="17:00",
            ),
            eval_answer(
                "Our office is closed on Sunday. Tomorrow at 5:00 PM is booked by another client already. I can hold a slot for you on Tuesday at 11:00 AM or 5:00 PM — which is better?",
                action="tentative", date="2026-10-13", time="17:00", share_location=True,
            ),
        ):
            with self.subTest(reply=completion.data["reply"][:40]):
                run, calls = run_eval("shops-taken", completion)
                self.assertEqual((calls, run.failures, run.out), (1, [], TAKEN_LINE))

    def test_a_confirm_corrected_with_other_times_passes_too(self):
        confirm = eval_answer("", action="confirm", place="office", date="2026-10-13", time="17:00")
        run, calls = run_eval("shops-taken", confirm, eval_answer("Sorry, that one is taken. Would 11:00 AM or 6:00 PM work?"))
        self.assertEqual((calls, run.failures, run.out), (2, [], TAKEN_LINE))


# D. The licence before the invitation (shops) ---------------------------------------------------------


class LicenceFirstTests(SimpleTestCase):
    def settle(self, reply=VAPE_INVITE, known=VAPE_KNOWN, earlier=ASKED_BUSINESS, said="I have vape 💨 business.", playbook=lane.IC_SHOPS, **extra):
        facts = extra.pop("facts", {"business_activity": "vape"})
        out = normal(shop_answer(reply, invited=extra.pop("invited", True), facts=facts, **extra), True)
        return engine.settle(out, earlier, [said], extra.get("invites", 0), playbook=playbook, address_sent=ADDRESS, now=NOW, facts=known)

    def test_the_35283_reply_asks_the_licence_and_keeps_its_reaction_and_match(self):
        out = self.settle()
        self.assertEqual((out["reply"], out["invited_to_meeting"], out["trimmed"]), (VAPE_LICENCE, False, ["licence_first"]))
        # The business need not be recorded when they are answering our question about it.
        self.assertEqual(self.settle(facts={})["reply"], VAPE_LICENCE)
        # An invitation the model did not flag, or an open "when", is caught the same way.
        self.assertEqual(self.settle(reply="A vape shop, got it. When would you like to come and see the shops?", invited=False)["reply"], f"A vape shop, got it. {ASK_LICENCE}")

    def test_the_line_in_every_language(self):
        self.assertEqual(ASK_LICENCE, "Do you have a DED or Trakhees licence, or will you open a new one?")
        for language in ("ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language=language):
                self.assertNotEqual(rules.line("ask_licence", language), ASK_LICENCE)
                self.assertIn("DED", rules.line("ask_licence", language))

    def test_not_when_the_licence_is_known_or_they_ask_to_come(self):
        cases = {
            "licence known": {"known": {**VAPE_KNOWN, "licence_kind": "ded"}},
            "licence yes": {"facts": {"business_activity": "vape", "trade_licence": "yes"}},
            "who it is for unknown": {"known": {**VAPE_KNOWN, "for_client": None}},
            "a broker": {"known": {**VAPE_KNOWN, "for_client": True}},
            "no size or budget": {"known": {"for_client": False}},
            "size only from this answer, business unknown": {"known": {"for_client": False}, "facts": {"size_sqft": 450}},
            "a question": {"said": "I have vape business. Can I see the shops?"},
            "asks to see": {"said": "Vape business, I want to see the shops"},
            "names a day": {"said": "Vape business, tomorrow"},
            "names an hour": {"said": "Vape business, 5 pm"},
            "asks for the location": {"said": "Vape business, send location"},
            "our last asked the licence": {"earlier": [("assistant", "Got it. Do you have a DED or Trakhees licence?")]},
            "slots on the table": {"earlier": [("assistant", TWO_SLOTS_NOW)]},
            "no invitation": {"reply": "A vape shop, got it. When do you want to open?", "invited": False},
            "a general chat": {"playbook": lane.GENERAL},
            "a handover": {"handover": "customer_asked_human"},
        }
        for name, extra in cases.items():
            with self.subTest(name):
                out = self.settle(**extra)
                self.assertNotIn("licence_first", out.get("trimmed", []))
        agreed = engine.settle(normal(shop_answer(VAPE_INVITE, invited=True), True), ASKED_BUSINESS, ["I have vape business."], 0, agreed=True, playbook=lane.IC_SHOPS, facts=VAPE_KNOWN)
        self.assertEqual(agreed["reply"], VAPE_INVITE)


class LicenceFirstTurnTests(ShopsBase):
    def test_the_first_real_chats_vape_reply_asks_the_licence(self):
        self.set_state(facts=dict(VAPE_KNOWN))
        self.ours(f"Here is our office:\n{ADDRESS}\nWhat business will the shop be for?", minutes_ago=5)
        message = self.inbound("I have vape 💨 business.")
        outcome, calls, _, _ = self.turn(message, [shop_answer(VAPE_INVITE, invited=True, facts={"business_activity": "vape"})])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), VAPE_LICENCE)
        self.assertEqual(self.actions(message)["trimmed"], ["licence_first"])
        self.assertFalse(self.actions(message)["invited_to_meeting"])
        self.assertEqual(self.state().invites, 0)


class LicenceFirstEvalTests(TestCase):
    def test_shops_35283_passes_with_the_answers_the_model_gave(self):
        for completion in (
            eval_answer(VAPE_INVITE, invited=True, facts={"business_activity": "vape"}),
            eval_answer(
                "A vape shop, got it. For your size and budget, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. "
                "I can hold a viewing slot for you today at 2:30 PM or 3:00 PM at our office. Which is better?",
            ),
        ):
            with self.subTest(reply=completion.data["reply"][60:100]):
                run, _ = run_eval("shops-35283", completion)
                self.assertEqual(run.failures, [])
                self.assertTrue(run.out.endswith(ASK_LICENCE))
                self.assertFalse(run.answer["invited_to_meeting"])


# E. Spam (shops) ----------------------------------------------------------------------------------------


class SpamRuleTests(SimpleTestCase):
    def test_plain_chain_messages_and_scams(self):
        for text in (
            SPAM,
            "Earn money daily from home! Join our crypto group now, forward to 10 friends",
            "Forex trading signals group, join now",
            "Congratulations! You have won a prize, click here to claim your reward",
            "Join this group for daily profit chat.whatsapp.com/AbCdEf",
            "Forward this message to 5 groups and get free money",
        ):
            with self.subTest(text=text[:40]):
                self.assertTrue(rules.looks_like_spam(text))

    def test_a_customers_own_words_are_never_spam(self):
        for text in (
            "I want a shop for my crypto trading platform",
            "Please forward this to your agent",
            "I want to earn money daily with a good shop",
            "I sell bitcoin mining machines, I need a shop",
            "Join us? I am a broker",
            "I have a forex office, I need 600 sq ft",
            "You have won my trust, I will come tomorrow",
            "",
        ):
            with self.subTest(text=text[:40]):
                self.assertFalse(rules.looks_like_spam(text))

    def test_the_rule_and_its_answer(self):
        self.assertEqual(engine.shops_rule(SPAM), engine.SPAM_RULE)
        self.assertEqual(engine.shops_rule(SPAM, followup_open=True), engine.SPAM_RULE)  # whatever came before
        for flags in ({"quiet": True}, {"single": False}, {"tapped": True}):
            with self.subTest(**flags):
                self.assertEqual(engine.shops_rule(SPAM, **flags), "")
        out = engine.shops_answer(engine.SPAM_RULE, "en", SPAM)
        self.assertEqual((out["opt_out"], out["send"], out["reply"], out["rule"], out.get("converted")), ("spam", False, "", "spam", None))


class SpamGeneralTests(GeneralBase):
    def test_a_general_chat_never_has_the_spam_rule(self):
        _, calls, _, _ = self.turn(self.inbound(SPAM), [answer("", send=False)])
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.state().stopped_at)
        self.assertEqual(LeadAiTurn.objects.get().actions.get("rule"), None)


class SpamEvalTests(TestCase):
    def test_shops_spam_is_code_first_as_live(self):
        run, calls = run_eval("shops-spam", eval_answer("Thanks for your message. Is the shop for yourself, or are you checking for a client?"))
        self.assertEqual((calls, run.out, run.failures, run.answer["opt_out"]), (0, "", [], "spam"))
        self.assertEqual(leadai_eval.code_first(scenario("shops-spam"))["rule"], engine.SPAM_RULE)


class ScenariosTests(SimpleTestCase):
    def test_the_scenarios_say_what_the_guards_do(self):
        defer = scenario("defer-with-time")
        self.assertEqual(defer.words, leadai_eval.CODE)
        self.assertEqual(shops.slot_taken("en", [at(13, 16, 30), at(13, 17, 30)], NOW), TAKEN_LINE)
