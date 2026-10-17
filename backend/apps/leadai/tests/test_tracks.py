"""Batch 2e slice A: which need a mixed International City chat serves (assistant/tracks.py; spec §1.2, board T90).

One campaign now reaches shop seekers, studio and one-bedroom seekers to rent or buy, and everyone else (Q26). Code
decides the track (shop, rent, sale, other, or not known yet) and the unit; the model never writes them. In slice A the
decision is stored in shadow (no reply changes), the mixed template's first answer is code's, and Template B and the
check-back follow only a shops template. Each test feeds customers' own words (the launch chats of 2026-10-15, the
brief's examples, the spec's traps) in English, Roman Urdu, Arabic, Urdu and Hindi, and fails without the rule it proves
(the scratchpad's guards_off.py switches each one off).

- A. needs.py's new words: "1 bed", "one bed", "1 bed hall", "ek bedroom", "غرفة وصالة", a 1BR near their shop;
- B. tracks.unit_of, the cluster names (never a nationality), another area, a wish for a shop;
- C. tracks.decide, step by step, and from_need's table;
- D. the launch customers' own words, in five scripts, as decide reads them;
- E. the mixed template's first yes: first_yes and the opener in six languages; POSITIVE_TAPS; ic_templates.kind_of.

The engine's turns are test_tracks_turns.py's; the lead context test_lead_context.py's; the follow-ups test_followups_mixed.py's.
"""

import types
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai import ic_templates
from apps.leadai.assistant import needs, rules, tracks
from apps.leadai.models import DEFAULT_RESIDENTIAL_FACTS, DEFAULT_SHOPS_FACTS

SPAIN_STUDIO = {"source": "Bayut", "listing_ref": "a7group-1722", "unit": "studio", "property": "apartment", "cluster": "Spain", "deal": "rent"}


def decide(words=(), **kwargs):
    """tracks.decide; with no ``lead`` given, a read of the lead context fails the test (the read is lazy: spec §2.8)."""
    reads = []
    if "lead" not in kwargs:
        kwargs["lead"] = lambda: reads.append(1) or {}
    decision = tracks.decide(words=list(words), **kwargs)
    if reads:
        raise AssertionError(f"the lead context was read for {list(words)!r}")
    return decision


# A. needs.py: what slice A adds (spec §1.2, "What needs.py gains") ------------------------------------------------


class NeedsPatternTests(SimpleTestCase):
    """The words for a one-bedroom that 2d read as nothing, or as a room."""

    ONE_BEDROOM = (
        "I need 1 bed",  # the brief's own shorthand
        "one bed flat for rent",
        "Looking for 1 bed hall in International City",  # a 1BHK, as people in Dubai say it
        "ek bedroom chahiye",  # Roman Urdu
        "ek bed room flat chahiye kiraye pe",
        "غرفة وصالة",  # Arabic: a room and a hall is a one-bedroom, never a room
        "أبحث عن شقة غرفة وصالة للإيجار",
        "مجھے ایک بیڈروم فلیٹ چاہیے",  # Urdu
        "मुझे एक बेडरूम फ्लैट चाहिए",  # Hindi
        "I need a 1BR near my shop",  # their shop is where, not what (spec §8's trap)
        "studio or 1 bed near my store",
    )
    TWO_BEDROOM = ("2 bed for my family", "غرفتين وصالة", "3 غرف وصالة", "दो बेडरूम फ्लैट", "دو بیڈروم فلیٹ")

    def test_a_one_bedroom_in_every_script(self):
        for text in self.ONE_BEDROOM:
            with self.subTest(text=text):
                need = needs.detect([text])
                self.assertIsNotNone(need)
                self.assertEqual(need.kind, needs.HOME)
                self.assertIn(need.noun, ("bedroom:1", "studio"))  # "studio or 1 bed" names the studio first
        self.assertEqual(needs.detect(["I need 1 bed"]).noun, "bedroom:1")
        self.assertEqual(needs.detect(["غرفة وصالة"]).noun, "bedroom:1")
        self.assertEqual(needs.detect(["أبحث عن شقة غرفة وصالة للإيجار"]).noun, "bedroom:1")  # never "a flat", unit unknown
        self.assertEqual(needs.detect(["I need a 1BR near my shop"]).noun, "bedroom:1")

    def test_two_bedrooms_and_more(self):
        expected = {"2 bed for my family": "bedroom:2", "غرفتين وصالة": "bedroom:2", "3 غرف وصالة": "bedroom:3"}
        for text in self.TWO_BEDROOM:
            with self.subTest(text=text):
                need = needs.detect([text])
                self.assertIsNotNone(need)
                self.assertEqual(need.kind, needs.HOME)
                self.assertTrue(need.noun.startswith("bedroom:") and need.noun != "bedroom:1", need.noun)
                if text in expected:
                    self.assertEqual(need.noun, expected[text])

    def test_what_stays_as_it_was(self):
        self.assertEqual(needs.detect(["I need 1 bed space"]).noun, "bed_space")
        self.assertEqual(needs.detect(["a room with 1 bed"]).noun, "room")  # a room with a bed is a room
        self.assertEqual(needs.detect(["غرفة للإيجار"]).noun, "room")
        self.assertEqual(needs.detect(["single bedroom flat"]).noun, "bedroom:1")
        self.assertIsNone(needs.detect(["I need a single bed"]))  # a bed, never a bedroom count
        # A shop customer's own place is no home they want, and their shop near a flat is still a shop.
        self.assertIsNone(needs.detect(["I need a shop near my flat"]))
        self.assertIsNone(needs.detect(["I need a shop with a back room"]))
        self.assertIsNone(needs.detect(["Is the shop near the apartments?"]))

    def test_the_arabic_line_says_one_bedroom(self):
        # 2d's owner's line for "غرفة وصالة" now names a one-bedroom, in Arabic's own count (never "1 rooms").
        self.assertEqual(needs.noun_words("bedroom:1", "ar"), "الشقق بغرفة نوم واحدة")
        self.assertEqual(needs.noun_words("bedroom:2", "ar"), "الشقق بغرفتي نوم")
        self.assertEqual(needs.noun_words("bedroom:3", "ar"), "شقق 3 غرف نوم")
        self.assertEqual(needs.noun_words("bedroom:1", "en"), "a 1-bedroom flat")
        line = needs.options_sentence("ar", needs.detect(["غرفة وصالة"]))
        self.assertEqual(line, "لدينا خيارات كثيرة من الشقق بغرفة نوم واحدة في جميع أنحاء دبي.")


# B. Units, clusters, another area, a wish for a shop -------------------------------------------------------------


class UnitTests(SimpleTestCase):
    def test_unit_of_words_and_facts(self):
        cases = {
            "studio": tracks.STUDIO, "Studio apartment": tracks.STUDIO, "0 B/R": tracks.STUDIO, "1BR": tracks.ONE_BR,
            "1 bedroom": tracks.ONE_BR, "one bed": tracks.ONE_BR, "1bhk": tracks.ONE_BR, "غرفة وصالة": tracks.ONE_BR,
            "2BR": tracks.TWO_PLUS, "3 bedroom": tracks.TWO_PLUS, "1": tracks.ONE_BR, "0": tracks.STUDIO, "2": tracks.TWO_PLUS,
            "apartment": "", "flat": "", "villa": "", "shop": "", "": "", None: "", "a room": "",
        }
        for text, unit in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tracks.unit_of(text), unit)

    def test_the_labels_the_panel_and_alerts_read(self):
        self.assertEqual(tracks.label("rent", "studio"), "Rent · Studio")
        self.assertEqual(tracks.label("sale", "one_br"), "Sale · 1BR")
        self.assertEqual(tracks.label("rent", ""), "Rent")
        self.assertEqual(tracks.label("shop", "studio"), "Shop")
        self.assertEqual(tracks.label("", ""), "Not known yet")
        self.assertEqual(tracks.label("other", "two_plus"), "Other")


class ClusterTests(SimpleTestCase):
    NAMES = tracks.DEFAULT_CLUSTERS

    def test_a_cluster_said_as_a_place(self):
        cases = {
            "I need room\n1bhk Englund x cluster": ("England",),  # launch chat 49, misspelt
            "studio in Spain cluster": ("Spain",),
            "Spain T07 studio": ("Spain",),  # a building code after it
            "a studio in France please": ("France",),  # "in" before it, in words about a home
            "Morroco cluster or China cluster": ("Morocco", "China"),
            "Chinese cluster studio": ("China",),  # an adjective, right before "cluster"
            "استوديو في كلستر إنجلترا": ("England",),
            "انگلینڈ کلسٹر میں فلیٹ": ("England",),
            "स्पेन क्लस्टर में स्टूडियो": ("Spain",),
            "Greece K16 1BR": ("Greece",),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tracks.clusters_in([text], self.NAMES), expected)

    def test_a_nationality_or_another_place_is_never_a_cluster(self):
        for text in (
            "I am from China, I need a studio",  # spec §1.2
            "I'm from Russia, looking for a flat",
            "Chinese studio please",  # an adjective with no "cluster" after it
            "China",  # alone: nothing says it is the cluster
            "I am in China now, coming next month",  # no home, no International City
            "a studio near Emirates Mall",
            "studio near the Mall of the Emirates",
            "Emirates Hills villa",
            "my passport is Italy",
        ):
            with self.subTest(text=text):
                self.assertEqual(tracks.clusters_in([text], self.NAMES), ())

    def test_cluster_names_follow_the_settings(self):
        self.assertIn("Greece", tracks.cluster_names(None))  # the residential defaults name Greece (Q42 added it to shops)
        row = types.SimpleNamespace(
            residential_facts={"clusters": ["Spain", "<b>x</b>", 7]}, shops_facts={"clusters": ["France", "Greece"]}
        )
        self.assertEqual(tracks.cluster_names(row), ("Spain", "France", "Greece"))
        broken = types.SimpleNamespace(residential_facts="junk", shops_facts=None)
        self.assertEqual(
            tracks.cluster_names(broken), tuple(dict.fromkeys([*DEFAULT_RESIDENTIAL_FACTS["clusters"], *DEFAULT_SHOPS_FACTS["clusters"]]))
        )

    def test_international_city_by_name(self):
        for text in ("studio in International City", "intl city flat", "near Dragon Mart", "IC studio", "England cluster", "المدينة العالمية"):
            with self.subTest(text=text):
                self.assertTrue(tracks.names_ic(text))
        self.assertFalse(tracks.names_ic("I need a studio"))
        self.assertFalse(tracks.names_ic("picnic"))  # "ic" only as a whole word


class OtherAreaTests(SimpleTestCase):
    def test_another_area_said_with_a_home(self):
        self.assertTrue(tracks.other_area(["a studio in JVC"]))
        self.assertTrue(tracks.other_area(["flat in Deira chahiye"]))
        self.assertTrue(tracks.other_area(["أبحث عن استوديو في ديرة"]))
        self.assertTrue(tracks.other_area(["ok"], {"community": "Jumeirah Village Circle"}))

    def test_never_without_a_home_never_with_international_city(self):
        self.assertFalse(tracks.other_area(["I need a shop in Deira"]))  # no home: the model's tag decides (2d's other_area)
        self.assertFalse(tracks.other_area(["I live in Deira, I need a studio in International City"]))
        self.assertFalse(tracks.other_area(["studio near Dragon Mart, I work in JLT"]))
        self.assertFalse(tracks.other_area(["ok"], {"community": "International City"}))
        self.assertFalse(tracks.other_area(["ok"], {"community": "England Cluster"}))
        self.assertFalse(tracks.other_area(["ok"], {"community": "Phase 2"}))  # not on the list: never guessed


class ShopWishTests(SimpleTestCase):
    def test_a_wish_for_a_shop(self):
        for words in (
            ["I need a shop for my salon"], ["Yes, show me shops"], ["Shop"], ["a shop for rent"], ["dukaan chahiye"], ["محل"],
            ["دکان چاہیے"], ["दुकान चाहिए"], ["looking for a showroom"], ["I need a studio and a shop"],
        ):
            with self.subTest(words=words):
                self.assertTrue(tracks.wants_shop(words))

    def test_no_wish_for_a_shop(self):
        for words in (
            ["I want to buy a shop"],  # buying is another need (2d)
            ["I want to sell my shop"],
            ["No shop, I need a studio"],
            ["shop nahi chahiye"],
            ["I don't want a shop on the main road"],
            ["Interested"],
            ["Yes, still looking"],
            ["I need a studio"],
            [],
        ):
            with self.subTest(words=words):
                self.assertFalse(tracks.wants_shop(words))


# C. decide, step by step --------------------------------------------------------------------------------------------


class DecideStepTests(SimpleTestCase):
    def test_step_1_their_words_decide_first(self):
        d = decide(["I need an apartment studio"], stored="shop", template_kind="shop", lead={})  # its deal: the lead's
        self.assertEqual((d.track, d.unit, d.reason, d.switched, d.sorry), ("rent", "studio", tracks.WORDS, True, True))
        d = decide(["I need a shop for my salon"], stored="rent", stored_unit="studio")
        self.assertEqual((d.track, d.unit, d.reason, d.switched), ("shop", "", tracks.WORDS, True))
        # A rent word decides rent over a sale lead; buying decides sale (slice C: SALE_LIVE on; other with it off).
        d = decide(["studio for monthly rent"], lead={"deal": "sale", "unit": "studio"})
        self.assertEqual((d.track, d.deal, d.deal_from), ("rent", "rent", tracks.WORDS))
        d = decide(["I want to buy a studio"])
        self.assertEqual((d.track, d.unit, d.deal), ("sale", "studio", "sale"))
        with patch.object(tracks, "SALE_LIVE", False):
            self.assertEqual((decide(["I want to buy a studio"]).track, decide(["I want to buy a studio"]).deal), ("other", "sale"))

    def test_two_needs_at_once(self):
        # The stored track when it is one of them, else the first named.
        self.assertEqual(decide(["I need a shop and a studio"]).track, "shop")
        d = decide(["I need a studio and a shop"], lead={})
        self.assertEqual((d.track, d.reason), ("rent", tracks.BOTH))
        self.assertEqual(decide(["I need a studio and a shop"], stored="shop").track, "shop")
        self.assertEqual(decide(["I need a shop and a studio"], stored="rent", stored_unit="studio").track, "rent")
        # A room in the shop is the shop's own: one need.
        self.assertEqual(decide(["I need a shop with a room for my salon"]).reason, tracks.WORDS)

    def test_a_stored_rent_or_sale_track_is_refined_never_switched(self):
        d = decide(["Spain cluster please"], stored="rent", stored_unit="studio")
        self.assertEqual((d.track, d.unit, d.clusters, d.switched), ("rent", "studio", ("Spain",), False))
        with patch.object(tracks, "SALE_LIVE", True):
            d = decide(["1BR instead"], stored="sale", stored_unit="studio")
            self.assertEqual((d.track, d.unit, d.switched), ("sale", "one_br", False))  # a new unit, never a switch to rent
            d = decide(["actually I want to rent"], stored="sale", stored_unit="studio")
            self.assertEqual((d.track, d.unit, d.switched), ("rent", "studio", True))  # their rent word switches it
        d = decide(["how much is the rent?"], stored="shop")
        self.assertEqual((d.track, d.reason), ("shop", tracks.STORED))  # a shop customer's rent question is no home

    def test_step_2_the_models_tag(self):
        d = decide(["ok"], model_tag="wrong_need", fresh={"property_type": "studio"}, lead={})
        self.assertEqual((d.track, d.unit, d.reason), ("rent", "studio", tracks.TAG))
        self.assertEqual(decide(["ok"], model_tag="wrong_need", fresh={"property_type": "villa"}).track, "other")
        self.assertEqual(decide(["ok"], model_tag="other_area", fresh={"property_type": "studio"}).track, "other")
        self.assertEqual(decide(["ok"], model_tag="wants_to_buy", fresh={"property_type": "shop"}).track, "other")
        self.assertEqual(decide(["ok"], model_tag="wants_to_sell").track, "other")
        # The residential schema's tags (slice B), read with the bedrooms recorded.
        d = decide(["ok"], model_tag="wants_rent", fresh={"bedrooms": "1"})
        self.assertEqual((d.track, d.unit, d.deal_from), ("rent", "one_br", tracks.WORDS))
        self.assertEqual(decide(["ok"], model_tag="wants_shop").track, "shop")
        # Their words beat the tag.
        self.assertEqual(decide(["I need a shop"], model_tag="wrong_need", fresh={"property_type": "studio"}).track, "shop")

    def test_step_3_what_the_chat_knows(self):
        # Campaigns 448 and 449: 2d's stored need moves the chat to the rent track before the template does.
        facts = {"need": "home", "wanted": "a studio apartment", "property_type": "studio apartment"}
        d = decide(["ok"], facts=facts, template_kind="shop", lead={})
        self.assertEqual((d.track, d.unit, d.reason), ("rent", "studio", tracks.FACTS))
        self.assertEqual(decide(["ok"], facts={"need": "buy", "wanted": "to buy a shop"}).track, "other")
        self.assertEqual(decide(["ok"], facts={"need": "home", "wanted": "a room"}).track, "other")
        d = decide(["Thanks"], stored="rent", stored_unit="one_br")
        self.assertEqual((d.track, d.unit, d.reason), ("rent", "one_br", tracks.STORED))

    def test_step_4_the_lead_context(self):
        # It decides alone on the first answer to the mixed template...
        d = decide(["Yes, still looking"], template_kind="mixed", first_answer=True, lead=SPAIN_STUDIO)
        self.assertEqual((d.track, d.unit, d.clusters, d.reason), ("rent", "studio", ("Spain",), tracks.LEAD))
        self.assertEqual(decide(["Yes"], template_kind="mixed", first_answer=True, lead={"property": "shop"}).track, "shop")
        self.assertEqual(decide(["Yes"], template_kind="mixed", first_answer=True, lead={"unit": "two_plus"}).track, "other")
        # ...and for "I never asked about a shop", with an apology.
        d = decide(["I never asked about a shop"], template_kind="shop", lead=SPAIN_STUDIO)
        self.assertEqual((d.track, d.unit, d.sorry, d.reason), ("rent", "studio", True, tracks.LEAD))
        self.assertEqual(decide(["I never asked about a shop"], lead={}).track, "other")
        # It fills a missing unit or deal, never more.
        d = decide(["I need a flat"], lead={"unit": "one_br", "deal": "rent"})
        self.assertEqual((d.track, d.unit), ("rent", "one_br"))
        d = decide(["is the studio still there?"], lead={"unit": "studio", "deal": "sale"})
        self.assertEqual((d.track, d.deal, d.deal_from), ("sale", "sale", tracks.LEAD))  # a sale listing: a buyer
        with patch.object(tracks, "SALE_LIVE", False):
            self.assertEqual(decide(["is the studio still there?"], lead={"unit": "studio", "deal": "sale"}).track, "other")
        # Not the first answer, or a shops template: the lead decides nothing alone.
        self.assertEqual(decide(["Yes"], template_kind="mixed", first_answer=False, lead=SPAIN_STUDIO).track, "")
        self.assertEqual(decide(["Yes"], template_kind="shop", first_answer=True).track, "shop")

    def test_the_lead_is_read_only_when_a_step_needs_it(self):
        reads = []

        def lead():
            reads.append(1)
            return SPAIN_STUDIO

        source = tracks.lazy(lead)
        decide(["Interested"], lead=source)  # a shops template's yes: no step asks
        decide(["I need a shop"], lead=source)
        decide(["how much?"], stored="shop", lead=source)
        self.assertEqual(reads, [])
        tracks.decide(words=["I need a flat"], lead=source)  # the deal and the unit
        tracks.decide(words=["I need a flat"], lead=source)
        self.assertEqual(reads, [1])  # once per turn, however many steps ask
        self.assertEqual(tracks.decide(words=["I need a flat"], lead=lambda: 1 / 0).track, "rent")  # a failing read is no lead

    def test_step_5_the_template(self):
        self.assertEqual((decide(["Interested"], template_kind="shop").track, decide(["Interested"]).reason), ("shop", tracks.TEMPLATE))
        self.assertEqual(decide(["Yes"], template_kind="mixed", first_answer=True, lead={}).track, "")
        self.assertEqual(decide(["Yes"], template_kind="studio", lead={}).track, "rent")  # the brief's T1, if ever submitted

    def test_another_area_is_other(self):
        self.assertEqual(decide(["a studio in JVC"], lead={}).track, "other")
        self.assertEqual(decide(["ok"], stored="rent", stored_unit="studio", fresh={"community": "Dubai Marina"}).track, "other")
        self.assertEqual(decide(["a studio in International City"], lead={}).track, "rent")


class FromNeedTests(SimpleTestCase):
    """Spec §1.2's table, row by row."""

    def test_the_table(self):
        lead = {"deal": "rent"}
        rows = [
            (needs.Need(needs.HOME, "studio"), {}, ("rent", "studio")),
            (needs.Need(needs.HOME, "studio_apartment"), {}, ("rent", "studio")),
            (needs.Need(needs.HOME, "bedroom:1"), {}, ("rent", "one_br")),
            (needs.Need(needs.HOME, "bhk:1"), {}, ("rent", "one_br")),
            (needs.Need(needs.HOME, "flat"), {}, ("rent", "")),
            (needs.Need(needs.HOME, "apartment"), {}, ("rent", "")),
            (needs.Need(needs.HOME, "bhk"), {}, ("rent", "")),
            (needs.Need(needs.HOME, "bedroom:2"), {}, ("other", "two_plus")),
            (needs.Need(needs.HOME, "villa"), {}, ("other", "")),
            (needs.Need(needs.HOME, "room"), {}, ("other", "")),
            (needs.Need(needs.HOME, "bed_space"), {}, ("other", "")),
            (needs.Need(needs.HOME, "accommodation"), {}, ("other", "")),
            (needs.Need(needs.BUY, "shop"), {}, ("other", "")),
            (needs.Need(needs.BUY, ""), {}, ("other", "")),  # no noun on a shops template: 2d's
            (needs.Need(needs.SELL, "studio"), {}, ("other", "studio")),
            (needs.Need(needs.NEVER_ASKED, "", True), {}, ("other", "")),
        ]
        for need, kwargs, (track, unit) in rows:
            with self.subTest(need=need):
                d = tracks.from_need(need, {}, lead, **kwargs)
                self.assertEqual((d.track, d.unit), (track, unit))

    def test_a_buyer(self):
        with patch.object(tracks, "SALE_LIVE", True):
            self.assertEqual(tracks.from_need(needs.Need(needs.BUY, "studio")).track, "sale")
            self.assertEqual(tracks.from_need(needs.Need(needs.BUY, "flat")).track, "sale")
            # No noun: a residential lead, a residential chat or the mixed template says what they buy.
            d = tracks.from_need(needs.Need(needs.BUY, ""), lead={"unit": "one_br", "deal": "sale"})
            self.assertEqual((d.track, d.unit), ("sale", "one_br"))
            self.assertEqual(tracks.from_need(needs.Need(needs.BUY, ""), lead={}, template_kind="mixed").track, "sale")
            self.assertEqual(tracks.from_need(needs.Need(needs.BUY, ""), lead={}, stored="rent").track, "sale")
            self.assertEqual(tracks.from_need(needs.Need(needs.BUY, ""), lead={}).track, "other")
        d = tracks.from_need(needs.Need(needs.BUY, "studio"))
        self.assertEqual((d.track, d.deal), ("sale", "sale"))  # slice C is live
        with patch.object(tracks, "SALE_LIVE", False):
            d = tracks.from_need(needs.Need(needs.BUY, "studio"))
            self.assertEqual((d.track, d.deal), ("other", "sale"))  # with the flag off, 2d's invitation: nobody is lost

    def test_a_home_on_a_sale_lead_is_bought_unless_they_say_rent(self):
        with patch.object(tracks, "SALE_LIVE", True):
            self.assertEqual(tracks.from_need(needs.Need(needs.HOME, "studio"), lead={"deal": "sale"}).track, "sale")
            self.assertEqual(tracks.from_need(needs.Need(needs.HOME, "studio"), lead={"deal": "sale"}, rent_said=True).track, "rent")
            self.assertEqual(tracks.from_need(needs.Need(needs.HOME, "studio"), lead={"deal": "rent"}, stored="sale").track, "sale")
        self.assertEqual(tracks.from_need(None).track, "")


# D. The launch customers' own words, in five scripts -----------------------------------------------------------------


class LaunchWordsTests(SimpleTestCase):
    """2d's launch chats (test_who_the_customer_is.NeedsTests.LAUNCH) and the brief's words, as decide reads them."""

    CASES = {
        # English (chat ids of the launch review)
        "I need an apartment studio": ("rent", "studio"),  # 44
        "I need room\n1bhk Englund x cluster": ("rent", "one_br"),  # 49
        "Looking for a room": ("other", ""),  # 50
        "am looking for studio for monthly rent sir": ("rent", "studio"),  # 57
        "To buy": ("other", ""),  # 42
        "I want to purchase shop": ("other", ""),  # 42
        "Studio apartment with balcony": ("rent", "studio"),  # 107
        "I did not say any thing about shop.i just requesting only apartment rent": ("rent", ""),  # 114
        "I asked for studio": ("rent", "studio"),  # 132
        "AM LOOKING FOR STUDIO APARTMENTS": ("rent", "studio"),  # 136
        "I am looking residential room": ("other", ""),  # 105
        # Roman Urdu / Hindi
        "mujhe studio chahiye kiraye pe": ("rent", "studio"),
        "ek bedroom flat chahiye": ("rent", "one_br"),
        "shop chahiye mobile ke liye": ("shop", ""),
        # Arabic
        "أبحث عن استوديو للإيجار": ("rent", "studio"),
        "أريد غرفة وصالة": ("rent", "one_br"),
        "أريد محل للإيجار": ("shop", ""),
        # Urdu
        "مجھے سٹوڈیو چاہیے": ("rent", "studio"),
        "مجھے ایک بیڈروم فلیٹ چاہیے": ("rent", "one_br"),
        "مجھے دکان چاہیے": ("shop", ""),
        # Hindi
        "मुझे स्टूडियो चाहिए": ("rent", "studio"),
        "मुझे एक बेडरूम फ्लैट चाहिए": ("rent", "one_br"),
        "मुझे दुकान चाहिए": ("shop", ""),
    }

    def test_the_launch_and_the_brief_in_five_scripts(self):
        for text, (track, unit) in self.CASES.items():
            with self.subTest(text=text):
                d = tracks.decide(words=[text], template_kind="shop", lead={})
                self.assertEqual((d.track, d.unit), (track, unit))
        self.assertEqual(tracks.decide(words=["I need room\n1bhk Englund x cluster"], lead={}).clusters, ("England",))

    def test_the_traps(self):
        # spec §8: "photo studio"; "a room at the back"; "I live in a studio"; "1BR near my shop"; "I am from China".
        self.assertEqual(tracks.decide(words=["I need a shop for my photo studio"], lead={}).track, "shop")
        self.assertEqual(tracks.decide(words=["I need a shop with a room at the back"], lead={}).track, "shop")
        self.assertEqual(tracks.decide(words=["I live in a studio, I need a shop"], lead={}).track, "shop")
        d = tracks.decide(words=["I need a 1BR near my shop"], lead={})
        self.assertEqual((d.track, d.unit), ("rent", "one_br"))
        d = tracks.decide(words=["I am from China, I need a studio"], fresh={"community": "China"}, lead={})
        self.assertEqual((d.track, d.clusters), ("rent", ()))


# E. The mixed template's first yes -----------------------------------------------------------------------------------


class FirstYesTests(SimpleTestCase):
    def test_what_answers_the_yes(self):
        studio = tracks.Decision("rent", "studio", ("Spain",), reason=tracks.LEAD)
        self.assertEqual(tracks.first_yes(studio), tracks.OPEN_LEAD)
        self.assertEqual(tracks.first_yes(studio, for_client_known=True), "")  # the model asks the next thing
        self.assertEqual(tracks.first_yes(tracks.Decision("rent", "", reason=tracks.STORED)), tracks.WHAT_NEED)
        self.assertEqual(tracks.first_yes(tracks.Decision("shop", reason=tracks.LEAD)), tracks.FOR_WHOM)
        self.assertEqual(tracks.first_yes(tracks.Decision("", reason=tracks.TEMPLATE)), tracks.WHAT_NEED)
        self.assertEqual(tracks.first_yes(tracks.Decision("other", "studio", deal="sale", reason=tracks.LEAD)), tracks.WHAT_NEED)
        self.assertEqual(tracks.first_yes(tracks.Decision("other", reason=tracks.STORED)), "")  # a need the chat knows: 2d's

    def test_the_opener_in_six_languages(self):
        self.assertEqual(
            tracks.open_lead_text("en", "studio", ("Spain",)), "Great! Is the studio in Spain Cluster for yourself, or are you checking for a client?"
        )
        self.assertEqual(
            tracks.open_lead_text("en", "one_br", ()), "Great! Is the one-bedroom apartment for yourself, or are you checking for a client?"
        )
        self.assertEqual(tracks.open_lead_text("ar", "studio", ("Spain",)), "رائع! هل الاستوديو في كلستر إسبانيا لك شخصياً، أم تبحث عنه لعميل؟")
        self.assertEqual(
            tracks.open_lead_text("ar", "one_br", ("England",)), "رائع! هل الشقة بغرفة نوم واحدة في كلستر إنجلترا لك شخصياً، أم تبحث عنها لعميل؟"
        )
        self.assertEqual(
            tracks.open_lead_text("ur_latin", "studio", ("France",)),
            "Behtareen! Kya France Cluster wala studio aap ke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",
        )
        self.assertIn("رشیا کلسٹر والا اسٹوڈیو", tracks.open_lead_text("ur", "studio", ("Russia",)))
        self.assertIn("one-bedroom apartment aapke apne liye", tracks.open_lead_text("hi_latin", "one_br", ()))
        self.assertIn("ग्रीस क्लस्टर वाला वन-बेडरूम अपार्टमेंट", tracks.open_lead_text("hi", "one_br", ("Greece",)))
        self.assertTrue(tracks.open_lead_text("xx", "studio", ()).startswith("Great! Is the studio"))
        # The brand rule (Q29) and no person named (Q30): neither a name nor A7 in any of them.
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language=language):
                self.assertNotIn("A7", tracks.open_lead_text(language, "studio", ("Spain",)))
                self.assertNotIn("A7", rules.line("res_what_need", language))
                self.assertTrue(rules.line("res_what_need", language).endswith(("?", "؟")))

    def test_the_mixed_templates_taps(self):
        for label in ("Yes, still looking", "yes still looking", "Still looking"):
            with self.subTest(label=label):
                self.assertTrue(rules.is_positive_tap(label))
        self.assertFalse(rules.is_positive_tap("Not now"))
        self.assertTrue(rules.shops_opt_out("Stop messages"))
        self.assertTrue(rules.is_not_now("Not now"))

    def test_the_template_kind_of_a_message(self):
        mixed = types.SimpleNamespace(template_id=1, template=types.SimpleNamespace(name=ic_templates.MIXED_NAME))
        shops = types.SimpleNamespace(template_id=2, template=types.SimpleNamespace(name="intl_city_shops_reconnect"))
        self.assertEqual(ic_templates.kind_of(mixed), "mixed")
        self.assertEqual(ic_templates.kind_of(shops), "shop")
        self.assertEqual(ic_templates.kind_of(None), "shop")
        self.assertEqual(ic_templates.kind_of(types.SimpleNamespace(template_id=None, template=None)), "shop")
        self.assertEqual(ic_templates.NOT_SHOP_NAMES, (ic_templates.MIXED_NAME,))
