"""inbox message_list / contact_detail for an agent who holds a chat through the handover desk alone.

A desk-only agent (no Lead AI access, no hold on the chat's number) gets a trimmed conversation on
messages and a 403 on the contact profile. An agent who holds the number keeps both as before.
"""

from django.utils import timezone

from apps.catalog.models import NumberAssignment
from apps.leadai import handover_desk
from apps.leadai.tests.test_desk import DeskBase


class HandoverDeskInboxTrimTests(DeskBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.handed = self.chat(
            handed_over_at=now,
            handover_reason="customer_asked_human",
            desk_at=now,
            desk_reason="customer_asked_human",
            responsible_bitrix_user_id="2500",
            responsible_agent=self.plain,
        )
        # plain holds other_number only — not self.number — so only_through_desk is true.
        self.assertTrue(handover_desk.only_through_desk(self.plain, self.handed))

    def test_desk_only_agent_gets_trimmed_messages_and_403_on_profile(self):
        self.client.force_login(self.plain)
        messages = self.client.get(f"/api/inbox/conversations/{self.handed.pk}/messages/")
        self.assertEqual(messages.status_code, 200)
        row = messages.json()["conversation"]
        self.assertIsNone(row["assigned_agent"])
        self.assertEqual(set(row["number"]), {"id", "phone_number"})
        self.assertIsNone(row.get("lead_ai_info"))
        self.assertIsNone(row.get("leadbot"))

        profile = self.client.get(f"/api/inbox/conversations/{self.handed.pk}/contact/")
        self.assertEqual(profile.status_code, 403)
        self.assertIn("handed-over", profile.json().get("detail", ""))

    def test_number_holder_keeps_full_messages_and_profile(self):
        NumberAssignment.objects.create(number=self.number, agent=self.plain)
        self.assertFalse(handover_desk.only_through_desk(self.plain, self.handed))

        self.client.force_login(self.plain)
        messages = self.client.get(f"/api/inbox/conversations/{self.handed.pk}/messages/")
        self.assertEqual(messages.status_code, 200)
        row = messages.json()["conversation"]
        self.assertEqual(row["assigned_agent"]["display_name"], "Matloob")
        self.assertIn("title", row["number"])

        profile = self.client.get(f"/api/inbox/conversations/{self.handed.pk}/contact/")
        self.assertEqual(profile.status_code, 200)
        body = profile.json()
        self.assertEqual(body["wa_id"], self.handed.contact.wa_id)
        self.assertIn("assigned_agent", body)
        self.assertIn("assignment_history", body)
