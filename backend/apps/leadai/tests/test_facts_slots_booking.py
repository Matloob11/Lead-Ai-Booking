"""Batch 2d, the launch fixes (2026-10-15): facts, slots and booking (launch review issues 5, 6, 12, 13, 16, 17, 22, 24).

What went wrong live, and what each test proves with the launch chats' own words (chat_<id>.json of the review) and the
model's live answers rebuilt from them; each fails without its guard (the patched-out cases show it):

- A. facts SHOP FACTS lacks (chats 96, 91, 59, 78; issue 5): no shop's building, side or unit, no food use allowed, no
  sale, no deposit, no other cost; our office's address is ours, never a shop's; Matloob's commission line (Q24);
- B. slots (chats 100, 59, 62, 96, 88; issue 17): an hour ahead at least, an hour apart, never past, in code's lines and
  in the model's own words;
- C. a same-day window (chat 96; issue 6): "barah saadhay barah baje ja ke check kar loon ga" is booked at its start;
- D. the price (chats 100, 59; issue 12): our lowest type, honestly, never the discount line; a budget below it offers
  a colleague;
- E. a tap with typed words (chats 81, 88; issue 13): the tap keeps its step and the words are answered;
- F. the size and price table said again (chat 91; issue 16);
- G. the invitation count and our labelled location (chats 81, 96, 88, 119; issue 24);
- H. discovery before a second invitation (chats 62, 88, 91, 96; issue 22);
- I. the eval's scenarios, with the live answers;
- J. what a replay of every live reply through engine.settle found in the guards above (chats 42, 59, 62, 96): an answer
  about our own figures cut as the table, a second "Good question", a "Which is better?" left with no offer, our opening
  hours read as a slot, our office's own unit read as a shop's, and a third invitation in words of no visit.

The fakes are test_assistant's: the clock is Monday 12 October 2026 (14:00 Dubai unless a test sets the live hour); the
chat is lead 555's. Chat 96's voice notes are not in the export: their words are rebuilt from our replies, the notes and
appointment 18 (his own "barah saadhay barah baje ja ke check kar loon ga" among them), as the eval's CHAT_96 does.
"""

import datetime as dt
import re
from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.inbox.models import Message
from apps.leadai import lane
from apps.leadai.assistant import claims, engine, filters, hours, offers, people, prompt, rules, shop_flow, shops
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import (
    DEFAULT_OFFICE_ADDRESS,
    DEFAULT_SHOPS_FACTS,
    LeadAiAlert,
    LeadAiAppointment,
    LeadAiSettings,
    LeadAiTranscript,
)
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_gate_2b_guards import normal, run_eval
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, at, shop_answer

ADDRESS = DEFAULT_OFFICE_ADDRESS
MAPS = "https://maps.app.goo.gl/u7xzyea9pPLpRxBD8"
KNOWN = shops.facts_block(DEFAULT_SHOPS_FACTS)
LOCATED = f"{offers.LOCATION_LABEL['en']} {MAPS}"
UNKNOWN_UR = claims.unknown_line("ur_latin")
COMMISSION_EN = claims.commission_line("en")

# The live claims (issue 5), with our address as the model reads it now (Building V03).
CLAIM_96 = leadai_eval.CLAIM_96
SIDE_96 = leadai_eval.SIDE_96
FOOD_91 = leadai_eval.FOOD_91
LIVE_59 = leadai_eval.CHAT_59[5][1]  # chat 59's live answer to "give me full details including rent security"
DEPOSIT_59 = "Rent security is usually a deposit, and payment is in 1 to 4 cheques."  # its first sentence
NO_COMMISSION_78 = leadai_eval.NO_COMMISSION_78
TABLE_91 = leadai_eval.TABLE_91
# The live slots (issue 17).
SLOTS_100 = leadai_eval.DISCOUNT_100  # 12:43, "today at 1:00 PM or 1:30 PM"
NEW_ONE_62 = leadai_eval.NEW_ONE_62  # 10:27, "today at 11:00 AM or 11:30 AM"
LICENCE_SLOTS_88 = (
    "No problem, many tenants open a new licence. Our agent will guide you through the process. I can hold a slot for you today at "
    "11:30 AM or 12:00 PM — which is better?"
)  # 10:33
WINDOW_WORDS = "barah saadhay barah baje ja ke check kar loon ga"
SHOP_FACTS_96 = leadai_eval.FACTS_96


def monday(hour, minute=0):
    return at(12, hour, minute)


_OFFER_SLOTS = filters.offer_slots


@contextmanager
def uncounted_rewrite():
    """The code before issue 24's count: an open "when" still becomes code's two slots, and is never counted."""
    rewrite = lambda text, line: (_OFFER_SLOTS(text, line)[0], False)  # noqa: E731
    with patch.object(filters, "offer_slots", side_effect=rewrite), patch.object(offers, "count_invitation", return_value=False):
        yield


class Base(ShopsBase):
    """The tests' shops chat, its Maps link and pin set as live, the alerts listed to Matloob (2311)."""

    def setUp(self):
        super().setUp()
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url=MAPS, office_latitude=25.169639, office_longitude=55.404667)
        self.list_matloob()

    def at_clock(self, hour, minute=0):
        self.clock.return_value = monday(hour, minute)

    def voice(self, words, seconds_ago=30):
        message = self.inbound("", kind=Message.Kind.AUDIO, seconds_ago=seconds_ago)
        LeadAiTranscript.objects.create(message=message, text=words)
        return message


# A. Facts SHOP FACTS lacks ---------------------------------------------------------------------------------------


class ClaimTopicTests(SimpleTestCase):
    def test_the_live_claims_are_found(self):
        for sentence, topic in (
            ("England cluster mein shop ka location Russia Cluster, Building V03, Shop 20 hai, Dubai International City.", "location"),
            ("Ji, shop Russia Cluster mein Building V03 ke paas hai, aur yeh parking side par hai, front side par nahi.", "location"),
            ("Yeh Russia 2 ya 3 dono buildings ke beech mein hai.", "location"),
            ("The shops are spaces ready for you to open your own restaurant or cafeteria, not existing businesses.", "food"),
            (DEPOSIT_59, "deposit"),
            ("There are no commissions from us for tenants.", claims.COMMISSION),
            ("These shops are also available for sale.", "sale"),
            ("The units come with a gas line and a chimney.", "food"),
            ("Parking is free for tenants.", "other"),
            ("DEWA is separate.", "other"),
            ("Only 2 shops are left.", "other"),
            ("المحل في مبنى V03 في الطابق الأرضي.", "location"),
        ):
            with self.subTest(sentence[:40]):
                self.assertEqual(claims.topic_of(sentence, KNOWN, ADDRESS), topic)

    def test_what_may_be_said(self):
        for sentence in (
            "Perfect, a restaurant or cafeteria.",
            "For a restaurant, Type 2 is perfect: 600-800 sq ft, from AED 48,000 a year.",
            f"Our office is in {ADDRESS}.",
            f"We're at {ADDRESS}.",
            ADDRESS,
            f"It is at {ADDRESS}.",
            "Our shops are in International City, in France, England, China, Russia, Morocco and Persia clusters.",
            "Our agent will drive you to the shops, 5 minutes away, and back.",
            "Good question — I'll have our agent confirm the parking for you at the viewing.",
            "That's fine — Trakhees licences are accepted for our shops.",
            "Payment is in 1 to 4 cheques.",
            # Chat 96's own wish said back to him (reply 180268), and the MATCH of his size (180279).
            "Aapko England cluster mein 400-550 sq ft ka chhota shop chahiye, parking side par.",
            "550 sq ft ka shop England cluster mein Type 1 hai, jo 400-550 sq ft ke darmiyan hota hai, aur iska rent AED 33,000 se shuru hota hai.",
            "Which side would you prefer, the parking or the front?",
            COMMISSION_EN.split(". ")[0] + ".",
            claims.unknown_line("ar"),
            "Photos help, but seeing 2-3 shops side by side is much easier.",
        ):
            with self.subTest(sentence[:40]):
                self.assertEqual(claims.topic_of(sentence, KNOWN, ADDRESS), "")

    def test_our_campaigns_own_words_may_be_said_again(self):
        campaign = leadai_eval.SHOPS_395.body  # "... in International City, close to Dragon Mart."
        self.assertEqual(claims.topic_of("Our shops are close to Dragon Mart.", KNOWN), "location")
        self.assertEqual(claims.topic_of("Our shops are close to Dragon Mart.", f"{KNOWN}\n{campaign}"), "")

    def test_a_sale_is_a_claim_only_while_shop_facts_says_nothing_of_one(self):
        self.assertEqual(claims.topic_of("These shops are also available for sale.", KNOWN), "sale")
        self.assertEqual(claims.topic_of("These shops are also available for sale.", f"{KNOWN}\n- Sale: Type 3 units are for sale"), "")

    def test_the_last_ten_launch_replies_of_ours_hold_no_other_claim(self):
        # Every other assistant sentence of the launch chats this package read (replayed over all 32 in the review).
        for sentence in filters.split_sentences(
            " ".join(
                [
                    leadai_eval.CHAT_96_START[3][1], leadai_eval.CHAT_96_START[5][1], leadai_eval.CHAT_96[-1][1], TABLE_91, SLOTS_100,
                    NEW_ONE_62, LICENCE_SLOTS_88, leadai_eval.LOCATION_81, leadai_eval.MATCH_88, leadai_eval.AGAIN_62,
                ]
            )
        ):
            with self.subTest(sentence[:40]):
                self.assertEqual(claims.topic_of(sentence, KNOWN, ADDRESS), "")


class ClaimSettleTests(SimpleTestCase):
    def answer(self, reply, language="en", **facts):
        return {"reply": reply, "language": language, "facts": {"notes": [], **facts}, "send": True}

    def test_chat_96_asked_which_building_gets_the_unknown_line_in_his_language(self):
        answer = self.answer(SIDE_96, "ur_latin")
        cut = claims.settle(answer, ["[voice note] Shop kaunsi building mein hai?"], known=KNOWN, office=ADDRESS)
        self.assertEqual(cut, ["location"])
        self.assertEqual(answer["reply"], f"{UNKNOWN_UR} Aap 12:30 PM ka slot confirm karna chahte hain?")
        self.assertEqual(answer["facts"]["notes"], ["which building or side the shop is in"])

    def test_unasked_the_claim_just_goes(self):
        answer = self.answer(f"Great. {DEPOSIT_59} What size do you need?")
        self.assertEqual(claims.settle(answer, ["How much is it?"], known=KNOWN), ["deposit"])
        self.assertEqual(answer["reply"], "Great. What size do you need?")

    def test_chat_91_the_food_use_claim_answers_nothing(self):
        answer = self.answer(FOOD_91)
        claims.settle(answer, ["are they an existing restaurant?", "i want to know the location"], known=KNOWN, office=ADDRESS)
        self.assertEqual(
            answer["reply"],
            f"{shops.UNKNOWN_LINE} Our office is in {ADDRESS}. When would you like to come and see them?",
        )
        self.assertEqual(answer["facts"]["notes"], ["whether the unit suits a food business"])

    def test_commission_is_matloobs_line_q24(self):
        # Chat 78 (14:19): "There are no commissions from us for tenants".
        answer = self.answer(NO_COMMISSION_78)
        self.assertEqual(claims.settle(answer, ["Is there any commission?"], known=KNOWN), [claims.COMMISSION])
        self.assertEqual(answer["reply"], f"{COMMISSION_EN} Do you have a DED or Trakhees licence, or will you open a new one?")
        # A commission question with nothing on it: the line opens the reply, and the unknown line it got goes.
        answer = self.answer(f"{shops.UNKNOWN_LINE} I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?")
        claims.settle(answer, ["agency fee?"], known=KNOWN)
        self.assertEqual(answer["reply"], f"{COMMISSION_EN} I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?")
        # The line said already is not said twice; in Urdu script and for someone who wants no shop: "the options".
        answer = self.answer(COMMISSION_EN)
        self.assertEqual(claims.settle(answer, ["commission?"], known=KNOWN), [])
        answer = self.answer("کمیشن نہیں ہے۔", "ur")
        claims.settle(answer, ["کمیشن کتنا ہے؟"], known=KNOWN)
        self.assertEqual(answer["reply"], claims.commission_line("ur"))
        answer = self.answer("There is no commission.")
        claims.settle(answer, ["commission?"], known=KNOWN, options=True)
        self.assertIn("see the options first", answer["reply"])

    def test_a_reply_left_with_nothing_is_the_unknown_line(self):
        answer = self.answer("Yes, parking is free for tenants.")
        claims.settle(answer, ["Is parking free?"], known=KNOWN)
        self.assertEqual(answer["reply"], shops.UNKNOWN_LINE)

    def test_the_lines_in_every_language(self):
        for table in (claims.UNKNOWN, {lang: pair[0] for lang, pair in claims.COMMISSION_LINE.items()}):
            self.assertEqual(set(table), {"en", "ar", "ur_latin", "ur", "hi_latin", "hi"})
            for language, line in table.items():
                with self.subTest(language=language, line=line[:20]):
                    if language != "en":
                        self.assertNotEqual(line, table["en"])
                    self.assertTrue(claims.is_code_line(line))


class ClaimTurnTests(Base):
    def test_chat_96_at_12_35_no_building_no_side_and_never_the_slot_that_passed(self):
        self.at_clock(12, 35)
        self.set_state(facts=dict(SHOP_FACTS_96), language="ur_latin", invites=2)
        # Appointment 18 as it stood: tentative, his own window in its note.
        LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", place="office", note=WINDOW_WORDS)
        self.ours(leadai_eval.CHAT_96[-1][1], minutes_ago=9)
        self.voice("Shop kaunsi building mein hai?", seconds_ago=240)
        message = self.voice("Parking side wali shop chahiye, front wali nahi", seconds_ago=120)
        live = shop_answer(SIDE_96, action="tentative", place="office", words=WINDOW_WORDS, language="ur_latin", facts=dict(SHOP_FACTS_96))
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(
            self.body(outcome), f"{UNKNOWN_UR} Main aap ke liye aaj 2:00 PM ya 4:00 PM ka slot rakh sakta hoon — kaunsa behtar rahega?"
        )
        self.assertEqual(self.actions(message)["trimmed"], [claims.CUT, offers.TIMES])

    def test_without_the_guards_the_live_reply_went(self):
        self.at_clock(12, 35)
        self.set_state(facts=dict(SHOP_FACTS_96), language="ur_latin")
        message = self.voice("Shop kaunsi building mein hai?")
        live = shop_answer(SIDE_96, language="ur_latin")
        with patch.object(claims, "settle", return_value=[]), patch.object(offers, "fix_times", return_value=False):
            outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), SIDE_96)

    def test_chat_96_at_11_12_our_office_is_never_the_shops_location(self):
        self.at_clock(11, 12)
        self.set_state(facts=dict(SHOP_FACTS_96), language="ur_latin")
        message = self.voice("England cluster mein shop kahan hai? Kaunsi building?")
        live = shop_answer(CLAIM_96, language="ur_latin", invited=True, share_location=True, facts=dict(SHOP_FACTS_96))
        outcome, _, _, _ = self.turn(message, [live])
        body = self.body(outcome)
        self.assertTrue(body.startswith(UNKNOWN_UR), body)
        self.assertNotIn("shop ka location", body)
        self.assertIn(f"\n{offers.LOCATION_LABEL['ur_latin']} {MAPS}", body)  # our office's, labelled

    def test_chat_91_the_food_claim_goes_and_the_question_is_noted(self):
        self.at_clock(10, 37)
        self.set_state(facts=dict(leadai_eval.FACTS_91))
        self.inbound("are they an existing restaurant?", seconds_ago=40)
        message = self.inbound("i want to know the location", seconds_ago=30)
        outcome, _, _, _ = self.turn(message, [shop_answer(FOOD_91, share_location=True)])
        body = self.body(outcome)
        self.assertNotIn("ready for you to open", body)
        self.assertTrue(body.startswith(f"{shops.UNKNOWN_LINE} Our office is in {ADDRESS}."), body)
        self.assertIn("whether the unit suits a food business", self.state().facts["notes"])

    def test_chat_59_rent_security_is_the_deposit_a_person_answers(self):
        # Must-answer (people.py): "rent security" is the deposit, handed to a person with the question listed.
        self.assertEqual(people.must_answer(["And give me full details including rent security"]), ["deposit"])
        message = self.inbound("And give me full details including rent security")
        self.assertTrue(LIVE_59.startswith(DEPOSIT_59))
        outcome, _, _, _ = self.turn(message, [shop_answer(LIVE_59)])
        # The chat goes on (batch 2d's review: people.MUST_ANSWER_PAUSES False): the line, with the model's own question.
        self.assertEqual(
            self.body(outcome), f"{people.line(people.MUST_ANSWER, 'en', shops=True)} What size or budget are you considering for the shop?"
        )
        self.assertIsNone(self.state().handed_over_at)
        self.assertEqual(self.actions(message)["must_answer"], ["deposit"])

    def test_chat_78_commission(self):
        message = self.inbound("Is there any commission?")
        outcome, _, _, _ = self.turn(message, [shop_answer(NO_COMMISSION_78)])
        self.assertTrue(self.body(outcome).startswith(COMMISSION_EN), self.body(outcome))
        self.assertEqual(self.actions(message)["trimmed"], [claims.COMMISSION])
        self.assertIsNone(self.state().handed_over_at)  # commission alone is no must-answer question (Q24)


class GeneralClaimTests(GeneralBase):
    def test_a_general_reply_is_not_read_for_shop_claims(self):
        message = self.inbound("Is there any commission?")
        reply = "Our specialist will confirm the commission with you here. Would you like to visit our office to go through the options?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply)])
        self.assertEqual(self.body(outcome), reply)


# B. Slots ------------------------------------------------------------------------------------------------------


class SlotRuleTests(SimpleTestCase):
    def test_an_hour_ahead_and_an_hour_apart(self):
        self.assertEqual((hours.OFFER_LEAD, hours.MIN_GAP), (dt.timedelta(hours=1), dt.timedelta(hours=1)))
        self.assertEqual(hours.first_offer(monday(12, 43)), monday(14))  # chat 100: never 1:00 PM at 12:43
        self.assertEqual(hours.first_offer(monday(10, 27)), monday(11, 30))  # chat 62: never 11:00 AM at 10:27
        self.assertEqual(hours.offer_pair(monday(12, 43)), [monday(14), monday(16)])
        self.assertEqual(hours.spaced([monday(15), monday(15, 30), monday(16), monday(17, 30)]), [monday(15), monday(16), monday(17, 30)])
        # Taken at the first free one: the next two, an hour apart, never the half hour after.
        self.assertEqual(hours.nearest_free(monday(15), NOW, (), [monday(15)]), [monday(15, 30), monday(16, 30)])

    def test_the_model_reads_free_slots_an_hour_apart(self):
        context = shops.context(LeadAiSettings(shops_facts=DEFAULT_SHOPS_FACTS), {}, NOW)
        self.assertEqual(context.free[:3], ["Mon 2026-10-12 15:00 (today 3:00 PM)", "Mon 2026-10-12 16:00 (today 4:00 PM)", "Mon 2026-10-12 17:00 (today 5:00 PM)"])
        header = next(line for line in prompt.shops_lines(context) if line.startswith("FREE SLOTS"))
        self.assertIn("an hour from now at least and an hour apart", header)
        self.assertIn("- Mon 2026-10-12 15:00 (today 3:00 PM)\n- Mon 2026-10-12 16:00 (today 4:00 PM)", header)

    def test_the_live_slots_are_replaced_by_the_two_nearest_valid_ones(self):
        cases = (
            (SLOTS_100, monday(12, 43), (), [monday(14), monday(16)]),  # chat 100: 17 minutes away, 30 apart
            (NEW_ONE_62, monday(10, 27), (), [monday(11, 30), monday(13, 30)]),  # chat 62
            (SIDE_96, monday(12, 35), (WINDOW_WORDS,), [monday(14), monday(16)]),  # chat 96: his own 12:30, passed
            (LICENCE_SLOTS_88, monday(10, 33), (), [monday(12), monday(14)]),  # chat 88: 11:30 is 57 minutes away
        )
        for reply, now, said, pair in cases:
            with self.subTest(reply[:30]):
                self.assertEqual(offers.wrong_times(reply, now, theirs=offers.theirs_from(said, now)), pair)

    def test_what_may_stay(self):
        stays = (
            ("I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", NOW, (), None),
            ("Sorry, 5:00 PM tomorrow is already booked. I can hold 4:30 PM or 5:30 PM tomorrow for you — which is better?", NOW, ("Tomorrow at 5 pm is better for me",), [at(13, 17)]),
            ("Sure, 2:30 PM works for you, shall I book it?", NOW, ("Can I come at 2:30?",), None),  # theirs: sooner than the lead
            ("Our agent will call you today between 11:30 and 12:00.", NOW, (), None),  # a call, no visit
            ("We're open Monday to Saturday, 10 AM to 8 PM. Would 4 PM work?", NOW, (), None),
            ("I can hold a slot for you today at 7:00 PM or tomorrow at 10:00 AM — which is better?", NOW, (), None),
            ("Sure, come now: I can hold 2:30 PM for you.", NOW, ("I can come now",), None),
        )
        for reply, now, said, taken in stays:
            with self.subTest(reply[:30]):
                soon = "now" in " ".join(said)
                self.assertIsNone(offers.wrong_times(reply, now, (), taken or (), theirs=offers.theirs_from(said, now), soon=soon))
        # The visit's own time, whatever its lead; never another client's.
        self.assertIsNone(offers.wrong_times("See you at 2:30 PM today.", NOW, booked=monday(14, 30)))
        self.assertEqual(offers.wrong_times(TWO_SLOTS_NOW, NOW, (), [monday(15)]), [monday(15, 30), monday(17, 30)])

    def test_the_same_pair_asked_again_goes_in_other_words(self):
        answer = {"reply": NEW_ONE_62, "language": "en", "handover": {"needed": False}, "opt_out": "none"}
        before = "I can hold a slot for you today at 11:30 AM or 1:30 PM — which is better?"
        self.assertTrue(offers.fix_times(answer, monday(10, 27), before=before))
        self.assertTrue(answer["reply"].endswith("Which one suits you better: today at 11:30 AM or 1:30 PM?"), answer["reply"])
        # Never while the answer hands the chat over.
        handed = {"reply": NEW_ONE_62, "language": "en", "handover": {"needed": True}, "opt_out": "none"}
        self.assertFalse(offers.fix_times(handed, monday(10, 27)))


class SlotTurnTests(Base):
    def test_chat_62_new_one_at_10_27(self):
        self.at_clock(10, 27)
        self.set_state(facts=dict(leadai_eval.FACTS_62))
        self.ours(leadai_eval.CHAT_62[-1][1], minutes_ago=1)
        self.inbound("New", seconds_ago=40)
        message = self.inbound("One", seconds_ago=30)
        live = shop_answer(NEW_ONE_62, action="tentative", place="office", date="2026-10-12", time="11:00", words="One", invited=True, share_location=True)
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(
            self.body(outcome),
            f"A Type 2 shop is great, starting from AED 48,000 a year. I can hold a slot for you today at 11:30 AM or 1:30 PM — which is better?\n{LOCATED}",
        )
        self.assertEqual(self.state().invites, 1)
        self.assertFalse(LeadAiAppointment.objects.exists())  # our own offer: no visit recorded (own_offer)

    def test_without_the_guard_the_live_slots_went(self):
        self.at_clock(10, 27)
        message = self.inbound("One")
        with patch.object(offers, "fix_times", return_value=False):
            outcome, _, _, _ = self.turn(message, [shop_answer(NEW_ONE_62, invited=True)])
        self.assertEqual(self.body(outcome), NEW_ONE_62)


class GeneralSlotTests(GeneralBase):
    def test_seven_or_half_past_is_left_as_the_general_prompt_says_it(self):
        reply = "Our office closes at 8 PM. Would 7 PM or 7:30 PM work for you?"
        outcome, _, _, _ = self.turn(self.inbound("Can I come at 9 pm?"), [shop_answer(reply)])
        self.assertEqual(self.body(outcome), reply)


# C. A same-day window ----------------------------------------------------------------------------------------


class WindowReaderTests(SimpleTestCase):
    def test_the_windows_customers_say(self):
        for said, window in (
            (WINDOW_WORDS, (dt.time(12), dt.time(12, 30))),
            ("بارہ ساڑھے بارہ بجے جا کے چیک کر لوں گا", (dt.time(12), dt.time(12, 30))),
            ("I will come at 12-12:30", (dt.time(12), dt.time(12, 30))),
            ("between 12 and 12:30", (dt.time(12), dt.time(12, 30))),
            ("I'll come at 5 or 6 pm", (dt.time(17), dt.time(18))),
            ("12 ya 12:30 baje aaunga", (dt.time(12), dt.time(12, 30))),
            ("We can have a call at 11.30 - 12 PM", (dt.time(11, 30), dt.time(12))),
        ):
            with self.subTest(said):
                self.assertEqual(hours.named_window(said), window)
        for said in ("1 to 4 cheques", "400-550 sq ft", "Type 1 or 2", "11 to 2", "15-10-2026", "10-15 minutes", "Tomorrow at 5 pm", "5"):
            with self.subTest(said):
                self.assertIsNone(hours.named_window(said))

    def test_half_past_as_chat_96_spelt_it(self):
        self.assertEqual(hours.said_times("saadhay barah baje"), {dt.time(12, 30)})
        self.assertTrue(hours.marks_hour("saadhay 5"))

    def test_a_plan_to_come(self):
        self.assertTrue(hours.window_promise(WINDOW_WORDS))
        for said in ("shayad 12-12:30", "agar time mila to 12-12:30", "12-12:30 nahi aa sakta", "Are you open at 12-12:30?"):
            with self.subTest(said):
                self.assertFalse(hours.window_promise(said))


class WindowBookingTests(SimpleTestCase):
    def answer(self, words=WINDOW_WORDS, **appointment):
        data = shop_answer("Theek hai.", action="tentative", place="office", words=words, language="ur_latin", **appointment).data
        return normal(type("C", (), {"data": data})())

    def test_chat_96_at_11_10_books_the_start_of_his_window(self):
        answer = self.answer()
        when = engine.book_window(answer, f"[voice note] {WINDOW_WORDS}", None, monday(11, 10), playbook="ic_shops")
        self.assertEqual(when, monday(12))
        self.assertEqual((answer["appointment"]["action"], answer["appointment"]["time"], answer["window"]), ("confirm", "12:00", {"start": "12:00", "end": "12:30"}))

    def test_taken_its_next_free_half_hour_passed_none(self):
        when = engine.book_window(self.answer(), WINDOW_WORDS, None, monday(11, 10), taken=[monday(12)], playbook="ic_shops")
        self.assertEqual(when, monday(12, 30))
        self.assertIsNone(engine.book_window(self.answer(), WINDOW_WORDS, None, monday(12, 35), playbook="ic_shops"))

    def test_never(self):
        cases = {
            "a general chat": dict(playbook="general"),
            "a person has it": dict(playbook="ic_shops", handed_over=True),
            "a colleague's plan": dict(playbook="ic_shops", agent_last=True),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.assertIsNone(engine.book_window(self.answer(), WINDOW_WORDS, None, monday(11, 10), **kwargs))
        for said in ("kal barah saadhay barah baje aaunga", "shayad barah saadhay barah baje", "barah saadhay barah baje, I will let you know"):
            with self.subTest(said):
                self.assertIsNone(engine.book_window(self.answer(said), said, None, monday(11, 10), playbook="ic_shops"))
        booked = LeadAiAppointment(status="confirmed", starts_at=monday(17))
        self.assertIsNone(engine.book_window(self.answer(), WINDOW_WORDS, booked, monday(11, 10), playbook="ic_shops"))
        none = normal(shop_answer("Theek hai.", language="ur_latin"))  # no tentative of the model's: nothing to book
        self.assertIsNone(engine.book_window(none, WINDOW_WORDS, None, monday(11, 10), playbook="ic_shops"))


class WindowTurnTests(Base):
    def test_chat_96_is_booked_for_12_and_confirmed(self):
        self.at_clock(11, 10)
        self.set_state(facts=dict(SHOP_FACTS_96), language="ur_latin", invites=1)
        message = self.voice(f"Kaunsi building mein hai? Main {WINDOW_WORDS}")
        live = shop_answer(
            CLAIM_96, action="tentative", place="office", words=WINDOW_WORDS, language="ur_latin", invited=True, share_location=True,
            facts=dict(SHOP_FACTS_96),
        )
        outcome, _, crm_delay, _ = self.turn(message, [live])
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.starts_at), ("confirmed", monday(12)))
        body = self.body(outcome)
        self.assertTrue(body.startswith("Aap ki viewing confirm ho gayi hai"), body)
        self.assertIn("Time: 12:00 PM", body)
        self.assertNotIn("shop ka location", body)
        crm_delay.assert_called_once()
        self.assertEqual(self.actions(message)["window"], {"start": "12:00", "end": "12:30"})
        self.assertTrue(LeadAiAlert.objects.filter(kind="booked", priority="high").exists())  # a visit within the hour

    def test_without_the_guard_he_stayed_tentative(self):
        self.at_clock(11, 10)
        message = self.voice(WINDOW_WORDS)
        live = shop_answer("Theek hai, main aap ke liye 12:30 PM ka slot rakh doon?", action="tentative", place="office", words=WINDOW_WORDS, language="ur_latin")
        with patch.object(engine, "book_window", return_value=None):
            self.turn(message, [live])
        self.assertEqual(LeadAiAppointment.objects.get().status, "tentative")


# D. The price -------------------------------------------------------------------------------------------------


class PriceReaderTests(SimpleTestCase):
    def test_a_price_objection(self):
        for said in (
            "I need cheaper price no good location", "Your rent is higher than others", "too expensive", "Is there anything cheaper?",
            "What's your lowest?", "bohat mehenga hai", "غالي جدا", "my budget is low", "out of my budget",
        ):
            with self.subTest(said):
                self.assertTrue(claims.objects_to_price([said]))
        for said in ("Can you give me a discount?", "best price?", "How much is the rent?", "I need a shop", "Type 1 is fine"):
            with self.subTest(said):
                self.assertFalse(claims.objects_to_price([said]))

    def test_cheaper_is_no_discount_ask_any_more(self):
        self.assertFalse(engine._DISCOUNT.search("I need cheaper price no good location"))
        self.assertFalse(engine._DISCOUNT.search("Is there anything lower?"))
        self.assertTrue(engine._DISCOUNT.search("Can you give me a discount?"))
        # Live, a second "cheaper ...?" would have been a price_or_details_insisted handover (engine._settle_shops_handover).
        earlier = [("customer", "I need cheaper price no good location"), ("assistant", "Our agent can discuss the best price for you at the viewing.")]
        answer = normal(shop_answer("Sure."))
        engine.settle_handover(answer, earlier, ["cheaper one?"], shops_chat=True)
        self.assertFalse(answer["handover"]["needed"])

    def test_the_lines(self):
        self.assertEqual(
            claims.price_text({"kind": claims.LOWEST}, "en", DEFAULT_SHOPS_FACTS),
            "I understand. Our lowest is Type 1, from AED 33,000 a year (400-550 sq ft), payable in 1 to 4 cheques. Would that size work for you?",
        )
        self.assertEqual(
            claims.price_text({"kind": claims.BELOW, "budget": 25000}, "en", DEFAULT_SHOPS_FACTS),
            "Thank you for telling me. To be honest, our lowest is Type 1, from AED 33,000 a year (400-550 sq ft), which is above your budget "
            "of AED 25,000. Would you like one of our colleagues to check other options for you?",
        )
        for language in ("ar", "ur_latin", "ur", "hi_latin", "hi"):
            for kind in (claims.LOWEST, claims.BELOW):
                with self.subTest(language=language, kind=kind):
                    text = claims.price_text({"kind": kind, "budget": 25000}, language, DEFAULT_SHOPS_FACTS)
                    self.assertIn("33,000", text)
                    self.assertNotIn("{", text)
                    if kind == claims.BELOW:
                        self.assertTrue(claims.asks_colleague(text))
        self.assertTrue(claims.sent_price_line([claims.price_text({"kind": claims.LOWEST}, "ar", DEFAULT_SHOPS_FACTS)]))

    def test_a_budget_is_read_yearly_from_aed_1000(self):
        self.assertEqual(claims.yearly_budget({"budget_aed": 2500, "budget_basis": "per_month"}), 30000)
        self.assertIsNone(claims.yearly_budget({"budget_aed": 33}))


class PriceTurnTests(Base):
    def test_chat_59_your_rent_is_higher_than_others(self):
        self.at_clock(12, 40)
        message = self.inbound("Your rent is higher than others")
        live = shop_answer(leadai_eval.DISCOUNT_59, action="tentative", place="office", words="Your rent is higher than others", invited=True)
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), claims.price_text({"kind": claims.LOWEST}, "en", DEFAULT_SHOPS_FACTS))
        self.assertEqual((self.actions(message)["price"], self.state().invites), (claims.LOWEST, 0))
        self.assertFalse(LeadAiAppointment.objects.exists())

    def test_chat_100_cheaper_then_cheaper_again_offers_a_colleague(self):
        self.at_clock(12, 43)
        self.set_state(facts=dict(leadai_eval.FACTS_100))
        message = self.inbound("I need cheaper price no good location")
        outcome, _, _, _ = self.turn(message, [shop_answer(SLOTS_100, invited=True)])
        lowest = self.body(outcome)
        self.assertTrue(lowest.startswith("I understand. Our lowest is Type 1"), lowest)
        self.later(2)
        again = self.inbound("still too expensive", seconds_ago=10)
        outcome, _, _, _ = self.turn(again, [shop_answer("I understand. Our agent can discuss the best price for you at the viewing.")])
        self.assertTrue(claims.asks_colleague(self.body(outcome)), self.body(outcome))
        # Their yes: a person, with the holding line and the handover alert.
        self.later(4)
        yes = self.inbound("Yes please", seconds_ago=10)
        outcome, _, _, _ = self.turn(yes, [shop_answer("Great! What size do you need?")])
        self.assertEqual(self.body(outcome), people.line(people.HOLDING, "en", shops=True))
        self.assertEqual(self.state().handover_reason, claims.COLLEAGUE_HANDOVER)
        self.assertTrue(LeadAiAlert.objects.filter(kind="handover").exists())

    def test_a_budget_below_our_lowest(self):
        message = self.inbound("My budget is 25k a year")
        outcome, _, _, _ = self.turn(message, [shop_answer("Type 1 fits your budget. What business is it for?", facts={"budget_aed": 25000, "budget_basis": "per_year"})])
        self.assertEqual(self.body(outcome), claims.price_text({"kind": claims.BELOW, "budget": 25000}, "en", DEFAULT_SHOPS_FACTS))

    def test_without_the_guard_the_discount_line_went(self):
        self.at_clock(12, 40)
        message = self.inbound("Your rent is higher than others")
        with patch.object(claims, "price_turn", return_value=""):
            outcome, _, _, _ = self.turn(message, [shop_answer("I understand. Our agent can discuss the best price for you at the viewing.")])
        self.assertEqual(self.body(outcome), "I understand. Our agent can discuss the best price for you at the viewing.")

    def test_never_for_someone_who_wants_no_shop_nor_over_a_location_asked(self):
        self.set_state(facts={"need": "home", "wanted": "a studio"})
        message = self.inbound("too expensive")
        outcome, _, _, _ = self.turn(message, [shop_answer("I understand. We have many studios across Dubai.")])
        self.assertNotIn("Our lowest is Type 1", self.body(outcome))
        self.assertFalse(engine.price_plain(normal(shop_answer("ok")), {}, None, "too expensive, where is your office?"))
        self.assertTrue(engine.price_plain(normal(shop_answer("ok")), {}, None, "I need cheaper price no good location"))


# E. A tap with typed words ----------------------------------------------------------------------------------------


class TapReaderTests(SimpleTestCase):
    def test_the_tap_of_a_burst_with_words(self):
        self.assertEqual(shop_flow.burst_tap([("Yes, show me shops", "")], True), (shop_flow.TAP_YES, ""))
        self.assertEqual(shop_flow.burst_tap([("Type 1 – Small", "type_1")], True), (shop_flow.TAP_TYPE, "type_1"))
        self.assertEqual(shop_flow.burst_tap([("Yes, book a viewing", "")], True), (shop_flow.TAP_YES, "book"))
        self.assertIsNone(shop_flow.burst_tap([("Type 1 – Small", "type_1")], False))  # a tap alone: code's tap rules
        self.assertIsNone(shop_flow.burst_tap([], True))
        self.assertEqual(shop_flow.without_taps("[tapped: Yes, show me shops] How much price monthly basis"), "How much price monthly basis")
        self.assertEqual(shop_flow.typed_words("[tapped: Yes, show me shops]"), "[tapped: Yes, show me shops]")
        self.assertFalse(shop_flow.asks_types(shop_flow.typed_words("[tapped: Yes, show me shops] How much price monthly basis")))
        self.assertEqual(shop_flow.for_whom_question("en"), "Is the shop for yourself, or are you checking for a client?")


class TapTurnTests(Base):
    def test_chat_81_the_answer_and_for_yourself_or_for_a_client(self):
        self.at_clock(11, 8)
        self.tap("Yes, show me shops", seconds_ago=40)
        message = self.inbound("How much price monthly basis", seconds_ago=30)
        answer = "Our rents are per year: Type 1 starts from AED 33,000 a year, payable in 1 to 4 cheques. What size do you need?"
        outcome, calls, _, _ = self.turn(message, [shop_answer(answer)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            self.body(outcome),
            "Our rents are per year: Type 1 starts from AED 33,000 a year, payable in 1 to 4 cheques. Is the shop for yourself, or are you checking for a client?",
        )
        self.sent_lists.assert_not_called()
        self.assertEqual(self.actions(message)["tap_step"], "for_whom")

    def test_chat_81_without_the_fixes_the_list_replaced_the_answer(self):
        self.at_clock(11, 8)
        self.tap("Yes, show me shops", seconds_ago=40)
        message = self.inbound("How much price monthly basis", seconds_ago=30)
        with patch.object(shop_flow, "typed_words", side_effect=lambda said: said), patch.object(engine, "tap_with_words", return_value=""):
            self.turn(message, [shop_answer("Rents are yearly.", facts={"for_client": False})])
        self.sent_lists.assert_called_once()

    def test_chat_88_his_words_then_the_type_1_row(self):
        self.at_clock(10, 33)
        self.set_state(facts={"for_client": False, "property_type": "shop"})
        self.ours(shop_flow.list_text("en", DEFAULT_SHOPS_FACTS), minutes_ago=2, shop_list=True)
        self.inbound("Preferable Location - France (P24 P23 P26 P22)\nSize - 400sqft", seconds_ago=40)
        row = self.inbound(
            "Type 1 – Small", kind=Message.Kind.INTERACTIVE, seconds_ago=30,
            payload={"interactive": {"type": "list_reply", "list_reply": {"id": "type_1", "title": "Type 1 – Small"}}},
        )
        outcome, calls, _, _ = self.turn(row, [shop_answer(leadai_eval.MATCH_88, invited=True, share_location=True, facts={"community": "France", "size_sqft": 400})])
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome.reason, "shop media queued (type_1)")
        self.assertEqual(self.media_delay.call_args.args[1], "type_1")
        self.assertEqual((self.state().facts["shop_type"], self.state().invites), ("type_1", 0))
        self.assertEqual(self.actions(row)["tap_step"], "media")
        self.assertFalse(Message.objects.filter(conversation=self.conversation, body__contains="Type 1 is perfect").exists())  # the card says it

    def test_chat_88_without_the_guard_no_media(self):
        self.at_clock(10, 33)
        self.set_state(facts={"for_client": False})
        self.inbound("Preferable Location - France (P24 P23 P26 P22)\nSize - 400sqft", seconds_ago=40)
        row = self.inbound(
            "Type 1 – Small", kind=Message.Kind.INTERACTIVE, seconds_ago=30,
            payload={"interactive": {"type": "list_reply", "list_reply": {"id": "type_1", "title": "Type 1 – Small"}}},
        )
        with patch.object(engine, "tap_with_words", return_value=""):
            self.turn(row, [shop_answer(leadai_eval.MATCH_88)])
        self.media_delay.assert_not_called()

    def test_see_other_types_with_a_question_sends_the_answer_then_the_list(self):
        self.set_state(facts={"for_client": False, "shop_type": "type_2"})
        self.inbound("Is parking available?", seconds_ago=40)
        tap = self.inbound(
            "See other types", kind=Message.Kind.INTERACTIVE, seconds_ago=30,
            payload={"interactive": {"type": "button_reply", "button_reply": {"id": shop_flow.TYPES_ID, "title": "See other types"}}},
        )
        self.turn(tap, [shop_answer(f"{shops.UNKNOWN_LINE} Which type would you like to see?")])
        self.sent_lists.assert_called_once()
        words = Message.objects.filter(conversation=self.conversation, direction=Message.Direction.OUTBOUND, body=shops.UNKNOWN_LINE)
        self.assertTrue(words.exists())

    def test_book_viewing_with_a_question_gets_two_free_slots(self):
        self.set_state(facts={"for_client": False, "shop_type": "type_2"})
        self.inbound("Is it near the metro?", seconds_ago=40)
        tap = self.inbound(
            "Book viewing", kind=Message.Kind.INTERACTIVE, seconds_ago=30,
            payload={"interactive": {"type": "button_reply", "button_reply": {"id": f"{shop_flow.BOOK_ID}type_2", "title": "Book viewing"}}},
        )
        # The model answers the words only (no open "when" for code's slots rewrite to catch).
        outcome, _, _, _ = self.turn(tap, [shop_answer(shops.UNKNOWN_LINE)])
        self.assertEqual(self.body(outcome), f"{shops.UNKNOWN_LINE} {TWO_SLOTS_NOW}")
        self.assertEqual((self.actions(tap)["tap_step"], self.state().invites), ("slots", 0))  # their own request to come


# F. The size and price table said again ---------------------------------------------------------------------------


class TableRepeatTests(SimpleTestCase):
    def test_chat_91_the_table_after_the_list(self):
        sent = [rules.line("for_whom", "en"), shop_flow.list_text("en", DEFAULT_SHOPS_FACTS)]
        answer = {"reply": TABLE_91}
        self.assertTrue(claims.drop_table_repeat(answer, sent, ["For me"], DEFAULT_SHOPS_FACTS))
        self.assertEqual(answer["reply"], "Perfect, a restaurant or cafeteria. What size shop do you need?")
        # Asked for now ("share me the prices and spaces"): the table is the answer (the list's rows sit behind its button).
        answer = {"reply": TABLE_91}
        self.assertFalse(claims.drop_table_repeat(answer, sent, ["share me the prices and spaces so i  could decide"], DEFAULT_SHOPS_FACTS))
        # Prices not given before are new; one type's figures are no table; a reply of nothing else stays whole.
        sizes_only = [TABLE_91]
        priced = "We have small from AED 33,000, medium from AED 48,000 and large from AED 80,000 a year."
        self.assertFalse(claims.restates_table(priced, sizes_only, DEFAULT_SHOPS_FACTS))
        self.assertFalse(claims.restates_table("Type 1 is 400-550 sq ft, from AED 33,000 a year.", sent, DEFAULT_SHOPS_FACTS))
        alone = {"reply": "We have small (400-550 sq ft), medium (600-800 sq ft), and large (900-1,200 sq ft) options."}
        self.assertFalse(claims.drop_table_repeat(alone, sent, ["For me"], DEFAULT_SHOPS_FACTS))


class TableRepeatTurnTests(Base):
    def chat_91(self):
        self.set_state(facts=dict(leadai_eval.FACTS_91))
        self.ours(rules.line("for_whom", "en"), minutes_ago=3)
        self.ours(shop_flow.list_text("en", DEFAULT_SHOPS_FACTS), minutes_ago=2, shop_list=True)
        return self.inbound("For me")

    def test_chat_91_for_me(self):
        message = self.chat_91()
        outcome, _, _, _ = self.turn(message, [shop_answer(TABLE_91)])
        self.assertEqual(self.body(outcome), "Perfect, a restaurant or cafeteria. What size shop do you need?")
        self.assertEqual(self.actions(message)["trimmed"], [claims.TABLE])

    def test_chat_91_without_the_guard_the_table_went_again(self):
        message = self.chat_91()
        with patch.object(claims, "drop_table_repeat", return_value=False):
            outcome, _, _, _ = self.turn(message, [shop_answer(TABLE_91)])
        self.assertEqual(self.body(outcome), TABLE_91)


# G. The invitation count and our labelled location -----------------------------------------------------------------


class InvitationCountTests(Base):
    def test_chat_81_location_code_made_two_slots_one_invitation(self):
        self.at_clock(11, 58)
        self.set_state(facts={"for_client": False, "property_type": "shop"})
        message = self.inbound("Location")
        outcome, _, _, _ = self.turn(message, [shop_answer(leadai_eval.LOCATION_81, share_location=True)])
        self.assertEqual(self.state().invites, 1)
        self.assertIn("today at 1:00 PM or 3:00 PM", self.body(outcome))
        self.assertTrue(self.actions(message)["invited_to_meeting"])

    def test_chat_81_without_the_count_none(self):
        # As live (turn 123: trimmed ["slots"], invited_to_meeting false): code's two slots, never counted.
        self.at_clock(11, 58)
        self.set_state(facts={"for_client": False, "property_type": "shop"})
        message = self.inbound("Location")
        with uncounted_rewrite():
            outcome, _, _, _ = self.turn(message, [shop_answer(leadai_eval.LOCATION_81, share_location=True)])
        self.assertIn("today at 1:00 PM or 3:00 PM", self.body(outcome))
        self.assertEqual(self.state().invites, 0)

    def test_chat_96_at_10_53_the_models_own_slots_put_right_and_counted(self):
        # Turn 110: "aaj 11:30 AM ya 12:00 PM" 37 minutes ahead and half an hour apart, and invited_to_meeting false.
        self.at_clock(10, 53)
        self.set_state(facts=dict(SHOP_FACTS_96), language="ur_latin")
        message = self.voice("550 square feet ka rent kitna hai?")
        live = leadai_eval.CHAT_96_START[5][1]
        outcome, _, _, _ = self.turn(message, [shop_answer(live, language="ur_latin", facts=dict(SHOP_FACTS_96))])
        self.assertEqual(
            self.body(outcome),
            "550 sq ft ka shop England cluster mein Type 1 hai, jo 400-550 sq ft ke darmiyan hota hai, aur iska rent AED 33,000 se shuru "
            "hota hai. Yeh shops France, England, China, Russia, Morocco aur Persia clusters mein hain. Main aap ke liye aaj 12:00 PM ya "
            "2:00 PM ka slot rakh sakta hoon — kaunsa behtar rahega?",
        )
        self.assertEqual(self.state().invites, 1)

    def test_chat_96_the_models_own_two_slots_are_one_invitation(self):
        self.at_clock(10, 53)
        self.set_state(facts=dict(SHOP_FACTS_96), language="ur_latin")
        message = self.voice("550 square feet ka rent kitna hai?")
        live = leadai_eval.CHAT_96_START[5][1].replace("11:30 AM ya 12:00 PM", "12:00 PM ya 2:00 PM")  # valid slots, the model's flag false
        self.turn(message, [shop_answer(live, language="ur_latin", facts=dict(SHOP_FACTS_96))])
        self.assertEqual(self.state().invites, 1)

    def test_chat_88_an_invitation_cut_as_a_second_question_is_none_and_takes_our_link(self):
        # Turn 82 (10:33): the licence question, then the slots cut as a second question, counted, and the bare
        # link under the licence question (180113). His words alone here (the tap beside them: TapTurnTests).
        self.at_clock(10, 33)
        self.set_state(facts={"for_client": False, "property_type": "shop", "shop_type": "type_1", "size_sqft": 400})
        message = self.inbound("Preferable Location - France (P24 P23 P26 P22)\nSize - 400sqft")
        outcome, _, _, _ = self.turn(message, [shop_answer(leadai_eval.MATCH_88, invited=True, share_location=True)])
        self.assertEqual(
            self.body(outcome),
            "For a shop in France cluster, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees licence, "
            "or will you open a new one?",
        )
        self.assertEqual((self.state().invites, self.actions(message)["invitation_cut"]), (0, True))

    def test_chat_88_valid_times_are_cut_the_same_way(self):
        self.at_clock(10, 33)
        self.set_state(facts={"for_client": False, "property_type": "shop", "shop_type": "type_1", "size_sqft": 400})
        message = self.inbound("Size - 400sqft, France")
        reply = leadai_eval.MATCH_88.replace("11:30 AM or 12:00 PM", "12:00 PM or 2:00 PM")
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, invited=True, share_location=True)])
        self.assertNotIn(MAPS, self.body(outcome))
        self.assertTrue(self.body(outcome).endswith("or will you open a new one?"), self.body(outcome))
        self.assertEqual(self.state().invites, 0)

    # Chat 119 (turn 94, 10:39): a second question cut (filtered second_question, no slots rewrite: no open "when"),
    # share_office_location set with no invitation, and the link sent bare under the for-whom question (180196).
    SHOPS_119 = "These shops are for rent in International City clusters like France, England, China, Russia, Morocco, and Persia."
    FOR_WHOM_119 = "Is the shop for yourself, or are you checking for a client?"

    def test_chat_119_our_link_goes_labelled_as_our_office(self):
        self.at_clock(10, 39)
        message = self.voice("Haan, shops ke baare mein batayein")
        live = shop_answer(f"{self.SHOPS_119} {self.FOR_WHOM_119} What size shop are you looking for?", share_location=True)
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), f"{self.SHOPS_119} {self.FOR_WHOM_119}\n{LOCATED}")
        self.assertEqual((self.actions(message)["filtered"], self.state().invites), (["second_question"], 0))

    def test_chat_119_without_the_label_the_bare_link_went(self):
        self.at_clock(10, 39)
        message = self.voice("Haan, shops ke baare mein batayein")
        live = shop_answer(f"{self.SHOPS_119} {self.FOR_WHOM_119} What size shop are you looking for?", share_location=True)
        with patch.object(offers, "with_location", side_effect=lambda text, appended, language: f"{text}\n{appended}"):
            outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), f"{self.SHOPS_119} {self.FOR_WHOM_119}\n{MAPS}")  # 180196 as sent

    def test_chat_119_an_invitation_cut_takes_the_link_with_it(self):
        self.at_clock(10, 39)
        message = self.voice("Haan, shops ke baare mein batayein")
        invited = f"{self.SHOPS_119} {self.FOR_WHOM_119} I can hold a slot for you today at 12:00 PM or 2:00 PM — which is better?"
        outcome, _, _, _ = self.turn(message, [shop_answer(invited, invited=True, share_location=True)])
        self.assertEqual(self.body(outcome), f"{self.SHOPS_119} {self.FOR_WHOM_119}")
        self.assertEqual(self.state().invites, 0)
        # Asked for the location, it goes, labelled as our office's.
        self.later(5)
        asked = self.inbound("Location please?", seconds_ago=10)
        outcome, _, _, _ = self.turn(asked, [shop_answer("Our shops are in six clusters, 5 minutes from our office.", share_location=True)])
        self.assertEqual(self.body(outcome), f"Our shops are in six clusters, 5 minutes from our office.\n{LOCATED}")

    def test_the_label_in_every_language(self):
        self.assertEqual(set(offers.LOCATION_LABEL), {"en", "ar", "ur_latin", "ur", "hi_latin", "hi"})
        self.assertEqual(offers.with_location("Hi.", MAPS, "xx"), f"Hi.\n{LOCATED}")
        self.assertEqual(offers.with_location("Hi.", "", "en"), "Hi.")


# H. Discovery before a second invitation -----------------------------------------------------------------------------


class DiscoveryTests(Base):
    def test_chat_62_how_much_sqf_after_our_slots_asks_the_business(self):
        self.at_clock(10, 29)
        self.set_state(facts={**leadai_eval.FACTS_62, "licence_kind": "new", "trade_licence": "no"}, invites=1)
        self.ours(f"{NEW_ONE_62.replace('11:00 AM or 11:30 AM', '11:30 AM or 1:30 PM')}\n{LOCATED}", minutes_ago=2)
        message = self.inbound("How much sqf")
        outcome, _, _, _ = self.turn(message, [shop_answer(leadai_eval.AGAIN_62, invited=True)])
        self.assertEqual(
            self.body(outcome), "A Type 2 shop ranges from 600 to 800 sq ft, starting from AED 48,000 a year. What business will the shop be for?"
        )
        self.assertEqual((self.actions(message)["trimmed"], self.state().invites), (["discovery"], 1))

    def test_the_licence_next_when_the_business_is_known(self):
        self.set_state(facts={"for_client": False, "property_type": "shop", "business_activity": "restaurant", "size_sqft": 500}, invites=1)
        self.ours(TWO_SLOTS_NOW, minutes_ago=5)
        message = self.inbound("Is there parking?")
        outcome, _, _, _ = self.turn(message, [shop_answer(f"{shops.UNKNOWN_LINE} {TWO_SLOTS_NOW}", invited=True)])
        self.assertEqual(self.body(outcome), f"{shops.UNKNOWN_LINE} {rules.line('ask_licence', 'en')}")

    def test_never(self):
        base = {"for_client": False, "property_type": "shop", "size_sqft": 600, "licence_kind": "new"}
        earlier = [("assistant", TWO_SLOTS_NOW)]
        for name, (facts, said, invites, agreed) in {
            "the first invitation": (base, ["How much sqf"], 0, False),
            "they agreed": (base, ["Yes"], 1, True),
            "they ask to visit": (base, ["Can I come and see them?"], 1, False),
            "a time of theirs": (base, ["Tomorrow at 5 pm"], 1, False),
            "the location asked": (base, ["Where is your office?"], 1, False),
            "a need": ({**base, "need": "home", "wanted": "a studio"}, ["How much sqf"], 1, False),
            "everything known": ({**base, "business_activity": "salon"}, ["How much sqf"], 1, False),
        }.items():
            with self.subTest(name):
                answer = normal(shop_answer(TWO_SLOTS_NOW, invited=True))
                self.assertFalse(engine.discovery_first(answer, facts, earlier, said, invites, agreed=agreed, now=NOW))
        # Our last line asked the business already: no loop.
        answer = normal(shop_answer(TWO_SLOTS_NOW, invited=True))
        self.assertFalse(engine.discovery_first(answer, base, [("assistant", "What business will the shop be for?")], ["no idea"], 1, now=NOW))
        # A visit booked this turn (code's window or T18 upgrade among them): the confirmation goes, no question.
        booking = normal(shop_answer("Theek hai.", action="confirm", place="office", date="2026-10-12", time="17:00", invited=True))
        self.assertFalse(engine.discovery_first(booking, base, earlier, ["[voice note] barah saadhay barah baje"], 1, now=NOW))

    def test_without_the_guard_the_slots_went_again(self):
        self.set_state(facts={**leadai_eval.FACTS_62, "licence_kind": "new"}, invites=1)
        self.ours(TWO_SLOTS_NOW, minutes_ago=2)
        message = self.inbound("How much sqf")
        with patch.object(engine, "discovery_first", return_value=False):
            outcome, _, _, _ = self.turn(message, [shop_answer(f"Type 2 is 600-800 sq ft. {TWO_SLOTS_NOW}", invited=True)])
        self.assertIn("3:00 PM", self.body(outcome))


# I. The eval's scenarios, with the live answers -------------------------------------------------------------------

def without(module, name, value):
    return lambda: patch.object(module, name, return_value=value)


LAUNCH_SCENARIOS = {
    "shops-same-day-window-96": without(engine, "book_window", None),
    "shops-building-and-past-slot-96": without(claims, "settle", []),
    "shops-food-claim-91": without(claims, "settle", []),
    "shops-commission-78": without(claims, "settle", []),
    "shops-rent-higher-59": without(claims, "price_turn", ""),
    "shops-cheaper-100": without(claims, "price_turn", ""),
    "shops-tap-and-question-81": without(engine, "tap_with_words", ""),
    "shops-tap-type-with-words-88": without(engine, "tap_with_words", ""),
    "shops-invitation-cut-88": without(offers, "invitation_cut", False),
    "shops-table-repeat-91": without(claims, "drop_table_repeat", False),
    "shops-discovery-second-invite-62": without(engine, "discovery_first", False),
    "shops-new-one-62": without(offers, "fix_times", False),
    "shops-location-counted-81": lambda: uncounted_rewrite(),
    "shops-figures-asked-42": without(claims, "asks_figures", False),
}


class LaunchScenarioTests(TestCase):
    def test_each_passes_with_the_live_answer_and_fails_without_its_guard(self):
        for scenario_id, guard_off in LAUNCH_SCENARIOS.items():
            with self.subTest(scenario_id):
                run, _ = run_eval(scenario_id, RIGHT[scenario_id])
                self.assertEqual(run.failures, [])
                with guard_off():
                    run, _ = run_eval(scenario_id, RIGHT[scenario_id])
                self.assertNotEqual(run.failures, [], f"{scenario_id} passes without its guard")

    def test_the_prompt_carries_the_rules(self):
        for text in (
            "Never say which building, unit, floor, street or side (parking or front) a shop is in",
            '"We charge the normal commission. Please come and see the shops first, then we will discuss the details."',
            "Before inviting a second time, ask what business the shop is for, then their licence",
            "Slots are an hour from now at least and an hour apart, and never a time that has passed",
            "A tap sent with typed words: answer what they typed",
            "A budget below that \"from\" price: say honestly that it is our lowest",
        ):
            with self.subTest(text=text[:40]):
                self.assertIn(text, prompt.SHOPS_SYSTEM)
        self.assertNotIn("33,000", prompt.SHOPS_SYSTEM)  # the figures are SHOP FACTS', never the prompt's


# J. What a replay of every live reply through engine.settle found ----------------------------------------------------
# Every live text reply of the export (51), settled at the moment it went, and probes of the same guards: where the
# guards above went wrong. Each case shows the code before its fix patched back in.

FIGURES_42 = leadai_eval.BUYER_42[6][1]  # reply 179977, to "Wat is 33000/year" and "48000/year" right after the list
SENT_42 = [leadai_eval.BUYER_42[1][1], shop_flow.list_text("en", DEFAULT_SHOPS_FACTS)]
ASKED_42 = ["Wat is 33000/year", "48000/year"]


class ReplayClaimTests(SimpleTestCase):
    def answer(self, reply):
        return {"reply": reply, "language": "en", "facts": {"notes": []}, "send": True}

    def test_chat_42_their_own_figures_asked_about_are_the_answer(self):
        answer = {"reply": FIGURES_42}
        self.assertFalse(claims.drop_table_repeat(answer, SENT_42, ASKED_42, DEFAULT_SHOPS_FACTS))
        self.assertEqual(answer["reply"], FIGURES_42)
        for said in (["Is the rent monthly?"], ["33k per year?"], ["48000"], ["yearly or monthly"], ["سنوي؟"]):
            with self.subTest(said=said):
                self.assertTrue(claims.asks_figures(said, DEFAULT_SHOPS_FACTS))
        self.assertFalse(claims.asks_figures(["For me"], DEFAULT_SHOPS_FACTS))  # chat 91's "For me": the table again still goes
        # Before the fix the figures they asked about were "the table again", and only the question was left.
        with patch.object(claims, "asks_figures", return_value=False):
            self.assertTrue(claims.drop_table_repeat(answer, SENT_42, ASKED_42, DEFAULT_SHOPS_FACTS))
        self.assertEqual(answer["reply"], "What business will the shop be for?")

    def test_chat_59_one_deferral_never_two(self):
        # Live (reply 180036): "Rent security is usually a deposit, ... Good question — I'll have our agent confirm details like
        # service charge, DEWA, parking, and fit-out at the viewing. ...": the claim goes, and the reply defers once already.
        answer = self.answer(LIVE_59)
        self.assertEqual(claims.settle(answer, ["And give me full details including rent security"], known=KNOWN, office=ADDRESS), ["deposit"])
        self.assertEqual(answer["reply"].count("Good question"), 1, answer["reply"])
        self.assertNotIn("usually a deposit", answer["reply"])
        self.assertEqual(answer["facts"]["notes"], ["the security deposit"])  # still noted for our agent
        for line in claims.UNKNOWN.values():
            with self.subTest(line=line[:20]):
                self.assertTrue(claims._ANSWERS_LATER.search(line))
        for sentence in (
            "Our agent will drive you to the shops, 5 minutes away, and back.",
            "Aap hamare office aakar slot le sakte hain, jahan se hamara agent aapko shops dikhane le jayega.",
            "Our agent can discuss the best price for you at the viewing.",
        ):
            with self.subTest(sentence=sentence[:30]):
                self.assertIsNone(claims._ANSWERS_LATER.search(sentence))
        # Before the fix: the build pack's line was added in front of the model's own deferral.
        with patch.object(claims, "_ANSWERS_LATER", re.compile(r"(?!x)x")):
            answer = self.answer(LIVE_59)
            claims.settle(answer, ["And give me full details including rent security"], known=KNOWN, office=ADDRESS)
        self.assertEqual(answer["reply"].count("Good question"), 2)

    def test_a_thanks_or_an_ok_gets_no_good_question(self):
        answer = self.answer("The shops are close to Dragon Mart.")
        self.assertEqual(claims.settle(answer, ["ok"], known=KNOWN, office=ADDRESS), ["location"])
        self.assertEqual((answer["reply"], answer["send"]), ("", False))
        # Anything else they said still gets the unknown line, as before.
        answer = self.answer("The shops are close to Dragon Mart.")
        claims.settle(answer, ["Tell me more"], known=KNOWN, office=ADDRESS)
        self.assertEqual((answer["reply"], answer["send"]), (shops.UNKNOWN_LINE, True))

    def test_our_office_unit_is_ours(self):
        for sentence in ("Yes, Shop 20 is open until 7:30 PM today.", "Shop No. 20 is open now.", "shop #20 is our office."):
            with self.subTest(sentence):
                self.assertEqual(claims.topic_of(sentence, KNOWN, ADDRESS), "")
        for sentence in ("England cluster mein shop ka location Shop 20 hai.", "The shop is in Building V03.", "Your shop will be Shop 20."):
            with self.subTest(sentence):
                self.assertEqual(claims.topic_of(sentence, KNOWN, ADDRESS), "location")
        answer = self.answer("Yes, Shop 20 is open until 7:30 PM today.")
        self.assertEqual(claims.settle(answer, ["Are you open now?"], known=KNOWN, office=ADDRESS), [])
        self.assertEqual(answer["reply"], "Yes, Shop 20 is open until 7:30 PM today.")
        # Before the fix our office's unit read as a shop for rent: cut, and "Are you open now?" got "Good question".
        with patch.object(claims, "_office_unit", return_value=None):
            self.assertEqual(claims.topic_of("Yes, Shop 20 is open until 7:30 PM today.", KNOWN, ADDRESS), "location")


class ReplaySlotTests(SimpleTestCase):
    def test_our_opening_hours_are_no_offer(self):
        for text in (
            "We're open until 7:30 PM today.", "Our office closes at 7:30 PM, so tomorrow may be easier.",
            "Hamara office 7:30 PM tak khula hai.", "Shop 20 is open until 7:30 PM today.",
        ):
            with self.subTest(text):
                self.assertEqual(offers.offered(text, monday(19)), [])
                self.assertIsNone(offers.wrong_times(text, monday(19)))
        # An offer stays one, with a slot or a question beside the hours.
        tomorrow = hours.offer_pair(monday(19))
        self.assertEqual(offers.wrong_times("I can hold 7:30 PM for you today.", monday(19)), tomorrow)
        self.assertEqual(offers.wrong_times("We're open until 7:30 PM. Would 7:30 PM work for you?", monday(19)), tomorrow)
        # Before the fix, "open until 7:30 PM" at 7 PM was a slot too soon: two slots tomorrow, an invitation nobody made.
        with patch.object(offers, "states_hours", return_value=False):
            self.assertEqual(offers.wrong_times("We're open until 7:30 PM today.", monday(19)), tomorrow)


class ThirdInvitationSettleTests(SimpleTestCase):
    EARLIER = [("assistant", TWO_SLOTS_NOW), ("customer", "Is there parking?"), ("assistant", shops.UNKNOWN_LINE)]

    def settle(self, reply, said, playbook=lane.IC_SHOPS):
        answer = normal(shop_answer(reply, invited=True))
        return engine.settle(answer, self.EARLIER, said, 2, playbook=playbook, now=NOW, facts={"for_client": False})

    def test_no_third_pair_of_slots_unless_theirs_or_asked_for(self):
        pushed = self.settle(f"{shops.UNKNOWN_LINE} {TWO_SLOTS_NOW}", ["Is the shop on the ground floor?"])
        self.assertEqual((pushed["reply"], pushed["trimmed"], pushed["invited_to_meeting"]), (shops.UNKNOWN_LINE, ["invitation"], False))
        # A time they named stays, and so do slots they ask for.
        self.assertEqual(self.settle("Sure, 6:00 PM today works for you.", ["6 pm is fine for me"])["reply"], "Sure, 6:00 PM today works for you.")
        self.assertEqual(self.settle(TWO_SLOTS_NOW, ["Can I come and see them?"])["reply"], TWO_SLOTS_NOW)
        # Before the fix the build pack's slot line names no visit, so it went (and offers.fix_times only put its times right).
        with patch.object(offers, "pushes_visit", return_value=False):
            pushed = self.settle(f"{shops.UNKNOWN_LINE} {TWO_SLOTS_NOW}", ["Is the shop on the ground floor?"])
        self.assertEqual(pushed["reply"], f"{shops.UNKNOWN_LINE} {TWO_SLOTS_NOW}")

    def test_no_question_left_with_nothing_to_choose(self):
        # Chat 62's 10:31 reply settled at two invitations: its slots went, and "Which is better?" was left with nothing before it.
        live = (
            "Photos help, but seeing 2-3 shops side by side is much easier. I can hold a slot for you today at 11:00 AM or 11:30 AM "
            "at our office. Which is better?"
        )
        self.assertEqual(filters.drop_invitations(live), ("Photos help, but seeing 2-3 shops side by side is much easier.", True))
        # Chat 96's 12:26 reply, in words of no visit ("hamare office ka slot"): only a shops chat's also= reads them.
        urdu = "Walekum assalam! Aap 12:30 PM ke liye hamare office ka slot confirm kar sakte hain. Kya yeh waqt aapke liye theek hai?"
        self.assertEqual(filters.drop_invitations(urdu, also=offers.pushes_visit), ("Walekum assalam!", True))
        # Another question stays, and a reply nothing went from stays as it was, newlines and all.
        self.assertEqual(
            filters.drop_invitations("No problem. You can visit our office any time. What business will the shop be for?"),
            ("No problem. What business will the shop be for?", True),
        )
        same = "Type 1 is 400-550 sq ft.\nWhich type would you like?"
        self.assertEqual(filters.drop_invitations(same), (same, False))
        for question in (
            "Which is better?", "Which works better for you?", "kaunsa behtar rahega?", "Is this time OK for you?",
            "Kya yeh waqt aapke liye theek hai?", "هل يناسبك هذا الوقت؟",
        ):
            with self.subTest(question):
                self.assertTrue(filters._asks_about_the_offer(question))
        for question in (
            "Which type would you like to see?", "What size do you need?", "Is this location OK?",
            "Is the shop for yourself, or are you checking for a client?",
        ):
            with self.subTest(question):
                self.assertFalse(filters._asks_about_the_offer(question))

    def test_a_general_chat_keeps_its_own_time_offer(self):
        # The general prompt offers its own times ("7 PM or 7:30 PM"), read by its rules as before; only the question
        # left with nothing to choose goes there too (the same bug).
        offer = "Our specialist can show you options. Would 7 PM or 7:30 PM work for you?"
        self.assertEqual(self.settle(offer, ["Is there parking?"], playbook=lane.GENERAL)["reply"], offer)
        dangling = self.settle("No problem. You can visit our office any time. Which is better?", ["No, I can't"], playbook=lane.GENERAL)
        self.assertEqual(dangling["reply"], "No problem.")


class ReplayTurnTests(Base):
    FACTS = {"for_client": False, "property_type": "shop", "intent": "rent"}

    def chat_42(self):
        self.set_state(facts=dict(self.FACTS))
        self.ours(SENT_42[0], minutes_ago=4)
        self.ours(SENT_42[1], minutes_ago=3, shop_list=True)
        self.inbound(ASKED_42[0], seconds_ago=40)
        return self.inbound(ASKED_42[1], seconds_ago=30)

    def test_chat_42_wat_is_33000_a_year_gets_its_answer(self):
        message = self.chat_42()
        outcome, _, _, _ = self.turn(message, [shop_answer(FIGURES_42)])
        self.assertEqual(self.body(outcome), FIGURES_42)

    def test_chat_42_without_the_fix_only_the_question_went(self):
        message = self.chat_42()
        with patch.object(claims, "asks_figures", return_value=False):
            outcome, _, _, _ = self.turn(message, [shop_answer(FIGURES_42)])
        self.assertEqual(self.body(outcome), "What business will the shop be for?")

    def test_no_third_invitation_in_words_of_no_visit(self):
        # Invited twice, and our last line offered nothing: their question gets its answer, never a third pair of slots.
        self.set_state(facts={**self.FACTS, "business_activity": "salon", "licence_kind": "new"}, invites=2)
        self.ours(shops.UNKNOWN_LINE, minutes_ago=5)
        message = self.inbound("Is there a washroom inside?")
        outcome, _, _, _ = self.turn(message, [shop_answer(f"{shops.UNKNOWN_LINE} {TWO_SLOTS_NOW}", invited=True)])
        self.assertEqual(self.body(outcome), shops.UNKNOWN_LINE)
        self.assertEqual((self.actions(message)["trimmed"], self.state().invites), (["invitation"], 2))
