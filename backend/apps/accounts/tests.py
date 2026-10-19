"""/api/auth/me/ tells the panel whether the agent has Lead AI access (Agent.can_lead_ai with the Official API inbox,
apps/leadai/lane.has_desk_access): an agent who holds no number still opens the Lead AI screen from the no-number card
(modules/access-requests.js "Open Lead AI"), so the field is there with or without numbers."""

from django.test import TestCase

from apps.accounts.models import Agent
from apps.accounts.views import _serialize


class MeLeadAiAccessTests(TestCase):
    def agent(self, **fields):
        return Agent.objects.create_user(username=f"a{Agent.objects.count()}", password="x", bitrix_user_id="1", **fields)

    def test_lead_ai_access_with_the_official_inbox(self):
        self.assertTrue(_serialize(self.agent(can_official_api=True, can_lead_ai=True))["can_lead_ai"])

    def test_no_official_inbox_means_no_desk(self):
        self.assertFalse(_serialize(self.agent(can_official_api=False, can_lead_ai=True))["can_lead_ai"])

    def test_default_is_off(self):
        self.assertFalse(_serialize(self.agent(can_official_api=True))["can_lead_ai"])

    def test_with_no_number_at_all(self):
        data = _serialize(self.agent(can_official_api=True, can_lead_ai=True))
        self.assertEqual(data["numbers"], [])
        self.assertTrue(data["can_lead_ai"])
