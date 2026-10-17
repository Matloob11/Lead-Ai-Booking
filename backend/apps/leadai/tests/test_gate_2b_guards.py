"""The code guards behind batch 2b's eval gate (197/208: three scenarios failed 0/2 on the real
model), each mirrored by leadai_eval:

- A. a DED or Trakhees licence gets the request for its copy even when the model's own
  invitation recorded a tentative visit, and that tentative goes with the invitation
  (engine.model_step; eval shops-licence-ask);
- B. in a shops chat a confirm of a time the customer neither gave nor took, a yes to the first
  nudge's "Shall I book you for this evening?" booked at 4 PM, is no booking but the two free
  slots for it (engine.unasked_confirm, engine.their_time, shops.yes_slots; eval
  shops-nudge-yes); our nudges are invitations (nudges.is_nudge);
- C. the time already booked, said again, changes nothing and is not confirmed a second time
  (engine._said_again), and a reply in Arabic script or Devanagari to a customer who types
  English letters is asked for once more in them, code's lines following those letters
  (script.LATIN, prompt.LATIN_CORRECTION; eval lang-inshallah-english, booked-same-time).

Each "as the model answered" test feeds the model's own answers from the gate run, rebuilt from
its replies, actions and times, through leadai_eval.run_once, and passes only with the guard.
The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.leadai import lane
from apps.leadai.assistant import engine, hours, nudges, prompt, rules, schema, script, shop_flow, shops
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, TUESDAY_5PM, answer
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_eval_command import booked
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, at, shop_answer

LICENCE_COPY = rules.line("licence_copy", "en")
# The model's two answers to "Yes I have a DED licence" (eval shops-licence-ask, both gate runs).
LICENCE_INVITE_1 = (
    "Perfect, a mobile phone shop with a DED licence. For that, Type 1 shops are ideal: 400-550 sq ft, from AED 33,000 a year. "
    "I can hold a slot for you today at 2:30 PM or 3:00 PM to visit our office and see the shops. Which is better?"
)
LICENCE_INVITE_2 = (
    "Perfect, a mobile phone shop with a DED licence. I can hold a viewing slot for you today at 2:30 PM or 3:00 PM at our office. "
    "Which is better? You'll meet our agent who will drive you to the shops and back."
)
DED = {"licence_kind": "ded", "trade_licence": "yes"}
# The model's answer to "Yes, book me for this evening" after the first nudge (eval shops-nudge-yes).
BOOKED_AT_FOUR = "I booked you for today at 4:00 PM. You'll meet our agent at our office, who will drive you to the shops."
EVENING_SLOTS = "I can hold a slot for you today at 5:00 PM or 7:00 PM — which is better?"
# The model's two answers to "ان شاء الله" after the confirmation (eval lang-inshallah-english).
ARABIC_1 = "نتطلع لرؤيتك غداً في موعدك المحدد الساعة 5 مساءً في مكتبنا في الموقع أعلاه."
ARABIC_2 = "بالتوفيق إن شاء الله، أحمد. نتطلع لرؤيتك غداً في مكتبنا."
ENGLISH = "We look forward to seeing you tomorrow at 5 PM, Ahmed."
KNOWN = {"for_client": False, "property_type": "shop", "business_activity": "mobile phone shop", "size_sqft": 450, "shop_type": "type_1"}
NUDGE = nudges.first_text("en", "Ahmed Khan", shop_type="type_1", business="mobile phone shop", now=at(12, 13, 5))


def scenario(scenario_id):
    return next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)


def run_eval(item, *completions):
    """leadai_eval.run_once on this scenario (or its id) with these model answers; (run, the messages of each call)."""
    item = scenario(item) if isinstance(item, str) else item
    calls = []

    def model(messages, schema_, **kwargs):
        calls.append(messages)
        return completions[min(len(calls) - 1, len(completions) - 1)]

    with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
        run = leadai_eval.run_once(item, item.id)
    return run, calls


def normal(completion, shops_chat=True):
    return schema.normalize(completion.data, shops=shops_chat)


# A. The licence copy before the invitation, over the model's own tentative ------------------------


class LicenceAskEvalTests(TestCase):
    def test_shops_licence_ask_passes_with_the_answers_the_model_gave(self):
        for reply in (LICENCE_INVITE_1, LICENCE_INVITE_2):
            for completion in (
                eval_answer(reply, action="tentative", invited=True, share_location=True, facts=DED),  # as both gate runs
                eval_answer(reply, action="tentative", place="office", date="2026-10-12", time="14:30", invited=True, facts=DED),
                eval_answer("", action="confirm", place="office", date="2026-10-12", time="14:30", facts=DED),  # its own slot, booked
            ):
                with self.subTest(reply=reply[50:80], action=completion.data["appointment"]["action"]):
                    run, calls = run_eval("shops-licence-ask", completion)
                    self.assertEqual((len(calls), run.failures), (1, []))
                    self.assertEqual((run.out, run.answer["shop_step"]["kind"], run.action), (LICENCE_COPY, shop_flow.LICENCE_ASK, "none"))
                    self.assertFalse(run.answer["invited_to_meeting"])
                    self.assertFalse(run.answer["share_office_location"])

    def test_without_the_guard_the_tentative_kept_the_invitation(self):
        # What the gate saw: the step was refused for the tentative, and the invitation went with the address.
        completion = eval_answer(LICENCE_INVITE_1, action="tentative", invited=True, share_location=True, facts=DED)
        with patch("apps.leadai.assistant.engine.model_step", side_effect=lambda answer, *a, **k: None):
            run, _ = run_eval("shops-licence-ask", completion)
        self.assertIn("shops step none, expected licence_ask", run.failures)
        self.assertIn("invited to a meeting, expected no invitation", run.failures)


class ModelStepTests(SimpleTestCase):
    def step(self, completion, said="Yes I have a DED licence", known=KNOWN, **options):
        out = normal(completion)
        flags = {
            "appointment": None, "agreed": False, "still_invalid": False, "when": None, "quiet": False, "list_sent": True,
            "licence_asked": False,
        }
        flags.update(options)
        return out, engine.model_step(out, known, said, NOW, **flags)

    def test_the_licence_request_takes_the_place_of_an_invitation_and_its_tentative(self):
        out, step = self.step(shop_answer(LICENCE_INVITE_1, action="tentative", invited=True, facts=DED))
        self.assertEqual((step, out["shop_step"]), ({"kind": shop_flow.LICENCE_ASK}, {"kind": shop_flow.LICENCE_ASK}))
        self.assertEqual(out["appointment"], engine.NO_TIME)
        # A plain invitation (no tentative) is taken as before, and nothing else changes in it.
        out, step = self.step(shop_answer(LICENCE_INVITE_1, invited=True, facts=DED))
        self.assertEqual((step, out["appointment"]["action"]), ({"kind": shop_flow.LICENCE_ASK}, "none"))

    def test_never_over_a_tentative_of_theirs_or_anything_that_must_go(self):
        tentative = shop_answer(LICENCE_INVITE_1, action="tentative", invited=True, facts=DED)
        cases = {
            "a yes to our invitation": ({"agreed": True}, tentative, "Yes"),
            "a visit open": ({"appointment": LeadAiAppointment(status="tentative", note="tomorrow")}, tentative, "Yes I have a DED licence"),
            "a day named": ({}, tentative, "DED licence, can I come tomorrow"),
            "a question": ({}, tentative, "DED licence. Where are the shops?"),
            "the copy asked for already": ({"licence_asked": True}, tentative, "Yes I have a DED licence"),
            "a handover": ({}, shop_answer("Our agent will call you.", action="tentative", handover="call_requested", facts=DED), "DED, please call me"),
            "a person has the chat": ({"quiet": True}, tentative, "Yes I have a DED licence"),
            "a new licence": ({}, shop_answer(LICENCE_INVITE_1, action="tentative", invited=True, facts={"licence_kind": "new"}), "I will open a new one"),
        }
        for name, (options, completion, said) in cases.items():
            with self.subTest(name):
                out, step = self.step(completion, said=said, **options)
                self.assertIsNone(step)
                self.assertEqual(out["appointment"]["action"], "tentative")  # theirs, or the model's words go with it

    def test_photos_or_the_types_are_taken_over_a_tentative_and_no_other_step(self):
        # The first live shops test (2026-10-15): photos asked for, or the types, get their step over a
        # tentative of the model's, which goes with its words (test_photos_over_tentative). Before, only the
        # licence request replaced a tentative, so "If possible to send me photo first" got no photos.
        offer = shop_answer("Sure. I can hold a slot for you today at 2:30 PM or 4:30 PM.", action="tentative")
        for said, expected in (("send photos please", {"kind": shop_flow.MEDIA, "type": "type_1"}), ("show me the options", {"kind": shop_flow.LIST})):
            with self.subTest(said):
                out, step = self.step(offer, said=said)
                self.assertEqual((step, out["shop_step"], out["appointment"]), (expected, expected, engine.NO_TIME))
        # No other step: "for myself" with nothing to match is the list only in a plain answer.
        unknown = {"property_type": "shop"}
        out, step = self.step(shop_answer("Great. What business will the shop be for?", action="tentative", facts={"for_client": False}), said="For myself", known=unknown)
        self.assertEqual((step, out["appointment"]["action"]), (None, "tentative"))
        out, step = self.step(shop_answer("Sure, here they are."), said="send photos please")
        self.assertEqual(step, {"kind": shop_flow.MEDIA, "type": "type_1"})  # plain, as before


class LicenceAskTurnTests(ShopsBase):
    def test_a_ded_licence_answered_with_a_tentative_invitation_gets_the_copy_asked_for(self):
        self.set_state(facts=dict(KNOWN))
        self.ours(
            "For a mobile shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees licence, "
            "or will you open a new one?",
            minutes_ago=5,
        )
        message = self.inbound("Yes I have a DED licence")
        outcome, calls, crm_delay, _ = self.turn(message, [shop_answer(LICENCE_INVITE_1, action="tentative", invited=True, share_location=True, facts=DED)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), LICENCE_COPY)
        self.assertFalse(LeadAiAppointment.objects.exists())  # no tentative visit nobody asked for
        crm_delay.assert_not_called()
        self.assertFalse(LeadAiAlert.objects.filter(kind="tentative").exists())
        state = self.state()
        self.assertIsNotNone(state.licence_asked_at)
        self.assertEqual((state.invites, state.facts["licence_kind"]), (0, "ded"))
        actions = self.actions(message)
        self.assertEqual((actions["shop_step"], actions["action"], actions["invited_to_meeting"]), ("licence_ask", "none", False))


# B. A time nobody named or took, in a shops chat --------------------------------------------------


class NudgeYesEvalTests(TestCase):
    def test_shops_nudge_yes_passes_with_the_answer_the_model_gave(self):
        completion = eval_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00")
        run, calls = run_eval("shops-nudge-yes", completion)
        self.assertEqual((len(calls), run.failures), (1, []))
        self.assertEqual((run.out, run.when, run.action), (EVENING_SLOTS, None, "tentative"))
        self.assertEqual(run.answer["unasked"]["start"], at(12, 16))
        self.assertEqual(run.answer["appointment"]["customer_words"], "Yes, book me for this evening")
        self.assertIn("unasked=Mon 12 Oct 16:00", leadai_eval.brief(run))

    def test_without_the_guard_it_was_booked(self):
        completion = eval_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00")
        with patch("apps.leadai.assistant.engine.unasked_confirm", return_value=False):
            run, _ = run_eval("shops-nudge-yes", completion)
        self.assertIn("booked Mon 12 Oct 16:00 (confirm), expected no booking", run.failures)

    def test_every_nudge_and_a_plain_yes(self):
        item = scenario("shops-nudge-yes")
        generic = nudges.first_text("en", "Ahmed Khan", now=at(12, 13, 5))  # no business known: "today or tomorrow"
        second = nudges.second_text("en", "Ahmed Khan", nudges.today_slots(at(13, 10, 30)))
        variants = {
            "the typed nudge, a plain yes": (item.chat, NOW, ["Yes"], "2026-10-12", "16:00", EVENING_SLOTS),
            "the generic nudge": (
                [*item.chat[:-1], ("assistant", generic, at(12, 13, 5))], NOW, ["Yes please"], "2026-10-12", "17:00", TWO_SLOTS_NOW,
            ),
            # The nudge's 11:30 AM is under an hour away by now (hours.OFFER_LEAD): the next two free ones.
            "the second nudge's two slots": (
                [*item.chat, ("assistant", second, at(13, 10, 30))], at(13, 10, 35), ["Yes"], "2026-10-13", "11:00",
                "I can hold a slot for you today at 12:00 PM or 2:00 PM — which is better?",
            ),
            "the nudge, and another day": (item.chat, NOW, ["Yes, but tomorrow"], "2026-10-13", "11:00",
                                           "I can hold a slot for you tomorrow at 10:00 AM or 12:00 PM — which is better?"),
        }
        for name, (chat, now, new, day, clock, out) in variants.items():
            with self.subTest(name):
                completion = eval_answer("", action="confirm", place="office", date=day, time=clock)
                run, _ = run_eval(replace(item, chat=chat, now=now, new=new), completion)
                self.assertEqual((run.out, run.when, run.failures), (out, None, []))

    def test_what_must_not_change(self):
        # The customer's own time, a yes to the one slot we offered, a pick from the morning nudge, a bare "5".
        for scenario_id, completion in (
            ("shops-nudge-morning-pick", booked("2026-10-13", "13:00")),
            ("yes-to-slot", booked("2026-10-13", "17:00")),
            ("lang-arabic-yes", booked("2026-10-13", "17:00", language="ar")),
            ("exact-time", booked("2026-10-14", "17:00")),
            ("shop-bare-5", booked("2026-10-13", "17:00")),
            ("shop-tomorrow-5pm", booked("2026-10-13", "17:00")),
            ("shop-outside-now", booked("2026-10-12", "14:00", hot_lead=True)),
        ):
            with self.subTest(scenario_id):
                run, _ = run_eval(scenario_id, completion)
                self.assertEqual(run.failures, [])
                self.assertIsNotNone(run.when)
                self.assertNotIn("unasked", run.answer)
        # A yes to an open invitation offers times, as before (the model's words).
        run, _ = run_eval("yes-to-invite", eval_answer("Great. Would 11 AM, 2 PM or 5 PM tomorrow work for you?", invited=True))
        self.assertEqual(run.failures, [])
        # In a shops chat a pick from our two slots with a word of its own is the model's booking.
        item = replace(scenario("shops-taken"), taken=(), new=["The later one please"])
        run, _ = run_eval(item, booked("2026-10-12", "16:30"))
        self.assertEqual(run.when, at(12, 16, 30))


class TheirTimeTests(SimpleTestCase):
    def theirs(self, start, said, our_last="", words="", appointment=None):
        return engine.their_time(start, said=said, words=words, our_last=our_last, appointment=appointment, now=NOW)

    def test_a_time_they_gave(self):
        for said in ("Tomorrow at 5 pm", "5", "kal 5 baje", "17:00 tomorrow", "ok 5pm", "غداً الساعة ٥ مساءً"):
            with self.subTest(said):
                self.assertTrue(self.theirs(TUESDAY_5PM, said))
        self.assertTrue(self.theirs(at(13, 16, 30), "4:30 works"))
        self.assertFalse(self.theirs(at(13, 16, 30), "4 works"))  # 4:30 is not 4
        self.assertTrue(self.theirs(TUESDAY_5PM, "For myself", words="Can I come tomorrow at 5 pm? For myself"))  # an answer ago
        self.assertFalse(self.theirs(at(12, 16), "Yes", words="Around 450 sq ft Yes"))  # a size names no hour
        self.assertTrue(self.theirs(at(12, 14, 20), "I'm outside your office now"))  # coming now
        tentative = LeadAiAppointment(status="tentative", starts_at=TUESDAY_5PM)
        self.assertTrue(self.theirs(TUESDAY_5PM, "ok confirm it", appointment=tentative))  # the open visit's own time

    def test_a_time_they_took_from_us(self):
        one = "Would tomorrow at 5 PM work for you to visit our office?"
        two = "I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?"
        self.assertTrue(self.theirs(TUESDAY_5PM, "Yes", our_last=one))
        self.assertTrue(self.theirs(TUESDAY_5PM, "ok", our_last=f"We're open Monday to Saturday, 10 AM to 8 PM. {one}"))
        self.assertFalse(self.theirs(at(12, 17), "Yes", our_last=one))  # its day is tomorrow
        self.assertFalse(self.theirs(at(12, 14, 30), "Yes", our_last=two))  # a plain yes picks neither
        self.assertFalse(self.theirs(at(12, 14, 30), "ok 👍", our_last=two))
        self.assertTrue(self.theirs(at(12, 16, 30), "the later one", our_last=two))
        self.assertFalse(self.theirs(at(12, 17), "the later one", our_last=two))  # not one we offered

    def test_a_time_nobody_named(self):
        for our_last in (NUDGE, nudges.first_text("en", "Ahmed", now=NOW), rules.line("for_whom", "en"), ""):
            with self.subTest(our_last=our_last[:30]):
                self.assertFalse(self.theirs(at(12, 16), "Yes, book me for this evening", our_last=our_last))


class UnaskedConfirmTests(SimpleTestCase):
    def guard(self, completion, said="Yes, book me for this evening", appointment=None, **extra):
        out = normal(completion)
        start = hours.check_slot(out["appointment"]["date"], out["appointment"]["time"], now=NOW)
        changed = engine.unasked_confirm(out, start, appointment, NOW, (), said=said, our_last=extra.pop("our_last", NUDGE), **extra)
        return out, changed

    def test_a_confirm_of_a_time_nobody_named_becomes_the_evening_slots(self):
        out, changed = self.guard(shop_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00"))
        self.assertTrue(changed)
        self.assertEqual(out["unasked"], {"start": at(12, 16), "slots": [at(12, 17), at(12, 19)]})
        self.assertEqual(
            out["appointment"],
            {"action": "tentative", "place": "office", "date": None, "time": None, "customer_words": "Yes, book me for this evening"},
        )
        step = engine.model_step(
            out, KNOWN, "Yes, book me for this evening", NOW, appointment=None, agreed=False, still_invalid=False, when=None,
            quiet=False, list_sent=True, licence_asked=False,
        )
        self.assertEqual(step, {"kind": shop_flow.SLOTS, "slots": [at(12, 17), at(12, 19)]})
        self.assertEqual(shop_flow.slots_text("en", step["slots"], NOW), EVENING_SLOTS)

    def test_never_a_move_a_person_a_call_or_their_own_time(self):
        confirm = shop_answer("", action="confirm", place="office", date="2026-10-12", time="16:00")
        booked_visit = LeadAiAppointment(status="confirmed", starts_at=TUESDAY_5PM)
        cases = {
            "a move": ({"appointment": booked_visit}, confirm),
            "a person has the chat": ({"handed_over": True}, confirm),
            "a handover in it": ({}, shop_answer("", action="confirm", place="office", date="2026-10-12", time="16:00", handover="customer_asked_human")),
            "someone outside our segments": ({}, shop_answer("", action="confirm", place="office", date="2026-10-12", time="16:00", segment="other")),
            "a call": ({"said": "Yes, call me this evening"}, confirm),
            "their own time": ({"said": "Yes, book me for 4 pm"}, confirm),
        }
        for name, (extra, completion) in cases.items():
            with self.subTest(name):
                out, changed = self.guard(completion, **extra)
                self.assertFalse(changed)
                self.assertNotIn("unasked", out)
        self.assertFalse(engine.unasked_confirm(normal(confirm), None, None, NOW, said="Yes", our_last=NUDGE))  # nothing booked

    def test_the_licence_request_still_goes_first(self):
        # A confirm of its own slot to "Yes I have a DED licence": the copy is asked for, nothing kept.
        out, changed = self.guard(
            shop_answer("", action="confirm", place="office", date="2026-10-12", time="14:30", facts=DED),
            said="Yes I have a DED licence", our_last="Do you have a DED or Trakhees licence, or will you open a new one?",
        )
        self.assertTrue(changed)
        step = engine.model_step(
            out, KNOWN, "Yes I have a DED licence", NOW, appointment=None, agreed=False, still_invalid=False, when=None,
            quiet=False, list_sent=True, licence_asked=False,
        )
        self.assertEqual((step, out["appointment"]), ({"kind": shop_flow.LICENCE_ASK}, engine.NO_TIME))


class YesSlotsTests(SimpleTestCase):
    def test_the_evening_the_day_and_the_days_ruled_out(self):
        slots = shops.yes_slots
        self.assertEqual(slots("Yes", NUDGE, NOW), [at(12, 17), at(12, 19)])  # our "this evening"
        self.assertEqual(slots("Yes, book me for this evening", "", NOW), [at(12, 17), at(12, 19)])  # theirs
        self.assertEqual(slots("aaj shaam theek hai", "", NOW), [at(12, 17), at(12, 19)])
        self.assertEqual(slots("Yes, tomorrow evening", NUDGE, NOW), [at(13, 17), at(13, 19)])
        self.assertEqual(slots("Yes, tomorrow", NUDGE, NOW), [at(13, 10), at(13, 12)])  # their day, no evening of ours
        self.assertEqual(slots("Yes", nudges.first_text("en", "Ahmed", now=NOW), NOW), [at(12, 15), at(12, 17)])  # "today or tomorrow"
        self.assertEqual(slots("Yes, but not today", nudges.first_text("en", "Ahmed", now=NOW), NOW), [at(13, 10), at(13, 12)])
        self.assertEqual(slots("Yes", NUDGE, at(12, 18, 40)), [at(13, 17), at(13, 19)])  # this evening gone: none an hour ahead
        taken = [at(12, 17), at(12, 17, 30), at(12, 18), at(12, 18, 30), at(12, 19), at(12, 19, 30)]
        self.assertEqual(slots("Yes", NUDGE, NOW, taken=taken), [at(13, 17), at(13, 19)])  # a full evening: the next one

    def test_offer_pair_from_an_hour(self):
        self.assertEqual(hours.offer_pair(NOW, after=dt.time(17, 0)), [at(12, 17), at(12, 19)])
        self.assertEqual(hours.offer_pair(NOW), [at(12, 15), at(12, 17)])  # as before, an hour ahead at least
        self.assertEqual(hours.offer_pair(at(12, 19, 20), after=dt.time(17, 0)), [at(13, 17), at(13, 19)])


class HourReadersTests(SimpleTestCase):
    def test_names_hour(self):
        five = TUESDAY_5PM
        for text in ("5", "5 pm", "at 5", "17:00", "17", "5.", "kal 5 baje", "ok ٥"):
            with self.subTest(text):
                self.assertTrue(hours.names_hour(text, five))
        for text in ("450 sq ft", "5:30", "15", "25", "Yes", "", "this evening", "Type 1"):
            with self.subTest(text):
                self.assertFalse(hours.names_hour(text, five))
        self.assertTrue(hours.names_hour("4:30 is fine", at(13, 16, 30)))
        self.assertFalse(hours.names_hour("4 is fine", at(13, 16, 30)))

    def test_offered_starts(self):
        self.assertEqual(hours.offered_starts(TWO_SLOTS_NOW), {dt.time(15, 0), dt.time(17, 0)})
        self.assertEqual(hours.offered_starts("We're open Monday to Saturday, 10 AM to 8 PM. Would 5 PM work?"), {dt.time(17, 0)})
        self.assertEqual(hours.offered_starts("نحن نعمل من الاثنين إلى السبت، من 10 صباحاً حتى 8 مساءً."), set())
        self.assertEqual(hours.offered_starts(NUDGE), set())
        self.assertEqual(hours.offered_starts("Would 9 PM work?"), set())  # no start we book


class NudgeIsAnInvitationTests(SimpleTestCase):
    def test_every_nudge_in_every_language_reads_as_one(self):
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            for text in (
                nudges.first_text(language, "Ahmed Khan", shop_type="type_2", business="salon", now=NOW),
                nudges.first_text(language, "", now=NOW),
                nudges.first_text(language, "Ahmed", now=at(17, 12)),  # Saturday: "today or on Monday"
                nudges.second_text(language, "Ahmed", [at(13, 11), at(13, 13)]),
            ):
                with self.subTest(language=language, text=text[:30]):
                    self.assertTrue(nudges.is_nudge(text))
                    self.assertTrue(engine.visit_offered(text))
        for text in (rules.line("for_whom", "en"), rules.line("licence_copy", "en"), "Shall I book it?", "I picked 2 shirts", ""):
            with self.subTest(text=text[:30]):
                self.assertFalse(nudges.is_nudge(text))

    def test_a_plain_yes_to_a_nudge_is_a_yes_to_coming(self):
        self.assertTrue(engine.agreed_to_come(visit_open=False, our_last=NUDGE, texts=["Yes"]))
        self.assertTrue(engine.agreed_to_come(visit_open=False, our_last=nudges.first_text("ur_latin", "Ahmed", now=NOW), texts=["ji"]))
        self.assertFalse(engine.agreed_to_come(visit_open=False, our_last=NUDGE, texts=["No, not today"]))
        # A deferral of it is the deferral rule's, as after any invitation.
        self.assertEqual(engine.deferral(["I will let you know"], offered=engine.visit_offered(NUDGE)), "I will let you know")

    def test_a_yes_to_the_nudge_is_never_asked_the_licence_instead(self):
        # licence_first stands aside for a yes to an invitation (settle's agreed), the nudge's too.
        reply = "Great! I can hold a slot for you today at 5:00 PM or 6:30 PM — which is better?"
        out = engine.settle(
            normal(shop_answer(reply, action="tentative", invited=True)), [("assistant", NUDGE)], ["Yes"], 0,
            agreed=engine.agreed_to_come(visit_open=False, our_last=NUDGE, texts=["Yes"]), playbook=lane.IC_SHOPS, now=NOW, facts=KNOWN,
        )
        self.assertEqual((out["reply"], out["invited_to_meeting"]), (reply, False))


class UnaskedConfirmTurnTests(ShopsBase):
    def nudged(self):
        self.set_state(facts=dict(KNOWN), nudges=1, nudged_at=NOW - dt.timedelta(minutes=55))
        self.inbound("Around 450 sq ft", seconds_ago=3 * 3600)  # live, any digit they wrote grounded any hour
        self.ours(NUDGE, minutes_ago=55, nudge=1)

    def test_yes_to_the_nudge_booked_by_the_model_gets_the_evening_slots(self):
        self.nudged()
        message = self.inbound("Yes, book me for this evening")
        outcome, calls, crm_delay, _ = self.turn(message, [shop_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), EVENING_SLOTS)
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.starts_at, appointment.note), ("tentative", None, "Yes, book me for this evening"))
        self.assertFalse(LeadAiAlert.objects.filter(kind="booked").exists())
        crm_delay.assert_called_once_with(appointment.pk, "tentative", False, 1)
        actions = self.actions(message)
        self.assertEqual((actions["unasked"], actions["shop_step"], actions["action"]), (at(12, 16).isoformat(), "slots", "tentative"))
        self.assertEqual(self.state().invites, 0)  # a yes to our nudge: these slots are no new invitation

    def test_refused_twice_as_vague_it_gets_the_evening_slots_never_an_open_question(self):
        # No digit in anything they wrote: live, the grounding refuses the 4 PM itself and asks again.
        self.set_state(facts=dict(KNOWN), nudges=1, nudged_at=NOW - dt.timedelta(minutes=55))
        self.ours(NUDGE, minutes_ago=55, nudge=1)
        message = self.inbound("Yes, book me for this evening")
        confirm = shop_answer(BOOKED_AT_FOUR, action="confirm", place="office", date="2026-10-12", time="16:00")
        outcome, calls, _, _ = self.turn(message, [confirm, confirm])
        self.assertEqual(len(calls), 2)
        self.assertIn("has not named that time", calls[1][-1]["content"])
        self.assertEqual(self.body(outcome), EVENING_SLOTS)
        self.assertEqual(self.actions(message)["fallback"], "slots")
        self.assertFalse(LeadAiAppointment.objects.exists())

    def test_a_plain_yes_to_our_two_slots_is_asked_which_and_a_pick_is_booked(self):
        self.set_state(facts=dict(KNOWN))
        self.inbound("Around 450 sq ft", seconds_ago=600)
        self.ours(TWO_SLOTS_NOW, minutes_ago=5)
        outcome, _, _, _ = self.turn(self.inbound("Yes"), [shop_answer("", action="confirm", place="office", date="2026-10-12", time="14:30")])
        # A plain yes picks neither: which one, again, never in the same words (finding F7).
        self.assertEqual(self.body(outcome), "Which one suits you better: today at 3:00 PM or 5:00 PM?")
        self.assertEqual(LeadAiAppointment.objects.get().status, "tentative")
        self.later(2)
        self.turn(self.inbound("The later one", seconds_ago=10), [shop_answer("", action="confirm", place="office", date="2026-10-12", time="17:00")])
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.status, appointment.starts_at), ("confirmed", at(12, 17)))


class UnaskedGeneralTurnTests(GeneralBase):
    def test_a_general_chat_keeps_its_booking(self):
        # The general playbook has no nudges and keeps today's rules (its yes-to-invite passes on the real model).
        self.inbound("Around 450 sq ft", seconds_ago=600)
        self.ours("Would 11 AM or 2 PM tomorrow work for you?", minutes_ago=5)
        self.turn(self.inbound("Yes"), [answer("", action="confirm", place="office", date="2026-10-13", time="11:00")])
        self.assertEqual(LeadAiAppointment.objects.get().status, "confirmed")


# C. The time already booked, said again; English letters ------------------------------------------


class InshallahEvalTests(TestCase):
    def test_lang_inshallah_english_passes_with_the_answers_the_model_gave(self):
        for reply in (ARABIC_1, ARABIC_2):
            with self.subTest(reply=reply[:20]):
                first = eval_answer(reply, action="reschedule", place="office", date="2026-10-13", time="17:00", language="ar", reply_en="See you tomorrow.")
                again = eval_answer(ENGLISH, action="reschedule", place="office", date="2026-10-13", time="17:00")
                run, calls = run_eval("lang-inshallah-english", first, again)
                self.assertEqual((len(calls), run.failures), (2, []))
                self.assertEqual(calls[1][-1], {"role": "user", "content": prompt.LATIN_CORRECTION})
                self.assertEqual((run.out, run.action, run.when, run.answer["script_fix"], run.line_language), (ENGLISH, "none", None, "fixed", "en"))

    def test_still_arabic_it_fails_as_it_would_go_out(self):
        first = eval_answer(ARABIC_1, action="reschedule", place="office", date="2026-10-13", time="17:00", language="ar")
        run, calls = run_eval("lang-inshallah-english", first, first)
        self.assertEqual((len(calls), run.answer["script_fix"], run.out), (2, "kept", ARABIC_1))
        self.assertIn("what goes out: reply is not in English letters", run.failures)
        self.assertNotIn("sends the booking again", " ".join(run.failures))

    def test_without_the_no_change_guard_the_confirmation_goes_again(self):
        # The gate's run: "reconfirm" wrote the booking out again (in Arabic then; in English letters
        # now, as code's lines follow them), and a booking's words are code's, so nothing was asked again.
        first = eval_answer(ARABIC_1, action="reschedule", place="office", date="2026-10-13", time="17:00", language="ar")
        with patch("apps.leadai.assistant.engine._said_again", return_value=False):
            run, calls = run_eval("lang-inshallah-english", first)
        self.assertEqual(len(calls), 1)
        self.assertTrue(run.out.startswith("Perfect, Ahmed. Your meeting is confirmed."), run.out)
        self.assertTrue(any(failure.startswith("sends the booking again") for failure in run.failures), run.failures)

    def test_nothing_said_back_is_still_an_english_answer(self):
        # Reply-less, labelled Arabic: nothing goes out, and the chat stays English (label and code's lines).
        quiet = eval_answer("", action="reschedule", place="office", date="2026-10-13", time="17:00", language="ar", send=False)
        run, calls = run_eval("lang-inshallah-english", quiet)
        self.assertEqual((len(calls), run.failures, run.out, run.answer["language"], run.line_language), (1, [], "", "en", "en"))

    def test_booked_same_time_says_nothing_again(self):
        for completion in (booked("2026-10-13", "17:00"), eval_answer("Great, see you then!", action="confirm", place="office", date="2026-10-13", time="17:00")):
            with self.subTest(reply=completion.data["reply"]):
                run, _ = run_eval("booked-same-time", completion)
                self.assertEqual((run.failures, run.action, run.when), ([], "none", None))
                self.assertNotEqual(run.out_by, leadai_eval.CODE)

    def test_what_must_not_change(self):
        right = {
            "lang-urdu": eval_answer("شکریہ۔ کیا آپ کے پاس ٹریڈ لائسنس ہے؟", language="ur", reply_en="Thank you. Do you have a trade licence?"),
            "lang-arabic": eval_answer("أهلاً بك. هل لديك رخصة تجارية للمطعم؟", language="ar", reply_en="Welcome. Do you have a trade licence?"),
            "lang-arabic-booking": booked("2026-10-13", "17:00"),
            "lang-roman-urdu": eval_answer("Shukriya. Kya aap ke paas trade licence hai?", language="ur_latin", reply_en="Thank you. Do you have a licence?"),
            "booked-reschedule": eval_answer("", action="reschedule", place="office", date="2026-10-14", time="11:00"),
            "booked-running-late": eval_answer("", action="running_late", time="17:30"),
        }
        for scenario_id, completion in right.items():
            with self.subTest(scenario_id):
                run, calls = run_eval(scenario_id, completion)
                self.assertEqual((run.failures, len(calls)), ([], 1))
        run, calls = run_eval("stop-arabic-after-english")
        self.assertEqual((run.failures, calls, run.out), ([], [], rules.line("stop_all", "ar")))


class SaidAgainTests(SimpleTestCase):
    def test_the_time_already_booked_said_again(self):
        mine = LeadAiAppointment(status="confirmed", starts_at=TUESDAY_5PM)
        again = normal(answer("", action="reschedule", place="office", date="2026-10-13", time="17:00"), False)
        confirm = normal(answer("", action="confirm", place="office", date="2026-10-13", time="17:00"), False)
        self.assertTrue(engine._said_again(again, TUESDAY_5PM, mine, "ان شاء الله"))
        self.assertTrue(engine._said_again(confirm, TUESDAY_5PM, mine, "Great, see you tomorrow at 5"))
        self.assertFalse(engine._said_again(confirm, TUESDAY_5PM, mine, "Is it still at 5 tomorrow?"))  # asked: the booking again
        self.assertFalse(engine._said_again(confirm, at(14, 17), mine, "Wednesday at 5 instead"))  # a move
        self.assertFalse(engine._said_again(confirm, TUESDAY_5PM, LeadAiAppointment(status="tentative", starts_at=TUESDAY_5PM), "ok"))
        moving = LeadAiAppointment(status="confirmed", starts_at=TUESDAY_5PM, customer_state="reschedule")
        self.assertFalse(engine._said_again(confirm, TUESDAY_5PM, moving, "Actually 5 is fine"))
        late = normal(answer("", action="running_late", time="17:00"), False)
        self.assertFalse(engine._said_again(late, TUESDAY_5PM, mine, "I'll make it on time"))  # "on time", as before

    def test_ask_model_makes_it_no_change_and_checks_the_script(self):
        mine = LeadAiAppointment(status="confirmed", starts_at=TUESDAY_5PM)
        calls = []
        replies = [answer(ARABIC_1, action="reschedule", place="office", date="2026-10-13", time="17:00", language="ar"), answer(ENGLISH)]

        def model(messages, schema_, **kwargs):
            calls.append(messages)
            return replies[len(calls) - 1]

        with patch("apps.leadai.assistant.openai_client.complete_json", side_effect=model):
            out, when, _, rejected, invalid = engine.ask_model(
                prompt.SYSTEM, "context", mine, NOW, (), said="ان شاء الله", customer_script=script.LATIN
            )
        self.assertEqual((when, rejected, invalid, len(calls)), (None, "", False, 2))
        self.assertEqual((out["appointment"], out["reply"], out["language"], out["script_fix"]), (engine.NO_TIME, ENGLISH, "en", "fixed"))


class LatinScriptTests(SimpleTestCase):
    def test_english_letters_are_a_script(self):
        self.assertTrue(script.has_script("See you tomorrow at 5 PM, inshallah!", script.LATIN))
        self.assertFalse(script.has_script("See you tomorrow, إن شاء الله", script.LATIN))
        self.assertFalse(script.has_script("नमस्ते", script.LATIN))
        self.assertTrue(script.has_script("👍 5 PM", script.LATIN))
        self.assertEqual(script.customer_script(["Tomorrow 5pm", "ان شاء الله"]), script.LATIN)

    def test_code_lines_follow_english_letters(self):
        cases = {"ar": "en", "ur": "ur_latin", "hi": "hi_latin", "en": "en", "ur_latin": "ur_latin", "hi_latin": "hi_latin"}
        for language, expected in cases.items():
            with self.subTest(language=language):
                self.assertEqual(script.follow(language, script.LATIN), expected)
                self.assertEqual(script.follow(language, ""), language)  # nothing typed: as it is

    def test_the_correction_in_english_letters(self):
        self.assertIn("English letters", prompt.LATIN_CORRECTION)
        self.assertIn("ان شاء الله", prompt.LATIN_CORRECTION)
        self.assertNotIn("{", prompt.LATIN_CORRECTION)


class InshallahTurnTests(GeneralBase):
    def booked_chat(self):
        LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", place="office", starts_at=TUESDAY_5PM,
            reminder_due_at=TUESDAY_5PM - dt.timedelta(minutes=30),
        )
        self.set_state(language="en")
        self.inbound("Tomorrow 5pm", seconds_ago=600)
        self.ours("Perfect, Ahmed. Your meeting is confirmed.\nDate: Tuesday 13 October\nTime: 5:00 PM", minutes_ago=9)

    def test_inshallah_answered_in_arabic_is_asked_again_in_english_and_nothing_is_booked_again(self):
        self.booked_chat()
        message = self.inbound("ان شاء الله")
        first = answer(ARABIC_2, action="reschedule", place="office", date="2026-10-13", time="17:00", language="ar", reply_en="See you tomorrow.")
        outcome, calls, crm_delay, _ = self.turn(message, [first, answer(ENGLISH)])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][-1]["content"], prompt.LATIN_CORRECTION)
        self.assertEqual(self.body(outcome), ENGLISH)
        crm_delay.assert_not_called()
        appointment = LeadAiAppointment.objects.get()
        self.assertEqual((appointment.starts_at, appointment.reminder_due_at, len(appointment.history or [])), (TUESDAY_5PM, TUESDAY_5PM - dt.timedelta(minutes=30), 0))
        self.assertFalse(LeadAiAlert.objects.filter(kind__in=("rescheduled", "booked")).exists())
        actions = self.actions(message)
        self.assertEqual((actions["action"], actions["script_fix"], actions["language"]), ("none", "fixed", "en"))
        self.assertEqual(self.state().language, "en")

    def test_kept_in_arabic_the_chat_stays_english_for_codes_lines(self):
        self.booked_chat()
        message = self.inbound("ان شاء الله")
        first = answer(ARABIC_1, action="none", language="ar")
        outcome, calls, _, _ = self.turn(message, [first, first])
        self.assertEqual((len(calls), self.body(outcome)), (2, ARABIC_1))
        self.assertEqual(self.actions(message)["line_language"], "en")
        self.assertEqual(self.state().language, "en")  # the reminder tomorrow is in the letters they type

    def test_asked_whether_it_stands_the_booking_is_said_again(self):
        self.booked_chat()
        outcome, _, crm_delay, _ = self.turn(self.inbound("Is it still at 5 pm tomorrow?"), [answer("", action="confirm", place="office", date="2026-10-13", time="17:00")])
        self.assertTrue(self.body(outcome).startswith("Perfect, Ahmed. Your meeting is confirmed."))
        crm_delay.assert_not_called()

    def test_a_stop_in_english_letters_keeps_the_letters_the_customer_types(self):
        # One word of English letters says nothing of their script (finding F4): an Arabic chat's
        # "STOP" gets the Arabic line, as before batch 2b; after English typed, the English one.
        self.set_state(language="ar")
        self.inbound("مرحبا، أحتاج محل في المدينة العالمية", seconds_ago=600)
        outcome, calls, _, _ = self.turn(self.inbound("STOP"), [])
        self.assertEqual((calls, self.body(outcome)), ([], rules.line("stop_all", "ar")))

    def test_a_stop_after_english_letters_in_a_chat_labelled_arabic_gets_the_english_line(self):
        self.set_state(language="ar")
        self.inbound("I need a shop in International City", seconds_ago=600)
        outcome, calls, _, _ = self.turn(self.inbound("STOP"), [])
        self.assertEqual((calls, self.body(outcome)), ([], rules.line("stop_all", "en")))


class MustNotChangeTests(TestCase):
    """The scenarios the three guards sit next to keep their verdicts with their right answers, and
    the licence scenarios keep the model's words when it answers them with a tentative."""

    NAMED = (
        "yes-to-slot", "lang-arabic-yes", "yes-to-invite", "shops-nudge-morning-pick", "exact-time", "booked-same-time",
        "shops-invite", "shops-licence-copy", "shops-licence-later", "shops-licence-send-later", "lang-urdu", "lang-arabic",
        "lang-arabic-booking", "stop-arabic-after-english", "shops-licence-ask", "shops-nudge-yes", "lang-inshallah-english",
    )

    def test_the_right_answers_still_pass(self):
        from apps.leadai.tests.test_eval_command import RIGHT

        for scenario_id in self.NAMED:
            with self.subTest(scenario_id):
                run, _ = run_eval(scenario_id, RIGHT[scenario_id])
                self.assertEqual(run.failures, [])

    def test_a_tentative_answer_where_the_licence_is_no_question_any_more(self):
        # The model's words go. Its tentative for its own two slots records no visit (engine.own_offer),
        # unless the customer speaks of coming ("I will bring it to the viewing"): then it stays, in their
        # words, at no day of ours.
        offer = "No problem. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?"
        for scenario_id, facts, kept in (
            ("shops-licence-later", {}, "tentative"), ("shops-licence-send-later", {}, "none"), ("shops-invite", {"licence_kind": "new"}, "none"),
        ):
            with self.subTest(scenario_id):
                completion = eval_answer(offer, action="tentative", place="office", date="2026-10-12", invited=True, facts=facts)
                run, _ = run_eval(scenario_id, completion)
                self.assertEqual(run.failures, [])
                self.assertEqual((run.out_by, run.action, run.answer.get("shop_step")), (leadai_eval.MODEL, kept, None))
                self.assertIsNone(run.answer["appointment"]["date"])


class LatinShopsTurnTests(ShopsBase):
    def test_an_english_reply_to_english_letters_makes_no_second_call(self):
        outcome, calls, _, _ = self.turn(self.inbound("I need a shop in International City"), [shop_answer()])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("script_fix", self.actions(LeadAiTurn.objects.get().inbound))
