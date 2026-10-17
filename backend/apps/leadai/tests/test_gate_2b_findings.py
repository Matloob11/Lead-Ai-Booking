"""The review of batch 2b's gate guards (findings F1-F9), each reproduced by a test that fails on
the guards as they were and passes with the fix, and mirrored by leadai_eval:

- F1. a walk-in the booking check accepts ("I'm here", "Reached", "وصلت") is the customer's own
  time to the shops guard too (engine.their_time reads engine._walk_in);
- F2. an hour said in words, as a half or from now ("Tomorrow at five", "half past 5", "kal
  saade 5 baje", "الساعة الخامسة مساءً", "in 1 hour") is theirs (hours.said_times,
  hours.hours_ahead); a different one than the model booked starts the two slots
  (engine.named_hour, shops.yes_slots ``at``);
- F3. asked for ("Please confirm my visit tomorrow at 5", "أكد لي الموعد"), the booking is sent
  again (engine.asks_for_booking); said again, nothing changes (engine._said_again);
- F4. product names and a word or two in English letters ("Type 2", "نعم DED", "Location?") keep
  an Arabic, Urdu or Hindi chat in its script (script.customer_script);
- F5. a tentative in the customer's own words ("DED hai, shaam ko aaunga", "maybe 7") is never
  taken for the model's invitation (engine.wants_to_come);
- F6. our request for the licence's copy is a request: an "ok" to it is answered, and a silence
  after it nudged (engine._pending_question, nudges.asks_or_invites);
- F7. a pick from our two slots after a message of ours in between, and a yes to our one bare-hour
  offer ("Does 5 work for you tomorrow?"), are theirs; the same two slots asked about again go in
  other words (hours.offered_starts, shop_flow.slots_text ``before``);
- F8. the location asked for with an unasked confirm goes with the two slots (engine.asked_location);
- F9. the customer's own name in the reply ("Hi محمد") says nothing of its script
  (script.has_script ``name``).

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.campaigns.models import CampaignRecipient
from apps.inbox.models import Message
from apps.leadai import followups
from apps.leadai.assistant import engine, hours, nudges, prompt, rules, schema, script, shop_flow, shops
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import DEFAULT_OFFICE_ADDRESS, LeadAiAppointment
from apps.leadai.tests.test_assistant import NOW, TUESDAY_5PM, answer
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_eval_command import booked
from apps.leadai.tests.test_follow_ups import NudgeBase
from apps.leadai.tests.test_follow_ups import at as follow_at
from apps.leadai.tests.test_gate_2b_guards import KNOWN, NUDGE, run_eval, scenario
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, at, shop_answer

ADDRESS = DEFAULT_OFFICE_ADDRESS
WHEN_TO_VISIT = "When would you like to visit our office to see the shops?"
EVENING_SLOTS = "I can hold a slot for you today at 5:00 PM or 7:00 PM — which is better?"
SHOPS_CONFIRMED = "Your viewing is confirmed ✅"
GENERAL_CONFIRMED = "Perfect, Ahmed. Your meeting is confirmed."
DED = {"licence_kind": "ded", "trade_licence": "yes"}
AR_CHAT = [
    ("customer", "مرحبا، أحتاج محل لبقالة صغيرة"),
    ("assistant", "أهلاً بك. لدينا ثلاثة أنواع من المحلات: Type 1 و Type 2 و Type 3. أي نوع يناسبك؟"),
]
ARABIC_REPLY = "ممتاز، محلات Type 2 مساحتها مناسبة للبقالة. هل تود زيارة مكتبنا لمعاينتها؟"
ENGLISH_REPLY = "Great, Type 2 shops suit a grocery well. Would you like to visit our office to see them?"


def theirs(start, said, our_last="", ours="", words="", now=NOW):
    return engine.their_time(start, said=said, words=words, our_last=our_last, ours=ours, now=now)


def asked_when(item_id="shops-licence-ask", **changes):
    """A shops scenario whose last line of ours asks when they would like to come, nothing booked."""
    base = scenario(item_id)
    return replace(base, chat=[*base.chat, ("assistant", WHEN_TO_VISIT)], appointment=None, **changes)


# F1. A walk-in -----------------------------------------------------------------------------------------


class WalkInTests(SimpleTestCase):
    WALKING_IN = (
        ("I'm here", 14, 0), ("Reached", 14, 0), ("Almost there", 14, 0), ("I am in front of your office", 14, 0),
        ("I'll be there in 20 minutes", 14, 30), ("Pahunch gaya", 14, 0), ("وصلت", 14, 0), ("I'm outside your office now", 14, 0),
    )

    def test_every_walk_in_the_booking_check_accepts_is_their_own_time(self):
        for said, hour, minute in self.WALKING_IN:
            with self.subTest(said):
                start = at(12, hour, minute)
                self.assertTrue(engine._walk_in(start, said, NOW))  # check_proposal's reading
                self.assertTrue(theirs(start, said, our_last=WHEN_TO_VISIT))
                out = schema.normalize(shop_answer("", action="confirm", place="office", date="2026-10-12", time=f"{hour:02d}:{minute:02d}").data, shops=True)
                self.assertFalse(engine.unasked_confirm(out, start, None, NOW, said=said, our_last=WHEN_TO_VISIT))

    def test_not_an_hour_from_now(self):
        # Coming tomorrow at this hour is no walk-in, and no hour was named for it.
        self.assertFalse(theirs(at(13, 14), "I'm coming tomorrow", our_last=WHEN_TO_VISIT))


class WalkInEvalTests(TestCase):
    def test_a_walk_in_to_a_shops_chat_with_nothing_booked_is_booked_now(self):
        for said in ("I'm here", "Reached", "وصلت", "Almost there"):
            with self.subTest(said):
                run, calls = run_eval(replace(scenario("shops-licence-ask"), new=[said]), booked("2026-10-12", "14:00", hot_lead=True))
                self.assertEqual((len(calls), run.when, run.out_by), (1, at(12, 14), leadai_eval.CODE))
                # The build pack's confirmation, in the letters they typed ("وصلت": Arabic).
                self.assertTrue(run.out.startswith((SHOPS_CONFIRMED, "تم تأكيد موعد المعاينة ✅")), run.out)
                self.assertNotIn("unasked", run.answer)

    def test_without_the_walk_in_reading_the_customer_at_the_door_got_two_slots(self):
        with patch("apps.leadai.assistant.engine._walk_in", return_value=False):
            run, _ = run_eval(replace(scenario("shops-licence-ask"), new=["I'm here"]), booked("2026-10-12", "14:00", hot_lead=True))
        self.assertIsNone(run.when)
        self.assertIn("which is better?", run.out)


# F2. An hour in words, as a half, or from now ------------------------------------------------------------


class HourInWordsTests(SimpleTestCase):
    CASES = (
        ("Tomorrow at five works for me", at(13, 17)),
        ("Today half past 5", at(12, 17, 30)),
        ("kal saade 5 baje aaunga", at(13, 17, 30)),
        ("بكرة الساعة الخامسة مساءً", at(13, 17)),
        ("कल शाम पाँच बजे आऊँगा", at(13, 17)),
        ("I can come in 1 hour", at(12, 15)),
        ("aadhe ghante mein aata hoon", at(12, 14, 30)),
        ("پانچ بجے آؤں گا", at(12, 17)),
    )

    def test_their_own_hour_in_any_form_stands(self):
        for said, start in self.CASES:
            with self.subTest(said):
                self.assertTrue(theirs(start, said, our_last=WHEN_TO_VISIT))
        # An answer ago, in words; a bare number back then is no hour ("we are 2 partners").
        self.assertTrue(theirs(at(12, 17), "Yes", words="I can come at five Yes", our_last=NUDGE))
        self.assertFalse(theirs(at(12, 14), "Yes", words="We are 2 partners Yes", our_last=NUDGE))

    def test_the_readers(self):
        times = hours.said_times
        self.assertEqual(times("Tomorrow at five works for me"), {dt.time(17, 0)})
        self.assertEqual(times("Today half past 5"), {dt.time(17, 30)})
        self.assertEqual(times("kal saade 5 baje aaunga"), {dt.time(17, 30)})
        self.assertEqual(times("بكرة الساعة الخامسة مساءً"), {dt.time(17, 0)})
        self.assertEqual(times("paune 6 baje"), {dt.time(17, 45)})
        self.assertEqual(times("٥ ونص"), {dt.time(17, 30)})
        self.assertEqual(times("at noon"), {dt.time(12, 0)})
        for text in ("Yes, book me for this evening", "Yes, Type 1 please", "I need 2 shops", "Around 450 sq ft", "AED 12,000 a year",
                     "1 to 4 cheques", "only 5 minutes away", "the later one", "One more question", "Do you have parking?", "12 October"):
            with self.subTest(text):
                self.assertEqual(times(text), set())
                self.assertFalse(hours.marks_hour(text))
        self.assertEqual(hours.hours_ahead("I can come in 1 hour"), [dt.timedelta(hours=1)])
        self.assertEqual(hours.hours_ahead("بعد نص ساعة"), [dt.timedelta(minutes=30)])
        # An hour said in a way not read exactly ("8 baje", "at 9"): the model's reading stands.
        self.assertEqual(times("8 baje"), set())
        self.assertTrue(hours.marks_hour("8 baje"))
        self.assertTrue(theirs(at(12, 19, 30), "8 baje", our_last=WHEN_TO_VISIT))

    def test_another_hour_than_the_one_they_named_starts_the_two_slots_from_theirs(self):
        self.assertFalse(theirs(at(13, 16, 30), "Tomorrow at 4 works"))
        out = schema.normalize(shop_answer("", action="confirm", place="office", date="2026-10-13", time="16:30").data, shops=True)
        self.assertTrue(engine.unasked_confirm(out, at(13, 16, 30), None, NOW, said="Tomorrow at 4 works", our_last=WHEN_TO_VISIT))
        self.assertEqual(out["unasked"]["slots"], [at(13, 16), at(13, 18)])
        self.assertEqual(engine.named_hour("Tomorrow at 4 works", NOW), dt.time(16, 0))
        self.assertIsNone(engine.named_hour("between 5 and 6", NOW))  # two hours: the usual pair
        self.assertEqual(shops.yes_slots("Yes", "", NOW, at=dt.time(16, 0)), [at(12, 16), at(12, 18)])


class HourInWordsEvalTests(TestCase):
    def test_a_confirm_of_their_own_hour_in_words_is_booked(self):
        cases = (
            ("Tomorrow at five works for me", "2026-10-13", "17:00", "en"),
            ("Today half past 5", "2026-10-12", "17:30", "en"),
            ("kal saade 5 baje aaunga", "2026-10-13", "17:30", "ur_latin"),
            ("بكرة الساعة الخامسة مساءً", "2026-10-13", "17:00", "ar"),
            ("I can come in 1 hour", "2026-10-12", "15:00", "en"),
        )
        for said, day, clock, language in cases:
            with self.subTest(said):
                run, calls = run_eval(asked_when(new=[said]), booked(day, clock, language=language))
                self.assertEqual(len(calls), 1)
                self.assertEqual(run.when, dt.datetime.combine(hours.parse_date(day), hours.parse_time(clock), tzinfo=hours.DUBAI))
                self.assertNotIn("unasked", run.answer)
                self.assertEqual(run.out_by, leadai_eval.CODE)

    def test_the_gates_case_still_gets_the_evening_slots(self):
        run, _ = run_eval("shops-nudge-yes", eval_answer("", action="confirm", place="office", date="2026-10-12", time="16:00"))
        self.assertEqual((run.out, run.when, run.failures), (EVENING_SLOTS, None, []))


# F3. The booking asked for again ---------------------------------------------------------------------------


class AskedForTheBookingTests(SimpleTestCase):
    def test_what_asks_for_it(self):
        for said in (
            "Please confirm my visit tomorrow at 5", "Kindly confirm my appointment for tomorrow 5 pm",
            "Send me the confirmation again for tomorrow 5pm", "We are still on for tomorrow 5pm right", "kal 5 baje confirm hai na",
            "Please resend the booking details, tomorrow 5 pm", "أكد لي الموعد بكرة الساعة 5", "Is it still at 5?",
            "See you tomorrow at 5, send me the location", "How do I reach there? See you at 5",
        ):
            with self.subTest(said):
                self.assertTrue(engine.asks_for_booking(said))
        for said in ("Great, see you tomorrow at 5", "ان شاء الله", "Ok thanks, all right", "Thanks, see you then", "Confirmed, see you tomorrow"):
            with self.subTest(said):
                self.assertFalse(engine.asks_for_booking(said))

    def test_only_a_restatement_changes_nothing(self):
        mine = LeadAiAppointment(status="confirmed", starts_at=TUESDAY_5PM)
        confirm = schema.normalize(answer("", action="confirm", place="office", date="2026-10-13", time="17:00").data)
        self.assertTrue(engine._said_again(confirm, TUESDAY_5PM, mine, "Great, see you tomorrow at 5"))
        self.assertFalse(engine._said_again(confirm, TUESDAY_5PM, mine, "Please confirm my visit tomorrow at 5"))


class AskedForTheBookingEvalTests(TestCase):
    def test_the_confirmation_goes_again_when_they_ask_for_it(self):
        for said, opening in (
            ("Please confirm my visit tomorrow at 5", GENERAL_CONFIRMED),
            ("Send me the confirmation again for tomorrow 5pm", GENERAL_CONFIRMED),
            ("We are still on for tomorrow 5pm right", GENERAL_CONFIRMED),
            ("kal 5 baje confirm hai na", "Perfect, Ahmed."),
            ("أكد لي الموعد بكرة الساعة 5", "ممتاز Ahmed. تم تأكيد موعدك."),
        ):
            with self.subTest(said):
                # As the prompt asks: a confirm of the booked time, its reply left empty for the system's message.
                run, _ = run_eval(replace(scenario("booked-same-time"), new=[said]), booked("2026-10-13", "17:00"))
                self.assertEqual(run.out_by, leadai_eval.CODE)
                self.assertTrue(run.out.startswith(opening), run.out)

    def test_a_restatement_still_sends_nothing(self):
        run, _ = run_eval("booked-same-time", booked("2026-10-13", "17:00"))
        self.assertEqual((run.failures, run.action, run.out), ([], "none", ""))


class AskedForTheBookingTurnTests(GeneralBase):
    def test_please_confirm_gets_the_booking_and_changes_nothing(self):
        LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", place="office", starts_at=TUESDAY_5PM,
            reminder_due_at=TUESDAY_5PM - dt.timedelta(minutes=30),
        )
        self.inbound("Tomorrow 5pm", seconds_ago=600)
        self.ours("Perfect, Ahmed. Your meeting is confirmed.\nDate: Tuesday 13 October\nTime: 5:00 PM", minutes_ago=9)
        message = self.inbound("Please confirm my visit tomorrow at 5")
        outcome, calls, crm_delay, _ = self.turn(message, [answer("", action="confirm", place="office", date="2026-10-13", time="17:00")])
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.body(outcome).startswith(GENERAL_CONFIRMED), self.body(outcome))
        crm_delay.assert_not_called()
        self.assertEqual(self.actions(message)["effective"], "reconfirm")
        self.assertEqual(LeadAiAppointment.objects.get().starts_at, TUESDAY_5PM)


# F4. The script of an Arabic, Urdu or Hindi chat ----------------------------------------------------------


class ScriptOfAShortLatinMessageTests(SimpleTestCase):
    def test_product_names_and_a_word_of_english_letters_decide_nothing(self):
        arabic, urdu, hindi = "مرحبا، أحتاج محل لبقالة صغيرة", "مجھے انٹرنیشنل سٹی میں دکان چاہیے۔", "मुझे इंटरनेशनल सिटी में दुकान चाहिए।"
        for latest in ("Type 2", "أريد Type 2", "نعم DED", "Location?", "DED licence", "Trakhees", "International City", "PDF ok"):
            with self.subTest(latest):
                self.assertEqual(script.customer_script([arabic, latest]), script.ARABIC)
        self.assertEqual(script.customer_script([urdu, "Type 1"]), script.URDU)
        self.assertEqual(script.customer_script([hindi, "Type 3"]), script.DEVANAGARI)
        self.assertEqual(script.customer_script(["Type 2"]), "")  # nothing else typed: nothing checked
        # English letters still decide when they say something.
        self.assertEqual(script.customer_script([arabic, "English please"]), script.LATIN)
        self.assertEqual(script.customer_script([arabic, "Can you send me the location please"]), script.LATIN)
        self.assertEqual(script.customer_script(["Tomorrow 5pm", "ان شاء الله"]), script.LATIN)


class ScriptOfAShortLatinMessageEvalTests(TestCase):
    def test_an_arabic_chat_keeps_its_arabic_reply_and_lines(self):
        for item_id in ("lang-arabic-yes", "shops-licence-ask"):
            for new in (["Type 2"], ["أريد Type 2"], ["نعم DED"], ["Location?"]):
                with self.subTest(item_id=item_id, new=new):
                    item = replace(scenario(item_id), chat=AR_CHAT, new=new, language_so_far="ar", appointment=None, invites=0)
                    run, calls = run_eval(item, eval_answer(ARABIC_REPLY, language="ar"), eval_answer(ENGLISH_REPLY))
                    self.assertEqual((len(calls), run.customer_script, run.line_language), (1, script.ARABIC, "ar"))
                    self.assertNotIn("script_fix", run.answer)


class ScriptOfAShortLatinMessageTurnTests(ShopsBase):
    def test_type_2_in_an_arabic_chat_is_answered_in_arabic_and_the_chat_stays_arabic(self):
        self.set_state(language="ar")
        self.inbound("مرحبا، أحتاج محل لبقالة صغيرة", seconds_ago=900)
        self.ours("أهلاً بك. لدينا ثلاثة أنواع من المحلات: Type 1 و Type 2 و Type 3. أي نوع يناسبك؟", minutes_ago=10)
        message = self.inbound("Type 2")
        outcome, calls, _, _ = self.turn(message, [shop_answer(ARABIC_REPLY, language="ar"), shop_answer(ENGLISH_REPLY)])
        body = self.body(outcome)
        # One call: the Arabic reply goes (its open invitation as two free slots, in Arabic: settle).
        self.assertEqual(len(calls), 1)
        self.assertTrue(body.startswith("ممتاز، محلات Type 2"), body)
        self.assertNotIn("script_fix", self.actions(message))
        self.assertEqual(self.state().language, "ar")


# F5. A tentative in their own words -------------------------------------------------------------------------


class WantsToComeTests(SimpleTestCase):
    def test_their_words_for_coming(self):
        for said in (
            "DED hai, shaam ko aaunga", "Yes DED. Evening works for me", "I have a DED licence, maybe 7", "نعم DED، ممكن أمر عليكم بعد الدوام",
            "DED, I'll drop by after work", "DED hai, kal aa jaunga", "हाँ DED है, शाम को आऊँगा", "DED licence, can I come tomorrow",
        ):
            with self.subTest(said):
                self.assertTrue(engine.wants_to_come(said, NOW))
        for said in ("Yes I have a DED licence", "Good morning, yes I have a DED licence", "صباح الخير، نعم عندي رخصة DED", "Trakhees"):
            with self.subTest(said):
                self.assertFalse(engine.wants_to_come(said, NOW))


class TheirTentativeEvalTests(TestCase):
    CASES = (
        ("DED hai, shaam ko aaunga", "Zabardast! Main aap ke liye aaj 5:00 PM ya 7:00 PM ka slot rakh sakta hoon — kaunsa behtar rahega?", None, None, "ur_latin"),
        ("Yes DED. Evening works for me", "Great! I can hold a slot for you today at 5:00 PM or 7:00 PM — which is better?", None, None, "en"),
        ("I have a DED licence, maybe 7", "Great, I have pencilled you in for today at 7 PM. Shall I confirm it?", "2026-10-12", "19:00", "en"),
        ("نعم DED، ممكن أمر عليكم بعد الدوام", "ممتاز! يمكنني حجز موعد لك اليوم الساعة 5:00 PM أو 7:00 PM — أيهما أنسب لك؟", None, None, "ar"),
    )

    def test_their_tentative_and_the_models_words_stay(self):
        for said, reply, day, clock, language in self.CASES:
            with self.subTest(said):
                completion = eval_answer(reply, action="tentative", place="office", date=day, time=clock, words=said, invited=True, facts=DED, language=language)
                run, _ = run_eval(replace(scenario("shops-licence-ask"), new=[said]), completion)
                self.assertEqual((run.action, run.answer["appointment"]["date"], run.answer["appointment"]["time"]), ("tentative", day, clock))
                self.assertNotIn("shop_step", run.answer)
                self.assertEqual(run.out_by, leadai_eval.MODEL)

    def test_the_gates_case_still_gets_the_licence_request(self):
        completion = eval_answer("I can hold a slot for you today at 2:30 PM or 3:00 PM. Which is better?", action="tentative", invited=True, facts=DED)
        run, _ = run_eval("shops-licence-ask", completion)
        self.assertEqual((run.failures, run.answer["shop_step"]["kind"], run.action), ([], shop_flow.LICENCE_ASK, "none"))


class TheirTentativeTurnTests(ShopsBase):
    def test_shaam_ko_aaunga_keeps_the_tentative_and_the_reply(self):
        self.set_state(facts=dict(KNOWN))
        self.ours(
            "For a mobile shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees licence, "
            "or will you open a new one?",
            minutes_ago=5,
        )
        message = self.inbound("DED hai, shaam ko aaunga")
        reply = "Zabardast! Main aap ke liye aaj 5:00 PM ya 7:00 PM ka slot rakh sakta hoon — kaunsa behtar rahega?"
        completion = shop_answer(reply, action="tentative", place="office", words="DED hai, shaam ko aaunga", invited=True, facts=DED, language="ur_latin")
        outcome, calls, crm_delay, _ = self.turn(message, [completion])
        self.assertEqual((len(calls), self.body(outcome)), (1, reply))
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.note), ("tentative", "DED hai, shaam ko aaunga"))
        crm_delay.assert_called_once()
        self.assertIsNone(self.state().licence_asked_at)


# F6. The licence request is a request ---------------------------------------------------------------------


class LicenceRequestIsARequestTests(ShopsBase):
    def test_ok_to_the_licence_request_is_answered(self):
        self.set_state(facts={**KNOWN, **DED}, licence_asked_at=NOW - dt.timedelta(minutes=5))
        self.ours(rules.line("licence_copy", "en"), minutes_ago=5, shop_step=shop_flow.LICENCE_ASK)
        reply = "Great! Meanwhile, I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?"
        outcome, calls, _, _ = self.turn(self.inbound("ok"), [shop_answer(reply, invited=True)])
        self.assertEqual((len(calls), self.body(outcome)), (1, reply))
        self.assertEqual(self.state().invites, 1)

    def test_the_eval_asks_the_model_too(self):
        item = replace(scenario("shops-licence-later"), new=["ok"])
        self.assertIsNone(leadai_eval.code_first(item))
        self.assertIsNotNone(leadai_eval.code_first(replace(item, playbook="general")))  # no licence request in a general chat


class LicenceRequestNudgeTests(NudgeBase):
    def test_silence_after_the_licence_request_is_nudged(self):
        Message.objects.filter(pk=self.question.pk).update(
            body=rules.line("licence_copy", "en"), payload={"source": "leadai_ai", "shop_step": shop_flow.LICENCE_ASK}
        )
        self.set_state(licence_asked_at=self.question.created_at)
        self.go(follow_at(12, 15, 1))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])
        result, sent = self.nudge()
        self.assertEqual(result, "sent")
        self.assertTrue(sent.call_args.args[2].endswith("Shall I book you for this evening?"))
        self.assertTrue(nudges.asks_or_invites(rules.line("licence_copy", "en"), "text", shop_flow.LICENCE_ASK))
        self.assertFalse(nudges.asks_or_invites(rules.line("licence_copy", "en")))  # its words alone ask nothing


# F7. What they took from our side -------------------------------------------------------------------------


class TookItFromUsTests(SimpleTestCase):
    def test_a_pick_after_a_message_of_ours_in_between(self):
        location = f"Our office is here:\n{ADDRESS}"
        ours = f"{EVENING_SLOTS} {location}"
        self.assertTrue(theirs(at(12, 17), "Ok the first one", our_last=location, ours=ours))
        self.assertFalse(theirs(at(12, 17), "Yes", our_last=location, ours=ours))  # a plain yes picks neither
        self.assertFalse(theirs(at(12, 18), "Ok the first one", our_last=location, ours=ours))  # not one we offered
        # Our last message offered other times: an older offer is not what they picked.
        tomorrow = "I can hold a slot for you tomorrow at 11:00 AM or 1:00 PM — which is better?"
        self.assertTrue(theirs(at(13, 11), "the first one", our_last=tomorrow, ours=f"{TWO_SLOTS_NOW} {tomorrow}"))
        self.assertFalse(theirs(at(12, 15), "the first one", our_last=tomorrow, ours=f"{TWO_SLOTS_NOW} {tomorrow}"))

    def test_a_yes_to_our_one_bare_hour(self):
        for said, ours in (
            ("Ji", "Kal shaam 5 ka slot book kar doon?"),
            ("Yes", "Does 5 work for you tomorrow?"),
            ("نعم", "هل يناسبك غداً الساعة الخامسة مساءً؟"),
        ):
            with self.subTest(ours):
                self.assertEqual(hours.offered_starts(ours), {dt.time(17, 0)})
                self.assertTrue(theirs(TUESDAY_5PM, said, our_last=ours))
        # Counts, sizes and prices are no offer.
        self.assertEqual(hours.offered_starts(NUDGE), set())
        self.assertEqual(hours.offered_starts("We accept 1 to 4 cheques, and our agent drives you, only 5 minutes away."), set())
        self.assertFalse(theirs(at(13, 14), "Yes", our_last=NUDGE))

    def test_the_same_two_slots_again_go_in_other_words(self):
        slots = [at(12, 15), at(12, 17)]
        self.assertEqual(shop_flow.slots_text("en", slots, NOW), TWO_SLOTS_NOW)
        again = shop_flow.slots_text("en", slots, NOW, before=TWO_SLOTS_NOW)
        self.assertEqual(again, "Which one suits you better: today at 3:00 PM or 5:00 PM?")
        self.assertEqual(shop_flow.slots_text("en", slots, NOW, before=f"{TWO_SLOTS_NOW} {again}"), TWO_SLOTS_NOW)  # both said: as it was
        self.assertEqual(shop_flow.slots_text("ar", slots, NOW, before="شكراً"), shops.slot_offer("ar", slots, NOW))
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                self.assertNotEqual(shops.slot_offer(language, slots, NOW, again=True), shops.slot_offer(language, slots, NOW))


class TookItFromUsEvalTests(TestCase):
    def test_ok_the_first_one_after_the_location_is_booked(self):
        base = scenario("shops-licence-ask")
        chat = [*base.chat, ("assistant", EVENING_SLOTS), ("customer", "Where is your office?"), ("assistant", f"Our office is here:\n{ADDRESS}")]
        run, _ = run_eval(replace(base, chat=chat, new=["Ok the first one"], facts={**base.facts, **DED}, licence_asked=True), booked("2026-10-12", "17:00"))
        self.assertEqual(run.when, at(12, 17))
        self.assertTrue(run.out.startswith(SHOPS_CONFIRMED), run.out)

    def test_a_plain_yes_to_our_two_slots_gets_them_in_other_words(self):
        base = scenario("shops-licence-ask")
        item = replace(base, chat=[*base.chat, ("assistant", TWO_SLOTS_NOW)], new=["Yes"], facts={**base.facts, **DED}, licence_asked=True)
        run, _ = run_eval(item, booked("2026-10-12", "14:30"))
        self.assertEqual((run.when, run.out), (None, "Which one suits you better: today at 3:00 PM or 5:00 PM?"))


# F8. The location asked for with the slots ----------------------------------------------------------------


class LocationWithTheSlotsTests(SimpleTestCase):
    def test_asked_location(self):
        self.assertEqual(engine.asked_location(EVENING_SLOTS, "Yes please, send me the location", ADDRESS), ADDRESS)
        self.assertEqual(engine.asked_location(EVENING_SLOTS, "Yes please, send me the location", ADDRESS, "https://maps.app.goo.gl/x"), "https://maps.app.goo.gl/x")
        self.assertEqual(engine.asked_location(EVENING_SLOTS, "Yes please", ADDRESS), "")
        self.assertEqual(engine.asked_location(f"{EVENING_SLOTS}\n{ADDRESS}", "send me the location", ADDRESS), "")


class LocationWithTheSlotsEvalTests(TestCase):
    def test_the_slots_go_with_the_address(self):
        completion = eval_answer("", action="confirm", place="office", date="2026-10-12", time="18:00", share_location=True)
        run, _ = run_eval(replace(scenario("shops-nudge-yes"), new=["Yes please, send me the location"]), completion)
        self.assertEqual((run.when, run.out), (None, f"{EVENING_SLOTS}\nOur office location: {ADDRESS}"))


class LocationWithTheSlotsTurnTests(ShopsBase):
    def test_yes_send_me_the_location_to_the_nudge(self):
        self.set_state(facts=dict(KNOWN), nudges=1, nudged_at=NOW - dt.timedelta(minutes=55))
        self.inbound("Around 450 sq ft", seconds_ago=3 * 3600)
        self.ours(NUDGE, minutes_ago=55, nudge=1)
        message = self.inbound("Yes please, send me the location")
        confirm = shop_answer("", action="confirm", place="office", date="2026-10-12", time="18:00", share_location=True)
        outcome, _, _, _ = self.turn(message, [confirm])
        self.assertEqual(self.body(outcome), f"{EVENING_SLOTS}\nOur office location: {ADDRESS}")
        self.assertTrue(self.actions(message)["location_appended"])
        self.assertEqual(LeadAiAppointment.objects.get().status, "tentative")


# F9. The customer's own name -------------------------------------------------------------------------------


class OwnNameTests(SimpleTestCase):
    def test_the_name_says_nothing_of_the_replys_script(self):
        reply = "Hi محمد, thanks for your message. What business will the shop be for?"
        self.assertFalse(script.has_script(reply, script.LATIN))
        self.assertTrue(script.has_script(reply, script.LATIN, "محمد علي"))
        self.assertFalse(script.has_script("Thank you یاسر", script.URDU, "یاسر"))  # an English reply to an Urdu one
        # An Arabic phrase in an English reply is still asked again (eval lang-inshallah-english).
        self.assertFalse(script.has_script("See you tomorrow at 5 PM إن شاء الله", script.LATIN, "Ahmed Khan"))

    def test_ask_model_makes_no_second_call_for_it(self):
        calls = []

        def model(messages, schema_, **kwargs):
            calls.append(messages)
            return answer("Hi محمد, thanks for your message. What size do you need?")

        with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
            out, *_ = engine.ask_model(prompt.SYSTEM, "context", None, NOW, (), customer_script=script.LATIN, name="محمد علي")
        self.assertEqual((len(calls), out.get("script_fix")), (1, None))


class OwnNameTurnTests(GeneralBase):
    def test_an_arabic_profile_name_in_an_english_chat_costs_no_correction(self):
        self.contact.display_name = "محمد علي"
        self.contact.save(update_fields=["display_name"])
        CampaignRecipient.objects.filter(conversation=self.conversation).update(name="محمد علي")
        reply = "Hi محمد, thanks for your message. What size do you need?"
        outcome, calls, _, _ = self.turn(self.inbound("I need a shop in International City"), [answer(reply), answer("Hi Mohammed!")])
        self.assertEqual((len(calls), self.body(outcome)), (1, reply))


class MustNotChangeTests(TestCase):
    """Every scenario's right answer still passes, and those the guards sit next to keep their verdicts."""

    def test_the_right_answers_still_pass(self):
        from apps.leadai.tests.test_eval_command import RIGHT

        for item in leadai_eval.SCENARIOS:
            with self.subTest(item.id):
                run, _ = run_eval(item, RIGHT[item.id])
                self.assertEqual(run.failures, [])

    def test_the_bookings_next_to_the_guards(self):
        for scenario_id, completion in (
            ("yes-to-slot", booked("2026-10-13", "17:00")),
            ("lang-arabic-yes", booked("2026-10-13", "17:00", language="ar")),
            ("shops-nudge-morning-pick", booked("2026-10-13", "13:00")),
            ("exact-time", booked("2026-10-14", "17:00")),
            ("shop-bare-5", booked("2026-10-13", "17:00")),
            ("shop-outside-now", booked("2026-10-12", "14:00", hot_lead=True)),
        ):
            with self.subTest(scenario_id):
                run, _ = run_eval(scenario_id, completion)
                self.assertEqual(run.failures, [])
                self.assertIsNotNone(run.when)
