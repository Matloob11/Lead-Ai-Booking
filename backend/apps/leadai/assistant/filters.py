"""What leaves for the customer: the reply filter and the texts code writes itself.

- Booking messages (confirm, reschedule, running late, on my way) are written
  here from the validated time, in the customer's language, so the date in
  the message can never differ from the date that was booked, and the owner's
  wording of rules 50, 54 and 55 is kept exactly.
- Every other reply passes ``clean_reply``: no links, phone numbers or e-mail
  addresses (the office link is added by code), no amounts that appear
  nowhere in the conversation, no markdown, no claim to be a person.
"""

from __future__ import annotations

import re

from . import hours

REPLY_MAX = 600

_URL = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:com|ae|net|org|io|co)(?:/\S*)?\b)", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
# A phone number has at least 9 digits; "400 - 500 sq ft" or "13-10-2026" is not one.
_PHONE = re.compile(r"(?<![\w])\+?\d[\d\s().-]{7,}\d")
PHONE_DIGITS = 9
# A number, with thousands separators, decimals and a k / m / lakh multiplier.
_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:\s*(k|mn|m|million|thousand|lakh|lac)\b)?",
    re.IGNORECASE,
)
_MULTIPLIER = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000, "lakh": 100_000, "lac": 100_000}
# Words that make a number in the same sentence a price, rent or fee.
_PRICE_WORDS = re.compile(
    r"(aed|dhs?\b|dirhams?|درهم|دراهم|\brent|price|cost|\bfees?\b|charges?\b|deposit|commission|budget|"
    r"per\s+(year|month|annum)|yearly|monthly|annual|a\s+year|a\s+month|/\s*(year|yr|month|mo)\b|"
    r"kiraya|qeemat|keemat|إيجار|سعر|ألف|الف|ہزار|هزار|hazaar|hazar|किराया|कीमत|हज़ार|हजार)",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"(\*\*|__|##+|^\s*[-*•]\s+)", re.MULTILINE)
_HUMAN_CLAIM = re.compile(
    r"(\b(i\s*am|i'm|im)\s+(a\s+)?(real\s+)?(human|person|not\s+a\s+bot|not\s+an?\s+ai)\b"
    r"|\b(main|mein|mai)\s+(ek\s+)?(asli\s+)?(insaan|insan)\b|\b(insaan|insan)\s+(hoon|hun|hu)\b"
    r"|\b(bot|robot)\s+(nahi|nahin)\s+(hoon|hun|hu)\b"
    r"|أنا\s+(إنسان|انسان|شخص\s+حقيقي)|لست\s+(روبوت|بوت|آلة)"
    r"|میں\s+(ایک\s+)?انسان\s+ہوں|میں\s+(بوٹ|روبوٹ)\s+نہیں"
    r"|मैं\s+(एक\s+)?इंसान\s+हूँ|मैं\s+(बॉट|रोबोट)\s+नहीं)",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?؟۔])\s+|\n+")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def numbers_in(text: str) -> list[tuple[int, bool]]:
    """Every number in the text as (whole value, written with a multiplier): '40k' is (40000, True)."""
    out = []
    for match in _NUMBER.finditer(text or ""):
        whole = match.group(1).replace(",", "")
        try:
            value = float(f"{whole}.{match.group(2)}") if match.group(2) else float(whole)
        except ValueError:
            continue
        multiplier = _MULTIPLIER.get((match.group(3) or "").lower(), 1)
        out.append((int(round(value * multiplier)), multiplier != 1))
    return out


AMOUNT_FLOOR = 1000


def _invented_amount(sentence: str, known: set[int], floor: int = AMOUNT_FLOOR) -> bool:
    """A price-like number the customer, the campaign or a colleague never wrote; ``floor``: the smallest amount checked
    (batch 2e's residential replies check from 100, so an invented "Ejari AED 250" goes too)."""
    priced = bool(_PRICE_WORDS.search(sentence))
    for value, scaled in numbers_in(sentence):
        if (scaled or (priced and value >= floor)) and value not in known:
            return True
    return False


def mentions_price(text: str) -> bool:
    """The text is about a price, rent, fee or budget (in any of the languages here)."""
    return bool(_PRICE_WORDS.search(text or ""))


def _strip_phones(text: str) -> str:
    return _PHONE.sub(lambda m: "" if len(_digits(m.group(0))) >= PHONE_DIGITS else m.group(0), text)


def clean_reply(reply: str, context_text: str, *, max_questions: int = 1, amount_floor: int = AMOUNT_FLOOR) -> tuple[str, list[str]]:
    """The reply made safe to send, and notes on what was removed (for the turn log).

    ``context_text`` is everything the customer, the campaign and our
    colleagues wrote (never the assistant's own replies): an amount found
    there may be repeated, in any form ("40k" covers "AED 40,000"); any other
    price-like number takes its sentence with it. ``max_questions``: questions a
    reply may ask (two on batch 2e's rent and sale tracks, spec §1.3); ``amount_floor``:
    the smallest price-like amount checked (100 there, spec §2.4).
    """
    notes: list[str] = []
    text = (reply or "").replace("’", "'")
    if _MARKDOWN.search(text):
        text = _MARKDOWN.sub("", text)
        notes.append("markdown")
    for pattern, label in ((_URL, "link"), (_EMAIL, "email")):
        if pattern.search(text):
            text = pattern.sub("", text)
            notes.append(label)
    without_phones = _strip_phones(text)
    if without_phones != text:
        text = without_phones
        notes.append("phone")

    known = {value for value, _ in numbers_in(context_text)}
    kept = []
    for sentence in _SENTENCE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if _invented_amount(sentence, known, amount_floor):
            notes.append("amount")
            continue
        if _HUMAN_CLAIM.search(sentence):
            notes.append("human_claim")
            continue
        kept.append(sentence)
    # The owner's style: one question per reply. A second one is nearly always
    # "which day and time?" after an invitation, and waits for the answer.
    single, asked = [], 0
    for sentence in kept:
        if any(mark in sentence for mark in QUESTION_MARKS):
            if asked >= max(1, max_questions):
                notes.append("second_question")
                continue
            asked += 1
        single.append(sentence)
    text = " ".join(single)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text[:REPLY_MAX], notes


QUESTION_MARKS = ("?", "؟", "？")
_INVITATION = re.compile(
    r"\b(visit|meet|meeting|appointment|come (to|by|over)|our office|daftar|office aa|mulaqat)\b|مكتب|زيارة|موعد|دفتر|ملاقات",
    re.IGNORECASE,
)


# A question that only asks them to choose between what the sentence before it offered ("Which is better?",
# "Which works better for you?", "kaunsa behtar rahega?"): once that offer is gone it asks nothing (launch review:
# chat 62's "Photos help, ... Which is better?" after its invitation was cut).
_CHOICE_ONLY = re.compile(
    r"^\W*(?:so\s+|and\s+)?(?:which|kaunsa|kaun\s*sa|konsa|kon\s*sa|أيهما|أي|اي|کون\s*سا|कौन\s*सा)(?!\w)"
    r"(?![^?؟]*\b(?:type|types|size|budget|business|licen[cs]e|cluster)\b)"
    r"[^?؟.!]{0,40}(?:better|best|suit|suits|work|works|prefer|behtar|theek|thik|أفضل|افضل|يناسب|بہتر|ٹھیک|बेहतर|ठीक)"
    r"[^?؟.!]{0,20}[?؟]\s*$",
    re.IGNORECASE,
)
# ... or one that asks whether that offer suits them ("Is this time OK for you?", "Does that work for you?", "Kya yeh
# waqt aapke liye theek hai?"), never one about a discovery item, the location or the photos.
_ABOUT_THE_OFFER = re.compile(
    r"^(?![^?؟]*\b(?:type|types|size|budget|business|licen[cs]e|cluster|location|address|photos?|pictures?|video)\b)"
    r"(?=[^?؟]*(?:\b(?:that|this|it|these|those|yeh|ye|woh|wo|waqt|time|times|slot|slots)\b|ذلك|هذا|هذه|الوقت|یہ|وقت|यह|वह|समय))"
    r"(?=[^?؟]*(?:\b(?:works?|suits?|ok|okay|fine|good|convenient|theek|thik|sahi|behtar|better|munasib)\b|يناسب|مناسب|ٹھیک|ठीक|सही))"
    r"[^.!?؟]{0,80}[?؟]\s*$",
    re.IGNORECASE,
)


def _asks_about_the_offer(sentence: str) -> bool:
    """A question left asking them to choose, or to agree to, what the sentence before it offered (_CHOICE_ONLY,
    _ABOUT_THE_OFFER), in twelve words at most."""
    text = (sentence or "").strip()
    return len(text.split()) <= 12 and bool(_CHOICE_ONLY.search(text) or _ABOUT_THE_OFFER.search(text))


def drop_invitations(text: str, also=None) -> tuple[str, bool]:
    """The reply without its sentences that invite to the office (after two refusals), nor the question left
    asking them to choose between what those offered ("Which is better?"). ``also``: what else is an
    invitation (a shops chat's slots, in words of no visit: offers.pushes_visit). The reply is unchanged when
    nothing went."""
    kept, gone, dropped = [], False, False
    for sentence in split_sentences(text):
        if _INVITATION.search(sentence) or (also is not None and also(sentence)):
            gone = dropped = True
            continue
        if gone and _asks_about_the_offer(sentence):
            continue
        gone = False
        kept.append(sentence)
    if not dropped:
        return (text or "").strip(), False
    return " ".join(kept).strip(), True


def is_invitation(text: str) -> bool:
    """The message asks them to visit or meet us (any of our messages: ours, a colleague's, a campaign's)."""
    return bool(_INVITATION.search(text or ""))


# An exact time of day ("11 AM", "5:30", "kal 5 baje", "الساعة 5"): a slot offered.
_CLOCK_TIME = re.compile(
    r"\b\d{1,2}(:[0-5]\d)?\s*(am|pm|a\.m\.|p\.m\.)(?!\w)|\b\d{1,2}:[0-5]\d\b|\b\d{1,2}\s*(baje|bajay|bje)\b"
    r"|\d{1,2}\s*(بجے|बजे|صباحاً|صباحا|مساءً|مساء)|الساعة\s*\d",
    re.IGNORECASE,
)


def offers_time(text: str) -> bool:
    """The message names an exact time ("Would 11 AM or 5 PM work?"), with or without a word of a visit."""
    return bool(_CLOCK_TIME.search(text or ""))


# An open question about WHEN to come ("When would you like to come?", "Which day
# suits you?"), which the shops playbook never asks: it names two free slots.
_WHEN_VISIT = re.compile(
    r"\bwhen (?:would|will|can|could|do|shall) you (?:like to |want to |prefer to |be able to |plan to )?"
    r"(?:come|visit|drop|pass|stop|meet|see|pop)"
    r"|\bwhen (?:are|r) you (?:free|available|coming)"
    r"|\b(?:what|which) (?:day|time|date|days|times)\b"
    r"|\bkab (?:aa|aana|aayenge|aaenge|aa sakte|aasakte|tashreef|visit|mil)"
    r"|متى (?:يمكنك|تستطيع|تود|تريد|يناسبك|ستأتي|تأتي)|أي وقت|اي وقت|أي يوم|اي يوم"
    r"|کب (?:آ|تشریف)|کس دن|کتنے بجے"
    r"|कब (?:आ|मिल)|किस दिन|कितने बजे",
    re.IGNORECASE,
)
# About opening the shop, not coming to see it ("When do you want to open?").
_OPENING = re.compile(r"\b(?:open|opening|start|launch)\b|kholna|khol|افتتاح|فتح|کھول|खोल", re.IGNORECASE)
# About arriving at a viewing already booked ("Approximately what time will you reach?").
_ARRIVAL = re.compile(
    r"\b(?:reach|reaching|arrive|arriving|arrival|get here|get there|eta)\b|pahunch|pohanch|پہنچ|تصل|يصل|ستصل|وصول|पहुँच|पहुंच",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    """The reply's sentences, as the filters here read them."""
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def is_open_when(sentence: str) -> bool:
    """One of our sentences asks when (or whether) they will come without naming a time."""
    text = sentence or ""
    if not any(mark in text for mark in QUESTION_MARKS) or offers_time(text):
        return False
    if _OPENING.search(text) or asks_for_location(text) or _ARRIVAL.search(text):
        return False
    return bool(_WHEN_VISIT.search(text)) or is_invitation(text)


def _sentence_key(sentence: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(sentence or "").casefold()).split())


def said_before(text: str, sent: list[str]) -> bool:
    """Every sentence of ``text`` is one that an earlier message of ours (``sent``) said word for word."""
    said = {_sentence_key(s) for message in sent for s in _SENTENCE.split(message or "") if _sentence_key(s)}
    keys = [_sentence_key(s) for s in split_sentences(text)]
    return bool(keys) and all(key in said for key in keys)


def drop_repeats(text: str, sent: list[str], keep=None) -> tuple[str, bool]:
    """The reply without the sentences one of our earlier messages already said word for
    word (the shops build pack: never the same sentence twice in a chat).

    A question is never dropped: asked again, it still wants its answer ("Is the shop
    for yourself, or are you checking for a client?" after answering the rent). Nor is
    a sentence ``keep`` accepts (the playbook's fixed answers, said each time they fit:
    "Good question — I'll have our agent confirm that for you at the viewing."). A
    reply that is nothing else stays whole: a repeat beats no answer."""
    said = {_sentence_key(s) for message in sent for s in _SENTENCE.split(message or "") if _sentence_key(s)}
    sentences = split_sentences(text)

    def repeated(sentence: str) -> bool:
        if _sentence_key(sentence) not in said or any(mark in sentence for mark in QUESTION_MARKS):
            return False
        return not (keep is not None and keep(sentence))

    kept = [s for s in sentences if not repeated(s)]
    if not kept or len(kept) == len(sentences):
        return (text or "").strip(), False
    return " ".join(kept), True


def offer_slots(text: str, line: str) -> tuple[str, bool]:
    """The reply with its open "when would you like to come?" replaced by ``line`` (two
    concrete slots), and whether it was; a second question goes with it (one per reply)."""
    if not line:
        return (text or "").strip(), False
    sentences = split_sentences(text)
    if not any(is_open_when(sentence) for sentence in sentences):
        return (text or "").strip(), False
    kept = [s for s in sentences if not is_open_when(s) and not any(mark in s for mark in QUESTION_MARKS)]
    return " ".join([*kept, line]), True


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").lower()).split())


# Words any address has, or that the model writes its own way ("Bldg" for
# "Building"): they tell no address apart, so they are not looked for.
_ADDRESS_WORDS = {
    "building", "bldg", "bld", "shop", "office", "no", "number", "unit", "floor", "flat", "the", "at", "in", "of",
    "near", "street", "st", "road", "rd", "cluster", "city", "dubai", "uae",
}


def carries_location(text: str, office_address: str, maps_url: str = "") -> bool:
    """The text holds the office's Maps link or its address: every word that tells the
    address apart (the cluster's name, the building code, the shop number), in any
    order, case or punctuation, so "Russia Cluster, Bldg V03, Shop 20" counts.
    Of an address in three parts or more the last (the city, which the model
    shortens or moves: "International City, Dubai") is not needed."""
    if maps_url and maps_url in (text or ""):
        return True
    parts = [part for part in (_plain(piece) for piece in str(office_address or "").split(",")) if part]
    if len(parts) >= 3:
        parts = parts[:-1]
    needed = {word for part in parts for word in part.split()} - _ADDRESS_WORDS
    plain = _plain(text)
    if needed and all(word.isdigit() for word in needed):
        # Only numbers tell it apart ("Shop 5, Building 3"): "3 PM or 5 PM" must not count, so each part whole.
        return all(f" {part} " in f" {plain} " for part in parts)
    return bool(needed) and needed <= set(plain.split())


def drop_location(text: str, office_address: str, maps_url: str = "") -> tuple[str, bool]:
    """The reply without its sentences that give the office's address again (it went
    out already); a reply that is nothing else stays whole: a repeat beats no answer."""
    sentences = [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]
    kept = [s for s in sentences if not carries_location(s, office_address, maps_url)]
    if not kept or len(kept) == len(sentences):
        return (text or "").strip(), False
    return " ".join(kept), True


# The customer asks for the location itself ("send the location", "your address?",
# "google map"): it goes again, however recently it went. Not "how do I reach
# there?", which the location already sent answers, nor "pata" (also "know").
_LOCATION_ASK = re.compile(
    r"\b(location|locations|address|map|maps|pin|directions?)\b|موقع|عنوان|لوكيشن|لوکیشن|ایڈریس|लोकेशन|एड्रेस",
    re.IGNORECASE,
)


def asks_for_location(text: str) -> bool:
    return bool(_LOCATION_ASK.search(text or ""))


# The customer asks the way to us, or where we are, without asking for the location
# itself (that is asks_for_location, which sends it again): "How do I reach there?",
# "How do I come?", "Where is your office?", "Which way to your office?", "kaise aaun?",
# "كيف أصل؟". Once our location went out, the reply points to it (engine.settle). Not
# "How do I get a licence?", "How do I come up with the deposit?" or "Which way is
# better?", nor "Where is it?": the "it" may be the shop or the unit we described.
_THE_WAY = re.compile(
    r"\bhow\s+(?:do|can|could|should|shall|will|would|to)\s+(?:i\s+|we\s+)?"
    # "come" ends the question, or a comma brings the means ("How should we come, by
    # metro?"); "How should I come, with my partner or alone?" is not the way.
    r"(?:reach|arrive|come\s+(?:there|here|to|over)|come(?=\s*(?:[?.!؟]|$|,\s*by\b))|get\s+(?:there|here|to)|go\s+(?:there|to)"
    r"|find\s+(?:you|your|ur|the\s+office|it))\b"
    # "Which way to your office / to you", "which way is the office": not "which way is
    # your shop facing" or "which way for you is better, cash or cheque".
    r"|\bwhich\s+way\s+(?:to\s+(?:you|u|your|ur|the\s+office)|is\s+(?:your|ur|the)\s+office)\b"
    r"|\bwhere\s+(?:is|are|r)\s+(?:you|u|your|ur|the\s+office)\b|\bwhere\s+exactly\b"
    r"|\b(?:can'?t|cannot|couldn'?t|not\s+able\s+to)\s+find\s+(?:you|your|ur|the\s+office|it)\b"
    r"|\bkaise\s+(?:aa|aaun|aaoon|aaon|aayen|aaen|aain|aana|pahunch\w*|pohanch\w*)"
    r"|\b(?:office|daftar)\s+(?:kahan|kidhar)\b|\b(?:kahan|kidhar)\s+(?:hai|hain|ho|par|pe|pr)\b"
    r"|كيف\s+(?:أصل|اصل|أوصل|اوصل|أجي|اجي|آجي|أروح|اروح)|(?:وين|أين|اين|فين)\s+(?:مكتبكم|المكتب|انتم|أنتم|موقعكم|مكانكم)|وينكم"
    r"|کیسے\s+(?:آؤں|آؤ|آئیں|آنا|پہنچوں|پہنچیں|پہنچ)|(?:آفس|دفتر)\s+کہاں|کہاں\s+(?:ہے|ہیں)"
    r"|कैसे\s+(?:आऊं|आऊँ|आएं|आएँ|आना|पहुंच|पहुँच)|(?:ऑफिस|ऑफ़िस|दफ्तर)\s+(?:कहाँ|कहां)|(?:कहाँ|कहां)\s+(?:है|हैं)",
    re.IGNORECASE,
)
# A reply that already points to the location we sent ("the location above", "already
# shared"). Strict on purpose: missing one only adds the pointer twice, while reading
# "Shops above 400 sq ft" as one would leave "How do I reach there?" unanswered.
_POINTER = re.compile(
    r"\b(?:location|address|pin|map|maps|link|details|message)\b[^.?!]{0,25}?\b(?:above|earlier|before|previously|already)\b"
    r"|\b(?:above|earlier|previous)\b[^.?!]{0,12}?\b(?:location|address|pin|map|link|message)\b"
    r"|\b(?:already|i'?ve|i\s+have|we'?ve|we\s+have|i|we)\s+(?:already\s+)?(?:shared|sent|given)\b"
    r"|\b(?:upar|oopar)\s+wal[aei]\b|\bbhej\s+(?:di|diya|chuke|chuka)\b"
    r"|أعلاه|بالأعلى|بالاعلى|أرسلت|ارسلت|أرسلنا|ارسلنا|الرسالة السابقة"
    r"|اوپر\s+(?:والے|والی|والا|دیکھ)|بھیج\s+(?:دی|دیا|چکے)|ऊपर\s+(?:वाले|वाली|वाला|देख)|भेज\s+(?:दी|दिया|चुके)",
    re.IGNORECASE,
)


def asks_the_way(text: str) -> bool:
    return bool(_THE_WAY.search(str(text or "").replace("’", "'")))


def points_to_location(text: str) -> bool:
    return bool(_POINTER.search(str(text or "").replace("’", "'")))


# Booking texts ------------------------------------------------------------------

CONFIRM = {
    "en": ("Perfect, {name}. Your meeting is confirmed.", "Date", "Time", "International City Office", "Our {who} will be expecting you."),
    "ar": ("ممتاز {name}. تم تأكيد موعدك.", "التاريخ", "الوقت", "مكتب المدينة العالمية (International City)", "سيكون {who} بانتظارك."),
    "ur_latin": ("Perfect, {name}. Aap ki meeting confirm ho gayi hai.", "Date", "Time", "International City Office", "Hamare {who} aap ka intezar karenge."),
    "ur": ("بہت خوب {name}۔ آپ کی میٹنگ کنفرم ہو گئی ہے۔", "تاریخ", "وقت", "انٹرنیشنل سٹی آفس", "ہمارے {who} آپ کا انتظار کریں گے۔"),
    "hi_latin": ("Perfect, {name}. Aapki meeting confirm ho gayi hai.", "Date", "Time", "International City Office", "Hamare {who} aapka intezaar karenge."),
    "hi": ("बहुत बढ़िया {name}। आपकी मीटिंग कन्फ़र्म हो गई है।", "तारीख़", "समय", "इंटरनेशनल सिटी ऑफ़िस", "हमारे {who} आपका इंतज़ार करेंगे।"),
}
RESCHEDULE_HEAD = {
    "en": "Done, {name}. Your meeting is now on:",
    "ar": "تم {name}. أصبح موعدك:",
    "ur_latin": "Ho gaya, {name}. Aap ki meeting ab is waqt hai:",
    "ur": "ہو گیا {name}۔ آپ کی میٹنگ اب اس وقت ہے:",
    "hi_latin": "Ho gaya, {name}. Aapki meeting ab is time par hai:",
    "hi": "हो गया {name}। आपकी मीटिंग अब इस समय है:",
}
SPECIALIST = {
    "en": {"commercial": "commercial specialist", "other": "specialist"},
    "ar": {"commercial": "مختص العقارات التجارية لدينا", "other": "المختص لدينا"},
    "ur_latin": {"commercial": "commercial specialist", "other": "specialist"},
    "ur": {"commercial": "کمرشل اسپیشلسٹ", "other": "اسپیشلسٹ"},
    "hi_latin": {"commercial": "commercial specialist", "other": "specialist"},
    "hi": {"commercial": "कमर्शियल स्पेशलिस्ट", "other": "स्पेशलिस्ट"},
}
ARRIVAL = {
    "en": "Perfect, I've updated your arrival time to {time}.",
    "ar": "ممتاز، قمت بتحديث وقت وصولك إلى {time}.",
    "ur_latin": "Perfect, maine aap ka aane ka waqt {time} kar diya hai.",
    "ur": "بہت خوب، میں نے آپ کے آنے کا وقت {time} کر دیا ہے۔",
    "hi_latin": "Perfect, maine aapka aane ka time {time} kar diya hai.",
    "hi": "बहुत बढ़िया, मैंने आपके आने का समय {time} कर दिया है।",
}
ON_MY_WAY = {
    "en": "Perfect. See you shortly.",
    "ar": "ممتاز. نراك قريباً.",
    "ur_latin": "Perfect. Jald mulaqat hoti hai.",
    "ur": "بہت خوب۔ جلد ملاقات ہوتی ہے۔",
    "hi_latin": "Perfect. Jald milte hain.",
    "hi": "बहुत बढ़िया। जल्द मिलते हैं।",
}


def _lang(language: str, table: dict) -> str:
    return language if language in table else "en"


_NOT_A_NAME = re.compile(r"[\[\]<>{}=/\\@:|*_~`#]")
_HONORIFICS = {"mr", "mrs", "ms", "miss", "mx", "dr", "sir", "madam", "maam", "mam", "eng", "engr", "prof", "capt"}
# "Md Sumon" goes by Sumon: these open a name, and the next word is the one used,
# unless it is a particle: "Mohammed Al Mansouri" is Mohammed, never "Al".
_NAME_PREFIXES = {"md", "mohd", "muhd", "mhd", "muhammad", "muhammed", "mohammad", "mohammed"}
_NAME_PARTICLES = {"al", "el", "bin", "ibn", "bint", "abu", "abd", "abdul", "abdel"}
# What a CRM card or a WhatsApp profile holds when it holds no name.
_NOT_NAMES = {
    "lead", "client", "customer", "owner", "tenant", "buyer", "landlord", "test", "unknown", "new",
    "shop", "office", "flat", "na", "none", "null", "user", "contact", "whatsapp",
    # A portal lead's title with no name after it ("Bayut WhatsApp").
    "bayut", "property", "propertyfinder", "dubizzle", "portal",
    # The campaign's greeting for a lead with no usable name (crm_leads.lead_display_name).
    "there",
    # Alone, an abbreviation or a particle is nobody's name to greet ("Hi Md", "Hi Al").
    "md", "mohd", "muhd", "mhd", "al", "el", "bin", "ibn", "bint",
}
_PHONE_ONLY = re.compile(r"[+\d\s().-]+")
_A_CALL = re.compile(r"(missed\s+)?call\b", re.IGNORECASE)
# A job title, or a word of an address or a company, where a CRM card or a profile should hold a name: the launch
# campaigns greeted "Hi MANAGER" and "Hi Road" (launch review issue 26). Never greeted; a name after one is the
# name ("Manager Ahmed" is Ahmed).
_NOT_PERSONS = {
    "manager", "admin", "administrator", "director", "ceo", "cfo", "coo", "cto", "gm", "founder", "cofounder", "chairman",
    "president", "partner", "proprietor", "boss", "supervisor", "accountant", "accounts", "sales", "salesman", "marketing",
    "hr", "staff", "team", "agent", "broker", "realtor", "secretary", "reception", "receptionist", "engineer", "technician",
    "company", "business", "trading", "llc", "fze", "fzco", "fzc", "est", "establishment", "group", "properties", "realty",
    "estate", "road", "street", "building", "tower", "villa", "apartment", "studio", "room", "store", "mall", "market",
    "cluster", "city", "dubai", "sharjah", "ajman", "uae", "international", "personal", "private", "home", "work", "mobile",
    "phone", "number",
}
# A word of capitals this short may be initials or a company ("ETS"): kept as it is written, never "Ets", when it reads
# as initials (_initials); a short name in capitals is a name ("ALI" is Ali, "MD ALI" Ali: review 2d).
INITIALS_MAX = 3
_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)
_VOWELS = frozenset("AEIOUY")


def _initials(letters: str) -> bool:
    """Capitals that read as initials, not a short name: no vowel ("SK", "MD"), or two different consonants side by
    side ("ETS", "ABC", "IBM"); "ALI", "ZIA", "RAJ", "SAM", "AMY", "JOY" and "OM" are names."""
    upper = letters.upper()
    if not any(ch in _VOWELS for ch in upper):
        return True
    return any(a not in _VOWELS and b not in _VOWELS and a != b for a, b in zip(upper, upper[1:]))


def _names_nobody(text: str) -> bool:
    """Every word is a placeholder, an honorific, a job title or a word of an address ("Sales Manager", "Road")."""
    words = [word.casefold() for word in _LETTERS.findall(text or "")]
    return bool(words) and all(word in _NOT_NAMES or word in _NOT_PERSONS or word in _HONORIFICS for word in words)


def person_name(raw: str) -> str:
    """The person a CRM title names, or ''.

    Portal leads are titled "<source> <channel> | <name>": "Bayut WhatsApp |
    Md Sumon" is "Md Sumon". What follows the last "|" is the name; nothing,
    a phone number, a "Missed Call..." or a placeholder ("there", the
    campaign's greeting for a lead with no name), a job title or a word of an
    address ("MANAGER", "Road") there names nobody.
    """
    text = " ".join(str(raw or "").split())
    if "|" in text:
        text = text.rsplit("|", 1)[1].strip()
    if not text or _A_CALL.match(text) or text.strip(".").casefold() in _NOT_NAMES or _names_nobody(text):
        return ""
    if _PHONE_ONLY.fullmatch(text) and sum(ch.isdigit() for ch in text) >= 7:
        return ""
    return text


def _cased(word: str, *, shouting: bool = False) -> str:
    """One word as a name is written: all small letters, or capitals past INITIALS_MAX letters (or among a name
    written all in capitals, ``shouting``), get a capital first ("kamalraafat" Kamalraafat, "AHMED" Ahmed); short
    capitals stay ("ETS")."""
    letters = "".join(_LETTERS.findall(word))
    if len(letters) < 2:
        return word
    if letters.islower() or (letters.isupper() and (len(letters) > INITIALS_MAX or shouting or not _initials(letters))):
        return word[:1].upper() + word[1:].lower()
    return word


def cased(name: str) -> str:
    """The name with its case put right, word by word (_cased): what the assistant's own lines, the CUSTOMER NAME it
    reads and our alerts and Bitrix comments say ("ora" Ora, "MOHAMMED ALI" Mohammed Ali; "ETS" stays)."""
    words = str(name or "").split()
    return " ".join(_cased(word, shouting=_shouting(words)) for word in words)


def _shouting(words) -> bool:
    """A name written all in capitals with a word longer than initials ("MOHAMMED ALI"): every word of it is cased."""
    letters = "".join("".join(_LETTERS.findall(word)) for word in words)
    return letters.isupper() and any(len("".join(_LETTERS.findall(word))) > INITIALS_MAX for word in words)


def first_name(name: str) -> str:
    """A safe first name: letters only, at most 20 characters, else ''.

    "Mr. Ahmed Khan" gives "Ahmed" and "AHMED KHAN" gives "Ahmed"; "Bayut
    WhatsApp | Md Sumon" (a portal lead's title) gives "Sumon". A word
    carrying markup or digits is not a name ("[URL=x]Click", a phone number),
    so it is dropped rather than cleaned into something that reads like one;
    so is a placeholder such as "Lead" or "Customer", and a job title or a
    word of an address ("MANAGER", "Road"; a name after one is the name). Emoji
    and dots are only trimmed off. Its case is put right ("kamalraafat"
    Kamalraafat), short capitals kept ("ETS": maybe initials; launch review 26).
    """
    whole = person_name(name)
    parts = whole.split()
    while parts and (parts[0].strip(".").lower() in _HONORIFICS or parts[0].strip(".").lower() in _NOT_PERSONS):
        parts.pop(0)
    if len(parts) > 1 and parts[0].strip(".").lower() in _NAME_PREFIXES and parts[1].strip(".").lower() not in _NAME_PARTICLES:
        parts.pop(0)
    first = parts[0] if parts else ""
    if _NOT_A_NAME.search(first):
        return ""
    first = re.sub(r"[^\w\-']", "", first, flags=re.UNICODE)
    if not first or any(ch.isdigit() for ch in first) or len(first) > 20 or first.lower() in _NOT_NAMES or first.lower() in _NOT_PERSONS:
        return ""
    return _cased(first, shouting=_shouting(whole.split()))


def confirmation(language: str, name: str, start, office_address: str, maps_url: str, commercial: bool) -> str:
    lang = _lang(language, CONFIRM)
    head, date_word, time_word, office, closing = CONFIRM[lang]
    first = first_name(name)
    lines = [head.format(name=first).replace(" .", ".").replace(", .", ".").replace(" ،", "")]
    if not first:
        lines[0] = lines[0].replace(", .", ".").replace(",.", ".").replace("  ", " ")
    lines += [
        f"{date_word}: {hours.day_label(start)}",
        f"{time_word}: {hours.time_label(start)}",
        office,
        office_address,
    ]
    if maps_url:
        lines.append(maps_url)
    who = SPECIALIST[lang]["commercial" if commercial else "other"]
    lines.append(closing.format(who=who))
    return _tidy("\n".join(lines))


def rescheduled(language: str, name: str, start, office_address: str, maps_url: str) -> str:
    lang = _lang(language, RESCHEDULE_HEAD)
    _, date_word, time_word, office, _ = CONFIRM[lang]
    lines = [
        RESCHEDULE_HEAD[lang].format(name=first_name(name)),
        f"{date_word}: {hours.day_label(start)}",
        f"{time_word}: {hours.time_label(start)}",
        office,
        office_address,
    ]
    if maps_url:
        lines.append(maps_url)
    return _tidy("\n".join(lines))


def arrival(language: str, at) -> str:
    return ARRIVAL[_lang(language, ARRIVAL)].format(time=hours.time_label(at))


def on_my_way(language: str) -> str:
    return ON_MY_WAY[_lang(language, ON_MY_WAY)]


def _tidy(text: str) -> str:
    # A missing first name leaves "Perfect, ." or "Done, ." behind.
    text = re.sub(r",\s*([.:۔])", r"\1", text)
    text = re.sub(r"\s+([.:۔])", r"\1", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
