"""Decisions made by code before (or instead of) the model.

- Opt-out: a tap on a template's "Unsubscribe" / "Stop promotions" /
  "Not Interested" button, or a short message that is only an opt-out phrase,
  in English, Arabic, Urdu, Roman Urdu or Hindi. "Unsubscribe" is the
  most-tapped template button on this account; one sales-style reply after
  it invites a block, which lowers the agent's number's quality rating.
- Acknowledgements ("ok", "thanks", an emoji) that need no answer.
- Deferrals ("I will message you") that put a visit off, and plain yeses
  ("yes", "ji") that accept one.
- Automatic replies from the customer's own WhatsApp Business bot.
- The fixed lines sent in those cases, in the customer's language.
"""

from __future__ import annotations

import re
import unicodedata

STOP_ALL = "stop_all"
NOT_INTERESTED = "not_interested"
WRONG_NUMBER = "wrong_number"

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
    "ok", "okay", "okk", "k", "kk", "thanks", "thank you", "thanx", "thx", "ty", "noted", "fine", "great",
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


FILLERS = ("please", "pls", "plz", "bro", "sir", "thanks", "thank you", "plz", "bhai", "yaar")


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


def is_deferral(text: str) -> bool:
    """A whole short message that puts the visit off ("ok, I'll message u later")."""
    words = " ".join(_TYPED.get(word, word) for word in normalize_text(text).split())
    return _whole_short_message(words, DEFERRALS, DEFERRAL_FILLERS)


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
}


def line(kind: str, language: str) -> str:
    table = LINES[kind]
    return table.get(language) or table["en"]
