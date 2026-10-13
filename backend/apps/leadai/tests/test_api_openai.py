"""The Lead AI's OpenAI client and its HTTP API.

- OpenAI time is bounded by the turn's deadline: each attempt waits at most
  until a second before it, there is no retry without time for a whole
  attempt, and no call at all with under five seconds left.
- What failed is told apart (transport, content, final, time), so a refusal
  or a cut-off answer fails one turn and never pauses the assistant.
- Settings: the office Maps link is parsed, not prefix-matched; test numbers
  are stored as WhatsApp ids (00 dropped, a local 0... refused); a NaN
  coordinate is a 400; only admins get the test numbers themselves.
- The chat list: a bad ?number= is a 400; the panel's thinking, note and
  handover_label fields; and its query count does not grow with the page.

OpenAI is a fake behind httpx.post, on a clock the test moves.
"""

import datetime as dt
import json
from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.inbox.models import Contact, Conversation, Label, Message
from apps.leadai.assistant import engine, openai_client
from apps.leadai.models import (
    LeadAiAlert,
    LeadAiAppointment,
    LeadAiChat,
    LeadAiChatState,
    LeadAiSettings,
    LeadAiTurn,
)
from apps.leadai.tests.test_assistant import NOW, TEST_SETTINGS, TUESDAY_5PM, Base, fake_send_text

# Base replaces these with fakes for every test; the real ones, for the tests
# that run the client against a fake OpenAI.
REAL_COMPLETE_JSON = openai_client.complete_json
REAL_TRANSCRIBE = openai_client.transcribe

MESSAGES = [{"role": "user", "content": "Do you have shops?"}]
SCHEMA = {"type": "object"}
TIMED_OUT = httpx.ReadTimeout("timed out")


class Clock:
    """openai_client's ``time``: monotonic() and sleep() on a clock the test moves."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeOpenAI:
    """Stands in for httpx.post. Each step is TIMED_OUT (the call waits its whole
    read timeout, then raises) or (seconds, response)."""

    def __init__(self, clock, *steps):
        self.clock = clock
        self.steps = list(steps)
        self.timeouts = []

    def __call__(self, url, **kwargs):
        timeout = kwargs["timeout"]
        self.timeouts.append(timeout)
        step = self.steps.pop(0)
        if step is TIMED_OUT:
            self.clock.now += timeout.read
            raise TIMED_OUT
        seconds, response = step
        self.clock.now += seconds
        return response


def completion(content='{"reply": "Sure."}', *, finish="stop", refusal=None):
    message = {"role": "assistant", "content": content, "refusal": refusal}
    return httpx.Response(
        200,
        json={
            "model": "gpt-4.1-mini",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def failure(status, code=""):
    return httpx.Response(status, json={"error": {"code": code or None, "type": code or "server_error"}})


@override_settings(**TEST_SETTINGS, LEADAI_OPENAI_TIMEOUT=25)
class DeadlineTests(SimpleTestCase):
    def call(self, clock, fake, deadline):
        with patch.object(openai_client, "time", clock), patch.object(openai_client.httpx, "post", fake):
            return REAL_COMPLETE_JSON(MESSAGES, SCHEMA, deadline=deadline)

    def test_an_attempt_waits_at_most_until_a_second_before_the_deadline(self):
        clock = Clock()
        fake = FakeOpenAI(clock, (3, completion()), (3, completion()))
        self.assertEqual(self.call(clock, fake, clock.now + 20).data, {"reply": "Sure."})
        self.assertEqual((fake.timeouts[0].read, fake.timeouts[0].connect), (19, 5))
        self.call(clock, fake, None)
        self.assertEqual(fake.timeouts[1].read, 25)

    def test_no_retry_without_time_for_a_whole_attempt(self):
        clock = Clock()
        # 45 s left: after a 25 s timeout, 20 s is not the pause plus 25 s more.
        fake = FakeOpenAI(clock, TIMED_OUT, (3, completion()))
        with self.assertRaises(openai_client.AssistantError) as caught:
            self.call(clock, fake, clock.now + 45)
        self.assertEqual((caught.exception.code, caught.exception.kind), ("unreachable", "transport"))
        self.assertEqual((len(fake.timeouts), clock.slept), (1, []))

        fake = FakeOpenAI(clock, (1, failure(503)), (3, completion()))
        with self.assertRaises(openai_client.AssistantError) as caught:
            self.call(clock, fake, clock.now + 27)
        self.assertEqual((caught.exception.code, caught.exception.kind), ("http_503", "transport"))
        self.assertEqual(len(fake.timeouts), 1)

    def test_a_retry_when_there_is_time(self):
        clock = Clock()
        fake = FakeOpenAI(clock, TIMED_OUT, (3, completion()))
        self.call(clock, fake, clock.now + 100)
        self.assertEqual((len(fake.timeouts), clock.slept), (2, [openai_client.RETRY_PAUSE]))

    def test_no_call_with_under_five_seconds_left(self):
        clock = Clock()
        fake = FakeOpenAI(clock)
        for deadline in (clock.now + 4.9, clock.now - 3):
            with self.assertRaises(openai_client.AssistantError) as caught:
                self.call(clock, fake, deadline)
            self.assertEqual((caught.exception.code, caught.exception.kind), ("no_time", "time"))
        with patch.object(openai_client, "time", clock), patch.object(openai_client.httpx, "post", fake):
            with self.assertRaises(openai_client.AssistantError) as caught:
                REAL_TRANSCRIBE(b"OggS voice", "audio/ogg; codecs=opus", deadline=clock.now + 3)
        self.assertEqual((caught.exception.code, caught.exception.kind), ("no_time", "time"))
        self.assertEqual(fake.timeouts, [], "OpenAI must not be called")

    def test_calls_sharing_a_turn_deadline_never_pass_it(self):
        """OpenAI never answers: a turn's calls (two model calls, a voice note...) all
        end a second before its deadline, however many there are."""
        clock = Clock()
        deadline = clock.now + 140
        fake = FakeOpenAI(clock, *[TIMED_OUT] * 20)
        codes = []
        for _ in range(6):
            with self.assertRaises(openai_client.AssistantError) as caught:
                self.call(clock, fake, deadline)
            codes.append(caught.exception.code)
            self.assertLessEqual(clock.now, deadline - 1)
        self.assertEqual(codes, ["unreachable"] * 4 + ["no_time"] * 2)

    def test_transcribe_returns_the_words_within_the_deadline(self):
        clock = Clock()
        fake = FakeOpenAI(clock, (2, httpx.Response(200, json={"text": " I need a shop "})))
        with patch.object(openai_client, "time", clock), patch.object(openai_client.httpx, "post", fake):
            text = REAL_TRANSCRIBE(b"OggS voice", "audio/ogg; codecs=opus", deadline=clock.now + 12)
        self.assertEqual(text, "I need a shop")
        self.assertEqual(fake.timeouts[0].read, 11)


@override_settings(**TEST_SETTINGS, LEADAI_OPENAI_TIMEOUT=25)
class ErrorKindTests(SimpleTestCase):
    def outcome(self, *steps):
        clock = Clock()
        fake = FakeOpenAI(clock, *steps)
        with patch.object(openai_client, "time", clock), patch.object(openai_client.httpx, "post", fake):
            with self.assertRaises(openai_client.AssistantError) as caught:
                REAL_COMPLETE_JSON(MESSAGES, SCHEMA, deadline=clock.now + 100)
        return caught.exception, len(fake.timeouts)

    def test_the_model_answering_badly_is_content(self):
        cases = {
            "refused": completion("", refusal="I'm sorry, I can't help with that."),
            "too_long": completion('{"language": "ur", "fa', finish="length"),
            "not JSON": completion("Sure! Here are the shops."),
            "not an object": completion("[1, 2]"),
        }
        for label, response in cases.items():
            with self.subTest(label):
                error, calls = self.outcome((1, response))
                self.assertEqual((error.kind, error.final, calls), ("content", False, 1))
                self.assertIn(error.code, ("refused", "too_long", "unreadable"))

    def test_the_way_to_openai_failing_is_transport(self):
        cases = {
            "timeouts": (TIMED_OUT, TIMED_OUT),
            "503": ((1, failure(503)), (1, failure(503))),
            "429": ((1, failure(429, "rate_limit_exceeded")), (1, failure(429, "rate_limit_exceeded"))),
            "a 200 with no completion in it": ((1, httpx.Response(200, json={"object": "error"})),),
        }
        for label, steps in cases.items():
            with self.subTest(label):
                error, calls = self.outcome(*steps)
                self.assertEqual((error.kind, error.final, calls), ("transport", False, len(steps)))

    def test_what_a_retry_cannot_fix_is_final(self):
        for status, code in ((400, "invalid_request_error"), (401, "invalid_api_key"), (403, ""), (404, "model_not_found"), (429, "insufficient_quota")):
            with self.subTest(status=status, code=code):
                error, calls = self.outcome((1, failure(status, code)), (1, completion()))
                self.assertEqual((error.kind, error.final, calls), ("final", True, 1))

    def test_a_kind_is_derived_for_older_callers(self):
        self.assertEqual(openai_client.AssistantError("http_503").kind, "transport")
        self.assertEqual(openai_client.AssistantError("not_configured", final=True).kind, "final")
        self.assertTrue(openai_client.AssistantError("not_configured", final=True).final)
        self.assertFalse(openai_client.AssistantError("refused", kind="content").final)
        self.assertEqual(openai_client.AssistantError("x", kind="nonsense").kind, "transport")


def openai_says(kind):
    """httpx.post as OpenAI answering with a refusal or with an answer cut off at the token limit."""

    def post(url, **kwargs):
        if kind == "refusal":
            return completion(None, refusal="I'm sorry, I can't help with that.")
        return completion('{"language": "ur", "segment": "other", "facts": {', finish="length")

    return post


class ContentFailureTests(Base):
    def test_refusals_and_cut_off_answers_pause_nobody(self):
        """Three turns in three chats in a row where OpenAI answered, just not
        usefully: each chat's agent is told, and the assistant is not paused."""
        for index, kind in enumerate(("refusal", "length", "refusal")):
            contact = Contact.objects.create(wa_id=f"97150555{index:04d}", display_name=f"Customer {index}")
            conversation = Conversation.objects.create(
                number=self.number, contact=contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=20)
            )
            LeadAiChat.objects.create(conversation=conversation, active=True)
            message = Message.objects.create(
                conversation=conversation,
                direction=Message.Direction.INBOUND,
                kind=Message.Kind.TEXT,
                body="Hello, I need a shop",
                status=Message.Status.RECEIVED,
                created_at=NOW - dt.timedelta(seconds=30),
            )
            with patch("apps.leadai.assistant.openai_client.complete_json", REAL_COMPLETE_JSON), patch.object(
                openai_client.httpx, "post", side_effect=openai_says(kind)
            ), patch("apps.inbox.services.send_text", side_effect=fake_send_text), self.captureOnCommitCallbacks(execute=True):
                outcome = engine.run_turn(message.pk, first_queued_at=(NOW - dt.timedelta(minutes=1)).isoformat())
            self.assertEqual(outcome.status, LeadAiTurn.Status.FAILED, outcome.reason)
            self.assertTrue(LeadAiAlert.objects.filter(kind="ai_error", conversation=conversation).exists())
        row = LeadAiSettings.load()
        self.assertEqual((row.paused_until, row.consecutive_failures), (None, 0))
        self.assertFalse(LeadAiAlert.objects.filter(kind="ai_down").exists())


class SettingsApiTests(Base):
    def put(self, body):
        return self.client.put("/api/leadai/settings/", body, content_type="application/json")

    def test_the_maps_link_must_really_be_google_maps(self):
        self.client.force_login(self.admin)
        good = "https://maps.app.goo.gl/abc123"
        self.assertEqual(self.put({"office_maps_url": good}).status_code, 200)
        refused = (
            "https://google.com.evil.example/x",
            "https://evil.example?.google.com",
            "https://evil.example#.google.com",
            "https://evil.example\\.google.com",
            "https://maps.app.goo.gl/abc https://evil.example/login",
            "https://maps.app.goo.gl/abc\nhttps://evil.example/login",
            "https://maps.app.goo.gl@evil.example/x",
            "https://maps.app.goo.gl:8443/abc",
            "http://maps.app.goo.gl/abc",
            "https://www.google.com/search?q=shops",
            "https://www.google.com/mapsevil",
            "https://sites.google.com/maps/x",
            "https://maps.app.goo.gl/" + "a" * 600,
        )
        for url in refused:
            with self.subTest(url=url[:60]):
                response = self.put({"office_maps_url": url})
                self.assertEqual(response.status_code, 400)
                self.assertIn("office_maps_url", response.json()["errors"])
        self.assertEqual(LeadAiSettings.load().office_maps_url, good)
        accepted = (
            "https://www.google.com/maps/place/Russia+Cluster/@25.1658,55.4089,17z",
            "https://maps.google.com/?q=25.1658,55.4089",
            "https://goo.gl/maps/xyz",
            "https://www.google.ae/maps/dir/",
            "https://google.com/maps",
        )
        for url in accepted:
            with self.subTest(url=url):
                self.assertEqual(self.put({"office_maps_url": url}).status_code, 200)
                self.assertEqual(LeadAiSettings.load().office_maps_url, url)

    def test_test_numbers_are_stored_as_whatsapp_ids(self):
        self.client.force_login(self.admin)
        LeadAiSettings.objects.filter(pk=1).update(assistant_enabled=False)
        response = self.put({"test_numbers": "00971501234567; +971 50 999 0000\n٠٠٩٧١٥٥٥٠٠٠١١١"})
        self.assertEqual(response.status_code, 200, response.content)
        row = LeadAiSettings.load()
        self.assertEqual(row.test_numbers, ["971501234567", "971509990000", "971555000111"])
        self.assertTrue(row.answers("971501234567"))
        for local in ("050 123 4567", "0501234567", "+0501234567"):
            with self.subTest(local):
                bad = self.put({"test_numbers": local})
                self.assertEqual(bad.status_code, 400)
                self.assertIn("country code", bad.json()["errors"]["test_numbers"])
        self.assertEqual(LeadAiSettings.load().test_numbers, ["971501234567", "971509990000", "971555000111"])

    def test_the_server_switch_stores_test_numbers_the_same_way(self):
        call_command("leadai_switch", "test-numbers", "00971501234567", stdout=StringIO())
        self.assertEqual(LeadAiSettings.load().test_numbers, ["971501234567"])
        with self.assertRaises(CommandError):
            call_command("leadai_switch", "test-numbers", "0501234567", stdout=StringIO())
        self.assertEqual(LeadAiSettings.load().test_numbers, ["971501234567"])

    def test_a_coordinate_that_is_not_a_number_is_a_400(self):
        self.client.force_login(self.admin)
        self.client.raise_request_exception = False
        for value in ("NaN", "sNaN", "-nan"):
            with self.subTest(value):
                response = self.put({"office_latitude": value, "office_longitude": "55.4"})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["errors"]["office_latitude"], "Latitude must be a number.")
        self.assertEqual(self.put({"office_latitude": "25.1", "office_longitude": "Infinity"}).status_code, 400)
        self.assertFalse(LeadAiSettings.load().has_pin)

    def test_only_admins_get_the_test_numbers_themselves(self):
        LeadAiSettings.objects.filter(pk=1).update(test_numbers=["971555000111"])
        self.client.force_login(self.agent)
        data = self.client.get("/api/leadai/settings/").json()
        self.assertNotIn("test_numbers", data)
        self.assertEqual(data["test_numbers_count"], 1)
        self.assertNotIn("971555000111", json.dumps(data))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/api/leadai/settings/").json()["test_numbers"], ["971555000111"])


class ChatListApiTests(Base):
    def ai(self):
        return self.client.get(f"/api/leadai/chats/{self.conversation.pk}/").json()["lead_ai_ai"]

    def listed_ai(self):
        return self.client.get("/api/leadai/chats/").json()["results"][0]["lead_ai_ai"]

    def test_a_number_filter_that_is_not_an_id_is_a_400(self):
        self.client.force_login(self.agent)
        self.client.raise_request_exception = False
        for value in ("abc", "1.5", "-1", "١"):
            with self.subTest(value):
                self.assertEqual(self.client.get("/api/leadai/chats/", {"number": value}).status_code, 400)
        self.assertEqual(self.client.get("/api/leadai/chats/", {"number": str(self.number.pk)}).json()["count"], 1)
        self.assertEqual(self.client.get("/api/leadai/chats/", {"number": "999999"}).json()["count"], 0)

    def test_thinking_is_a_turn_running_for_under_three_minutes(self):
        self.client.force_login(self.agent)
        self.assertFalse(self.ai()["thinking"])
        turn = LeadAiTurn.objects.create(conversation=self.conversation, created_at=NOW - dt.timedelta(minutes=1))
        self.assertTrue(self.ai()["thinking"])
        self.assertTrue(self.listed_ai()["thinking"])
        LeadAiTurn.objects.filter(pk=turn.pk).update(created_at=NOW - dt.timedelta(minutes=4))  # stuck, not thinking
        self.assertFalse(self.ai()["thinking"])
        LeadAiTurn.objects.filter(pk=turn.pk).update(created_at=NOW - dt.timedelta(minutes=1), status=LeadAiTurn.Status.REPLIED)
        self.assertFalse(self.listed_ai()["thinking"])

    def test_the_note_says_why_an_assistant_that_is_on_stays_silent(self):
        self.client.force_login(self.agent)
        self.assertEqual((self.ai()["mode"], self.ai()["note"]), ("on", ""))
        LeadAiSettings.objects.filter(pk=1).update(paused_until=NOW + dt.timedelta(minutes=5))
        self.assertEqual(self.ai()["note"], "Paused after OpenAI errors until 2:05 PM")
        self.assertEqual(self.listed_ai()["note"], "Paused after OpenAI errors until 2:05 PM")
        LeadAiSettings.objects.filter(pk=1).update(paused_until=None, daily_call_limit=3)
        LeadAiTurn.objects.create(
            conversation=self.conversation, status=LeadAiTurn.Status.REPLIED, calls=3, created_at=NOW - dt.timedelta(hours=1)
        )
        self.assertEqual(self.ai()["note"], "Daily limit reached")
        # A chat an agent paused says so by its mode; no note on top.
        LeadAiChatState.objects.create(conversation=self.conversation, paused_at=NOW, paused_by=self.agent)
        self.assertEqual((self.ai()["mode"], self.listed_ai()["note"]), ("paused", ""))

    @override_settings(LEADAI_OPENAI_API_KEY="")
    def test_the_note_names_a_missing_key(self):
        self.client.force_login(self.agent)
        ai = self.ai()
        self.assertEqual((ai["mode"], ai["note"]), ("off", "No Lead AI key"))

    def test_the_handover_label_is_the_reason_in_english(self):
        self.client.force_login(self.agent)
        self.assertEqual(self.ai()["handover_label"], "")
        LeadAiChatState.objects.create(conversation=self.conversation, handed_over_at=NOW, handover_reason="customer_asked_human")
        ai = self.ai()
        self.assertEqual((ai["mode"], ai["handover_label"]), ("handed_over", "asked to talk to a person"))
        self.assertEqual(ai["handover_label"], engine.HANDOVER_TEXT["customer_asked_human"])

    def test_the_list_costs_the_same_queries_for_one_chat_or_five(self):
        self.client.force_login(self.agent)
        LeadAiTurn.objects.create(conversation=self.conversation, created_at=NOW - dt.timedelta(minutes=1))
        self.client.get("/api/leadai/chats/")  # the session and the settings row
        with CaptureQueriesContext(connection) as one:
            first = self.client.get("/api/leadai/chats/").json()
        label = Label.objects.create(name="Hot")
        for index in range(4):
            contact = Contact.objects.create(wa_id=f"97150999{index:04d}", display_name=f"C{index}")
            conversation = Conversation.objects.create(
                number=self.number, contact=contact, assigned_agent=self.agent, session_expires_at=NOW + dt.timedelta(hours=3)
            )
            LeadAiChat.objects.create(conversation=conversation, active=True, added_by=self.agent)
            LeadAiChatState.objects.create(conversation=conversation, paused_at=NOW, paused_by=self.agent, facts={"budget": "50k"})
            LeadAiAppointment.objects.create(conversation=conversation, status="confirmed", starts_at=TUESDAY_5PM)
            LeadAiTurn.objects.create(conversation=conversation, created_at=NOW - dt.timedelta(minutes=1))
            conversation.labels.add(label)
        with CaptureQueriesContext(connection) as five:
            many = self.client.get("/api/leadai/chats/").json()
        self.assertEqual((first["count"], many["count"]), (1, 5))
        self.assertTrue(all(row["lead_ai_ai"]["thinking"] for row in many["results"]))
        self.assertEqual(len(one.captured_queries), len(five.captured_queries))
