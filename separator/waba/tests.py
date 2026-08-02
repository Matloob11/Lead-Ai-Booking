import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from separator.bitrix.placements import WabaPlacementModule
from separator.waba.models import Phone, SessionWindow, normalize_msisdn


class NormalizeMsisdnTests(TestCase):
    def test_strips_formatting_and_prefixes_plus(self):
        self.assertEqual(normalize_msisdn("+7 (999) 123-45-67"), "+79991234567")
        self.assertEqual(normalize_msisdn("79991234567"), "+79991234567")
        self.assertEqual(normalize_msisdn("wa:79991234567"), "+79991234567")

    def test_empty_input_returns_empty_string(self):
        for value in (None, "", "   ", "abc"):
            self.assertEqual(normalize_msisdn(value), "")


class SessionWindowTests(TestCase):
    def setUp(self):
        self.phone = Phone.objects.create(phone="+15550001111", phone_id="pnid-1")
        self.other_phone = Phone.objects.create(phone="+15550002222", phone_id="pnid-2")
        self.customer = "+79991234567"

    def test_touch_creates_open_window(self):
        window = SessionWindow.touch(self.phone, self.customer)

        self.assertIsNotNone(window)
        self.assertTrue(window.is_open)
        self.assertEqual(window.customer_phone, self.customer)
        # Fresh window should have close to the full 24h left.
        self.assertGreater(window.remaining_seconds, 23 * 3600)
        self.assertLessEqual(window.remaining_seconds, 24 * 3600)

    def test_window_older_than_24h_is_closed(self):
        stale = timezone.now() - timedelta(hours=24, minutes=1)
        SessionWindow.touch(self.phone, self.customer, when=stale)

        is_open, window = SessionWindow.status_for(self.phone, self.customer)
        self.assertFalse(is_open)
        self.assertIsNotNone(window)
        self.assertEqual(window.remaining_seconds, 0)

    def test_window_just_inside_24h_is_open(self):
        recent = timezone.now() - timedelta(hours=23, minutes=59)
        SessionWindow.touch(self.phone, self.customer, when=recent)

        is_open, _window = SessionWindow.status_for(self.phone, self.customer)
        self.assertTrue(is_open)

    def test_new_inbound_message_reopens_window(self):
        stale = timezone.now() - timedelta(hours=30)
        SessionWindow.touch(self.phone, self.customer, when=stale)
        self.assertFalse(SessionWindow.status_for(self.phone, self.customer)[0])

        SessionWindow.touch(self.phone, self.customer)
        self.assertTrue(SessionWindow.status_for(self.phone, self.customer)[0])

    def test_out_of_order_delivery_does_not_move_anchor_backwards(self):
        newest = timezone.now()
        SessionWindow.touch(self.phone, self.customer, when=newest, wamid="wamid.new")

        older = newest - timedelta(hours=5)
        SessionWindow.touch(self.phone, self.customer, when=older, wamid="wamid.old")

        window = SessionWindow.objects.get(phone=self.phone, customer_phone=self.customer)
        self.assertEqual(window.last_inbound_at, newest)
        self.assertEqual(window.last_inbound_wamid, "wamid.new")

    def test_touch_is_idempotent_per_phone_and_customer(self):
        SessionWindow.touch(self.phone, self.customer)
        SessionWindow.touch(self.phone, self.customer)

        self.assertEqual(
            SessionWindow.objects.filter(phone=self.phone, customer_phone=self.customer).count(),
            1,
        )

    def test_windows_are_scoped_per_business_phone(self):
        SessionWindow.touch(self.phone, self.customer)

        self.assertTrue(SessionWindow.status_for(self.phone, self.customer)[0])
        # Same customer on a different business number is a separate conversation.
        self.assertFalse(SessionWindow.status_for(self.other_phone, self.customer)[0])

    def test_lookup_normalizes_customer_phone_formatting(self):
        SessionWindow.touch(self.phone, "7 999 123 45 67")

        for variant in ("+79991234567", "79991234567", "+7 (999) 123-45-67"):
            self.assertTrue(
                SessionWindow.status_for(self.phone, variant)[0],
                msg=f"lookup failed for {variant!r}",
            )

    def test_unknown_customer_is_closed(self):
        is_open, window = SessionWindow.status_for(self.phone, "+10000000000")

        self.assertFalse(is_open)
        self.assertIsNone(window)

    def test_touch_ignores_blank_customer_phone(self):
        self.assertIsNone(SessionWindow.touch(self.phone, ""))
        self.assertEqual(SessionWindow.objects.count(), 0)

    @override_settings(WABA_SESSION_WINDOW_HOURS=12)
    def test_window_duration_honours_setting(self):
        when = timezone.now() - timedelta(hours=13)
        SessionWindow.touch(self.phone, self.customer, when=when)

        self.assertFalse(SessionWindow.status_for(self.phone, self.customer)[0])


class WindowStatusActionTests(TestCase):
    """BE-05: the `window_status` placement action consumed by the agent widget."""

    def setUp(self):
        self.module = WabaPlacementModule()
        self.phone = Phone.objects.create(phone="+15550001111", phone_id="pnid-1")
        self.sender_phones = Phone.objects.all()
        self.customer = "+79991234567"

    def _call(self, **data):
        response = self.module._window_status_action(data, self.sender_phones)
        return response.status_code, json.loads(response.content)

    def test_open_window_reports_countdown(self):
        SessionWindow.touch(self.phone, self.customer)

        status_code, payload = self._call(
            sender_phone_id=str(self.phone.id), phone=self.customer
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["open"])
        self.assertEqual(payload["window_hours"], 24)
        self.assertGreater(payload["remaining_seconds"], 23 * 3600)
        self.assertIsNotNone(payload["expires_at"])
        self.assertIsNotNone(payload["last_inbound_at"])

    def test_expired_window_reports_closed(self):
        SessionWindow.touch(self.phone, self.customer, when=timezone.now() - timedelta(hours=25))

        _status_code, payload = self._call(
            sender_phone_id=str(self.phone.id), phone=self.customer
        )

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["open"])
        self.assertEqual(payload["remaining_seconds"], 0)

    def test_customer_never_seen_reports_closed_without_timestamps(self):
        _status_code, payload = self._call(
            sender_phone_id=str(self.phone.id), phone="+10000000000"
        )

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["open"])
        self.assertEqual(payload["remaining_seconds"], 0)
        self.assertIsNone(payload["expires_at"])
        self.assertIsNone(payload["last_inbound_at"])

    def test_accepts_unformatted_recipient_number(self):
        SessionWindow.touch(self.phone, self.customer)

        _status_code, payload = self._call(
            sender_phone_id=str(self.phone.id), phone="7 (999) 123-45-67"
        )

        self.assertTrue(payload["open"])

    def test_missing_sender_phone_is_rejected(self):
        _status_code, payload = self._call(sender_phone_id="", phone=self.customer)

        self.assertFalse(payload["ok"])
        self.assertIn("sender phone", payload["error"])

    def test_missing_recipient_phone_is_rejected(self):
        _status_code, payload = self._call(sender_phone_id=str(self.phone.id), phone="")

        self.assertFalse(payload["ok"])
        self.assertIn("recipient phone", payload["error"])
