"""The shops playbook's steps that code takes by itself (board T31, T32, T34, T44).

- The shop types list (T31): when the customer says the shop is for themselves
  (facts.for_client turns false) or asks what shops there are, the reply is a
  WhatsApp list of the three types ("Great! We have 3 types of shops available
  in International City:", button "View shop types"), rows from SHOP FACTS.
- A type's media (T32): a tap on a row, or a request for photos or a video with
  one type in view, sends that type's video, its photos and its detail card
  (shop_media.send_type, outside the turn); the card's [Book viewing] gets the
  slot finder's two free slots, [See other types] the list again. A type's files
  go once a day in a chat (media_step): the same type tapped again that day gets
  its card alone, a typed request for its photos or video gets everything again,
  and the same type asked for again within minutes (a double tap) gets nothing.
- The licence copy (T34): once the customer has a DED or Trakhees licence, code
  asks once for a copy, while no visit is booked (the confirmation says to bring
  it); a photo or PDF while that ask is open is the licence, thanked for
  ("Thank you, got it.") before whatever else the reply says. "I'll send it
  later" keeps the ask open, "I'll bring it" or a no closes it (copy_reply); a
  second page minutes after the copy is no "media received" handover either
  (another_page).
- The reschedule offer (T44): "Need to reschedule" gets the two nearest free slots.
- Never a shop step for someone who wants no shop to rent (launch 2026-10-15, shops_unwanted):
  a home, to buy or to sell, "I never asked about a shop", or a shop they rented already (said
  now); and never the list when this burst turns the offer down or says "not now" (needs.declines).
  9 of the first 16 lists went to such people, in place of the model's own words.

Everything here is plain functions on plain data, so the eval (leadai_eval)
decides exactly as the engine does, with no database. The words are the build
pack's, in the six languages of the other fixed lines; a row's title and
description stay English, as the build pack's own list does.
"""

from __future__ import annotations

import datetime as dt
import re

from . import filters, needs, rules, shops

TYPE_KEYS = shops.TYPE_KEYS
# Reply-button ids of the detail card (never "leadai:...": that is a reminder tap).
BOOK_ID = "lai-shop:book:"
TYPES_ID = "lai-shop:types"
# What a step is (``answer["shop_step"]["kind"]``).
LIST = "list"
MEDIA = "media"
SLOTS = "slots"
LICENCE_ASK = "licence_ask"
LICENCE_THANKS = "licence_thanks"
# Taps (tap_rule).
TAP_TYPE = "type"
TAP_BOOK = "book"
TAP_TYPES = "types"
# A licence ask is open this long at most.
LICENCE_OPEN_DAYS = 14
# After the copy came, a photo or PDF within this long is its next page (another_page).
LICENCE_PAGES_FOR = dt.timedelta(minutes=10)
# WhatsApp's limits for a list message.
ROW_TITLE_MAX = 24
ROW_DESCRIPTION_MAX = 72
BUTTON_MAX = 20
SECTION_MAX = 24

# The header names the three sizes, never stock ("We have 3 types ... available" read as an inventory to the first mixed
# campaign's customers, 2026-10-19, chat 49958: "which shops are available in China Cluster A/B?" asked three times).
_LIST = {
    "en": ("Great! Shops in International City come in 3 types:", "View shop types", "Shop types"),
    "ar": ("رائع! المحلات في المدينة العالمية على 3 أنواع:", "عرض أنواع المحلات", "أنواع المحلات"),
    "ur_latin": ("Behtareen! International City mein shops 3 qisam ki hoti hain:", "Shop types dekhein", "Shop types"),
    "ur": ("بہترین! انٹرنیشنل سٹی میں دکانیں 3 قسم کی ہوتی ہیں:", "دکانوں کی اقسام", "دکانوں کی اقسام"),
    "hi_latin": ("Badhiya! International City mein shops 3 tarah ki hoti hain:", "Shop types dekhiye", "Shop types"),
    "hi": ("बढ़िया! इंटरनेशनल सिटी में दुकानें 3 तरह की होती हैं:", "दुकानों के प्रकार", "दुकानों के प्रकार"),
}
# (Size, Rent, per year, cheapest, Payment, Clusters, the question)
_CARD = {
    "en": ("Size", "Rent", "per year", "cheapest", "Payment", "Clusters", "Would you like to see it in person?"),
    "ar": ("المساحة", "الإيجار", "سنوياً", "الأقل", "الدفع", "المجمعات", "هل تود رؤيته على الطبيعة؟"),
    "ur_latin": ("Size", "Kiraya", "salana", "sab se kam", "Payment", "Clusters", "Kya aap ise khud aa kar dekhna chahenge?"),
    "ur": ("سائز", "کرایہ", "سالانہ", "سب سے کم", "ادائیگی", "کلسٹرز", "کیا آپ اسے خود آ کر دیکھنا چاہیں گے؟"),
    "hi_latin": ("Size", "Kiraya", "salana", "sabse kam", "Payment", "Clusters", "Kya aap ise khud aakar dekhna chahenge?"),
    "hi": ("साइज़", "किराया", "सालाना", "सबसे कम", "भुगतान", "क्लस्टर", "क्या आप इसे खुद आकर देखना चाहेंगे?"),
}
_BUTTONS = {
    "en": ("Book viewing", "See other types"),
    "ar": ("احجز معاينة", "أنواع أخرى"),
    "ur_latin": ("Viewing book karein", "Doosri qisam"),
    "ur": ("ویونگ بک کریں", "دوسری اقسام"),
    "hi_latin": ("Viewing book karein", "Doosre types"),
    "hi": ("व्यूइंग बुक करें", "दूसरे प्रकार"),
}
_BOOK_TITLES = {rules.normalize_text(book) for book, _ in _BUTTONS.values()}
_TYPES_TITLES = {rules.normalize_text(other) for _, other in _BUTTONS.values()}
_ROW_TITLE = re.compile(r"^\s*type\s*([123])(?!\d)", re.IGNORECASE)

# The customer asks what shops there are (the list), or for photos or a video (a type's media).
_ASKS_TYPES = re.compile(
    r"\b(?:what|which)\s+(?:kinds?|types?|sorts?|sizes?)\s+(?:of\s+)?(?:shops?|units?|options?)\b"
    r"|\b(?:what|which)\s+(?:shops|units|options|sizes|types)\b"
    r"|\bwhat\s+(?:do|have)\s+you\s+(?:have|got)\b|\bshops?\s+(?:types|options|sizes)\b|\btypes?\s+of\s+shops?\b"
    r"|\b(?:show|send)\s+(?:me\s+)?(?:the\s+|all\s+(?:the\s+)?|your\s+)?(?:options|types|list|shops)\b"
    r"|\bavailable\s+shops\b|\bshops?\s+available\b"
    r"|\bkaun\s*s[aie]\s+(?:shops?|dukan\w*)\b|\bkis\s+(?:qisam|type|tarah)\b|\bkitni\s+(?:qisam|types)\b"
    r"|(?:ما|ماهي|ما هي|شو|ايش|إيش)\s+(?:أنواع|انواع|المحلات|محلات)|أنواع المحلات|انواع المحلات|شو عندكم|ماذا لديكم"
    r"|کون\s*سی\s*دکان|کس\s*قسم|دکانوں\s*کی\s*اقسام|कौन\s*सी\s*दुकान|किस\s*तरह|दुकानों\s*के\s*प्रकार",
    re.IGNORECASE,
)
_MEDIA_NOUN = re.compile(
    r"\b(?:photos?|pictures?|pics?|images?|videos?|clips?)\b|\btasveer\w*|\bfoto\w*"
    r"|صور|صورة|فيديو|فديو|تصویر|تصاویر|ویڈیو|فوٹو|तस्वीर|फ़ोटो|फोटो|वीडियो",
    re.IGNORECASE,
)
_MEDIA_REQUEST = re.compile(
    r"[?؟]|\b(?:send|share|show|see|look)\b|\bbhej\w*|\bdikha\w*|ارسل|أرسل|ابعث|ابعت|وريني|ورني|شوف|بھیج|دکھا|भेज|दिखा",
    re.IGNORECASE,
)
# Their own photo, not ours: "I will send my licence photo", "here is a picture of my licence".
_THEIR_OWN = re.compile(
    r"\b(?:i|we)(?:'ll|\s+will|\s+am going to|\s+can|\s+shall)?\s+(?:send|share)\b|\bmy\s+(?:\w+\s+)?(?:photos?|pictures?|pics?|images?|copy)\b"
    r"|licen[cs]e|passport|emirates\s+id|رخص|لائسنس|लाइसेंस",
    re.IGNORECASE,
)
# Their answer to our request for the licence copy, in words (copy_reply). They will send it: a
# send verb, never negated ("I'll send it later", "kal bhej dunga", "Ok I will share later") ...
_SENDS_COPY = re.compile(
    r"\b(?:send|sending|sent|share|sharing|forward|upload|whatsapp)\b|\bbhej\w*|\bbhij\w*"
    r"|أرسل|ارسل|سأرسل|راح ارسل|ابعث|ابعت|بعث|بھیج|भेज",
    re.IGNORECASE,
)
# ... or they will not ("I won't send it", "I don't want to share it") ...
_WONT_SEND = re.compile(
    r"\b(?:won'?t|will\s+not|can'?t|cannot|can\s+not|not\s+going\s+to|don'?t\s+want\s+to|do\s+not\s+want\s+to|rather\s+not|prefer\s+not)"
    r"\s+(?:to\s+)?(?:send|share|give|forward|upload)\b|\bna(?:hi|hin|hi?n)?\s+bhej\w*|\bbhej\w*\s+na(?:hi|hin)\b"
    r"|لن أرسل|لن ارسل|ما راح ارسل|ما بقدر ارسل|نہیں بھیج|नहीं भेज",
    re.IGNORECASE,
)
# ... they will bring it to the viewing (the request is answered: closed) ...
_BRINGS_COPY = re.compile(
    r"\b(?:will|i'?ll|i\s+will|shall|can)\s+bring\b|\bbring\s+it\b|\bat\s+the\s+viewing\b|\bwhen\s+i\s+come\b|\bsaath\s+la\w*|\bla\s+(?:dunga|doonga|denge)\b"
    r"|ساتھ لا|साथ ला|أحضر|احضر|بجيبها|معي في الزيارة",
    re.IGNORECASE,
)
# ... later, with no word of how (the request stays open: a photo that comes after is the copy) ...
_LATER = re.compile(
    r"\blater\b|\bbaad\s+m(?:ein|e|ain)\b|\bkal\b|\btomorrow\b|\btonight\b|\bsoon\b|\babhi\s+(?:nahi|nahin|nhi)\b|\bnot\s+now\b|\bthodi?\s+der\b"
    r"|لاحقا|لاحقاً|بعدين|بكرة|بكره|غدا|غداً|بعد میں|ابھی نہیں|बाद में|अभी नहीं",
    re.IGNORECASE,
)
# ... or they have none to give ("I don't have it", "not with me", "no licence yet").
_HAS_NONE = re.compile(
    r"\b(?:don'?t|do\s+not|dont|not)\s+(?:have|got|carry)\b|\bnot\s+with\s+me\b|\bno\s+licen[cs]e\b"
    r"|ليس معي|مو معي|مش معي|ما عندي|میرے پاس نہیں|मेरे पास नहीं",
    re.IGNORECASE,
)
COPY_LATER = "later"
COPY_DECLINED = "declined"


def _lang(language: str, table: dict) -> str:
    return language if language in table else "en"


# The list --------------------------------------------------------------------------------------


def list_rows(facts) -> list[dict]:
    """The list's rows: id type_N, title "Type 1 – Small", description "400-550 sq ft | from AED 33,000/yr"."""
    rows = []
    for shop in shops.types_of(facts):
        rows.append(
            {
                "id": shop.key,
                "title": shop.name[:ROW_TITLE_MAX],
                "description": f"{shop.size_from:,}-{shop.size_to:,} sq ft | from AED {shop.cheapest:,}/yr"[:ROW_DESCRIPTION_MAX],
            }
        )
    return rows


def list_interactive(language: str, facts) -> dict:
    """The WhatsApp interactive list object (gateway client.send_interactive)."""
    body, button, section = _LIST[_lang(language, _LIST)]
    return {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button[:BUTTON_MAX], "sections": [{"title": section[:SECTION_MAX], "rows": list_rows(facts)}]},
    }


def list_text(language: str, facts) -> str:
    """The list as the thread and the transcript show it: the body, then one line per row."""
    body = _LIST[_lang(language, _LIST)][0]
    lines = [f"- {row['title']}: {row['description']}" for row in list_rows(facts)]
    return "\n".join([body, *lines])


# The detail card ----------------------------------------------------------------------------------


def card_text(language: str, shop_type: str, facts) -> str:
    """The build pack's detail card ("TYPE 1 – SMALL SHOP / Size ... / Would you like to see it in person?")."""
    shop = shops.type_by_key(shop_type, facts)
    clean = shops.facts_of(facts)
    lang = _lang(language, _CARD)
    size, rent, per_year, cheapest, payment, clusters, question = _CARD[lang]
    if shop is None:
        return question
    head = f"TYPE {shop.number} – {shop.label.upper()} SHOP" if lang == "en" else shop.name
    lines = [
        head,
        f"{size}: {shop.size_from:,}-{shop.size_to:,} sq ft",
        f"{rent}: AED {shop.rent_from:,}-{shop.rent_to:,} {per_year} ({cheapest} AED {shop.cheapest:,})",
    ]
    if clean["cheques"]:
        lines.append(f"{payment}: {clean['cheques']}")
    if clean["clusters"]:
        lines.append(f"{clusters}: {', '.join(clean['clusters'])}")
    lines.append(question)
    return "\n".join(lines)


def card_buttons(language: str, shop_type: str) -> list[dict]:
    book, other = _BUTTONS[_lang(language, _BUTTONS)]
    return [{"id": f"{BOOK_ID}{shop_type}", "title": book[:BUTTON_MAX]}, {"id": TYPES_ID, "title": other[:BUTTON_MAX]}]


def video_caption(shop_type: str, facts) -> str:
    """The caption under a type's video: "Type 1 – Small · 400-550 sq ft"."""
    shop = shops.type_by_key(shop_type, facts)
    return f"{shop.name} · {shop.size_from:,}-{shop.size_to:,} sq ft" if shop is not None else ""


def media_text(shop_type: str, language: str, facts, files: bool = True) -> str:
    """What a type's media step sends, as the eval reports it: the files (unless they went
    out today already: media_step), then the card."""
    if not files:
        return card_text(language, shop_type, facts)
    shop = shops.type_by_key(shop_type, facts)
    name = shop.name if shop is not None else shop_type
    return f"[the video and photos of {name}]\n{card_text(language, shop_type, facts)}"


# Taps ----------------------------------------------------------------------------------------------


def tap_rule(label: str, tap_id: str = "") -> tuple[str, str] | None:
    """(what was tapped, the shop type) for a tap on our list or detail card, else None:
    (TAP_TYPE, "type_2") for a row, (TAP_BOOK, "type_2" or "") for [Book viewing],
    (TAP_TYPES, "") for [See other types]. The id decides when there is one; the eval
    has the label alone ("[tapped: Type 1 – Small]")."""
    tap_id = str(tap_id or "").strip()
    if tap_id in TYPE_KEYS:
        return TAP_TYPE, tap_id
    if tap_id.startswith(BOOK_ID):
        rest = tap_id[len(BOOK_ID) :]
        return TAP_BOOK, rest if rest in TYPE_KEYS else ""
    if tap_id == TYPES_ID:
        return TAP_TYPES, ""
    if tap_id.startswith("leadai:"):
        return None  # a reminder button
    words = rules.normalize_text(label)
    if not words:
        return None
    match = _ROW_TITLE.match(str(label or ""))
    if match:
        return TAP_TYPE, f"type_{match[1]}"
    if words in _BOOK_TITLES:
        return TAP_BOOK, ""
    if words in _TYPES_TITLES:
        return TAP_TYPES, ""
    return None


# What the customer asked --------------------------------------------------------------------------

# A tap as the burst's words carry it (transcript.inbound_text): "[tapped: Yes, show me shops]".
_TAPPED = re.compile(r"\[tapped:[^\]]*\]")


def without_taps(said: str) -> str:
    """The burst's words without its taps: what they typed or said. Live, a tap's own label ("Yes, show me
    shops") read as asking for the shop types, and the list replaced the answer to chat 81's typed "How much
    price monthly basis" (launch review issue 13): a burst that holds typed words is read without its taps
    (engine.model_step); a tap alone still asks what its label says."""
    return " ".join(_TAPPED.sub(" ", str(said or "")).split())


def typed_words(said: str) -> str:
    """The burst's words as a request for photos or the shop types is read from them: without the taps when it
    holds anything else (without_taps), else as they are (a lone [Yes, show me shops] asks for the shops)."""
    rest = without_taps(said)
    return rest if rest else str(said or "")


def asks_types(text: str) -> bool:
    return bool(_ASKS_TYPES.search(str(text or "").replace("’", "'")))


def asks_media(text: str) -> bool:
    """Photos or a video asked for ("Can you send photos?", "video bhej do"), not merely named,
    and not their own ("I will send my licence photo")."""
    text = str(text or "").replace("’", "'")
    return bool(_MEDIA_NOUN.search(text)) and bool(_MEDIA_REQUEST.search(text)) and not _THEIR_OWN.search(text)


# A tap sent together with typed words (launch review issue 13) -----------------------------------------------
# Chat 81 tapped [Yes, show me shops] and typed "How much price monthly basis" 8 s later: one burst, and the
# build pack's "for yourself, or for a client?" never went. Chat 88 typed his size and cluster, then tapped
# "Type 1 – Small" 11 s later: no video, photos or card. Code's tap rules read a burst of taps alone; with
# words in it, the model answers them and the tap keeps its step (engine.tap_with_words).
TAP_YES = "yes"  # a template's positive tap ([Yes, show me shops], [Yes, book a viewing], "Interested")


def burst_tap(taps, typed: bool) -> tuple[str, str] | None:
    """The tap of a burst that also holds words of theirs (``typed``): (TAP_TYPE, its type) for our list's
    row, (TAP_BOOK, type) or (TAP_TYPES, '') for a card's button, (TAP_YES, "book" or '') for a template's
    positive tap; None when the burst is taps alone (code's tap rules answer it) or holds none. ``taps``:
    the burst's taps, oldest first, as (label, id); the last one is their choice."""
    if not taps or not typed:
        return None
    label, tap_id = taps[-1]
    found = tap_rule(label, tap_id)
    if found:
        return found
    if rules.is_positive_tap(label):
        return TAP_YES, ("book" if rules.is_book_tap(label) else "")
    return None


_FOR_WHOM_ASKED = re.compile(
    r"\bfor\s+yourself\b|\bfor\s+a\s+client\b|\bapne\s+liye\b|\bclient\s+ke\s+liye\b|لعميل|شخصياً|کلائنٹ|اپنے\s+لیے|क्लाइंट|अपने\s+लिए",
    re.IGNORECASE,
)


def asks_for_whom(text: str) -> bool:
    """The text asks the build pack's first question: is the shop for themselves, or for a client?"""
    return bool(_FOR_WHOM_ASKED.search(str(text or "")))


def for_whom_question(language: str) -> str:
    """The for-whom question alone, without the line's own "Thank you!" (rules "for_whom")."""
    return rules.line("for_whom", language).split("! ", 1)[-1]


def names_types(sentence: str) -> bool:
    """The sentence names one of our types ("Type 1 is perfect: 400-550 sq ft ..."): a type's card or the list says it."""
    return bool(re.search(r"\btype\s*[123]\b", str(sentence or ""), re.IGNORECASE))


def copy_reply(text: str) -> str:
    """How the customer answers our request for the licence copy, in words:

    - COPY_LATER: they will send it ("Sure, I'll send it later", "baad mein bhej dunga", "Ok I
      will share later", "later", "not now"): the request stays open, so the photo or PDF that
      comes after is the copy, not a "media received" handover;
    - COPY_DECLINED: they will not, or not here ("No", "I won't send it", "I'll bring it to the
      viewing", "I don't have it"): the request is closed;
    - '' when the words say neither (the model reads them, the request stays as it was).

    A send verb decides first ("I don't have it with me, I'll send it tomorrow" will send it),
    then bringing it, then a bare "later", then having none or a plain no."""
    words = str(text or "").strip()
    if not words:
        return ""
    flat = words.replace("’", "'")
    if _WONT_SEND.search(flat):
        return COPY_DECLINED
    if _SENDS_COPY.search(flat):
        return COPY_LATER
    if _BRINGS_COPY.search(flat):
        return COPY_DECLINED
    if _LATER.search(flat) or rules.is_deferral(words) or rules.is_not_now(words):
        return COPY_LATER
    if _HAS_NONE.search(flat) or rules.is_refusal(words):
        return COPY_DECLINED
    return ""


def declines_copy(text: str) -> bool:
    """The customer will not share the licence copy ("No", "I'll bring it", "I don't have it"); a
    promise to send it later is no decline (copy_reply)."""
    return copy_reply(text) == COPY_DECLINED


def is_licence_media(kind: str, mime: str = "", name: str = "") -> bool:
    """A photo, or a document that is a PDF: what may be the licence copy (its bytes are checked later)."""
    if kind == "image":
        return True
    if kind != "document":
        return False
    return "pdf" in str(mime or "").lower() or str(name or "").lower().endswith(".pdf")


def licence_open(asked_at, closed_at, now) -> bool:
    """The licence copy was asked for and neither came nor was refused, within LICENCE_OPEN_DAYS."""
    if asked_at is None or closed_at is not None:
        return False
    return (now - asked_at).days < LICENCE_OPEN_DAYS


def another_page(closed_at, copy, now) -> bool:
    """The licence copy came a few minutes ago (``copy`` is facts.licence_copy): a photo or a PDF
    now is its next page, never a "media received" handover. The lead keeps the first file; the
    others stay in the chat."""
    return copy == "received" and closed_at is not None and dt.timedelta(0) <= now - closed_at <= LICENCE_PAGES_FOR


def type_in_view(answer_facts: dict, known: dict, facts) -> str:
    """The one type the chat is about: the one chosen (this answer's, else known), else MATCH's."""
    for source in (answer_facts or {}, known or {}):
        value = source.get("shop_type")
        if value in TYPE_KEYS:
            return value
    merged = {**(known or {}), **{k: v for k, v in (answer_facts or {}).items() if v not in (None, "", [])}}
    shop, _ = shops.match(merged, facts)
    return shop.key if shop is not None else ""


def media_step(shop_type: str, *, typed: bool, recent=(), today=()) -> dict | None:
    """The step that sends a type's media, else None (board T32: once per chat and type a day).

    ``recent``: the types whose media a turn queued minutes ago: the same request
    again (a double tap) sends nothing. ``today``: the types whose files went out
    today: a tap on the same row again gets the detail card alone ("files": False),
    a typed request for its photos or video (``typed``) is asked again and gets
    everything."""
    if shop_type not in TYPE_KEYS or shop_type in set(recent or ()):
        return None
    step = {"kind": MEDIA, "type": shop_type}
    if shop_type in set(today or ()) and not typed:
        step["files"] = False
    return step


# Who gets no shop step (launch 2026-10-15) ---------------------------------------------------------


def shops_unwanted(answer_facts: dict, known: dict, said: str) -> bool:
    """No shop step at all (the list, a type's media, the licence request): the customer wants no shop
    to rent (the chat's own need, facts.need, or one said now: needs.detect; a home as property_type;
    intent buy or sell), or says now that they rented one already (this answer's already_rented, or
    their words: needs.rented_already). A shop they rented before stops nothing later: a second one
    gets its steps."""
    answer_facts, known = answer_facts or {}, known or {}
    merged = {**known, **{key: value for key, value in answer_facts.items() if value not in (None, "", [])}}
    if needs.of(known) is not None or merged.get("intent") in ("buy", "sell") or needs.is_home_type(merged.get("property_type")):
        return True
    if answer_facts.get("already_rented") is True and known.get("already_rented") is not True:
        return True
    return needs.detect([said]) is not None or needs.rented_already([said])


# After the model -----------------------------------------------------------------------------------


def after_model(
    answer: dict,
    known: dict,
    said: str,
    *,
    plain: bool,
    asked: bool,
    list_sent: bool,
    licence_asked: bool,
    media_recent=(),
    media_today=(),
    booked: bool = False,
    facts=None,
    invitation: bool = False,
    requested: bool = False,
) -> dict | None:
    """The step code takes instead of the model's words in a shops turn, else None.

    ``plain``: the answer has nothing that must go out instead (no opt-out,
    handover, booking or fixed line; the caller decides); ``asked``: the customer
    asked something the model should answer (a question, the way, a day or a time);
    ``list_sent``: the list went out in this chat already; ``licence_asked``: the
    licence copy was asked for already (never twice); ``media_recent`` and
    ``media_today``: the types whose media went out minutes ago, and today
    (media_step); ``booked``: a visit is open, so the copy is not asked for (the
    confirmation says to bring the licence); ``invitation``: the answer would be
    plain but for a tentative visit only its own invitation recorded (nobody asked
    to come: engine.model_step), which the licence request alone replaces, as the
    build pack asks for the copy before it invites (eval shops-licence-ask);
    ``requested``: the answer would be plain but for a tentative of the model's, and
    photos, a video or the shop types are asked for (engine.model_step), which their
    step alone replaces.
    In this order: photos or a video asked for (the type in view, else the list);
    the shop types asked for; "for myself" said now, with no size, budget or type
    to match yet (the list, once); a DED or Trakhees licence known (the copy asked
    for, once). None of them for someone who wants no shop to rent or just rented one
    (shops_unwanted), and never the list when this burst says no or "not now"
    (needs.declines): the model's words go.
    """
    if not plain and not invitation and not requested:
        return None
    answer_facts = answer.get("facts") or {}
    if shops_unwanted(answer_facts, known, said):
        return None
    no_list = needs.declines([said])
    if plain or requested:
        if asks_media(said):
            shop_type = type_in_view(answer_facts, known, facts)
            if not shop_type:
                return None if no_list else {"kind": LIST}
            step = media_step(shop_type, typed=True, recent=media_recent, today=media_today)
            if step is not None or plain or not invitation:
                return step
        elif asks_types(said):
            return None if no_list else {"kind": LIST}
    if plain:
        for_me = (known or {}).get("for_client") is None and answer_facts.get("for_client") is False
        # Not when their size, budget or type already gives the one type to recommend (MATCH): that reply goes.
        if (
            for_me and not list_sent and not asked and not no_list and not answer.get("invited_to_meeting")
            and not type_in_view(answer_facts, known, facts)
        ):
            return {"kind": LIST}
    if not plain and not invitation:
        return None
    licence = answer_facts.get("licence_kind") or (known or {}).get("licence_kind")
    if licence in ("ded", "trakhees") and not licence_asked and not asked and not booked:
        return {"kind": LICENCE_ASK}
    return None


def step_flags(answer: dict) -> None:
    """A step's words replace the model's: its invitation and its location go with them.
    [Book viewing] answers the customer's own request to come (no invitation to count),
    and the licence thanks says itself whether it offers slots (the engine sets it)."""
    step = answer.get("shop_step") or {}
    if step.get("kind") in (LIST, MEDIA, SLOTS, LICENCE_ASK, LICENCE_THANKS):
        answer["invited_to_meeting"] = False
        answer["share_office_location"] = False


def thank_first(answer: dict, language: str) -> bool:
    """The licence copy came with other words (board T34): "Thank you, got it." opens the
    model's reply (and its English gloss). True when the reply changed."""
    if not answer.get("send") or not answer.get("reply") or answer.get("opt_out", "none") != "none":
        return False
    if answer.get("converted") or answer.get("slot_taken") or answer.get("shop_step"):
        return False
    thanks = rules.line("licence_thanks", language)
    if answer["reply"].startswith(thanks):
        return False
    answer["reply"] = f"{thanks} {answer['reply']}"
    if answer.get("reply_en"):
        answer["reply_en"] = f"{rules.line('licence_thanks', 'en')} {answer['reply_en']}"
    return True


def slots_text(language: str, slots: list, now, before: str = "", *, again: bool = False) -> str:
    """[Book viewing]: the two free slots ("I can hold a slot for you today at ... — which is better?").
    ``before``: what our side said lately; when that already offered these two in these words (a
    plain "Yes" to them picks neither), they are asked about in other words (never the same sentence
    twice in a chat). ``again``: these two are the ones our message offered in words of its own (a
    plain yes to the morning nudge's: engine.nudge_yes), so they are asked about again first ("Which
    one suits you better: today at 4:00 PM or 6:00 PM?")."""
    if not slots:
        return rules.line("ask_time", language)
    plain = shops.slot_offer(language, slots, now)
    other = shops.slot_offer(language, slots, now, again=True)
    first, second = (other, plain) if again else (plain, other)
    if before and filters.said_before(first, [before]):
        return first if filters.said_before(second, [before]) else second
    return first


def thanks_text(language: str, slots: list, now) -> str:
    """The licence copy came: "Thank you, got it.", and the two free slots when a visit is still to book."""
    thanks = rules.line("licence_thanks", language)
    offer = shops.slot_offer(language, slots, now) if slots else ""
    return f"{thanks} {offer}".strip()


def reschedule_text(language: str, slots: list, now) -> str:
    """ "Need to reschedule": the two nearest free slots, not an open question (T44)."""
    if not slots:
        return rules.line("ask_new_time", language)
    return f"{rules.line('reschedule_slots', language)} {shops.slot_offer(language, slots, now)}"


def step_text(step: dict, language: str, facts, now, slots: list = (), before: str = "") -> str:
    """What a step sends, as text (the list as the thread shows it, a type's media as the eval reports
    it). ``before``: what our side said lately (slots_text)."""
    kind = step.get("kind")
    if kind == LIST:
        return list_text(language, facts)
    if kind == MEDIA:
        return media_text(step.get("type", ""), language, facts, files=step.get("files", True) is not False)
    if kind == SLOTS:
        return slots_text(language, list(slots), now, before, again=bool(step.get("again")))
    if kind == LICENCE_ASK:
        return rules.line("licence_copy", language)
    if kind == LICENCE_THANKS:
        return thanks_text(language, list(slots), now)
    return ""


# The model may not name a business the customer does not have (board T56) --------------------------

_GENERIC = {
    "shop", "shops", "store", "stores", "business", "businesses", "retail", "small", "new", "your", "a", "an", "the",
    "start", "starter", "unit", "one", "outlet", "space", "this", "that", "it", "you", "yourself", "client", "clients",
    # A size or a budget is no business ("For a 450 sq ft shop", "For a budget of AED 40,000").
    "sq", "ft", "sqft", "square", "feet", "foot", "size", "sized", "big", "bigger", "smaller", "large", "medium",
    "budget", "of", "aed", "year", "yearly", "month", "monthly", "around", "about", "first", "single", "family", "start-up",
}
_BUSINESS_NOUNS = (
    "shop", "store", "business", "salon", "restaurant", "cafe", "café", "pharmacy", "clinic", "office", "boutique",
    "outlet", "showroom", "centre", "center", "studio", "bakery", "kitchen", "supermarket", "grocery store", "laundry",
)
_FOR_LEAD = re.compile(
    r"\b(?P<lead>[Ff]or)\s+(?P<art>a|an|your)\s+(?P<biz>[^,.!?:;\n—–-]{2,40}?)"
    r"(?P<tail>\s*[,—–:-]?\s+(?:(?:I'?d|I\s+would|we'?d|we\s+would|I|we)\s+(?:recommend|suggest)\s+)?Type\s*[123]\b)"
)
_FOR_TAIL = re.compile(
    r"(?P<head>\bType\s*[123]\b[^.!?\n]{0,40}?)\s+for\s+(?P<art>a|an|your)\s+(?P<biz>[^,.!?:;\n—–-]{2,40}?)(?=\s*(?:[,.!?:;\n—–-]|$))"
)


# SHOPS_SYSTEM's examples say "<their business>" where the customer's business goes; copied as it is,
# it is filled in (or its sentence dropped while the business is unknown), never sent.
_PLACEHOLDER = re.compile(r"(?:\b(?P<art>an?|your)\s+)?<\s*their\s+business\s*>", re.IGNORECASE)


def fill_placeholders(reply: str, activity: str) -> tuple[str, bool]:
    """The reply with a copied "<their business>" made the customer's business, or the sentence
    that carries it left out when that is not known; (reply, changed)."""
    text = str(reply or "")
    if not _PLACEHOLDER.search(text):
        return text, False
    phrase = business_phrase(activity)
    if phrase:
        text = _PLACEHOLDER.sub(lambda match: phrase, text)
    else:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        text = " ".join(sentence for sentence in sentences if not _PLACEHOLDER.search(sentence))
    text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text.strip())
    return text, True


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[\w']+", str(text or "").casefold())
    return {word for word in words if word not in _GENERIC and not word.replace(",", "").isdigit()}


def business_phrase(activity: str) -> str:
    """"a vape shop" for "vape shop", "your vape business" for "vape" (the customer's own business)."""
    text = re.split(r"[(\[{]", str(activity or ""), maxsplit=1)[0]
    text = " ".join(text.split()).strip(" ,.;:-")
    if not text:
        return ""
    lowered = text.casefold()
    if lowered.endswith(_BUSINESS_NOUNS):
        return f"{'an' if lowered[0] in 'aeiou' else 'a'} {text}"
    return f"your {text} business"


def own_business(reply: str, activity: str, said: str = "") -> tuple[str, bool]:
    """The reply with a MATCH sentence's "for a <business>" made the customer's own business,
    or dropped when it is not known; (reply, changed). A generic word ("shop", "your
    business") and the customer's own business stay as they are: any word of
    ``activity`` (facts.business_activity), or of what they said now (``said``: "I have
    vape business" before the model recorded it)."""
    mine = _tokens(activity) | _tokens(said)
    phrase = business_phrase(activity)
    changed = False

    def theirs(biz: str) -> bool:
        words = _tokens(biz)
        return not words or bool(mine and words & mine)

    def lead(match):
        nonlocal changed
        if theirs(match["biz"]):
            return match.group(0)
        changed = True
        tail = match["tail"].lstrip(" ,—–:-")
        if phrase:
            return f"{match['lead']} {phrase},{' ' if not tail.startswith(' ') else ''}{tail}"
        return tail

    def tail(match):
        nonlocal changed
        if theirs(match["biz"]):
            return match.group(0)
        changed = True
        return f"{match['head']} for {phrase}" if phrase else match["head"]

    text = _FOR_LEAD.sub(lead, str(reply or ""))
    text = _FOR_TAIL.sub(tail, text)
    if changed:
        # A dropped opening leaves a sentence that starts in lower case or with a space.
        text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text.strip())
        text = re.sub(r"[ \t]{2,}", " ", text)
    return text, changed
