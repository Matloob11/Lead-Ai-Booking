"""The script the customer types in, and replies that are not in it (board T19; every playbook).

The prompt says: reply in the language and script of the customer's latest
typed message. An Urdu-script customer still got English or Roman Urdu in
three of four eval runs, so code checks it: ``customer_script`` reads the
customer's typed messages, newest first, skipping what carries no script ("ok",
"yes", a number, "5 pm", an emoji) and what is not typed (taps, voice notes,
media); ``has_script`` says whether a reply is written in that script. When it
is not, engine.ask_model asks the model once more (prompt.SCRIPT_CORRECTION),
and keeps its first answer if the second is no better. ``follow`` makes the
language of a line code writes (a booking, an opt-out, a holding line) follow
the customer's script too.

The phrases people of every language type in Arabic script, "ان شاء الله",
"السلام عليكم", "الحمد لله", "جزاك الله خير" and the like (``FIXED``), say nothing
about the script the customer writes in: an English or Roman Urdu customer who
answers "ان شاء الله" is still answered in English letters. They are read past,
in any spelling (Arabic or Urdu letters, with or without spaces or marks), and
what is left of the message decides.

English letters are a script too (``LATIN``: English, or Urdu or Hindi written in
English letters): a reply in Arabic script or Devanagari to such a customer is
asked for once more in English letters (prompt.LATIN_CORRECTION; eval
lang-inshallah-english, where the model answered "ان شاء الله" in Arabic twice),
and code's own lines then go in the English-letter form of the language (Urdu in
Roman Urdu, Hindi in Roman Hindi, Arabic in English). The names of what is on
offer, typed in English letters in any chat ("Type 2", "DED", "Trakhees", "PDF",
"International City": ``LATIN_FIXED``), are read past like the FIXED phrases, and a
word or two of English letters ("Location?") never decides: an Arabic chat whose
customer types "أريد Type 2" or "Type 2" stays Arabic, the message before deciding.
``customer_script`` gives '' only when nothing they typed says anything (taps,
voice notes, "ok"), and then nothing is checked. The customer's own name, written
as their profile has it ("Hi محمد" in an English reply), says nothing of the
reply's script either (``has_script``'s ``name``).
"""

from __future__ import annotations

import re
import unicodedata

from . import rules

ARABIC = "arabic"
URDU = "urdu"
DEVANAGARI = "devanagari"
LATIN = "latin"  # English letters: English, Roman Urdu, Roman Hindi
# Fewer letters than this say nothing about a script ("ok", "pm", "جی").
MIN_LETTERS = 4
# Letters Urdu writes and Arabic does not (as rules.guess_language reads them).
_URDU_LETTERS = re.compile(r"[ٹڈڑںھہۃےۓیکگچپ]")
NAMES = {
    ARABIC: "Arabic script (Arabic)",
    URDU: "Urdu script (Urdu, not Roman Urdu)",
    DEVANAGARI: "Devanagari script (Hindi)",
}


FIXED = (
    "السلام عليكم ورحمة الله وبركاته", "السلام عليكم ورحمة الله", "وعليكم السلام ورحمة الله وبركاته", "وعليكم السلام",
    "السلام عليكم", "اسلام عليكم", "سلام عليكم", "السلام علیکم", "اسلام علیکم", "وعلیکم السلام",
    "إن شاء الله", "ان شاء الله", "انشاء الله", "انشالله", "ان شاء اللہ", "انشاءاللہ", "انشاء اللہ",
    "ما شاء الله", "ماشاء الله", "ماشالله", "مشاء الله", "ما شاء اللہ", "ماشاءاللہ",
    "الحمد لله", "الحمدلله", "الحمد للہ", "الحمدللہ",
    "جزاك الله خيرا", "جزاك الله خير", "جزاک اللہ خیر", "جزاک اللہ", "جزاك الله",
    "بارك الله فيكم", "بارك الله فيك", "بارک اللہ", "بسم الله", "بسم اللہ", "سبحان الله", "سبحان اللہ",
    "الله أكبر", "الله اكبر", "اللہ اکبر", "أستغفر الله", "استغفر الله", "استغفر اللہ", "يا الله", "یا اللہ",
    "شكرا جزيلا", "شكراً جزيلاً", "شكرا", "شكراً", "شکریہ", "جمعة مباركة", "جمعة مبارك", "جمعه مبارک",
    "عيد مبارك", "عید مبارک", "رمضان كريم", "رمضان مبارك", "رمضان مبارک", "الله", "اللہ",
)
# One spelling for each letter the phrases are typed with: Arabic and Urdu letters alike, no
# hamza, no short vowels or tatweel (U+0640), so "انشاءاللہ" and "إن شاء الله" read the same.
_FOLD = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ی": "ي", "ې": "ي", "ئ": "ي", "ة": "ه", "ہ": "ه",
        "ۃ": "ه", "ھ": "ه", "ک": "ك", "ؤ": "و", "ء": "", "ـ": "",
    }
)


def _fold(text: str) -> str:
    return "".join(ch for ch in str(text or "").translate(_FOLD) if ch.isalpha())


_FIXED_FOLDED = tuple(sorted({_fold(phrase) for phrase in FIXED if _fold(phrase)}, key=len, reverse=True))


def _arabic_left(text: str) -> str:
    """The message's Arabic-script letters, as typed, without the FIXED phrases among them."""
    letters = [ch for ch in str(text or "") if ch.isalpha() and unicodedata.name(ch, "").startswith("ARABIC")]
    folded, index = [], []
    for position, ch in enumerate(letters):
        one = ch.translate(_FOLD)
        if one:
            folded.append(one)
            index.append(position)
    flat = "".join(folded)
    keep = [True] * len(flat)
    for phrase in _FIXED_FOLDED:
        start = flat.find(phrase)
        while start != -1:
            if all(keep[start : start + len(phrase)]):
                keep[start : start + len(phrase)] = [False] * len(phrase)
            start = flat.find(phrase, start + 1)
    return "".join(letters[index[k]] for k in range(len(flat)) if keep[k])


def _letters(text: str, fixed: bool = False) -> tuple[int, int, int]:
    """(Arabic-script, Devanagari, Latin) letter counts; the FIXED phrases' letters do not count
    unless ``fixed`` (a reply of ours: any letter of the script is the script)."""
    arabic = devanagari = latin = 0
    for ch in str(text or ""):
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("ARABIC"):
            arabic += 1
        elif name.startswith("DEVANAGARI"):
            devanagari += 1
        elif name.startswith("LATIN"):
            latin += 1
    return (arabic if fixed else len(_arabic_left(text))), devanagari, latin


def script_of(text: str) -> str:
    """ARABIC, URDU or DEVANAGARI when most of the message's letters are in that script,
    '' for English letters or too few letters to tell (the FIXED phrases read past)."""
    arabic, devanagari, latin = _letters(text)
    if arabic + devanagari + latin < MIN_LETTERS:
        return ""
    if arabic > devanagari and arabic > latin:
        return URDU if _URDU_LETTERS.search(_arabic_left(text)) else ARABIC
    if devanagari > arabic and devanagari > latin:
        return DEVANAGARI
    return ""


def _says_nothing(text: str) -> bool:
    """A typed message that keeps the language so far: ok, yes, a number, a time, emoji, or only
    a FIXED phrase ("ان شاء الله")."""
    words = str(text or "").strip()
    if not words:
        return True
    if rules.is_acknowledgement(words) or rules.is_acceptance(words) or rules.is_refusal(words):
        return True
    return sum(_letters(words)) < MIN_LETTERS


# What a chat in any script types in English letters: the shops on offer and the place (read past
# like FIXED, so "أريد Type 2" is an Arabic message and "Type 2" alone none).
LATIN_FIXED = re.compile(
    r"\btype[\s-]*(?:[123]|one|two|three|i{1,3})\b|\b(?:ded|trakhees|pdf|aed|dhs?|sq\.?\s*ft|sqft|sq|ok|okay"
    r"|international\s+city|dragon\s+mart|dubai|sharjah|ajman|uae|whatsapp|emirates\s+id)\b",
    re.IGNORECASE,
)
# English letters decide only with this many words of them, LATIN_FIXED read past ("Location?" is one).
LATIN_WORDS = 2
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def _script_of_message(text: str) -> str:
    """The script one typed message is written in: script_of's, else LATIN when English letters
    clearly win (LATIN_WORDS of them, the names on offer read past, more letters than any other
    script's), else '': it says nothing of the customer's script ("Type 2", "Location?", "نعم DED")."""
    rest = LATIN_FIXED.sub(" ", str(text or ""))
    found = script_of(rest)
    if found:
        return found
    arabic, devanagari, latin = _letters(rest)
    if latin >= MIN_LETTERS and latin > arabic + devanagari and len(_LATIN_WORD.findall(rest)) >= LATIN_WORDS:
        return LATIN
    return ""


def customer_script(typed: list) -> str:
    """The script of the customer's latest typed message that says something of it: ARABIC, URDU,
    DEVANAGARI or LATIN (English letters; the FIXED phrases and LATIN_FIXED read past, and a word
    or two of English letters, "Location?", decides nothing: the message before it does); '' when
    nothing they typed says anything. ``typed``: their typed texts, oldest first."""
    for text in reversed(list(typed or [])):
        if _says_nothing(text):
            continue
        found = _script_of_message(text)
        if found:
            return found
    return ""


def _without_name(text: str, name: str) -> str:
    """The text without the words of the customer's own name (as their profile writes it)."""
    words = {_fold(word).casefold() for word in re.split(r"[\s,.;:!?()]+", str(name or "")) if len(_fold(word)) >= 2}
    if not words:
        return str(text or "")
    return re.sub(r"\w+", lambda match: " " if _fold(match.group(0)).casefold() in words else match.group(0), str(text or ""))


def has_script(reply: str, script: str, name: str = "") -> bool:
    """The reply is written in the customer's script (any letters of it; Urdu needs Urdu's own);
    in English letters (LATIN) when it has no Arabic-script or Devanagari letter at all. The
    customer's own ``name`` is read past ("Hi محمد, ..." is English letters)."""
    reply = _without_name(reply, name)
    arabic, devanagari, _ = _letters(reply, fixed=True)
    if script == URDU:
        return arabic > 0 and bool(_URDU_LETTERS.search(str(reply or "")))
    if script == ARABIC:
        return arabic > 0
    if script == DEVANAGARI:
        return devanagari > 0
    if script == LATIN:
        return arabic == 0 and devanagari == 0
    return True


# The English-letter form of a language written in another script (LATIN): Arabic has none here.
_IN_LATIN = {"ur": "ur_latin", "hi": "hi_latin", "ar": "en"}


def follow(language: str, script: str) -> str:
    """The language of a line code writes, made to follow the customer's script: Arabic or
    Urdu letters get ar or ur, Devanagari hi, English letters the English-letter form (ur is
    ur_latin, hi hi_latin, ar en; en, ur_latin and hi_latin stay as they are); nothing typed
    keeps the language as it is."""
    if script == URDU and language != "ur":
        return "ur"
    if script == ARABIC and language not in ("ar", "ur"):
        return "ar"
    if script == DEVANAGARI and language != "hi":
        return "hi"
    if script == LATIN:
        return _IN_LATIN.get(language, language)
    return language


def typed_texts(lines) -> list[str]:
    """The customer's typed messages among transcript-style texts: taps, voice notes and
    media ("[tapped: ...]", "[voice note] ...", "[photo ...]") are not typed."""
    return [str(text) for text in lines or [] if str(text or "").strip() and not str(text).lstrip().startswith("[")]
