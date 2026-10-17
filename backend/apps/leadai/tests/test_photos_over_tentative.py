"""The first live shops test (2026-10-15, +971563072771 on the Coastline number, lead 79229), and
what it showed:

- A. "If possible to send me photo first" got the model's words ("Photos help, but seeing 2-3 shops
  side by side is much easier" and two slots) and no photos: the model answered it tentative, and no
  shops step went over a tentative. Photos, a video or the shop types asked for now get their step
  over a tentative of the model's, which then changes nothing (engine.model_step, engine.comes);
- B. the model's own two slots ("today at 11:00 AM or 11:30 AM") were recorded as a tentative visit at
  11:00, a time the customer never named: such a tentative records no visit, or one in their words
  alone (engine.own_offer);
- C. with no visit recorded for it, a question after our two slots made the model offer them again,
  which counted as the second invitation: slots offered again after words that turn nothing down are
  that same invitation (engine.reoffered, settle).

Each "as the model answered" test feeds the live turn's answer, rebuilt from its reply, action and
time, and passes only with the fix. The fakes are test_assistant's: the clock is Monday 12 October
2026, 14:00 Dubai, so the live 11:00 AM and 11:30 AM are 2:30 PM and 3:00 PM here.
"""

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.leadai import lane
from apps.leadai.assistant import engine, rules, shop_flow
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_gate_2b_guards import BOOKED_AT_FOUR, EVENING_SLOTS, KNOWN, LICENCE_COPY, LICENCE_INVITE_1, NUDGE, DED, normal, run_eval
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, at, shop_answer

FIRST = at(12, 14, 30)  # live: today at 11:00 AM
PHOTO_FIRST = "If possible to send me photo first"
LIVE_FACTS = {**leadai_eval.LIVE_KNOWN, "licence_kind": "new"}
ASKED_LICENCE = leadai_eval.LIVE_ASKED_LICENCE[-1][1]  # our 10:26 line: "... or will you be opening a new one?"
OBJECTION = (
    "Photos help, but seeing 2-3 shops side by side is much easier. I can hold a slot for you today at 2:30 PM or 3:00 PM at "
    "our office. Which is better?"
)
PARKING = (
    "Good question — I'll have our agent confirm that for you at the viewing. I can hold a slot for you today at 2:30 PM or 3:00 PM "
    "at our office. Which is better?"
)


def invitation_1027(**extra):
    """The model's answer to "New" "One" (a new licence), as live: its own two slots, tentative at the first."""
    return shop_answer(
        leadai_eval.LIVE_INVITE, action="tentative", place="office", date="2026-10-12", time="14:30", words="One", invited=True,
        share_location=True, facts={"licence_kind": "new", "trade_licence": "no"}, **extra,
    )


def objection_1031(said=PHOTO_FIRST, time="14:30"):
    """The model's answer to "If possible to send me photo first", as live: the objection line, two slots, tentative."""
    return shop_answer(OBJECTION, action="tentative", place="office", date="2026-10-12", time=time, words=said, invited=True)


def appointment_16():
    """The live tentative its own invitation opened, built and never saved."""
    return LeadAiAppointment(status="tentative", place="office", starts_at=FIRST, note="One", customer_words="One")


def step(completion, said, *, appointment=None, agreed=False, known=LIVE_FACTS, **flags):
    out = normal(completion)
    options = {"still_invalid": False, "when": None, "quiet": False, "list_sent": True, "licence_asked": False}
    options.update(flags)
    return out, engine.model_step(out, known, said, NOW, appointment=appointment, agreed=agreed, **options)


def own(completion, said, *, words="I need 600sqf", our_last=ASKED_LICENCE, yes=False, appointment=None):
    out = normal(completion)
    done = engine.own_offer(out, appointment=appointment, said=said, words=f"{words} {said}".strip(), our_last=our_last, yes=yes, now=NOW)
    return out, done


# A. Photos or the types asked for, over a tentative --------------------------------------------------


class PhotosOverTentativeTests(SimpleTestCase):
    def test_the_live_photo_request_gets_type_2s_media_over_appointment_16(self):
        out, got = step(objection_1031(), PHOTO_FIRST, appointment=appointment_16(), agreed=True)
        self.assertEqual(got, {"kind": shop_flow.MEDIA, "type": "type_2"})
        self.assertEqual(out["shop_step"], got)
        self.assertEqual(out["appointment"], engine.NO_TIME)  # nothing is written for appointment 16
        # The same with no visit open, and for the shop types.
        out, got = step(objection_1031(), PHOTO_FIRST)
        self.assertEqual((got, out["appointment"]), ({"kind": shop_flow.MEDIA, "type": "type_2"}, engine.NO_TIME))
        out, got = step(objection_1031("show me the options"), "show me the options", appointment=appointment_16(), agreed=True)
        self.assertEqual((got, out["appointment"]), ({"kind": shop_flow.LIST}, engine.NO_TIME))
        # No type in view: the list, as for a plain answer.
        out, got = step(objection_1031(), PHOTO_FIRST, known={"for_client": False, "property_type": "shop"})
        self.assertEqual(got, {"kind": shop_flow.LIST})

    def test_their_own_words_of_coming_keep_the_tentative_and_the_photos_still_go(self):
        # Probed by the review: each named an hour or a hedge of their own, beside the photo request.
        for said in (
            "photos bhejo, 8 baje aaunga",
            "send pics, will come around 8",
            "Send me photos please, I'll try to come in the evening",
            "photos bhej do, shaam ko aaunga",
            "ابعث الصور، ممكن أمر عليكم بعد الدوام",
            "फोटो भेज दो, शाम को आऊँगा",
        ):
            for appointment, agreed in ((None, False), (appointment_16(), True)):
                with self.subTest(said=said, open=appointment is not None):
                    out, got = step(objection_1031(said, time="19:30"), said, appointment=appointment, agreed=agreed)
                    self.assertEqual(got, {"kind": shop_flow.MEDIA, "type": "type_2"})
                    self.assertEqual((out["appointment"]["action"], out["appointment"]["customer_words"]), ("tentative", said))

    def test_a_yes_to_the_nudge_that_asks_for_photos_still_gets_the_two_slots(self):
        # The model booked a time nobody named (eval shops-nudge-yes); unasked_confirm's two slots go first.
        said = "Yes, book me for this evening and send me photos of the shop"
        out = normal(shop_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00"))
        self.assertTrue(engine.unasked_confirm(out, at(12, 16), None, NOW, (), said=said, words=f"Around 450 sq ft {said}", our_last=NUDGE, ours=NUDGE))
        agreed = engine.agreed_to_come(visit_open=False, our_last=NUDGE, texts=[said])
        yes = agreed or (engine.visit_offered(NUDGE) and engine.opens_with_yes([said]))
        self.assertEqual(engine.own_offer(out, appointment=None, said=said, words=said, our_last=NUDGE, yes=yes, now=NOW), "")
        got = engine.model_step(
            out, KNOWN, said, NOW, appointment=None, agreed=agreed, still_invalid=False, when=None, quiet=False, list_sent=True,
            licence_asked=False,
        )
        self.assertEqual(got, {"kind": shop_flow.SLOTS, "slots": [at(12, 17), at(12, 19)]})
        self.assertEqual(shop_flow.slots_text("en", got["slots"], NOW), EVENING_SLOTS)
        self.assertEqual((out["appointment"]["action"], out["appointment"]["customer_words"]), ("tentative", said))

    def test_nothing_that_must_go_instead_is_replaced(self):
        tentative = objection_1031("send photos and call me")
        confirm = shop_answer("", action="confirm", place="office", date="2026-10-12", time="17:00")
        cases = {
            "a handover": ({}, shop_answer("Our agent will call you.", action="tentative", place="office", handover="call_requested"), "send photos and call me"),
            "a person has the chat": ({"quiet": True}, tentative, "send photos please"),
            "the location asked for": ({}, tentative, "send photos and the location please"),
            "a time refused twice": ({"still_invalid": True}, tentative, "send photos please"),
            "a booking": ({"when": at(12, 17)}, confirm, "send photos, I will come today at 5 pm"),
        }
        for name, (flags, completion, said) in cases.items():
            with self.subTest(name):
                out, got = step(completion, said, **flags)
                self.assertIsNone(got)
                self.assertIn(out["appointment"]["action"], ("tentative", "confirm"))
        out = normal(tentative)
        out["slot_taken"] = True  # another client's slot: code's two free ones go
        got = engine.model_step(
            out, LIVE_FACTS, "send photos please", NOW, appointment=None, agreed=False, still_invalid=False, when=None, quiet=False,
            list_sent=True, licence_asked=False,
        )
        self.assertIsNone(got)

    def test_without_a_request_for_photos_or_the_types_the_tentative_keeps_its_rules(self):
        # The licence request replaces only the model's own invitation; anything else keeps the model's words.
        out, got = step(shop_answer(LICENCE_INVITE_1, action="tentative", invited=True, facts=DED), "Yes I have a DED licence", known=KNOWN)
        self.assertEqual((got, out["appointment"]), ({"kind": shop_flow.LICENCE_ASK}, engine.NO_TIME))
        out, got = step(objection_1031("Where are the shops?"), "Where are the shops?", appointment=appointment_16(), agreed=True)
        self.assertEqual((got, out["appointment"]["action"]), (None, "tentative"))

    def test_a_yes_to_our_offer_with_the_photo_request_keeps_its_tentative(self):
        # own_offer finds it theirs (a message that opens with a yes): the photos go, and so does the visit, in their words.
        said = "Yes please, send photos first"
        yes = engine.visit_offered(leadai_eval.LIVE_INVITE) and engine.opens_with_yes([said])
        out = normal(objection_1031(said))
        self.assertEqual(engine.own_offer(out, appointment=None, said=said, our_last=leadai_eval.LIVE_INVITE, yes=yes, now=NOW), engine.OWN_UNTIMED)
        got = engine.model_step(
            out, LIVE_FACTS, said, NOW, appointment=None, agreed=False, still_invalid=False, when=None, quiet=False, list_sent=True,
            licence_asked=False,
        )
        self.assertEqual((got, out["appointment"]["action"], out["appointment"]["time"]), ({"kind": shop_flow.MEDIA, "type": "type_2"}, "tentative", None))


# B. The model's own slot offer records no visit ------------------------------------------------------


class OwnOfferTests(SimpleTestCase):
    def test_the_live_invitation_records_no_visit(self):
        out, done = own(invitation_1027(), "New One")
        self.assertEqual(done, engine.OWN_DROPPED)
        self.assertEqual(out["appointment"], engine.NO_TIME)
        self.assertTrue(out["invited_to_meeting"])  # still an invitation, counted when it goes
        # The same with a day and no time, or neither, beside our two slots.
        for date in ("2026-10-12", None):
            with self.subTest(date=date):
                out, done = own(shop_answer(leadai_eval.LIVE_INVITE, action="tentative", place="office", date=date, invited=True), "New One")
                self.assertEqual((done, out["appointment"]), (engine.OWN_DROPPED, engine.NO_TIME))

    def test_a_question_or_a_request_to_see_says_nothing_of_coming(self):
        # The review's probe: customer_asks (any "?", "see", "show") would have kept the model's 2:30 PM.
        for said in ("New. Is the rent yearly?", "New one, can I see type 2 first", "New licence, what is the deposit", "How much sqf", PHOTO_FIRST):
            with self.subTest(said):
                out, done = own(invitation_1027(), said)
                self.assertEqual((done, out["appointment"]), (engine.OWN_DROPPED, engine.NO_TIME))

    def test_after_our_offer_a_tentative_at_one_of_our_slots_is_still_ours(self):
        # their_time reads anything but a plain yes to two slots as a pick (unasked_confirm's confirm); a
        # tentative at our first slot after "How much sqf" is our offer said again.
        out, done = own(objection_1031("How much sqf"), "How much sqf", our_last=leadai_eval.LIVE_INVITE)
        self.assertEqual((done, out["appointment"]), (engine.OWN_DROPPED, engine.NO_TIME))
        self.assertTrue(engine.their_time(FIRST, said="How much sqf", our_last=leadai_eval.LIVE_INVITE, now=NOW))

    def test_their_day_or_hour_stays_and_their_coming_keeps_it_without_ours(self):
        tomorrow_11 = shop_answer("Tomorrow at 11:00 AM or 5:00 PM?", action="tentative", place="office", date="2026-10-13", time="11:00", invited=True)
        today = {"place": "office", "date": "2026-10-12", "invited": True}
        stays = {
            "their hour": (shop_answer("Sure.", action="tentative", time="17:00", **today), "I'll come around 5"),
            "an hour as the model read it": (shop_answer("Sure.", action="tentative", time="19:30", **today), "8 baje aaunga"),
            "their day, no time": (shop_answer("Tomorrow?", action="tentative", place="office", date="2026-10-13", invited=True), "Maybe tomorrow"),
            "their day and hour": (shop_answer("", action="tentative", place="office", date="2026-10-13", time="17:00"), "I may come tomorrow at 5 pm"),
        }
        for name, (completion, said) in stays.items():
            with self.subTest(name):
                out, done = own(completion, said)
                self.assertEqual((done, out["appointment"]), ("", normal(completion)["appointment"]))
        untimed = {
            "their day, our hour": (tomorrow_11, "Maybe tomorrow", "2026-10-13"),
            "their coming, our day and hour": (shop_answer("Sure.", action="tentative", time="17:00", **today), "shaam ko aaunga", None),
            "I will come": (invitation_1027(), "New. I will come", None),
            "a hedge": (invitation_1027(), "Maybe", None),
        }
        for name, (completion, said, date) in untimed.items():
            with self.subTest(name):
                out, done = own(completion, said)
                self.assertEqual(done, engine.OWN_UNTIMED)
                self.assertEqual(out["appointment"], {"action": "tentative", "place": "office", "date": date, "time": None, "customer_words": said})

    def test_a_yes_to_our_offer_keeps_a_tentative_in_their_words(self):
        # Never dropped after a yes (the review's plan-2 finding): agreed_to_come stays true on later turns.
        out, done = own(shop_answer(TWO_SLOTS_NOW, action="tentative", place="office", date="2026-10-12", time="14:30"), "Yes", our_last=TWO_SLOTS_NOW, yes=True)
        self.assertEqual(done, engine.OWN_UNTIMED)
        self.assertEqual(out["appointment"], {"action": "tentative", "place": "office", "date": None, "time": None, "customer_words": "Yes"})
        out, done = own(shop_answer("Great.", action="tentative", place="office", date="2026-10-12", time="18:00"), "Yes", our_last=NUDGE, yes=True)
        self.assertEqual((done, out["appointment"]["time"]), (engine.OWN_UNTIMED, None))
        # A yes to the one slot we offered took it.
        one = "Would tomorrow at 5 PM work for you to visit our office?"
        out, done = own(shop_answer("", action="tentative", place="office", date="2026-10-13", time="17:00"), "Yes", our_last=one, yes=True)
        self.assertEqual((done, out["appointment"]["time"]), ("", "17:00"))

    def test_a_message_that_opens_with_a_yes_to_our_offer_is_a_yes(self):
        for texts in (["Yes please, send me the location"], ["Sure, where is it?"], ["haan ji location bhej do"], ["ok"], ["How much sqf", "Yes"]):
            with self.subTest(texts):
                self.assertTrue(engine.opens_with_yes(texts))
        for texts in (["ok how much sqf"], ["How much sqf"], ["No"], ["New", "One"], [""]):
            with self.subTest(texts):
                self.assertFalse(engine.opens_with_yes(texts))
        # The nudge's "Yes please, send me the location": its tentative stays, in their words (test_gate_2b_findings).
        said = "Yes please, send me the location"
        yes = engine.visit_offered(NUDGE) and engine.opens_with_yes([said])
        completion = shop_answer("Great.", action="tentative", place="office", date="2026-10-12", time="18:00", share_location=True)
        out, done = own(completion, said, our_last=NUDGE, yes=yes)
        self.assertEqual((done, out["appointment"]["customer_words"], out["theirs"]), (engine.OWN_UNTIMED, said, True))
        # A yes to our licence question is no yes to coming: it is never asked here (visit_offered).
        self.assertFalse(engine.visit_offered(ASKED_LICENCE))

    def test_left_alone(self):
        # A deferral said in two messages (the deferral rule takes one), which offers no time.
        deferral = shop_answer(rules.line("let_me_know", "en"), action="tentative", place="office", words="I will let you know")
        out, done = own(deferral, "Let me discuss with my partner I will let you know")
        self.assertEqual((done, out["appointment"]["action"]), ("", "tentative"))
        cases = {
            "a visit open": ({"appointment": appointment_16()}, invitation_1027()),
            "a handover in it": ({}, invitation_1027(handover="customer_asked_human")),
            "a call": ({}, shop_answer("Our agent will call you.", action="tentative", place="call", date="2026-10-12", time="14:30")),
            "no tentative": ({}, shop_answer(leadai_eval.LIVE_INVITE, invited=True)),
        }
        for name, (options, completion) in cases.items():
            with self.subTest(name):
                out = normal(completion)
                before = dict(out["appointment"])
                done = engine.own_offer(out, said="New One", words="New One", our_last=ASKED_LICENCE, now=NOW, appointment=options.get("appointment"))
                self.assertEqual((done, out["appointment"]), ("", before))
        for flag, value in (("slot_taken", True), ("converted", "holding")):
            with self.subTest(flag):
                out = normal(invitation_1027())
                out[flag] = value
                self.assertEqual(engine.own_offer(out, appointment=None, said="New One", our_last=ASKED_LICENCE, now=NOW), "")
                self.assertEqual(out["appointment"]["action"], "tentative")

    def test_a_confirm_of_our_own_slot_gets_its_two_slots_and_no_visit(self):
        # The model booking its own slot to "New" "One" became unasked_confirm's tentative in their words: no
        # visit of theirs either. Its two free slots still go.
        said = "New One"
        out = normal(shop_answer("", action="confirm", place="office", date="2026-10-12", time="14:30", facts={"licence_kind": "new"}))
        self.assertTrue(engine.unasked_confirm(out, FIRST, None, NOW, (), said=said, words=f"I need 600sqf {said}", our_last=ASKED_LICENCE, ours=ASKED_LICENCE))
        self.assertEqual(engine.own_offer(out, appointment=None, said=said, words=said, our_last=ASKED_LICENCE, now=NOW), engine.OWN_DROPPED)
        got = engine.model_step(
            out, LIVE_FACTS, said, NOW, appointment=None, agreed=False, still_invalid=False, when=None, quiet=False, list_sent=True,
            licence_asked=False,
        )
        self.assertEqual((got["kind"], out["appointment"]), (shop_flow.SLOTS, engine.NO_TIME))
        # After a yes, or words of coming, it stays in their words (eval shops-nudge-yes).
        for said, our_last, agreed in (("Yes", TWO_SLOTS_NOW, True), ("Yes, book me for this evening", NUDGE, False)):
            with self.subTest(said):
                out = normal(shop_answer("", action="confirm", place="office", date="2026-10-12", time="16:00"))
                self.assertTrue(engine.unasked_confirm(out, at(12, 16), None, NOW, (), said=said, our_last=our_last))
                self.assertEqual(engine.own_offer(out, appointment=None, said=said, our_last=our_last, yes=agreed, now=NOW), "")
                self.assertEqual((out["appointment"]["action"], out["appointment"]["customer_words"]), ("tentative", said))


# C. Slots offered again are the same invitation ---------------------------------------------------------


class ReofferTests(SimpleTestCase):
    def test_what_turns_our_offer_down(self):
        for text in (
            "No", "No, I told you I can't come to the office. Just send me the details here", "I am busy this week", "not today",
            "Maybe later", "I will let you know", "Can we do another day?", "لا", "مشغول اليوم", "abhi nahi", "nahi aa sakta aaj",
        ):
            with self.subTest(text):
                self.assertTrue(engine.turns_down([text]))
        for text in ("How much sqf", PHOTO_FIRST, "Tomorrow?", "No problem, what is the deposit?", "Is there parking?", "لازم أشوف", "Yes", ""):
            with self.subTest(text):
                self.assertFalse(engine.turns_down([text]))

    def test_reoffered_only_after_our_offer_and_never_a_yes(self):
        self.assertTrue(engine.reoffered(agreed=False, our_last=leadai_eval.LIVE_INVITE, texts=["How much sqf"]))
        self.assertTrue(engine.reoffered(agreed=False, our_last=NUDGE, texts=["Where are the shops?"]))
        self.assertFalse(engine.reoffered(agreed=False, our_last=ASKED_LICENCE, texts=["How much sqf"]))  # we offered nothing
        self.assertFalse(engine.reoffered(agreed=False, our_last=leadai_eval.LIVE_INVITE, texts=["Not today, I am busy"]))
        self.assertFalse(engine.reoffered(agreed=True, our_last=leadai_eval.LIVE_INVITE, texts=["Yes"]))  # agreed_to_come's

    def test_the_live_chat_counts_one_invitation(self):
        earlier = [("assistant", ASKED_LICENCE), ("customer", "New"), ("customer", "One"), ("assistant", leadai_eval.LIVE_INVITE)]
        # 10:29, "How much sqf" after our two slots: the same invitation again, neither counted nor cut.
        again = normal(shop_answer(leadai_eval.LIVE_AGAIN, invited=True))
        reoffer = engine.reoffered(agreed=False, our_last=leadai_eval.LIVE_INVITE, texts=["How much sqf"])
        engine.settle(again, earlier, ["How much sqf"], 1, reoffer=reoffer, playbook=lane.IC_SHOPS, now=NOW, facts=LIVE_FACTS)
        # Neither counted nor cut; its live slots (2:30 PM, half an hour away, and 3:00 PM) are code's valid pair now (offers.fix_times).
        size = "A Type 2 shop ranges from 600 to 800 sq ft, starting from AED 48,000 a year."
        self.assertEqual((again["invited_to_meeting"], again["reply"], again.get("trimmed")), (False, f"{size} {TWO_SLOTS_NOW}", ["times"]))
        # A third question, still one invitation: its slots stay, valid ones.
        third = normal(shop_answer(PARKING, invited=True))
        earlier += [("customer", "How much sqf"), ("assistant", leadai_eval.LIVE_AGAIN)]
        reoffer = engine.reoffered(agreed=False, our_last=leadai_eval.LIVE_AGAIN, texts=["Is there parking?"])
        engine.settle(third, earlier, ["Is there parking?"], 1, reoffer=reoffer, playbook=lane.IC_SHOPS, now=NOW, facts=LIVE_FACTS)
        self.assertEqual((third["invited_to_meeting"], third["reply"]), (False, f"{PARKING.split(' I can hold')[0]} {TWO_SLOTS_NOW}"))
        # As the fix was first proposed (no reoffer), 10:29 was the second invitation and the next reply lost its slots.
        cut = normal(shop_answer(PARKING, invited=True))
        engine.settle(cut, earlier, ["Is there parking?"], 2, playbook=lane.IC_SHOPS, now=NOW, facts=LIVE_FACTS)
        self.assertEqual(cut.get("trimmed"), ["invitation"])
        # A refusal: the slots offered after it are a new invitation, counted (the cap reads it).
        refused = normal(shop_answer("No problem. Would Saturday at 11 AM or 5 PM suit you better?", invited=True))
        reoffer = engine.reoffered(agreed=False, our_last=leadai_eval.LIVE_INVITE, texts=["I am busy today"])
        engine.settle(refused, earlier, ["I am busy today"], 1, reoffer=reoffer, playbook=lane.IC_SHOPS, now=NOW, facts=LIVE_FACTS)
        self.assertTrue(refused["invited_to_meeting"])


# The eval, with the answers the model gave live ----------------------------------------------------------


class LiveTestEvalTests(TestCase):
    def test_shops_photos_after_invite_passes_with_the_live_answer(self):
        completion = eval_answer(OBJECTION, action="tentative", place="office", date="2026-10-12", time="14:30", words=PHOTO_FIRST, invited=True)
        run, calls = run_eval("shops-photos-after-invite", completion)
        self.assertEqual((len(calls), run.failures), (1, []))
        self.assertEqual((run.answer["shop_step"], run.action, run.out_by), ({"kind": shop_flow.MEDIA, "type": "type_2"}, "none", leadai_eval.CODE))
        self.assertTrue(run.out.startswith("[the video and photos of Type 2"), run.out)
        # As live before: no step over the model's tentative, its words and the tentative went.
        with patch("apps.leadai.assistant.engine.model_step", side_effect=lambda answer, *a, **k: None):
            run, _ = run_eval("shops-photos-after-invite", completion)
        self.assertIn("shops step none, expected media", run.failures)
        self.assertIn("action tentative, expected none", run.failures)

    def test_shops_invite_no_tentative_passes_with_the_live_answer(self):
        completion = eval_answer(
            leadai_eval.LIVE_INVITE, action="tentative", place="office", date="2026-10-12", time="14:30", words="One", invited=True,
            share_location=True, facts={"licence_kind": "new", "trade_licence": "no"},
        )
        run, calls = run_eval("shops-invite-no-tentative", completion)
        self.assertEqual((len(calls), run.failures), (1, []))
        self.assertEqual((run.action, run.answer["invited_to_meeting"], run.answer["appointment"]), ("none", True, engine.NO_TIME))
        with patch("apps.leadai.assistant.engine.own_offer", return_value=""):
            run, _ = run_eval("shops-invite-no-tentative", completion)
        self.assertIn("action tentative, expected none", run.failures)

    def test_what_must_not_change(self):
        for scenario_id in (
            "shops-photos", "shops-type-tap", "shops-licence-ask", "shops-invite", "shops-nudge-yes", "yes-to-slot", "exact-time",
            "exact-time-may", "defer-with-time", "booked-reschedule", "booked-same-time", "owner-viewing-slot", "job-applicant",
            "lang-voice-urdu", "invites-exhausted",
        ):
            with self.subTest(scenario_id):
                run, _ = run_eval(scenario_id, RIGHT[scenario_id])
                self.assertEqual(run.failures, [])
        # The 2b gate's answers keep their guards: the evening slots for the nudge's yes, the licence copy.
        run, _ = run_eval("shops-nudge-yes", eval_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00"))
        self.assertEqual((run.failures, run.out, run.action), ([], EVENING_SLOTS, "tentative"))
        run, _ = run_eval("shops-licence-ask", eval_answer(LICENCE_INVITE_1, action="tentative", invited=True, share_location=True, facts=DED))
        self.assertEqual((run.failures, run.out), ([], LICENCE_COPY))

    def test_what_changes_in_the_scenarios_named(self):
        # The nudge's yes, answered tentative this evening by the model: kept, in their own words now.
        run, _ = run_eval("shops-nudge-yes", RIGHT["shops-nudge-yes"])
        self.assertEqual((run.failures, run.action, run.answer["appointment"]["customer_words"]), ([], "tentative", "Yes, book me for this evening"))
        # A tentative answer to "Can you send me some photos of the shop?": the photos go now.
        tentative = eval_answer("Sure! I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?", action="tentative", place="office", date="2026-10-12", time="14:30", invited=True)
        run, _ = run_eval("shops-photos", tentative)
        self.assertEqual((run.failures, run.action), ([], "none"))


# The turn itself, the gateway faked -----------------------------------------------------------------------


class LiveTurnTests(ShopsBase):
    def open_16(self):
        appointment = LeadAiAppointment(
            conversation=self.conversation, status="tentative", place="office", starts_at=FIRST, note="One", customer_words="One",
            crm_entity="lead", crm_id=555, details=engine._details(LIVE_FACTS),
        )
        appointment.log("tentative", note="One", place="office", start=FIRST.isoformat())
        appointment.save()
        return appointment

    def test_the_photo_request_with_appointment_16_open_sends_type_2s_media_and_changes_nothing(self):
        self.set_state(facts=dict(LIVE_FACTS), invites=1)
        appointment = self.open_16()
        before = (appointment.status, appointment.starts_at, appointment.note, appointment.customer_words, list(appointment.history))
        self.ours(leadai_eval.LIVE_INVITE, minutes_ago=5)
        self.inbound("How much sqf", seconds_ago=4 * 60)
        self.ours(leadai_eval.LIVE_AGAIN, minutes_ago=3)
        message = self.inbound(PHOTO_FIRST)
        outcome, calls, crm_delay, _ = self.turn(message, [objection_1031()])
        self.assertEqual((len(calls), outcome.reason), (1, "shop media queued (type_2)"))
        turn = LeadAiTurn.objects.get(inbound=message)
        self.media_delay.assert_called_once_with(self.conversation.pk, "type_2", turn.pk, "en", True)  # the video, the photos, the card
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.starts_at, appointment.note, appointment.customer_words, appointment.history), before)
        crm_delay.assert_not_called()
        self.assertFalse(LeadAiAlert.objects.filter(kind="tentative").exists())
        actions = self.actions(message)
        self.assertEqual(
            (actions["shop_step"], actions["shop_type"], actions["action"], actions["effective"], actions["invited_to_meeting"]),
            ("media", "type_2", "none", "none", False),
        )
        self.assertEqual(self.state().invites, 1)

    def test_our_invitation_records_no_visit(self):
        self.set_state(facts=dict(leadai_eval.LIVE_KNOWN))
        self.ours(ASKED_LICENCE, minutes_ago=2)
        self.inbound("New", seconds_ago=40)
        message = self.inbound("One", seconds_ago=30)
        outcome, calls, crm_delay, _ = self.turn(message, [invitation_1027()])
        self.assertEqual(len(calls), 1)
        # Its live slots (half an hour away, half an hour apart) are code's valid pair now (offers.fix_times).
        great = "A Type 2 shop is great, starting from AED 48,000 a year."
        self.assertTrue(self.body(outcome).startswith(f"{great} {TWO_SLOTS_NOW}"), self.body(outcome))
        self.assertFalse(LeadAiAppointment.objects.exists())  # no "Tentative - Time mentioned" banner
        crm_delay.assert_not_called()  # no MEETING TENTATIVE on the lead
        self.assertFalse(LeadAiAlert.objects.filter(kind="tentative").exists())
        actions = self.actions(message)
        self.assertEqual((actions["action"], actions["own_offer"], actions["invited_to_meeting"]), ("none", "dropped", True))
        self.assertEqual(self.state().invites, 1)

    def test_the_live_chat_replayed_one_invitation_slots_after_a_question_and_the_photos(self):
        self.set_state(facts=dict(leadai_eval.LIVE_KNOWN))
        self.ours(ASKED_LICENCE, minutes_ago=2)
        self.inbound("New", seconds_ago=40)
        self.turn(self.inbound("One", seconds_ago=30), [invitation_1027()])
        self.assertEqual(self.state().invites, 1)
        # 10:29: the same slots again, for a question.
        self.later(2)
        message = self.inbound("How much sqf", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer(leadai_eval.LIVE_AGAIN, invited=True)])
        # Its live slots are code's valid pair now (an hour ahead at least: it is 2:02 PM; offers.fix_times).
        size = "A Type 2 shop ranges from 600 to 800 sq ft, starting from AED 48,000 a year."
        later_pair = "I can hold a slot for you today at 3:30 PM or 5:30 PM — which is better?"
        self.assertEqual(self.body(outcome), f"{size} {later_pair}")
        self.assertEqual((self.actions(message)["reoffer"], self.state().invites), (True, 1))
        # A third question still gets its slots, and it is still one invitation; the same two asked about in other words.
        self.later(3)
        message = self.inbound("Is there parking?", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [shop_answer(PARKING, invited=True, facts={"notes": ["parking"]})])
        self.assertEqual(self.body(outcome), f"{PARKING.split(' I can hold')[0]} Which one suits you better: today at 3:30 PM or 5:30 PM?")
        self.assertEqual(self.state().invites, 1)
        # 10:31: the photos.
        self.later(5)
        message = self.inbound(PHOTO_FIRST, seconds_ago=20)
        outcome, _, crm_delay, _ = self.turn(message, [objection_1031()])
        self.assertEqual(outcome.reason, "shop media queued (type_2)")
        self.media_delay.assert_called_once()
        self.assertFalse(LeadAiAppointment.objects.exists())
        crm_delay.assert_not_called()
        self.assertEqual(self.state().invites, 1)



class GeneralTurnTests(GeneralBase):
    def test_a_general_chat_keeps_its_tentative_and_its_counting(self):
        # The general playbook is unchanged: the model's tentative for its own times is still recorded, and a
        # re-offer after a question still counts (no reoffered there).
        self.ours("Thank you. Would you like to visit our office? We're open Monday to Saturday, 10 AM to 8 PM.", minutes_ago=2)
        message = self.inbound("Is there parking?")
        completion = eval_answer("Yes, there is parking. Would 11 AM or 5 PM tomorrow suit you?", action="tentative", place="office", date="2026-10-13", time="11:00", invited=True)
        self.turn(message, [completion])
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.starts_at), ("tentative", at(13, 11)))
        actions = self.actions(message)
        self.assertNotIn("own_offer", actions)
        self.assertNotIn("reoffer", actions)
        self.assertEqual(self.state().invites, 1)
