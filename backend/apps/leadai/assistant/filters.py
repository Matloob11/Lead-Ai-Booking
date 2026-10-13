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


def _invented_amount(sentence: str, known: set[int]) -> bool:
    """A price-like number the customer, the campaign or a colleague never wrote."""
    priced = bool(_PRICE_WORDS.search(sentence))
    for value, scaled in numbers_in(sentence):
        if (scaled or (priced and value >= 1000)) and value not in known:
            return True
    return False


def mentions_price(text: str) -> bool:
    """The text is about a price, rent, fee or budget (in any of the languages here)."""
    return bool(_PRICE_WORDS.search(text or ""))


def _strip_phones(text: str) -> str:
    return _PHONE.sub(lambda m: "" if len(_digits(m.group(0))) >= PHONE_DIGITS else m.group(0), text)


def clean_reply(reply: str, context_text: str) -> tuple[str, list[str]]:
    """The reply made safe to send, and notes on what was removed (for the turn log).

    ``context_text`` is everything the customer, the campaign and our
    colleagues wrote (never the assistant's own replies): an amount found
    there may be repeated, in any form ("40k" covers "AED 40,000"); any other
    price-like number takes its sentence with it.
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
        if _invented_amount(sentence, known):
            notes.append("amount")
            continue
        if _HUMAN_CLAIM.search(sentence):
            notes.append("human_claim")
            continue
        kept.append(sentence)
    # The owner's style: one question per reply. A second one is nearly always
    # "which day and time?" after an invitation, and waits for the answer.
    single, asked = [], False
    for sentence in kept:
        if any(mark in sentence for mark in QUESTION_MARKS):
            if asked:
                notes.append("second_question")
                continue
            asked = True
        single.append(sentence)
    text = " ".join(single)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text[:REPLY_MAX], notes


QUESTION_MARKS = ("?", "؟", "？")
_INVITATION = re.compile(
    r"\b(visit|meet|meeting|appointment|come (to|by|over)|our office|daftar|office aa|mulaqat)\b|مكتب|زيارة|موعد|دفتر|ملاقات",
    re.IGNORECASE,
)


def drop_invitations(text: str) -> tuple[str, bool]:
    """The reply without its sentences that invite to the office (after two refusals)."""
    kept = [s.strip() for s in _SENTENCE.split(text or "") if s.strip() and not _INVITATION.search(s)]
    out = " ".join(kept).strip()
    return out, out != (text or "").strip()


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
# What a CRM card or a WhatsApp profile holds when it holds no name.
_NOT_NAMES = {
    "lead", "client", "customer", "owner", "tenant", "buyer", "landlord", "test", "unknown", "new",
    "shop", "office", "flat", "na", "none", "null", "user", "contact", "whatsapp",
}


def first_name(name: str) -> str:
    """A safe first name: letters only, at most 20 characters, else ''.

    "Mr. Ahmed Khan" gives "Ahmed" and "AHMED KHAN" gives "Ahmed". A word
    carrying markup or digits is not a name ("[URL=x]Click", a phone number),
    so it is dropped rather than cleaned into something that reads like one;
    so is a placeholder such as "Lead" or "Customer". Emoji and dots are only
    trimmed off.
    """
    parts = (name or "").split()
    while parts and parts[0].strip(".").lower() in _HONORIFICS:
        parts.pop(0)
    first = parts[0] if parts else ""
    if _NOT_A_NAME.search(first):
        return ""
    first = re.sub(r"[^\w\-']", "", first, flags=re.UNICODE)
    if not first or any(ch.isdigit() for ch in first) or len(first) > 20 or first.lower() in _NOT_NAMES:
        return ""
    if len(first) > 1 and (first.isupper() or first.islower()):
        first = first.capitalize()
    return first


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
