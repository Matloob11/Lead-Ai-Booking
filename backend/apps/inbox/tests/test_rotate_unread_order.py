"""Rotate WhatsApp list: unread campaign replies before quiet threads."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import WabaNumber
from apps.inbox.models import Contact, Conversation


User = get_user_model()


class RotateUnreadOrderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="rotate-unread-admin",
            password="x",
            is_wa_admin=True,
        )
        self.number = WabaNumber.objects.create(
            phone_number_id="rotate-unread-pnid",
            phone_number="971500000099",
            waba_business_id="rotate-unread-waba",
            is_active=True,
        )
        now = timezone.now()
        self.read_new = self._thread("read-new", unread=0, last=now)
        self.unread_old = self._thread(
            "unread-old", unread=2, last=now - timezone.timedelta(days=3)
        )
        self.read_old = self._thread(
            "read-old", unread=0, last=now - timezone.timedelta(days=5)
        )
        self.unread_mid = self._thread(
            "unread-mid", unread=1, last=now - timezone.timedelta(days=1)
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _thread(self, wa_id, *, unread, last):
        contact = Contact.objects.create(wa_id=wa_id, profile_name=wa_id)
        return Conversation.objects.create(
            number=self.number,
            contact=contact,
            staff_only=True,
            unread_count=unread,
            last_message_at=last,
        )

    def test_rotate_list_puts_unread_before_read(self):
        response = self.client.get("/api/inbox/conversations/", {"rotate": "1", "limit": 20})
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(
            ids,
            [
                self.unread_mid.pk,
                self.unread_old.pk,
                self.read_new.pk,
                self.read_old.pk,
            ],
        )

    def test_main_list_keeps_staff_only_out(self):
        now = timezone.now()
        contact = Contact.objects.create(wa_id="official-new", profile_name="official-new")
        official = Conversation.objects.create(
            number=self.number,
            contact=contact,
            staff_only=False,
            unread_count=0,
            last_message_at=now,
        )
        response = self.client.get("/api/inbox/conversations/", {"limit": 20})
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(official.pk, ids)
        self.assertNotIn(self.unread_old.pk, ids)
