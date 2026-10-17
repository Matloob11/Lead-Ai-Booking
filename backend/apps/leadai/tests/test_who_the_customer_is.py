"""Batch 2d, the launch fixes (2026-10-15): who the shops customer is.

The shops campaigns 448 and 449 reached 32 people who replied; 13 wanted no shop to rent (a studio, a
room, a flat, to buy) or never asked about one, and 9 of the 16 shop lists went to such people. Matloob's
rule of the same day: no customer is ever lost. These tests feed the launch customers' own words and the
model's answers as the live turns recorded them (chat_<id>.json of the review), and each fails without
the guard it proves:

- A. needs.py on their words, in every language, and what is no need;
- B. the shop types list never goes to them (shop_flow.after_model, the live answers);
- C. a shops turn end to end: the owner's line, our office's location and pin, the team's alert, no
  handover, never lost;
- D. "we got one": already rented, the second-shop question;
- E. their visit booked in neutral words, their follow-ups about the visit only;
- F. never "only for rent, not for sale"; the office address is Building V03;
- G. the eval's launch scenarios hold because of these guards.

The fakes are test_assistant's; the shops chat is test_shops_playbook's (lead 555, the clock Monday
12 October 2026, 14:00 Dubai, so the two free slots are 2:30 PM and 4:30 PM).
"""

import re
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.inbox.models import Message
from apps.leadai import followups, tasks
from apps.leadai.assistant import crm, crm_fields, engine, needs, nudges, prompt, rules, schema, shop_flow
from apps.leadai.assistant import residential
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import DEFAULT_OFFICE_ADDRESS, LeadAiAlert, LeadAiAppointment, LeadAiCrmField, LeadAiSettings, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, fake_send_text
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_follow_ups import NudgeBase, at
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, shop_answer

MAPS = "https://maps.app.goo.gl/u7xzyea9pPLpRxBD8"
V03 = "Russia Cluster, Building V03, Shop 20, Dubai International City"
VISIT = "Visit our office and we'll give you the best option."
THANKS = "Thank you for letting us know."
SORRY = "Thank you for letting us know, and sorry for the confusion."


def line(options: str, *, sorry: bool = False) -> str:
    return f"{SORRY if sorry else THANKS} {options} {VISIT} {TWO_SLOTS_NOW}"


# A. needs.py on the launch customers' own words ------------------------------------------------------


class NeedsTests(SimpleTestCase):
    # Every inbound text of the 32 launch chats that says what they want (chat id: words -> kind, noun).
    LAUNCH = {
        "To buy": (needs.BUY, ""),  # 42
        "You are not getting I feel\n\nI want purchase shop\nNot to rent": (needs.BUY, "shop"),  # 42
        "Sorry nobody\nI want to purchase shop": (needs.BUY, "shop"),  # 42
        "I need an apartment studio": (needs.HOME, "studio_apartment"),  # 44
        "I need room\n1bhk Englund x cluster": (needs.HOME, "bhk:1"),  # 49
        "No shop": (needs.NEVER_ASKED, ""),  # 50
        "Looking for a room": (needs.HOME, "room"),  # 50
        "I dont need shops": (needs.NEVER_ASKED, ""),  # 52
        "am looking for studio for monthly rent sir": (needs.HOME, "studio"),  # 57
        "no sir am looking for studio only not shop": (needs.HOME, "studio"),  # 57
        "Actually i was looking for a studio": (needs.HOME, "studio"),  # 68
        "Not shops": (needs.NEVER_ASKED, ""),  # 68
        "No I didnt look for shop": (needs.NEVER_ASKED, ""),  # 98
        "I am looking residential room": (needs.HOME, "room"),  # 105
        "Studio apartment with balcony": (needs.HOME, "studio_apartment"),  # 107
        "I did not ask shop.": (needs.NEVER_ASKED, ""),  # 114
        "I did not say any thing about shop.i just requesting only apartment rent.Manhial told me already": (needs.HOME, "apartment"),  # 114
        "No I didn’t ask for shop": (needs.NEVER_ASKED, ""),  # 132
        "I asked for studio": (needs.HOME, "studio"),  # 132
        "Not looking for shops": (needs.NEVER_ASKED, ""),  # 134
        "AM NOT LOOKING FOR SHOPS": (needs.NEVER_ASKED, ""),  # 136
        "AM LOOKING FOR STUDIO APARTMENTS": (needs.HOME, "studio_apartment"),  # 136
    }
    # The rest of their words, and shop customers' own: no need at all.
    NO_NEED = (
        "Myself", "Wat is 33000/year", "Yes, show me shops", "How many square feet area", "Your rent is higher than others",
        "I need 600sqf", "If possible to send me photo first", "we got one", "if anything will let you know", "Not now", "no thanks",
        "For me", "How much is yur shop", "Parking side", "33k", "Im actually looking for a restaurant or cafeteria",
        "is there available gas line and chimney?", "i will be available on saturday", "I need shop in Morroco cluster",
        "I need cheaper price no good location", "Send me address first", "No", "No thankyou", "OK",
        "We can have a call at 11.30 - 12 PM", "Preferable Location - France (P24 P23 P26 P22)\nSize - 400sqft",
        # Shop customers' words that look like a need and are none.
        "I need a shop for my family business", "Shop for my photo studio", "I want a shop for my yoga studio", "Is there room for storage?",
        "flat rate?", "I want to buy stock for the shop", "I will purchase furniture", "I don't want to buy, I want to rent", "rent not buy",
        "I will come with my family", "Can I bring my family to the viewing?", "I need a shop, not a studio", "Is the shop in a residential area?",
        "shop nahi mil rahi", "Ji haan mujhe shop chahiye, mera mobile ka kaam hai", "ما زلت أبحث عن محل لمطعم", "لا، أبحث عن محل لمطعم",
        "store room available?", "The shop has enough room?", "I want to open a restaurant for families", "family restaurant shop",
        "Earn money daily from home! Join our crypto investment group now", "I need a shop with a back room",
        "مجھے انٹرنیشنل سٹی میں دکان چاہیے، میرا کپڑوں کا کاروبار ہے۔", "नमस्ते, मुझे इंटरनेशनल सिटी में किराने की दुकान के लिए शॉप चाहिए।",
    )

    def test_the_launch_customers_own_words(self):
        for text, (kind, noun) in self.LAUNCH.items():
            with self.subTest(text=text):
                need = needs.detect([text])
                self.assertIsNotNone(need)
                self.assertEqual((need.kind, need.noun), (kind, noun))
        # A burst is read whole: "No shop" + "Looking for a room" is a room, said by someone who never asked for a shop.
        need = needs.detect(["No shop", "Looking for a room"])
        self.assertEqual((need.kind, need.noun, need.denies), (needs.HOME, "room", True))
        self.assertEqual(needs.detect(["AM NOT LOOKING FOR SHOPS", "AM LOOKING FOR STUDIO APARTMENTS"]).what, "a studio apartment")

    def test_what_is_no_need(self):
        for text in self.NO_NEED:
            with self.subTest(text=text):
                self.assertIsNone(needs.detect([text]))
        self.assertIsNone(needs.detect([]))
        self.assertIsNone(needs.detect(["", "  "]))

    # A shop customer buys and sells goods, and chooses among shops: none of it is a buyer, an owner or "no shop".
    TRADE_AND_CHOICE = (
        "I sell mobile phones", "We buy and sell used phones", "I want to sell mobile accessories in my shop", "main mobile bechta hoon",
        "hum kapde bechte hain", "mobile ki dukan hai, hum phone bechte hain", "أشتري وأبيع جوالات", "أبيع عطور", "What is the selling price?",
        "We are a buy and sell company", "I buy gold", "I want to buy the shop furniture also", "I want to sell here",
        "Is this shop for rent or for sale?", "mujhe shop kiraye pe de do", "مجھے دکان کرائے پر دیں",
        "I'm not looking for shops near the road", "I don't want a shop on the main road", "I'm not looking for a big shop",
        "I don't need a shop now", "abhi shop nahi chahiye", "No shops available near me", "Not a shop owner yet",
        "Is the shop under an apartment building?", "Is there a room at the back?", "Is there a room inside the shop?",
        "I want a shop for my studio", "Is the shop in a flats building?", "near apartments", "Is there a bath room?",
        # The home they already have.
        "My studio is in Deira, I need a shop", "I have a studio flat in Warsan, need a shop here", "I live in a studio near Dragon Mart",
        "mera flat Deira mein hai, shop chahiye",
    )

    def test_a_shop_customers_trade_and_choice_is_no_need(self):
        for text in self.TRADE_AND_CHOICE:
            with self.subTest(text=text):
                self.assertIsNone(needs.detect([text]))
        for text, kind in {
            "Do you sell shops?": needs.BUY, "Can I buy it?": needs.BUY, "I am a cash buyer": needs.BUY, "Freehold?": needs.BUY,
            "I want to own a shop": needs.BUY, "Can you sell my shop?": needs.SELL, "I have a flat for rent": needs.SELL,
            "We want to rent out our 2 shops": needs.SELL, "meri dukan bechni hai": needs.SELL, "محلي للبيع": needs.SELL,
            "I want to sell": needs.SELL, "I did not ask for shop in International City": needs.NEVER_ASKED,
            "Not interested in shops": needs.NEVER_ASKED, "I'm not in need of a shop": needs.NEVER_ASKED,
            "I have a studio requirement": needs.HOME, "mere liye flat chahiye": needs.HOME, "Do you have a studio?": needs.HOME,
            "I want to live in a studio": needs.HOME,
        }.items():
            with self.subTest(text=text):
                self.assertEqual(getattr(needs.detect([text]), "kind", None), kind)

    def test_every_language(self):
        cases = {
            "Mujhe flat chahiye": needs.HOME, "mujhe kamra chahiye": needs.HOME, "mujhe shop nahi chahiye": needs.NEVER_ASKED,
            "maine shop nahi poochi": needs.NEVER_ASKED, "shop kharidni hai": needs.BUY, "apni shop bechni hai": needs.SELL,
            "rehne ke liye jagah chahiye": needs.HOME, "1 bhk chahiye": needs.HOME,
            "أبحث عن شقة": needs.HOME, "أريد استوديو للإيجار": needs.HOME, "لا أريد محل": needs.NEVER_ASKED, "لم أطلب محل": needs.NEVER_ASKED,
            "أريد شراء محل": needs.BUY, "هل المحلات للبيع؟": needs.BUY, "أريد بيع محلي": needs.SELL, "أبحث عن سكن عائلي": needs.HOME,
            "مجھے فلیٹ چاہیے": needs.HOME, "مجھے دکان نہیں چاہیے": needs.NEVER_ASKED, "کمرہ چاہیے": needs.HOME, "دکان خریدنی ہے": needs.BUY,
            "मुझे फ्लैट चाहिए": needs.HOME, "मुझे दुकान नहीं चाहिए": needs.NEVER_ASKED, "कमरा चाहिए": needs.HOME, "दुकान खरीदनी है": needs.BUY,
            "I want to invest in a shop": needs.BUY, "Is it for sale?": needs.BUY, "I want to sell my shop": needs.SELL,
            "I want to rent out my flat": needs.SELL, "Looking for a bed space": needs.HOME, "Family flat needed": needs.HOME,
        }
        for text, kind in cases.items():
            with self.subTest(text=text):
                self.assertEqual(getattr(needs.detect([text]), "kind", None), kind)

    def test_already_rented_and_what_is_not(self):
        for text in ("we got one", "Already rented", "I found one already", "found one", "I got a shop in Deira", "I already have a shop",
                     "Thank you but I already rented a shop last month", "shop mil gayi", "pehle hi le li", "استأجرت محل", "دکان مل گئی", "दुकान मिल गई"):
            with self.subTest(text=text):
                self.assertTrue(needs.rented_already([text]))
        for text in ("I got your message", "Got it", "I got one question", "I got the shop photos, thanks", "I already have a trade licence",
                     "I already booked the slot", "already got your message", "I found the location", "if anything will let you know"):
            with self.subTest(text=text):
                self.assertFalse(needs.rented_already([text]))

    def test_a_decline_or_not_now_anywhere_in_the_burst(self):
        for text in ("No", "No thankyou", "Not now", "[tapped: Not now]", "not interested", "abhi nahi", "ليس الآن", "नहीं चाहिए", "Maybe later"):
            with self.subTest(text=text):
                self.assertTrue(needs.declines([text]))
        for text in ("No problem, I can come at 5", "For myself", "What types of shops do you have?", "Yes"):
            with self.subTest(text=text):
                self.assertFalse(needs.declines([text]))

    def test_the_owners_line_in_six_languages(self):
        studio = needs.Need(needs.HOME, "studio")
        self.assertEqual(needs.line("en", studio, TWO_SLOTS_NOW, sorry=False), line("We have many options for a studio across Dubai."))
        self.assertEqual(
            needs.line("en", needs.Need(needs.NEVER_ASKED, "", True), TWO_SLOTS_NOW, sorry=True),
            line("We have many other options across Dubai too, not only shops.", sorry=True),
        )
        self.assertIn("We have many options to buy a shop across Dubai.", needs.line("en", needs.Need(needs.BUY, "shop"), "", sorry=False))
        self.assertIn("We have many options to buy across Dubai.", needs.line("en", needs.Need(needs.BUY), "", sorry=False))
        self.assertIn("We help owners sell and rent out their property across Dubai.", needs.line("en", needs.Need(needs.SELL, "shop"), "", sorry=False))
        self.assertIn("options for a 1BHK across Dubai", needs.line("en", needs.Need(needs.HOME, "bhk:1"), "", sorry=False))
        for language, visit in (
            ("ar", "تفضل بزيارة مكتبنا وسنقدم لك أفضل خيار."),
            ("ur_latin", "Hamare office tashreef layein, hum aap ko sab se behtar option denge."),
            ("ur", "ہمارے آفس تشریف لائیں، ہم آپ کو سب سے بہتر آپشن دیں گے۔"),
            ("hi_latin", "Hamare office aaiye, hum aapko sabse behtar option denge."),
            ("hi", "हमारे ऑफ़िस आइए, हम आपको सबसे बेहतर विकल्प देंगे।"),
        ):
            with self.subTest(language=language):
                text = needs.line(language, studio, "[slots]", sorry=True)
                self.assertIn(visit, text)
                self.assertTrue(text.endswith("[slots]"))
                self.assertNotRegex(text, r"\bType\s*[123]\b")
        self.assertIn("لدينا خيارات كثيرة من الاستوديوهات", needs.line("ar", studio, "", sorry=False))

    def test_what_our_team_reads(self):
        self.assertEqual(needs.summary(needs.Need(needs.HOME, "studio"), {"budget_basis": "per_month", "community": "England"}), "a studio, monthly rent, England")
        self.assertEqual(needs.summary(needs.Need(needs.HOME, "bhk:1"), {"bedrooms": "1bhk", "community": "International City"}), "a 1BHK")
        self.assertEqual(needs.Need(needs.BUY, "shop").what, "to buy a shop")
        self.assertEqual(needs.Need(needs.NEVER_ASKED, "", True).what, "no shop (never asked about one)")
        self.assertEqual(needs.property_words("studio_apartment"), "studio apartment")
        self.assertEqual(needs.of({"need": "home", "wanted": "a studio, monthly rent"}), needs.Need(needs.HOME, "studio", False))
        self.assertEqual(needs.of({"need": "buy", "wanted": "to buy a shop"}).noun, "shop")
        self.assertIsNone(needs.of({"need": "villas"}))
        self.assertIsNone(needs.of(None))

    def test_the_models_tags_are_the_schemas_and_a_shops_answer_only(self):
        self.assertEqual(set(needs.REASON_KINDS), set(schema.NOT_A_SHOP_REASONS))
        enum = schema.SHOPS_SCHEMA["properties"]["handover"]["properties"]["reason"]["enum"]
        for reason in schema.NOT_A_SHOP_REASONS:
            self.assertIn(reason, enum)
            self.assertNotIn(reason, schema.SCHEMA["properties"]["handover"]["properties"]["reason"]["enum"])
        data = {"handover": {"needed": True, "reason": "wrong_need"}}
        self.assertEqual(schema.normalize(data, shops=True)["handover"], {"needed": True, "reason": "wrong_need"})
        self.assertEqual(schema.normalize(data)["handover"], {"needed": True, "reason": None})
        self.assertEqual(needs.from_reason("wants_to_buy", {"property_type": "shop"}), needs.Need(needs.BUY, "shop", False))
        self.assertEqual(needs.from_reason("wrong_need", {"property_type": "studio"}).kind, needs.HOME)
        self.assertIsNone(needs.from_reason("unclear"))

    def test_never_only_for_rent_unless_shop_facts_say_so(self):
        live = "Thanks for clarifying. Currently, we only have shops available for rent, not for sale. Are you interested in renting a shop instead, or do you know someone who is?"  # chat 42
        self.assertEqual(
            needs.drop_sale_claims(live), ("Thanks for clarifying. Are you interested in renting a shop instead, or do you know someone who is?", True)
        )
        for claim in ("Our shops are for rent only.", "We don't sell shops.", "These shops are not for sale.", "Yeh shops sirf kiraye ke liye hain.", "المحلات للإيجار فقط."):
            with self.subTest(claim=claim):
                self.assertEqual(needs.drop_sale_claims(f"{claim} What size do you need?")[0], "What size do you need?")
        self.assertEqual(needs.drop_sale_claims("The rent is only AED 33,000 a year."), ("The rent is only AED 33,000 a year.", False))
        self.assertFalse(needs.drop_sale_claims(live, "- Type 1: for sale or rent")[1])  # SHOP FACTS speak of a sale

    def test_no_shop_talk_to_someone_who_wants_a_home(self):
        reply = "Our shops are for retail or commercial use, not studios. If you want, I can connect you to our agent to explore options that fit your studio needs."  # chat 57
        self.assertEqual(
            needs.drop_shop_pitch(reply, needs.Need(needs.HOME, "studio")),
            ("If you want, I can connect you to our agent to explore options that fit your studio needs.", True),
        )
        self.assertEqual(needs.drop_shop_pitch("Is the shop for yourself, or are you checking for a client?", needs.Need(needs.NEVER_ASKED))[0], "")
        # A buyer of a shop may hear of shops, never of shop types or the for-yourself question.
        self.assertEqual(needs.drop_shop_pitch("We sell shops too. Type 1 is perfect.", needs.Need(needs.BUY, "shop"))[0], "We sell shops too.")


# B. The shop types list never goes to them -----------------------------------------------------------


class ListGuardTests(SimpleTestCase):
    # chat: (what they said, the model's facts as the live turn left them, the facts known before). Each got the list live.
    LIVE = {
        44: ("I need an apartment studio", {"for_client": False, "property_type": "shop", "business_activity": "apartment studio"}, {}),
        49: ("I need room\n1bhk Englund x cluster", {"for_client": False, "property_type": "shop", "business_activity": "room", "bedrooms": "1bhk"}, {}),
        50: ("No shop Looking for a room", {"for_client": False, "property_type": "room"}, {}),
        57: ("am looking for studio for monthly rent sir", {"for_client": False, "property_type": "studio", "business_activity": "studio"}, {}),
        63: ("we got one thank you", {"for_client": False, "property_type": "shop", "already_rented": True}, {}),
        68: ("Actually i was looking for a studio", {"for_client": False, "property_type": "studio", "business_activity": "studio"}, {}),
        107: ("Studio apartment with balcony", {"for_client": False, "property_type": "studio apartment"}, {}),
        132: ("No I didn’t ask for shop I asked for studio", {"for_client": False, "property_type": "studio"}, {}),
        # 42: "Myself" to the for-whom question, the chat knowing they want to buy.
        42: ("Myself", {"for_client": False, "property_type": "shop", "intent": "buy"}, {"intent": "buy", "property_type": "shop"}),
    }

    def decide(self, said, facts, known, **options):
        flags = {"plain": True, "asked": False, "list_sent": False, "licence_asked": False}
        flags.update(options)
        return shop_flow.after_model({"facts": facts, "invited_to_meeting": False}, known, said, **flags)

    def test_the_launch_answers_get_no_list(self):
        for chat, (said, facts, known) in self.LIVE.items():
            with self.subTest(chat=chat):
                self.assertIsNone(self.decide(said, facts, known))
                self.assertTrue(shop_flow.shops_unwanted(facts, known, said))
        # A shop customer's "For myself" still gets it.
        self.assertEqual(self.decide("For myself", {"for_client": False}, {}), {"kind": shop_flow.LIST})

    def test_no_shop_step_at_all_for_them(self):
        for said, known in (("send photos please", {"need": "home", "wanted": "a studio"}), ("what types do you have?", {"intent": "buy"})):
            with self.subTest(said=said):
                self.assertIsNone(self.decide(said, {}, known))
        self.assertIsNone(self.decide("Yes I have a DED licence", {"licence_kind": "ded"}, {"need": "buy", "wanted": "to buy a shop"}))

    def test_never_the_list_when_the_burst_declines(self):
        self.assertIsNone(self.decide("[tapped: Not now] For myself", {"for_client": False}, {}))
        self.assertIsNone(self.decide("No, what types of shops do you have?", {}, {}))
        self.assertIsNone(self.decide("no thanks send photos", {}, {}))
        self.assertEqual(self.decide("No problem, what types of shops do you have?", {}, {}), {"kind": shop_flow.LIST})

    def test_a_shop_customer_who_says_what_they_sell_still_gets_it(self):
        for said, facts in (
            ("For myself, I sell mobile phones", {"for_client": False, "business_activity": "mobile phones"}),
            ("Myself. We buy and sell used cars", {"for_client": False, "business_activity": "used cars"}),
            ("For me, hum kapde bechte hain", {"for_client": False, "business_activity": "clothes"}),
        ):
            with self.subTest(said=said):
                self.assertFalse(shop_flow.shops_unwanted(facts, {}, said))
                self.assertEqual(self.decide(said, facts, {}), {"kind": shop_flow.LIST})

    def test_a_shop_they_rented_before_stops_nothing_later(self):
        self.assertFalse(shop_flow.shops_unwanted({"for_client": False}, {"already_rented": True}, "Yes, I need one more for my brother"))
        self.assertEqual(self.decide("Yes, I need one more for my brother", {"for_client": False}, {"already_rented": True}), {"kind": shop_flow.LIST})


# C. A shops turn end to end ----------------------------------------------------------------------------


class NotAShopBase(ShopsBase):
    def setUp(self):
        super().setUp()
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url=MAPS, office_latitude=25.169639, office_longitude=55.404667)
        self.list_matloob()

    def wanted_alerts(self):
        return LeadAiAlert.objects.filter(kind="wanted").order_by("pk")


class NotAShopTurnTests(NotAShopBase):
    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_chat_44_gets_the_owners_line_our_location_the_pin_and_the_teams_alert(self):
        message = self.inbound("I need an apartment studio")
        live = shop_answer(
            "Great! What business will the shop be for?",
            facts={"for_client": False, "property_type": "shop", "business_activity": "apartment studio", "intent": "rent",
                   "notes": ["fit-out requirements", "parking availability"]},
        )
        outcome, calls, _, note_delay = self.turn(message, [live])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), f"{line('We have many options for a studio apartment across Dubai.')}\nOur office location: {MAPS}")
        self.assertEqual(self.sent_lists.call_count, 0)  # never the shop types list
        self.assertTrue(Message.objects.filter(kind=Message.Kind.LOCATION, payload__source="leadai_ai").exists())
        state = self.state()
        self.assertEqual((state.facts["need"], state.facts["wanted"], state.facts["property_type"]), ("home", "a studio apartment", "studio apartment"))
        self.assertNotIn("business_activity", state.facts)  # a studio is no business (chat 44 wrote it to Bitrix live)
        self.assertEqual((state.handed_over_at, state.not_interested_at, state.invites), (None, None, 1))
        self.assertEqual(self.fields(), [(crm_fields.FIELD_BOT_STATUS, "2476")])
        alerts = list(self.wanted_alerts())
        self.assertEqual({alert.bitrix_user_id for alert in alerts}, {"77", "2311"})  # the chat's owner and the Lead AI alert list
        self.assertEqual(alerts[0].priority, "high")
        self.assertEqual(alerts[0].title, "Ahmed Khan wants a studio apartment, not a shop")
        self.assertIn("Their words: I need an apartment studio", alerts[0].text)
        self.assertIn("keeps arranging the visit here", alerts[0].text)
        note_delay.assert_called_once()
        self.assertEqual(note_delay.call_args.args[1], "wanted")
        self.assertIn("Wants: a studio apartment", note_delay.call_args.args[2])
        actions = self.actions(message)
        self.assertEqual((actions["who"], actions["need"], actions["invited_to_meeting"]), ("not_a_shop", "home", True))

    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_chat_136_an_unclear_handover_is_dropped_and_capitals_get_a_sorry(self):
        self.inbound("AM NOT LOOKING FOR SHOPS", seconds_ago=40)
        message = self.inbound("AM LOOKING FOR STUDIO APARTMENTS", seconds_ago=30)
        live = shop_answer(
            "We specialize in shops in International City. For studio apartments, I will connect you to our agent who can assist you further here.",
            handover="unclear", segment="other", facts={"for_client": False, "property_type": "studio apartment", "intent": "rent"},
        )
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), f"{line('We have many options for a studio apartment across Dubai.', sorry=True)}\nOur office location: {MAPS}")
        self.assertIsNone(self.state().handed_over_at)  # live it was "unclear", and nobody answered for hours
        self.assertFalse(LeadAiAlert.objects.filter(kind="handover").exists())
        self.assertTrue(self.wanted_alerts().exists())
        self.assertEqual(self.actions(message)["segment"], "residential_tenant")

    def test_chat_42_a_buyer_is_invited_and_never_lost(self):
        first = self.inbound("To buy")
        live = shop_answer(
            "You mentioned buying a shop. Is the shop for yourself, or are you checking for a client?",
            facts={"intent": "buy", "property_type": "shop", "notes": ["Is the shop for yourself, or are you checking for a client?"]},
        )
        outcome, _, _, _ = self.turn(first, [live])
        self.assertEqual(self.body(outcome), f"{line('We have many options to buy a shop across Dubai.')}\nOur office location: {MAPS}")
        self.assertEqual(self.state().facts["wanted"], "to buy a shop")
        # Later, as live: "Sorry nobody / I want to purchase shop", which the model closed as not interested.
        self.later(6)
        message = self.inbound("Sorry nobody\nI want to purchase shop", seconds_ago=10)
        outcome, _, _, _ = self.turn(message, [shop_answer("No problem, thank you for letting us know.", opt_out="not_interested")])
        self.assertIsNone(self.state().not_interested_at)
        self.assertFalse(LeadAiCrmField.objects.filter(field=crm_fields.LOST).exists())
        self.assertNotIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_LOST)), self.fields())
        # Invited again, with a sorry (we talked to them already), and no location twice in a day; at 2:06 PM the
        # first slot an hour ahead is 3:30 PM (hours.OFFER_LEAD).
        later_pair = "I can hold a slot for you today at 3:30 PM or 5:30 PM — which is better?"
        self.assertEqual(self.body(outcome), line("We have many options to buy a shop across Dubai.", sorry=True).replace(TWO_SLOTS_NOW, later_pair))
        self.assertEqual(self.wanted_alerts().count(), 2)  # the same want: no second alert (one row each for 77 and 2311)

    def test_a_no_from_them_stops_the_invitations_but_the_lead_is_never_lost(self):
        self.set_state(facts={"need": "home", "wanted": "a studio"})
        self.ours(line("We have many options for a studio across Dubai."), minutes_ago=30)
        outcome, calls, _, note_delay = self.turn(self.inbound("no thanks"), [shop_answer()])
        self.assertEqual(calls, [])  # the code rule's opt-out, as before
        self.assertIsNotNone(self.state().not_interested_at)
        self.assertEqual(self.fields(), [])  # no Bot Status Lost and no move to Not Interested
        note_delay.assert_called_once()

    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_a_want_said_with_not_interested_or_wrong_number_is_never_lost(self):
        # "not interested" alone would be code's opt-out before any model; said with a want it waits.
        self.inbound("I need a studio", seconds_ago=40)
        message = self.inbound("not interested", seconds_ago=30)
        outcome, calls, _, _ = self.turn(message, [shop_answer("No problem, thank you for letting us know.", opt_out="not_interested")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), f"{line('We have many options for a studio across Dubai.')}\nOur office location: {MAPS}")
        self.assertIsNone(self.state().not_interested_at)
        self.assertFalse(LeadAiCrmField.objects.filter(field=crm_fields.LOST).exists())

    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_a_wrong_number_with_a_want_is_none_and_without_one_stays(self):
        outcome, calls, _, _ = self.turn(self.inbound("Wrong number, need a flat"), [shop_answer("Sorry.", opt_out="wrong_number")])
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.state().stopped_at)
        self.assertTrue(self.body(outcome).startswith(THANKS))
        # "Wrong number. I am not Ahmed" is one, as before (code's, no model).
        self.assertTrue(engine.not_lost_for(rules.NOT_INTERESTED, ["I need a villa", "not interested"]))
        self.assertFalse(engine.not_lost_for(rules.WRONG_NUMBER, ["Wrong number. I am not Ahmed"]))
        self.assertFalse(engine.not_lost_for(rules.WRONG_NUMBER, ["Wrong number, I never asked about a shop"]))
        self.assertFalse(engine.not_lost_for(rules.STOP_ALL, ["stop, I need a flat"]))

    def test_later_the_models_words_go_without_shop_talk(self):
        self.set_state(facts={"need": "home", "wanted": "a studio", "property_type": "studio"}, invites=1)
        self.ours(line("We have many options for a studio across Dubai."), minutes_ago=30)
        reply = "Our shops start from AED 33,000 a year. Our agent will share studio options with you at the office."
        outcome, _, _, _ = self.turn(self.inbound("What is the rent of a studio?"), [shop_answer(reply)])
        self.assertEqual(self.body(outcome), "Our agent will share studio options with you at the office.")
        self.assertEqual(self.sent_lists.call_count, 0)

    def test_a_request_for_a_person_still_hands_them_over(self):
        self.set_state(facts={"need": "home", "wanted": "a studio"})
        outcome, _, _, _ = self.turn(
            self.inbound("I need a studio, please ask someone to call me"),
            [shop_answer("Sure, our agent will call you.", handover="call_requested")],
        )
        self.assertIsNotNone(self.state().handed_over_at)
        self.assertNotIn(VISIT, self.body(outcome))

    def test_the_models_tag_alone_is_a_need(self):
        message = self.inbound("I am looking for something in Deira")
        outcome, _, _, _ = self.turn(message, [shop_answer("Noted.", handover="other_area", facts={"community": "Deira"})])
        self.assertIsNone(self.state().handed_over_at)
        self.assertEqual(self.body(outcome), f"{line('We have many other options across Dubai too, not only shops.')}\nOur office location: {MAPS}")
        self.assertEqual(self.actions(message)["need_tag"], "other_area")

    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_chat_68_not_now_then_a_studio(self):
        self.turn(self.tap("Not now", seconds_ago=60), [])
        self.assertIsNotNone(self.state().followup_asked_at)
        self.later(1)
        live = shop_answer(
            "I see, a studio. Our shops are for retail or commercial use. Is the studio for a business activity?",
            facts={"for_client": False, "property_type": "studio", "business_activity": "studio"},
        )
        outcome, _, _, _ = self.turn(self.inbound("Actually i was looking for a studio", seconds_ago=10), [live])
        self.assertTrue(self.body(outcome).startswith(SORRY))
        self.assertEqual(self.sent_lists.call_count, 0)
        self.assertIsNone(self.state().followup_asked_at)  # the invitation answers it now


class GeneralChatUnchangedTests(GeneralBase):
    def test_a_general_chat_gets_none_of_it(self):
        outcome, _, _, _ = self.turn(self.inbound("I need an apartment studio"), [shop_answer("Sure. Which area do you prefer?", segment="residential_tenant")])
        self.assertEqual(self.body(outcome), "Sure. Which area do you prefer?")
        self.assertFalse(LeadAiAlert.objects.filter(kind="wanted").exists())
        self.assertNotIn("need", self.state().facts)


# D. "we got one": already rented -------------------------------------------------------------------------


class AlreadyRentedTests(NotAShopBase):
    def test_chat_63_we_got_one_is_asked_about_a_second_shop_never_shown_the_list(self):
        self.inbound("we got one", seconds_ago=40)
        message = self.inbound("thank you", seconds_ago=30)
        live = shop_answer("Great! What business will the shop be for?", facts={"for_client": False, "property_type": "shop", "already_rented": True})
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), rules.line("rented_second_shop", "en"))
        self.assertEqual(self.sent_lists.call_count, 0)
        self.assertTrue(self.actions(message)["rented_asked"])
        # Their no to it closes the lead as already rented (board T27), as before.
        self.later(2)
        outcome, calls, _, _ = self.turn(self.inbound("No", seconds_ago=10), [shop_answer()])
        self.assertEqual(calls, [])
        self.assertEqual(LeadAiCrmField.objects.get(field=crm_fields.LOST).payload, {"reason": "already rented"})

    def test_a_not_interested_with_it_is_asked_first(self):
        outcome, _, _, _ = self.turn(
            self.inbound("No thank you, I already rented a shop last month"),
            [shop_answer("No problem, thank you for letting us know.", opt_out="not_interested")],
        )
        self.assertIsNone(self.state().not_interested_at)
        self.assertEqual(self.body(outcome), rules.line("rented_second_shop", "en"))
        self.assertTrue(self.state().facts["already_rented"])


# E. Their visit, and their follow-ups ---------------------------------------------------------------------


class NotAShopVisitTests(NotAShopBase):
    @patch.object(residential, "RENT_LIVE", False)  # 2d's own path (batch 2e's rent flow off: its kill switch)
    def test_their_yes_books_an_office_visit_in_words_about_no_shop(self):
        self.set_state(facts={"need": "home", "wanted": "a studio", "property_type": "studio"}, invites=1)
        self.ours(line("We have many options for a studio across Dubai."), minutes_ago=5)
        outcome, _, crm_delay, _ = self.turn(
            self.inbound("4:30 PM today is fine"), [shop_answer("", action="confirm", place="office", date="2026-10-12", time="16:30")]
        )
        body = self.body(outcome)
        self.assertTrue(body.startswith("Perfect, Ahmed. Your meeting is confirmed."), body)
        self.assertIn("Our specialist will be expecting you.", body)
        for shop_words in ("Shop type", "drive you", "trade license", "shops"):
            self.assertNotIn(shop_words, body)
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.details["wanted"]), ("confirmed", "a studio"))
        crm_delay.assert_called_once()
        self.assertIn("Wants: a studio", crm.comment_text(appointment, "confirmed", office_address=V03))
        self.assertIn("Wants: a studio", "\n".join(engine._detail_lines(appointment.details)))

    @override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
    def test_the_timeline_note_says_what_they_want(self):
        lines = engine.wanted_note_lines({"wanted": "a studio, monthly rent"}, "am looking for studio for monthly rent sir")
        with patch("apps.crmlink.client.add_comment") as comment:
            tasks.record_crm_note(self.conversation.pk, "wanted", lines)
        entity, crm_id, text = comment.call_args.args
        self.assertEqual((entity, crm_id), ("lead", 555))
        self.assertTrue(text.startswith("WhatsApp Lead AI · CUSTOMER WANTS SOMETHING OTHER THAN A SHOP"))
        self.assertIn("Wants: a studio, monthly rent", text)
        self.assertNotIn("stopped", text)
        # The opt-out notes are as before.
        self.assertTrue(crm.note_text("not_interested", "Ahmed", "971501234567").endswith("The assistant stopped inviting this customer."))


class NotAShopNudgeTests(NudgeBase):
    def test_the_nudge_is_about_the_visit_only(self):
        self.set_state(facts={"need": "home", "wanted": "a studio"})
        self.go(at(12, 15, 1))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])
        result, sent = self.nudge()
        self.assertEqual(result, "sent")
        self.assertEqual(sent.call_args.args[2], "Hi Ahmed, just checking in — shall I hold a slot for you to see the options today or tomorrow?")
        self.assertTrue(nudges.is_nudge(sent.call_args.args[2]))  # a yes to it is a yes to coming
        self.go(at(13, 10, 35))
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text) as last:
            self.assertEqual(followups.send(self.conversation.pk, followups.NUDGE_2), "sent")
        self.assertEqual(
            # An hour ahead at least at 10:35 (hours.OFFER_LEAD).
            last.call_args.args[2], "Good morning Ahmed, would today suit you to come and see the options? I can hold a slot at 12:00 PM or 2:00 PM."
        )

    def test_no_shop_word_in_any_language_and_never_template_b(self):
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language=language):
                for text in (nudges.first_text(language, "Ahmed", now=NOW, options=True), nudges.second_text(language, "Ahmed", [NOW], options=True)):
                    self.assertNotRegex(text, r"(?i)\bshops?\b|محلات|دکانیں|दुकानें")
                    self.assertTrue(nudges.is_nudge(text))
        # A check-back planned for them is dropped: Template B is all shops.
        self.set_state(facts={"need": "home", "wanted": "a studio"}, followup_due_at=NOW)
        state = self.state()
        self.assertFalse(followups.check_back_due(self.conversation, state, NOW))
        self.assertTrue(followups.check_back_moot(self.conversation, state, NOW))
        self.assertIsNone(self.state().followup_due_at)


# F. Never "only for rent"; the office is Building V03 -------------------------------------------------------


class SaleClaimTurnTests(NotAShopBase):
    def test_a_shops_reply_never_says_only_for_rent(self):
        outcome, _, _, _ = self.turn(
            self.inbound("Is the rent yearly?"),
            [shop_answer("Yes, the rent is yearly, payable in 1 to 4 cheques. Our shops are only for rent, not for sale.")],
        )
        self.assertEqual(self.body(outcome), "Yes, the rent is yearly, payable in 1 to 4 cheques.")
        self.assertIn("sale_claim", self.actions(LeadAiTurn.objects.get().inbound)["trimmed"])


class OfficeAddressTests(SimpleTestCase):
    def test_the_office_is_building_v03(self):
        self.assertEqual(DEFAULT_OFFICE_ADDRESS, V03)
        self.assertEqual(LeadAiSettings._meta.get_field("office_address").default, V03)
        migration = Path(__file__).resolve().parents[1] / "migrations" / "0007_office_address_v03.py"
        self.assertIn(f"default='{V03}'", migration.read_text(encoding="utf-8"))
        # Our office, never a shop for rent: the prompt says so.
        self.assertIn('OFFICE in the context is our own office, where every visit starts: it is never the location of a shop for rent ("Shop 20"', prompt.SHOPS_SYSTEM)

    def test_no_v02_left_in_the_code(self):
        root = Path(__file__).resolve().parents[1]
        found = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if "V02" in path.read_text(encoding="utf-8") and path.name not in ("0002_assistant.py", "models.py", "test_first_chat_fixes.py", Path(__file__).name)
        ]
        self.assertEqual(found, [])

    def test_the_prompt_carries_the_owners_rule(self):
        system = prompt.SHOPS_SYSTEM
        for text in (
            "NOT A SHOP (the owner's rule: no customer is ever lost)",
            '"Visit our office and we\'ll give you the best option." with two free slots from FREE SLOTS',
            "never say our shops are only for rent or not for sale unless SHOP FACTS says so",
            "wrong_need (a home or another kind of property), wants_to_buy, wants_to_sell, never_asked or other_area",
            "never to someone who wants no shop to rent (NOT A SHOP)",
            '("we got one", "already got one", "found one", "rented already")',
        ):
            with self.subTest(text=text[:40]):
                self.assertIn(text, system)


# G. The eval's launch scenarios hold because of these guards -----------------------------------------------

# The launch customers still on 2d's path: someone who wants a room, to buy, or never asked about a shop (the other track),
# and a shop customer. The studio and one-bedroom seekers are the rent flow's since batch 2e (REROUTED: test_residential_turns).
LAUNCH_SCENARIOS = (
    "shops-no-shop-room-50", "shops-we-got-one-63", "shops-never-asked-98", "shops-did-not-ask-114", "shops-buyer-42",
    "shops-buyer-not-lost-42", "shops-residential-room-105",
)
REROUTED = (
    "shops-want-studio-44", "shops-want-1bhk-49", "shops-studio-monthly-57", "shops-not-now-studio-68", "shops-studio-balcony-107",
    "shops-asked-for-studio-132", "shops-studio-capitals-136",
)


class EvalLaunchTests(SimpleTestCase):
    def run_scenario(self, scenario_id):
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=RIGHT[scenario_id]):
            return leadai_eval.run_once(scenario, scenario_id)

    @override_settings(LEADAI_OPENAI_API_KEY="test")
    def test_every_launch_scenario_passes_with_the_live_answer(self):
        for scenario_id in LAUNCH_SCENARIOS:
            with self.subTest(scenario_id):
                run = self.run_scenario(scenario_id)
                self.assertEqual(run.failures, [])
                if scenario_id != "shops-we-got-one-63":
                    self.assertTrue(filters_carries(run.out))
                    self.assertTrue(run.answer["invited_to_meeting"])

    @override_settings(LEADAI_OPENAI_API_KEY="test")
    def test_and_fails_without_the_guards(self):
        with patch.object(engine, "who_they_are", return_value=""), patch.object(engine, "untag_need", return_value=None), patch.object(
            shop_flow, "shops_unwanted", return_value=False
        ):
            for scenario_id in LAUNCH_SCENARIOS:
                with self.subTest(scenario_id):
                    self.assertNotEqual(self.run_scenario(scenario_id).failures, [])
            # Live these got the shop types list (132's "No I didn't ask..." is held by the decline guard alone); the studio and
            # one-bedroom seekers on 2d's own path (the rent flow off).
            with patch.object(residential, "RENT_LIVE", False):
                for scenario_id in ("shops-want-studio-44", "shops-want-1bhk-49", "shops-studio-balcony-107", "shops-we-got-one-63"):
                    with self.subTest(scenario_id):
                        self.assertEqual((self.run_scenario(scenario_id).answer.get("shop_step") or {}).get("kind"), shop_flow.LIST)


def filters_carries(text: str) -> bool:
    from apps.leadai.assistant import filters

    return filters.carries_location(text, DEFAULT_OFFICE_ADDRESS)


class LaunchWordsTests(SimpleTestCase):
    def test_the_scenarios_use_the_launch_customers_own_words(self):
        words = {s.id: s.new for s in leadai_eval.SCENARIOS}
        self.assertEqual(words["shops-no-shop-room-50"], ["No shop", "Looking for a room"])
        self.assertEqual(words["shops-buyer-not-lost-42"], ["Sorry nobody\nI want to purchase shop"])
        self.assertEqual(words["shops-studio-capitals-136"], ["AM NOT LOOKING FOR SHOPS", "AM LOOKING FOR STUDIO APARTMENTS"])
        for scenario_id in (*LAUNCH_SCENARIOS, *REROUTED):
            self.assertTrue(re.search(r"-\d+$", scenario_id), scenario_id)
