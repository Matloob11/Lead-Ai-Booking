"""Board T57 and the Bitrix REST throttle of 2026-10-14: the CRM mirror stops losing messages.

- client.call tells a passing failure (BitrixTransient: 429, 5xx, a body that is not JSON, a
  timeout, a network error) from a refusal, says whether the request may have run there anyway
  (maybe_applied), names the HTTP status, and never quotes the body or the webhook token;
- every call waits for a slot under a limit shared through Redis, gives up as a BitrixTransient
  past the wait, and goes on unlimited when Redis is out. Background work (the mirror and its
  summaries) never waits: a slot free now or none, leaving a reserve to everybody else, a
  shorter timeout, no call at all for a minute after Bitrix timed out, two tasks at most;
- find_records(strict=True) raises instead of reading a passing failure as "no record", and a
  complete lookup is cached per number for about ten minutes, never past a record made here;
- mirror_message and refresh_summary try a passing failure again with a growing wait, post
  only what is still missing, look for a post whose answer was lost before sending it again,
  and never mirror a campaign's own template;
- a Lead AI chat mirrors to its own lead (no phone search for the person), the lead of the
  newest Lead AI campaign that reached it, plus Owner Data;
- crmlink_backfill_mirrors picks what never reached its record and queues it, spaced, and
  never while a campaign is sending;
- the panel's CRM lookups say "busy" rather than "not in the CRM".

Redis and Bitrix are faked; nothing leaves the machine. The fake Redis runs the limiter's GCRA
in Python, step for step the Lua in redis_state.GCRA.
"""

import datetime as dt
import io
from unittest.mock import patch

import httpx
import redis as redis_lib
from celery.exceptions import Retry
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Agent
from apps.campaigns.models import Campaign, CampaignRecipient
from apps.catalog.models import WabaNumber, WaTemplate
from apps.crmlink import client, redis_state, tasks
from apps.crmlink.management.commands import crmlink_backfill_mirrors as backfill
from apps.crmlink.models import Mirror
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai import lane
from apps.leadai.assistant import crm_fields
from apps.leadai.models import LeadAiChat

TOKEN = "s3cr3tt0ken"
WEBHOOK = f"https://bitrix.test/rest/1/{TOKEN}/"
OWNER_DATA = f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}"
WA_ID = "971501234567"
TOO_MANY = "crm.item.list: HTTP 429, the portal answered with something that is not JSON"

# Other apps queue their own work for every stored message; not under test here.
OTHER_TASKS = (
    "apps.crmlink.tasks.mirror_message.delay",
    "apps.leadbot.tasks.reply_to_inbound.apply_async",
    "apps.inboxai.tasks.reply_to_inbound.apply_async",
    "apps.inboxai.tasks.consider_health.apply_async",
    "apps.leadai.tasks.assistant_turn.apply_async",
    "apps.leadai.tasks.handle_reminder_tap.apply_async",
)

# The kwargs a mirror's first try runs with.
FIRST_TRY = {"summary_check": True, "check": None, "look_first": False, "deferred": 0}


def passing(text=TOO_MANY):
    """A passing failure that provably never ran there (the throttle's 429)."""
    return client.BitrixTransient(text)


def lost(text="crm.timeline.comment.add: timed out (ReadTimeout)"):
    """A passing failure after the request was sent: it may have run there."""
    return client.BitrixTransient(text, maybe_applied=True)


class Landed:
    """In FakeBitrix's ``fail``: the comment is stored, then ``error`` is raised (its answer lost)."""

    def __init__(self, error):
        self.error = error


NO_ID = object()  # in FakeBitrix's ``fail``: the comment answers with no result, and is not stored
THIS_CHAT = object()  # MirrorBase.sent: the test's own conversation


# Fakes
# ---------------------------------------------------------------------------


class FakeLock:
    def __init__(self, fake, name, timeout):
        self.fake, self.name, self.timeout = fake, name, timeout

    def acquire(self, blocking=True):
        self.fake.check()
        if self.name in self.fake.locks:
            return False
        self.fake.locks.add(self.name)
        self.fake.lock_timeouts.append(self.timeout)
        return True

    def release(self):
        self.fake.locks.discard(self.name)


class FakePipeline:
    def __init__(self, fake):
        self.fake, self.ops = fake, []

    def incr(self, key):
        self.ops.append((self.fake.incr, (key,)))
        return self

    def expire(self, key, seconds):
        self.ops.append((self.fake.expire, (key, seconds)))
        return self

    def delete(self, *keys):
        self.ops.append((self.fake.delete, keys))
        return self

    def execute(self):
        self.fake.check()
        return [op(*args) for op, args in self.ops]


class FakeRedis:
    """The Redis calls redis_state makes, in memory."""

    def __init__(self):
        self.values, self.expiry, self.ex, self.px = {}, {}, {}, {}
        self.locks, self.lock_timeouts, self.deleted = set(), [], []
        self.script_calls = 0
        self.fail = None  # an exception every call raises

    def check(self):
        if self.fail is not None:
            raise self.fail

    def register_script(self, source):
        assert source == redis_state.GCRA
        return self.gcra

    def gcra(self, keys=(), args=(), client=None):
        """redis_state.GCRA in Python (ms in, ms or -1 out)."""
        self.check()
        self.script_calls += 1
        key = keys[0]
        now, interval, burst, max_wait = (int(value) for value in args)
        if key in self.values and self.expiry.get(key, float("inf")) <= now:
            del self.values[key]
        tat = max(int(self.values.get(key, now)), now)
        wait = max(0, tat - now - (burst - 1) * interval)
        if wait > max_wait:
            return -1
        tat += interval
        self.values[key] = str(tat)
        self.expiry[key] = now + (tat - now + interval)
        return wait

    def get(self, key):
        self.check()
        value = self.values.get(key)
        return value.encode() if isinstance(value, str) else value

    def mget(self, keys):
        self.check()
        return [self.get(key) for key in keys]

    def set(self, key, value, ex=None, px=None, **kwargs):
        self.check()
        self.values[key], self.ex[key], self.px[key] = value, ex, px
        return True

    def exists(self, key):
        self.check()
        return int(key in self.values)

    def incr(self, key):
        self.check()
        self.values[key] = str(int(self.values.get(key, 0)) + 1)
        return int(self.values[key])

    def expire(self, key, seconds):
        self.check()
        self.ex[key] = seconds
        return True

    def delete(self, *keys):
        self.check()
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def lock(self, name, timeout=None, blocking=False, **kwargs):
        return FakeLock(self, name, timeout)


class FakeRedisMixin:
    """Every test gets a fresh FakeRedis behind redis_state, and clocks it controls."""

    def use_redis(self):
        self.redis = FakeRedis()
        self.reset_redis_state()
        self.addCleanup(self.reset_redis_state)
        self.now_ms = 1_760_440_000_000
        self.clock = 1000.0
        for target, kwargs in (
            ((redis_state.redis.Redis, "from_url"), {"return_value": self.redis}),
            ((redis_state, "_now_ms"), {"side_effect": lambda: self.now_ms}),
            ((redis_state, "_clock"), {"side_effect": lambda: self.clock}),
        ):
            patcher = patch.object(*target, **kwargs)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if target[1] == "from_url":
                self.from_url = mock
        return self.redis

    @staticmethod
    def reset_redis_state():
        redis_state._state.update(pid=None, redis=None, slot=None, quiet_until=0.0, warned_at=None)


class FakeBitrix:
    """client.call for the lookups and the timeline: answers by method and records every call.

    ``fail`` maps a method, or (method, entity type), to what happens in turn: an exception to
    raise, None (answer normally that time), Landed(exc) (the comment is stored, then exc) or
    NO_ID (a comment answered with no result).
    """

    def __init__(self, *, leads=(101,), contacts=(), phones=None, owner_data=(7,), fail=None):
        self.leads, self.contacts, self.owner_data = list(leads), list(contacts), list(owner_data)
        self.phones = phones or {}
        self.fail = {key: list(value) for key, value in (fail or {}).items()}
        self.calls, self.comments, self.comment_ids = [], [], []
        self.next_comment = 9000

    def _pop(self, *keys):
        for key in keys:
            queue = self.fail.get(key)
            if queue:
                return queue.pop(0)
        return None

    def _maybe_fail(self, *keys):
        exc = self._pop(*keys)
        if exc is not None:
            raise exc

    def store(self, entity, pk, text):
        self.next_comment += 1
        self.comments.append((entity, pk, text))
        self.comment_ids.append(self.next_comment)
        return self.next_comment

    def __call__(self, method, payload=None):
        payload = payload or {}
        self.calls.append((method, payload))
        if method == "crm.duplicate.findbycomm":
            entity = payload["entity_type"]
            self._maybe_fail((method, entity), method)
            found = self.leads if entity == "LEAD" else self.contacts
            return {entity: list(found)} if found else []
        if method in ("crm.lead.get", "crm.contact.get"):
            self._maybe_fail(method)
            return {"ID": str(payload["id"]), "PHONE": [{"VALUE": "x"}] * self.phones.get(payload["id"], 1)}
        if method == "crm.item.list":
            self._maybe_fail(method)
            return {"items": [{"id": pk} for pk in self.owner_data]}
        if method == "crm.timeline.comment.add":
            fields = payload["fields"]
            what = self._pop((method, fields["ENTITY_TYPE"]), method)
            if isinstance(what, Landed):
                self.store(fields["ENTITY_TYPE"], fields["ENTITY_ID"], fields["COMMENT"])
                raise what.error
            if what is NO_ID:
                return None
            if what is not None:
                raise what
            return self.store(fields["ENTITY_TYPE"], fields["ENTITY_ID"], fields["COMMENT"])
        if method == "crm.timeline.comment.list":
            self._maybe_fail(method)
            wanted = (payload["filter"]["ENTITY_TYPE"], payload["filter"]["ENTITY_ID"])
            rows = [
                {"ID": str(pk), "COMMENT": text}
                for (entity, record, text), pk in zip(self.comments, self.comment_ids)
                if (entity, record) == wanted
            ]
            return list(reversed(rows))[:50]  # newest first, one page
        if method.endswith(".update") or method in ("crm.lead.add", "crm.item.add"):
            self._maybe_fail(method)
            if method == "crm.lead.add":
                return 555
            if method == "crm.item.add":
                return {"item": {"id": 77}}
            return True
        raise AssertionError(f"unexpected Bitrix method {method}")

    def methods(self):
        return [method for method, _ in self.calls]

    def posted_on(self):
        return [(entity, pk) for entity, pk, _ in self.comments]


def answer(status, *, json=None, text=None):
    if json is not None:
        return httpx.Response(status, json=json)
    return httpx.Response(status, text=text or "")


# 1. Passing failures and refusals
# ---------------------------------------------------------------------------


@override_settings(BITRIX_WEBHOOK_URL=WEBHOOK)
class TransientTests(SimpleTestCase):
    def setUp(self):
        for name, kwargs in (("bitrix_slot", {"return_value": 0.0}), ("mark_bitrix_down", {})):
            patcher = patch.object(redis_state, name, **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def call(self, response=None, error=None, method="crm.item.list"):
        with patch.object(client.httpx, "post", return_value=response, side_effect=error) as post:
            try:
                return client.call(method, {"filter": {"x": 1}})
            finally:
                self.posted = post

    def caught(self, response=None, error=None, method="crm.item.list", kind=client.BitrixTransient):
        with self.assertRaises(client.BitrixError) as caught:
            self.call(response, error, method)
        self.assertIs(type(caught.exception), kind)
        self.assertNotIn(TOKEN, str(caught.exception))
        return caught.exception

    def raises(self, response=None, error=None, method="crm.item.list", kind=client.BitrixTransient):
        return str(self.caught(response, error, method, kind))

    def test_a_429_page_is_passing_names_the_status_and_quotes_nothing_of_it(self):
        page = f"<html><body><h1>429 Too Many Requests</h1>nginx {TOKEN}</body></html>"
        text = self.raises(answer(429, text=page))
        self.assertEqual(text, TOO_MANY)
        self.assertNotIn("html", text.lower())
        self.assertNotIn("nginx", text)

    def test_every_5xx_is_passing_with_its_status(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                text = self.raises(answer(status, text="<html>Bad Gateway</html>"))
                self.assertEqual(text, f"crm.item.list: HTTP {status}, the portal answered with something that is not JSON")

    def test_bitrix_own_throttle_is_a_503_with_json_and_passing(self):
        text = self.raises(answer(503, json={"error": "QUERY_LIMIT_EXCEEDED", "error_description": "Too many requests"}))
        self.assertEqual(text, "crm.item.list: HTTP 503, Too many requests")
        text = self.raises(answer(500, json={"error": "INTERNAL_SERVER_ERROR"}))
        self.assertEqual(text, "crm.item.list: HTTP 500, INTERNAL_SERVER_ERROR")
        text = self.raises(answer(429, json={"error": "QUERY_LIMIT_EXCEEDED"}))
        self.assertEqual(text, "crm.item.list: HTTP 429, QUERY_LIMIT_EXCEEDED")
        self.assertEqual(self.raises(answer(502, json={"result": True})), "crm.item.list: HTTP 502")

    def test_a_body_that_is_not_json_is_passing_whatever_the_status(self):
        text = self.raises(answer(200, text="<html>maintenance</html>"))
        self.assertEqual(text, "crm.item.list: HTTP 200, the portal answered with something that is not JSON")

    def test_timeouts_and_network_errors_are_passing_without_the_token(self):
        request = httpx.Request("POST", WEBHOOK + "crm.lead.get")
        for error, name in (
            (httpx.ReadTimeout("timed out", request=request), "ReadTimeout"),
            (httpx.ConnectTimeout("", request=request), "ConnectTimeout"),
            (httpx.ConnectError(f"cannot reach {WEBHOOK}crm.lead.get", request=request), "ConnectError"),
            (httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request), "RemoteProtocolError"),
        ):
            with self.subTest(name=name):
                text = self.raises(error=error, method="crm.lead.get")
                self.assertTrue(text.startswith("crm.lead.get: "), text)
                self.assertTrue(text.endswith(f"({name})"), text)
        self.assertIn("***", self.raises(error=httpx.ConnectError(f"cannot reach {WEBHOOK}", request=request)))
        self.assertIn("no answer", self.raises(error=httpx.ConnectTimeout("", request=request)))

    def test_what_may_have_run_there_and_what_provably_did_not(self):
        # A write that failed the second way must not simply be sent again (board T57 review F2).
        request = httpx.Request("POST", WEBHOOK)
        never_ran = {
            "nginx 429 page": self.caught(answer(429, text="<html>")),
            "429 with JSON": self.caught(answer(429, json={"error": "QUERY_LIMIT_EXCEEDED"})),
            "QUERY_LIMIT_EXCEEDED": self.caught(answer(503, json={"error": "QUERY_LIMIT_EXCEEDED", "error_description": "Too many requests"})),
            "ConnectError": self.caught(error=httpx.ConnectError("[Errno 111] Connection refused", request=request)),
            "ConnectTimeout": self.caught(error=httpx.ConnectTimeout("", request=request)),
            "PoolTimeout": self.caught(error=httpx.PoolTimeout("", request=request)),
        }
        may_have_run = {
            "ReadTimeout": self.caught(error=httpx.ReadTimeout("timed out", request=request)),
            "WriteTimeout": self.caught(error=httpx.WriteTimeout("", request=request)),
            "ReadError": self.caught(error=httpx.ReadError("reset by peer", request=request)),
            "RemoteProtocolError": self.caught(error=httpx.RemoteProtocolError("Server disconnected", request=request)),
            "500 JSON": self.caught(answer(500, json={"error": "INTERNAL_SERVER_ERROR"})),
            "502 page": self.caught(answer(502, text="<html>Bad Gateway</html>")),
            "503 page": self.caught(answer(503, text="<html>")),
            "504 page": self.caught(answer(504, text="<html>")),
            "200 not JSON": self.caught(answer(200, text="<html>maintenance</html>")),
        }
        for name, exc in never_ran.items():
            with self.subTest(name=name):
                self.assertFalse(exc.maybe_applied)
        for name, exc in may_have_run.items():
            with self.subTest(name=name):
                self.assertTrue(exc.maybe_applied)
        self.assertFalse(passing().maybe_applied)  # the default: the local limit, Bitrix down

    def test_a_slow_or_unreachable_bitrix_is_marked_down_for_background_work(self):
        request = httpx.Request("POST", WEBHOOK)
        for case in (
            {"error": httpx.ReadTimeout("timed out", request=request)},
            {"error": httpx.ConnectError("refused", request=request)},
            {"error": httpx.ConnectTimeout("", request=request)},
            {"error": httpx.RemoteProtocolError("Server disconnected", request=request)},
            {"response": answer(502, text="<html>")},
            {"response": answer(503, json={"error": "QUERY_LIMIT_EXCEEDED"})},
            {"response": answer(504, text="<html>")},
        ):
            with self.subTest(case=case):
                self.mark_bitrix_down.reset_mock()
                self.caught(**case)
                self.mark_bitrix_down.assert_called_once_with()
        for case, kind in (
            ({"response": answer(429, text="<html>")}, client.BitrixTransient),
            ({"response": answer(500, json={"error": "INTERNAL_SERVER_ERROR"})}, client.BitrixTransient),
            ({"response": answer(200, text="<html>")}, client.BitrixTransient),
            ({"response": answer(400, json={"error": "ERROR_CORE"})}, client.BitrixError),
        ):
            with self.subTest(case=case):
                self.mark_bitrix_down.reset_mock()
                self.caught(**case, kind=kind)
                self.mark_bitrix_down.assert_not_called()
        self.call(answer(200, json={"result": 1}))
        self.mark_bitrix_down.assert_not_called()

    def test_a_refusal_stays_a_plain_bitrix_error_worded_as_before(self):
        text = self.raises(answer(401, json={"error": "expired_token", "error_description": "The access token provided has expired."}), method="crm.lead.get", kind=client.BitrixError)
        self.assertEqual(text, "crm.lead.get: The access token provided has expired.")
        text = self.raises(answer(400, json={"error": "ERROR_CORE"}), kind=client.BitrixError)
        self.assertEqual(text, "crm.item.list: ERROR_CORE")
        bad_scheme = httpx.UnsupportedProtocol("Request URL has an unsupported protocol 'ftp://'.")
        self.raises(error=bad_scheme, kind=client.BitrixError)

    def test_an_answer_is_returned_as_before(self):
        self.assertEqual(self.call(answer(200, json={"result": {"ID": "5"}})), {"ID": "5"})
        self.assertEqual(self.call(answer(200, json={"result": []})), [])
        # Bitrix's "Not found" carries an empty error code, which never read as an error.
        self.assertIsNone(self.call(answer(400, json={"error": "", "error_description": "Not found"})))
        self.assertEqual(self.posted.call_args.kwargs["timeout"], 20)

    def test_no_webhook_is_a_refusal_and_nothing_is_asked(self):
        with override_settings(BITRIX_WEBHOOK_URL=""), patch.object(client.httpx, "post") as post:
            with self.assertRaises(client.BitrixError) as caught:
                client.call("crm.lead.get")
        self.assertIs(type(caught.exception), client.BitrixError)
        post.assert_not_called()

    def test_every_except_bitrix_error_still_catches_a_passing_failure(self):
        self.assertTrue(issubclass(client.BitrixTransient, client.BitrixError))
        try:
            raise passing()
        except client.BitrixError as exc:
            self.assertIsInstance(exc, client.BitrixTransient)

    def test_lead_ai_still_reads_each_passing_failure_as_one_to_retry(self):
        # apps.leadai.tasks._transient matches on words of the text; it must keep seeing them.
        from apps.leadai.tasks import _transient

        request = httpx.Request("POST", WEBHOOK)
        texts = [
            self.raises(answer(429, text="<html>")),
            self.raises(answer(502, text="<html>")),
            self.raises(answer(500, text="<html>")),
            self.raises(answer(503, json={"error": "QUERY_LIMIT_EXCEEDED", "error_description": "Too many requests"})),
            self.raises(error=httpx.ReadTimeout("timed out", request=request)),
            self.raises(error=httpx.ConnectTimeout("", request=request)),
            self.raises(error=httpx.ConnectError("[Errno 111] Connection refused", request=request)),
        ]
        with patch.object(redis_state, "bitrix_slot", return_value=None):
            texts.append(self.raises(answer(200, json={"result": 1})))
            with client.background():
                texts.append(self.raises(answer(200, json={"result": 1})))
        with client.background(), patch.object(redis_state, "bitrix_down", return_value=True):
            texts.append(self.raises(answer(200, json={"result": 1})))
        for text in texts:
            with self.subTest(text=text):
                self.assertTrue(_transient(client.BitrixTransient(text)), text)

    def test_a_comment_id_is_a_positive_whole_number(self):
        for value, expected in ((9001, 9001), ("9001", 9001), (" 12 ", 12), (None, None), (True, None), (0, None), ("", None), ({"id": 1}, None), (-3, None)):
            with self.subTest(value=value):
                self.assertEqual(client.comment_id(value), expected)


# 2. The shared rate limit
# ---------------------------------------------------------------------------


@override_settings(BITRIX_WEBHOOK_URL=WEBHOOK, BITRIX_REST_RATE=2.0, BITRIX_REST_BURST=3, BITRIX_REST_MAX_WAIT=1.2)
class LimiterTests(FakeRedisMixin, SimpleTestCase):
    def setUp(self):
        self.use_redis()
        patcher = patch.object(client, "_sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(client.httpx, "post", return_value=answer(200, json={"result": True}))
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def waits(self, count):
        out = []
        for _ in range(count):
            self.sleep.reset_mock()
            client.call("crm.lead.get", {"id": 1})
            out.append(self.sleep.call_args[0][0] if self.sleep.called else 0)
        return out

    def test_the_burst_goes_at_once_then_each_call_waits_its_turn(self):
        self.assertEqual(self.waits(5), [0, 0, 0, 0.5, 1.0])
        self.assertEqual(self.post.call_count, 5)
        self.assertEqual(self.redis.script_calls, 5)  # one round trip a call

    def test_past_the_longest_wait_it_gives_up_as_a_passing_failure_and_asks_nothing(self):
        self.waits(5)
        with self.assertRaises(client.BitrixTransient) as caught:
            client.call("crm.item.list", {})
        text = str(caught.exception)
        self.assertEqual(text, "crm.item.list: local rate limit, no Bitrix request slot within 1.2 s (timed out waiting)")
        self.assertFalse(caught.exception.maybe_applied)
        self.assertEqual(self.post.call_count, 5)
        # Nothing was reserved by the call that gave up: the next slot is the same one.
        self.now_ms += 500
        self.assertEqual(self.waits(1), [1.0])

    def test_slots_come_back_with_time(self):
        self.waits(5)
        self.now_ms += 10_000
        self.assertEqual(self.waits(4), [0, 0, 0, 0.5])

    def test_the_defaults_stay_under_the_nginx_limit(self):
        from django.conf import settings

        with override_settings():
            for name in ("BITRIX_REST_RATE", "BITRIX_REST_BURST", "BITRIX_REST_MAX_WAIT"):
                delattr(settings, name)  # as in production: not in settings.py at all
            self.assertEqual((redis_state.rate(), redis_state.burst(), redis_state.max_wait()), (1.8, 12, 2.5))
            self.assertEqual(
                (redis_state.background_reserve(), redis_state.down_seconds(), redis_state.background_parallel()), (6, 60, 2)
            )
            waits = self.waits(16)
            self.assertEqual(waits[:12], [0] * 12)
            self.assertEqual(waits[12:], [0.556, 1.112, 1.668, 2.224])
            with self.assertRaises(client.BitrixTransient):
                client.call("crm.lead.get")
            # 12 at once, then one every 556 ms: the nginx zone lets 21 through at once and refills
            # one every 500 ms, so neither the burst nor the pace is refused there.
            self.assertLess(redis_state.burst(), 21)
            self.assertLess(redis_state.rate(), 2)

    def test_redis_out_means_no_limit_and_one_warning_a_minute(self):
        self.redis.fail = redis_lib.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")
        with self.assertLogs("apps.crmlink.redis_state", level="WARNING") as logs:
            self.assertEqual(self.waits(8), [0] * 8)
            self.clock += 30  # past the quiet spell: Redis is asked again, still out
            self.waits(2)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Redis is not answering (ConnectionError", logs.output[0])
        self.assertEqual(self.post.call_count, 10)
        # A minute on, the next failure warns again.
        self.clock += 61
        with self.assertLogs("apps.crmlink.redis_state", level="WARNING") as logs:
            self.waits(1)
        self.assertEqual(len(logs.output), 1)

    def test_redis_back_means_the_limit_is_back(self):
        self.redis.fail = redis_lib.TimeoutError("Timeout reading from socket")
        with self.assertLogs("apps.crmlink.redis_state", level="WARNING"):
            self.waits(1)
        self.redis.fail = None
        self.clock += 11
        self.assertEqual(self.waits(4), [0, 0, 0, 0.5])

    @override_settings(BITRIX_REST_RATE=0)
    def test_a_rate_of_zero_turns_the_limit_off(self):
        self.assertEqual(self.waits(10), [0] * 10)
        self.assertEqual(self.redis.script_calls, 0)

    def test_a_forked_child_makes_its_own_client(self):
        self.waits(1)
        self.assertEqual(self.from_url.call_count, 1)
        with patch.object(redis_state.os, "getpid", return_value=424242):
            self.waits(1)
        self.assertEqual(self.from_url.call_count, 2)
        _, kwargs = self.from_url.call_args
        self.assertEqual((kwargs["socket_timeout"], kwargs["socket_connect_timeout"]), (0.5, 0.5))

    def test_the_fake_runs_the_lua_line_for_line(self):
        # This suite cannot run Lua, so FakeRedis.gcra is the script in Python. The script was run
        # in a real Lua 5.1 against the same algorithm before it went in; a change to it must change
        # this list, and the fake with it. Background work asks the same script with a smaller
        # burst and no wait, so it needs no line of its own.
        lines = [line.strip() for line in redis_state.GCRA.strip().splitlines()]
        self.assertEqual(
            lines,
            [
                "local now = tonumber(ARGV[1])",
                "local interval = tonumber(ARGV[2])",
                "local burst = tonumber(ARGV[3])",
                "local max_wait = tonumber(ARGV[4])",
                "local tat = tonumber(redis.call('GET', KEYS[1])) or now",
                "if tat < now then",
                "tat = now",
                "end",
                "local wait = tat - now - (burst - 1) * interval",
                "if wait < 0 then",
                "wait = 0",
                "end",
                "if wait > max_wait then",
                "return -1",
                "end",
                "tat = tat + interval",
                "redis.call('SET', KEYS[1], tat, 'PX', tat - now + interval)",
                "return wait",
            ],
        )

    def test_no_redis_url_means_no_limit(self):
        with override_settings(REDIS_URL=""):
            self.assertEqual(self.waits(6), [0] * 6)
        self.from_url.assert_not_called()


@override_settings(
    BITRIX_WEBHOOK_URL=WEBHOOK,
    BITRIX_REST_RATE=2.0,
    BITRIX_REST_BURST=12,
    BITRIX_REST_MAX_WAIT=2.5,
    BITRIX_REST_BACKGROUND_RESERVE=6,
)
class BackgroundTests(FakeRedisMixin, SimpleTestCase):
    """Board T57 review F1, S1, S3: background work never sleeps in a worker child."""

    def setUp(self):
        self.use_redis()
        patcher = patch.object(client, "_sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(client.httpx, "post", return_value=answer(200, json={"result": True}))
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def background_calls(self, count):
        """How many of ``count`` background calls went, stopping at the first refusal."""
        went = 0
        with client.background():
            for _ in range(count):
                try:
                    client.call("crm.timeline.comment.add", {})
                except client.BitrixTransient as exc:
                    self.refusal = exc
                    break
                went += 1
        return went

    def test_background_work_takes_a_slot_free_now_or_none_and_leaves_the_reserve(self):
        self.assertEqual(self.background_calls(10), 6)
        self.assertEqual(
            str(self.refusal),
            "crm.timeline.comment.add: local rate limit, no Bitrix request slot free for background work now (timed out waiting)",
        )
        self.assertFalse(self.refusal.maybe_applied)
        self.sleep.assert_not_called()
        self.assertEqual(self.post.call_count, 6)
        # The reserve is there for everybody else: a campaign's burst of six goes at once.
        for _ in range(6):
            client.call("crm.item.list", {})
        self.sleep.assert_not_called()
        client.call("crm.item.list", {})
        self.sleep.assert_called_once_with(0.5)

    def test_while_others_wait_for_slots_background_work_asks_nothing(self):
        for _ in range(14):
            client.call("crm.item.list", {})  # 12 at once, then two waits: the bucket is in debt
        self.sleep.reset_mock()
        asked = self.post.call_count
        self.assertEqual(self.background_calls(1), 0)
        self.sleep.assert_not_called()
        self.assertEqual(self.post.call_count, asked)
        # It reserved nothing: the next caller's wait is the one it would have had.
        client.call("crm.item.list", {})
        self.sleep.assert_called_once_with(1.5)

    def test_slots_come_back_for_background_work_with_time(self):
        self.background_calls(10)
        self.now_ms += 3_000  # six slots back at two a second
        self.assertEqual(self.background_calls(10), 6)

    def test_bitrix_down_stops_background_calls_and_nobody_else(self):
        self.redis.values[redis_state.DOWN_KEY] = "1"
        self.assertEqual(self.background_calls(1), 0)
        self.assertIn("Bitrix timed out or could not be reached in the last minute", str(self.refusal))
        self.assertIn("timed out", str(self.refusal))
        self.assertFalse(self.refusal.maybe_applied)
        self.post.assert_not_called()
        self.assertEqual(self.redis.script_calls, 0)  # no slot taken either
        client.call("crm.lead.get", {"id": 1})  # campaigns, Lead AI and the panel go on
        self.assertEqual(self.post.call_count, 1)

    def test_a_timeout_marks_bitrix_down_for_a_minute(self):
        request = httpx.Request("POST", WEBHOOK)
        self.post.side_effect = httpx.ReadTimeout("timed out", request=request)
        with self.assertRaises(client.BitrixTransient) as caught:
            client.call("crm.lead.get", {"id": 1})  # anybody's timeout counts
        self.assertTrue(caught.exception.maybe_applied)
        self.assertEqual(self.redis.px[redis_state.DOWN_KEY], 60_000)
        self.post.reset_mock()
        self.assertEqual(self.background_calls(3), 0)
        self.post.assert_not_called()

    @override_settings(BITRIX_DOWN_SECONDS=0)
    def test_down_seconds_of_zero_turns_the_pause_off(self):
        self.post.side_effect = httpx.ConnectError("refused", request=httpx.Request("POST", WEBHOOK))
        with self.assertRaises(client.BitrixTransient):
            client.call("crm.lead.get", {"id": 1})
        self.assertNotIn(redis_state.DOWN_KEY, self.redis.values)

    def test_background_calls_give_up_sooner(self):
        client.call("crm.lead.get", {"id": 1})
        self.assertEqual(self.post.call_args.kwargs["timeout"], 20)
        with client.background():
            client.call("crm.lead.get", {"id": 1})
        timeout = self.post.call_args.kwargs["timeout"]
        self.assertIs(timeout, client.BACKGROUND_TIMEOUT)
        self.assertEqual((timeout.read, timeout.connect), (10.0, 5.0))

    def test_the_flag_ends_with_its_block_even_on_an_error(self):
        with self.assertRaises(RuntimeError):
            with client.background():
                self.assertTrue(client._background.get())
                raise RuntimeError("boom")
        self.assertFalse(client._background.get())

    def test_redis_out_background_work_goes_unlimited_as_before(self):
        self.redis.fail = redis_lib.ConnectionError("down")
        with self.assertLogs("apps.crmlink.redis_state", level="WARNING"):
            self.assertEqual(self.background_calls(10), 10)
        self.sleep.assert_not_called()


# 3. Finding the records: strict and cached
# ---------------------------------------------------------------------------


@override_settings(BITRIX_WEBHOOK_URL=WEBHOOK)
class FindRecordsTests(FakeRedisMixin, SimpleTestCase):
    LEAD = {"type": "lead", "id": 101, "kind": "lead"}
    CARD = {"type": OWNER_DATA, "id": 7, "kind": "owner data"}

    def setUp(self):
        self.use_redis()

    def bitrix(self, **kwargs):
        fake = FakeBitrix(**kwargs)
        patcher = patch.object(client, "call", side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_a_complete_lookup_is_the_same_as_before(self):
        fake = self.bitrix()
        self.assertEqual(client.find_records(WA_ID), [self.LEAD, self.CARD])
        self.assertEqual(
            fake.methods(),
            ["crm.duplicate.findbycomm", "crm.lead.get"] + ["crm.item.list"] * 4,
        )

    def test_not_strict_a_passing_failure_is_logged_and_skipped_as_before(self):
        fake = self.bitrix(contacts=(202,), fail={("crm.duplicate.findbycomm", "LEAD"): [passing()], "crm.item.list": [passing()]})
        with self.assertLogs("apps.crmlink.client", level="WARNING") as logs:
            records = client.find_records(WA_ID)
        # The lead search failed, so the contact search ran, as it always did.
        self.assertEqual(records, [{"type": "contact", "id": 202, "kind": "contact"}, self.CARD])
        self.assertIn("Bitrix duplicate search failed for LEAD", logs.output[0])
        self.assertIn("crm.duplicate.findbycomm", fake.methods())

    def test_strict_a_passing_failure_of_any_lookup_raises(self):
        for fail in (
            {("crm.duplicate.findbycomm", "LEAD"): [passing()]},
            {("crm.duplicate.findbycomm", "CONTACT"): [passing()]},
            {"crm.lead.get": [passing()]},
            {"crm.item.list": [None, None, passing()]},
        ):
            with self.subTest(fail=list(fail)):
                self.bitrix(leads=() if ("crm.duplicate.findbycomm", "CONTACT") in fail else (101,), fail=fail)
                with self.assertRaises(client.BitrixTransient):
                    client.find_records(WA_ID, strict=True)

    def test_strict_a_refusal_is_skipped_as_before(self):
        self.bitrix(fail={"crm.lead.get": [client.BitrixError("crm.lead.get: Access denied")]})
        with self.assertLogs("apps.crmlink.client", level="WARNING"):
            records = client.find_records(WA_ID, strict=True)
        self.assertEqual(records, [self.CARD])

    def test_owner_data_matches_keeps_its_shape_for_campaigns_and_never_raises(self):
        self.bitrix(fail={"crm.item.list": [passing(), passing(), passing(), passing()]})
        with self.assertLogs("apps.crmlink.client", level="WARNING"):
            self.assertEqual(client._owner_data_matches(WA_ID), [])
        self.bitrix()
        self.assertEqual(client._owner_data_matches(WA_ID), [self.CARD])
        self.assertEqual(self.redis.values, {})  # campaigns' lookups are not cached

    def test_a_cached_lookup_asks_bitrix_once_per_number(self):
        fake = self.bitrix()
        first = client.find_records(WA_ID, strict=True, cached=True)
        asked = len(fake.calls)
        again = client.find_records(f"+{WA_ID}", strict=True, cached=True)
        self.assertEqual(first, again)
        self.assertEqual(len(fake.calls), asked)
        self.assertEqual(client.owner_data_records(WA_ID, cached=True), [self.CARD])
        self.assertEqual(len(fake.calls), asked)
        # About ten minutes, then Bitrix is asked again (a lead made in Bitrix meanwhile shows).
        self.assertEqual(set(self.redis.ex.values()), {600})
        # The number itself never appears in a key.
        self.assertFalse(any(WA_ID in key for key in self.redis.values))

    def test_a_failed_lookup_is_never_cached(self):
        fake = self.bitrix(fail={"crm.item.list": [passing()]})
        with self.assertLogs("apps.crmlink.client", level="WARNING"):
            client.find_records(WA_ID, cached=True)
        self.assertNotIn(client._cache_key("owner", WA_ID), self.redis.values)
        self.assertIn(client._cache_key("person", WA_ID), self.redis.values)  # that half answered
        asked = fake.methods().count("crm.item.list")
        self.assertEqual(client.find_records(WA_ID, cached=True), [self.LEAD, self.CARD])
        self.assertEqual(fake.methods().count("crm.item.list"), asked + 4)
        self.assertEqual(fake.methods().count("crm.duplicate.findbycomm"), 1)

    def test_a_refused_lookup_is_never_cached_either(self):
        self.bitrix(fail={"crm.lead.get": [client.BitrixError("crm.lead.get: Access denied")]})
        with self.assertLogs("apps.crmlink.client", level="WARNING"):
            client.find_records(WA_ID, cached=True)
        self.assertNotIn(client._cache_key("person", WA_ID), self.redis.values)

    def test_every_other_caller_asks_bitrix_and_leaves_the_fresh_answer(self):
        fake = self.bitrix()
        client.find_records(WA_ID)
        client.find_records(WA_ID)
        self.assertEqual(fake.methods().count("crm.duplicate.findbycomm"), 2)
        asked = len(fake.calls)
        client.find_records(WA_ID, cached=True)
        self.assertEqual(len(fake.calls), asked)

    def test_no_record_is_an_answer_worth_keeping_too_but_for_two_minutes(self):
        fake = self.bitrix(leads=(), owner_data=())
        self.assertEqual(client.find_records(WA_ID, cached=True), [])
        asked = len(fake.calls)
        self.assertEqual(client.find_records(WA_ID, cached=True), [])
        self.assertEqual(len(fake.calls), asked)
        # A lead somebody makes by hand after the first message starts getting the lines soon.
        self.assertEqual(set(self.redis.ex.values()), {120})
        fake.owner_data = [7]
        self.redis.values.clear()
        client.find_records(WA_ID, cached=True)
        self.assertEqual(self.redis.ex, {client._cache_key("person", WA_ID): 120, client._cache_key("owner", WA_ID): 600})

    def test_a_record_made_here_drops_the_entry(self):
        fake = self.bitrix(leads=(), owner_data=())
        client.find_records(WA_ID, cached=True)
        client.create_lead(WA_ID, "Ahmed")
        self.assertIn(client._cache_key("person", WA_ID), self.redis.deleted)
        fake.leads, fake.owner_data = [555], [77]
        self.assertEqual([r["id"] for r in client.find_records(WA_ID, cached=True)], [555, 77])
        client.create_owner_data(WA_ID, "Ahmed")
        self.assertIn(client._cache_key("owner", WA_ID), self.redis.deleted[-2:])
        self.assertEqual(self.redis.values[client._generation_key(WA_ID)], "2")
        self.assertEqual(self.redis.ex[client._generation_key(WA_ID)], client.GENERATION_SECONDS)

    def test_a_lookup_under_way_when_a_record_is_made_is_never_read_back(self):
        # Board T57 review F8: an agent presses Create lead while a mirror's lookup of the same
        # number is half done. Its "no record", stored after the lead was made, must not hide it.
        fake = FakeBitrix(leads=(), owner_data=())

        def racing(method, payload=None):
            if method == "crm.duplicate.findbycomm" and payload["entity_type"] == "CONTACT" and not fake.leads:
                fake.leads = [555]
                client.create_lead(WA_ID, "Ahmed")  # crm.lead.add answers 555
            return fake(method, payload)

        with patch.object(client, "call", side_effect=racing):
            self.assertEqual(client.find_records(WA_ID, strict=True, cached=True), [])  # began before the lead
            self.assertIn(client._cache_key("person", WA_ID), self.redis.values)  # stored, but stale
            searches = fake.methods().count("crm.duplicate.findbycomm")
            records = client.find_records(WA_ID, strict=True, cached=True)
        self.assertEqual(records[0], {"type": "lead", "id": 555, "kind": "lead"})
        self.assertEqual(fake.methods().count("crm.duplicate.findbycomm"), searches + 1)

    def test_without_redis_every_lookup_asks_bitrix(self):
        fake = self.bitrix()
        self.redis.fail = redis_lib.ConnectionError("down")
        with self.assertLogs("apps.crmlink.redis_state", level="WARNING"):
            client.find_records(WA_ID, cached=True)
            client.find_records(WA_ID, cached=True)
        self.assertEqual(fake.methods().count("crm.duplicate.findbycomm"), 2)

    def test_something_else_under_the_key_is_a_miss(self):
        fake = self.bitrix()
        self.redis.values[client._cache_key("person", WA_ID)] = '[{"type": "lead"}]'
        self.redis.values[client._cache_key("owner", WA_ID)] = "not json"
        self.assertEqual(client.find_records(WA_ID, cached=True), [self.LEAD, self.CARD])
        self.assertIn("crm.duplicate.findbycomm", fake.methods())
        self.redis.values[client._generation_key(WA_ID)] = "garbage"
        asked = len(fake.calls)
        self.assertEqual(client.find_records(WA_ID, cached=True), [self.LEAD, self.CARD])
        self.assertGreater(len(fake.calls), asked)

    def test_a_comment_is_found_by_its_text_newest_first_skipping_known_ids(self):
        fake = self.bitrix()
        fake.store("lead", 101, "WhatsApp · Customer · 14 Oct 11:46\nok")
        fake.store("lead", 101, "something else")
        fake.store("lead", 101, "WhatsApp · Customer · 14 Oct 11:46\nok")
        fake.store("lead", 202, "WhatsApp · Customer · 14 Oct 11:47\nhi")
        line = "WhatsApp · Customer · 14 Oct 11:46\nok"
        self.assertEqual(client.find_comment("lead", 101, line), 9003)
        self.assertEqual(client.find_comment("lead", 101, line, skip={9003}), 9001)
        self.assertIsNone(client.find_comment("lead", 101, line, skip={9001, 9003}))
        self.assertIsNone(client.find_comment("lead", 101, "WhatsApp · Customer · 14 Oct 11:47\nhi"))
        # Bitrix may give it back with other line ends and entities.
        fake.store("lead", 303, "WhatsApp · Customer · 14 Oct 11:48\r\nfish &amp; chips")
        self.assertEqual(client.find_comment("lead", 303, "WhatsApp · Customer · 14 Oct 11:48\nfish & chips"), 9005)
        _, payload = fake.calls[0]
        self.assertEqual(payload["order"], {"ID": "DESC"})
        self.assertEqual(payload["filter"], {"ENTITY_ID": 101, "ENTITY_TYPE": "lead"})


# 4 and 5. The mirror: retries, and the Lead AI chat's own lead
# ---------------------------------------------------------------------------


@override_settings(BITRIX_WEBHOOK_URL=WEBHOOK, SUMMARY_EVERY_N_MESSAGES=0)
class MirrorBase(FakeRedisMixin, TestCase):
    BODY = "My budget is 45k, Dragon Mart side please"

    def setUp(self):
        for target in OTHER_TASKS:
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.use_redis()
        self.number = WabaNumber.objects.create(phone_number="971500000001", phone_number_id="pn1", waba_business_id="waba1")
        self.contact = Contact.objects.create(wa_id=WA_ID, display_name="Ahmed Khan")
        self.conversation = Conversation.objects.create(number=self.number, contact=self.contact)
        self.bitrix = FakeBitrix()
        self.call_patch = patch.object(client, "call", side_effect=self.bitrix)
        self.call_patch.start()
        self.addCleanup(self.call_patch.stop)

    def message(self, body=None, direction=Message.Direction.INBOUND, kind=Message.Kind.TEXT, conversation=None, **fields):
        return Message.objects.create(
            conversation=conversation or self.conversation,
            direction=direction,
            kind=kind,
            body=self.BODY if body is None else body,
            **fields,
        )

    def mirrored(self, message):
        return set(Mirror.objects.filter(message=message).values_list("entity_type", "entity_id"))

    @property
    def agent(self):
        if not hasattr(self, "_agent"):
            self._agent = Agent.objects.create_user(username="agent", password="x", bitrix_user_id="77", display_name="Nabiha")
        return self._agent

    @property
    def template(self):
        if not hasattr(self, "_template"):
            self._template = WaTemplate.objects.create(
                waba_business_id="waba1",
                name="ic_shops",
                language="en",
                category="MARKETING",
                status=WaTemplate.Status.APPROVED,
                components=[{"type": "BODY", "text": "Hi {{1}}, shops are available in International City."}],
            )
        return self._template

    def campaign(self, *, lead_ai=False, name="CRM Leads · campaign", **fields):
        campaign = Campaign.objects.create(name=name, number=self.number, template=self.template, created_by=self.agent, **fields)
        if lead_ai:
            lane.mark_campaign(campaign)
        return campaign

    def sent(self, campaign, at, conversation=THIS_CHAT, phone=WA_ID, **fields):
        """A recipient of ``campaign`` whose attempt began ``at`` (``conversation`` None: before
        process_recipient saved it on the row, after the send)."""
        fields.setdefault("status", CampaignRecipient.Status.SENT)
        return CampaignRecipient.objects.create(
            campaign=campaign,
            phone=phone,
            conversation=self.conversation if conversation is THIS_CHAT else conversation,
            last_attempt_at=at,
            **fields,
        )

    def run_once(self, message, retries=0, **kwargs):
        """One run as the worker would make it, with retry() caught rather than queued."""
        with patch.object(tasks.mirror_message, "retry", side_effect=Retry("again")) as retry:
            result = tasks.mirror_message.apply(args=[message.pk], kwargs=kwargs, retries=retries, throw=False)
        if retry.called:
            self.assertIsInstance(result.result, Retry)
        else:
            self.assertEqual(result.state, "SUCCESS", result.result)
        return retry


class MirrorRetryTests(MirrorBase):
    def test_a_passing_lookup_failure_is_tried_again_in_about_30_seconds(self):
        self.bitrix.fail = {("crm.duplicate.findbycomm", "LEAD"): [passing()]}
        message = self.message()
        retry = self.run_once(message)
        retry.assert_called_once()
        kwargs = retry.call_args.kwargs
        self.assertTrue(30 <= kwargs["countdown"] <= 36, kwargs)
        self.assertEqual(kwargs["kwargs"], FIRST_TRY)
        self.assertIsInstance(kwargs["exc"], client.BitrixTransient)
        self.assertEqual(self.bitrix.comments, [])
        self.assertEqual(self.mirrored(message), set())

    def test_the_waits_grow_to_half_an_hour_with_a_little_jitter(self):
        for retries, base in enumerate((30, 60, 120, 300, 600, 1200, 1800, 1800)):
            for _ in range(20):
                countdown = tasks._countdown(tasks.MIRROR_RETRY_SECONDS, retries)
                self.assertTrue(base <= countdown <= base * 1.2, (retries, countdown))
        # About an hour and a half of tries in all: longer than a busy campaign keeps the budget.
        self.assertGreater(sum(tasks.MIRROR_RETRY_SECONDS), 90 * 60)
        self.assertEqual(tasks.mirror_message.max_retries, 8 + tasks.MAX_DEFERRALS)
        self.assertLess(max(tasks.MIRROR_RETRY_SECONDS) * (1 + tasks.JITTER), 3600)
        self.assertLess(max(tasks.DEFER_SECONDS), 3600)

    def test_a_passing_post_failure_retries_only_the_record_still_missing_it(self):
        self.bitrix.fail = {("crm.timeline.comment.add", OWNER_DATA): [passing()]}
        message = self.message()
        retry = self.run_once(message)
        self.assertEqual(self.mirrored(message), {("lead", 101)})
        self.assertEqual(retry.call_args.kwargs["kwargs"], {**FIRST_TRY, "summary_check": False})
        # The next try: the lead has it already and is not posted again.
        retry = self.run_once(message, retries=1, summary_check=False)
        retry.assert_not_called()
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101), (OWNER_DATA, 7)])
        self.assertNotIn("crm.timeline.comment.list", self.bitrix.methods())  # a 429 never ran: no look

    def test_the_whole_chain_as_celery_runs_it_posts_each_record_once(self):
        # apply() runs a retry at once, as the worker would after its countdown.
        self.bitrix.fail = {
            ("crm.duplicate.findbycomm", "LEAD"): [passing()],
            ("crm.timeline.comment.add", OWNER_DATA): [passing(), Landed(lost())],
        }
        message = self.message()
        result = tasks.mirror_message.apply(args=[message.pk])
        self.assertEqual(result.state, "SUCCESS", result.result)
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})
        self.assertEqual(sorted(self.bitrix.posted_on()), sorted([("lead", 101), (OWNER_DATA, 7)]))
        self.assertEqual(self.redis.locks, set())  # every run let go of the message and its slot

    def test_after_the_last_try_one_warning_names_the_message_and_record_never_its_text(self):
        self.bitrix.fail = {("crm.timeline.comment.add", OWNER_DATA): [passing()]}
        message = self.message()
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            retry = self.run_once(message, retries=8, summary_check=False)
        retry.assert_not_called()
        self.assertEqual(len(logs.output), 1)
        self.assertIn(f"Gave up mirroring message {message.pk} to {OWNER_DATA} 7 after 9 tries", logs.output[0])
        self.assertIn("HTTP 429", logs.output[0])
        for secret in (self.BODY, "45k", WA_ID, "Ahmed"):
            self.assertNotIn(secret, logs.output[0])

    def test_a_lookup_that_never_answers_gives_up_with_one_warning(self):
        self.bitrix.fail = {("crm.duplicate.findbycomm", "LEAD"): [passing("crm.duplicate.findbycomm: HTTP 503, Too many requests")]}
        message = self.message()
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            self.run_once(message, retries=8).assert_not_called()
        self.assertIn(f"Gave up mirroring message {message.pk} to its records after 9 tries", logs.output[0])

    def test_a_refusal_is_not_tried_again(self):
        self.bitrix.fail = {("crm.timeline.comment.add", "lead"): [client.BitrixError("crm.timeline.comment.add: Access denied")]}
        message = self.message()
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            self.run_once(message).assert_not_called()
        self.assertIn(f"Could not mirror message {message.pk} to lead 101", logs.output[0])
        self.assertEqual(self.mirrored(message), {(OWNER_DATA, 7)})
        self.assertEqual(self.bitrix.posted_on(), [(OWNER_DATA, 7)])

    def test_another_run_posting_the_message_now_sends_this_one_back_soon_using_up_no_try(self):
        message = self.message()
        self.redis.locks.add(f"crmlink:mirror:{message.pk}")
        retry = self.run_once(message, retries=5, deferred=2)
        retry.assert_called_once()
        kwargs = retry.call_args.kwargs
        self.assertTrue(15 <= kwargs["countdown"] <= 75, kwargs)
        self.assertEqual(kwargs["kwargs"], {**FIRST_TRY, "deferred": 3})
        self.assertEqual(self.bitrix.calls, [])

    def test_no_more_than_two_background_tasks_talk_to_bitrix_at_once(self):
        message = self.message()
        self.redis.locks.update({f"{tasks.BACKGROUND_SLOTS}:0", f"{tasks.BACKGROUND_SLOTS}:1"})
        retry = self.run_once(message)
        self.assertEqual(retry.call_args.kwargs["kwargs"], {**FIRST_TRY, "deferred": 1})
        self.assertEqual(self.bitrix.calls, [])
        self.assertNotIn(f"crmlink:mirror:{message.pk}", self.redis.locks)  # let go of the message
        # One slot free again: it goes.
        self.redis.locks.discard(f"{tasks.BACKGROUND_SLOTS}:1")
        self.run_once(message, retries=1, deferred=1).assert_not_called()
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})

    def test_too_many_busy_turns_count_as_a_failed_try_and_end_in_one_warning(self):
        message = self.message()
        self.redis.locks.add(f"crmlink:mirror:{message.pk}")
        retry = self.run_once(message, retries=tasks.MAX_DEFERRALS, deferred=tasks.MAX_DEFERRALS)
        kwargs = retry.call_args.kwargs
        self.assertTrue(30 <= kwargs["countdown"] <= 36, kwargs)  # the first failed try's wait
        self.assertEqual(kwargs["kwargs"]["deferred"], tasks.MAX_DEFERRALS)
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            self.run_once(message, retries=tasks.MAX_DEFERRALS + 8, deferred=tasks.MAX_DEFERRALS).assert_not_called()
        self.assertIn("another run of it is posting now", logs.output[0])

    def test_the_lock_and_a_background_slot_are_held_while_posting_and_let_go_after(self):
        message = self.message()
        seen = []
        real = self.bitrix.__call__

        def spy(method, payload=None):
            seen.append(set(self.redis.locks))
            return real(method, payload)

        with patch.object(client, "call", side_effect=spy):
            self.run_once(message).assert_not_called()
        self.assertTrue(all({f"crmlink:mirror:{message.pk}", f"{tasks.BACKGROUND_SLOTS}:0"} <= locks for locks in seen))
        self.assertEqual(self.redis.locks, set())
        self.assertEqual(self.redis.lock_timeouts, [redis_state.LOCK_SECONDS, redis_state.LOCK_SECONDS])

    def test_without_redis_the_mirror_still_posts(self):
        self.redis.fail = redis_lib.ConnectionError("down")
        message = self.message()
        with self.assertLogs("apps.crmlink.redis_state", level="WARNING"):
            self.run_once(message).assert_not_called()
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})

    def test_no_record_is_neither_an_error_nor_retried(self):
        self.bitrix.leads, self.bitrix.owner_data = [], []
        message = self.message()
        self.run_once(message).assert_not_called()
        self.assertEqual(self.bitrix.comments, [])

    @override_settings(SUMMARY_EVERY_N_MESSAGES=1)
    def test_the_summary_is_considered_once_however_many_tries(self):
        self.bitrix.fail = {("crm.timeline.comment.add", OWNER_DATA): [passing()]}
        message = self.message()
        with patch.object(tasks.refresh_summary, "delay") as summary:
            retry = self.run_once(message)
            self.run_once(message, retries=1, **retry.call_args.kwargs["kwargs"])
        summary.assert_called_once_with(self.conversation.pk)

    @override_settings(SUMMARY_EVERY_N_MESSAGES=1)
    def test_a_lookup_failure_leaves_the_summary_to_the_try_that_answers(self):
        self.bitrix.fail = {("crm.duplicate.findbycomm", "LEAD"): [passing()]}
        message = self.message()
        with patch.object(tasks.refresh_summary, "delay") as summary:
            retry = self.run_once(message)
            summary.assert_not_called()
            self.run_once(message, retries=1, **retry.call_args.kwargs["kwargs"])
        summary.assert_called_once_with(self.conversation.pk)

    @override_settings(SUMMARY_EVERY_N_MESSAGES=2)
    def test_the_summary_turn_is_the_nth_message_s_whenever_its_mirror_runs(self):
        # Board T57 review S6: a try that runs late, after more messages came, must neither take
        # the turn of the message that is the Nth nor leave that one without its turn.
        first, second, third = self.message("one"), self.message("two"), self.message("three")
        with patch.object(tasks.refresh_summary, "delay") as summary:
            self.run_once(first)
            self.run_once(third)
            summary.assert_not_called()
            self.run_once(second)
        summary.assert_called_once_with(self.conversation.pk)

    def test_the_mirror_reuses_the_lookup_within_the_chat(self):
        first, second = self.message("one"), self.message("two")
        self.run_once(first)
        asked = len(self.bitrix.calls)
        self.run_once(second)
        self.assertEqual(self.bitrix.methods()[asked:], ["crm.timeline.comment.add"] * 2)
        self.assertEqual(self.mirrored(second), {("lead", 101), (OWNER_DATA, 7)})


class LostAnswerTests(MirrorBase):
    """Board T57 review F2 / S4: a post whose answer was lost may be on the timeline already."""

    def test_a_comment_whose_answer_was_lost_is_looked_for_and_not_posted_again(self):
        self.bitrix.fail = {("crm.timeline.comment.add", "lead"): [Landed(lost())]}
        message = self.message()
        retry = self.run_once(message)
        later = retry.call_args.kwargs["kwargs"]
        self.assertEqual(later, {**FIRST_TRY, "summary_check": False, "check": [["lead", 101]]})
        self.assertEqual(self.mirrored(message), {(OWNER_DATA, 7)})
        self.run_once(message, retries=1, **later).assert_not_called()
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101), (OWNER_DATA, 7)])  # the lead's line once
        landed = self.bitrix.comment_ids[0]
        self.assertEqual(Mirror.objects.get(message=message, entity_type="lead").comment_id, landed)
        self.assertEqual(self.bitrix.methods().count("crm.timeline.comment.list"), 1)

    def test_one_that_never_landed_is_posted_on_the_next_try(self):
        self.bitrix.fail = {("crm.timeline.comment.add", "lead"): [lost("crm.timeline.comment.add: HTTP 502")]}
        message = self.message()
        later = self.run_once(message).call_args.kwargs["kwargs"]
        self.run_once(message, retries=1, **later).assert_not_called()
        self.assertEqual(self.bitrix.posted_on(), [(OWNER_DATA, 7), ("lead", 101)])
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})

    def test_a_look_that_fails_in_passing_is_made_again_on_the_try_after(self):
        self.bitrix.fail = {
            ("crm.timeline.comment.add", "lead"): [Landed(lost())],
            "crm.timeline.comment.list": [passing("crm.timeline.comment.list: HTTP 429, not JSON")],
        }
        message = self.message()
        later = self.run_once(message).call_args.kwargs["kwargs"]
        later = self.run_once(message, retries=1, **later).call_args.kwargs["kwargs"]
        self.assertEqual(later["check"], [["lead", 101]])
        self.run_once(message, retries=2, **later).assert_not_called()
        self.assertEqual(self.bitrix.posted_on().count(("lead", 101)), 1)
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})

    def test_a_look_bitrix_refuses_is_not_followed_by_a_second_post(self):
        self.bitrix.fail = {
            ("crm.timeline.comment.add", "lead"): [Landed(lost())],
            "crm.timeline.comment.list": [client.BitrixError("crm.timeline.comment.list: Access denied")],
        }
        message = self.message()
        later = self.run_once(message).call_args.kwargs["kwargs"]
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            self.run_once(message, retries=1, **later).assert_not_called()
        self.assertIn(f"Could not check whether message {message.pk} reached lead 101; not posted again", logs.output[0])
        self.assertEqual(self.bitrix.posted_on().count(("lead", 101)), 1)

    def test_a_back_filled_message_already_on_the_timeline_is_recorded_not_posted(self):
        message = self.message()
        old = self.bitrix.store("lead", 101, tasks._line(message))  # posted before, its answer lost
        self.run_once(message, look_first=True, summary_check=False).assert_not_called()
        self.assertEqual(Mirror.objects.get(message=message, entity_type="lead").comment_id, old)
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101), (OWNER_DATA, 7)])  # the card's is new

    def test_two_alike_lines_are_told_apart_by_the_ids_already_recorded(self):
        first = self.message("ok")
        second = self.message("ok", created_at=first.created_at)
        self.run_once(first).assert_not_called()
        self.run_once(second, look_first=True, summary_check=False).assert_not_called()
        self.assertEqual(self.bitrix.posted_on().count(("lead", 101)), 2)
        ids = set(Mirror.objects.filter(entity_type="lead").values_list("comment_id", flat=True))
        self.assertEqual(len(ids), 2)


class CampaignTemplateTests(MirrorBase):
    """Board T57 review F9: a campaign posts its own copy of its template; the mirror never does,
    whether it runs before the send's transaction commits or after."""

    def template_message(self, at, **fields):
        return self.message("Hi Ahmed, shops are available", Message.Direction.OUTBOUND, Message.Kind.TEMPLATE, template=self.template, created_at=at, **fields)

    def test_a_campaign_template_is_never_mirrored(self):
        now = timezone.now()
        campaign = self.campaign()
        # Mirrored after the commit, before process_recipient saved the conversation on the row.
        recipient = self.sent(campaign, now - dt.timedelta(seconds=20), conversation=None, status=CampaignRecipient.Status.PENDING)
        message = self.template_message(now)
        self.run_once(message).assert_not_called()
        self.assertEqual(self.bitrix.calls, [])
        self.assertEqual(self.mirrored(message), set())
        # And after it.
        CampaignRecipient.objects.filter(pk=recipient.pk).update(conversation=self.conversation, phone="0")
        self.run_once(message).assert_not_called()
        self.assertEqual(self.bitrix.calls, [])

    def test_the_lead_ai_own_templates_and_an_agent_s_template_are_mirrored(self):
        now = timezone.now()
        campaign = self.campaign()
        self.sent(campaign, now - dt.timedelta(hours=2))
        reminder = self.template_message(now - dt.timedelta(hours=2) + dt.timedelta(seconds=30), payload={"source": "leadai_reminder"})
        resent = self.template_message(now)  # an agent sent the same template from the panel, later
        for message in (reminder, resent):
            self.run_once(message).assert_not_called()
            self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})
        other_line = WabaNumber.objects.create(phone_number="971500000002", phone_number_id="pn2", waba_business_id="waba1")
        elsewhere = Conversation.objects.create(number=other_line, contact=self.contact)
        sent_elsewhere = self.message("Hi", Message.Direction.OUTBOUND, Message.Kind.TEMPLATE, template=self.template, conversation=elsewhere)
        self.assertFalse(tasks._campaign_send(sent_elsewhere))


class StaleRecordTests(MirrorBase):
    """Board T57 review S5: a cached record that is gone gets the number looked up again."""

    def test_a_cached_record_that_refuses_is_looked_up_afresh_once(self):
        self.run_once(self.message("one")).assert_not_called()  # caches lead 101 and card 7
        # The leads were merged in Bitrix: 101 is gone, 202 holds the number.
        self.bitrix.leads = [202]
        self.bitrix.fail = {("crm.timeline.comment.add", "lead"): [client.BitrixError("crm.timeline.comment.add: Not found")]}
        message = self.message("two")
        searches = self.bitrix.methods().count("crm.duplicate.findbycomm")
        with self.assertLogs("apps.crmlink.tasks", level="WARNING"):
            self.run_once(message).assert_not_called()
        self.assertEqual(self.mirrored(message), {("lead", 202), (OWNER_DATA, 7)})
        self.assertEqual(self.bitrix.methods().count("crm.duplicate.findbycomm"), searches + 1)
        self.assertNotIn(("lead", 101), self.mirrored(message))

    def test_an_answer_without_a_comment_id_writes_no_mirror_row(self):
        self.bitrix.fail = {("crm.timeline.comment.add", OWNER_DATA): [NO_ID, NO_ID]}
        message = self.message()
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            self.run_once(message).assert_not_called()
        self.assertIn("Bitrix gave no comment id", logs.output[0])
        self.assertEqual(self.mirrored(message), {("lead", 101)})
        self.assertFalse(Mirror.objects.filter(comment_id__isnull=True).exists())

    def test_a_refusal_on_the_chat_s_own_lead_asks_bitrix_nothing_more(self):
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=73688)
        self.bitrix.fail = {("crm.timeline.comment.add", "lead"): [client.BitrixError("crm.timeline.comment.add: Not found")]}
        with self.assertLogs("apps.crmlink.tasks", level="WARNING"):
            self.run_once(self.message()).assert_not_called()
        self.assertNotIn("crm.duplicate.findbycomm", self.bitrix.methods())
        self.assertEqual(self.bitrix.methods().count("crm.item.list"), 4)  # the Owner Data half, once


@override_settings(BITRIX_REST_RATE=2.0, BITRIX_REST_BURST=12, BITRIX_REST_BACKGROUND_RESERVE=6)
class MirrorInTheBackgroundTests(MirrorBase):
    """The mirror through the real client.call: it never sleeps for a slot, and leaves Bitrix
    alone for a minute after a timeout (board T57 review F1, S1, S3)."""

    def setUp(self):
        super().setUp()
        self.call_patch.stop()
        self.timeouts = []
        patcher = patch.object(client.httpx, "post", side_effect=self.http)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(client, "_sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)
        self.down = None
        self.latency_ms = 300  # each answer takes this long: the bucket refills meanwhile

    def http(self, url, json=None, timeout=None):
        self.timeouts.append(timeout)
        self.now_ms += self.latency_ms
        if self.down is not None:
            raise self.down
        return httpx.Response(200, json={"result": self.bitrix(url.rsplit("/", 1)[-1], json)})

    def test_the_mirror_posts_with_background_priority(self):
        message = self.message()
        self.run_once(message).assert_not_called()
        self.assertEqual(self.mirrored(message), {("lead", 101), (OWNER_DATA, 7)})
        self.assertTrue(self.timeouts)
        self.assertTrue(all(timeout is client.BACKGROUND_TIMEOUT for timeout in self.timeouts))
        self.sleep.assert_not_called()

    def test_with_the_budget_taken_the_mirror_comes_back_later_and_never_sleeps(self):
        self.latency_ms = 0
        for _ in range(13):
            client.call("crm.item.list", {})  # a campaign's burst: the bucket is in debt
        self.sleep.reset_mock()
        asked = self.post.call_count
        message = self.message()
        retry = self.run_once(message)
        self.assertIn("free for background work now", str(retry.call_args.kwargs["exc"]))
        self.assertTrue(30 <= retry.call_args.kwargs["countdown"] <= 36)
        self.sleep.assert_not_called()
        self.assertEqual(self.post.call_count, asked)

    def test_after_a_timeout_the_next_messages_wait_without_asking_bitrix(self):
        self.down = httpx.ReadTimeout("timed out", request=httpx.Request("POST", WEBHOOK))
        first = self.message("one")
        retry = self.run_once(first)
        self.assertIsInstance(retry.call_args.kwargs["exc"], client.BitrixTransient)
        self.assertEqual(self.post.call_count, 1)  # one timeout, and Bitrix is left alone
        self.down = None
        second = self.message("two")
        retry = self.run_once(second)
        self.assertIn("Bitrix timed out or could not be reached", str(retry.call_args.kwargs["exc"]))
        self.assertEqual(self.post.call_count, 1)
        self.redis.values.pop(redis_state.DOWN_KEY)  # a minute on
        self.run_once(second, retries=1).assert_not_called()
        self.assertEqual(self.mirrored(second), {("lead", 101), (OWNER_DATA, 7)})


class OwnLeadTests(MirrorBase):
    """Board T57: a Lead AI chat's messages go on the lead its campaign was sent from."""

    def chat(self, entity="lead", crm_id=73688, **fields):
        return LeadAiChat.objects.create(conversation=self.conversation, crm_entity=entity, crm_id=crm_id, **fields)

    def test_a_lead_ai_chat_mirrors_to_its_own_lead_and_never_searches_for_the_person(self):
        self.chat()
        records = tasks._mirror_records(self.conversation, strict=True)
        self.assertEqual(records, [{"type": "lead", "id": 73688, "kind": "lead"}, {"type": OWNER_DATA, "id": 7, "kind": "owner data"}])
        self.assertNotIn("crm.duplicate.findbycomm", self.bitrix.methods())
        self.assertNotIn("crm.lead.get", self.bitrix.methods())
        self.assertIn("crm.item.list", self.bitrix.methods())  # Owner Data as everywhere

    def test_every_message_of_the_chat_lands_on_that_lead(self):
        self.chat()
        customer = self.message()
        assistant = self.message("Type 1 is from AED 33,000 a year.", Message.Direction.OUTBOUND, payload={"source": "leadai_ai"})
        for message in (customer, assistant):
            self.assertIsNone(tasks.mirror_message.apply(args=[message.pk], throw=True).result)
        self.assertEqual(self.bitrix.posted_on(), [("lead", 73688), (OWNER_DATA, 7)] * 2)
        self.assertNotIn(("lead", 101), self.bitrix.posted_on())
        self.assertIn("Lead AI assistant", self.bitrix.comments[2][2])

    def test_a_chat_without_lead_ai_is_mirrored_exactly_as_before(self):
        records = tasks._mirror_records(self.conversation, strict=True)
        self.assertEqual(records, [{"type": "lead", "id": 101, "kind": "lead"}, {"type": OWNER_DATA, "id": 7, "kind": "owner data"}])
        self.assertEqual(self.bitrix.methods()[:2], ["crm.duplicate.findbycomm", "crm.lead.get"])
        # A campaign that is not a Lead AI one names nothing either.
        self.sent(self.campaign(), timezone.now(), crm_lead_id=999)
        self.assertIsNone(tasks._own_record(self.conversation))

    def test_a_contact_or_a_deal_of_its_own_counts_too(self):
        chat = self.chat("contact", 3030)
        self.assertEqual(tasks._mirror_records(self.conversation)[0], {"type": "contact", "id": 3030, "kind": "contact"})
        LeadAiChat.objects.filter(pk=chat.pk).update(crm_entity="deal", crm_id=900)
        self.assertEqual(tasks._mirror_records(self.conversation)[0], {"type": "deal", "id": 900, "kind": "deal"})
        self.assertNotIn("crm.duplicate.findbycomm", self.bitrix.methods())

    def test_owner_data_or_no_record_of_its_own_finds_the_person_by_phone_as_before(self):
        chat = self.chat("owner_data", 5)
        self.assertEqual(tasks._mirror_records(self.conversation)[0]["id"], 101)
        LeadAiChat.objects.filter(pk=chat.pk).update(crm_entity="lead", crm_id=None)
        self.assertEqual(tasks._mirror_records(self.conversation)[0]["id"], 101)
        LeadAiChat.objects.filter(pk=chat.pk).update(crm_entity="", crm_id=None)
        self.assertEqual(tasks._mirror_records(self.conversation)[0]["id"], 101)

    def test_a_chat_moved_to_the_inbox_keeps_its_lead(self):
        self.chat(active=False)
        self.assertEqual(tasks._mirror_records(self.conversation)[0], {"type": "lead", "id": 73688, "kind": "lead"})

    def test_its_own_renewals_deal_keeps_the_tenant_label_and_is_posted_once(self):
        self.chat("deal", 900)
        renewal = [{"type": "deal", "id": 900, "kind": "deal", "role": "tenant"}, {"type": "deal", "id": 901, "kind": "deal", "role": "owner"}]
        with patch.object(tasks, "_renewal_deals", return_value=renewal):
            records = tasks._mirror_records(self.conversation)
            self.assertEqual([(r["type"], r["id"], r.get("role")) for r in records], [("deal", 900, "tenant"), (OWNER_DATA, 7, None), ("deal", 901, "owner")])
            message = self.message()
            tasks.mirror_message.apply(args=[message.pk], throw=True)
        lines = {(entity, pk): text for entity, pk, text in self.bitrix.comments}
        self.assertTrue(lines[("deal", 900)].startswith("WhatsApp · Tenant · Customer"))
        self.assertTrue(lines[("deal", 901)].startswith("WhatsApp · Owner · Customer"))
        self.assertEqual(len(self.bitrix.comments), 3)

    def test_a_newer_lead_ai_campaign_from_another_lead_takes_the_chat_from_its_send_on(self):
        # Board T57 review F3, the story of apps/leadai's
        # test_a_shops_campaign_from_another_lead_writes_to_that_lead: the chat came from lead 555;
        # a shops campaign from lead 777 reached it while it was active, and LeadAiChat still says 555.
        now = timezone.now()
        chat = self.chat(crm_id=555)
        self.sent(self.campaign(lead_ai=True), now - dt.timedelta(hours=3), crm_lead_id=555)
        before = self.message("Hello", created_at=now - dt.timedelta(hours=2))
        self.sent(self.campaign(lead_ai=True, name="CRM Leads · Lead AI · shops"), now - dt.timedelta(hours=1), crm_lead_id=777)
        after = self.message("Type 1 please", created_at=now - dt.timedelta(minutes=30))
        chat.refresh_from_db()
        self.assertEqual(chat.crm_id, 555)
        self.assertEqual(tasks._own_record(self.conversation, at=before.created_at)["id"], 555)
        self.assertEqual(tasks._own_record(self.conversation, at=after.created_at)["id"], 777)
        # Now: the lead the Lead AI writes its fields to.
        self.assertEqual(tasks._own_record(self.conversation)["id"], crm_fields.lead_of(chat, self.conversation))
        for message in (before, after):
            tasks.mirror_message.apply(args=[message.pk], throw=True)
        self.assertEqual(self.mirrored(before), {("lead", 555), (OWNER_DATA, 7)})
        self.assertEqual(self.mirrored(after), {("lead", 777), (OWNER_DATA, 7)})

    def test_a_deal_campaign_names_its_deal_and_one_with_neither_keeps_the_chat_s_record(self):
        now = timezone.now()
        self.chat(crm_id=555)
        self.sent(self.campaign(lead_ai=True), now - dt.timedelta(hours=2), crm_deal_id=900)
        self.assertEqual(tasks._own_record(self.conversation), {"type": "deal", "id": 900, "kind": "deal"})
        self.sent(self.campaign(lead_ai=True), now - dt.timedelta(hours=1))  # an Owner Data popup send
        self.assertEqual(tasks._own_record(self.conversation), {"type": "lead", "id": 555, "kind": "lead"})


# refresh_summary
# ---------------------------------------------------------------------------


SUMMARY = {"summary": "Wants a shop", "client_score": 70, "client_reason": "keen", "agent_score": 80, "agent_reason": "fast"}


class SummaryRetryTests(MirrorBase):
    def setUp(self):
        super().setUp()
        for name, kwargs in (("configured", {"return_value": True}), ("summarise", {"return_value": SUMMARY})):
            patcher = patch.object(tasks.ai, name, **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.message()

    def run_once(self, retries=0, **kwargs):
        with patch.object(tasks.refresh_summary, "retry", side_effect=Retry("again")) as retry:
            result = tasks.refresh_summary.apply(args=[self.conversation.pk], kwargs=kwargs, retries=retries)
        if retry.called:
            self.assertIsInstance(result.result, Retry)
        else:
            self.assertEqual(result.state, "SUCCESS", result.result)
        return retry

    def test_a_passing_lookup_failure_is_tried_again_before_any_model_call(self):
        self.bitrix.fail = {"crm.item.list": [passing()]}
        retry = self.run_once()
        self.assertTrue(60 <= retry.call_args.kwargs["countdown"] <= 72)
        self.assertEqual(retry.call_args.kwargs["kwargs"], {"only": None, "deferred": 0})
        self.summarise.assert_not_called()
        self.assertEqual(tasks.refresh_summary.max_retries, 3 + tasks.MAX_DEFERRALS)

    def test_a_record_that_did_not_take_it_is_the_only_one_tried_again(self):
        self.bitrix.fail = {("crm.timeline.comment.add", OWNER_DATA): [passing()]}
        retry = self.run_once()
        only = retry.call_args.kwargs["kwargs"]["only"]
        self.assertEqual(only, [[OWNER_DATA, 7]])
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101)])
        self.run_once(retries=1, only=only).assert_not_called()
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101), (OWNER_DATA, 7)])
        self.assertEqual(self.bitrix.methods().count("crm.lead.update"), 1)  # the lead's fields once

    def test_a_retry_after_a_failed_comment_writes_no_field_twice(self):
        # Board T57 review F7: one more crm.lead.update is one more run of BP 235.
        self.bitrix.fail = {("crm.timeline.comment.add", "lead"): [passing()]}
        retry = self.run_once()
        only = retry.call_args.kwargs["kwargs"]["only"]
        self.assertEqual(only, [["lead", 101, "comment"]])
        self.run_once(retries=1, only=only).assert_not_called()
        self.assertEqual(self.bitrix.methods().count("crm.lead.update"), 1)
        self.assertEqual(self.bitrix.posted_on(), [(OWNER_DATA, 7), ("lead", 101)])

    def test_fields_that_did_not_take_are_written_again_alone(self):
        self.bitrix.fail = {"crm.lead.update": [passing()]}
        retry = self.run_once()
        only = retry.call_args.kwargs["kwargs"]["only"]
        self.assertEqual(only, [["lead", 101, "fields"]])
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101), (OWNER_DATA, 7)])
        self.run_once(retries=1, only=only).assert_not_called()
        self.assertEqual(self.bitrix.methods().count("crm.lead.update"), 2)
        self.assertEqual(len(self.bitrix.comments), 2)  # no comment twice

    def test_a_write_whose_answer_was_lost_counts_as_done(self):
        self.bitrix.fail = {"crm.lead.update": [lost("crm.lead.update: timed out (ReadTimeout)")], ("crm.timeline.comment.add", OWNER_DATA): [Landed(lost())]}
        with self.assertLogs("apps.crmlink.tasks", level="INFO") as logs:
            self.run_once().assert_not_called()
        self.assertTrue(any("may have been written" in line for line in logs.output))
        self.assertTrue(any("may have been posted" in line for line in logs.output))
        self.assertEqual(self.bitrix.methods().count("crm.lead.update"), 1)
        self.assertEqual(sorted(self.bitrix.posted_on()), sorted([("lead", 101), (OWNER_DATA, 7)]))

    def test_a_chat_moved_to_the_inbox_still_gets_the_summary_as_a_comment_only(self):
        # Board T57 review F6: it still mirrors to its campaign lead, which the assistant may have
        # booked; a REST update there would run BP 235 (meeting time cleared, a due-now to-do).
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=73688, active=False)
        self.run_once().assert_not_called()
        self.assertNotIn("crm.lead.update", self.bitrix.methods())
        self.assertEqual(self.bitrix.posted_on(), [("lead", 73688), (OWNER_DATA, 7)])

    def test_every_background_slot_taken_sends_it_back_soon(self):
        self.redis.locks.update({f"{tasks.BACKGROUND_SLOTS}:0", f"{tasks.BACKGROUND_SLOTS}:1"})
        retry = self.run_once()
        self.assertEqual(retry.call_args.kwargs["kwargs"], {"only": None, "deferred": 1})
        self.assertTrue(15 <= retry.call_args.kwargs["countdown"] <= 75)
        self.summarise.assert_not_called()
        self.assertEqual(self.bitrix.calls, [])

    def test_after_the_last_try_one_warning(self):
        self.bitrix.fail = {("crm.timeline.comment.add", OWNER_DATA): [passing()]}
        with self.assertLogs("apps.crmlink.tasks", level="WARNING") as logs:
            self.run_once(retries=3).assert_not_called()
        self.assertIn(f"Gave up on the summary of conversation {self.conversation.pk} for {OWNER_DATA} 7 after 4 tries", logs.output[0])


# 6. The back-fill
# ---------------------------------------------------------------------------

SINCE = dt.datetime(2026, 10, 14, 7, 40, tzinfo=dt.timezone.utc)


@override_settings(BITRIX_WEBHOOK_URL=WEBHOOK)
class BackfillTests(MirrorBase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(tasks.mirror_message, "apply_async")
        self.queued = patcher.start()
        self.addCleanup(patcher.stop)
        self.now = timezone.now()
        hour = dt.timedelta(hours=1)
        self.after = max(SINCE + hour, self.now - hour)
        self.before = SINCE - hour

    def at(self, moment, *args, **fields):
        return self.message(*args, created_at=moment, **fields)

    def run_backfill(self, *args, dry_run=False):
        out = io.StringIO()
        call_command("crmlink_backfill_mirrors", *args, *(["--dry-run"] if dry_run else []), stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def queued_ids(self):
        return [call.kwargs["args"][0] for call in self.queued.call_args_list]

    def other_chat(self, wa_id="971559999999", **chat):
        contact = Contact.objects.create(wa_id=wa_id, display_name="Sara Secret")
        conversation = Conversation.objects.create(number=self.number, contact=contact)
        if chat:
            LeadAiChat.objects.create(conversation=conversation, **chat)
        return conversation

    def campaign_template(self, moment, conversation=None):
        """A template one of our campaigns sent at ``moment`` (it posted its own copy)."""
        chat = conversation or self.conversation
        self.sent(self.campaign(), moment - dt.timedelta(seconds=15), conversation=chat, phone=chat.contact.wa_id)
        return self.at(moment, "Hello from A7", Message.Direction.OUTBOUND, Message.Kind.TEMPLATE, template=self.template, conversation=chat)

    def test_since_picks_every_message_since_then_and_leaves_out_the_rest(self):
        mirrored = self.at(self.after)
        Mirror.objects.create(message=mirrored, entity_type="lead", entity_id=101)
        partly = self.at(self.after)  # the lead search met a 429 and only the card got it
        Mirror.objects.create(message=partly, entity_type=OWNER_DATA, entity_id=7)
        original = self.at(self.after, "the original")
        picked = [
            self.at(self.after),
            self.at(self.after, "Sure, which size?", Message.Direction.OUTBOUND),
            self.at(self.after, "", kind=Message.Kind.IMAGE),
            mirrored,
            partly,
            original,
            # The Lead AI's own reminder, and a template an agent sent from the panel: nothing
            # else posts a copy of either.
            self.at(self.after, "Reminder", Message.Direction.OUTBOUND, Message.Kind.TEMPLATE, template=self.template, payload={"source": "leadai_reminder"}),
            self.at(self.after, "Hello again", Message.Direction.OUTBOUND, Message.Kind.TEMPLATE, template=self.template),
        ]
        left_out = [
            self.campaign_template(self.after, conversation=self.other_chat("971557777777")),
            self.at(self.after, "👍", kind=Message.Kind.REACTION),
            self.at(self.after, "Chat transferred", Message.Direction.OUTBOUND, Message.Kind.SYSTEM),
            self.at(self.after, "Sent from WhatsApp", Message.Direction.OUTBOUND, Message.Kind.UNKNOWN),
            self.at(self.after, "the original", mirrored_from=original),
            self.at(self.after, "never sent", Message.Direction.OUTBOUND, status=Message.Status.FAILED),
            self.at(self.now - dt.timedelta(minutes=2)),
            self.at(self.before),
        ]
        ids = set(backfill.candidates(since=SINCE).values_list("pk", flat=True))
        self.assertEqual(ids, {m.pk for m in picked})
        self.assertFalse(ids & {m.pk for m in left_out})

    def test_a_partly_mirrored_message_reaches_the_record_it_missed(self):
        # Board T57 review F4: what the task makes of a back-filled message that one record has.
        message = self.at(self.after)
        Mirror.objects.create(message=message, entity_type=OWNER_DATA, entity_id=7, comment_id=8000)
        self.assertIn(message.pk, set(backfill.candidates(since=SINCE).values_list("pk", flat=True)))
        self.run_once(message, summary_check=False, look_first=True).assert_not_called()
        self.assertEqual(self.bitrix.posted_on(), [("lead", 101)])

    def test_leadai_picks_every_message_not_on_the_chat_s_own_lead_of_any_date(self):
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=73688)
        on_another_lead = self.at(self.before)
        Mirror.objects.create(message=on_another_lead, entity_type="lead", entity_id=101)
        on_its_lead = self.at(self.before)
        Mirror.objects.create(message=on_its_lead, entity_type="lead", entity_id=73688)
        never = self.at(self.before - dt.timedelta(days=30), "old", Message.Direction.OUTBOUND)
        template = self.campaign_template(self.before)
        # An Owner Data chat has no lead of its own: no mirror at all is what counts there.
        card_chat = self.other_chat(crm_entity="owner_data", crm_id=5)
        card_none = self.at(self.before, conversation=card_chat)
        card_some = self.at(self.before, conversation=card_chat)
        Mirror.objects.create(message=card_some, entity_type=OWNER_DATA, entity_id=5)
        # Not a Lead AI chat: --leadai alone leaves it alone.
        plain = self.at(self.before, conversation=self.other_chat("971558888888"))
        ids = set(backfill.candidates(leadai=True).values_list("pk", flat=True))
        self.assertEqual(ids, {on_another_lead.pk, never.pk, card_none.pk})
        self.assertFalse(ids & {on_its_lead.pk, template.pk, card_some.pk, plain.pk})

    def test_leadai_follows_the_newest_lead_ai_campaign_as_the_mirror_does(self):
        # Board T57 review F3: the back-fill's SQL and the mirror name the same record for every
        # message: before the shops campaign, lead 555; after it, lead 777.
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=555)
        self.sent(self.campaign(lead_ai=True), self.before - dt.timedelta(hours=3), crm_lead_id=555)
        early = self.at(self.before - dt.timedelta(hours=2))
        Mirror.objects.create(message=early, entity_type="lead", entity_id=555)
        self.sent(self.campaign(lead_ai=True), self.before - dt.timedelta(hours=1), crm_lead_id=777)
        late = self.at(self.before)
        Mirror.objects.create(message=late, entity_type="lead", entity_id=555)  # mirrored before T57
        deal_chat = self.other_chat(crm_entity="", crm_id=None)
        self.sent(self.campaign(lead_ai=True), self.before - dt.timedelta(hours=1), conversation=deal_chat, phone="971559999999", crm_deal_id=900)
        on_deal = self.at(self.before, conversation=deal_chat)
        history = self.at(self.before - dt.timedelta(days=9), conversation=deal_chat)  # from before the campaign
        plain = self.at(self.before, conversation=self.other_chat("971558888888"))
        self.assertEqual(set(backfill.candidates(leadai=True).values_list("pk", flat=True)), {late.pk, on_deal.pk, history.pk})
        first, second = tasks.own_record_annotations()
        rows = Message.objects.annotate(**first).annotate(**second).values_list("pk", "own_type", "own_id")
        for pk, own_type, own_id in rows:
            message = Message.objects.select_related("conversation").get(pk=pk)
            own = tasks._own_record(message.conversation, at=message.created_at)
            with self.subTest(message=pk):
                self.assertEqual((own_type, own_id), (own["type"], own["id"]) if own else (None, None))
        self.assertEqual(tasks._own_record(self.conversation, at=late.created_at)["id"], 777)
        self.assertIsNone(tasks._own_record(plain.conversation, at=plain.created_at))

    def test_both_pick_either_and_neither_is_refused(self):
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=73688)
        old = self.at(self.before)
        new = self.at(self.after, conversation=self.other_chat())
        both = set(backfill.candidates(since=SINCE, leadai=True).values_list("pk", flat=True))
        self.assertEqual(both, {old.pk, new.pk})
        with self.assertRaises(CommandError):
            self.run_backfill()
        with self.assertRaises(CommandError):
            self.run_backfill(dry_run=True)

    def test_a_dry_run_queues_nothing_and_prints_counts_only(self):
        self.at(self.after)
        self.at(self.after, "Sure, which size?", Message.Direction.OUTBOUND)
        self.at(self.after, "", kind=Message.Kind.AUDIO)
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", dry_run=True)
        self.queued.assert_not_called()
        self.assertIn("Matching messages: 3. This run: 3", text)
        self.assertIn("direction: in 2, out 1", text)
        self.assertIn("kind: text 2, audio 1", text)
        self.assertIn(f"created_at: first {self.after:%Y-%m-%dT%H:%M:%S}Z", text.replace("+00:00", "Z"))
        self.assertIn("Dry run: nothing was queued.", text)
        self.assertNotIn("more match", text)
        for secret in (self.BODY, "which size", WA_ID, "Ahmed", "Khan"):
            self.assertNotIn(secret, text)
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", "--limit", "2", dry_run=True)
        self.assertIn("1 more match beyond this run.", text)
        self.queued.assert_not_called()

    def test_tasks_are_spaced_by_every_oldest_first_never_ask_for_a_summary_and_look_first(self):
        first = self.at(self.after - dt.timedelta(minutes=3))
        second = self.at(self.after - dt.timedelta(minutes=2))
        elsewhere = self.at(self.after - dt.timedelta(minutes=9), conversation=self.other_chat())
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", "--every", "5")
        # Oldest first, so every timeline reads in the order its conversation happened.
        self.assertEqual(self.queued_ids(), [elsewhere.pk, first.pk, second.pk])
        self.assertEqual([call.kwargs["countdown"] for call in self.queued.call_args_list], [0, 5, 10])
        for call in self.queued.call_args_list:
            self.assertEqual(call.kwargs["kwargs"], {"summary_check": False, "look_first": True})
        self.assertIn("Queued 3 mirror tasks; the last runs in 10 s.", text)
        self.assertNotIn("more match", text)

    def test_the_default_spacing_is_eight_seconds(self):
        # Board T57 review S2: an unanswered lookup costs six to eight REST calls.
        for minute in range(3):
            self.at(self.after - dt.timedelta(minutes=minute))
        self.run_backfill("--since", "2026-10-14T07:40:00Z")
        self.assertEqual([call.kwargs["countdown"] for call in self.queued.call_args_list], [0, 8, 16])

    def test_the_limit_and_the_45_minute_horizon_cap_one_run(self):
        for minute in range(6):
            self.at(self.after - dt.timedelta(minutes=minute))
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", "--limit", "4")
        self.assertEqual(self.queued.call_count, 4)
        resume = backfill._utc(self.after - dt.timedelta(minutes=2))
        self.assertIn(f"2 more match. Once these have run, go on from where this run stopped: --since {resume}", text)
        self.queued.reset_mock()
        with patch.object(backfill, "HORIZON_SECONDS", 120):
            text = self.run_backfill("--since", "2026-10-14T07:40:00Z", "--every", "60")
        self.assertEqual([call.kwargs["countdown"] for call in self.queued.call_args_list], [0, 60, 120])
        self.assertIn("3 more match", text)
        self.assertEqual(backfill.HORIZON_SECONDS // backfill.EVERY_DEFAULT + 1, 338)  # the defaults: 338 a run, 45 minutes
        self.assertLess(backfill.HORIZON_SECONDS, 3600)

    def test_the_next_run_goes_on_past_what_this_one_took(self):
        # Every one of these keeps matching --since (none of them ever stops: the task posts only
        # what is missing). A run that started from the beginning again would pick the same four.
        messages = [self.at(self.after - dt.timedelta(minutes=minute)) for minute in range(6, 0, -1)]
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", "--limit", "4")
        first = self.queued_ids()
        self.assertEqual(first, [m.pk for m in messages[:4]])
        flags = text.rsplit("go on from where this run stopped: ", 1)[1].split()
        self.queued.reset_mock()
        self.run_backfill(*flags)
        second = self.queued_ids()
        # Only the last one of the first run can come again (the hint is to the second).
        self.assertEqual(second[-2:], [m.pk for m in messages[4:]])
        self.assertLessEqual(set(second) - {m.pk for m in messages[4:]}, {messages[3].pk})

    def test_the_hint_never_reaches_back_before_the_since_asked_for(self):
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=73688)
        for days in (5, 4, 3):
            self.at(SINCE - dt.timedelta(days=days))  # Lead AI history, long before --since
        self.at(self.after, conversation=self.other_chat())
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", "--leadai", "--limit", "2")
        self.assertIn("go on from where this run stopped: --since 2026-10-14T07:40:00Z --leadai", text)

    def test_leadai_alone_says_to_run_it_again(self):
        LeadAiChat.objects.create(conversation=self.conversation, crm_entity="lead", crm_id=73688)
        for days in (3, 2, 1):
            self.at(SINCE - dt.timedelta(days=days))
        text = self.run_backfill("--leadai", "--limit", "2")
        self.assertIn("1 more match: run this again once these have run.", text)

    def test_refused_while_a_campaign_is_sending(self):
        # Board T57 review S1 / S2: its lookups and comments need the Bitrix budget.
        self.at(self.after)
        campaign = self.campaign(status=Campaign.Status.RUNNING)
        self.sent(campaign, None, status=CampaignRecipient.Status.PENDING, phone="971550000001", conversation=None)
        with self.assertRaises(CommandError) as caught:
            self.run_backfill("--since", "2026-10-14T07:40:00Z")
        self.assertIn(f"Campaign {campaign.pk} is sending now", str(caught.exception))
        self.queued.assert_not_called()
        text = self.run_backfill("--since", "2026-10-14T07:40:00Z", dry_run=True)
        self.assertIn("Matching messages: 1.", text)
        self.assertIn(f"Campaign {campaign.pk} is sending now: a real run would be refused", text)
        # Stuck in RUNNING with nobody waiting and nothing tried for hours: not sending.
        CampaignRecipient.objects.filter(campaign=campaign).update(
            status=CampaignRecipient.Status.SENT, last_attempt_at=self.now - dt.timedelta(hours=3)
        )
        self.run_backfill("--since", "2026-10-14T07:40:00Z")
        self.assertEqual(self.queued.call_count, 1)
        # One between two retry waves is.
        Campaign.objects.filter(pk=campaign.pk).update(status=Campaign.Status.RETRYING)
        CampaignRecipient.objects.filter(campaign=campaign).update(last_attempt_at=self.now - dt.timedelta(minutes=4))
        self.assertEqual(backfill.sending_campaigns(), [campaign.pk])

    def test_values_out_of_range_are_refused(self):
        for args in (
            ("--leadai", "--every", "0"),
            ("--leadai", "--every", "61"),
            ("--leadai", "--limit", "0"),
            ("--leadai", "--limit", "20001"),
            ("--since", "yesterday"),
        ):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.run_backfill(*args)
        self.queued.assert_not_called()

    def test_since_is_read_as_utc(self):
        self.assertEqual(backfill.parse_since("2026-10-14T07:40:00Z"), SINCE)
        self.assertEqual(backfill.parse_since("2026-10-14T07:40:00"), SINCE)
        self.assertEqual(backfill.parse_since("2026-10-14T11:40:00+04:00"), SINCE)

    def test_a_broker_failure_stops_the_run_and_says_how_far_it_got(self):
        for minute in range(3):
            self.at(self.after - dt.timedelta(minutes=minute))
        self.queued.side_effect = [None, OSError("redis://:password@redis:6379 refused")]
        err = io.StringIO()
        out = io.StringIO()
        call_command("crmlink_backfill_mirrors", "--since", "2026-10-14T07:40:00Z", stdout=out, stderr=err)
        self.assertIn("The broker refused a task (OSError); 1 were queued.", err.getvalue())
        self.assertNotIn("password", err.getvalue())
        self.assertIn("Queued 1 mirror tasks", out.getvalue())


# 7. The panel's lookups
# ---------------------------------------------------------------------------


class PanelLookupTests(MirrorBase):
    """Board T57 review F5: a lookup that met a passing failure is "busy", never "not in the CRM"."""

    def setUp(self):
        super().setUp()
        self.admin = Agent.objects.create_user(username="admin", password="x", bitrix_user_id="1", is_wa_admin=True)
        self.client.force_login(self.admin)

    def test_whereis_says_busy_rather_than_not_in_the_crm(self):
        self.bitrix.fail = {("crm.duplicate.findbycomm", "LEAD"): [passing()]}
        response = self.client.get("/api/crm/whereis/", {"phone": WA_ID})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Bitrix is busy. Try again in a minute.")
        response = self.client.get("/api/crm/whereis/", {"phone": WA_ID})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([(r["type"], r["id"]) for r in response.json()["records"]], [("lead", 101), (OWNER_DATA, 7)])

    def test_create_makes_no_second_lead_while_bitrix_is_busy(self):
        self.bitrix.owner_data = []  # the customer's only record is lead 101
        self.bitrix.fail = {("crm.duplicate.findbycomm", "LEAD"): [passing()]}
        response = self.client.post("/api/crm/create/", {"conversation": self.conversation.pk, "where": "lead"}, content_type="application/json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Bitrix is busy. Try again in a minute.")
        self.assertNotIn("crm.lead.add", self.bitrix.methods())
        # Once Bitrix answers, the lead it has is found and nothing is made.
        response = self.client.post("/api/crm/create/", {"conversation": self.conversation.pk, "where": "lead"}, content_type="application/json")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("crm.lead.add", self.bitrix.methods())

    def test_create_records_only_the_comments_that_came_back_with_an_id(self):
        self.bitrix.leads, self.bitrix.owner_data = [], []
        kept, dropped = self.message("one"), self.message("two")
        self.bitrix.fail = {"crm.timeline.comment.add": [None, NO_ID]}
        response = self.client.post("/api/crm/create/", {"conversation": self.conversation.pk, "where": "lead"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["messages_copied"], response.json()["messages_failed"]), (1, 1))
        self.assertEqual(self.mirrored(kept), {("lead", 555)})
        self.assertEqual(self.mirrored(dropped), set())
