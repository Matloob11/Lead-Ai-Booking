"""Who above the responsible hears an escalation (assistant/escalation.py; Cursor's C49 map endpoint; round 20): the team
lead and the department head of the lead's responsible (else the chat's owner) get the handover_waiting alert too
(people.escalate_waiting), each once; nobody when the map is off, unknown or failing, and the alert goes as before."""

import datetime as dt
import json
from unittest.mock import patch

import httpx
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.leadai.assistant import alerts, escalation, people
from apps.leadai.models import LeadAiAlert
from apps.leadai.tests.test_assistant import NOW
from apps.leadai.tests.test_review_2d import ReviewBase

MAP_URL = "https://bitrix.test/bitrix/tools/a7_leadai_escalation.php"
MAP = {"ok": True, "map": {"2311": {"lead": 2560, "head": 60}, "5": {"lead": 1, "head": 9}, "6": {"lead": 9, "head": 9}, "7": {"lead": 0, "head": 7}}, "count": 4}


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def answers(body):
    return patch.object(escalation.httpx, "post", return_value=FakeResponse(body))


@override_settings(LEADAI_BITRIX_ESCALATION_URL=MAP_URL, CRM_LEAD_WA_SECRET="test-crm-secret")
class MapTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_whole_map_is_asked_once_and_signed(self):
        posts = []

        def fake_post(url, *, content, headers, timeout):
            posts.append((url, content, headers))
            return FakeResponse(MAP)

        with patch.object(escalation.httpx, "post", side_effect=fake_post):
            self.assertEqual(escalation.above("2311"), ["2560", "60"])
            self.assertEqual(escalation.above(2311), ["2560", "60"])
            self.assertEqual(escalation.above("5"), ["9"])  # user 1 holds unassigned leads: nobody's work
            self.assertEqual(escalation.above("6"), ["9"])  # the same person once
            self.assertEqual(escalation.above("7"), [])  # 0 is unknown; themselves is nobody
            self.assertEqual(escalation.above("8"), [])  # not in the map
        self.assertEqual(len(posts), 1)  # one call for everyone, kept
        url, raw, headers = posts[0]
        self.assertEqual((url, json.loads(raw)), (MAP_URL, {}))
        self.assertEqual(headers["X-Leadai-Sign"], escalation.sign(raw, headers["X-Leadai-Ts"], "test-crm-secret"))
        self.assertNotEqual(headers["X-Leadai-Sign"], alerts.sign(raw, headers["X-Leadai-Ts"], "test-crm-secret"))  # its own prefix

    def test_nobody_when_unknown_off_or_failing(self):
        with patch.object(escalation.httpx, "post", side_effect=httpx.ConnectError("x")):
            self.assertEqual(escalation.above("2311"), [])
        cache.clear()
        with patch.object(escalation.httpx, "post", side_effect=RuntimeError("a bad URL, a surprise")):
            self.assertEqual(escalation.above("2311"), [])  # never raises: the alert must still go
        cache.clear()
        with answers({"ok": False, "error": "Unauthorized."}):
            self.assertEqual(escalation.above("2311"), [])
        cache.clear()
        with answers(ValueError("not JSON")):
            self.assertEqual(escalation.above("2311"), [])
        cache.clear()
        with answers({"ok": True, "map": "x"}):
            self.assertEqual(escalation.above("2311"), [])
        cache.clear()
        with answers({"ok": True, "map": {"2311": {"lead": "abc", "head": None}, "x": {"lead": 1}}}):
            self.assertEqual(escalation.above("2311"), [])
        for who in ("", "0", "1", "abc", None):
            with self.subTest(who=who):
                self.assertEqual(escalation.above(who), [])
        cache.clear()
        with override_settings(LEADAI_BITRIX_ESCALATION_URL=""), patch.object(escalation.httpx, "post", side_effect=AssertionError("asked")):
            self.assertEqual(escalation.above("2311"), [])

    def test_a_failure_is_asked_again_sooner_than_an_answer(self):
        with patch.object(escalation, "cache") as fake:
            fake.get.return_value = None
            with answers(MAP):
                self.assertEqual(escalation.above("2311"), ["2560", "60"])
            fake.set.assert_called_once_with(escalation.CACHE_KEY, {"2311": {"lead": 2560, "head": 60}, "5": {"lead": 1, "head": 9}, "6": {"lead": 9, "head": 9}, "7": {"head": 7}}, escalation.CACHE_SECONDS)
            fake.set.reset_mock()
            with patch.object(escalation.httpx, "post", side_effect=httpx.ReadTimeout("slow")):
                self.assertEqual(escalation.above("2311"), [])
            fake.set.assert_called_once_with(escalation.CACHE_KEY, {}, escalation.CACHE_SECONDS // 10)


class EscalationReachesAboveTests(ReviewBase):
    def handed(self, minutes_ago=40, reason="call_requested", **fields):
        self.inbound("We can have a call at 11.30 - 12 PM", seconds_ago=minutes_ago * 60 + 20)
        self.ours(people.line(people.CALL_PASSED, "en", shops=True), minutes_ago=minutes_ago)
        self.set_state(handed_over_at=NOW - dt.timedelta(minutes=minutes_ago), handover_reason=reason, **fields)

    def waiting(self):
        return list(LeadAiAlert.objects.filter(conversation=self.conversation, kind=people.WAITING).order_by("pk"))

    def test_the_responsibles_lead_and_head_hear_the_escalation_once(self):
        self.handed(responsible_bitrix_user_id="88")
        with patch.object(escalation, "above", return_value=["2560", "2311"]) as above:
            self.assertEqual(people.escalate_waiting(NOW), 1)
        above.assert_called_once_with("88")
        rows = self.waiting()
        ids = [row.bitrix_user_id for row in rows]
        self.assertIn("2560", ids)  # the team lead, by their Bitrix id (no agent row)
        self.assertEqual(ids.count("2311"), 1)  # Matloob is listed already: not twice, though the map named them too
        self.assertEqual(ids.count("88"), 1)
        for row in rows:
            self.assertIn("The responsible's team lead and department head were sent this alert too.", row.text)
        lead_row = next(row for row in rows if row.bitrix_user_id == "2560")
        self.assertIsNone(lead_row.agent)
        self.assertEqual(lead_row.dedupe_key.rsplit(":", 1)[1], "b2560")
        # Nothing twice: the sweep again adds no row.
        with patch.object(escalation, "above", return_value=["2560", "2311"]):
            self.assertEqual(people.escalate_waiting(NOW), 0)
        self.assertEqual(len(self.waiting()), len(rows))

    def test_no_responsible_or_a_hold_user_asks_for_the_owner(self):
        self.handed()
        with patch.object(escalation, "above", return_value=[]) as above:
            self.assertEqual(people.escalate_waiting(NOW), 1)
        above.assert_called_once_with("77")  # the chat's owner
        rows = self.waiting()
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("team lead", row.text)
        # A lead held by Bitrix user 1 (unassigned) is nobody's: the owner's people again (alerts.recipients reads it so).
        LeadAiAlert.objects.all().delete()
        self.set_state(responsible_bitrix_user_id="1")
        with patch.object(escalation, "above", return_value=["2560"]) as above:
            self.assertEqual(people.escalate_waiting(NOW), 1)
        above.assert_called_once_with("77")
        self.assertIn("2560", [row.bitrix_user_id for row in self.waiting()])

    def test_a_lead_with_an_agent_row_gets_their_own_row_once(self):
        from apps.accounts.models import Agent

        lead = Agent.objects.create_user(username="lead", password="x", bitrix_user_id="2560", can_official_api=True, display_name="Lead")
        self.handed(responsible_bitrix_user_id="88")
        with patch.object(escalation, "above", return_value=["2560", "2560"]):
            self.assertEqual(people.escalate_waiting(NOW), 1)
        rows = [row for row in self.waiting() if row.bitrix_user_id == "2560"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].agent, lead)
