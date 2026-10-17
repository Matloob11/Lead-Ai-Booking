"""The nudges to a shops customer who went quiet after our question (board T29; owner's choice Q7).

When the assistant's last message in a shops chat asked something or invited them (or asked for
the licence's copy, which has no question mark: asks_or_invites), and the customer has said
nothing for two hours, one nudge goes, written by code from what the chat knows (the build
pack's words):

- "Hi {name}, I picked 2 {Type N} shops that would work well for a {business}. Shall I book you
  for this evening?" when the type in view (the one they chose, else MATCH's) and their business
  are known;
- "Hi {name}, just checking in — shall I hold a slot for you to see the shops today or
  tomorrow?" otherwise ("today or on Monday" when tomorrow is closed).

The first one goes between 10:00 and 18:00 Dubai on an open day, so "this evening" still holds.
At 10:30 Dubai the next day, while the customer still said nothing, one last one: "Good morning
{name}, would today suit you to see the shops? I can hold a slot at {two free slots}." (only on
an open day with a free slot left, until noon). Then nothing more in that chat. Both only inside
the 24-hour window, ten minutes to spare: a nudge is a free-form message, never a template.

A customer who wants no shop to rent (assistant/needs.py, the owner's rule of 2026-10-15) is nudged
only about the visit, never about shops (``options``): "Hi {name}, just checking in — shall I hold a
slot for you to see the options today or tomorrow?", and the morning after "Good morning {name},
would today suit you to come and see the options? I can hold a slot at {two free slots}."

Our "Is the shop for yourself, or are you checking for a client?" still open (it sorts an end user
from a broker, the build pack's first step) is asked again rather than skipped (``for_whom``): "Hi
{name}, just checking in — is the shop for yourself, or are you checking for a client?" (launch chats
103 and 78 were invited to see the shops over it). It is no invitation: a yes to it agrees to nothing.
A message of ours that told them a colleague will confirm what they asked (``defers_question``: "Good
question — I'll have our agent confirm that for you at the viewing.") gets no nudge at all: a person
is alerted instead (followups.py; launch chats 95 and 59).

Plain functions on plain data, in the six languages of the other fixed lines: followups.py
decides and sends with them, and the eval (leadai_eval) writes the same words. A shop type's
name ("Type 1") stays English, as the shop types list and the detail card keep it.
"""

from __future__ import annotations

import datetime as dt
import re

from . import crm_facts, filters, hours, rules, shop_flow, shops

SILENT_FOR = dt.timedelta(hours=2)
WINDOW_MARGIN = dt.timedelta(minutes=10)
FIRST_FROM = dt.time(10, 0)
FIRST_UNTIL = dt.time(18, 0)
SECOND_FROM = dt.time(10, 30)
SECOND_UNTIL = dt.time(12, 0)
MOST = 2
# A business longer than this is not named in a nudge (the generic one goes).
BUSINESS_MAX = 50
_NOT_A_WORD = re.compile(r"[<>\[\]{}\\|*_~`#@=/]")

# (with a name, without one)
_HI = {
    "en": ("Hi {name}", "Hi there"),
    "ar": ("مرحباً {name}", "مرحباً"),
    "ur_latin": ("Hi {name}", "Hi"),
    "ur": ("السلام علیکم {name}", "السلام علیکم"),
    "hi_latin": ("Namaste {name}", "Namaste"),
    "hi": ("नमस्ते {name}", "नमस्ते"),
}
_MORNING = {
    "en": ("Good morning {name}", "Good morning"),
    "ar": ("صباح الخير {name}", "صباح الخير"),
    "ur_latin": ("Good morning {name}", "Good morning"),
    "ur": ("صبح بخیر {name}", "صبح بخیر"),
    "hi_latin": ("Good morning {name}", "Good morning"),
    "hi": ("सुप्रभात {name}", "सुप्रभात"),
}
_TYPED = {
    "en": "{hi}, I picked 2 {type} shops that would work well for {business}. Shall I book you for this evening?",
    "ar": "{hi}، اخترت لك محلّين من {type} يناسبان {business}. هل أحجز لك موعداً هذا المساء؟",
    "ur_latin": "{hi}, maine aap ke {business} ke liye {type} ki 2 shops chuni hain. Kya main aap ke liye aaj shaam ka slot book kar doon?",
    "ur": "{hi}، میں نے آپ کے {business} کے لیے {type} کی 2 دکانیں منتخب کی ہیں۔ کیا میں آپ کے لیے آج شام کا سلاٹ بک کر دوں؟",
    "hi_latin": "{hi}, maine aapke {business} ke liye {type} ki 2 shops chuni hain. Kya main aapke liye aaj shaam ka slot book kar doon?",
    "hi": "{hi}, मैंने आपके {business} के लिए {type} की 2 दुकानें चुनी हैं। क्या मैं आपके लिए आज शाम का स्लॉट बुक कर दूँ?",
}
_GENERIC = {
    "en": "{hi}, just checking in — shall I hold a slot for you to see the shops {days}?",
    "ar": "{hi}، أردت فقط الاطمئنان — هل أحجز لك موعداً لمعاينة المحلات {days}؟",
    "ur_latin": "{hi}, bas haal chaal poochna tha — kya main aap ke liye {days} shops dekhne ka slot rakh doon?",
    "ur": "{hi}، بس خیریت معلوم کرنی تھی — کیا میں آپ کے لیے {days} دکانیں دیکھنے کا سلاٹ رکھ دوں؟",
    "hi_latin": "{hi}, bas haal-chaal poochna tha — kya main aapke liye {days} shops dekhne ka slot rakh doon?",
    "hi": "{hi}, बस हालचाल पूछना था — क्या मैं आपके लिए {days} दुकानें देखने का स्लॉट रख दूँ?",
}
_SECOND = {
    "en": "{gm}, would today suit you to see the shops? I can hold a slot at {slots}.",
    "ar": "{gm}، هل يناسبك اليوم لمعاينة المحلات؟ يمكنني حجز موعد لك الساعة {slots}.",
    "ur_latin": "{gm}, kya aaj shops dekhne ke liye theek rahega? Main aap ke liye {slots} ka slot rakh sakta hoon.",
    "ur": "{gm}، کیا آج دکانیں دیکھنے کے لیے ٹھیک رہے گا؟ میں آپ کے لیے {slots} کا سلاٹ رکھ سکتا ہوں۔",
    "hi_latin": "{gm}, kya aaj shops dekhne ke liye theek rahega? Main aapke liye {slots} ka slot rakh sakta hoon.",
    "hi": "{gm}, क्या आज दुकानें देखने के लिए ठीक रहेगा? मैं आपके लिए {slots} का स्लॉट रख सकता हूँ।",
}
# The same two for a customer who wants no shop to rent: the visit only, "to see the options".
_OPTIONS = {
    "en": "{hi}, just checking in — shall I hold a slot for you to see the options {days}?",
    "ar": "{hi}، أردت فقط الاطمئنان — هل أحجز لك موعداً لرؤية الخيارات {days}؟",
    "ur_latin": "{hi}, bas haal chaal poochna tha — kya main aap ke liye {days} options dekhne ka slot rakh doon?",
    "ur": "{hi}، بس خیریت معلوم کرنی تھی — کیا میں آپ کے لیے {days} آپشنز دیکھنے کا سلاٹ رکھ دوں؟",
    "hi_latin": "{hi}, bas haal-chaal poochna tha — kya main aapke liye {days} options dekhne ka slot rakh doon?",
    "hi": "{hi}, बस हालचाल पूछना था — क्या मैं आपके लिए {days} विकल्प देखने का स्लॉट रख दूँ?",
}
_OPTIONS_SECOND = {
    "en": "{gm}, would today suit you to come and see the options? I can hold a slot at {slots}.",
    "ar": "{gm}، هل يناسبك اليوم أن تأتي لرؤية الخيارات؟ يمكنني حجز موعد لك الساعة {slots}.",
    "ur_latin": "{gm}, kya aaj options dekhne ke liye aana theek rahega? Main aap ke liye {slots} ka slot rakh sakta hoon.",
    "ur": "{gm}، کیا آج آپشنز دیکھنے کے لیے آنا ٹھیک رہے گا؟ میں آپ کے لیے {slots} کا سلاٹ رکھ سکتا ہوں۔",
    "hi_latin": "{gm}, kya aaj options dekhne ke liye aana theek rahega? Main aapke liye {slots} ka slot rakh sakta hoon.",
    "hi": "{gm}, क्या आज विकल्प देखने के लिए आना ठीक रहेगा? मैं आपके लिए {slots} का स्लॉट रख सकता हूँ।",
}
# Our for-whom question (rules "for_whom" without its "Thank you!") asked again, never skipped by an
# invitation: no invitation itself, so it is none of _SHAPES.
_FOR_WHOM_AGAIN = {
    "en": "{hi}, just checking in — is the shop for yourself, or are you checking for a client?",
    "ar": "{hi}، أردت فقط الاطمئنان — هل المحل لك شخصياً، أم تبحث عنه لعميل؟",
    "ur_latin": "{hi}, bas haal chaal poochna tha — kya shop aap ke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",
    "ur": "{hi}، بس خیریت معلوم کرنی تھی — کیا دکان آپ کے اپنے لیے ہے، یا آپ کسی کلائنٹ کے لیے دیکھ رہے ہیں؟",
    "hi_latin": "{hi}, bas haal-chaal poochna tha — kya shop aapke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",
    "hi": "{hi}, बस हालचाल पूछना था — क्या दुकान आपके अपने लिए है, या आप किसी क्लाइंट के लिए देख रहे हैं?",
}
# (today or tomorrow, today or on <day>, or)
_DAYS = {
    "en": ("today or tomorrow", "today or on {day}", " or "),
    "ar": ("اليوم أو غداً", "اليوم أو يوم {day}", " أو "),
    "ur_latin": ("aaj ya kal", "aaj ya {day} ko", " ya "),
    "ur": ("آج یا کل", "آج یا {day} کو", " یا "),
    "hi_latin": ("aaj ya kal", "aaj ya {day} ko", " ya "),
    "hi": ("आज या कल", "आज या {day} को", " या "),
}
# Monday first, as date.weekday() counts. English letters keep the English names.
_WEEKDAYS = {
    "ar": ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"),
    "ur": ("پیر", "منگل", "بدھ", "جمعرات", "جمعہ", "ہفتہ", "اتوار"),
    "hi": ("सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"),
}
# The business in the customer's script: English words stay as they were said, after "your business".
_BUSINESS_IN = {"ar": "نشاطك ({bare})", "ur": "کاروبار ({bare})", "hi": "बिज़नेस ({bare})"}


def _lang(language: str) -> str:
    return language if language in _TYPED else "en"


def _greeting(table: dict, lang: str, name: str) -> str:
    first = filters.first_name(name or "")
    with_name, without = table[lang]
    return with_name.format(name=first) if first else without


def bare_business(activity) -> str:
    """The customer's business as they told it, short and plain ("restaurant (shawarma)" is
    "restaurant"), or '' when there is none worth naming."""
    text = re.split(r"[(\[{]", str(activity or ""), maxsplit=1)[0]
    text = " ".join(text.split()).strip(" ,.;:-")
    if not text or len(text) > BUSINESS_MAX or _NOT_A_WORD.search(text):
        return ""
    # Never a home they want ("your apartment studio business"): a chat from before may hold one (crm_facts).
    return text if crm_facts.is_business(text) else ""


def business_words(language: str, activity) -> str:
    """The business as a nudge names it: "a vape shop" or "your vape business" in English,
    "vape shop" or "vape business" in English letters, "نشاطك (vape shop)" in a script."""
    bare = bare_business(activity)
    if not bare:
        return ""
    lang = _lang(language)
    if lang == "en":
        return shop_flow.business_phrase(bare)
    if lang in _BUSINESS_IN:
        return _BUSINESS_IN[lang].format(bare=bare)
    return bare if bare.casefold().endswith(shop_flow._BUSINESS_NOUNS) else f"{bare} business"


def days_phrase(language: str, now, closed_dates=()) -> str:
    """'today or tomorrow', or 'today or on Monday' when tomorrow is closed."""
    lang = _lang(language)
    both, other, _ = _DAYS[lang]
    today = hours.now_dubai(now).date()
    tomorrow = today + dt.timedelta(days=1)
    if hours.is_open_day(tomorrow, closed_dates):
        return both
    day = tomorrow
    for _ in range(14):
        day += dt.timedelta(days=1)
        if hours.is_open_day(day, closed_dates):
            break
    names = _WEEKDAYS.get(lang)
    return other.format(day=names[day.weekday()] if names else f"{day:%A}")


def first_text(
    language: str,
    name: str,
    *,
    shop_type: str = "",
    business: str = "",
    now=None,
    closed_dates=(),
    options: bool = False,
    for_whom: bool = False,
) -> str:
    """The first nudge: the type in view and their business when both are known, else the generic one;
    ``options``: a customer who wants no shop to rent, asked only about the visit (needs.py);
    ``for_whom``: our for-whom question is still open, and is asked again instead (asks_for_whom)."""
    lang = _lang(language)
    hi = _greeting(_HI, lang, name)
    if options:
        return _OPTIONS[lang].format(hi=hi, days=days_phrase(lang, now, closed_dates))
    if for_whom:
        return _FOR_WHOM_AGAIN[lang].format(hi=hi)
    words = business_words(lang, business)
    if shop_type in shops.TYPE_KEYS and words:
        return _TYPED[lang].format(hi=hi, type=shops.type_label(shop_type), business=words)
    return _GENERIC[lang].format(hi=hi, days=days_phrase(lang, now, closed_dates))


def _fixed_words(template: str) -> list[str]:
    """A nudge's own words between its {name}, {type}, {business}, {days} and {slots}."""
    parts = (part.strip(" ,،—-") for part in re.split(r"\{\w+\}", template))
    return [part for part in parts if part]


_SHAPES = tuple(
    _fixed_words(template) for table in (_TYPED, _GENERIC, _SECOND, _OPTIONS, _OPTIONS_SECOND) for template in table.values()
)


def is_nudge(text: str) -> bool:
    """The text is one of the nudges, in any of the six languages: all its own words, in order
    ("Shall I book you for this evening?", "shall I hold a slot for you to see the shops"). A
    nudge invites them (engine.visit_offered), though filters.is_invitation reads none of these
    words: a yes to one is a yes to coming, as to any invitation."""
    body = str(text or "")
    for parts in _SHAPES:
        at = 0
        for part in parts:
            found = body.find(part, at)
            if found < 0:
                break
            at = found + len(part)
        else:
            return True
    return False


def slots_words(language: str, slots) -> str:
    """'11:00 AM or 1:00 PM' (the hours only: the nudge says "today" itself)."""
    joiner = _DAYS[_lang(language)][2]
    return joiner.join(hours.time_label(slot) for slot in list(slots)[:2])


def second_text(language: str, name: str, slots, *, options: bool = False) -> str:
    """The last nudge, the morning after: today's free slots (``options``: about the visit only)."""
    lang = _lang(language)
    table = _OPTIONS_SECOND if options else _SECOND
    return table[lang].format(gm=_greeting(_MORNING, lang, name), slots=slots_words(lang, slots))


# What our last message left open ----------------------------------------------------------------------

# Our for-whom question, in each language, without the "Thank you!" that opens the line.
FOR_WHOM_QUESTIONS = tuple(line.split("!", 1)[1].strip().casefold() for line in rules.LINES["for_whom"].values())


def asks_for_whom(text: str) -> bool:
    """Our message asks "Is the shop for yourself, or are you checking for a client?" (code's line, or the
    model's words around the same question), in any of the six languages."""
    body = " ".join(str(text or "").split()).casefold()
    return any(question in body for question in FOR_WHOM_QUESTIONS)


# A colleague will confirm or answer what they asked: SHOPS_SYSTEM's "Good question — I'll have our agent
# confirm that for you at the viewing." (shops.UNKNOWN_LINE) in the model's own words and language, and the
# general "Our specialist will confirm that with you here." Never our agent driving them to the shops,
# calling them, guiding them through a licence, or confirming the visit itself ("Our specialist will confirm
# the viewing with you here", "specialist ... viewing confirm kar lenge"), nor the holding line a person's
# chat gets ("Our specialist has your message and will reply here", "... woh yahin jawab denge").
_COLLEAGUE = r"(?:agent|specialist|colleague|consultant|team)s?"
_ANSWERS = r"(?:confirm|answer|clarify|explain|check|reply|respond|get\s+back\s+to\s+you)"
_ABOUT_VISIT = r"(?!\s+(?:the|your)\s+(?:visit|viewing|booking|appointment|meeting|slot|time)\b)"
_AR_VISIT = r"(?:موعد|الموعد|المعاينة|معاينة|الزيارة|زيارة|الحجز|حجز)"
# Right before the verb in Urdu, Hindi and their Latin spelling, the visit is what is confirmed.
_VISIT_BEFORE = (
    "(?<!viewing )(?<!visit )(?<!booking )(?<!meeting )(?<!appointment )(?<!slot )(?<!time )(?<!waqt )"
    "(?<!ویونگ )(?<!وزٹ )(?<!ملاقات )(?<!میٹنگ )(?<!وقت )(?<!व्यूइंग )(?<!विज़िट )(?<!मीटिंग )(?<!समय )"
)
_DEFERS = re.compile(
    rf"\b(?:have|get|ask)\s+(?:our|my|the|a)\s+{_COLLEAGUE}\s+(?:to\s+)?{_ANSWERS}\b{_ABOUT_VISIT}"
    rf"|\b(?:our|my|the|a|an)\s+{_COLLEAGUE}\s+(?:will|can|would|shall|is\s+going\s+to)\s+(?:\w+\s+)?{_ANSWERS}\b{_ABOUT_VISIT}"
    # Roman Urdu / Hindi: "hamara agent viewing par confirm kar dega", "agent se confirm karwa dunga", and the
    # deflect line "Hamare specialist yahin aap ko is ki tasdeeq kar denge" (an English "confirm" is the above's)
    rf"|\b(?:agent|specialist)\b[^.?!\n]{{0,40}}?{_VISIT_BEFORE}\b(?:confirm|tasdeeq|pushti)\s+(?:kar|karwa|karva|kara)\w*"
    r"|\bagent\b[^.?!\n]{0,40}?\b(?:jawab\s+de\w*|bata\s*(?:dega|denge|dein|dain|ga|ge))"
    # Arabic, never with the visit as what is confirmed ("لتأكيد الموعد", "سيؤكد المختص لدينا موعد المعاينة")
    r"|(?:وكيلنا|الوكيل|المختص|زميلنا|فريقنا)[^.؟!\n]{0,40}?(?:تأكيد|يؤكد|سيؤكد|يجيب|سيجيب|يوضح|سيوضح|توضيح)"
    rf"(?!\s+(?:لك\s+|معك\s+)?{_AR_VISIT})"
    # Arabic puts the verb first: "سيؤكد لك المختص لدينا ذلك هنا" (the deflect line)
    rf"|(?:سيؤكد|يؤكد|سيجيب|يجيب|سيوضح|يوضح)[^.؟!\n]{{0,30}}?(?:المختص|الوكيل|وكيلنا|زميلنا|فريقنا)(?!\s+(?:لدينا\s+)?{_AR_VISIT})"
    rf"|(?:ایجنٹ|ساتھی)[^۔؟!\n]{{0,40}}?{_VISIT_BEFORE}(?:کنفرم|تصدیق|جواب|بتا)|اسپیشلسٹ[^۔؟!\n]{{0,40}}?{_VISIT_BEFORE}(?:کنفرم|تصدیق)"
    rf"|(?:एजेंट|सहकर्मी)[^।?!\n]{{0,40}}?{_VISIT_BEFORE}(?:कन्फ़र्म|कन्फर्म|पुष्टि|जवाब|बता)"
    rf"|स्पेशलिस्ट[^।?!\n]{{0,40}}?{_VISIT_BEFORE}(?:कन्फ़र्म|कन्फर्म|पुष्टि)",
    re.IGNORECASE,
)


def defers_question(text: str) -> bool:
    """Our message told them a colleague will confirm or answer what they asked: their question is still
    open (launch chat 95's nine questions, 59's "full details including rent security"), so no nudge
    pushes a visit over it and a person is alerted instead (followups.nudge_due)."""
    return bool(_DEFERS.search(" ".join(str(text or "").replace("’", "'").split())))


# When ----------------------------------------------------------------------------------------------


def asks_or_invites(text: str, kind: str = "text", step: str = "") -> bool:
    """Our message asked something or invited them: a question mark, an invitation, buttons or a
    list to tap (an interactive message), or the request for the licence's copy (``step``, the
    message's payload "shop_step": shop_flow.LICENCE_ASK), whose words ask no question. A silence
    after that request is nudged like any other, or the chat would stall there for good."""
    return kind == "interactive" or step == shop_flow.LICENCE_ASK or rules.asks_question(text) or filters.is_invitation(text)


def window_left(window_until, now) -> bool:
    """The customer's 24-hour window is open for at least WINDOW_MARGIN more."""
    return bool(window_until) and window_until - now >= WINDOW_MARGIN


def first_due(now, asked_at, window_until, closed_dates=()) -> bool:
    """The first nudge may go now: silent SILENT_FOR since our question, the window open with
    its margin, an open day between FIRST_FROM and FIRST_UNTIL Dubai."""
    local = hours.now_dubai(now)
    return (
        asked_at is not None
        and now - asked_at >= SILENT_FOR
        and window_left(window_until, now)
        and hours.is_open_day(local.date(), closed_dates)
        and FIRST_FROM <= local.time() < FIRST_UNTIL
    )


def second_due(now, first_at, window_until, closed_dates=()) -> bool:
    """The last nudge may go now: the day after the first one, from SECOND_FROM to SECOND_UNTIL
    Dubai, an open day, the window open with its margin."""
    if first_at is None:
        return False
    local = hours.now_dubai(now)
    first_day = first_at.astimezone(hours.DUBAI).date()
    return (
        local.date() == first_day + dt.timedelta(days=1)
        and SECOND_FROM <= local.time() < SECOND_UNTIL
        and hours.is_open_day(local.date(), closed_dates)
        and window_left(window_until, now)
    )


def today_slots(now, closed_dates=(), taken=()) -> list:
    """Today's two free slots for the last nudge (one when only one is left; none: no nudge)."""
    today = hours.now_dubai(now).date()
    return [slot for slot in hours.offer_pair(now, closed_dates, taken, day=today) if slot.astimezone(hours.DUBAI).date() == today]
