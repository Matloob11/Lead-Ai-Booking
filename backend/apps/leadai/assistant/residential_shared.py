"""Thin stand-ins for the rent lane's ``assistant/residential.py``, by the spec's names (batch 2e, the sale lane's branch).

The rent lane (branch leadai-2e) owns residential.py: the residential facts and bands (spec §2.2), the full-name gate (§2.6),
the confirmations in six languages (§2.7), the handover lines (§2.11) and the one commission function (§2.4). The sale lane
calls them by these names; until the branches are merged each lives here, as small as the sale flow needs it. The merge
replaces every call of this module with residential's own function and deletes the module.

Kept to the spec's words: AR Properties' bot names nobody (Q30) and gives no number (Q38); a call is "our sales team".
"""

from __future__ import annotations

import copy
import re

from ..models import DEFAULT_RESIDENTIAL_FACTS
from . import filters, hours, rules

RENT = "rent"
SALE = "sale"
_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


# The residential facts (spec §2.2) ----------------------------------------------------------------------------------


def facts_of(raw) -> dict:
    """The residential facts, falling back to the defaults key by key (residential.facts_of)."""
    facts = copy.deepcopy(DEFAULT_RESIDENTIAL_FACTS)
    if not isinstance(raw, dict):
        return facts
    for section in ("rent", "sale", "charges"):
        given = raw.get(section)
        if not isinstance(given, dict):
            continue
        for key, value in given.items():
            if key in facts[section] and isinstance(value, type(facts[section][key])):
                facts[section][key] = value
    for key in ("clusters", "european_clusters"):
        if isinstance(raw.get(key), list) and raw[key]:
            facts[key] = [name for name in raw[key] if isinstance(name, str)]
    return facts


def sale_band(unit: str, clusters=(), facts=None) -> dict | None:
    """The sale band of a unit (residential.sale_band): a studio in Morocco Cluster has its own; None for no unit."""
    sale = facts_of(facts)["sale"]
    if unit == "studio":
        return sale.get("studio_morocco") if "Morocco" in tuple(clusters or ()) else sale.get("studio")
    if unit == "one_br":
        return sale.get("one_br")
    return None


# The full name (spec §2.6) ----------------------------------------------------------------------------------------

FULL_NAME_MAX = 80
_NAME_WORD = re.compile(r"^[^\W\d_][^\W\d_'\-.]*$", re.UNICODE)
# Words a reply to "May I have your full name?" holds that name nobody ("Yes please", "ok sure", "tomorrow 5").
_NOT_A_NAME = frozenset(
    """
    yes yeah yep no nope ok okay sure please pls thanks thank you fine done good great call me my name is it its this the
    today tomorrow now later morning evening pm am sir madam maam bro dear hi hello salam not interested why what who
    """.split()
)
FULL_NAME_LINE = {
    "en": "Great! May I have your full name for the booking?",
    "ar": "رائع! هل يمكنني معرفة اسمك الكامل للحجز؟",
    "ur_latin": "Behtareen! Booking ke liye kya main aap ka poora naam jaan sakta hoon?",
    "ur": "بہترین! بکنگ کے لیے کیا میں آپ کا پورا نام جان سکتا ہوں؟",
    "hi_latin": "Badhiya! Booking ke liye kya main aapka poora naam jaan sakta hoon?",
    "hi": "बढ़िया! बुकिंग के लिए क्या मैं आपका पूरा नाम जान सकता हूँ?",
}


def full_name_line(language: str) -> str:
    """res_full_name: the ask before a booking, for a viewing and a call alike."""
    return FULL_NAME_LINE[_lang(language)]


def _name_words(text) -> list[str]:
    words = [word.strip(".,") for word in " ".join(str(text or "").split()).split()]
    return [word for word in words if word]


def _full(text) -> str:
    """A full name: two to four words of letters, no digits, no markup, at most FULL_NAME_MAX characters; else ''."""
    name = filters.person_name(str(text or ""))
    words = _name_words(name)
    if not 2 <= len(words) <= 4 or len(name) > FULL_NAME_MAX:
        return ""
    if not all(_NAME_WORD.match(word) for word in words) or any(word.casefold() in _NOT_A_NAME for word in words):
        return ""
    return filters.cased(" ".join(words))


def full_name_known(facts: dict, lead: dict | None = None) -> str:
    """The customer's full name when the chat knows it: facts.full_name of two words or more, else the lead's NAME and
    LAST_NAME when both are a person's (lead_context keeps only those); '' otherwise."""
    name = _full((facts or {}).get("full_name"))
    if name:
        return name
    lead = lead or {}
    first, last = str(lead.get("name") or "").strip(), str(lead.get("last_name") or "").strip()
    if first and last and first.casefold() != last.casefold():
        return _full(f"{first} {last}")
    return ""


def name_from_reply(text: str, our_last: str) -> str:
    """Code's fallback for the model's full_name: a reply of two to four words of letters, with no digit and no question,
    right after our ask (res_full_name in any of its languages); '' otherwise."""
    if not our_last or not any(" ".join(our_last.split()).endswith(line) or line in our_last for line in FULL_NAME_LINE.values()):
        return ""
    words = " ".join(str(text or "").split())
    if not words or rules.asks_question(words) or any(ch.isdigit() for ch in words):
        return ""
    if rules.is_acknowledgement(words) or rules.is_refusal(words) or rules.is_acceptance(words):
        return ""
    words = re.sub(r"^(?:my\s+name\s+is|i\s+am|i'm|it'?s|this\s+is|name\s*:)\s+", "", words, flags=re.IGNORECASE)
    return _full(words)


def full_name_gate(answer: dict, *, track: str, when, facts: dict, lead: dict | None = None, said: str = "", our_last: str = "",
                   appointment=None, now=None, closed_dates=()) -> tuple:
    """The full name before a booking on the rent and sale tracks (spec §2.6), as (when, what):

    - a confirm or a move to a new time with the full name unknown: no booking; the time is held as a tentative at its
      place (``answer["held_for_name"]``; engine._apply marks it), and the reply asks the name: (None, "held");
    - no new time, a time held for the name open, and the name known now (the model's full_name, or ``name_from_reply``):
      the held time is booked, if still ahead: (its start, "released");
    - else (when, '').
    A name the customer gives is kept as facts.full_name; a booked visit's move needs no name again."""
    if track not in (RENT, SALE):
        return when, ""
    fresh = answer["facts"]
    name = full_name_known({**(facts or {}), **{key: value for key, value in fresh.items() if value not in (None, "", [])}}, lead)
    given = name_from_reply(said, our_last) if not name else ""
    if given:
        fresh["full_name"] = given
        name = given
    elif fresh.get("full_name") and _full(fresh.get("full_name")):
        fresh["full_name"] = _full(fresh["full_name"])
    proposal = answer["appointment"]
    confirmed = appointment is not None and appointment.status == "confirmed"
    if when is not None and proposal["action"] in ("confirm", "reschedule"):
        if name or confirmed:
            return when, ""
        answer["appointment"] = {**proposal, "action": "tentative"}
        answer["held_for_name"] = True
        return None, "held"
    held = (
        appointment is not None and appointment.status == "tentative" and appointment.starts_at is not None
        and (appointment.details or {}).get("held_for_name")
    )
    if not held or not name or hours.named_times(said) or hours.named_days(said, now):
        return when, ""
    local = appointment.starts_at.astimezone(hours.DUBAI)
    try:
        start = hours.check_slot(f"{local:%Y-%m-%d}", f"{local:%H:%M}", now=now, closed_dates=closed_dates)
    except hours.SlotError:
        return when, ""
    answer["appointment"] = {
        "action": "confirm", "place": appointment.place or "office", "date": f"{local:%Y-%m-%d}", "time": f"{local:%H:%M}",
        "customer_words": (appointment.customer_words or said or "")[:255] or None,
    }
    return start, "released"


# The confirmations (spec §2.7, §3.3.3) ---------------------------------------------------------------------------------

CALL_BOOKED = {
    "en": "Perfect{name}! Your 5-minute call with our sales team is booked for {day} at {time}. We'll call you on this number. Speak soon!",
    "ar": "ممتاز{name}! تم حجز مكالمتك مع فريق المبيعات لدينا ومدتها 5 دقائق يوم {day} الساعة {time}. سنتصل بك على هذا الرقم. نتحدث قريباً!",
    "ur_latin": "Perfect{name}! Hamari sales team ke saath aap ki 5 minute ki call {day} ko {time} par book ho gayi hai. Hum aap ko isi number par call karenge. Jald baat hogi!",
    "ur": "بہت خوب{name}! ہماری سیلز ٹیم کے ساتھ آپ کی 5 منٹ کی کال {day} کو {time} پر بک ہو گئی ہے۔ ہم آپ کو اسی نمبر پر کال کریں گے۔ جلد بات ہوگی!",
    "hi_latin": "Perfect{name}! Hamari sales team ke saath aapki 5 minute ki call {day} ko {time} par book ho gayi hai. Hum aapko isi number par call karenge. Jald baat karte hain!",
    "hi": "बहुत बढ़िया{name}! हमारी सेल्स टीम के साथ आपकी 5 मिनट की कॉल {day} को {time} पर बुक हो गई है। हम आपको इसी नंबर पर कॉल करेंगे। जल्द बात करते हैं!",
}
VISIT = {
    "en": ("Perfect{name}! Your meeting is confirmed ✅", ("Date", "Time", "Place"), "Our agent will meet you at the office. See you soon!"),
    "ar": ("ممتاز{name}! تم تأكيد موعدك ✅", ("التاريخ", "الوقت", "المكان"), "سيقابلك وكيلنا في المكتب. نراك قريباً!"),
    "ur_latin": ("Perfect{name}! Aap ki meeting confirm ho gayi hai ✅", ("Date", "Time", "Jagah"), "Hamare agent aap se office mein milenge. Jald mulaqat hogi!"),
    "ur": ("بہت خوب{name}! آپ کی میٹنگ کنفرم ہو گئی ہے ✅", ("تاریخ", "وقت", "جگہ"), "ہمارے ایجنٹ آپ سے آفس میں ملیں گے۔ جلد ملاقات ہوگی!"),
    "hi_latin": ("Perfect{name}! Aapki meeting confirm ho gayi hai ✅", ("Date", "Time", "Jagah"), "Hamare agent aapse office mein milenge. Jald milte hain!"),
    "hi": ("बहुत बढ़िया{name}! आपकी मीटिंग कन्फ़र्म हो गई है ✅", ("तारीख़", "समय", "जगह"), "हमारे एजेंट आपसे ऑफ़िस में मिलेंगे। जल्द मिलते हैं!"),
}


def _day(start) -> str:
    """'Mon 19 Oct' in Dubai time."""
    local = start.astimezone(hours.DUBAI)
    return f"{local:%a} {local.day} {local:%b}"


def confirmation(language: str, start, *, kind: str, full_name: str = "", unit: str = "", clusters=(), office_address: str = "",
                 maps_url: str = "") -> str:
    """The booking message (residential.confirmation): a call (res_call_booked: "Perfect, Ahmed Khan! Your 5-minute call
    with our sales team is booked for Mon 19 Oct at 4:00 PM. We'll call you on this number. Speak soon!") or an office
    meeting (date, time, our office and its Maps link, "Our agent will meet you at the office."). Names no agent (Q30),
    never a Meet link or an e-mail (T102), never a travel time."""
    lang = _lang(language)
    name = f", {full_name}" if full_name else ""
    if lang in ("ar", "ur", "hi") and full_name:
        name = f" {full_name}"
    if kind == "call":
        return CALL_BOOKED[lang].format(name=name, day=_day(start), time=hours.time_label(start))
    head, (date_word, time_word, place_word), closing = VISIT[lang]
    lines = [head.format(name=name), f"{date_word}: {_day(start)}", f"{time_word}: {hours.time_label(start)}"]
    if office_address:
        lines.append(f"{place_word}: {office_address}")
    if maps_url:
        lines.append(maps_url)
    lines.append(closing)
    return "\n".join(lines)


# The handover line (spec §2.11) ------------------------------------------------------------------------------------

HANDOVER_LINE = {
    "en": "Sure, no problem. I've passed your details to our {team} team, so you don't need to explain again. Our agent will reply to you here.",
    "ar": "بالتأكيد، لا مشكلة. أرسلت بياناتك إلى فريق {team} لدينا، فلن تحتاج إلى الشرح مرة أخرى. سيرد عليك وكيلنا هنا.",
    "ur_latin": "Zaroor, koi masla nahi. Main ne aap ki details hamari {team} team ko de di hain, taake aap ko dobara samjhana na pare. Hamare agent yahin aap ko jawab denge.",
    "ur": "ضرور، کوئی مسئلہ نہیں۔ میں نے آپ کی تفصیلات ہماری {team} ٹیم کو دے دی ہیں، تاکہ آپ کو دوبارہ سمجھانا نہ پڑے۔ ہمارے ایجنٹ یہیں آپ کو جواب دیں گے۔",
    "hi_latin": "Zaroor, koi dikkat nahi. Maine aapki details hamari {team} team ko de di hain, taaki aapko dobara samjhana na pade. Hamare agent yahin aapko jawab denge.",
    "hi": "ज़रूर, कोई दिक्कत नहीं। मैंने आपकी जानकारी हमारी {team} टीम को दे दी है, ताकि आपको दोबारा समझाना न पड़े। हमारे एजेंट यहीं आपको जवाब देंगे।",
}
_TEAM = {
    SALE: {"en": "sales", "ar": "المبيعات", "ur_latin": "sales", "ur": "سیلز", "hi_latin": "sales", "hi": "सेल्स"},
    RENT: {"en": "rental", "ar": "التأجير", "ur_latin": "rental", "ur": "رینٹل", "hi_latin": "rental", "hi": "रेंटल"},
}


def handover_line(language: str, track: str) -> str:
    """res_handover: names nobody (Q30), gives no number (Q38); our team replies in this chat."""
    lang = _lang(language)
    return HANDOVER_LINE[lang].format(team=_TEAM.get(track, _TEAM[RENT])[lang])


# Commission (spec §2.4) --------------------------------------------------------------------------------------------

_COMMISSION = re.compile(
    r"\bcomm?iss?ions?\b|\bagency\s+fees?\b|\bagent'?s?\s+fees?\b|\bbrokerage\b|\bbroker'?s?\s+fees?\b|عمولة|العمولة|کمیشن|कमीशन",
    re.IGNORECASE,
)


def asked_commission(texts) -> bool:
    """Their words ask about (or speak of) the commission."""
    return any(_COMMISSION.search(str(text or "")) for text in texts or ())


def commission_answer(track: str, unit: str, earlier, new_texts, *, answer: dict) -> tuple[str, bool]:
    """Only code's commission line goes out (residential.commission_answer; here the sale track's rule, Q33 open): every
    sentence of the model's that names the commission is cut, and when they asked about it (or the model spoke of it) the
    track's line goes before the reply's first question. (reply, changed); other tracks unchanged."""
    reply = str(answer.get("reply") or "")
    if track != SALE:
        return reply, False
    from . import sales

    sentences = filters.split_sentences(reply)
    kept = [sentence for sentence in sentences if not _COMMISSION.search(sentence) or sentence == sales.commission_line(answer.get("language") or "en")]
    cut = len(kept) != len(sentences)
    if not cut and not asked_commission(new_texts):
        return reply, False
    line = sales.commission_line(answer.get("language") or "en")
    if line not in kept:
        for index, sentence in enumerate(kept):
            if rules.asks_question(sentence):
                kept.insert(index, line)
                break
        else:
            kept.append(line)
    return " ".join(kept).strip(), True
