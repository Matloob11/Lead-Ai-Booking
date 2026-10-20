"""One turn at a time per chat (assistant/turn_lock.py; the first mixed campaign's issue I02): the lease through the
shared Redis lock, and run_turn waiting behind it."""

from contextlib import contextmanager
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.crmlink import redis_state
from apps.leadai.assistant import engine, turn_lock
from apps.leadai.models import LeadAiTurn
from apps.leadai.tests.test_assistant import Base, answer


class FakeLock:
    def __init__(self, store, name, token):
        self.store, self.name, self.token = store, name, token

    def acquire(self, blocking=False):
        if self.name in self.store:
            return False
        self.store[self.name] = self.token
        return True

    def release(self):
        if self.store.get(self.name) != self.token:
            raise RuntimeError("not owned")
        del self.store[self.name]


class FakeConnection:
    """conn.lock(name, timeout, blocking): one holder per name, released only by its holder (as redis-py's Lock)."""

    def __init__(self):
        self.store = {}
        self.made = 0

    def lock(self, name, timeout=None, blocking=False):
        self.made += 1
        return FakeLock(self.store, name, f"token{self.made}")


class LeaseTests(SimpleTestCase):
    def setUp(self):
        self.conn = FakeConnection()
        patcher = patch.object(redis_state, "_connection", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_holder_at_a_time_and_the_exit_frees_it(self):
        with turn_lock.leased(55) as first:
            self.assertTrue(first)
            self.assertEqual(set(self.conn.store), {"leadai:turn:55"})
            with turn_lock.leased(55) as second:
                self.assertFalse(second)
            with turn_lock.leased(56) as other:
                self.assertTrue(other)  # another chat is another key
        self.assertEqual(self.conn.store, {})
        with turn_lock.leased(55) as again:
            self.assertTrue(again)

    def test_a_late_finisher_never_drops_a_newer_lease(self):
        with turn_lock.leased(55) as first:
            self.assertTrue(first)
            self.conn.store.clear()  # the lease expired: the holder outlived LEASE_SECONDS
            with turn_lock.leased(55) as second:
                self.assertTrue(second)
                # the old holder's exit comes with the new lease in place: its release is refused and swallowed
        self.assertEqual(self.conn.store, {})

    def test_redis_out_means_no_lease_and_the_turn_runs(self):
        with patch.object(redis_state, "_connection", return_value=None):
            with turn_lock.leased(55) as mine:
                self.assertIsNone(mine)


@contextmanager
def lease_answering(value):
    yield value


class RunTurnWaitsTests(Base):
    def test_a_second_turn_of_the_chat_waits_and_claims_nothing(self):
        message = self.inbound("Yes I need a shop")
        with patch.object(turn_lock, "leased", side_effect=lambda cid: lease_answering(False)):
            with self.assertRaises(engine.NotReady) as raised:
                engine.run_turn(message.pk)
        self.assertEqual((raised.exception.countdown, raised.exception.reason), (turn_lock.RETRY_IN, turn_lock.WAITING))
        self.assertFalse(LeadAiTurn.objects.filter(inbound=message).exists())

    def test_a_turn_runs_inside_its_lease(self):
        message = self.inbound("Yes I need a shop")
        seen = []

        @contextmanager
        def leased(cid):
            seen.append(cid)
            yield True

        with patch.object(turn_lock, "leased", side_effect=leased):
            self.turn(message, [answer("Great. What business will the shop be for?")])
        self.assertEqual(seen, [self.conversation.pk])
        self.assertNotIn(LeadAiTurn.objects.get(inbound=message).status, (LeadAiTurn.Status.SKIPPED, LeadAiTurn.Status.FAILED))

    def test_without_redis_the_turn_runs_as_before(self):
        message = self.inbound("Yes I need a shop")
        with patch.object(turn_lock, "leased", side_effect=lambda cid: lease_answering(None)):
            self.turn(message, [answer("Great. What business will the shop be for?")])
        self.assertNotIn(LeadAiTurn.objects.get(inbound=message).status, (LeadAiTurn.Status.SKIPPED, LeadAiTurn.Status.FAILED))
