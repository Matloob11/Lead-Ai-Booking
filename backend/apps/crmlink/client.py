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
"""

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class BitrixError(Exception):
    """The portal refused, or could not be reached."""


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
    """One REST method. Returns ``result``; raises BitrixError otherwise."""
    if not configured():
        raise BitrixError("No Bitrix webhook is configured")

    url = f"{settings.BITRIX_WEBHOOK_URL.rstrip('/')}/{method}"
    try:
        response = httpx.post(url, json=payload or {}, timeout=20)
        body = response.json()
    except httpx.HTTPError as exc:
        raise BitrixError(f"{method}: {_safe(exc)}") from None
    except ValueError:
        raise BitrixError(f"{method}: the portal answered with something that is not JSON") from None

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


def _is_a_person(entity_type, entity_id):
    """Whether this record looks like one customer rather than a phone list."""
    try:
        record = call(f"crm.{entity_type}.get", {"id": int(entity_id)})
    except BitrixError as exc:
        logger.warning("Could not read %s %s: %s", entity_type, entity_id, exc)
        return False

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


# The Owner Data smart process, and the two fields somebody's phone number
# ends up in on it.
#
# It is searched separately because `crm.duplicate.findbycomm` only knows about
# leads, contacts and companies — a smart process is invisible to it. And these
# two fields are plain numbers rather than Bitrix's phone type, so the match is
# an exact numeric one: the stored value has no `+`, no spaces and no country
# code unless whoever typed it included one.
OWNER_DATA_TYPE_ID = 1042
OWNER_DATA_PHONE_FIELDS = ("ufCrm5_1768317611513", "ufCrm5_1769416533028")


def _owner_data_matches(digits):
    """Owner Data records carrying this number, as timeline targets."""
    # Both spellings that survive being stored as a number: the full
    # international form, and the local one with the country code dropped.
    candidates = {digits}
    if digits.startswith("971") and len(digits) > 9:
        candidates.add(digits[3:])

    found = []
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
                logger.warning("Owner Data search on %s failed: %s", field, exc)
                continue

            for item in (result or {}).get("items", []):
                found.append(int(item["id"]))

    # An item can carry the same number in both fields, and would otherwise be
    # written to twice for one message.
    return [
        {"type": f"DYNAMIC_{OWNER_DATA_TYPE_ID}", "id": item_id, "kind": "owner data"}
        for item_id in dict.fromkeys(found)
    ]


def find_records(wa_id):
    """Every CRM record carrying this number: lead or contact, and Owner Data.

    A list rather than one answer. An agent often works the owner side of a
    property from Owner Data and never opens a lead at all, so a conversation
    can belong in two places at once — and picking one of them would leave the
    other looking as though nothing had been said.

    Both spellings are asked of the lead and contact search. Bitrix matches the
    string it holds, and a number saved as ``+971…`` does not match the same
    number saved as ``971…`` — which is most of them, because the portals that
    create these leads write it however the customer typed it.
    """
    digits = "".join(ch for ch in str(wa_id) if ch.isdigit())
    if not digits:
        return []

    records = []
    values = [digits, f"+{digits}"]

    for entity_type, kind in _SEARCH_ORDER:
        try:
            found = call(
                "crm.duplicate.findbycomm",
                {"entity_type": entity_type, "type": "PHONE", "values": values},
            )
        except BitrixError as exc:
            logger.warning("Bitrix duplicate search failed for %s: %s", entity_type, exc)
            continue

        for candidate in (found or {}).get(entity_type) or (found or {}).get(kind) or []:
            if _is_a_person(kind, candidate):
                records.append({"type": kind, "id": int(candidate), "kind": kind})
                break
            # Otherwise keep looking. A number can sit on both a real lead and
            # somebody's dumped phone list, and the list must not win just
            # because Bitrix returned it first.
        if records:
            # One of lead or contact, not both: the contact behind a lead is
            # usually the same person, and writing to both puts every message
            # on the screen twice.
            break

    records.extend(_owner_data_matches(digits))
    return records


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


def update_fields(entity_type, entity_id, fields):
    """Writes custom fields on a lead or contact."""
    return call(f"crm.{entity_type}.update", {"id": int(entity_id), "fields": fields})
