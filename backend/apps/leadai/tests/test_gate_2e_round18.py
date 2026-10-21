"""Batch 2e's real-model gate, round 18 (2026-10-21): 576 of 584 (98.6%), the model's own words 307 of 314 (97.8%), but
the every-run rule failed on one code scenario, one run, and a sale scenario failed both runs:

- shops-gate-half-hour #2: "Can I come today at 4:30?" got "I can hold a slot for you today at 4:00 PM or 6:00 PM — which
  is better?" with the hourly reason in the English gloss alone ("Our office slots start on the hour or half hour. …" in
  reply_en). engine.passed_over_hour read the reply only (round 11's fix); it reads reply_en too now.
- shops-sale-abroad #1 and #2: "I am in London now, I can't come to the office" got the model's own call offer with no
  abroad_cannot_visit handover, so sales.abroad never set the abroad call and the generic call-slots line went instead
  of the abroad line (rounds 16 and 17 had the handover in every run). sales.abroad reads their own words now
  (abroad_words), so a buyer abroad gets the abroad line and two call slots whatever the model tagged.
"""

from django.test import SimpleTestCase

from apps.leadai.assistant import engine, sales
from apps.leadai.tests.test_deployed_gate_2d import CAN_I_COME, at, tentative
from apps.leadai.tests.test_eval_command import answer as eval_answer
from apps.leadai.tests.test_launch_gate import run_eval
from apps.leadai.tests.test_residential_turns import res_answer

FOUR_OR_SIX = "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?"
GLOSS = "Our office slots start on the hour or half hour. I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?"
LONDON = "I understand you're in London and can't visit our office. We can arrange a call to discuss your studio purchase options. Would you be available for a quick call today at 3:00 PM or 4:00 PM Dubai time?"


class HourlyGlossTests(SimpleTestCase):
    def test_the_hourly_reason_in_the_gloss_books_their_half_hour(self):
        live = tentative(FOUR_OR_SIX, reply_en=GLOSS, words=CAN_I_COME, share_location=True, maker=eval_answer)
        run = run_eval("shops-gate-half-hour", live)
        self.assertEqual((run.failures, run.when), ([], at(12, 16, 30)))
        self.assertNotIn("on the hour", run.out)
        # The reply's own words alone (no gloss, no reason) keep round 1's rule: the two offered slots stand, nothing is
        # booked for them (test_gate_2e_round11: FOUR_OR_SIX upgrades nothing).
        plain = tentative(FOUR_OR_SIX, reply_en="", words=CAN_I_COME, share_location=True, maker=eval_answer)
        run = run_eval("shops-gate-half-hour", plain)
        self.assertIn("4:00 PM or 6:00 PM", run.out)
        self.assertNotEqual(run.when, at(12, 16, 30))


class AbroadWordsTests(SimpleTestCase):
    def test_their_words_say_abroad(self):
        for text in ("I am in London now, I can't come to the office", "I'm abroad till December", "We are in Pakistan these days", "not in Dubai at the moment", "outside UAE"):
            with self.subTest(text):
                self.assertTrue(sales.abroad_words(text))
        for text in ("I live in Spain cluster", "Can I come today at 5 pm?", "I am in the office now", ""):
            with self.subTest(text):
                self.assertFalse(sales.abroad_words(text))
        self.assertTrue(sales.abroad({"needed": False, "reason": None}, {}, "I am in London now"))
        self.assertTrue(sales.abroad({"needed": True, "reason": "abroad_cannot_visit"}, {}, "ok"))
        self.assertFalse(sales.abroad({"needed": False, "reason": None}, {}, "ok"))

    def test_the_rounds_own_answer_gets_the_abroad_line_now(self):
        run = run_eval("shops-sale-abroad", res_answer(LONDON, segment="buyer"))
        self.assertEqual(run.failures, [], run.out)
        self.assertEqual((run.answer.get("sale") or {}).get("kind"), sales.ABROAD)
        self.assertIn("quick 5-minute call with our sales team", run.out)
