"""Office hours and appointment-time rules (the owner's rules 45-49 and 59).

The office is open Monday to Saturday, 10:00 to 20:00 Dubai time, and closed
on Sunday and on the closed dates an admin lists (public holidays). A visit
is booked only for an exact date and time inside those hours; the last start
offered is 19:30, as in the owner's own example ("Would 7 PM or 7:30 PM work
for you?"). Same-day visits may start right away (walk-ins, "on my way"),
and a booking reaches at most 21 days ahead. Everything here is plain
functions on aware datetimes, so the model's proposal is checked without
trusting it.

Slots (owner's choice 2026-10-13): the office takes ONE client per
30-minute slot, on a grid from 10:00 to the last slot at 19:30. ``free_slots``
lists the free starts from our own appointment table (the caller passes the
starts already taken), ``nearest_free`` the two around a taken one, and
``offer_pair`` the two a shops invitation names. ``named_days`` and
``named_times`` read the day and the hour a customer wrote themselves, so code
can tell "Can I come Wednesday at 5 pm?" from a time the model picked.
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
    """A proposed time the office cannot accept. ``code`` is stable for tests.

    ``alternatives``: for a slot another client has ("taken"), the free starts
    nearest it, which the reply offers instead.
    """

    def __init__(self, code: str, message: str, alternatives=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.alternatives = list(alternatives or [])


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


# Slots ----------------------------------------------------------------------------

SLOT = dt.timedelta(minutes=30)
# A slot is offered only this far ahead at least, then up to the next half hour:
# at 14:00 the first one offered is 14:30, at 14:20 it is 15:00.
OFFER_LEAD = dt.timedelta(minutes=15)
# The two slots an invitation names are this far apart when the day allows
# ("today at 4:00 PM or 6:00 PM").
OFFER_GAP = dt.timedelta(hours=2)
SLOTS_SHOWN = 6
_EVERY_SLOT = 22 * 20  # every start of the 30-minute grid within MAX_AHEAD


def slot_grid(day: dt.date) -> list[dt.datetime]:
    """Every start of a day's 30-minute grid, 10:00 to 19:30 Dubai time (whatever the day)."""
    out = []
    moment = dt.datetime.combine(day, OPEN, tzinfo=DUBAI)
    last = dt.datetime.combine(day, LATEST_START, tzinfo=DUBAI)
    while moment <= last:
        out.append(moment)
        moment += SLOT
    return out


def is_taken(start: dt.datetime, taken=()) -> bool:
    """Another client's visit starts less than 30 minutes before or after this one."""
    return any(abs(start - other) < SLOT for other in taken or ())


def first_offer(now: dt.datetime | None = None) -> dt.datetime:
    """The earliest start worth offering: OFFER_LEAD from now, up to the next half hour."""
    moment = now_dubai(now) + OFFER_LEAD
    base = moment.replace(minute=0, second=0, microsecond=0)
    for step in range(3):
        candidate = base + step * SLOT
        if candidate >= moment:
            return candidate
    return base + 3 * SLOT


def free_slots(now: dt.datetime | None = None, closed_dates=(), taken=(), *, count: int = SLOTS_SHOWN) -> list[dt.datetime]:
    """The next ``count`` free 30-minute starts: open days only, none sooner than
    first_offer, none more than MAX_AHEAD away, and none another client has
    (``taken``: the starts of the other open office visits)."""
    current = now_dubai(now)
    earliest = first_offer(current)
    limit = current + MAX_AHEAD
    closed = closed_set(closed_dates)
    out: list[dt.datetime] = []
    day = earliest.date()
    while day <= limit.date() and len(out) < count:
        if day.weekday() != SUNDAY and day not in closed:
            for start in slot_grid(day):
                if earliest <= start <= limit and not is_taken(start, taken):
                    out.append(start)
                    if len(out) >= count:
                        break
        day += dt.timedelta(days=1)
    return out


def nearest_free(start: dt.datetime, now: dt.datetime | None = None, closed_dates=(), taken=()) -> list[dt.datetime]:
    """The free starts to offer instead of a taken one: the nearest before it and the
    nearest after it, or the two nearest on the side that has any."""
    every = free_slots(now, closed_dates, taken, count=_EVERY_SLOT)
    before = [slot for slot in every if slot < start]
    after = [slot for slot in every if slot > start]
    if before and after:
        return [before[-1], after[0]]
    return after[:2] if after else before[-2:]


def offer_pair(
    now: dt.datetime | None = None, closed_dates=(), taken=(), *, day: dt.date | None = None, avoid=()
) -> list[dt.datetime]:
    """The two free starts an invitation names: the first one free, and the first one
    OFFER_GAP after it the same day, else the next open day's first.

    ``day``: the day the customer asked for; the pair is that day's, or the first
    open day's after it (Sunday, a closed or a full day). ``avoid``: days they ruled
    out ("I am busy today"), never offered."""
    every = [
        slot
        for slot in free_slots(now, closed_dates, taken, count=_EVERY_SLOT)
        if slot.date() not in avoid and (day is None or slot.date() >= day)
    ]
    if not every:
        return []
    first = every[0]
    later = [slot for slot in every[1:] if slot.date() == first.date() and slot - first >= OFFER_GAP]
    other_day = [slot for slot in every[1:] if slot.date() != first.date()]
    if later:
        return [first, later[0]]
    if other_day:
        return [first, other_day[0]]
    return every[:2]


def slot_line(start: dt.datetime, now: dt.datetime | None = None) -> str:
    """'Mon 2026-10-12 14:30 (today 2:30 PM)': one FREE SLOTS line of the model's context."""
    local = start.astimezone(DUBAI)
    today = now_dubai(now).date()
    tag = "today" if local.date() == today else ("tomorrow" if local.date() == today + dt.timedelta(days=1) else f"{local:%A}")
    return f"{local:%a %Y-%m-%d %H:%M} ({tag} {time_label(local)})"


# What day and hour a customer named ----------------------------------------------------

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹०१२३४५६७८९", "0123456789" * 3)
# The prompt's reading of a bare hour: 1 to 7 is PM, 10 or 11 AM, 12 noon; 8 and 9 are anyone's guess.
_BARE_HOURS = {1: 13, 2: 14, 3: 15, 4: 16, 5: 17, 6: 18, 7: 19, 10: 10, 11: 11, 12: 12}
_TODAY = {"today", "tonight", "tday", "aaj", "aj", "اليوم", "الليلة", "آج", "आज"}
_TOMORROW = {"tomorrow", "tomorow", "tommorow", "tommorrow", "tmrw", "tmr", "tmw", "kal", "غدا", "غداً", "بكرة", "بكره", "کل", "कल"}
_DAY_AFTER = {"parson", "parso", "parsoun", "پرسوں", "परसों"}
_WEEKDAYS = {
    0: ("monday", "mon", "peer", "pir", "somvar", "الاثنين", "الإثنين", "اثنين", "پیر", "सोमवार"),
    1: ("tuesday", "tue", "tues", "mangal", "الثلاثاء", "ثلاثاء", "منگل", "मंगलवार"),
    2: ("wednesday", "wed", "weds", "budh", "الأربعاء", "الاربعاء", "اربعاء", "بدھ", "बुधवार"),
    3: ("thursday", "thu", "thur", "thurs", "jumerat", "jumeraat", "الخميس", "خميس", "جمعرات", "गुरुवार"),
    4: ("friday", "fri", "jumma", "juma", "jummah", "الجمعة", "جمعة", "جمعہ", "शुक्रवार"),
    5: ("saturday", "sat", "السبت", "سبت", "शनिवार"),
    6: ("sunday", "sun", "itwar", "itwaar", "الأحد", "الاحد", "اتوار", "रविवार"),
}
_WEEKDAY_INDEX = {word: day for day, words in _WEEKDAYS.items() for word in words}
_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
            ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_ORDINAL = r"(\d{1,2})(?:st|nd|rd|th)?"
_DAY_MONTH = re.compile(rf"\b{_ORDINAL}\s*(?:of\s+)?([a-z]{{3,9}})\b")
_MONTH_DAY = re.compile(rf"\b([a-z]{{3,9}})\s+{_ORDINAL}\b")
_NUMERIC_DATE = re.compile(r"(?<![\d:.])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?![\d:])")
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_WORDS = re.compile(r"\w+", re.UNICODE)
_MERIDIEM_TIME = re.compile(r"(?<![\d:.])(\d{1,2})(?:[:.]([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])")
_CLOCK_TIME = re.compile(r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?![\d])")
_WORD_TIME = re.compile(
    r"(?<![\d:.])(\d{1,2})(?:[:.]([0-5]\d))?\s*(baje|bajay|bje|o'?clock|بجے|बजे|مساءً|مساءا|مساء|صباحاً|صباحا|صباح)"
)
_AT_TIME = re.compile(r"(?:\bat|@|الساعة|ساعة)\s*(\d{1,2})(?:[:.]([0-5]\d))?(?!\s*(?:a\.?m|p\.?m|\d))")
# "Tomorrow 5", "kal 5", "بكرة ٥": a bare hour right after today or tomorrow, with nothing but
# punctuation after it. Not after a weekday ("Monday 12" may be the 12th, "Saturday 2" the
# 2nd) or "tonight" (its 10 is 10 PM), and not with more after it ("Tomorrow 5 or 6" is a
# choice, "Tomorrow 2 people" names no hour).
_RELATIVE_DAYS = (_TODAY - {"tonight", "الليلة"}) | _TOMORROW | _DAY_AFTER
_DAY_HOUR = re.compile(
    r"(?<!\w)(?:" + "|".join(sorted(map(re.escape, _RELATIVE_DAYS), key=len, reverse=True)) + r")\W{1,3}(\d{1,2})(?=\W*$)"
)
_HEDGE = re.compile(
    r"\b(maybe|may be|might|perhaps|possibly|probably|not sure|i'?ll try|will try|try to|shayad|ho sakta"
    # "I may come", "we could": no promise; "May I come ...?" and "Could I come ...?" ask for the slot.
    r"|(?:i|we|he|she|they)\s+(?:may|could)|i'?ll see|we'?ll see|let'?s see|let me see|if possible|hopefully)\b"
    r"|ربما|شاید|शायद",
    re.IGNORECASE,
)
# What else makes a day and hour no promise to come at it (engine.upgrade_exact_time):
# a condition, a "no", a range or an approximate hour, or a question whether we are open or free.
_CONDITION = re.compile(r"\b(if|unless|depends|depending|agar|bashart)\b|اگر|إذا|اذا|\bلو\b|अगर|यदि", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(not|never|can'?t|cannot|won'?t|wont|don'?t|dont|doesn'?t|isn'?t|unable|busy|nahi|nahin|nhi|mat)\b"
    r"|\bلا\b|\bلن\b|\bمش\b|\bما\s+(?:أقدر|اقدر|أستطيع|استطيع)|نہیں|\bنہ\b|नहीं",
    re.IGNORECASE,
)
# "No problem", "not an issue": a reassurance, not a "no" ("Thursday is not a problem").
_NO_PROBLEM = re.compile(
    r"\b(?:no|not a|not an|not any)\s+(?:problem|problems|issue|issues|worries|worry)\b"
    r"|\bkoi\s+(?:baat|masla|masala|problem|issue)\s+(?:nahi|nahin|nhi)\b"
    r"|لا مشكلة|مش مشكلة|ما في مشكلة|ما فيه مشكلة|کوئی بات نہیں|کوئی مسئلہ نہیں|कोई बात नहीं|कोई दिक्कत नहीं|कोई समस्या नहीं",
    re.IGNORECASE,
)


def without_no_problem(text: str) -> str:
    """The words without their "no problem"s, which say yes, not no."""
    return _NO_PROBLEM.sub(" ", str(text or ""))
# An hour after "around", "from", "by" and the like: one or two digits that end there
# ("around 5", "after 5:30"), or a number word. Not a size, a price or a year: "around
# 400 sq ft", "budget about 50k", "from 33,000", "by 2027" made a plain booking look
# like no promise (probe-leadai-turn, 2026-10-14).
_HOUR_AHEAD = (
    r"(?:\d{1,2}(?::\d\d)?(?![\d:])(?![.,]\d)"
    r"|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon)\b)"
    r"(?!\s*(?:sq\b|sq\.|sqft|square|ft\b|feet|foot|aed|dhs?\b|dirhams?|k\b|%|percent|years?\b|yrs?\b"
    r"|months?\b|weeks?\b|days?\b|people|persons?|units?\b|shops?\b|cheques?|checks?\b))"
)
_RANGE = re.compile(
    rf"\b(?:after|before|from|by|till|until|untill|around|about|approx(?:imately)?|roughly|between|taqreeban|lagbhag)\s+{_HOUR_AHEAD}"
    r"|\b\d{1,2}(?::\d\d)?\s*(?:-|–|to)\s*\d{1,2}(?::\d\d)?\s*(?:[ap]\.?m\.?|baje|bje|o'?clock)"
    r"|\d\s*(?::\d\d)?\s*(?:[ap]\.?m\.?)?\s*(?:onwards?|or later|or so|latest|ish)\b"
    r"|\d\s*(?:baje|bajay|bje|بجے|बजे)?\s*(?:ke baad|ke bad|se pehle|se pahle|tak|ke aas ?paas)\b"
    r"|\d\s*(?:بجے)?\s*(?:کے بعد|سے پہلے|تک)|\d\s*(?:बजे)?\s*(?:के बाद|से पहले|तक)|लगभग\s*\d"
    r"|(?:بعد|قبل|حوالي|حوالى|تقريبا|تقريباً)\s*(?:الساعة\s*)?\d|\d\s*(?:تقريبا|تقريباً)",
    re.IGNORECASE,
)
_OPEN_OR_FREE = re.compile(
    # "Are you open", "open tomorrow": our office. Not "to open" or "open a shop / my
    # business / the licence": a shop customer opening theirs.
    r"\b(?<!to\s)open\b(?!\s+(?:a|an|my|the|our|new|shop|business|store|company|licen[cs]e|branch)\b)"
    r"|\b(free|available|availability|vacant|khula|khule|khuli)\b|مفتوح|متاح|متوفر|فاضي|کھلا|کھلے|خالی|खुला|खुले|उपलब्ध|खाली",
    re.IGNORECASE,
)


def _plain_text(text: str) -> str:
    return str(text or "").translate(_DIGITS).lower().replace("’", "'")


def _year_date(year: int | None, month: int, day: int, today: dt.date) -> dt.date | None:
    """A day and month the customer wrote, in the year it is next (or the year they gave)."""
    try:
        if year:
            return dt.date(year if year > 99 else 2000 + year, month, day)
        candidate = dt.date(today.year, month, day)
    except ValueError:
        return None
    if candidate < today - dt.timedelta(days=1):
        try:
            candidate = dt.date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def named_days(text: str, now: dt.datetime | None = None) -> set[dt.date]:
    """The days a customer's own words name: today, tomorrow, a weekday (its next
    one, and the one a week later), or a date. Empty when they name none."""
    raw = _plain_text(text)
    today = now_dubai(now).date()
    days: set[dt.date] = set()
    words = _WORDS.findall(raw)
    for word in words:
        if word in _TODAY:
            days.add(today)
        elif word in _TOMORROW:
            days.add(today + dt.timedelta(days=1))
        elif word in _DAY_AFTER:
            days.add(today + dt.timedelta(days=2))
        elif word in _WEEKDAY_INDEX:
            ahead = (_WEEKDAY_INDEX[word] - today.weekday()) % 7
            days.add(today + dt.timedelta(days=ahead))
            days.add(today + dt.timedelta(days=ahead + 7))
    if "day after tomorrow" in raw or "بعد غد" in raw:
        days.add(today + dt.timedelta(days=2))
    for match in _ISO_DATE.finditer(raw):
        found = _year_date(int(match[1]), int(match[2]), int(match[3]), today)
        if found:
            days.add(found)
    for match in _NUMERIC_DATE.finditer(_ISO_DATE.sub(" ", raw)):
        found = _year_date(int(match[3]) if match[3] else None, int(match[2]), int(match[1]), today)
        if found:
            days.add(found)
    for match in _DAY_MONTH.finditer(raw):
        if match[2] in _MONTHS:
            found = _year_date(None, _MONTHS[match[2]], int(match[1]), today)
            if found:
                days.add(found)
    for match in _MONTH_DAY.finditer(raw):
        if match[1] in _MONTHS:
            found = _year_date(None, _MONTHS[match[1]], int(match[2]), today)
            if found:
                days.add(found)
    return days


def _bare(hour: int, minute: int) -> dt.time | None:
    mapped = _BARE_HOURS.get(hour)
    if mapped is None and 13 <= hour <= 23:
        mapped = hour
    return dt.time(mapped, minute) if mapped is not None else None


def named_times(text: str) -> set[dt.time]:
    """The hours a customer's own words name ("5 pm", "17:30", "kal 5 baje", "الساعة 5",
    "Tomorrow 5"), a bare hour read the way the prompt reads one (1 to 7 PM, 10 to 12 as
    said; 8 and 9 are anyone's guess). Empty when they name none."""
    raw = _plain_text(text)
    times: set[dt.time] = set()

    def blank(match) -> str:
        return " " * len(match.group(0))

    for match in _MERIDIEM_TIME.finditer(raw):
        hour, minute = int(match[1]), int(match[2] or 0)
        if 1 <= hour <= 12:
            pm = match[3].startswith("p")
            times.add(dt.time(hour % 12 + (12 if pm else 0), minute))
    # Each reading takes its words away from the next: "10:30 pm" is not also 10:30 AM.
    raw = _MERIDIEM_TIME.sub(blank, raw)
    for match in _WORD_TIME.finditer(raw):
        hour, minute, word = int(match[1]), int(match[2] or 0), match[3]
        if word.startswith("مساء") and 1 <= hour <= 11:
            times.add(dt.time(hour + 12, minute))
        elif word.startswith("صباح") and 1 <= hour <= 12:
            times.add(dt.time(hour % 12, minute))
        else:
            found = _bare(hour, minute)
            if found:
                times.add(found)
    raw = _WORD_TIME.sub(blank, raw)
    for pattern in (_CLOCK_TIME, _AT_TIME):
        for match in pattern.finditer(raw):
            found = _bare(int(match[1]), int(match[2] or 0))
            if found:
                times.add(found)
    for match in _DAY_HOUR.finditer(raw):
        hour = _BARE_HOURS.get(int(match[1]))
        if hour is not None:
            times.add(dt.time(hour, 0))
    return times


def hedged(text: str) -> bool:
    """'Maybe', 'I may come', 'I'll try', 'shayad': a time said this way is no promise to come."""
    return bool(_HEDGE.search(_plain_text(text)))


def no_promise(text: str) -> bool:
    """The day and hour in these words are no promise to come at that time: a hedge,
    a condition ("if I finish early"), a "no" ("I can't come Wednesday at 5"), a
    range or an approximate hour ("after 5 pm", "around 5"), or a question whether
    we are open or free then ("Are you open tomorrow at 5?")."""
    raw = _plain_text(text)
    if _HEDGE.search(raw) or _CONDITION.search(raw) or _NEGATION.search(without_no_problem(raw)) or _RANGE.search(raw):
        return True
    return any(mark in raw for mark in ("?", "؟", "？")) and bool(_OPEN_OR_FREE.search(raw))
