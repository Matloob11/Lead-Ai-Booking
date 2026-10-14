"""What the Bitrix client shares between processes, through Redis.

Every Bitrix REST call Django makes (the CRM mirror, Lead AI, campaigns, the lead bot) leaves
from one address, and the Bitrix nginx allows that address 2 requests a second with a burst of
20, answering 429 with an HTML page past that (ops/bitrix-aws/live/nginx/
a7_rate_limit_zadarma_voiso.conf and a7_rest_limit_zadarma_voiso.conf). web, worker,
worker-leadai and beat are separate containers, and the workers fork children, so the count
has to live outside every one of them: in Redis (settings.REDIS_URL), which Celery and channels
already use.

What is kept there:

- the request slots (``bitrix_slot``): a GCRA token bucket a little under the nginx limit
  (BITRIX_REST_RATE, default 1.8 a second, with a burst of BITRIX_REST_BURST, 12), one Lua call
  per request. Background work (the CRM mirror and its summaries, client.background) asks with
  low priority: a slot that is free now or none, and only while the bucket keeps
  BITRIX_REST_BACKGROUND_RESERVE (6) slots for everybody else, so it never sleeps in a worker
  and never slows a campaign;
- a short cache of record lookups by phone (``cache_get`` / ``cache_set`` / ``cache_forget``);
- a per-message lock (``held``), so two runs of the same mirror never post at the same moment,
  and a few shared background slots (``held_one_of``), so background work never holds more
  than BITRIX_BACKGROUND_PARALLEL (2) of the worker's children, whatever Bitrix is doing;
- "Bitrix is down" (``bitrix_down``): set for BITRIX_DOWN_SECONDS (60) after a timeout, a
  network error or a 502/503/504, so background work stops asking for that long instead of
  holding a worker child through one more timeout.

Each fails open. With Redis unreachable there is no limit, no cache, no lock and no "down",
which is how everything behaved before this module existed, and the process says so in one
warning a minute at most, never one per call. After an error it leaves Redis alone for a few
seconds, so a dead Redis costs one short timeout now and then rather than one on every Bitrix
call.

The settings are read with getattr and defaults; none of them is in a7wa/settings.py.
"""

import json
import logging
import os
import time
from contextlib import contextmanager

import redis
from django.conf import settings

logger = logging.getLogger(__name__)

SLOT_KEY = "crmlink:bitrix:rest:tat"
DOWN_KEY = "crmlink:bitrix:down"
# A Redis that does not answer in this long is treated as down: every Bitrix call waits on it.
TIMEOUT_SECONDS = 0.5
# After an error, how long this process leaves Redis alone (and so goes unlimited).
QUIET_SECONDS = 10
WARN_EVERY_SECONDS = 60

# GCRA, the token bucket written as one number: the key holds the theoretical arrival time (TAT,
# in ms) of the next request at the steady rate. A request may go at max(TAT, now) minus
# (burst - 1) intervals; when that is further away than the caller will wait, nothing is reserved
# and -1 comes back. Otherwise its slot is reserved (TAT moves one interval on) and the
# milliseconds to wait for it come back: 0 is "go now". Reserving rather than polling keeps the
# callers in order and costs one round trip. The key expires once the bucket is full again, which
# is the same state as no key at all. ARGV: now, interval, burst, max wait (ms or counts, whole
# numbers); the caller's clock rather than Redis TIME, so no Redis version question arises about
# writing after a non-deterministic command.
GCRA = """
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])
local max_wait = tonumber(ARGV[4])
local tat = tonumber(redis.call('GET', KEYS[1])) or now
if tat < now then
  tat = now
end
local wait = tat - now - (burst - 1) * interval
if wait < 0 then
  wait = 0
end
if wait > max_wait then
  return -1
end
tat = tat + interval
redis.call('SET', KEYS[1], tat, 'PX', tat - now + interval)
return wait
"""

_state = {"pid": None, "redis": None, "slot": None, "quiet_until": 0.0, "warned_at": None}


def rate():
    """Requests a second the shared bucket refills at; 0 or less turns the limit off."""
    return float(getattr(settings, "BITRIX_REST_RATE", 1.8))


def burst():
    return max(1, int(getattr(settings, "BITRIX_REST_BURST", 12)))


def max_wait():
    """Seconds a caller waits for its slot at most."""
    return max(0.0, float(getattr(settings, "BITRIX_REST_MAX_WAIT", 2.5)))


def background_reserve():
    """Slots of the burst background work leaves to everybody else: a campaign's lookups and its
    comments come in bursts of about six, and they must find them free."""
    return max(0, int(getattr(settings, "BITRIX_REST_BACKGROUND_RESERVE", 6)))


def down_seconds():
    """How long background work leaves Bitrix alone after a timeout or a network error."""
    return max(0.0, float(getattr(settings, "BITRIX_DOWN_SECONDS", 60)))


def background_parallel():
    """How many background tasks may talk to Bitrix at once (of the worker's four children)."""
    return max(1, int(getattr(settings, "BITRIX_BACKGROUND_PARALLEL", 2)))


def _now_ms():
    """Wall-clock milliseconds: the bucket is shared by processes, so it needs their common clock."""
    return int(time.time() * 1000)


def _clock():
    """This process's own clock, for its quiet spell and its warnings."""
    return time.monotonic()


def _connection():
    """This process's Redis client, or None while Redis is out.

    One per process id: a Celery prefork child must not share the parent's sockets, so a fork is
    noticed by its new pid and gets a client of its own.
    """
    if _clock() < _state["quiet_until"]:
        return None
    pid = os.getpid()
    if _state["redis"] is None or _state["pid"] != pid:
        url = str(getattr(settings, "REDIS_URL", "") or "")
        if not url:
            return None
        try:
            conn = redis.Redis.from_url(
                url, socket_timeout=TIMEOUT_SECONDS, socket_connect_timeout=TIMEOUT_SECONDS
            )
            slot = conn.register_script(GCRA)
        except Exception as exc:  # noqa: BLE001 - a bad URL is Redis being out, never a failed call
            _failed(exc)
            return None
        _state.update(pid=pid, redis=conn, slot=slot)
    return _state["redis"]


def _failed(exc):
    now = _clock()
    _state["quiet_until"] = now + QUIET_SECONDS
    last = _state["warned_at"]
    if last is None or now - last >= WARN_EVERY_SECONDS:
        _state["warned_at"] = now
        logger.warning(
            "Redis is not answering (%s: %s); Bitrix calls go on without the shared rate limit, "
            "the record cache, the mirror's locks and the Bitrix-down pause for now",
            type(exc).__name__,
            str(exc)[:200],
        )


def bitrix_slot(background=False):
    """Seconds to wait before this Bitrix request may go: 0.0 to go now, None when no slot comes
    free within ``max_wait()`` (nothing was reserved). Redis out, or the limit off: 0.0.

    ``background``: low priority. Only a slot that is free now (never a wait, so a worker child
    never sleeps here), and only while ``background_reserve()`` slots stay free after it: the
    same bucket asked with a smaller burst, so the Lua is the same for both.
    """
    per_second = rate()
    if per_second <= 0:
        return 0.0
    if _connection() is None:
        return 0.0
    interval = max(1, int(round(1000 / per_second)))
    if background:
        size, wait_limit = max(1, burst() - background_reserve()), 0
    else:
        size, wait_limit = burst(), int(max_wait() * 1000)
    try:
        wait_ms = int(_state["slot"](keys=[SLOT_KEY], args=[_now_ms(), interval, size, wait_limit]))
    except Exception as exc:  # noqa: BLE001 - the limit fails open, it never fails the call
        _failed(exc)
        return 0.0
    if wait_ms < 0:
        return None
    return wait_ms / 1000.0


# "Bitrix is down"
# ---------------------------------------------------------------------------


def bitrix_down():
    """Whether a Bitrix call (anybody's) timed out, could not connect or got a 502/503/504 in the
    last ``down_seconds()``. Redis out: False (background work goes on asking, as it did before
    this module)."""
    conn = _connection()
    if conn is None:
        return False
    try:
        return bool(conn.exists(DOWN_KEY))
    except Exception as exc:  # noqa: BLE001
        _failed(exc)
        return False


def mark_bitrix_down():
    seconds = down_seconds()
    if seconds <= 0:
        return
    conn = _connection()
    if conn is None:
        return
    try:
        conn.set(DOWN_KEY, "1", px=int(seconds * 1000))
    except Exception as exc:  # noqa: BLE001
        _failed(exc)


# The record cache
# ---------------------------------------------------------------------------


def cache_get(key, generation_key):
    """(the JSON value stored under ``key``, the generation under ``generation_key``), in one round
    trip. The value is None when missing or unreadable; the generation 0 when never moved on.
    Redis out: (None, None), and nothing is to be stored."""
    conn = _connection()
    if conn is None:
        return None, None
    try:
        raw, generation = conn.mget([key, generation_key])
    except Exception as exc:  # noqa: BLE001
        _failed(exc)
        return None, None
    try:
        generation = int(generation or 0)
    except (TypeError, ValueError):
        return None, None  # something else under the key: neither read nor store
    if raw is None:
        return None, generation
    try:
        return json.loads(raw), generation
    except (TypeError, ValueError):
        return None, generation


def cache_set(key, value, seconds):
    if seconds <= 0:
        return
    conn = _connection()
    if conn is None:
        return
    try:
        conn.set(key, json.dumps(value), ex=int(seconds))
    except Exception as exc:  # noqa: BLE001
        _failed(exc)


def cache_forget(generation_key, *keys, seconds):
    """Moves the generation on and drops ``keys``, in one round trip.

    A lookup that began before this and stores its answer after it stores it under the old
    generation, which no read accepts any more (client._lookup): its answer predates the record
    just made. The generation key outlives every entry (``seconds``)."""
    conn = _connection()
    if conn is None:
        return
    try:
        pipe = conn.pipeline(transaction=False)
        pipe.incr(generation_key)
        pipe.expire(generation_key, int(seconds))
        if keys:
            pipe.delete(*keys)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        _failed(exc)


# The per-message lock
# ---------------------------------------------------------------------------

# Longer than the slowest mirror or summary (a few lookups and comments, each up to its 10-second
# background HTTP timeout, and a summary's model call) and short enough that a worker killed while
# holding it costs a few minutes at most.
LOCK_SECONDS = 300


@contextmanager
def held(name, seconds=LOCK_SECONDS):
    """Yields True while this caller holds the lock ``name``, False when somebody else holds it,
    None when Redis is out (no lock: the caller goes on as if it held it)."""
    conn = _connection()
    if conn is None:
        yield None
        return
    try:
        lock = conn.lock(name, timeout=seconds, blocking=False)
        got = lock.acquire(blocking=False)
    except Exception as exc:  # noqa: BLE001
        _failed(exc)
        yield None
        return
    if not got:
        yield False
        return
    try:
        yield True
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - expired or Redis gone: its timeout frees it anyway
            pass


@contextmanager
def held_one_of(prefix, count, seconds=LOCK_SECONDS):
    """``held`` for any one of ``count`` slots (``prefix``:0 to ``prefix``:count-1): True while this
    caller holds one, False when every one is held, None when Redis is out (no limit)."""
    conn = _connection()
    if conn is None:
        yield None
        return
    lock = None
    try:
        for index in range(max(1, int(count))):
            candidate = conn.lock(f"{prefix}:{index}", timeout=seconds, blocking=False)
            if candidate.acquire(blocking=False):
                lock = candidate
                break
    except Exception as exc:  # noqa: BLE001
        _failed(exc)
        yield None
        return
    if lock is None:
        yield False
        return
    try:
        yield True
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001
            pass
