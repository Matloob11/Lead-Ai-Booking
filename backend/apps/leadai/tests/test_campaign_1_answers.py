"""The first mixed campaign (2026-10-19), I09 (docs/superpowers/specs/2026-10-19-leadai-campaign-1-issues.md): questions
answered with something else.

- Chat 50390, 13:46: "What are the agency charges" read as the charges in general (every charge line, no commission).
  "Agency charges" is a commission ask (residential._COMMISSION_WORDS).
- Chat 50390, 13:50: "Normally it ranges from ?" right after code's commission line got "our agent can explain": a figure
  asked (residential._ASKS_FIGURE), so code's figure line goes (asks_commission_figure).
- Chat 50093, 13:54 and 13:59: "is it a family building or bachelors as well?" was asked three times, and the model's every
  answer ("Our agent can share details about the building rules ...") was cut as screening. An answer to their own
  occupancy question that states no restriction is no screening (residential.screens); a restriction still is.
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import residential
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

COMMISSION_FIRST = residential.line("res_commission_first", "en")


class AgencyChargesTests(SimpleTestCase):
    def test_agency_charges_is_a_commission_ask(self):
        for said in ("What are the agency charges", "agency charges?", "any agency fee", "what's your brokerage"):
            with self.subTest(said):
                self.assertTrue(residential.asks_commission([said]))

    def test_the_other_charges_are_not(self):
        for said in ("how much is the deposit", "Ejari charges?", "DEWA charges", "what are the charges"):
            with self.subTest(said):
                self.assertFalse(residential.asks_commission([said]))


class RangesFromTests(SimpleTestCase):
    def test_a_range_asked_after_our_commission_line_is_a_figure_asked(self):
        earlier = [("customer", "Any commission charges are there?"), ("assistant", COMMISSION_FIRST)]
        for said in ("Normally it ranges from ?", "what range?", "roughly?", "approximately how much", "what percent"):
            with self.subTest(said):
                self.assertTrue(residential.asks_commission_figure(earlier, [said]))

    def test_not_after_another_line_of_ours(self):
        earlier = [("customer", "how much is the deposit"), ("assistant", "Normally the security deposit is around AED 2,500–3,000.")]
        self.assertFalse(residential.asks_commission_figure(earlier, ["Normally it ranges from ?"]))

    def test_the_rent_asked_is_not_the_commission(self):
        earlier = [("customer", "Any commission charges are there?"), ("assistant", COMMISSION_FIRST)]
        self.assertFalse(residential.asks_commission_figure(earlier, ["and the rent ranges from?"]))


class OccupancyAnswerTests(SimpleTestCase):
    def test_an_answer_to_their_own_question_is_no_screening(self):
        for sentence in (
            "Our agent can share details about the building rules and options when you visit.",
            "Our agent will confirm the details about the building rules when you visit.",
            "It depends on the building and the owner; our agent confirms the rules for the exact unit.",
            "Most buildings in France Cluster are mixed, with both families and bachelors.",
            "Whether bachelors are accepted depends on the building, our agent will check for you.",
        ):
            with self.subTest(sentence):
                self.assertFalse(residential.screens(sentence))

    def test_a_restriction_said_is_still_screening(self):
        for sentence in (
            "Sorry, no bachelors.",
            "The owner prefers families.",
            "This building is for families only.",
            "Bachelors are not allowed in that building.",
            "What is your nationality?",
            "Are you married or single?",
            # An answer's shape with a restriction in it: the restriction wins.
            "Our agent confirms the building rules, but that building is for families only.",
            "It depends on the building; the owner prefers families there.",
        ):
            with self.subTest(sentence):
                self.assertTrue(residential.screens(sentence))

    def test_chat_50093_gets_its_answer(self):
        reply = "Our agent can share details about the building rules and options when you visit. When would you like to come to our office?"
        run = run_eval("shops-res-any-cluster", res_answer(reply, facts={"for_client": False}))
        self.assertIn("building rules", run.out)
        self.assertNotIn("screening", run.answer.get("trimmed") or [])
