"""The first mixed campaign (2026-10-19), I14 (docs/superpowers/specs/2026-10-19-leadai-campaign-1-issues.md): stock
claimed on the shops track. Chat 49958: "The Type 3 large shops are available in all clusters including China" (the
model's) went out, as the availability guard ran on the residential path only; the shop-types card said "We have 3 types
of shops available", which the customer read as an inventory. The card names the three sizes now, and engine.settle cuts
the model's stock claims on the shops track with the residential guard's policy reading; the shops' fixed lines stay."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.leadai import lane
from apps.leadai.assistant import claims, engine, residential, schema, shop_flow
from apps.leadai.tests.test_shops_playbook import NOW, shop_answer

CLAIM = "The Type 3 large shops are available in all clusters including China."
QUESTION = "What business will the shop be for?"


def settle(reply: str) -> dict:
    answer = schema.normalize(shop_answer(reply).data, shops=True)
    return engine.settle(answer, [], ["I need a big shop in China cluster"], 0, playbook=lane.IC_SHOPS, now=NOW)


class ShopsStockClaimTests(SimpleTestCase):
    def test_the_models_stock_claim_goes_and_its_question_stays(self):
        out = settle(f"{CLAIM} {QUESTION}")
        self.assertNotIn("available in all clusters", out["reply"])
        self.assertIn(QUESTION, out["reply"])
        self.assertIn("availability", out["trimmed"])

    def test_with_the_guard_off_it_went(self):
        with patch.object(claims, "claims_stock", lambda sentence: False):
            out = settle(f"{CLAIM} {QUESTION}")
        self.assertIn("available in all clusters", out["reply"])

    def test_what_the_reader_takes_and_leaves(self):
        for sentence in (CLAIM, "Type 1 shops are available now.", "There are shops available in China cluster.", "We have units in every cluster."):
            with self.subTest(sentence):
                self.assertTrue(claims.claims_stock(sentence))
        for sentence in (
            QUESTION,
            "Our agent will show you the available options at the viewing.",
            "Shops may be available in China cluster; the agent checks.",
            "I can hold two free slots for you.",
            # An availability word with no shop noun is not a stock claim: our agent's time, a free slot, the office.
            "Our agent is available at 4 PM today.",
            "I am free to answer any question.",
            "The office is available for a visit until 7:30 PM.",
        ):
            with self.subTest(sentence):
                self.assertFalse(claims.claims_stock(sentence))

    def test_a_sentence_with_no_shop_noun_stays_in_the_reply(self):
        out = settle(f"Our agent is available at 4 PM today. {QUESTION}")
        self.assertIn("available at 4 PM", out["reply"])
        self.assertNotIn("availability", out.get("trimmed") or [])

    def test_the_shops_own_fixed_lines_are_never_cut(self):
        # The build pack's fixed answers stay whatever the reading says. None of them names stock today (shops._FIXED_KEYS:
        # the unknown and discount lines, the honesty prefix), so the keep is a belt for a line added later.
        line = "Good question — I'll have our agent confirm that for you at the viewing."
        out = settle(f"{line} {QUESTION}")
        self.assertIn(line, out["reply"])

    def test_the_card_names_sizes_not_stock(self):
        for lang, (header, _, _) in shop_flow._LIST.items():
            with self.subTest(lang):
                self.assertFalse(residential.availability_talk(header), header)
        self.assertEqual(shop_flow._LIST["en"][0], "Great! Shops in International City come in 3 types:")
