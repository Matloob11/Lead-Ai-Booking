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


def find_record(wa_id):
    """The lead or contact carrying this number, or None.

    Both spellings are asked for. Bitrix matches the string it holds, and a
    number saved as ``+971…`` does not match the same number saved as ``971…``
    — which is most of them, because the portals that create these leads write
    it whichever way the customer typed it.
    """
    digits = "".join(ch for ch in str(wa_id) if ch.isdigit())
    if not digits:
        return None

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
                return {"type": kind, "id": int(candidate)}
            # Otherwise keep looking. A number can sit on both a real lead and
            # somebody's dumped phone list, and the list must not win just
            # because Bitrix returned it first.

    return None


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
