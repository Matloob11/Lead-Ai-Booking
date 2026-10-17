"""The studio and one-bedroom photo sets of the rent track (batch 2e slice E, spec §4; board T96, Q36, D11).

The library is built from A7's own portal listings: ``backend/Types shops/Residential sets/`` (gitignored) holds one
folder per set, and each folder's ``set.json`` says the unit, the label, whether it is the unit's default, the listing
refs whose leads get it, and its photos in sending order. A listing often has no photos of its own and A7 uses a
related unit's, which inside are almost the same; only the building outside can differ, and the visit clears that. So
every set is the same type of unit, never the exact one (Q36): label "standard", no photo of a building outside, a
studio customer gets studio photos and a one-bedroom customer one-bedroom photos, and no caption promises furniture
(7 of the 9 residential listings say unfurnished while their photos show furniture).

- ``import_directory`` (``leadai_media_import``) reads each ``set.json``, never the folder's name, and refuses a label
  other than standard, a second default for a unit, one listing ref in two sets of a unit, a ref not shaped
  a7group-NNNN, more than PHOTOS_PER_SET photos or a second video, and any file shop_media.check_file refuses. A set is
  all or nothing, and running it twice adds nothing twice: a set already there is brought to what its set.json says.
- ``pick`` (``choose`` on plain data, for the eval): only sets of the customer's unit; the set whose for_listing_refs
  holds the lead's listing ref (the lead context's, UF_CRM_1760707563281: the photos they saw on the portal), else the
  unit's default. Never another unit's. An exact or matching set goes stale MEDIA_FRESH after verified_at; a standard
  set never claims to be the unit, so it never does. The cluster plays no part. With the unit not known yet, nothing.
- ``settle`` (pure, engine and eval alike): on the rent track only, a request for photos or a video (their words, a
  "Send pictures" tap, or one asked earlier that no photos answered yet), or a unit and a cluster confirmed by a direct
  customer whose unit's set never went to the chat, makes the turn's media step (``answer["unit_media"]``). The
  model's statements go first, then the photos with the caption on the first, then its own question, or else "Would
  you like to visit and see the exact available option?" with two free slots. With no set of their unit imported, a
  request gets "I don't have approved pictures for this one yet, but we can show you in person." and two free slots
  (res_no_media), and a confirmed unit nothing. Never to a broker, never over a line code writes, a booking, a time to
  refuse, a handover or an opt-out, and the same unit's set not twice in RESEND_AFTER.
- ``deliver`` (the engine's) sends the words now and queues ``tasks.send_unit_media`` (``send_set``: the photos, then
  the question), which logs the set on the lead's timeline with its label.

Every customer-facing line is in six languages; agents read English.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import time
import unicodedata

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import shop_media
from .assistant import filters, hours, rules, shop_flow, tracks
from .models import LeadAiShopMedia, LeadAiUnitMediaSet

logger = logging.getLogger(__name__)

STUDIO = tracks.STUDIO
ONE_BR = tracks.ONE_BR
UNITS = (STUDIO, ONE_BR)
Label = LeadAiUnitMediaSet.Label
STANDARD = Label.STANDARD.value
# The labels a set may be imported with (Q36: same type, never exact), and the labels the bot sends (its captions say
# what a standard set is; an exact or matching set needs an inventory feed first, T101).
IMPORTED_LABELS = (STANDARD,)
SENT_LABELS = (Label.EXACT.value, Label.MATCHING.value, STANDARD)
PHOTOS_PER_SET = 5
VIDEOS_PER_SET = 1
SET_FILE = "set.json"
SET_FILE_MAX = 64 * 1024
NAME_MAX = 120
CLUSTER_MAX = 40
# An exact or matching set's photos go stale this long after they were verified (never a standard one).
MEDIA_FRESH = dt.timedelta(days=90)
# The same unit's set goes to a chat once in this long, asked or not.
RESEND_AFTER = dt.timedelta(hours=24)
# How far back an unanswered request for photos is looked for (lines of the chat before this burst).
PENDING_LINES = 6
# Between two photos of a set, so they arrive in order.
SEND_PAUSE = shop_media.SEND_PAUSE
_REF = re.compile(r"^a7group-\d{1,6}$")
_CLUSTER = re.compile(r"^[A-Za-z][A-Za-z ]{0,38}$")

# The guards, one line each (their tests switch each off to prove it is what holds):
# - only sets of the customer's unit, whatever set their lead's listing ref names (Q36: studio to studio, 1BR to 1BR);
SAME_UNIT_ONLY = True
# - never to a broker or an agent (the brief, Part 5 step 1: a broker is handed over, and gets no media);
NEVER_TO_BROKERS = True
# - the same unit's set once in RESEND_AFTER, asked or not.
ONCE_A_DAY = True

# What the step answers (answer[STEP]["trigger"]).
STEP = "unit_media"
ASKED = "asked"
CONFIRMED = "confirmed"
# The answer keys of a line code writes instead of the model's words: the media step never goes over them (the 2e merge
# added the rent flow's res_line and the sale track's sale step, which also set "converted").
CODE_LINE_KEYS = (
    "converted", "not_a_shop", "price", "open_lead", "shop_step", "slot_taken", "broker", "quiet", "call", "res_line", "sale",
)
# A template's "Send Pictures" button (the brief's T1 and T2), and the same asked in words.
SEND_TAPS = frozenset(rules.normalize_text(label) for label in ("send pictures", "send picture", "send photos", "send pics", "send me pictures"))


# Words -------------------------------------------------------------------------------------------------------------------

_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")

# The first photo's caption (Q36): the same type of unit, never "this unit" or "the exact unit" (only the visit shows
# that), and no word of furniture.
CAPTIONS = {
    STUDIO: {
        "en": "These are photos of the same type of studio. Inside they are almost the same; the building can differ, and our "
        "agent will show you the exact unit at the viewing.",
        "ar": "هذه صور لاستوديو من النوع نفسه. من الداخل تكون الاستوديوهات متشابهة تقريباً، وقد يختلف المبنى، وسيُريك وكيلنا "
        "الوحدة الفعلية عند المعاينة.",
        "ur_latin": "Yeh isi type ke studio ki tasveerein hain. Andar se yeh taqreeban ek jaise hote hain; building mukhtalif ho "
        "sakti hai, aur hamare agent viewing par aap ko asal unit dikhayenge.",
        "ur": "یہ اسی قسم کے اسٹوڈیو کی تصویریں ہیں۔ اندر سے یہ تقریباً ایک جیسے ہوتے ہیں؛ بلڈنگ مختلف ہو سکتی ہے، اور ہمارے "
        "ایجنٹ ویونگ پر آپ کو اصل یونٹ دکھائیں گے۔",
        "hi_latin": "Ye isi type ke studio ki photos hain. Andar se ye lagbhag ek jaise hote hain; building alag ho sakti hai, "
        "aur hamare agent viewing par aapko asli unit dikhayenge.",
        "hi": "ये इसी तरह के स्टूडियो की तस्वीरें हैं। अंदर से ये लगभग एक जैसे होते हैं; बिल्डिंग अलग हो सकती है, और हमारे एजेंट "
        "व्यूइंग पर आपको असली यूनिट दिखाएँगे।",
    },
    ONE_BR: {
        "en": "These are photos of the same type of one-bedroom apartment. Inside they are almost the same; the building can "
        "differ, and our agent will show you the exact unit at the viewing.",
        "ar": "هذه صور لشقة بغرفة نوم واحدة من النوع نفسه. من الداخل تكون هذه الشقق متشابهة تقريباً، وقد يختلف المبنى، وسيُريك "
        "وكيلنا الوحدة الفعلية عند المعاينة.",
        "ur_latin": "Yeh isi type ke one-bedroom apartment ki tasveerein hain. Andar se yeh taqreeban ek jaise hote hain; "
        "building mukhtalif ho sakti hai, aur hamare agent viewing par aap ko asal unit dikhayenge.",
        "ur": "یہ اسی قسم کے ون بیڈروم اپارٹمنٹ کی تصویریں ہیں۔ اندر سے یہ تقریباً ایک جیسے ہوتے ہیں؛ بلڈنگ مختلف ہو سکتی ہے، "
        "اور ہمارے ایجنٹ ویونگ پر آپ کو اصل یونٹ دکھائیں گے۔",
        "hi_latin": "Ye isi type ke one-bedroom apartment ki photos hain. Andar se ye lagbhag ek jaise hote hain; building alag "
        "ho sakti hai, aur hamare agent viewing par aapko asli unit dikhayenge.",
        "hi": "ये इसी तरह के वन-बेडरूम अपार्टमेंट की तस्वीरें हैं। अंदर से ये लगभग एक जैसे होते हैं; बिल्डिंग अलग हो सकती है, और "
        "हमारे एजेंट व्यूइंग पर आपको असली यूनिट दिखाएँगे।",
    },
}
# After the photos, the one question (the brief, Part 6 rule 7), with code's two free slots when there are any.
VISIT_QUESTION = {
    "en": "Would you like to visit and see the exact available option?",
    "ar": "هل تودّ زيارتنا لمشاهدة الخيار المتاح فعلياً؟",
    "ur_latin": "Kya aap visit kar ke asal dastiyab option dekhna chahenge?",
    "ur": "کیا آپ تشریف لا کر اصل دستیاب آپشن دیکھنا چاہیں گے؟",
    "hi_latin": "Kya aap visit karke asli available option dekhna chahenge?",
    "hi": "क्या आप आकर असली उपलब्ध विकल्प देखना चाहेंगे?",
}
# res_no_media (spec Appendix C): asked for photos, and no set of their unit is imported (the brief, Part 6 rule 6).
NO_MEDIA = {
    "en": "I don't have approved pictures for this one yet, but we can show you in person.",
    "ar": "ليست لديّ صور معتمدة لهذه الوحدة بعد، لكن يمكننا أن نُريك إياها شخصياً.",
    "ur_latin": "Is ki approved tasveerein abhi mere paas nahi hain, lekin hum aap ko khud dikha sakte hain.",
    "ur": "اس کی منظور شدہ تصویریں ابھی میرے پاس نہیں ہیں، لیکن ہم آپ کو خود دکھا سکتے ہیں۔",
    "hi_latin": "Iski approved photos abhi mere paas nahi hain, lekin hum aapko khud dikha sakte hain.",
    "hi": "इसकी अप्रूव्ड तस्वीरें अभी मेरे पास नहीं हैं, लेकिन हम आपको ख़ुद दिखा सकते हैं।",
}
# For agents (the timeline, the panel, the eval's report): what a label says.
LABEL_WORDS = {
    Label.EXACT.value: "the exact available unit",
    Label.MATCHING.value: "a matching unit, same building and layout",
    STANDARD: "the same type of unit, never the exact one (Q36)",
    Label.REFERENCE.value: "reference only",
}
UNIT_WORDS = {STUDIO: "studio", ONE_BR: "one-bedroom apartment"}


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


def caption(unit: str, language: str) -> str:
    """The first photo's caption, in the customer's language (Q36)."""
    table = CAPTIONS.get(unit) or CAPTIONS[STUDIO]
    return table[_lang(language)]


def follow_up(language: str, *, photos_sent: bool, questions: str = "", invite: bool = False, slots=(), now=None, ours: str = "") -> str:
    """What goes after the photos (or instead of them): the model's own question when it asked one; else, when the chat
    may be invited, "Would you like to visit and see the exact available option?" and code's two free slots (in words
    our side did not just use: shop_flow.slots_text). With no photos sent: "I don't have approved pictures for this one
    yet, but we can show you in person." first, and the slots alone after it."""
    lang = _lang(language)
    questions = " ".join(str(questions or "").split())
    offer = shop_flow.slots_text(lang, list(slots), now, ours) if invite and slots else ""
    if photos_sent:
        if questions:
            return questions
        if not invite:
            return ""
        return f"{VISIT_QUESTION[lang]} {offer}".strip()
    head = NO_MEDIA[lang]
    tail = questions or offer
    return f"{head} {tail}".strip()


# Reading the customer --------------------------------------------------------------------------------------------------

_MEDIA_NOUN = re.compile(
    r"\b(?:photos?|pictures?|pics?|pix|images?|videos?|clips?)\b|\btasveer\w*|\btasweer\w*|\bfoto\w*"
    r"|صور|صورة|فيديو|فديو|تصویر|تصاویر|ویڈیو|فوٹو|तस्वीर|फ़ोटो|फोटो|वीडियो",
    re.IGNORECASE,
)
# "No need to send photos", "don't send pictures", "photos nahi chahiye": no request.
_NO_THANKS = re.compile(
    r"\bno\s+need\b|\bnot\s+(?:needed|necessary|required)\b|\b(?:do\s*n'?t|dont|do\s+not|no)\s+(?:send|share)\b|\bwithout\s+(?:photos?|pictures?)\b"
    r"|\b(?:nahi|nahin|nhi)\s+(?:chahiye|chaiye|bhej\w*)\b|\bmat\s+bhej\w*|\bzaroorat\s+nahi"
    r"|لا\s+داعي|لا\s+حاجة|لا\s+ترسل|ما\s+(?:أبي|ابي|ابغى|أبغى)|ضرورت\s+نہیں|مت\s+بھیج|नहीं\s+चाहिए|मत\s+भेज|ज़रूरत\s+नहीं",
    re.IGNORECASE,
)
# "Thanks for the photos", "got the pictures", "nice pics": what we sent, answered; a request only with "more" or "again".
_GOT_THEM = re.compile(
    r"\b(?:thanks?|thank\s+you|thx|got|received|saw|seen|nice|good|great|beautiful|liked?|love)\b[^.?!]{0,20}"
    r"\b(?:photos?|pictures?|pics?|images?|videos?)\b|شكرا[^.?!؟]{0,20}(?:صور|الصور)|شکریہ[^.?!؟]{0,20}تصاویر",
    re.IGNORECASE,
)
_MORE = re.compile(r"\b(?:more|another|other|again|mazeed|dobara)\b|المزيد|أكثر|مزید|दोबारा", re.IGNORECASE)
# Photos of a shop ("send photos of the shop") are no studio's or one-bedroom's: never this step's (the shops flow has its own).
_SHOP_WORD = re.compile(r"\bshops?\b|\bdukaa?n\w*|\bshowrooms?\b|محل|محلات|دكان|دکان|शॉप|दुकान", re.IGNORECASE)
_HOME_WORD = re.compile(
    r"\b(?:studios?|flats?|apartments?|rooms?|bed\s*rooms?|bedrooms?|1\s*br|1\s*bhk|bhk|unit|home)\b"
    r"|استوديو|الاستوديو|شقة|غرفة|اسٹوڈیو|فلیٹ|اپارٹمنٹ|स्टूडियो|फ्लैट|अपार्टमेंट",
    re.IGNORECASE,
)
_WORDS = re.compile(r"\w+", re.UNICODE)


def asks_photos(text) -> bool:
    """Their words ask for photos or a video of the place: "Can you send photos?", "video bhej do", "pics please", a
    "Send Pictures" tap; never "no need to send photos", nor a photo of their own ("I will send my licence photo")."""
    raw = unicodedata.normalize("NFKC", str(text or "")).replace("’", "'")
    if not raw.strip():
        return False
    if rules.normalize_text(raw) in SEND_TAPS:
        return True
    if not _MEDIA_NOUN.search(raw) or _NO_THANKS.search(raw):
        return False
    if _GOT_THEM.search(raw) and not _MORE.search(raw):
        return False
    if _SHOP_WORD.search(raw) and not _HOME_WORD.search(raw):
        return False
    if shop_flow.asks_media(raw):
        return True
    # A short message that is mostly the noun ("pics please", "photos?", "تصاویر"): a request too.
    return len(_WORDS.findall(raw)) <= 4 and not re.search(r"\b(?:my|our|mine)\b", raw, re.IGNORECASE)


def asked_now(words) -> bool:
    return any(asks_photos(text) for text in words or ())


_PHOTO_SENT = "[sent a photo]"
_VIDEO_SENT = "[sent a video]"


def asked_before(earlier) -> bool:
    """An earlier message of theirs asked for photos, and no photo of ours followed it (a line code wrote went instead):
    ``earlier`` is the chat before this burst as (author, words), oldest first (engine: transcript.outbound_text writes
    our photos as "[sent a photo] ..."). Only the last PENDING_LINES lines."""
    for author, text in list(earlier or ())[-PENDING_LINES:][::-1]:
        words = str(text or "")
        if author == "assistant" and (words.startswith((_PHOTO_SENT, _VIDEO_SENT)) or any(line in words for line in NO_MEDIA.values())):
            return False  # answered: our photos, or our "no approved pictures yet"
        if author == "customer" and asks_photos(words):
            return True
    return False


def _resolve(value):
    return value() if callable(value) else value


def trigger(words=(), *, unit: str, clusters=(), for_client=None, sent=None, earlier=(), now=None) -> str:
    """ASKED, CONFIRMED or '' (the module note). ``sent``: {unit: when its set last went to this chat}; ``sent`` and
    ``clusters`` may be callables, asked only when the answer depends on them."""
    if unit not in UNITS or (NEVER_TO_BROKERS and for_client is True):
        return ""
    asked = asked_now(words) or asked_before(earlier)
    if not asked and for_client is not False:
        return ""
    last = (_resolve(sent) or {}).get(unit)
    if asked:
        recently = ONCE_A_DAY and last is not None and now is not None and now - last < RESEND_AFTER
        return "" if recently else ASKED
    if last is None and any(str(name or "").strip() for name in _resolve(clusters) or ()):
        return CONFIRMED
    return ""


# Choosing the set -------------------------------------------------------------------------------------------------------


def _get(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def ref_of(value) -> str:
    """A listing ref as the sets hold it ("a7group-1726"), else ''."""
    text = str(value or "").strip().lower()
    return text if _REF.match(text) else ""


def refs_of(item) -> list[str]:
    refs = _get(item, "for_listing_refs") or []
    return [ref for ref in (ref_of(value) for value in refs if isinstance(value, str)) if ref] if isinstance(refs, list) else []


def photo_count(item) -> int:
    count = _get(item, "photo_count")
    if count is None:
        count = _get(item, "photos_count")
    if count is None and isinstance(item, dict):
        photos = item.get("photos")
        count = len(photos) if isinstance(photos, (list, tuple)) else photos
    try:
        return max(int(count or 0), 0)
    except (TypeError, ValueError):
        return 0


def usable(item, now=None) -> bool:
    """The set may go out: a label the bot sends, a photo to send, and an exact or matching set verified within
    MEDIA_FRESH (an exact unit known to be gone never). A standard set never goes stale (Q36)."""
    label = _get(item, "label") or STANDARD
    if label not in SENT_LABELS or photo_count(item) <= 0:
        return False
    if label in (Label.EXACT.value, Label.MATCHING.value):
        verified = _get(item, "verified_at")
        if verified is None or (now is not None and now - verified > MEDIA_FRESH):
            return False
        if label == Label.EXACT.value and _get(item, "available") is False:
            return False
    return True


def choose(sets, unit: str, listing_ref: str = "", now=None):
    """The set a customer of ``unit`` gets: the one whose for_listing_refs holds their lead's listing ref, else the
    unit's default; only sets of their unit, only usable ones; None with the unit not known or nothing to send."""
    if unit not in UNITS:
        return None
    mine = sorted(
        (item for item in sets or () if (_get(item, "unit") == unit or not SAME_UNIT_ONLY) and usable(item, now)),
        key=lambda item: (str(_get(item, "name") or ""), _get(item, "pk") or _get(item, "id") or 0),
    )
    ref = ref_of(listing_ref)
    if ref:
        for item in mine:
            if ref in refs_of(item):
                return item
    return next((item for item in mine if _get(item, "default_for_unit") and _get(item, "unit") == unit), None)


# The step ---------------------------------------------------------------------------------------------------------------

# The model's sentences that deny photos ("I don't have photos right now"): wrong once ours go, and never needed after the
# no-media line.
_DENIES_PHOTOS = re.compile(
    r"\b(?:do\s*n'?t|dont|do\s+not|can'?t|cannot|unable\s+to)\s+(?:have|send|share)\b[^.?!]{0,40}\b(?:photos?|pictures?|pics?|images?|videos?)\b"
    r"|\bno\s+(?:photos?|pictures?|pics?|images?|videos?)\b|\b(?:photos?|pictures?|videos?)\s+(?:are\s+)?not\s+available\b",
    re.IGNORECASE,
)


def split_reply(reply: str) -> tuple[str, str]:
    """(what the model said, what it asked): its statements go before the photos, its questions after them, and its
    invitations with them (they ask); a sentence that says we have no photos goes nowhere."""
    before, after = [], []
    for sentence in filters.split_sentences(reply or ""):
        if _DENIES_PHOTOS.search(sentence):
            continue
        asks = rules.asks_question(sentence) or filters.offers_time(sentence) or filters.is_invitation(sentence)
        (after if asks else before).append(sentence)
    return " ".join(before), " ".join(after)


def settle(
    answer: dict,
    *,
    track: str,
    unit: str,
    clusters=(),
    words=(),
    earlier=(),
    known=None,
    library=(),
    listing_ref="",
    sent=None,
    now=None,
    quiet: bool = False,
    when=None,
    still_invalid: bool = False,
    appointment=None,
    may_invite: bool = True,
    slots=(),
    dry_run: bool = False,
) -> str:
    """The rent track's media step after the rest of the turn settled the answer (live and in the eval, with the same
    values): sets ``answer[STEP]`` and returns its trigger (ASKED, CONFIRMED), else ''. ``dry_run``: the answer is left
    as it is, and the trigger comes back only when a set's photos would go (residential.settle's ``sending``, read
    before it: "Here are the photos." is then no false claim). ``known``: the chat's facts
    (the answer's own are read on top of them); ``library``, ``listing_ref``, ``sent`` and ``slots`` may be callables,
    asked only when a step is due (the engine reads the database and the lead context then). ``slots``: code's two free
    slots, for the question after the photos."""
    if track != tracks.RENT or unit not in UNITS:
        return ""
    if answer.get("opt_out", "none") != "none" or (answer.get("handover") or {}).get("needed"):
        return ""
    if quiet or when is not None or still_invalid or any(answer.get(key) for key in CODE_LINE_KEYS):
        return ""
    # What the chat knew, with what the model recorded this turn (its unset keys say nothing).
    known = {**(known or {}), **{key: value for key, value in (answer.get("facts") or {}).items() if value not in (None, "", [])}}
    kind = trigger(words, unit=unit, clusters=clusters, for_client=known.get("for_client"), sent=sent, earlier=earlier, now=now)
    if not kind or (kind == CONFIRMED and (appointment is not None or not answer.get("send"))):
        return ""  # unasked photos only in a turn that says something, and never to someone booked already
    chosen = choose(_resolve(library) or (), unit, _resolve(listing_ref) or "", now)
    if chosen is None and kind == CONFIRMED:
        return ""  # nothing to show, and nobody asked: the turn goes on as it was
    if dry_run:
        return kind if chosen is not None else ""
    before, after = split_reply(answer["reply"] if answer.get("send") else "")
    invite = bool(may_invite and appointment is None and not after)
    answer[STEP] = {
        "trigger": kind,
        "unit": unit,
        "set": (_get(chosen, "pk") or _get(chosen, "id")) if chosen is not None else None,
        "name": str(_get(chosen, "name") or "") if chosen is not None else "",
        "label": str(_get(chosen, "label") or STANDARD) if chosen is not None else "",
        "photos": min(photo_count(chosen), PHOTOS_PER_SET) if chosen is not None else 0,
        "before": before,
        "after": after,
        "invite": invite,
        "slots": list(_resolve(slots) or []) if invite else [],
    }
    answer["share_office_location"] = False
    return kind


def text_without_set(step: dict, language: str, now, *, clean=None, ours: str = "") -> str:
    """A request for photos with no set of their unit imported: the model's statements, then "I don't have approved
    pictures for this one yet, but we can show you in person." and its own question, or code's two free slots (one
    message, sent as the turn's reply). ``clean``: filters.clean_reply with the turn's context."""
    clean = clean or (lambda text: text)
    before = clean(step.get("before") or "") if step.get("before") else ""
    questions = clean(step.get("after") or "") if step.get("after") else ""
    tail = follow_up(language, photos_sent=False, questions=questions, invite=bool(step.get("invite")), slots=step.get("slots") or (), now=now, ours=ours)
    return " ".join(part for part in (before, tail) if part)


def plan_of(step: dict) -> dict:
    """The step as the turn's actions keep it (no datetimes)."""
    return {
        key: value
        for key, value in {
            "trigger": step.get("trigger"), "unit": step.get("unit"), "set": step.get("set"), "name": step.get("name"),
            "photos": step.get("photos"), "invite": bool(step.get("invite")),
        }.items()
        if value not in (None, "")
    }


def media_report(step: dict, language: str = "en") -> str:
    """What the photos are, as the eval reports what goes out (the photos themselves go from their task)."""
    if not step.get("set"):
        return ""
    unit = step.get("unit") or STUDIO
    return f"[{step.get('photos') or 0} photos of the same type of {UNIT_WORDS.get(unit, unit)}: {step.get('name')}; caption: {caption(unit, language)}]"


# The library (the database) --------------------------------------------------------------------------------------------


def sets_for(unit: str) -> list[LeadAiUnitMediaSet]:
    """The sets of a unit, each with its photo count (``photo_count``)."""
    if unit not in UNITS:
        return []
    return list(
        LeadAiUnitMediaSet.objects.filter(unit=unit).annotate(photo_count=Count("photos", filter=Q(photos__kind=LeadAiShopMedia.Kind.PHOTO)))
    )


def pick(unit: str, listing_ref: str = "", now=None):
    """The set this customer gets (choose, on the database's sets of their unit), else None."""
    return choose(sets_for(unit), unit, listing_ref, now or timezone.now())


def photos_of(media_set) -> list[LeadAiShopMedia]:
    """A set's files in sending order: its photos by ``order`` (at most PHOTOS_PER_SET), then its video, if any."""
    rows = list(LeadAiShopMedia.objects.filter(unit_set=media_set).order_by("order", "pk"))
    photos = [row for row in rows if row.kind == LeadAiShopMedia.Kind.PHOTO][:PHOTOS_PER_SET]
    videos = [row for row in rows if row.kind == LeadAiShopMedia.Kind.VIDEO][:VIDEOS_PER_SET]
    return photos + videos


def sent_units(conversation) -> dict:
    """{unit: when its set last went to this chat}, from our own messages."""
    from apps.inbox.models import Message

    out: dict = {}
    rows = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__has_key="unit_set")
        .values_list("payload", "created_at")
        .order_by("-pk")[:50]
    )
    for payload, created in rows:
        unit = (payload or {}).get("unit") if isinstance(payload, dict) else None
        if unit in UNITS and unit not in out:
            out[unit] = created
    return out


def turn_step(
    answer: dict, conversation, decision, *, words=(), earlier=(), known=None, lead=None, now=None, quiet: bool = False,
    when=None, still_invalid: bool = False, appointment=None, may_invite: bool = True, slots=(), ruled: bool = False,
    dry_run: bool = False,
) -> str:
    """engine._run_claimed's media step (settle, with the database and the lead context read only when a step is due).
    ``lead``: tracks.lazy's lead context (its listing ref picks the set); ``ruled``: a shops rule or a deferral settled the
    turn (no step then); ``dry_run``: settle's, before residential.settle (no step set, a set's photos would go or not)."""
    if ruled or decision is None or getattr(decision, "track", "") != tracks.RENT:
        return ""

    def clusters():
        # Their words', else the lead context's (the bot stays on the enquiry: "Perfect, the Spain Cluster studio.").
        said = tuple(getattr(decision, "clusters", ()) or ())
        if said:
            return said
        cluster = lead_context_of(lead).get("cluster")
        return (cluster,) if isinstance(cluster, str) and cluster else ()

    return settle(
        answer, track=decision.track, unit=decision.unit, clusters=clusters, words=words, earlier=earlier, known=known,
        library=lambda: sets_for(decision.unit), listing_ref=lambda: lead_context_of(lead).get("listing_ref") or "",
        sent=lambda: sent_units(conversation), now=now, quiet=quiet, when=when, still_invalid=still_invalid,
        appointment=appointment, may_invite=may_invite, slots=slots, dry_run=dry_run,
    )


def lead_context_of(lead) -> dict:
    """The lead context from tracks.lazy (read from Bitrix at most once a turn, and once a chat), a dict, or nothing."""
    if lead is None:
        return {}
    if isinstance(lead, dict):
        return lead
    try:
        value = lead.get()
    except Exception:  # noqa: BLE001 - the lead context is a help, never a reason to fail a turn
        return {}
    return value if isinstance(value, dict) else {}


# Sending ------------------------------------------------------------------------------------------------------------------


def _payload(turn_id, **extra) -> dict:
    from .assistant import transcript

    return {"source": transcript.ASSISTANT, "turn": turn_id, **extra}


def deliver(conversation, step: dict, turn_id, language: str, *, clean=None):
    """The engine's send of a media step with a set: the model's statements now (cleaned by ``clean``:
    filters.clean_reply with the turn's context), then the photos and the question after them from their own task
    (tasks.send_unit_media), queued once the turn is stored. Returns the message sent now, else None; a failed send
    here leaves the photos to go."""
    from apps.inbox import services as inbox_services

    from .tasks import send_unit_media

    clean = clean or (lambda text: text)
    before = clean(step.get("before") or "") if step.get("before") else ""
    questions = clean(step.get("after") or "") if step.get("after") else ""
    first = None
    if before:
        try:
            first = inbox_services.send_text(conversation, None, before, payload=_payload(turn_id))
        except Exception as exc:  # noqa: BLE001 - the photos still go
            logger.warning("Lead AI could not send the words before the photos on conversation %s: %s", conversation.pk, exc)
    transaction.on_commit(
        lambda pk=conversation.pk, set_id=step["set"], turn=turn_id, lang=language, asked=questions, invite=bool(step.get("invite")): (
            send_unit_media.delay(pk, set_id, turn, lang, asked, invite)
        )
    )
    return first


def _sent_by_turn(conversation, turn_id) -> tuple[set, bool]:
    """(library file ids, follow-up sent) this turn's task sent already: a task delivered twice sends nothing twice."""
    from apps.inbox.models import Message

    if turn_id is None:
        return set(), False
    files, follow = set(), False
    for payload in Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, payload__turn=turn_id).values_list("payload", flat=True):
        if not isinstance(payload, dict):
            continue
        if payload.get("unit_set") and payload.get("shop_media_id"):
            files.add(payload["shop_media_id"])
        if payload.get("unit_follow_up"):
            follow = True
    return files, follow


def send_set(conversation_id: int, set_id: int, turn_id=None, language: str = "en", questions: str = "", invite: bool = False) -> dict:
    """A set's photos one by one (the caption on the first), then the question after them (follow_up: the model's own,
    or the visit question with two free slots computed now); with no photo delivered, the no-media line instead. Nothing
    goes once the chat is no longer the assistant's to answer; what this turn's task sent already is not sent again."""
    from apps.gateway.client import AlotsError
    from apps.inbox import services as inbox_services
    from apps.inbox.models import Conversation
    from apps.inbox.services import SendBlocked

    from .assistant import engine
    from .models import LeadAiSettings

    out: dict = {"files": 0, "skipped": [], "follow_up": None, "stopped": ""}
    conversation = Conversation.objects.select_related("contact", "number").filter(pk=conversation_id).first()
    media_set = LeadAiUnitMediaSet.objects.filter(pk=set_id).first() if set_id else None
    if conversation is None or media_set is None:
        out["stopped"] = "no such chat or set"
        return out
    done, follow_done = _sent_by_turn(conversation, turn_id)
    rows = photos_of(media_set)
    already = len([row for row in rows if row.pk in done])
    for index, row in enumerate(rows):
        if row.pk in done:
            continue
        why = shop_media._still_ours(conversation)
        if why:
            out["stopped"] = why
            return out
        text = caption(media_set.unit, language) if index == 0 else ""
        try:
            shop_media.send_file(
                conversation, row, turn_id=turn_id, shop_type=media_set.unit, caption=text,
                extra={"unit_set": media_set.pk, "unit": media_set.unit, "unit_label": media_set.label},
            )
            out["files"] += 1
        except (AlotsError, SendBlocked, OSError, ValueError) as exc:
            logger.warning("Lead AI skipped set photo %s for conversation %s: %s", row.pk, conversation_id, exc)
            out["skipped"].append(row.pk)
            continue
        time.sleep(SEND_PAUSE)
    if follow_done:
        out["stopped"] = "the question went out already"
        return out
    why = shop_media._still_ours(conversation)
    if why:
        out["stopped"] = why
        return out
    now = timezone.now()
    settings_row = LeadAiSettings.load()
    slots = hours.offer_pair(now, settings_row.closed_dates, engine.taken_slots(conversation, now)) if invite else []
    text = follow_up(language, photos_sent=bool(out["files"] or already), questions=questions, invite=invite, slots=slots, now=now)
    if text:
        message = inbox_services.send_text(conversation, None, text, payload=_payload(turn_id, unit_follow_up=media_set.pk))
        out["follow_up"] = message.pk
    if out["files"]:
        from .tasks import record_crm_note

        lines = note_lines(media_set, out["files"])
        transaction.on_commit(lambda pk=conversation.pk, note=lines: record_crm_note.delay(pk, NOTE_KIND, note))
    return out


NOTE_KIND = "photos sent"


def note_lines(media_set, count: int) -> list[str]:
    """The lead's timeline note for a set sent (spec §5: media sent and its label), in English for the agents."""
    verified = f"; built {timezone.localtime(media_set.verified_at):%d %b %Y}" if media_set.verified_at else ""
    return [
        f"Sent {count} photo{'s' if count != 1 else ''} of the same type of {UNIT_WORDS.get(media_set.unit, media_set.unit)}, "
        f"set \"{media_set.name}\".",
        f"Label: {LABEL_WORDS.get(media_set.label, media_set.label)}{verified}. Our agent shows the exact unit at the viewing.",
    ]


# The import (set.json) -----------------------------------------------------------------------------------------------------


class SetRefused(ValueError):
    """A set.json the library cannot take; the message says why, for an admin."""


def holds_set(path: str) -> bool:
    return os.path.isfile(os.path.join(path, SET_FILE))


def holds_sets(path: str) -> bool:
    """A folder whose own folders hold set.json files ("Residential sets")."""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    return any(os.path.isdir(os.path.join(path, name)) and holds_set(os.path.join(path, name)) for name in names)


def set_folders(path: str) -> list[str]:
    """Every set folder under ``path``: itself, its own folders, and those of a folder of sets inside it (the "Types
    shops" folder holds "Residential sets"), in name order."""
    if holds_set(path):
        return [path]
    found = []
    for name in sorted(os.listdir(path), key=shop_media._natural):
        full = os.path.join(path, name)
        if not os.path.isdir(full):
            continue
        if holds_set(full):
            found.append(full)
        elif holds_sets(full):
            found += [os.path.join(full, inner) for inner in sorted(os.listdir(full), key=shop_media._natural) if holds_set(os.path.join(full, inner))]
    return found


def _built_on(value):
    if value in (None, ""):
        return None
    try:
        day = dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise SetRefused(f"built_on {value!r} is not a date (YYYY-MM-DD).") from None
    return dt.datetime.combine(day, dt.time(0, 0), tzinfo=hours.DUBAI)


def read_set(folder: str) -> dict:
    """A set folder's set.json, checked on its own (the whole run's checks are import_directory's): the plan for it, or
    SetRefused. Its photos are read and checked by their bytes; nothing is stored."""
    name = shop_media.clean_name(os.path.basename(os.path.normpath(folder)))[:NAME_MAX]
    path = os.path.join(folder, SET_FILE)
    try:
        if os.path.getsize(path) > SET_FILE_MAX:
            raise SetRefused("set.json is larger than 64 KB.")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except SetRefused:
        raise
    except (OSError, ValueError) as exc:
        raise SetRefused(f"set.json cannot be read ({type(exc).__name__}).") from None
    if not isinstance(data, dict):
        raise SetRefused("set.json is not an object.")
    unit = str(data.get("unit") or "").strip()
    if unit not in UNITS:
        raise SetRefused(f"unit {unit!r}: a set is a studio or a one_br.")
    label = str(data.get("label") or "").strip()
    if label not in IMPORTED_LABELS:
        raise SetRefused(f"label {label!r}: every set is the same type of unit, 'standard', never exact or matching (Q36).")
    default = data.get("default_for_unit", False)
    if not isinstance(default, bool):
        raise SetRefused("default_for_unit must be true or false.")
    raw_refs = data.get("for_listing_refs") or []
    if not isinstance(raw_refs, list):
        raise SetRefused("for_listing_refs must be a list.")
    refs = []
    for value in raw_refs:
        ref = ref_of(value) if isinstance(value, str) else ""
        if not ref:
            raise SetRefused(f"listing ref {str(value)[:40]!r} is not shaped a7group-NNNN.")
        if ref not in refs:
            refs.append(ref)
    cluster = str(data.get("cluster") or "").strip()
    if cluster and not _CLUSTER.match(cluster):
        raise SetRefused(f"cluster {cluster[:40]!r} is not a cluster's name.")
    photos = data.get("photos") or []
    if not isinstance(photos, list) or not photos:
        raise SetRefused("photos must list the set's photos, in sending order.")
    if len(photos) > PHOTOS_PER_SET:
        raise SetRefused(f"{len(photos)} photos: a set takes at most {PHOTOS_PER_SET}.")
    video = data.get("video")
    files = []
    for entry in photos:
        file_name = entry.get("file") if isinstance(entry, dict) else entry
        files.append(("photo", str(file_name or "")))
    if video not in (None, "", [], {}):
        file_name = video.get("file") if isinstance(video, dict) else video
        if isinstance(video, list):
            raise SetRefused(f"one video at most: a set takes {VIDEOS_PER_SET}.")
        files.append(("video", str(file_name or "")))
    checked = []
    seen = set()
    for want, file_name in files:
        base = os.path.basename(file_name.replace("\\", "/"))
        if not base or base != file_name or base in (".", "..") or base == SET_FILE:
            raise SetRefused(f"{file_name[:60]!r} is not a file of this folder.")
        full = os.path.join(folder, base)
        try:
            if os.path.getsize(full) > shop_media.VIDEO_MAX:
                raise SetRefused(f"{base}: larger than 16 MB.")
            with open(full, "rb") as handle:
                data_bytes = handle.read()
        except SetRefused:
            raise
        except OSError as exc:
            raise SetRefused(f"{base}: cannot read it ({type(exc).__name__}).") from None
        try:
            kind, mime, found = shop_media.check_file(base, data_bytes)
        except shop_media.MediaRejected as exc:
            raise SetRefused(str(exc)) from None
        if kind != want:
            raise SetRefused(f"{base}: set.json lists it as a {want}, and it is a {kind}.")
        sha = hashlib.sha256(data_bytes).hexdigest()
        if sha in seen:
            raise SetRefused(f"{base}: the same photo twice in the set.")
        seen.add(sha)
        checked.append({"file": base, "kind": kind, "mime": mime, "format": found, "sha256": sha, "data": data_bytes})
    return {
        "name": name, "unit": unit, "label": label, "default_for_unit": default, "for_listing_refs": refs, "cluster": cluster,
        "verified_at": _built_on(data.get("built_on")), "files": checked,
    }


def _conflicts(plan: dict, others: dict) -> str:
    """Why this set cannot stand beside the others of its unit ('' when it can): a second default, or a listing ref of
    another set. ``others``: {name: (unit, default, refs)} of every set as the run has left them so far."""
    for name, (unit, default, refs) in others.items():
        if unit != plan["unit"] or name == plan["name"]:
            continue
        if default and plan["default_for_unit"]:
            return f"a second default for {plan['unit']}: '{name}' is the default already."
        shared = sorted(set(refs) & set(plan["for_listing_refs"]))
        if shared:
            return f"listing ref {shared[0]} is in set '{name}' already (one set per ref and unit)."
    return ""


def _shared_photo(plan: dict, taken: dict) -> str:
    """A photo of this set that another set of its unit holds already, in the library or in this run (``taken``:
    {(unit, sha256): set name}), '' for none: one file belongs to one set."""
    for item in plan["files"]:
        owner = taken.get((plan["unit"], item["sha256"]))
        if owner and owner != plan["name"]:
            return f"{item['file']}: the same photo is in '{owner}' already."
        other = (
            LeadAiShopMedia.objects.filter(shop=plan["unit"], sha256=item["sha256"])
            .exclude(unit_set__name=plan["name"])
            .select_related("unit_set")
            .first()
        )
        if other is not None:
            owner = other.unit_set.name if other.unit_set_id else "the shop media"
            return f"{item['file']}: the same photo is in '{owner}' already."
    return ""


def import_directory(path: str, *, dry_run: bool = False, uploaded_by=None) -> list[str]:
    """Load every set folder under ``path`` (set_folders) into the library, each from its set.json: one line per set
    and per refusal. A set is all or nothing; a set already there (by its folder's name) is brought to what its
    set.json says (photos added, reordered, or taken out), so running it twice adds nothing twice. ``dry_run`` checks
    and reports, and stores nothing."""
    if not os.path.isdir(path):
        raise shop_media.MediaRejected(f"{path} is not a directory.")
    lines: list[str] = []
    plans = []
    for folder in set_folders(path):
        label = shop_media.clean_name(os.path.basename(os.path.normpath(folder)))
        try:
            plans.append(read_set(folder))
        except SetRefused as exc:
            lines.append(f"refused set '{label}': {exc}")
    # Every set as the run leaves it: the library's own first, then each set this run takes. A set that conflicts now may
    # stand once another one moved (a default handed from one set to another), so the refused are tried again until
    # nothing changes; a set refused for good keeps what the library had for it.
    others = {row.name: (row.unit, row.default_for_unit, refs_of(row)) for row in LeadAiUnitMediaSet.objects.all()}
    taken: dict = {}  # (unit, sha256) -> the set of this run that holds the photo
    waiting, results = list(plans), {}
    while waiting:
        still = []
        for plan in waiting:
            why = _conflicts(plan, others) or _shared_photo(plan, taken)
            if why:
                still.append(plan)
                results[plan["name"]] = f"refused set '{plan['name']}': {why}"
                continue
            try:
                results[plan["name"]] = _apply_set(plan, dry_run=dry_run, uploaded_by=uploaded_by)
            except IntegrityError:
                logger.warning("Lead AI could not store the set %s", plan["name"], exc_info=True)
                results[plan["name"]] = f"refused set '{plan['name']}': the library changed while it was imported; run it again."
                continue
            others[plan["name"]] = (plan["unit"], plan["default_for_unit"], plan["for_listing_refs"])
            taken.update({(plan["unit"], item["sha256"]): plan["name"] for item in plan["files"]})
        if len(still) == len(waiting):
            break
        waiting = still
    return lines + [results[plan["name"]] for plan in plans]


def _apply_set(plan: dict, *, dry_run: bool, uploaded_by) -> str:
    """Store one checked set (or say what a dry run would do): the set's row, then its files in set.json's order."""
    current = LeadAiUnitMediaSet.objects.filter(name=plan["name"]).first()
    have = {row.sha256: row for row in LeadAiShopMedia.objects.filter(unit_set=current)} if current is not None else {}
    wanted = [item["sha256"] for item in plan["files"]]
    adds = [item for item in plan["files"] if item["sha256"] not in have]
    drops = [row for sha, row in have.items() if sha not in wanted]
    meta = {
        "unit": plan["unit"], "label": plan["label"], "default_for_unit": plan["default_for_unit"],
        "for_listing_refs": plan["for_listing_refs"], "cluster": plan["cluster"], "verified_at": plan["verified_at"],
    }
    changed = current is None or any(getattr(current, key) != value for key, value in meta.items())
    photos = sum(1 for item in plan["files"] if item["kind"] == "photo")
    summary = f"{UNIT_WORDS[plan['unit']]}, {photos} photo{'s' if photos != 1 else ''}" + (", the unit's default" if plan["default_for_unit"] else "")
    if current is not None and not adds and not drops and not changed and [have[sha].order for sha in wanted] == list(range(1, len(wanted) + 1)):
        return f"already there set '{plan['name']}' ({summary})"
    if dry_run:
        verb = "would add" if current is None else "would update"
        return f"{verb} set '{plan['name']}' ({summary})"
    created = current is None
    with transaction.atomic():
        if current is None:
            current = LeadAiUnitMediaSet.objects.create(name=plan["name"], **meta)
        else:
            for key, value in meta.items():
                setattr(current, key, value)
            current.save()
        for row in drops:
            shop_media.delete(row)
        for position, item in enumerate(plan["files"], start=1):
            row = have.get(item["sha256"])
            if row is None:
                row = LeadAiShopMedia(
                    shop=plan["unit"], kind=item["kind"], file_name=item["file"], mime_type=item["mime"],
                    size_bytes=len(item["data"]), sha256=item["sha256"], order=position, uploaded_by=uploaded_by, unit_set=current,
                )
                from django.core.files.base import ContentFile

                row.file.save(f"{plan['unit']}-{item['sha256'][:16]}.{shop_media.EXTENSION[item['format']]}", ContentFile(item["data"]), save=False)
                row.save()
            elif row.order != position or row.file_name != item["file"]:
                LeadAiShopMedia.objects.filter(pk=row.pk).update(order=position, file_name=item["file"])
    return f"{'added' if created else 'updated'} set '{plan['name']}' ({summary})"


# The panel ---------------------------------------------------------------------------------------------------------------


def serialize_sets(user=None) -> dict:
    """The library as the panel lists it (lead-ai/unit-media.js): the sets by unit, each with its label, the default
    mark, its listing refs, verified_at and its photos in sending order."""
    from .views import _can_edit

    units = []
    for unit, label in LeadAiUnitMediaSet.Unit.choices:
        items = []
        for media_set in LeadAiUnitMediaSet.objects.filter(unit=unit).order_by("-default_for_unit", "name"):
            files = photos_of(media_set)
            items.append(
                {
                    "id": media_set.pk,
                    "name": media_set.name,
                    "label": media_set.label,
                    "label_text": LABEL_WORDS.get(media_set.label, media_set.label),
                    "default_for_unit": media_set.default_for_unit,
                    "for_listing_refs": refs_of(media_set),
                    "cluster": media_set.cluster,
                    "verified_at": media_set.verified_at.astimezone(hours.DUBAI).isoformat() if media_set.verified_at else None,
                    "sendable": usable({"label": media_set.label, "photo_count": sum(1 for row in files if row.kind == "photo"),
                                        "verified_at": media_set.verified_at, "available": media_set.available}, timezone.now()),
                    "files": [
                        {
                            "id": row.pk, "kind": row.kind, "file_name": row.file_name, "size_bytes": row.size_bytes,
                            "order": position, "url": f"/api/leadai/unit-media/{row.pk}/file/",
                        }
                        for position, row in enumerate(files, start=1)
                    ],
                }
            )
        units.append({"unit": unit, "label": label, "sets": items})
    return {
        "can_edit": _can_edit(user) if user is not None else False,
        "limits": {"photos": PHOTOS_PER_SET, "videos": VIDEOS_PER_SET, "photo_mb": shop_media.PHOTO_MAX // shop_media.MB, "video_mb": shop_media.VIDEO_MAX // shop_media.MB},
        "captions": {unit: CAPTIONS[unit]["en"] for unit in UNITS},
        "units": units,
    }
