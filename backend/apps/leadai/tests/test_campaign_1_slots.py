"""The first mixed campaign (2026-10-19), I05 and I07 (docs/superpowers/specs/2026-10-19-leadai-campaign-1-issues.md):

- I07: one pair of slots to a message. Chat 49818 got the model's "I can offer 3:00 PM or 4:00 PM today" and code's
  "3:00 PM or 5:00 PM" in one message: offers.fix_times kept the model's valid pair while filters.offer_slots turned its
  open question into code's. engine.settle now drops the model's own pair when code's closes the message.
- I05: a call asked for is never held by the reply cap (engine._run_claimed).
"""

from django.test import SimpleTestCase

from apps.leadai import lane
from apps.leadai.assistant import engine, hours, people, schema
from apps.leadai.tests.test_shops_playbook import NOW, TWO_SLOTS_NOW, shop_answer

# Chat 49818's reply at 13:27, as the model wrote it (the turn's trimmed held only "slots").
REPLY_49818 = (
    "Great, you prefer a studio with a balcony in France Cluster and plan to move by year end. Our agent can explain all "
    "details at the viewing. I can offer 3:00 PM or 4:00 PM today. When would you like to come?"
)


def settle(reply: str, **extra) -> dict:
    answer = schema.normalize(shop_answer(reply, **extra).data, shops=True)
    return engine.settle(answer, [], ["By year end"], 0, playbook=lane.IC_SHOPS, slots=hours.offer_pair(NOW), now=NOW)


class OnePairOfSlotsTests(SimpleTestCase):
    def test_the_models_own_pair_goes_when_codes_closes_the_message(self):
        out = settle(REPLY_49818)
        self.assertEqual(out["reply"].count("PM or"), 1, out["reply"])
        self.assertIn(TWO_SLOTS_NOW, out["reply"])
        self.assertNotIn("3:00 PM or 4:00 PM", out["reply"])
        self.assertIn("Great, you prefer a studio with a balcony", out["reply"])
        self.assertIn("slots", out["trimmed"])

    def test_the_models_valid_pair_alone_still_stands(self):
        # No open question: offer_slots rewrites nothing, and fix_times keeps a valid pair (launch review issue 17).
        out = settle("Great. Would today at 3:00 PM or 5:00 PM work for you?")
        self.assertEqual(out["reply"].count("PM or"), 1, out["reply"])
        self.assertNotIn("slots", out.get("trimmed") or [])

    def test_an_open_question_alone_gets_codes_pair_as_before(self):
        out = settle("Great. When would you like to come to our office?")
        self.assertEqual(out["reply"], f"Great. {TWO_SLOTS_NOW}")


class CallRequestBypassesTheCapTests(SimpleTestCase):
    def test_the_bypass_reads_the_campaigns_words(self):
        # The condition engine._run_claimed uses, on chat 50005's words.
        self.assertTrue(people.asks_for_call("Urgent ‼️ for call 📲"))
        self.assertFalse(people.asks_for_call("what is the rent"))
