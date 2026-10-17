"""Batch 2e slice C, the sales flow (spec §3, §3.3; board T94; Q32, Q33, Q39, Q40): a buyer of a studio or a one-bedroom.

- A. the buyer's questions in their order (sales.next_questions, step_line), a question about what is known cut;
- B. the price never hidden, the bands of their unit only;
- C. no media first; a call asked for gets two free call slots; a buyer abroad gets the call;
- D. to our sales team: negotiation, the mortgage process, DLD fees, a legal question; the buyer's commission line (Q33);
- E. the call pool (calls.py): booked on the sale track only, one call per slot, and no office slot (Q40);
- F. the full name before a booking: the rent flow's gate (residential.full_name_gate, name_turn, hold_for_name) on a call;
- G. a buyer's turn end to end in engine._run_claimed: a call booked from their words or held for the full name, a taken
  slot, the photos, a DLD question, the commission, the price; no call_requested handover, no office pin, the alert;
- H. Bitrix (C40): Online 43 and the "Sales call" to-do on the booking, its move and its cancel;
- I. the reminder of a call and its taps;
- J. the eval mirrors the engine.

Each guard's test fails with that guard off (the scratchpad's sale/guards_off.py). The fakes are test_assistant's; the shops
chat is test_shops_playbook's (lead 555, Monday 12 October 2026, 14:00 Dubai).
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.catalog.models import WaTemplate
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import tasks
from apps.leadai.assistant import calls, crm, engine, filters, hours, reminders, sales, taps
from apps.leadai.assistant import residential
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import DEFAULT_RESIDENTIAL_FACTS, LeadAiAlert, LeadAiAppointment, LeadAiChat
from apps.leadai.tests.test_assistant import NOW, fake_send_template, fake_send_text
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_reminders_crm import BITRIX, FakeBitrix, RcBase, todo
from apps.leadai.tests.test_residential_turns import res_answer
from apps.leadai.tests.test_shops_playbook import shop_answer
from apps.leadai.tests.test_who_the_customer_is import NotAShopBase

DUBAI = hours.DUBAI
BUYER = {"for_client": False, "intent": "buy", "property_type": "studio", "need": "buy", "wanted": "to buy a studio"}
NAMED = {**BUYER, "full_name": "Ahmed Khan"}
CALL_BOOKED_5 = (
    "Perfect, Ahmed Khan! Your 5-minute call with our sales team is booked for Monday 12 October at 5:00 PM. We'll call you on this number. "
    "Speak soon!"
)
SLOTS_3_5 = "I can book the call for you today at 3:00 PM or 5:00 PM — which is better?"
FULL_NAME_ASK = "Great! May I have your full name for the booking?"
BUYER_LINE = (
    "Sure! To show you the best options for your budget, our sales team will do a quick 5-minute call with you first, so we share "
    "the right units instead of sending everything."
)
SALES_HANDOVER = "Sure, no problem. I've passed your details to our sales team, so you don't need to explain again. Our agent will reply to you here."
COMMISSION = "Our agent will go through all the costs with you on the call."


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=DUBAI)


def model(reply="", **extra):
    """A model answer on the sale track: RES_SCHEMA (the residential path, RES_SYSTEM's sale section)."""
    extra.setdefault("segment", "buyer")
    return res_answer(reply, **extra)


def normal(reply="", **extra):
    """The model's answer as the engine reads it (schema.normalize), for the pure functions."""
    from apps.leadai.assistant import schema

    return schema.normalize(model(reply, **extra).data, shops=True, residential=True)


# A. The buyer's questions in their order (brief Part 5B) ---------------------------------------------------------------


class QuestionOrderTests(SimpleTestCase):
    def test_five_questions_in_three_messages(self):
        self.assertEqual(sales.next_questions({}, "studio"), (sales.FOR_CLIENT,))
        facts = {"for_client": False}
        self.assertEqual(sales.next_questions(facts, "studio"), (sales.PAYMENT, sales.TIMELINE))
        facts["payment"] = "cash"
        self.assertEqual(sales.next_questions(facts, "studio"), (sales.TIMELINE,))  # what is known is skipped
        facts["buy_timeline"] = "within a month"
        self.assertEqual(sales.next_questions(facts, "studio"), (sales.STATUS, sales.PURPOSE))
        facts.update(occupancy_status="vacant", purpose="investment")
        self.assertEqual(sales.next_questions(facts, "studio"), ())
        self.assertEqual(sales.step(facts, "studio"), sales.PRICE)
        self.assertEqual(sales.step(facts, "studio", priced=True), "meeting")
        # "For myself" is known as False: a False is an answer.
        self.assertTrue(sales.known({"for_client": False}, sales.FOR_CLIENT))
        self.assertFalse(sales.known({"for_client": None}, sales.FOR_CLIENT))

    def test_a_one_bedroom_asks_the_balcony_in_question_4s_sentence(self):
        facts = {"for_client": False, "payment": "mortgage", "buy_timeline": "3 months"}
        self.assertEqual(sales.next_questions(facts, "one_br"), (sales.STATUS, sales.BALCONY, sales.PURPOSE))
        self.assertEqual(sales.next_questions({**facts, "balcony": "yes"}, "one_br"), (sales.STATUS, sales.PURPOSE))
        self.assertEqual(sales.next_questions(facts, "studio"), (sales.STATUS, sales.PURPOSE))  # a studio has no balcony question

    def test_the_step_line_says_what_to_ask_and_what_follows(self):
        line = sales.step_line({"for_client": False}, "studio")
        self.assertTrue(line.startswith("SALE STEP: ask now, in one message: whether they are a cash buyer"))
        self.assertIn("how soon they plan to buy", line)
        self.assertIn("Give the price at once if they ask it.", line)
        done = {"for_client": False, "payment": "cash", "buy_timeline": "now", "occupancy_status": "vacant", "purpose": "investment"}
        self.assertIn("give the price band of their unit", sales.step_line(done, "studio"))
        self.assertIn("two CALL SLOTS", sales.step_line(done, "studio", priced=True))

    def test_a_question_about_what_is_known_is_cut(self):
        reply = "Got it. Are you a cash buyer or planning to use finance? Do you prefer a rented unit or a vacant one?"
        cut, changed = sales.drop_known_questions(reply, {"payment": "cash"})
        self.assertEqual((cut, changed), ("Got it. Do you prefer a rented unit or a vacant one?", True))
        # Not known: it stays; a question that also asks something new stays.
        self.assertEqual(sales.drop_known_questions(reply, {})[1], False)
        mixed = "Are you a cash buyer, and do you want it for investment?"
        self.assertEqual(sales.drop_known_questions(mixed, {"payment": "cash"})[1], False)
        self.assertEqual(sales.drop_known_questions("Is it for yourself or for a client?", {"for_client": False})[0], "")


# B. The price ---------------------------------------------------------------------------------------------------------


class PriceTests(SimpleTestCase):
    def test_their_words_ask_the_price(self):
        for words in ("price?", "What is the price of a studio?", "How much is a one bedroom to buy?", "kitne ka hai", "كم السعر؟", "कितने का है",
                      "Just tell me the price and book"):
            with self.subTest(words):
                self.assertTrue(sales.asks_price([words]))
        for words in ("What is your commission?", "What is the DLD transfer fee?", "For myself", "Cash, within a month"):
            with self.subTest(words):
                self.assertFalse(sales.asks_price([words]))

    def test_the_band_of_their_unit_only(self):
        self.assertEqual(
            sales.price_line("en", "studio"),
            "Studios in International City are generally around AED 330,000–350,000, depending on the cluster and whether the unit is "
            "vacant or rented. In Morocco Cluster, they start from around AED 310,000.",
        )
        self.assertEqual(
            sales.price_line("en", "studio", ("Morocco",)),
            "Studios in Morocco Cluster are generally around AED 310,000–350,000, depending on whether the unit is vacant or rented.",
        )
        self.assertNotIn("Morocco", sales.price_line("en", "studio", ("Spain",)))
        one_br = sales.price_line("en", "one_br")
        self.assertIn("AED 450,000–550,000", one_br)
        self.assertNotIn("330,000", one_br)
        both = sales.price_line("en", "")
        self.assertIn("330,000–350,000", both)
        self.assertIn("450,000–550,000", both)
        # Never a rent figure (Q41's studio rent is 29,000-33,000).
        self.assertNotRegex(sales.price_line("en", "studio") + one_br + both, r"\b(?:29|33),000\b")

    def test_the_bands_follow_the_settings_and_every_language_carries_them(self):
        facts = {**DEFAULT_RESIDENTIAL_FACTS, "sale": {**DEFAULT_RESIDENTIAL_FACTS["sale"], "studio": {"from": 340000, "to": 360000}}}
        self.assertIn("AED 340,000–360,000", sales.price_line("en", "studio", (), facts))
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                values = {value for value, _ in filters.numbers_in(sales.price_line(language, "studio"))}
                self.assertEqual(values, {330000, 350000, 310000})

    def test_priced_and_the_known_amounts(self):
        self.assertTrue(sales.priced("Studios are around AED 330K.", "studio"))
        self.assertFalse(sales.priced("Our agent will share the details.", "studio"))
        self.assertFalse(sales.priced("One-bedrooms are around AED 450,000.", "studio"))  # not their unit's band
        self.assertEqual(sales.known_amounts("studio"), "310000 330000 350000")
        self.assertEqual(sales.known_amounts("one_br"), "450000 550000")

    def test_the_price_is_never_hidden(self):
        # The guard: "price?" answered with no figure gets code's band line before the reply's question.
        answer = normal("Our sales team will share all the details with you on a quick call. Are you a cash buyer or planning to use finance?")
        done = sales.settle(answer, facts=BUYER, texts=["price?"], said="price?", earlier=[], now=NOW, unit="studio")
        self.assertEqual(done, sales.PRICE)
        self.assertIn("AED 330,000–350,000", answer["reply"])
        self.assertTrue(answer["reply"].endswith("Are you a cash buyer or planning to use finance?"))
        # A reply that gives the band already is left as it is.
        answer = normal(f"{leadai_eval.STUDIO_PRICE} Are you a cash buyer?")
        self.assertEqual(sales.settle(answer, facts=BUYER, texts=["price?"], said="price?", earlier=[], now=NOW, unit="studio"), "")


# C. No media first; the call; a buyer abroad ---------------------------------------------------------------------------


class FirstStepsTests(SimpleTestCase):
    def test_photos_get_the_buyer_media_line_and_two_call_slots(self):
        said = "Can you send me photos of the studio?"
        answer = normal("Sure, here are the photos of the studio.")
        self.assertEqual(sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio"), sales.BUYER_MEDIA)
        self.assertEqual(sales.text(answer["sale"], "en", NOW), f"{BUYER_LINE} {SLOTS_3_5}")
        self.assertTrue(answer["invited_to_meeting"])
        self.assertEqual(answer["converted"], "sale")

    def test_a_buyer_abroad_gets_the_call_never_2ds_handover(self):
        answer = normal("Thank you. Our specialist will reply to you here.", handover="abroad_cannot_visit")
        when, done = sales.call_step(answer, None, appointment=None, said="I am in London now, I can't come to the office", now=NOW)
        self.assertEqual((when, done, answer["handover"]["needed"], answer.get("abroad_call")), (None, "", False, True))
        said = "I am in London now, I can't come to the office"
        self.assertEqual(sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio"), sales.ABROAD)
        text = sales.text(answer["sale"], "en", NOW)
        self.assertTrue(text.startswith("No problem! The best next step is a quick 5-minute call with our sales team"))
        self.assertTrue(text.endswith(SLOTS_3_5))
        self.assertNotIn("office", text)  # they cannot come

    def test_2ds_untag_took_the_abroad_handover_off_already(self):
        answer = normal("Thank you.")
        answer["need_dropped"] = "abroad_cannot_visit"
        sales.call_step(answer, None, appointment=None, said="I live in India", now=NOW)
        self.assertTrue(answer.get("abroad_call"))

    def test_the_models_open_when_becomes_two_free_call_slots(self):
        said = "Just tell me the price and book"
        answer = normal("Studios in International City are generally around AED 330,000–350,000. When would you like the 5-minute call with our sales team?")
        done = sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio")
        self.assertEqual(done, sales.MEETING)
        self.assertEqual(answer["reply"], f"Studios in International City are generally around AED 330,000–350,000. {SLOTS_3_5}")
        # A question about when they buy is no meeting: it stays.
        self.assertFalse(sales.asks_when_to_meet("When are you planning to buy?"))
        self.assertTrue(sales.asks_when_to_meet("Which suits you better, and what time?"))

    def test_a_buyer_who_asks_for_the_office_gets_office_slots_from_the_offices_pool(self):
        said = "I prefer to visit your office, when can I come?"
        answer = normal("Sure! When would you like to come to our office?")
        sales.settle(
            answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio", office_taken=[at(12, 15)], call_taken=[at(12, 15, 30)]
        )
        # The office's own pool: 3:00 PM is another client's visit; a call at 3:30 PM holds no office slot (Q40).
        self.assertEqual(answer["reply"], "Sure! I can hold a meeting at our office for you today at 3:30 PM or 5:30 PM — which is better?")

    def test_no_slots_once_they_refused_twice(self):
        said = "Just tell me the price and book"
        answer = normal("Studios are around AED 330,000–350,000. When would you like the call?")
        sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio", may_invite=False)
        self.assertNotIn("3:00 PM", answer["reply"])

    def test_a_buyers_want_is_kept_as_2d_keeps_it(self):
        answer = normal("Sure!")
        self.assertTrue(sales.record_need(answer, {}, "one_br"))
        facts = answer["facts"]
        self.assertEqual((facts["need"], facts["wanted"], facts["intent"], facts["property_type"]), ("buy", "to buy a 1-bedroom flat", "buy", "1-bedroom flat"))
        # Said again: no new want (no second alert to the team).
        self.assertFalse(sales.record_need(normal("Sure!"), {**BUYER, "wanted": "to buy a studio"}, "studio"))


# D. To our sales team; the commission (Q33) -----------------------------------------------------------------------------


class SalesHandoverTests(SimpleTestCase):
    def test_their_words_that_go_to_our_sales_team(self):
        cases = {
            "Can the owner do 300k for the studio?": sales.REASON_PRICE,
            "any discount?": sales.REASON_PRICE,
            "what is your best price?": sales.REASON_PRICE,
            "How does the mortgage process work if I buy?": sales.REASON_LEGAL,
            "Can I get a mortgage for this?": sales.REASON_LEGAL,
            "What is the DLD transfer fee?": sales.REASON_LEGAL,
            "Can I get golden visa if I buy?": sales.REASON_LEGAL,
            # Their answers to our questions are none.
            "mortgage": "",
            "I will take a mortgage": "",
            "I will pay through bank finance": "",
            "Cash, within a month": "",
            "For investment": "",
        }
        for words, reason in cases.items():
            with self.subTest(words):
                self.assertEqual(sales.handover_topic([words]), reason)

    def test_a_dld_question_is_handed_over_and_the_models_figure_never_goes(self):
        said = "What is the DLD transfer fee?"
        answer = normal("The DLD transfer fee is 4% of the price.")
        done = sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio")
        self.assertEqual(done, f"{sales.HANDOVER}:{sales.REASON_LEGAL}")
        self.assertEqual(answer["handover"], {"needed": True, "reason": sales.REASON_LEGAL})
        self.assertEqual(sales.text(answer["sale"], "en", NOW), SALES_HANDOVER)

    def test_the_buyers_commission_line_and_never_a_figure(self):
        said = "What is your commission?"
        answer = normal("Our commission is 2% of the price. Are you a cash buyer or planning to use finance?")
        self.assertEqual(sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio"), sales.COMMISSION)
        self.assertEqual(answer["reply"], f"{COMMISSION} Are you a cash buyer or planning to use finance?")
        # Asked, and the model said nothing on it: the line opens the reply.
        answer = normal("Are you a cash buyer?")
        sales.settle(answer, facts=BUYER, texts=[said], said=said, earlier=[], now=NOW, unit="studio")
        self.assertEqual(answer["reply"], f"{COMMISSION} Are you a cash buyer?")
        for language in ("ar", "ur_latin", "ur", "hi_latin", "hi"):
            self.assertNotEqual(sales.commission_line(language), COMMISSION)

    def test_the_handover_line_names_nobody_and_gives_no_number(self):
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                line = residential.handover_line(language, "sale")
                self.assertNotRegex(line, r"\d{5,}|Shoaib|Malik")
        self.assertIn("rental team", residential.handover_line("en", "rent"))


# E. The call pool (calls.py) ----------------------------------------------------------------------------------------


class CallPoolTests(NotAShopBase):
    def other_chat(self, wa_id="971509999999"):
        contact = Contact.objects.create(wa_id=wa_id, display_name="Other")
        conversation = Conversation.objects.create(number=self.number, contact=contact, session_expires_at=NOW + dt.timedelta(hours=20))
        LeadAiChat.objects.create(conversation=conversation, active=True)
        return conversation

    def test_the_pool_counts_other_buyers_calls_only(self):
        other = self.other_chat()
        LeadAiAppointment.objects.create(conversation=other, status="confirmed", place="call", starts_at=at(12, 17), details={"track": "sale"})
        held = self.other_chat("971508888888")
        LeadAiAppointment.objects.create(conversation=held, status="tentative", place="call", starts_at=at(12, 18), details={"track": "sale", "held_for_name": True})
        shop = self.other_chat("971507777777")
        # A shops chat's tentative call request (2d's call_requested) holds no call slot.
        LeadAiAppointment.objects.create(conversation=shop, status="tentative", place="call", starts_at=at(12, 19), details={})
        office = self.other_chat("971506666666")
        LeadAiAppointment.objects.create(conversation=office, status="confirmed", place="office", starts_at=at(12, 16))
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="call", starts_at=at(12, 15), details={"track": "sale"})
        self.assertEqual(sorted(calls.taken(self.conversation, NOW)), [at(12, 17), at(12, 18)])
        self.assertEqual(engine.taken_slots(self.conversation, NOW), [at(12, 16)])  # a call takes no office slot (Q40)

    def test_check_proposal_books_a_call_on_the_sale_track_only(self):
        proposal = {"action": "confirm", "place": "call", "date": "2026-10-12", "time": "17:00", "customer_words": "5 pm"}
        with self.assertRaises(hours.SlotError) as refused:
            engine.check_proposal(dict(proposal), None, NOW)
        self.assertEqual(refused.exception.code, "not_office")
        self.assertEqual(engine.check_proposal(dict(proposal), None, NOW, places=calls.PLACES), at(12, 17))

    def test_one_call_per_slot_and_no_office_slot(self):
        proposal = {"action": "confirm", "place": "call", "date": "2026-10-12", "time": "17:00", "customer_words": "5 pm"}
        with self.assertRaises(hours.SlotError) as refused:
            engine.check_proposal(dict(proposal), None, NOW, places=calls.PLACES, call_taken=[at(12, 17)], taken=[])
        self.assertEqual((refused.exception.code, refused.exception.alternatives), ("taken", [at(12, 16, 30), at(12, 17, 30)]))
        self.assertIn("our sales team takes one call per 30-minute slot", refused.exception.message)
        # An office visit at 5 PM takes no call slot (Q40), and a call none of the office's.
        self.assertEqual(engine.check_proposal(dict(proposal), None, NOW, places=calls.PLACES, taken=[at(12, 17)]), at(12, 17))
        office = {**proposal, "place": "office"}
        self.assertEqual(engine.check_proposal(office, None, NOW, places=calls.PLACES, call_taken=[at(12, 17)]), at(12, 17))

    def test_shape_leaves_a_buyers_call_a_booking(self):
        answer = normal("", action="confirm", place="call", date="2026-10-12", time="17:00")
        engine._shape(answer, calls.PLACES)
        self.assertEqual((answer["appointment"]["action"], answer["handover"]["needed"]), ("confirm", False))
        answer = normal("", action="confirm", place="call", date="2026-10-12", time="17:00")
        engine._shape(answer)  # any other track: 2d's call_requested, as before
        self.assertEqual((answer["appointment"]["action"], answer["handover"]["reason"]), ("tentative", "call_requested"))

    def test_the_rows_mark_survives_the_details_written_again(self):
        row = LeadAiAppointment(conversation=self.conversation, status="confirmed", place="office", details={})
        calls.mark(row)
        self.assertEqual((row.place, row.details), ("call", {"track": "sale"}))
        self.assertEqual(calls.kept_details({"budget_aed": 1}, row), {"budget_aed": 1, "track": "sale"})
        hold = LeadAiAppointment(conversation=self.conversation, status="tentative", place="office", details={"held_for_name": True})
        self.assertEqual(calls.kept_details({}, hold), {"held_for_name": True})
        visit = LeadAiAppointment(conversation=self.conversation, status="confirmed", place="office", details={})
        self.assertEqual(calls.kept_details({"a": 1}, visit), {"a": 1})

    def test_the_context_line_offers_free_call_slots(self):
        line = calls.slots_line(NOW, (), [at(12, 15)])
        self.assertTrue(line.startswith("CALL SLOTS (a 5-minute call with our sales team, one call per half hour; it takes no office slot"))
        self.assertIn("Mon 2026-10-12 15:30 (today 3:30 PM); Mon 2026-10-12 16:30 (today 4:30 PM)", line)  # an hour apart
        self.assertNotIn("15:00 (today", line)  # another buyer's


# F. The full name before a booking: the rent flow's gate on a buyer's call ---------------------------------------------


class FullNameTests(SimpleTestCase):
    def test_known_from_the_chat_or_the_lead(self):
        self.assertEqual(residential.full_name_known({"full_name": "ahmed khan"}), "Ahmed Khan")
        self.assertEqual(residential.full_name_known({"full_name": "Ahmed"}), "")
        self.assertEqual(residential.full_name_known({}, {"name": "Md Sumon", "last_name": "Mia"}), "Md Sumon Mia")
        self.assertEqual(residential.full_name_known({}, {"name": "Sumon"}), "")
        self.assertEqual(residential.full_name_known({"full_name": "Ahmed 123"}), "")

    def test_the_name_from_their_reply_after_our_ask(self):
        self.assertEqual(residential.name_from_reply("Ahmed Khan"), "Ahmed Khan")
        self.assertEqual(residential.name_from_reply("my name is ahmed khan"), "Ahmed Khan")
        for words in ("Yes please", "ok sure", "tomorrow 5 pm", "why?", "Ahmed"):
            with self.subTest(words):
                self.assertEqual(residential.name_from_reply(words), "")
        # Never unasked: name_turn reads a bare name only right after our ask (its ``asked``).
        answer = normal("Thank you.")
        step = residential.name_turn(answer, BUYER, None, held=None, asked=False, said="Ahmed Khan", now=NOW)
        self.assertEqual((step.full_name, answer["facts"]["full_name"]), ("", None))

    def test_the_gate_holds_a_call_at_its_place_and_books_it_once_the_name_comes(self):
        self.assertEqual(residential.full_name_gate(track="sale", action="confirm", when=at(12, 17), facts=BUYER), residential.ASK)
        answer = normal("", action="confirm", place="call", date="2026-10-12", time="17:00")
        residential.hold_for_name(answer, at(12, 17))
        self.assertEqual(
            (answer["appointment"]["action"], answer["appointment"]["place"], answer["hold_for_name"], answer["res_line"]["kind"]),
            ("tentative", "call", True, "res_full_name"),
        )
        held = LeadAiAppointment(status="tentative", place="call", starts_at=at(12, 17), details={"held_for_name": True, "track": "sale"})
        self.assertEqual(residential.held_of(held)["place"], "call")
        answer = normal("Thank you.")
        step = residential.name_turn(answer, BUYER, None, held=residential.held_of(held), asked=True, texts=["Ahmed Khan"], said="Ahmed Khan", now=NOW)
        self.assertEqual(
            (step.kind, step.when, answer["appointment"]["place"], answer["facts"]["full_name"]), ("book_held", at(12, 17), "call", "Ahmed Khan")
        )
        # Known: no gate; a shop chat has none.
        self.assertEqual(residential.full_name_gate(track="sale", action="confirm", when=at(12, 17), facts=NAMED), residential.BOOK)
        self.assertEqual(residential.full_name_gate(track="shop", action="confirm", when=at(12, 17), facts=BUYER), residential.BOOK)

    def test_a_held_call_gone_by_gets_two_free_call_slots(self):
        held = {"start": at(12, 11), "words": "11 am", "asks": 1, "place": "call"}  # 11:00 AM went by (NOW is 2:00 PM)
        answer = normal("Thank you.")
        step = residential.name_turn(answer, NAMED, None, held=held, asked=True, said="Ahmed Khan", now=NOW, taken=[at(12, 15)])
        self.assertEqual((step.kind, answer["sale"]["kind"]), ("held_gone", sales.CALL_SLOTS))
        self.assertEqual(sales.text(answer["sale"], "en", NOW), "Sure, our sales team can do a quick 5-minute call with you. I can book the call for you today at 3:30 PM or 5:30 PM — which is better?")

    def test_the_confirmations_name_nobody_and_carry_no_link_in_six_languages(self):
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                call = residential.confirmation(language, at(19, 16), kind="call", full_name="Ahmed Khan")
                self.assertIn("Ahmed Khan", call)
                self.assertIn("4:00 PM", call)
                self.assertNotRegex(call, r"https?://|meet\.google|@")
        self.assertEqual(
            residential.confirmation("en", at(19, 16), kind="call", full_name="Ahmed Khan"),
            "Perfect, Ahmed Khan! Your 5-minute call with our sales team is booked for Monday 19 October at 4:00 PM. We'll call you on this number. "
            "Speak soon!",
        )
        visit = residential.confirmation(
            "en", at(19, 16), kind="visit", full_name="Ahmed Khan", office_address="Russia Cluster, Building V03", maps_url="https://maps.x/y", track="sale",
        )
        self.assertEqual(
            visit,
            "Perfect, Ahmed Khan! Your meeting is confirmed ✅\nDate: Monday 19 October\nTime: 4:00 PM\nPlace: Russia Cluster, Building V03\nhttps://maps.x/y\n"
            "Our agent will meet you at the office. See you soon!",
        )
        self.assertEqual(sales.booking_text("en", at(19, 16), call=True, facts=NAMED), residential.confirmation("en", at(19, 16), kind="call", full_name="Ahmed Khan"))


# G. A buyer's turn, end to end ------------------------------------------------------------------------------------------


class SaleTurnTests(NotAShopBase):
    def buyer(self, **facts):
        self.set_state(track="sale", unit="studio", facts={**BUYER, **facts})

    def test_a_buyers_call_at_5_is_booked_in_the_call_pool_never_a_handover(self):
        # 2d interplay (spec §8): "can we do a call at 5" was 2d's call_requested handover; the model answers it so.
        self.buyer(full_name="Ahmed Khan")
        message = self.inbound("can we do a call at 5")
        outcome, _, crm_delay, _ = self.turn(message, [model("Sure, our agent will call you at 5.", handover="call_requested")])
        self.assertEqual(self.body(outcome), CALL_BOOKED_5)
        appointment = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual(
            (appointment.status, appointment.place, appointment.starts_at, appointment.details.get("track")), ("confirmed", "call", at(12, 17), "sale")
        )
        state = self.state()
        self.assertEqual((state.handed_over_at, state.handover_reason), (None, ""))
        self.assertFalse(Message.objects.filter(kind=Message.Kind.LOCATION).exists())  # no office pin for a call
        alerts = list(LeadAiAlert.objects.filter(kind="booked"))
        self.assertTrue(alerts)
        self.assertEqual(alerts[0].title, "Sales call: Ahmed Khan, Monday 12 October 2026, 5:00 PM")
        self.assertEqual(alerts[0].priority, "high")
        self.assertIn("Take it on the Lead AI screen, then call them on +971501234567.", alerts[0].text)
        self.assertFalse(LeadAiAlert.objects.filter(kind="handover").exists())
        crm_delay.assert_called_once()
        self.assertEqual(self.actions(message)["sale"], {"call": "booked"})

    def test_the_full_name_first_then_the_held_call_is_booked(self):
        self.buyer()
        first = self.inbound("can we do a call at 5")
        outcome, _, _, _ = self.turn(first, [model("Sure, our agent will call you at 5.", handover="call_requested")])
        self.assertEqual(self.body(outcome), FULL_NAME_ASK)
        held = LeadAiAppointment.objects.get(conversation=self.conversation)
        self.assertEqual(
            (held.status, held.place, held.starts_at, held.details.get("held_for_name"), held.details.get("track")),
            ("tentative", "call", at(12, 17), True, "sale"),
        )
        self.assertEqual(calls.taken(Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="9715000")), NOW), [at(12, 17)])
        self.later(2)
        second = self.inbound("Ahmed Khan", seconds_ago=10)
        outcome, _, _, _ = self.turn(second, [model("Thank you, Ahmed Khan.", facts={"customer_name": "Ahmed Khan"})])
        self.assertEqual(self.body(outcome), CALL_BOOKED_5)
        held.refresh_from_db()
        self.assertEqual((held.status, held.place, held.starts_at), ("confirmed", "call", at(12, 17)))
        self.assertEqual(self.state().facts["full_name"], "Ahmed Khan")
        self.assertEqual(self.actions(second)["full_name"], "book_held")

    def test_a_call_slot_another_buyer_holds_gets_the_two_nearest_free_call_slots(self):
        self.buyer(full_name="Ahmed Khan")
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509999999"))
        LeadAiAppointment.objects.create(conversation=other, status="confirmed", place="call", starts_at=at(12, 17), details={"track": "sale"})
        message = self.inbound("can we do a call at 5")
        outcome, _, _, _ = self.turn(message, [model("Sure, our agent will call you at 5.", handover="call_requested")])
        self.assertEqual(
            self.body(outcome), "Sorry, that time is already booked for another call. I can book the call for you today at 4:30 PM or 5:30 PM — which is better?"
        )
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation).exists())
        self.assertIsNone(self.state().handed_over_at)

    def test_an_office_visit_takes_no_call_slot(self):
        self.buyer(full_name="Ahmed Khan")
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509999999"))
        LeadAiAppointment.objects.create(conversation=other, status="confirmed", place="office", starts_at=at(12, 17))
        outcome, _, _, _ = self.turn(self.inbound("can we do a call at 5"), [model("Sure.", handover="call_requested")])
        self.assertEqual(self.body(outcome), CALL_BOOKED_5)

    def test_the_models_own_call_booking_is_the_call_pools(self):
        self.buyer(full_name="Ahmed Khan")
        self.ours(SLOTS_3_5, minutes_ago=3)
        outcome, _, _, _ = self.turn(self.inbound("5 pm works"), [model("", action="confirm", place="call", date="2026-10-12", time="17:00")])
        self.assertEqual(self.body(outcome), CALL_BOOKED_5)
        self.assertEqual(LeadAiAppointment.objects.get(conversation=self.conversation).place, "call")

    def test_a_plain_yes_to_two_call_slots_books_neither(self):
        self.buyer(full_name="Ahmed Khan")
        self.ours(SLOTS_3_5, minutes_ago=3)
        outcome, _, _, _ = self.turn(self.inbound("Yes"), [model("", action="confirm", place="call", date="2026-10-12", time="15:00")])
        self.assertEqual(self.body(outcome), "Which time suits you better for the call: today at 3:00 PM or 5:00 PM?")
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation).exists())

    def test_a_call_with_no_time_gets_two_free_call_slots(self):
        self.buyer(full_name="Ahmed Khan")
        outcome, _, _, _ = self.turn(self.inbound("Can someone call me?"), [model("Sure, our agent will call you shortly.", handover="call_requested")])
        self.assertEqual(self.body(outcome), f"Sure, our sales team can do a quick 5-minute call with you. {SLOTS_3_5}")
        self.assertIsNone(self.state().handed_over_at)

    def test_photos_get_the_buyer_media_line_never_a_media_step(self):
        self.buyer()
        outcome, _, _, _ = self.turn(self.inbound("Can you send me photos of the studio?"), [model("Sure, here are the photos.")])
        self.assertEqual(self.body(outcome), f"{BUYER_LINE} {SLOTS_3_5}")
        self.media_delay.assert_not_called()
        self.assertEqual(self.state().invites, 1)

    def test_a_dld_question_goes_to_our_sales_team(self):
        self.buyer()
        outcome, _, _, _ = self.turn(self.inbound("What is the DLD transfer fee?"), [model("The DLD transfer fee is 4% of the price.")])
        self.assertEqual(self.body(outcome), SALES_HANDOVER)
        state = self.state()
        self.assertEqual((state.handed_over_at, state.handover_reason), (NOW, sales.REASON_LEGAL))
        self.assertTrue(LeadAiAlert.objects.filter(kind="handover").exists())

    def test_the_commission_and_the_price_on_a_buyers_turn(self):
        self.buyer()
        outcome, _, _, _ = self.turn(
            self.inbound("What is your commission?"), [model("Our commission is 2% of the price. Are you a cash buyer or planning to use finance?")]
        )
        self.assertEqual(self.body(outcome), f"{COMMISSION} Are you a cash buyer or planning to use finance?")
        self.later(3)
        outcome, _, _, _ = self.turn(self.inbound("price?", seconds_ago=10), [model("Our agent will share the details on the call. Are you a cash buyer?")])
        self.assertIn("AED 330,000–350,000", self.body(outcome))  # code's band line passes the reply filter (the sale amounts)

    def test_two_questions_go_to_a_buyer(self):
        self.buyer()
        reply = "Perfect. Are you a cash buyer or planning to use finance? And how soon are you looking to buy?"
        outcome, _, _, _ = self.turn(self.inbound("For myself"), [model(reply)])
        self.assertEqual(self.body(outcome), reply)

    def test_a_shop_customers_call_request_is_still_2ds(self):
        self.set_state(track="shop", facts={"for_client": False, "business_activity": "mobile phones"})
        outcome, _, _, _ = self.turn(self.inbound("Please call me at 5"), [shop_answer("Sure, our agent will call you at 5.", handover="call_requested")])
        self.assertEqual(self.state().handover_reason, "call_requested")
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation, status="confirmed").exists())


# H. Bitrix (C40) ------------------------------------------------------------------------------------------------------


class SubjectBitrix(FakeBitrix):
    """FakeBitrix whose to-dos have a subject: crm.activity.list reads its filter, and the tool's booking action moves the
    newest open to-do of the booking's own subject (C40)."""

    def __init__(self, **kwargs):
        self.subjects = kwargs.pop("subjects", {})
        super().__init__(**kwargs)

    def __call__(self, method, payload=None):
        if method == "crm.activity.list":
            self.calls.append((method, payload))
            subject = payload["filter"].get("SUBJECT")
            ids = sorted((i for i, t in self.todos.items() if not t["done"] and self.subjects.get(i, "Viewing/Meeting") == subject), reverse=True)
            return [{"ID": str(i)} for i in ids]
        return super().__call__(method, payload)

    def tool(self, body):
        subject = (body.get("booking") or {}).get("todo_subject", "Viewing/Meeting")
        others = {i: t for i, t in self.todos.items() if self.subjects.get(i, "Viewing/Meeting") != subject}
        for i in others:
            self.todos.pop(i)
        try:
            answer = super().tool(body)
        finally:
            self.todos.update(others)
        if answer.get("todo_id"):
            self.subjects.setdefault(answer["todo_id"], subject)
        return answer


@override_settings(**BITRIX)
class CallCrmTests(RcBase):
    def call(self, **fields):
        defaults = dict(status="confirmed", place="call", starts_at=at(13, 17), customer_name="Ahmed Khan", crm_entity="lead", crm_id=555,
                        details={"track": "sale"})
        defaults.update(fields)
        return LeadAiAppointment.objects.create(conversation=self.conversation, **defaults)

    def test_the_booking_body_of_a_call(self):
        appointment = self.call()
        body = crm.booking_body(555, appointment, "confirmed")
        self.assertEqual(
            (body["booking"]["mode"], body["booking"]["todo_subject"], body["booking"]["meeting_at"]), (43, "Sales call", "2026-10-13T17:00:00+04:00")
        )
        self.assertEqual(crm.booking_body(555, appointment, "cancelled")["booking"], {"event": "cancelled", "todo_subject": "Sales call"})
        visit = LeadAiAppointment(status="confirmed", place="office", starts_at=at(13, 17), details={})
        self.assertEqual(crm.booking_body(555, visit, "confirmed")["booking"], {"event": "confirmed", "meeting_at": "2026-10-13T17:00:00+04:00", "mode": 42})

    def test_a_calls_booking_moves_only_a_sales_call_todo_never_a_persons_viewing(self):
        bitrix = SubjectBitrix(todos={700: todo("2026-10-15T15:00:00+04:00")})  # a person's open "Viewing/Meeting"
        appointment = self.call()
        with patch("apps.crmlink.client.call", side_effect=bitrix), patch("apps.leadai.assistant.crm_fields.post", side_effect=bitrix.tool):
            tasks.sync_appointment_crm(appointment.pk, "confirmed", False, 1)
        booking = [body for body in bitrix.posted if body.get("booking")]
        self.assertEqual(len(booking), 1)
        self.assertEqual((booking[0]["booking"]["mode"], booking[0]["booking"]["todo_subject"]), (43, "Sales call"))
        self.assertEqual(bitrix.todos[700]["deadline"], "2026-10-15T15:00:00+04:00")  # the person's to-do kept its time
        appointment.refresh_from_db()
        self.assertEqual(appointment.crm_todo_id, 901)
        lists = [payload["filter"]["SUBJECT"] for method, payload in bitrix.calls if method == "crm.activity.list"]
        self.assertEqual(lists, ["Sales call"])


# I. The reminder of a call, and its taps --------------------------------------------------------------------------------


class CallReminderTests(RcBase):
    def call(self):
        start = NOW + dt.timedelta(minutes=29)
        return self.booked(starts_at=start, place="call", details={"track": "sale"})

    def test_inside_the_window_it_says_our_sales_team_calls_them(self):
        self.call()
        route, send = self.send_due()
        self.assertEqual(route, "buttons")
        self.assertEqual(send.call_args.args[2], "Hi Ahmed, a reminder of your 5-minute call with our sales team today at 2:29 PM. We'll call you on this number.")

    def test_outside_the_window_the_approved_reminder_names_this_number(self):
        self.call()
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=NOW - dt.timedelta(minutes=1))
        WaTemplate.objects.create(
            waba_business_id="waba1", name=reminders.TEMPLATE_NAME, language="en", category="UTILITY", status=WaTemplate.Status.APPROVED,
            components=[{"type": "BODY", "text": "Hi {{1}}, a reminder of your meeting today at {{2}} at {{3}}"}],
        )
        pk, claimed, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template) as send:
            self.assertEqual(reminders.send(pk, claimed, start), "template")
        self.assertEqual(send.call_args.args[3]["3"], "this number (our team will call you)")

    def test_on_my_way_on_a_calls_reminder_is_ready_for_the_call(self):
        appointment = self.call()
        tap = self.session_tap(reminders.button_id(appointment, "on_my_way"))
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
            taps.handle(tap.pk)
        self.assertEqual(Message.objects.get(payload__source="leadai_tap").body, "Perfect, our sales team will call you shortly on this number.")
        self.assertTrue(LeadAiAlert.objects.filter(title="Ahmed Khan is ready for the call").exists())

    def test_need_to_reschedule_on_a_call_gets_two_free_call_slots(self):
        from apps.campaigns.models import Campaign
        from apps.leadai import lane

        lane.mark_campaign(Campaign.objects.get(), playbook=lane.IC_SHOPS)
        appointment = self.call()
        other = Conversation.objects.create(number=self.number, contact=Contact.objects.create(wa_id="971509999999"))
        LeadAiAppointment.objects.create(conversation=other, status="confirmed", place="call", starts_at=at(12, 15), details={"track": "sale"})
        tap = self.session_tap(reminders.button_id(appointment, "reschedule"), title="Need to Reschedule")
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
            taps.handle(tap.pk)
        body = Message.objects.get(payload__source="leadai_tap").body
        self.assertEqual(body, "Sure. I can hold a slot for you today at 3:30 PM or 5:30 PM — which is better?")  # 3:00 PM is another buyer's


# J. The eval mirrors the engine ----------------------------------------------------------------------------------------


class SaleEvalTests(SimpleTestCase):
    def run_scenario(self, scenario_id, completion=None):
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion or RIGHT[scenario_id]):
            return leadai_eval.run_once(scenario, scenario_id)

    def test_the_sale_scenarios_cover_spec_8s_sales_group(self):
        ids = {s.id for s in leadai_eval.SCENARIOS if s.id.startswith("shops-sale-")}
        for wanted in (
            "shops-sale-first-message", "shops-sale-cash-and-when", "shops-sale-rented-or-vacant", "shops-sale-price-early", "shops-sale-price-morocco", "shops-sale-price-1br",
            "shops-sale-price-and-book", "shops-sale-photos", "shops-sale-call-booked", "shops-sale-call-full-name-first", "shops-sale-call-name-given", "shops-sale-call-at-5",
            "shops-sale-office-meeting", "shops-sale-negotiation", "shops-sale-mortgage", "shops-sale-dld-fee",
        ):
            self.assertIn(wanted, ids)

    def test_the_eval_books_the_call_as_the_engine_does(self):
        run = self.run_scenario("shops-sale-call-at-5")
        self.assertEqual((run.failures, run.when, run.answer["appointment"]["place"], run.out), ([], at(12, 17), "call", CALL_BOOKED_5))

    def test_a_wrong_answer_fails_a_sale_scenario(self):
        run = self.run_scenario("shops-sale-office-meeting", completion=RIGHT["shops-sale-photos"])
        self.assertTrue(run.failures)
        run = self.run_scenario("shops-sale-cash-and-when", completion=RIGHT["shops-sale-rented-or-vacant"])
        self.assertIn("does not ask cash or finance", run.failures)
        # The first plain message is code's opener (res_open_sale on the residential path): no model answer changes it.
        run = self.run_scenario("shops-sale-first-message", completion=RIGHT["shops-sale-cash-and-when"])
        self.assertEqual((run.failures, run.out_by, run.answer["res_line"]["kind"]), ([], leadai_eval.CODE, "open"))
