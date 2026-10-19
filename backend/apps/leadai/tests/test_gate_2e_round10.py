"""Batch 2e's real-model gate, round 10 (2026-10-19, on the server's build context): 569 of 574 (99.1%), the model's own
words 300 of 304 (98.7%), the shop scenarios 187 of 188, but the every-run rule failed on three scenarios, one run each:

- declines #1: "No thank you, I already rented a shop last month" got opt_out none (the model tagged it unclear): ten
  words, past rules.opt_out_from_text's whole-message limit. A no opening the message with the reason they are done after
  it (rules.declines, _LOST_REASON) is not interested in any length, set by engine.settle over the model's none. Never
  code's before the model (opt_out_from_text, the eval's code_first): a shops chat reads the same words in who_they_are
  and asks about a second shop first (board T27, test_who_the_customer_is AlreadyRentedTests).
- shops-res-invitation-two-slots #1: the charges paragraph nobody asked for plus the invitation made 698 characters, and
  filters.clean_reply's cut at 600 took code's two slots, last in the reply. engine.settle fits the reply with the slot
  line kept (residential._fit); clean_reply's own cut falls at a sentence end, never mid-word.
- shops-res-cluster-unknown #1: the model asked "Will it be just for yourself, your family, or company staff?" and the
  cluster was not asked; cluster_first read the question (asks_occupancy) and cut it, and the check still failed. Held by
  test_gate_2e_round2's own fixture of that reply, which passes: model variance over that run, no gap found.
"""

import dataclasses
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.leadai import followups, lane
from apps.leadai.assistant import engine, filters, hours, reminders, rules, schema
from apps.leadai.management.commands import leadai_eval
from apps.leadai.tests.test_launch_gate import run_eval, scenario
from apps.leadai.tests.test_residential_turns import res_answer
from apps.leadai.tests.test_shops_playbook import NOW, TWO_SLOTS_NOW, shop_answer

# The round-10 runs' answers (eval2e_r10.log).
DECLINED = "No thank you, I already rented a shop last month"
DECLINES_REPLY = "Thank you for letting us know. Our specialist will be available here if you need any assistance in the future."
INVITATION_REPLY = (
    "No problem. Normally the security deposit in International City is around AED 2,500–3,000, refundable at the end of the "
    "tenancy, depending on the apartment's condition. Ejari is AED 350, and we handle the registration for you. DEWA requires a "
    "refundable deposit of about AED 2,000 plus a small connection fee. Chiller charges depend on the building; our agent will "
    "confirm for the unit. Usually, 1 to 4 cheques are accepted, and fewer cheques can sometimes mean a better price. Our agent "
    "will explain everything at the viewing. Our agent will meet you at our office in Russia Cluster and take you to the "
    "available apartments. When would you like to come?"
)


def run_in_shops(scenario_id, completion):
    """The scenario on the shops playbook, with this model answer: its own path (engine.who_they_are) after settle."""
    shops = dataclasses.replace(scenario(scenario_id), playbook=leadai_eval.IC_SHOPS)
    with patch("apps.leadai.assistant.openai_client.complete_json", return_value=completion), override_settings(LEADAI_OPENAI_API_KEY="test"):
        return leadai_eval.run_once(shops, scenario_id)


class DeclinesTests(SimpleTestCase):
    def test_a_no_with_the_reason_after_it_is_not_interested(self):
        run = run_eval("declines", res_answer(DECLINES_REPLY, handover="unclear"))
        self.assertEqual(run.failures, [])
        self.assertEqual(run.answer["opt_out"], "not_interested")
        self.assertIn("declines", run.answer.get("trimmed") or [])

    def test_with_the_rule_off_it_fails_again(self):
        with patch.object(rules, "_LOST_REASON", rules.re.compile(r"$^")):
            failures = run_eval("declines", res_answer(DECLINES_REPLY, handover="unclear")).failures
        self.assertIn("opt_out none, expected not_interested", failures)

    def test_the_words_it_reads_and_leaves(self):
        for said in (DECLINED, "no thanks, already found one", "Not interested, got a flat already", "no thanks, mil gaya"):
            with self.subTest(said):
                self.assertTrue(rules.declines(said))
        for said in (
            "no thanks but can I see a 2BR", "Not now, maybe next July", "I already rented one, do you have a shop too?",
            "No thanks, I already rented one, but do you have offices?", "no thanks", "",
        ):
            with self.subTest(said):
                self.assertFalse(rules.declines(said))

    def test_it_is_read_after_the_model_never_before(self):
        # Code's own opt-out before any model (opt_out_from_text, the eval's code_first) keeps its whole-message limit: the
        # words carry what the model and who_they_are read (a shop rented elsewhere).
        self.assertIsNone(rules.opt_out_from_text(DECLINED))
        self.assertIsNone(leadai_eval.code_first(scenario("declines")))

    def test_a_shops_chat_asks_about_a_second_shop_first(self):
        run = run_in_shops("declines", shop_answer("No problem, thank you for letting us know."))
        self.assertEqual(run.answer["opt_out"], "none")
        self.assertIs(run.answer["facts"].get("already_rented"), True)
        self.assertIn(rules.line("rented_second_shop", "en"), run.out)

    def test_the_follow_up_and_the_reminder_readers_agree(self):
        self.assertTrue(followups._says_no(DECLINED))

        class Said:
            kind = "text"
            body = DECLINED
            payload = {}

        with patch.object(reminders.transcript, "payload", return_value={}):
            self.assertEqual(reminders._opt_out_in(Said()), rules.NOT_INTERESTED)


class InvitationOverTheLimitTests(SimpleTestCase):
    def test_codes_two_slots_survive_a_long_reply(self):
        run = run_eval("shops-res-invitation-two-slots", res_answer(INVITATION_REPLY, invited_to_meeting=True))
        self.assertEqual(run.failures, [])
        self.assertLessEqual(len(run.out), filters.REPLY_MAX)
        self.assertIn("PM or", run.out)
        self.assertIn("length", run.answer.get("trimmed") or [])

    def test_with_the_fit_off_the_slots_were_cut(self):
        from apps.leadai.assistant import residential

        with patch.object(residential, "_fit", lambda reply, keep: reply):
            run = run_eval("shops-res-invitation-two-slots", res_answer(INVITATION_REPLY, invited_to_meeting=True))
        self.assertNotIn("PM or", run.out)
        self.assertNotEqual(run.failures, [])

    def test_clean_reply_cuts_at_a_sentence_end(self):
        long = " ".join(f"Sentence number {n} of the reply is here." for n in range(1, 30))
        text, notes = filters.clean_reply(long, "", max_questions=2)
        self.assertLessEqual(len(text), filters.REPLY_MAX)
        self.assertTrue(text.endswith("."), text[-20:])
        self.assertIn("length", notes)

    def test_a_single_sentence_over_the_limit_is_cut_as_before(self):
        text, _ = filters.clean_reply("x" * 700, "", max_questions=2)
        self.assertEqual(len(text), filters.REPLY_MAX)


class SlotLineKeptInSettleTests(SimpleTestCase):
    def test_the_models_statements_go_before_the_slot_line(self):
        filler = " ".join(f"The model wrote statement number {n} about the apartment here." for n in range(1, 12))
        answer = schema.normalize(shop_answer(f"{filler} When would you like to come?").data, shops=True)
        out = engine.settle(answer, [], ["Just me"], 0, playbook=lane.IC_SHOPS, slots=hours.offer_pair(NOW), now=NOW)
        self.assertIn(TWO_SLOTS_NOW, out["reply"])
        self.assertLessEqual(len(out["reply"]), filters.REPLY_MAX)
        self.assertIn("length", out["trimmed"])
