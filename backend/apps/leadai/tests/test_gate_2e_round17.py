"""Batch 2e's real-model gate, rounds 15–17 (2026-10-20): shops-mixed-not-known-booking failed in five of six runs — "can I
come today 5 pm and discuss?" in a mixed-template chat whose need is not known came back a tentative at 17:00 with the
segment "other" ("Sure, I can hold a slot for you today at 5:00 PM at our office in Russia Cluster. May I have your full
name to book it?"), and engine._code_may_act, which refuses to book for someone outside our segments, kept code from
booking the customer's own time (T18, upgrade_exact_time). The residential prompt's OUTPUT rule says the segment is
residential_tenant while the track is not known: residential.segment_of forces it there too (RENT_SYSTEM's own words),
so the customer's exact time is booked with the neutral confirmation. A job applicant keeps the model's handover, which
keeps code from booking for them (the general playbook's job-applicant scenario is untouched: not the residential path)."""

from django.test import SimpleTestCase

from apps.leadai.assistant import residential, tracks
from apps.leadai.tests.test_deployed_gate_2d import tentative
from apps.leadai.tests.test_launch_gate import run_eval

HELD_FOR_NAME = "Sure, I can hold a slot for you today at 5:00 PM at our office in Russia Cluster. May I have your full name to book it?"


class NotKnownTrackSegmentTests(SimpleTestCase):
    def test_the_segment_is_forced_while_the_track_is_not_known(self):
        self.assertEqual(residential.segment_of(tracks.UNKNOWN), "residential_tenant")
        self.assertEqual(residential.segment_of(tracks.RENT), "residential_tenant")
        self.assertEqual(residential.segment_of(tracks.SALE), "buyer")
        self.assertEqual(residential.segment_of(tracks.OTHER), "")

    def test_the_rounds_own_answer_books_their_time_now(self):
        run = run_eval("shops-mixed-not-known-booking", tentative(HELD_FOR_NAME, time="17:00", segment="other"))
        self.assertEqual(run.failures, [], run.out)
        self.assertEqual(run.answer["segment"], "residential_tenant")
        self.assertEqual(run.answer["appointment"]["action"], "confirm")
        self.assertNotIn("full name", run.out.lower())
