"""What a shops reply may say about the shops (launch review 2026-10-15, issues 5, 12 and 16; Matloob's Q24).

- Facts SHOP FACTS lacks (issue 5, ``settle``): the model told chat 96 "England cluster mein shop ka location Russia
  Cluster, Building ..., Shop 20 hai" (our office's address) and "yeh parking side par hai, front side par nahi" (his
  own wish), chat 91 "The shops are spaces ready for you to open your own restaurant or cafeteria", chat 78 "There
  are no commissions from us for tenants" and chat 59 "Rent security is usually a deposit". Code cuts every
  sentence that states a shop's building, unit, floor, street or side, that a food business (or its gas, chimney
  or exhaust) works there, that anything is for sale, or anything about the commission, the deposit or another
  cost SHOP FACTS does not give. A question of theirs on it gets the build pack's unknown line ("Good question —
  I'll have our agent confirm that for you at the viewing.") in their language, and a note for our agent. Our
  office's own address, the clusters, the drive to the shops and a deferral to our agent stay. Nor does a reply say
  our slots start only on the hour (the launch gate: "Our office slots start on the hour, so I booked you for 4:00 PM
  today."; its review: "Our slots are hourly", "We only book full hours"): they are every 30 minutes. A reply left with
  nothing else gets code's two free slots from their hour instead (engine.hourly_slots), never silence.
- Commission (Matloob, Q24, 2026-10-15): "We charge the normal commission. Please come and see the shops first,
  then we will discuss the details." in their language, for any commission question and in place of any claim
  about it; never "no commission", never a figure. Its words for a customer who wants no shop to rent say "the
  options" for "the shops", as their nudges do.
- The price (issue 12, ``price_turn``): "cheaper", "too expensive", "your rent is higher than others" got the
  discount line live (chats 100 and 59), never the cheaper Type 1. A price objection gets code's honest line
  ("our lowest is Type 1, from AED 33,000 a year (400-550 sq ft) ... Would that size work for you?"), and a
  budget below the lowest "from" price, or the objection again, says so and offers a colleague; their yes to
  the colleague hands the chat to a person.
- The size and price table said again (issue 16, ``drop_table_repeat``): chat 91 got it three times in six
  minutes. A sentence restating the figures of two types or more that our messages already gave (the list
  among them) is cut, unless they ask for the prices, sizes or the rent's period now, or name our figures
  themselves (chat 42's "Wat is 33000/year": the figures are the answer).

The defaults are module constants, each a one-line change when Matloob decides otherwise. Plain functions on
plain data: the eval (leadai_eval) calls the same ones.
"""

from __future__ import annotations

import re

from . import filters, rules, shops

# Defaults (Matloob's open decisions, synth.json decisions_for_matloob; one constant each) ------------------

# A price objection gets the honest line (our lowest type and its size, "would that size work?"); a budget
# below the lowest "from" price, or the objection again after that line, the honest line with a colleague
# offered (BELOW). A budget is read only from AED 1,000 a year (a smaller one is a misread figure).
PRICE_LINE = True
BUDGET_FLOOR = 1_000
# Their yes to the colleague offered for a budget below our lowest: handed to a person (the alert says why).
COLLEAGUE_HANDOVER = "customer_asked_human"

# What answer["trimmed"] says for each cut.
CUT = "claim"
TABLE = "table_repeat"
COMMISSION = "commission"
# The topic of a sentence that says our slots start only on the hour: they are every 30 minutes (hours.SLOT).
HOURLY = "hourly"
# The converted answer of the price line (engine: answer["price"] holds its words' spec).
PRICE = "price"

_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


# The lines ---------------------------------------------------------------------------------------------------

UNKNOWN = {
    "en": shops.UNKNOWN_LINE,
    "ar": "سؤال جيد — سأطلب من وكيلنا تأكيد ذلك لك عند المعاينة.",
    "ur_latin": "Acha sawal hai — main hamare agent se viewing par aap ke liye is ki tasdeeq karwa doon ga.",
    "ur": "اچھا سوال ہے — میں ہمارے ایجنٹ سے ویونگ پر آپ کے لیے اس کی تصدیق کروا دوں گا۔",
    "hi_latin": "Accha sawaal hai — main hamare agent se viewing par aapke liye iski pushti karwa dunga.",
    "hi": "अच्छा सवाल है — मैं हमारे एजेंट से व्यूइंग पर आपके लिए इसकी पुष्टि करवा दूँगा।",
}
# Matloob's own words (Q24), and their form for someone who wants no shop to rent ("the options").
COMMISSION_LINE = {
    "en": (
        "We charge the normal commission. Please come and see the shops first, then we will discuss the details.",
        "We charge the normal commission. Please come and see the options first, then we will discuss the details.",
    ),
    "ar": (
        "نتقاضى العمولة المعتادة. تفضل بزيارتنا ومعاينة المحلات أولاً، ثم نناقش التفاصيل.",
        "نتقاضى العمولة المعتادة. تفضل بزيارتنا ومشاهدة الخيارات أولاً، ثم نناقش التفاصيل.",
    ),
    "ur_latin": (
        "Hum normal commission lete hain. Pehle aa kar shops dekh lein, phir hum details discuss karenge.",
        "Hum normal commission lete hain. Pehle aa kar options dekh lein, phir hum details discuss karenge.",
    ),
    "ur": (
        "ہم عام کمیشن لیتے ہیں۔ پہلے آ کر دکانیں دیکھ لیں، پھر ہم تفصیلات پر بات کریں گے۔",
        "ہم عام کمیشن لیتے ہیں۔ پہلے آ کر آپشنز دیکھ لیں، پھر ہم تفصیلات پر بات کریں گے۔",
    ),
    "hi_latin": (
        "Hum normal commission lete hain. Pehle aakar shops dekh lijiye, phir hum details discuss karenge.",
        "Hum normal commission lete hain. Pehle aakar options dekh lijiye, phir hum details discuss karenge.",
    ),
    "hi": (
        "हम सामान्य कमीशन लेते हैं। पहले आकर दुकानें देख लीजिए, फिर हम डिटेल्स पर बात करेंगे।",
        "हम सामान्य कमीशन लेते हैं। पहले आकर विकल्प देख लीजिए, फिर हम डिटेल्स पर बात करेंगे।",
    ),
}


def unknown_line(language: str) -> str:
    return UNKNOWN[_lang(language)]


def commission_line(language: str, *, options: bool = False) -> str:
    return COMMISSION_LINE[_lang(language)][1 if options else 0]


def _key(text: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").casefold()).split())


_CODE_LINES = (*UNKNOWN.values(), *(line for pair in COMMISSION_LINE.values() for line in pair))
# Every fixed answer here, whole and sentence by sentence (a reply's sentences are read one at a time).
_CODE_KEYS = {_key(line) for line in _CODE_LINES} | {_key(part) for line in _CODE_LINES for part in filters.split_sentences(line)}


def is_code_line(sentence: str) -> bool:
    """One of this module's fixed answers (or one of its sentences): said again whenever the same kind of
    question comes, so the no-repeat guard keeps it, and never cut as a claim."""
    key = _key(sentence)
    return bool(key) and key in _CODE_KEYS


# What a sentence claims ---------------------------------------------------------------------------------------

# Our office or our own place: its address is ours, never a shop's.
_OUR_PLACE = re.compile(
    r"\boffice\b|\bdaftar\b|\bour\s+(?:address|location|place)\b|\b(?:we'?re|we\s+are)\s+(?:at|in|located)\b|\bfind\s+us\b|\bvisit\s+us\b"
    r"|\bham(?:ara|are|ari)\s+(?:office|daftar|pata|address|location)\b|مكتب|عنوان(?:نا)?\b|موقعنا|آفس|دفتر|ऑफ़िस|ऑफिस|दफ्तर|हमारा\s+पता",
    re.IGNORECASE,
)
# Our agent confirms or shows it: the build pack's deferral (or its drive to the shops), never a claim.
_DEFERS = re.compile(
    r"\b(?:agent|agents|specialist|colleague|team)\b[^.?!]{0,50}?\b(?:confirm|show|check|tell|share|guide|explain|answer|go\s+through|discuss|help|drive|take)"
    r"|\bat\s+the\s+(?:viewing|visit)\b|\bwhen\s+you\s+(?:visit|come)\b|\bviewing\s+(?:par|pe|mein|ke\s+waqt)\b"
    r"|\bagent\b[^.?!]{0,40}\b(?:batayenge|bata\s+denge|confirm\s+kar|dikha|tasdeeq|pushti)"
    r"|عند\s+المعاينة|وكيلنا\s+(?:سيؤكد|يؤكد|سيوضح)|ایجنٹ[^۔?؟]{0,40}(?:بتائیں|کنفرم|تصدیق|دکھا)|एजेंट[^।?]{0,40}(?:बताएँगे|कन्फ़र्म|पुष्टि|दिखा)",
    re.IGNORECASE,
)
# A question of theirs left to our agent, as the build pack's unknown line leaves it ("Good question — I'll have our
# agent confirm ..." in any of its languages, or the model's own "our agent will confirm details like ... at the
# viewing"): never the drive to the shops ("hamara agent aapko shops dikhane le jayega") or the discount line.
_ANSWERS_LATER = re.compile(
    r"\b(?:agent|agents|specialist|colleague|team)\b[^.?!]{0,60}?\b(?:confirm|check|tell|share|explain|answer)"
    r"|\bconfirm\b[^.?!]{0,60}\bat\s+the\s+(?:viewing|visit)\b"
    r"|\bagent\b[^.?!]{0,40}\b(?:batayenge|bata\s+denge|confirm\s+kar|tasdeeq|pushti)"
    r"|وكيلنا\s+(?:سيؤكد|يؤكد|سيوضح)|تأكيد[^.?!؟]{0,40}عند\s+المعاينة|ایجنٹ[^۔?؟]{0,40}(?:بتائیں|کنفرم|تصدیق)|एजेंट[^।?]{0,40}(?:बताएँगे|कन्फ़र्म|पुष्टि)",
    re.IGNORECASE,
)
# Their own wish said back to them ("Aapko England cluster mein ... shop chahiye, parking side par"), never ours.
_THEIR_WISH = re.compile(
    r"\byou(?:'re|\s+are)?\s+(?:need|want|wanted|looking|prefer|asked|mentioned|would\s+like|'d\s+like|said)\b"
    r"|\b(?:your|ur)\s+(?:need|preference|requirement|choice)\b"
    r"|\baap(?:ko|ke|ki|)\b[^.?!]{0,60}\b(?:chahiye|chaiye|chahte|chahti|chah\s+rahe|dhoond|pasand)\b"
    r"|تريد|تبحث\s+عن|تفضل|آپ\s+کو[^۔?؟]{0,60}چاہیے|آپ[^۔?؟]{0,40}چاہتے|आपको[^।?]{0,60}चाहिए|आप[^।?]{0,40}चाहते",
    re.IGNORECASE,
)
# A MATCH sentence ("For a restaurant, Type 2 is perfect: 600-800 sq ft, from AED 48,000 a year."): about size and rent.
_MATCH = re.compile(r"\btype\s*[123]\b[^.?!]{0,80}\d", re.IGNORECASE)
# Where a shop is: a building, a unit number, a floor, a side or what it faces, a street, what it is near.
_PLACE_DETAIL = re.compile(
    r"\bbuildings?\b|\bbldg\b|\bV\s?0?\d{1,2}\b|\bunit\s*(?:no\.?|number|#)\s*\d"
    r"|\bshop\s*(?:no\.?|number|#)?\s*\d{1,4}\b(?!\s*(?:-|to)?\s*\d|\s*(?:min|mins|minutes?|sq|square|ft|feet|aed|k\b|%|types?\b))"
    r"|\b(?:ground|first|second|1st|2nd|top)\s+floor\b|\bmezzanine\b"
    r"|\b(?:parking|front|back|road|main\s+road|street|corner)\s+(?:side|facing)\b|\broadside\b|\bfacing\s+(?:the\s+)?(?:parking|road|street|main)"
    r"|\bon\s+the\s+main\s+road\b|\bcorner\s+(?:shop|unit)\b|\b(?:near|next\s+to|close\s+to|opposite|behind|beside)\s+(?!our\b|the\s+office\b|us\b)(?:the\s+)?[a-z]"
    # "... Building V03 ke darmiyan", never a size between two figures ("400-550 sq ft ke darmiyan hota hai") nor a span of
    # time ("aaj 2:00 PM ya 3:00 PM ke darmiyan", "3 baje ke paas": the launch gate's eval shops-building-and-past-slot-96).
    # An am or pm only after a digit ("3pm", "3:00 PM"): "Islam ke paas", "Masjid e Imam ke paas" name a place.
    r"|(?<!ft\s)(?<!sqft\s)(?<!sqf\s)(?<!\d\sam\s)(?<!\d\spm\s)(?<!\dam\s)(?<!\dpm\s)(?<!baje\s)(?<!bje\s)(?<!:\d\d\s)"
    r"\bke\s+(?:darmiyan|beech|bich|samne|saamne|peeche|peechay|paas)\b"
    r"|\b(?:parking|front|back|road)\s+(?:side|taraf)\s+(?:par|pe|mein)\b"
    r"|مبنى|بناية|الطابق|جهة\s+(?:الباركنج|المواقف|الشارع)|عمارت|بلڈنگ|منزل\s+پر|बिल्डिंग|मंज़िल|फ्लोर",
    re.IGNORECASE,
)
_SHOP_OR_IT = re.compile(r"\bshops?\b|\bunits?\b|\bdukaa?n\w*|\bstores?\b|\b(?:it|they|yeh|ye|woh|wo|this|these)\b|محل|المحل|دکان|दुकान", re.IGNORECASE)
# A shop named outright (never "it": "It is at <our address>" may answer "Where is your office?").
_A_SHOP = re.compile(r"\bshops?\b|\bunits?\b|\bdukaa?n\w*|محل|المحل|دکان|दुकान", re.IGNORECASE)
# A food business, and what it needs.
_FOOD = re.compile(
    r"\b(?:restaurants?|caf[eé]s?|cafeteria|kitchens?|food|f\s?&\s?b|fnb|bakery|bakeries|shawarma|takeaway|take-away|catering|cooking|desserts?|sweets|juice)\b"
    r"|مطعم|مطاعم|كافيه|مقهى|مطبخ|طعام|ریسٹورنٹ|ریسٹورانٹ|کھانا|रेस्टोरेंट|खाना|किचन",
    re.IGNORECASE,
)
# A business suits these units, or may run there ("ready for you to open your own restaurant", "suitable for
# restaurants"); never the reaction to their business ("Perfect, a restaurant or cafeteria.").
_FOOD_OK = re.compile(
    r"\b(?:suitable|ideal|perfect|good|great|fit|fine|ok|okay|ready|available)\s+for\b|\b(?:allowed|permitted|approved|possible)\b"
    r"|\bno\s+(?:problem|issue)\s+(?:for|with)\b|\bcan\s+(?:open|run|start|operate|set\s+up|have)\b|\bworks?\s+(?:well\s+)?for\b"
    r"|\bfor\s+you\s+to\s+open\b|\b(?:chal|khol)\s+sakt[eai]\b"
    r"|مناسب\s+(?:ل|لـ)|مسموح|يمكنك\s+(?:فتح|تشغيل)|جاهزة\s+(?:ل|لـ)|کھول\s+سکت|चला\s+सकत|खोल\s+सकत",
    re.IGNORECASE,
)
_FOOD_FIT = re.compile(
    r"\b(?:gas(?:\s+line)?|chimn(?:e?y|eys|ies)|exhaust|ventilation|grease\s+trap|kitchen\s+hood|drainage|water\s+(?:line|supply|connection)|power\s+load|noc)\b"
    r"[^.?!]{0,40}\b(?:is|are|available|provided|there|included|installed|ready|allowed|fine|possible|exists?|comes?)\b"
    r"|\b(?:there\s+is|there\s+are|has|have|having|comes?\s+with)\b[^.?!]{0,30}\b(?:gas|chimn\w+|exhaust|grease\s+trap|ventilation|drainage)\b",
    re.IGNORECASE,
)
# A sale: these shops for sale, bought or sold (unless SHOP FACTS speaks of one).
_SALE = re.compile(
    r"\b(?:shops?|units?|it|they|these|them|this|all)\s+(?:is|are)\s+(?:also\s+)?(?:available\s+)?(?:for|on)\s+sale\b"
    r"|\b(?:available|up)\s+for\s+(?:sale|purchase)\b|\byou\s+can\s+(?:also\s+)?(?:buy|purchase|own)\s+(?:the|these|this|our|a|one)\b"
    r"|\bwe\s+(?:also\s+)?sell\s+(?:the\s+|these\s+|our\s+)?(?:shops?|units?)\b|\b(?:sale|selling|purchase)\s+price\b"
    r"|\b(?:sale|kharid\w*|khareed\w*)\s+(?:ke\s+liye\s+)?(?:bhi\s+)?(?:available|dastiyab|mil\s+sakt)"
    r"|(?:المحلات|المحل)\s+(?:متاحة\s+)?للبيع|متاحة\s+للبيع|برائے\s+فروخت|बिक्री\s+के\s+लिए\s+(?:उपलब्ध|है)",
    re.IGNORECASE,
)
_SALE_FACTS = re.compile(r"\b(?:sale|sell|selling|sold|buy|buying|purchase)\b|للبيع|بيع|فروخت|बिक्री", re.IGNORECASE)
_COMMISSION = re.compile(
    r"\bcomm?iss?ions?\b|\bagency\s+fees?\b|\bagent'?s?\s+fees?\b|\bbrokerage\b|\bbroker'?s?\s+fees?\b|عمولة|العمولة|کمیشن|कमीशन",
    re.IGNORECASE,
)
_DEPOSIT = re.compile(
    r"\bdeposits?\b|\bsecurity\s+(?:deposit|cheque|check|amount|money|fee|fees)\b|\brent\s+security\b|\bsecurity\s+(?:is|of)\b"
    r"|تأمين|وديعة|ڈپازٹ|ڈیپازٹ|सिक्योरिटी|डिपॉज़िट|डिपॉजिट",
    re.IGNORECASE,
)
# The other costs and terms SHOP FACTS does not give, stated as facts.
_OTHER = re.compile(
    r"\bservice\s+charges?\b|\bdewa\b|\bchiller\b|\bfit[\s-]?out\b|\brent[\s-]?free\b|\bgrace\s+period\b|\bvat\b|\bejari\b|\bfootfall\b"
    r"|\bmaintenance\s+(?:fee|fees|charge|charges)\b|\butilit(?:y|ies)\b|\b(?:electricity|water)\s+(?:bills?|charges?)\b"
    r"|\bparking\s+(?:is|are|space|spaces|spots?|available|free)\b|\b(?:free|ample|plenty\s+of|enough|dedicated)\s+parking\b"
    r"|\b(?:only|just)?\s*(?:\d+|one|two|three|a\s+few|few)\s+(?:units?|shops?)\s+(?:are\s+|is\s+)?(?:left|remaining)\b|\blast\s+(?:unit|shop)\b",
    re.IGNORECASE,
)
_ASSERTS = re.compile(
    r"\b(?:is|are|was|will\s+be|comes?|included|includes?|free|available|provided|extra|separate(?:ly)?|charged|covered|no|not|none|plenty"
    r"|ample|aed|percent|months?|days?|weeks?|left|remaining|hai|hain|nahi|milega|milegi)\b|\d+\s*%",
    re.IGNORECASE,
)
# Our slots said to start only on the hour, or to be hourly (the launch gate's eval shops-not-a-shop-booked: "Our office
# slots start on the hour, so I booked you for 4:00 PM today." to "4:30 PM today is fine"): they are every 30 minutes. Said
# as a fact of them too (the gate's review): "Our slots are hourly", "We only book full hours", "Viewings are only at the top
# of the hour", "4:30 is not available as our slots are on full hours only", "Hamare slots har ghante par hote hain".
_SLOT_WORDS = r"(?:slots?|viewings?|visits?|appointments?|bookings?|timings?|meetings?)"
_HOURLY = re.compile(
    r"\bon\s+the\s+hour\b|\btop\s+of\s+the\s+hour\b"
    rf"|\b(?:hourly|full[-\s]hours?|whole[-\s]hours?)\s+{_SLOT_WORDS}\b"
    rf"|\b{_SLOT_WORDS}\b[^.?!]{{0,30}}?(?:\bevery\s+(?:full\s+|whole\s+)?hour\b|\b(?:hourly|each\s+hour)\b|\b(?:full|whole)\s+hours?\b)"
    r"|\b(?:book|books|booking|take|takes|offer|offers|schedule|schedules)\s+(?:only\s+)?(?:(?:on|at|in)\s+)?(?:full|whole)\s+hours?\b"
    r"|\bonly\s+(?:on\s+|at\s+|in\s+)?(?:the\s+)?(?:full|whole)\s+hours?\b|\b(?:full|whole)\s+hours?\s+only\b"
    r"|\bhar\s+ghante\b|\bghante\s+ke\s+hisaab\b|كل\s+ساعة|على\s+رأس\s+الساعة|ہر\s+گھنٹے|हर\s+घंटे",
    re.IGNORECASE,
)
# What they asked about, read in their own words (the topic of a claim).
_ASKED = {
    "location": re.compile(
        r"\b(?:where|which|location|located|building|bldg|floor|side|facing|street|road|address|area|near|nearby|close|metro|far"
        r"|distance|kahan|kidhar|kaunsi|kon\s*si)\b|أين|وين|موقع|مبنى|قريب|کہاں|کون\s*سی|قریب|बिल्डिंग|कहाँ|कहां|पास",
        re.IGNORECASE,
    ),
    "food": re.compile(
        r"\b(?:restaurants?|caf[eé]s?|cafeteria|kitchen|food|cooking|bakery|gas|chimn\w+|exhaust|existing|allowed|permitted|approval)\b"
        r"|مطعم|مطبخ|غاز|ریسٹورنٹ|گیس|रेस्टोरेंट|गैस",
        re.IGNORECASE,
    ),
    "sale": re.compile(r"\b(?:sale|sell|selling|buy|buying|purchase|own|freehold|investment)\b|للبيع|شراء|خرید|فروخت|खरीद|बिक्री", re.IGNORECASE),
    "deposit": _DEPOSIT,
    "other": _OTHER,
}
_NOTES = {
    "location": "which building or side the shop is in",
    "food": "whether the unit suits a food business",
    "sale": "whether the shops are for sale",
    "deposit": "the security deposit",
    "other": "costs or terms not in SHOP FACTS",
}


def _question(sentence: str) -> bool:
    return any(mark in sentence for mark in filters.QUESTION_MARKS)


def _in(known: str, words) -> bool:
    """One of these words is in what we know to be true (SHOP FACTS, our campaign's own words): a fact repeated."""
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", known or "", re.IGNORECASE) for word in words if word)


def _place_words(text: str) -> list[str]:
    """The words that name where a shop is ("dragon" of "close to Dragon Mart", "V03", "parking")."""
    out = []
    for match in _PLACE_DETAIL.finditer(text):
        words = re.findall(r"[^\W\d_]+|\w*\d\w*", match.group(0))
        out.append(words[-1] if words else match.group(0))
    following = re.search(r"\b(?:near|next\s+to|close\s+to|opposite|behind|beside)\s+(?:the\s+)?([A-Za-z][\w-]*)", text, re.IGNORECASE)
    if following:
        out.append(following.group(1))
    return out


_UNIT_PART = re.compile(r"^\s*(shop|office|unit|suite)\s*(?:no\.?|number|#)?\s*(\d{1,4})\s*$", re.IGNORECASE)


def _office_unit(office: str) -> re.Pattern | None:
    """Our office's own unit, as its address names it ("Shop 20") and as a reply may write it ("Shop No. 20",
    "shop #20"): ours wherever a reply names it, never a shop for rent."""
    for part in str(office or "").split(","):
        match = _UNIT_PART.match(part)
        if match:
            return re.compile(rf"\b{match[1]}\s*(?:no\.?|number|#)?\s*{match[2]}\b", re.IGNORECASE)
    return None


def _names_ours(text: str, office: str) -> bool:
    """The sentence holds our office's address, or its own unit ("Yes, Shop 20 is open until 7:30 PM today")."""
    unit = _office_unit(office)
    return filters.carries_location(text, office) or bool(unit and unit.search(text))


def _without_address(text: str, office: str) -> str:
    """The sentence without our office's address in it (each of its parts: "Russia Cluster", "Building V03", "Shop 20")."""
    rest = text
    for part in (piece.strip() for piece in str(office or "").split(",")):
        if part:
            rest = re.sub(re.escape(part), " ", rest, flags=re.IGNORECASE)
    unit = _office_unit(office)
    if unit:
        rest = unit.sub(" ", rest)
    return " ".join(rest.split())


def topic_of(sentence: str, known: str = "", office: str = "") -> str:
    """What the sentence claims that SHOP FACTS lacks ('' for nothing): "commission", "location", "food",
    "sale", "deposit" or "other". A question claims nothing; nor do our office's own address, a deferral to
    our agent, their own wish said back, a MATCH sentence, one of the build pack's fixed lines, or what
    ``known`` says (the SHOP FACTS block and our campaign's own words: "close to Dragon Mart" when our
    campaign said so). ``office``: our office's address, which a sentence may give as ours ("Our office is
    in ...", the address on its own, its own unit: "Yes, Shop 20 is open until 7:30 PM today"), never as a
    shop's ("England cluster mein shop ka location <it> hai", "... shop ka location Shop 20 hai")."""
    text = " ".join(str(sentence or "").replace("’", "'").split())
    if not text or shops.is_fixed_line(text) or is_code_line(text):
        return ""
    if _HOURLY.search(text):
        return HOURLY  # never true of our slots, said or asked (hours.SLOT: every 30 minutes)
    if office and _names_ours(text, office) and not _COMMISSION.search(text):
        rest = _without_address(text, office)
        if _A_SHOP.search(rest) and not _OUR_PLACE.search(rest) and not _question(text) and not _DEFERS.search(text):
            return "location"  # our office's address given as a shop's
        text = rest  # the address is ours: what else the sentence says is read on its own
    if _COMMISSION.search(text):
        return COMMISSION  # any word on it is Matloob's line, asked or not (a question of ours on it too)
    if _question(text) or _DEFERS.search(text):
        return ""
    wish = bool(_THEIR_WISH.search(text))
    if _SALE.search(text) and not _SALE_FACTS.search(known or ""):
        return "sale"
    if _DEPOSIT.search(text) and _ASSERTS.search(text):
        return "deposit"
    food = _FOOD_FIT.search(text) or (_FOOD.search(text) and _FOOD_OK.search(text) and not _MATCH.search(text))
    if food and not wish and not _in(known, [match.group(0) for match in _FOOD.finditer(text)] if not _FOOD_FIT.search(text) else []):
        return "food"
    if (
        _PLACE_DETAIL.search(text) and not _OUR_PLACE.search(text) and not wish
        and (_SHOP_OR_IT.search(text) or "building" in text.casefold()) and not _in(known, _place_words(text))
    ):
        return "location"
    if _OTHER.search(text) and _ASSERTS.search(text) and not wish:
        return "other"
    return ""


def asked_about(topic: str, texts) -> bool:
    """Their words this burst ask about (or speak of) what the claim is about."""
    words = " ".join(str(text or "") for text in texts or ())
    if topic == COMMISSION:
        return bool(_COMMISSION.search(words))
    pattern = _ASKED.get(topic)
    return bool(pattern and pattern.search(words))


def settle(answer: dict, texts, *, known: str = "", office: str = "", options: bool = False) -> list[str]:
    """The model's words in a shops reply without the facts SHOP FACTS lacks (live and in the eval, from
    engine.settle). Returns the topics cut ([] when nothing changed). ``known``: the SHOP FACTS block and our
    campaign's own words; ``office``: our office's address (topic_of).

    Each sentence that claims one (topic_of) goes; the first that answers their question on it (asked_about)
    gives way to the build pack's unknown line, once, in the reply's language (never when the reply defers to
    our agent already: live, chat 59's reply had its own "Good question — I'll have our agent confirm ..."),
    and each question becomes a note for our agent (facts.notes). A word on commission, or a commission
    question of theirs, gets Matloob's line in its place, or opening the reply when the reply has none
    (``options``: the chat wants no shop to rent: "see the options first"). A reply left with nothing is the
    unknown line, unless all they said was a thanks or an "ok" (then nothing goes)."""
    reply = answer.get("reply") or ""
    if not reply:
        return []
    language = answer.get("language") or "en"
    asked_commission = asked_about(COMMISSION, texts)
    sentences = filters.split_sentences(reply)
    topics = [topic_of(sentence, known, office) for sentence in sentences]
    kept: list[str] = []
    cut: list[str] = []
    # The reply leaves a question to our agent already (its own words or the build pack's line): no second deferral.
    unknown_used = any(not topic and _ANSWERS_LATER.search(sentence) for sentence, topic in zip(sentences, topics))
    # The reply gives Matloob's line already (the prompt says it word for word): nothing to add.
    commission_used = any(is_code_line(sentence) and _COMMISSION.search(sentence) for sentence in sentences)
    for sentence, topic in zip(sentences, topics):
        if not topic:
            kept.append(sentence)
            continue
        cut.append(topic)
        if topic == COMMISSION:
            if not commission_used:
                kept.append(commission_line(language, options=options))
                commission_used = True
        elif asked_about(topic, texts):
            _note(answer, _NOTES.get(topic, ""))
            if not unknown_used:
                kept.append(unknown_line(language))
                unknown_used = True
    if asked_commission and not commission_used:
        # Their question on commission, with nothing on it in the reply: the line opens it (the build pack's
        # unknown line given for that same question goes, since this answers it).
        alone = len([text for text in texts or () if str(text or "").strip()]) <= 1
        kept = [sentence for sentence in kept if not (alone and _key(sentence) == _key(unknown_line(language)))]
        kept.insert(0, commission_line(language, options=options))
        cut.append(COMMISSION)
    if not cut:
        return []
    said = [str(text or "") for text in texts or () if str(text or "").strip()]
    answer["reply"] = " ".join(kept).strip()
    if not answer["reply"] and not all(rules.is_acknowledgement(text) for text in said) and any(topic != HOURLY for topic in cut):
        # (Our slots said to be hourly answer no question of theirs: nothing is left to defer.)
        answer["reply"] = unknown_line(language)
    answer["send"] = bool(answer["reply"])
    return list(dict.fromkeys(cut))


def _note(answer: dict, note: str) -> None:
    if not note:
        return
    facts = answer.setdefault("facts", {})
    notes = facts.get("notes")
    notes = list(notes) if isinstance(notes, list) else []
    if note.casefold() not in {str(item).casefold() for item in notes}:
        notes.append(note)
    facts["notes"] = notes


# The size and price table said again (issue 16) -----------------------------------------------------------------

_ASKS_FIGURES = re.compile(
    r"\b(?:price|prices|pricing|rent|rents|cost|costs|rate|rates|how\s+much|kitna|kitne|kitni|qeemat|keemat|kiraya|size|sizes|sq\.?\s*ft"
    r"|sqft|sqf|square\s+feet|space|spaces|area|how\s+big|types?|options|details?"
    # The rent's period ("Wat is 33000/year", "is it monthly?", "per annum?"): the figures again are the answer.
    r"|year|years|yearly|yr|annual|annually|annum|month|months|monthly|salana|mahana)\b"
    r"|كم|سعر|أسعار|الإيجار|مساحة|سنوي|شهري|کتنا|کرایہ|قیمت|سائز|سالانہ|ماہانہ|कितना|किराया|कीमत|साइज़|सालाना|महीने",
    re.IGNORECASE,
)


def asks_figures(texts, facts) -> bool:
    """Their words ask for prices, sizes, the types or the rent's period, or name one of our types' figures
    themselves: launch chat 42 asked "Wat is 33000/year" and "48000/year" after the list, and the reply that
    explained those figures is the answer (the table cut took all of it but "What business will the shop be for?")."""
    words = " ".join(str(text or "") for text in texts or ())
    return bool(_ASKS_FIGURES.search(words) or _figures(words, facts))


def _figures(text: str, facts) -> dict[int, set[int]]:
    """The figures of each shop type the text names: {type number: its sizes and rents found}."""
    numbers = {value for value, _ in filters.numbers_in(text or "")}
    found: dict[int, set[int]] = {}
    for shop in shops.types_of(facts):
        figures = {shop.size_from, shop.size_to, shop.rent_from, shop.rent_to, shop.cheapest}
        hit = numbers & figures
        if hit:
            found[shop.number] = hit
    return found


def restates_table(sentence: str, sent: list[str], facts) -> bool:
    """The sentence gives the figures of two types or more, and every one of them is in what we sent already."""
    mine = _figures(sentence, facts)
    if len(mine) < 2:
        return False
    before: dict[int, set[int]] = {}
    for message in sent or ():
        for number, values in _figures(message, facts).items():
            before.setdefault(number, set()).update(values)
    return all(values <= before.get(number, set()) for number, values in mine.items())


def drop_table_repeat(answer: dict, sent: list[str], texts, facts) -> bool:
    """A shops reply without its sentences that give the table again (restates_table), unless their words now
    ask for prices, sizes, the types or the rent's period, or name our figures (asks_figures: asked again, the
    table is the answer; the list's rows sit behind its button). A reply that is nothing else stays whole.
    True when the reply changed."""
    reply = answer.get("reply") or ""
    if not reply or asks_figures(texts, facts):
        return False
    sentences = filters.split_sentences(reply)
    kept = [sentence for sentence in sentences if not restates_table(sentence, sent, facts)]
    if not kept or len(kept) == len(sentences):
        return False
    answer["reply"] = " ".join(kept)
    return True


# The price (issue 12) -------------------------------------------------------------------------------------------

_EXPENSIVE = re.compile(
    r"\bcheap(?:er|est)?\b|\blow(?:er|est)\b|\b(?:too\s+|very\s+|so\s+|bit\s+|a\s+bit\s+)?(?:expensive|costly|pricey|overpriced)\b"
    r"|\btoo\s+(?:much|high)\b|\b(?:rent|rents|price|prices|rate|rates|it|this|cost)\s+(?:is|are|r|seems?|looks?)\s+(?:very\s+|too\s+|so\s+|bit\s+|a\s+bit\s+|little\s+)?"
    r"(?:high|higher|much|more|expensive)\b|\bhigher\s+than\b|\bmore\s+than\s+(?:others|other|market)\b"
    r"|\b(?:over|above|out\s+of|beyond|exceeds?)\s+(?:my|our)\s+budget\b|\bcan'?t\s+afford\b|\bcannot\s+afford\b|\bnot\s+affordable\b"
    r"|\bbudget\s+is\s+(?:very\s+|too\s+|a\s+bit\s+)?(?:low|less|limited|tight|small)\b|\b(?:low|less|small|limited)\s+budget\b|\bbudget\s+kam\b|\bkam\s+budget\b"
    r"|\b(?:mehe?nga|mahe?nga|mehngi|mahngi|mehenge|sasta|sasti|saste)\b|\bbohat\s+zyada\b|\bbahut\s+zyada\b"
    r"|غالي|غالية|غاليه|غالي\s+جدا|أرخص|ارخص|رخيص|مہنگا|مہنگی|سستا|سستی|महंगा|महंगी|सस्ता|सस्ती",
    re.IGNORECASE,
)


def objects_to_price(texts) -> bool:
    """Their words find our rents too high, or ask for something cheaper ("I need cheaper price", "Your rent is
    higher than others", "too expensive", "mehenga hai"). A discount asked for ("any discount?", "best price?")
    is the discount line's (engine._DISCOUNT)."""
    return bool(_EXPENSIVE.search(" ".join(str(text or "").replace("’", "'") for text in texts or ())))


_LOWEST = {
    "en": "I understand. Our lowest is Type {n}, from AED {cheapest} a year ({size} sq ft){pay}. Would that size work for you?",
    "ar": "أتفهم ذلك. أقل خياراتنا هو النوع {n}، من {cheapest} درهم سنوياً ({size} قدم مربع){pay}. هل يناسبك هذا الحجم؟",
    "ur_latin": "Main samajhta hoon. Hamara sab se kam Type {n} hai, AED {cheapest} salana se ({size} sq ft){pay}. Kya yeh size aap ke liye theek rahega?",
    "ur": "میں سمجھتا ہوں۔ ہمارا سب سے کم ٹائپ {n} ہے، سالانہ AED {cheapest} سے ({size} مربع فٹ){pay}۔ کیا یہ سائز آپ کے لیے ٹھیک رہے گا؟",
    "hi_latin": "Main samajhta hoon. Hamara sabse kam Type {n} hai, AED {cheapest} salana se ({size} sq ft){pay}. Kya yeh size aapke liye theek rahega?",
    "hi": "मैं समझता हूँ। हमारा सबसे कम टाइप {n} है, सालाना AED {cheapest} से ({size} वर्ग फ़ुट){pay}। क्या यह साइज़ आपके लिए ठीक रहेगा?",
}
_PAY = {
    "en": ", payable in {cheques}",
    "ar": "، ويمكن الدفع على {cheques}",
    "ur_latin": ", {cheques} mein payment",
    "ur": "، {cheques} میں ادائیگی",
    "hi_latin": ", {cheques} mein payment",
    "hi": ", {cheques} में भुगतान",
}
_BELOW = {
    "en": "Thank you for telling me. To be honest, our lowest is Type {n}, from AED {cheapest} a year ({size} sq ft){above}.",
    "ar": "شكراً لإخباري. بصراحة، أقل خياراتنا هو النوع {n}، من {cheapest} درهم سنوياً ({size} قدم مربع){above}.",
    "ur_latin": "Batane ka shukriya. Sach kahun to hamara sab se kam Type {n} hai, AED {cheapest} salana se ({size} sq ft){above}.",
    "ur": "بتانے کا شکریہ۔ سچ کہوں تو ہمارا سب سے کم ٹائپ {n} ہے، سالانہ AED {cheapest} سے ({size} مربع فٹ){above}۔",
    "hi_latin": "Batane ke liye shukriya. Sach kahun to hamara sabse kam Type {n} hai, AED {cheapest} salana se ({size} sq ft){above}.",
    "hi": "बताने के लिए शुक्रिया। सच कहूँ तो हमारा सबसे कम टाइप {n} है, सालाना AED {cheapest} से ({size} वर्ग फ़ुट){above}।",
}
_ABOVE = {
    "en": ", which is above your budget of AED {budget}",
    "ar": "، وهذا أعلى من ميزانيتك البالغة {budget} درهم",
    "ur_latin": ", jo aap ke AED {budget} ke budget se zyada hai",
    "ur": "، جو آپ کے AED {budget} کے بجٹ سے زیادہ ہے",
    "hi_latin": ", jo aapke AED {budget} ke budget se zyada hai",
    "hi": ", जो आपके AED {budget} के बजट से ज़्यादा है",
}
# The colleague offered (its words end the line: a yes to them is read by colleague_yes).
COLLEAGUE_ASK = {
    "en": "Would you like one of our colleagues to check other options for you?",
    "ar": "هل تود أن يبحث لك أحد زملائنا عن خيارات أخرى؟",
    "ur_latin": "Kya aap chahenge ke hamara koi colleague aap ke liye doosre options dekhe?",
    "ur": "کیا آپ چاہیں گے کہ ہمارا کوئی ساتھی آپ کے لیے دوسرے آپشنز دیکھے؟",
    "hi_latin": "Kya aap chahenge ki hamara koi colleague aapke liye doosre options dekhe?",
    "hi": "क्या आप चाहेंगे कि हमारा कोई साथी आपके लिए दूसरे विकल्प देखे?",
}
LOWEST, BELOW = "lowest", "below"


def yearly_budget(facts: dict) -> int | None:
    """facts.budget_aed as a yearly figure (a monthly one times 12), None when none, or a misread one."""
    value = (facts or {}).get("budget_aed")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    yearly = value * 12 if (facts or {}).get("budget_basis") == "per_month" else value
    return int(yearly) if yearly >= BUDGET_FLOOR else None


def price_text(spec: dict, language: str, facts) -> str:
    """The price line's words (live and in the eval): our lowest type, honestly, then "would that size work?",
    or, below our lowest (or asked again), the colleague offered."""
    lang = _lang(language)
    clean = shops.facts_of(facts)
    cheapest = min(shops.types_of(clean), key=lambda shop: shop.cheapest)
    values = {"n": cheapest.number, "cheapest": f"{cheapest.cheapest:,}", "size": f"{cheapest.size_from:,}-{cheapest.size_to:,}"}
    if spec.get("kind") == BELOW:
        budget = spec.get("budget")
        above = _ABOVE[lang].format(budget=f"{int(budget):,}") if budget else ""
        return f"{_BELOW[lang].format(above=above, **values)} {COLLEAGUE_ASK[lang]}"
    pay = _PAY[lang].format(cheques=clean["cheques"]) if clean["cheques"] else ""
    return _LOWEST[lang].format(pay=pay, **values)


def lowest_from(facts) -> int:
    return min(shop.cheapest for shop in shops.types_of(shops.facts_of(facts)))


def sent_price_line(sent: list[str]) -> bool:
    """One of our messages already gave the price line (any language, either kind)."""
    starts = [_key(line.split("{")[0]) for line in (*_LOWEST.values(), *_BELOW.values())]
    for message in sent or ():
        key = _key(message)
        if any(start and key.startswith(start) for start in starts):
            return True
    return False


def asks_colleague(text: str) -> bool:
    """Our message offered a colleague for a budget below our lowest (price_text BELOW)."""
    words = " ".join(str(text or "").split())
    return any(words.endswith(line) for line in COLLEAGUE_ASK.values())


def price_turn(answer: dict, texts, known: dict, *, our_last: str, sent: list[str], facts, plain: bool, yes: bool) -> str:
    """The price line in place of the model's words (live and in the eval, after people.settle): returns
    PRICE when it goes, COLLEAGUE_HANDOVER when their yes to our colleague hands the chat over, else ''.

    ``plain``: nothing else must go out instead (no opt-out, handover, booking, fixed line, a person on the
    chat, a customer who wants no shop to rent); ``our_last``: our last message; ``sent``: our earlier
    messages; ``facts``: SHOP FACTS; ``yes``: their burst is a yes (engine.opens_with_yes)."""
    if not PRICE_LINE or not plain:
        return ""
    if yes and asks_colleague(our_last):
        answer["handover"] = {"needed": True, "reason": COLLEAGUE_HANDOVER}
        answer["converted"] = "holding"
        answer["invited_to_meeting"] = answer["share_office_location"] = False
        answer["send"] = True
        answer.pop("shop_step", None)
        return COLLEAGUE_HANDOVER
    known = known or {}
    merged = {**known, **{key: value for key, value in (answer.get("facts") or {}).items() if value not in (None, "", [])}}
    budget = yearly_budget(merged)
    new_budget = budget is not None and budget != yearly_budget(known)
    below = new_budget and budget < lowest_from(facts)
    objection = objects_to_price(texts)
    if not (objection or below):
        return ""
    again = objection and sent_price_line(sent)
    answer["converted"] = PRICE
    answer["price"] = {"kind": BELOW if (below or again) else LOWEST, "budget": budget if below else None}
    answer["invited_to_meeting"] = answer["share_office_location"] = False
    answer["send"] = True
    answer.pop("shop_step", None)
    return PRICE
