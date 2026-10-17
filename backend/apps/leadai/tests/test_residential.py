"""Batch 2e slice B, the rent flow's pure parts (assistant/residential.py; spec §2, §6.3, Appendix C; board T92):

- A. residential_facts: the confirmed defaults (Q27, Q28, Q41), validate's keys, facts_of's part-by-part fallback, the bands,
  what a reply may quote by track and unit;
- B. code's lines in six languages: the openers, the commission and VAT lines, the handover, the confirmations, every line;
- C. the guards on the model's words (spec §2.9), each from words a customer or the model wrote, each failing without it;
- D. the special cases (spec §2.10): paying now, a phone number asked for, rented elsewhere, PDPL's numbers and deletion;
- E. the full name (spec §2.6): known, read from a bare reply, refused, the gate;
- F. the rules before the model: the opener of a track entered, a voice note nobody heard, a document number, the neutral
  invitation.

No database: these are the functions the engine and the eval both call.
"""

import datetime as dt

from django.test import SimpleTestCase

from apps.leadai.assistant import hours, needs, residential, schema, tracks
from apps.leadai.models import DEFAULT_RESIDENTIAL_FACTS

DUBAI = hours.DUBAI
NOW = dt.datetime(2026, 10, 12, 14, 0, tzinfo=DUBAI)
LANGS = residential.LANGS


def model_answer(reply, **extra):
    """A residential answer as schema.normalize leaves it."""
    data = {"language": extra.pop("language", "en"), "segment": "residential_tenant", "send": True, "reply": reply}
    data["facts"] = extra.pop("facts", {})
    if "handover" in extra:
        data["handover"] = {"needed": True, "reason": extra.pop("handover")}
    if "opt_out" in extra:
        data["opt_out"] = extra.pop("opt_out")
    assert not extra, extra
    return schema.normalize(data, residential=True)


def settle(reply, new_texts, *, track="rent", unit="studio", earlier=(), **extra):
    answer = model_answer(reply, facts=extra.pop("facts", {}), **{k: v for k, v in extra.items() if k in ("handover", "opt_out", "language")})
    cut = residential.settle(answer, list(earlier), list(new_texts), track=track, unit=unit)
    return answer, cut


# A. The facts --------------------------------------------------------------------------------------------------------


class FactsTests(SimpleTestCase):
    def test_the_defaults_are_the_confirmed_figures(self):
        facts = residential.facts_of(None)
        self.assertEqual(facts, DEFAULT_RESIDENTIAL_FACTS)
        self.assertEqual(facts["rent"]["studio"], {"from": 29000, "to": 33000, "average": 31000})  # Q41
        self.assertEqual(facts["rent"]["one_br"], {"from": 40000, "to": 45000})  # Q27
        self.assertEqual(facts["rent"]["one_br_european"], {"from": 42000, "to": 43000})
        self.assertEqual(facts["sale"]["studio_morocco"], {"from": 310000, "to": 350000})
        self.assertEqual((facts["charges"]["vat_percent"], facts["charges"]["ejari"]), (5, 350))  # Q28, Q27

    def test_validate_names_each_wrong_part(self):
        raw = residential.facts_of(None)
        raw["rent"]["studio"] = {"from": 33000, "to": 29000, "average": 31000}
        raw["sale"]["one_br"] = {"from": "lots", "to": 550000}
        raw["european_clusters"] = ["Spain", "Atlantis"]
        raw["charges"]["chiller"] = "<b>free</b>"
        raw["clusters"] = [f"Cluster{index}" for index in range(13)] + ["Spain"]
        _, errors = residential.validate(raw)
        self.assertEqual(errors["residential_facts.rent.studio.to"], "Must not be smaller than the from.")
        self.assertEqual(errors["residential_facts.sale.one_br.from"], "Give a whole number above 0.")
        self.assertIn("residential_facts.charges.chiller", errors)
        self.assertIn("residential_facts.clusters", errors)
        studio = residential.facts_of(None)
        studio["rent"]["studio"] = {"from": 29000, "to": 33000, "average": 40000}
        self.assertEqual(residential.validate(studio)[1], {"residential_facts.rent.studio.average": "Must be between the from and the to."})
        self.assertEqual(residential.validate("not facts")[1], {"residential_facts": "Send the residential facts as an object."})
        self.assertEqual(residential.validate(residential.facts_of(None))[1], {})

    def test_a_broken_part_falls_back_alone(self):
        raw = residential.facts_of(None)
        raw["rent"]["one_br"] = {"from": 41000, "to": 46000}
        raw["rent"]["studio"] = {"from": "x"}
        raw["charges"]["ejari"] = -1
        facts = residential.facts_of(raw)
        self.assertEqual(facts["rent"]["one_br"], {"from": 41000, "to": 46000})  # the admin's, valid
        self.assertEqual(facts["rent"]["studio"], DEFAULT_RESIDENTIAL_FACTS["rent"]["studio"])  # broken: the default
        self.assertEqual(facts["charges"]["ejari"], 350)

    def test_the_bands(self):
        self.assertEqual(residential.rent_band("studio", ("Spain",))["average"], 31000)
        self.assertEqual(residential.rent_band("one_br", ("China",)), {"from": 40000, "to": 45000})
        self.assertEqual(residential.rent_band("one_br", ("Spain",)), {"from": 42000, "to": 43000})  # a European cluster
        self.assertEqual(residential.rent_band("one_br", ("Spain", "China")), {"from": 40000, "to": 45000})  # not all European
        self.assertEqual(residential.sale_band("studio", ("Morocco",)), {"from": 310000, "to": 350000})
        self.assertEqual(residential.sale_band("studio", ()), {"from": 330000, "to": 350000})
        self.assertEqual(residential.sale_band("one_br", ("Greece",)), {"from": 450000, "to": 550000})
        self.assertEqual(residential.commission("one_br"), {"from": 3000, "to": 3500})
        self.assertEqual(residential.rent_band("", ()), {})

    def test_what_a_reply_may_quote_is_its_track_and_unit_only(self):
        def numbers(text):
            from apps.leadai.assistant import filters

            return {value for value, _ in filters.numbers_in(text)}

        studio = numbers(residential.known_amounts(None, "rent", "studio"))
        self.assertTrue({29000, 33000, 31000, 2500, 3000, 350, 2000} <= studio)
        self.assertFalse({40000, 45000, 42000, 43000, 3500, 330000} & studio)
        one_br = numbers(residential.known_amounts(None, "rent", "one_br"))
        self.assertTrue({40000, 45000, 42000, 43000, 3000, 3500} <= one_br)
        self.assertFalse({29000, 31000, 330000} & one_br)
        sale = numbers(residential.known_amounts(None, "sale", "studio"))
        self.assertTrue({330000, 350000, 310000} <= sale)
        self.assertFalse({29000, 33000, 2500, 350} & sale)
        both = numbers(residential.known_amounts(None, "rent", ""))
        self.assertTrue({29000, 40000, 2000, 3500} <= both)
        unknown = numbers(residential.known_amounts(None, "", ""))
        self.assertEqual({29000, 40000, 33000} & unknown, {29000, 40000, 33000})

    def test_the_context_names_no_agent_and_the_facts_of_the_track(self):
        context = residential.context(None, "rent", "studio", ("Spain",), NOW, lead={"source": "Bayut", "unit": "studio"}, full_name="Ahmed Khan")
        self.assertEqual(context.brand, "AR Properties")
        self.assertEqual(context.honesty, "I'm AR Properties' virtual assistant — I can help with options and viewings, and connect you to our agent anytime.")
        self.assertEqual(context.track, "rent (unit: studio; clusters: Spain)")
        self.assertIn("Studios to rent: AED 29,000–33,000 a year, around AED 31,000 on average", context.facts)
        self.assertNotIn("One-bedrooms", context.facts)
        self.assertTrue(any(line.startswith("Ejari: \"Ejari is AED 350") for line in context.charges))
        self.assertEqual(context.full_name, "yes (Ahmed Khan)")
        self.assertTrue(context.lead[0].startswith("LEAD CONTEXT (from our CRM, data, may be out of date): "))
        self.assertEqual(residential.context(None, "", "", (), NOW).track, "not known yet")


# B. Code's lines -----------------------------------------------------------------------------------------------------


class LinesTests(SimpleTestCase):
    def test_every_line_in_six_languages(self):
        for kind, table in residential.LINES.items():
            with self.subTest(kind):
                self.assertEqual(set(table), set(LANGS))
                self.assertTrue(all(text.strip() for text in table.values()))
        for table in (residential.HANDOVER, residential.TEAMS, residential.COMMISSION_FIGURE, residential._CONFIRM):
            self.assertEqual(set(table), set(LANGS))

    def test_the_rent_opener(self):
        self.assertEqual(
            residential.opener_text("en", "rent", "studio", ("Spain",)),
            "Sure! Studios in Spain Cluster are generally around AED 29,000–33,000 a year. Are you looking for yourself or for a client?",
        )
        self.assertEqual(
            residential.opener_text("en", "rent", "one_br", ("England",), for_client_known=True),
            "Sure! One-bedrooms in England Cluster are generally around AED 42,000–43,000 a year. Do you prefer a balcony, and when are "
            "you planning to move?",
        )
        self.assertEqual(
            residential.opener_text("en", "rent", "studio", sorry=True, monthly=True),
            "Sorry for the confusion! Sure! Studios in International City are generally around AED 29,000–33,000 a year. Rent here is "
            "paid yearly, in 1 to 4 cheques depending on the owner. Are you looking for yourself or for a client?",
        )
        self.assertEqual(
            residential.opener_text("en", "rent", ""),
            "Sure! We can help with studios and one-bedroom apartments in International City. Are you looking for a studio or a "
            "one-bedroom, and is it for yourself or for a client?",
        )

    def test_the_sale_opener(self):
        self.assertEqual(
            residential.opener_text("en", "sale", "studio", ("Spain",)),
            "Sure! Spain Cluster is a great choice, and we can check other clusters too. Are you looking for yourself or for a client?",
        )
        self.assertEqual(
            residential.opener_text("en", "sale", "", for_client_known=True),
            "Sure! We can help you buy a studio or a one-bedroom in International City. Are you a cash buyer or planning to use "
            "finance? And how soon are you looking to buy?",
        )

    def test_the_openers_in_every_language_carry_the_band_and_a_question(self):
        for lang in LANGS:
            with self.subTest(lang):
                text = residential.opener_text(lang, "rent", "studio", ("Spain",))
                self.assertIn("29,000–33,000", text)
                self.assertTrue(any(mark in text for mark in "?؟"))
                self.assertIn(residential.cluster_words(lang, "Spain"), text)
        self.assertIn("كلستر إسبانيا", residential.opener_text("ar", "rent", "studio", ("Spain",)))
        self.assertIn("स्पेन क्लस्टर", residential.opener_text("hi", "rent", "studio", ("Spain",)))

    def test_the_commission_and_vat_lines(self):
        self.assertEqual(
            residential.commission_figure_line("en", "studio"),
            "For a studio, commission is normally around AED 2,000–2,500 plus 5% VAT, depending on the unit. You're welcome to see "
            "the flat first — we'll confirm every charge clearly before you decide.",
        )
        self.assertIn("AED 3,000–3,500", residential.commission_figure_line("en", "one_br"))
        self.assertNotIn("2,000", residential.commission_figure_line("en", "one_br"))
        both = residential.commission_figure_line("en", "")
        self.assertIn("AED 2,000–2,500 for a studio and AED 3,000–3,500 for a one-bedroom", both)
        self.assertEqual(
            residential.vat_line("en"), "5% VAT applies only to the agency commission. There is no VAT on the rent, the deposit, Ejari or DEWA."
        )

    def test_the_handover_names_no_person_and_gives_no_number(self):
        self.assertEqual(
            residential.handover_line("en"),
            "Sure, no problem. I've passed your details to our rental team, so you don't need to explain again. Our agent will reply "
            "to you here.",
        )
        self.assertIn("our sales team", residential.handover_line("en", "sale"))
        for lang in LANGS:
            text = residential.handover_line(lang)
            self.assertNotRegex(text, r"\d{6,}|Shoaib|Malik")

    def test_the_viewing_confirmation(self):
        start = dt.datetime(2026, 10, 19, 16, 0, tzinfo=DUBAI)
        text = residential.confirmation(
            "en", start, full_name="ahmed khan", office_address="Russia Cluster, Building V03, Shop 20, Dubai International City",
            maps_url="https://maps.app.goo.gl/u7xzyea9pPLpRxBD8",
        )
        self.assertEqual(
            text,
            "Perfect, Ahmed Khan! Your viewing is confirmed ✅\nDate: Monday 19 October\nTime: 4:00 PM\n"
            "Place: Russia Cluster, Building V03, Shop 20, Dubai International City\nhttps://maps.app.goo.gl/u7xzyea9pPLpRxBD8\n"
            "Our agent will meet you at the office and take you to the available apartments, a short drive away. See you soon!",
        )
        self.assertNotRegex(text, r"\b5 minutes\b|A7 Group")  # no travel time (brief Part 8), no office-sign brand (Q29)
        moved = residential.confirmation("en", start, full_name="Ahmed Khan", office_address="V03", rescheduled=True)
        self.assertTrue(moved.startswith("Done, Ahmed Khan! Your viewing is now on:"))
        meeting = residential.confirmation("en", start, full_name="Ahmed Khan", track="sale")
        self.assertIn("Your meeting is confirmed", meeting)
        self.assertTrue(meeting.endswith("Our agent will meet you at the office. See you soon!"))
        self.assertEqual(
            residential.confirmation("en", start, kind="call", full_name="Ahmed Khan"),
            "Perfect, Ahmed Khan! Your 5-minute call with our sales team is booked for Monday 19 October at 4:00 PM. We'll call you "
            "on this number. Speak soon!",
        )
        self.assertTrue(residential.confirmation("en", start).startswith("Perfect! Your viewing is confirmed"))

    def test_the_confirmations_in_six_languages(self):
        start = dt.datetime(2026, 10, 19, 16, 0, tzinfo=DUBAI)
        for lang in LANGS:
            for kind, track in (("visit", "rent"), ("visit", "sale"), ("call", "sale")):
                with self.subTest(lang=lang, kind=kind, track=track):
                    text = residential.confirmation(lang, start, kind=kind, full_name="Ahmed Khan", office_address="V03", track=track)
                    self.assertIn("Ahmed Khan", text)
                    self.assertIn("4:00 PM", text)
        self.assertIn("ممتاز أحمد", residential.confirmation("ar", start, full_name="أحمد خان")[:12])

    def test_code_lines_are_kept_by_the_no_repeat_guard(self):
        self.assertTrue(residential.is_fixed_line("Are you looking for yourself or for a client?"))
        self.assertTrue(residential.is_fixed_line(residential.line("res_full_name", "ar")))
        self.assertTrue(residential.is_fixed_line("Our agent will reply to you here."))
        self.assertFalse(residential.is_fixed_line("Spain Cluster is lovely."))


# C. The guards on the model's words ----------------------------------------------------------------------------------


class GuardTests(SimpleTestCase):
    def test_a_studio_reply_carries_no_one_bedroom_figure_even_from_the_campaign(self):
        # The mixed template names "one-bedrooms from around AED 40,000": a studio chat never hears it.
        answer, cut = settle("Studios are around AED 29,000–33,000 a year. One-bedrooms start from AED 40,000. Any cluster you prefer?", ["how much"])
        self.assertEqual(answer["reply"], "Studios are around AED 29,000–33,000 a year. Any cluster you prefer?")
        self.assertIn("other_unit", cut)
        answer, _ = settle("A one-bedroom is around AED 40,000–45,000 a year.", ["1br price?"], unit="one_br")
        self.assertIn("40,000", answer["reply"])
        # A deposit of AED 3,000 is no one-bedroom's commission: it stays on a studio chat.
        answer, cut = settle("The deposit is around AED 2,500–3,000, refundable.", ["deposit?"])
        self.assertNotIn("other_unit", cut)

    def test_the_wrong_deal(self):
        answer, cut = settle("You could also buy one for AED 330,000. Rent is around AED 31,000 on average.", ["price?"])
        self.assertEqual(answer["reply"], "Rent is around AED 31,000 on average.")
        self.assertIn("wrong_deal", cut)
        answer, cut = settle("Studios sell for AED 330,000–350,000. Renting is about AED 31,000.", ["price?"], track="sale")
        self.assertEqual(answer["reply"], "Studios sell for AED 330,000–350,000.")

    def test_only_code_speaks_of_commission_the_first_time_its_general_line(self):
        answer, cut = settle("There is no commission for you! Do you prefer a balcony?", ["Is there any commission?"])
        self.assertEqual(
            answer["reply"],
            "Our normal agency commission applies once you choose an apartment you like. The exact amount depends on the unit. Do "
            "you prefer a balcony?",
        )
        self.assertIn("commission", cut)

    def test_asked_again_or_for_a_number_the_units_figure(self):
        earlier = [("customer", "commission?"), ("assistant", residential.line("res_commission_first", "en"))]
        answer, _ = settle("Commission is half a month's rent.", ["How much is it exactly?", "the commission"], earlier=earlier)
        self.assertEqual(answer["reply"], residential.commission_figure_line("en", "studio"))
        answer, _ = settle("", ["What is the commission amount?"], unit="one_br")
        self.assertIn("AED 3,000–3,500", answer["reply"])
        self.assertNotIn("2,000", answer["reply"])

    def test_a_switch_from_shop_to_rent_between_two_commission_questions(self):
        from apps.leadai.assistant import claims

        earlier = [("customer", "What is your commission?"), ("assistant", claims.commission_line("en")), ("customer", "I need a studio")]
        answer, _ = settle("", ["And the commission for the studio?"], earlier=earlier)
        self.assertEqual(answer["reply"], residential.commission_figure_line("en", "studio"))
        self.assertEqual(residential.commission_answer("shop", "", [], ["commission?"]), claims.commission_line("en"))
        self.assertEqual(residential.commission_answer("sale", "studio", [], ["commission?"]), residential.line("res_commission_sale", "en"))

    def test_vat_is_codes_line_only(self):
        answer, cut = settle("Yes, 5% VAT applies on the rent too.", ["Is there VAT on the rent?"])
        self.assertEqual(answer["reply"], residential.vat_line("en"))
        self.assertEqual(cut, ["vat_words", "vat"])

    def test_no_shop_words_but_the_broker_question_and_the_documents_line_stay(self):
        reply = (
            "We also have shops near Dragon Mart. Are you looking for yourself or for a client? For a company contract, the trade "
            "licence and the signatory's documents are needed."
        )
        answer, cut = settle(reply, ["studio pls"])
        self.assertEqual(
            answer["reply"],
            "Are you looking for yourself or for a client? For a company contract, the trade licence and the signatory's documents are needed.",
        )
        self.assertIn("shop_words", cut)
        # needs.drop_shop_pitch, 2d's filter, would have cut both sentences that stay.
        self.assertEqual(needs.drop_shop_pitch(answer["reply"], needs.Need(needs.HOME, "studio"))[0], "")
        # On the not-known track, the question naming a shop stays; the shop types do not.
        answer, _ = settle("Our Type 1 shop is great. Are you looking for a shop, a studio or a one-bedroom?", ["hi"], track="", unit="")
        self.assertEqual(answer["reply"], "Are you looking for a shop, a studio or a one-bedroom?")

    def test_no_unit_is_ever_available(self):
        answer, cut = settle("Yes, the studio is still available. We have a studio in Spain Cluster ready to move.", ["is the studio still there?"])
        self.assertEqual(answer["reply"], "")
        self.assertFalse(answer["send"])
        self.assertIn("availability", cut)
        kept = "Options may be available in Spain Cluster. Our agent will show you the available apartments at the viewing."
        answer, cut = settle(kept, ["any studio?"])
        self.assertEqual(answer["reply"], kept)
        self.assertNotIn("availability", cut)

    def test_no_booked_or_sent_claim(self):
        answer, cut = settle("I've booked you for 5 PM. I have sent the photos.", ["5pm ok"])
        self.assertEqual(answer["reply"], "")
        self.assertIn("claim", cut)
        answer, cut = settle("It's not booked yet. May I have your full name?", ["5pm"])
        self.assertNotIn("claim", cut)
        answer = model_answer("I've booked you for 5 PM.")  # code booked it this turn: its own words are never cut
        self.assertEqual(residential.settle(answer, [], ["5pm"], track="rent", unit="studio", booked=True), [])

    def test_no_document_or_bank_ask(self):
        answer, cut = settle(
            "Please send your passport copy and Emirates ID here. Our agent collects the documents in person.", ["documents?"]
        )
        self.assertEqual(answer["reply"], "Our agent collects the documents in person.")
        self.assertIn("private_ask", cut)
        for ask in ("What is your salary?", "Can you share your IBAN?", "Please type the OTP you received.", "What's your Emirates ID number?"):
            self.assertTrue(residential.asks_private(ask), ask)
        self.assertFalse(residential.asks_private("Passport, UAE residence visa and Emirates ID; our agent collects them in person."))

    def test_no_screening(self):
        answer, cut = settle("Are you married? This building is family only. Do you prefer a balcony?", ["studio"])
        self.assertEqual(answer["reply"], "Do you prefer a balcony?")
        self.assertIn("screening", cut)
        self.assertTrue(residential.screens("Sorry, no bachelors."))
        self.assertTrue(residential.screens("What is your nationality?"))
        self.assertFalse(residential.screens("Will it be for yourself, your family, or company staff?"))

    def test_their_facts_only(self):
        # The CRM name the context shows is never their full name; their own words are.
        answer, dropped = settle("Great.", ["ok"], facts={"full_name": "Ahmed Khan"})
        self.assertIsNone(answer["facts"]["full_name"])
        self.assertIn("full_name", answer["facts_dropped"])
        answer, _ = settle("Great.", ["my name is ahmed khan"], facts={"full_name": "ahmed khan"})
        self.assertEqual(answer["facts"]["full_name"], "Ahmed Khan")
        answer, _ = settle("Great.", ["no budget given"], facts={"budget_aed": 31000})
        self.assertIsNone(answer["facts"]["budget_aed"])  # our average, never theirs
        answer, _ = settle("Great.", ["my budget is 31000"], facts={"budget_aed": 31000})
        self.assertEqual(answer["facts"]["budget_aed"], 31000)
        answer, _ = settle("Noted.", ["784-1990-1234567-1"], facts={"notes": ["my id 784-1990-1234567-1"]})
        self.assertEqual(answer["facts"]["notes"], ["my id [number removed]"])

    def test_the_schema_is_strict_and_has_no_bachelor(self):
        node = schema.RES_SCHEMA
        self.assertEqual(node["required"], list(node["properties"]))
        facts = node["properties"]["facts"]
        self.assertEqual(facts["required"], list(facts["properties"]))
        self.assertNotIn("bachelor", str(facts["properties"]["occupancy"]))
        self.assertIn("meet_at_building", node["properties"]["handover"]["properties"]["reason"]["enum"])
        self.assertEqual(node["properties"]["appointment"]["properties"]["place"]["enum"], ["office", "call", None])
        self.assertEqual(list(node["properties"])[:4], ["language", "segment", "facts", "need_tag"])
        for key in ("shop_type", "licence_kind", "trade_licence", "business_activity", "size_sqft"):
            self.assertNotIn(key, facts["properties"])
        normal = schema.normalize(
            {"facts": {"full_name": "Ahmed 2 Khan", "email": "Not An Email", "occupants": 70, "clusters": ["Spain", "Spain", "<x>"]}, "need_tag": "wants_shop"},
            residential=True,
        )
        self.assertEqual((normal["facts"]["full_name"], normal["facts"]["email"], normal["facts"]["occupants"]), (None, None, None))
        self.assertEqual((normal["facts"]["clusters"], normal["need_tag"]), (["Spain"], "wants_shop"))
        self.assertEqual(schema.normalize({"facts": {"email": "Ahmed@Mail.com"}}, residential=True)["facts"]["email"], "ahmed@mail.com")


# D. The special cases ------------------------------------------------------------------------------------------------


class SpecialCasesTests(SimpleTestCase):
    def test_a_handover_is_our_teams_line(self):
        answer, done = settle("Sure, I'll ask Shoaib to call you on 0501234567.", ["I want to talk to a person"], handover="customer_asked_human")
        self.assertEqual(done, ["handover"])
        self.assertEqual(residential.render(answer["res_line"], "en"), residential.handover_line("en"))
        answer, _ = settle("I'm so sorry about that. Our team will check.", ["you never called me back, worst service"], handover="complaint_or_upset")
        self.assertEqual(residential.render(answer["res_line"], "en"), f"I'm so sorry about that. {residential.handover_line('en')}")
        # A call they ask for is people.settle's (CALL_ASK), never this line.
        answer, done = settle("Sure.", ["please call me"], handover="customer_asked_human")
        self.assertNotIn("handover", done)

    def test_paying_now_gets_the_official_process_and_a_person(self):
        answer, done = settle("Sure, send AED 2,500 to IBAN AE07...", ["Can I pay the deposit online now?"])
        self.assertEqual(done, ["pay_online"])
        self.assertEqual(answer["handover"], {"needed": True, "reason": "legal_visa_licence_contract"})
        self.assertEqual(residential.render(answer["res_line"], "en"), residential.line("res_pay_online", "en"))
        self.assertFalse(residential.wants_to_pay(["I want to book it for tomorrow 5 pm"]))

    def test_no_number_ever(self):
        answer, done = settle("The owner is Mr. Ali, 0509998888.", ["Give me the owner's number please"])
        self.assertEqual(done, ["no_number"])
        text = residential.render(answer["res_line"], "en", office_address="Russia Cluster, Building V03", maps_url="https://maps.app.goo.gl/x")
        self.assertEqual(text, "Our team will reply to you here in this chat. You're also welcome at our office:\nRussia Cluster, Building V03\nhttps://maps.app.goo.gl/x")
        for words in ("send me your number", "what is the agent's number", "رقم الوكيل", "aap ka number do", "apna number bhejo"):
            self.assertTrue(residential.asks_for_number([words]), words)
        self.assertFalse(residential.asks_for_number(["my number is the same as this one"]))

    def test_rented_elsewhere_is_lost_with_our_line(self):
        answer, done = settle("Congrats!", ["We already found a flat, thanks"])
        self.assertEqual(done, ["already_rented"])
        self.assertEqual((answer["opt_out"], answer["lost_reason"], answer["opt_out_line"], answer["lost_ok"]), ("not_interested", "rented elsewhere", "res_already_rented", True))
        self.assertFalse(residential.rented_elsewhere(["I already rented a shop, now I need a studio"]))
        self.assertTrue(residential.rented_elsewhere(["not looking anymore"]))

    def test_the_numbers_pdpl_masks(self):
        self.assertTrue(residential.has_private_number("my id 784-1990-1234567-1"))
        self.assertTrue(residential.has_private_number("IBAN AE07 0331 2345 6789 0123 456"))
        self.assertTrue(residential.has_private_number("card 4111 1111 1111 1111"))
        self.assertFalse(residential.has_private_number("call me on 971501234567"))
        self.assertFalse(residential.has_private_number("4111 1111 1111 1112"))  # fails Luhn: no card
        self.assertEqual(residential.mask("card 4111 1111 1111 1111 ok"), "card [number removed] ok")

    def test_delete_my_data_in_four_languages(self):
        for words in ("Please delete my data", "remove my number from your list", "احذف بياناتي", "mera data delete karo", "मेरा डेटा डिलीट करो"):
            self.assertTrue(residential.asks_deletion(words), words)
        self.assertFalse(residential.asks_deletion("delete the photo please"))


# E. The full name ----------------------------------------------------------------------------------------------------


class FullNameTests(SimpleTestCase):
    def test_when_the_name_is_known(self):
        self.assertEqual(residential.full_name_known({"full_name": "ahmed khan"}), "Ahmed Khan")
        self.assertEqual(residential.full_name_known({"full_name": "Mr Khan"}), "")  # one name of a person
        self.assertEqual(residential.full_name_known({}, {"name": "Ahmed", "last_name": "Khan"}), "Ahmed Khan")
        self.assertEqual(residential.full_name_known({}, {"name": "Ahmed Khan"}), "")  # NAME alone: asked
        self.assertEqual(residential.full_name_known({"full_name": "Sara 2"}), "")

    def test_a_bare_name_after_our_ask(self):
        for words, name in (
            ("Ahmed Khan", "Ahmed Khan"), ("my name is ahmed khan", "Ahmed Khan"), ("mera naam Ahmed Raza hai", "Ahmed Raza"),
            ("محمد علي", "محمد علي"), ("No thanks", ""), ("Ok sure", ""), ("Tomorrow 5pm", ""), ("Why?", ""), ("Ali", ""),
            ("Great deal", ""), ("I will come at 6", ""),
        ):
            self.assertEqual(residential.name_from_reply(words), name, words)

    def test_a_refusal(self):
        for words in ("Why do you need my name?", "no", "I don't want to give my name", "naam nahi dunga"):
            self.assertTrue(residential.refuses_name([words]), words)
        self.assertFalse(residential.refuses_name(["Ahmed Khan"]))

    def test_the_gate(self):
        start = dt.datetime(2026, 10, 12, 18, 0, tzinfo=DUBAI)
        self.assertEqual(residential.full_name_gate(track="rent", action="confirm", when=start, facts={}), residential.ASK)
        self.assertEqual(residential.full_name_gate(track="rent", action="confirm", when=start, facts={"full_name": "Ahmed Khan"}), "")
        self.assertEqual(residential.full_name_gate(track="shop", action="confirm", when=start, facts={}), "")  # never on shop or other
        self.assertEqual(residential.full_name_gate(track="other", action="confirm", when=start, facts={}), "")
        answer = model_answer("Booked!")
        residential.hold_for_name(answer, start)
        self.assertEqual(answer["appointment"]["action"], "tentative")
        self.assertEqual((answer["appointment"]["date"], answer["appointment"]["time"]), ("2026-10-12", "18:00"))
        self.assertEqual(answer["res_line"], {"kind": "res_full_name"})

    def test_the_hold_lapses_thirty_minutes_after_the_ask_unless_refused(self):
        from apps.leadai.models import LeadAiAppointment

        held = LeadAiAppointment(status="tentative", starts_at=NOW, details={"held_for_name": True, "asked_at": NOW.isoformat()})
        self.assertFalse(residential.held_lapsed(held, NOW + dt.timedelta(minutes=29)))
        self.assertTrue(residential.held_lapsed(held, NOW + dt.timedelta(minutes=31)))
        held.details["name_refused"] = True
        self.assertFalse(residential.held_lapsed(held, NOW + dt.timedelta(hours=2)))


# F. The rules before the model -----------------------------------------------------------------------------------------


class PreModelRuleTests(SimpleTestCase):
    def decision(self, track="rent", unit="studio", clusters=(), sorry=False):
        return tracks.Decision(track, unit, clusters=clusters, deal=track if track in ("rent", "sale") else "", sorry=sorry)

    def test_the_opener_of_a_track_entered(self):
        spec = residential.pre_model_rule(self.decision(clusters=("Spain",)), {}, words=["studio in spain cluster"], entered=True, plain=True)
        self.assertEqual(spec, {"kind": "open", "track": "rent", "unit": "studio", "clusters": ["Spain"], "for_client_known": False, "sorry": False})
        self.assertIsNone(residential.pre_model_rule(self.decision(), {}, words=["studio"], entered=False, plain=True))
        self.assertIsNone(residential.pre_model_rule(self.decision(), {}, words=["studio, how much?"], entered=True, plain=False))
        sorry = residential.pre_model_rule(self.decision(), {}, words=["studio"], entered=True, plain=True, talked_shops=True)
        self.assertTrue(sorry["sorry"])
        monthly = residential.pre_model_rule(self.decision(), {}, words=["studio for monthly rent"], entered=True, plain=True)
        self.assertTrue(monthly["monthly"])

    def test_a_voice_note_nobody_heard_and_a_document_number(self):
        self.assertEqual(residential.pre_model_rule(self.decision(), {}, unheard=True), {"kind": "res_voice_failed"})
        self.assertEqual(residential.pre_model_rule(self.decision(), {}, typed=["784-1990-1234567-1"]), {"kind": "res_no_documents"})
        self.assertIsNone(residential.pre_model_rule(self.decision(), {}, unheard=True, handed_over=True))

    def test_the_neutral_invitation_after_a_second_unclear_answer(self):
        slots = [NOW + dt.timedelta(hours=1), NOW + dt.timedelta(hours=3)]
        spec = residential.pre_model_rule(self.decision("", ""), {}, words=["hmm"], plain=True, ours=2, slots=slots)
        self.assertEqual(spec["kind"], "res_invite_neutral")
        self.assertTrue(spec["invite"])
        self.assertIsNone(residential.pre_model_rule(self.decision("", ""), {}, words=["hmm"], plain=True, ours=1, slots=slots))
        text = residential.render(spec, "en", now=NOW)
        self.assertEqual(
            text,
            "We have many options in International City and across Dubai. Visit our office and we'll give you the best option. I can "
            "hold a slot for you today at 3:00 PM or 5:00 PM — which is better?",
        )

    def test_words_the_opener_leaves_to_the_model(self):
        for words in ("I need a studio, I want to talk to a person", "I need a studio for my client", "worst service, I need a studio"):
            self.assertTrue(residential.needs_model([words]), words)
        self.assertFalse(residential.needs_model(["I need an apartment studio"]))
