"""Batch 2e's real-model gate, round 6 (2026-10-18): passed (571 of 574, 99.5%; every strict scenario every run) and went
live. Its review found:

- a must: availability_talk cut the sale flow's own question when worded otherwise ("Do you prefer a vacant studio or a
  tenanted one?"), so shops-sale-rented-or-vacant lost it. A choice of theirs between vacant and tenanted, asked with a
  wish before it, is no claim (_AVAILABILITY_ALLOWED); "We have vacant or tenanted studios" still is.
- a should: a broker who named someone else earlier ("Actually it's for my buyer") lost the tag on a bare number ask
  when the model's for_client was null or false. _CLIENT_TALK now keeps it whatever the model says, and its Arabic and
  Urdu words stand alone ("طلبت" is no "طلب").
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


class SaleQuestionTests(SimpleTestCase):
    def test_the_buyers_choice_goes_however_it_is_worded(self):
        for question in CHOICES:
            with self.subTest(question):
                run = run_eval("shops-sale-rented-or-vacant", res_answer(f"Great, thanks. {question}", segment="buyer", facts=BUYER_FACTS))
                self.assertEqual(run.failures, [])

    def test_a_choice_is_no_claim_but_inventory_still_is(self):
        for question in CHOICES:
            with self.subTest(question):
                self.assertFalse(residential.availability_talk(question))
                self.assertFalse(residential.claims_availability(question))
        for claim in (
            "We have vacant or tenanted studios in Spain Cluster.",  # the guard's own "we have ... studios"
            "There are vacant studios or tenanted ones in France Cluster.",
            "Our agent can show you available studios in Spain Cluster.",
        ):
            with self.subTest(claim):
                self.assertTrue(residential.claims_availability(claim))


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

    def test_arabic_words_stand_alone(self):
        self.assertIsNone(residential._CLIENT_TALK.search("طلبت شقة"))
        self.assertIsNotNone(residential._CLIENT_TALK.search("عندي طلب على استوديو"))


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
