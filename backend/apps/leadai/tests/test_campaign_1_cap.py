"""The first mixed campaign (2026-10-19), I05 (docs/superpowers/specs/2026-10-19-leadai-campaign-1-issues.md): a call asked
for is never held by the reply cap. One chat's "arrange a call" waited 20 minutes behind the cap; chat 50005's "Urgent
‼️ for call" is the words the bypass reads (engine._run_claimed, people.asks_for_call)."""

from apps.leadai.assistant import engine
from apps.leadai.tests.test_shops_playbook import shop_answer
from apps.leadai.tests.test_silence_caps_people import PeopleBase


class CallRequestAtTheCapTests(PeopleBase):
    def test_a_call_asked_for_gets_its_turn_at_the_cap(self):
        self.replies(12, 20)  # the hour's twelve replies are out: the cap is reached
        message = self.inbound("Urgent ‼️ for call 📲", seconds_ago=10)
        outcome, calls, _, _ = self.turn(message, [shop_answer("Sure, our agent will call you.", handover="call_requested")])
        self.assertNotEqual(outcome.reason, engine.CAPPED_REASON)
        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(self.state().handed_over_at)

    def test_anything_else_at_the_cap_still_waits(self):
        self.replies(12, 20)
        message = self.inbound("what size is type 2?", seconds_ago=10)
        outcome, calls, _, _ = self.turn(message, [shop_answer("never asked")])
        self.assertEqual((outcome.reason, calls), (engine.CAPPED_REASON, []))
