"""Round 27 (Matloob 2026-10-24, chats 54325 / lead 74029 and 54240 / lead 73625):

- a chat the assistant stopped takes itself up again when the customer writes after the stop, so nobody has to press
  Resume (engine.resume_reason): after an automatic-reply stop any tap, voice note or file, or a text that is no
  automatic reply; after the customer's own STOP a message of theirs at least RESUME_AFTER_STOP later that is no
  acknowledgement, never after "delete my data"; never after a wrong number or spam; an agent's Pause never lifts;
- "Yes I have ma shops", answering "Is the shop for yourself, or are you checking for a client?", tagged other_need, stays
  on the shop track (tracks.decide), so the shop types list goes, never the "many other options across Dubai, not only
  shops" line.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

import datetime as dt

from apps.leadai import ic_templates
from apps.leadai.assistant import engine, tracks
from apps.leadai.models import LeadAiChatState, LeadAiOptOut, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_shops_playbook import ShopsBase, shop_answer

PERSON = "I need a shop for my salon, what sizes do you have?"
GREETING = "Thank you for contacting us! We are unavailable right now, but will respond as soon as possible."


class ResumeTests(ShopsBase):
    def stop(self, reason, minutes_ago=120):
        self.set_state(stopped_at=NOW - dt.timedelta(minutes=minutes_ago), stop_reason=reason)

    def state_now(self):
        return LeadAiChatState.objects.get(conversation=self.conversation)

    # The automatic-reply stop ------------------------------------------------------------------------------------

    def test_a_person_writing_after_an_automatic_reply_takes_the_chat_up_again(self):
        self.stop("auto_reply")
        outcome, calls, _, _ = self.turn(self.inbound(PERSON), [shop_answer("Great. What business will the shop be for?")])
        self.assertEqual(outcome.status, LeadAiTurn.Status.REPLIED, outcome.reason)
        self.assertEqual(len(calls), 1)
        state = self.state_now()
        self.assertEqual((state.stopped_at, state.stop_reason), (None, ""))

    def test_a_tap_after_an_automatic_reply_takes_the_chat_up_again(self):
        self.stop("auto_reply")
        outcome, _, _, _ = self.turn(self.tap("Yes, still looking"), [shop_answer()])
        self.assertNotEqual(outcome.reason, "stopped: auto_reply")
        self.assertIsNone(self.state_now().stopped_at)

    def test_another_automatic_reply_keeps_it_stopped(self):
        self.stop("auto_reply", minutes_ago=1)
        self.ours("Hi, are you still looking for a shop?", minutes_ago=0.6)  # their greeting comes back seconds after ours
        outcome, calls, _, _ = self.turn(self.inbound(GREETING, seconds_ago=30), [shop_answer()])
        self.assertEqual(calls, [])
        self.assertIsNotNone(self.state_now().stopped_at)
        self.assertIn(outcome.reason, ("stopped: auto_reply", "automatic reply on the customer's side"))

    # The customer's own STOP -------------------------------------------------------------------------------------

    def test_a_message_well_after_their_stop_takes_the_chat_up_again(self):
        self.stop("stop_all", minutes_ago=60)
        LeadAiOptOut.objects.create(phone=self.conversation.contact.wa_id, reason="Stop messages", source="leadai_stop", conversation=self.conversation)
        outcome, calls, _, _ = self.turn(self.inbound("Salam, I am looking for a shop now"), [shop_answer("Wa alaikum salam. What business will the shop be for?")])
        self.assertEqual(outcome.status, LeadAiTurn.Status.REPLIED, outcome.reason)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(self.state_now().stopped_at)
        # Only this chat answers them again: the registry still keeps every campaign away, as the panel's Resume does.
        self.assertTrue(LeadAiOptOut.objects.filter(phone=self.conversation.contact.wa_id).exists())

    def own_stop(self, reason="Stop messages", source="leadai_stop"):
        LeadAiOptOut.objects.create(phone=self.conversation.contact.wa_id, reason=reason, source=source, conversation=self.conversation)

    def test_a_tap_on_a_templates_stop_is_their_own_too(self):
        self.stop("stop_all", minutes_ago=60)
        self.own_stop(source="inbox_tap")
        outcome, _, _, _ = self.turn(self.inbound("Hi, any shops in China cluster?"), [shop_answer()])
        self.assertEqual(outcome.status, LeadAiTurn.Status.REPLIED, outcome.reason)
        self.assertIsNone(self.state_now().stopped_at)

    def test_a_persons_opted_out_in_bitrix_never_lifts(self):
        self.stop("stop_all", minutes_ago=60)
        self.own_stop(reason="Set in Bitrix on lead 555", source="bitrix")
        outcome, calls, _, _ = self.turn(self.inbound("Hello, do you have shops?"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))

    def test_a_stop_with_no_registry_row_never_lifts(self):
        self.stop("stop_all", minutes_ago=60)
        outcome, calls, _, _ = self.turn(self.inbound("Hello, do you have shops?"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))

    def test_a_message_right_after_their_stop_keeps_it(self):
        self.own_stop()
        self.stop("stop_all", minutes_ago=5)
        outcome, calls, _, _ = self.turn(self.inbound("Salam"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))
        self.assertIsNotNone(self.state_now().stopped_at)

    def test_an_acknowledgement_after_their_stop_keeps_it(self):
        self.own_stop()
        self.stop("stop_all", minutes_ago=60)
        outcome, calls, _, _ = self.turn(self.inbound("ok thanks"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))

    def test_after_delete_my_data_it_never_lifts(self):
        self.stop("stop_all", minutes_ago=60)
        self.own_stop(reason="asked to delete their data")
        outcome, calls, _, _ = self.turn(self.inbound("Hello, do you have shops?"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))

    def test_a_wrong_number_or_spam_never_lifts_by_itself(self):
        for reason in ("wrong_number", "spam"):
            with self.subTest(reason):
                self.stop(reason, minutes_ago=60)
                message = self.inbound("Hello, do you have shops?")
                outcome, calls, _, _ = self.turn(message, [shop_answer()])
                self.assertEqual((calls, outcome.reason), ([], f"stopped: {reason}"))
                self.assertIsNotNone(self.state_now().stopped_at)

    def test_an_agents_pause_never_lifts_by_itself(self):
        self.set_state(paused_at=NOW - dt.timedelta(hours=2), paused_by=self.agent)
        outcome, calls, _, _ = self.turn(self.inbound(PERSON), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "paused by an agent"))

    def test_the_rule_itself(self):
        state = LeadAiChatState.for_conversation(self.conversation)
        self.assertEqual(engine.resume_reason(self.conversation, state, []), "")  # not stopped
        state.stopped_at, state.stop_reason = NOW - dt.timedelta(hours=1), "stop_all"
        self.own_stop()
        before = self.inbound("old words", seconds_ago=7200)
        self.assertEqual(engine.resume_reason(self.conversation, state, [before]), "")  # nothing said after the stop
        self.assertTrue(engine.resume_reason(self.conversation, state, [self.inbound("I want a shop")]))


class ReviewTests(ResumeTests):
    """The round-27 review's findings."""

    def test_a_typed_stop_in_a_chat_stopped_for_an_automatic_reply_is_their_stop(self):
        self.stop("auto_reply")
        outcome, calls, _, _ = self.turn(self.inbound("Stop"), [shop_answer()])
        self.assertEqual(calls, [])
        state = self.state_now()
        self.assertEqual(state.stop_reason, "stop_all")  # a person's STOP takes the automatic reply's place
        self.assertTrue(LeadAiOptOut.objects.filter(phone=self.conversation.contact.wa_id).exists())
        self.assertTrue(self.body(outcome))  # the confirmation goes to the person who typed it

    def test_words_asking_to_stop_never_lift_a_stop(self):
        for reason, minutes in (("auto_reply", 120), ("stop_all", 60)):
            for words in ("STOP STOP STOP", "I said stop", "Stop it now", "please stop messaging me"):
                with self.subTest(reason=reason, words=words):
                    state = LeadAiChatState.for_conversation(self.conversation)
                    state.stopped_at, state.stop_reason = NOW - dt.timedelta(minutes=minutes), reason
                    self.own_stop() if not LeadAiOptOut.objects.filter(phone=self.conversation.contact.wa_id).exists() else None
                    item = self.inbound(words)
                    self.assertEqual(engine.resume_reason(self.conversation, state, [item]), "", words)

    def test_a_lone_stop_or_block_in_other_words_lifts_an_automatic_reply_stop(self):
        self.stop("auto_reply")
        state = LeadAiChatState.for_conversation(self.conversation)
        for words in ("Which block is the shop in?", "Can I stop by tomorrow to see it?"):
            with self.subTest(words):
                self.assertTrue(engine.resume_reason(self.conversation, state, [self.inbound(words)]), words)

    def test_delete_my_data_from_the_chats_own_record(self):
        self.stop("stop_all", minutes_ago=60)
        self.own_stop()  # the registry's first reason is the tap's, not the deletion
        LeadAiTurn.objects.create(conversation=self.conversation, inbound=self.inbound("Please delete my data", seconds_ago=3000), status="replied", actions={"deletion": True})
        self.ours("Your request is noted.", minutes_ago=40)  # a reply between: the new burst holds only their new words
        outcome, calls, _, _ = self.turn(self.inbound("When will it be deleted?"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))

    def test_remove_my_number_said_in_the_chat_never_lifts(self):
        self.stop("stop_all", minutes_ago=60)
        self.own_stop()
        self.inbound("remove my number from your list", seconds_ago=3000)
        self.ours("Noted.", minutes_ago=40)  # a reply between: the new burst holds only their new words
        outcome, calls, _, _ = self.turn(self.inbound("Hello, any shops?"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))

    def test_a_persons_bitrix_opted_out_after_their_own_stop_never_lifts(self):
        from apps.leadai.assistant import crm_fields
        from apps.leadai.models import LeadAiCrmField

        self.stop("stop_all", minutes_ago=60)
        self.own_stop()  # the registry keeps the customer's first row
        LeadAiCrmField.objects.create(
            conversation=self.conversation, lead_id=555, field=crm_fields.FIELD_BOT_STATUS, value=str(crm_fields.STATUS_OPTED_OUT),
            payload={"set_in_bitrix": True, "changed_by": 7}, sent_at=NOW, error="set in Bitrix",
        )
        outcome, calls, _, _ = self.turn(self.inbound("Hello, do you have shops?"), [shop_answer()])
        self.assertEqual((calls, outcome.reason), ([], "stopped: stop_all"))


class ShopWordsTrackTests(ShopsBase):
    def decide(self, words, tag="other_need", stored="", facts=None):
        return tracks.decide(
            words=words, facts=facts if facts is not None else {"property_type": "shop", "intent": "rent"}, lead={}, stored=stored,
            template_kind=ic_templates.MIXED, model_tag=tag,
        )

    def test_words_about_shops_are_no_other_need(self):
        for words in (["Yes I have ma shops"], ["yes, my shops"], ["I have shops"]):
            with self.subTest(words):
                self.assertEqual(self.decide(words).track, tracks.SHOP)

    def test_a_real_other_need_stays_other(self):
        for words in (["No shop, something else"], ["AM NOT LOOKING FOR SHOPS"], ["shop nahi chahiye"], ["I did not ask shop"]):
            with self.subTest(words):
                self.assertEqual(self.decide(words).track, tracks.OTHER)
        self.assertEqual(self.decide(["Something bigger please"]).track, tracks.OTHER)  # no shop named: the model's tag stands
        self.assertEqual(self.decide(["shops in Al Quoz"], tag="other_area").track, tracks.OTHER)  # another area is no shop words
        # The review: a shop named beside another property, a letting or a long sentence stays the model's other need.
        for words in (
            ["Thanks for the shop offer, but I'm looking for a 2 bedroom apartment"], ["I already have a shop, now I need a villa"],
            ["I have 2 shops in Dragon Mart, want to rent them out"], ["shop is fine but I need an office"],
        ):
            with self.subTest(words):
                self.assertEqual(self.decide(words).track, tracks.OTHER)

    def test_the_shop_types_list_goes_on_the_switch(self):
        # As engine.residential_switch reads it: a shop track after the not-known one, with for_client known, is the
        # shop types list and "Sure! We have shops in International City too.", never the not-a-shop line.
        answer = shop_answer("Thank you for letting us know.", facts={"for_client": True}).data
        answer.setdefault("need_tag", "other_need")
        done = engine.residential_switch(
            answer, tracks.Decision(tracks.UNKNOWN), self.decide(["Yes I have ma shops"]), {}, ["Yes I have ma shops"], "Yes I have ma shops", NOW,
        )
        self.assertEqual(done, "shop")
        self.assertEqual((answer.get("shop_step") or {}).get("kind"), "list")
        self.assertNotIn("not_a_shop", answer)
