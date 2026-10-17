"""A customer who wants to BUY a shop (Q43, Matloob 2026-10-17): no price, the office invitation, and a person told.

A7 lists shops for sale in International City (England Cluster at about AED 1,100 a square foot, one in China), but
SHOP FACTS holds rents only and no sale figure. So a shop buyer never hears a price: every figure the model writes them
is cut (a rent from SHOP FACTS read as a price is worse than none), and when they ask what a shop costs, code answers:
"The price depends on the shop, so our agent will go through the options and prices with you at our office.", with
Q25's invitation ("Visit our office and we'll give you the best option.") and two free office slots, and the team is
alerted that they asked. The rest is 2d's for a buyer (engine.who_they_are: the owner's line, never the shop list,
never a word of renting, never lost).

A buyer of a shop, or a buyer in a shops chat who named nothing else ("To buy"), on the shops or the other track; a
studio or one-bedroom buyer is the sale flow's (batch 2e slice C), never this module's. Plain functions on plain
data, so the eval (leadai_eval) decides exactly as the engine does.
"""

from __future__ import annotations

import re
import unicodedata

from . import needs, tracks

# What settle did (the turn's actions): code's price answer, or the figures cut from the model's words.
PRICE_LINE = "shop_buyer_price"
AMOUNTS_CUT = "shop_buyer_amounts"
# The guards, one line each (their tests switch each off to prove it is what holds): no figure in the model's words to a
# shop buyer, and code's answer to their price question.
NO_FIGURES = True
PRICE_ANSWER = True
# The alert's priority: a person may call them back within the hour.
ALERT_PRIORITY = "high"

_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")
PRICE_SENTENCE = {
    "en": "The price depends on the shop, so our agent will go through the options and prices with you at our office.",
    "ar": "يعتمد السعر على المحل، لذلك سيشرح لك وكيلنا الخيارات والأسعار في مكتبنا.",
    "ur_latin": "Qeemat dukaan par munhasir hai, is liye hamare agent office mein aap ko options aur qeematein tafseel se batayenge.",
    "ur": "قیمت دکان پر منحصر ہے، اس لیے ہمارے ایجنٹ آفس میں آپ کو آپشنز اور قیمتیں تفصیل سے بتائیں گے۔",
    "hi_latin": "Keemat dukaan par nirbhar karti hai, isliye hamare agent office mein aapko options aur keematein vistaar se batayenge.",
    "hi": "क़ीमत दुकान पर निर्भर करती है, इसलिए हमारे एजेंट ऑफ़िस में आपको विकल्प और क़ीमतें विस्तार से बताएँगे।",
}

# They ask what it costs: "price?", "how much", "what is the cost", "kitne ka", "qeemat", "rate", "سعر", "بكم", "कीमत".
_ASKS_PRICE = re.compile(
    r"\b(?:price|prices|pricing|priced|cost|costs|costing|rate|rates|how\s+much|valuation|per\s+(?:sq|square))\b"
    r"|\bkitn[aei]\s+(?:ka|ki|ke|mein|me|main|paise|paisa|price|cost|rate|rupay|dirham)\b|\bqeem?at\b|\bkeemat\b|\bkimat\b|\bdaam\b"
    r"|سعر|السعر|أسعار|اسعار|بكم|كم\s+(?:سعر|ثمن|السعر|يكلف|تكلفة)|ثمن|قیمت|قيمت|کتنے\s+(?:کا|کی|میں)|کتنا\s+(?:ہے|ہوگا)"
    r"|कीमत|क़ीमत|दाम|कितने\s+(?:का|की|में)",
    re.IGNORECASE,
)
# Money in the model's words: an amount with a currency, "33k", "1,100", a bare number of four digits or more, a price
# per square foot, lakh or million; Arabic-Indic digits too.
_AMOUNT = re.compile(
    r"(?:\b(?:aed|dhs?|dirhams?|usd)|درهم|درہم|दिरहम)\s*[\d٠-٩۰-۹]"
    r"|[\d٠-٩۰-۹][\d٠-٩۰-۹,.]*\s*(?:k\b|aed\b|dhs?\b|dirhams?\b|درهم|درہم|thousand\b|lakh\b|lac\b|million\b|ألف|الف|ہزار|लाख|हज़ार|हजार)"
    r"|(?<![\d,.:/])\d{1,3}(?:,\d{3})+(?![\d,])|(?<![\d:,./-])\d{4,}(?![\d:/-])|[٠-٩۰-۹]{4,}"
    r"|\bper\s+(?:sq\.?\s*(?:ft|feet|foot|m)|square\s+(?:foot|feet|metre|meter))\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?؟۔।])\s+|\n+")


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


def _flat(text) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).split())


def is_buyer(need, known=None, *, track: str = "") -> bool:
    """The chat's customer wants to buy a shop: ``need`` (needs.Need, said now or the chat's own) is to buy a shop, or to
    buy with nothing named in a chat whose property is a shop or not known (a shops campaign's "To buy"). Never on the
    rent or the sale track."""
    if need is None or need.kind != needs.BUY or track in (tracks.RENT, tracks.SALE):
        return False
    if need.noun == "shop":
        return True
    named = needs.noun_of((known or {}).get("property_type"))
    return not need.noun and named in ("", "shop")


def asks_price(texts) -> bool:
    return any(_ASKS_PRICE.search(_flat(text)) for text in texts or () if str(text or "").strip())


def has_amount(text) -> bool:
    return bool(_AMOUNT.search(_flat(text)))


def drop_amounts(reply: str) -> tuple[str, bool]:
    """The reply without its sentences that carry a figure; (reply, changed)."""
    sentences = [part.strip() for part in _SENTENCES.split(str(reply or "")) if part.strip()]
    kept = [sentence for sentence in sentences if not has_amount(sentence)]
    if len(kept) == len(sentences):
        return str(reply or "").strip(), False
    return " ".join(kept), True


def price_line(spec: dict, language: str, offer: str) -> str:
    """The owner's line for a buyer who asked the price (engine.not_a_shop_text with spec["price"]): the first time,
    thanks (and sorry), the options to buy, then the price sentence; after that the price sentence alone; then Q25's
    "Visit our office and we'll give you the best option." and ``offer`` (two free slots, or nothing once invited)."""
    lang = _lang(language)
    parts = []
    if spec.get("price") != "again":
        need = needs.Need(spec.get("kind") or needs.BUY, spec.get("noun") or "", bool(spec.get("denies")))
        # needs.line's own sentences, in its order, with the price sentence before the invitation.
        parts += [needs._THANKS[lang][1 if spec.get("sorry") else 0], needs.options_sentence(lang, need)]
    parts += [PRICE_SENTENCE[lang], needs._VISIT[lang], offer]
    return " ".join(part for part in parts if part)


def settle(answer: dict, need, known: dict, texts, *, track: str = "", invites: int = 0, slots=(), plain: bool = True) -> str:
    """A shops answer to a shop buyer (live and in the eval, after engine.bare_need_reply): the model's words carry no
    figure, and a price they ask about gets code's answer with the invitation (its slots only while they were not
    invited yet). Returns PRICE_LINE, AMOUNTS_CUT or ''. ``plain``: nobody holds the chat, no booking or time to
    refuse, no open visit (engine.bare_need_reply's). ``known``: the chat's facts (the answer's own are read on top)."""
    known = {**(known or {}), **{key: value for key, value in (answer.get("facts") or {}).items() if value not in (None, "", [])}}
    if not is_buyer(need, known, track=track):
        return ""
    done = ""
    trimmed = list(answer.get("trimmed") or [])
    if NO_FIGURES and answer.get("send") and answer.get("reply") and not answer.get("converted"):
        answer["reply"], cut = drop_amounts(answer["reply"])
        if cut:
            trimmed.append(AMOUNTS_CUT)
            done = AMOUNTS_CUT
    asked = PRICE_ANSWER and asks_price(texts)
    others = answer.get("opt_out", "none") != "none" or (answer.get("handover") or {}).get("needed") or answer.get("broker")
    if asked and plain and not others:
        if answer.get("not_a_shop"):
            # The owner's line goes this turn (their first word of buying): it answers the price as well.
            answer["not_a_shop"]["price"] = "first"
            done = PRICE_LINE
        elif not answer.get("converted") and not answer.get("shop_step"):
            invite = not invites
            answer["converted"] = needs.CONVERTED
            answer["not_a_shop"] = {
                "kind": need.kind, "noun": need.noun or "shop", "denies": False, "sorry": False,
                "slots": list(slots or []) if invite else [], "ask": invite, "price": "again",
            }
            answer["invited_to_meeting"] = invite
            answer["share_office_location"] = True
            answer["send"] = True
            done = PRICE_LINE
    if trimmed:
        answer["trimmed"] = trimmed
        if not answer.get("reply") and not answer.get("converted"):
            answer["send"] = False
    return done


def alert(conversation, chat, words: str = "") -> None:
    """The team hears that a shop buyer asked the price (Q43: a person takes it from here): the "wanted" kind, so the
    alert list gets it as well as the chat's own people; once a day per chat."""
    from django.utils import timezone

    from . import alerts

    who = (conversation.contact.display_name or "").strip() or f"+{conversation.contact.wa_id}"
    said = " ".join(str(words or "").split())[:200]
    alerts.raise_alert(
        kind="wanted",
        conversation=conversation,
        priority=ALERT_PRIORITY,
        title=f"{who} wants to buy a shop and asked the price",
        text=f"{who} (WhatsApp +{conversation.contact.wa_id}) wants to buy a shop and asked what it costs. The assistant "
        "gave no figure (we hold no sale prices) and invited them to the office. Please call them back with the options."
        + (f' Their words: "{said}"' if said else ""),
        dedupe_key=f"shop_buyer_price:{conversation.pk}:{timezone.now():%Y%m%d}",
        crm_url=alerts.crm_path(chat.crm_entity if chat else "", chat.crm_id if chat else None),
    )
