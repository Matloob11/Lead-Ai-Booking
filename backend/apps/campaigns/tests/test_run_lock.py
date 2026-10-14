"""C35: overlapping run_campaign deliveries send each row once."""

from unittest.mock import call, patch

from django.test import SimpleTestCase

from apps.campaigns import run_lock
from apps.campaigns.tasks import run_campaign


class RunLockUnitTests(SimpleTestCase):
    def setUp(self):
        run_lock._QUIET_UNTIL = 0.0

    @patch("apps.campaigns.run_lock._conn")
    def test_second_acquire_is_refused(self, conn):
        store = {}

        class FakeRedis:
            def set(self, key, value, nx=False, ex=None):
                if nx and key in store:
                    return False
                store[key] = value
                return True

            def expire(self, key, ttl):
                return True

            def delete(self, key):
                store.pop(key, None)
                return 1

        conn.return_value = FakeRedis()
        self.assertTrue(run_lock.acquire(7))
        self.assertFalse(run_lock.acquire(7))
        run_lock.release(7)
        self.assertTrue(run_lock.acquire(7))

    @patch("apps.campaigns.tasks._run_campaign_locked")
    @patch("apps.campaigns.run_lock.release")
    @patch("apps.campaigns.run_lock.acquire")
    def test_overlapping_deliveries_process_the_body_once(self, acquire, release, locked):
        """Two deliveries of the same campaign: only the first runs the send loop."""
        acquire.side_effect = [True, False]
        run_campaign(42)
        run_campaign(42)
        locked.assert_called_once_with(42)
        release.assert_called_once_with(42)
        self.assertEqual(acquire.call_args_list, [call(42), call(42)])
