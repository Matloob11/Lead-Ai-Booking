"""ops/wa.sh leadai-health (management/commands/leadai_health.py; the advance plan's A5): one screen, read only, exit 1
when something is red."""

import datetime as dt
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

from apps.leadai.models import LeadAiChatState, LeadAiSettings, LeadAiTurn, LeadAiUnit
from apps.leadai.tests.test_assistant import NOW, Base


class HealthTests(Base):
    def run_health(self):
        out = StringIO()
        with patch("apps.leadai.management.commands.leadai_health.queue_depth", return_value=3), patch(
            "apps.leadai.assistant.openai_client.configured", return_value=True
        ):
            call_command("leadai_health", stdout=out)
        return out.getvalue()

    def test_a_healthy_screen(self):
        LeadAiSettings.objects.filter(pk=1).update(last_sweep_at=NOW - dt.timedelta(seconds=30))
        LeadAiTurn.objects.create(conversation=self.conversation, status="replied", latency_ms=2000, created_at=NOW - dt.timedelta(minutes=5))
        LeadAiUnit.objects.create(source="pf", source_id="u1", community="International City", unit="studio", deal="rent", price=30000, title="x")
        text = self.run_health()
        self.assertIn("  switch: on", text)
        self.assertIn("  sweep (worker-leadai): 30 s ago", text)
        self.assertIn("  leadai queue: 3 waiting", text)
        self.assertIn("  last hour: 1 replied, 0 skipped, 0 failed (0%); 0 late; p50 2.0 s, p95 2.0 s", text)
        self.assertIn("  inventory: 1 live (pf 1, bitrix 0), synced", text)
        self.assertIn("! digest: none yet", text)
        self.assertIn("today so far: Replies: 1 in 1 chats", text)
        self.assertTrue(text.strip().endswith("HEALTH: WARN"), text)

    def test_a_dead_sweep_and_a_missing_key_are_red(self):
        LeadAiSettings.objects.filter(pk=1).update(last_sweep_at=NOW - dt.timedelta(minutes=20))
        LeadAiChatState.objects.create(conversation=self.conversation, handed_over_at=NOW - dt.timedelta(hours=2), handover_reason="unclear")
        out = StringIO()
        with patch("apps.leadai.management.commands.leadai_health.queue_depth", return_value=None), self.assertRaises(SystemExit):
            call_command("leadai_health", stdout=out)
        text = out.getvalue()
        self.assertIn("X sweep (worker-leadai): 20 min ago", text)
        self.assertIn("! leadai queue: unreachable", text)
        self.assertIn("  handed over (3 days): 1 chats, oldest 2.0 h ago", text)
        self.assertIn("X openai key: MISSING", text)
        self.assertIn("HEALTH: FAIL", text)
