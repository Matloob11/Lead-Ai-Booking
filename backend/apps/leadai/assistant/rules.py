"""Decisions made by code before (or instead of) the model.

- Opt-out: a tap on a template's "Unsubscribe" / "Stop promotions" /
  "Not Interested" button, or a short message that is only an opt-out phrase,
  in English, Arabic, Urdu, Roman Urdu or Hindi. "Unsubscribe" is the
  most-tapped template button on this account; one sales-style reply after
  it invites a block, which lowers the agent's number's quality rating.
- Acknowledgements ("ok", "thanks", an emoji) that need no answer.
- Deferrals ("I will message you", and "Tomorrow at 5 pm, I will let you
  know": a day or an hour said with it is still no promise) that put a visit
  off, and plain yeses ("yes", "ji") that accept one.
- Automatic replies from the customer's own WhatsApp Business bot.
- The fixed lines sent in those cases, in the customer's language.
- The shops playbook's own (International City shops campaigns, owner's
  choice 2026-10-13, never in a general chat): the template's "Stop messages"
  tap, "Not now", a plain no, the positive first answer, a plain chain message
  or scam, and their lines.
"""

from __future__ import annotations

import re
import unicodedata

STOP_ALL = "stop_all"
NOT_INTERESTED = "not_interested"
WRONG_NUMBER = "wrong_number"
# Shops chats only (the model's call): a forwarded chain message, a scam or an advert.
SPAM = "spam"

BUTTON_OPT_OUT = {
    "unsubscribe": STOP_ALL,
    "unsubscibe": STOP_ALL,
    "stop promotions": STOP_ALL,
    "stop promotion": STOP_ALL,
    "stop": STOP_ALL,
    "not interested": NOT_INTERESTED,
}

PHRASES = {
    STOP_ALL: (
        # English
        "stop", "unsubscribe", "stop messaging", "stop messaging me", "stop sending", "dont message me",
        "do not message me", "dont contact me", "do not contact me", "do not contact", "remove my number",
        "leave me alone", "block", "stop it",
        # Arabic (a bare "الغاء" is the usual unsubscribe word, unless a meeting is
        # booked: then it cancels the meeting, see is_meeting_cancel)
        "توقف", "وقف", "إلغاء الاشتراك", "الغاء الاشتراك", "الغاء", "إلغاء", "لا ترسل", "لا تراسلني", "احذف رقمي",
        # Urdu
        "مت بھیجیں", "میسج نہ کریں", "بند کریں",
        # Roman Urdu / Hindi
        "mat bhejo", "msg mat karo", "message mat karo", "message na karo", "band karo", "msg na karo",
        # Hindi
        "मत भेजो", "मैसेज मत करो", "बंद करो",
    ),
    # Not "not now": to "Would 5 PM or 6 PM work?" it means another time, not no.
    NOT_INTERESTED: (
        "not interested", "no thanks", "no thank you", "im not interested", "i am not interested",
        # As people type them (launch chat 120's "No thankyou"; launch review issue 26).
        "no thankyou", "no thanku", "no thank u", "no thanx", "no thnx", "no thx",
        "لا أريد", "لا اريد", "ما ابي", "لا ابي", "غير مهتم", "مش مهتم", "مو مهتم",
        "دلچسپی نہیں", "نہیں چاہیے",
        "interested nahi", "interested nahin", "nahi chahiye", "nahin chahiye", "zaroorat nahi", "zarurat nahi",
        "रुचि नहीं", "दिलचस्पी नहीं", "नहीं चाहिए",
    ),
    WRONG_NUMBER: (
        "wrong number", "wrong no", "رقم خطأ", "رقم غلط", "غلط نمبر", "galat number", "ghalat number",
        "rong number", "गलत नंबर",
    ),
}

ACKS = {
    "ok", "okay", "okk", "k", "kk", "thanks", "thank you", "thankyou", "thanku", "thank u", "thnx", "thanx", "thx", "ty",
    "noted", "fine", "great",
    "good", "alright", "sure", "done", "got it", "acha", "achha", "theek hai", "thik hai", "shukriya",
    "jazakallah", "شكرا", "شكراً", "تمام", "اوکے", "ٹھیک ہے", "شکریہ", "धन्यवाद", "ठीक है",
}

# A WhatsApp Business away or greeting message. Real customers write the weak
# phrases too ("Thank you for your message. Yes, I am interested"), so one of
# them counts only when it came back within seconds of our message, the way a
# bot answers; a message that asks a question is never treated as automatic.
AUTO_REPLY_STRONG = (
    "auto-reply", "auto reply", "autoreply", "automatic reply", "automated message", "automated reply",
    "automated response", "this is an automated", "out of office", "out-of-office",
)
AUTO_REPLY_WEAK = (
    "we will get back to you", "we'll get back to you", "we will reply", "we'll reply", "we will respond",
    "we'll respond", "will respond as soon as", "thank you for contacting", "thanks for contacting",
    "thank you for reaching out", "thanks for reaching out", "thank you for your message",
    "our business hours", "currently unavailable", "outside our working hours", "outside business hours",
    "our team will reply", "our team will get back", "reply to you shortly", "get back to you shortly",
)
AUTO_REPLY_SECONDS = 15
QUESTION_MARKS = ("?", "؟", "？")

_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase, no punctuation or emoji, single spaces, no apostrophes."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower().replace("’", "'")
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("S"))
    text = _PUNCT.sub(" ", text).replace("'", "")
    return " ".join(text.split())


def _phrase_index():
    return {normalize_text(p): kind for kind, phrases in PHRASES.items() for p in phrases}


PHRASE_INDEX = _phrase_index()
WRONG_NUMBER_INDEX = tuple(normalize_text(p) for p in PHRASES[WRONG_NUMBER])


# Alone, these mean "cancel". With a meeting booked that is the meeting, not
# the chat, so the model hears them instead of the stop rule.
MEETING_CANCEL = {normalize_text(p) for p in ("الغاء", "إلغاء", "cancel", "cancel it", "please cancel", "cancel please")}


def is_meeting_cancel(text: str) -> bool:
    return normalize_text(text) in MEETING_CANCEL


def opt_out_from_button(label: str) -> str | None:
    return BUTTON_OPT_OUT.get(normalize_text(label))


# Asking for no messages AT ALL, unmistakable however long the message is.
STOP_ANYWHERE = tuple(
    normalize_text(p)
    for p in (
        "do not message me again", "dont message me again", "do not contact me again", "dont contact me again",
        "never message me", "never contact me", "stop messaging me", "remove my number", "unsubscribe me",
    )
)


FILLERS = (
    "please", "pls", "plz", "bro", "sir", "thanks", "thank you", "plz", "bhai", "yaar",
    # "No thankyou" (launch chat 120) as "No thank you": one word, as people type it.
    "thankyou", "thanku", "thank u", "thanx", "thnx", "thx",
)


def opt_out_from_text(text: str) -> str | None:
    """Only a whole short message counts: "stop sending 1BR, I need 2BR" is not an opt-out
    (except a request for no messages at all, which counts in any length)."""
    words = normalize_text(text)
    if words and any(f" {phrase} " in f" {words} " for phrase in STOP_ANYWHERE):
        return STOP_ALL
    if not words or len(words.split()) > 6:
        return None
    if words in PHRASE_INDEX:
        return PHRASE_INDEX[words]
    # "Wrong number. I am not Ahmed": a wrong-number phrase opening a short message.
    for phrase in WRONG_NUMBER_INDEX:
        if words.startswith(phrase + " "):
            return WRONG_NUMBER
    # "please stop", "stop please", "no thanks bro": one extra polite word either side.
    for filler in FILLERS:
        for candidate in (words.removeprefix(filler + " "), words.removesuffix(" " + filler)):
            if candidate != words and candidate in PHRASE_INDEX:
                return PHRASE_INDEX[candidate]
    return None


def _whole_short_message(text: str, index, fillers) -> bool:
    """The message is one of ``index`` with at most one extra word from ``fillers`` at each end."""
    words = normalize_text(text)
    if not words or len(words.split()) > 8:
        return False
    heads = {words} | {words.removeprefix(filler + " ") for filler in fillers}
    candidates = heads | {head.removesuffix(" " + filler) for head in heads for filler in fillers}
    return bool(candidates & index)


# The visit put off, not refused ("I will massage you" was "message" in the
# first real chat): the visit stays tentative, and nobody offers times again.
_LATER = (
    "message you", "text you", "call you", "contact you", "inform you", "let you know", "tell you", "update you",
    "get back to you",
)
_BATAUNGA = ("batata hoon", "bata dunga", "bataunga")
DEFERRALS = {
    normalize_text(p)
    for p in (
        *(f"{who} {what}" for who in ("i will", "will", "i") for what in _LATER),
        "i will massage you", "will message you later", "let you know", "later", "i will confirm", "will confirm",
        *(f"{when} {what}".strip() for when in ("baad mein", "baad me", "baad main", "main", "") for what in _BATAUNGA),
        *(f"{what} kar dunga" for what in ("inform", "message", "call", "contact")),
    )
}
DEFERRAL_FILLERS = FILLERS + ("ok", "okay", "ji", "sure", "later", "soon", "inshallah")
# How people type them: normalize_text makes "I'll" "ill" (it drops the
# apostrophe), and "u", "msg", "hun" stand for "you", "message", "hoon".
_TYPED = {
    "ill": "i will", "ll": "will", "wil": "will", "u": "you", "msg": "message", "txt": "text",
    "hun": "hoon", "hu": "hoon", "doonga": "dunga", "dungi": "dunga", "batati": "batata", "bataungi": "bataunga",
}


def _typed_words(text: str) -> str:
    return " ".join(_TYPED.get(word, word) for word in normalize_text(text).split())


def is_deferral(text: str) -> bool:
    """A whole short message that puts the visit off ("ok, I'll message u later")."""
    return _whole_short_message(_typed_words(text), DEFERRALS, DEFERRAL_FILLERS)


# What a deferral may name besides ("Tomorrow at 5 pm, I will let you know", "kal 5 baje
# bata dunga"): a day, a part of the day, an hour, the words that join them, a hedge. The
# hour is no promise to come at it (hours.no_promise reads it the same way).
_WHEN_WORDS = frozenset(
    """
    today tonight tomorrow tomorow tommorow tommorrow tmrw tmr tmw kal aaj aj parso parson
    monday tuesday wednesday thursday friday saturday sunday mon tue tues wed weds thu thur thurs fri sat sun
    morning afternoon evening night noon midday subah sham shaam raat dopahar
    this next week weekend day after at on by around about in the
    am pm a p m baje bajay bje oclock maybe probably perhaps shayad
    """.split()
)
_WHEN_NUMBER = re.compile(r"^\d{1,2}(?:am|pm)?$")  # "5", "5pm"; "17:00" reads "17 00"
DATED_DEFERRAL_WORDS = 14
# With a day or an hour, only a real deferral phrase puts the visit off ("I will let you
# know", "bata dunga", "I'll text u"), never a bare "later": "Today later at 5 pm" asks
# for 5 PM today. Alone, "later" is still a deferral (is_deferral).
PUTS_OFF = frozenset(DEFERRALS - {"later"})


def is_dated_deferral(text: str) -> bool:
    """A short message that is a deferral once its day, its hour and the words around them
    are set aside ("Tomorrow at 5 pm, I will let you know"): the visit is still put off.
    What is left must be a real deferral phrase (PUTS_OFF): "Today later at 5 pm" is
    not one. "I will come tomorrow at 5" is not, nor anything with a question
    ("Tomorrow at 5? I will let you know" may ask whether 5 is free): the model answers
    those."""
    words = _typed_words(text).split()
    if not words or len(words) > DATED_DEFERRAL_WORDS or asks_question(text):
        return False
    rest = [word for word in words if word not in _WHEN_WORDS and not _WHEN_NUMBER.match(word)]
    return bool(rest) and len(rest) < len(words) and _whole_short_message(" ".join(rest), PUTS_OFF, DEFERRAL_FILLERS)


def mentions_deferral(text: str) -> bool:
    """The message puts the visit off somewhere, however long it is ("Tomorrow at 5 pm,
    I will let you know"): a time said with it is no booking (engine.upgrade_exact_time).
    A bare "later" puts nothing off ("I will come tomorrow at 5 pm, see you later")."""
    words = f" {_typed_words(text)} "
    return any(f" {phrase} " in words for phrase in PUTS_OFF)


# A plain yes, which right after our invitation means they will come.
ACCEPTANCES = {
    normalize_text(p)
    for p in (
        "yes", "yeah", "yep", "yes please", "yes sure", "ok", "okay", "ok sure", "sure", "of course",
        "haan", "han", "haan ji", "ji haan", "ji", "jee", "g",
        "نعم", "أكيد", "اكيد", "ہاں", "جی", "جی ہاں", "हाँ", "हां", "जी", "जी हाँ",
    )
}


def is_acceptance(text: str) -> bool:
    return _whole_short_message(text, ACCEPTANCES, FILLERS)


# The shops playbook -----------------------------------------------------------------

# Template A's buttons are [Yes, show me shops] [Not now] [Stop messages] and
# Template B's [Yes, book a viewing] [Not now]; the live campaign's own is "Interested".
SHOPS_OPT_OUT = {normalize_text("stop messages"): STOP_ALL, normalize_text("stop message"): STOP_ALL}
POSITIVE_TAPS = {
    normalize_text(p)
    for p in ("yes, show me shops", "yes show me shops", "show me shops", "yes, book a viewing", "book a viewing", "interested", "i am interested", "im interested")
}
# Template B's yes: a viewing to book, not shops to look at.
BOOK_TAPS = {normalize_text(p) for p in ("yes, book a viewing", "book a viewing")}
NOT_NOW = {
    normalize_text(p)
    for p in (
        "not now", "not right now", "not now thanks", "not now thank you", "not at the moment", "not for now", "maybe later",
        "ليس الآن", "ليس الان", "مش الحين", "مو الحين", "مش دلوقتي", "مش هلق",
        "abhi nahi", "abhi nahin", "abhi nhi", "filhal nahi", "filhaal nahi", "abhi nahi chahiye",
        "ابھی نہیں", "فی الحال نہیں",
        "अभी नहीं",
    )
}
# A plain no, which answers our "Should I check back with you in a month?" or
# "Do you need a second shop?"; on its own, anywhere else, it is the model's.
REFUSALS = {
    normalize_text(p)
    for p in (
        "no", "nope", "nah", "no sir", "no need", "not needed", "no thanks", "no thank you", "not interested", "no its ok",
        "no thankyou", "no thanku", "no thank u", "no thanx", "no thnx", "no thx",
        "nahi", "nahin", "nhi", "na", "nai", "nahi chahiye", "zaroorat nahi", "nahi shukriya",
        "لا", "لا شكرا", "لا شكراً", "لا ما ابي", "لا شكرا لك",
        "نہیں", "جی نہیں", "نہیں شکریہ",
        "नहीं", "जी नहीं", "नहीं धन्यवाद",
    )
}


def shops_opt_out(label: str) -> str | None:
    """"Stop messages" (the shops template's button, or typed alone): a STOP in a shops chat."""
    words = normalize_text(label)
    return SHOPS_OPT_OUT.get(words) or SHOPS_OPT_OUT.get(words.removeprefix("please ").removesuffix(" please"))


def is_positive_tap(label: str) -> bool:
    return normalize_text(label) in POSITIVE_TAPS


def is_book_tap(label: str) -> bool:
    return normalize_text(label) in BOOK_TAPS


def is_not_now(text: str) -> bool:
    return _whole_short_message(text, NOT_NOW, FILLERS)


def is_refusal(text: str) -> bool:
    return _whole_short_message(text, REFUSALS, FILLERS)


# A forwarded chain message, a scam or another business's advert, in words no customer
# answering us writes. Spam stops the assistant and closes the lead as Junk, so code
# calls it only when it is plain: a strong marker and a second marker of any kind,
# the second looked for outside the first's own words ("a shop for my crypto trading
# platform" is one marker, never two). Anything less is the model's call (SHOPS_SYSTEM).
_SPAM_STRONG = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bforward\b[^.!?\n]{0,30}?\b(?:\d+|five|ten|twenty|all (?:of )?your|every)\s+(?:friends|people|contacts|groups|persons|members|numbers)\b",
        r"\bshare\b[^.!?\n]{0,30}?\bwith\s+(?:\d+|five|ten|twenty|all (?:of )?your)\s+(?:friends|people|contacts|groups)\b",
        r"chat\.whatsapp\.com/|\bt\.me/|\bbit\.ly/|\btinyurl\.com/",
        r"\bearn(?:ing)?\s+(?:money|cash|income|extra income|profits?|\$\s*\d+|aed\s*\d+|usd\s*\d+|\d+)[^.!?\n]{0,25}?"
        r"\b(?:daily|per day|a day|every day|from home|online|per week|weekly)\b",
        r"\b(?:crypto|bitcoin|btc|forex|binary|trading|investment)\s+(?:investment\s+|trading\s+)?(?:group|signals?|channel|scheme|plan)\b",
        r"\bguaranteed\s+(?:profit|returns?|income|earnings)\b|\bdouble your (?:money|investment|income)\b",
        r"\byou (?:have )?(?:won|been selected)\b|\bclaim your (?:prize|reward|gift|bonus)\b",
    )
)
_SPAM_WEAK = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:crypto|bitcoin|btc|usdt|forex|lottery|jackpot|giveaway)\b",
        r"\blimited (?:seats|slots|spots|time offer)\b",
        r"\bjoin (?:our|my|the|now|us)\b",
        r"\bclick (?:here|the link|this link|below)\b|\blink (?:below|in bio)\b",
        r"\b(?:work|earn) from home\b|\bpassive income\b|\bdaily (?:profit|income|earnings)\b",
        r"\b100% (?:free|guaranteed|profit|safe)\b|\bfree (?:gift|money|bonus|crypto)\b",
    )
)


def looks_like_spam(text: str) -> bool:
    """Plainly a chain message, a scam or an advert (a shops chat's spam rule, engine.shops_rule)."""
    rest = unicodedata.normalize("NFKC", str(text or "")).replace("’", "'")
    strong = 0
    for pattern in _SPAM_STRONG:
        if pattern.search(rest):
            strong += 1
            rest = pattern.sub(" ", rest)
    if not strong:
        return False
    return strong + sum(1 for pattern in _SPAM_WEAK if pattern.search(rest)) >= 2


ACK_INDEX = {normalize_text(a) for a in ACKS}


def _all_acks(words: list[str]) -> bool:
    """True when the words split cleanly into acknowledgements ("ok thanks", "thank you ok")."""
    reachable = [True] + [False] * len(words)
    for end in range(1, len(words) + 1):
        reachable[end] = any(
            end - size >= 0 and reachable[end - size] and " ".join(words[end - size : end]) in ACK_INDEX
            for size in (1, 2, 3)
        )
    return reachable[-1]


def is_acknowledgement(text: str) -> bool:
    """'ok', 'ok thanks', 'شكرا', or only emoji: nothing to answer."""
    raw = str(text or "").strip()
    if raw and all(unicodedata.category(ch).startswith(("S", "Z", "P")) or ch in "‍️" for ch in raw):
        return True
    words = normalize_text(raw).split()
    return 0 < len(words) <= 6 and _all_acks(words)


def asks_question(text: str) -> bool:
    """A question in any of the scripts used here (Arabic and Urdu write '؟')."""
    return any(mark in str(text or "") for mark in QUESTION_MARKS)


# They ask who we are or why we wrote, clause by clause (_who_words): "Who is this?", "Why did you call me?", "How did you
# get my number?", "aap kaun?", "من انت", "आप कौन". Never "Who is the owner?", "Why is the rent so high?" or "Who will
# show me the shop?": those ask about the offer.
_WHO_WE_ARE = re.compile(
    r"(?:(?:hi|hello|hey|salam|salaam|dear|sir|madam|bro|excuse me|sorry|please|pls|plz|ok|okay)\s+)*"
    r"(?:"
    r"who\s+(?:is|are|r|s)\s+(?:this|that|you|u|it|there|speaking|calling|messaging|texting)(?:\s+(?:guys|people|please|pls|plz|sir|madam|bro))?"
    r"|whos\s+(?:this|that|there|calling|speaking|messaging|texting)|who\s+dis|who\s+r\s+u"
    r"|who\s+(?:am\s+i|i\s+am)\s+(?:talking|speaking|chatting)\s+(?:to|with)"
    r"|(?:which|what)\s+company(?:\s+(?:is\s+this|is\s+it|are\s+you|r\s+u))?"
    r"|where\s+(?:are\s+you|r\s+u)\s+(?:from|calling\s+from|messaging\s+from|texting\s+from)"
    r"|why\s+(?:did|do|are|r|have|would|were)\s+(?:you|u|ya|your\s+team)\s+(?:\w+\s+)?"
    r"(?:call|calling|called|message|messaging|messaged|msg|text|texting|texted|contact|contacting|contacted|send|sending|sent"
    r"|write|writing|wrote|ring|ringing|rang|whatsapp|whatsapping)(?:\s+(?:me|us|this\s+number|my\s+number))?"
    r"(?:\s+(?:this|that|these|the|a|your)\s+(?:message|messages|msg|text|texts|offer))?(?:\s+(?:again|today|now|here))?"
    r"|why\s+(?:am\s+i|i\s+am|did\s+i|do\s+i)\s+(?:getting|receiving|get|receive|got|received)(?:\s+(?:this|these|your|a|the))?"
    r"(?:\s+(?:message|messages|msg|call|calls|text|texts))?"
    r"|(?:how|where)\s+did\s+(?:you|u)\s+get\s+my\s+(?:number|no|contact|details)"
    r"|(?:what\s+is|whats)\s+this(?:\s+(?:about|regarding|for))?"
    r"|(?:aap|ap|tum|tm)\s+(?:kaun|kon|kaon)(?:\s+(?:ho|hain|hai|hn|bol\s+rahe\s+(?:ho|hain)))?"
    r"|(?:kaun|kon)\s+(?:ho|hai|hain|bol\s+raha\s+hai|bol\s+rahe\s+ho)"
    r"|(?:kyun|kyu|kyon|kis\s+liye)\s+(?:call|message|msg|phone|rabta)(?:\s+(?:kiya|kia|kiya\s+hai|kar\s+rahe\s+ho))?"
    r"|(?:call|message|msg|phone)\s+(?:kyun|kyu|kyon|kis\s+liye)(?:\s+(?:kiya|kia))?"
    # Arabic
    r"|(?:مين|من)\s*(?:انت|أنت|حضرتك|معي|معاي)?"
    r"|(?:ليش|لماذا|ليه)\s+(?:تتصل|اتصلت|تتصلون|ترسل|ارسلت|أرسلت|راسلت|تراسلني)"
    # Urdu
    r"|(?:آپ|تم)\s+کون(?:\s+(?:ہیں|ہو|ہے))?|کون\s+(?:ہیں|ہو|ہے)"
    r"|کیوں\s+(?:کال|میسج|فون)(?:\s+کی[اے]?)?|(?:کال|میسج|فون)\s+کیوں(?:\s+کی[اے]?)?"
    # Hindi
    r"|(?:आप|तुम)\s+कौन(?:\s+(?:हैं|हो|है))?|कौन\s+(?:हैं|हो|है)"
    r"|क्यों\s+(?:कॉल|मैसेज|फ़ोन|फोन)(?:\s+किया)?|(?:कॉल|मैसेज|फ़ोन|फोन)\s+क्यों(?:\s+किया)?"
    r")"
    r"(?:\s+(?:please|pls|plz|sir|madam|bro|dear))?"
)
_WHO_CLAUSES = re.compile(r"[.!?؟,;:،\n]+")
# Not normalize_text: its \w drops Devanagari's vowel signs ("कौन" would read "क न").
_NOT_A_WORD = re.compile(r"[^\w\s\u0900-\u097f]", re.UNICODE)


def _who_words(text: str) -> str:
    """Lower case, NFKC, no apostrophes, punctuation or emoji, single spaces; Devanagari kept whole."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower().replace("’", "'").replace("'", "")
    return " ".join(_NOT_A_WORD.sub(" ", text).split())


GREETINGS = {
    _who_words(p)
    for p in (
        "hi", "hii", "hello", "helo", "hey", "salam", "salaam", "assalam o alaikum", "assalamu alaikum", "assalamualaikum",
        "asalam o alaikum", "aoa", "good morning", "good afternoon", "good evening", "السلام عليكم", "مرحبا", "مرحباً", "اهلا",
        "أهلا", "هلا", "السلام علیکم", "नमस्ते", "हेलो",
    )
}


def asks_who_we_are(texts) -> bool:
    """All they said asks who we are or why we wrote ("Who is this? Why did you call me?"), greetings and
    acknowledgements aside: both prompts answer it with the company and what the campaign is about, and it is no
    request for a person (engine.settle_handover takes the model's "unclear" off it)."""
    asked = False
    for text in texts or ():
        for part in _WHO_CLAUSES.split(str(text or "")):
            words = _who_words(part)
            if not words:
                continue
            if _WHO_WE_ARE.fullmatch(words):
                asked = True
            elif words not in GREETINGS and not is_acknowledgement(part):
                return False
    return asked


def looks_like_auto_reply(text: str, seconds_after_ours: float | None = None) -> bool:
    """``seconds_after_ours``: how long after our last message this one arrived, if known.

    Within seconds of ours, any marker is a bot ("Thank you for contacting us!
    How can we help?"). Otherwise a question is a person ("Is this an automated
    message?"), and one weak phrase alone is not enough.
    """
    lowered = str(text or "").lower().replace("’", "'")
    if not lowered:
        return False
    strong = any(marker in lowered for marker in AUTO_REPLY_STRONG)
    weak = sum(1 for marker in AUTO_REPLY_WEAK if marker in lowered)
    fast = seconds_after_ours is not None and 0 <= seconds_after_ours <= AUTO_REPLY_SECONDS
    if fast and (strong or weak):
        return True
    if asks_question(lowered):
        return False
    return strong or weak >= 2


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Letters Urdu writes and Arabic does not (ٹ ڈ ڑ ں ھ ہ ے ی ک گ چ پ ...).
_URDU_LETTERS = re.compile(r"[ٹڈڑںھہۃےۓیکگچپ]")
_ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")
_ROMAN_URDU = {
    "mat", "bhejo", "karo", "karein", "nahi", "nahin", "chahiye", "hai", "hain", "kya", "aap", "mujhe",
    "zaroorat", "zarurat", "theek", "thik", "acha", "achha", "band", "galat", "ghalat", "shukriya", "kal",
    "baad", "batata", "bataunga", "hoon", "dunga",
}


def guess_language(text: str) -> str:
    """The reply language for a fixed line when the model has not judged it yet."""
    raw = str(text or "")
    if _DEVANAGARI.search(raw):
        return "hi"
    if _URDU_LETTERS.search(raw):
        return "ur"
    if _ARABIC_SCRIPT.search(raw):
        return "ar"
    if set(normalize_text(raw).split()) & _ROMAN_URDU:
        return "ur_latin"
    return "en"


# Fixed lines, in the customer's language -------------------------------------

LINES = {
    "stop_all": {
        "en": "Understood. We won't message you again. Sorry for the trouble.",
        "ar": "تم. لن نرسل لك رسائل أخرى. نعتذر عن الإزعاج.",
        "ur_latin": "Theek hai. Hum aap ko dobara message nahi karenge. Takleef ke liye maazrat.",
        "ur": "ٹھیک ہے۔ ہم آپ کو دوبارہ میسج نہیں کریں گے۔ زحمت کے لیے معذرت۔",
        "hi_latin": "Theek hai. Hum aapko dobara message nahi karenge. Takleef ke liye maafi.",
        "hi": "ठीक है। हम आपको दोबारा मैसेज नहीं करेंगे। तकलीफ़ के लिए माफ़ी।",
    },
    "wrong_number": {
        "en": "Sorry about that. We won't message this number again.",
        "ar": "نعتذر عن ذلك. لن نرسل إلى هذا الرقم مرة أخرى.",
        "ur_latin": "Maazrat. Hum is number par dobara message nahi karenge.",
        "ur": "معذرت۔ ہم اس نمبر پر دوبارہ میسج نہیں کریں گے۔",
        "hi_latin": "Maafi. Hum is number par dobara message nahi karenge.",
        "hi": "माफ़ी। हम इस नंबर पर दोबारा मैसेज नहीं करेंगे।",
    },
    "not_interested": {
        "en": "No problem, thank you for letting us know. If anything changes, just message us here.",
        "ar": "لا مشكلة، شكراً لإبلاغنا. إذا تغيّر شيء، راسلنا هنا.",
        "ur_latin": "Koi baat nahi, batane ka shukriya. Kabhi zaroorat ho to yahin message kar dein.",
        "ur": "کوئی بات نہیں، بتانے کا شکریہ۔ کبھی ضرورت ہو تو یہیں میسج کر دیں۔",
        "hi_latin": "Koi baat nahi, batane ke liye shukriya. Kabhi zaroorat ho to yahin message kar dijiye.",
        "hi": "कोई बात नहीं, बताने के लिए शुक्रिया। कभी ज़रूरत हो तो यहीं मैसेज कर दीजिए।",
    },
    "holding": {
        "en": "Our specialist has your message and will reply here.",
        "ar": "وصلت رسالتك إلى المختص لدينا وسيرد عليك هنا.",
        "ur_latin": "Aap ka message hamare specialist tak pahunch gaya hai, woh yahin jawab denge.",
        "ur": "آپ کا میسج ہمارے اسپیشلسٹ تک پہنچ گیا ہے، وہ یہیں جواب دیں گے۔",
        "hi_latin": "Aapka message hamare specialist tak pahunch gaya hai, woh yahin jawab denge.",
        "hi": "आपका मैसेज हमारे स्पेशलिस्ट तक पहुँच गया है, वो यहीं जवाब देंगे।",
    },
    "unsupported": {
        "en": "Sorry, that message type doesn't come through here. Could you type it, or send a voice note?",
        "ar": "عذراً، هذا النوع من الرسائل لا يصلنا هنا. هل يمكنك كتابتها أو إرسال رسالة صوتية؟",
        "ur_latin": "Maazrat, is qisam ka message yahan nahi aata. Kya aap likh kar ya voice note bhej sakte hain?",
        "ur": "معذرت، اس قسم کا میسج یہاں نہیں آتا۔ کیا آپ لکھ کر یا وائس نوٹ بھیج سکتے ہیں؟",
        "hi_latin": "Maafi, is tarah ka message yahan nahi aata. Kya aap likh kar ya voice note bhej sakte hain?",
        "hi": "माफ़ी, इस तरह का मैसेज यहाँ नहीं आता। क्या आप लिखकर या वॉइस नोट भेज सकते हैं?",
    },
    "ask_time": {
        "en": "Which day and exact time suit you? We're open Monday to Saturday, 10 AM to 8 PM.",
        "ar": "ما اليوم والوقت المناسبان لك؟ نحن نعمل من الاثنين إلى السبت، من 10 صباحاً حتى 8 مساءً.",
        "ur_latin": "Aap ko kaunsa din aur waqt theek rahega? Hum Monday se Saturday, subah 10 se raat 8 baje tak khule hain.",
        "ur": "آپ کو کون سا دن اور وقت ٹھیک رہے گا؟ ہم پیر سے ہفتہ، صبح 10 سے رات 8 بجے تک کھلے ہیں۔",
        "hi_latin": "Aapko kaunsa din aur time theek rahega? Hum Monday se Saturday, subah 10 se raat 8 baje tak khule hain.",
        "hi": "आपको कौन सा दिन और समय ठीक रहेगा? हम सोमवार से शनिवार, सुबह 10 से रात 8 बजे तक खुले हैं।",
    },
    # Rule 55: running late, no time given yet.
    "ask_eta": {
        "en": "No problem. Approximately what time will you reach?",
        "ar": "لا مشكلة. في أي وقت تقريباً ستصل؟",
        "ur_latin": "Koi baat nahi. Aap taqreeban kis waqt tak pahunch jayenge?",
        "ur": "کوئی بات نہیں۔ آپ تقریباً کس وقت تک پہنچ جائیں گے؟",
        "hi_latin": "Koi baat nahi. Aap lagbhag kitne baje tak pahunch jayenge?",
        "hi": "कोई बात नहीं। आप लगभग कितने बजे तक पहुँच जाएँगे?",
    },
    # Rule 56: they want to reschedule, no new time given yet.
    "ask_new_time": {
        "en": "Sure. What day and time works better for you? We're open Monday to Saturday, 10 AM to 8 PM.",
        "ar": "بالتأكيد. ما اليوم والوقت الأنسب لك؟ نحن نعمل من الاثنين إلى السبت، من 10 صباحاً حتى 8 مساءً.",
        "ur_latin": "Zaroor. Aap ke liye kaunsa din aur waqt behtar rahega? Hum Monday se Saturday, subah 10 se raat 8 baje tak khule hain.",
        "ur": "ضرور۔ آپ کے لیے کون سا دن اور وقت بہتر رہے گا؟ ہم پیر سے ہفتہ، صبح 10 سے رات 8 بجے تک کھلے ہیں۔",
        "hi_latin": "Zaroor. Aapke liye kaunsa din aur time behtar rahega? Hum Monday se Saturday, subah 10 se raat 8 baje tak khule hain.",
        "hi": "ज़रूर। आपके लिए कौन सा दिन और समय बेहतर रहेगा? हम सोमवार से शनिवार, सुबह 10 से रात 8 बजे तक खुले हैं।",
    },
    # An owner's slot for a viewing at their property: noted, a person confirms it.
    "viewing_noted": {
        "en": "Thank you. Our specialist will confirm the viewing with you here.",
        "ar": "شكراً لك. سيؤكد المختص لدينا موعد المعاينة معك هنا.",
        "ur_latin": "Shukriya. Hamare specialist yahin aap se viewing confirm kar lenge.",
        "ur": "شکریہ۔ ہمارے اسپیشلسٹ یہیں آپ سے ویونگ کنفرم کر لیں گے۔",
        "hi_latin": "Shukriya. Hamare specialist yahin aapse viewing confirm kar lenge.",
        "hi": "शुक्रिया। हमारे स्पेशलिस्ट यहीं आपसे व्यूइंग कन्फ़र्म कर लेंगे।",
    },
    # The whole reply was a price or detail the filter had to remove.
    "deflect": {
        "en": "Our specialist will confirm that with you here.",
        "ar": "سيؤكد لك المختص لدينا ذلك هنا.",
        "ur_latin": "Hamare specialist yahin aap ko is ki tasdeeq kar denge.",
        "ur": "ہمارے اسپیشلسٹ یہیں آپ کو اس کی تصدیق کر دیں گے۔",
        "hi_latin": "Hamare specialist yahin aapko iski pushti kar denge.",
        "hi": "हमारे स्पेशलिस्ट यहीं आपको इसकी पुष्टि कर देंगे।",
    },
    # The visit put off ("I will message you"): kept tentative, no times offered again.
    "let_me_know": {
        "en": "Sure. Once you know the time, let me know and I'll reserve a slot for you.",
        "ar": "بالتأكيد. عندما تعرف الوقت المناسب، أخبرنا وسنحجز لك موعداً.",
        "ur_latin": "Zaroor. Jab aap ko waqt pata ho, hamein bata dein, hum aap ke liye slot reserve kar denge.",
        "ur": "ضرور۔ جب آپ کو وقت معلوم ہو، ہمیں بتا دیں، ہم آپ کے لیے سلاٹ ریزرو کر دیں گے۔",
        "hi_latin": "Zaroor. Jab aapko time pata ho, humein bata dijiye, hum aapke liye slot reserve kar denge.",
        "hi": "ज़रूर। जब आपको समय पता हो, हमें बता दीजिए, हम आपके लिए स्लॉट रिज़र्व कर देंगे।",
    },
    # A broker in a shops campaign (the build pack's own hand-off line); the assistant then stays silent.
    "broker": {
        "en": "Thank you for your interest. Let me pass your details to the concerned agent and he will come back to you.",
        "ar": "شكراً لاهتمامك. سأحوّل بياناتك إلى الوكيل المختص وسيتواصل معك.",
        "ur_latin": "Aap ki dilchaspi ka shukriya. Main aap ki details mutalliqa agent ko de raha hoon, woh aap se rabta karenge.",
        "ur": "آپ کی دلچسپی کا شکریہ۔ میں آپ کی تفصیلات متعلقہ ایجنٹ کو دے رہا ہوں، وہ آپ سے رابطہ کریں گے۔",
        "hi_latin": "Aapki dilchaspi ke liye shukriya. Main aapki details sambandhit agent ko de raha hoon, woh aapse sampark karenge.",
        "hi": "आपकी दिलचस्पी के लिए शुक्रिया। मैं आपकी जानकारी संबंधित एजेंट को दे रहा हूँ, वो आपसे संपर्क करेंगे।",
    },
    # Shops: the first answer to the campaign is a yes, and we do not know yet who the shop is for.
    "for_whom": {
        "en": "Thank you! Is the shop for yourself, or are you checking for a client?",
        "ar": "شكراً لك! هل المحل لك شخصياً، أم تبحث عنه لعميل؟",
        "ur_latin": "Shukriya! Kya shop aap ke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",
        "ur": "شکریہ! کیا دکان آپ کے اپنے لیے ہے، یا آپ کسی کلائنٹ کے لیے دیکھ رہے ہیں؟",
        "hi_latin": "Shukriya! Kya shop aapke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",
        "hi": "शुक्रिया! क्या दुकान आपके अपने लिए है, या आप किसी क्लाइंट के लिए देख रहे हैं?",
    },
    # Shops: "Not now".
    "check_back": {
        "en": "No problem! Should I check back with you in a month?",
        "ar": "لا مشكلة! هل أتواصل معك مرة أخرى بعد شهر؟",
        "ur_latin": "Koi baat nahi! Kya main ek mahine baad aap se dobara rabta karun?",
        "ur": "کوئی بات نہیں! کیا میں ایک مہینے بعد آپ سے دوبارہ رابطہ کروں؟",
        "hi_latin": "Koi baat nahi! Kya main ek mahine baad aapse dobara sampark karun?",
        "hi": "कोई बात नहीं! क्या मैं एक महीने बाद आपसे दोबारा संपर्क करूँ?",
    },
    # Shops: yes to "Should I check back with you in a month?".
    "check_back_yes": {
        "en": "Great, I'll check back with you then.",
        "ar": "رائع، سأتواصل معك حينها.",
        "ur_latin": "Behtareen, main tab aap se dobara rabta karunga.",
        "ur": "بہترین، میں تب آپ سے دوبارہ رابطہ کروں گا۔",
        "hi_latin": "Badhiya, main tab aapse dobara sampark karunga.",
        "hi": "बढ़िया, मैं तब आपसे दोबारा संपर्क करूँगा।",
    },
    # Shops: a no ("Not now" then no, already rented then no, not interested): the lead is lost.
    "shops_not_interested": {
        "en": "No problem, thank you for letting us know.",
        "ar": "لا مشكلة، شكراً لإبلاغنا.",
        "ur_latin": "Koi baat nahi, batane ka shukriya.",
        "ur": "کوئی بات نہیں، بتانے کا شکریہ۔",
        "hi_latin": "Koi baat nahi, batane ke liye shukriya.",
        "hi": "कोई बात नहीं, बताने के लिए शुक्रिया।",
    },
    # Shops: "Stop messages", or any STOP.
    "shops_stop_all": {
        "en": "Done, you won't receive more messages from us.",
        "ar": "تم، لن تصلك منا رسائل أخرى.",
        "ur_latin": "Ho gaya, aap ko hamari taraf se mazeed messages nahi aayenge.",
        "ur": "ہو گیا، آپ کو ہماری طرف سے مزید میسجز نہیں آئیں گے۔",
        "hi_latin": "Ho gaya, aapko hamari taraf se aur messages nahi aayenge.",
        "hi": "हो गया, आपको हमारी तरफ़ से और मैसेज नहीं आएँगे।",
    },
    # "How do I reach there?" once our location went out: the reply points to it (engine.settle).
    "location_above": {
        "en": "Our office location is in my message above.",
        "ar": "موقع مكتبنا موجود في رسالتي أعلاه.",
        "ur_latin": "Hamare office ki location upar wale message mein hai.",
        "ur": "ہمارے آفس کی لوکیشن اوپر والے میسج میں ہے۔",
        "hi_latin": "Hamare office ki location upar wale message mein di gayi hai.",
        "hi": "हमारे ऑफ़िस की लोकेशन ऊपर वाले मैसेज में है।",
    },
    # Shops: the build pack's licence request, once the customer has a DED or Trakhees licence (shop_flow).
    "licence_copy": {
        "en": "Perfect! Please share a copy of your trade license here (photo or PDF). It helps us show you shops that suit your business activity.",
        "ar": "ممتاز! يرجى مشاركة نسخة من رخصتك التجارية هنا (صورة أو PDF). يساعدنا ذلك على عرض المحلات التي تناسب نشاطك التجاري.",
        "ur_latin": "Perfect! Barah-e-karam apne trade license ki copy yahan share kar dein (photo ya PDF). Is se hum aap ko aap ke business ke mutabiq shops dikha sakenge.",
        "ur": "بہترین! براہ کرم اپنے ٹریڈ لائسنس کی کاپی یہاں شیئر کر دیں (فوٹو یا PDF)۔ اس سے ہم آپ کو آپ کے کاروبار کے مطابق دکانیں دکھا سکیں گے۔",
        "hi_latin": "Perfect! Kripya apne trade license ki copy yahan share kar dijiye (photo ya PDF). Isse hum aapko aapke business ke hisaab se shops dikha payenge.",
        "hi": "बहुत बढ़िया! कृपया अपने ट्रेड लाइसेंस की कॉपी यहाँ शेयर कर दीजिए (फ़ोटो या PDF)। इससे हम आपको आपके बिज़नेस के हिसाब से दुकानें दिखा पाएँगे।",
    },
    # Shops: the licence copy came, while the request was open.
    "licence_thanks": {
        "en": "Thank you, got it.",
        "ar": "شكراً لك، وصلتني.",
        "ur_latin": "Shukriya, mil gaya.",
        "ur": "شکریہ، مل گیا۔",
        "hi_latin": "Shukriya, mil gaya.",
        "hi": "शुक्रिया, मिल गया।",
    },
    # Shops: "Need to reschedule", before the two nearest free slots (shop_flow.reschedule_text).
    "reschedule_slots": {
        "en": "Sure.",
        "ar": "بالتأكيد.",
        "ur_latin": "Zaroor.",
        "ur": "ضرور۔",
        "hi_latin": "Zaroor.",
        "hi": "ज़रूर।",
    },
    # Shops: they already rented a shop elsewhere ("we got one"): the build pack's congratulation and its
    # second-shop question (board T27); a no to it closes the lead as already rented (engine RENTED_NO).
    "rented_second_shop": {
        "en": "Congratulations on your new shop! Do you need a second shop, or do you know someone who does?",
        "ar": "مبروك على محلك الجديد! هل تحتاج محلاً ثانياً، أو تعرف أحداً يحتاج؟",
        "ur_latin": "Nayi shop mubarak ho! Kya aap ko ek aur shop chahiye, ya aap kisi ko jaante hain jise zaroorat ho?",
        "ur": "نئی دکان مبارک ہو! کیا آپ کو ایک اور دکان چاہیے، یا آپ کسی کو جانتے ہیں جسے ضرورت ہو؟",
        "hi_latin": "Nayi shop mubarak ho! Kya aapko ek aur shop chahiye, ya aap kisi ko jaante hain jise zaroorat ho?",
        "hi": "नई दुकान मुबारक हो! क्या आपको एक और दुकान चाहिए, या आप किसी को जानते हैं जिसे ज़रूरत हो?",
    },
    # Shops: the build pack's first discovery question, before a second invitation (engine.discovery_first).
    "ask_business": {
        "en": "What business will the shop be for?",
        "ar": "ما النشاط التجاري الذي سيكون المحل له؟",
        "ur_latin": "Shop kis business ke liye hogi?",
        "ur": "دکان کس کاروبار کے لیے ہوگی؟",
        "hi_latin": "Shop kis business ke liye hogi?",
        "hi": "दुकान किस बिज़नेस के लिए होगी?",
    },
    # Shops: the build pack's next question when the reply invited before the licence was known.
    "ask_licence": {
        "en": "Do you have a DED or Trakhees licence, or will you open a new one?",
        "ar": "هل لديك رخصة DED أو Trakhees، أم ستفتح رخصة جديدة؟",
        "ur_latin": "Kya aap ke paas DED ya Trakhees ka licence hai, ya aap naya licence banwayenge?",
        "ur": "کیا آپ کے پاس DED یا Trakhees کا لائسنس ہے، یا آپ نیا لائسنس بنوائیں گے؟",
        "hi_latin": "Kya aapke paas DED ya Trakhees ka licence hai, ya aap naya licence banwayenge?",
        "hi": "क्या आपके पास DED या Trakhees का लाइसेंस है, या आप नया लाइसेंस बनवाएँगे?",
    },
}

# The shops playbook says these in its own words (the build pack's).
SHOPS_LINES = {STOP_ALL: "shops_stop_all", NOT_INTERESTED: "shops_not_interested"}


def line(kind: str, language: str) -> str:
    table = LINES[kind]
    return table.get(language) or table["en"]


def line_for(kind: str, language: str, shops: bool = False) -> str:
    """``line``, in the shops playbook's own words where it has them."""
    return line(SHOPS_LINES.get(kind, kind) if shops else kind, language)
