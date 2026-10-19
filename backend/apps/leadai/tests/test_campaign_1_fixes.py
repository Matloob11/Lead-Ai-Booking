"""The first mixed campaign (2026-10-19, intl_city_property_reconnect, 222 replies): the four mistakes that lost customers,
each pinned with the chat's own words (docs/superpowers/specs/2026-10-19-leadai-campaign-1-issues.md, I01-I06).

- I01: a reply nobody answered is answered late, not dropped (engine.run_turn, LATE_UNTIL): test_assistant holds it.
- I03: "Stop messages" and "Not now" tapped together, delivered out of order (chat 50108): the stop wins.
- I04: "Urgent ‼️ for call" (chat 50005) is a call request.
- I06: "I have tentatively held the 4:00 PM slot" on a bare "Okey" (chat 49569) is a hold code never made: cut.
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import people, residential, rules
from apps.leadai.tests.test_tracks_turns import MixedBase


class StopTappedWithNotNowTests(MixedBase):
    def test_the_stop_wins_whatever_order_the_taps_came_in(self):
        # Chat 50108: "Not now" pk after "Stop messages" though sent first; the last item read as "Not now".
        self.tap("Stop messages", seconds_ago=12)
        later = self.tap("Not now", seconds_ago=11)
        outcome, calls, _, _ = self.turn(later, [])
        self.assertEqual(self.body(outcome), rules.line("shops_stop_all", "en"))
        self.assertEqual(self.state().stop_reason, "stop_all")
        self.assertEqual(calls, [])

    def test_and_in_the_other_order_too(self):
        self.tap("Not now", seconds_ago=12)
        stop = self.tap("Stop messages", seconds_ago=11)
        outcome, _, _, _ = self.turn(stop, [])
        self.assertEqual(self.body(outcome), rules.line("shops_stop_all", "en"))
        self.assertEqual(self.state().stop_reason, "stop_all")

    def test_typed_words_after_a_stop_still_take_it_back(self):
        # The old rule stays for typed text: "Stop" then a real request is no stop (test_assistant holds the model side).
        self.inbound("Stop", seconds_ago=12)
        request = self.inbound("sending me studios, I need a 2BR", seconds_ago=11)
        from apps.leadai.assistant import engine

        burst = [m for m in [self.conversation.messages.get(body="Stop"), request]]
        self.assertIsNone(engine._burst_opt_out(burst, meeting_open=False, shops_chat=True))


class CallRequestWordsTests(SimpleTestCase):
    def test_the_campaigns_words_ask_for_a_call(self):
        for said in (
            "Urgent ‼️ for call 📲",
            "Urgent for call",
            "for a call please",
            "Call please",
            "call pls",
            "need call",
            "asap call",
        ):
            with self.subTest(said):
                self.assertTrue(people.asks_for_call(said))

    def test_no_call_is_still_no_call(self):
        for said in ("don't call me", "no calls please", "I called the owner yesterday", "why did you call me?"):
            with self.subTest(said):
                self.assertFalse(people.asks_for_call(said))


class HoldClaimTests(SimpleTestCase):
    def test_a_hold_code_never_made_is_a_claim(self):
        for sentence in (
            "Great, I have tentatively held the 4:00 PM slot for you today at our office in Russia Cluster.",
            "I've held the 7:00 PM slot for you.",
            "I'll hold the 3:00 PM slot for you.",
            "We have kept the viewing time for you.",
        ):
            with self.subTest(sentence):
                self.assertTrue(residential.claims_done(sentence))

    def test_an_offer_to_hold_is_no_claim(self):
        for sentence in (
            "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?",
            "Would you like me to hold the 4:00 PM slot?",
            "Shall I hold a time for you?",
        ):
            with self.subTest(sentence):
                self.assertFalse(residential.claims_done(sentence))
