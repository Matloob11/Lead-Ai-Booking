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
# A slot is offered only this far ahead at least, then up to the next half hour: at 14:00 the first
# one offered is 15:00, at 14:20 it is 15:30 (launch review issue 17: live, slots 17 and 33 minutes
# away were offered, and one that had passed; the old lead was 15 minutes). The default of Matloob's
# open decision, one line to change.
OFFER_LEAD = dt.timedelta(minutes=60)
# The two slots an invitation names are this far apart when the day allows
# ("today at 4:00 PM or 6:00 PM").
OFFER_GAP = dt.timedelta(hours=2)
# ... and never closer than this, whoever names them: code's pair, FREE SLOTS (spaced) and the model's
# own pair (assistant/offers.py). Live, "1:00 PM or 1:30 PM" were offered as the two choices.
MIN_GAP = dt.timedelta(minutes=60)
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


def spaced(slots, gap: dt.timedelta = MIN_GAP, count: int | None = None) -> list[dt.datetime]:
    """The slots in order, each at least ``gap`` after the one kept before it (``count`` of them at most):
    FREE SLOTS as the model reads them, so any two it takes are far enough apart."""
    out: list[dt.datetime] = []
    for slot in sorted(slots):
        if not out or slot - out[-1] >= gap:
            out.append(slot)
            if count is not None and len(out) >= count:
                break
    return out


def nearest_free(start: dt.datetime, now: dt.datetime | None = None, closed_dates=(), taken=()) -> list[dt.datetime]:
    """The free starts to offer instead of a taken one: the nearest before it and the
    nearest after it, or the two nearest on the side that has any, never closer than
    MIN_GAP to each other."""
    every = free_slots(now, closed_dates, taken, count=_EVERY_SLOT)
    before = [slot for slot in every if slot < start]
    after = [slot for slot in every if slot > start]
    if before and after and after[0] - before[-1] >= MIN_GAP:
        return [before[-1], after[0]]
    if after:
        first = after[0]
        return [first, *[slot for slot in after[1:] if slot - first >= MIN_GAP][:1]]
    if before:
        last = before[-1]
        return [*[slot for slot in before[:-1] if last - slot >= MIN_GAP][-1:], last]
    return []


def offer_pair(
    now: dt.datetime | None = None, closed_dates=(), taken=(), *, day: dt.date | None = None, avoid=(), after: dt.time | None = None
) -> list[dt.datetime]:
    """The two free starts an invitation names: the first one free, and the first one
    OFFER_GAP after it the same day, else the next open day's first.

    ``day``: the day the customer asked for; the pair is that day's, or the first
    open day's after it (Sunday, a closed or a full day). ``avoid``: days they ruled
    out ("I am busy today"), never offered. ``after``: no start before this hour of
    the day, on any day ("this evening": from 5 PM; shops.yes_slots)."""
    every = [
        slot
        for slot in free_slots(now, closed_dates, taken, count=_EVERY_SLOT)
        if slot.date() not in avoid and (day is None or slot.date() >= day) and (after is None or slot.time() >= after)
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
    # The last free day within reach: its next start an hour on at least, never the half hour after.
    return [first, *[slot for slot in every[1:] if slot - first >= MIN_GAP][:1]]


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
# The hour of something else, after which they come (the launch gate's review: "Tomorrow I finish work at 6, I can come
# after that", "my duty finishes at 5 pm, then I will come", "my flight lands at 3 pm, I'll come after" were booked at
# 6, 5 and 3): work, a duty or a shift that ends, a flight that lands. Never "a day off" ("Tomorrow is my day off, I will
# come at 5 pm") ...
_ANOTHER_EVENT = re.compile(
    r"\b(?:finish|finishes|finished|finishing|duty|duties|shift|flight|lands|landing|landed|(?:i|we)\s+land)\b"
    r"|\b(?:work|job|office|class|college|school|meeting)\s+(?:ends|ending|finish\w*|is\s+over|gets\s+over|till|until)\b"
    r"|\b(?:after|from|off|leave|leaving|left)\s+(?:work|my\s+work|job|my\s+job|the\s+office|my\s+office|duty|class|college)\b"
    r"|\b(?:get|gets|getting|i'?m|i\s+am)\s+off\s+(?:at|by|from)\b|\boff\s+at\b"
    # Roman Urdu / Hindi ("duty khatam karke aaunga", "chutti ke baad", "kaam se farigh ho kar"), Arabic, Urdu, Hindi.
    r"|\bkhatam\b|\bchutti\b|\bfarigh\b|دوام|أخلص|اخلص|رحلة|طيارة|الطائرة|ڈیوٹی|چھٹی|ड्यूटी|छुट्टी",
    re.IGNORECASE,
)
# ... and what comes after an hour they named ("... at 3 pm, after that I can come", "... at 5 pm, then I will come", "...
# I'll come after"): never "Ok then I will come at 5 pm" or "Wednesday at 5 pm then", whose hour is the visit's own.
_AFTER_IT = re.compile(
    r"\bafter\s+(?:that|this|it)\b|\bthen\s+(?:i|we)\b|\bthen\s+(?:come|coming|visit|reach)\b"
    r"|\b(?:come|coming|reach|visit|be\s+there|drop\s+by|pass\s+by)\s+after\b(?!\s*\d)"
    r"|\b(?:us|is|uss|iss)\s*ke\s+(?:baad|bad)\b|\b(?:uske|iske)\s+(?:baad|bad)\b"
    r"|\b(?:phir|pher|fir)\s+(?:aa|aaun|aaunga|aaoon|aaonga|aunga|aaungi|aayenge|aaenge)\b"
    r"|بعدها|بعد\s+ذلك|\bثم\b|اس\s+کے\s+بعد|\bپھر\b|उसके\s+बाद|\bफिर\b",
    re.IGNORECASE,
)


def another_event(text: str) -> bool:
    """The hour in these words may be another event's, after which they come: work, a duty or a shift that ends, a flight
    that lands (_ANOTHER_EVENT), or an hour followed by "after that", "then I'll come" or "I'll come after" (_AFTER_IT).
    No hour of the visit (no_promise)."""
    raw = _plain_text(text)
    if _ANOTHER_EVENT.search(raw):
        return True
    return any(spoken_times(raw[: match.start()]) for match in _AFTER_IT.finditer(raw))


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


# Every hour the words name, in whatever form (engine.their_time: a shops confirm stands on the
# customer's own hour) ------------------------------------------------------------------------------
# A number word is an hour only beside a word of time ("at five", "five pm", "panch baje", "الساعة
# الخامسة", "पाँच बजे"): alone, "one" or "do" is no hour. Arabic and Devanagari words are read
# without \b, which their marks break.
_EN_HOURS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}
_ROMAN_HOURS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5, "paanch": 5, "chhe": 6, "chhay": 6, "chay": 6, "saat": 7,
    "aath": 8, "nau": 9, "das": 10, "gyarah": 11, "giyarah": 11, "barah": 12, "baarah": 12,
}
_SCRIPT_HOURS = {
    # Arabic: the hour's ordinal ("الساعة الخامسة"), or the number.
    "الواحدة": 1, "الثانية عشرة": 12, "الثانية عشر": 12, "الحادية عشرة": 11, "الحادية عشر": 11, "الثانية": 2, "الثالثة": 3,
    "الرابعة": 4, "الخامسة": 5, "السادسة": 6, "السابعة": 7, "الثامنة": 8, "التاسعة": 9, "العاشرة": 10,
    "واحدة": 1, "ثنتين": 2, "اثنين": 2, "ثلاثة": 3, "ثلاث": 3, "أربعة": 4, "اربعة": 4, "أربع": 4, "اربع": 4, "خمسة": 5, "خمس": 5,
    "ستة": 6, "سبعة": 7, "سبع": 7, "ثمانية": 8, "تسعة": 9, "عشرة": 10,
    # Urdu
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10, "گیارہ": 11, "بارہ": 12,
    # Hindi
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12,
}
_NUMBER_OF = {**_EN_HOURS, **_ROMAN_HOURS, **_SCRIPT_HOURS}


def _alternation(words) -> str:
    return "|".join(sorted(map(re.escape, words), key=len, reverse=True))


_LATIN_WORD = rf"\b(?:{_alternation([*_EN_HOURS, *_ROMAN_HOURS])})\b"
_SCRIPT_WORD = rf"(?<![\u0621-\u064a\u0671-\u06d3\u0900-\u0963])(?:{_alternation(_SCRIPT_HOURS)})(?![\u0621-\u064a\u0671-\u06d3\u0900-\u0963])"
# An hour as a number or a word, captured.
_N = rf"(\d{{1,2}}|{_LATIN_WORD}|{_SCRIPT_WORD})"
# A word for the part of the day right after an hour: it says AM or PM.
_PM = r"\s*(p\.?m\.?(?![a-z])|مساء|مساءً|مساءا|عصرا|عصراً|ليلا|ليلاً)"
_AM = r"\s*(a\.?m\.?(?![a-z])|صباحا|صباحاً|صباح)"
# "Half past" in Roman Urdu/Hindi, as people spell it (launch chat 96's voice note: "barah saadhay barah baje").
_SAADHE = "saade|sade|saadhe|sadhe|sarhe|saarhe|saadhay|sadhay|saadhey|sadhey|saday|saaday|sadey|saadey|sarhay|saarhay"
# A half or a quarter: (pattern, minutes after the hour; -15 is "a quarter to").
_HALVES = tuple(
    (re.compile(pattern), minutes)
    for pattern, minutes in (
        (rf"\bhalf\s+past\s+{_N}", 30),
        (rf"\bquarter\s+past\s+{_N}", 15),
        (rf"\bquarter\s+to\s+{_N}", -15),
        (rf"{_N}\s+thirty\b", 30),
        (rf"\b(?:{_SAADHE})\s+{_N}", 30),
        (rf"\b(?:sawa|sava)\s+{_N}", 15),
        (rf"\b(?:paune|pone|pauney)\s+{_N}", -15),
        (rf"{_N}\s*(?:و\s*نص|والنص|و\s*النصف|و\s*نصف)", 30),
        (rf"{_N}\s*(?:و\s*ربع|والربع)", 15),
        (rf"{_N}\s*(?:الا|إلا)\s*ربع", -15),
        (rf"(?:ساڑھے|ساڑے)\s*{_N}", 30),
        (rf"(?<![\u0621-\u06d3])سوا\s*{_N}", 15),
        (rf"پونے\s*{_N}", -15),
        (rf"(?:साढ़े|साढे)\s*{_N}", 30),
        (rf"सवा\s*{_N}", 15),
        (rf"पौने\s*{_N}", -15),
    )
)
# One and a half, two and a half ("dedh baje", "ڈھائی بجے"): (pattern, hour, minute).
_HALF_WORDS = tuple(
    (re.compile(pattern), hour, minute)
    for pattern, hour, minute in (
        (r"\b(?:dedh|derh)\s*(?:baje|bajay|bje)\b|ڈیڑھ\s*بجے|डेढ़\s*बजे", 1, 30),
        (r"\b(?:dhai|dhaai|arhai|adhai)\s*(?:baje|bajay|bje)\b|ڈھائی\s*بجے|ढाई\s*बजे", 2, 30),
    )
)
# A number word with a word of time beside it.
_WORD_HOURS = (
    re.compile(rf"\b(?:at|around|about|by|till|until|from|after|before)\s+({_LATIN_WORD})(?!\s*-?\s*(?:shops?|types?|people|persons?|units?|cheques?|sq|aed)\b)"),
    re.compile(rf"({_LATIN_WORD})\s*(?:o'?clock|baje|bajay|bje)\b"),
    re.compile(rf"(?:الساعة|الساعه|ساعة|ساعه)\s*({_SCRIPT_WORD})"),
    re.compile(rf"({_SCRIPT_WORD})\s*(?:بجے|बजे)"),
)
_WORD_MERIDIEM = (re.compile(rf"({_LATIN_WORD}|{_SCRIPT_WORD}){_PM}"), re.compile(rf"({_LATIN_WORD}|{_SCRIPT_WORD}){_AM}"))
_NOON = re.compile(r"\b(?:noon|midday)\b")
# A number that may be an hour ("5", "at 5", "17"): one or two digits, not part of a longer number, a
# date or a range of sizes, not a count of anything ("2 shops", "450 sq ft", "5 minutes away", "1 to 4
# cheques") and not after the words that number things ("Type 1", "AED 33,000", "Shop 20").
_UNITS = (
    r"(?:sq\b|sq\.|sqft|square|ft\b|feet|foot|m2|sqm|met(?:er|re)s?\b|aed|dhs?\b|dirhams?|k\b|lakhs?|lacs?\b|thousand|hazaa?r|million|mn\b"
    r"|crore|%|percent|years?|yrs?\b|months?|weeks?|wks?\b|days?\b|nights?\b|people|persons?|pax\b|members|kids|children|adults"
    r"|units?\b|shops?\b|stores?\b|outlets?|branch(?:es)?|cheques?|checks?\b|chqs?\b|installments?|instalments?|types?\b|bhk|br\b"
    r"|bed(?:room)?s?\b|rooms?\b|cars?\b|employees|staff|workers|times\b|x\b|×|st\b|nd\b|rd\b|th\b|hours?\b|hrs?\b|h\b"
    r"|minutes?|mins?\b|ghante|ghanta|ghantay|mint\b|minat|seconds?|secs?\b"
    r"|jan(?:uary)?\b|feb(?:ruary)?\b|march\b|apr(?:il)?\b|june?\b|july?\b|aug(?:ust)?\b|sept?(?:ember)?\b|oct(?:ober)?\b"
    r"|nov(?:ember)?\b|dec(?:ember)?\b"
    r"|محل|متر|قدم|درهم|سنة|سنوات|شهر|أشهر|اشهر|يوم|أيام|ايام|شيك|ألف|الف|دقيقة|دقائق|دقايق|ساعات|ساعة|ساعتين"
    r"|دکان|فٹ|درہم|سال|مہینے|دن|ہزار|لاکھ|منٹ|گھنٹ|दुकान|फ़ीट|फीट|दिरहम|साल|महीने|दिन|हज़ार|हजार|लाख|मिनट|घंट)"
)
_DIGIT_HOUR = re.compile(
    r"(?<![\w:.,/\-+#])(\d{1,2})(?:[:.]([0-5]\d))?(?![\d])(?![:.]\d)(?!,\d{3})(?!\s*[/\-–]\s*\d)(?!\s+\d{3,})"
    rf"(?!\s*-?\s*{_UNITS})(?!\s*(?:to|-|–|or|and)\s*\d{{1,3}}\s*-?\s*{_UNITS})"
)
_NUMBERING = re.compile(
    r"(?:\b(?:type|aed|dhs?|dh|no\.?|number|num|unit|shop|cluster|building|bldg|block|floor|plot|room|office|villa|flat"
    r"|apartment|apt|level|phase|street|st\.?|road|rd\.?|gate|plan|option|step|version|ref|id|code|size|cheque)"
    r"|رقم|نوع|محل|درهم|نمبر|ٹائپ|नंबर|टाइप)\s*$"
)
# "In 1 hour", "aadhe ghante mein", "بعد ساعة", "एक घंटे में": a time from now, (pattern, minutes; None
# when a number in the words says how many hours, or with "min" how many minutes).
_AHEAD = tuple(
    (re.compile(pattern), minutes)
    for pattern, minutes in (
        (r"\b(?:in|after|within)\s+(?:half\s+an?|a\s+half|1/2)\s+(?:hour|hr)\b", 30),
        (r"\b(?:in|after|within)\s+(?:an?|one|1)\s+(?:hour|hr)\b(?!\s+and)", 60),
        (r"\b(?:in|after|within)\s+(?:an?|one|1)\s+(?:hour|hr)\s+and\s+a\s+half\b", 90),
        (r"\b(?:in|after|within)\s+(\d{1,2}|two|three)\s*(?:hours|hrs|h)\b", None),
        (r"\b(?:in|after|within)\s+(\d{1,3})\s*(?:minutes?|mins?)\b", -1),
        (r"\b(?:aadhe|adhe|aadha|adha)\s+(?:ghante|ghanta|ghantay)\s*(?:mein|me|main|mai|tak|baad|bad)\b", 30),
        (r"\b(?:ek|1)\s+(?:ghante|ghanta|ghantay)\s*(?:mein|me|main|mai|tak|baad|bad)\b", 60),
        (r"\b(?:dedh|derh)\s+(?:ghante|ghanta|ghantay)\s*(?:mein|me|main|mai|tak|baad|bad)\b", 90),
        (r"\b(\d{1,2}|do|teen)\s+(?:ghante|ghanta|ghantay)\s*(?:mein|me|main|mai|tak|baad|bad)\b", None),
        (r"\b(\d{1,3})\s*(?:minute|minutes|mint|minat|min)\s*(?:mein|me|main|mai|tak|baad|bad)\b", -1),
        (r"(?:بعد|خلال)\s*(?:نص|نصف)\s*(?:ساعة|ساعه)", 30),
        (r"(?:بعد|خلال)\s*ربع\s*(?:ساعة|ساعه)", 15),
        (r"(?:بعد|خلال)\s*(?:ساعة|ساعه)(?!\s*(?:\d|و))", 60),
        (r"(?:بعد|خلال)\s*(?:ساعة|ساعه)\s*(?:و\s*نص|ونص|والنص|و\s*نصف)", 90),
        (r"(?:بعد|خلال)\s*ساعتين", 120),
        (r"(?:بعد|خلال)\s*(\d{1,2})\s*(?:ساعات|ساعة)", None),
        (r"(?:بعد|خلال)\s*(\d{1,3})\s*(?:دقيقة|دقائق|دقايق|دقيقه)", -1),
        (r"آدھے\s*گھنٹے\s*(?:میں|تک|بعد)|आधे\s*घंटे\s*(?:में|तक|बाद)", 30),
        (r"(?:ایک|1)\s*گھنٹ(?:ے|ہ)\s*(?:میں|تک|بعد)|(?:एक|1)\s*घंटे\s*(?:में|तक|बाद)", 60),
        (r"(\d{1,3})\s*(?:منٹ|मिनट)\s*(?:میں|تک|بعد|में|तक|बाद)", -1),
    )
)
# Words only an hour has: when one is there and the hour is not read above ("quarter to six" in a
# spelling not listed, "8 baje", "at 9"), the customer still named one.
_HOUR_MARK = re.compile(
    rf"\b(?:o'?clock|oclock|baje|bajay|bje|bajey|bjy|half\s+past|quarter\s+(?:past|to)|{_SAADHE}|sawa|paune|noon|midday)\b"
    r"|\d\s*(?:a\.?m\.?|p\.?m\.?)(?![a-z])|\bat\s+\d{1,2}(?![\d,])|الساعة|الساعه|بجے|बजे|ساڑھے|پونے|साढ़े|पौने|ونص|والنصف"
)


def _hour_of(word: str) -> int | None:
    word = (word or "").strip()
    return int(word) if word.isdecimal() else _NUMBER_OF.get(word)


def _clock(hour: int, minute: int, after: str = "") -> dt.time | None:
    """An hour and a minute read as the prompt reads a bare one, or as "pm"/"مساء" (``after``) says."""
    if after:
        pm = after[0] in "pمعل"
        if not 1 <= hour <= 12:
            return None
        return dt.time(hour % 12 + (12 if pm else 0), minute)
    return _bare(hour, minute)


def _read_halves(raw: str) -> tuple[set[dt.time], str]:
    """The halves and quarters the words name ("half past 5", "saade 5 baje", "٥ ونص"), and the
    words without them."""
    times: set[dt.time] = set()
    for pattern, minutes in _HALVES:
        def take(match, minutes=minutes) -> str:
            hour = _hour_of(match[1])
            if hour is not None and 1 <= hour <= 12:
                if minutes < 0:
                    hour, minute = (hour - 1) or 12, 60 + minutes
                else:
                    minute = minutes
                tail = raw[match.end() : match.end() + 12]
                meridiem = re.match(_PM, tail) or re.match(_AM, tail)
                found = _clock(hour, minute, meridiem[1] if meridiem else "")
                if found:
                    times.add(found)
            return " " * len(match.group(0))

        raw = pattern.sub(take, raw)
    for pattern, hour, minute in _HALF_WORDS:
        if pattern.search(raw):
            times.add(_bare(hour, minute))
            raw = pattern.sub(lambda match: " " * len(match.group(0)), raw)
    return times, raw


def _read_words(raw: str) -> tuple[set[dt.time], str]:
    """The number words with a word of time beside them, and the words without them."""
    times: set[dt.time] = set()

    def blank(match) -> str:
        return " " * len(match.group(0))

    for pattern, pm in ((_WORD_MERIDIEM[0], "p"), (_WORD_MERIDIEM[1], "a")):
        for match in pattern.finditer(raw):
            hour = _hour_of(match[1])
            found = _clock(hour, 0, "p" if pm == "p" else "a") if hour else None
            if found:
                times.add(found)
        raw = pattern.sub(blank, raw)
    for pattern in _WORD_HOURS:
        for match in pattern.finditer(raw):
            hour = _hour_of(match[1])
            found = _bare(hour, 0) if hour else None
            if found:
                times.add(found)
        raw = pattern.sub(blank, raw)
    if _NOON.search(raw):
        times.add(dt.time(12, 0))
        raw = _NOON.sub(blank, raw)
    return times, raw


def _blank_named(raw: str) -> str:
    """The words without what named_times reads ("5 pm", "17:30", "5 baje", "at 5", "tomorrow 5")."""
    for pattern in (_MERIDIEM_TIME, _WORD_TIME, _CLOCK_TIME, _AT_TIME, _DAY_HOUR):
        raw = pattern.sub(lambda match: " " * len(match.group(0)), raw)
    return raw


def _digit_hours(raw: str, *, every: bool = False) -> set:
    """The numbers left in the words that may be an hour, as times (``every``: the hours themselves,
    8 and 9 too, which a bare number leaves to anyone's guess)."""
    found = set()
    for match in _DIGIT_HOUR.finditer(raw):
        if _NUMBERING.search(raw[: match.start()]):
            continue
        hour, minute = int(match[1]), int(match[2] or 0)
        if every:
            if 1 <= hour <= 23:
                found.add(hour)
            continue
        at = _bare(hour, minute)
        if at:
            found.add(at)
    return found


def _readings(text: str) -> tuple[set[dt.time], str]:
    """(every hour the words name exactly but their bare numbers, the words left)."""
    raw = _plain_text(text)
    times, raw = _read_halves(raw)
    times |= named_times(raw)
    raw = _blank_named(raw)
    words, raw = _read_words(raw)
    return times | words, raw


def spoken_times(text: str) -> set[dt.time]:
    """The hours the words name in a form that is plainly a time (said_times without its bare
    numbers: "at five" and "kal saade 5 baje" are hours, a "2" alone may be anything)."""
    return _readings(text)[0]


def said_times(text: str) -> set[dt.time]:
    """Every hour the customer's words name, in any of the forms they write one: as named_times
    reads it ("5 pm", "17:30", "kal 5 baje", "الساعة 5"), a half or a quarter ("half past 5",
    "saade 5 baje", "٥ ونص"), a number word beside a word of time ("at five", "الساعة الخامسة
    مساءً", "पाँच बजे"), or a number that may be an hour ("5", "Does 5 work?"), read the way the
    prompt reads a bare one. Never "450 sq ft", "2 shops", "Type 1" or "AED 33,000"."""
    times, rest = _readings(text)
    return times | _digit_hours(rest)


def hours_ahead(text: str) -> list[dt.timedelta]:
    """The times from now the words name ("in 1 hour", "in 20 minutes", "aadhe ghante mein", "بعد
    ساعة", "एक घंटे में")."""
    raw = _plain_text(text)
    found = []
    for pattern, minutes in _AHEAD:
        for match in pattern.finditer(raw):
            if minutes is not None and minutes > 0:
                found.append(dt.timedelta(minutes=minutes))
                continue
            count = _hour_of(match[1]) or 0  # "2", "two", "do"
            if count:
                found.append(dt.timedelta(minutes=count) if minutes == -1 else dt.timedelta(hours=count))
    return found


def marks_hour(text: str) -> bool:
    """The words name an hour, read above or not: a word only an hour has ("o'clock", "baje",
    "الساعة"), or a number that may be one, 8 and 9 too ("8 baje", "at 9")."""
    raw = _plain_text(text)
    if _HOUR_MARK.search(raw):
        return True
    times, rest = _readings(text)
    return bool(times) or bool(_digit_hours(rest, every=True))


def names_hour(text: str, start: dt.datetime) -> bool:
    """The words name this start's hour, in any form said_times reads ("5", "17", "4:30", "five
    pm", "saade 5 baje"). "450 sq ft" names no hour."""
    return start.astimezone(DUBAI).time() in said_times(text)


# "10 AM to 8 PM", "subah 10 se raat 8 baje", "من 10 صباحاً حتى 8 مساءً": the opening hours, not an offer.
_OPENING_HOURS = re.compile(
    r"10\s*(?::00)?\s*(?:am\b|a\.m\.|baje\b|صباحاً|صباحا)?\s*(?:to|until|till|se|-|–|حتى|إلى|الى|سے|से)\s*"
    r"(?:raat\s*|رات\s*|रात\s*)?8(?::00)?\s*(?:pm\b|p\.m\.|baje\b|مساءً|مساء|بجے|बजे)?",
    re.IGNORECASE,
)


def offered_starts(text: str) -> set[dt.time]:
    """The exact starts a message of ours offers ("today at 2:30 PM or 4:30 PM — which is
    better?", "Would tomorrow at 5 PM work?", "هل يناسبك غداً الساعة الخامسة مساءً؟"), within the
    hours a visit may start, the opening hours ("10 AM to 8 PM") left out; else the one bare hour
    it names ("Does 5 work for you tomorrow?", "Kal shaam 5 ka slot book kar doon?"), never a
    count, a size or a price ("I picked 2 Type 1 shops", "only 5 minutes away")."""
    times, rest = _readings(_OPENING_HOURS.sub(" ", _plain_text(text)))
    if not times:
        loose = _digit_hours(rest)
        times = loose if len(loose) == 1 else set()
    return {at for at in times if OPEN <= at <= LATEST_START}


def hedged(text: str) -> bool:
    """'Maybe', 'I may come', 'I'll try', 'shayad': a time said this way is no promise to come."""
    return bool(_HEDGE.search(_plain_text(text)))


def no_promise(text: str) -> bool:
    """The day and hour in these words are no promise to come at that time: a hedge,
    a condition ("if I finish early"), a "no" ("I can't come Wednesday at 5"), a
    range or an approximate hour ("after 5 pm", "around 5"), the hour of something
    else they come after ("I finish work at 6, I can come after that": another_event),
    or a question whether we are open or free then ("Are you open tomorrow at 5?")."""
    raw = _plain_text(text)
    if _HEDGE.search(raw) or _CONDITION.search(raw) or _NEGATION.search(without_no_problem(raw)) or _RANGE.search(raw):
        return True
    if another_event(raw):
        return True
    return any(mark in raw for mark in ("?", "؟", "？")) and bool(_OPEN_OR_FREE.search(raw))


# A window of time they will come in (launch review issue 6) -----------------------------------------------------
# Chat 96 said, in a voice note at 11:10, he would come and check at "barah saadhay barah baje" (12, half past 12),
# and was never booked: T18 (engine.upgrade_exact_time) books one exact hour only, and reads a range as no promise.

# The widest window that is still one plan to come ("12-12:30", "5 or 6"); wider ("11 to 2") is a choice.
WINDOW_MAX = dt.timedelta(hours=1)
_SPAN = re.compile(
    r"(?<![\d:.,])(\d{1,2})(?:[:.]([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?\s*"
    r"(?:-|–|—|to|till|until|or|ya|se|and|aur|/|او|أو|یا|या|से)\s*"
    r"(\d{1,2})(?:[:.]([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d:])"
    rf"(?!\s*-?\s*{_UNITS})"
)


def _span_readings(hour: int, minute: int, meridiem: str) -> list[dt.time]:
    """The readings of one end of a span: as its am/pm says; a bare hour the prompt's way first, then the
    other half of the day ("11.30 - 12 PM": the 11.30 is AM)."""
    if not 0 <= minute <= 59:
        return []
    if meridiem:
        return [dt.time(hour % 12 + (12 if meridiem.startswith("p") else 0), minute)] if 1 <= hour <= 12 else []
    if 13 <= hour <= 23:
        return [dt.time(hour, minute)]
    if not 1 <= hour <= 12:
        return []
    readings = [dt.time(12, minute)] if hour == 12 else [dt.time(hour, minute), dt.time(hour + 12, minute)]
    bare = _bare(hour, minute)
    return sorted(readings, key=lambda at: at != bare)


def _fits(start: dt.time, end: dt.time) -> bool:
    gap = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    return 0 < gap <= WINDOW_MAX.total_seconds() / 60 and OPEN <= start <= LATEST_START


def _span_is_hours(raw: str, match) -> bool:
    """A span of numbers is hours only with a mark of an hour on it (review 2d: "3 or 4 of us", "2 ya 3 dukaan
    chahiye", "2-3 dost" are counts, and were booked as windows): minutes ("12-12:30", "11.30 - 12"), am or pm,
    "baje" or "o'clock" right after it, or "at", "between", "from", "around" or "الساعة" right before it."""
    if match[2] or match[3] or match[5] or match[6]:
        return True
    return bool(_SPAN_AFTER.match(raw, match.end()) or _SPAN_BEFORE.search(raw[: match.start()]))


_SPAN_AFTER = re.compile(r"\s*(?:baje|bajay|bje|bajey|bjy|o'?clock|oclock|بجے|बजे)")
_SPAN_BEFORE = re.compile(r"(?:\b(?:at|between|from|around|about|by|till|until)|الساعة|الساعه|ساعة)\s*$")


def named_window(text: str) -> tuple[dt.time, dt.time] | None:
    """The window of time the words give for coming, as (start, end): no wider than WINDOW_MAX, starting
    within the hours a visit may start. A span of numbers that carries a mark of an hour (_span_is_hours:
    "12-12:30", "11.30 - 12 PM", "between 12 and 12:30", "at 5 or 6", "12 ya 12:30 baje"), or two hours
    named in words ("barah saadhay barah baje", "بارہ ساڑھے بارہ بجے"). None for one hour (T18's to book), a
    wider span ("1 to 4 cheques", "11 to 2"), a count ("3 or 4 of us", "2 ya 3 dukaan"), a size or a date."""
    raw = _plain_text(text)
    for match in _SPAN.finditer(raw):
        if _NUMBERING.search(raw[: match.start()]):
            continue  # "Type 1 or 2", "Shop 20 - 21"
        if not _span_is_hours(raw, match):
            continue  # "3 or 4 of us", "2-3 dost": a count of something, not two hours
        first, second = match[3] or "", match[6] or ""
        starts = _span_readings(int(match[1]), int(match[2] or 0), first)
        if not first and second:
            # "11.30 - 12 PM": the end's half of the day first, then the other one.
            starts = _span_readings(int(match[1]), int(match[2] or 0), second) + _span_readings(int(match[1]), int(match[2] or 0), "")
        ends = _span_readings(int(match[4]), int(match[5] or 0), second or first)
        for start in starts:
            for end in ends:
                if _fits(start, end):
                    return start, end
    times = sorted(spoken_times(text))
    if len(times) == 2 and _fits(*times):
        return times[0], times[1]
    return None


def window_promise(text: str) -> bool:
    """A window said as a plan to come: no hedge, condition, "no" or deferral, and no question whether we are
    open (no_promise without its reading of a range, which is the window itself)."""
    raw = _plain_text(text)
    if _HEDGE.search(raw) or _CONDITION.search(raw) or _NEGATION.search(without_no_problem(raw)):
        return False
    return not (any(mark in raw for mark in ("?", "؟", "？")) and bool(_OPEN_OR_FREE.search(raw)))
