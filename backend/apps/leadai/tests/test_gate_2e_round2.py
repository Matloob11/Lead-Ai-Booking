"""Batch 2e's real-model gate, round 2 (2026-10-17, on the server's build context at 3f7ba05): 559 of 574 runs passed (97.4%),
the model-written ones 291 of 304 (95.7%), and the gate failed only on its rule that every CODE, money and policy scenario
passes every run. Each failing run is held here with the scenario's own customer words and the model's answer as the round-2
log recorded it (eval2e_round2.log), passes for its cause, and fails again with that fix switched off (the scratchpad's
r2/guards_off.py switches each off in the source, in turn):

- A. Our office's own address is no shop talk: code's "Our office location: Russia Cluster, Building V03, Shop 20, ..." under
  the rent track's invitation failed shops-res-any-cluster and shops-res-book-tap-template-b as shop talk. A check correction
  (leadai_eval.no_shop_words reads each sentence without our address), and the guards that cut the same sentence of the
  model's (residential.drop_shop_words; 2d's needs.drop_shop_pitch) read it without our address too (filters.without_office).
- B. The cluster before who will stay and before the invitation (residential.cluster_first): shops-res-cluster-unknown got two
  slots in run 1 and "Will it be just for yourself?" in run 2, and the cluster was never asked.
- C. Whose name goes on the contract, for a company stay or a shared one (residential.contract_line_kind): shops-res-company-
  staff was invited with no word of the contract, both runs.
- D. A broker on the rent track (brokers.backstop's ``track``): "Book 6 pm for my client Ahmed Khan" with the model's
  for_client false (from "For myself" earlier) booked a confirmed viewing, both runs of shops-res-broker-books.
- E. A template yes on a known rent or sale track gets that track's next step from code (engine.reads_first_yes), and the
  model's need tag never moves a known home on a bare yes (tracks.template_yes): shops-res-yes-to-shops-template moved a
  studio seeker to the shop track, both runs.
- F. The commission's figure asked ("how much exactly?" after code's first line) asks no other charge (residential.asked_charges),
  and code's lines go out whole under the reply's limit (residential._fit): shops-res-commission-how-much-exactly ran 966-972
  characters and lost code's figure line.
- G. Photos asked for with a sales call booked (sales.asks_call): the model's call_requested is the booked call, never a
  request for another: shops-sale-photos-call-booked run 2 offered a second call, at their own 5:00 PM.
- H. shops-same-day-window-96 is EITHER, not CODE: code books a window only over the model's tentative; run 2 recorded none.

The clock is Monday 12 October 2026, 14:00 Dubai; the chat is test_shops_playbook's (lead 555).
"""

import dataclasses
import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.leadai import ic_templates
from apps.leadai.assistant import brokers, engine, filters, hours, needs, people, residential, sales, schema, tracks
from apps.leadai.management.commands import leadai_eval
from apps.leadai.models import LeadAiAppointment
from apps.leadai.tests.test_eval_command import RIGHT, scenario
from apps.leadai.tests.test_eval_command import answer as shops_answer
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import RentBase, res_answer
from apps.leadai.tests.test_sales_calls import BUYER, BUYER_LINE, at
from apps.leadai.tests.test_who_the_customer_is import NotAShopBase

ADDRESS = leadai_eval.ADDRESS
HONESTY = "I'm AR Properties' virtual assistant — I can help with options and viewings, and connect you to our agent anytime."
INVITE = (
    "Our agent will meet you at our office in Russia Cluster and take you to the available apartments. I can hold a slot for you today "
    "at 3:00 PM or 4:00 PM — which is better?"
)
LOCATION = f"Our office location: {ADDRESS}"
CLUSTER_ASK = residential.CLUSTER_ASK["en"]
CONTRACT_ASK = "Would the contract be in your name or the company's?"
OPEN_STUDIO = "Great! Is the studio for yourself, or are you checking for a client?"
BROKER_LINE = "Thank you for your interest. Let me pass your details to the concerned agent and he will come back to you."
CALL_NAMED = f"{BUYER_LINE} Your call with our sales team is booked today at 5:00 PM."
CHARGES = (
    "Normally the security deposit in International City is around AED 2,500–3,000, depending on the owner and the unit. It's "
    "refundable at the end of the tenancy, subject to the apartment's condition. We'll confirm the exact amount before you proceed. "
    "Ejari is AED 350, and we handle the registration for you. DEWA takes a refundable deposit of around AED 2,000 for an apartment, "
    "plus a small connection fee, paid directly to DEWA. Chiller charges depend on the building; our agent will confirm for the unit. "
    "Usually 1 to 4 cheques are accepted, depending on the owner. Fewer cheques can sometimes mean a better price; our agent confirms "
    "it for the unit you like."
)


def normal(completion):
    """The model's answer as the engine reads it (schema.normalize)."""
    return schema.normalize(completion.data, shops=True, residential=True)


def failures(scenario_id, completion=None):
    return run_eval(scenario_id, completion).failures


def run_scenario(built, completion):
    """A scenario object (not one of the eval's own) as the eval runs it, with this model answer."""
    with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion), override_settings(LEADAI_OPENAI_API_KEY="test"):
        return leadai_eval.run_once(built, built.id)


def unchanged(reply, answer, **kwargs):
    """residential.cluster_first switched off."""
    return reply, "", False


def old_asked_charges(texts, money_line=""):
    """residential.asked_charges as round 1 read them: their words alone."""
    return residential.charges_asked(texts)


def old_asks_call(said, answer, appointment=None):
    """sales.asks_call as it was: the model's call request is one, whatever call is booked."""
    return people.asks_for_call(said) or people.is_call_request(answer)


def unfitted(reply, keep):
    """residential._fit switched off."""
    return reply


# The round-2 runs' answers (eval2e_round2.log): the reply before the guards cut it.
ANY_CLUSTER_2 = res_answer(
    "Perfect, that gives us more options. Normally the security deposit in International City is around AED 2,500–3,000, refundable "
    "at tenancy end depending on the apartment's condition. Ejari is AED 350, and DEWA takes a refundable deposit of about AED 2,000 "
    f"plus a connection fee. Cheques are usually 1 to 4, depending on the owner. {INVITE}",
    invited=True, share_location=True, facts={"cluster_flexible": True},
)
BOOK_TAP = (
    res_answer(f"Perfect, you're looking for a studio in International City. {INVITE}", action="tentative", place="office", invited=True, share_location=True),
    res_answer(
        f"Perfect, you're looking for a studio in International City. Any cluster you prefer, or are you flexible? {INVITE}",
        action="tentative", place="office", invited=True, share_location=True,
    ),
)
CLUSTER_RUNS = (
    res_answer(
        "Great, a studio with a balcony for next month. Normally the security deposit is around AED 2,500–3,000, refundable at tenancy "
        "end. Ejari is AED 350, and DEWA requires about AED 2,000 deposit. Payment is usually 1 to 4 cheques. When would you like to "
        "visit our office to see options? I can offer today at 3:00 PM or 4:00 PM.",
        invited=True, facts={"balcony": "yes", "move_in": "next month"},
    ),
    res_answer("Great, a studio with a balcony for next month. Will it be just for yourself?", facts={"balcony": "yes", "move_in": "next month"}),
)
STAFF_RUNS = (
    res_answer(f"No problem, I'll check which options suit you for your company staff of 4. {INVITE}", invited=True,
               facts={"occupancy": "company_staff", "occupants": 4}),
    res_answer(f"No problem, I'll check which options suit your company staff of 4. {INVITE}", invited=True,
               facts={"occupancy": "company_staff", "occupants": 4}),
)
BROKER_BOOKED = (
    res_answer(
        "Great, I've booked your viewing for today at 6:00 PM under the name Ahmed Khan. Our office is in Russia Cluster, Building V03, "
        "Shop 20, Dubai International City.",
        action="confirm", place="office", date="2026-10-12", time="18:00", words="Book 6 pm", facts={"full_name": "Ahmed Khan", "for_client": False},
    ),
    res_answer(
        "The 6:00 PM slot today is booked for you, Ahmed Khan. Our agent will meet you at our office in Russia Cluster and take you to "
        "the available Spain Cluster studios.",
        action="confirm", place="office", date="2026-10-12", time="18:00", words="Book 6 pm", facts={"full_name": "Ahmed Khan", "for_client": False},
    ),
)
SHOPS_TAGGED = (
    res_answer(
        "I understand you're interested in shops, but our team specialises in studios and one-bedroom apartments in International City. "
        "Are you looking for a studio or a one-bedroom apartment to rent or buy?",
        need_tag="wants_shop",
    ),
    res_answer(
        "I see you're interested in shops, but our team here specializes in studios and one-bedroom apartments in International City. If "
        "you want, I can connect you to our agent who handles shops to assist you further.",
        need_tag="wants_shop", handover="broker_or_for_client",
    ),
)
EXACTLY = (res_answer(CHARGES), res_answer(CHARGES.replace("for the unit", "for your unit")))
PHOTOS_CALL_BOOKED = res_answer(
    f"{HONESTY} Our agent will discuss photos and details with you during your call at 5:00 PM today.", segment="buyer", handover="call_requested",
)


# A. Our office's own address is no shop talk -------------------------------------------------------------------------


class OfficeAddressTests(SimpleTestCase):
    def test_the_two_scenarios_pass_with_codes_location_line_and_fail_with_the_old_check(self):
        for scenario_id, completion in (
            ("shops-res-any-cluster", ANY_CLUSTER_2), ("shops-res-book-tap-template-b", BOOK_TAP[0]), ("shops-res-book-tap-template-b", BOOK_TAP[1]),
        ):
            with self.subTest(scenario_id, reply=completion.data["reply"][:60]):
                run = run_eval(scenario_id, completion)
                self.assertEqual(run.failures, [])
                self.assertTrue(run.out.endswith(LOCATION), run.out)
                # The check as it was (any shop word, our address's too) failed code's own location line.
                with patch.object(leadai_eval, "_without_our_office", side_effect=lambda sentence: sentence):
                    off = failures(scenario_id, completion)
                self.assertTrue(any(item.startswith('talks shops: "Our office location:') for item in off), off)

    def test_the_check_still_reads_shop_talk_beside_our_address(self):
        check = leadai_eval.no_shop_words()
        run = run_eval("shops-res-for-myself", res_answer("Perfect. Do you prefer a balcony, and when are you planning to move?"))
        for text in (f"We have shops near our office, {ADDRESS}.", "Our shops are close to Shop 20.", "Type 1 is at Shop No. 20."):
            with self.subTest(text):
                run.out = text
                self.assertIsNotNone(check(run))
        for text in (LOCATION, f"Our office is in {ADDRESS}.", "Our office is Shop No. 20 in Russia Cluster.", "See you at shop #20."):
            with self.subTest(text):
                run.out = text
                self.assertIsNone(check(run))

    def test_the_rent_flows_guard_keeps_our_address(self):
        reply = f"Our office is in {ADDRESS}. Our agent will meet you there. We have shops in International City too."
        self.assertEqual(
            residential.drop_shop_words(reply, "rent", ADDRESS), (f"Our office is in {ADDRESS}. Our agent will meet you there.", True)
        )
        self.assertEqual(residential.drop_shop_words("Come to our office, Shop No. 20.", "sale", ADDRESS), ("Come to our office, Shop No. 20.", False))
        # With no address (as before the fix) our office's unit read as a shop.
        self.assertTrue(residential.drop_shop_words("Come to our office, Shop No. 20.", "rent")[1])
        self.assertNotRegex(filters.without_office(LOCATION, ADDRESS), r"(?i)shop|cluster|v03")
        self.assertEqual(filters.without_office("Shop #20 is our office.", ADDRESS), "is our office.")

    def test_2ds_guard_on_the_other_track_keeps_our_address(self):
        reply = f"Visit our office in {ADDRESS} and we'll give you the best option. Our shops start from AED 33,000."
        villa = needs.Need(needs.HOME, "villa")
        self.assertEqual(needs.drop_shop_pitch(reply, villa, ADDRESS), (f"Visit our office in {ADDRESS} and we'll give you the best option.", True))
        self.assertEqual(needs.drop_shop_pitch(reply, villa), ("", True))  # as before: our office's address went with the pitch

    def test_settle_reads_our_address(self):
        reply = f"Our office is in {ADDRESS}. Do you prefer a balcony, and when are you planning to move?"
        answer = normal(res_answer(reply))
        residential.settle(answer, [], ["For myself"], track="rent", unit="studio", office_address=ADDRESS)
        self.assertEqual(answer["reply"], reply)
        answer = normal(res_answer(reply))
        residential.settle(answer, [], ["For myself"], track="rent", unit="studio")
        self.assertNotIn(ADDRESS, answer["reply"])


    def test_the_eval_passes_our_address_to_the_guards_as_live(self):
        # The rent track: the model's own sentence with our address goes out (residential.settle's office_address).
        run = run_eval("shops-res-who-will-meet-me", res_answer(f"Our agent will meet you at our office, {ADDRESS}."))
        self.assertEqual(run.failures, [])
        self.assertIn(ADDRESS, run.out)
        # The other track, its want known: 2d's guard keeps it too (engine.who_they_are's office_address).
        run = run_scenario(OTHER_KNOWN, OTHER_REPLY)
        self.assertEqual(run.decision.track, tracks.OTHER)
        self.assertIn(ADDRESS, run.out)


# The other track (a two-bedroom flat), its want known from our earlier line (which gave no address): a later question.
OTHER_LINE = "Thank you for letting us know. We have many options for a 2-bedroom flat across Dubai. Would 3:00 PM or 5:00 PM today suit you?"
OTHER_FACTS = {"need": "home", "wanted": "a 2-bedroom flat", "property_type": "2-bedroom flat", "intent": "rent", "for_client": False}
OTHER_KNOWN = dataclasses.replace(
    scenario("shops-track-2br"), id="other-known-office", track="other", unit="two_plus", facts=OTHER_FACTS, invites=1,
    chat=[("customer", "Looking for a 2BR flat"), ("assistant", OTHER_LINE)], new=["What time are you open?"],
)
OTHER_REPLY = shops_answer(
    f"We're open Monday to Saturday, 10 AM to 8 PM. Visit our office in {ADDRESS} and we'll give you the best option.",
    segment="residential_tenant", facts={"for_client": False},
)


class OfficeAddressTurnTests(RentBase):
    def test_a_rent_reply_that_gives_our_office_keeps_it_live(self):
        self.rent(clusters=["Spain"])
        reply = f"Our office is in {ADDRESS}. Our agent will meet you there and take you to the available apartments."
        outcome, _, _, _ = self.turn(self.inbound("Where is your office?"), [res_answer(reply)])
        self.assertIn("Building V03, Shop 20", self.body(outcome))

    def test_the_other_tracks_reply_that_gives_our_office_keeps_it_live(self):
        self.set_state(track="other", unit="two_plus", facts=OTHER_FACTS, invites=1)
        self.ours(OTHER_LINE, minutes_ago=30)
        outcome, _, _, _ = self.turn(self.inbound("What time are you open?"), [OTHER_REPLY])
        self.assertIn("Building V03, Shop 20", self.body(outcome))


# B. The cluster before who will stay and before the invitation -------------------------------------------------------


class ClusterFirstTests(SimpleTestCase):
    def test_both_runs_ask_the_cluster_and_fail_with_the_guard_off(self):
        expected = (
            "Great, a studio with a balcony for next month. Normally the security deposit is around AED 2,500–3,000, refundable at tenancy "
            "end. Ejari is AED 350, and DEWA requires about AED 2,000 deposit. Payment is usually 1 to 4 cheques. Any cluster you prefer, or "
            "are you flexible? When would you like to visit our office to see options? I can offer today at 3:00 PM or 4:00 PM.",
            f"Great, a studio with a balcony for next month. {CLUSTER_ASK}",
        )
        for completion, out in zip(CLUSTER_RUNS, expected):
            with self.subTest(out[:40]):
                run = run_eval("shops-res-cluster-unknown", completion)
                self.assertEqual(run.failures, [])
                self.assertEqual(run.out, out)
                with patch.object(residential, "cluster_first", side_effect=unchanged):
                    self.assertIn("does not ask the cluster", failures("shops-res-cluster-unknown", completion))

    def test_who_will_stay_in_more_words_and_never_the_for_whom_question(self):
        for sentence in (
            "Will it be just for yourself?", "Is it only for you?", "Will anyone else stay with you?", "Will you be living alone?",
            "Will it be for yourself, your family, or company staff?", "Akele rahenge?",
        ):
            with self.subTest(sentence):
                self.assertTrue(residential.asks_occupancy(sentence))
        for sentence in ("Are you looking for yourself or for a client?", "Is it just for yourself or for a client?", "Just for yourself."):
            with self.subTest(sentence):
                self.assertFalse(residential.asks_occupancy(sentence))

    def test_the_occupancy_reading_alone(self):
        # A chat that has not said who it is for (no end user yet): only an occupancy question brings the cluster in.
        answer = normal(CLUSTER_RUNS[1])
        residential.settle(answer, [], ["Balcony would be nice, next month"], track="rent", unit="studio")
        self.assertTrue(answer["reply"].endswith(CLUSTER_ASK), answer["reply"])
        self.assertNotIn("just for yourself", answer["reply"])
        answer = normal(CLUSTER_RUNS[1])
        with patch.object(residential, "_ALONE_ASK", residential.re.compile(r"$^")):
            residential.settle(answer, [], ["Balcony would be nice, next month"], track="rent", unit="studio")
        self.assertNotIn("cluster", answer["reply"])

    def test_an_invitation_gets_the_cluster_first(self):
        answer = normal(res_answer(f"Great. {INVITE}", invited=True))
        residential.settle(answer, [], ["ok"], track="rent", unit="studio", facts={"for_client": False})
        self.assertEqual(
            answer["reply"], f"Great. Studios in International City are generally around AED 29,000–33,000 a year. {CLUSTER_ASK} {INVITE}"
        )
        answer = normal(res_answer(f"Great. {INVITE}", invited=True))
        with patch.object(residential, "invites", return_value=False):
            residential.settle(answer, [], ["ok"], track="rent", unit="studio", facts={"for_client": False})
        self.assertEqual(answer["reply"], f"Great. {INVITE}")

    def test_their_answer_to_our_balcony_question_gets_the_cluster_next(self):
        earlier = [("assistant", "Perfect. Do you prefer a balcony, and when are you planning to move?")]
        answer = normal(res_answer("Great, a studio with a balcony for next month."))
        residential.settle(answer, earlier, ["Balcony would be nice, next month"], track="rent", unit="studio", facts={"for_client": False})
        self.assertTrue(answer["reply"].endswith(CLUSTER_ASK), answer["reply"])
        answer = normal(res_answer("Great, a studio with a balcony for next month."))
        with patch.object(residential, "requirement_asked_last", return_value=False):
            residential.settle(answer, earlier, ["Balcony would be nice, next month"], track="rent", unit="studio", facts={"for_client": False})
        self.assertEqual(answer["reply"], "Great, a studio with a balcony for next month.")

    def test_never_when_it_is_known_asked_answered_now_or_another_step_goes(self):
        invite = res_answer(f"Great. {INVITE}", invited=True)
        cases = {
            "who it is for not known (step 1 first)": dict(facts={}),
            "the cluster known": dict(clusters=("Spain",)),
            "flexible": dict(facts={"for_client": False, "cluster_flexible": True}),
            "asked before": dict(earlier=[("assistant", f"Great. {CLUSTER_ASK}")]),
            "photos go this turn": dict(sending=True),
            "a visit open": dict(visit_open=True),
            "the sale track": dict(track="sale"),
            "the unit not known": dict(unit=""),
        }
        for name, extra in cases.items():
            with self.subTest(name):
                answer = normal(invite)
                kwargs = {"track": "rent", "unit": "studio", "facts": {"for_client": False}, **extra}
                residential.settle(answer, kwargs.pop("earlier", []), ["ok"], **kwargs)
                self.assertNotIn(CLUSTER_ASK, answer["reply"])
        # Their words now: any cluster will do; or photos asked for (unit_media's step answers them, its question after them).
        for words in ("Any cluster is fine", "Can you send photos first?"):
            with self.subTest(words):
                answer = normal(invite)
                residential.settle(answer, [], [words], track="rent", unit="studio", facts={"for_client": False})
                self.assertNotIn(CLUSTER_ASK, answer["reply"])
        # The model asks the cluster itself (round 2's run 2 of shops-res-book-tap-template-b): never twice in a reply.
        answer = normal(BOOK_TAP[1])
        residential.settle(answer, [], ["Yes, book a viewing"], track="rent", unit="studio", facts={"for_client": False})
        self.assertEqual(answer["reply"].count("cluster"), 1)
        # The model asks step 2's first half: the cluster comes after it, an invitation in the same reply or not.
        for reply in (
            "Perfect. Do you prefer a balcony, and when are you planning to move?",
            "Do you prefer a balcony? I can hold a slot for you today at 3:00 PM or 4:00 PM — which is better?",
        ):
            with self.subTest(reply):
                answer = normal(res_answer(reply, invited=True))
                residential.settle(answer, [], ["For myself"], track="rent", unit="studio", facts={"for_client": False})
                self.assertNotIn(CLUSTER_ASK, answer["reply"])

    def test_the_band_once(self):
        answer = normal(res_answer(f"Studios in International City are generally around AED 29,000–33,000 a year. {INVITE}", invited=True))
        residential.settle(answer, [], ["ok"], track="rent", unit="studio", facts={"for_client": False})
        self.assertEqual(answer["reply"].count("29,000"), 1)
        self.assertIn(CLUSTER_ASK, answer["reply"])


class ClusterTurnTests(RentBase):
    def test_the_invitation_waits_behind_the_cluster_live(self):
        self.rent(balcony=None, move_in=None)
        self.ours("Perfect. Do you prefer a balcony, and when are you planning to move?")
        outcome, _, _, _ = self.turn(self.inbound("Balcony would be nice, next month"), [CLUSTER_RUNS[0]])
        body = self.body(outcome)
        self.assertIn(CLUSTER_ASK, body)
        self.assertLess(body.index(CLUSTER_ASK), body.index("3:00 PM"))


# C. Whose name goes on the contract -------------------------------------------------------------------------------------


class ContractTests(SimpleTestCase):
    def test_both_runs_ask_the_contract_and_fail_with_the_guard_off(self):
        for completion in STAFF_RUNS:
            with self.subTest(completion.data["reply"][:40]):
                run = run_eval("shops-res-company-staff", completion)
                self.assertEqual(run.failures, [])
                self.assertIn(f"staff of 4. {CONTRACT_ASK} Our agent will meet you", run.out)
                self.assertTrue(run.out.endswith("which is better?"))
                with patch.object(residential, "contract_line_kind", return_value=""):
                    self.assertIn("does not ask whose name goes on the contract", failures("shops-res-company-staff", completion))

    def test_which_question_and_when(self):
        staff = {"occupancy": "company_staff"}
        self.assertEqual(residential.contract_line_kind({}, {**staff, "occupants": 4}), "res_contract_company")
        self.assertEqual(residential.contract_line_kind({}, staff), "res_occupants_contract_company")
        self.assertEqual(residential.contract_line_kind({}, staff, ["It is for my company staff, 4 people"]), "res_contract_company")
        self.assertEqual(residential.contract_line_kind({}, {"occupancy": "sharing"}), "res_occupants_contract_shared")
        self.assertEqual(residential.contract_line_kind({}, {"occupancy": "sharing", "occupants": 3}), "res_contract_shared")
        # Their words, when the model recorded no occupancy.
        self.assertEqual(residential.contract_line_kind({}, {}, ["It is for my company staff, 4 people"]), "res_contract_company")
        self.assertEqual(residential.contract_line_kind({}, {}, ["sharing with 2 friends"]), "res_occupants_contract_shared")
        # Never: another occupancy, the contract known, asked before, spoken of now, or asked in the reply.
        self.assertEqual(residential.contract_line_kind({}, {"occupancy": "myself"}, ["my company staff"]), "")
        self.assertEqual(residential.contract_line_kind({}, {**staff, "contract": "company"}), "")
        self.assertEqual(residential.contract_line_kind({}, staff, earlier=[("assistant", f"Great. {CONTRACT_ASK}")]), "")
        self.assertEqual(residential.contract_line_kind({}, staff, ["company staff, contract in the company name"]), "")
        self.assertEqual(residential.contract_line_kind({}, staff, reply="Whose name would the contract be in?"), "")

    def test_the_lines_in_six_languages_promise_no_approval(self):
        for kind in ("res_contract_company", "res_contract_shared", "res_occupants_contract_company", "res_occupants_contract_shared"):
            self.assertEqual(set(residential.LINES[kind]), set(residential.LANGS))
            for language, text in residential.LINES[kind].items():
                with self.subTest(kind, language=language):
                    self.assertTrue(text.endswith(("?", "؟")))
                    self.assertNotRegex(text, r"(?i)approv")
                    self.assertTrue(residential.is_fixed_line(text))  # the repeat guard keeps it

    def test_not_with_the_clusters_question_nor_off_the_rent_track(self):
        answer = normal(STAFF_RUNS[0])
        residential.settle(answer, [], ["It is for my company staff, 4 people"], track="rent", unit="studio", facts={"for_client": False})
        self.assertIn(CLUSTER_ASK, answer["reply"])  # step 2 first: the contract waits for the next turn
        self.assertNotIn("contract", answer["reply"])
        self.assertNotIn("contract", answer["trimmed"])  # nor is it noted as asked
        answer = normal(STAFF_RUNS[0])
        residential.settle(answer, [], ["It is for my company staff, 4 people"], track="sale", unit="studio", facts={"for_client": False})
        self.assertNotIn("contract", answer["reply"])


class ContractTurnTests(RentBase):
    def test_company_staff_are_asked_whose_name_goes_on_the_contract_live(self):
        self.rent(clusters=["Spain"])
        outcome, _, _, _ = self.turn(self.inbound("It is for my company staff, 4 people"), [STAFF_RUNS[1]])
        self.assertIn(f"staff of 4. {CONTRACT_ASK} Our agent", self.body(outcome))


# D. A broker on the rent track ---------------------------------------------------------------------------------------


class BrokerOnTheRentTrackTests(SimpleTestCase):
    def test_both_runs_hand_over_and_book_nothing_and_fail_with_the_fix_off(self):
        for completion in BROKER_BOOKED:
            with self.subTest(completion.data["reply"][:30]):
                run = run_eval("shops-res-broker-books", completion)
                self.assertEqual(run.failures, [])
                self.assertIsNone(run.when)
                self.assertEqual((run.answer["handover"]["reason"], run.out), (brokers.REASON, BROKER_LINE))
                with patch.object(brokers, "HOME_TRACKS", ()):
                    off = failures("shops-res-broker-books", completion)
                self.assertTrue(any(item.startswith("booked Mon 12 Oct 18:00") for item in off), off)

    def test_client_words_count_on_the_home_tracks_whatever_the_end_user_said(self):
        words = ["Book 6 pm for my client Ahmed Khan"]
        for track in ("rent", "sale"):
            with self.subTest(track):
                answer = normal(BROKER_BOOKED[0])
                self.assertEqual(brokers.backstop(answer, {"for_client": False}, words, track=track), brokers.WORDS)
                self.assertEqual(answer["handover"], {"needed": True, "reason": brokers.REASON})
        # The shops' salon owner keeps 2d's reading; a chat a person holds counts "I am a broker" only, on every track; and an
        # owner's own client at a time is none on the rent track either.
        answer = normal(BROKER_BOOKED[0])
        self.assertEqual(brokers.backstop(answer, {"for_client": False}, words, track="shop"), "")
        answer = normal(BROKER_BOOKED[0])
        self.assertEqual(brokers.backstop(answer, {}, words, held=True, track="rent"), "")
        answer = normal(BROKER_BOOKED[0])
        self.assertEqual(brokers.backstop(answer, {"for_client": False}, ["I have a client at 3, can we do 5?"], track="rent"), "")


class BrokerTurnTests(RentBase):
    def test_a_broker_on_the_rent_track_books_nothing_live(self):
        self.rent()  # for_client false: they said "For myself" earlier
        self.ours(leadai_eval.RENT_INVITE_4_6)
        message = self.inbound("Book 6 pm for my client Ahmed Khan")
        outcome, _, _, _ = self.turn(message, [BROKER_BOOKED[0]])
        self.assertEqual(self.body(outcome), BROKER_LINE)
        self.assertFalse(LeadAiAppointment.objects.filter(conversation=self.conversation, status="confirmed").exists())
        self.assertIsNotNone(self.state().paused_at)
        self.assertTrue(self.conversation.labels.filter(name__iexact="Broker").exists())
        self.assertEqual(self.actions(message)["broker_backstop"], brokers.WORDS)


# E. A template yes on a known rent or sale track ---------------------------------------------------------------------


class TemplateYesTests(SimpleTestCase):
    def test_codes_opener_with_no_model_and_both_runs_fail_with_it_off(self):
        settled = leadai_eval.code_first(scenario("shops-res-yes-to-shops-template"))
        self.assertEqual(settled["open_lead"], {"unit": "studio", "clusters": []})
        run = run_eval("shops-res-yes-to-shops-template", SHOPS_TAGGED[0])
        self.assertEqual((run.failures, run.out, run.calls), ([], OPEN_STUDIO, 0))
        for completion in SHOPS_TAGGED:
            with self.subTest(completion.data["reply"][:30]):
                with patch.object(engine, "reads_first_yes", return_value=False):
                    self.assertTrue(failures("shops-res-yes-to-shops-template", completion))

    def test_the_rule_reads_the_track(self):
        rent = tracks.Decision(tracks.RENT, tracks.STUDIO)
        self.assertTrue(engine.reads_first_yes(ic_templates.SHOP, rent))
        self.assertTrue(engine.reads_first_yes(ic_templates.SHOP, tracks.Decision(tracks.SALE, tracks.STUDIO)))
        self.assertFalse(engine.reads_first_yes(ic_templates.SHOP, tracks.Decision(tracks.SHOP)))
        self.assertFalse(engine.reads_first_yes(ic_templates.SHOP, tracks.Decision(tracks.OTHER)))
        self.assertTrue(engine.reads_first_yes(ic_templates.MIXED, tracks.Decision(tracks.SHOP)))
        with patch.object(residential, "RENT_LIVE", False):  # the rent flow's kill switch: 2d's own rules
            self.assertFalse(engine.reads_first_yes(ic_templates.SHOP, rent))
        rule = engine.shops_rule("Yes", first_answer=True, template_kind=ic_templates.SHOP, mixed=tracks.OPEN_LEAD, track=tracks.RENT)
        self.assertEqual(rule, f"{engine.MIXED_YES}:{tracks.OPEN_LEAD}")
        # Who it is for known: the model's (nothing of code's), never the shops' for-whom line.
        known = engine.shops_rule("Yes", first_answer=True, for_client_known=True, template_kind=ic_templates.SHOP, mixed="", track=tracks.RENT)
        self.assertEqual(known, "")
        # A shop chat keeps the shops' own.
        self.assertEqual(engine.shops_rule("Yes", first_answer=True, template_kind=ic_templates.SHOP, track=tracks.SHOP), engine.FOR_WHOM)

    def test_the_models_tag_never_moves_a_known_home_on_a_bare_yes(self):
        base = {
            "stored": "rent", "stored_unit": "studio", "template_kind": ic_templates.SHOP, "model_tag": "wants_shop",
            "facts": {"need": "home", "wanted": "a studio"},
        }
        self.assertEqual(tracks.decide(words=["Yes"], first_answer=True, **base).track, tracks.RENT)
        self.assertEqual(tracks.decide(words=["Yes, book a viewing"], first_answer=True, **base).track, tracks.RENT)
        # Not their first answer to the template, or more words than a yes: the tag reads as before.
        self.assertEqual(tracks.decide(words=["Yes"], first_answer=False, **base).track, tracks.SHOP)
        self.assertEqual(tracks.decide(words=["Yes, I also want to see what you have"], first_answer=True, **base).track, tracks.SHOP)
        # A tap that names a shop is their own words.
        self.assertEqual(tracks.decide(words=["Yes, show me shops"], first_answer=True, **{**base, "model_tag": ""}).track, tracks.SHOP)
        # 2d's want with no track stored yet (campaigns 448 and 449) is a known home too.
        self.assertEqual(tracks.decide(words=["Yes"], first_answer=True, **{**base, "stored": "", "stored_unit": ""}).track, tracks.RENT)
        with patch.object(tracks, "template_yes", return_value=False):
            self.assertEqual(tracks.decide(words=["Yes"], first_answer=True, **base).track, tracks.SHOP)

    def test_template_b_from_an_end_user_keeps_the_rent_track_whatever_the_model_tags(self):
        tagged = res_answer(f"Perfect, you're looking for a studio in International City. {INVITE}", invited=True, need_tag="wants_shop")
        run = run_eval("shops-res-book-tap-template-b", tagged)
        self.assertEqual(run.failures, [])
        with patch.object(tracks, "template_yes", return_value=False):
            off = run_eval("shops-res-book-tap-template-b", tagged)
        self.assertIn("track shop, expected rent", "; ".join(off.failures))
        # The switch it would make: the shops' line and their list, code's (no KeyError: engine.residential_switch's converted
        # "res_switch_shop" is never read as a fixed line over the list).
        self.assertEqual(off.out_by, leadai_eval.CODE)
        self.assertTrue(off.out.startswith("Sure! We have shops in International City too."), off.out)


class SwitchToShopTurnTests(RentBase):
    def test_an_end_user_the_models_tag_moves_to_shops_gets_the_line_and_the_list(self):
        self.rent(clusters=["Spain"])  # an end user (for_client false), on the rent track
        message = self.inbound("I also need something for my business")
        outcome, _, _, _ = self.turn(message, [res_answer("Sure! What kind of business?", need_tag="wants_shop")])
        self.assertIsNotNone(outcome.reply_message_id, outcome)
        bodies = [row.body for row in self.outbound()]
        self.assertIn("Sure! We have shops in International City too.", bodies)
        self.assertEqual(self.sent_lists.call_count, 1)  # the shop types list, never "Is the shop for yourself?" again
        self.assertEqual(self.state().track, "shop")


# F. The commission's figure, and code's lines whole ------------------------------------------------------------------


class CommissionFigureTests(SimpleTestCase):
    def test_both_runs_get_codes_figure_line_and_fail_with_the_guards_off(self):
        line = residential.commission_figure_line("en", "studio")
        for completion in EXACTLY:
            with self.subTest(completion.data["reply"][-20:]):
                run = run_eval("shops-res-commission-how-much-exactly", completion)
                self.assertEqual(run.failures, [])
                self.assertEqual(run.out, line)
                with patch.object(residential, "asked_charges", side_effect=old_asked_charges):
                    self.assertIn('answer a charge they did not ask about: "deposit"', failures("shops-res-commission-how-much-exactly", completion))
                with patch.object(residential, "asked_charges", side_effect=old_asked_charges), patch.object(residential, "_fit", side_effect=unfitted):
                    off = failures("shops-res-commission-how-much-exactly", completion)
                self.assertTrue(any("expected the figure commission line" in item for item in off), off)

    def test_the_commission_is_what_they_asked(self):
        self.assertEqual(residential.asked_charges(["how much exactly?"], "a line"), {"commission"})
        self.assertEqual(residential.asked_charges(["how much exactly?"]), set())  # no line of code's: nothing asked
        self.assertIsNone(residential.asked_charges(["what are the total charges?"], "a line"))  # the charges in general: all may go
        self.assertEqual(residential.asked_charges(["and the deposit?"], "a line"), {"deposit"})
        earlier = [("customer", "Is there any commission?"), ("assistant", residential.line("res_commission_first", "en"))]
        answer = normal(EXACTLY[0])
        residential.settle(answer, earlier, ["how much exactly?"], track="rent", unit="studio", clusters=("Spain",))
        self.assertEqual(answer["reply"], residential.commission_figure_line("en", "studio"))

    def test_codes_line_goes_out_whole_under_the_limit(self):
        # Asked about the deposit and the commission: the deposit's own lines stay, and code's line is never cut off.
        long_deposit = " ".join([CHARGES.split(" Ejari")[0]] * 3)
        asked = ["What is the deposit and how much is the commission?"]
        line = residential.commission_figure_line("en", "studio")
        answer = normal(res_answer(f"{long_deposit} Shall I hold a slot for you?"))
        residential.settle(answer, [], asked, track="rent", unit="studio", clusters=("Spain",))
        self.assertLessEqual(len(answer["reply"]), filters.REPLY_MAX)
        self.assertIn(line, answer["reply"])
        self.assertTrue(answer["reply"].endswith("Shall I hold a slot for you?"))  # the model's question stays, its statements made room
        answer = normal(res_answer(f"{long_deposit} Shall I hold a slot for you?"))
        with patch.object(residential, "_fit", side_effect=unfitted):
            residential.settle(answer, [], asked, track="rent", unit="studio", clusters=("Spain",))
        self.assertGreater(answer["reply"].index(line) + len(line), filters.REPLY_MAX)  # clean_reply's limit would cut it


# G. Photos asked for with a sales call booked ------------------------------------------------------------------------


class PhotosWithACallBookedTests(SimpleTestCase):
    def test_the_models_call_request_is_the_booked_call_and_fails_with_the_fix_off(self):
        tentative = res_answer(PHOTOS_CALL_BOOKED.data["reply"], segment="buyer", action="tentative", place="call", date="2026-10-12", time="17:00")
        for completion in (PHOTOS_CALL_BOOKED, tentative):
            with self.subTest(completion.data["handover"]["reason"] or "tentative"):
                run = run_eval("shops-sale-photos-call-booked", completion)
                self.assertEqual(run.failures, [])
                self.assertEqual(run.out, CALL_NAMED)
                with patch.object(sales, "asks_call", side_effect=old_asks_call):
                    off = failures("shops-sale-photos-call-booked", completion)
                self.assertIn("sale step call_slots, expected buyer_media", off)

    def test_their_own_words_still_ask_for_a_call(self):
        booked = LeadAiAppointment(place="call", status="confirmed", starts_at=at(12, 17), details={"track": "sale"})
        answer = normal(PHOTOS_CALL_BOOKED)
        self.assertFalse(sales.asks_call("Also can you send photos of the studio?", answer, booked))
        self.assertTrue(sales.asks_call("Can you call me now instead?", answer, booked))
        self.assertTrue(sales.asks_call("Also can you send photos of the studio?", answer, None))  # no call booked: the model's request is one


class PhotosWithACallBookedTurnTests(NotAShopBase):
    def test_photos_with_a_call_booked_name_the_call_live(self):
        self.set_state(track="sale", unit="studio", facts={**BUYER, "full_name": "Ahmed Khan"})
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="call", starts_at=at(12, 17), details={"track": "sale"})
        message = self.inbound("Thanks. Also can you send photos of the studio?")
        outcome, _, _, _ = self.turn(message, [PHOTOS_CALL_BOOKED])
        self.assertEqual(self.body(outcome), CALL_NAMED)
        self.assertEqual(LeadAiAppointment.objects.filter(conversation=self.conversation).count(), 1)
        self.assertIsNone(self.state().handed_over_at)
        self.media_delay.assert_not_called()


# H. shops-same-day-window-96 is EITHER ------------------------------------------------------------------------------


class SameDayWindowTests(SimpleTestCase):
    def test_either_with_the_reason(self):
        s = scenario("shops-same-day-window-96")
        self.assertEqual(s.words, leadai_eval.EITHER)
        self.assertFalse(leadai_eval.policy_scenario(s))
        # Over the model's tentative code books his window's start, as before (test_facts_slots_booking holds book_window off).
        self.assertEqual(failures("shops-same-day-window-96", RIGHT["shops-same-day-window-96"]), [])
        # Round 2's run 2: no visit recorded (action none), so code booked nothing; a failing run no longer fails the strict rule.
        none = shops_answer(
            "Hamari office Russia Cluster, Building V03, Shop 20 mein hai. Aap yahan aayen, phir hamara agent aapko shops dikhane le "
            "jayega. Main aapke liye aaj 12:30 PM ya 1:30 PM ka slot reserve kar sakta hoon, kaunsa behtar hai?",
            language="ur_latin", facts=leadai_eval.FACTS_96,
        )
        run = run_eval("shops-same-day-window-96", none)
        self.assertTrue(any(item.startswith("(nothing booked") for item in run.failures), run.failures)
        self.assertEqual(leadai_eval.must_pass([run]), [])
        # Code's reading of a window is no reading of a visit: these name the same window, and promise no visit.
        for text in ("I have a meeting from 12 to 12:30", "My lunch is 12-12:30", "Is your office closed between 12 and 12:30?"):
            with self.subTest(text):
                self.assertTrue(hours.window_promise(text))
                self.assertEqual(hours.named_window(text), (dt.time(12, 0), dt.time(12, 30)))
