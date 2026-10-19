"""Who a shops chat's customer is (launch fixes, 2026-10-15): someone who wants no shop to rent.

The International City shops campaigns of 2026-10-15 reached many people who never wanted one of
these shops: 13 of the 32 who replied wanted a flat, a studio, a room or a villa, wanted to buy, or
said they never asked about a shop (chats 42-136 of the launch review). Matloob's rule for them,
the same day, over anything else: NO CUSTOMER IS EVER LOST. We have options of every kind
everywhere, not only these shops. Such a customer is thanked (with a short apology when we misread
them), told in their language that we have many options for exactly that across Dubai (never a
unit, building, price or availability), sent our office's location and invited to visit: "Visit our
office and we'll give you the best option.", with two free office slots like any invitation. A yes
books an office visit through the normal flow, in words that never mention shop types, the shop
list or driving to the shops; an alert tells the team (the Lead AI alert list and the lead's owner)
what they want, so a person can prepare options. The chat is not paused for it (a request for a
person or a call, a complaint or a broker still hands it over, as anywhere), it is never Lost and
never Junk, and its follow-ups are only about the visit.

This module reads the customer's own words, in English, Roman Urdu or Hindi, Arabic, Urdu script
and Devanagari, and writes the fixed words of that answer:

- ``detect``: what they want instead of a shop to rent (HOME, BUY, SELL, NEVER_ASKED), or None;
- ``rented_already``: "we got one", "already rented", "found one", "I already rented another shop": a
  shop they rented elsewhere (the build pack's "already rented" step: congratulate them, ask about a
  second shop), never with another shop asked for (``wants_another``: "need one more", "I want a second
  shop", "one more please"; never a want said with a no, "we don't need another one", nor "another" they
  rented);
- ``declines``: a no, "not now" or "not interested" anywhere in their words (never the shop list then);
- ``line``: the answer above, in six languages;
- ``drop_sale_claims`` / ``drop_shop_pitch``: the model's sentences that say our shops are only for
  rent or not for sale (unless SHOP FACTS says so), and in such a chat any word of shop types.

Plain functions on plain data, so the eval (leadai_eval) decides exactly as the engine does.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# What they want instead of a shop to rent (facts["need"]).
HOME = "home"  # a flat, studio, room, BHK, villa or any home
BUY = "buy"  # to buy, a shop or anything else
SELL = "sell"  # to sell, or let out, their own property
NEVER_ASKED = "never_asked"  # they never asked about a shop, or want none, and named nothing else
OTHER = "other"  # another kind of property or another area (the model's tag: schema.WRONG_NEED, OTHER_AREA)
KINDS = (HOME, BUY, SELL, NEVER_ASKED, OTHER)
# The facts this module keeps (code's own: the model's answer never carries them).
NEED = "need"
WANTED = "wanted"
# The fixed answer is "converted" (engine), like the other lines code writes.
CONVERTED = "not_a_shop"
RENTED_LINE = "rented_second_shop"

# The owner's defaults (Matloob, 2026-10-15), one line each to change later:
# - the alert that says what they want is high priority (a visit may be booked within hours);
ALERT_PRIORITY = "high"
# - the office pin goes with the first answer, besides the Maps link in the text;
SEND_PIN = True
# - a no from such a customer stops the invitations, but the lead is never Lost or Junk in Bitrix;
NEVER_LOST = True
# (Only the model's tag for such a customer, and an "unclear", are taken off the handover (engine.untag_need):
# a request for a person or a call, a complaint, a broker, a contract question and the rest still hand over.)
# - the segment code gives an answer the model called "other" (engine._shape would hand it over).
SEGMENTS = {HOME: "residential_tenant", BUY: "buyer", SELL: "owner", NEVER_ASKED: "residential_tenant", OTHER: "residential_tenant"}

# The model's handover reasons that only say "this customer wants no shop" (schema.NOT_A_SHOP_REASONS).
REASON_KINDS = {"wrong_need": OTHER, "wants_to_buy": BUY, "wants_to_sell": SELL, "never_asked": NEVER_ASKED, "other_area": OTHER}


@dataclass(frozen=True)
class Need:
    kind: str
    noun: str = ""  # a noun key of _NOUNS ("studio", "bhk:1", "shop"), '' when none was named
    denies: bool = False  # they said they never asked about a shop, or are not looking for one

    @property
    def what(self) -> str:
        """What they want, in English words for our team ("a studio", "to buy a shop")."""
        noun = noun_words(self.noun, "en")
        if self.kind == BUY:
            return f"to buy {noun}" if noun else "to buy"
        if self.kind == SELL:
            return f"to sell or let {_their(noun)}" if noun else "to sell or let their property"
        if self.kind == NEVER_ASKED:
            return "no shop (never asked about one)" if self.denies else "no shop"
        if self.kind == OTHER:
            return noun or "something other than these shops"
        return noun or "a home"


def _their(noun: str) -> str:
    """'a shop' -> 'their shop'."""
    return re.sub(r"^(?:a|an)\s+", "their ", noun)


def _flat(text: str) -> str:
    """One line, NFKC, lower case, straight apostrophes."""
    text = unicodedata.normalize("NFKC", str(text or "")).replace("’", "'").replace("‘", "'")
    return " ".join(text.lower().split())


# A home ---------------------------------------------------------------------------------------------

# Words before "studio" that make it a business ("a photo studio", "my salon studio").
_STUDIO_BUSINESS = (
    r"photo|photography|tattoo|dance|yoga|fitness|pilates|recording|music|design|beauty|nail|nails|hair|art|film|"
    r"video|podcast|gaming|makeup|make\s?up|salon|spa|massage|barber|lash|brow|piercing|printing|interior|"
    r"architecture|animation|sound|ceramic|pottery|gym|boxing|martial|crossfit|editing|media|content|bridal"
)
_NOUN_PATTERNS = (
    # (noun key, pattern); the first that matches names what they want. A key with its count ("bedroom:1") is that noun.
    ("bhk", re.compile(r"\b(\d)\s*-?\s*b\.?\s*h\.?\s*k\b")),
    ("bhk", re.compile(r"\bbhk\b")),
    ("bedroom", re.compile(r"\b(\d|one|two|three|four|five|single|double|ek)[\s-]*(?:bed\s*rooms?|bedrooms?|br|b/r)\b")),
    # Batch 2e (spec §1.2): "1 bed", "one bed", "1 bed hall" (a 1BHK), never a bed space, nor "a room with 1 bed".
    ("bedroom", re.compile(r"(?<!with )(?<!with a )\b(\d|one|two|three|four|five|ek)[\s-]*bed\b(?![\s-]*(?:spaces?|sharing|partitions?)\b)")),
    # Arabic: a room and a hall is a one-bedroom ("غرفة وصالة"), two rooms and a hall a two-bedroom; 2d read both as a room.
    ("bedroom:1", re.compile(r"(?:غرفة|غرفه)\s*(?:نوم\s*)?و\s*(?:صالة|صاله|صالون)")),
    ("bedroom:2", re.compile(r"(?:غرفتين|غرفتان)\s*(?:نوم\s*)?و\s*(?:صالة|صاله|صالون)")),
    ("bedroom", re.compile(r"([0-9٠-٩])\s*غرف\s*(?:نوم\s*)?و\s*(?:صالة|صاله|صالون)")),
    # Urdu and Devanagari: "ایک بیڈروم", "ون بیڈروم", "एक बेडरूम", "दो बेडरूम".
    ("bedroom", re.compile(r"(ایک|ون|دو|تین|[0-9۰-۹])\s*بیڈ\s*روم")),
    ("bedroom", re.compile(r"(एक|वन|दो|तीन|[0-9])\s*बेड\s*रूम")),
    ("studio_apartment", re.compile(r"\bstudio\s+(?:apartments?|flats?|units?|rooms?)\b|\b(?:apartment|flat)\s+studio\b")),
    ("studio", re.compile(r"\bstudios?\b")),
    # Never the building a shop is in: "under an apartment building", "a flats building", "near the villas"; nor the homes
    # above it ("apartments above the shop?": batch 2e review, a shop customer's question about the building).
    (
        "apartment",
        re.compile(
            r"\bapartments?\b(?!\s+(?:building|buildings|block|blocks|complex|tower|towers|area|community|above|upstairs|over\s+the|on\s+top))|\bapt\b"
        ),
    ),
    # Never "flat" the adjective (batch 2e review: "Is the rent flat or negotiable?", "Can you give it flat 30k?", "30k flat
    # final": _FLAT_ADJECTIVE_BEFORE reads the words before it), nor the flats above a shop ("flats above the shop?").
    (
        "flat",
        re.compile(
            r"\bflats?\b(?!\s*(?:rate|fee|fees|price|amount|discount|percent|%|\d+\s*%|screen|roof|surface|floor|building|buildings|block|area"
            r"|final\b|fixed\b|negotiable\b|or\s+negotiable\b|(?:aed\s*|dhs?\s*)?\d[\d,.]*\s*k?\s+(?:final|fixed|only|last|negotiable)\b"
            r"|above\b|upstairs\b|over\s+the\b|on\s+top\b))"
        ),
    ),
    ("villa", re.compile(r"\bvillas?\b(?!\s+(?:area|community|compound))")),
    ("townhouse", re.compile(r"\btown\s?houses?\b")),
    ("penthouse", re.compile(r"\bpent\s?houses?\b")),
    ("bed_space", re.compile(r"\bbed\s?spaces?\b|\bpartitions?\b|\bsharing\s+(?:room|accommodation|flat)\b|\bhostel\b")),
    # Never a room in the shop: "a room at the back", "a room inside the shop".
    ("room", re.compile(r"\brooms?\b(?!\s+(?:at|in|inside|behind|within)\s+(?:the\s+)?(?:back|shop|unit|store))")),
    ("house", re.compile(r"\b(?:a|an|one|independent|small|big|whole|family)\s+house\b|\bhouse\s+(?:for|on)\s+rent\b")),
    ("accommodation", re.compile(r"\baccommodation\b|\baccomodation\b")),
    # Roman Urdu / Hindi
    ("room", re.compile(r"\bkamr[aeiy]h?\b|\bkamre\b|\bkamron\b")),
    ("house", re.compile(r"\b(?:ghar|makaan|makan)\b\s+(?:chahiye|chaiye|chahye|chahie|chiye|chahiyay|dhoond\w*|kiray[ae]\w*|rent|ke\s+liye)")),
    # Devanagari
    ("flat", re.compile(r"फ्लैट|फ़्लैट|फ्लेट")),
    ("room", re.compile(r"कमरा|कमरे|रूम")),
    ("studio", re.compile(r"स्टूडियो")),
    ("apartment", re.compile(r"अपार्टमेंट")),
    ("villa", re.compile(r"विला")),
    ("house", re.compile(r"(?:घर|मकान)\s*(?:चाहिए|किराए|किराये)")),
    # Urdu script
    ("flat", re.compile(r"فلیٹ")),
    ("room", re.compile(r"کمرہ|کمرے|کمرا|کمروں")),
    ("studio", re.compile(r"اسٹوڈیو|سٹوڈیو")),
    ("apartment", re.compile(r"اپارٹمنٹ")),
    ("house", re.compile(r"(?:گھر|مکان)\s*(?:چاہیے|چاہئے|چاہیئے|کرائے|کرایہ)")),
    # Arabic
    ("flat", re.compile(r"شقة|شقه|شقق")),
    ("studio", re.compile(r"استوديو|ستوديو|ستديو|استديو")),
    ("room", re.compile(r"(?:غرفة|غرفه|غرف)(?!\s*(?:تخزين|اجتماعات|اجتماع|عرض|تبريد))")),
    ("villa", re.compile(r"فيلا|فلة|فلل")),
    ("house", re.compile(r"(?:بيت|منزل)\s*(?:للإيجار|للايجار|للعائلة|عائلي)|(?:أبحث|ابحث|أدور|ادور|أبي|ابي|أبغى|ابغى|أريد|اريد)\s+(?:عن\s+)?(?:بيت|منزل)")),
)
# "flat" the adjective, read in the words before it: an amount or the rent/price it describes ("30k flat", "the rent flat").
_FLAT_ADJECTIVE_BEFORE = re.compile(
    r"(?:\b\d[\d,.]*\s*k|\b\d{3,}[\d,]*|\b(?:aed|dhs?)\s*\d[\d,.]*\s*k?"
    r"|\b(?:the|your|this|that)\s+(?:rent|price|rate|amount|cost|fee)(?:\s+(?:is|be))?|\b(?:rent|price|rate|amount|cost|fee)\s+(?:is|be)"
    r"|\b(?:give|make|keep|do)\s+(?:it|me|us))\s+$"
)
# A shop customer's room in the shop (batch 2e review): "Does it have a small room inside?", "is there a room for my staff to
# sleep?": part of the shop, unless a wish for a home comes before it (_HOME_WISH: "I need a room for my staff").
_SHOP_ROOM = re.compile(
    r"\brooms?\s+inside\b|\brooms?\s+(?:for|to)\s+(?:(?:my|our|the)\s+)?(?:staff|workers?|employees?|labou?rs?|sleep|sleeping|rest|change|pray)\b"
    r"|\bsleeping\s+rooms?\b"
)
_HOME_WISH = re.compile(
    r"\b(?:need|needs|needed|want|wants|wanted|looking\s+for|look\s+for|searching\s+for|search\s+for|require|required|interested\s+in"
    r"|asked\s+for|asking\s+for|ask\s+for|enquir\w*|inquir\w*|prefer|chahiye|chaiye|chahie|chahye)\b"
    r"|أريد|اريد|أبحث|ابحث|أبغى|ابغى|محتاج|چاہیے|ڈھونڈ|चाहिए|ढूंढ|ढूँढ"
)
# A room that is no home: a store room, a showroom, room for the stock.
_NOT_A_HOME_ROOM = re.compile(
    r"\b(?:store|storage|stock|cold|show|meeting|changing|trial|waiting|back|server|prayer|staff|wash|rest|tea|class|"
    r"board|conference|fitting|dressing|machine|electric|pantry|kitchen|toilet|baby|treatment|massage|consultation|"
    r"interview|office|bath|shower|locker|utility|control|panel|mechanical|pump)\s+rooms?\b"
    r"|\b(?:enough|no|more|some|any|extra|much|little)\s+room\b|\broom\s+(?:for|to)\s+(?:storage|stock|goods|parking|cars?|my\s+stock|keep|store|grow|expand)\b"
)
# A whole residential word with no noun of its own: a home. Never "residential or commercial?", a question about
# the kind of property (review 2d).
_HOME_WORDS = re.compile(
    r"(?<!commercial or )(?<!commercial/)(?<!commercial )"
    r"\bresidential\b(?!\s+(?:area|areas|zone|zones|neighbou?rhoods?|community|communities|population|buildings?|towers?|side|crowd|footfall"
    r"|or\s+commercial|/\s*commercial|and\s+commercial))"
    r"|\bfor\s+(?:my\s+|our\s+)?(?:living|stay|staying|residence)\b|\bto\s+live\b|\bliving\s+(?:space|purpose|purposes|place|unit)\b"
    r"|\bplace\s+to\s+(?:live|stay)\b"
    # A family's home ("a family flat", "family accommodation"), never "with my family" or a family business.
    r"|\bfamily\s+(?:flat|room|apartment|villa|house|home|accommodation|stay|living|sharing|unit|place)\b"
    r"|\brehne\s+(?:ke\s+liye|ki\s+jagah|ka|ko)\b|\brehna\s+hai\b"
    r"|रहने\s+के\s+लिए|रहने\s+की\s+जगह"
    r"|رہنے\s+کے\s+(?:لیے|لئے)|رہائش"
    r"|للسكن|سكني|سكن\s+(?:عائلي|عائلة|للعائلة|عمال|موظفين)|(?:أبحث|ابحث|أدور|ادور|أبي|ابي|أبغى|ابغى|أريد|اريد)\s+(?:عن\s+)?سكن"
)
# "a shop, not a studio", "no flat", "لا أريد شقة": the home turned down is not the one they want.
_NOUN_NEGATED = re.compile(
    r"(?:\bnot|\bno|n't\s+\w+|\bnever|\binstead\s+of|\brather\s+than|\bnahi|\bnahin)\s+(?:a\s+|an\s+|the\s+|any\s+)?$"
    r"|(?:لا\s+(?:أريد|اريد|أبي|ابي|أبغى|ابغى|أحتاج|احتاج)|ما\s+(?:أبي|ابي|أبغى|ابغى|أريد|اريد|أحتاج|احتاج)|مش\s+(?:عايز|محتاج)|مو\s+(?:عايز|محتاج))\s+$"
)
# ... and said after the noun ("flat nahi", "फ्लैट नहीं", "فلیٹ نہیں": review 2d).
_NOUN_NEGATED_AFTER = re.compile(r"\s*(?:nahi|nahin|nhi|nai)\b|\s*(?:نہیں|नहीं|नही)")
# "near the apartments", "under an apartment building", "تحت الشقق": where the shop is, not what they want; and their own
# place ("a 1BR near my shop", "a shop close to our flat": batch 2e) is where, never what.
_NOUN_PLACE = re.compile(
    r"\b(?:near|under|beside|behind|next\s+to|opposite|facing|between|around|among|above|below|close\s+to)\s+"
    r"(?:the\s+|a\s+|an\s+|some\s+|my\s+|our\s+|his\s+|her\s+|their\s+)?$"
    r"|(?:تحت|فوق|قرب|قريب\s+من|بجانب|جنب|عند|بين)\s+$"
)
# "Villa maintenance", "apartment cleaning services": a trade of theirs, not a home they want (review 2d).
_NOUN_TRADE_AFTER = re.compile(
    r"\s+(?:maintenance|cleaning|cleaners|renovations?|repairs?|painting|services?|management|movers|moving|shifting|decor|decoration"
    r"|interiors?|furniture|supplies|agency|brokerage|contracting|contractors?)\b"
)
# "we rent out flats", "I sell villas": their trade, or their own property the model asks about, never a home they want.
_NOUN_TRADED_BEFORE = re.compile(
    r"\b(?:sell|sells|selling|rent\s+out|rents\s+out|renting\s+out|lease\s+out|leasing\s+out|let\s+out|letting\s+out|deal\s+in|dealing\s+in)"
    r"\s+(?:\w+\s+)?$"
)
# "my studio is in Deira", "I have a studio flat", "I live in a studio": the home they have, not one they want.
_NOUN_OWNED = re.compile(
    r"\b(?:my|our|mera|meri|mere|hamara|hamari|hamare)\s+(?:own\s+)?(?:(?!(?:liye|lie|liay|lye)\b)\w+\s+)?$"  # never "mere liye flat"
    r"|\b(?:i|we)\s+(?:already\s+)?(?:have|own|run|'ve\s+got|have\s+got)\s+(?:a\s+|an\s+|one\s+)?(?:\w+\s+){0,2}$"
    r"|\b(?:i|we)(?:'m|'re|\s+am|\s+are)?\s+(?:live|living|stay|staying)\s+in\s+(?:a\s+|an\s+|the\s+|my\s+|our\s+)?(?:\w+\s+)?$"
)
# ...unless it is what they need: "I have a studio requirement", "my flat search".
_NOUN_WANTED_AFTER = re.compile(
    r"\s*(?:apartment\s+|flat\s+|room\s+)?(?:requirement|requirment|requirements|need|needed|enquiry|inquiry|search|hunt|chahiye|chaiye)\b"
)
_STUDIO_FOR_BUSINESS = re.compile(
    rf"\b(?:{_STUDIO_BUSINESS})\s+studios?\b"
    rf"|\bstudios?\s+(?:business|shop|for\s+my\s+business|for\s+(?:my\s+)?(?:{_STUDIO_BUSINESS}))\b"
    # "I want a shop for my studio", "I want shop for studio": a shop, for their studio business.
    r"|\bshops?\b[^.?!\n]{0,20}\bfor\s+(?:(?:my|our|a|the)\s+)?studios?\b"
)


def wishes(text: str) -> bool:
    """Their words carry a wish (need, want, looking for, asked for, chahiye, أريد ...), not said with a no before it."""
    flat = _flat(text)
    return any(not _NEGATED.search(flat[: match.start()]) for match in _HOME_WISH.finditer(flat))


def _home_noun(text: str) -> str:
    """The home they want, as a noun key ("studio", "bhk:1", "room"), else ''."""
    for key, pattern in _NOUN_PATTERNS:
        for match in pattern.finditer(text):
            if key == "studio" and _STUDIO_FOR_BUSINESS.search(text):
                break  # "a shop for my photo studio": a business, not a home
            if key == "room" and _NOT_A_HOME_ROOM.search(text[max(0, match.start() - 16) : match.end() + 24]):
                continue
            before = text[: match.start()]
            if key == "room" and _SHOP_ROOM.search(text[max(0, match.start() - 10) : match.end() + 30]) and not _HOME_WISH.search(before):
                continue  # "Does it have a small room inside?", "a room for my staff to sleep?": the shop's own room
            if key == "flat" and _FLAT_ADJECTIVE_BEFORE.search(before):
                continue  # "the rent flat or negotiable?", "30k flat final": flat the adjective
            owned = _NOUN_OWNED.search(before) and not _NOUN_WANTED_AFTER.match(text, match.end())
            if _NOUN_NEGATED.search(before) or _NOUN_PLACE.search(before) or owned:
                continue  # "a shop, not a studio"; "near the apartments"; "my studio is in Deira"
            if _NOUN_NEGATED_AFTER.match(text, match.end()) or _NOUN_TRADE_AFTER.match(text, match.end()) or _NOUN_TRADED_BEFORE.search(before):
                continue  # "flat nahi"; "Villa maintenance"; "we rent out flats"
            if key == "bhk" and match.groups():
                return f"bhk:{match.group(1)}"
            if key == "bedroom":
                return f"bedroom:{_count(match.group(1))}"
            return key
    return "home" if _HOME_WORDS.search(text) else ""


_COUNTS = {
    "one": "1", "single": "1", "two": "2", "double": "2", "three": "3", "four": "4", "five": "5",
    # Roman Urdu / Hindi, Urdu script and Devanagari (batch 2e): "ek bedroom", "ایک بیڈروم", "दो बेडरूम".
    "ek": "1", "ایک": "1", "ون": "1", "دو": "2", "تین": "3", "एक": "1", "वन": "1", "दो": "2", "तीन": "3",
}


def _count(word: str) -> str:
    """A count as digits: "one" and "ek" are 1; a digit of any script ("٣", "۲") is itself."""
    if word in _COUNTS:
        return _COUNTS[word]
    if len(word) == 1 and word.isdigit():
        return str(unicodedata.digit(word))
    return word


# To buy, to sell ----------------------------------------------------------------------------------

# A shop customer buys and sells goods all day ("I sell mobile phones", "we buy and sell used cars",
# "hum kapde bechte hain"): only a property, or a plain wish to buy or sell with nothing after it,
# is a buyer or an owner.
# Never a purchase or a sale: "I don't want to buy", "rent, not buy", "لا أريد شراء محل".
_NEGATED = re.compile(r"(?:\bnot|n't|\bnever|\bwithout|\bnahi|\bnahin|\bnhi|\bmat|\bلا|\bلم|\bمش|\bليس|\bغير)\s+(?:\w+\s+){0,3}$|\bno\s+$")
# Trading in goods ("buy and sell", "أشتري وأبيع"), read as no word of either.
_TRADING = re.compile(
    r"\b(?:buy|buying)\s*(?:and|&|n|/|or|\+)\s*(?:sell|selling)\b|\b(?:sell|selling)\s*(?:and|&|n|/|or|\+)\s*(?:buy|buying)\b"
    r"|(?:أشتري|اشتري|نشتري|شراء)\s*و\s*(?:أبيع|ابيع|نبيع|بيع)|(?:أبيع|ابيع|نبيع|بيع)\s*و\s*(?:أشتري|اشتري|نشتري|شراء)"
)
_PROPERTY = (
    r"(?:shops?|units?|propert(?:y|ies)|flats?|studios?|villas?|apartments?|houses?|homes?|offices?|lands?|plots?|townhouses?|"
    r"penthouses?|warehouses?|buildings?|real\s+estate|\d?\s*-?\s*bhk|commercial|retail|space"
    # A bedroom count is a home too (batch 2e review: "I want to buy a one-bedroom", "I want to purchase 1BR flat", "1BR, to
    # buy" were read as a home to rent, and a buyer was told the rent).
    r"|(?:(?:\d|one|two|three|four|five|single|double|ek)\s*-?\s*)?(?:bed\s*rooms?|bedrooms?|br|b/r)|(?:\d|one|ek)\s*-?\s*bed)\b"
    # Never what is in it: "buy the shop furniture", "sell my shop stock"; nor goods named after a home ("I want to sell
    # home appliances", "home made food": review 2d).
    r"(?!\s+(?:furniture|fixtures?|fittings?|stock|goods|equipment|items?|products?|licen[cs]es?|photos?|pictures?|pics|keys?|deposit|"
    r"things|materials?|supplies|interior|decor|signs?|signboards?|boards?|shel(?:f|ves)|racks?|counters?|business|"
    r"appliances?|electronics|accessories|textiles|made|based|delivery|services?|care|cleaning|food|kitchen\s+items?"
    # "I want to buy a bedroom set" (a bedroom with no count is furniture's as often as a home's).
    r"|sets?|sheets?|linens?|covers?)\b)"
)
_FILL = (
    r"(?:(?:a|an|the|this|that|these|those|one|some|any|your|ur|small|big|large|new|ready|good|cheap|nice|second|another|"
    r"commercial|retail|residential|\d+)\s+){0,3}"
)
# What may follow "I want to buy" with nothing bought: the end, or a word that buys nothing ("in Dubai", "please").
_TAIL = (
    r"(?=\s*$|\s*[.!?,;:)\]]|\s+(?:not|and|but|in|at|from|here|there|please|pls|plz|only|now|sir|bro|thanks|thank|instead|rather|"
    r"first|soon|urgently|asap|if|because|bcz|bcoz|coz|as|ok|okay|also|too|ji|madam|maam|dear)\b|\s+or\b(?!\s+(?:rent|renting|lease|leasing)\b))"
)
# "I want to sell" with nothing after it ("I want to sell here" is a shop customer's business).
_SELL_TAIL = r"(?=\s*$|\s*[.!?,;:)\]]|\s+(?:please|pls|plz|sir|bro|madam|maam|dear|ji|now|asap|urgently|soon)\b)"
_WISH = r"(?:want|wants|wanted|wanna|like|looking|plan|plans|planning|interested|intend|intending|thinking|ready|wish|prefer|trying)"
_BUY = re.compile(
    # "To buy", "Purchase", "sale": the whole message.
    r"^\W*(?:to\s+|for\s+)?(?:buy|buying|purchase|purchasing|sale|investor|investment)\W*$"
    # "buy a shop", "I want purchase shop", "purchasing 2 units", "can I buy it?"
    rf"|\b(?:buy|buying|purchase|purchasing)\s+{_FILL}(?:{_PROPERTY}|(?:it|one|them|this|these|those){_TAIL})"
    # "I want to buy", "interested in buying", "looking to purchase in Dubai"
    rf"|\b{_WISH}\s+(?:to\s+|in\s+|of\s+|for\s+|on\s+)?(?:buy|buying|purchase|purchasing){_TAIL}"
    # "Is it for sale?", "shops for sale", "a shop for purchase", "a shop to buy" (never "for rent or for sale?", a question)
    r"|(?<!\brent\sor\s)\bfor\s+(?:sale|purchase|buying)\b(?!\s+or\s+(?:for\s+)?(?:rent|lease)\b)"
    # "a studio to buy", and as an answer to our "a studio or a one-bedroom, to rent or to buy?": "studio, to buy", "buy, 1BR"
    rf"|\b{_PROPERTY}\s*[,/-]?\s*to\s+(?:buy|purchase)\b|\b(?:buy|buying|purchase|purchasing)\s*[,/-]\s*{_FILL}{_PROPERTY}"
    # "Do you sell shops?", "are you selling?"
    rf"|\b(?:do|does|are|is|can|could|will|would)\s+(?:you|u|ya|they|these|those|the\s+shops?|this|it)\s+(?:\w+\s+)?(?:sell|selling)"
    rf"(?:{_TAIL}|\s+(?:me\s+)?{_FILL}{_PROPERTY})"
    # "to own a shop", "I am an investor", "invest in a shop", "for investment", "freehold". Never a bare
    # "investment": a chain message offers an "investment group" (rules.looks_like_spam's own word).
    rf"|\b(?:to|wanna)\s+own\s+{_FILL}{_PROPERTY}|\b(?:to|wanna)\s+own{_TAIL}"
    r"|\b(?:i'?m|i\s+am|we\s+are|we'?re|as)\s+(?:a\s+|an\s+)?(?:\w+\s+)?(?:buyer|investor)s?\b"
    rf"|\b(?:invest|investing)\s+(?:in\s+|on\s+)?{_FILL}{_PROPERTY}|\b{_WISH}\s+(?:to\s+|in\s+)?(?:invest|investing)(?=\s*$|\s*[.!?,;:])"
    r"|\bfor\s+investment\b|\binvestment\s+purpose|\bas\s+(?:an\s+)?investment\b|\bfreehold\b"
    # Roman Urdu / Hindi: "shop kharidni hai", "dukaan khareedni hai", "kharidna hai" (never "shop nahi kharidni")
    r"|\b(?:shops?|dukaa?n\w*|flats?|ghar|makaa?n|property|villa|plot|zameen|office|apartment|studio|(?:\d\s*-?\s*)?(?:bhk|br|bed\s*rooms?|bedrooms?))\s+"
    r"(?:(?!(?:nahi|nahin|nhi|nai|na|mat)\b)\w+\s+)?kh[ae]+r[ie]+d\w*(?!\s+(?:nahi|nahin|nhi|nai)\b)"
    r"|^\W*(?:mujhe\s+|muje\s+|hume\s+|humein\s+|hamein\s+|main\s+|mein\s+|hum\s+)?kh[ae]+r[ie]+d(?:na|ni|ne)\s+(?:hai|hain|chahta|chahti|chahte|chahiye)\b"
    # Urdu, Devanagari: "دکان خریدنی ہے", "दुकान खरीदनी है"
    r"|(?:دکان|شاپ|فلیٹ|گھر|مکان|پراپرٹی|پلاٹ|اپارٹمنٹ)\s+(?:(?!نہیں|نہ\s)\S+\s+)?خرید(?!\S*\s+نہیں)"
    r"|(?:दुकान|शॉप|फ्लैट|घर|मकान|प्रॉपर्टी|प्लॉट)\s+(?:(?!नहीं|न\s)\S+\s+)?(?:खरीद|ख़रीद)(?!\S*\s+नहीं)"
    # Arabic: "أريد شراء محل", "هل المحلات للبيع؟", "للتمليك"
    r"|(?:شراء|أشتري|اشتري|نشتري|للشراء)\s+(?:\S+\s+)?(?:محل|محلات|دكان|عقار|شقة|شقه|فيلا|أرض|ارض|مكتب|وحدة|وحده|بيت|منزل|استوديو)"
    r"|للبيع|للتمليك|تمليك|أتملك|اتملك|للاستثمار|أستثمر|نستثمر|استثمر\s+في"
)
_SELL = re.compile(
    # "Sell", "to sell": the whole message.
    r"^\W*(?:to\s+)?(?:sell|selling)\W*$"
    # "sell my shop", "selling my flat", "rent out our 2 shops"
    r"|\b(?:sell|selling|sale\s+of|rent\s+out|renting\s+out|lease\s+out|leasing\s+out|let\s+out|letting\s+out)\s+(?:off\s+)?(?:my|our)\s+(?:own\s+)?"
    rf"{_FILL}{_PROPERTY}"
    # "I want to sell", "looking to sell a shop", "planning to rent out"
    rf"|\b(?:{_WISH}|need|needs)\s+(?:to\s+|in\s+|of\s+|for\s+|on\s+)?(?:sell|selling|rent\s+out|renting\s+out|lease\s+out|let\s+out)"
    rf"(?:{_SELL_TAIL}|\s+(?:it|one|them|this|that){_SELL_TAIL}|\s+(?:off\s+)?(?:my\s+|our\s+)?{_FILL}{_PROPERTY})"
    # "I am the owner, I want to rent it", "I'm owner of a studio", "owner here" (the first mixed campaign, 2026-10-19,
    # chat 50020: an owner offering a studio got tenant photos and a viewing slot).
    r"|\b(?:i\s*am|i'm|im|we\s*are|we're)\s+(?:the\s+|an?\s+)?(?:owner|landlord|landlady)s?\b(?!\s+of\s+(?:a\s+)?(?:company|business|shop\s+licen))"
    r"|\b(?:owner|landlord)\s+here\b|\bmain\s+(?:owner|malik)\s+hoo?n\b|\bأنا\s+(?:المالك|صاحب\s+(?:الشقة|الاستوديو|العقار))"
    # "my villa is for sale", "I have a shop for sale", "I have a flat for rent"
    r"|\b(?:my|our)\b[^.?!]{0,30}\b(?:for|on)\s+sale\b"
    r"|\b(?:i|we)\s+(?:have|got|own)\s+(?:a\s+|an\s+|one\s+|two\s+|\d+\s+)?(?:\w+\s+){0,2}?(?:for|on)\s+sale\b"
    rf"|\b(?:i|we)\s+(?:have|own)\s+(?:a\s+|an\s+|one\s+|two\s+|\d+\s+)?(?:(?:small|big|new|commercial|retail|residential)\s+)?{_PROPERTY}"
    r"\s+(?:for|to)\s+(?:rent|let|lease)(?:\s+out)?\b"
    # Roman Urdu / Hindi: "apni shop bechni hai", "flat kiraye par dena hai" (never "mujhe shop kiraye pe de do")
    r"|\b(?:shops?|dukaa?n\w*|flats?|ghar|makaa?n|property|villa|plot|zameen|office|apartment|studio)\s+"
    r"(?:(?!(?:nahi|nahin|nhi|nai|na|mat)\b)\w+\s+)?(?:bech\w*|farokht)\b(?!\s+(?:nahi|nahin|nhi|nai)\b)"
    r"|\b(?:shops?|dukaa?n\w*|flats?|ghar|makaa?n|property|villa|apartment|studio|office)\s+(?:\w+\s+){0,2}?kiraye?\s+(?:par|pe|pr)\s+"
    r"(?:dena|deni|dene|de\s+(?:dena|deni|di|diya))\b"
    # Urdu, Devanagari: "دکان بیچنی ہے", "दुकान बेचनी है"
    r"|(?:دکان|شاپ|فلیٹ|گھر|مکان|پراپرٹی|پلاٹ|اپارٹمنٹ)\s+(?:(?!نہیں|نہ\s)\S+\s+)?(?:بیچ|فروخت|کرائے\s+پر\s+دین[اےی])(?!\S*\s+نہیں)"
    r"|(?:दुकान|शॉप|फ्लैट|घर|मकान|प्रॉपर्टी|प्लॉट)\s+(?:(?!नहीं|न\s)\S+\s+)?(?:बेच|किराए\s+पर\s+दे(?:ना|नी|ने))(?!\S*\s+नहीं)"
    # Arabic: "أريد بيع محلي", "أبيع محل", "محلي للبيع" (never "أبيع جوالات")
    r"|(?:أبيع|ابيع|نبيع|بيع|أؤجر|اؤجر|نؤجر|تأجير)\s+(?:محلي|محلنا|شقتي|شقتنا|عقاري|عقارنا|فيلتي|بيتي|منزلي|أرضي|مكتبي)"
    r"|(?:أبيع|ابيع|نبيع)\s+(?:\S+\s+)?(?:محل|محلات|دكان|عقار|شقة|شقه|فيلا|أرض|ارض|مكتب|بيت|منزل)"
    r"|(?:محلي|محلنا|شقتي|شقتنا|عقاري|عقارنا|فيلتي|بيتي|منزلي|أرضي|مكتبي)\s+(?:\S+\s+)?للبيع"
)


def _unnegated(pattern, text: str) -> bool:
    text = _TRADING.sub(" trading ", text)
    for match in pattern.finditer(text):
        if _NEGATED.search(text[: match.start()]):
            continue
        return True
    return False


# No shop at all -----------------------------------------------------------------------------------

_SHOP = r"(?:shops?|dukaa?n\w*|stores?)"
# What may follow "not looking for shops" when it turns down every shop: the end of what they say, or a
# word that adds nothing ("please", "at all", "but", "I need a studio"). Never "not looking for shops
# near the road" or "I don't want a shop on the main road": a shop customer choosing one.
# Not "now", "yet" or "anymore": "I don't need a shop now" puts the offer off, it is no other need.
_CLAUSE_END = (
    r"(?=\s*$|\s*[.!?,;:)\]]|\s+(?:please|pls|plz|sir|bro|madam|maam|dear|ji|thanks|thank|needed|required|wanted|at\s+all|"
    r"but|i|i'?m|we|only|again|bhai|yaar|habibi|and|or|because|bcz|as|actually|brother|boss|anywhere|from\s+(?:you|u)|for\s+(?:me|us))\b)"
)
# The words between "not looking" and "shops" that name no kind of shop ("for", "any", "about a"):
# never "not looking for a big shop".
_ABOUT = (
    r"(?:\s+(?:for|about|regarding|abt|any|anything|any\s+thing|something|a|an|the|some|these|those|your|ur|ya|in|of|on|to|into|at|"
    r"more|other|such|you|u|from|with|me|us))*"
)
# "I did not ask for shop photos" asked about the photos.
_SHOP_THING = r"(?!\s+(?:photos?|pictures?|pics|images?|videos?|rent|price|prices|size|sizes|details?|types?|number|owner|layout|plan|keys?|visit|viewing)\b)"
_NO_SHOP = re.compile(
    # "I did not ask shop", "No I didn't look for shop", "I never asked about a shop", "I did not ask for shop in International City"
    r"\b(?:did\s*n'?t|didnt|did\s+not|never|have\s*n'?t|havent|have\s+not|has\s*n'?t|was\s+not|wasn'?t)\s+"
    r"(?:\w+\s+){0,2}(?:ask(?:ed|ing)?|look(?:ed|ing)?|enquir\w*|inquir\w*|request\w*|search\w*|appl(?:y|ied)|need(?:ed)?|want(?:ed)?|"
    r"say|said|mention\w*|talk\w*|writ(?:e|ten)|wrote|contact\w*|message\w*|interested|registered|"
    rf"submit\w*)\b{_ABOUT}\s+{_SHOP}\b{_SHOP_THING}"
    # "AM NOT LOOKING FOR SHOPS", "not interested in shops", "I'm not in need of a shop"
    r"|\b(?:not|am\s+not|i'?m\s+not)\s+(?:\w+\s+){0,2}(?:look(?:ing)?|search\w*|need(?:ed|ing)?|want(?:ed|ing)?|interested|ask(?:ed|ing)?)\b"
    rf"{_ABOUT}\s+{_SHOP}\b{_CLAUSE_END}"
    # "I dont need shops", "we do not want a shop"
    rf"|\b(?:do\s*n'?t|dont|do\s+not|does\s*n'?t|doesnt)\s+(?:\w+\s+){{0,1}}(?:need|want|require|like)\b{_ABOUT}\s+{_SHOP}\b{_CLAUSE_END}"
    # "No shop", "no shops please" (a message or a clause that opens with it), "no need of shop"
    rf"|(?:^|[.!?,;\n]\s*)no\s+(?:need\s+(?:of|for)\s+(?:a\s+|any\s+)?)?{_SHOP}\b{_CLAUSE_END}"
    # "Not shops", "studio only not shop", "not a shop"
    rf"|\bnot\s+(?:a\s+|any\s+|the\s+)?{_SHOP}\b{_CLAUSE_END}"
    rf"|\b{_SHOP}\s+(?:is\s+|are\s+)?not\s+(?:needed|required|wanted|for\s+me|for\s+us)\b"
    rf"|\bwhy\s+(?:are\s+|r\s+)?(?:you|u)\s+(?:sending|asking|messaging|texting)\b[^.?!\n]{{0,20}}?\b{_SHOP}"
    # Roman Urdu / Hindi: "shop nahi chahiye", "mujhe dukan nahi chahiye", "maine shop nahi poochi" (never
    # "abhi shop nahi chahiye", which is a "not now")
    rf"|(?<!\babhi\s)(?<!\babi\s)\b{_SHOP}\s+(?:(?!(?:abhi|abi|filhal|filhaal)\b)\w+\s+)?(?:nahi|nahin|nhi|nai)\s+"
    r"(?:chahiye|chaiye|chahye|chahie|chiye|chahiyay|chahta|chahti|chahte|"
    r"poochi|puchi|poocha|pucha|mangi|maangi|kaha|bola|dekh\w*|lena|leni)\b"
    rf"|\b{_SHOP}\s+(?:nahi|nahin|nhi|nai)\s*$"
    # Devanagari, Urdu, Arabic
    r"|(?:दुकान|शॉप)\s*(?:नहीं|नही)\s*(?:चाहिए|चाहिये|पूछ|मांग|ली)?|(?:दुकान|शॉप)\s+की\s+(?:ज़रूरत|जरूरत)\s+नहीं"
    r"|(?:دکان|شاپ)\s*(?:نہیں|نہی)|(?:دکان|شاپ)\s+کی\s+ضرورت\s+نہیں"
    r"|(?:لا\s+أريد|لا\s+اريد|ما\s+أبي|ما\s+ابي|ما\s+أبغى|ما\s+ابغى|مش\s+عايز|مو\s+عايز|مش\s+محتاج|لا\s+أحتاج|لا\s+احتاج|لست\s+بحاجة"
    r"|لم\s+أطلب|لم\s+اطلب|ما\s+طلبت|ما\s+سألت|لم\s+أسأل|لم\s+اسأل|لست\s+أبحث|لست\s+ابحث|ما\s+أدور|ما\s+ادور|مب\s+محتاج|ما\s+احتاج)"
    r"\s+(?:\S+\s+){0,2}?(?:محل|محلات|دكان|دكاكين)"
)


def denies_shop(text: str) -> bool:
    """They say they never asked about a shop, or want none ("No shop", "I did not ask shop",
    "AM NOT LOOKING FOR SHOPS", "shop nahi chahiye")."""
    return bool(_NO_SHOP.search(_flat(text)))


# A shop spoken of, in any of our languages (a shop customer's burst: "I need a shop with a room", "shop chahiye, flat
# nahi", "أبحث عن محل، لا أريد شقة").
_SHOP_SPOKEN = re.compile(rf"\b{_SHOP}\b|محل|محلات|دكان|دكاكين|دکان|دکانیں|दुकान|शॉप")


def _speaks_of_a_shop(text: str) -> bool:
    """A shop is what the words speak of, never where something else is ("a studio near the shops")."""
    return any(not _NOUN_PLACE.search(text[: match.start()]) for match in _SHOP_SPOKEN.finditer(text))


def about_a_shop(texts) -> bool:
    """Their burst speaks of a shop and nowhere turns shops down: a home word in it is the shop's own room, a home they
    turn down or where the shop is, never a home they want (review 2d: "I need a shop with a room for my salon", "kya
    shop me kamra hai?", "mujhe shop chahiye, flat nahi", "أريد محل مع غرفة" all got the not-a-shop line). A shop as
    the place of a home ("a studio near the shops") is none."""
    words = [_flat(text) for text in (texts or ()) if str(text or "").strip()]
    return any(_speaks_of_a_shop(text) for text in words) and not any(denies_shop(text) for text in words)


# A shop asked for in so many words ("No, I want a SHOP for my salon", "shop chahiye", "send me the shop types",
# "أريد محل", "دکان چاہیے"), never turned down ("I don't want a shop on the main road").
_WANT_A_SHOP = re.compile(
    rf"\b(?:need|needs|want|wants|wanted|looking\s+for|look\s+for|searching\s+for|require|interested\s+in|send\s+me|show\s+me)"
    rf"(?:\s+\w+){{0,3}}?\s+{_SHOP}\b"
    rf"|\b{_SHOP}\s+(?:\w+\s+){{0,2}}?(?:chahiye|chaiye|chahye|chahie|chiye|chahiyay)\b"
    r"|(?:أريد|اريد|أبحث\s+عن|ابحث\s+عن|أبغى|ابغى|أبي|ابي|محتاج)\s+(?:\S+\s+){0,2}?(?:محل|محلات|دكان)"
    r"|(?:دکان|شاپ)\s+(?:\S+\s+){0,2}?(?:چاہیے|چاہئے)|(?:दुकान|शॉप)\s+(?:\S+\s+){0,2}?चाहिए"
)


def wants_a_shop(texts) -> bool:
    """They ask for a shop to rent in so many words, and nothing they say turns shops down or wants something else: a
    chat that read them as wanting a home was wrong (engine.who_they_are forgets that want: review 2d)."""
    words = [_flat(text) for text in (texts or ()) if str(text or "").strip()]
    if not words or any(denies_shop(text) for text in words):
        return False
    for text in words:
        for match in _WANT_A_SHOP.finditer(text):
            if not _NEGATED.search(text[: match.start()]) and "nahi" not in match.group(0) and "نہیں" not in match.group(0):
                return True
    return False


def detect(texts) -> Need | None:
    """What the customer wants instead of a shop to rent, from their own words in this burst (a
    voice note's transcript and a tap's label among them), else None. To buy or to sell first
    (they name the property with it), then a home, then "no shop" alone. A burst about a shop
    (about_a_shop) names no home they want."""
    words = [_flat(text) for text in (texts or ()) if str(text or "").strip()]
    if not words:
        return None
    joined = "\n".join(words)
    denies = any(denies_shop(text) for text in words)
    noun = ""
    if not about_a_shop(words):
        for text in words:
            noun = _home_noun(text)
            if noun:
                break
    if any(_unnegated(_SELL, text) for text in words):
        return Need(SELL, noun or ("shop" if re.search(rf"\b{_SHOP}|محل|دكان|دکان|दुकान", joined) else ""), denies)
    if any(_unnegated(_BUY, text) for text in words):
        return Need(BUY, noun or ("shop" if re.search(rf"\b{_SHOP}|محل|دكان|دکان|दुकान", joined) else ""), denies)
    if noun:
        return Need(HOME, noun, denies)
    if denies:
        return Need(NEVER_ASKED, "", True)
    return None


def from_reason(reason: str, facts: dict | None = None) -> Need | None:
    """The model's tag for a customer who wants no shop (schema.NOT_A_SHOP_REASONS), as a Need: the
    property they named in facts, when there is one."""
    kind = REASON_KINDS.get(str(reason or ""))
    if kind is None:
        return None
    named = noun_of((facts or {}).get("property_type"))
    if kind == OTHER and named and named != "shop":
        kind = HOME
    if kind in (HOME, OTHER) and named == "shop":
        named = ""  # a shop is no other property: what they want is somewhere else (another area)
    return Need(kind, "" if kind == NEVER_ASKED else named, kind == NEVER_ASKED)


def of(facts: dict | None) -> Need | None:
    """The chat's need as its facts keep it (facts["need"]; facts["wanted"] names the property), else None."""
    facts = facts or {}
    kind = facts.get(NEED)
    if kind not in KINDS:
        return None
    wanted = _flat(facts.get(WANTED) or "")
    noun = _home_noun(wanted)
    if noun == "home" and not wanted.startswith("a home"):
        noun = ""
    if not noun and re.search(rf"\b{_SHOP}", wanted):
        noun = "shop"
    return Need(kind, noun, kind == NEVER_ASKED)


def noun_of(property_type) -> str:
    """The noun key a property type names ("studio", "bhk:2", "shop"), '' for none or a bare home."""
    text = _flat(property_type or "")
    if not text:
        return ""
    named = _home_noun(text)
    if named and named != "home":
        return named
    return "shop" if re.search(rf"\b{_SHOP}", text) else ""


def is_home_type(property_type) -> bool:
    """facts.property_type names a home ("studio", "1BHK", "apartment"), not a shop."""
    text = _flat(property_type or "")
    return bool(text) and not re.search(r"\bshops?\b|\bretail\b|\bshowroom\b", text) and bool(_home_noun(text))


def wants_no_shop(facts: dict | None) -> bool:
    """What the chat's facts know says the customer wants no shop to rent (shop_flow.shops_unwanted's
    test of what is known, for the follow-ups): their need (facts.need), a home as property_type, intent
    buy or sell, or a home recorded as the business activity ("apartment studio", "room": launch chats 44
    and 49 kept it so before who_they_are cleared it)."""
    facts = facts or {}
    if of(facts) is not None or facts.get("intent") in (BUY, SELL) or is_home_type(facts.get("property_type")):
        return True
    activity = facts.get("business_activity")
    return isinstance(activity, str) and bool(activity.strip()) and detect([activity]) is not None


# Already rented -----------------------------------------------------------------------------------

# What may follow "we got one" ("we got one", "found one already", "rented a shop in Deira"), never
# "I got one question" or "I got the shop photos".
_END = (
    r"(?=\s*$|\s*[.!,;\n]|\s+(?:already|alhamdulillah|thanks|thank|bro|sir|now|last|recently|yesterday|today|elsewhere|"
    r"somewhere|from|in|near|at|but|and|so|for\s+(?:my|our|us|me)))"
)
# Never "it": "Got it" and "already got it" say they understood.
_RENTED_OBJECT = r"(?:a\s+(?:new\s+)?shop|the\s+shop|another\s+(?:shop|one)|one|a\s+(?:place|space|unit))"
_RENTED = re.compile(
    rf"\b(?:already|alredy|allready|allredy)\s+(?:have\s+|'ve\s+)?(?:rented|got|taken|took|found|bought|leased)(?:\s+{_RENTED_OBJECT})?{_END}"
    rf"|\b(?:rented|taken|took|found|leased)\s+(?:a\s+shop\s+|one\s+|the\s+shop\s+)?already\b"
    rf"|\b(?:we|i)\s+(?:have\s+|'ve\s+|ve\s+|already\s+|just\s+|have\s+already\s+)?(?:got|found|rented|taken|took|leased|bought)\s+"
    rf"{_RENTED_OBJECT}(?:\s+already)?{_END}"
    rf"|\b(?:i|we)\s+already\s+have\s+(?:a\s+shop|one|the\s+shop){_END}"
    rf"|^\W*(?:got|found|rented|taken)\s+(?:one|a\s+shop|the\s+shop)(?:\s+already)?{_END}"
    r"|\b(?:found|got|rented)\s+(?:a\s+)?(?:shop|place|space|unit)\s+(?:elsewhere|somewhere\s+else|already|in\s+another)\b"
    # Roman Urdu / Hindi: "shop mil gayi", "dukan le li", "pehle hi le li"
    rf"|\b{_SHOP}\s+(?:mil|le)\s+(?:gayi|gai|gaya|li|liya|lia|chuke|chuka|chuki)\b|\bpehle\s+(?:hi|se)\s+(?:le|mil)\s+(?:li|liya|lia|gayi|gai|chuke|chuka)\b"
    r"|(?:دکان|شاپ)\s+(?:مل|لے)\s+(?:گئی|لی|چکے)|(?:दुकान|शॉप)\s+(?:मिल|ले)\s+(?:गई|ली|चुके)"
    r"|(?:استأجرت|استاجرت|أجرت|اجرت|لقيت|وجدت|حصلت\s+على|أخذت|اخذت|استأجرنا|استاجرنا|لقينا)\s+(?:محل|محلا|محلاً|واحد|دكان)"
)


# What a shop customer who has a shop, or found one, says when they still want ours (review 2d: "We already have a shop,
# need one more", "I found one at 30k", "we found a shop in Deira at 30k is yours cheaper" were read as rented, and
# their next "No, ..." closed the lead as Lost): another shop wanted, or a price weighed against ours. A want is a verb of
# wanting, then one more, another, a second, an additional, extra or bigger one ("need one more", "I want a second shop",
# "we need an additional shop", "need a bigger one"), never "another" for anything else ("another time").
_MORE_SHOP = r"(?:\s+(?:\w+\s+)?(?:one|ones|shops?|units?|stores?|branch(?:es)?|outlets?|spaces?|places?|locations?|dukaa?n\w*))"
_WANTS_MORE = re.compile(
    r"\b(?:need|needs|needed|want|wants|wanted|looking\s+for|look\s+for|searching\s+for|require|requires|required|interested\s+in)\b"
    r"[^.!?\n]{0,25}?\b(?P<more>one\s+more\b|another(?=" + _MORE_SHOP + r"|\s*(?:$|[.!?,;\n]))"
    r"|(?:second|additional|extra|bigger|larger)(?=" + _MORE_SHOP + r")|more(?=\s+(?:shops?|units?|space)\b))"
)
# "One more" said alone is a want too ("We already have a shop, one more please", "1 more for my brother"), as the gate's
# reading took it; never "one more question" or "one more thing".
_ONE_MORE_ALONE = re.compile(
    r"\b(?P<more>(?:one|1)\s+more)\b(?=\s*(?:$|[.!?,;:)\n]|(?:please|pls|plz|kindly|bhi|also|too|shops?|units?|stores?|spaces?"
    r"|branch(?:es)?|outlets?|dukaa?n\w*|for\s+(?:me|us|my|our|him|her|them))\b))"
)
# ... and never a want said with a no ("we don't need another one", "not looking for another shop", "no need of another"),
# nor "another" or "one" that they rented, found or got ("... and rented another one already").
_RENTED_IT = re.compile(r"\b(?:rented|taken|took|found|got|gotten|leased|bought|have|has|had)\s+(?:a\s+|an\s+)?$")
_PRICE_WEIGHED = re.compile(
    r"\b(?:at|for)\s+(?:aed\s*)?\d[\d,.]*\s*k?\b|\bcheaper\b|\bis\s+yours\b|\byour\s+(?:best\s+)?(?:rent|price|rate)\b|\bbetter\s+(?:price|rate|deal)\b"
)


def _wants_more(words: str) -> bool:
    """Their words (one line, flat) want another shop of ours: a want of one more (_WANTS_MORE, or "one more" alone:
    _ONE_MORE_ALONE) said with no "no" before it (_NEGATED) and not of a shop they rented ("Sorry, I already rented another
    shop", "We found another one, thanks", "We already rented a shop, we don't need another one", "Already rented, not
    looking for another shop": the launch gate's review found every one of them read as a want)."""
    for match in [*_WANTS_MORE.finditer(words), *_ONE_MORE_ALONE.finditer(words)]:
        if _NEGATED.search(words[: match.start()]) or _RENTED_IT.search(words[: match.start("more")]):
            continue
        return True
    return False


def rented_already(texts) -> bool:
    """They already rented a shop elsewhere ("we got one", "already rented", "found one already", "I already rented
    another shop"), and the same message neither wants another one nor weighs its price against ours ("need one more",
    "at 30k, is yours cheaper?")."""
    for text in texts or ():
        words = _flat(text)
        if words and _RENTED.search(words) and not (_wants_more(words) or _PRICE_WEIGHED.search(words)):
            return True
    return False


def wants_another(texts) -> bool:
    """Their words ask for another shop ("We already have a shop, need one more", "I want a second shop", "we need another
    one"), with no "no" and not of one they rented (_wants_more): whatever they have, they want one more of ours, so the
    burst records no shop rented elsewhere (engine.who_they_are clears the model's facts.already_rented for it)."""
    return any(_wants_more(_flat(text)) for text in texts or () if str(text or "").strip())


# A no ---------------------------------------------------------------------------------------------

_DECLINES = re.compile(
    r"^\W*(?:no|nope|nah|nahi|nahin|nhi|nai|na)\b(?!\s+(?:problem|prob|prblm|problm|worries|worry|issue|issues|tension))"
    r"|\bnot\s+(?:now|interested|looking|needed|required|anymore|any\s+more)\b|\bno\s+(?:thanks|thank\s*you|thankyou|need|longer)\b"
    r"|\b(?:do\s*n'?t|dont|do\s+not)\s+(?:need|want)\b|\b(?:nahi|nahin)\s+chahiye\b|\babhi\s+(?:nahi|nahin|nhi)\b|\bmaybe\s+later\b"
    r"|ليس\s+الآن|ليس\s+الان|غير\s+مهتم|مش\s+مهتم|لا\s+أريد|لا\s+اريد|ما\s+أبي|ما\s+ابي"
    r"|نہیں\s+چاہیے|ابھی\s+نہیں|دلچسپی\s+نہیں|नहीं\s+चाहिए|अभी\s+नहीं|रुचि\s+नहीं"
)


def declines(texts) -> bool:
    """Something they said turns down or puts off the offer: a no, "not now", "not interested"."""
    return any(_DECLINES.search(_flat(text)) for text in (texts or ()) if str(text or "").strip())


# The answer's words ------------------------------------------------------------------------------

_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")


def _lang(language: str) -> str:
    return language if language in _LANGS else "en"


# (with an English article for "en"; the form each sentence below takes in the others)
_NOUNS = {
    "studio": ("a studio", "الاستوديوهات", "studio", "اسٹوڈیو", "studio", "स्टूडियो"),
    "studio_apartment": ("a studio apartment", "الشقق الاستوديو", "studio apartment", "اسٹوڈیو اپارٹمنٹ", "studio apartment", "स्टूडियो अपार्टमेंट"),
    "apartment": ("an apartment", "الشقق", "apartment", "اپارٹمنٹ", "apartment", "अपार्टमेंट"),
    "flat": ("a flat", "الشقق", "flat", "فلیٹ", "flat", "फ्लैट"),
    "villa": ("a villa", "الفلل", "villa", "ولا", "villa", "विला"),
    "townhouse": ("a townhouse", "التاون هاوس", "townhouse", "ٹاؤن ہاؤس", "townhouse", "टाउनहाउस"),
    "penthouse": ("a penthouse", "البنتهاوس", "penthouse", "پینٹ ہاؤس", "penthouse", "पेंटहाउस"),
    "bed_space": ("a bed space", "أماكن السكن المشترك", "bed space", "بیڈ اسپیس", "bed space", "बेड स्पेस"),
    "room": ("a room", "الغرف", "room", "کمرے", "room", "कमरे"),
    "house": ("a house", "المنازل", "ghar", "گھر", "ghar", "घर"),
    "accommodation": ("accommodation", "السكن", "rehaish", "رہائش", "rehne ki jagah", "रहने की जगह"),
    "home": ("a home", "الوحدات السكنية", "ghar", "رہائش", "ghar", "घर"),
    "shop": ("a shop", "المحلات", "shop", "دکان", "shop", "दुकान"),
}


def noun_words(noun: str, language: str) -> str:
    """A noun key in a language: "studio" is "a studio" in English, "bhk:1" "a 1BHK"."""
    if not noun:
        return ""
    index = _LANGS.index(_lang(language))
    key, _, count = noun.partition(":")
    if key == "bhk":
        if index == 0:
            return f"a {count}BHK" if count else "a BHK flat"
        return f"شقق {count}BHK" if index == 1 else f"{count}BHK"
    if key == "bedroom":
        # Arabic counts its own way: one bedroom, two bedrooms (a dual), three bedrooms and more (batch 2e: "غرفة وصالة"
        # now reads as a one-bedroom, so its line says so).
        arabic = {"1": "الشقق بغرفة نوم واحدة", "2": "الشقق بغرفتي نوم"}.get(count, f"شقق {count} غرف نوم")
        forms = (
            f"a {count}-bedroom flat", arabic, f"{count} bedroom flat", f"{count} بیڈروم فلیٹ", f"{count} bedroom flat",
            f"{count} बेडरूम फ्लैट",
        )
        return forms[index]
    row = _NOUNS.get(key)
    return row[index] if row else ""


def property_words(noun: str) -> str:
    """facts.property_type for a noun key, in English ("studio apartment", "1BHK", "room"), '' for none."""
    words = noun_words(noun, "en")
    return re.sub(r"^(?:a|an)\s+", "", words)


# Upset at being misread: "You are not getting I feel", "Do u understand now", a message in capitals.
_FRUSTRATED = re.compile(
    r"\bnot\s+getting\b|\b(?:do\s*n'?t|dont|do\s+not)\s+understand\b|\b(?:do|did)\s+(?:u|you)\s+understand\b|\bunderstand\s+now\b"
    r"|\bi\s+(?:already\s+)?(?:said|told)\b|\balready\s+told\b|\bhow\s+many\s+times\b|\bi\s+just\s+said\b"
)


def misread(texts) -> bool:
    """They tell us we misread them: upset words, or a message in capital letters."""
    for text in texts or ():
        raw = str(text or "")
        letters = [ch for ch in raw if ch.isalpha() and ch.isascii()]
        if len(letters) >= 8 and sum(ch.isupper() for ch in letters) >= 0.8 * len(letters):
            return True
        if _FRUSTRATED.search(_flat(raw)):
            return True
    return False


_THANKS = {
    "en": ("Thank you for letting us know.", "Thank you for letting us know, and sorry for the confusion."),
    "ar": ("شكراً لإبلاغنا.", "شكراً لإبلاغنا، ونعتذر عن اللبس."),
    "ur_latin": ("Batane ka shukriya.", "Batane ka shukriya, aur ghalat-fehmi ke liye maazrat."),
    "ur": ("بتانے کا شکریہ۔", "بتانے کا شکریہ، اور غلط فہمی کے لیے معذرت۔"),
    "hi_latin": ("Batane ke liye shukriya.", "Batane ke liye shukriya, aur galatfehmi ke liye maafi."),
    "hi": ("बताने के लिए शुक्रिया।", "बताने के लिए शुक्रिया, और ग़लतफ़हमी के लिए माफ़ी।"),
}
# (a home or another kind of property, its noun given; to buy; to buy, its noun given; to sell; no shop)
_OPTIONS = {
    "en": (
        "We have many options for {noun} across Dubai.",
        "We have many options to buy across Dubai.",
        "We have many options to buy {noun} across Dubai.",
        "We help owners sell and rent out their property across Dubai.",
        "We have many other options across Dubai too, not only shops.",
    ),
    "ar": (
        "لدينا خيارات كثيرة من {noun} في جميع أنحاء دبي.",
        "لدينا خيارات كثيرة للشراء في جميع أنحاء دبي.",
        "لدينا خيارات كثيرة لشراء {noun} في جميع أنحاء دبي.",
        "نساعد الملاك في بيع وتأجير عقاراتهم في جميع أنحاء دبي.",
        "لدينا أيضاً خيارات كثيرة أخرى في جميع أنحاء دبي، وليس المحلات فقط.",
    ),
    "ur_latin": (
        "Hamare paas poore Dubai mein {noun} ke bohat se options hain.",
        "Hamare paas poore Dubai mein khareedne ke liye bohat se options hain.",
        "Hamare paas poore Dubai mein {noun} khareedne ke liye bohat se options hain.",
        "Hum poore Dubai mein owners ki property bechne aur kiraye par dene mein madad karte hain.",
        "Hamare paas poore Dubai mein sirf shops nahi, aur bhi bohat se options hain.",
    ),
    "ur": (
        "ہمارے پاس پورے دبئی میں {noun} کے بہت سے آپشنز ہیں۔",
        "ہمارے پاس پورے دبئی میں خریدنے کے لیے بہت سے آپشنز ہیں۔",
        "ہمارے پاس پورے دبئی میں {noun} خریدنے کے لیے بہت سے آپشنز ہیں۔",
        "ہم پورے دبئی میں مالکان کی پراپرٹی بیچنے اور کرائے پر دینے میں مدد کرتے ہیں۔",
        "ہمارے پاس پورے دبئی میں صرف دکانیں نہیں، اور بھی بہت سے آپشنز ہیں۔",
    ),
    "hi_latin": (
        "Hamare paas poore Dubai mein {noun} ke bahut saare options hain.",
        "Hamare paas poore Dubai mein kharidne ke liye bahut saare options hain.",
        "Hamare paas poore Dubai mein {noun} kharidne ke liye bahut saare options hain.",
        "Hum poore Dubai mein owners ki property bechne aur kiraye par dene mein madad karte hain.",
        "Hamare paas poore Dubai mein sirf shops nahi, aur bhi bahut saare options hain.",
    ),
    "hi": (
        "हमारे पास पूरे दुबई में {noun} के बहुत सारे विकल्प हैं।",
        "हमारे पास पूरे दुबई में खरीदने के लिए बहुत सारे विकल्प हैं।",
        "हमारे पास पूरे दुबई में {noun} खरीदने के लिए बहुत सारे विकल्प हैं।",
        "हम पूरे दुबई में मालिकों की प्रॉपर्टी बेचने और किराए पर देने में मदद करते हैं।",
        "हमारे पास पूरे दुबई में सिर्फ़ दुकानें नहीं, और भी बहुत सारे विकल्प हैं।",
    ),
}
# The owner's own words (2026-10-15).
_VISIT = {
    "en": "Visit our office and we'll give you the best option.",
    "ar": "تفضل بزيارة مكتبنا وسنقدم لك أفضل خيار.",
    "ur_latin": "Hamare office tashreef layein, hum aap ko sab se behtar option denge.",
    "ur": "ہمارے آفس تشریف لائیں، ہم آپ کو سب سے بہتر آپشن دیں گے۔",
    "hi_latin": "Hamare office aaiye, hum aapko sabse behtar option denge.",
    "hi": "हमारे ऑफ़िस आइए, हम आपको सबसे बेहतर विकल्प देंगे।",
}


def options_sentence(language: str, need: Need) -> str:
    """'We have many options for a studio across Dubai.', in the customer's language."""
    lang = _lang(language)
    home, buy, buy_noun, sell, none = _OPTIONS[lang]
    noun = noun_words(need.noun, lang)
    if need.kind == BUY:
        return buy_noun.format(noun=noun) if noun else buy
    if need.kind == SELL:
        return sell
    if need.kind in (HOME, OTHER) and noun:
        return home.format(noun=noun)
    if need.kind == HOME:
        return home.format(noun=noun_words("home", lang))
    return none


def line(language: str, need: Need, offer: str, *, sorry: bool) -> str:
    """The answer to a customer who wants no shop (the owner's rule): thanks (and sorry), the
    options for what they want across Dubai, "Visit our office and we'll give you the best
    option." and ``offer``, the two free slots (shops.slot_offer), or the question for a time."""
    lang = _lang(language)
    parts = [_THANKS[lang][1 if sorry else 0], options_sentence(lang, need), _VISIT[lang], offer]
    return " ".join(part for part in parts if part)


# The model's words in a shops chat ------------------------------------------------------------------

_SENTENCES = re.compile(r"(?<=[.!?؟۔])\s+|\n+")
# Our shops are only for rent, not for sale (the build pack never says so; a buyer is invited like anyone).
_SALE_CLAIM = re.compile(
    r"\b(?:only|just|solely|exclusively)\s+(?:for\s+)?(?:rent|renting|rental|lease|leasing)\b|\b(?:rent|rental|lease|leasing)\s+only\b"
    r"|\bnot\s+(?:for|available\s+for|up\s+for|on)\s+(?:sale|purchase|buying|selling)\b|\bnot\s+(?:selling|sold)\b"
    r"|\b(?:we|they)\s+(?:do\s*n'?t|do\s+not|cannot|can'?t|won'?t|never)\s+(?:sell|offer\s+(?:\w+\s+)?for\s+sale)\b"
    r"|\bno\s+(?:shops?\s+|units?\s+)?(?:for\s+sale|sale|selling)\b|\bnothing\s+(?:is\s+)?(?:for\s+sale|on\s+sale)\b"
    r"|\b(?:only|sirf|sirif)\s+(?:kiraye|kiraya|rent)\b|\bsale\s+(?:ke\s+liye\s+)?(?:nahi|nahin)\b"
    r"|\bbechne\s+ke\s+liye\s+(?:nahi|nahin)\b|\bfarokht\s+(?:nahi|nahin)\b"
    r"|صرف\s+کرائے|فروخت\s+کے\s+لیے\s+نہیں|برائے\s+فروخت\s+نہیں"
    r"|للإيجار\s+فقط|للايجار\s+فقط|ليست\s+للبيع|ليس\s+للبيع|غير\s+متاحة\s+للبيع|لا\s+نبيع|ليست\s+معروضة\s+للبيع"
    r"|सिर्फ़\s+किराए|सिर्फ\s+किराए|केवल\s+किराए|बिक्री\s+के\s+लिए\s+नहीं|बेचने\s+के\s+लिए\s+नहीं",
    re.IGNORECASE,
)
_SALE_WORDS = re.compile(r"\b(?:sale|sell|selling|sold|buy|buying|purchase)\b|للبيع|بيع|فروخت|बिक्री", re.IGNORECASE)


def _split(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCES.split(str(text or "")) if part.strip()]


def drop_sale_claims(reply: str, shop_facts: str = "") -> tuple[str, bool]:
    """The reply without the sentences that say our shops are only for rent or not for sale, unless
    SHOP FACTS (``shop_facts``, the block the model reads) says something about a sale itself; (reply,
    changed). A reply that is nothing else becomes ''."""
    if _SALE_WORDS.search(shop_facts or ""):
        return str(reply or "").strip(), False
    sentences = _split(reply)
    kept = [sentence for sentence in sentences if not _SALE_CLAIM.search(_flat(sentence))]
    if len(kept) == len(sentences):
        return str(reply or "").strip(), False
    return " ".join(kept), True


# In a chat that wants no shop: shop types, the shop list, MATCH, "for yourself or for a client?", the drive.
_PITCH = re.compile(
    r"\btype\s*[123]\b|\bshop\s+types?\b|\btypes?\s+of\s+shops?\b|\bfor\s+yourself\b|\bfor\s+a\s+client\b|\bclient\s+of\s+yours\b"
    r"|\bdrive\s+you\b|\b5\s+minutes?\s+away\b|\btrade\s+licen[cs]e\b|\bDED\b|\btrakhees\b",
    re.IGNORECASE,
)
_SHOP_WORD = re.compile(r"\bshops?\b|\bdukaa?n\w*|محل|محلات|دكان|دکان|دکانیں|शॉप|दुकान", re.IGNORECASE)
# A home or no shop at all: never a question about their business or their licence (review 2d: chat 68 was asked "Is the
# studio for a business activity?").
_BUSINESS_TALK = re.compile(
    r"\bbusiness(?:es)?\b|\bactivity\b|\blicen[cs]e\b|\btrade\b|\bkaro?bar\b|نشاط|رخصة|کاروبار|لائسنس|व्यापार|बिज़नेस|लाइसेंस", re.IGNORECASE
)
# A buyer: never a word of renting (review 2d: chat 42, who said "I want purchase shop / Not to rent", was asked "Are you
# interested in renting a shop instead, or do you know someone who is?").
_RENT_TALK = re.compile(
    r"\b(?:rent|rents|renting|rental|rented|lease|leasing|tenancy|tenant)\b|\binstead\b|\bkiray[ae]\w*|إيجار|ايجار|استئجار|کرائے|کرایہ|किराए|किराये|किराया",
    re.IGNORECASE,
)
# An owner who sells or lets out: never one of our shops offered for rent instead.
_OUR_SHOPS_FOR_RENT = re.compile(
    r"\binstead\b|\b(?:rent|renting|lease|leasing)\s+(?:a|one|our|the|these|any)\s+(?:shop|unit|space)s?\b|\b(?:shops?|units?)\s+(?:for|to|on)\s+rent\b",
    re.IGNORECASE,
)


def drop_shop_pitch(reply: str, need: Need, office: str = "") -> tuple[str, bool]:
    """The model's reply in a chat that wants no shop, without its sentences about shop types, the
    for-yourself question, a licence or the drive to the shops; for a home (or no shop at all), any
    sentence about shops, their business or their licence; for a buyer any word of renting, and for an
    owner our shops offered for rent. (reply, changed); '' when nothing is left. ``office``: our office's
    address, whose words and unit ("Shop 20") are no shop talk (filters.without_office; the 2e real-model
    gate, round 2: "Visit our office in Russia Cluster, Building V03, Shop 20" read as a shop)."""
    from . import filters

    sentences = _split(filters.join_office_unit(reply, office) if office else reply)
    strict = need.kind in (HOME, NEVER_ASKED, OTHER)

    def pitch(sentence: str) -> bool:
        text = filters.without_office(sentence, office) if office else sentence
        if _PITCH.search(text):
            return True
        if strict:
            return bool(_SHOP_WORD.search(text) or _BUSINESS_TALK.search(text))
        if need.kind == BUY:
            return bool(_RENT_TALK.search(text))
        return bool(_OUR_SHOPS_FOR_RENT.search(text))

    kept = [s for s in sentences if not pitch(s)]
    if len(kept) == len(sentences):
        return str(reply or "").strip(), False
    return " ".join(kept), True


# What is left of a reply that says nothing: an apology, a thanks, an "I see" ("Sorry for the confusion.", "I see, a
# studio.", "Thanks for clarifying.").
_FILLER = re.compile(
    r"^\W*(?:sorry|apolog\w*|my\s+apologies|thanks?|thank\s+you|thankyou|i\s+see|got\s+it|understood|noted|ok(?:ay)?|sure|alright"
    r"|no\s+problem|i\s+understand|great|perfect|of\s+course|maazrat|maafi|shukriya|عذرا|عذراً|آسف|شكرا|شكراً|معذرت|شکریہ|माफ़|शुक्रिया)",
    re.IGNORECASE,
)
FILLER_WORDS_MAX = 8


def only_filler(reply: str) -> bool:
    """The reply is an apology, a thanks or an "I see" and nothing more: no question, no answer of its own."""
    sentences = _split(reply)
    return bool(sentences) and all(
        len(sentence.split()) <= FILLER_WORDS_MAX and not any(mark in sentence for mark in "?؟") and _FILLER.match(sentence)
        for sentence in sentences
    )


def replaces(new: Need | None, old: Need | None) -> bool:
    """The want said now replaces the one the chat knows: it is as specific at least (review 2d: chat 68's "Not shops", 33
    seconds after "a studio", turned it into "no shop (never asked about one)", and the team got a second alert). A "no
    shop" never replaces a want they named, nor a want with no noun the same want with one ("a home" never replaces "a
    studio")."""
    if new is None:
        return False
    if old is None:
        return True
    if new.kind == NEVER_ASKED and old.kind != NEVER_ASKED:
        return False
    if new.kind == old.kind and old.noun and (not new.noun or (new.noun == "home" and old.noun != "home")):
        return False
    return True


def summary(need: Need, facts: dict | None = None) -> str:
    """What our team prepares for, in English ("a studio, monthly rent, England"): what they want and
    what the chat knows of it (owner's example, 2026-10-15)."""
    facts = facts or {}
    parts = [need.what]
    if facts.get("budget_basis") == "per_month":
        parts.append("monthly rent")
    community = str(facts.get("community") or "").strip()
    if community and community.casefold() not in ("international city", "dubai"):
        parts.append(community)
    bedrooms = str(facts.get("bedrooms") or "").strip()
    if bedrooms and "bhk" not in need.what.casefold() and "bedroom" not in need.what.casefold():
        parts.append(f"{bedrooms} bedrooms")
    budget = facts.get("budget_aed")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        parts.append(f"budget AED {int(budget):,}")
    return ", ".join(part for part in parts if part)[:200]
