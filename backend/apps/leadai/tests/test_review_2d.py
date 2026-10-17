"""Batch 2d's review (2026-10-16): what the replay of the launch chats and the probes found in the batch.

Each test feeds the launch customers' own words (chat_<id>.json of the review), or a shop customer's words the probes
found misread, with the model's answers as the live turns recorded them, and fails without the fix it proves:

- A. our office's pin after the owner's line is no "last word" of ours: an "OK" to the line is answered and the
  options nudge goes (chats 44 and 136);
- B. must-answer questions go to a person while the chat goes on, and are escalated like a handover (chats 91, 95);
- C. the escalation sweep: a page of other playbooks' handovers never hides a shops one; a Broker or a Handed set in
  Bitrix, an opt-out elsewhere or a "not interested" is no handover to chase;
- D. who the customer is: a shop customer's room, staff accommodation or "flat nahi" is no home they want; a later
  request for a shop forgets a want read wrong; a call in their own words beats the owner's line; "Not shops" never
  replaces "a studio"; a buyer hears no word of renting and no third invitation; an apology alone becomes the owner's
  line; such a chat is handed over only for a person, a call, a complaint or a broker; a buyer the model knows is
  never Lost;
- E. a count ("3 or 4 of us") is no window of time to book;
- F. "need one more" is no shop rented elsewhere, and "No, I told you I need another one" no no to a second shop;
- G. "Why did you call me?" and "I'll call back later" are no call requests; "I want to sign the contract today" no
  contract question;
- H. the CRM: a call recorded through user 1 is a person's work; a person's touch our own write hid is remembered;
  the notes go to the shops campaign's lead; a retried lost move whose answer was lost writes no false record;
- I. the follow-ups hold for a lead a person booked or works in Bitrix;
- J. the smaller ones: short names in capitals, a note that restates the reply's own claim, the eval gate, the
  guards nothing tested.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai; the chat is lead 555's.
"""

import contextlib
import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Agent
from apps.campaigns.models import CampaignRecipient
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import bitrix_status, followups, lane, optout, tasks
from apps.leadai.assistant import crm, crm_facts, crm_fields, engine, filters, hours, lost, needs, people, rules
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiChat, LeadAiChatState, LeadAiCrmField, LeadAiSettings, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, _outbound, fake_send_text
from apps.leadai.tests.test_crm_writes import IDLE_LEAD, CrmWritesBase, FakeBitrix
from apps.leadai.tests.test_eval_command import RIGHT, answer as eval_answer
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, shop_answer

DUBAI = hours.DUBAI
MAPS = "https://maps.app.goo.gl/u7xzyea9pPLpRxBD8"
THANKS = "Thank you for letting us know."
SORRY = "Thank you for letting us know, and sorry for the confusion."
VISIT = "Visit our office and we'll give you the best option."
MUST_ANSWER_LINE = people.line(people.MUST_ANSWER, "en", shops=True)


def line(options: str, *, sorry: bool = False, slots: str = TWO_SLOTS_NOW) -> str:
    return " ".join(part for part in (SORRY if sorry else THANKS, options, VISIT, slots) if part)


class ReviewBase(ShopsBase):
    def setUp(self):
        super().setUp()
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url=MAPS, office_latitude=25.169639, office_longitude=55.404667)
        self.list_matloob()

    def go(self, moment):
        self.clock.return_value = moment

    def outbound(self):
        return list(
            Message.objects.filter(conversation=self.conversation, direction=Message.Direction.OUTBOUND)
            .order_by("pk")
            .values_list("kind", "body")
        )

    def alerts_of(self, kind):
        return list(LeadAiAlert.objects.filter(conversation=self.conversation, kind=kind).order_by("pk"))


# A. Our office's pin after the owner's line ---------------------------------------------------------------------------


class PinIsNoLastWordTests(ReviewBase):
    def owners_line_136(self):
        """Chat 136 at 10:39: "AM NOT LOOKING FOR SHOPS" / "AM LOOKING FOR STUDIO APARTMENTS", the model's live answer an
        "unclear" handover; code's answer the owner's line with two slots, the Maps link, then the pin."""
        self.inbound("AM NOT LOOKING FOR SHOPS", seconds_ago=40)
        message = self.inbound("AM LOOKING FOR STUDIO APARTMENTS", seconds_ago=30)
        live = shop_answer(
            "We specialize in shops in International City. For studio apartments, I will connect you to our agent who can assist you further here.",
            handover="unclear", segment="other", facts={"for_client": False, "property_type": "studio apartment", "intent": "rent"},
        )
        outcome, _, _, _ = self.turn(message, [live])
        self.assertTrue(self.body(outcome).startswith(SORRY))
        self.assertEqual(self.outbound()[-1][0], Message.Kind.LOCATION)  # the pin is the newest message of ours
        return outcome

    def test_chat_136_ok_to_the_owners_line_is_answered(self):
        self.owners_line_136()
        for word in ("OK", "Sure", "theek hai"):
            with self.subTest(word=word):
                self.go(timezone.now() + dt.timedelta(minutes=4))
                message = self.inbound(word, seconds_ago=20)
                outcome, calls, _, _ = self.turn(message, [shop_answer("Which time works better for you: 3:00 PM or 5:00 PM?")])
                self.assertEqual(outcome.reason, "")  # live: "an acknowledgement needs no answer", and nothing more ever went
                self.assertEqual(len(calls), 1)

    def test_an_ok_to_a_booking_and_its_pin_still_needs_no_answer(self):
        self.set_state(facts={"need": "home", "wanted": "a studio", "property_type": "studio"}, invites=1)
        self.ours(f"{THANKS} We have many options for a studio across Dubai. {VISIT} {TWO_SLOTS_NOW}", minutes_ago=5)
        booked, _, _, _ = self.turn(self.inbound("5 PM today is fine"), [shop_answer("", action="confirm", place="office", date="2026-10-12", time="17:00")])
        self.assertTrue(self.body(booked).startswith("Perfect, Ahmed. Your meeting is confirmed."))
        self.assertEqual(self.outbound()[-1][0], Message.Kind.LOCATION)
        self.go(NOW + dt.timedelta(minutes=2))
        outcome, calls, _, _ = self.turn(self.inbound("ok", seconds_ago=20), [shop_answer("See you!")])
        self.assertEqual((outcome.reason, calls), ("an acknowledgement needs no answer", []))

    def test_a_yes_to_the_owners_line_is_a_yes_to_its_slots(self):
        self.owners_line_136()
        self.assertTrue(engine.visit_offered(engine.transcript.outbound_text(engine._last_outbound(self.conversation))))


class PinAndTheNudgeTests(ReviewBase):
    def setUp(self):
        super().setUp()
        self.queued = self.stub("apps.leadai.tasks.send_follow_up.delay")

    def test_chat_44_the_options_nudge_follows_the_owners_line_and_its_pin(self):
        message = self.inbound("I need an apartment studio")
        live = shop_answer(
            "Great! What business will the shop be for?",
            facts={"for_client": False, "property_type": "shop", "business_activity": "apartment studio"},
        )
        self.turn(message, [live])
        self.assertEqual(self.outbound()[-1][0], Message.Kind.LOCATION)
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=NOW + dt.timedelta(hours=20))
        self.go(NOW + dt.timedelta(hours=2, minutes=1))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.NUDGE_1)])  # live: [] at every moment
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text) as sent:
            self.assertEqual(followups.send(self.conversation.pk, followups.NUDGE_1), "sent")
        self.assertEqual(sent.call_args.args[2], "Hi Ahmed, just checking in — shall I hold a slot for you to see the options today or tomorrow?")


# B. Must-answer questions while the chat goes on ------------------------------------------------------------------------


NINE_QUESTIONS = leadai_eval.NINE_QUESTIONS_95


class QuestionsEscalationTests(ReviewBase):
    def asked(self):
        message = self.inbound("is there available gas line and chimney?", seconds_ago=20)
        self.turn(message, [shop_answer("Good question — I'll have our agent confirm that for you at the viewing.")])
        self.assertIsNone(self.state().handed_over_at)
        self.assertEqual(len(self.alerts_of(people.QUESTIONS)), 2)  # the chat's owner (77) and 2311

    def test_questions_nobody_answered_are_escalated_once_after_30_office_minutes(self):
        self.asked()
        self.assertEqual(people.escalate_waiting(NOW + dt.timedelta(minutes=29)), 0)
        self.assertEqual(people.escalate_waiting(NOW + dt.timedelta(minutes=31)), 1)
        rows = self.alerts_of(people.WAITING)
        self.assertEqual({row.priority for row in rows}, {"high"})
        self.assertIn("asked questions a person must answer before any visit", rows[0].text)
        self.assertIn("Their last words: is there available gas line and chimney?", rows[0].text)
        self.assertEqual(people.escalate_waiting(NOW + dt.timedelta(minutes=50)), 0)  # once

    def test_not_when_a_person_wrote_since(self):
        self.asked()
        _outbound(self.conversation, self.matloob, Message.Kind.TEXT, "Yes, Type 2 has a gas line.", {}, created_at=NOW + dt.timedelta(minutes=10))
        self.assertEqual(people.escalate_waiting(NOW + dt.timedelta(minutes=31)), 0)

    def test_no_nudge_pushes_a_visit_over_them(self):
        self.stub("apps.leadai.tasks.send_follow_up.delay")
        self.asked()
        self.go(NOW + dt.timedelta(hours=2, minutes=1))
        self.assertEqual(followups.due_now(), [(self.conversation.pk, followups.OPEN_QUESTION)])  # a person is told, no nudge


class MustAnswerWordsTests(SimpleTestCase):
    def test_what_the_model_may_say_with_the_line(self):
        reply = (
            "Good question — I'll have our agent confirm that for you at the viewing. Our agent will call you today. Please contact "
            "Manhial. Type 1 is from AED 33,000 a year. Is there a gas line? What size do you need?"
        )
        kept = people.must_answer_kept(reply)
        self.assertEqual(kept, "Type 1 is from AED 33,000 a year. What size do you need?")
        self.assertEqual(people.with_kept(MUST_ANSWER_LINE, kept), f"Type 1 is from AED 33,000 a year. {MUST_ANSWER_LINE} What size do you need?")
        self.assertEqual(people.with_kept(MUST_ANSWER_LINE, ""), MUST_ANSWER_LINE)

    def test_the_line_holds_the_nudge_in_every_language(self):
        from apps.leadai.assistant import nudges

        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi"):
            with self.subTest(language):
                self.assertTrue(nudges.defers_question(people.line(people.MUST_ANSWER, language, shops=True)))


# C. The escalation sweep ----------------------------------------------------------------------------------------------


class EscalationSweepTests(ReviewBase):
    def handed(self, minutes_ago=40, reason="call_requested", **fields):
        self.inbound("We can have a call at 11.30 - 12 PM", seconds_ago=minutes_ago * 60 + 20)
        self.ours(people.line(people.CALL_PASSED, "en", shops=True), minutes_ago=minutes_ago)
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=minutes_ago), handover_reason=reason, **fields)

    def test_a_page_of_older_handovers_of_other_playbooks_never_hides_a_shops_one(self):  # crm-F1
        for index in range(people.ESCALATE_PAGE + 5):
            contact = Contact.objects.create(wa_id=f"9715000{index:05d}", display_name=f"C{index}")
            other = Conversation.objects.create(number=self.number, contact=contact, session_expires_at=NOW + dt.timedelta(hours=20))
            LeadAiChatState.objects.create(conversation=other, handed_over_at=NOW - dt.timedelta(days=1, minutes=index), handover_reason="unclear")
        self.handed()
        self.assertEqual(people.escalate_waiting(NOW), 1)
        self.assertEqual({row.conversation_id for row in LeadAiAlert.objects.filter(kind=people.WAITING)}, {self.conversation.pk})

    def test_a_broker_set_in_bitrix_is_no_handover_to_chase(self):  # crm-F5
        self.inbound("We can have a call at 11.30 - 12 PM", seconds_ago=45 * 60)
        with self.captureOnCommitCallbacks(execute=True):
            self.go(NOW - dt.timedelta(minutes=40))
            bitrix_status.apply(555, bot_status=bitrix_status.BROKER, changed_by="2302")
            self.go(NOW)
        self.assertEqual(self.state().handover_reason, engine.BROKER)
        self.assertEqual(people.escalate_waiting(NOW), 0)

    def test_handed_in_bitrix_after_the_bots_own_handover_is_no_handover_to_chase(self):  # crm-F5
        self.handed()
        with self.captureOnCommitCallbacks(execute=True):
            self.go(NOW - dt.timedelta(minutes=10))
            bitrix_status.apply(555, bot_status=bitrix_status.HANDED, changed_by="2302")
            self.go(NOW)
        self.assertEqual(self.state().handover_reason, "call_requested")  # the bot's reason stays (C36)
        self.assertEqual(people.escalate_waiting(NOW), 0)

    def test_opted_out_elsewhere_or_not_interested_since(self):  # crm-F6
        self.handed()
        optout.record(self.contact.wa_id, reason="STOP", source=optout.source_for(rules.STOP_ALL))
        self.assertEqual(people.escalate_waiting(NOW), 0)
        LeadAiChatState.objects.filter(conversation=self.conversation).update(not_interested_at=NOW - dt.timedelta(minutes=5))
        from apps.leadai.models import LeadAiOptOut

        LeadAiOptOut.objects.all().delete()
        self.assertEqual(people.escalate_waiting(NOW), 0)
        LeadAiChatState.objects.filter(conversation=self.conversation).update(not_interested_at=None)
        self.assertEqual(people.escalate_waiting(NOW), 1)  # the same chat, nothing against it


# D. Who the customer is -------------------------------------------------------------------------------------------------


class NeedDetectionTests(SimpleTestCase):
    # A shop customer's own words the review found read as a home, a sale or "no shop" (regressions-F2).
    SHOP_CUSTOMERS = (
        "I need a shop with a room for my salon", "Is it residential or commercial?", "I want a shop with staff accommodation",
        "kya shop me kamra hai?", "I want shop for studio", "Villa maintenance", "mujhe dukan kiraye pe chahiye, flat nahi",
        "I want to sell home appliances", "mujhe shop chahiye, flat nahi", "मुझे फ्लैट नहीं, दुकान चाहिए", "مجھے فلیٹ نہیں، دکان چاہیے",
        "أبحث عن محل، لا أريد شقة", "أريد محل مع غرفة", "هل المحل تحت الشقق؟", "shop ke saath kamra bhi chahiye",
        "apartment cleaning services", "we rent out flats, need a shop for office", "No, I want a SHOP for my salon. What sizes do you have?",
    )

    def test_a_shop_customers_words_are_no_want(self):
        for text in self.SHOP_CUSTOMERS:
            with self.subTest(text=text):
                self.assertIsNone(needs.detect([text]))
        # A burst: "I need a shop" then "with a room for my salon" is a shop customer's.
        self.assertIsNone(needs.detect(["I need a shop", "with a room for my salon"]))

    def test_the_wants_still_read(self):
        for text, kind in {
            "I need a studio near the shops": needs.HOME, "no sir am looking for studio only not shop": needs.HOME,
            "I need flat not shop": needs.HOME, "mujhe flat chahiye shop nahi": needs.HOME, "I need staff accommodation": needs.HOME,
            "I did not say any thing about shop.i just requesting only apartment rent.Manhial told me already": needs.HOME,
            "I want to buy a shop": needs.BUY, "I want to sell my villa": needs.SELL, "No shop": needs.NEVER_ASKED,
        }.items():
            with self.subTest(text=text):
                self.assertEqual(getattr(needs.detect([text]), "kind", None), kind)
        # Their trade is a business activity, never a home (crm_facts.is_business reads the same detector).
        for activity in ("Villa maintenance", "apartment cleaning services"):
            self.assertTrue(crm_facts.is_business(activity))

    def test_a_shop_asked_for_in_so_many_words(self):
        for text in ("No, I want a SHOP for my salon. What sizes do you have?", "Send me the shop types please", "shop chahiye", "أريد محل"):
            with self.subTest(text=text):
                self.assertTrue(needs.wants_a_shop([text]))
        for text in ("I don't want a shop on the main road", "shop nahi chahiye", "I need a studio", "No shop"):
            with self.subTest(text=text):
                self.assertFalse(needs.wants_a_shop([text]))

    def test_how_specific_a_want_is(self):
        studio = needs.Need(needs.HOME, "studio")
        self.assertFalse(needs.replaces(needs.Need(needs.NEVER_ASKED, "", True), studio))  # chat 68's "Not shops"
        self.assertFalse(needs.replaces(needs.Need(needs.HOME, "home"), studio))
        self.assertFalse(needs.replaces(needs.Need(needs.HOME, ""), studio))
        self.assertTrue(needs.replaces(needs.Need(needs.HOME, "bhk:1"), studio))
        self.assertTrue(needs.replaces(needs.Need(needs.BUY, "shop"), studio))
        self.assertTrue(needs.replaces(studio, needs.Need(needs.NEVER_ASKED, "", True)))  # chat 114: "I did not ask shop." then an apartment

    def test_a_buyer_hears_no_word_of_renting(self):
        buyer = needs.Need(needs.BUY, "shop")
        live = "Thanks for clarifying. Are you interested in renting a shop instead, or do you know someone who is?"  # chat 42
        self.assertEqual(needs.drop_shop_pitch(live, buyer), ("Thanks for clarifying.", True))
        self.assertEqual(needs.drop_shop_pitch("We have Type 1 shops for rent from AED 33,000 a year. Would you like to rent one instead?", buyer)[0], "")
        # A seller may hear of renting out their own property.
        seller = needs.Need(needs.SELL, "shop")
        self.assertEqual(needs.drop_shop_pitch("Our agent can help you rent out your shop.", seller), ("Our agent can help you rent out your shop.", False))
        # A home: no business or licence question (chat 68).
        self.assertEqual(needs.drop_shop_pitch("I see, a studio. Is the studio for a business activity?", needs.Need(needs.HOME, "studio"))[0], "I see, a studio.")
        self.assertTrue(needs.only_filler("I see, a studio."))
        self.assertTrue(needs.only_filler("Sorry for the confusion."))
        self.assertFalse(needs.only_filler("Sorry, which area?"))


class NeedTurnTests(ReviewBase):
    def test_a_shop_with_a_room_for_a_salon_gets_no_owners_line(self):  # regressions-F2
        message = self.inbound("I need a shop with a room for my salon")
        live = shop_answer("A salon, got it. Is the shop for yourself, or are you checking for a client?", facts={"business_activity": "salon", "property_type": "shop"})
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), "A salon, got it. Is the shop for yourself, or are you checking for a client?")
        self.assertNotIn("need", self.state().facts)
        self.assertEqual(self.state().facts["business_activity"], "salon")
        self.assertFalse(LeadAiAlert.objects.filter(kind="wanted").exists())

    def test_a_later_request_for_a_shop_forgets_a_want_read_wrong(self):  # regressions-F2, the lock-in
        self.set_state(facts={"need": "home", "wanted": "a room", "property_type": "room", "for_client": False}, invites=1)
        self.ours(line("We have many options for a room across Dubai."), minutes_ago=5)
        message = self.inbound("No, I want a SHOP for my salon. What sizes do you have?")
        live = shop_answer(
            "Sorry for the confusion! For a salon, Type 1 (400-550 sq ft, from AED 33,000 a year) works well. Which size suits your salon?",
            facts={"business_activity": "salon", "property_type": "shop"},
        )
        outcome, _, _, _ = self.turn(message, [live])
        self.assertIn("Type 1", self.body(outcome))  # live, the sizes were cut as shop talk to a "room" customer
        facts = self.state().facts
        self.assertNotIn("need", facts)
        self.assertNotIn("wanted", facts)
        self.assertEqual((facts["property_type"], facts["business_activity"]), ("shop", "salon"))
        self.assertEqual(self.actions(message)["forgot"], ["need", "wanted"])
        # And the shop types are hers again.
        self.later(2)
        outcome, _, _, _ = self.turn(self.inbound("Send me the shop types please", seconds_ago=10), [shop_answer("Sure! Here are our shop types.")])
        self.assertEqual(self.sent_lists.call_count, 1)

    def test_a_call_in_their_own_words_beats_the_owners_line(self):  # regressions-F5
        message = self.inbound("I need a studio flat, please call me")
        outcome, _, _, note_delay = self.turn(message, [shop_answer("Sure! What area do you prefer?", segment="residential_tenant")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_ASK, "en", shops=True))
        state = self.state()
        self.assertEqual(state.handover_reason, "call_requested")
        self.assertEqual(state.facts["need"], "home")  # the want is recorded and alerted all the same
        self.assertTrue(LeadAiAlert.objects.filter(kind="wanted").exists())
        self.assertTrue(LeadAiAlert.objects.filter(kind="handover").exists())
        self.assertIn("call", [call.args[1] for call in note_delay.call_args_list])

    def test_a_call_with_its_time_beats_the_owners_line_and_its_time_is_passed_on(self):  # regressions-F5
        message = self.inbound("I am looking for a studio, call me at 5 pm")
        outcome, _, _, _ = self.turn(message, [shop_answer("Sure! Shall I hold a slot for you at our office today?", segment="residential_tenant")])
        self.assertEqual(self.body(outcome), people.line(people.CALL_PASSED, "en", shops=True))  # live: the office invitation
        alert = self.alerts_of("handover")[0]
        self.assertIn("Call asked for: the time in their words below", alert.text)
        self.assertIn("Their words: I am looking for a studio, call me at 5 pm", alert.text)

    def test_chat_68_not_shops_keeps_the_studio_and_asks_no_business(self):  # replay-want-downgraded
        self.inbound("Actually i was looking for a studio", seconds_ago=40)
        first = self.inbound("Actually i was looking for a studio", seconds_ago=33)
        self.turn(first, [shop_answer("I see. Is the studio for a business?", facts={"for_client": False, "property_type": "studio", "business_activity": "studio"})])
        self.assertEqual(self.state().facts["wanted"], "a studio")
        alerts = LeadAiAlert.objects.filter(kind="wanted").count()
        self.later(1)
        message = self.inbound("Not shops", seconds_ago=10)
        live = shop_answer("I see, a studio. Our shops are for retail or commercial use, not residential studios. Is the studio for a business activity?")
        outcome, _, _, _ = self.turn(message, [live])
        facts = self.state().facts
        self.assertEqual((facts["need"], facts["wanted"], facts["property_type"]), ("home", "a studio", "studio"))
        self.assertEqual(LeadAiAlert.objects.filter(kind="wanted").count(), alerts)  # no second "wanted" alert
        body = self.body(outcome)
        self.assertNotIn("business", body)
        # What was left was "I see, a studio.": the owner's line again, with no new slots (invited already).
        self.assertEqual(body, line("We have many options for a studio across Dubai.", sorry=True, slots=""))
        self.assertEqual(self.state().invites, 1)

    def test_chat_114_an_apology_alone_becomes_the_owners_line(self):  # replay-bare-apology-left
        self.set_state(facts={"need": "never_asked", "wanted": "no shop (never asked about one)"}, invites=1)
        first = line("We have many other options across Dubai too, not only shops.", sorry=True)
        self.ours(f"{first}\nOur office location: {MAPS}", minutes_ago=4)
        message = self.inbound("I did not say any thing about shop.i just requesting only apartment rent.Manhial told me already")
        live = shop_answer(
            "Sorry for the confusion. We handle shops for rent in International City. For apartments, please contact Manhial as you mentioned.",
            segment="residential_tenant",
        )
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual(self.body(outcome), line("We have many options for an apartment across Dubai.", sorry=True, slots=""))
        self.assertEqual(self.state().facts["wanted"], "an apartment")

    def test_chat_42_a_buyer_hears_no_rent_pitch_and_no_third_invitation(self):  # replay-buyer-gets-rent-pitch
        self.turn(self.inbound("To buy"), [shop_answer("You mentioned buying a shop.", facts={"intent": "buy", "property_type": "shop"})])
        self.assertEqual(self.state().invites, 1)
        self.later(5)
        self.inbound("You are not getting I feel\n\nI want purchase shop\nNot to rent", seconds_ago=20)
        message = self.inbound("Do u understand now", seconds_ago=10)
        live = shop_answer(
            "Thanks for clarifying. Currently, we only have shops available for rent, not for sale. Are you interested in renting a shop "
            "instead, or do you know someone who is?",
            facts={"intent": "buy"},
        )
        outcome, _, _, _ = self.turn(message, [live])
        body = self.body(outcome)
        self.assertNotRegex(body, r"\brent")
        self.assertTrue(body.startswith(SORRY), body)
        # Three more restated wants the model reads as "not interested": the line at most twice with slots, then none.
        invites = []
        for minutes_on in (10, 15, 20):
            self.later(minutes_on)
            out, _, _, _ = self.turn(
                self.inbound("Sorry nobody\nI want to purchase shop", seconds_ago=5),
                [shop_answer("No problem, thank you for letting us know.", opt_out="not_interested")],
            )
            invites.append(self.state().invites)
            self.assertIsNone(self.state().not_interested_at)
        self.assertEqual(invites, [2, 2, 2])  # live: 2, 3, 4
        self.assertNotIn("which is better", self.body(out))

    def test_a_buyers_visa_question_is_no_handover(self):  # crm-F2
        message = self.inbound("I want to buy a shop here. Will I get a golden visa with it?")
        outcome, _, _, _ = self.turn(message, [shop_answer("Thanks! Our agent will reply here.", handover="legal_visa_licence_contract", facts={"intent": "buy"})])
        self.assertIsNone(self.state().handed_over_at)
        self.assertEqual(self.body(outcome), f"{line('We have many options to buy a shop across Dubai.')}\nOur office location: {MAPS}")
        alert = self.alerts_of("wanted")[0]
        self.assertIn("They also asked about legal, visa, licence or contract matters", alert.text)
        self.assertEqual(self.actions(message)["need_dropped"], "legal_visa_licence_contract")

    def test_a_known_sellers_photo_is_no_handover_and_the_team_hears_of_it(self):  # crm-F2
        self.set_state(facts={"need": "sell", "wanted": "to sell or let their shop", "intent": "sell"}, invites=1)
        self.ours(line("We help owners sell and rent out their property across Dubai."), minutes_ago=5)
        message = self.inbound("Here is my shop", kind=Message.Kind.IMAGE)
        self.turn(message, [shop_answer("Thanks! Our agent will reply here.", handover="media_received")])
        self.assertIsNone(self.state().handed_over_at)
        alert = self.alerts_of("wanted")[-1]
        self.assertIn("They also sent a photo, document, contact or location", alert.text)

    def test_a_request_for_a_person_still_hands_them_over(self):
        self.set_state(facts={"need": "home", "wanted": "a studio"})
        self.turn(self.inbound("I need a studio, I want to talk to a person"), [shop_answer("Sure.", handover="customer_asked_human")])
        self.assertEqual(self.state().handover_reason, "customer_asked_human")


class NeverLostTests(ReviewBase):
    def test_a_buyer_only_the_model_recorded_is_never_lost(self):  # crm-F3
        self.assertIsNone(needs.detect(["What is the selling price?"]))
        self.set_state(facts={"intent": "buy", "property_type": "shop", "customer_name": "Ahmed"})
        with self.captureOnCommitCallbacks(execute=False):
            engine.record_opt_out(self.conversation, rules.NOT_INTERESTED, by="rule", words="Not interested", playbook=lane.IC_SHOPS)
        self.assertEqual(self.fields(), [])
        self.assertFalse(LeadAiAlert.objects.filter(kind="lost").exists())
        # A shop customer's no is Lost, as before.
        self.set_state(facts={"intent": "rent", "property_type": "shop"}, not_interested_at=None)
        with self.captureOnCommitCallbacks(execute=False):
            engine.record_opt_out(self.conversation, rules.NOT_INTERESTED, by="rule", words="Not interested", playbook=lane.IC_SHOPS)
        self.assertIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_LOST)), self.fields())


# E. A count is no window -----------------------------------------------------------------------------------------------


class CountIsNoWindowTests(ReviewBase):
    COUNTS = (
        "today I will come, 3 or 4 of us", "aaj aaunga, 2 ya 3 dukaan chahiye", "I will come today with 2 or 3 friends",
        "I'll come today, 2-3 of us", "I will come today, need 1 or 2 dukan", "I will come today, 2 ya 3 log",
        "main aaj aaunga, 2-3 dost saath honge", "سأأتي اليوم، نحن 3 أو 4 أشخاص", "I will come 5 or 6",
    )

    def test_counts_are_no_window(self):
        for said in self.COUNTS:
            with self.subTest(said):
                self.assertIsNone(hours.named_window(said))
        for said, window in (
            ("I will come at 5 or 6", (dt.time(17), dt.time(18))), ("I will come at 12-12:30", (dt.time(12), dt.time(12, 30))),
            ("5 ya 6 baje aaunga", (dt.time(17), dt.time(18))),
        ):
            with self.subTest(said):
                self.assertEqual(hours.named_window(said), window)

    def test_a_count_books_nothing(self):
        self.set_state(facts={"for_client": False, "property_type": "shop", "business_activity": "mobile shop", "size_sqft": 400, "trade_licence": "yes"})
        message = self.inbound("today I will come, 3 or 4 of us")
        live = shop_answer(
            "Great, all of you are welcome. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", invited=True,
            action="tentative", place="office", date="2026-10-12",
        )
        outcome, _, _, _ = self.turn(message, [live])
        self.assertNotIn("confirmed", self.body(outcome))  # live: "Your viewing is confirmed ✅ ... Time: 3:00 PM"
        self.assertFalse(engine.LeadAiAppointment.objects.filter(status="confirmed").exists())


# F. Rented, and a second shop ------------------------------------------------------------------------------------------


class RentedTests(ReviewBase):
    def test_need_one_more_or_a_price_weighed_is_no_shop_rented_elsewhere(self):
        for text in ("We already have a shop, need one more", "we found a shop in Deira at 30k is yours cheaper", "I found one at 30k"):
            with self.subTest(text=text):
                self.assertFalse(needs.rented_already([text]))
        for text in ("we got one", "Thank you but I already rented a shop last month", "found one already"):
            with self.subTest(text=text):
                self.assertTrue(needs.rented_already([text]))

    def test_what_is_no_no_to_a_second_shop(self):
        for text in (
            "No, I told you I need another one", "No we did not take it, I am asking your best rent", "no not rented yet",
            "I'm ok with one more if the price is good", "We are good to take another one", "All good, send me the list",
            "I am fine with a bigger one", "No, the one we got is small, we need another",
        ):
            with self.subTest(text=text):
                self.assertFalse(engine.second_shop_no(text))
        for text in ("No", "no thanks", "Not interested", "if anything will let you know", "will definitely reach out if we need anything in the future", "We are good, thank you"):
            with self.subTest(text=text):
                self.assertTrue(engine.second_shop_no(text))

    def test_need_one_more_is_a_shop_lead_never_the_second_shop_question(self):
        message = self.inbound("We already have a shop, need one more")
        outcome, _, _, _ = self.turn(message, [shop_answer("Great, one more shop. What business will it be for?", facts={"for_client": False})])
        self.assertNotEqual(self.body(outcome), rules.line("rented_second_shop", "en"))  # live: "Congratulations on your new shop!"
        self.assertEqual(self.sent_lists.call_count, 1)  # a known end user who wants a shop gets the shop types
        self.assertNotIn("already_rented", self.state().facts)
        self.assertNotIn("rented_asked", self.actions(message))

    def test_a_no_with_a_want_after_the_second_shop_question_is_the_models(self):
        self.inbound("we got one", seconds_ago=60)
        first = self.inbound("thank you", seconds_ago=50)
        self.turn(first, [shop_answer("Great!", facts={"for_client": False, "already_rented": True})])
        self.later(2)
        outcome, calls, _, _ = self.turn(self.inbound("No, I told you I need another one", seconds_ago=10), [shop_answer("Sorry! What size do you need?")])
        self.assertEqual(len(calls), 1)  # live: closed as Lost "already rented" by code, no model
        self.assertIsNone(self.state().not_interested_at)
        self.assertFalse(LeadAiCrmField.objects.filter(field=crm_fields.LOST).exists())


# G. Calls and contracts ------------------------------------------------------------------------------------------------


class CallWordsTests(SimpleTestCase):
    def test_no_call_request(self):
        for text in (
            "Who is this? Why did you call me?", "I'm driving, I'll call back later", "Did you call me?", "Someone tried to call me from this number",
            "who is this, you call me yesterday", "you can call me Ahmed", "I will call back in 5 min", "I'll phone back in 10 minutes",
            "I will ring back", "I don't want a call",
        ):
            with self.subTest(text=text):
                self.assertFalse(people.asks_for_call(text))

    def test_a_call_request(self):
        for text in (
            "Please call me", "call me at 5", "Can you call me?", "ok call me", "Call me back please", "pls call back",
            "I need a studio flat, please call me", "We can have a call at 11.30 - 12 PM", "give me a call", "call kar lo",
            "I am looking for a studio, call me at 5 pm", "I am driving now call me later", "I need you to call me",
        ):
            with self.subTest(text=text):
                self.assertTrue(people.asks_for_call(text))

    def test_a_contract_to_sign_is_no_contract_question(self):
        for text in ("I want to sign the contract today, when can I come?", "Can I do the contract this week?"):
            with self.subTest(text=text):
                self.assertEqual(people.must_answer([text]), [])
        for text in ("how long is the contract?", "Is the contract yearly?", "Can I sign the contract for 2 years?", "Can you send me the contract copy?"):
            with self.subTest(text=text):
                self.assertEqual(people.must_answer([text]), ["contract"])


class GeneralCallTurnTests(GeneralBase):
    def test_why_did_you_call_me_gets_the_models_answer(self):  # regressions-F4
        message = self.inbound("Who is this? Why did you call me?")
        reply = "This is A7 Real Estate: we sent you a message about properties in Dubai. Are you looking to rent, buy or sell?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, segment="other")])
        self.assertEqual(self.body(outcome), reply)
        self.assertIsNone(self.state().handed_over_at)


class ContractTurnTests(ReviewBase):
    def test_ready_to_sign_gets_the_slots_not_a_handover(self):  # regressions-F6
        self.set_state(facts={"for_client": False, "property_type": "shop", "business_activity": "mobile shop", "size_sqft": 400, "trade_licence": "yes"})
        message = self.inbound("I want to sign the contract today, when can I come?")
        outcome, _, _, _ = self.turn(message, [shop_answer(f"Great! {TWO_SLOTS_NOW}", invited=True)])
        self.assertEqual(self.body(outcome), f"Great! {TWO_SLOTS_NOW}")
        self.assertIsNone(self.state().handed_over_at)
        self.assertFalse(LeadAiAlert.objects.filter(kind__in=("handover", people.QUESTIONS)).exists())


# H. The CRM ------------------------------------------------------------------------------------------------------------


CALL_OF_2302 = {
    "ID": "180001", "SUBJECT": "3CX outbound call", "COMPLETED": "Y", "TYPE_ID": "2", "PROVIDER_ID": "VOXIMPLANT_CALL", "RESPONSIBLE_ID": "2302",
    "AUTHOR_ID": "1", "EDITOR_ID": "1", "CREATED": (NOW - dt.timedelta(days=2)).isoformat(), "LAST_UPDATED": (NOW - dt.timedelta(days=2)).isoformat(),
}


@override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
class LostBlindSpotsTests(CrmWritesBase):
    def test_a_call_recorded_through_user_1_is_a_persons_work(self):  # crm-F4
        self.assertEqual(lost.judge_activities([CALL_OF_2302], NOW, lost.system_users()), "Bitrix user 2302 had a call with the customer on 10 Oct (3CX outbound call)")
        old = {**CALL_OF_2302, "CREATED": (NOW - dt.timedelta(days=9)).isoformat(), "LAST_UPDATED": (NOW - dt.timedelta(days=9)).isoformat()}
        self.assertEqual(lost.judge_activities([old], NOW, lost.system_users()), "")
        robot = {**CALL_OF_2302, "TYPE_ID": "6", "PROVIDER_ID": "CRM_TODO"}
        self.assertEqual(lost.judge_activities([robot], NOW, lost.system_users()), "")
        with patch("apps.crmlink.client.call", side_effect=FakeBitrix()):
            self.assertTrue(lost.may_move(555, "971501234567", now=NOW, lead=dict(IDLE_LEAD)).move)
        with patch("apps.crmlink.client.call", side_effect=FakeBitrix(activities=[CALL_OF_2302])):
            decision = lost.may_move(555, "971501234567", now=NOW, lead=dict(IDLE_LEAD))
        self.assertEqual((decision.move, decision.why), (False, "Bitrix user 2302 had a call with the customer on 10 Oct (3CX outbound call)"))

    def test_a_persons_edit_our_own_write_hid_is_remembered(self):  # crm-F4
        # Oct 10: agent 2302 edited the lead; our Qualifying write read it so before it wrote (and hid it: user 1).
        edited = {**IDLE_LEAD, "MODIFY_BY_ID": "2302", "DATE_MODIFY": (NOW - dt.timedelta(days=2)).isoformat()}
        ids = self.queue([(crm_fields.FIELD_BOT_STATUS, crm_fields.STATUS_QUALIFYING, {})])
        self.write(ids, FakeBitrix(lead=edited))
        self.assertEqual(self.row(crm_fields.FIELD_BOT_STATUS).payload[lost.PERSON_TOUCH]["by"], "2302")
        # Oct 12: the customer says no; the lead now shows our own write last.
        ids = self.queue(crm_fields.opt_out_writes(rules.NOT_INTERESTED, "No"))
        posted, _ = self.write(ids, FakeBitrix(lead=dict(IDLE_LEAD)))
        self.assertNotIn("lost", posted[-1])
        self.assertIn("Bitrix user 2302 changed it on 10 Oct", self.row(crm_fields.LOST).error)

    def test_a_retry_after_a_move_bitrix_applied_writes_no_false_record(self):  # crm-F8
        ids = self.queue(crm_fields.opt_out_writes(rules.NOT_INTERESTED, "No"))
        LeadAiCrmField.objects.filter(pk__in=ids).update(attempts=1)  # posted once; the answer was lost on the way back
        moved = {**IDLE_LEAD, "STATUS_ID": "1", "STATUS_SEMANTIC_ID": "F", crm_fields.FIELD_BOT_STATUS: "2480"}
        posted, _ = self.write(ids, FakeBitrix(lead=moved))
        self.assertEqual(posted, [])  # no "it was not moved" comment
        self.assertEqual((self.row(crm_fields.LOST).error, self.row(crm_fields.FIELD_BOT_STATUS).error), ("", ""))
        self.assertIsNotNone(self.row(crm_fields.LOST).sent_at)

    def test_a_kept_comment_goes_once(self):  # crm-F8
        ids = self.queue(crm_fields.opt_out_writes(rules.NOT_INTERESTED, "No"))
        busy = FakeBitrix(open_activities=[{"ID": "1", "SUBJECT": "Follow up", "COMPLETED": "N", "RESPONSIBLE_ID": "2298"}])
        with patch("apps.leadai.assistant.crm_fields.post", side_effect=crm_fields.FieldsError("read timeout")), patch(
            "apps.crmlink.client.call", side_effect=busy
        ):
            tasks.write_crm_fields.apply(args=[ids])
        self.assertIsNotNone(self.row(crm_fields.LOST).payload.get(lost.KEPT_COMMENT))
        posted, _ = self.write(ids, busy)
        self.assertNotIn("comment", posted[-1] if posted else {})
        self.assertTrue(self.row(crm_fields.LOST).error.startswith(lost.NOT_MOVED))


@override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
class NotesGoToTheShopsLeadTests(ShopsBase):
    def test_wanted_and_call_notes_go_to_the_shops_campaigns_lead(self):  # crm-F7
        LeadAiChat.objects.filter(pk=self.chat.pk).update(crm_entity="deal", crm_id=900)
        self.assertEqual(crm_fields.lead_of(LeadAiChat.objects.get(pk=self.chat.pk), self.conversation), 555)
        with patch("apps.crmlink.client.add_comment") as comment:
            tasks.record_crm_note(self.conversation.pk, "wanted", ["Wants: a studio"])
        self.assertEqual(comment.call_args.args[:2], ("lead", 555))  # live: deal 900
        with patch("apps.leadai.assistant.crm.read_record", return_value={"assigned": "2302", "stage": "", "fields": {}}) as read, patch(
            "apps.leadai.assistant.alerts.reach_responsible"
        ):
            tasks.resolve_responsible(self.conversation.pk)
        self.assertEqual(read.call_args.args, ("lead", 555))

    def test_a_chat_with_no_lead_ai_lead_keeps_its_own_record(self):
        CampaignRecipient.objects.filter(conversation=self.conversation).update(crm_lead_id=None)
        LeadAiChat.objects.filter(pk=self.chat.pk).update(crm_entity="deal", crm_id=900)
        with patch("apps.crmlink.client.add_comment") as comment:
            tasks.record_crm_note(self.conversation.pk, "not_interested")
        self.assertEqual(comment.call_args.args[:2], ("deal", 900))


# I. The follow-ups over a person's booking -----------------------------------------------------------------------------


@override_settings(BITRIX_WEBHOOK_URL="https://bitrix.test/rest/1/token/")
class FollowUpsOverAPersonTests(ShopsBase):
    def lead(self, **fields):
        row = {"ID": "555", "STATUS_ID": "IN_PROCESS", "ASSIGNED_BY_ID": "88", "MODIFY_BY_ID": "1", "DATE_MODIFY": NOW.isoformat(), **fields}
        return patch("apps.crmlink.client.call", side_effect=lambda method, payload=None: row if method == "crm.lead.get" else True)

    def test_chat_119_a_meeting_an_agent_booked_holds_the_nudges(self):  # replay-nudges-over-agent-booking
        with self.lead(STATUS_ID="10"):
            self.assertEqual(followups.bitrix_blocks(self.conversation, self.chat, {"need": "buy"}), "the Bitrix lead shows a person has it: it has a meeting (Meeting/Viewing Scheduled)")
        with self.lead(**{crm.FIELD_MEETING_AT: (NOW + dt.timedelta(hours=4)).isoformat()}):
            self.assertIn("it has a meeting time", followups.bitrix_blocks(self.conversation, self.chat, {}))
        with self.lead(**{crm.FIELD_MEETING_AT: (NOW - dt.timedelta(days=20)).isoformat()}):
            self.assertEqual(followups.bitrix_blocks(self.conversation, self.chat, {}), "")  # a meeting long past holds nothing

    def test_a_persons_work_holds_a_need_chat_only(self):
        worked = {"MODIFY_BY_ID": "2302", "DATE_MODIFY": (NOW - dt.timedelta(hours=3)).isoformat()}
        with self.lead(**worked):
            self.assertEqual(
                followups.bitrix_blocks(self.conversation, self.chat, {"need": "buy", "wanted": "to buy a shop"}),
                "the Bitrix lead shows a person has it: Bitrix user 2302 changed it on 12 Oct",
            )
            self.assertEqual(followups.bitrix_blocks(self.conversation, self.chat, {"for_client": False}), "")


# J. The smaller ones ---------------------------------------------------------------------------------------------------


class NameTests(SimpleTestCase):
    def test_short_names_in_capitals_are_names_and_initials_stay(self):  # regressions-F7
        for raw, name in (("ALI", "Ali"), ("MD ALI", "Ali"), ("ZIA", "Zia"), ("RAJ", "Raj"), ("SAM", "Sam"), ("AMY", "Amy"), ("JOY", "Joy"), ("OM", "Om")):
            with self.subTest(raw=raw):
                self.assertEqual(filters.first_name(raw), name)
        for raw in ("ETS", "SK", "ABC"):
            with self.subTest(raw=raw):
                self.assertEqual(filters.first_name(raw), raw)
        self.assertEqual(engine.name_from("ALI"), "Ali")
        self.assertEqual(filters.first_name("AHMED KHAN"), "Ahmed")


class SameTurnNoteTests(SimpleTestCase):
    def test_a_note_that_restates_the_replys_own_claim_is_ours(self):  # replay-same-turn-sale-claim-note
        answer = {
            "reply": "Thanks for clarifying. Currently, we only have shops available for rent, not for sale.",
            "facts": {"notes": ["Currently only shops for rent, not sale", "Is the parking free?"]},
        }
        earlier = [("customer", "To buy"), ("customer", "Is the parking free?")]
        crm_facts.settle(answer, earlier, ["I want purchase shop"])
        self.assertEqual(answer["facts"]["notes"], ["Is the parking free?"])


class EvalGateTests(SimpleTestCase):
    def test_the_model_written_scenarios_gate_on_their_own(self):  # regressions-F8
        from django.core.management.base import CommandError

        from apps.leadai.management.commands.leadai_eval import CODE, MODEL, Command, Run

        code = next(s for s in leadai_eval.SCENARIOS if s.words == CODE)
        model = next(s for s in leadai_eval.SCENARIOS if s.words == MODEL)
        runs = [Run(scenario=code, label=f"c{index}") for index in range(19)] + [Run(scenario=model, label="m", failures=["x"])]
        command = Command()
        command.stdout = type("Out", (), {"write": lambda self, text: None})()
        with self.assertRaises(CommandError) as raised:
            command._summary(runs, 1, 1.0, 95.0)  # 95.0% overall, 0% of the model's own
        self.assertIn("of the scenarios the model writes passed", str(raised.exception))

    def test_the_review_scenarios_pass_with_a_right_answer(self):
        ids = [s.id for s in leadai_eval.SCENARIOS if s.id.startswith(("shops-review-", "review-"))]
        self.assertEqual(len(ids), 11)
        for scenario_id in ids:
            self.assertIn(scenario_id, RIGHT)


class EvalReviewScenarioTests(SimpleTestCase):
    def run_scenario(self, scenario_id, completion):
        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion), override_settings(LEADAI_OPENAI_API_KEY="test"):
            return leadai_eval.run_once(scenario, scenario_id)

    def test_they_pass_with_the_right_answer_and_fail_without_the_fixes(self):
        never = needs.re.compile(r"$^")
        for scenario_id, broken in (
            ("shops-review-shop-with-room", [patch.object(needs, "about_a_shop", return_value=False)]),
            ("shops-review-flat-nahi", [patch.object(needs, "about_a_shop", return_value=False), patch.object(needs, "_NOUN_NEGATED_AFTER", never)]),
            ("shops-review-staff-accommodation", [patch.object(needs, "about_a_shop", return_value=False)]),
            ("shops-review-studio-call-me", [patch.object(people, "asks_for_call", return_value=False)]),
            # "need one more" is read twice over now: as a want of one more, and as "one more" alone (the gate's review).
            ("shops-review-rented-one-more", [patch.object(needs, "_WANTS_MORE", never), patch.object(needs, "_ONE_MORE_ALONE", never)]),
            ("shops-review-buyer-no-rent-42", [patch.object(needs, "_RENT_TALK", never)]),
            ("shops-review-studio-not-shops-68", [patch.object(needs, "replaces", return_value=True)]),
        ):
            with self.subTest(scenario_id):
                self.assertEqual(self.run_scenario(scenario_id, RIGHT[scenario_id]).failures, [])
                with contextlib.ExitStack() as stack:
                    for patcher in broken:
                        stack.enter_context(patcher)
                    self.assertNotEqual(self.run_scenario(scenario_id, RIGHT[scenario_id]).failures, [])


class UntestedGuardsTests(ReviewBase):
    def test_a_first_answer_in_capitals_gets_its_apology(self):  # regressions-F9: needs.misread
        self.assertTrue(needs.misread(["I NEED A STUDIO FLAT"]))
        outcome, _, _, _ = self.turn(self.inbound("I NEED A STUDIO FLAT"), [shop_answer("Sure.", segment="residential_tenant")])
        self.assertTrue(self.body(outcome).startswith(SORRY), self.body(outcome))

    def test_asap_keeps_a_slot_half_an_hour_ahead(self):  # regressions-F9: engine._COME_NOW
        answer = {
            **eval_answer("Sure! I can hold a slot for you today at 2:30 PM or 3:30 PM — which is better?", invited=True).data,
            "facts": {key: None for key in engine.schema.SHOPS_FACT_KEYS} | {"notes": []},
        }
        answer = engine.schema.normalize(answer, shops=True)
        engine.settle(answer, [], ["I want to come asap"], 0, playbook=lane.IC_SHOPS, now=NOW)
        self.assertIn("2:30 PM", answer["reply"])
        answer = engine.schema.normalize(
            {**eval_answer("Sure! I can hold a slot for you today at 2:30 PM or 3:30 PM — which is better?", invited=True).data}, shops=True
        )
        engine.settle(answer, [], ["I want to come today"], 0, playbook=lane.IC_SHOPS, now=NOW)
        self.assertNotIn("2:30 PM", answer["reply"])  # without "asap", too soon: offers.fix_times
