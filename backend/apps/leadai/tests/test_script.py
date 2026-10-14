"""Batch 2b: the customer's own script (board T19; every playbook).

A customer who types Arabic or Urdu script, or Devanagari, gets a reply in it: a reply of
the model's own words in another script is asked for once more (prompt.SCRIPT_CORRECTION),
and goes as it was if the second answer is no better. Code's own lines (a booking, an
opt-out line, a fixed line) follow the script the customer types, whatever language the
model named. An English chat makes no second call.
"""

import datetime as dt

from django.test import SimpleTestCase

from apps.leadai import lane
from apps.leadai.assistant import prompt, rules, script
from apps.leadai.models import LeadAiChatState
from apps.leadai.tests.test_assistant import NOW, answer
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, shop_answer

URDU = "مجھے انٹرنیشنل سٹی میں دکان چاہیے۔"
ARABIC = "أبحث عن محل في المدينة العالمية"
HINDI = "मुझे इंटरनेशनल सिटी में दुकान चाहिए।"


class ScriptRulesTests(SimpleTestCase):
    def test_the_script_a_message_is_written_in(self):
        self.assertEqual(script.script_of(URDU), script.URDU)
        self.assertEqual(script.script_of(ARABIC), script.ARABIC)
        self.assertEqual(script.script_of(HINDI), script.DEVANAGARI)
        self.assertEqual(script.script_of("I need a shop"), "")
        self.assertEqual(script.script_of("Mujhe shop chahiye"), "")  # Roman Urdu is English letters
        self.assertEqual(script.script_of("جی"), "")  # too short to tell

    def test_the_latest_typed_message_that_says_something_decides(self):
        self.assertEqual(script.customer_script([URDU, "ok", "5 pm", "👍", "جی"]), script.URDU)
        self.assertEqual(script.customer_script([URDU, "Actually I prefer English"]), script.LATIN)
        self.assertEqual(script.customer_script(["I need a shop", ARABIC]), script.ARABIC)
        self.assertEqual(script.customer_script(["Mujhe shop chahiye"]), script.LATIN)  # Roman Urdu is English letters
        self.assertEqual(script.customer_script([]), "")
        self.assertEqual(script.customer_script(["ok", "👍", "5 pm"]), "")  # nothing that says anything
        self.assertEqual(script.typed_texts(["[tapped: Interested]", "[voice note] السلام", ARABIC, " "]), [ARABIC])

    def test_a_reply_is_in_the_script_when_it_has_its_letters(self):
        self.assertTrue(script.has_script("شکریہ۔ کیا آپ کے پاس لائسنس ہے؟", script.URDU))
        self.assertFalse(script.has_script("شكرا. هل لديك رخصة؟", script.URDU))  # Arabic, not Urdu
        self.assertFalse(script.has_script("Shukriya. Kya aap ke paas licence hai?", script.URDU))
        self.assertTrue(script.has_script("شكرا", script.ARABIC))
        self.assertTrue(script.has_script("धन्यवाद", script.DEVANAGARI))
        self.assertTrue(script.has_script("Thank you", ""))

    def test_code_lines_follow_the_script(self):
        cases = {
            ("en", script.URDU): "ur",
            ("ur_latin", script.URDU): "ur",
            ("ur", script.URDU): "ur",
            ("en", script.ARABIC): "ar",
            ("ur", script.ARABIC): "ur",  # Urdu written with no Urdu-only letter
            ("hi_latin", script.DEVANAGARI): "hi",
            ("ur_latin", ""): "ur_latin",
            ("en", ""): "en",
        }
        for (language, written), expected in cases.items():
            with self.subTest(language=language, written=written):
                self.assertEqual(script.follow(language, written), expected)


class GeneralScriptTests(GeneralBase):
    """Every playbook: a general chat here."""

    def test_an_urdu_customer_answered_in_roman_urdu_is_asked_for_once_more(self):
        message = self.inbound(URDU)
        roman = answer("Ji zaroor. Kya aap ke paas trade licence hai?", language="ur_latin", reply_en="Sure. Do you have a trade licence?")
        urdu = answer("جی ضرور۔ کیا آپ کے پاس ٹریڈ لائسنس ہے؟", language="ur", reply_en="Sure. Do you have a trade licence?")
        outcome, calls, _, _ = self.turn(message, [roman, urdu])
        self.assertEqual(len(calls), 2)
        self.assertIn("written in Urdu script (Urdu, not Roman Urdu)", calls[1][-1]["content"])
        self.assertEqual(calls[1][-1]["content"], prompt.SCRIPT_CORRECTION.format(script=script.NAMES[script.URDU]))
        self.assertEqual(self.body(outcome), "جی ضرور۔ کیا آپ کے پاس ٹریڈ لائسنس ہے؟")
        actions = self.actions(message)
        self.assertEqual((actions["script_fix"], actions["language"]), ("fixed", "ur"))
        self.assertEqual(LeadAiChatState.objects.get(conversation=self.conversation).language, "ur")

    def test_still_wrong_the_first_words_go(self):
        message = self.inbound(ARABIC)
        english = answer("Welcome! What business will the shop be for?")
        outcome, calls, _, _ = self.turn(message, [english, answer("Welcome again!")])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.body(outcome), "Welcome! What business will the shop be for?")
        self.assertEqual(self.actions(message)["script_fix"], "kept")

    def test_an_english_chat_makes_no_second_call(self):
        outcome, calls, _, _ = self.turn(self.inbound("I need a shop in International City"), [answer()])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("script_fix", outcome.actions)

    def test_a_booking_is_code_written_in_the_customers_script(self):
        self.ours("Would tomorrow at 5 PM work for you to visit our office?", minutes_ago=3)
        message = self.inbound("تمام، غداً الساعة 5 مساءً")
        outcome, calls, _, _ = self.turn(message, [answer("", action="confirm", place="office", date="2026-10-13", time="17:00", language="en")])
        self.assertEqual(len(calls), 1)  # code writes the confirmation: nothing to ask again
        text = self.body(outcome)
        self.assertTrue(any("؀" <= ch <= "ۿ" for ch in text), text)
        self.assertEqual(self.actions(message)["line_language"], "ar")

    def test_a_stop_after_an_english_chat_is_answered_in_the_customers_script(self):
        LeadAiChatState.objects.update_or_create(conversation=self.conversation, defaults={"language": "en"})
        message = self.inbound("توقف")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), rules.line("stop_all", "ar"))

    def test_while_a_person_has_the_chat_nothing_is_asked_again(self):
        LeadAiChatState.objects.update_or_create(conversation=self.conversation, defaults={"handed_over_at": NOW - dt.timedelta(minutes=5), "handover_reason": "call_requested"})
        outcome, calls, _, _ = self.turn(self.inbound(URDU), [answer("Our specialist will reply.")])
        self.assertEqual(len(calls), 1)


class ShopsScriptTests(ShopsBase):
    def test_a_shops_chat_is_checked_the_same_way(self):
        self.assertEqual(lane.playbook_for(self.conversation), lane.IC_SHOPS)
        message = self.inbound(HINDI)
        latin = shop_answer("Namaste! Shop aapke liye hai ya kisi client ke liye?", language="hi_latin")
        devanagari = shop_answer("नमस्ते! दुकान आपके लिए है या किसी क्लाइंट के लिए?", language="hi", reply_en="Hello! Is the shop for you or a client?")
        outcome, calls, _, _ = self.turn(message, [latin, devanagari])
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.body(outcome), "नमस्ते! दुकान आपके लिए है या किसी क्लाइंट के लिए?")
