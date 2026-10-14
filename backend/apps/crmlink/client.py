"""Writing to Bitrix24 from the server, through an inbound webhook.

The panel talks to Bitrix from the browser, with the agent's own session. That
is no use here: a customer's message arrives at three in the morning and there
is no agent, no session and no AUTH_ID to borrow — the one the panel signs in
with is spent verifying who they are and deliberately never stored.

An inbound webhook is a standing credential belonging to the portal rather than
to a person, which is exactly what a background worker needs. It is also a
bearer token in a URL, so it lives only in the environment and is never logged:
``_safe`` exists to keep it out of exception text, which is the place a secret
usually escapes from.

Every call goes through ``call``, which also (board T57 and the REST throttle
found on 2026-10-14):

- waits its turn under a limit every process shares (redis_state.bitrix_slot),
  a little under the 2 requests a second the Bitrix nginx allows our address.
  A call can wait up to about 2.5 s for its slot, and raises BitrixTransient
  when none comes free in that time;
- tells a passing failure from a refusal. ``BitrixTransient`` is an HTTP 429,
  any 5xx, a body that is not JSON, a timeout or a network error, or no slot in
  time: asking again later can work. It is a ``BitrixError``, so every
  ``except BitrixError`` still catches it. Any other BitrixError is the portal
  saying no, and asking again changes nothing;
- names the HTTP status when the answer is not JSON. The nginx throttle answers
  429 with an HTML page; without the status, that read as a fault of the portal.

Work nobody waits for (the CRM mirror and its summaries) runs inside
``background()``: low priority under the shared limit (a slot free now or none,
never a sleep in a worker child), a 10-second timeout instead of 20, and no
call at all for a minute after Bitrix timed out or could not be reached
(redis_state.bitrix_down). Its tasks try again later instead.
"""

import contextvars
import hashlib
import html
import logging
import time
from contextlib import contextmanager

import httpx
from django.conf import settings

from . import redis_state

logger = logging.getLogger(__name__)

# Looked up at call time, so a test can stand in for the wait without touching time.sleep.
_sleep = time.sleep

FOREGROUND_TIMEOUT = 20
BACKGROUND_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_background = contextvars.ContextVar("crmlink_bitrix_background", default=False)


@contextmanager
def background():
    """Every Bitrix call inside this block is background work (see the module docstring).

    A Celery prefork child runs one task at a time on one thread, so the flag set here is seen
    by every call the task makes, through any helper, and by nothing else.
    """
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


class BitrixError(Exception):
    """The portal refused, or could not be reached."""


class BitrixTransient(BitrixError):
    """The portal could not answer now: HTTP 429, a 5xx, a body that is not JSON, a timeout or
    a network error, or no request slot under the shared rate limit in time. Worth asking again
    later. Its text keeps the words other code reads it by ("not JSON", "timed out", the status):
    apps.leadai.tasks._transient matches on them.

    ``maybe_applied``: the request may have reached Bitrix and done its work, the answer being
    what was lost (a read timeout, a dropped connection, a 500/502/504, a body that is not JSON).
    A write that failed so must not simply be sent again. False only when the request provably
    never ran there: no slot here, "Bitrix is down" here, a connection that never opened, nginx's
    429, or Bitrix's own QUERY_LIMIT_EXCEEDED.
    """

    def __init__(self, message="", *, maybe_applied=False):
        super().__init__(message)
        self.maybe_applied = bool(maybe_applied)


# The httpx failures that say nothing against the request itself: it timed out, the network
# dropped, or the far end hung up or garbled the answer. Anything else from httpx (a malformed
# URL, a scheme it cannot speak) fails the same way the next time.
_PASSING_HTTPX = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.ProxyError,
    httpx.DecodingError,
)
# Of those, the ones where the request never left: no connection was ever made.
_NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ProxyError)
# The ones that say the box is slow or unreachable, rather than one answer being garbled.
_DOWN = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
_DOWN_STATUSES = (502, 503, 504)


def configured():
    return bool(settings.BITRIX_WEBHOOK_URL)


def _safe(text):
    """The same text with the webhook token taken out of it.

    Bitrix puts errors and URLs into its own messages, and httpx puts the URL
    into every timeout. Either would carry the token into a log file that is
    read by more people than the environment file is.
    """
    token = settings.BITRIX_WEBHOOK_URL.rstrip("/").rsplit("/", 1)[-1]
    return str(text).replace(token, "***") if token else str(text)


def call(method, payload=None):
    """One REST method. Returns ``result``; raises BitrixError otherwise.

    BitrixTransient (a BitrixError) when the failure may pass: HTTP 429, any 5xx, a body that
    is not JSON, a timeout or a network error, or no slot under the shared rate limit within
    about 2.5 s (background work: no slot free now, or Bitrix down a moment ago). Its
    ``maybe_applied`` says whether the request may have run there anyway. The body itself is
    never quoted: it is somebody else's HTML and can say anything.
    """
    if not configured():
        raise BitrixError("No Bitrix webhook is configured")

    in_background = _background.get()
    # "timed out" is one of the words apps.leadai.tasks._transient reads a retry from.
    if in_background and redis_state.bitrix_down():
        raise BitrixTransient(
            f"{method}: Bitrix timed out or could not be reached in the last minute, so background "
            "work waits (timed out)"
        )
    wait = redis_state.bitrix_slot(background=in_background)
    if wait is None:
        if in_background:
            raise BitrixTransient(
                f"{method}: local rate limit, no Bitrix request slot free for background work now "
                "(timed out waiting)"
            )
        raise BitrixTransient(
            f"{method}: local rate limit, no Bitrix request slot within "
            f"{redis_state.max_wait():g} s (timed out waiting)"
        )
    if wait > 0:
        _sleep(wait)

    url = f"{settings.BITRIX_WEBHOOK_URL.rstrip('/')}/{method}"
    try:
        response = httpx.post(
            url, json=payload or {}, timeout=BACKGROUND_TIMEOUT if in_background else FOREGROUND_TIMEOUT
        )
    except _PASSING_HTTPX as exc:
        if isinstance(exc, _DOWN):
            redis_state.mark_bitrix_down()
        raise BitrixTransient(
            f"{method}: {_safe(exc) or 'no answer'} ({type(exc).__name__})",
            maybe_applied=not isinstance(exc, _NEVER_SENT),
        ) from None
    except httpx.HTTPError as exc:
        raise BitrixError(f"{method}: {_safe(exc)}") from None

    status = response.status_code
    if status in _DOWN_STATUSES:
        redis_state.mark_bitrix_down()
    try:
        body = response.json()
    except ValueError:
        # nginx's limit_req answers 429 before anything reaches PHP; any other page may come from
        # a request that ran.
        raise BitrixTransient(
            f"{method}: HTTP {status}, the portal answered with something that is not JSON",
            maybe_applied=status != 429,
        ) from None

    if status == 429 or status >= 500:
        # Bitrix's own throttle (QUERY_LIMIT_EXCEEDED) is a 503 with JSON; a 500 is a fault on
        # its side. Either may pass, whatever the body says.
        detail = ""
        throttled = False
        if isinstance(body, dict):
            detail = _safe(body.get("error_description") or body.get("error") or "")[:200]
            throttled = str(body.get("error") or "").upper() == "QUERY_LIMIT_EXCEEDED"
        raise BitrixTransient(
            f"{method}: HTTP {status}" + (f", {detail}" if detail else ""),
            maybe_applied=not (status == 429 or throttled),
        )

    if isinstance(body, dict) and body.get("error"):
        raise BitrixError(f"{method}: {body.get('error_description') or body['error']}")

    return body.get("result") if isinstance(body, dict) else body


# Finding the record a number belongs to
# ---------------------------------------------------------------------------

# Leads first, then contacts. Deals are deliberately absent: a deal has no
# phone of its own, and following it through its contact would write the same
# message twice on the same screen.
_SEARCH_ORDER = (("LEAD", "lead"), ("CONTACT", "contact"))

# More phone numbers than this, and the record is not a person.
#
# Contact 167 in this portal is called "Dubai Agent" and carries several
# thousand numbers — somebody emptied a phone list into one record. Bitrix's
# duplicate search matches it for every one of them, so without this a
# customer's private conversation would be posted onto a record shared with
# thousands of unrelated numbers, and the timeline of the person it actually
# belongs to would stay empty.
#
# Six is generous for a human — mobile, work, home, and a couple of old ones.
MAX_PHONES_ON_A_PERSON = 6


def _check_person(entity_type, entity_id):
    """True when this record looks like one customer, False when it is a phone list.

    Raises BitrixError when the record cannot be read.
    """
    record = call(f"crm.{entity_type}.get", {"id": int(entity_id)})
    phones = (record or {}).get("PHONE") or []
    if len(phones) > MAX_PHONES_ON_A_PERSON:
        logger.warning(
            "Ignoring %s %s: it carries %s phone numbers, so it is a list rather than a person",
            entity_type,
            entity_id,
            len(phones),
        )
        return False
    return True


def _is_a_person(entity_type, entity_id):
    """Whether this record looks like one customer rather than a phone list (unreadable: no)."""
    try:
        return _check_person(entity_type, entity_id)
    except BitrixError as exc:
        logger.warning("Could not read %s %s: %s", entity_type, entity_id, exc)
        return False


# The Owner Data smart process, and the two fields somebody's phone number
# ends up in on it.
#
# It is searched separately because `crm.duplicate.findbycomm` only knows about
# leads, contacts and companies — a smart process is invisible to it. And these
# two fields are plain numbers rather than Bitrix's phone type, so the match is
# an exact numeric one: the stored value has no `+`, no spaces and no country
# code unless whoever typed it included one.
OWNER_DATA_TYPE_ID = 1042
OWNER_DATA_CATEGORY_AVAILABILITY = 14
OWNER_DATA_STAGE_NEW_AVAILABILITY = "DT1042_14:NEW"
# The calling board — where an Excel batch can file its cards instead.
OWNER_DATA_CATEGORY_CALLING = 13
OWNER_DATA_STAGE_NEW_CALLING = "DT1042_13:NEW"
OWNER_DATA_PHONE_FIELDS = ("ufCrm5_1768317611513", "ufCrm5_1769416533028")


def _owner_data_lookup(digits, strict):
    """(Owner Data records carrying this number, as timeline targets; whether every search answered).

    ``strict``: a passing failure of any search raises BitrixTransient instead of being logged
    and skipped, so that it cannot read as "no card".
    """
    # Both spellings that survive being stored as a number: the full
    # international form, and the local one with the country code dropped.
    candidates = {digits}
    if digits.startswith("971") and len(digits) > 9:
        candidates.add(digits[3:])

    found = []
    complete = True
    for field in OWNER_DATA_PHONE_FIELDS:
        for value in candidates:
            try:
                result = call(
                    "crm.item.list",
                    {
                        "entityTypeId": OWNER_DATA_TYPE_ID,
                        "select": ["id"],
                        "filter": {field: int(value)},
                    },
                )
            except (BitrixError, ValueError) as exc:
                if strict and isinstance(exc, BitrixTransient):
                    raise
                logger.warning("Owner Data search on %s failed: %s", field, exc)
                complete = False
                continue

            for item in (result or {}).get("items", []):
                found.append(int(item["id"]))

    # An item can carry the same number in both fields, and would otherwise be
    # written to twice for one message.
    records = [
        {"type": f"DYNAMIC_{OWNER_DATA_TYPE_ID}", "id": item_id, "kind": "owner data"}
        for item_id in dict.fromkeys(found)
    ]
    return records, complete


def _owner_data_matches(digits):
    """Owner Data records carrying this number, as timeline targets.

    As it always was: every failed search logged and skipped, nothing cached.
    apps.campaigns.services.ensure_owner_data calls it with a recipient's phone.
    """
    return _owner_data_lookup(digits, strict=False)[0]


def _person_lookup(digits, strict):
    """([the lead or the contact carrying this number], whether every search and read answered).

    ``strict``: a passing failure raises BitrixTransient instead of being logged and skipped.
    """
    values = [digits, f"+{digits}"]
    complete = True

    for entity_type, kind in _SEARCH_ORDER:
        try:
            found = call(
                "crm.duplicate.findbycomm",
                {"entity_type": entity_type, "type": "PHONE", "values": values},
            )
        except BitrixError as exc:
            if strict and isinstance(exc, BitrixTransient):
                raise
            logger.warning("Bitrix duplicate search failed for %s: %s", entity_type, exc)
            complete = False
            continue

        for candidate in (found or {}).get(entity_type) or (found or {}).get(kind) or []:
            try:
                person = _check_person(kind, candidate)
            except BitrixError as exc:
                if strict and isinstance(exc, BitrixTransient):
                    raise
                logger.warning("Could not read %s %s: %s", kind, candidate, exc)
                complete = False
                person = False
            if person:
                # One of lead or contact, not both: the contact behind a lead is
                # usually the same person, and writing to both puts every message
                # on the screen twice.
                return [{"type": kind, "id": int(candidate), "kind": kind}], complete
            # Otherwise keep looking. A number can sit on both a real lead and
            # somebody's dumped phone list, and the list must not win just
            # because Bitrix returned it first.

    return [], complete


# How long a lookup is kept, per number. Long enough that an active chat asks once rather than for
# every message, short enough that a lead or card made in Bitrix after the first message (the
# normal order when a customer writes before anybody has entered them) is found once its entry
# expires. "No record" is kept for less long: until it expires, nothing of the chat reaches a
# record somebody has just made by hand. One made from here (create_lead, create_owner_data)
# drops the entry at once, and moves the number's generation on, so that a lookup already under
# way when the record was made cannot store its older answer after that.
RECORDS_CACHE_SECONDS = 600
NO_RECORD_CACHE_SECONDS = 120
GENERATION_SECONDS = 24 * 3600


def _cache_seconds():
    return int(getattr(settings, "BITRIX_RECORDS_CACHE_SECONDS", RECORDS_CACHE_SECONDS))


def _no_record_cache_seconds():
    return int(getattr(settings, "BITRIX_NO_RECORD_CACHE_SECONDS", NO_RECORD_CACHE_SECONDS))


def _cache_key(part, digits):
    # The number hashed: a listing of Redis keys is no place for customers' phone numbers.
    return f"crmlink:records:v2:{part}:{hashlib.sha256(digits.encode()).hexdigest()[:32]}"


def _generation_key(digits):
    return _cache_key("generation", digits)


def _cached_records(entry, generation):
    """The records of a cache entry, or None when it is not a usable one: missing, garbled, or
    stored under another generation than the number's current one."""
    if not (isinstance(entry, dict) and isinstance(entry.get("records"), list)):
        return None
    if generation is None or entry.get("generation") != generation:
        return None
    records = []
    for item in entry["records"]:
        if not (isinstance(item, dict) and isinstance(item.get("type"), str) and isinstance(item.get("id"), int)):
            return None
        records.append({"type": item["type"], "id": item["id"], "kind": str(item.get("kind") or item["type"])})
    return records


def _lookup(part, digits, strict, cached, look):
    """One half of find_records, through the cache.

    Only a lookup in which every search answered is stored, so a failure is never remembered as
    "no record". It is stored whoever asked: a fresh answer is the best one there is. It is
    stored with the generation read before the lookup began, so that a record made here in the
    meantime (forget_records) makes it unreadable.
    """
    seconds = _cache_seconds()
    if seconds <= 0:
        return look(digits, strict)[0]
    key = _cache_key(part, digits)
    entry, generation = redis_state.cache_get(key, _generation_key(digits))
    if cached:
        hit = _cached_records(entry, generation)
        if hit is not None:
            return hit
    records, complete = look(digits, strict)
    if complete and generation is not None:
        redis_state.cache_set(
            key,
            {"generation": generation, "records": records},
            seconds if records else min(seconds, _no_record_cache_seconds()),
        )
    return records


def _digits(raw):
    return "".join(ch for ch in str(raw or "") if ch.isdigit())


def find_records(wa_id, strict=False, *, cached=False):
    """Every CRM record carrying this number: lead or contact, and Owner Data.

    A list rather than one answer. An agent often works the owner side of a
    property from Owner Data and never opens a lead at all, so a conversation
    can belong in two places at once — and picking one of them would leave the
    other looking as though nothing had been said.

    Both spellings are asked of the lead and contact search. Bitrix matches the
    string it holds, and a number saved as ``+971…`` does not match the same
    number saved as ``971…`` — which is most of them, because the portals that
    create these leads write it however the customer typed it.

    ``strict``: a passing failure (BitrixTransient) of any search or read raises
    instead of being logged and skipped, so it cannot look like "no record". The
    default is how it always behaved, which every caller but the mirror keeps.

    ``cached``: answer from a lookup of the same number made in the last
    RECORDS_CACHE_SECONDS (NO_RECORD_CACHE_SECONDS when it found nothing), kept
    in Redis, when there is one. Off by default: the panel asking "where is this
    number" and the Lead AI tasks still ask Bitrix.
    """
    digits = _digits(wa_id)
    if not digits:
        return []
    return _lookup("person", digits, strict, cached, _person_lookup) + _lookup(
        "owner", digits, strict, cached, _owner_data_lookup
    )


def owner_data_records(wa_id, strict=False, *, cached=False):
    """Only the Owner Data half of find_records, with the same ``strict`` and ``cached``.

    For a chat that knows its person already: a Lead AI chat's own lead (board T57).
    """
    digits = _digits(wa_id)
    if not digits:
        return []
    return _lookup("owner", digits, strict, cached, _owner_data_lookup)


def forget_records(wa_id):
    """Drop the cached lookups of this number: a record was just made for it here, or one of its
    cached records refused a comment (deleted or merged since)."""
    digits = _digits(wa_id)
    if digits:
        redis_state.cache_forget(
            _generation_key(digits),
            _cache_key("person", digits),
            _cache_key("owner", digits),
            seconds=max(GENERATION_SECONDS, _cache_seconds()),
        )


def find_record(wa_id):
    """The first record for this number, or None. Kept for callers wanting one."""
    records = find_records(wa_id)
    return records[0] if records else None


# Writing
# ---------------------------------------------------------------------------


def add_comment(entity_type, entity_id, text):
    """Puts one line in a record's timeline. Returns the comment id."""
    return call(
        "crm.timeline.comment.add",
        {"fields": {"ENTITY_ID": int(entity_id), "ENTITY_TYPE": entity_type, "COMMENT": text}},
    )


def comment_id(value):
    """The comment id in what crm.timeline.comment.add answered, or None when it gave none: an
    empty-code "Not found" comes back as no result at all, and is no comment."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) or None
    return None


def _comparable(text):
    """A timeline comment as plain words: Bitrix may give back HTML entities and other line ends
    than it was sent."""
    return " ".join(html.unescape(str(text or "")).split())


def find_comment(entity_type, entity_id, text, *, skip=()):
    """The id of a comment reading ``text`` among the record's latest comments, or None.

    For a post whose answer was lost after it was sent (BitrixTransient.maybe_applied): Bitrix
    may hold it already, and posting it again would put the line on the timeline twice. Only the
    newest page (50) is read; ``skip`` holds ids already known to belong to other messages (two
    "ok"s in the same minute read the same). Raises BitrixError like any call.
    """
    found = call(
        "crm.timeline.comment.list",
        {
            "filter": {"ENTITY_ID": int(entity_id), "ENTITY_TYPE": entity_type},
            "select": ["ID", "COMMENT"],
            "order": {"ID": "DESC"},
        },
    )
    if isinstance(found, dict):
        found = found.get("items")
    items = found if isinstance(found, list) else []
    wanted = _comparable(text)
    skip = set(skip or ())
    for item in items:
        if not isinstance(item, dict):
            continue
        pk = comment_id(item.get("ID"))
        if pk is not None and pk not in skip and _comparable(item.get("COMMENT")) == wanted:
            return pk
    return None


def update_fields(entity_type, entity_id, fields):
    """Writes custom fields on a lead or contact."""
    return call(f"crm.{entity_type}.update", {"id": int(entity_id), "fields": fields})


# Creating the record a number does not have yet
# ---------------------------------------------------------------------------


def create_lead(wa_id, name=""):
    """A new lead carrying this number. Returns the same shape as find_records.

    The phone goes on as WORK rather than MOBILE: Bitrix's duplicate search
    matches on the value and not the type, so the label only decides what a
    person reads on the card — and WORK is the truthful one for a number a
    business was contacted on.
    """
    digits = "".join(ch for ch in str(wa_id) if ch.isdigit())
    if not digits:
        raise BitrixError("No number to create a lead from")

    title = name.strip() if name and name.strip() else f"WhatsApp +{digits}"
    fields = {
        "TITLE": title,
        # "OTHER" rather than inventing a WhatsApp source: a SOURCE_ID Bitrix
        # does not know is rejected outright, and adding one to the portal is a
        # decision for whoever runs the CRM, not for this code.
        "SOURCE_ID": "OTHER",
        "PHONE": [{"VALUE": f"+{digits}", "VALUE_TYPE": "WORK"}],
    }
    if name and name.strip():
        fields["NAME"] = name.strip()[:100]

    lead_id = call("crm.lead.add", {"fields": fields})
    if not lead_id:
        raise BitrixError("Bitrix created no lead and gave no reason")
    # The mirror's cached "no record" for this number would hide the new lead for minutes.
    forget_records(digits)
    return {"type": "lead", "id": int(lead_id), "kind": "lead"}


def create_owner_data(wa_id, name="", *, stage_id=None, category_id=None):
    """A new Owner Data item carrying this number.

    The phone fields on that smart process are numeric, which is why the search
    side casts to int — so the same has to be done writing, or the value lands
    as text and no later search will ever match it.

    Campaign sends land on New Availability (category 14) so agents see them on
    the kanban the business already works from.
    """
    digits = "".join(ch for ch in str(wa_id) if ch.isdigit())
    if not digits:
        raise BitrixError("No number to create an Owner Data record from")

    fields = {
        "title": name.strip() if name and name.strip() else f"WhatsApp +{digits}",
        # Only the first field is written. The second exists so a person can
        # record an alternative number by hand; filling both from one WhatsApp
        # id would put the same number on the record twice.
        OWNER_DATA_PHONE_FIELDS[0]: int(digits),
    }
    if category_id is not None:
        fields["categoryId"] = int(category_id)
    if stage_id:
        fields["stageId"] = stage_id

    result = call("crm.item.add", {"entityTypeId": OWNER_DATA_TYPE_ID, "fields": fields})
    item = (result or {}).get("item") or {}
    item_id = item.get("id")
    if not item_id:
        raise BitrixError("Bitrix created no Owner Data record and gave no reason")
    # A campaign makes these for numbers the mirror may have looked up (and cached) minutes ago.
    forget_records(digits)
    return {
        "type": f"DYNAMIC_{OWNER_DATA_TYPE_ID}",
        "id": int(item_id),
        "kind": "owner data",
    }
