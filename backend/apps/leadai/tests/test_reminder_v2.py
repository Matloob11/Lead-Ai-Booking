"""Batch 2e (board T45): reminder v2 where it is approved on the chat's number, and its [Office Location] tap.

a7_leadai_meeting_reminder_v2 is v1 with a fourth quick reply, [Office Location]. Outside the customer's 24-hour window
the reminder is v2 wherever Meta approved it on the chat's number (its WABA), else v1; inside the window it is the
free-form message with three reply buttons (WhatsApp's most), which carries the address and the Maps link already.
A tap on [Office Location] is answered with the office's address and Maps link, in the customer's language, then the
pin; it changes nothing on the meeting, syncs nothing to Bitrix and alerts nobody.

The fakes and the clock are test_reminders_crm's (Monday 12 October 2026, 14:00 Dubai).
"""

import datetime as dt
from unittest.mock import patch

from apps.catalog.models import WaTemplate
from apps.inbox.models import Message
from apps.leadai.assistant import reminders, taps
from apps.leadai.management.commands import submit_leadai_reminder_v2_template as v2_command
from apps.leadai.models import LeadAiAlert, LeadAiAppointment, LeadAiChatState, LeadAiSettings, LeadAiTurn
from apps.leadai.tests.test_assistant import NOW, _outbound, fake_send_location, fake_send_template, fake_send_text
from apps.leadai.tests.test_reminders_crm import RcBase

MAPS = "https://maps.app.goo.gl/u7xzyea9pPLpRxBD8"


def template(name, status=WaTemplate.Status.APPROVED, waba="waba1", category="UTILITY"):
    return WaTemplate.objects.create(
        waba_business_id=waba, name=name, language="en", category=category, status=status,
        components=[{"type": "BODY", "text": "Hi {{1}}, a reminder of your meeting today at {{2}} at {{3}}. Please tap below to let us know."}],
    )


class TemplateChoiceTests(RcBase):
    def test_v2_where_it_is_approved_on_the_chats_number_else_v1(self):
        self.assertIsNone(reminders.approved_template(self.conversation))
        v1 = template(reminders.TEMPLATE_NAME)
        self.assertEqual(reminders.approved_template(self.conversation), v1)
        v2 = template(reminders.TEMPLATE_V2_NAME, status=WaTemplate.Status.PENDING)  # still at Meta: v1 goes
        self.assertEqual(reminders.approved_template(self.conversation), v1)
        template(reminders.TEMPLATE_V2_NAME, waba="other-waba")  # approved on another number's WABA only
        self.assertEqual(reminders.approved_template(self.conversation), v1)
        WaTemplate.objects.filter(pk=v2.pk).update(status=WaTemplate.Status.APPROVED)
        self.assertEqual(reminders.approved_template(self.conversation), v2)
        v1.delete()
        self.assertEqual(reminders.approved_template(self.conversation), v2)
        WaTemplate.objects.filter(pk=v2.pk).update(category="MARKETING")  # a reminder is a UTILITY template, as v1
        self.assertIsNone(reminders.approved_template(self.conversation))

    def test_a_call_is_reminded_with_v1_never_with_office_location(self):
        v1 = template(reminders.TEMPLATE_NAME)
        v2 = template(reminders.TEMPLATE_V2_NAME)
        self.assertEqual(reminders.approved_template(self.conversation), v2)
        self.assertEqual(reminders.approved_template(self.conversation, location_button=False), v1)
        call = self.booked(place=LeadAiAppointment.Place.CALL)
        self.assertFalse(reminders.to_the_office(call))
        self.assertTrue(reminders.to_the_office(LeadAiAppointment(place=LeadAiAppointment.Place.OFFICE)))
        self.conversation.session_expires_at = NOW - dt.timedelta(minutes=5)
        self.conversation.save(update_fields=["session_expires_at"])
        pk, at, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template) as send:
            self.assertEqual(reminders.send(pk, at, start), "template")
        self.assertEqual(send.call_args.args[2], v1)

    def test_outside_the_window_the_reminder_goes_as_v2_with_v1s_values(self):
        template(reminders.TEMPLATE_NAME)
        v2 = template(reminders.TEMPLATE_V2_NAME)
        appointment = self.booked()
        self.conversation.session_expires_at = NOW - dt.timedelta(minutes=5)
        self.conversation.save(update_fields=["session_expires_at"])
        pk, at, start = reminders.claim_one(NOW)
        with patch("apps.inbox.services.send_template", side_effect=fake_send_template) as send:
            route = reminders.send(pk, at, start)
        self.assertEqual(route, "template")
        sent_template, variables = send.call_args.args[2], send.call_args.args[3]
        self.assertEqual(sent_template, v2)
        self.assertEqual(variables, {"1": "Ahmed", "2": "2:29 PM", "3": LeadAiSettings.load().office_address})
        appointment.refresh_from_db()
        self.assertEqual(appointment.reminder_message.template_id, v2.pk)

    def test_the_command_submits_the_labels_the_assistant_reads(self):
        self.assertEqual(v2_command.V2_NAME, "a7_leadai_meeting_reminder_v2")
        self.assertEqual([label for _, label in v2_command.V2_BUTTONS], ["On My Way", "Running Late", "Need to Reschedule", "Office Location"])
        self.assertTrue(all(len(label) <= 20 for _, label in reminders.V2_BUTTONS))
        self.assertEqual(reminders.ACTION_BY_LABEL["office location"], reminders.LOCATION)
        # The free-form reminder keeps three reply buttons (WhatsApp's most).
        self.assertEqual(len(reminders.BUTTONS), 3)


class LocationTapTests(RcBase):
    def setUp(self):
        super().setUp()
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url=MAPS, office_latitude=25.169639, office_longitude=55.404667)
        self.v2 = template(reminders.TEMPLATE_V2_NAME)

    def reminder(self, appointment):
        row = _outbound(
            self.conversation, None, Message.Kind.TEMPLATE, "reminder", {"source": "leadai_reminder", "appointment": appointment.pk},
            template=self.v2,
        )
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(reminder_message=row, reminder_sent_at=NOW - dt.timedelta(minutes=2))
        return row

    def tap(self, reply_to, label="Office Location"):
        return self.inbound(label, kind=Message.Kind.BUTTON, payload={"button": {"text": label}}, reply_to=reply_to)

    def handle(self, message):
        with patch("apps.inbox.services.send_text", side_effect=fake_send_text) as text, patch(
            "apps.inbox.services.send_location", side_effect=fake_send_location
        ) as pin, self.captureOnCommitCallbacks(execute=True):
            result = taps.handle(message.pk)
        return result, text, pin

    def test_office_location_gets_the_address_the_maps_link_and_the_pin_and_changes_nothing(self):
        appointment = self.booked(customer_state="")
        message = self.tap(self.reminder(appointment))
        self.assertTrue(reminders.looks_like_tap(message))
        self.assertEqual(reminders.tap_on_reminder(message), (appointment, reminders.LOCATION))
        result, text, pin = self.handle(message)
        self.assertEqual(result, "tap: location")
        body = text.call_args.args[2]
        address = LeadAiSettings.load().office_address
        self.assertEqual(body, f"{address}\nOur office location: {MAPS}")
        pin.assert_called_once()
        self.assertEqual(pin.call_args.args[2:4], (25.169639, 55.404667))
        appointment.refresh_from_db()
        self.assertEqual(appointment.customer_state, "")  # nothing about the meeting changed
        self.assertEqual(appointment.history[-1]["event"], "tap")
        self.assertEqual(appointment.history[-1]["action"], "location")
        self.crm_delay.assert_not_called()  # nothing for Bitrix
        self.assertFalse(LeadAiAlert.objects.exists())  # nobody needs to act on it
        turn = LeadAiTurn.objects.get(inbound=message)
        self.assertEqual((turn.status, turn.actions), (LeadAiTurn.Status.REPLIED, {"tap": "location"}))
        self.assertEqual(Message.objects.get(pk=turn.reply_message_id).payload["source"], "leadai_tap")

    def test_in_the_customers_language_and_with_no_maps_link_the_address(self):
        appointment = self.booked()
        LeadAiChatState.objects.update_or_create(conversation=self.conversation, defaults={"language": "ar"})
        result, text, pin = self.handle(self.tap(self.reminder(appointment)))
        self.assertEqual(text.call_args.args[2], f"{LeadAiSettings.load().office_address}\nموقع مكتبنا: {MAPS}")
        LeadAiSettings.objects.filter(pk=1).update(office_maps_url="", office_latitude=None, office_longitude=None)
        LeadAiChatState.objects.filter(conversation=self.conversation).update(language="en")
        LeadAiAppointment.objects.filter(pk=appointment.pk).update(status="done")  # one open meeting per chat
        other = self.booked(starts_at=NOW + dt.timedelta(hours=2))
        result, text, pin = self.handle(self.tap(self.reminder(other)))
        self.assertEqual(text.call_args.args[2], f"Our office location: {LeadAiSettings.load().office_address}")
        pin.assert_not_called()

    def test_with_the_window_closed_or_the_assistant_off_nothing_is_sent(self):
        appointment = self.booked()
        self.conversation.session_expires_at = NOW
        self.conversation.save(update_fields=["session_expires_at"])
        result, text, pin = self.handle(self.tap(self.reminder(appointment)))
        self.assertEqual(result, "tap: location (no reply: assistant off or window closed)")
        text.assert_not_called()
        pin.assert_not_called()

    def test_a_tap_hours_after_the_meeting_is_the_assistants(self):
        appointment = self.booked(NOW - dt.timedelta(hours=3, minutes=5))
        message = self.tap(self.reminder(appointment))
        self.assertEqual(reminders.tap_on_reminder(message), (None, ""))
