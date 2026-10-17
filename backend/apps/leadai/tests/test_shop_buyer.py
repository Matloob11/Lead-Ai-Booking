"""Q43 (Matloob, 2026-10-17): a customer who wants to buy a shop hears no price, gets the office invitation, and a
person is alerted (assistant/shop_buyer.py).

From real words: launch chat 42 ("To buy", then "I want purchase shop / Not to rent"), whom the model told "AED 33,000
or AED 48,000 per year means the annual rent price for the shop" live. The guards' tests switch each off
(shop_buyer.NO_FIGURES, PRICE_ANSWER) to prove it is what holds. The shops chat is test_who_the_customer_is's.
"""

import json

from apps.inbox.models import Message
from apps.leadai.assistant import needs, shop_buyer
from apps.leadai.models import LeadAiAlert
from apps.leadai.tests.test_assistant import NOW, answer
from apps.leadai.tests.test_shops_playbook import shop_answer
from apps.leadai.tests.test_who_the_customer_is import MAPS, NotAShopBase
from django.test import SimpleTestCase
from unittest.mock import patch

# The model's live words to chat 42's buyer (launch review, 2026-10-15).
LIVE_42 = (
    "AED 33,000 or AED 48,000 per year means the annual rent price for the shop. For example, Type 1 shops start from AED "
    "33,000 per year, and Type 2 shops start from AED 48,000 per year. What business will the shop be for?"
)
BUYER = needs.Need(needs.BUY, "shop")
PRICE = "The price depends on the shop, so our agent will go through the options and prices with you at our office."
VISIT = "Visit our office and we'll give you the best option."


def model_answer(reply, **facts):
    data = json.loads(json.dumps(answer(reply, segment="buyer").data))
    data["facts"].update(facts)
    return data


class ReadingTests(SimpleTestCase):
    def test_who_is_a_shop_buyer(self):
        self.assertTrue(shop_buyer.is_buyer(BUYER, {}))
        self.assertTrue(shop_buyer.is_buyer(needs.Need(needs.BUY, ""), {"property_type": "shop"}))  # "To buy" on a shops template
        self.assertTrue(shop_buyer.is_buyer(needs.Need(needs.BUY, ""), {}))
        for need, known, track in (
            (needs.Need(needs.BUY, "studio"), {}, ""),  # a studio buyer is the sale flow's
            (needs.Need(needs.BUY, ""), {"property_type": "studio"}, ""),
            (needs.Need(needs.HOME, "studio"), {}, ""),
            (needs.Need(needs.SELL, "shop"), {}, ""),
            (BUYER, {}, "sale"),
            (BUYER, {}, "rent"),
            (None, {}, ""),
        ):
            with self.subTest(need=need, track=track):
                self.assertFalse(shop_buyer.is_buyer(need, known, track=track))

    def test_a_price_question_in_their_words(self):
        for text in (
            "What is the price of the shop?", "price?", "How much for a shop to buy", "kitne ka hai shop", "shop ki qeemat kya hai",
            "بكم المحل؟", "دکان کی قیمت کیا ہے؟", "दुकान की कीमत क्या है?", "What would it cost per sq ft?",
        ):
            with self.subTest(text):
                self.assertTrue(shop_buyer.asks_price([text]))
        for text in ("I want purchase shop\nNot to rent", "kitne baje aa sakte hain", "What time suits you?", "Which cluster?", "ok"):
            with self.subTest(text):
                self.assertFalse(shop_buyer.asks_price([text]))

    def test_figures_in_the_models_words(self):
        reply, cut = shop_buyer.drop_amounts(LIVE_42)
        self.assertTrue(cut)
        self.assertEqual(reply, "What business will the shop be for?")
        for text in ("Prices start around 33k.", "England Cluster shops sell at about 1,100 per sq ft.", "It is 650000 for 522 sq ft.", "AED 509,135"):
            with self.subTest(text):
                self.assertTrue(shop_buyer.has_amount(text))
        for text in ("Our shops are 400 to 550 sq ft.", "I can hold 4:00 PM or 6:00 PM today.", "Building V03, Shop 20"):
            with self.subTest(text):
                self.assertFalse(shop_buyer.has_amount(text))


class SettleTests(SimpleTestCase):
    def test_no_figure_goes_to_a_shop_buyer(self):
        data = model_answer(LIVE_42)
        self.assertEqual(shop_buyer.settle(data, BUYER, {}, ["I want purchase shop\nNot to rent"]), shop_buyer.AMOUNTS_CUT)
        self.assertEqual(data["reply"], "What business will the shop be for?")
        self.assertIn(shop_buyer.AMOUNTS_CUT, data["trimmed"])
        with patch.object(shop_buyer, "NO_FIGURES", False):  # guard off: the rent goes to the buyer as a price
            data = model_answer(LIVE_42)
            shop_buyer.settle(data, BUYER, {}, ["I want purchase shop\nNot to rent"])
            self.assertIn("AED 33,000", data["reply"])

    def test_a_price_question_gets_codes_answer_and_the_invitation(self):
        slots = [NOW.replace(hour=16), NOW.replace(hour=18)]
        data = model_answer("Our agent will share the details with you.")
        self.assertEqual(shop_buyer.settle(data, BUYER, {}, ["What is the price of the shop?"], invites=1, slots=slots), shop_buyer.PRICE_LINE)
        self.assertEqual(data["converted"], needs.CONVERTED)
        self.assertEqual(data["not_a_shop"]["price"], "again")
        self.assertEqual((data["not_a_shop"]["slots"], data["not_a_shop"]["ask"], data["invited_to_meeting"]), ([], False, False))
        self.assertTrue(data["share_office_location"])
        data = model_answer("Our agent will share the details with you.")
        shop_buyer.settle(data, BUYER, {}, ["What is the price of the shop?"], invites=0, slots=slots)
        self.assertEqual((data["not_a_shop"]["slots"], data["invited_to_meeting"]), (slots, True))
        with patch.object(shop_buyer, "PRICE_ANSWER", False):  # guard off: the model's words answer the price
            data = model_answer("Our agent will share the details with you.")
            self.assertEqual(shop_buyer.settle(data, BUYER, {}, ["What is the price of the shop?"]), "")
            self.assertNotIn("converted", data)

    def test_the_first_answer_says_it_too_and_nothing_goes_over_a_handover_or_a_person(self):
        data = model_answer("")
        data["converted"] = needs.CONVERTED
        data["not_a_shop"] = {"kind": "buy", "noun": "shop", "slots": [], "ask": True}
        self.assertEqual(shop_buyer.settle(data, BUYER, {}, ["I want to buy a shop, what is the price?"]), shop_buyer.PRICE_LINE)
        self.assertEqual(data["not_a_shop"]["price"], "first")
        for extra, plain in (({"handover": {"needed": True, "reason": "customer_asked_human"}}, True), ({}, False)):
            with self.subTest(extra=extra, plain=plain):
                data = model_answer("Our agent will call you.")
                data.update(extra)
                self.assertNotEqual(shop_buyer.settle(data, BUYER, {}, ["price?"], plain=plain), shop_buyer.PRICE_LINE)
                self.assertNotIn("not_a_shop", data)

    def test_the_line_in_six_languages_never_a_figure(self):
        self.assertEqual(shop_buyer.price_line({"price": "again"}, "en", ""), f"{PRICE} {VISIT}")
        self.assertEqual(
            shop_buyer.price_line({"price": "first", "kind": "buy", "noun": "shop"}, "en", "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?"),
            f"Thank you for letting us know. We have many options to buy a shop across Dubai. {PRICE} {VISIT} "
            "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?",
        )
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                text = shop_buyer.price_line({"price": "first", "kind": "buy", "noun": "shop"}, language, "")
                self.assertIn(shop_buyer.PRICE_SENTENCE[language], text)
                self.assertIn(needs._VISIT[language], text)
                self.assertFalse(shop_buyer.has_amount(text))


class BuyerTurnTests(NotAShopBase):
    def test_a_known_shop_buyers_price_question_gets_codes_answer_and_the_team_is_alerted(self):
        self.set_state(facts={"need": "buy", "wanted": "to buy a shop", "intent": "buy", "property_type": "shop"}, invites=1)
        self.ours("Thank you for letting us know. We have many options to buy a shop across Dubai. Visit our office and we'll give you the best option.")
        message = self.inbound("What is the price of the shop?")
        outcome, _, _, _ = self.turn(message, [shop_answer("Small shops are AED 33,000 a year. Would you like to visit?", segment="buyer")])
        body = self.body(outcome)
        self.assertTrue(body.startswith(f"{PRICE} {VISIT}"), body)
        self.assertNotIn("33,000", body)
        alert = LeadAiAlert.objects.filter(kind="wanted", title="Ahmed Khan wants to buy a shop and asked the price").first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.priority, "high")
        self.assertIn("gave no figure", alert.text)
        self.assertIn('Their words: "What is the price of the shop?"', alert.text)

    def test_their_first_word_of_buying_with_a_price_question(self):
        message = self.inbound("I want to buy a shop, what is the price?")
        outcome, _, _, _ = self.turn(message, [shop_answer("Great! What size are you looking for?", segment="buyer")])
        body = self.body(outcome)
        self.assertTrue(body.startswith(f"Thank you for letting us know. We have many options to buy a shop across Dubai. {PRICE} {VISIT} I can hold a slot"), body)
        self.assertTrue(body.endswith(f"Our office location: {MAPS}"), body)
        self.assertTrue(Message.objects.filter(kind=Message.Kind.LOCATION, payload__source="leadai_ai").exists())  # the pin, as 2d's line
        self.assertTrue(LeadAiAlert.objects.filter(title="Ahmed Khan wants to buy a shop and asked the price").exists())

    def test_a_buyers_other_question_hears_no_figure(self):
        self.set_state(facts={"need": "buy", "wanted": "to buy a shop", "intent": "buy", "property_type": "shop"}, invites=1)
        self.ours("Thank you for letting us know. We have many options to buy a shop across Dubai. Visit our office and we'll give you the best option.")
        live = shop_answer("They are in Russia and England Cluster. Small ones are AED 33,000 a year.", segment="buyer")
        message = self.inbound("Which clusters are the shops in?")
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), "They are in Russia and England Cluster.")
        self.assertFalse(LeadAiAlert.objects.filter(title__contains="asked the price").exists())
        # Guard off: SHOP FACTS' rent passes the amount filter, and goes to the buyer as if it were a price.
        self.later(5)
        again = self.inbound("And how big are they?", seconds_ago=10)
        with patch.object(shop_buyer, "NO_FIGURES", False):
            outcome, _, _, _ = self.turn(again, [live])
        self.assertIn("AED 33,000", self.body(outcome))
