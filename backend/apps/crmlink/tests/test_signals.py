"""A customer's message is mirrored to the CRM once it is committed, never inside its transaction.

Queued inside the webhook's transaction, the worker could pick the task up
before the row was visible, find no message and return in silence: none of
the customer messages of the first Lead AI chat reached the Bitrix timeline.
Our own messages are queued as before: a campaign posts its own copy of each
template it sends, so mirroring them after the commit would show it twice.
"""

from unittest.mock import patch

from django.db import transaction
from django.test import TestCase

from apps.catalog.models import WabaNumber
from apps.inbox.models import Contact, Conversation, Message

# Other apps queue their own work for every stored message; not under test here.
OTHER_TASKS = (
    "apps.leadbot.tasks.reply_to_inbound.apply_async",
    "apps.inboxai.tasks.reply_to_inbound.apply_async",
    "apps.inboxai.tasks.consider_health.apply_async",
    "apps.leadai.tasks.assistant_turn.apply_async",
    "apps.leadai.tasks.handle_reminder_tap.apply_async",
)


class MirrorOnCommitTests(TestCase):
    def setUp(self):
        for target in OTHER_TASKS:
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        number = WabaNumber.objects.create(phone_number="971500000001", phone_number_id="pn1", waba_business_id="waba1")
        contact = Contact.objects.create(wa_id="971501234567")
        self.conversation = Conversation.objects.create(number=number, contact=contact)

    def store(self, body="Yes I need a shop"):
        return Message.objects.create(
            conversation=self.conversation, direction=Message.Direction.INBOUND, kind=Message.Kind.TEXT, body=body
        )

    def test_queued_after_the_commit_not_inside_the_transaction(self):
        with patch("apps.crmlink.tasks.mirror_message.delay") as delay:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                with transaction.atomic():
                    message = self.store()
                    delay.assert_not_called()
                delay.assert_not_called()  # the test's own transaction has not committed yet
            self.assertTrue(callbacks)
            for callback in callbacks:  # the commit
                callback()
        delay.assert_called_once_with(message.pk)

    def test_our_own_messages_are_queued_as_before(self):
        # A campaign's template is stored inside the send's transaction and the
        # campaign posts its own copy to the timeline (campaigns.services,
        # renewals.post_deal_timeline): queued after the commit, the mirror
        # would add a second one to every lead it reaches.
        with patch("apps.crmlink.tasks.mirror_message.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    message = Message.objects.create(
                        conversation=self.conversation, direction=Message.Direction.OUTBOUND, kind=Message.Kind.TEMPLATE, body="Hi"
                    )
                    delay.assert_called_once_with(message.pk)
        delay.assert_called_once_with(message.pk)  # and not once more at the commit

    def test_once_per_message_never_on_its_status_updates(self):
        with patch("apps.crmlink.tasks.mirror_message.delay") as delay, self.captureOnCommitCallbacks(execute=True):
            message = self.store()
            message.status = Message.Status.READ
            message.save(update_fields=["status"])
        delay.assert_called_once_with(message.pk)

    def test_a_broker_failure_at_the_commit_is_logged_not_raised(self):
        with patch("apps.crmlink.tasks.mirror_message.delay", side_effect=OSError("broker down")), self.assertLogs(
            "apps.crmlink.signals", level="WARNING"
        ) as logs, self.captureOnCommitCallbacks(execute=True):
            message = self.store()
        self.assertTrue(Message.objects.filter(pk=message.pk).exists())
        self.assertIn(f"Could not queue the CRM mirror for message {message.pk}: broker down", logs.output[0])
