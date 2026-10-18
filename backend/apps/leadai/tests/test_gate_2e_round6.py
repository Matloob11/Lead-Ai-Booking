"""Batch 2e's real-model gate, round 6 (2026-10-18): passed (571 of 574, 99.5%; every strict scenario every run) and went
live. Its review found:

- a must: availability_talk cut the sale flow's own question when worded otherwise ("Do you prefer a vacant studio or a
  tenanted one?"), so shops-sale-rented-or-vacant lost it. Round 7 allowed such questions, and its review showed a claim
  in the same sentence then went out too. So the guard still cuts them, and on the sale track the first cut sentence that
  asks the choice gives way to code's own question (residential.drop_availability, sales.next_question_line): the question
  stays, no claim goes with it, and code's own Arabic question ("شاغرة") is no longer cut either.
- a should: a broker who named someone else earlier ("Actually it's for my buyer") lost the tag on a bare number ask
  when the model's for_client was null or false. _CLIENT_TALK now keeps it whatever the model says; its Arabic words are
  read with their article ("العميل"), and "طلب" only as a word of its own ("طلبت" is no "طلب").
- a nit: the turn's actions kept broker_backstop for a handover unasked_broker had taken off.
"""

from apps.leadai.assistant import residential, rules, schema
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import RentBase, res_answer
from django.test import SimpleTestCase

BUYER_FACTS = {"for_client": False, "intent": "buy", "property_type": "studio", "payment": "cash", "buy_timeline": "within a month"}
CHOICES = (
    "Do you prefer a rented unit or a vacant one? And is this for investment or for your own use?",
    "Do you prefer a vacant studio or a tenanted one? And is this for investment or for your own use?",
    "Would you like a vacant studio or one with a tenant? And is it for investment or your own use?",
    "Are you looking for a tenanted unit or a vacant unit? And is this for investment or for your own use?",
    "Do you prefer a vacant unit, or one that is already rented? And is it for investment or own use?",
)
BROKER = "broker_or_for_client"
HONESTY = "I'm AR Properties' virtual assistant — I can help with options and viewings, and connect you to our agent anytime."
REPLY = f"{HONESTY} I can't share the owner's number, but our agent will assist you with all details and arrange viewings."
FOR_MYSELF = [("assistant", "Are you looking for yourself or for a client?"), ("customer", "For myself")]


STATUS_EN = "Do you prefer a rented unit or a vacant one?"  # sales._Q_STATUS["en"][0]


class SaleQuestionTests(SimpleTestCase):
    def test_the_buyer_is_asked_however_the_model_worded_it(self):
        for question in CHOICES:
            with self.subTest(question):
                run = run_eval("shops-sale-rented-or-vacant", res_answer(f"Great, thanks. {question}", segment="buyer", facts=BUYER_FACTS))
                self.assertEqual(run.failures, [])

    def test_a_cut_question_gives_way_to_codes_own_once(self):
        for question in CHOICES[1:]:
            with self.subTest(question):
                reply, changed = residential.drop_availability(f"Great, thanks. {question}", residential.SALE, "en")
                self.assertTrue(changed)
                self.assertEqual(reply.count(STATUS_EN), 1)
        reply, _ = residential.drop_availability(f"{CHOICES[1]} {CHOICES[2]}", residential.SALE, "en")
        self.assertEqual(reply.count(STATUS_EN), 1)

    def test_no_claim_goes_with_it(self):
        # Round 7's review: an allowance for the question let a claim in the same sentence out.
        claim = "If you prefer a vacant studio or a tenanted one, there are several in Spain Cluster."
        self.assertEqual(residential.drop_availability(claim, residential.SALE, "en"), ("", True))
        both = "Do you prefer a vacant studio or a tenanted one, as we have both in Spain Cluster?"
        self.assertEqual(residential.drop_availability(both, residential.SALE, "en"), (STATUS_EN, True))
        for inventory in (
            "We have vacant or tenanted studios in Spain Cluster.",
            "There are vacant studios or tenanted ones in France Cluster.",
            "Our agent can show you available studios in Spain Cluster.",
        ):
            with self.subTest(inventory):
                self.assertTrue(residential.claims_availability(inventory))

    def test_codes_own_arabic_question_goes(self):
        # sales._Q_STATUS["ar"][0], whose "شاغرة" guard 6 cuts when the model writes it.
        question = "هل تفضّل وحدة مؤجرة أم شاغرة؟"
        reply, _ = residential.drop_availability(question, residential.SALE, "ar")
        self.assertEqual(reply, question)

    def test_never_off_the_sale_track(self):
        reply, changed = residential.drop_availability(CHOICES[1], residential.RENT, "en")
        self.assertEqual((reply, changed), ("And is this for investment or for your own use?", True))


class SomeoneElseNamedEarlierTests(SimpleTestCase):
    def tagged(self, for_client):
        return schema.normalize(res_answer(REPLY, handover=BROKER, facts={"for_client": for_client}).data, shops=True, residential=True)

    def test_the_tag_stays_whatever_the_models_for_client(self):
        for said in (
            "Actually it's for my buyer",
            "I have someone interested in your studio",
            "Requirement hai mere paas",
            "Tenant ke liye hai actually",
            "عندي مستأجر",
        ):
            for for_client in (None, False, True):
                with self.subTest(said=said, for_client=for_client):
                    answer = self.tagged(for_client)
                    earlier = [*FOR_MYSELF, ("customer", said)]
                    taken = residential.unasked_broker(answer, ["Owner's number?"], earlier, known={"for_client": False}, track=residential.RENT)
                    self.assertEqual(taken, "")
                    self.assertEqual(answer["handover"]["reason"], BROKER)

    def test_an_earlier_broker_only_brokers_declares_reads_keeps_it(self):
        # A firm named as theirs (brokers._ROLE), no client word: brokers.declares alone keeps the tag.
        said = "This is Neeta from Hamptons Properties"
        self.assertIsNone(residential._CLIENT_TALK.search(said))
        answer = self.tagged(None)
        earlier = [*FOR_MYSELF, ("customer", said)]
        taken = residential.unasked_broker(answer, ["Owner's number?"], earlier, known={"for_client": False}, track=residential.RENT)
        self.assertEqual(taken, "")
        self.assertEqual(answer["handover"]["reason"], BROKER)

    def test_arabic_words_with_their_article_but_no_request_inside_another_word(self):
        self.assertIsNotNone(residential._CLIENT_TALK.search("العميل يبي استوديو"))
        self.assertIsNotNone(residential._CLIENT_TALK.search("عندي طلب على استوديو"))
        self.assertIsNotNone(residential._CLIENT_TALK.search("الطلب جاهز"))
        self.assertIsNone(residential._CLIENT_TALK.search("طلبت شقة"))


class BackstopRecordTests(RentBase):
    def test_the_record_goes_with_the_tag_it_was(self):
        # brokers.backstop's facts path (the model's for_client true, no tag) in a chat that said for themselves, over a bare
        # number ask: unasked_broker takes it off, and the turn's actions record no broker handover.
        self.rent(clusters=["Spain"])
        message = self.inbound("Owner's number?")
        live = res_answer(REPLY, facts={"for_client": True, "intent": "rent", "property_type": "studio", "clusters": ["Spain"]})
        outcome, _, _, _ = self.turn(message, [live])
        self.assertNotIn("broker_backstop", self.actions(message) or {})
        self.assertNotEqual(self.body(outcome), rules.line("broker", "en"))
        self.assertIsNone(self.state().paused_at)

    def test_a_real_backstop_still_records_it(self):
        self.rent(clusters=["Spain"])
        message = self.inbound("I'm a real estate broker, owner's number?")
        live = res_answer(REPLY, facts={"for_client": None, "intent": "rent", "property_type": "studio", "clusters": ["Spain"]})
        outcome, _, _, _ = self.turn(message, [live])
        self.assertEqual((self.actions(message) or {}).get("broker_backstop"), "words")
        self.assertEqual(self.body(outcome), rules.line("broker", "en"))
