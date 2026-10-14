# Run through `ops/wa.sh probe-leadai-turn`: three real Lead AI assistant turns on
# the LIVE code, database and Lead AI OpenAI key, inside ONE transaction that is
# ALWAYS rolled back. Nothing reaches WhatsApp, Bitrix or a browser, and nothing
# stays:
#   - the gateway sends (send_text, send_location, send_buttons, send_template)
#     are replaced by fakes that only store the row;
#   - the channel layer is replaced, so no live event reaches any browser;
#   - every Celery task (CRM sync, alerts, notes) is queued with on_commit,
#     which a rolled-back transaction never runs; the task objects are replaced
#     as well, and the probe checks none was called;
#   - the synthetic customer 999000000004 and everything made for it vanish
#     (checked at the end).
# The one thing that leaves: two or three OpenAI calls with this synthetic
# text, billed to the Lead AI key.
import datetime as dt
import json
from unittest import mock

from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Agent
from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import WabaNumber, WaTemplate
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai.assistant import engine, hours, openai_client
from apps.leadai.models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings, LeadAiTurn

HOST = "wa.srv1802669.hstgr.cloud"
CUSTOMER = "999000000004"
results = []


def check(name, ok, detail=""):
    results.append((bool(ok), name, detail))


class Rollback(Exception):
    pass


class FakeLayer:
    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append(message.get("event"))


def stored(conversation, agent, kind, body, payload):
    return Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=kind,
        body=body,
        sent_by=agent,
        status=Message.Status.SENT,
        payload=payload or {},
        created_at=timezone.now(),
    )


def fake_text(conversation, agent, body, reply_to=None, payload=None):
    return stored(conversation, agent, Message.Kind.TEXT, body, payload)


def fake_location(conversation, agent, latitude, longitude, name="", address="", payload=None):
    return stored(conversation, agent, Message.Kind.LOCATION, name, {**(payload or {}), "location": {"latitude": latitude}})


def fake_buttons(conversation, agent, body, buttons, header="", footer="", payload=None):
    return stored(conversation, agent, Message.Kind.INTERACTIVE, body, payload)


def fake_template(conversation, agent, template, variables=None, *args, payload=None, **kwargs):
    return stored(conversation, agent, Message.Kind.TEMPLATE, template.name, payload)


def say(conversation, text):
    return Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        kind=Message.Kind.TEXT,
        body=text,
        status=Message.Status.RECEIVED,
        created_at=timezone.now(),
        payload={"type": "text", "text": {"body": text}},
    )


def turn(message):
    queued = (timezone.now() - dt.timedelta(minutes=1)).isoformat()
    return engine.run_turn(message.pk, attempt=0, first_queued_at=queued)


def next_open_day(now, closed):
    day = now.astimezone(hours.DUBAI).date() + dt.timedelta(days=1)
    while day.weekday() == 6 or day.isoformat() in closed:
        day += dt.timedelta(days=1)
    return day


check("Lead AI key is set in this container", openai_client.configured())
layer = FakeLayer()
task_names = (
    "sync_appointment_crm",
    "deliver_alert",
    "record_crm_note",
    "resolve_responsible",
    "assistant_turn",
    "crm_readback",
)
patches = [
    mock.patch("apps.inbox.events.get_channel_layer", return_value=layer),
    mock.patch("apps.inbox.services.send_text", side_effect=fake_text),
    mock.patch("apps.inbox.services.send_location", side_effect=fake_location),
    mock.patch("apps.inbox.services.send_buttons", side_effect=fake_buttons),
    mock.patch("apps.inbox.services.send_template", side_effect=fake_template),
]
tasks = {name: mock.patch(f"apps.leadai.tasks.{name}") for name in task_names}
usage = {"calls": 0, "prompt": 0, "completion": 0}
try:
    with transaction.atomic():
        started = [p.start() for p in patches]
        task_mocks = {name: p.start() for name, p in tasks.items()}
        try:
            admin = Agent.objects.get(bitrix_user_id="2311", is_active=True)
            number = WabaNumber.objects.get(phone_number="971524077268")
            settings_row = LeadAiSettings.load()
            settings_row.test_numbers = list(settings_row.test_numbers or []) + [CUSTOMER]
            settings_row.save()
            print("assistant_enabled", settings_row.assistant_enabled, "| model", openai_client.chat_model())

            now = timezone.now()
            contact = Contact.objects.create(wa_id=CUSTOMER, display_name="ZZ Lead AI probe (rolled back)")
            conversation = Conversation.objects.create(
                number=number, contact=contact, assigned_agent=admin, session_expires_at=now + dt.timedelta(hours=20)
            )
            LeadAiChat.objects.create(conversation=conversation, active=True, crm_entity="lead", crm_id=900000001)
            template = (
                WaTemplate.objects.filter(waba_business_id=number.waba_business_id, status=WaTemplate.Status.APPROVED)
                .order_by("pk")
                .first()
            )
            Message.objects.create(
                conversation=conversation,
                direction=Message.Direction.OUTBOUND,
                kind=Message.Kind.TEMPLATE,
                template=template,
                body="Hi, shops are available for rent in International City, Dubai. Are you interested?",
                sent_by=admin,
                status=Message.Status.DELIVERED,
                created_at=now - dt.timedelta(hours=2),
            )
            # As live, the template came from a campaign, so the engine reads it as the campaign
            # and not as a colleague's message (transcript.campaign_template_ids). Without this
            # the exact-time upgrade (board T18) stood aside: "a colleague spoke last".
            campaign = Campaign.objects.create(
                name="ZZ Lead AI probe (rolled back)", number=number, template=template, created_by=admin,
                status=Campaign.Status.DONE,
            )
            CampaignRecipient.objects.create(
                campaign=campaign, phone=CUSTOMER, conversation=conversation, status=CampaignRecipient.Status.SENT,
            )

            # 1. An exact day and time: booked, confirmation written by code.
            day = next_open_day(now, settings_row.closed_dates or [])
            asked = f"Hi, I need a shop around 400 sq ft for a cafe, my trade licence is ready. Can I come on {hours.day_label(dt.datetime.combine(day, dt.time(12), tzinfo=hours.DUBAI))} at 5 pm?"
            outcome = turn(say(conversation, asked))
            reply = Message.objects.filter(pk=outcome.reply_message_id).first()
            print("turn 1:", outcome.status, outcome.reason, "|", (reply.body if reply else "").replace("\n", " / "))
            # What the model and the code decided, so a tentative left as it is can be traced (board T18).
            first = LeadAiTurn.objects.filter(conversation=conversation).order_by("pk").last()
            if first is not None:
                print("turn 1 actions:", json.dumps(first.actions, default=str, ensure_ascii=False)[:600])
            check("turn 1 replied", outcome.status == "replied", (outcome.status, outcome.reason))
            check("turn 1 reply tagged as the assistant, no sender", reply is not None and reply.payload.get("source") == "leadai_ai" and reply.sent_by_id is None)
            appointment = LeadAiAppointment.objects.filter(conversation=conversation).first()
            expected = dt.datetime.combine(day, dt.time(17), tzinfo=hours.DUBAI)
            check(
                "turn 1 booked the exact time",
                appointment is not None and appointment.status == "confirmed" and appointment.starts_at == expected,
                (appointment and appointment.status, appointment and appointment.starts_at, expected),
            )
            check("turn 1 confirmation names the booked day", reply is not None and hours.day_label(expected) in reply.body, reply.body if reply else "")
            check(
                "turn 1 reminder 30 minutes before",
                appointment is not None and appointment.reminder_due_at == expected - dt.timedelta(minutes=30),
                appointment and appointment.reminder_due_at,
            )
            state = LeadAiChatState.objects.get(conversation=conversation)
            check("turn 1 facts kept", (state.facts or {}).get("size_sqft") in (400, 400.0), state.facts)

            # 2. A new time: the same appointment moves.
            outcome = turn(say(conversation, "Sorry, can we make it 6 pm instead on the same day?"))
            reply = Message.objects.filter(pk=outcome.reply_message_id).first()
            print("turn 2:", outcome.status, outcome.reason, "|", (reply.body if reply else "").replace("\n", " / "))
            appointment = LeadAiAppointment.objects.filter(conversation=conversation, status__in=LeadAiAppointment.OPEN).first()
            check(
                "turn 2 rescheduled to 6 pm",
                appointment is not None and appointment.starts_at == expected.replace(hour=18),
                appointment and appointment.starts_at,
            )
            check("still one appointment", LeadAiAppointment.objects.filter(conversation=conversation).count() == 1)

            # 3. STOP: handled by rule, no model call, reminder dropped.
            calls_before = sum(LeadAiTurn.objects.filter(conversation=conversation).values_list("calls", flat=True))
            outcome = turn(say(conversation, "STOP"))
            state.refresh_from_db()
            appointment.refresh_from_db()
            print("turn 3:", outcome.status, outcome.reason)
            check("STOP stops the assistant", state.stop_reason == "stop_all" and state.stopped_at is not None, state.stop_reason)
            check("STOP drops the reminder", appointment.reminder_due_at is None)
            check(
                "STOP needed no model call",
                sum(LeadAiTurn.objects.filter(conversation=conversation).values_list("calls", flat=True)) == calls_before,
            )

            # The panel's view of it, as the admin.
            client = APIClient(HTTP_HOST=HOST)
            client.force_authenticate(user=admin)
            response = client.get(f"/api/leadai/chats/{conversation.pk}/", secure=True)
            row = response.json() if response.status_code == 200 else {}
            check("chat detail answers", response.status_code == 200, response.status_code)
            check("chat detail says stopped", (row.get("lead_ai_ai") or {}).get("mode") == "stopped", row.get("lead_ai_ai"))
            check("chat detail shows the meeting", (row.get("lead_ai_appointment") or {}).get("status") == "confirmed", row.get("lead_ai_appointment"))
            response = client.get(f"/api/inbox/conversations/{conversation.pk}/messages/", {"limit": 20}, secure=True)
            sources = [m.get("source") for m in (response.json().get("results") or [])] if response.status_code == 200 else []
            check("message list carries the assistant's source", "leadai_ai" in sources, (response.status_code, sources))

            for row in LeadAiTurn.objects.filter(conversation=conversation):
                usage["calls"] += row.calls
                usage["prompt"] += row.prompt_tokens
                usage["completion"] += row.completion_tokens
            check("no task ran or was queued", not any(m.called for m in task_mocks.values()), {n: m.call_count for n, m in task_mocks.items()})
            check("events stayed in the fake layer", "leadai.ai.state" in layer.sent or "ai.state" in layer.sent, layer.sent[:6])
        finally:
            for p in list(tasks.values()) + patches:
                p.stop()
        raise Rollback
except Rollback:
    pass

kept_numbers = LeadAiSettings.objects.filter(pk=1).values_list("test_numbers", flat=True).first() or []
left = {
    "contacts": Contact.objects.filter(wa_id=CUSTOMER).count(),
    "chats": LeadAiChat.objects.filter(conversation__contact__wa_id=CUSTOMER).count(),
    "test_number_kept": CUSTOMER in kept_numbers,
}
check("rolled back: nothing of the probe stayed", left == {"contacts": 0, "chats": 0, "test_number_kept": False}, left)

for ok, name, detail in results:
    print("PASS" if ok else "FAIL", "|", name, "" if ok else f"| {detail}")
print("openai usage:", usage)
print("passed", sum(1 for ok, _, _ in results if ok), "of", len(results))
print("PROBE_OK")
