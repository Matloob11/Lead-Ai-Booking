"""One turn at a time per chat (the first mixed campaign, 2026-10-19, issue I02).

Two messages from one customer seconds apart are two queued turns. Each one checks for a newer inbound before it
runs, but the first may already be inside its OpenAI call when the second arrives: both answer, and the customer
gets two replies, two slot pairs ("3:00 PM or 4:00 PM" and then "3:00 PM or 5:00 PM" in chat 49818). With
worker-leadai at concurrency 6 that window is wide open.

A turn now holds a lease on its chat for as long as it may run: the Bitrix client's shared Redis lock
(apps.crmlink.redis_state.held — redis-py's token lock, so a late finisher never drops a newer lease, fail-open when
Redis is out, quiet for a few seconds after an error). A second turn of the same chat waits RETRY_IN seconds and comes
back (engine.NotReady), and when it runs the first reply is in the chat already: the burst is only what came after it,
and the usual skips ("a newer message will be answered", "answered since") apply. Redis down means no lease and the
turn runs as before: a duplicate reply is better than no reply, and the breaker and alerts still watch the turn.
"""

from __future__ import annotations

from contextlib import contextmanager

from apps.crmlink import redis_state

KEY = "leadai:turn:{conversation_id}"
# A turn's own deadline is engine.TURN_BUDGET (140 s) and the task's soft limit 180 s: a lease that outlives both is
# a dead holder's, and the next turn takes it.
LEASE_SECONDS = 200
# How long a second turn of the same chat waits before it looks again.
RETRY_IN = 5
WAITING = "another turn of this chat is running"


@contextmanager
def leased(conversation_id: int):
    """Yields True while this turn holds the chat's lease, False when another turn holds it, None with no Redis."""
    with redis_state.held(KEY.format(conversation_id=int(conversation_id)), seconds=LEASE_SECONDS) as mine:
        yield mine
