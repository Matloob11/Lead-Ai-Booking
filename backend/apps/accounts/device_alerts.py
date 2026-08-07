"""Telling somebody that a linked handset has gone away.

When an agent unlinks their phone the inbox simply stops receiving on that
number. Nothing on any screen says so — the chats stop arriving and the first
sign is a customer complaining that nobody answered. This is the part that says
it out loud, on WhatsApp, to the people who can do something about it.

Sent as a **template**. The 24-hour free-form window opens only on an inbound
message, so plain text to an admin who has not written today fails with 131047 —
precisely when the alert matters most. The template is UTILITY, so it is also
outside the per-customer daily cap that the marketing templates share.

Two WABAs are tried in turn, and that is deliberate rather than belt-and-braces:
an alert that shares a business account with whatever has gone wrong is an alert
that can go down with it.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta

from django.conf import settings

from apps.gateway.client import AlotsClient, AlotsError

logger = logging.getLogger(__name__)

# The alert is stamped in the time the people reading it live in, not UTC. They
# are in Dubai; a timestamp four hours out is worse than none, because it is
# believed.
_GST = timezone(timedelta(hours=4))


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def format_when(moment: datetime | None = None) -> str:
    """`07 Aug 2026, 18:42 GST` — the shape the approved template's sample used."""
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(_GST).strftime("%d %b %Y, %H:%M GST")


def describe_device(phone: str | None, session_name: str | None) -> str:
    """What went away, as one readable string.

    Both halves are worth having and neither is reliable on its own: the number
    is what an admin recognises, the session name is what the gateway calls it,
    and an unlink can leave the row with no number at all. Whichever survives is
    what gets sent.
    """
    phone = (phone or "").strip()
    name = (session_name or "").strip()
    if phone and name:
        return f"{phone} ({name})"
    return phone or name or "an unnamed device"


def send_device_disconnected_alert(*, phone: str | None, session_name: str | None, when: datetime | None = None):
    """Send the alert to every configured recipient. Returns a per-number result.

    Never raises. This is called from a request handler that has already done the
    thing it was asked to do, and a failure to *tell* somebody must not be
    reported as a failure to notice.
    """
    recipients = [_digits(number) for number in settings.DEVICE_ALERT_RECIPIENTS]
    recipients = [number for number in recipients if number]
    if not recipients:
        logger.warning("Device-disconnected alert not sent: no recipients configured")
        return {}

    device = describe_device(phone, session_name)
    components = [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": device},
                {"type": "text", "text": format_when(when)},
            ],
        }
    ]

    # Built once and reused across recipients: a fresh client per number would
    # open a fresh connection for each, and the alert is already racing whatever
    # made the phone disappear.
    client = AlotsClient()
    # The backup is only in the list when it is actually a different number —
    # otherwise a misconfiguration turns one failed send into two identical ones.
    senders = [settings.DEVICE_ALERT_PHONE_ID]
    if settings.DEVICE_ALERT_PHONE_ID_BACKUP and settings.DEVICE_ALERT_PHONE_ID_BACKUP != senders[0]:
        senders.append(settings.DEVICE_ALERT_PHONE_ID_BACKUP)

    results = {}
    for number in recipients:
        results[number] = _send_one(client, senders, number, components, device)
    return results


def _send_one(client: AlotsClient, senders: list[str], number: str, components: list, device: str) -> dict:
    """One recipient, each sending number tried until one is accepted."""
    errors = []
    for phone_number_id in senders:
        if not phone_number_id:
            continue
        try:
            response = client.send_template(
                phone_number_id,
                number,
                settings.DEVICE_ALERT_TEMPLATE,
                language=settings.DEVICE_ALERT_TEMPLATE_LANG,
                components=components,
            )
        except AlotsError as error:
            # Logged per attempt rather than only at the end: when both numbers
            # fail, the reason each one gave is the whole diagnosis, and a
            # summary that keeps only the last one throws the first away.
            logger.warning(
                "Device alert to %s from %s failed: %s",
                number,
                phone_number_id,
                error,
            )
            errors.append(f"{phone_number_id}: {error}")
            continue
        except Exception as error:  # noqa: BLE001 - a broken alert must not break the caller
            logger.warning("Device alert to %s from %s raised: %s", number, phone_number_id, error)
            errors.append(f"{phone_number_id}: {error}")
            continue

        logger.info("Device alert sent to %s from %s (%s)", number, phone_number_id, device)
        return {"sent": True, "from": phone_number_id, "response": response}

    return {"sent": False, "errors": errors}
