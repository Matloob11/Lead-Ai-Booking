"""A broker is never served as an end user (2026-10-17, assistant/brokers.py; the launch gate's eval shops-broker).

In the real-model eval the model answered "I am an agent, I am checking for my client. He needs a shop around 500 sq
ft" with facts.for_client true and no handover, in both runs, and served the agent: "For your client, a Type 1 shop is
perfect ...". Q11: a broker gets the hand-off line, the Broker label and a pause. Each test feeds the scenario's own
words, or one exclusion's, with the model's answer as the gate's runs recorded it (or the one an exclusion would get).
Every test fails with the backstop switched off (brokers.BACKSTOP False): an exclusion is tested beside the broker's
words it differs from, and fails as well with its own reader switched off (the scratchpad guard-off run):

- A. who declares themselves a broker, in our languages, and who never does: a trade of theirs, words about us, a no,
  someone looking for a client;
- B. who is an end user whatever the model's for_client says: a business owner's own customers, family, a friend or a
  partner (eval shops-rented-licence-no keeps "Yes, I need one more for my brother's salon" an end user), "client"
  only in words about us;
- C. the backstop on the answer: the facts newly, the words over a weaker handover but never a call, a person or a
  complaint, never over an opt-out or in a chat labelled Broker, no taken slot offered around it;
- D. the turn: the hand-off line, the Broker label, the pause, Purpose and Bot Status Broker, the alert; an end user's
  turn goes on; a must-answer question from a broker; after Resume AI; a general chat is untouched;
- E. the eval runs it as the engine does: shops-broker passes with the gate's own answers;
- F. the review (2026-10-17), one class per finding, each beside the broker's words it differs from: our agent is
  none of theirs and a chat a person holds counts "I am a broker" only (F1); a business owner's own client, and client
  words where anything says they are the end user (F2); their questions are theirs, about us only with "you" before the
  word (F3); a no, a fee or a past before "as a broker" (F4); a broker's words of his client's customers (F5); more ways
  a broker says it, under the same guards (F6); a bare "Agent" answers our for-whom question only (F7); the eval mirror
  reads the held chat and our last line as live.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai; the chat is lead 555's.
"""

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.inbox.models import Label
from apps.leadai.assistant import brokers, crm_fields, engine, nudges, people, rules, schema
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAlert, LeadAiAppointment
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_shops_playbook import TWO_SLOTS_NOW, GeneralBase, ShopsBase, at, shop_answer

# The scenario's own words (eval shops-broker), the model's two replies as the gate's runs printed them, and its facts:
# for_client true, as the gate recorded (the size is the scenario's own).
SCENARIO_WORDS = "I am an agent, I am checking for my client. He needs a shop around 500 sq ft"
RUN_1 = (
    "For your client, a Type 1 shop is perfect: 400-550 sq ft, from AED 33,000 a year. Does your client have a trade "
    "licence, or will they open a new one?"
)
RUN_2 = (
    "For your client, a Type 1 shop is perfect: 400-550 sq ft, from AED 33,000 a year. What licence does your client "
    "have, DED, Trakhees, or will they open a new one?"
)
GATE_FACTS = {"for_client": True, "property_type": "shop", "size_sqft": 500}
FOR_WHOM = rules.line("for_whom", "en")
BROKER_LINE = rules.line("broker", "en")
MODELS_QUESTION = "Great. What business will the shop be for?"


def shops_answer(reply=MODELS_QUESTION, **extra):
    """A model's shops answer as engine.ask_model hands it on (schema.normalize)."""
    return schema.normalize(shop_answer(reply, **extra).data, shops=True)


def hand(words, *, known=None, labelled=False, held=False, our_last="", **model):
    """(what brokers.backstop did, the answer) for their words and the model's answer (``model``: shop_answer's);
    ``held``: a person holds the chat; ``our_last``: our last message."""
    answer = shops_answer(**model)
    texts = [words] if isinstance(words, str) else list(words)
    return brokers.backstop(answer, known or {}, texts, labelled=labelled, held=held, our_last=our_last), answer


class BrokerBase(SimpleTestCase):
    def assertHanded(self, words, by=brokers.WORDS, **kwargs):
        done, answer = hand(words, **kwargs)
        self.assertEqual(done, by, words)
        self.assertEqual(answer["handover"], {"needed": True, "reason": engine.BROKER}, words)
        self.assertIs(answer["facts"]["for_client"], True)
        return answer

    def assertNotHanded(self, words, **kwargs):
        done, answer = hand(words, **kwargs)
        self.assertEqual(done, "", words)
        self.assertNotEqual(answer["handover"]["reason"], engine.BROKER, words)
        return answer

    def assertPairs(self, pairs, by=None, **kwargs):
        """Each end user's words stay theirs; the broker's words beside them are handed over (the backstop is on): by
        their words, or by ``by``."""
        for end_user, broker in pairs:
            with self.subTest(end_user=end_user):
                self.assertNotHanded(end_user, **kwargs)
                self.assertHanded(broker, by=by or brokers.WORDS, **kwargs)


# A. Who declares themselves a broker --------------------------------------------------------------------------------


class DeclaresTests(BrokerBase):
    def test_the_scenarios_own_words(self):
        answer = self.assertHanded(SCENARIO_WORDS, reply=RUN_1, facts=GATE_FACTS)
        self.assertEqual(answer["broker_backstop"], brokers.WORDS)
        for sentence in ("I am an agent", "I am checking for my client"):
            with self.subTest(sentence):
                self.assertHanded(sentence)
        # Their last sentence alone says nothing of an agent: the model's for_client true hands it over (B, C).
        self.assertNotHanded("He needs a shop around 500 sq ft")
        self.assertHanded("He needs a shop around 500 sq ft", by=brokers.FACTS, reply=RUN_2, facts=GATE_FACTS)

    def test_how_a_broker_says_it(self):
        said = (
            "I am a broker, I have a client looking for a shop around 300 sqft in IC. How much commission do you share?",
            "I'm a real estate agent", "Im agent", "i m a broker", "We are a brokerage", "we are real estate brokers", "I'm a realtor",
            "I am a RERA registered broker", "I am Ahmed, a real estate agent", "Broker here, do you share commission?", "Hi, agent here",
            "As a broker, do you share commission?", "I'm an agent at Betterhomes", "I am a property consultant",
            "I'm from a real estate agency", "I am also an agent",
            "for my client", "For my clients", "for one of my clients", "on behalf of my client", "I am asking on behalf of a client",
            "checking for a client", "For a client", "No, for a client", "Client", "client", "Yes, client", "for client",
            "I have a client looking for a shop", "I've got a client who wants a shop", "my client is looking for a shop in France cluster",
            "My client wants Type 2", "Can my client see the shop tomorrow?", "Yes, for my client's restaurant",
            "We have clients looking for shops in International City", "a client of mine needs a shop",
            "Hi, for a client. What sizes do you have?", "For a client, what sizes do you have?", "I'm looking for a shop for a client",
            "I'm checking for a client for your shops",
            # Roman Urdu
            "main agent hoon", "mai broker hu", "hum broker hain", "client ke liye", "Client k liye chahiye", "client ke liye ur 400 sqft chahiye",
            "mere client ko shop chahiye", "mera client France cluster mein shop dhoond raha hai", "mere paas ek client hai",
            # Arabic
            "أنا وسيط عقاري", "انا سمسار", "نحن مكتب عقاري", "أبحث عن محل لعميل", "عندي عميل يبحث عن محل", "عميلي يريد محل",
            # Urdu script and Devanagari: our own for-whom question's words in the scripts we ask it in
            "میں بروکر ہوں", "کلائنٹ کے لیے", "मैं ब्रोकर हूँ", "क्लाइंट के लिए",
        )
        for words in said:
            with self.subTest(words):
                self.assertHanded(words)

    def test_a_trade_of_theirs_is_no_broker(self):
        self.assertPairs(
            [
                ("I am a travel agent, I need a shop for my agency", "I am a real estate agent, I need a shop"),
                ("I'm an insurance broker", "I'm a real estate broker"),
                ("I am a customs broker, I need a shop for my clearing business", "I am a property broker"),
                ("I am an agent for Etisalat, I want to open a mobile shop", "I am an agent for my client, he wants a mobile shop"),
                ("I am Ali, agent for du", "I am Ali, a real estate agent"),
                # Someone else's words or deeds, never theirs.
                ("I am confused, a broker told me the rent is 30k", "I am Sana, a broker"),
                ("As an agent told me, the rent is 30k", "As an agent, I ask the rent"),
                ("The broker here told me the rent is 30k", "Broker here, what is the rent?"),
            ]
        )

    def test_words_about_us_a_no_or_a_client_sought(self):
        self.assertPairs(
            [
                ("Are you checking for a client?", "Yes, checking for a client"),
                ("Is the shop for yourself, or are you checking for a client?", "For a client"),
                ("What do you mean, for a client?", "Yes, for a client"),
                ("client?", "client"),
                ("Are you an agent?", "I am an agent"),
                ("Do you work with agents?", "I work as an agent"),
                ("For myself, not for a client", "For a client, not for myself"),
                ("I'm not checking for a client, it's for me", "I'm checking for a client, not for me"),
                ("I don't have a client", "I have a client"),
                ("I am not a broker", "I am a broker"),
                ("client ke liye nahi, apne liye", "client ke liye, apne liye nahi"),
                ("I am looking for a client for my shop", "I am looking for a shop for a client"),
            ]
        )


# B. Who is an end user whatever the model's for_client says ------------------------------------------------------------


class EndUserTests(BrokerBase):
    """The model recorded facts.for_client true, with no handover: these words keep them an end user (end_user)."""

    def test_a_business_owners_own_customers(self):
        for words in (
            "I need a shop to serve my clients", "My clients come to my salon every day", "I need it for client meetings",
            "I need a bigger shop for my clients, I have a salon", "A shop for my clients to visit easily",
            "My clients need parking near the shop", "Parking for my clients is important", "The location is good for my clients",
            "mere client bohat aate hain", "لخدمة عملائي",
        ):
            with self.subTest(words):
                self.assertEqual(brokers.end_user([words]), brokers.OWN_CUSTOMERS)
        self.assertPairs(
            [
                ("I need a shop to serve my clients", "I need a shop for my client"),
                ("My clients come to my salon every day", "My client wants a shop near Dragon Mart"),
                ("I need it for client meetings", "I need it for a client"),
                ("I need a bigger shop for my clients, I have a salon", "I need a bigger shop for my clients, I am an agent"),
                ("Parking for my clients is important", "Parking for my client is important"),
                # Theirs ("my", "our") only: "parking for customers" may be a broker's client's (review F5).
                ("The location is good for my clients", "The location is good for my client"),
            ],
            facts={"for_client": True},
        )

    def test_family_a_friend_or_a_partner(self):
        for words in (
            "Yes, I need one more for my brother's salon", "Yes, I need one more for my brother", "My friend needs one, I will let you know",
            "My partner and I need a shop", "It is for my wife's boutique", "mere bhai ke liye", "لأخي",
        ):
            with self.subTest(words):
                self.assertEqual(brokers.end_user([words]), brokers.FAMILY)
        self.assertPairs(
            [
                # Eval shops-rented-licence-no: "for my brother's salon" is an end user, facts.for_client false.
                ("Yes, I need one more for my brother's salon", "Yes, I need one more for my client's salon"),
                # Eval shops-rented-friend-63: someone they know is a referral, never a broker of code's.
                ("My friend needs one, I will let you know", "My client needs one, I will let you know"),
                # Their own word as an agent beats a partner or a brother named beside it.
                ("My partner and I need a shop", "I am an agent, my partner and I need a shop for a client"),
                ("mere bhai ke liye", "mere client ke liye"),
                ("لأخي", "لعميلي"),
            ],
            facts={"for_client": True},
        )

    def test_client_only_in_words_about_us(self):
        for words in ("Who is your client?", "Who is ur client?", "Which client?", "Are you an agent?", "What do you mean, for a client?"):
            with self.subTest(words):
                self.assertEqual(brokers.end_user([words]), brokers.ABOUT_US)
        self.assertPairs(
            [
                ("Who is your client?", "My client is a restaurant owner"), ("Who is ur client?", "client ke liye ur 400 sqft chahiye"),
                ("Which client?", "Client"), ("Are you an agent?", "I am an agent"),
            ],
            facts={"for_client": True},
        )

    def test_nothing_in_their_words_leaves_the_models_for_client(self):
        for words in ("He needs a shop around 500 sq ft", "Type 2 please", "Do you share commission?", "I am looking for a shop for my boss"):
            with self.subTest(words):
                self.assertEqual(brokers.end_user([words]), "")
                self.assertHanded(words, by=brokers.FACTS, facts={"for_client": True})


# C. The backstop on the answer -------------------------------------------------------------------------------------------


class BackstopTests(BrokerBase):
    def test_the_facts_only_when_new_this_turn(self):
        self.assertHanded("Type 2 please", by=brokers.FACTS, facts={"for_client": True}, known={"for_client": False})
        self.assertHanded("Type 2 please", by=brokers.FACTS, facts={"for_client": True}, known={})
        # Known already: the turn that learned it was the one to hand over; later turns repeat KNOWN FACTS.
        self.assertNotHanded("Type 2 please", facts={"for_client": True}, known={"for_client": True})
        self.assertNotHanded("Type 2 please", facts={"for_client": False})

    def test_the_facts_never_replace_a_handover_of_the_models(self):
        done, answer = hand("Is there a gas line for a restaurant?", facts={"for_client": True}, handover="legal_visa_licence_contract")
        self.assertEqual((done, answer["handover"]["reason"]), ("", "legal_visa_licence_contract"))
        self.assertHanded("Is there a gas line for a restaurant?", by=brokers.FACTS, facts={"for_client": True})

    def test_their_words_over_a_weaker_handover(self):
        # A must-answer "legal" handover people.settle would lift (the chat goes on, MUST_ANSWER_PAUSES False): a broker.
        for reason in ("legal_visa_licence_contract", "price_or_details_insisted", "unclear", "media_received", "abroad_cannot_visit"):
            with self.subTest(reason):
                self.assertHanded("I am a broker. What is the deposit?", handover=reason)
        with patch.object(brokers, "OVER_WEAKER", False):
            self.assertNotHanded("I am a broker. What is the deposit?", handover="legal_visa_licence_contract")
        self.assertHanded("I am a broker. What is the deposit?")

    def test_never_over_a_call_a_person_or_a_complaint(self):
        self.assertEqual(set(brokers.KEEPS) | {brokers.REASON}, set(people._STRONGER))
        for reason in brokers.KEEPS:
            with self.subTest(reason):
                done, answer = hand("I am a broker, please call me", handover=reason)
                self.assertEqual((done, answer["handover"]["reason"]), ("", reason))
        self.assertHanded("I am a broker, please call me")

    def test_the_models_own_tag_is_left_as_it_is(self):
        done, answer = hand(SCENARIO_WORDS, handover=engine.BROKER, facts=GATE_FACTS)
        self.assertEqual(done, "")
        self.assertNotIn("broker_backstop", answer)
        self.assertHanded(SCENARIO_WORDS, facts=GATE_FACTS)

    def test_never_over_an_opt_out(self):
        for kind in ("not_interested", "stop_all", "wrong_number", "spam"):
            with self.subTest(kind):
                self.assertNotHanded("I am an agent, my client found a shop already", opt_out=kind, facts={"for_client": True})
        self.assertHanded("I am an agent, my client found a shop already", facts={"for_client": True})

    def test_never_in_a_chat_labelled_broker_and_the_label_is_asked_only_when_it_would_act(self):
        asked = []

        def labelled():
            asked.append(True)
            return True

        self.assertNotHanded(SCENARIO_WORDS, labelled=labelled, facts=GATE_FACTS)
        self.assertNotHanded("He needs a shop around 500 sq ft", labelled=True, facts=GATE_FACTS)
        self.assertEqual(len(asked), 1)
        self.assertNotHanded("Type 2 please", labelled=labelled)
        self.assertEqual(len(asked), 1)  # nothing to hand over: no query
        self.assertHanded(SCENARIO_WORDS, labelled=lambda: False, facts=GATE_FACTS)

    def test_a_taken_slot_it_offered_is_none(self):
        # Code offers no slots around a handover (engine._code_may_act), as for the model's own tag.
        answer = shops_answer(action="tentative", place="office", date="2026-10-13", time="17:00")
        answer["slot_taken"] = True
        brokers.backstop(answer, {}, ["Tomorrow at 5 pm"])
        self.assertTrue(answer["slot_taken"])
        brokers.backstop(answer, {}, ["Tomorrow at 5 pm, I am checking for my client"])
        self.assertNotIn("slot_taken", answer)


# D. The turn -------------------------------------------------------------------------------------------------------------


class BrokerTurnBase(ShopsBase):
    def asked_for_whom(self):
        self.tap("Yes, show me shops", seconds_ago=300)
        self.ours(FOR_WHOM, minutes_ago=4)

    def assertBroker(self, message, outcome, by, line=BROKER_LINE):
        self.assertEqual(self.body(outcome), line)
        state = self.state()
        self.assertEqual(state.handover_reason, engine.BROKER)
        self.assertIsNotNone(state.paused_at)
        self.assertIsNone(state.paused_by)
        self.assertIs(state.facts["for_client"], True)
        self.assertEqual(list(self.conversation.labels.values_list("name", flat=True)), [engine.BROKER_LABEL])
        fields = self.fields()
        self.assertIn((crm_fields.FIELD_PURPOSE, str(crm_fields.PURPOSE_BROKER)), fields)
        self.assertIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_BROKER)), fields)
        alert = LeadAiAlert.objects.filter(kind="handover").order_by("-pk").first()  # the turn's own (a chat held before has one)
        self.assertIn("is a broker or asks for a client", alert.text)
        self.assertIn("stays silent in it until someone presses Resume AI", alert.text)
        actions = self.actions(message)
        self.assertEqual((actions["broker_backstop"], actions["broker"], actions["handover"]), (by, True, engine.BROKER))

    def assertNoBroker(self, message):
        """No pause, no Broker label, no Purpose or Bot Status Broker, nothing of the backstop's in the turn."""
        state = self.state()
        self.assertIsNone(state.paused_at)
        self.assertNotEqual(state.handover_reason, engine.BROKER)
        self.assertFalse(self.conversation.labels.exists())
        fields = self.fields()
        self.assertNotIn((crm_fields.FIELD_PURPOSE, str(crm_fields.PURPOSE_BROKER)), fields)
        self.assertNotIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_BROKER)), fields)
        self.assertFalse(LeadAiAlert.objects.filter(kind="handover", text__contains="is a broker or asks for a client").exists())
        self.assertNotIn("broker_backstop", self.actions(message))

    def assertServed(self, message, outcome, reply):
        self.assertEqual(self.body(outcome), reply)
        self.assertIsNone(self.state().handed_over_at)
        self.assertNoBroker(message)


class BrokerTurnTests(BrokerTurnBase):
    def test_the_scenarios_words_with_the_gates_first_answer(self):
        self.asked_for_whom()
        message = self.inbound(SCENARIO_WORDS)
        outcome, calls, _, _ = self.turn(message, [shop_answer(RUN_1, facts=GATE_FACTS)])
        self.assertEqual(len(calls), 1)
        self.assertBroker(message, outcome, brokers.WORDS)
        # Paused: the agent's next words get nothing until someone presses Resume AI.
        later = self.inbound("Hello? What is the commission?", seconds_ago=10)
        self.assertEqual(engine.run_turn(later.pk).reason, "paused until an agent presses Resume")

    def test_the_scenarios_words_with_the_gates_second_answer(self):
        self.asked_for_whom()
        message = self.inbound(SCENARIO_WORDS)
        outcome, _, _, _ = self.turn(message, [shop_answer(RUN_2, facts=GATE_FACTS)])
        self.assertBroker(message, outcome, brokers.WORDS)

    def test_the_models_for_client_alone(self):
        self.asked_for_whom()
        message = self.inbound("He needs a shop around 500 sq ft")
        outcome, _, _, _ = self.turn(message, [shop_answer(RUN_1, facts=GATE_FACTS)])
        self.assertBroker(message, outcome, brokers.FACTS)

    def test_roman_urdu_words_and_nothing_from_the_model(self):
        self.asked_for_whom()
        message = self.inbound("Client ke liye dekh raha hoon, 400 sqft chahiye")
        live = shop_answer("Theek hai. Shop kis business ke liye hai?", language="ur_latin", facts={"size_sqft": 400})
        outcome, _, _, _ = self.turn(message, [live])
        self.assertBroker(message, outcome, brokers.WORDS, line=rules.line("broker", "ur_latin"))

    def test_a_brokers_must_answer_question_is_the_brokers_hand_off(self):
        self.asked_for_whom()
        message = self.inbound("I am a broker. What is the deposit?")
        live = shop_answer("Our agent will answer the deposit for you here before the visit.", handover="legal_visa_licence_contract")
        outcome, _, _, _ = self.turn(message, [live])
        self.assertBroker(message, outcome, brokers.WORDS)
        self.assertNotIn("questions_waiting", self.actions(message))

    def test_family_goes_on_and_their_word_as_an_agent_later_hands_over(self):
        self.ours("Congratulations! Do you need a second shop, or know someone who does?", minutes_ago=4)
        family = self.inbound("Yes, I need one more for my brother")
        reply = "Great. What business will your brother's shop be for?"
        outcome, _, _, _ = self.turn(family, [shop_answer(reply, facts={"for_client": True})])
        self.assertServed(family, outcome, reply)
        self.later(3)
        message = self.inbound("Actually I am an agent, it is for my client", seconds_ago=10)
        outcome, _, _, _ = self.turn(message, [shop_answer("Great. What business will the shop be for?")])
        self.assertBroker(message, outcome, brokers.WORDS)

    def test_a_business_owner_goes_on_and_their_word_as_a_broker_later_hands_over(self):
        self.asked_for_whom()
        owner = self.inbound("For myself. I need a shop to serve my clients, I have a salon")
        reply = "A salon, got it. What size do you need?"
        outcome, _, _, _ = self.turn(owner, [shop_answer(reply, facts={"for_client": True, "business_activity": "salon"})])
        self.assertServed(owner, outcome, reply)
        self.later(3)
        message = self.inbound("Sorry, to be clear: I am a broker", seconds_ago=10)
        outcome, _, _, _ = self.turn(message, [shop_answer("Thanks for letting us know. What size does the salon need?")])
        self.assertBroker(message, outcome, brokers.WORDS)

    def test_after_resume_ai_the_labelled_chat_is_the_agents(self):
        # An agent pressed Resume AI on a broker's chat: the label stays, the assistant answers the broker.
        self.conversation.labels.add(engine.broker_label())
        self.asked_for_whom()
        message = self.inbound("I am checking for my client, can he see Type 2 tomorrow?")
        reply = "Sure. I can hold a slot for you tomorrow at 11:00 AM or 5:00 PM — which is better?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply)])
        self.assertEqual(self.body(outcome), reply)
        self.assertIsNone(self.state().paused_at)
        self.assertNotIn("broker_backstop", self.actions(message))
        # The same words in a chat with no label are a broker's.
        self.conversation.labels.clear()
        Label.objects.all().delete()
        self.later(3)
        again = self.inbound("I am checking for my client, can he see Type 2 tomorrow?", seconds_ago=10)
        outcome, _, _, _ = self.turn(again, [shop_answer(reply)])
        self.assertBroker(again, outcome, brokers.WORDS)

    def test_the_engine_calls_it_right_after_the_model_with_their_words(self):
        self.asked_for_whom()
        message = self.inbound(SCENARIO_WORDS)
        with patch.object(brokers, "backstop", wraps=brokers.backstop) as backstop:
            self.turn(message, [shop_answer(RUN_1, facts=GATE_FACTS)])
        backstop.assert_called_once()
        answer, known, texts = backstop.call_args.args
        self.assertEqual((known, texts), ({}, [SCENARIO_WORDS]))
        self.assertTrue(callable(backstop.call_args.kwargs["labelled"]))
        # Nobody holds the chat; our last line is the for-whom question (the review: held, our_last).
        self.assertEqual((backstop.call_args.kwargs["held"], backstop.call_args.kwargs["our_last"]), (False, FOR_WHOM))
        self.assertEqual(self.state().handover_reason, engine.BROKER)


class GeneralChatTests(GeneralBase):
    def test_a_general_chat_keeps_every_rule_it_had(self):
        message = self.inbound(SCENARIO_WORDS)
        reply = "Great. What size does your client need?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, facts=GATE_FACTS)])
        self.assertEqual(self.body(outcome), reply)
        self.assertIsNone(self.state().handed_over_at)
        self.assertNotIn("broker_backstop", self.actions(message))
        # In a shops chat the same answer is a broker's (ShopsBase, above): the backstop is on.
        self.assertEqual(hand(SCENARIO_WORDS, reply=reply, facts=GATE_FACTS)[0], brokers.WORDS)


# E. The eval runs it as the engine does ----------------------------------------------------------------------------------


def run_eval(scenario_id, completion):
    scenario = next(s for s in leadai_eval.SCENARIOS if s.id == scenario_id)
    with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion), override_settings(LEADAI_OPENAI_API_KEY="test"):
        return leadai_eval.run_once(scenario, scenario_id)


class BrokerEvalTests(SimpleTestCase):
    def test_shops_broker_passes_with_the_gates_answers(self):
        for reply in (RUN_1, RUN_2):
            with self.subTest(reply=reply[-40:]):
                run = run_eval("shops-broker", eval_answer(reply, facts=GATE_FACTS))
                self.assertEqual(run.failures, [])
                self.assertEqual((run.out_by, run.out), (leadai_eval.CODE, BROKER_LINE))
                self.assertEqual(run.answer["broker_backstop"], brokers.WORDS)

    def test_the_eval_calls_it_as_the_engine_does(self):
        with patch.object(brokers, "backstop", wraps=brokers.backstop) as backstop:
            run = run_eval("shops-broker", eval_answer(RUN_1, facts=GATE_FACTS))
        backstop.assert_called_once()
        _, known, texts = backstop.call_args.args
        self.assertEqual((known, texts), ({}, [SCENARIO_WORDS]))
        self.assertNotIn("labelled", backstop.call_args.kwargs)  # no scenario carries the Broker label
        # As live: whether a person holds the chat, and our last line (the review: held, our_last).
        self.assertEqual((backstop.call_args.kwargs["held"], backstop.call_args.kwargs["our_last"]), (False, FOR_WHOM))
        # Right after untag_need, before settle: settle made the handover the build pack's line, as live.
        self.assertEqual((run.answer["handover"]["reason"], run.answer.get("converted")), (engine.BROKER, "broker"))

    def test_the_friends_referral_stays_the_models(self):
        # Eval shops-rented-friend-63: "My friend needs one" is a referral; code hands over nobody for it, whatever the
        # model's for_client says (the model's own tag would stand: its handover is loose there).
        reply = "That's great! Your friend is welcome to message us here, and we'll help them find the right shop."
        facts = {"already_rented": True, "for_client": True, "property_type": "shop", "intent": "rent", "customer_name": "Jerin"}
        run = run_eval("shops-rented-friend-63", eval_answer(reply, facts=facts))
        self.assertEqual(run.failures, [])
        self.assertFalse(run.answer["handover"]["needed"])
        self.assertEqual(run_eval("shops-broker", eval_answer(RUN_1, facts=GATE_FACTS)).failures, [])


# F. The review (2026-10-17) -----------------------------------------------------------------------------------------------
# Each finding's own inputs, as the review wrote them, beside the broker's words they differ from.

PRICE_LINE = "Type 1 shops are 400-550 sq ft, from AED 33,000 a year. What licence do you have?"
VISIT_TODAY = "See you at 1:55 PM. If anything changes, just message me here."
# What a chat knows, or the answer says, that makes them the end user (brokers.told_end_user).
END_USER_CHATS = ({"known": {"for_client": False}}, {"known": {"business_activity": "salon"}}, {"facts": {"for_client": False}})


class OurAgentTests(BrokerBase):
    """F1: talk about our agent is no "I am an agent"; in a chat a person holds only "I am / we are a broker" counts."""

    PAIRS = [
        # "<I'm | I am | this is> <a word or two>, agent": an article or a real-estate kind, and the clause ends there.
        ("I'm here, agent not here", "I'm here, I am an agent"),
        ("I am waiting, agent didn't come", "I am Sana, a real estate agent"),
        ("I am waiting, agent hasn't come yet", "I am Sana, a broker."),
        ("I'm here, agent?", "I'm Ali, an agent at Betterhomes"),
        ("I'm late, agent please wait", "I'm late, I am a broker"),
        ("This is Rahul, agent Khurram gave me your number", "This is Rahul, a real estate agent"),
        ("im at work, agent call me after 6", "im a real estate agent, call me after 6"),
        # "agent here" opens the message and is no question.
        ("I reached the office. Agent here?", "Agent here, do you share commission?"),
        ("Agent here?", "Agent here. What is the rent?"),
        # Roman Urdu: "mein", "me", "mn" and "mai ... hai" say "in".
        ("Office mein agent hai?", "Main agent hoon"),
        ("office me agent hai kya", "main broker hoon, office kahan hai?"),
        ("abhi shop mein broker hai?", "hum broker hain"),
        ("office mai agent hai", "mai agent hu"),
        ("office mn agent hai?", "main property dealer hoon"),
        ("آفس میں ایجنٹ ہے؟", "میں بروکر ہوں"),
    ]

    def test_our_agent_is_none_of_theirs(self):
        self.assertPairs(self.PAIRS)
        # A booked customer's chat knows for_client false: their words about our agent stay theirs there too.
        for words, _ in self.PAIRS:
            with self.subTest(end_user_chat=words):
                self.assertNotHanded(words, known={"for_client": False})

    def test_a_chat_a_person_holds_counts_i_am_a_broker_only(self):
        self.assertNotHanded("I'm outside, agent not picking up", held=True)
        self.assertNotHanded("I'm outside, agent not picking up", held=True, handover="unclear")
        # Words that hand over a chat nobody holds.
        for words in ("My client wants Type 2", "for a client", "Broker here, any update?"):
            with self.subTest(words):
                self.assertNotHanded(words, held=True)
                self.assertHanded(words)
        self.assertNotHanded("Agent", held=True, our_last=FOR_WHOM)
        self.assertHanded("Agent", our_last=FOR_WHOM)
        # Never the model's for_client in a held chat.
        self.assertNotHanded("Type 2 please", held=True, facts={"for_client": True})
        self.assertHanded("Type 2 please", by=brokers.FACTS, facts={"for_client": True})
        for words in ("I am an agent, my client wants Type 2", "We are a brokerage", "main broker hoon", "أنا وسيط عقاري"):
            with self.subTest(explicit=words):
                self.assertHanded(words, held=True)


class OwnClientTests(BrokerBase):
    """F2: a business owner's own client (at a time, coming, with them now, awaited, their parking) is no broker's; and
    where the answer or the chat says they are the end user, only "I am / we are a broker" counts."""

    def test_an_owners_own_client(self):
        self.assertPairs(
            [
                ("I have a client at 3, can I come at 5?", "I have a client looking for a shop, can I come at 5?"),
                ("I have a client appointment at 3, can I come at 5?", "I have a client, can I come at 5?"),
                ("I have a client call at 4, can we meet at 6?", "I have a client, can we meet at 6?"),
                ("I have a client coming at 4, can we meet at 6?", "I have a client who wants Type 2, can we meet at 6?"),
                ("I have a client now, call me later", "I have a client, call me later"),
                ("Sorry, my client is here, I'll reply later", "Sorry, my client is interested, I'll reply later"),
                ("my client is waiting, talk later", "my client wants Type 2, talk later"),
                ("Waiting for client now", "Checking for client now"),
                ("I'm waiting for a client, will call you", "I'm checking for a client, will call you"),
                ("Need parking for client", "Need a shop for client"),
                ("Parking for client is must", "A shop for client is must"),
                ("I have many clients who live in International City", "I have many clients who need shops in International City"),
                (
                    "I have a travel agency, I need a shop near the road for my clients",
                    "I have a real estate agency, I need a shop near the road for my clients",
                ),
                ("I have a beauty center, I need a shop on the main road for my clients", "I need a shop on the main road for my clients"),
                ("mere client ko parking chahiye", "mere client ko shop chahiye"),
                ("client ke liye parking chahiye", "client ke liye shop chahiye"),
                ("mere client IC mein rehte hain", "mere client ko IC mein shop chahiye"),
                ("معي عميل الحين", "معي عميل يبحث عن محل"),
                ("عندي زبون الحين، اكلمك بعدين", "عندي زبون يبحث عن محل"),
                ("أحتاج محل مناسب لعملائي", "أحتاج محل لعميلي"),
            ]
        )

    def test_where_they_are_the_end_user_only_i_am_a_broker_counts(self):
        for chat in END_USER_CHATS:
            with self.subTest(**{key: str(value) for key, value in chat.items()}):
                for words in ("My client wants Type 2", "for a client", "Broker here, any discount?", "I'm from Betterhomes"):
                    self.assertNotHanded(words, **chat)
                self.assertNotHanded("Agent", our_last=FOR_WHOM, **chat)
                self.assertHanded("Sorry, to be clear: I am a broker", **chat)
        for words in ("My client wants Type 2", "for a client", "Broker here, any discount?", "I'm from Betterhomes"):
            with self.subTest(nothing_known=words):
                self.assertHanded(words)
        # A mind changed later still reaches the model's own for_client: that turn learned it (FACTS).
        self.assertHanded("Actually it is for my client", by=brokers.FACTS, known={"for_client": False}, facts={"for_client": True})

    def test_for_myself_in_the_burst(self):
        self.assertPairs(
            [
                ("For myself. I need a shop with good visibility for my clients", "For my client. I need a shop with good visibility"),
                (["For myself", "my client is a restaurant owner"], ["For my client", "he is a restaurant owner"]),
                ("It's for me, my client meetings are here", "It's for my client"),
                ("apne liye, mere client ko bhi shop chahiye", "mere client ko shop chahiye"),
                ("لي شخصياً، عميلي يريد محل أيضاً", "عميلي يريد محل"),
            ]
        )
        self.assertEqual(brokers.end_user(["For myself"]), brokers.SELF)
        self.assertHanded("For myself. I am a broker, my client wants Type 2")
        # Never "not for myself", "apne liye nahi", nor "for me" inside another ask.
        for words in ("For a client, not for myself", "client ke liye, apne liye nahi", "Please hold 5 PM for me, I am checking for my client"):
            with self.subTest(words):
                self.assertFalse(brokers.self_words([words]))
                self.assertHanded(words)


class TheirQuestionsTests(BrokerBase):
    """F3: a question mark, or a "you" after the word, is no words about us (brokers ask); "you" or "your" before the
    word, in a phrase about us, is."""

    QUESTIONS = (
        "Any shop for client?", "Do you have Type 2 for a client", "Do u have shop for client", "Is there any discount for client?",
        "Can I see the shop with my client?", "Can I come with my client at 5?", "Ok, I will share with my client and let you know",
        "Will share with my client and get back to you", "Do you share commission with agents?", "Do you work with brokers?",
    )

    def test_their_questions_with_the_models_for_client(self):
        for words in self.QUESTIONS:
            with self.subTest(words):
                self.assertEqual(brokers.end_user([words]), "")
                done, answer = hand(words, facts={"for_client": True})
                self.assertIn(done, (brokers.FACTS, brokers.WORDS))
                self.assertEqual(answer["handover"], {"needed": True, "reason": engine.BROKER})
        # The model's for_client alone hands these over (FACTS); with nothing from the model, nothing from code.
        for words in ("Is there any discount for client?", "Do you share commission with agents?", "Do you work with brokers?"):
            with self.subTest(facts_only=words):
                self.assertNotHanded(words)
                self.assertHanded(words, by=brokers.FACTS, facts={"for_client": True})
        # Their own request for a client, or what they do with theirs, is theirs whatever the model says.
        for words in ("Any shop for client?", "Do you have Type 2 for a client", "Do u have shop for client", "Can I come with my client at 5?"):
            with self.subTest(words_only=words):
                self.assertHanded(words)

    def test_words_about_us_say_you_before_the_word(self):
        for words in (
            "Who is your client?", "Can your agent call me?", "Are you an agent?", "r u agent", "Are you checking for a client?",
            "What do you mean, for a client?", "Which client?", "client?", "aap ka client kaun hai?", "Are you working as a broker?",
        ):
            with self.subTest(words):
                self.assertEqual(brokers.end_user([words]), brokers.ABOUT_US)
        # "you" before the word in a phrase about us, or in one of theirs (the model's for_client then hands over).
        self.assertPairs(
            [
                ("Are you an agent?", "Do you work with agents?"), ("Who is your client?", "Is there any discount for client?"),
                ("Are you working as a broker?", "Do you share commission with brokers?"), ("Can your agent call me?", "Can agents get commission?"),
            ],
            by=brokers.FACTS,
            facts={"for_client": True},
        )


class NotAsABrokerTests(BrokerBase):
    """F4: a no, a fee or a past before "as a broker" (and before every other way of saying it)."""

    def test_a_no_a_fee_or_a_past(self):
        self.assertPairs(
            [
                ("I'm asking for myself, not as an agent", "I'm asking as an agent"),
                ("Not as an agent, for myself", "As an agent, for my client"),
                ("For my own business, not as a broker", "As a broker, for a client"),
                ("Treat me as a customer, not as an agent", "Treat me as an agent"),
                ("I used to work as a broker, now I want to open my own shop", "I work as a broker, my client wants a shop"),
                ("I was working as an agent before, now I want my own shop", "I am working as an agent, my client wants a shop"),
                ("How much I pay as broker commission", "As a broker, how much commission do you pay?"),
                ("Do I need to pay anything as broker fee?", "As a broker, do I need to pay anything?"),
                ("What's the commission as broker?", "As a broker, what's the commission?"),
                ("5% as agent fee is too much", "As an agent, 5% is too much"),
                ("I never said I am a broker", "I said I am a broker"),
            ]
        )
        # "No" opening the clause answers our question.
        self.assertHanded("No I am an agent")
        self.assertNotHanded("No I am not an agent")


class TheirClientsCustomersTests(BrokerBase):
    """F5: a broker's words of his client's business ("parking for customers") never take back his client words; a
    business owner's words count clause by clause, and theirs ("my", "our") only."""

    BURSTS = (
        ["My client needs a shop with parking for customers"], ["I'm looking for a shop for my client, parking for customers is a must"],
        ["For my client, he wants space for customers to sit"], ["my client needs a big shop to serve customers"],
        ["My client wants a shop near main road, easy for customers"],
        ["I have a client looking for a shop", "He has a restaurant, needs seating for customers"],
    )

    def test_a_brokers_words_of_his_clients_customers(self):
        for words in self.BURSTS:
            with self.subTest(words):
                self.assertFalse(brokers.own_customers(words))
                self.assertEqual(brokers.end_user(words), "")
                self.assertHanded(words, facts={"for_client": True})
                self.assertHanded(words)

    def test_clause_by_clause_and_theirs_only(self):
        self.assertPairs(
            [
                # "my customers" is theirs; "customers" may be a client's.
                (["client ke liye shop chahiye", "parking for my customers bhi"], ["client ke liye shop chahiye", "parking for customers bhi"]),
                # Two messages are no one phrase: "The location is good" and "for my clients, ..." are no owner's "good for
                # my clients".
                (["The location is good for my clients"], ["The location is good", "for my clients, what sizes do you have?"]),
            ]
        )


class MoreBrokerWordsTests(BrokerBase):
    """F6: more ways a broker says it, under the same guards (a no; only "I am / we are a broker" where they are the
    end user)."""

    BROKERS = (
        "Hi This is Neeta here from AR Properties. We got your query on bayut that you were looking for a property. Are you still "
        "looking for that ?",
        "This is Ali from Prime Properties, do you have shops for rent?", "Hi, Ali from Betterhomes here", "I'm from Betterhomes",
        "Am broker", "am an agent", "We r agents", "My customer needs 500 sqft shop", "For my customer", "I have a tenant for your shop",
        "I have a party looking for a shop", "customer ke liye dekh raha hoon", "main dealer hoon", "I will bring my client at 5pm",
        "I'll come with my client tomorrow at 11",
    )
    EXPLICIT = ("Am broker", "am an agent", "We r agents", "main dealer hoon")

    def test_more_ways_a_broker_says_it(self):
        for words in self.BROKERS:
            with self.subTest(words):
                self.assertHanded(words)
        self.assertPairs(
            [
                ("This is Ali from Dubai, do you have shops for rent?", "This is Ali from Prime Properties, do you have shops for rent?"),
                ("Hi, Ali from Karachi here", "Hi, Ali from Betterhomes here"),
                ("I'm from Pakistan", "I'm from Betterhomes"),
                ("I am from the property next door", "I am from Prime Properties"),
                ("This is Ahmed from Dubai looking for property", "This is Ahmed from Dubai Properties"),
                ("I'm with family looking for property", "I'm with Allsopp & Allsopp"),
                ("am looking for studio", "Am broker"),  # launch chat 57 drops the "I" too
                ("AM NOT LOOKING FOR SHOPS", "am an agent"),  # launch chat 136
                ("We r looking for a shop", "We r agents"),
                ("My customers need parking", "My customer needs 500 sqft shop"),
                ("For my customers to visit", "For my customer"),
                ("I have a tenant", "I have a tenant for your shop"),
                ("I have a party tonight, talk tomorrow", "I have a party looking for a shop"),
                ("customer ke liye parking chahiye", "customer ke liye dekh raha hoon"),
                ("main car dealer hoon", "main dealer hoon"),
                ("I will bring my wife at 5pm", "I will bring my client at 5pm"),
                ("I'll come with my brother tomorrow at 11", "I'll come with my client tomorrow at 11"),
            ]
        )

    def test_under_the_same_guards(self):
        self.assertNotHanded("I will not bring my client")
        self.assertNotHanded("Am broker?")
        for chat in END_USER_CHATS:
            for words in self.BROKERS:
                with self.subTest(words=words, **{key: str(value) for key, value in chat.items()}):
                    if words in self.EXPLICIT:
                        self.assertHanded(words, **chat)
                    else:
                        self.assertNotHanded(words, **chat)


class AloneAgentTests(BrokerBase):
    """F7: "Agent" or "Broker" alone answers our for-whom question only; after our price line it may ask for a person."""

    def test_a_bare_agent_answers_our_for_whom_question_only(self):
        for words in ("Agent", "Broker", "agent.", "Yes, broker", "وسيط", "एजेंट"):
            with self.subTest(words):
                self.assertNotHanded(words)
                self.assertNotHanded(words, our_last=PRICE_LINE)
                done, answer = hand(words, our_last=PRICE_LINE, handover="unclear")
                self.assertEqual((done, answer["handover"]["reason"]), ("", "unclear"))
                self.assertHanded(words, our_last=FOR_WHOM)
        # The nudge that asks it again, the model's own words around it, any question of ours about a client.
        self.assertHanded("Agent", our_last=nudges.first_text("en", "Ali", for_whom=True, now=NOW))
        self.assertHanded("Agent", our_last="Is the shop for your own business, or for a client?")
        self.assertHanded("Broker", our_last=rules.line("for_whom", "ar"))
        self.assertNotHanded("Agent?", our_last=FOR_WHOM)
        # "Client" alone names someone else's client wherever it comes.
        self.assertHanded("Client", our_last=PRICE_LINE)


class ReviewTurnTests(BrokerTurnBase):
    """The review's own full turns: what goes out, the pause, the label and the lead's fields. Each end user's turn goes
    on, and their word as a broker later hands over (so each test fails with the backstop switched off too)."""

    def visit_today(self, **facts):
        self.set_state(facts={"for_client": False, "business_activity": "grocery", **facts})
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", starts_at=NOW - dt.timedelta(minutes=5))
        self.ours(VISIT_TODAY, minutes_ago=60)

    def then_a_broker(self, words="Sorry, to be clear: I am a broker", line=BROKER_LINE, **model):
        self.later(3)
        message = self.inbound(words, seconds_ago=10)
        outcome, _, _, _ = self.turn(message, [shop_answer(MODELS_QUESTION, **model)])
        self.assertBroker(message, outcome, brokers.WORDS, line=line)

    def test_f1_a_booked_customer_at_our_office(self):
        self.visit_today()
        message = self.inbound("I'm here, agent not here")
        reply = "Sorry for the wait. Our agent will be with you in a few minutes."
        outcome, _, _, _ = self.turn(message, [shop_answer(reply)])
        self.assertServed(message, outcome, reply)
        self.then_a_broker("Actually I am an agent, the shop is for my client")

    def test_f1_roman_urdu_is_an_agent_at_the_office(self):
        self.set_state(facts={"for_client": False})
        self.ours(TWO_SLOTS_NOW, minutes_ago=4)
        message = self.inbound("Office mein agent hai?")
        reply = "Ji, hamara agent office mein hota hai. Aap kis waqt aana chahenge?"
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, language="ur_latin")])
        self.assertServed(message, outcome, reply)
        self.then_a_broker("Main bhi agent hoon, client ke liye dekh raha hoon", line=rules.line("broker", "ur_latin"), language="ur_latin")

    def test_f1_a_chat_a_colleague_holds(self):
        self.visit_today()
        self.set_state(handed_over_at=NOW - dt.timedelta(hours=1), handover_reason="call_requested")
        self.ours("Our agent will call you.", minutes_ago=50)
        message = self.inbound("I'm outside, agent not picking up")
        with patch.object(brokers, "backstop", wraps=brokers.backstop) as backstop:
            self.turn(message, [shop_answer("Our agent will reply to you here shortly.", facts={"for_client": True})])
        self.assertIs(backstop.call_args.kwargs["held"], True)
        self.assertEqual(self.state().handover_reason, "call_requested")
        self.assertNoBroker(message)
        # In the same held chat, "I am a broker" still counts.
        self.later(3)
        again = self.inbound("I am a broker, my client wants Type 2", seconds_ago=10)
        self.turn(again, [shop_answer("Our agent will reply to you here shortly.")])
        self.assertHeldBroker(again)

    def assertHeldBroker(self, message):
        """A broker in a chat a person held already: labelled and paused, with Purpose and Bot Status Broker (the chat
        keeps the reason it was first handed over for, engine._apply)."""
        actions = self.actions(message)
        self.assertEqual((actions.get("broker_backstop"), actions.get("broker"), actions.get("handover")), (brokers.WORDS, True, engine.BROKER))
        self.assertIsNotNone(self.state().paused_at)
        self.assertEqual(list(self.conversation.labels.values_list("name", flat=True)), [engine.BROKER_LABEL])
        self.assertIn((crm_fields.FIELD_PURPOSE, str(crm_fields.PURPOSE_BROKER)), self.fields())
        self.assertIn((crm_fields.FIELD_BOT_STATUS, str(crm_fields.STATUS_BROKER)), self.fields())

    def test_f2_a_salon_owner_books_around_her_own_client(self):
        self.set_state(facts={"for_client": False, "business_activity": "salon"})
        self.ours(TWO_SLOTS_NOW, minutes_ago=4)
        message = self.inbound("I have a client at 3, can I come at 5?")
        self.turn(message, [shop_answer("", action="confirm", place="office", date="2026-10-12", time="17:00")])
        self.assertEqual(LeadAiAppointment.objects.get(conversation=self.conversation).starts_at, at(12, 17))
        self.assertEqual(LeadAiAppointment.objects.get(conversation=self.conversation).status, LeadAiAppointment.Status.CONFIRMED)
        self.assertNoBroker(message)
        self.then_a_broker()

    def test_f2_an_arabic_owner_busy_with_a_customer(self):
        self.set_state(facts={"for_client": False, "business_activity": "bakery"})
        self.ours(TWO_SLOTS_NOW, minutes_ago=4)
        message = self.inbound("عندي زبون الحين، اكلمك بعدين")
        reply = "تمام، خذ راحتك. نحن هنا متى ما احتجت."
        outcome, _, _, _ = self.turn(message, [shop_answer(reply, language="ar")])
        self.assertServed(message, outcome, reply)
        self.then_a_broker("أنا وسيط عقاري", line=rules.line("broker", "ar"), language="ar")

    def test_f2_for_myself_and_my_clients(self):
        self.asked_for_whom()
        message = self.inbound("For myself. I need a shop with good visibility for my clients")
        outcome, _, _, _ = self.turn(message, [shop_answer(MODELS_QUESTION, facts={"for_client": False})])
        self.assertNoBroker(message)
        self.assertIs(self.state().facts["for_client"], False)
        self.then_a_broker()

    def test_f3_their_questions_with_the_models_for_client(self):
        message = self.inbound("Any shop for client?")
        outcome, _, _, _ = self.turn(message, [shop_answer(RUN_1, facts={"for_client": True})])
        self.assertBroker(message, outcome, brokers.WORDS)
        self.later(3)
        self.conversation.labels.clear()
        Label.objects.all().delete()
        self.set_state(paused_at=None, handed_over_at=None, handover_reason="", facts={"business_activity": "restaurant"})
        LeadAiAlert.objects.all().delete()
        self.ours("Type 2 shops are 600-800 sq ft, from AED 48,000 a year.", minutes_ago=1)
        again = self.inbound("Ok, I will share with my client and let you know", seconds_ago=10)
        reply = "Sure. Would you like to visit our office to see the shops?"
        outcome, _, _, _ = self.turn(again, [shop_answer(reply, facts={"for_client": True})])
        self.assertBroker(again, outcome, brokers.FACTS)

    def test_f4_not_as_an_agent_and_the_commission(self):
        self.asked_for_whom()
        message = self.inbound("I'm asking for myself, not as an agent")
        outcome, _, _, _ = self.turn(message, [shop_answer(MODELS_QUESTION, facts={"for_client": False})])
        self.assertNoBroker(message)
        self.later(3)
        self.set_state(facts={"for_client": False, "business_activity": "laundry"})
        self.ours(PRICE_LINE, minutes_ago=1)
        again = self.inbound("How much I pay as broker commission", seconds_ago=10)
        owner_line = "We charge the normal commission. Please come and see the shops first, then we will discuss the details."
        outcome, _, _, _ = self.turn(again, [shop_answer(owner_line)])
        self.assertServed(again, outcome, owner_line)
        self.then_a_broker("Sorry, I should say: we are a brokerage")

    def test_f5_a_broker_describes_his_clients_customers(self):
        self.asked_for_whom()
        message = self.inbound("My client needs a shop with parking for customers")
        outcome, _, _, _ = self.turn(message, [shop_answer(RUN_1, facts={"for_client": True})])
        self.assertBroker(message, outcome, brokers.WORDS)

    def test_f6_am_broker_and_the_model_sets_nothing(self):
        self.asked_for_whom()
        message = self.inbound("Am broker")
        outcome, _, _, _ = self.turn(message, [shop_answer(MODELS_QUESTION)])
        self.assertBroker(message, outcome, brokers.WORDS)

    def test_f7_a_bare_agent_after_our_price_line_is_the_models(self):
        self.ours(PRICE_LINE, minutes_ago=4)
        message = self.inbound("Agent")
        self.turn(message, [shop_answer("Our agent will reply to you here.", handover="unclear")])
        self.assertEqual(self.state().handover_reason, "unclear")
        self.assertNoBroker(message)
        # The chat a person now holds: "I am a broker" still counts.
        self.later(3)
        again = self.inbound("I am a broker", seconds_ago=10)
        self.turn(again, [shop_answer("Our agent will reply to you here.")])
        self.assertHeldBroker(again)

    def test_f7_a_bare_agent_answering_our_for_whom_question(self):
        self.asked_for_whom()
        message = self.inbound("Agent")
        with patch.object(brokers, "backstop", wraps=brokers.backstop) as backstop:
            outcome, _, _, _ = self.turn(message, [shop_answer(MODELS_QUESTION)])
        self.assertEqual(backstop.call_args.kwargs["our_last"], FOR_WHOM)
        self.assertBroker(message, outcome, brokers.WORDS)


def mirror(new, completion, chat=(leadai_eval.SHOPS_YES, leadai_eval.FOR_WHOM), **fields):
    """The eval's run of a shops scenario of the review's own words (built here, in no list of the eval's)."""
    scenario = leadai_eval.Scenario(
        "review-broker", "the review's words", new=list(new), chat=list(chat), playbook=leadai_eval.IC_SHOPS, campaign=leadai_eval.SHOPS_A,
        **fields,
    )
    with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion), override_settings(LEADAI_OPENAI_API_KEY="test"):
        return leadai_eval.run_once(scenario, scenario.id)


class ReviewEvalTests(SimpleTestCase):
    """The eval mirror reads the held chat (F1) and our last line (F7) as live, and the review's words as the engine does."""

    def assertBrokerRun(self, run, by=brokers.WORDS):
        self.assertEqual((run.answer["handover"]["reason"], run.answer.get("broker_backstop")), (engine.BROKER, by))
        self.assertEqual((run.out_by, run.out), (leadai_eval.CODE, BROKER_LINE))

    def assertNoBrokerRun(self, run):
        self.assertNotEqual(run.answer["handover"].get("reason"), engine.BROKER)
        self.assertNotIn("broker_backstop", run.answer)

    def test_f1_a_chat_a_person_holds(self):
        reply = "Great. What size does your client need?"
        self.assertBrokerRun(mirror(["My client wants Type 2"], eval_answer(reply, facts={"for_client": True})))
        held = mirror(["My client wants Type 2"], eval_answer(reply, facts={"for_client": True}), handed_over="yes (call_requested)")
        self.assertNoBrokerRun(held)
        explicit = mirror(["I am an agent, my client wants Type 2"], eval_answer(reply), handed_over="yes (call_requested)")
        self.assertEqual(explicit.answer["broker_backstop"], brokers.WORDS)

    def test_f7_a_bare_agent(self):
        self.assertBrokerRun(mirror(["Agent"], eval_answer(MODELS_QUESTION)))
        after_price = mirror(
            ["Agent"], eval_answer("Our agent will reply to you here.", handover="unclear"),
            chat=(leadai_eval.SHOPS_YES, leadai_eval.FOR_WHOM, leadai_eval.FOR_MYSELF, ("assistant", PRICE_LINE)),
        )
        self.assertNoBrokerRun(after_price)
        self.assertEqual(after_price.answer["handover"]["reason"], "unclear")

    def test_the_reviews_words_as_the_engine_reads_them(self):
        # F2: a salon owner's chat; F3: a question with the model's for_client; F6: "Am broker".
        salon = {"for_client": False, "business_activity": "salon"}
        self.assertNoBrokerRun(mirror(["I have a client at 3, can I come at 5?"], eval_answer(MODELS_QUESTION), facts=salon))
        self.assertBrokerRun(mirror(["Do you work with brokers?"], eval_answer(MODELS_QUESTION, facts={"for_client": True})), by=brokers.FACTS)
        self.assertBrokerRun(mirror(["Am broker"], eval_answer(MODELS_QUESTION)))
