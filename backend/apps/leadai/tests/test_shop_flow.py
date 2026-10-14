"""Batch 2b: the shops conversation's own steps (board T31 the list, T32 a type's media and
card, T34 the licence copy, T44 reschedule, T56 the MATCH example), and that a general chat
keeps behaving as before.

- A. shop_flow on plain data (what the eval runs too);
- B. a shops turn end to end: the list, a tap on a row, [Book viewing], [See other types],
  photos asked for, a type's files once a day;
- C. the licence copy: asked once, taken from a photo or PDF, thanked for, refused;
  write_licence_file to the lead;
- D. "Need to reschedule" (typed or tapped) gets two free slots in a shops chat only;
- E. the recommendation names the customer's own business.

The fakes are test_assistant's; the shops chat is test_shops_playbook's (lead 555, the
clock Monday 12 October 2026, 14:00 Dubai).
"""

import base64
import datetime as dt
import shutil
import tempfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from apps.inbox.models import Conversation, MediaAsset, Message
from apps.leadai import tasks
from apps.leadai.assistant import crm_fields, engine, rules, shop_flow, taps
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChatState, LeadAiCrmField, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, answer, fake_send_text
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_shops_playbook import FIELDS_URL, TWO_SLOTS_NOW, GeneralBase, ShopsBase, shop_answer

LICENCE_ASK = rules.line("licence_copy", "en")
THANKS = rules.line("licence_thanks", "en")


# A. shop_flow on plain data ------------------------------------------------------------------------


class ShopFlowTests(SimpleTestCase):
    def test_a_tap_maps_back_to_its_type_by_id_or_by_title(self):
        self.assertEqual(shop_flow.tap_rule("Type 2 – Medium", "type_2"), ("type", "type_2"))
        self.assertEqual(shop_flow.tap_rule("Type 3 – Large"), ("type", "type_3"))  # the eval has the title alone
        self.assertEqual(shop_flow.tap_rule("Book viewing", "lai-shop:book:type_1"), ("book", "type_1"))
        self.assertEqual(shop_flow.tap_rule("احجز معاينة"), ("book", ""))
        self.assertEqual(shop_flow.tap_rule("See other types", "lai-shop:types"), ("types", ""))
        self.assertEqual(shop_flow.tap_rule("Doosri qisam"), ("types", ""))
        self.assertIsNone(shop_flow.tap_rule("Need to Reschedule", "leadai:5:reschedule"))  # a reminder's button
        self.assertIsNone(shop_flow.tap_rule("Interested"))
        self.assertIsNone(shop_flow.tap_rule(""))
        self.assertEqual(engine.tap_rule_name(shop_flow.tap_rule("Type 1 – Small", "type_1")), "type_tap:type_1")
        self.assertEqual(engine.tap_rule_name(shop_flow.tap_rule("See other types")), "types_tap")

    def test_what_the_customer_asks_for(self):
        for text in ("What types of shops do you have?", "which sizes are available", "show me the options", "kaun si shops hain?", "ما هي أنواع المحلات"):
            with self.subTest(text):
                self.assertTrue(shop_flow.asks_types(text))
        for text in ("I need a shop", "For myself", "How much is the rent?", "Type 1 please"):
            with self.subTest(text):
                self.assertFalse(shop_flow.asks_types(text))
        for text in ("Can you send photos?", "send me the video", "video bhej do", "ارسل صور", "photos?"):
            with self.subTest(text):
                self.assertTrue(shop_flow.asks_media(text))
        # Named, not asked for; or their own photo, not ours.
        for text in ("I saw the photos, nice", "I will send my licence photo", "I'll share a photo of my trade license", "here is my photo"):
            with self.subTest(text):
                self.assertFalse(shop_flow.asks_media(text))
        for text in ("No", "I will bring it", "Not with me right now", "I don't have it", "I won't send it", "I'll bring it to the viewing later"):
            with self.subTest(text):
                self.assertTrue(shop_flow.declines_copy(text))
                self.assertEqual(shop_flow.copy_reply(text), shop_flow.COPY_DECLINED)
        # A promise to send it later is no decline: the request stays open for the copy (board review 2b).
        for text in (
            "later", "baad mein", "Sure, I'll send it later", "will send it later today", "baad mein bhej dunga",
            "Ok I will share later", "I don't have it with me, I'll send it tomorrow", "not now", "سأرسلها لاحقاً",
        ):
            with self.subTest(text):
                self.assertFalse(shop_flow.declines_copy(text))
                self.assertEqual(shop_flow.copy_reply(text), shop_flow.COPY_LATER)
        self.assertFalse(shop_flow.declines_copy("Here it is"))
        self.assertEqual(shop_flow.copy_reply("Is the shop near Dragon Mart?"), "")

    def test_what_may_be_the_licence_copy(self):
        self.assertTrue(shop_flow.is_licence_media("image"))
        self.assertTrue(shop_flow.is_licence_media("document", "application/pdf"))
        self.assertTrue(shop_flow.is_licence_media("document", "", "Trade License.PDF"))
        self.assertFalse(shop_flow.is_licence_media("document", "application/msword", "licence.docx"))
        self.assertFalse(shop_flow.is_licence_media("video"))
        self.assertFalse(shop_flow.licence_open(None, None, NOW))
        self.assertTrue(shop_flow.licence_open(NOW - dt.timedelta(days=13), None, NOW))
        self.assertFalse(shop_flow.licence_open(NOW - dt.timedelta(days=14), None, NOW))
        self.assertFalse(shop_flow.licence_open(NOW - dt.timedelta(days=1), NOW, NOW))

    def answer(self, **facts):
        return {"facts": facts, "invited_to_meeting": False}

    def decide(self, said, answer=None, known=None, **flags):
        options = {"plain": True, "asked": False, "list_sent": False, "licence_asked": False}
        options.update(flags)
        return shop_flow.after_model(answer or self.answer(), known or {}, said, **options)

    def test_after_the_model_in_the_build_packs_order(self):
        # Photos asked for: the type in view, else the list.
        self.assertEqual(self.decide("send photos please", known={"shop_type": "type_3"}), {"kind": "media", "type": "type_3"})
        self.assertEqual(self.decide("send photos please", known={"size_sqft": 700}), {"kind": "media", "type": "type_2"})
        self.assertEqual(self.decide("send photos please"), {"kind": "list"})
        # The types asked for, even when the list went out already.
        self.assertEqual(self.decide("what types of shops do you have?", list_sent=True, asked=True), {"kind": "list"})
        # "For myself" now, with nothing to match yet: the list, once.
        self.assertEqual(self.decide("For myself", self.answer(for_client=False)), {"kind": "list"})
        self.assertIsNone(self.decide("For myself", self.answer(for_client=False), list_sent=True))
        self.assertIsNone(self.decide("For myself, around 450 sq ft", self.answer(for_client=False, size_sqft=450)))
        self.assertIsNone(self.decide("For myself", self.answer(for_client=False), known={"for_client": False}))
        self.assertIsNone(self.decide("For myself. When can I come?", self.answer(for_client=False), asked=True))
        # A DED or Trakhees licence: the copy asked for, once, never with a visit booked or a question open.
        self.assertEqual(self.decide("DED", self.answer(licence_kind="ded")), {"kind": "licence_ask"})
        self.assertEqual(self.decide("ok", known={"licence_kind": "trakhees"}), {"kind": "licence_ask"})
        self.assertIsNone(self.decide("DED", self.answer(licence_kind="ded"), licence_asked=True))
        self.assertIsNone(self.decide("DED", self.answer(licence_kind="ded"), booked=True))
        self.assertIsNone(self.decide("DED, when can I come?", self.answer(licence_kind="ded"), asked=True))
        self.assertIsNone(self.decide("New one", self.answer(licence_kind="new")))
        # Nothing at all when the answer must go as it is (a handover, a booking, a fixed line).
        self.assertIsNone(self.decide("send photos", known={"shop_type": "type_1"}, plain=False))

    def test_a_types_files_go_once_a_day_unless_asked_again(self):
        self.assertEqual(shop_flow.media_step("type_1", typed=False), {"kind": "media", "type": "type_1"})
        self.assertIsNone(shop_flow.media_step("type_1", typed=True, recent={"type_1"}))  # a double request
        self.assertEqual(shop_flow.media_step("type_1", typed=False, today={"type_1"}), {"kind": "media", "type": "type_1", "files": False})
        self.assertEqual(shop_flow.media_step("type_1", typed=True, today={"type_1"}), {"kind": "media", "type": "type_1"})
        self.assertIsNone(shop_flow.media_step("type_9", typed=True))
        self.assertEqual(self.decide("send the photos again", known={"shop_type": "type_1"}, media_today={"type_1"}), {"kind": "media", "type": "type_1"})

    def test_a_step_takes_the_models_invitation_and_location_with_its_words(self):
        for kind in ("list", "media", "slots", "licence_ask", "licence_thanks"):
            answer = {"shop_step": {"kind": kind}, "invited_to_meeting": True, "share_office_location": True}
            shop_flow.step_flags(answer)
            self.assertEqual((answer["invited_to_meeting"], answer["share_office_location"]), (False, False), kind)
        answer = {"invited_to_meeting": True, "share_office_location": True}
        shop_flow.step_flags(answer)
        self.assertTrue(answer["invited_to_meeting"])

    def test_the_licence_thanks_opens_the_reply_and_its_gloss(self):
        answer = {"send": True, "reply": "Yes, it is near Dragon Mart.", "reply_en": "", "opt_out": "none"}
        self.assertTrue(shop_flow.thank_first(answer, "en"))
        self.assertEqual(answer["reply"], "Thank you, got it. Yes, it is near Dragon Mart.")
        self.assertFalse(shop_flow.thank_first(answer, "en"))  # never twice
        arabic = {"send": True, "reply": "نعم.", "reply_en": "Yes.", "opt_out": "none"}
        shop_flow.thank_first(arabic, "ar")
        self.assertEqual((arabic["reply"], arabic["reply_en"]), ("شكراً لك، وصلتني. نعم.", "Thank you, got it. Yes."))
        for other in ({"send": False, "reply": "x"}, {"send": True, "reply": "x", "converted": "holding"}, {"send": True, "reply": "x", "shop_step": {"kind": "list"}}):
            self.assertFalse(shop_flow.thank_first({"opt_out": "none", **other}, "en"))

    def test_the_detail_card_is_the_build_packs(self):
        self.assertEqual(
            shop_flow.card_text("en", "type_1", None),
            "TYPE 1 – SMALL SHOP\nSize: 400-550 sq ft\nRent: AED 33,000-45,000 per year (cheapest AED 33,000)\nPayment: 1 to 4 cheques\n"
            "Clusters: France, England, China, Russia, Morocco, Persia\nWould you like to see it in person?",
        )
        self.assertTrue(shop_flow.card_text("ur", "type_3", None).startswith("Type 3 – Large\nسائز: 900-1,200 sq ft"))
        self.assertEqual([b["title"] for b in shop_flow.card_buttons("en", "type_1")], ["Book viewing", "See other types"])
        self.assertEqual(shop_flow.media_text("type_1", "en", None, files=False), shop_flow.card_text("en", "type_1", None))
        self.assertTrue(shop_flow.media_text("type_1", "en", None).startswith("[the video and photos of Type 1 – Small]\nTYPE 1"))

    def test_the_recommendation_names_their_own_business_or_none(self):
        own = shop_flow.own_business
        wrong = "For a mobile shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year."
        self.assertEqual(own(wrong, "vape"), ("For your vape business, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year.", True))
        self.assertEqual(own(wrong, "vape shop")[0], "For a vape shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year.")
        self.assertEqual(own(wrong, ""), ("Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year.", True))
        self.assertEqual(own(wrong, "", said="I have a mobile phone shop"), (wrong, False))  # said now, not recorded yet
        self.assertEqual(own(wrong, "mobile phones and accessories"), (wrong, False))
        self.assertEqual(own("For a 450 sq ft shop, Type 1 is perfect.", "vape")[1], False)  # a size is no business
        self.assertEqual(own("For your business, Type 2 is the best fit.", "vape")[1], False)
        self.assertEqual(
            own("Type 2 is perfect for a pharmacy. Shall I hold a slot?", "salon")[0], "Type 2 is perfect for a salon. Shall I hold a slot?"
        )
        self.assertEqual(own("Type 2 is perfect for a pharmacy.", "")[0], "Type 2 is perfect.")
        self.assertEqual(shop_flow.business_phrase("restaurant (shawarma and fresh juice)"), "a restaurant")
        self.assertEqual(shop_flow.business_phrase("ice cream"), "your ice cream business")

    def test_a_copied_placeholder_is_filled_in_or_left_out_never_sent(self):
        fill = shop_flow.fill_placeholders
        self.assertEqual(fill("A <their business>, got it. What size do you need?", "vape shop"), ("A vape shop, got it. What size do you need?", True))
        self.assertEqual(fill("Perfect, a <their business>.", "salon")[0], "Perfect, a salon.")
        self.assertEqual(fill("Units that suit a <Their Business>.", "ice cream")[0], "Units that suit your ice cream business.")
        self.assertEqual(fill("A <their business>, got it. What size do you need?", ""), ("What size do you need?", True))
        self.assertEqual(fill("A vape shop, got it.", "vape"), ("A vape shop, got it.", False))


# B. A shops turn end to end ------------------------------------------------------------------------


def list_reply(base, shop_type, title, seconds_ago=30):
    return base.inbound(
        title,
        kind=Message.Kind.INTERACTIVE,
        payload={"interactive": {"type": "list_reply", "list_reply": {"id": shop_type, "title": title, "description": "x"}}},
        seconds_ago=seconds_ago,
    )


def button_reply(base, button_id, title, seconds_ago=30):
    return base.inbound(
        title,
        kind=Message.Kind.INTERACTIVE,
        payload={"interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": title}}},
        seconds_ago=seconds_ago,
    )


class ShopStepTests(ShopsBase):
    def test_for_myself_gets_the_list_of_the_three_types(self):
        self.ours(rules.line("for_whom", "en"), minutes_ago=5)
        message = self.inbound("For myself")
        outcome, calls, _, _ = self.turn(message, [shop_answer("Great. What business will the shop be for?", facts={"for_client": False})])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.sent_lists.call_count, 1)
        sent = Message.objects.get(pk=outcome.reply_message_id)
        self.assertTrue(sent.payload["shop_list"])
        self.assertEqual(self.actions(message)["shop_step"], "list")
        self.assertIs(self.state().facts["for_client"], False)
        # The list goes once: "for myself" again later gets the model's words.
        self.later(5)
        again = self.inbound("for myself only")
        self.turn(again, [shop_answer("Noted. What business will it be for?", facts={"for_client": False})])
        self.assertEqual(self.sent_lists.call_count, 1)

    def test_a_tap_on_a_row_sends_that_types_media_and_records_it(self):
        message = list_reply(self, "type_2", "Type 2 – Medium")
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(calls, [])  # code's, no model
        self.media_delay.assert_called_once()
        conversation_id, shop_type, turn_id, language, files = self.media_delay.call_args.args
        self.assertEqual((conversation_id, shop_type, language, files), (self.conversation.pk, "type_2", "en", True))
        self.assertEqual(turn_id, LeadAiTurn.objects.get(inbound=message).pk)
        self.assertEqual(outcome.reason, "shop media queued (type_2)")
        self.assertEqual(self.state().facts["shop_type"], "type_2")
        self.assertIn((crm_fields.FIELD_SHOP_TYPE, "2472"), self.fields())
        actions = self.actions(message)
        self.assertEqual((actions["rule"], actions["shop_step"], actions["shop_type"]), ("type_tap:type_2", "media", "type_2"))

    def stamped_turn(self, message, completions):
        """A turn whose row is dated by the test's clock (the field's default reads the real one)."""
        result = self.turn(message, completions)
        LeadAiTurn.objects.filter(inbound=message).update(created_at=self.clock.return_value)
        return result

    def test_the_same_type_again_a_double_tap_nothing_later_its_card_asked_for_its_files(self):
        self.stamped_turn(list_reply(self, "type_2", "Type 2 – Medium"), [])
        self.later(3)
        # Nothing went out meanwhile (the files' task is a fake here), so this burst holds both taps.
        outcome, calls, _, _ = self.stamped_turn(list_reply(self, "type_2", "Type 2 – Medium"), [])
        self.assertEqual((calls, self.media_delay.call_count, outcome.reason), ([], 1, "no reply needed"))
        # The files' task (a fake here) sent the video and a photo, as shop_media.send_file stores them.
        turn = self.media_delay.call_args.args[2]
        for media_id in (1, 2):
            self.ours("", minutes_ago=-5, turn=turn, shop_media="type_2", shop_media_id=media_id)
        self.later(40)
        outcome, _, _, _ = self.stamped_turn(list_reply(self, "type_2", "Type 2 – Medium"), [])
        self.assertEqual(self.media_delay.call_args.args[4], False)  # its card alone: the files went out today
        self.assertEqual(outcome.reason, "shop card queued (type_2)")
        self.later(90)
        message = self.inbound("Can you send the photos and the video again?")
        self.stamped_turn(message, [shop_answer("Sure.")])
        self.assertEqual((self.media_delay.call_count, self.media_delay.call_args.args[1], self.media_delay.call_args.args[4]), (3, "type_2", True))
        # Another day (the customer wrote since, so the window is open), a tap sends the files again.
        Conversation.objects.filter(pk=self.conversation.pk).update(session_expires_at=NOW + dt.timedelta(days=2))
        self.later(24 * 60)
        self.ours(shop_flow.card_text("en", "type_2", None), minutes_ago=-(24 * 60 - 1), shop_card="type_2")  # the card that went out
        outcome, _, _, _ = self.stamped_turn(list_reply(self, "type_2", "Type 2 – Medium"), [])
        self.assertEqual((outcome.reason, self.media_delay.call_count, self.media_delay.call_args.args[4]), ("shop media queued (type_2)", 4, True))

    def test_a_double_tap_on_two_rows_is_the_last_one(self):
        first = list_reply(self, "type_1", "Type 1 – Small", seconds_ago=40)
        second = list_reply(self, "type_3", "Type 3 – Large", seconds_ago=30)
        self.assertLess(first.pk, second.pk)
        _, calls, _, _ = self.turn(second, [])
        self.assertEqual((calls, self.media_delay.call_args.args[1]), ([], "type_3"))

    def test_book_viewing_gets_two_free_slots_and_see_other_types_the_list(self):
        self.set_state(facts={"for_client": False, "shop_type": "type_2"})
        outcome, calls, _, _ = self.turn(button_reply(self, "lai-shop:book:type_2", "Book viewing"), [])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), TWO_SLOTS_NOW)
        self.later(5)
        self.turn(button_reply(self, "lai-shop:types", "See other types"), [])
        self.assertEqual(self.sent_lists.call_count, 1)

    def test_photos_asked_for_send_the_type_in_view_not_the_models_words(self):
        self.set_state(facts={"for_client": False, "size_sqft": 450, "business_activity": "salon"})
        message = self.inbound("Can you send me some photos?")
        outcome, calls, _, _ = self.turn(message, [shop_answer("Sure, here they are!")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.media_delay.call_args.args[1], "type_1")  # MATCH: 450 sq ft
        self.assertFalse(Message.objects.filter(conversation=self.conversation, body="Sure, here they are!").exists())

    def test_a_handover_or_a_booking_is_never_replaced_by_a_step(self):
        self.set_state(facts={"for_client": False, "shop_type": "type_1"})
        message = self.inbound("Send photos, and please call me")
        self.turn(message, [shop_answer("Our agent will call you.", handover="call_requested")])
        self.media_delay.assert_not_called()


class GeneralChatTests(GeneralBase):
    """A general chat gets none of the shops steps (only the script check is every playbook's)."""

    def test_no_list_no_media_no_licence_request(self):
        message = self.inbound("What types of shops do you have? Send photos")
        outcome, _, _, _ = self.turn(message, [answer("We have shops of several sizes. What size do you need?")])
        self.assertEqual(self.body(outcome), "We have shops of several sizes. What size do you need?")
        self.media_delay.assert_not_called()
        self.assertEqual(self.sent_lists.call_count, 0)
        self.assertNotIn("shop_step", self.actions(message))


# C. The licence copy -----------------------------------------------------------------------------


class LicenceTests(ShopsBase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="leadai-licence-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root, LEADAI_BITRIX_FIELDS_URL=FIELDS_URL, CRM_LEAD_WA_SECRET="test-crm-secret")
        override.enable()
        self.addCleanup(override.disable)
        self.list_matloob()

    def asked(self, minutes_ago=5):
        self.set_state(facts={"for_client": False, "licence_kind": "ded", "trade_licence": "yes"}, licence_asked_at=NOW - dt.timedelta(minutes=minutes_ago))
        return self.ours(LICENCE_ASK, minutes_ago=minutes_ago, shop_step="licence_ask")

    def photo(self, data=b"\xff\xd8\xff\xe0" + b"\x01" * 50, *, kind=Message.Kind.IMAGE, mime="image/jpeg", name="licence.jpg", downloaded=True, body=""):
        asset = MediaAsset(mime_type=mime, file_name=name, size_bytes=len(data), downloaded=downloaded)
        if downloaded:
            asset.file.save(name, ContentFile(data), save=False)
        asset.save()
        return self.inbound(body, kind=kind, media=asset)

    def test_a_ded_licence_gets_the_copy_asked_for_once(self):
        message = self.inbound("Yes I have a DED licence")
        outcome, _, _, _ = self.turn(
            message, [shop_answer("Perfect. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?", facts={"licence_kind": "ded"}, invited=True)]
        )
        self.assertEqual(self.body(outcome), LICENCE_ASK)
        sent = Message.objects.get(pk=outcome.reply_message_id)
        self.assertEqual(sent.payload["shop_step"], "licence_ask")
        state = self.state()
        self.assertIsNotNone(state.licence_asked_at)
        self.assertEqual(state.invites, 0)  # the copy asked for is no invitation
        self.later(5)
        again = self.inbound("It is a DED licence, yes")
        outcome, _, _, _ = self.turn(again, [shop_answer("Great. I can hold a slot for you today at 2:30 PM or 4:30 PM — which is better?", facts={"licence_kind": "ded"})])
        self.assertNotEqual(self.body(outcome), LICENCE_ASK)  # never twice

    def test_no_copy_asked_for_once_a_visit_is_booked(self):
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=NOW + dt.timedelta(days=1))
        self.set_state(facts={"for_client": False, "licence_kind": "ded"})
        outcome, _, _, _ = self.turn(self.inbound("ok, it is Trakhees actually"), [shop_answer("Noted, a Trakhees licence.", facts={"licence_kind": "trakhees"})])
        self.assertEqual(self.body(outcome), "Noted, a Trakhees licence.")

    def test_the_photo_while_asked_is_the_licence_thanked_and_sent_to_the_lead(self):
        self.asked()
        message = self.photo()
        outcome, calls, _, _ = self.turn(message, [])
        self.assertEqual(calls, [])
        self.assertEqual(self.body(outcome), f"{THANKS} {TWO_SLOTS_NOW}")
        state = self.state()
        self.assertIsNotNone(state.licence_closed_at)
        self.assertEqual(state.facts["licence_copy"], "received")
        self.assertIsNone(state.handed_over_at)  # never a "media received" handover
        row = LeadAiCrmField.objects.get(field=crm_fields.LICENCE_FILE)
        self.assertEqual((row.lead_id, row.value), (555, str(message.pk)))
        self.licence_delay.assert_called_once_with(row.pk)
        self.assertEqual(self.actions(message)["licence"], "received")

    def test_the_pdf_with_a_question_suppresses_the_media_handover_and_thanks_first(self):
        self.asked()
        self.photo(b"%PDF-1.4 licence", kind=Message.Kind.DOCUMENT, mime="application/pdf", name="licence.pdf")
        question = self.inbound("Is the shop near Dragon Mart?", seconds_ago=20)
        outcome, calls, _, _ = self.turn(question, [shop_answer("Yes, a few minutes away.", handover="media_received")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), f"{THANKS} Yes, a few minutes away.")
        self.assertIsNone(self.state().handed_over_at)
        self.assertEqual(LeadAiCrmField.objects.filter(field=crm_fields.LICENCE_FILE).count(), 1)
        self.assertTrue(self.actions(question)["licence_thanked"])

    def test_a_colleague_answering_meanwhile_drops_the_reply_never_the_copy(self):
        from apps.leadai.tests.test_assistant import _outbound

        self.asked()
        self.photo()
        question = self.inbound("Which cluster is it in?", seconds_ago=20)
        outcome, _, _, _ = self.turn(
            question, [shop_answer("France cluster.")],
            during_model=lambda: _outbound(self.conversation, self.agent, Message.Kind.TEXT, "I will call you now", {}),
        )
        self.assertEqual(outcome.reason, "an agent answered while thinking")
        self.assertEqual(self.state().facts["licence_copy"], "received")
        self.assertIsNotNone(self.state().licence_closed_at)
        self.licence_delay.assert_called_once()

    def test_a_no_closes_the_request_and_is_no_deferral(self):
        self.asked()
        message = self.inbound("I will bring it to the viewing")
        outcome, calls, _, _ = self.turn(message, [shop_answer("No problem, please bring it with you.")])
        self.assertEqual(len(calls), 1)  # the model's, not the deferral rule's
        self.assertEqual(self.body(outcome), "No problem, please bring it with you.")
        state = self.state()
        self.assertEqual(state.facts["licence_copy"], "declined")
        self.assertIsNotNone(state.licence_closed_at)
        self.assertFalse(LeadAiAppointment.objects.exists())  # no tentative visit from "I will bring it"
        # Closed: a photo later is an ordinary photo again.
        self.later(10)
        self.photo()
        self.assertFalse(shop_flow.licence_open(state.licence_asked_at, state.licence_closed_at, NOW))

    def test_write_licence_file_posts_the_copy_to_the_lead(self):
        self.asked()
        message = self.photo(b"%PDF-1.7 the licence", kind=Message.Kind.DOCUMENT, mime="application/pdf", name="TL.pdf")
        row = LeadAiCrmField.objects.create(conversation=self.conversation, lead_id=555, field=crm_fields.LICENCE_FILE, value=str(message.pk))
        with patch("apps.leadai.assistant.crm_fields.post", return_value={"ok": True, "updated": ["UF_CRM_A7_TRADE_LICENSE_FILE"]}) as post:
            tasks.write_licence_file.apply(args=[row.pk])
        body = post.call_args.args[0]
        self.assertEqual((body["lead_id"], body["license_file"]["name"]), (555, "licence.pdf"))
        self.assertEqual(base64.b64decode(body["license_file"]["content_base64"]), b"%PDF-1.7 the licence")
        row.refresh_from_db()
        self.assertIsNotNone(row.sent_at)
        self.assertFalse(LeadAiAlert.objects.filter(kind="licence").exists())

    def test_a_file_too_large_stays_in_the_chat_and_2311_is_told(self):
        self.asked()
        message = self.photo(b"\xff\xd8\xff\xe0" + b"\x00" * (5 * 1024 * 1024))
        row = LeadAiCrmField.objects.create(conversation=self.conversation, lead_id=555, field=crm_fields.LICENCE_FILE, value=str(message.pk))
        with patch("apps.leadai.assistant.crm_fields.post") as post:
            tasks.write_licence_file.apply(args=[row.pk])
        post.assert_not_called()
        alerts = LeadAiAlert.objects.filter(kind="licence")
        self.assertIn("licence file too large, saved in the chat", alerts.first().text)
        self.assertTrue(alerts.filter(agent=self.matloob).exists())  # the listed users (2311) hear of it
        row.refresh_from_db()
        self.assertIsNone(row.sent_at)

    def test_a_file_that_is_no_pdf_jpeg_or_png_and_a_refusal_are_told_too(self):
        self.asked()
        message = self.photo(b"GIF89a....", mime="image/gif", name="licence.gif")
        row = LeadAiCrmField.objects.create(conversation=self.conversation, lead_id=555, field=crm_fields.LICENCE_FILE, value=str(message.pk))
        tasks.write_licence_file.apply(args=[row.pk])
        self.assertIn("not a PDF, JPEG or PNG", LeadAiAlert.objects.filter(kind="licence").first().text)
        LeadAiAlert.objects.all().delete()
        ok = self.photo()
        row = LeadAiCrmField.objects.create(conversation=self.conversation, lead_id=555, field=crm_fields.LICENCE_FILE, value=str(ok.pk))
        with patch("apps.leadai.assistant.crm_fields.post", return_value={"ok": False, "error": "Bad licence."}):
            tasks.write_licence_file.apply(args=[row.pk])
        self.assertIn("Bitrix refused the file (Bad licence.)", LeadAiAlert.objects.filter(kind="licence").first().text)

    def test_it_waits_for_the_download_then_gives_up_and_tells(self):
        self.asked()
        message = self.photo(downloaded=False)
        row = LeadAiCrmField.objects.create(conversation=self.conversation, lead_id=555, field=crm_fields.LICENCE_FILE, value=str(message.pk))
        with patch("apps.leadai.assistant.crm_fields.post") as post:
            tasks.write_licence_file.apply(args=[row.pk])
        post.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.error, "The file never downloaded.")
        self.assertIn("could not be downloaded", LeadAiAlert.objects.get(kind="licence", agent=self.matloob).text)

    def test_bitrix_down_is_retried_then_left_for_the_sweep(self):
        self.asked()
        message = self.photo()
        row = LeadAiCrmField.objects.create(conversation=self.conversation, lead_id=555, field=crm_fields.LICENCE_FILE, value=str(message.pk))
        with patch("apps.leadai.assistant.crm_fields.post", side_effect=crm_fields.FieldsError("Bitrix answered 503")) as post:
            tasks.write_licence_file.apply(args=[row.pk])
        self.assertEqual(post.call_count, 1 + len(tasks.CRM_RETRY))
        row.refresh_from_db()
        self.assertIsNotNone(row.retry_at)
        self.assertIsNone(row.sent_at)

    def test_the_licence_body_checks_the_bytes_and_the_size(self):
        self.assertEqual(crm_fields.licence_body(1, b"\x89PNG\r\n\x1a\nxx")["license_file"]["name"], "licence.png")
        for data, error in ((b"MZ binary", "not a PDF, JPEG or PNG"), (b"%PDF" + b"0" * (5 * 1024 * 1024), "larger than 5 MB")):
            with self.subTest(error), self.assertRaises(ValueError) as raised:
                crm_fields.licence_body(1, data)
            self.assertEqual(str(raised.exception), error)


# D. "Need to reschedule": two free slots in a shops chat ------------------------------------------


class RescheduleTests(ShopsBase):
    def booked(self, start=None):
        return LeadAiAppointment.objects.create(
            conversation=self.conversation, status="confirmed", starts_at=start or NOW + dt.timedelta(days=1, hours=3), customer_name="Ahmed"
        )

    def test_typed_it_gets_the_two_nearest_free_slots_never_their_own(self):
        self.booked(NOW + dt.timedelta(minutes=30))  # today at 2:30 PM
        message = self.inbound("I need to reschedule")
        outcome, _, _, _ = self.turn(message, [shop_answer("Sure, no problem.", action="reschedule")])
        text = self.body(outcome)
        self.assertEqual(text, "Sure. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?")
        self.assertEqual(self.actions(message)["fallback"], "reschedule_slots")
        self.assertEqual(LeadAiAppointment.objects.get().customer_state, "reschedule")

    def test_an_open_when_for_the_move_is_two_slots_too(self):
        self.booked(NOW + dt.timedelta(minutes=30))
        message = self.inbound("I need to reschedule")
        outcome, _, _, _ = self.turn(message, [shop_answer("Sure, when would you like to come instead?", action="reschedule")])
        text = self.body(outcome)
        self.assertIn("I can hold a slot for you today at 3:00 PM or 5:00 PM", text)  # settle's own two slots
        self.assertNotIn("2:30 PM", text)
        self.assertIn("slots", self.actions(message)["trimmed"])

    def test_choosing_one_re_books(self):
        appointment = self.booked(NOW + dt.timedelta(minutes=30))
        self.ours("Sure. I can hold a slot for you today at 3:00 PM or 5:00 PM — which is better?", minutes_ago=2)
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(customer_state="reschedule")
        message = self.inbound("5 pm please")
        self.turn(message, [shop_answer("", action="reschedule", place="office", date="2026-10-12", time="17:00")])
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.starts_at.astimezone(NOW.tzinfo).hour), ("confirmed", 17))

    def test_a_tap_on_the_reminder_gets_them_too(self):
        appointment = self.booked(NOW + dt.timedelta(minutes=30))
        tap = button_reply(self, f"leadai:{appointment.pk}:reschedule", "Need to Reschedule")
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text), patch("apps.leadai.tasks.sync_appointment_crm.delay"), self.captureOnCommitCallbacks(execute=True):
            result = taps.handle(tap.pk)
        self.assertEqual(result, "tap: reschedule")
        reply = Message.objects.get(payload__source="leadai_tap")
        self.assertTrue(reply.body.startswith("Sure. I can hold a slot for you today at "), reply.body)
        self.assertNotIn("2:30 PM", reply.body)


class GeneralRescheduleTests(GeneralBase):
    def test_a_general_chat_keeps_its_open_question(self):
        appointment = LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=NOW + dt.timedelta(minutes=30))
        tap = button_reply(self, f"leadai:{appointment.pk}:reschedule", "Need to Reschedule")
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text), patch("apps.leadai.tasks.sync_appointment_crm.delay"), self.captureOnCommitCallbacks(execute=True):
            taps.handle(tap.pk)
        self.assertEqual(Message.objects.get(payload__source="leadai_tap").body, rules.line("ask_new_time", "en"))
        message = self.inbound("I need to reschedule please", seconds_ago=20)
        outcome, _, _, _ = self.turn(message, [answer("", action="reschedule")])
        self.assertEqual(self.body(outcome), rules.line("ask_new_time", "en"))


# E. The recommendation names the customer's own business (board T56) -------------------------------


class OwnBusinessTests(ShopsBase):
    def test_a_vape_business_never_reads_mobile_shop(self):
        self.set_state(facts={"for_client": False, "business_activity": "vape"})
        message = self.inbound("Around 450 sq ft")
        outcome, _, _, _ = self.turn(
            message,
            [shop_answer("For a mobile shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees licence, or will you open a new one?", facts={"size_sqft": 450})],
        )
        text = self.body(outcome)
        self.assertNotIn("mobile", text)
        self.assertTrue(text.startswith("For your vape business, Type 1 is perfect"), text)
        self.assertIn("business", self.actions(message)["trimmed"])


class GeneralOwnBusinessTests(GeneralBase):
    def test_no_business_guard_in_a_general_chat(self):
        LeadAiChatState.objects.update_or_create(conversation=self.conversation, defaults={"facts": {"business_activity": "vape"}})
        message = self.inbound("Around 450 sq ft")
        outcome, _, _, _ = self.turn(message, [answer("For a mobile shop, a unit of that size works well. Shall we meet at our office?")])
        self.assertIn("mobile shop", self.body(outcome))


# F. The eval mirrors these paths (leadai_eval) -----------------------------------------------------


@override_settings(LEADAI_OPENAI_API_KEY="test")
class EvalMirrorTests(ShopsBase):
    MODEL = "apps.leadai.assistant.openai_client.complete_json"

    def run_with(self, scenario_id, *answers):
        from apps.leadai.management.commands import leadai_eval

        scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
        with patch(self.MODEL, side_effect=list(answers)) as model:
            run = leadai_eval.run_once(scenario, scenario_id)
        return run, model.call_count

    def test_the_batch_2b_scenarios_are_there(self):
        from apps.leadai.management.commands import leadai_eval

        ids = {s.id for s in leadai_eval.SCENARIOS}
        wanted = {
            "shops-for-myself-list", "shops-asks-types", "shops-type-tap", "shops-type-tap-again", "shops-book-tap",
            "shops-other-types-tap", "shops-photos", "shops-licence-ask", "shops-licence-copy", "shops-licence-copy-question",
            "shops-licence-later", "shops-reschedule", "shops-vape-match", "lang-urdu-after-english", "lang-hindi-devanagari",
            "lang-arabic-booking", "stop-arabic-after-english",
        }
        self.assertLessEqual(wanted, ids)

    def test_an_english_first_answer_is_asked_for_again_in_urdu(self):
        english = eval_answer("Thank you. Do you have a trade licence?")
        urdu = eval_answer("شکریہ۔ کیا آپ کے پاس ٹریڈ لائسنس ہے؟", language="ur", reply_en="Thank you. Do you have a trade licence?")
        run, calls = self.run_with("lang-urdu-after-english", english, urdu)
        self.assertEqual((calls, run.failures, run.answer["script_fix"]), (2, [], "fixed"))
        run, calls = self.run_with("lang-urdu-after-english", english, english)
        self.assertEqual(calls, 2)
        self.assertIn("reply is not in Urdu script", run.failures)

    def test_the_vape_scenario_holds_only_because_of_the_code_guard(self):
        wrong = eval_answer(
            "For a mobile shop, Type 1 is perfect: 400-550 sq ft, from AED 33,000 a year. Do you have a DED or Trakhees licence, "
            "or will you open a new one?",
            facts={"size_sqft": 450, "shop_type": "type_1"},
        )
        run, _ = self.run_with("shops-vape-match", wrong)
        self.assertEqual(run.failures, [])
        self.assertTrue(run.reply.startswith("For a vape shop, Type 1 is perfect"), run.reply)
        with patch("apps.leadai.assistant.shop_flow.own_business", side_effect=lambda reply, *a, **k: (reply, False)):
            run, _ = self.run_with("shops-vape-match", wrong)
        self.assertIn('names a business the customer does not have: "mobile"', run.failures)

    def test_a_step_is_reported_as_what_it_would_send(self):
        run, calls = self.run_with("shops-licence-copy")
        self.assertEqual((calls, run.failures), (0, []))
        self.assertEqual(run.out, f"{THANKS} {TWO_SLOTS_NOW}")
        run, calls = self.run_with("shops-type-tap")
        self.assertTrue(run.out.startswith("[the video and photos of Type 2 – Medium]\nTYPE 2 – MEDIUM SHOP"), run.out)
        run, _ = self.run_with("shops-type-tap-again")
        self.assertTrue(run.out.startswith("TYPE 2 – MEDIUM SHOP"), run.out)
        run, _ = self.run_with("stop-arabic-after-english")
        self.assertEqual((run.out, run.failures), (rules.line("stop_all", "ar"), []))

    def test_a_model_answer_that_must_go_as_it_is_fails_a_step_scenario(self):
        handover = eval_answer("Our agent will call you.", handover="call_requested")
        run, _ = self.run_with("shops-photos", handover)
        self.assertIn("shops step none, expected media", run.failures)
        # The licence request goes once: the model asking again in its own words fails (said word for
        # word, the no-repeat guard cuts it before it goes).
        run, _ = self.run_with("shops-licence-later", eval_answer("No problem. Could you send a copy of your trade license today?"))
        self.assertTrue(any("asks for the copy again" in failure for failure in run.failures), run.failures)
        run, _ = self.run_with("shops-licence-later", eval_answer("No problem. " + LICENCE_ASK))
        self.assertEqual((run.reply, run.failures), ("No problem.", []))

    def test_the_reschedule_offer_never_names_their_own_slot(self):
        run, _ = self.run_with("shops-reschedule", eval_answer("Sure, no problem.", action="reschedule"))
        self.assertEqual(run.failures, [])
        self.assertEqual(run.out, f"Sure. {TWO_SLOTS_NOW}")
