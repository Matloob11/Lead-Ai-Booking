"""Office hours and appointment-time rules (the owner's rules 45-49 and 59).

The office is open Monday to Saturday, 10:00 to 20:00 Dubai time, and closed
on Sunday and on the closed dates an admin lists (public holidays). A visit
is booked only for an exact date and time inside those hours; the last start
offered is 19:30, as in the owner's own example ("Would 7 PM or 7:30 PM work
for you?"). Same-day visits may start right away (walk-ins, "on my way"),
and a booking reaches at most 21 days ahead. Everything here is plain
functions on aware datetimes, so the model's proposal is checked without
trusting it.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.utils import timezone

DUBAI = ZoneInfo("Asia/Dubai")
OPEN = dt.time(10, 0)
CLOSE = dt.time(20, 0)
LATEST_START = dt.time(19, 30)
SUNDAY = 6  # date.weekday(): Monday is 0
WALK_IN_GRACE = dt.timedelta(minutes=2)
MAX_AHEAD = dt.timedelta(days=21)
REMINDER_BEFORE = dt.timedelta(minutes=30)
HOT_WITHIN = dt.timedelta(minutes=60)

HOURS_TEXT = "Monday to Saturday, 10 AM to 8 PM. Closed on Sunday."

_DATE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


class SlotError(ValueError):
    """A proposed time the office cannot accept. ``code`` is stable for tests."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Day:
    date: dt.date
    open: bool
    earliest: dt.time | None = None  # today only: the first start still possible

    @property
    def label(self) -> str:
        return f"{self.date:%a} {self.date.isoformat()}"


def now_dubai(now: dt.datetime | None = None) -> dt.datetime:
    return (now or timezone.now()).astimezone(DUBAI)


def parse_date(value) -> dt.date | None:
    match = _DATE.match(str(value or ""))
    if not match:
        return None
    try:
        return dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def parse_time(value) -> dt.time | None:
    match = _TIME.match(str(value or ""))
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    if hour > 23 or minute > 59:
        return None
    return dt.time(hour, minute)


def closed_set(closed_dates) -> set[dt.date]:
    days = set()
    for value in closed_dates or []:
        day = parse_date(value)
        if day:
            days.add(day)
    return days


def is_open_day(day: dt.date, closed_dates=()) -> bool:
    return day.weekday() != SUNDAY and day not in closed_set(closed_dates)


def _round_up_5(moment: dt.datetime) -> dt.datetime:
    moment = moment.replace(second=0, microsecond=0)
    extra = (-moment.minute) % 5
    return moment + dt.timedelta(minutes=extra)


def check_slot(date_value, time_value, *, now: dt.datetime | None = None, closed_dates=()) -> dt.datetime:
    """The aware start of a visit, or SlotError explaining why it cannot be booked."""
    if not date_value:
        raise SlotError("missing_date", "No date was agreed yet. Ask which day suits them.")
    if not time_value:
        raise SlotError(
            "missing_time",
            "No exact time was agreed yet. A vague time is not a booking: offer one or two exact times.",
        )
    day = parse_date(date_value)
    if day is None:
        raise SlotError("bad_date", f"'{date_value}' is not a date in YYYY-MM-DD form.")
    at = parse_time(time_value)
    if at is None:
        raise SlotError("bad_time", f"'{time_value}' is not a time in 24-hour HH:MM form.")

    if day.weekday() == SUNDAY:
        raise SlotError("sunday", "The office is closed on Sunday. Offer Monday or Saturday instead.")
    if day in closed_set(closed_dates):
        raise SlotError("closed", "The office is closed on that date (holiday). Offer the next open day.")
    if at < OPEN:
        raise SlotError("before_open", "The office opens at 10:00 AM. Offer a time from 10:00 AM.")
    if at > LATEST_START:
        raise SlotError(
            "after_latest",
            "The office closes at 8:00 PM; the latest visit we book starts at 7:30 PM. "
            "Offer 7:00 PM or 7:30 PM, or another day.",
        )

    start = dt.datetime.combine(day, at, tzinfo=DUBAI)
    current = now_dubai(now)
    if start < current - WALK_IN_GRACE:
        raise SlotError("past", "That time has already passed. Offer a later time.")
    if start > current + MAX_AHEAD:
        raise SlotError(
            "too_far",
            "That is more than three weeks away. Record it as tentative and let the specialist confirm it.",
        )
    return start


def check_late_arrival(starts_at: dt.datetime, time_value, *, now: dt.datetime | None = None) -> dt.datetime:
    """The new arrival time for a customer running late (same day as the visit).

    The meeting's own time is accepted ("I'll make it on time"): the caller
    then changes nothing. An arrival after the last start we book is not.
    """
    at = parse_time(time_value)
    if at is None:
        raise SlotError("bad_time", f"'{time_value}' is not a time in 24-hour HH:MM form.")
    local_start = starts_at.astimezone(DUBAI)
    arrival = dt.datetime.combine(local_start.date(), at, tzinfo=DUBAI)
    if arrival < local_start:
        raise SlotError(
            "not_later",
            "That is before the meeting time, so the meeting stays as booked. Tell them we will see them then.",
        )
    if arrival.time() > LATEST_START:
        raise SlotError(
            "after_close",
            "The office closes at 8:00 PM and the latest arrival we can hold is 7:30 PM. "
            "Offer to reschedule to another day.",
        )
    current = now_dubai(now)
    if arrival < current - dt.timedelta(minutes=5):
        raise SlotError("past", "That time has already passed. Ask for their new arrival time.")
    return arrival


def calendar(now: dt.datetime | None = None, closed_dates=(), days: int = 14) -> list[Day]:
    """The next ``days`` days, open or closed; today shows the earliest start still possible."""
    current = now_dubai(now)
    closed = closed_set(closed_dates)
    out: list[Day] = []
    for offset in range(days):
        day = current.date() + dt.timedelta(days=offset)
        is_open = day.weekday() != SUNDAY and day not in closed
        earliest = None
        if offset == 0 and is_open:
            first = max(dt.datetime.combine(day, OPEN, tzinfo=DUBAI), _round_up_5(current))
            if first.time() > LATEST_START:
                is_open = False
            else:
                earliest = first.time()
        out.append(Day(day, is_open, earliest))
    return out


def calendar_lines(now: dt.datetime | None = None, closed_dates=(), days: int = 14) -> list[str]:
    today = now_dubai(now).date()
    lines = []
    for day in calendar(now, closed_dates, days):
        tag = " (today)" if day.date == today else (" (tomorrow)" if day.date == today + dt.timedelta(days=1) else "")
        if not day.open:
            lines.append(f"{day.label}{tag}: CLOSED")
        elif day.earliest:
            lines.append(f"{day.label}{tag}: open, starts from {day.earliest:%H:%M} to 19:30")
        else:
            lines.append(f"{day.label}{tag}: open, starts 10:00 to 19:30")
    return lines


def describe(start: dt.datetime) -> str:
    """'Monday 12 October 2026, 5:00 PM' in Dubai time."""
    local = start.astimezone(DUBAI)
    return f"{local:%A} {local.day} {local:%B %Y}, {time_label(local)}"


def day_label(start: dt.datetime) -> str:
    """'Monday 12 October' in Dubai time."""
    local = start.astimezone(DUBAI)
    return f"{local:%A} {local.day} {local:%B}"


def time_label(start: dt.datetime) -> str:
    """'5:00 PM' in Dubai time."""
    local = start.astimezone(DUBAI)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{local:%M} {local:%p}"


def is_today(start: dt.datetime, now: dt.datetime | None = None) -> bool:
    return start.astimezone(DUBAI).date() == now_dubai(now).date()


def is_soon(start: dt.datetime, now: dt.datetime | None = None) -> bool:
    """Starts within the hour: a walk-in or a customer on the way (owner's rule 60)."""
    current = now or timezone.now()
    return start - current <= HOT_WITHIN


def reminder_due(start: dt.datetime, now: dt.datetime | None = None) -> dt.datetime | None:
    """When the 30-minute reminder goes out; None if that moment has already passed."""
    due = start - REMINDER_BEFORE
    return due if due > (now or timezone.now()) else None
