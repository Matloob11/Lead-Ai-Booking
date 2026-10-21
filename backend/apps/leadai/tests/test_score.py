"""The lead score (assistant/score.py; the advance plan's F1): hot, warm or cold with its reasons from the chat's facts
and events, stored on the state at each turn, written to the lead's two fields (Cursor's C50, allowed since C65) when it
moved, cooled once a day while the customer is quiet, and read by the desk (the chip, ?sort=score)."""

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.inbox.models import Conversation
from apps.leadai.assistant import crm_fields, score
from apps.leadai.models import LeadAiAppointment, LeadAiChatState, LeadAiCrmField
from apps.leadai.tests.test_assistant import NOW, Base
from apps.leadai.tests.test_desk import DeskBase
from apps.leadai.tests.test_residential_turns import RentBase, res_answer

KNOWN = {"budget_aed": 32000.0, "budget_basis": "per_year", "clusters": ["Spain"], "move_in": "next month", "full_name": "Ahmed Khan"}


def appointment(status="confirmed", place="office", starts_at=None):
    return SimpleNamespace(status=status, place=place, starts_at=NOW + dt.timedelta(hours=3) if starts_at is None else starts_at)


class ComputeTests(SimpleTestCase):
    def test_hot_warm_and_cold(self):
        nothing = score.compute(facts={}, now=NOW)
        self.assertEqual((nothing.value, nothing.reasons, nothing.label), (0, (), score.COLD))
        self.assertEqual(nothing.text, "Cold 0: nothing known yet")
        wrote = score.compute(facts={}, now=NOW, last_inbound_at=NOW - dt.timedelta(minutes=5))
        self.assertEqual((wrote.value, wrote.reasons), (10, ("they wrote",)))
        warm = score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, last_inbound_at=NOW)
        self.assertEqual(warm.value, 60)
        self.assertEqual(warm.label, score.WARM)
        self.assertEqual(warm.reasons, ("they wrote", "unit known", "to rent", "budget known", "area known", "moving soon", "full name given"))
        hot = score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, last_inbound_at=NOW, appointment=appointment())
        self.assertEqual((hot.value, hot.label), (85, score.HOT))
        self.assertTrue(hot.text.startswith("Hot 85: they wrote; unit known; to rent; budget known"))
        self.assertIn("visit booked", hot.reasons)
        done = score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, last_inbound_at=NOW, appointment=appointment("done"))
        self.assertEqual((done.value, done.reasons[-1]), (90, "visit done"))
        call = score.compute(facts={}, now=NOW, appointment=appointment(place="call"))
        self.assertEqual(call.reasons, ("call booked",))
        # A booked visit whose time went by without being marked done counts nothing; a held time a little; a cancel less.
        self.assertEqual(score.compute(facts={}, now=NOW, appointment=appointment(starts_at=NOW - dt.timedelta(hours=1))).value, 0)
        self.assertEqual(score.compute(facts={}, now=NOW, appointment=appointment("tentative")).reasons, ("time held",))
        self.assertEqual(score.compute(facts={}, now=NOW, last_inbound_at=NOW, appointment=appointment("cancelled")).value, 0)  # 10 - 15, floored
        # A buyer's timeline, a budget said in words, a flexible cluster.
        buyer = score.compute(facts={"buy_timeline": "within 3 months", "budget": "half a million", "cluster_flexible": True}, track="sale", unit="one_br", now=NOW)
        self.assertEqual(buyer.reasons, ("unit known", "to buy", "budget known", "area known", "move-in known"))
        self.assertEqual(buyer.value, 38)

    def test_how_fast_they_answer_and_the_models_word(self):
        fast = score.compute(facts={}, now=NOW, reply_minutes=[5, 20, 40])
        self.assertEqual(fast.reasons, ("replies within the hour",))
        slow = score.compute(facts={}, now=NOW, last_inbound_at=NOW, reply_minutes=[2000, 3000, 10])
        self.assertEqual((slow.value, slow.reasons), (5, ("they wrote", "slow to reply")))
        self.assertEqual(score.compute(facts={}, now=NOW, reply_minutes=[90, 200]).reasons, ())
        self.assertEqual(score.compute(facts={}, now=NOW, hot=True).reasons, ("wants to move fast",))
        self.assertEqual(score.compute(facts={}, now=NOW, last_inbound_at=NOW, handover_reason="abroad_cannot_visit").value, 5)

    def test_the_nos_and_the_quiet(self):
        self.assertEqual(score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, stopped=True), score.Score(0, ("opted out",)))
        self.assertEqual(score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, not_interested=True), score.Score(0, ("not interested",)))
        for facts, reason in ((KNOWN, "broker_or_for_client"), ({**KNOWN, "for_client": True}, "")):
            self.assertEqual(score.compute(facts=facts, track="rent", unit="studio", now=NOW, handover_reason=reason).value, 5)
        quiet = score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, last_inbound_at=NOW - dt.timedelta(days=4))
        self.assertEqual((quiet.value, quiet.reasons[-1]), (50, "quiet 4 days"))
        long = score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, last_inbound_at=NOW - dt.timedelta(days=9))
        self.assertEqual((long.value, long.reasons[-1]), (40, "quiet 9 days"))
        # Never past the ends.
        top = score.compute(facts=KNOWN, track="rent", unit="studio", now=NOW, last_inbound_at=NOW, appointment=appointment("done"), reply_minutes=[1], hot=True)
        self.assertEqual(top.value, 100)
        self.assertEqual(score.label_of(None), score.COLD)
        self.assertEqual((score.label_of(70), score.label_of(40), score.label_of(39)), (score.HOT, score.WARM, score.COLD))

    def test_the_writes_pass_the_tools_own_checks(self):
        scored = score.compute(facts={}, now=NOW)
        rows = [LeadAiCrmField(lead_id=555, field=field, value=str(value)[:255], payload=payload) for field, value, payload in score.writes(scored)]
        body = crm_fields.body_for(rows)
        self.assertEqual(body["fields"], {crm_fields.FIELD_AI_SCORE: 0, crm_fields.FIELD_AI_SCORE_WHY: "Cold 0: nothing known yet"})
        self.assertEqual(crm_fields.refusal(body), "")
        self.assertIn("not a number", crm_fields.refusal({"lead_id": 555, "fields": {crm_fields.FIELD_AI_SCORE: -1}}))
        self.assertIn("not text", crm_fields.refusal({"lead_id": 555, "fields": {crm_fields.FIELD_AI_SCORE_WHY: ""}}))


class TurnTests(RentBase):
    def scores(self):
        return list(LeadAiCrmField.objects.filter(conversation=self.conversation, field=crm_fields.FIELD_AI_SCORE).order_by("pk").values_list("value", flat=True))

    def test_a_rent_turn_scores_the_chat_and_writes_the_lead_when_it_moved(self):
        self.rent(clusters=["Spain"])
        message = self.inbound("Balcony would be nice, next month")
        self.turn(message, [res_answer("Great. Any cluster you prefer, or are you flexible?", facts={"balcony": "yes", "move_in": "next month"})])
        state = self.state()
        self.assertIsNotNone(state.score)
        self.assertEqual(state.scored_at, NOW)
        self.assertTrue(state.score_reasons.startswith(f"{state.score_reasons.split()[0]} {state.score}:"))
        self.assertIn("unit known", state.score_reasons)
        self.assertEqual(self.actions(message)["score"], state.score)
        rows = {row.field: row.value for row in LeadAiCrmField.objects.filter(conversation=self.conversation, field__in=[crm_fields.FIELD_AI_SCORE, crm_fields.FIELD_AI_SCORE_WHY])}
        self.assertEqual(rows, {crm_fields.FIELD_AI_SCORE: str(state.score), crm_fields.FIELD_AI_SCORE_WHY: state.score_reasons})
        # Scored again with nothing moved: no new row (score.update says so; crm_fields.queue keeps only news anyway).
        scored, moved = score.update(self.conversation, self.state(), now=NOW)
        self.assertEqual((scored.value, moved), (state.score, False))
        self.assertEqual(len(self.scores()), 1)

    def test_a_booking_makes_it_hot_and_the_lead_hears_it(self):
        self.rent(clusters=["Spain"], full_name="Ahmed Khan", move_in="next month")
        before = self.state().score
        self.assertIsNone(before)
        message = self.inbound("Tomorrow at 5 pm")
        self.turn(message, [res_answer("Perfect, see you tomorrow at 5 PM.", action="confirm", place="office", date="2026-10-13", time="17:00")])
        state = self.state()
        self.assertGreaterEqual(state.score, 60)
        self.assertIn("visit booked", state.score_reasons)
        self.assertEqual(self.scores(), [str(state.score)])


class DeskTests(DeskBase):
    def test_the_rows_carry_the_score_and_sort_hot_first_when_asked(self):
        hot = self.chat(name="Hot", score=82, score_reasons="Hot 82: visit booked; unit known", scored_at=NOW)
        cold = self.chat(name="Cold", score=12, score_reasons="Cold 12: they wrote", scored_at=NOW)
        unscored = self.chat(name="New")
        Conversation.objects.filter(pk=hot.pk).update(last_message_at=NOW - dt.timedelta(hours=3))
        Conversation.objects.filter(pk=cold.pk).update(last_message_at=NOW - dt.timedelta(hours=2))
        Conversation.objects.filter(pk=unscored.pk).update(last_message_at=NOW - dt.timedelta(hours=1))
        newest_first = [row["id"] for row in self.rows(self.desker)["results"]]
        self.assertEqual(newest_first, [unscored.pk, cold.pk, hot.pk])
        payload = self.rows(self.desker, "?sort=score")
        self.assertEqual([row["id"] for row in payload["results"]], [hot.pk, cold.pk, unscored.pk])
        by_id = {row["id"]: row["lead_ai_ai"]["score"] for row in payload["results"]}
        self.assertEqual(by_id[hot.pk], {"value": 82, "label": "hot", "reasons": "Hot 82: visit booked; unit known"})
        self.assertEqual(by_id[cold.pk]["label"], "cold")
        self.assertIsNone(by_id[unscored.pk])
        self.client.force_login(self.desker)
        self.assertEqual(self.client.get("/api/leadai/chats/?sort=x").status_code, 400)
        # The desk's own views keep their order.
        self.assertEqual(self.client.get("/api/leadai/chats/?needs=1&sort=score").status_code, 200)


class RescoreTests(Base):
    def test_a_quiet_chat_cools_down_once_a_day(self):
        state = LeadAiChatState.for_conversation(self.conversation)
        LeadAiChatState.objects.filter(pk=state.pk).update(
            track="rent", unit="studio", facts=KNOWN, score=60, score_reasons="Warm 60: x", scored_at=NOW - dt.timedelta(days=2)
        )
        self.inbound("Balcony would be nice, next month", seconds_ago=5 * 24 * 3600)
        Conversation.objects.filter(pk=self.conversation.pk).update(last_message_at=NOW - dt.timedelta(days=5))
        self.assertEqual(score.rescore_quiet(NOW), 1)
        state.refresh_from_db()
        self.assertEqual((state.score, state.scored_at), (50, NOW))
        self.assertIn("quiet 5 days", state.score_reasons)
        self.assertEqual(LeadAiCrmField.objects.filter(conversation=self.conversation, field=crm_fields.FIELD_AI_SCORE).count(), 1)
        # Scored today already, or nothing moved: left alone.
        self.assertEqual(score.rescore_quiet(NOW), 0)
        LeadAiChatState.objects.filter(pk=state.pk).update(scored_at=NOW - dt.timedelta(days=2))
        self.assertEqual(score.rescore_quiet(NOW), 0)

    def test_their_reply_times_are_read_from_the_chat(self):
        # Our message two hours ago (the campaign), theirs now: 120 minutes. Read in time order, not by row.
        self.inbound("Yes", seconds_ago=0)
        self.assertEqual(score.reply_minutes_for(self.conversation), [120])
        self.assertEqual(score.last_inbound_at(self.conversation), NOW)
        self.inbound("Earlier", seconds_ago=3 * 24 * 3600)  # a row stored later for an older message: still before ours
        self.assertEqual(score.reply_minutes_for(self.conversation), [120])
        self.assertEqual(score.last_inbound_at(self.conversation), NOW)
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=NOW + dt.timedelta(hours=2))
        scored, moved = score.update(self.conversation, LeadAiChatState.for_conversation(self.conversation), now=NOW)
        self.assertTrue(moved)
        self.assertIn("visit booked", scored.reasons)
