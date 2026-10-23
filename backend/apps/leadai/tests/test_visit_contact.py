"""Whom a client on the way is told to call (Matloob 2026-10-23; round 24): the office contact waiting for them, and the
backup when he does not answer. Two settings pairs (LeadAiSettings.visit_contact), one line in the customer's language
after "Perfect. See you shortly." (filters.on_my_way), on a typed "on my way" for a confirmed visit, on a late arrival
at the booked time, on a walk-in with no meeting, and on the reminder's On My Way button (taps.reply_line); never for a
sales call. Nothing until both the name and the phone are set; the settings endpoint keeps them.

The fakes are test_assistant's: the clock is Monday 12 October 2026, 14:00 Dubai.
"""

from django.test import SimpleTestCase

from apps.accounts.models import Agent
from apps.leadai.assistant import engine, filters, taps
from apps.leadai.models import LeadAiAppointment, LeadAiSettings
from apps.leadai.tests.test_shops_playbook import ShopsBase, at, shop_answer

CONTACT = {"name": "Shoaib Malik", "phone": "971581058726", "backup_name": "Abdul Malik", "backup_phone": "971555484423"}
LINE = "If you need anything on the way, call Shoaib Malik on +971 58 105 8726. If Shoaib Malik does not answer, call Abdul Malik on +971 55 548 4423."


def set_contact(**fields):
    LeadAiSettings.load()
    LeadAiSettings.objects.filter(pk=1).update(
        visit_contact_name="Shoaib Malik", visit_contact_phone="971581058726",
        visit_contact_backup_name="Abdul Malik", visit_contact_backup_phone="971555484423", **fields,
    )


class LineTests(SimpleTestCase):
    def test_the_phone_label(self):
        self.assertEqual(filters.phone_label("971581058726"), "+971 58 105 8726")
        self.assertEqual(filters.phone_label("+971 55 548 4423"), "+971 55 548 4423")
        self.assertEqual(filters.phone_label("447700900123"), "+447700900123")
        self.assertEqual(filters.phone_label(""), "")

    def test_the_line_with_and_without_the_backup_and_with_nobody(self):
        self.assertEqual(filters.on_my_way("en"), "Perfect. See you shortly.")
        self.assertEqual(filters.on_my_way("en", None), "Perfect. See you shortly.")
        self.assertEqual(filters.on_my_way("en", CONTACT), f"Perfect. See you shortly.\n{LINE}")
        alone = {"name": "Shoaib Malik", "phone": "971581058726", "backup_name": "", "backup_phone": ""}
        self.assertEqual(filters.visit_contact("en", alone), "If you need anything on the way, call Shoaib Malik on +971 58 105 8726.")
        self.assertEqual(filters.visit_contact("en", {"name": "Shoaib Malik", "phone": ""}), "")
        self.assertEqual(filters.visit_contact("en", "Shoaib"), "")

    def test_every_language_has_a_whole_line(self):
        for language in ("en", "ar", "ur_latin", "ur", "hi_latin", "hi", "fr"):
            text = filters.on_my_way(language, CONTACT)
            self.assertIn("+971 58 105 8726", text, language)
            self.assertIn("+971 55 548 4423", text, language)
            self.assertNotIn("{", text, language)
            self.assertTrue(text.startswith(filters.ON_MY_WAY[language if language in filters.ON_MY_WAY else "en"]), language)

    def test_the_settings_row_gives_the_contact_only_when_whole(self):
        row = LeadAiSettings(visit_contact_name="Shoaib Malik", visit_contact_phone="+971 58 105 8726", visit_contact_backup_name="Abdul Malik", visit_contact_backup_phone="")
        self.assertEqual(row.visit_contact(), {"name": "Shoaib Malik", "phone": "971581058726", "backup_name": "", "backup_phone": ""})
        self.assertIsNone(LeadAiSettings(visit_contact_name="Shoaib Malik").visit_contact())
        self.assertIsNone(LeadAiSettings(visit_contact_phone="971581058726").visit_contact())
        self.assertIsNone(LeadAiSettings().visit_contact())

    def test_the_tap_line_and_the_sales_call(self):
        self.assertEqual(taps.reply_line("on_my_way", "en", contact=CONTACT), f"Perfect. See you shortly.\n{LINE}")
        self.assertEqual(taps.reply_line("on_my_way", "en"), "Perfect. See you shortly.")
        row = LeadAiSettings(**{f"visit_contact_{key}": value for key, value in CONTACT.items()})
        visit = LeadAiAppointment(status="confirmed", place="office", starts_at=at(12, 15))
        call = LeadAiAppointment(status="confirmed", place="call", starts_at=at(12, 15))
        self.assertEqual(engine.visit_contact_for(row, visit), CONTACT)
        self.assertEqual(engine.visit_contact_for(row, None), CONTACT)
        self.assertIsNone(engine.visit_contact_for(row, call))


class TurnTests(ShopsBase):
    def test_on_my_way_with_a_meeting_gets_the_contact_line(self):
        set_contact()
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=at(12, 15), customer_name="Ahmed Khan")
        outcome, calls, _, _ = self.turn(self.inbound("On my way, reaching in 15 minutes"), [shop_answer("", action="on_my_way", send=False)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.body(outcome), f"Perfect. See you shortly.\n{LINE}")
        self.assertEqual(LeadAiAppointment.objects.get().customer_state, LeadAiAppointment.CustomerState.ON_MY_WAY)

    def test_nothing_is_added_until_the_settings_name_someone(self):
        LeadAiAppointment.objects.create(conversation=self.conversation, status="confirmed", place="office", starts_at=at(12, 15), customer_name="Ahmed Khan")
        outcome, _, _, _ = self.turn(self.inbound("On my way, reaching in 15 minutes"), [shop_answer("", action="on_my_way", send=False)])
        self.assertEqual(self.body(outcome), "Perfect. See you shortly.")


class SettingsTests(ShopsBase):
    def setUp(self):
        super().setUp()
        self.admin = Agent.objects.create_user(username="adm", password="x", can_official_api=True, is_wa_admin=True, display_name="Admin")
        self.client.force_login(self.admin)

    def put(self, payload):
        return self.client.put("/api/leadai/settings/", payload, content_type="application/json")

    def test_the_four_are_kept_cleaned_and_shown(self):
        response = self.put({
            "visit_contact_name": "  Shoaib   Malik ", "visit_contact_phone": "+971 58 105 8726",
            "visit_contact_backup_name": "Abdul Malik", "visit_contact_backup_phone": "971555484423",
        })
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data["visit_contact_name"], data["visit_contact_phone"]), ("Shoaib Malik", "971581058726"))
        self.assertEqual((data["visit_contact_backup_name"], data["visit_contact_backup_phone"]), ("Abdul Malik", "971555484423"))
        row = LeadAiSettings.load()
        self.assertEqual(row.visit_contact(), CONTACT)
        self.assertIn("visit_contact_phone", row.history[-1]["changes"])
        self.assertEqual(self.client.get("/api/leadai/settings/").json()["visit_contact_name"], "Shoaib Malik")
        # Cleared one by one; the line goes with the phone.
        self.assertEqual(self.put({"visit_contact_backup_phone": ""}).status_code, 200)
        self.assertEqual(LeadAiSettings.load().visit_contact()["backup_name"], "")

    def test_a_bad_phone_or_a_marked_up_name_is_refused(self):
        self.assertIn("visit_contact_phone", self.put({"visit_contact_phone": "0501234"}).json()["errors"])
        self.assertIn("visit_contact_phone", self.put({"visit_contact_phone": "call me"}).json()["errors"])
        self.assertIn("visit_contact_backup_name", self.put({"visit_contact_backup_name": "<b>Malik</b>"}).json()["errors"])
        self.assertEqual(self.put({"visit_contact_phone": "(971) 58-105 8726"}).json()["visit_contact_phone"], "971581058726")
