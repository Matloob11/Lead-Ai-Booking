"""What a reply offers: the slots it names, the invitation it counts and our office's location (launch review
2026-10-15, issues 17 and 24).

- Slots (issue 17): every slot offered is at least hours.OFFER_LEAD (an hour) from now and at least
  hours.MIN_GAP (an hour) from the other one, and never in the past. Code's own pairs follow from hours.py;
  the model's own times are read here (``fix_times``): live, chat 100 was offered "today at 1:00 PM or 1:30 PM"
  at 12:43, chat 62 "11:00 AM or 11:30 AM" at 10:27, and chat 96 "12:30 PM" at 12:35, five minutes after it had
  passed. A shops reply whose times are past, too soon, taken, on a closed day or half an hour apart has its
  slot sentences replaced by the two nearest valid free slots, in code's words (shops.slot_offer); a discovery
  question asked before them (chat 88's licence question) keeps its place, as it would beside valid times. A
  time the customer named themselves, or the visit's own, may be sooner than the lead (it is theirs), never past.
  Our opening hours said as a fact ("We're open until 7:30 PM today") offer nothing (states_hours); and after two
  invitations a slot of ours goes, in any words (pushes_visit, read by engine.settle).
- The invitation count (issue 24): a reply that ends up offering two slots is an invitation, also when code
  wrote them (an open "when" rewritten: chat 81 stayed at 0 invitations after one, 91 and 96 at 1 after two),
  unless they had agreed to come or we offered the same slots again (engine.reoffered); and one the reply
  filter cut as a second question is none (``invitation_cut``: chat 88 was counted twice after one), with no
  Maps link under what is left (chat 119's bare link under "for yourself, or for a client?").
- Our location goes with its label (``with_location``: "Our office location: <link>"), so it never reads as
  the shops' location.

Plain functions on plain data: the eval (leadai_eval) calls the same ones.
"""

from __future__ import annotations

import datetime as dt
import re

from . import filters, hours, rules, shop_flow, shops

# Only a shops chat's times are checked (engine.settle): the general playbook's prompt has no FREE SLOTS and
# offers its own times, "7 PM or 7:30 PM" among its examples.
TIMES = "times"  # what answer["trimmed"] says when the times were replaced

# The label our location goes out with, in the customer's language (every playbook).
LOCATION_LABEL = {
    "en": "Our office location:",
    "ar": "موقع مكتبنا:",
    "ur_latin": "Hamare office ki location:",
    "ur": "ہمارے آفس کی لوکیشن:",
    "hi_latin": "Hamare office ki location:",
    "hi": "हमारे ऑफ़िस की लोकेशन:",
}


def with_location(text: str, appended: str, language: str) -> str:
    """The reply with our office's Maps link (or address) under it, labelled as our office's."""
    if not appended:
        return text
    label = LOCATION_LABEL.get(language) or LOCATION_LABEL["en"]
    return f"{text}\n{label} {appended}" if text else f"{label} {appended}"


# The model's own times ------------------------------------------------------------------------------------


def _first_days(days: set) -> set:
    """A weekday's next date only (hours.named_days also gives the one a week later)."""
    return {day for day in days if day - dt.timedelta(days=7) not in days}


# A sentence about a call ("Our agent will call you at 11:30") offers no visit (people.settle reads it).
_CALL = re.compile(r"\b(?:call|calls|calling|phone|ring)\b|اتصل|اتصال|مكالمة|کال|فون|कॉल|फ़ोन|फोन", re.IGNORECASE)
# Our opening hours said as a fact ("We're open until 7:30 PM today", "Our office closes at 8 PM", "Hamara office
# 7:30 PM tak khula hai"): no visit offered, unless the sentence asks, or offers a slot or a visit as well. Read as an
# offer, "open until 7:30 PM" at 7 PM was "too soon" and became two slots tomorrow, an invitation nobody made.
_OUR_HOURS = re.compile(
    r"\b(?:open|opens|close|closes|closing|closed|until|till|timings?|working\s+hours|office\s+hours)\b|\bkhul\w*|\bband\s+ho\w*"
    r"|يفتح|نفتح|مفتوح|يغلق|نغلق|مغلق|کھل|بند|खुल|बंद",
    re.IGNORECASE,
)
_OFFER_WORDS = re.compile(
    r"\b(?:slots?|hold|book|booking|reserve|come|coming|visit|viewing|meet|see\s+you|works?|suits?|better|prefer|confirm)\b"
    r"|\brakh\w*|\baa\s+sakt\w*|\baaiye\b|\btashreef\b|موعد|زيارة|احجز|أحجز|يناسب|سلاٹ|آ\s*سکت|बुक|स्लॉट|आ\s*सकत",
    re.IGNORECASE,
)


def states_hours(sentence: str) -> bool:
    """The sentence gives our opening hours and offers nothing: no question, no slot, no visit (_OFFER_WORDS)."""
    text = sentence or ""
    return bool(_OUR_HOURS.search(text)) and not _OFFER_WORDS.search(text) and not any(mark in text for mark in filters.QUESTION_MARKS)


def offered(reply: str, now) -> list[tuple[str, set, set]]:
    """Each sentence of the reply that offers exact starts for a visit: (the sentence, the days it may mean,
    its times). A sentence's days are its own (today, tomorrow, a weekday, a date), else the reply's, else
    today. A sentence about a call, or one that gives our opening hours (states_hours), is none."""
    today = hours.now_dubai(now).date()
    reply_days = _first_days(hours.named_days(reply or "", now))
    out = []
    for sentence in filters.split_sentences(reply):
        times = hours.offered_starts(sentence)
        if times and not _CALL.search(sentence) and not states_hours(sentence):
            days = _first_days(hours.named_days(sentence, now)) or reply_days or {today}
            out.append((sentence, days, times))
    return out


def offered_again(text: str, now, closed_dates=(), taken=()) -> list[dt.datetime]:
    """The two exact starts our message offered ("I can hold a slot at 4:00 PM or 6:00 PM.", the morning nudge), when both
    may still be offered (_valid: ahead by the lead, on an open day, no other client's) an hour apart at least: a plain yes
    to it is asked about those two again (engine.nudge_yes); else []."""
    starts = sorted({_start(min(days), at) for _, days, times in offered(text, now) for at in times})
    if len(starts) != 2 or starts[1] - starts[0] < hours.MIN_GAP:
        return []
    if not all(_valid(start, now, closed_dates, taken, theirs=False, booked=None) for start in starts):
        return []
    return starts


def pushes_visit(sentence: str, theirs=()) -> bool:
    """The sentence offers a time for a visit that is ours, not one the customer named (``theirs``: theirs_from):
    a third invitation after two (engine.settle drops it with filters.drop_invitations, which reads only words of
    a visit: "I can hold a slot for you today at 4:00 PM or 6:00 PM — which is better?" names none)."""
    times = hours.offered_starts(sentence or "")
    if not times or _CALL.search(sentence or "") or states_hours(sentence or ""):
        return False
    return bool(times - set(theirs or ()))


def _start(day: dt.date, at: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, at, tzinfo=hours.DUBAI)


def _valid(start: dt.datetime, now, closed_dates, taken, *, theirs: bool, booked, soon: bool = False) -> bool:
    """A start a reply may name: the visit's own; one the customer named, unless it has passed (the reply may
    say it is taken); else ahead of now by the lead at least (``soon``: they want to come now: any time
    ahead), on an open day within three weeks, and no other client's."""
    if booked is not None and start == booked:
        return True
    if start <= now:
        return False
    if theirs:
        return True
    if not soon and start < now + hours.OFFER_LEAD:
        return False
    if not hours.is_open_day(start.date(), closed_dates) or start > now + hours.MAX_AHEAD:
        return False
    return not hours.is_taken(start, taken)


def theirs_from(texts, now=None) -> set[dt.time]:
    """The hours the customer named lately (their words, the burst among them): a slot at one of these is
    theirs. A time from now ("in 30 minutes") gives the half hours either side of it."""
    found: set[dt.time] = set()
    for text in texts or ():
        found |= hours.said_times(text or "")
        window = hours.named_window(text or "")
        if window:
            found |= set(window)
        if now is not None:
            for gap in hours.hours_ahead(text or ""):
                moment = hours.now_dubai(now) + gap
                floor = moment.replace(minute=0 if moment.minute < 30 else 30, second=0, microsecond=0)
                found |= {floor.time(), (floor + hours.SLOT).time()}
    return found


def wrong_times(reply: str, now, closed_dates=(), taken=(), *, theirs=(), booked=None, soon: bool = False) -> list[dt.datetime] | None:
    """The two slots to offer instead of the reply's own times, or None when its times may go: every time it
    offers is valid on a day it may mean (_valid), and two of ours on one day are MIN_GAP apart at least.
    ``theirs``: the hours the customer named (theirs_from); ``booked``: the open visit's start; ``soon``:
    they want to come now, so a time sooner than the lead may go."""
    rows = offered(reply, now)
    if not rows:
        return None
    theirs = set(theirs or ())
    bad, ours_by_day = False, {}
    for _, days, times in rows:
        for at in times:
            mine = at not in theirs
            good = [
                day for day in sorted(days) if _valid(_start(day, at), now, closed_dates, taken, theirs=not mine, booked=booked, soon=soon)
            ]
            if not good:
                bad = True
            elif mine and not (booked is not None and _start(good[0], at) == booked):
                ours_by_day.setdefault(frozenset(days), set()).add(_start(good[0], at))
    if not bad:
        # Spacing, when every offer reads one day: two of our own an hour apart at least.
        if len(ours_by_day) == 1:
            ours = sorted(next(iter(ours_by_day.values())))
            bad = any(later - earlier < hours.MIN_GAP for earlier, later in zip(ours, ours[1:]))
        if not bad:
            return None
        anchor = min(next(iter(ours_by_day.values())))
        pair = hours.offer_pair(now, closed_dates, [*taken, *([booked] if booked else [])], day=anchor.date(), after=anchor.time())
        return pair or None
    today = hours.now_dubai(now).date()
    first_day = min(min(days) for _, days, _ in rows)
    pair = hours.offer_pair(now, closed_dates, [*taken, *([booked] if booked else [])], day=first_day if first_day >= today else None)
    return pair or None


# A discovery question of ours (the licence, the business, the size or budget; who the shop is for is
# shop_flow.asks_for_whom), as against one that leads in to the times ("Kya aap dekhna chahenge?").
_DISCOVERY = re.compile(
    r"licen[cs]e|\bDED\b|trakhees|\bbusiness\b|\bactivity\b|\bsize\b|\bbudget\b|\bsq\s*\.?\s*ft\b|\bsquare\s+f(?:ee|oo)t\b|\bkaro?bar\b"
    r"|رخصة|نشاط|مساحة|ميزانية|لائسنس|کاروبار|سائز|بجٹ|लाइसेंस|व्यापार|बिज़नेस|बिजनेस|साइज़|साइज|बजट",
    re.IGNORECASE,
)


def _stays(sentence: str, before_times: bool) -> bool:
    """A sentence of a reply whose times are replaced that stays: any but a question; and a discovery question
    asked before the times (the licence, the business, the size or budget, who the shop is for). That one stays
    first, as it would beside valid times: the reply filter then cuts code's slots as a second question
    (filters.clean_reply), and invitation_cut their count and our location. Any other question goes with them."""
    if not any(mark in sentence for mark in filters.QUESTION_MARKS):
        return True
    if not before_times or filters.is_open_when(sentence) or filters.is_invitation(sentence):
        return False
    return bool(_DISCOVERY.search(sentence)) or shop_flow.asks_for_whom(sentence)


def fix_times(answer: dict, now, closed_dates=(), taken=(), *, theirs=(), booked=None, soon: bool = False, before: str = "") -> bool:
    """A shops reply whose own times may not go (wrong_times): its sentences that name them, and the questions
    that lead in to them or follow them, become code's two nearest valid free slots ("I can hold a slot for you
    today at 3:00 PM or 5:00 PM — which is better?"), in other words when ``before`` (our side's last words) said
    that very sentence; a discovery question asked before them keeps its place (_stays). True when the reply
    changed (live and in the eval, engine.settle). Never while the answer hands the chat to a person or opts out
    (no slots go then)."""
    if answer.get("handover", {}).get("needed") or answer.get("opt_out", "none") != "none":
        return False
    reply = answer.get("reply") or ""
    pair = wrong_times(reply, now, closed_dates, taken, theirs=theirs, booked=booked, soon=soon)
    if not pair:
        return False
    timed = {sentence for sentence, _, _ in offered(reply, now)}
    sentences = filters.split_sentences(reply)
    first = next((index for index, sentence in enumerate(sentences) if sentence in timed), len(sentences))
    kept = [sentence for index, sentence in enumerate(sentences) if sentence not in timed and _stays(sentence, index < first)]
    line = shops.slot_offer(answer["language"], pair, now)
    if before and filters.said_before(line, [before]):
        again = shops.slot_offer(answer["language"], pair, now, again=True)
        line = line if filters.said_before(again, [before]) else again  # never the same sentence twice in a chat
    answer["reply"] = " ".join([*kept, line])
    answer["send"] = True
    return True


# The invitation count ---------------------------------------------------------------------------------------


def offers_slots(text: str) -> bool:
    """The text offers a choice of slots: two exact starts or more, and a question ("... 3:00 PM or 5:00 PM —
    which is better?"). One time alone ("We're open until 7:30 PM") is no invitation."""
    return len(hours.offered_starts(text or "")) >= 2 and any(mark in (text or "") for mark in filters.QUESTION_MARKS)


def count_invitation(answer: dict, *, agreed: bool, reoffer: bool) -> bool:
    """A shops reply that offers slots, in the model's words or code's, counts as an invitation, unless they
    agreed to come or the slots are the ones we just offered again. True when the count changed."""
    if agreed or reoffer or answer.get("converted") or answer["invited_to_meeting"] or not offers_slots(answer["reply"]):
        return False
    answer["invited_to_meeting"] = True
    return True


def _invites(text: str) -> bool:
    sentences = filters.split_sentences(text)
    return any(filters.offers_time(s) or filters.is_open_when(s) or filters.is_invitation(s) for s in sentences)


def invitation_cut(answer: dict, before: str, after: str, asked: str) -> bool:
    """The reply filter (filters.clean_reply) cut the invitation as a second question: what goes out invites
    no one, so no invitation is counted, and our location goes only when they asked for it (asks_location_now:
    chat 88's "Preferable Location - France" asked for nothing). True when the flags changed."""
    if not (answer["invited_to_meeting"] or answer["share_office_location"]):
        return False
    if not _invites(before) or _invites(after):
        return False
    changed = answer["invited_to_meeting"]
    answer["invited_to_meeting"] = False
    if answer["share_office_location"] and not asks_location_now(asked):
        answer["share_office_location"] = False
        changed = True
    return changed


# They ask us for our location ("send me the location", "address please"), not only name the word.
_LOCATION_REQUEST = re.compile(
    r"\b(?:send|share|give|drop|forward)\b[^.?!]{0,25}\b(?:location|address|map|maps|pin)\b"
    r"|\b(?:location|address|map|pin)\b[^.?!]{0,12}\b(?:send|share|please|pls|plz|bhej\w*|dein|chahiye)\b"
    r"|^\W*(?:location|address|map|maps|pin)\W*$",
    re.IGNORECASE,
)


def requests_location(said: str) -> bool:
    """Their words ask us for the location in so many words ("send me the location", "Location")."""
    return bool(_LOCATION_REQUEST.search(str(said or "")))


def asks_location_now(said: str) -> bool:
    """Their words ask for our location or the way to us now ("Location?", "send me the location", "where is your
    office?"), not only name the word ("Preferable Location - France", "no good location")."""
    said = str(said or "")
    if filters.asks_the_way(said):
        return True
    return filters.asks_for_location(said) and (rules.asks_question(said) or requests_location(said))


# A clause that asks where we are, in itself ("Location?", "Your address please", "What is the location?", "Where are you
# located?", "location kahan hai?", "وين الموقع؟", "Location of the shops?", "Directions to the office?": the gate's reading
# took both), never one that only names the word ("Is the location good for a restaurant?", "Do you have shops in another
# location like Al Quoz?", "Is there parking near the location?", "Is the location of the shops good for a restaurant?").
_WHERE_ASKED = re.compile(
    r"^\W*(?:(?:the|your|ur|ya|our|office|exact|full|shop|shops)\s+){0,2}(?:location|locations|address|map|maps|pin|directions?)"
    r"(?:\s+(?:of|for|to)\s+(?:the\s+|your\s+|ur\s+|our\s+|this\s+|that\s+)?(?:shops?|office|units?|place|property|building|it|you))?"
    r"(?:\s+(?:please|pls|plz|sir|bro|dear|bhai|ji))?\W*$"
    r"|\b(?:what(?:'?s|\s+is)|whats|where(?:'?s|\s+is)|wheres)\s+(?:the\s+|your\s+|ur\s+|ya\s+|exact\s+|office\s+){0,3}(?:location|address)\b"
    r"|\bwhere\s+(?:are\s+(?:you|u)|r\s+u|is\s+(?:it|this|that|the\s+office))\s+located\b|\blocated\s+where\b"
    r"|\b(?:location|address)\s+(?:kahan|kidhar|kya)\b|\b(?:kahan|kidhar)\b[^.?!]{0,15}\b(?:location|address)\b"
    r"|(?:وين|أين|اين|فين|ما\s+هو|شو)\s+(?:الموقع|العنوان|موقعكم|عنوانكم|اللوكيشن)|^\W*(?:الموقع|العنوان|لوكيشن|اللوكيشن)\W*$"
    r"|(?:لوکیشن|ایڈریس|پتہ)\s+(?:کیا|بھیج|بتا)|^\W*(?:لوکیشن|ایڈریس)\W*$|(?:लोकेशन|एड्रेस|पता)\s+(?:क्या|भेज|बता)|^\W*(?:लोकेशन|एड्रेस)\W*$",
    re.IGNORECASE,
)
_WHERE_CLAUSE = re.compile(r"[.!?؟,;:،\n]+")
_VOICE_NOTE = re.compile(r"^\s*\[voice note\]\s*", re.IGNORECASE)  # a voice note's words, as transcript.inbound_text writes them


def asks_where_we_are(texts) -> bool:
    """A clause of their words asks for our location or the way to us in itself: a request for it (requests_location:
    "send me the location", "Location"), the way (filters.asks_the_way: "where is your office?"), or a clause that asks
    where (_WHERE_ASKED: "What is the location?"); never the word in a clause that asks something else ("Is the location
    good for a restaurant?", "Location is too far for me" with "Any shop in Al Quoz?", chat 88's "Preferable Location -
    France" with "How much is type 1?"). Stricter than asks_location_now, which reads the word and any "?" in the burst
    (engine.location_invitation; the launch gate's review)."""
    for text in texts or ():
        for clause in _WHERE_CLAUSE.split(_VOICE_NOTE.sub("", str(text or "")).replace("’", "'")):
            clause = clause.strip()
            if clause and (requests_location(clause) or filters.asks_the_way(clause) or _WHERE_ASKED.search(clause)):
                return True
    return False


# Words that want another area, or object to the distance ("Do you have shops in another location?", "Location is too far
# for me"): our location and slots answer neither (engine.location_invitation).
_ELSEWHERE = re.compile(
    r"\b(?:another|other|different)\s+(?:location|locations|area|areas|place|places|community|communities|city)\b"
    r"|\b(?:outside|other\s+than|apart\s+from|except)\s+international\s+city\b|\btoo\s+far\b|\bvery\s+far\b|\bso\s+far\s+(?:from|for)\b"
    r"|\bfar\s+(?:from|for)\s+(?:me|us|my|our|home)\b|\b(?:bohat|bahut|kaafi|kafi)\s+door\b|بعيد|دور\s+ہے|बहुत\s+दूर",
    re.IGNORECASE,
)


def elsewhere(said: str) -> bool:
    """Their words want another area or object to the distance (_ELSEWHERE)."""
    return bool(_ELSEWHERE.search(str(said or "")))
