"""Two sends in flight in one chat: the Lead AI assistant and an agent (or two agents).

A status webhook can beat a send's own gateway answer, which is what
gateway.ingest._adopt_queued_outbound exists for. With two sends in flight
it used to hand the status's wamid to the NEWEST queued row; when the other
send's answer then came back, _record_result took that row for a webhook
stub and deleted it, and its own answer failed with a DatabaseError (a 500
to the agent, who re-sends: the customer gets the message twice).

Now no real message is ever deleted and each keeps its own wamid; a
placeholder the webhook made is still merged into the send it belongs to.
The gateway is faked; the send path, the status ingest and _record_result
are the real ones.
"""

import datetime as dt
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Agent
from apps.catalog.models import WabaNumber
from apps.gateway import ingest
from apps.gateway.parse import PLACEHOLDER_BODY
from apps.inbox import services
from apps.inbox.models import Contact, Conversation, Message

WA_ID = "971501234567"
OUR_NUMBER = "971500000001"
AI_REPLY = "Perfect, Ahmed. Your meeting is confirmed."
AGENT_REPLY = "I will call you in five minutes."

# Other apps queue Celery work for stored messages; with no broker each
# enqueue would wait on retries. Not under test.
QUIET = (
    "apps.crmlink.tasks.mirror_message.delay",
    "apps.leadbot.tasks.reply_to_inbound.apply_async",
    "apps.inboxai.tasks.reply_to_inbound.apply_async",
    "apps.inboxai.tasks.consider_health.apply_async",
    "apps.gateway.media.download_media.delay",
)


def status(wamid, state="sent"):
    return {"id": wamid, "status": state, "recipient_id": WA_ID, "timestamp": str(int(timezone.now().timestamp()))}


def accepted(wamid):
    """The gateway's answer to a send it accepted."""
    return {"messaging_product": "whatsapp", "contacts": [{"input": f"+{WA_ID}", "wa_id": WA_ID}], "messages": [{"id": wamid}]}


def gateway(wamid, while_in_flight):
    """AlotsClient whose send runs ``while_in_flight`` before it answers with ``wamid``."""

    class FakeAlots:
        def __init__(self, *args, **kwargs):
            pass

        def send_text(self, phone_number_id, to, body, preview_url=False, reply_to_wamid=None):
            while_in_flight()
            return accepted(wamid)

    return FakeAlots


class TwoSendersBase(TestCase):
    def setUp(self):
        for target in QUIET:
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.agent = Agent.objects.create_user(username="agent", password="x", can_official_api=True)
        self.number = WabaNumber.objects.create(phone_number=OUR_NUMBER, phone_number_id="pn1", waba_business_id="waba1")
        self.contact = Contact.objects.create(wa_id=WA_ID)
        self.conversation = Conversation.objects.create(
            number=self.number,
            contact=self.contact,
            assigned_agent=self.agent,
            session_expires_at=timezone.now() + dt.timedelta(hours=20),
        )

    def queued(self, body, *, agent=None, payload=None, **fields):
        """A send in flight: its row is written, the gateway has not answered yet."""
        fields.setdefault("status", Message.Status.QUEUED)
        return Message.objects.create(
            conversation=self.conversation,
            direction=Message.Direction.OUTBOUND,
            kind=Message.Kind.TEXT,
            body=body,
            sent_by=agent,
            payload=payload or {},
            **fields,
        )

    def ai_send(self, **fields):
        return self.queued(AI_REPLY, payload={"source": "leadai_ai", "turn": 1}, **fields)

    def agent_send(self, **fields):
        return self.queued(AGENT_REPLY, agent=self.agent, **fields)

    def outbound(self):
        return list(
            Message.objects.filter(conversation=self.conversation, direction=Message.Direction.OUTBOUND)
            .order_by("pk")
            .values_list("body", "wamid", "status")
        )


class TwoSendersTests(TwoSendersBase):
    def test_ai_reply_answered_while_an_agent_send_is_in_flight(self):
        """The assistant's reply goes out through the real send path; while it waits on
        the gateway the agent sends too, and the status of the reply's wamid arrives."""
        rows = {}

        def in_flight():
            rows["agent"] = self.agent_send()
            ingest.apply_status(self.number, status("wamid.A"))

        with patch("apps.inbox.services.AlotsClient", gateway("wamid.A", in_flight)):
            services.send_text(self.conversation, None, AI_REPLY, payload={"source": "leadai_ai"})
        services._record_result(rows["agent"], accepted("wamid.B"), intended_to=WA_ID)  # the agent's own answer

        self.assertEqual(self.outbound(), [(AI_REPLY, "wamid.A", "sent"), (AGENT_REPLY, "wamid.B", "sent")])

    def test_agent_reply_answered_while_an_ai_send_is_in_flight(self):
        rows = {}

        def in_flight():
            rows["ai"] = self.ai_send()
            ingest.apply_status(self.number, status("wamid.B"))

        with patch("apps.inbox.services.AlotsClient", gateway("wamid.B", in_flight)):
            services.send_text(self.conversation, self.agent, AGENT_REPLY)
        services._record_result(rows["ai"], accepted("wamid.A"), intended_to=WA_ID)  # the assistant's own answer

        self.assertEqual(self.outbound(), [(AGENT_REPLY, "wamid.B", "sent"), (AI_REPLY, "wamid.A", "sent")])

    def _wamid_on_the_wrong_send(self, first, second):
        """What a status adopted by the wrong row leaves: ``second`` holds ``first``'s
        wamid and its 'delivered'. Then both answers come back, ``first``'s first."""
        a, b = first(), second()
        Message.objects.filter(pk=b.pk).update(wamid="wamid.A", status=Message.Status.DELIVERED, delivered_at=timezone.now())
        services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        b.refresh_from_db()
        self.assertEqual((b.wamid, b.status, b.delivered_at), (None, Message.Status.QUEUED, None))
        services._record_result(b, accepted("wamid.B"), intended_to=WA_ID)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.wamid, a.status), ("wamid.A", Message.Status.SENT))
        self.assertEqual((b.wamid, b.status), ("wamid.B", Message.Status.SENT))
        self.assertEqual(len(self.outbound()), 2)

    def test_an_agent_send_holding_the_ai_wamid_is_kept(self):
        self._wamid_on_the_wrong_send(self.ai_send, self.agent_send)

    def test_an_ai_send_holding_the_agent_wamid_is_kept(self):
        self._wamid_on_the_wrong_send(self.agent_send, self.ai_send)

    def test_a_slow_send_whose_status_lands_on_a_newer_one(self):
        """The first send has waited longer than adoption looks back, so its status
        goes to the only recent send: still nobody loses a row or a wamid."""
        a = self.ai_send(created_at=timezone.now() - ingest.ADOPT_WITHIN - dt.timedelta(seconds=30))
        b = self.agent_send()
        ingest.apply_status(self.number, status("wamid.A", "delivered"))
        services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        services._record_result(b, accepted("wamid.B"), intended_to=WA_ID)
        self.assertEqual(self.outbound(), [(AI_REPLY, "wamid.A", "sent"), (AGENT_REPLY, "wamid.B", "sent")])

    def test_the_other_sends_own_answer_in_between_is_not_undone(self):
        """B's own answer lands after A found B holding A's wamid and before A takes
        it back: B's real wamid must not be wiped."""
        a, b = self.ai_send(), self.agent_send()
        Message.objects.filter(pk=b.pk).update(wamid="wamid.A", status=Message.Status.SENT)
        real = services._is_status_placeholder

        def b_answers_meanwhile(row):
            Message.objects.filter(pk=b.pk).update(wamid="wamid.B", status=Message.Status.SENT)
            return real(row)

        with patch("apps.inbox.services._is_status_placeholder", side_effect=b_answers_meanwhile):
            services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        self.assertEqual(self.outbound(), [(AI_REPLY, "wamid.A", "sent"), (AGENT_REPLY, "wamid.B", "sent")])

    def test_a_failure_already_recorded_on_the_other_send_stays(self):
        a, b = self.ai_send(), self.agent_send()
        Message.objects.filter(pk=b.pk).update(wamid="wamid.A", status=Message.Status.FAILED, error_detail="Gateway timeout")
        services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        b.refresh_from_db()
        self.assertEqual((b.wamid, b.status, b.error_detail), (None, Message.Status.FAILED, "Gateway timeout"))
        a.refresh_from_db()
        self.assertEqual((a.wamid, a.status), ("wamid.A", Message.Status.SENT))

    def test_the_status_placeholder_is_still_merged_into_its_send(self):
        a, b = self.ai_send(), self.agent_send()
        ingest.apply_status(self.number, status("wamid.A", "delivered"))
        placeholder = Message.objects.get(wamid="wamid.A")
        self.assertEqual((placeholder.body, placeholder.sent_by_id), (PLACEHOLDER_BODY, None))
        services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        self.assertFalse(Message.objects.filter(pk=placeholder.pk).exists())
        self.assertEqual(self.outbound(), [(AI_REPLY, "wamid.A", "sent"), (AGENT_REPLY, None, "queued")])

    def test_a_row_an_echo_made_or_filled_in_is_still_merged(self):
        a, b = self.ai_send(), self.agent_send()
        echo = {"from": OUR_NUMBER, "to": WA_ID, "type": "text", "timestamp": str(int(timezone.now().timestamp()))}
        # The status-only placeholder for A, then the echo of A's text fills it in.
        ingest.apply_status(self.number, status("wamid.A"))
        ingest.store_message(self.number, {**echo, "id": "wamid.A", "text": {"body": AI_REPLY}}, {}, {}, force_outbound=True)
        filled = Message.objects.get(wamid="wamid.A")
        self.assertEqual((filled.kind, filled.body, filled.sent_by_id), (Message.Kind.TEXT, AI_REPLY, None))
        # The echo of B arrives before B's answer and makes its own row.
        ingest.store_message(self.number, {**echo, "id": "wamid.B", "text": {"body": AGENT_REPLY}}, {}, {}, force_outbound=True)
        echoed = Message.objects.get(wamid="wamid.B")
        services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        services._record_result(b, accepted("wamid.B"), intended_to=WA_ID)
        self.assertFalse(Message.objects.filter(pk__in=[filled.pk, echoed.pk]).exists())
        self.assertEqual(self.outbound(), [(AI_REPLY, "wamid.A", "sent"), (AGENT_REPLY, "wamid.B", "sent")])


class AdoptQueuedOutboundTests(TwoSendersBase):
    def test_the_one_send_in_flight_still_takes_its_early_status(self):
        a = self.ai_send()
        ingest.apply_status(self.number, status("wamid.A"))
        a.refresh_from_db()
        self.assertEqual((a.wamid, a.status), ("wamid.A", Message.Status.SENT))
        services._record_result(a, accepted("wamid.A"), intended_to=WA_ID)
        self.assertEqual(self.outbound(), [(AI_REPLY, "wamid.A", "sent")])

    def test_with_two_sends_in_flight_neither_is_guessed(self):
        a, b = self.ai_send(), self.agent_send()
        ingest.apply_status(self.number, status("wamid.A"))
        self.assertEqual(
            self.outbound(),
            [(AI_REPLY, None, "queued"), (AGENT_REPLY, None, "queued"), (PLACEHOLDER_BODY, "wamid.A", "sent")],
        )

    def test_a_failed_send_is_never_given_a_status(self):
        """A failed send keeps an empty wamid for good: a later status (here from the
        WhatsApp Business app on the phone) must not mark it sent."""
        failed = self.agent_send(status=Message.Status.FAILED)
        ingest.apply_status(self.number, status("wamid.PHONE", "delivered"))
        failed.refresh_from_db()
        self.assertEqual((failed.wamid, failed.status), (None, Message.Status.FAILED))
        self.assertTrue(Message.objects.filter(wamid="wamid.PHONE", body=PLACEHOLDER_BODY).exists())
        # ... nor does it stop the one send in flight from taking its own status.
        a = self.ai_send()
        ingest.apply_status(self.number, status("wamid.A"))
        a.refresh_from_db()
        self.assertEqual(a.wamid, "wamid.A")

    def test_an_old_queued_row_is_not_adopted(self):
        stale = self.agent_send(created_at=timezone.now() - ingest.ADOPT_WITHIN - dt.timedelta(minutes=1))
        ingest.apply_status(self.number, status("wamid.PHONE"))
        stale.refresh_from_db()
        self.assertIsNone(stale.wamid)
