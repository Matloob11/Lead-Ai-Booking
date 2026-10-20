"""The daily digest (assistant/digest.py; the advance plan's A2): the day's figures from the tables, the words, one row a
day sent once to the admins and the alert list, the days the sweep missed stored quietly, and the Reports endpoint."""

import datetime as dt
from unittest.mock import patch

from django.test import override_settings

from apps.inbox.models import Message
from apps.leadai.assistant import digest, hours
from apps.leadai.models import LeadAiAppointment, LeadAiDigest, LeadAiDraftOutcome, LeadAiOptOut, LeadAiSettings, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, Base

DAY = hours.now_dubai(NOW).date()


class DigestBase(Base):
    def setUp(self):
        super().setUp()
        LeadAiSettings.objects.filter(pk=1).update(alert_bitrix_user_ids=["2311"])

    def a_turn(self, *, status="replied", latency_ms=2500, actions=None, minutes_ago=60, model="gpt-4.1-mini-2025-04-14"):
        return LeadAiTurn.objects.create(
            conversation=self.conversation, status=status, model=model, calls=1, prompt_tokens=10_000, completion_tokens=500,
            latency_ms=latency_ms, actions=actions or {}, created_at=NOW - dt.timedelta(minutes=minutes_ago),
        )


class ComputeTests(DigestBase):
    def test_the_days_figures_tie_to_the_tables(self):
        self.a_turn(minutes_ago=120)
        self.a_turn(minutes_ago=90, latency_ms=75_000)  # late: over a minute
        self.a_turn(minutes_ago=80, status="skipped")
        self.a_turn(minutes_ago=70, status="failed")
        self.a_turn(minutes_ago=60, actions={"handover": "call_requested"})
        # A person wrote 14 minutes after the handover: taken, by Nabiha.
        Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEXT, body="Calling you now",
            sent_by=self.agent, created_at=NOW - dt.timedelta(minutes=46),
        )
        LeadAiDraftOutcome.objects.create(conversation=self.conversation, kind="auto", draft_text="x")
        LeadAiDraftOutcome.objects.create(conversation=self.conversation, kind="sent", draft_text="y", sent_text="y")
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=NOW + dt.timedelta(days=1))
        LeadAiAppointment.objects.create(conversation=self.conversation, status="tentative", place="call", starts_at=NOW + dt.timedelta(days=1))
        LeadAiOptOut.objects.create(phone="971509999999", source="leadai_stop", reason="stop", created_at=NOW - dt.timedelta(minutes=5))
        # Yesterday's turn is another day's.
        self.a_turn(minutes_ago=36 * 60)

        stats = digest.compute(DAY, NOW)
        self.assertEqual(stats["turns"], {"replied": 3, "skipped": 1, "failed": 1, "late": 1, "p50_ms": 2500, "p95_ms": 75_000})
        self.assertEqual(stats["chats"]["answered"], 1)
        self.assertEqual(stats["handovers"]["new"], 1)
        self.assertEqual(stats["handovers"]["taken"], 1)
        self.assertEqual(stats["handovers"]["median_minutes"], 14)
        self.assertEqual(stats["handovers"]["by"], {"Nabiha": 1})
        self.assertEqual(stats["handovers"]["reasons"], {"asked for a call": 1})
        self.assertEqual(stats["drafts"], {"sent": 1, "edited": 0, "auto": 1, "dismissed": 0})
        self.assertEqual((stats["bookings"]["created"], stats["bookings"]["visits"], stats["bookings"]["calls"], stats["bookings"]["confirmed"]), (2, 1, 1, 1))
        self.assertEqual(stats["opt_outs"], {"total": 1, "by_source": {"leadai_stop": 1}})
        # 5 turns of the day × (10,000 × $0.40 + 500 × $1.60) per million = $0.024.
        self.assertEqual(stats["cost"]["prompt_tokens"], 50_000)
        self.assertEqual(stats["cost"]["usd"], 0.02)
        self.assertEqual(stats["cost"]["calls"], 5)
        text = digest.text(stats)
        self.assertTrue(text.startswith(f"Lead AI — {DAY:%A} {DAY.day} {DAY:%b %Y}"))
        self.assertIn("Replies: 3 in 1 chats (1 skipped, 1 failed); 1 late (over a minute); median 2.5 s.", text)
        self.assertIn("Handovers: 1 new; 1 taken by a person (median 14 min; Nabiha 1); 0 waiting now. Why: asked for a call 1.", text)
        self.assertIn("Drafts: 1 sent as written, 0 edited, 1 went out by themselves, 0 dismissed.", text)
        self.assertIn("Bookings: 2 (1 office visits, 1 calls); 1 confirmed, 1 tentative, 0 cancelled.", text)
        self.assertIn("Opt-outs: 1. Lead AI: asked us to stop 1.", text)
        self.assertNotIn("9999", text)  # never a customer's number

    def test_the_ai_s_own_reply_is_no_persons_and_an_untaken_handover_waits(self):
        self.a_turn(minutes_ago=60, actions={"handover": "unclear"})
        Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEXT, body="One moment please",
            payload={"source": "leadai_ai"}, created_at=NOW - dt.timedelta(minutes=59),
        )
        stats = digest.compute(DAY, NOW)
        self.assertEqual((stats["handovers"]["new"], stats["handovers"]["taken"], stats["handovers"]["median_minutes"]), (1, 0, None))

    def test_prices_by_model_name(self):
        self.assertEqual(digest.price_of("gpt-4.1-mini-2025-04-14"), (0.40, 1.60))
        self.assertEqual(digest.price_of("gpt-4.1-2025-04-14"), (2.00, 8.00))
        self.assertEqual(digest.price_of(""), digest.DEFAULT_PRICE)
        with override_settings(LEADAI_MODEL_PRICES={"gpt-4.1-mini": [0.2, 0.8]}):
            self.assertEqual(digest.price_of("gpt-4.1-mini-2025-04-14"), (0.2, 0.8))


class SendTests(DigestBase):
    def test_one_row_a_day_sent_once_to_the_admins_and_the_list(self):
        self.admin.bitrix_user_id = "501"
        self.admin.save(update_fields=["bitrix_user_id"])
        self.assertEqual(digest.recipients(), [501, 2311])
        with patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True}) as notify:
            row = digest.send(DAY, now=NOW)
        self.assertEqual(row.sent_to, [501, 2311])
        self.assertEqual(row.errors, [])
        self.assertEqual(notify.call_count, 2)
        kwargs = notify.call_args_list[0].kwargs
        self.assertEqual((kwargs["to_user_id"], kwargs["title"]), (501, digest.TITLE))
        self.assertTrue(kwargs["message"].startswith("Lead AI — "))
        self.assertEqual(kwargs["tag"], f"LEADAI|DIGEST|{DAY:%Y%m%d}|501")
        # The same day again: nothing, and no second bell.
        with patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True}) as notify:
            self.assertIsNone(digest.send(DAY, now=NOW))
        notify.assert_not_called()
        self.assertEqual(LeadAiDigest.objects.count(), 1)

    def test_a_refusal_is_kept_and_the_others_still_go(self):
        self.admin.bitrix_user_id = "501"
        self.admin.save(update_fields=["bitrix_user_id"])
        answers = iter([{"ok": False, "error": "No such active user."}, {"ok": True}])
        with patch("apps.leadai.assistant.alerts.notify_bitrix", side_effect=lambda **kw: next(answers)):
            row = digest.send(DAY, now=NOW)
        self.assertEqual(row.sent_to, [2311])
        self.assertEqual(row.errors, [{"user": 501, "error": "No such active user."}])


class SweepTests(DigestBase):
    def test_yesterday_goes_with_a_bell_from_eight_and_older_days_quietly(self):
        yesterday = DAY - dt.timedelta(days=1)
        early = dt.datetime.combine(DAY, dt.time(7, 30), tzinfo=hours.DUBAI)
        # The older days have theirs; before eight, yesterday's waits for the hour.
        for offset in range(2, digest.BACKFILL_DAYS + 1):
            LeadAiDigest.objects.create(day=DAY - dt.timedelta(days=offset), stats={}, text="")
        self.assertIsNone(digest.due(early))
        at_eight = dt.datetime.combine(DAY, dt.time(8, 0), tzinfo=hours.DUBAI)
        self.assertEqual(digest.due(at_eight), yesterday)
        with patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True}) as notify:
            self.assertEqual(digest.sweep(at_eight), yesterday)
        notify.assert_called_once()
        self.assertEqual(LeadAiDigest.objects.get(day=yesterday).sent_to, [2311])
        self.assertIsNone(digest.sweep(at_eight))

    def test_missed_days_are_backfilled_without_a_bell(self):
        at_noon = dt.datetime.combine(DAY, dt.time(12, 0), tzinfo=hours.DUBAI)
        stored = []
        with patch("apps.leadai.assistant.alerts.notify_bitrix", return_value={"ok": True}) as notify:
            for _ in range(digest.BACKFILL_DAYS + 1):
                stored.append(digest.sweep(at_noon))
        self.assertEqual(stored[-1], None)
        self.assertEqual(sorted(day for day in stored if day), [DAY - dt.timedelta(days=offset) for offset in range(digest.BACKFILL_DAYS, 0, -1)])
        notify.assert_called_once()  # yesterday's bell alone
        self.assertEqual(LeadAiDigest.objects.get(day=DAY - dt.timedelta(days=1)).sent_to, [2311])
        self.assertEqual(LeadAiDigest.objects.get(day=DAY - dt.timedelta(days=3)).sent_to, [])

    def test_the_sweep_step_runs_inside_the_minute_sweep(self):
        from apps.leadai import tasks

        with patch("apps.leadai.assistant.digest.sweep", return_value=None) as sweep:
            tasks.send_due_reminders()
        sweep.assert_called_once()


class EndpointTests(DigestBase):
    def test_the_reports_endpoint_gives_today_and_the_stored_days(self):
        LeadAiDigest.objects.create(day=DAY - dt.timedelta(days=1), stats={"turns": {"replied": 7}}, text="Lead AI — yesterday", sent_to=[2311])
        self.a_turn(minutes_ago=10)
        self.client.force_login(self.agent)
        response = self.client.get("/api/leadai/digests/?days=5")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["today"]["day"], DAY.isoformat())
        self.assertEqual(data["today"]["stats"]["turns"]["replied"], 1)
        self.assertEqual([row["day"] for row in data["digests"]], [(DAY - dt.timedelta(days=1)).isoformat()])
        self.assertEqual(data["digests"][0]["sent_to"], [2311])
        self.assertEqual(data["digest_hour"], 8)
        self.assertEqual(self.client.get("/api/leadai/digests/?days=zzz").status_code, 200)
