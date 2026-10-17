"""Batch 2d, the launch fixes (2026-10-15): the shops follow-ups (launch review issues 9, 11 and 23).

What went wrong live: 7 of the first 12 nudges asked people who wanted a studio or a room to see the shops,
one of them after "Not now" and "Not shops" (chat 68); one pushed a visit over nine questions the bot had left
to the viewing (95); our "for yourself, or for a client?" was skipped by an invitation (103, 78); "we got one"
and an unanswered "Not now" stayed Qualifying for good (63, 87); and a tentative visit with no time, or a past
one, held every follow-up back for 7 days (100, 96, 59, 62). Each test feeds a launch chat's own words
(chat_<id>.json of the review) and fails without the guard it proves:

- A. no nudge, Template B or check-back after a decline, a "Not now" or a shop rented elsewhere, unless a later
  yes of theirs took it back; Template B never to a customer who wants no shop to rent, whose nudges are about
  the visit only (chats 44, 50, 132); a reply-cap skip pending holds the check-back (followups.holds); an
  unanswered check-back question gets nothing, or what CHECK_BACK_SILENCE says;
- B. a question of theirs left to a colleague: no nudge, a person alerted once, whatever else holds the chat
  (followups.question_left, OPEN_QUESTION);
- C. our for-whom question asked again, never skipped (nudges.asks_for_whom);
- D. a no to the second-shop question in other words closes the lead as already rented (engine.second_shop_no);
- E. a shops tentative with no time lapses a day after it was said, one with a time an hour after that time and
  after their last word on it; a general chat's tentative never keeps a shops one waiting;
- F. the eval's scenarios, and the guards patched out.

The fakes are test_assistant's; the shops chat is test_follow_ups' (lead 555; the campaign's template went out
Monday 12 October 2026 at 12:00 Dubai; the clock moves).
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.inbox.models import Conversation, Message
from apps.leadai import followups, tasks
from apps.leadai.assistant import crm_fields, engine, hours, needs, nudges, rules, shop_flow, transcript
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import DEFAULT_OFFICE_ADDRESS, DEFAULT_SHOPS_FACTS, LeadAiAlert, LeadAiAppointment, LeadAiCrmField, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, _outbound, fake_send_template, fake_send_text
from apps.leadai.tests.test_eval_command import RIGHT
from apps.leadai.tests.test_follow_ups import CHECK_DAY, THURSDAY, FollowUpBase
from apps.leadai.tests.test_shops_playbook import GeneralBase, ShopsBase, shop_answer

DUBAI = hours.DUBAI
MAPS = "https://maps.app.goo.gl/u7xzyea9pPLpRxBD8"
FOR_WHOM_AGAIN = "Hi Ahmed, just checking in — is the shop for yourself, or are you checking for a client?"
SHOPS_NUDGE = "Hi Ahmed, just checking in — shall I hold a slot for you to see the shops today or tomorrow?"
OPTIONS_NUDGE = "Hi Ahmed, just checking in — shall I hold a slot for you to see the options today or tomorrow?"
# Chat 95's own message (10:33 live) and the bot's answer to it.
NINE_QUESTIONS = (
    "Hi, I’m seriously interested in this unit for a small dessert takeaway and production kitchen.\n\nBefore arranging the next "
    "steps, I need to confirm a few technical points:\n\n1. Can the landlord provide an NOC for F&B / food preparation activity?\n"
    "2. Can this exact unit be approved by Dubai Municipality for a food establishment?\n3. What is the total electrical load "
    "available in kW?\n4. Is there existing water supply and drainage inside the shop?\n5. Can preparation and hand-wash sinks "
    "be installed?\n6. Is there provision for exhaust/ventilation if required by Municipality?\n7. Is there a grease trap or "
    "provision for one?\n8. Will I receive my own Ejari for the unit?\n9. What is the complete upfront amount including deposit, "
    "agency commission, Ejari, VAT and any other fees?"
)
DEFERRED_95 = (
    "Thanks for your detailed questions about the shop for your dessert takeaway and production kitchen. Good question — I'll "
    "have our agent confirm those technical points for you at the viewing. Meanwhile, what size shop are you looking for?"
)
DEFERRED_59 = (
    "Rent security is usually a deposit, and payment is in 1 to 4 cheques. Good question — I'll have our agent confirm details "
    "like service charge, DEWA, parking, and fit-out at the viewing. What size or budget are you considering for the shop?"
)
DEFERRED_78 = (
    "For your budget of AED 33,000, the Small shop type is perfect: 400-550 sq ft, from AED 33,000 a year. Good question — I'll "
    "have our agent confirm the back area and parking availability for you at the viewing. What business will you run in the shop?"
)
LICENCE_78 = (
    "Perfect, an interior landscape shop. For your budget, the Type 1 small shop is ideal: 400-550 sq ft, from AED 33,000 a year. "
    "Do you have a DED or Trakhees licence, or will you open a new one?"
)
STUDIO_68 = "I see, a studio. Our shops are for retail or commercial use, not residential studios. Is the studio for a business activity?"
REACH_OUT_63 = "Thank you so much! \nI really appreciate your support and will definitely reach out if we need anything in the future."


def at(day, hour, minute=0, second=0, month=10):
    return dt.datetime(2026, month, day, hour, minute, second, tzinfo=DUBAI)


class LaunchBase(FollowUpBase):
    """A launch chat replayed on the tests' shops chat, each message at its own moment (pk order is its order)."""

    def setUp(self):
        super().setUp()
        self.list_matloob()
        self.set_state(language="en")

    def said(self, text, moment, **fields):
        fields.setdefault("kind", Message.Kind.TEXT)
        return Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.INBOUND, body=text, status=Message.Status.RECEIVED,
            created_at=moment, **fields,
        )

    def tapped(self, label, moment):
        return self.said(label, moment, kind=Message.Kind.BUTTON, payload={"button": {"text": label}})

    def wrote(self, text, moment, kind=Message.Kind.TEXT, **payload):
        return _outbound(self.conversation, None, kind, text, {"source": "leadai_ai", **payload}, created_at=moment)

    def listed(self, moment):
        return self.wrote(shop_flow.list_text("en", DEFAULT_SHOPS_FACTS), moment, kind=Message.Kind.INTERACTIVE, shop_list=True)

    def window_from(self, last_inbound):
        Conversation.objects.filter(pk=self.conversation.pk).update(
            session_expires_at=last_inbound + dt.timedelta(hours=24), last_inbound_at=last_inbound
        )

    def due(self):
        return dict(followups.due_now()).get(self.conversation.pk, "")

    def nudge(self, kind=followups.NUDGE_1):
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text) as sent:
            result = followups.send(self.conversation.pk, kind)
        return result, sent

    def holds(self, kind=followups.NUDGE_1):
        return followups.holds(self.conversation, self.state(), self.clock.return_value, kind)


# A. Who a follow-up never goes to ---------------------------------------------------------------------


class NotNowTests(LaunchBase):
    def chat_68(self, answer_to_studio):
        """Chat 68 live: [Not now], the check-back question, "Actually i was looking for a studio", what went out
        to it (the shop list live), "Not shops", the model's question; silence."""
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Actually i was looking for a studio", at(12, 12, 5, 40))
        answer_to_studio(at(12, 12, 6))
        self.said("Not shops", at(12, 12, 6, 20))
        self.wrote(STUDIO_68, at(12, 12, 6, 40))
        self.window_from(at(12, 12, 6, 20))
        # The list's reply took the check-back question's marker away, as live (engine._apply).
        self.set_state(followup_asked_at=None, facts={"for_client": False, "property_type": "studio", "business_activity": "studio"})

    def test_chat_68_after_not_now_and_not_shops_gets_no_nudge(self):
        self.chat_68(self.listed)
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), "")
        result, sent = self.nudge()
        self.assertEqual(result, "not due")
        sent.assert_not_called()
        self.assertEqual(self.holds(), followups.HELD_NOT_NOW)
        self.go(at(13, 10, 30))  # nor the next morning's
        self.assertEqual(self.due(), "")

    def test_chat_68_as_it_goes_now_the_owners_line_and_no_nudge_after_not_now(self):
        line = engine.not_a_shop_text({"kind": "home", "noun": "studio", "sorry": True, "slots": hours.offer_pair(at(12, 12, 6))}, "en", at(12, 12, 6))
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Actually i was looking for a studio", at(12, 12, 5, 40))
        self.wrote(f"{line}\n{MAPS}", at(12, 12, 6))
        self.window_from(at(12, 12, 5, 40))
        self.set_state(facts={"need": "home", "wanted": "a studio", "property_type": "studio"}, invites=1)
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), "")
        self.assertEqual(self.holds(), followups.HELD_NOT_NOW)

    def test_chat_87_an_unanswered_check_back_gets_nothing_ever(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.window_from(at(12, 12, 5))
        self.set_state(followup_asked_at=at(12, 12, 5, 14))
        for moment in (at(12, 14, 6), at(13, 10, 30), THURSDAY, at(11, 14, month=11), at(20, 14, month=11)):
            with self.subTest(moment=moment):
                self.go(moment)
                self.assertEqual(followups.due_now(), [])
        state = self.state()
        self.assertEqual((state.followup_asked_at, state.followup_due_at), (at(12, 12, 5, 14), None))  # nothing planned

    def test_the_not_now_holds_even_when_its_marker_went(self):
        # Chat 87 had they asked about sizes instead of answering the check-back: our answer clears the marker.
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("What sizes do you have?", at(12, 12, 5, 40))
        self.wrote("We have three types, from 400 sq ft to 1,200 sq ft. What size do you need?", at(12, 12, 6))
        self.window_from(at(12, 12, 5, 40))
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), "")
        for words in ("not now, maybe next month", "abhi nahi", "ليس الآن", "Maybe later"):
            with self.subTest(words=words):
                self.assertTrue(followups._says_not_now(words))
        self.assertFalse(followups._says_not_now("Not yet, I will open a new licence"))

    def test_not_now_then_their_yes_tap_on_the_template_is_under_way_again(self):
        # The template's buttons stay tappable: [Not now], the check-back question, then [Yes, show me shops].
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.tapped("Yes, show me shops", at(12, 12, 10))
        self.wrote(rules.line("for_whom", "en"), at(12, 12, 10, 15))
        self.window_from(at(12, 12, 10))
        self.go(at(12, 14, 11))
        self.assertEqual(self.holds(), "")
        result, sent = self.nudge()
        self.assertEqual((result, sent.call_args.args[2]), ("sent", FOR_WHOM_AGAIN))
        with patch.object(followups, "_takes_it_up", return_value=False):
            self.assertEqual(self.holds(), followups.HELD_NOT_NOW)  # without the take-back, as the previous guard had it

    def test_a_yes_to_the_check_back_question_takes_no_not_now_back(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Yes", at(12, 12, 6))
        self.wrote("Sure. What business is the shop for, so I can send the right options then?", at(12, 12, 6, 15))
        self.window_from(at(12, 12, 6))
        self.go(at(12, 14, 7))
        self.assertEqual(self.holds(), followups.HELD_NOT_NOW)
        self.assertEqual(self.due(), "")

    def test_silence_is_lost_closes_the_lead_a_month_after_the_question(self):
        # CHECK_BACK_SILENCE, one line: the unanswered check-back question closes the lead as Lost.
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.set_state(followup_asked_at=at(12, 12, 5, 14))
        with patch.object(followups, "CHECK_BACK_SILENCE", followups.SILENCE_IS_LOST):
            self.go(at(11, 12, month=11))  # a month less five minutes
            self.assertEqual(followups.due_now(), [])
            self.assertIsNone(self.state().not_interested_at)
            self.go(at(11, 14, month=11))
            self.assertEqual(followups.due_now(), [])
        state = self.state()
        self.assertEqual((state.followup_asked_at, state.followup_due_at), (None, None))
        self.assertEqual(state.not_interested_at, at(11, 14, month=11))
        self.assertEqual(LeadAiCrmField.objects.get(field=crm_fields.LOST).payload, {"reason": followups.SILENT_LOST_REASON})
        self.assertEqual(followups.due_now(), [])  # blocked from now on

    def test_silence_is_lost_never_loses_a_customer_who_wants_no_shop(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.set_state(followup_asked_at=at(12, 12, 5, 14), facts={"need": "home", "wanted": "a studio"})
        self.go(at(11, 14, month=11))
        with patch.object(followups, "CHECK_BACK_SILENCE", followups.SILENCE_IS_LOST):
            followups.due_now()
        self.assertIsNotNone(self.state().not_interested_at)  # no more invitations ...
        self.assertFalse(LeadAiCrmField.objects.filter(field=crm_fields.LOST).exists())  # ... and never Lost (needs.NEVER_LOST)

    def test_silence_is_yes_sends_the_check_back_a_month_after_the_question(self):
        # CHECK_BACK_SILENCE, one line: Template B a month after an unanswered check-back question.
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.set_state(followup_asked_at=at(12, 12, 5, 14))
        self.go(at(11, 14, month=11))
        with patch.object(followups, "CHECK_BACK_SILENCE", followups.SILENCE_IS_YES):
            self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.CHECK_BACK)])
        self.assertEqual((self.state().followup_asked_at, self.state().followup_due_at), (None, at(12, 12, 5, 14) + dt.timedelta(days=30)))
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template):
            self.assertEqual(followups.send(self.conversation.pk, followups.CHECK_BACK), "sent")


class DeclineTests(LaunchBase):
    def test_a_no_the_model_talked_over_gets_no_nudge(self):
        self.said("No thank you", at(12, 12, 5))
        self.said("Who gave you my number?", at(12, 12, 5, 10))
        self.wrote("Sorry for the trouble: you asked us about a shop in International City some time ago. Are you still looking for one?", at(12, 12, 5, 30))
        self.window_from(at(12, 12, 5, 10))
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), "")
        self.assertEqual(self.holds(), followups.HELD_DECLINED)

    def test_a_no_with_a_time_of_theirs_is_no_decline(self):
        self.said("Yes I need a shop", at(12, 12, 5))
        self.wrote("I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?", at(12, 12, 5, 20))
        self.said("No, tomorrow is better", at(12, 12, 6))
        self.wrote("Sure! Would 11:00 AM or 1:00 PM tomorrow suit you?", at(12, 12, 6, 20))
        self.window_from(at(12, 12, 6))
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), followups.NUDGE_1)

    def test_a_no_to_a_question_of_ours_is_no_decline(self):
        self.said("Yes I need a shop", at(12, 12, 5))
        self.wrote("Do you already have a trade licence?", at(12, 12, 5, 20))
        self.said("No", at(12, 12, 6))
        self.wrote("No problem, many tenants open a new one. What business will the shop be for?", at(12, 12, 6, 20))
        self.window_from(at(12, 12, 6))
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), followups.NUDGE_1)

    def test_a_no_to_today_then_a_yes_to_tomorrow_takes_the_no_back(self):
        self.said("Yes I need a shop", at(12, 12, 5))
        self.wrote("I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?", at(12, 12, 5, 20))
        self.said("No", at(12, 12, 6))
        self.wrote("No problem! Would tomorrow at 11:00 AM or 1:00 PM suit you better?", at(12, 12, 6, 20))
        self.said("Yes", at(12, 12, 7))
        self.wrote("Great! Which one suits you, 11:00 AM or 1:00 PM?", at(12, 12, 7, 20))
        self.window_from(at(12, 12, 7))
        self.go(at(12, 14, 8))
        self.assertEqual(self.holds(), "")
        self.assertEqual(self.due(), followups.NUDGE_1)
        with patch.object(followups, "_takes_it_up", return_value=False):
            self.assertEqual(self.holds(), followups.HELD_DECLINED)
        # With no yes after it, the no holds the chat.
        Message.objects.filter(conversation=self.conversation, created_at__gte=at(12, 12, 7)).delete()
        self.window_from(at(12, 12, 6))
        self.assertEqual(self.holds(), followups.HELD_DECLINED)
        self.assertEqual(self.due(), "")

    def test_a_maybe_after_a_no_takes_nothing_back(self):
        self.said("Yes I need a shop", at(12, 12, 5))
        self.wrote("I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?", at(12, 12, 5, 20))
        self.said("No", at(12, 12, 6))
        self.wrote("No problem! Would tomorrow at 11:00 AM or 1:00 PM suit you better?", at(12, 12, 6, 20))
        self.said("maybe next week", at(12, 12, 7))
        self.wrote("Sure, just let me know the day that suits you. Shall I hold a slot for Monday?", at(12, 12, 7, 20))
        self.window_from(at(12, 12, 7))
        self.go(at(12, 14, 8))
        self.assertEqual(self.holds(), followups.HELD_DECLINED)

    def test_what_reads_as_a_no(self):
        for words in ("No", "No thank you", "No need", "Not interested", "nahi chahiye", "No sir", "No thanks, all good"):
            with self.subTest(words=words):
                self.assertTrue(followups._says_no(words))
        for words in (
            "No need to send photos, I will come", "no need for parking", "Not interested in Type 3", "No problem", "Not now",
            "No, tomorrow is better",
        ):
            with self.subTest(words=words):
                self.assertFalse(followups._says_no(words))

    def test_chat_50_no_shop_and_a_room_is_a_need_nudged_about_the_visit_only(self):
        self.said("No shop", at(12, 12, 5))
        self.said("Looking for a room", at(12, 12, 5, 4))
        self.listed(at(12, 12, 5, 20))  # as live
        self.window_from(at(12, 12, 5, 4))
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), followups.NUDGE_1)
        result, sent = self.nudge()
        self.assertEqual(result, "sent")
        self.assertEqual(sent.call_args.args[2], OPTIONS_NUDGE)


class NeedNudgeTests(LaunchBase):
    """Chats 44 and 132 as they went live (the shop list, then the generic shops nudge), and what goes now."""

    def test_chat_44_an_apartment_studio_is_nudged_about_the_options(self):
        self.said("I need an apartment studio", at(12, 12, 5))
        self.listed(at(12, 12, 5, 20))
        self.window_from(at(12, 12, 5))
        # The facts the live turn left (turn 51): the studio written as the business, before who_they_are.
        self.set_state(facts={"for_client": False, "property_type": "shop", "business_activity": "apartment studio", "intent": "rent"})
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), followups.NUDGE_1)
        result, sent = self.nudge()
        self.assertEqual((result, sent.call_args.args[2]), ("sent", OPTIONS_NUDGE))
        for kind in (followups.REENGAGE, followups.CHECK_BACK):
            self.assertEqual(self.holds(kind), followups.HELD_NO_SHOP)  # Template B is all shops

    def test_chat_132_no_shop_asked_and_a_studio_both_nudges_are_about_the_options(self):
        self.said("No I didn’t ask for shop", at(12, 12, 5))
        self.said("I asked for studio", at(12, 12, 5, 4))
        self.listed(at(12, 12, 5, 21))
        self.window_from(at(12, 12, 5, 4))
        self.set_state(facts={"for_client": False, "property_type": "studio", "intent": "rent"})
        self.go(at(12, 14, 6))
        self.assertEqual(self.holds(), "")  # "No I didn't ask for shop" says who they are: no decline of a visit
        result, sent = self.nudge()
        self.assertEqual((result, sent.call_args.args[2]), ("sent", OPTIONS_NUDGE))
        self.go(at(13, 10, 30))  # live, chat 132's second shops nudge was due about now
        result, sent = self.nudge(followups.NUDGE_2)
        self.assertEqual(result, "sent")
        self.assertTrue(sent.call_args.args[2].startswith("Good morning Ahmed, would today suit you to come and see the options?"))
        self.assertNotIn("shop", sent.call_args.args[2].lower())


class RentedTests(LaunchBase):
    def chat_63(self):
        self.said("we got one", at(12, 12, 5))
        self.said("thank you", at(12, 12, 5, 3))
        self.wrote(rules.line("rented_second_shop", "en"), at(12, 12, 5, 20))
        self.window_from(at(12, 12, 5, 3))

    def test_chat_63_silence_after_the_second_shop_question_gets_nothing(self):
        self.chat_63()  # the model's facts missed it: their words say it
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), "")
        self.assertEqual(self.holds(), followups.HELD_RENTED)

    def test_a_yes_to_a_second_shop_is_a_shop_lead_again(self):
        self.chat_63()
        self.said("Yes, I need one more for my brother", at(12, 12, 6))
        self.wrote("Great! What business will your brother's shop be for?", at(12, 12, 6, 20))
        self.window_from(at(12, 12, 6))
        self.set_state(facts={"already_rented": True, "for_client": False, "property_type": "shop"})
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), followups.NUDGE_1)

    def test_a_yes_that_says_they_rented_is_no_yes(self):
        self.chat_63()
        self.said("Yes we already got one, thanks", at(12, 12, 6))
        self.wrote("Thanks for letting us know! If you or anyone you know needs a shop, just message us here.", at(12, 12, 6, 20))
        self.window_from(at(12, 12, 6))
        self.go(at(12, 14, 7))
        self.assertEqual(self.holds(), followups.HELD_RENTED)

    def test_their_yes_tap_after_they_said_they_rented_is_a_lead_again(self):
        self.chat_63()
        self.tapped("Yes, show me shops", at(12, 12, 10))
        self.listed(at(12, 12, 10, 20))
        self.window_from(at(12, 12, 10))
        self.set_state(facts={"already_rented": True})
        self.go(at(12, 14, 11))
        self.assertEqual(self.holds(), "")
        self.assertEqual(self.due(), followups.NUDGE_1)

    def test_a_yes_to_the_campaign_before_the_model_learned_they_rented_is_no_yes(self):
        # [Yes, show me shops], then words needs.py does not read as rented; the model recorded it (facts).
        self.tapped("Yes, show me shops", at(12, 12, 5))
        self.wrote(rules.line("for_whom", "en"), at(12, 12, 5, 15))
        self.said("Actually my brother took a place last week, we are sorted", at(12, 12, 6))
        self.wrote("Congratulations! Do you need a second shop, or do you know someone who does?", at(12, 12, 6, 20))
        self.window_from(at(12, 12, 6))
        self.set_state(facts={"already_rented": True})
        self.go(at(12, 14, 7))
        self.assertEqual(self.holds(), followups.HELD_RENTED)

    def test_no_template_b_and_no_check_back_for_a_shop_rented_elsewhere(self):
        self.set_state(facts={"already_rented": True})
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(followups.send(self.conversation.pk, followups.REENGAGE), "not due")


class TemplateBNeverToANeedTests(LaunchBase):
    def test_what_the_chat_knows_of_a_need_keeps_template_b_away(self):
        self.go(THURSDAY)
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.REENGAGE)])  # nothing known: it goes
        for facts in (
            {"need": "home", "wanted": "a studio"},
            {"property_type": "studio"},  # chats 68, 132
            {"property_type": "shop", "business_activity": "apartment studio"},  # chat 44, before who_they_are
            {"intent": "buy", "property_type": "shop"},  # chat 42
        ):
            with self.subTest(facts=facts):
                self.set_state(facts=facts)
                self.assertEqual(followups.due_now(), [])
                self.assertEqual(followups.send(self.conversation.pk, followups.REENGAGE), "not due")
                self.assertEqual(followups.panel_note(self.conversation, self.state(), set()), "")  # no "waits for approval" note

    def test_a_check_back_planned_for_someone_who_rented_since_is_dropped(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Yes", at(12, 12, 6))
        self.wrote(rules.line("check_back_yes", "en"), at(12, 12, 6, 15))
        self.set_state(followup_due_at=CHECK_DAY, facts={"already_rented": True})
        self.go(CHECK_DAY)
        self.assertEqual(followups.due_now(), [])
        self.assertIsNone(self.state().followup_due_at)  # moot: nothing waits for it any more

    def test_a_template_b_the_gateway_refused_for_credit_is_read_past(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        refused = _outbound(
            self.conversation, None, Message.Kind.TEMPLATE, "Hi Ahmed, a quick follow-up.",
            {"source": transcript.FOLLOW_UP, "attempt": "check_back:x", followups.ATTEMPT_FAILED: followups.NO_CREDIT},
            template=self.template_b, created_at=at(12, 13),
        )
        Message.objects.filter(pk=refused.pk).update(status=Message.Status.FAILED)
        templates = transcript.campaign_template_ids(self.conversation)
        self.assertEqual(transcript.campaign_message(self.conversation, templates).pk, refused.pk)
        self.assertEqual(followups._boundary(self.conversation, templates).pk, self.campaign_message.pk)
        self.assertEqual(followups.read_since(self.conversation).words, ["Not now"])

    def test_a_reply_cap_skip_pending_holds_the_check_back_and_keeps_its_date(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Yes", at(12, 12, 6))
        self.wrote(rules.line("check_back_yes", "en"), at(12, 12, 6, 15))
        self.set_state(followup_due_at=CHECK_DAY)
        capped = self.said("ok", CHECK_DAY - dt.timedelta(hours=1))
        LeadAiTurn.objects.create(conversation=self.conversation, inbound=capped, status=LeadAiTurn.Status.SKIPPED, reason=engine.CAPPED_REASON)
        self.go(CHECK_DAY)
        self.assertEqual(followups.due_now(), [])
        self.assertEqual(self.state().followup_due_at, CHECK_DAY)  # it waits
        LeadAiTurn.objects.filter(inbound=capped).update(reason="an acknowledgement needs no answer")
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.CHECK_BACK)])


# B. A question of theirs left to a colleague ------------------------------------------------------------


class OpenQuestionTests(LaunchBase):
    def test_chat_95_no_nudge_over_nine_questions_and_a_person_is_alerted_once(self):
        self.said(NINE_QUESTIONS, at(12, 12, 5))
        self.wrote(DEFERRED_95, at(12, 12, 5, 20))
        self.window_from(at(12, 12, 5))
        self.go(at(12, 14, 5))
        self.assertEqual(self.due(), "")  # not two hours yet
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), followups.OPEN_QUESTION)
        with patch("apps.inbox.services.send_text") as sent:
            self.assertEqual(followups.send(self.conversation.pk, followups.OPEN_QUESTION), "alerted")
        sent.assert_not_called()  # nothing to the customer
        alerts = LeadAiAlert.objects.filter(kind=followups.OPEN_QUESTION).order_by("pk")
        self.assertEqual({alert.bitrix_user_id for alert in alerts}, {"77", "2311"})  # the chat's owner and the Lead AI list
        self.assertEqual(alerts[0].title, "Ahmed Khan is waiting for an answer")
        self.assertIn("Can the landlord provide an NOC for F&B", alerts[0].text)
        self.assertIn("9. What is the complete upfront amount including deposit", alerts[0].text)  # all nine, not 255 characters
        self.assertIn("please answer them here", alerts[0].text)
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), "")  # once for those words
        self.assertEqual(self.nudge()[0], "not due")
        self.assertEqual(self.state().nudges, 0)

    def test_chat_59_full_details_including_rent_security(self):
        self.tapped("Yes, show me shops", at(12, 12, 5))
        self.wrote(rules.line("for_whom", "en"), at(12, 12, 5, 15))
        self.said("How many square feet area", at(12, 12, 5, 20))
        self.listed(at(12, 12, 5, 40))
        self.said("And give me full details including rent security", at(12, 12, 6))
        self.wrote(DEFERRED_59, at(12, 12, 6, 20))
        self.window_from(at(12, 12, 6))
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), followups.OPEN_QUESTION)
        self.assertEqual(self.holds(), followups.HELD_QUESTION)

    def test_chat_78_a_question_left_earlier_and_answered_on_holds_nothing(self):
        self.said("And can u give me the detai computation i need back area", at(12, 12, 5))
        self.wrote(DEFERRED_78, at(12, 12, 5, 20))
        self.said("Interior landscape", at(12, 12, 6))
        self.said("Artificial plants pots", at(12, 12, 6, 10))
        self.wrote(LICENCE_78, at(12, 12, 6, 30))
        self.window_from(at(12, 12, 6, 10))
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), followups.NUDGE_1)

    def test_a_question_left_open_after_a_no_still_reaches_a_person(self):
        self.said("No thanks. But can the landlord give an NOC for a restaurant?", at(12, 12, 5))
        self.wrote("Good question — I'll have our agent confirm that for you at the viewing. Would you like to see the shops?", at(12, 12, 5, 20))
        self.window_from(at(12, 12, 5))
        self.go(at(12, 14, 6))
        self.assertEqual(self.holds(), followups.HELD_QUESTION)  # before the no
        self.assertEqual(self.due(), followups.OPEN_QUESTION)

    def test_chat_78_its_nudge_spent_a_question_left_open_is_told_to_a_person(self):
        # Chat 78 live, the times moved to the tests' campaign: the nudge brought him back, then his back area and
        # parking side were left to our agent. With no nudge left, a silence there is no longer a dead end.
        self.tapped("Yes, show me shops", at(12, 12, 2))
        self.wrote(rules.line("for_whom", "en"), at(12, 12, 2, 15))
        self.wrote(SHOPS_NUDGE.replace("Ahmed", "there"), at(12, 14, 3), nudge=1)
        self.said("For me", at(12, 14, 4, 39))
        self.listed(at(12, 14, 4, 56))
        self.said("And can u give me the detai computation i need back area", at(12, 14, 5, 22))
        self.said("Parking side", at(12, 14, 5, 28))
        self.said("33k", at(12, 14, 5, 42))
        self.wrote(DEFERRED_78, at(12, 14, 6))
        self.window_from(at(12, 14, 5, 42))
        self.set_state(nudges=1, nudged_at=at(12, 14, 3))
        self.go(at(12, 16, 7))
        self.assertEqual(self.due(), followups.OPEN_QUESTION)
        self.assertEqual(followups.send(self.conversation.pk, followups.OPEN_QUESTION), "alerted")
        self.assertIn("And can u give me the detai computation i need back area / Parking side / 33k", LeadAiAlert.objects.first().text)

    def test_what_reads_as_a_question_left_to_a_colleague(self):
        for text in (
            DEFERRED_95, DEFERRED_59, DEFERRED_78, "Hamara agent viewing par yeh confirm kar dega.",
            "Our team will get back to you with the details.", "A colleague will answer your questions here before the visit.",
            "سؤال جيد — سأطلب من وكيلنا تأكيد ذلك لك أثناء المعاينة.", *rules.LINES["deflect"].values(),
        ):
            with self.subTest(text=text[:40]):
                self.assertTrue(nudges.defers_question(text))
        for text in (
            "Our agent can discuss the best price for you at the viewing.",  # a discount: the price rules' own
            "Our agent will drive you to the shops and back.", "Our agent will guide you through the process.",
            "Our team will confirm the time with you here.", LICENCE_78,
            "Our agent will call you today between 11:30 and 12:00 to discuss your needs and guide you further.",
            "سيتواصل معك المختص لدينا لتأكيد الموعد.",
        ):
            with self.subTest(text=text[:40]):
                self.assertFalse(nudges.defers_question(text))
        # None of code's own lines but the deflect line (the holding line and the visit's own confirmation among them).
        for key, table in rules.LINES.items():
            for language, line in table.items():
                with self.subTest(key=key, language=language):
                    self.assertEqual(nudges.defers_question(line), key == "deflect")


# C. Our for-whom question asked again ---------------------------------------------------------------------


class ForWhomAgainTests(LaunchBase):
    def chat_103(self):
        self.tapped("Yes, show me shops", at(12, 12, 5))
        self.wrote(rules.line("for_whom", "en"), at(12, 12, 5, 15))
        self.window_from(at(12, 12, 5))

    def test_chat_103_the_nudge_asks_for_whom_again(self):
        self.chat_103()
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), followups.NUDGE_1)
        result, sent = self.nudge()
        self.assertEqual(result, "sent")
        self.assertEqual(sent.call_args.args[2], FOR_WHOM_AGAIN)
        # The morning after, the build pack's last nudge, as before.
        self.go(at(13, 10, 30))
        result, sent = self.nudge(followups.NUDGE_2)
        self.assertEqual(result, "sent")
        self.assertTrue(sent.call_args.args[2].startswith("Good morning Ahmed, would today suit you to see the shops?"))

    def test_in_their_language_and_after_the_models_own_words_around_it(self):
        self.chat_103()
        self.set_state(language="ar")
        self.go(at(12, 14, 6))
        self.assertEqual(self.nudge()[1].call_args.args[2], "مرحباً Ahmed، أردت فقط الاطمئنان — هل المحل لك شخصياً، أم تبحث عنه لعميل؟")
        self.assertTrue(nudges.asks_for_whom("I see, thanks for clarifying. Is the shop for yourself, or are you checking for a client?"))  # chat 98
        self.assertFalse(nudges.asks_for_whom("What business will the shop be for?"))

    def test_the_question_asked_again_is_the_lines_own_in_six_languages_and_invites_nobody(self):
        for language, line in rules.LINES["for_whom"].items():
            with self.subTest(language=language):
                text = nudges.first_text(language, "Ahmed", for_whom=True, now=at(12, 14))
                question = line.split("!", 1)[1].strip()
                self.assertTrue(text.endswith(question[0].lower() + question[1:] if language in ("en", "ur_latin", "hi_latin") else question), text)
                self.assertFalse(nudges.is_nudge(text))
                self.assertFalse(engine.visit_offered(text))
                self.assertFalse(engine.agreed_to_come(visit_open=False, our_last=text, texts=["Yes"]))  # a yes to it agrees to nothing
        # A need's nudge stays about the visit.
        self.assertEqual(nudges.first_text("en", "Ahmed", for_whom=True, options=True, now=at(12, 14)), OPTIONS_NUDGE)


# D. A no to the second-shop question, in other words ------------------------------------------------------


class SecondShopNoTests(ShopsBase):
    def ask_second_shop(self):
        self.inbound("we got one", seconds_ago=40)
        message = self.inbound("thank you", seconds_ago=30)
        live = shop_answer("Great! What business will the shop be for?", facts={"for_client": False, "property_type": "shop", "already_rented": True})
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), rules.line("rented_second_shop", "en"))
        self.later(2)

    def no_to_it(self, words):
        self.ask_second_shop()
        outcome, calls, _, _ = self.turn(self.inbound(words, seconds_ago=10), [shop_answer()])
        self.assertEqual(calls, [])  # code's, no model
        self.assertEqual(self.body(outcome), rules.line_for(rules.NOT_INTERESTED, "en", shops=True))
        self.assertEqual(LeadAiCrmField.objects.get(field=crm_fields.LOST).payload, {"reason": "already rented"})
        self.assertIsNotNone(self.state().not_interested_at)

    def test_chat_63_if_anything_will_let_you_know_closes_the_lead_as_already_rented(self):
        self.no_to_it("if anything will let you know")

    def test_chat_63_will_reach_out_if_we_need_anything_is_a_no_too(self):
        self.no_to_it(REACH_OUT_63)

    def test_a_referral_or_a_yes_is_the_models(self):
        self.ask_second_shop()
        outcome, calls, _, _ = self.turn(
            self.inbound("My friend needs one, I will let you know", seconds_ago=10),
            [shop_answer("That's great! Your friend is welcome to message us here.")],
        )
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.state().not_interested_at)
        self.assertFalse(LeadAiCrmField.objects.filter(field=crm_fields.LOST).exists())

    def test_what_says_no_to_a_second_shop(self):
        for words in (
            "if anything will let you know", REACH_OUT_63, "No", "no need", "No thanks, all good", "Not now", "We're good for now",
            "I'm fine, thank you", "abhi nahi", "jab zaroorat hogi bata dunga",
        ):
            with self.subTest(words=words[:30]):
                self.assertTrue(engine.second_shop_no(words) or rules.is_refusal(words))
        for words in (
            "Yes, I need one more for my brother", "My friend needs one, I will let you know", "I know someone who needs a shop",
            "Do you have bigger ones?", "yes, okay", "Thank you", "What is the rent of Type 2?",
        ):
            with self.subTest(words=words[:30]):
                self.assertFalse(engine.second_shop_no(words))


# E. A tentative visit with no time, or a past one, lapses ----------------------------------------------------


class TentativeLapseTests(LaunchBase):
    def tentative(self, words, made, *, starts_at=None, place="office", revisions=(), name="Saif"):
        self.go(made)
        history = [{"at": made.isoformat(), "event": "tentative", "note": words, "place": place}]
        for moment, start in revisions:
            entry = {"at": moment.isoformat(), "event": "tentative", "note": words, "place": place}
            if start is not None:
                entry["start"] = start.isoformat()
            history.append(entry)
        return LeadAiAppointment.objects.create(
            conversation=self.conversation, status="tentative", place=place, starts_at=starts_at, note=words, customer_words=words,
            customer_name=name, history=history, crm_entity="lead", crm_id=555,
            details={"intent": "rent", "property_type": "shop", "community": "Morocco", "shop_type": "type_2"},
        )

    def sweep(self, moment):
        self.go(moment)
        tasks._close_past_appointments()

    def test_chat_100_ok_with_no_time_lapses_a_day_on_and_the_team_is_told(self):
        # Chat 100: "Ok" to the nudge (12:35) became tentative 19 with no time; the chat went on to "Send me address first".
        appointment = self.tentative("Ok", at(12, 12, 35))
        self.said("Send me address first", at(12, 12, 54))
        self.wrote(f"Our office is in {DEFAULT_OFFICE_ADDRESS}. Would you like to book a viewing?\n{MAPS}", at(12, 12, 54, 17))
        self.window_from(at(12, 12, 54))
        outbound = Message.objects.filter(direction=Message.Direction.OUTBOUND).count()
        self.sweep(at(13, 12, 34))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "tentative")
        self.assertEqual(self.due(), "")  # still held by it
        self.sweep(at(13, 12, 36))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, LeadAiAppointment.Status.DONE)
        self.assertEqual((appointment.history[-1]["event"], appointment.history[-1]["why"]), ("lapsed", tasks.LAPSED_NO_TIME))
        alerts = LeadAiAlert.objects.filter(kind="tentative_lapsed")
        self.assertEqual({alert.bitrix_user_id for alert in alerts}, {"77", "2311"})
        self.assertEqual(alerts[0].title, "Saif: tentative visit lapsed")
        self.assertIn("Their words: Ok", alerts[0].text)
        self.assertIn("No day and time were agreed in the 24 hours since they said it.", alerts[0].text)
        self.assertEqual(Message.objects.filter(direction=Message.Direction.OUTBOUND).count(), outbound)  # nothing to the customer
        self.assertEqual(self.due(), followups.NUDGE_1)  # the chat is no longer frozen
        self.sweep(at(13, 12, 37))
        self.assertEqual(alerts.count(), 2)  # once

    def test_chat_96_the_day_runs_from_the_last_time_they_said_it(self):
        appointment = self.tentative(
            "barah saadhay barah baje ja ke check kar loon ga", at(12, 11, 12),
            revisions=((at(12, 12, 27), at(12, 12, 30)), (at(12, 12, 35), None)), name="",
        )
        self.sweep(at(13, 11, 13))  # a day after it was made, not after it was last said
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "tentative")
        self.sweep(at(13, 12, 36))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, LeadAiAppointment.Status.DONE)
        self.assertEqual(LeadAiAlert.objects.get(kind="tentative_lapsed", bitrix_user_id="2311").title, "Ahmed Khan: tentative visit lapsed")

    def test_chat_62_a_past_time_lapses_an_hour_on_and_the_models_own_offer_alerts_nobody(self):
        appointment = self.tentative("If possible to send me photo first", at(12, 10, 27), starts_at=at(12, 11), name="ora")
        self.sweep(at(12, 11, 59))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "tentative")
        self.sweep(at(12, 12, 1))
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.history[-1]["why"]), (LeadAiAppointment.Status.DONE, tasks.LAPSED_TIME_PASSED))
        self.assertFalse(LeadAiAlert.objects.filter(kind="tentative_lapsed").exists())

    def test_chat_59_your_rent_is_higher_lapses_without_an_alert(self):
        appointment = self.tentative("Your rent is higher than others", at(12, 12, 40), name="ETS")
        self.sweep(at(13, 12, 41))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, LeadAiAppointment.Status.DONE)
        self.assertFalse(LeadAiAlert.objects.filter(kind="tentative_lapsed").exists())

    def test_chat_88_a_call_at_a_time_of_theirs_that_passed(self):
        appointment = self.tentative("We can have a call at 11.30 - 12 PM", at(12, 10, 35), starts_at=at(12, 11, 30), place="call", name="Abd")
        self.sweep(at(12, 12, 31))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, LeadAiAppointment.Status.DONE)
        alert = LeadAiAlert.objects.get(kind="tentative_lapsed", bitrix_user_id="2311")
        self.assertEqual(alert.title, "Abd: tentative call lapsed")
        self.assertIn("Its time, Monday 12 October 2026, 11:30 AM, has passed with nothing confirmed.", alert.text)

    def test_no_alert_for_a_customer_who_stopped_or_declined_since(self):
        for field in ("stopped_at", "not_interested_at"):
            with self.subTest(field=field):
                LeadAiAppointment.objects.all().delete()
                self.set_state(stopped_at=None, not_interested_at=None)
                appointment = self.tentative("Ok", at(12, 12, 35))
                self.set_state(**{field: at(12, 13)})
                self.sweep(at(13, 12, 36))
                appointment.refresh_from_db()
                self.assertEqual(appointment.status, LeadAiAppointment.Status.DONE)
                self.assertFalse(LeadAiAlert.objects.filter(kind="tentative_lapsed").exists())

    def test_a_past_time_they_spoke_of_after_it_waits_an_hour_from_their_words(self):
        appointment = self.tentative(
            "I'm on my way, 10 minutes", at(12, 10, 27), starts_at=at(12, 11), revisions=((at(12, 11, 50), at(12, 11)),),
        )
        self.sweep(at(12, 12, 1))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "tentative")
        self.sweep(at(12, 12, 51))
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.history[-1]["why"]), (LeadAiAppointment.Status.DONE, tasks.LAPSED_TIME_PASSED))

    def test_a_general_chats_tentative_never_keeps_a_shops_one_waiting(self):
        # The sweep reads LAPSE_PAGE a minute: an older tentative of a chat that is not a shops chat (open for days)
        # came first by pk and filled the page, so the shops one never lapsed.
        general = LeadAiAppointment.objects.create(conversation=self.other(), status="tentative", note="may come", customer_words="may come")
        LeadAiAppointment.objects.filter(pk=general.pk).update(created_at=at(12, 9))
        appointment = self.tentative("Ok", at(12, 12, 35))
        with patch.object(tasks, "LAPSE_PAGE", 1):
            self.sweep(at(13, 12, 36))
        appointment.refresh_from_db()
        general.refresh_from_db()
        self.assertEqual((appointment.status, general.status), (LeadAiAppointment.Status.DONE, "tentative"))

    def test_a_visit_still_ahead_and_a_confirmed_one_stay(self):
        ahead = self.tentative("Tomorrow at 5 pm", at(12, 12, 40), starts_at=at(13, 17))
        self.sweep(at(13, 17, 59))
        ahead.refresh_from_db()
        self.assertEqual(ahead.status, "tentative")
        LeadAiAppointment.objects.filter(pk=ahead.pk).update(status="confirmed")
        self.sweep(at(13, 18, 1))
        self.assertEqual(LeadAiAppointment.objects.get(pk=ahead.pk).status, "confirmed")  # done only three hours after it


class GeneralTentativeTests(GeneralBase):
    def test_a_general_chats_tentative_keeps_its_seven_days(self):
        appointment = LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", note="may come", customer_words="may come")
        self.clock.return_value = NOW + dt.timedelta(days=2)
        tasks._close_past_appointments()
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "tentative")
        self.assertFalse(LeadAiAlert.objects.filter(kind="tentative_lapsed").exists())
        self.clock.return_value = NOW + dt.timedelta(days=8)
        tasks._close_past_appointments()
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, LeadAiAppointment.Status.DONE)  # TENTATIVE_LAPSES, as before


# F. The eval's scenarios, and the guards patched out -----------------------------------------------------------

SCENARIOS = ("shops-rented-soft-no-63", "shops-rented-reach-out-63", "shops-rented-friend-63", "shops-for-whom-again-103")


class EvalFollowUpTests(SimpleTestCase):
    def run_scenario(self, scenario_id):
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=RIGHT[scenario_id]):
            return leadai_eval.run_once(scenario, scenario_id)

    @override_settings(LEADAI_OPENAI_API_KEY="test")
    def test_the_scenarios_pass_with_the_live_answers_and_fail_without_the_guard(self):
        for scenario_id in SCENARIOS:
            with self.subTest(scenario_id):
                self.assertEqual(self.run_scenario(scenario_id).failures, [])
        with patch.object(engine, "second_shop_no", return_value=False):
            for scenario_id in ("shops-rented-soft-no-63", "shops-rented-reach-out-63"):
                with self.subTest(scenario_id):
                    self.assertNotEqual(self.run_scenario(scenario_id).failures, [])

    def test_the_scenarios_use_the_launch_customers_own_words(self):
        words = {s.id: s.new for s in leadai_eval.SCENARIOS}
        self.assertEqual(words["shops-rented-soft-no-63"], ["if anything will let you know"])
        self.assertEqual(words["shops-rented-reach-out-63"], [REACH_OUT_63])
        self.assertEqual(words["shops-for-whom-again-103"], ["For me"])  # chat 78's answer to its nudge


class WithoutTheGuardsTests(LaunchBase):
    """The same launch chats with this batch's guards taken out: the old follow-ups come back."""

    def setUp(self):
        super().setUp()
        for patcher in (
            patch.object(followups, "holds", return_value=""),
            patch.object(followups, "question_left", return_value=False),
            patch.object(followups, "wants_no_shop", side_effect=lambda facts, reading: needs.of(facts) is not None),
            patch.object(nudges, "asks_for_whom", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_old_nudges_go_to_68_95_50_and_103(self):
        self.tapped("Not now", at(12, 12, 5))
        self.wrote(rules.line("check_back", "en"), at(12, 12, 5, 15))
        self.said("Actually i was looking for a studio", at(12, 12, 5, 40))
        self.listed(at(12, 12, 6))
        self.said("Not shops", at(12, 12, 6, 20))
        self.wrote(STUDIO_68, at(12, 12, 6, 40))
        self.window_from(at(12, 12, 6, 20))
        self.go(at(12, 14, 7))
        self.assertEqual(self.due(), followups.NUDGE_1)  # chat 68, live
        Message.objects.filter(conversation=self.conversation, pk__gt=self.campaign_message.pk).delete()
        self.said(NINE_QUESTIONS, at(12, 12, 5))
        self.wrote(DEFERRED_95, at(12, 12, 5, 20))
        self.go(at(12, 14, 6))
        self.assertEqual(self.due(), followups.NUDGE_1)  # chat 95, live
        Message.objects.filter(conversation=self.conversation, pk__gt=self.campaign_message.pk).delete()
        self.tapped("Yes, show me shops", at(12, 12, 5))
        self.wrote(rules.line("for_whom", "en"), at(12, 12, 5, 15))
        self.assertEqual(self.nudge()[1].call_args.args[2], SHOPS_NUDGE)  # chat 103, live

    def test_the_old_sweep_keeps_a_tentative_for_seven_days(self):
        with patch.object(tasks, "_lapse_shops_tentatives"):
            self.go(at(12, 12, 35))
            appointment = LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", note="Ok", customer_words="Ok")
            self.go(at(14, 12, 36))
            tasks._close_past_appointments()
            appointment.refresh_from_db()
            self.assertEqual(appointment.status, "tentative")
