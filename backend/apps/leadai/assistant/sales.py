"""A buyer of a studio or a one-bedroom in International City (batch 2e slice C; spec §3.1, §3.2, §2.4; brief Part 5B; T94).

Code decides the sale steps; the model writes the words of the questions (RES_SYSTEM's sale section) and code checks them:

- **The buyer's five questions, in three messages** (``MESSAGES``): who it is for; cash or finance and how soon; a rented or
  a vacant unit (with the balcony for a one-bedroom) and investment or own use. What the chat knows is skipped
  (``next_questions``, ``step_line`` for the context), and a question of the model's about something they told us already
  is cut (``drop_known_questions``). The model's words that skip the step's questions get them in the brief's own words
  (``ask_next``, ``next_question_line``; what their words just answered counts as known: ``answered``). Then the price,
  then the meeting: a 5-minute call with our sales team or a visit to our office, the full name, the booking (calls.py, the
  full-name gate); asked for at once ("just tell me the price and book", ``asks_to_meet``), the meeting goes now
  (``book_now``).
- **The price is never hidden** (``asks_price``, ``price_line``): a buyer who asks the price gets the band of their unit (a
  studio's, from around AED 310,000 in Morocco Cluster, a one-bedroom's; both, each labelled, while the unit is unknown),
  code's line when the model's words carry none.
- **No media first** (§3.2): a request for photos or a video gets ``res_buyer_media`` and two free call slots, never a step.
- **The meeting** (§3.1 message 5): an open "when" or a time the model offers becomes code's two free CALL slots (office
  slots when they asked for the office), from the call pool (calls.py); a call asked for with no time gets the slots too
  (``call_step`` books one with a day and an hour), and a buyer abroad gets the call, never 2d's abroad_cannot_visit.
- **To a person** (§3.1): negotiation, an offer, the mortgage process, DLD fees and legal questions, in their own words, go
  to our sales team with the existing reasons (price_or_details_insisted, legal_visa_licence_contract) and the handover line.
- **Commission** (§2.4, Q33 open): ``res_commission_sale``, "Our agent will go through all the costs with you on the call.",
  and the model's own words on it cut (residential.commission_answer's sale rule; residential.settle has done both on the
  engine's path, before this).
- **The full name** is the rent flow's gate (residential.name_turn and hold_for_name, spec §2.6): a call is held at place
  "call" and booked there once the name comes (``mark_hold``, ``offer_call_slots``).
- **What the chat keeps** (``record_need``): 2d's facts.need "buy" and facts.wanted ("to buy a studio"), intent buy, so the
  follow-ups' holds, the nudges and the panel note read a buyer as 2d did.

``settle`` runs on the sale track in place of 2d's who_they_are (engine._run_claimed, and the eval the same way), and its
fixed lines (``answer["sale"]``) are written by ``text`` in the language code writes in. Plain functions on plain data.
"""

from __future__ import annotations

import datetime as dt
import re

from . import calls, filters, hours, needs, offers, residential, rules, shop_flow, shops

FOR_CLIENT = "for_client"
PAYMENT = "payment"
TIMELINE = "buy_timeline"
STATUS = "occupancy_status"
PURPOSE = "purpose"
BALCONY = "balcony"
# Brief Part 5B: the five questions in this order, in three messages; a one-bedroom's balcony goes with question 4.
QUESTIONS = (FOR_CLIENT, PAYMENT, TIMELINE, STATUS, PURPOSE)
MESSAGES = ((FOR_CLIENT,), (PAYMENT, TIMELINE), (STATUS, PURPOSE))
STUDIO = "studio"
ONE_BR = "one_br"

# What a turn's sale step did (the turn's actions, "sale").
BUYER_MEDIA = "buyer_media"
CALL_SLOTS = "call_slots"
CALL_TAKEN = "call_taken"
ABROAD = "abroad"
HANDOVER = "handover"
FULL_NAME = "full_name"
PRICE = "price"
COMMISSION = "commission"
KNOWN = "known_question"
MEETING = "meeting_slots"
NEXT = "next_questions"  # code asked the SALE STEP's questions the model skipped (ask_next)

# The handover reasons the brief's sales handover takes (the existing ones: spec §3.1).
REASON_PRICE = "price_or_details_insisted"
REASON_LEGAL = "legal_visa_licence_contract"

_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


def _flat(text) -> str:
    return " ".join(str(text or "").replace("’", "'").split())


# The question order -----------------------------------------------------------------------------------------------


def known(facts: dict, key: str) -> bool:
    """The chat knows the answer to this question (facts as the residential schema keeps them)."""
    value = (facts or {}).get(key)
    if key == FOR_CLIENT:
        return isinstance(value, bool)
    return value not in (None, "", [])


def questions_left(facts: dict, unit: str = "") -> list[str]:
    """The buyer's questions the chat does not know yet, in the brief's order (a one-bedroom's balcony after question 4)."""
    left = []
    for key in QUESTIONS:
        if not known(facts, key):
            left.append(key)
        if key == STATUS and unit == ONE_BR and not known(facts, BALCONY):
            left.append(BALCONY)
    return left


def next_questions(facts: dict, unit: str = "") -> tuple:
    """The questions of the next message: the first of the three messages with a question left, without what is known. A
    one-bedroom's balcony rides in question 4's own sentence (brief Part 5B), so a message still asks two questions."""
    left = questions_left(facts, unit)
    for group in MESSAGES:
        asked = [key for key in group if key in left]
        if group == (STATUS, PURPOSE) and BALCONY in left:
            asked = [key for key in (STATUS, BALCONY, PURPOSE) if key in left]
        if asked:
            return tuple(asked)
    return ()


_ASK_WORDS = {
    FOR_CLIENT: "whether it is for themselves or for a client",
    PAYMENT: "whether they are a cash buyer or will use finance (a mortgage)",
    TIMELINE: "how soon they plan to buy",
    STATUS: "whether they want a rented (tenanted) unit or a vacant one",
    BALCONY: "whether they prefer a balcony (in the same question as the rented or vacant unit)",
    PURPOSE: "whether it is for investment or their own use",
}


def step(facts: dict, unit: str = "", *, priced: bool = False) -> str:
    """The sale step the chat is at: the next questions ("for_client", "payment", ...), "price" once they are answered or
    skipped, then "meeting" (a call or a visit, the full name, the booking)."""
    questions = next_questions(facts, unit)
    if questions:
        return questions[0]
    return "meeting" if priced else PRICE


def context_lines(facts: dict, unit: str, clusters, earlier, now, closed_dates=(), call_taken=(), residential_facts=None) -> list[str]:
    """The sale track's own lines of the residential context (spec §1.3: CALL SLOTS; the brief's question order as SALE
    STEP), as one text each."""
    done = priced_before(earlier, unit, clusters, residential_facts)
    return [step_line(facts, unit, priced=done), calls.slots_line(now, closed_dates, call_taken)]


def context_parts(facts: dict, unit: str, clusters, earlier, now, closed_dates=(), call_taken=(), residential_facts=None) -> dict:
    """What residential.context takes on the sale track (engine._run_claimed and the eval's build): the SALE STEP line and
    the CALL SLOTS (the call pool's free slots, an hour apart)."""
    done = priced_before(earlier, unit, clusters, residential_facts)
    return {
        "sale_step": step_line(facts, unit, priced=done),
        "calls": [hours.slot_line(slot, now) for slot in calls.free(now, closed_dates, call_taken)],
    }


def step_line(facts: dict, unit: str = "", *, priced: bool = False) -> str:
    """The residential context's SALE STEP line: what to ask now, in one message, and what comes after (spec §3.1)."""
    questions = next_questions(facts, unit)
    if questions:
        asked = " and ".join(_ASK_WORDS[key] for key in questions)
        then = "Give the price at once if they ask it."
        return f"SALE STEP: ask now, in one message: {asked}. {then} Skip any question they will not answer."
    if not priced:
        return "SALE STEP: give the price band of their unit (RES FACTS, sale), then offer the meeting: a quick 5-minute call with our sales team, or a visit to our office."
    return "SALE STEP: offer the meeting: a quick 5-minute call with our sales team (two CALL SLOTS), or a visit to our office (two FREE SLOTS)."


# Skip what is known --------------------------------------------------------------------------------------------------

_ASKS_ABOUT = {
    FOR_CLIENT: re.compile(
        r"\bfor\s+yourself\b|\bfor\s+a\s+client\b|\bfor\s+your\s+own\b|\bapne\s+liye\b|\bclient\s+ke\s+liye\b|لعميل|لك\s+شخصياً|لنفسك"
        r"|اپنے\s+لیے|کلائنٹ|अपने\s+लिए|क्लाइंट",
        re.IGNORECASE,
    ),
    PAYMENT: re.compile(
        r"\bcash\b|\bfinanc\w*|\bmortgage\b|\bloan\b|\bbank\b|نقد|كاش|تمويل|رهن|قرض|کیش|نقد|فنانس|قرض|मॉर्गेज|लोन|कैश|फाइनेंस",
        re.IGNORECASE,
    ),
    TIMELINE: re.compile(
        r"\bhow\s+soon\b|\bwhen\s+(?:are\s+you|do\s+you|would\s+you|will\s+you)\s+(?:\w+\s+){0,3}(?:buy|purchase|planning|looking)\b|\btimeline\b"
        r"|\bkab\s+tak\b|\bkitni\s+jaldi\b|متى\s+تخطط|متى\s+تريد\s+الشراء|کب\s+تک|کتنی\s+جلدی|कब\s+तक|कितनी\s+जल्दी",
        re.IGNORECASE,
    ),
    STATUS: re.compile(
        r"\brented\b|\bvacant\b|\btenanted\b|\bempty\b|\bwith\s+a\s+tenant\b|\bkhaa?li\b|\bkiraye\s+par\b|خالي|خالية|شاغر|شاغرة|مؤجر|مؤجرة|خالی|کرائے\s+پر|ख़ाली|खाली|किराए\s+पर",
        re.IGNORECASE,
    ),
    BALCONY: re.compile(r"\bbalcon\w*|بلكون|شرفة|بالکونی|बालकनी", re.IGNORECASE),
    PURPOSE: re.compile(
        r"\binvest\w*|\bown\s+use\b|\bpersonal\s+use\b|\blive\s+in\b|\bend\s+use\b|\bfor\s+living\b|استثمار|للسكن|سرمایہ|رہنے|निवेश|रहने",
        re.IGNORECASE,
    ),
}


def asked_keys(sentence: str) -> set:
    """The buyer's questions a sentence of ours asks about."""
    return {key for key, pattern in _ASKS_ABOUT.items() if pattern.search(sentence or "")}


def drop_known_questions(reply: str, facts: dict) -> tuple[str, bool]:
    """The model's reply without its questions about what the chat knows already (brief Part 5B: skip what is known): a
    question every one of whose topics is known goes; one that also asks something new stays. (reply, changed)."""
    sentences = filters.split_sentences(reply)
    kept, cut = [], False
    for sentence in sentences:
        if any(mark in sentence for mark in filters.QUESTION_MARKS):
            keys = asked_keys(sentence)
            if keys and all(known(facts, key) for key in keys):
                cut = True
                continue
        kept.append(sentence)
    return (" ".join(kept).strip() if cut else str(reply or "").strip()), cut


# The next questions, in code's words when the model skips them. The 2e real-model gate (round 1) answered "Within 2 months"
# (cash known) with the cluster or the meeting, never the brief's message 3, in both runs of shops-sale-known-question-cut:
# SALE STEP in the context says what to ask, and the model does not always ask it. _Q_TIMELINE and _Q_PURPOSE hold the
# question alone and as a message's second ("And how soon ...?"); _Q_STATUS alone and with a one-bedroom's balcony. Message
# 2 asked whole is residential._SALE_NEXT, word for word.
_Q_PAYMENT = {
    "en": "Are you a cash buyer or planning to use finance?",
    "ar": "هل ستشتري نقداً أم بتمويل؟",
    "ur_latin": "Kya aap cash buyer hain ya finance (mortgage) lenge?",
    "ur": "کیا آپ کیش خریدار ہیں یا فنانس (مارگیج) لیں گے؟",
    "hi_latin": "Kya aap cash buyer hain ya finance (mortgage) lenge?",
    "hi": "क्या आप कैश ख़रीदार हैं या फ़ाइनेंस (मॉर्गेज) लेंगे?",
}
_Q_TIMELINE = {
    "en": ("How soon are you looking to buy?", "And how soon are you looking to buy?"),
    "ar": ("متى تخطط للشراء؟", "ومتى تخطط للشراء؟"),
    "ur_latin": ("Aap kitni jaldi khareedna chahte hain?", "Aur aap kitni jaldi khareedna chahte hain?"),
    "ur": ("آپ کتنی جلدی خریدنا چاہتے ہیں؟", "اور آپ کتنی جلدی خریدنا چاہتے ہیں؟"),
    "hi_latin": ("Aap kitni jaldi kharidna chahte hain?", "Aur aap kitni jaldi kharidna chahte hain?"),
    "hi": ("आप कितनी जल्दी ख़रीदना चाहते हैं?", "और आप कितनी जल्दी ख़रीदना चाहते हैं?"),
}
# Question 4 (a one-bedroom's balcony in its own sentence: two questions to a message, brief Part 5B).
_Q_STATUS = {
    "en": ("Do you prefer a rented unit or a vacant one?", "Do you prefer a rented unit or a vacant one, and would you like a balcony?"),
    "ar": ("هل تفضّل وحدة مؤجرة أم شاغرة؟", "هل تفضّل وحدة مؤجرة أم شاغرة، وهل تريدها مع شرفة؟"),
    "ur_latin": (
        "Kya aap kiraye par di hui unit pasand karenge ya khali?",
        "Kya aap kiraye par di hui unit pasand karenge ya khali, aur kya balcony chahiye?",
    ),
    "ur": ("کیا آپ کرائے پر دی ہوئی یونٹ پسند کریں گے یا خالی؟", "کیا آپ کرائے پر دی ہوئی یونٹ پسند کریں گے یا خالی، اور کیا بالکونی چاہیے؟"),
    "hi_latin": (
        "Kya aap kiraye par di hui unit pasand karenge ya khaali?",
        "Kya aap kiraye par di hui unit pasand karenge ya khaali, aur kya balcony chahiye?",
    ),
    "hi": ("क्या आप किराए पर दी हुई यूनिट पसंद करेंगे या ख़ाली?", "क्या आप किराए पर दी हुई यूनिट पसंद करेंगे या ख़ाली, और क्या बालकनी चाहिए?"),
}
_Q_BALCONY = {
    "en": "Do you prefer a balcony?",
    "ar": "هل تفضّل شقة مع شرفة؟",
    "ur_latin": "Kya aap balcony pasand karenge?",
    "ur": "کیا آپ بالکونی پسند کریں گے؟",
    "hi_latin": "Kya aap balcony pasand karenge?",
    "hi": "क्या आप बालकनी पसंद करेंगे?",
}
_Q_PURPOSE = {
    "en": ("Is this for investment or for your own use?", "And is this for investment or for your own use?"),
    "ar": ("هل هي للاستثمار أم للاستخدام الشخصي؟", "وهل هي للاستثمار أم للاستخدام الشخصي؟"),
    "ur_latin": ("Kya yeh investment ke liye hai ya apne istemal ke liye?", "Aur kya yeh investment ke liye hai ya apne istemal ke liye?"),
    "ur": ("کیا یہ سرمایہ کاری کے لیے ہے یا اپنے استعمال کے لیے؟", "اور کیا یہ سرمایہ کاری کے لیے ہے یا اپنے استعمال کے لیے؟"),
    "hi_latin": ("Kya yeh investment ke liye hai ya apne istemaal ke liye?", "Aur kya yeh investment ke liye hai ya apne istemaal ke liye?"),
    "hi": ("क्या यह निवेश के लिए है या अपने इस्तेमाल के लिए?", "और क्या यह निवेश के लिए है या अपने इस्तेमाल के लिए?"),
}


def next_question_line(language: str, questions) -> str:
    """The brief's own words for the questions of the next message (next_questions), in the customer's language: "Do you
    prefer a rented unit or a vacant one? And is this for investment or for your own use?" (message 3)."""
    lang = _lang(language)
    keys = tuple(questions or ())
    if not keys:
        return ""
    if keys[0] == FOR_CLIENT:
        return residential._FOR_WHOM[lang]
    if PAYMENT in keys and TIMELINE in keys:
        return residential._SALE_NEXT[lang]
    parts = []
    if PAYMENT in keys:
        parts.append(_Q_PAYMENT[lang])
    if TIMELINE in keys:
        parts.append(_Q_TIMELINE[lang][1 if parts else 0])
    if STATUS in keys:
        parts.append(_Q_STATUS[lang][1 if BALCONY in keys else 0])
    elif BALCONY in keys:
        parts.append(_Q_BALCONY[lang])
    if PURPOSE in keys:
        parts.append(_Q_PURPOSE[lang][1 if parts else 0])
    return " ".join(parts)


# A buyer who will not answer is not pushed (brief Part 5B: "don't push. Move on and offer the meeting").
_REFUSES = re.compile(
    r"\b(?:rather\s+not|prefer\s+not|no\s+comment|not\s+(?:your|ur)\s+(?:business|concern)|why\s+do\s+you\s+(?:need|want|ask)"
    r"|(?:do\s*n'?t|dont|do\s+not)\s+want\s+to\s+(?:say|share|answer|tell)|won'?t\s+(?:say|share|answer|tell)|skip\s+(?:it|this|that|the\s+questions?)"
    r"|nahi\s+bata\w*|nahin\s+bata\w*|mat\s+pooch\w*)\b|لا\s+أريد\s+(?:أن\s+)?(?:أقول|أجيب)|نہیں\s+بتا|नहीं\s+बता",
    re.IGNORECASE,
)


def refuses(texts) -> bool:
    return any(_REFUSES.search(_flat(text)) for text in texts or ())


# Their own words answering a question of the five, in a sentence that asks nothing ("Within 2 months", "cash", "vacant,
# for investment"): read beside the facts the model recorded, so code never asks again what they just said.
_ANSWERS = {
    PAYMENT: _ASKS_ABOUT[PAYMENT],
    TIMELINE: re.compile(
        r"\bwithin\b|\bin\s+(?:a|an|one|two|three|four|five|six|\d+)\s+(?:days?|weeks?|months?|years?)\b|\b(?:next|this|coming)\s+(?:week|month|year)\b"
        r"|\b\d+\s*(?:-\s*\d+\s*)?(?:days?|weeks?|months?|years?)\b|\basap\b|\bimmediately\b|\burgent\w*|\bright\s+away\b|\bno\s+rush\b"
        r"|\bjaldi\b|\bfauran\b|خلال|فوراً|فورا|جلد|ہفتے|مہینے|महीने|हफ़्ते|जल्दी",
        re.IGNORECASE,
    ),
    STATUS: re.compile(
        r"\bvacant\b|\brented\b|\btenanted\b|\bempty\b|\beither\b|\bwith\s+(?:a\s+)?tenants?\b|\bkhaa?li\b|\bkiraye\s+par\b"
        r"|خالي|خالية|شاغر|شاغرة|مؤجر|مؤجرة|خالی|کرائے\s+پر|खाली|ख़ाली|किराए\s+पर",
        re.IGNORECASE,
    ),
    PURPOSE: re.compile(_ASKS_ABOUT[PURPOSE].pattern + r"|\brent\s+(?:it\s+)?out\b|\bto\s+live\b", re.IGNORECASE),
}


def answered(texts) -> set:
    """The buyer's questions their words answer (_ANSWERS), in sentences that ask nothing."""
    found = set()
    for text in texts or ():
        for sentence in filters.split_sentences(str(text or "")):
            if not rules.asks_question(sentence):
                found |= {key for key, pattern in _ANSWERS.items() if pattern.search(sentence)}
    return found


def ask_next(
    reply: str, facts: dict, unit: str, language: str, texts=(), *, cut_known: bool = False, progressed: bool = False,
) -> tuple[str, bool]:
    """The reply with the questions SALE STEP names (next_questions), in code's words (next_question_line), where its own
    questions or offered times ask none of them (the brief's order: a later question waits for these): those go, its
    statements stay; and where it asks nothing after code cut its only question as one the chat knows (``cut_known``), or
    after they answered a question this turn (``progressed``). ``facts`` holds what their words answered this turn too
    (answered), so nothing they just said is asked again. Untouched while no question is left or they refuse to answer.
    (reply, changed)."""
    keys = next_questions(facts, unit)
    if not keys or refuses(texts):
        return str(reply or "").strip(), False
    sentences = filters.split_sentences(reply)
    offering = [
        sentence for sentence in sentences
        if rules.asks_question(sentence) or asks_when_to_meet(sentence) or (filters.offers_time(sentence) and not offers.states_hours(sentence))
    ]
    if any(asked_keys(sentence) & set(keys) for sentence in offering if rules.asks_question(sentence)):
        return str(reply or "").strip(), False
    if not offering and not (cut_known or progressed):
        return str(reply or "").strip(), False
    kept = [sentence for sentence in sentences if sentence not in offering]
    return " ".join([*kept, next_question_line(language, keys)]).strip(), True


# A buyer who asks to come to the office now ("I prefer to visit your office"), never one who cannot ("I can't come").
_CANNOT_COME = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|won'?t|unable\s+to|not\s+able\s+to|do\s*n'?t\s+want\s+to|no\s+time\s+to)\s+(?:\w+\s+){0,2}?(?:come|visit|meet|travel)\b"
    r"|لا\s+أستطيع|نہیں\s+آ\s+سکتا|नहीं\s+आ\s+सकता",
    re.IGNORECASE,
)


def asks_to_meet(said: str) -> bool:
    """Their words ask for the meeting now: to book ("just tell me the price and book"), or to come to the office."""
    return asks_to_book(said) or (wants_office(said) and not _CANNOT_COME.search(_flat(said)))


# "Just tell me the price and book" (brief Part 5B: the price, then the booking; the agent collects the rest on the call).
_BOOK = re.compile(
    r"\bbook(?:ing)?\b|\bschedul\w*|\b(?:arrange|set\s+up|fix|organi[sz]e)\s+(?:a|the|an|my)\s+(?:call|meeting|time|slot|appointment|visit|viewing)\b"
    r"|\bappointment\b|\breserve\s+(?:a|the|my)\s+(?:slot|time)\b|\bbook\s+kar\w*|احجز|حجز|موعد|بک\s+کر|بکنگ|बुक|बुकिंग",
    re.IGNORECASE,
)
_BOOKED = re.compile(r"\b(?:already|have|has|had)\s+(?:\w+\s+)?booked\b|\bbooked\s+(?:already|it)\b", re.IGNORECASE)


def asks_to_book(said: str) -> bool:
    """Their words ask us to book ("book", "schedule a call", "an appointment"), never "I already booked"."""
    words = _flat(said)
    return bool(_BOOK.search(words)) and not _BOOKED.search(words)


def book_now(reply: str, line: str) -> tuple[str, bool]:
    """A buyer who asked to book: the reply's questions and offered times go, code's two free slots (``line``) close it.
    (reply, changed)."""
    if not line:
        return str(reply or "").strip(), False
    sentences = filters.split_sentences(reply)
    kept = [
        sentence for sentence in sentences
        if not (rules.asks_question(sentence) or asks_when_to_meet(sentence) or (filters.offers_time(sentence) and not offers.states_hours(sentence)))
    ]
    return " ".join([*kept, line]).strip(), True


# The price ---------------------------------------------------------------------------------------------------------

_PRICE_ASK = re.compile(
    r"\b(?:price|prices|pricing|priced|cost|costs|costing|how\s+much|rate|rates|value|valuation|kitna|kitne|kitni|qeemat|keemat|qimat|daam)\b"
    r"|سعر|أسعار|اسعار|بكم|كم\s+(?:السعر|سعر|يكلف|ثمن)|قیمت|کتنے|کتنا|کتنی|कीमत|क़ीमत|कितने|कितना|कितनी|दाम",
    re.IGNORECASE,
)
_COMMISSION_ASK = re.compile(r"\bcomm?iss?ions?\b|\bagency\s+fees?\b|\bbrokerage\b|عمولة|کمیشن|कमीशन", re.IGNORECASE)
_PRICE_NOUN = re.compile(r"\b(?:price|prices|pricing|cost|rate|value|qeemat|keemat|qimat|daam)\b|سعر|أسعار|قیمت|कीमत|दाम", re.IGNORECASE)
# A fee the brief hands to the sales agent: never answered with a band (handover_topic).
_FEE_ASK = re.compile(r"\bDLD\b|\btransfer\s+fees?\b|\btrustee\b|\bregistration\s+fees?\b|\bservice\s+charges?\b", re.IGNORECASE)


def asks_price(texts) -> bool:
    """Their words ask the price ("how much?", "price?", "kitne ka hai", "كم السعر", "कीमत"): never commission alone, nor
    a DLD or transfer fee (handed over)."""
    for text in texts or ():
        words = _flat(text)
        if not _PRICE_ASK.search(words) or _FEE_ASK.search(words):
            continue
        if _COMMISSION_ASK.search(words) and not _PRICE_NOUN.search(words):
            continue
        return True
    return False


def _band(unit: str, clusters=(), facts: dict | None = None) -> tuple[int, int] | None:
    """(from, to) of a unit's sale band (residential.sale_band: a studio in Morocco Cluster has its own), when it is sound."""
    band = residential.sale_band(unit, clusters, facts)
    try:
        low, high = int(band["from"]), int(band["to"])
    except (KeyError, TypeError, ValueError):
        return None
    return (low, high) if 0 < low <= high else None


def bands(facts: dict | None = None) -> dict:
    """The sale bands of the residential facts (the settings', key by key over the defaults), by name: "studio",
    "studio_morocco", "one_br" (spec §2.2, Q27)."""
    found = {
        "studio": _band(STUDIO, (), facts),
        "studio_morocco": _band(STUDIO, ("Morocco",), facts),
        "one_br": _band(ONE_BR, (), facts),
    }
    return {key: band for key, band in found.items() if band}


def band_numbers(unit: str, clusters=(), facts: dict | None = None) -> set:
    """Every figure of the bands their unit may hear (a studio's with Morocco Cluster's, a one-bedroom's; both units' while
    it is unknown)."""
    found = bands(facts)
    keys = {STUDIO: ("studio", "studio_morocco"), ONE_BR: ("one_br",)}.get(unit, ("studio", "studio_morocco", "one_br"))
    return {value for key in keys if key in found for value in found[key]}


def priced(reply: str, unit: str, clusters=(), facts: dict | None = None) -> bool:
    """The reply names a figure of their unit's sale band, in any form ("330K", "AED 330,000", "3.3 lakh")."""
    numbers = band_numbers(unit, clusters, facts)
    return any(value in numbers for value, _ in filters.numbers_in(reply or ""))


def priced_before(earlier, unit: str, clusters=(), facts: dict | None = None) -> bool:
    """Our side gave their unit's sale band already in this chat."""
    return any(author in ("assistant", "agent") and priced(text, unit, clusters, facts) for author, text in earlier or ())


PRICE_LINES = {
    "en": {
        "studio": "Studios in International City are generally around AED {lo}–{hi}, depending on the cluster and whether the unit is vacant or rented.",
        "morocco_tail": "In Morocco Cluster, they start from around AED {lo}.",
        "studio_morocco": "Studios in Morocco Cluster are generally around AED {lo}–{hi}, depending on whether the unit is vacant or rented.",
        "one_br": "One-bedrooms in International City are generally around AED {lo}–{hi}, depending on the cluster, whether the unit is vacant or rented, and the balcony.",
        "both": "Studios in International City are generally around AED {s_lo}–{s_hi} (from around AED {m_lo} in Morocco Cluster), and one-bedrooms around AED {b_lo}–{b_hi}.",
    },
    "ar": {
        "studio": "تتراوح أسعار الاستوديوهات في المدينة العالمية عادةً بين {lo} و {hi} درهم تقريباً، حسب الكلستر وما إذا كانت الوحدة شاغرة أو مؤجرة.",
        "morocco_tail": "وفي كلستر المغرب تبدأ من حوالي {lo} درهم.",
        "studio_morocco": "تتراوح أسعار الاستوديوهات في كلستر المغرب عادةً بين {lo} و {hi} درهم تقريباً، حسب ما إذا كانت الوحدة شاغرة أو مؤجرة.",
        "one_br": "تتراوح أسعار الشقق بغرفة نوم واحدة في المدينة العالمية عادةً بين {lo} و {hi} درهم تقريباً، حسب الكلستر وما إذا كانت الوحدة شاغرة أو مؤجرة ووجود الشرفة.",
        "both": "تتراوح أسعار الاستوديوهات في المدينة العالمية عادةً بين {s_lo} و {s_hi} درهم تقريباً (ومن حوالي {m_lo} درهم في كلستر المغرب)، والشقق بغرفة نوم واحدة بين {b_lo} و {b_hi} درهم تقريباً.",
    },
    "ur_latin": {
        "studio": "International City mein studios aam tor par taqreeban AED {lo}–{hi} ke hote hain, cluster aur is baat par ke unit khali hai ya kiraye par.",
        "morocco_tail": "Morocco Cluster mein yeh taqreeban AED {lo} se shuru hote hain.",
        "studio_morocco": "Morocco Cluster mein studios aam tor par taqreeban AED {lo}–{hi} ke hote hain, is baat par ke unit khali hai ya kiraye par.",
        "one_br": "International City mein one-bedroom aam tor par taqreeban AED {lo}–{hi} ke hote hain, cluster, unit ke khali ya kiraye par hone aur balcony par.",
        "both": "International City mein studios aam tor par taqreeban AED {s_lo}–{s_hi} ke hote hain (Morocco Cluster mein taqreeban AED {m_lo} se), aur one-bedroom taqreeban AED {b_lo}–{b_hi} ke.",
    },
    "ur": {
        "studio": "انٹرنیشنل سٹی میں اسٹوڈیو عام طور پر تقریباً AED {lo}–{hi} کے ہوتے ہیں، کلسٹر اور اس بات پر کہ یونٹ خالی ہے یا کرائے پر۔",
        "morocco_tail": "مراکش کلسٹر میں یہ تقریباً AED {lo} سے شروع ہوتے ہیں۔",
        "studio_morocco": "مراکش کلسٹر میں اسٹوڈیو عام طور پر تقریباً AED {lo}–{hi} کے ہوتے ہیں، اس بات پر کہ یونٹ خالی ہے یا کرائے پر۔",
        "one_br": "انٹرنیشنل سٹی میں ون بیڈروم عام طور پر تقریباً AED {lo}–{hi} کے ہوتے ہیں، کلسٹر، یونٹ کے خالی یا کرائے پر ہونے اور بالکونی پر۔",
        "both": "انٹرنیشنل سٹی میں اسٹوڈیو عام طور پر تقریباً AED {s_lo}–{s_hi} کے ہوتے ہیں (مراکش کلسٹر میں تقریباً AED {m_lo} سے)، اور ون بیڈروم تقریباً AED {b_lo}–{b_hi} کے۔",
    },
    "hi_latin": {
        "studio": "International City mein studios aam taur par lagbhag AED {lo}–{hi} ke hote hain, cluster aur is par ki unit khaali hai ya kiraye par.",
        "morocco_tail": "Morocco Cluster mein yeh lagbhag AED {lo} se shuru hote hain.",
        "studio_morocco": "Morocco Cluster mein studios aam taur par lagbhag AED {lo}–{hi} ke hote hain, is par ki unit khaali hai ya kiraye par.",
        "one_br": "International City mein one-bedroom aam taur par lagbhag AED {lo}–{hi} ke hote hain, cluster, unit ke khaali ya kiraye par hone aur balcony par.",
        "both": "International City mein studios aam taur par lagbhag AED {s_lo}–{s_hi} ke hote hain (Morocco Cluster mein lagbhag AED {m_lo} se), aur one-bedroom lagbhag AED {b_lo}–{b_hi} ke.",
    },
    "hi": {
        "studio": "इंटरनेशनल सिटी में स्टूडियो आम तौर पर लगभग AED {lo}–{hi} के होते हैं, क्लस्टर और इस पर कि यूनिट ख़ाली है या किराए पर।",
        "morocco_tail": "मोरक्को क्लस्टर में ये लगभग AED {lo} से शुरू होते हैं।",
        "studio_morocco": "मोरक्को क्लस्टर में स्टूडियो आम तौर पर लगभग AED {lo}–{hi} के होते हैं, इस पर कि यूनिट ख़ाली है या किराए पर।",
        "one_br": "इंटरनेशनल सिटी में वन-बेडरूम आम तौर पर लगभग AED {lo}–{hi} के होते हैं, क्लस्टर, यूनिट के ख़ाली या किराए पर होने और बालकनी पर।",
        "both": "इंटरनेशनल सिटी में स्टूडियो आम तौर पर लगभग AED {s_lo}–{s_hi} के होते हैं (मोरक्को क्लस्टर में लगभग AED {m_lo} से), और वन-बेडरूम लगभग AED {b_lo}–{b_hi} के।",
    },
}


def _aed(value: int) -> str:
    return f"{int(value):,}"


def price_line(language: str, unit: str, clusters=(), facts: dict | None = None) -> str:
    """The sale band of their unit, in their language (brief Part 5B message 4): a studio's (with Morocco Cluster's lower
    start, or Morocco's own band when that is their cluster), a one-bedroom's, or both while the unit is unknown."""
    lines = PRICE_LINES[_lang(language)]
    found = bands(facts)
    morocco = "Morocco" in tuple(clusters or ())
    studio, studio_m, one_br = found.get("studio"), found.get("studio_morocco"), found.get("one_br")
    if unit == STUDIO and morocco and studio_m:
        return lines["studio_morocco"].format(lo=_aed(studio_m[0]), hi=_aed(studio_m[1]))
    if unit == STUDIO and studio:
        text = lines["studio"].format(lo=_aed(studio[0]), hi=_aed(studio[1]))
        if studio_m and studio_m[0] < studio[0] and not clusters:
            text = f"{text} {lines['morocco_tail'].format(lo=_aed(studio_m[0]))}"
        return text
    if unit == ONE_BR and one_br:
        return lines["one_br"].format(lo=_aed(one_br[0]), hi=_aed(one_br[1]))
    if studio and one_br:
        m_lo = studio_m[0] if studio_m else studio[0]
        return lines["both"].format(s_lo=_aed(studio[0]), s_hi=_aed(studio[1]), m_lo=_aed(m_lo), b_lo=_aed(one_br[0]), b_hi=_aed(one_br[1]))
    return ""


def known_amounts(unit: str, clusters=(), facts: dict | None = None) -> str:
    """The figures a buyer's reply may carry (the reply filter's known amounts on the sale track): their unit's sale bands
    only (residential.known_amounts' sale part)."""
    return " ".join(str(value) for value in sorted(band_numbers(unit, clusters, facts)))


# To a person ---------------------------------------------------------------------------------------------------------

# A question about the mortgage itself (its process, a bank, eligibility), never "mortgage" as their answer to cash or finance.
_ASKING = re.compile(
    r"[?؟]|\b(?:how|process|procedure|eligib\w*|which\s+bank|can\s+i\s+get|could\s+i\s+get|do\s+you\s+(?:help|arrange|assist|provide)"
    r"|help\s+(?:me\s+)?(?:with|get)|explain|requirements?|kaise|batao|bataiye)\b|كيف|هل|ممكن|کیسے|بتائیں|कैसे|बताइए",
    re.IGNORECASE,
)
_NEGOTIATE = re.compile(
    r"\bnegotia\w*|\bdiscount\w*|\b(?:best|last|final|lowest)\s+price\b|\b(?:lower|reduce|drop)\s+(?:the\s+)?price\b|\bbargain\w*"
    r"|\bmy\s+offer\b|\bmake\s+(?:an?\s+)?offer\b|\bcounter[\s-]?offer\b|\boffer\s+(?:of\s+)?(?:aed\s*)?\d|\b(?:can|could|would)\s+(?:you|the\s+owner|owner)\s+(?:do|accept|take|give)\s+(?:it\s+(?:for|at)\s+)?(?:aed\s*)?\d"
    r"|\b(?:aed\s*)?\d{2,3}(?:,\d{3}|k)\s+(?:final|last|ok|okay)\b|\bkam\s+(?:karo|kar\s+do|ho\s+sakta)\b|\brate\s+kam\b"
    r"|خصم|تخفيض|آخر\s+سعر|اخر\s+سعر|أفضل\s+سعر|تفاوض|ڈسکاؤنٹ|رعایت|آخری\s+قیمت|کم\s+کر|डिस्काउंट|आख़िरी\s+कीमत|आखिरी\s+कीमत|मोलभाव|कम\s+कर",
    re.IGNORECASE,
)
_MORTGAGE = re.compile(
    r"\bmortgage\w*|\bhome\s+loan\b|\bbank\s+(?:loan|finance|financing)\b|\bpre-?approval\b|\binterest\s+rates?\b|\bdown\s*payment\b|\bfinance\s+(?:process|approval)\b"
    r"|رهن|قرض\s+عقاري|تمويل\s+عقاري|الدفعة\s+الأولى|مارٹگیج|ہوم\s+لون|بینک\s+لون|मॉर्गेज|होम\s+लोन|बैंक\s+लोन",
    re.IGNORECASE,
)
_DLD = re.compile(
    r"\bDLD\b|\bland\s+department\b|\btransfer\s+fees?\b|\btrustee\s+fees?\b|\bregistration\s+fees?\b|\boqood\b|\btitle\s+deed\b|\b4\s*%\s*(?:fee|transfer)?"
    r"|دائرة\s+الأراضي|رسوم\s+(?:التسجيل|النقل|التحويل)|سند\s+الملكية|ڈی\s+ایل\s+ڈی|ٹرانسفر\s+فیس|ट्रांसफर\s+फीस|डीएलडी",
    re.IGNORECASE,
)
_LEGAL = re.compile(
    r"\blegal\w*|\blawyer\w*|\bsolicitor\b|\bconveyanc\w*|\bSPA\b|\bMOU\b|\bform\s+[FA]\b|\bgolden\s+visa\b|\binvestor\s+visa\b|\bresidency\s+visa\b|\bproperty\s+visa\b"
    r"|\bvisa\b[^.?!]{0,30}\b(?:buy|property|invest\w*)|\b(?:buy|property|invest\w*)\b[^.?!]{0,30}\bvisa\b|\bfreehold\b|\bownership\s+(?:rights|for)\b|\bcontract\s+(?:terms|clauses?|review)\b"
    r"|قانوني|محامي|تأشيرة|إقامة\s+ذهبية|التأشيرة\s+الذهبية|گولڈن\s+ویزا|ویزا|قانونی|वकील|गोल्डन\s+वीज़ा|वीज़ा|वीजा",
    re.IGNORECASE,
)


def handover_topic(texts) -> str:
    """The handover reason their words call for on the sale track (brief Part 5B, sales handover), '' for none: an offer, a
    discount or another negotiation (price_or_details_insisted); the mortgage process asked about, DLD or transfer fees, a
    legal or visa question (legal_visa_licence_contract). "Mortgage" as their answer to cash or finance is none."""
    words = " ".join(_flat(text) for text in texts or () if str(text or "").strip())
    if not words:
        return ""
    if _NEGOTIATE.search(words):
        return REASON_PRICE
    if _DLD.search(words) or _LEGAL.search(words):
        return REASON_LEGAL
    if _MORTGAGE.search(words) and _ASKING.search(words):
        return REASON_LEGAL
    return ""


# The office or a call ------------------------------------------------------------------------------------------------

_OFFICE = re.compile(
    r"\b(?:office|daftar|in\s+person|come\s+(?:to|by|over)|visit|meet\s+(?:you|in\s+person|at)|face\s+to\s+face)\b|\boffice\s+(?:aa|aana|aaunga|aa\s+jaunga)"
    r"|مكتب|زيارة|أزوركم|ازوركم|آفس|دفتر|ملاقات|ऑफ़िस|ऑफिस|दफ्तर|मिलने",
    re.IGNORECASE,
)
_CALL = re.compile(r"\b(?:call|calls|calling|phone|ring)\b|اتصال|مكالمة|کال|فون|कॉल|फ़ोन|फोन", re.IGNORECASE)


def wants_office(said: str) -> bool:
    """They asked to meet at our office rather than on a call: office slots go, from the office's own pool."""
    words = _flat(said)
    return bool(_OFFICE.search(words)) and not _CALL.search(words)


def asks_media(said: str) -> bool:
    """Photos or a video asked for, in their typed words (shop_flow.asks_media): a buyer gets none first (§3.2)."""
    return shop_flow.asks_media(shop_flow.typed_words(said))


def abroad(handover: dict, answer: dict) -> bool:
    """The model read a buyer abroad who cannot visit (its abroad_cannot_visit, kept or taken off by 2d's untag_need):
    they get the call (spec §3.1), never that handover."""
    return "abroad_cannot_visit" in ((handover or {}).get("reason"), answer.get("need_dropped"))


# The lines --------------------------------------------------------------------------------------------------------

BUYER_MEDIA_LINE = {
    "en": "Sure! To show you the best options for your budget, our sales team will do a quick 5-minute call with you first, so we share the right units instead of sending everything.",
    "ar": "بالتأكيد! لنعرض عليك أفضل الخيارات ضمن ميزانيتك، سيجري فريق المبيعات لدينا مكالمة سريعة معك مدتها 5 دقائق أولاً، حتى نشاركك الوحدات المناسبة بدلاً من إرسال كل شيء.",
    "ur_latin": "Zaroor! Aap ke budget ke mutabiq behtareen options dikhane ke liye hamari sales team pehle aap ke saath 5 minute ki ek mukhtasar call karegi, taake hum sab kuch bhejne ke bajaye sahi units share karein.",
    "ur": "ضرور! آپ کے بجٹ کے مطابق بہترین آپشنز دکھانے کے لیے ہماری سیلز ٹیم پہلے آپ کے ساتھ 5 منٹ کی ایک مختصر کال کرے گی، تاکہ ہم سب کچھ بھیجنے کے بجائے صحیح یونٹس شیئر کریں۔",
    "hi_latin": "Zaroor! Aapke budget ke hisaab se best options dikhane ke liye hamari sales team pehle aapke saath 5 minute ki ek chhoti si call karegi, taaki hum sab kuch bhejne ke bajaye sahi units share karein.",
    "hi": "ज़रूर! आपके बजट के हिसाब से सबसे अच्छे विकल्प दिखाने के लिए हमारी सेल्स टीम पहले आपके साथ 5 मिनट की एक छोटी सी कॉल करेगी, ताकि हम सब कुछ भेजने के बजाय सही यूनिट्स शेयर करें।",
}
CALL_OFFER_LINE = {
    "en": "The best next step is a quick 5-minute call with our sales team, so we can understand exactly what you need and get you the best deal. Or you're welcome to visit our office in Russia Cluster.",
    "ar": "أفضل خطوة تالية هي مكالمة سريعة مدتها 5 دقائق مع فريق المبيعات لدينا، لنفهم بالضبط ما تحتاجه ونحصل لك على أفضل صفقة. أو يسعدنا أن تزور مكتبنا في كلستر روسيا.",
    "ur_latin": "Agla behtareen qadam hamari sales team ke saath 5 minute ki ek mukhtasar call hai, taake hum samajh sakein ke aap ko kya chahiye aur aap ko best deal dila sakein. Ya aap Russia Cluster mein hamare office bhi tashreef la sakte hain.",
    "ur": "اگلا بہترین قدم ہماری سیلز ٹیم کے ساتھ 5 منٹ کی ایک مختصر کال ہے، تاکہ ہم سمجھ سکیں کہ آپ کو کیا چاہیے اور آپ کو بہترین ڈیل دلا سکیں۔ یا آپ رشیا کلسٹر میں ہمارے آفس بھی تشریف لا سکتے ہیں۔",
    "hi_latin": "Agla best step hamari sales team ke saath 5 minute ki ek chhoti si call hai, taaki hum samajh sakein ki aapko kya chahiye aur aapko best deal dila sakein. Ya aap Russia Cluster mein hamare office bhi aa sakte hain.",
    "hi": "अगला सबसे अच्छा कदम हमारी सेल्स टीम के साथ 5 मिनट की एक छोटी सी कॉल है, ताकि हम समझ सकें कि आपको क्या चाहिए और आपको सबसे अच्छी डील दिला सकें। या आप रशिया क्लस्टर में हमारे ऑफ़िस भी आ सकते हैं।",
}
# A buyer abroad, who cannot come to the office: the call alone (spec §3.1), never the office.
ABROAD_LINE = {
    "en": "No problem! The best next step is a quick 5-minute call with our sales team, so we can understand exactly what you need and get you the best deal.",
    "ar": "لا مشكلة! أفضل خطوة تالية هي مكالمة سريعة مدتها 5 دقائق مع فريق المبيعات لدينا، لنفهم بالضبط ما تحتاجه ونحصل لك على أفضل صفقة.",
    "ur_latin": "Koi masla nahi! Agla behtareen qadam hamari sales team ke saath 5 minute ki ek mukhtasar call hai, taake hum samajh sakein ke aap ko kya chahiye aur aap ko best deal dila sakein.",
    "ur": "کوئی مسئلہ نہیں! اگلا بہترین قدم ہماری سیلز ٹیم کے ساتھ 5 منٹ کی ایک مختصر کال ہے، تاکہ ہم سمجھ سکیں کہ آپ کو کیا چاہیے اور آپ کو بہترین ڈیل دلا سکیں۔",
    "hi_latin": "Koi dikkat nahi! Agla best step hamari sales team ke saath 5 minute ki ek chhoti si call hai, taaki hum samajh sakein ki aapko kya chahiye aur aapko best deal dila sakein.",
    "hi": "कोई दिक्कत नहीं! अगला सबसे अच्छा कदम हमारी सेल्स टीम के साथ 5 मिनट की एक छोटी सी कॉल है, ताकि हम समझ सकें कि आपको क्या चाहिए और आपको सबसे अच्छी डील दिला सकें।",
}
# A call they asked for themselves, with no time yet: before the two free call slots.
CALL_YES_LINE = {
    "en": "Sure, our sales team can do a quick 5-minute call with you.",
    "ar": "بالتأكيد، يمكن لفريق المبيعات لدينا إجراء مكالمة سريعة معك مدتها 5 دقائق.",
    "ur_latin": "Zaroor, hamari sales team aap ke saath 5 minute ki ek mukhtasar call kar sakti hai.",
    "ur": "ضرور، ہماری سیلز ٹیم آپ کے ساتھ 5 منٹ کی ایک مختصر کال کر سکتی ہے۔",
    "hi_latin": "Zaroor, hamari sales team aapke saath 5 minute ki ek chhoti si call kar sakti hai.",
    "hi": "ज़रूर, हमारी सेल्स टीम आपके साथ 5 मिनट की एक छोटी सी कॉल कर सकती है।",
}
# The two free call slots (the model's open "when" or its own times become these).
CALL_SLOTS_LINE = {
    "en": "I can book the call for you {slots} — which is better?",
    "ar": "يمكنني حجز المكالمة لك {slots} — أيهما أنسب لك؟",
    "ur_latin": "Main aap ke liye call {slots} book kar sakta hoon — kaunsa waqt behtar rahega?",
    "ur": "میں آپ کے لیے کال {slots} بک کر سکتا ہوں — کون سا وقت بہتر رہے گا؟",
    "hi_latin": "Main aapke liye call {slots} book kar sakta hoon — kaunsa time behtar rahega?",
    "hi": "मैं आपके लिए कॉल {slots} बुक कर सकता हूँ — कौन सा समय बेहतर रहेगा?",
}
# The two free office slots for a buyer who asked for the office.
OFFICE_SLOTS_LINE = {
    "en": "I can hold a meeting at our office for you {slots} — which is better?",
    "ar": "يمكنني حجز موعد لك في مكتبنا {slots} — أيهما أنسب لك؟",
    "ur_latin": "Main aap ke liye hamare office mein {slots} ki meeting rakh sakta hoon — kaunsa waqt behtar rahega?",
    "ur": "میں آپ کے لیے ہمارے آفس میں {slots} کی میٹنگ رکھ سکتا ہوں — کون سا وقت بہتر رہے گا؟",
    "hi_latin": "Main aapke liye hamare office mein {slots} ki meeting rakh sakta hoon — kaunsa time behtar rahega?",
    "hi": "मैं आपके लिए हमारे ऑफ़िस में {slots} की मीटिंग रख सकता हूँ — कौन सा समय बेहतर रहेगा?",
}
# The same two call slots asked about again (a plain "Yes" to them picks neither): in other words, never the same sentence.
CALL_AGAIN_LINE = {
    "en": "Which time suits you better for the call: {slots}?",
    "ar": "أي وقت يناسبك أكثر للمكالمة: {slots}؟",
    "ur_latin": "Call ke liye aap ko kaunsa waqt behtar rahega: {slots}?",
    "ur": "کال کے لیے آپ کو کون سا وقت بہتر رہے گا: {slots}؟",
    "hi_latin": "Call ke liye aapko kaunsa time behtar rahega: {slots}?",
    "hi": "कॉल के लिए आपको कौन सा समय बेहतर रहेगा: {slots}?",
}
CALL_TAKEN_LINE = {
    "en": "Sorry, that time is already booked for another call.",
    "ar": "عذراً، هذا الوقت محجوز لمكالمة أخرى.",
    "ur_latin": "Maazrat, yeh waqt kisi aur call ke liye book hai.",
    "ur": "معذرت، یہ وقت کسی اور کال کے لیے بک ہے۔",
    "hi_latin": "Maafi, yeh time kisi aur call ke liye book hai.",
    "hi": "माफ़ी, यह समय किसी और कॉल के लिए बुक है।",
}
# Q33 open (spec §2.4): a buyer's commission question gets the rent flow's res_commission_sale (residential.LINES).
COMMISSION_LINE = residential.LINES["res_commission_sale"]
ALL_LINES = frozenset(
    line
    for table in (BUYER_MEDIA_LINE, CALL_OFFER_LINE, ABROAD_LINE, CALL_YES_LINE, CALL_TAKEN_LINE, COMMISSION_LINE)
    for line in table.values()
)


def commission_line(language: str) -> str:
    """res_commission_sale (Q33 open): what a buyer hears for any commission question."""
    return residential.line("res_commission_sale", _lang(language))


def slots_line(language: str, slots, now, *, office: bool = False, again: bool = False) -> str:
    """The two free slots, of a call (or of an office meeting), in the customer's language; '' when none is free. ``again``:
    the two our message offered, asked about again in other words."""
    if not slots:
        return ""
    table = CALL_AGAIN_LINE if again and not office else OFFICE_SLOTS_LINE if office else CALL_SLOTS_LINE
    lang = _lang(language)
    return table[lang].format(slots=shops.slots_phrase(list(slots), now, lang))


def is_fixed_line(sentence: str) -> bool:
    """One of the sale track's fixed lines (or one of their sentences): said again whenever it fits."""
    key = " ".join(str(sentence or "").split())
    if not key:
        return False
    return key in ALL_LINES or any(key in filters.split_sentences(line) for line in ALL_LINES)


def text(spec: dict, language: str, now) -> str:
    """The words of a sale step code writes (``answer["sale"]``), in the language code writes in."""
    lang = _lang(language)
    kind = (spec or {}).get("kind")
    slots = list((spec or {}).get("slots") or [])
    office = bool((spec or {}).get("office"))
    again = bool((spec or {}).get("again"))
    price = str((spec or {}).get("price") or "")
    offer = slots_line(lang, slots, now, office=office, again=again) if slots else ""
    if kind == BUYER_MEDIA:
        parts = [price, BUYER_MEDIA_LINE[lang], offer]
    elif kind == ABROAD:
        parts = [price, ABROAD_LINE[lang], offer]
    elif kind == CALL_SLOTS:
        parts = [price, offer] if again else [price, CALL_YES_LINE[lang], offer]
    elif kind == CALL_TAKEN:
        parts = [CALL_TAKEN_LINE[lang], offer]
    elif kind == HANDOVER:
        parts = [residential.handover_line(lang, residential.SALE)]
    elif kind == FULL_NAME:
        parts = [residential.line("res_full_name", lang)]
    else:
        parts = []
    return " ".join(part for part in parts if part).strip()


# What the chat keeps ------------------------------------------------------------------------------------------------


def record_need(answer: dict, known_facts: dict, unit: str = "") -> bool:
    """A buyer's want, kept as 2d keeps it (needs.py): facts.need "buy", facts.wanted ("to buy a studio"), intent buy, the
    home as the property type, never as a business; so followups.holds, the nudges and the panel note read them as before.
    True when the chat's want changed (the team's "wanted" alert follows: engine._apply)."""
    facts = answer["facts"]
    noun = {STUDIO: "studio", ONE_BR: "bedroom:1"}.get(unit, "")
    need = needs.Need(needs.BUY, noun or "apartment")
    had = needs.of(known_facts)
    merged = {**(known_facts or {}), **{key: value for key, value in facts.items() if value not in (None, "", [])}}
    # As who_they_are: written when the want is new or another one (a unit learned now), never again for a budget said later;
    # never over the want residential.record_need wrote this turn (the engine's path runs it first).
    written = facts.get(needs.NEED) == needs.BUY and bool(facts.get(needs.WANTED))
    changed = not written and (had is None or had.kind != needs.BUY or bool(noun and had.noun != noun))
    if changed:
        facts[needs.NEED] = needs.BUY
        facts[needs.WANTED] = needs.summary(need, merged)
    facts["intent"] = "buy"
    if facts.get("business_activity"):
        facts["business_activity"] = None
    if noun and not needs.is_home_type(merged.get("property_type")):
        facts["property_type"] = needs.property_words(noun)
    return bool(changed)


# The turn ---------------------------------------------------------------------------------------------------------


def plain(answer: dict, *, when=None, still_invalid: bool = False, quiet: bool = False) -> bool:
    """Nothing in the answer must go out instead of a sale step: no person on the chat, booking or time to refuse,
    opt-out, broker, fixed line (code's or settle's), taken slot."""
    return not (
        quiet or when is not None or still_invalid or answer["opt_out"] != "none" or answer.get("broker")
        or answer.get("converted") or answer.get("slot_taken") or answer.get("sale")
    )


def _code_line(answer: dict, spec: dict, *, invited: bool) -> None:
    """The answer becomes a sale line code writes (``text``): no shop step, no location, never the model's words."""
    answer["sale"] = spec
    answer["converted"] = "sale"
    answer["send"] = True
    answer["share_office_location"] = False
    answer["invited_to_meeting"] = invited
    answer.pop("shop_step", None)
    answer.pop("res_line", None)  # a residential line (residential.code_line) written before it no longer goes


def offer_call_slots(answer: dict, pair) -> None:
    """Two free call slots in code's words (CALL_SLOTS), no booking: a call held for the full name whose time went by
    (residential.name_turn)."""
    answer["appointment"] = dict(NO_TIME)
    _code_line(answer, {"kind": CALL_SLOTS, "slots": list(pair)}, invited=False)


def _only_code_commission(reply: str, line: str) -> tuple[str, bool]:
    """The reply with only code's commission line (residential.commission_answer's, ``line``): every other sentence of the
    model's that speaks of commission cut, and the line before the reply's first question when they asked. (reply, changed)."""
    sentences = filters.split_sentences(reply)
    kept = [sentence for sentence in sentences if not residential.asks_commission([sentence]) or sentence == line]
    cut = len(kept) != len(sentences)
    if line and line not in kept:
        for index, sentence in enumerate(kept):
            if rules.asks_question(sentence):
                kept.insert(index, line)
                break
        else:
            kept.append(line)
        cut = True
    return (" ".join(kept).strip() if cut else str(reply or "").strip()), cut


def _with_line(reply: str, line: str) -> str:
    """The model's words with code's line before their first question (the question stays last)."""
    sentences = filters.split_sentences(reply)
    for index, sentence in enumerate(sentences):
        if rules.asks_question(sentence):
            return " ".join([*sentences[:index], line, *sentences[index:]])
    return " ".join([*sentences, line]).strip()


_WHEN = re.compile(
    r"\b(?:when|what\s+(?:time|day|date)|which\s+(?:time|day|date)|kab|kis\s+waqt|kitne\s+baje)\b|متى|أي\s+وقت|أي\s+يوم|کب|کس\s+وقت|کتنے\s+بجے"
    r"|कब|किस\s+समय|कितने\s+बजे",
    re.IGNORECASE,
)
_MEETING = re.compile(
    r"\b(?:call|meet|meeting|visit|come|office|appointment|slot|book|booking)\b|مكالمة|اتصال|زيارة|موعد|مكتب|کال|ملاقات|آفس|کب\s+آ"
    r"|कॉल|मीटिंग|ऑफ़िस|ऑफिस",
    re.IGNORECASE,
)


def asks_when_to_meet(sentence: str) -> bool:
    """A question of ours about when they will have the call or come ("When would you like the 5-minute call?", "Which suits
    you better, and what time?"), never about when they plan to buy ("When are you planning to buy?")."""
    text = str(sentence or "")
    if not rules.asks_question(text):
        return False
    return filters.is_open_when(text) or bool(_WHEN.search(text) and _MEETING.search(text))


def offer_slots(reply: str, line: str) -> tuple[str, bool]:
    """The reply with its open "when" and its own offered times replaced by code's two slots (``line``); a second question
    goes with them (filters.offer_slots, on the sale track's times too)."""
    if not line:
        return str(reply or "").strip(), False
    sentences = filters.split_sentences(reply)
    offering = [
        sentence for sentence in sentences
        if asks_when_to_meet(sentence) or (filters.offers_time(sentence) and not offers.states_hours(sentence))
    ]
    if not offering:
        return str(reply or "").strip(), False
    kept = [sentence for sentence in sentences if sentence not in offering and not rules.asks_question(sentence)]
    return " ".join([*kept, line]).strip(), True


def settle(
    answer: dict,
    *,
    facts: dict,
    texts,
    said: str,
    earlier,
    now,
    closed_dates=(),
    office_taken=(),
    call_taken=(),
    residential_facts=None,
    unit: str = "",
    clusters=(),
    when=None,
    still_invalid: bool = False,
    quiet: bool = False,
    may_invite: bool = True,
) -> str:
    """The sale track's steps on the model's answer, in place of 2d's who_they_are (live and in the eval, with the same
    values). Returns what was done ('' for nothing).

    ``facts``: the chat's facts before this turn; ``texts``: their words in the burst (engine.need_texts); ``said``: the
    burst as one string; ``earlier``: the conversation before it, (author, text); ``office_taken`` / ``call_taken``: the
    other chats' open office visits and calls; ``unit`` / ``clusters``: the track's (tracks.decide); ``may_invite``: the
    chat may still be invited (two refusals end the offers)."""
    record_need(answer, facts, unit)
    if not plain(answer, when=when, still_invalid=still_invalid, quiet=quiet):
        return ""
    known_now = {**(facts or {}), **{key: value for key, value in answer["facts"].items() if value not in (None, "", [])}}
    # What their words in this burst answered counts too, recorded by the model or not: never asked again (ask_next).
    said_now = answered(texts)
    for key in said_now:
        if not known(known_now, key):
            known_now[key] = "said"
    # They answered one of the five this turn: the next ones follow, even after a reply of the model's that asks nothing.
    progressed = bool(said_now) or any(
        known(answer["facts"], key) and answer["facts"].get(key) != (facts or {}).get(key) for key in QUESTIONS
    )
    language = answer["language"]
    topic = handover_topic(texts)
    if topic or answer["handover"]["needed"]:
        # Negotiation, an offer, the mortgage process, DLD fees, a legal question: our sales team (brief Part 5B). A handover
        # the model kept (a person or a complaint asked for) gets the same line: our team replies here.
        answer["handover"] = {"needed": True, "reason": answer["handover"]["reason"] if answer["handover"]["needed"] else topic}
        _code_line(answer, {"kind": HANDOVER}, invited=False)
        return f"{HANDOVER}:{answer['handover']['reason']}"
    asked_price = asks_price(texts)
    price = price_line(language, unit, clusters, residential_facts) if asked_price else ""
    office = wants_office(said)
    pair = []
    if may_invite:
        pair = calls.offer(now, closed_dates, office_taken if office else call_taken)
    if answer.pop("abroad_call", False):
        # A buyer abroad gets the call (spec §3.1), never 2d's abroad_cannot_visit handover.
        _code_line(answer, {"kind": ABROAD, "slots": pair, "price": price}, invited=bool(pair))
        return ABROAD
    if asks_media(said):
        # No media to a buyer first (§3.2): res_buyer_media and two free call slots.
        call_pair = calls.offer(now, closed_dates, call_taken) if may_invite else []
        _code_line(answer, {"kind": BUYER_MEDIA, "slots": call_pair, "price": price}, invited=bool(call_pair))
        return BUYER_MEDIA
    done = []
    reply = answer["reply"] if answer["send"] else ""
    commission = residential.commission_answer(residential.SALE, unit, earlier, texts, language=language, facts=residential_facts)
    if reply:
        reply, cut = _only_code_commission(reply, commission)
        if cut:
            done.append(COMMISSION)
        reply, dropped = drop_known_questions(reply, known_now)
        if dropped:
            done.append(KNOWN)
        line = slots_line(language, pair, now, office=office) if pair else ""
        if line and asks_to_meet(said):
            # They ask for the meeting now ("Just tell me the price and book", "I prefer to visit your office"): code's two
            # free slots, in place of the model's open "when", or else of its questions (the 2e real-model gate, round 1, asked
            # cash or finance instead, both runs of shops-sale-price-and-book); our agent asks the rest on the call.
            reply, offered = offer_slots(reply, line)
            if not offered:
                reply, offered = book_now(reply, line)
            done.append(MEETING)
            answer["invited_to_meeting"] = True
        else:
            reply, asked_next = ask_next(reply, known_now, unit, language, texts, cut_known=dropped, progressed=progressed)
            if asked_next:
                done.append(NEXT)
                answer["invited_to_meeting"] = False  # the meeting waits for the questions (brief Part 5B's order)
            elif line:
                reply, offered = offer_slots(reply, line)
                if offered:
                    done.append(MEETING)
                    answer["invited_to_meeting"] = True
        if asked_price and price and not priced(reply, unit, clusters, residential_facts):
            reply = _with_line(reply, price)
            done.append(PRICE)
    elif asked_price and price:
        reply = price
        done.append(PRICE)
    elif commission:
        reply = commission
        done.append(COMMISSION)
    if not done:
        return ""
    answer["reply"] = reply.strip()
    answer["send"] = bool(answer["reply"])
    answer["trimmed"] = [*(answer.get("trimmed") or []), *done]
    return ",".join(done)


def booking_text(
    language: str, start, *, call: bool, facts: dict, lead=None, unit: str = "", clusters=(), office_address: str = "", maps_url: str = "",
    rescheduled: bool = False,
) -> str:
    """A buyer's booking message (spec §3.3, §2.7): a call (res_call_booked) or an office meeting, under their full name
    (residential.confirmation on the sale track, as engine._run_claimed's booking_text writes it)."""
    return residential.confirmation(
        language, start, kind=residential.CALL if call else residential.VISIT, full_name=residential.full_name_known(facts, lead),
        unit=unit, clusters=clusters, office_address=office_address, maps_url=maps_url, track=residential.SALE, rescheduled=rescheduled,
    )


def mark_hold(row, answer: dict) -> None:
    """A buyer's call held while we ask the full name (residential.hold_for_name, spec §2.6): marked as the call pool's
    (calls.mark), so no other buyer takes it; residential.mark_hold writes the hold's own marks."""
    if answer.get("hold_for_name") and row.place == calls.PLACE:
        calls.mark(row)


# A buyer's call in their own words ------------------------------------------------------------------------------------

NO_TIME = {"action": "none", "place": None, "date": None, "time": None, "customer_words": None}


def _their_call(said: str, now) -> dict | None:
    """The call's day and hour in their own words ("can we do a call at 5", "call me tomorrow at 11 am"): one day (today
    when none is named) and one hour said as an hour (hours.spoken_times), as a plan (never "maybe", "if", a deferral);
    else None."""
    if hours.no_promise(said) or rules.mentions_deferral(said):
        return None
    named = hours.named_days(said, now)
    days = {day for day in named if day - dt.timedelta(days=7) not in named}
    times = hours.spoken_times(said)
    if len(times) != 1 or len(days) > 1:
        return None
    day = next(iter(days)) if days else hours.now_dubai(now).date()
    at = next(iter(times))
    return {"action": "confirm", "place": calls.PLACE, "date": f"{day:%Y-%m-%d}", "time": f"{at:%H:%M}", "customer_words": " ".join(said.split())[:255] or None}


def offered_calls(our_last: str, now, closed_dates=(), taken=()) -> list:
    """The two call slots our last message offered (code's CALL_SLOTS_LINE), while both are still free in the call pool and
    half an hour ahead; else [] (offers.offered_again reads no sentence about a call)."""
    times = sorted(hours.offered_starts(our_last or ""))
    if len(times) != 2:
        return []
    days = hours.named_days(our_last or "", now)
    day = min(days) if days else hours.now_dubai(now).date()
    starts = [dt.datetime.combine(day, at, tzinfo=hours.DUBAI) for at in times]
    if starts[1] - starts[0] < hours.MIN_GAP:
        return []
    for start in starts:
        if start < now + hours.SLOT or hours.is_taken(start, taken):
            return []
        try:
            hours.check_slot(f"{start:%Y-%m-%d}", f"{start:%H:%M}", now=now, closed_dates=closed_dates)
        except hours.SlotError:
            return []
    return starts


def unasked_call(start, *, said: str, words: str = "", our_last: str = "", ours: str = "", appointment=None, now=None) -> bool:
    """The model booked a call at a time the buyer neither gave nor took (engine.their_time: a plain "Yes" to our two call
    slots picks neither), as engine.unasked_confirm reads an office visit's: no booking, the slots asked about again."""
    from . import engine

    return not engine.their_time(start, said=said, words=words, our_last=our_last, ours=ours, appointment=appointment, now=now)


def call_step(
    answer: dict,
    when,
    *,
    appointment,
    said: str,
    words: str = "",
    our_last: str = "",
    ours: str = "",
    now,
    closed_dates=(),
    taken=(),
    still_invalid: bool = False,
    handed_over: bool = False,
    grounding=None,
) -> tuple:
    """A buyer's call, right after the model on the sale track (live and in the eval): (when, what).

    - Never 2d's call_requested handover: a buyer's call is booked here, and a buyer abroad gets the call
      (``answer["abroad_call"]``, settle's line), never abroad_cannot_visit.
    - The model's call at a time they neither gave nor took (a plain "Yes" to two call slots; engine.their_time): no
      booking, the two slots asked about again ("unasked").
    - A call asked for (their words: people.asks_for_call; or the model's call request) with their own day and hour, free
      in the call pool and in office hours: booked ("booked"); held by another buyer: the two nearest free call slots
      ("taken"); with no time, or one we cannot book: two free call slots ("slots").
    Nothing while a person has the chat, a time was refused, or they opted out."""
    from . import engine, people

    if handed_over or still_invalid or answer["opt_out"] != "none" or answer.get("broker"):
        return when, ""
    handover = answer["handover"]
    asked = people.asks_for_call(said) or people.is_call_request(answer)
    if handover["needed"] and handover["reason"] in ("call_requested", "abroad_cannot_visit"):
        answer["handover"] = {"needed": False, "reason": None}
    if abroad(handover, answer):
        answer["abroad_call"] = True  # settle's ABROAD line: the call and two free call slots
    proposal = answer["appointment"]
    if when is not None:
        if proposal.get("place") != calls.PLACE or not unasked_call(
            when, said=said, words=words, our_last=our_last, ours=ours, appointment=appointment, now=now,
        ):
            return when, ""
        answer["appointment"] = dict(NO_TIME)
        pair = offered_calls(our_last, now, closed_dates, taken) or calls.offer(now, closed_dates, taken)
        _code_line(answer, {"kind": CALL_SLOTS, "slots": pair, "again": True}, invited=False)
        return None, "unasked"
    if not asked:
        if proposal.get("place") == calls.PLACE:
            answer["appointment"] = dict(NO_TIME)  # a call is never kept tentative on the sale track: it is booked or offered
        return None, ""
    theirs = _their_call(said, now)
    if theirs is not None:
        try:
            start = engine.check_proposal(
                theirs, appointment, now, closed_dates, grounding=grounding, segment=answer["segment"], said=said,
                places=calls.PLACES, call_taken=taken,
            )
        except hours.SlotError as exc:
            if exc.code == "taken" and exc.alternatives:
                answer["appointment"] = dict(NO_TIME)
                _code_line(answer, {"kind": CALL_TAKEN, "slots": list(exc.alternatives)}, invited=False)
                return None, "taken"
        else:
            if start is not None:
                answer["appointment"] = theirs
                return start, "booked"
    answer["appointment"] = dict(NO_TIME)
    _code_line(answer, {"kind": CALL_SLOTS, "slots": calls.offer(now, closed_dates, taken)}, invited=False)
    return None, "slots"
