"""The International City shops playbook: its facts, its slot offers and its booking message.

A Lead AI campaign whose popup "Script" is "International City shops" puts
its chats on this playbook (lane.playbook_for). The owner's build pack of
2026-10-12 decides what it may say:

- the facts it quotes (LeadAiSettings.shops_facts, which an admin edits in the
  AI settings; DEFAULT_SHOPS_FACTS fills any part that is missing or broken),
  rendered as the SHOP FACTS block of each turn's context, so the static
  system prompt stays cacheable; the amounts in that block are the only ones a
  shops reply may carry that nobody else wrote (filters.clean_reply);
- MATCH: the ONE type to recommend, by the size they need, else by budget
  (under the Type 2 "from" price is Type 1, under the Type 3 one Type 2, else
  Type 3);
- the invitation's two concrete free slots ("I can hold a slot for you today at
  4:00 PM or 6:00 PM — which is better?"), and the same offer when a slot is
  taken;
- the booking confirmation in the build pack's own format.

Everything here is plain functions on plain data: the eval runs them with no
database.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from ..models import DEFAULT_BRAND_NAME, DEFAULT_SHOPS_FACTS, default_shops_facts
from . import hours

TYPE_KEYS = ("type_1", "type_2", "type_3")
NUMBER_KEYS = ("size_from", "size_to", "rent_from", "rent_to", "cheapest")
TEXT_KEYS = ("cheques", "licences", "viewing")
NUMBER_MAX = 10_000_000
LABEL_MAX = 40
CLUSTERS_MAX = 12
TEXT_MAX = 300
BRAND_MAX = 80
AGENT_MAX = 60
NOTES_KEPT = 10
FOLLOW_UP_AFTER = dt.timedelta(days=30)
# What could open markup in a prompt, a WhatsApp message or a Bitrix comment.
_MARKUP = re.compile(r"[<>\[\]{}\\]")


@dataclass(frozen=True)
class ShopType:
    number: int
    label: str
    size_from: int
    size_to: int
    rent_from: int
    rent_to: int
    cheapest: int

    @property
    def key(self) -> str:
        return f"type_{self.number}"

    @property
    def name(self) -> str:
        """'Type 1 – Small'."""
        return f"Type {self.number} – {self.label}"

    def line(self) -> str:
        return (
            f"{self.name}: {self.size_from:,}-{self.size_to:,} sq ft, AED {self.rent_from:,}-{self.rent_to:,} a year, "
            f"from AED {self.cheapest:,}"
        )


# Reading and checking the facts ----------------------------------------------------------------


def _positive(value) -> int | None:
    """A whole number above 0 ("33,000" and 33000.0 too), else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        value = int(value) if value.is_integer() else None
    elif isinstance(value, str):
        text = value.replace(",", "").replace(" ", "").strip()
        # isdecimal, not isdigit: "²" is a digit int() refuses; and nothing longer than a
        # whole number below NUMBER_MAX can be one (int() refuses 4,300 digits and more).
        try:
            value = int(text) if text.isdecimal() and len(text) <= 12 else None
        except ValueError:
            value = None
    if not isinstance(value, int) or not 0 < value < NUMBER_MAX:
        return None
    return value


def clean_text(value, limit: int) -> tuple[str, str]:
    """(text on one line, '' or why it cannot be used)."""
    text = " ".join(str(value if value is not None else "").split())
    if len(text) > limit:
        return text, f"At most {limit} characters."
    if _MARKUP.search(text):
        return text, "Use words and simple punctuation only (no < > [ ] { } or backslash)."
    return text, ""


def validate(raw) -> tuple[dict, dict]:
    """(facts, errors) for the shop facts an admin sent: the cleaned facts, and for each
    part that is wrong its key ("shops_facts.types.1.rent_to") and why."""
    errors: dict[str, str] = {}
    if not isinstance(raw, dict):
        return {}, {"shops_facts": "Send the shop facts as an object."}
    types_in = raw.get("types")
    if not isinstance(types_in, list) or len(types_in) != len(TYPE_KEYS):
        errors["shops_facts.types"] = "Give exactly three shop types."
        types_in = types_in if isinstance(types_in, list) else []
    types = []
    for index, item in enumerate(types_in[: len(TYPE_KEYS)]):
        prefix = f"shops_facts.types.{index}"
        item = item if isinstance(item, dict) else {}
        label, error = clean_text(item.get("label"), LABEL_MAX)
        if error or not label:
            errors[f"{prefix}.label"] = error or "Give the type a name."
        numbers = {key: _positive(item.get(key)) for key in NUMBER_KEYS}
        for key, value in numbers.items():
            if value is None:
                errors[f"{prefix}.{key}"] = "Give a whole number above 0."
        if numbers["size_from"] and numbers["size_to"] and numbers["size_from"] > numbers["size_to"]:
            errors[f"{prefix}.size_to"] = "Must not be smaller than the size from."
        low, high, cheapest = numbers["rent_from"], numbers["rent_to"], numbers["cheapest"]
        if low and high and low > high:
            errors[f"{prefix}.rent_to"] = "Must not be smaller than the rent from."
        elif low and high and cheapest and not low <= cheapest <= high:
            errors[f"{prefix}.cheapest"] = "Must be between the rent from and the rent to."
        types.append({"label": label, **numbers})

    clusters_in = raw.get("clusters")
    if isinstance(clusters_in, str):
        clusters_in = clusters_in.split(",")
    clusters = []
    if not isinstance(clusters_in, list):
        errors["shops_facts.clusters"] = "Give the clusters separated by commas."
    else:
        for item in clusters_in:
            name, error = clean_text(item, LABEL_MAX)
            if error:
                errors["shops_facts.clusters"] = f"'{name[:40]}': {error}"
            elif name and name.casefold() not in {c.casefold() for c in clusters}:
                clusters.append(name)
        if not clusters:
            errors.setdefault("shops_facts.clusters", "Give at least one cluster.")
        elif len(clusters) > CLUSTERS_MAX:
            errors["shops_facts.clusters"] = f"Give at most {CLUSTERS_MAX} clusters."
    facts = {"types": types, "clusters": clusters}
    for key in TEXT_KEYS:
        text, error = clean_text(raw.get(key), TEXT_MAX)
        if key not in raw:
            error = "Missing: send it, empty if it does not apply."
        if error:
            errors[f"shops_facts.{key}"] = error
        facts[key] = text
    return facts, errors


def facts_of(raw) -> dict:
    """The facts to use: what the settings hold, each part that does not check out
    (an edit in the Django admin, an older shape) replaced by the build pack's."""
    facts, errors = validate(raw)
    fallback = default_shops_facts()
    if not facts:
        return fallback
    out = {}
    for key in ("types", "clusters", *TEXT_KEYS):
        broken = any(name == f"shops_facts.{key}" or name.startswith(f"shops_facts.{key}.") for name in errors)
        out[key] = fallback[key] if broken else facts[key]
    return out


def types_of(facts: dict) -> list[ShopType]:
    rows = facts_of(facts)["types"]
    return [ShopType(number=index + 1, **row) for index, row in enumerate(rows)]


def type_by_key(key, facts: dict) -> ShopType | None:
    return next((shop for shop in types_of(facts) if shop.key == key), None)


def facts_block(facts: dict) -> str:
    """SHOP FACTS, as the model reads them (and as clean_reply allows their amounts)."""
    clean = facts_of(facts)
    lines = [f"- {shop.line()}" for shop in types_of(clean)]
    if clean["clusters"]:
        lines.append(f"- Clusters: {', '.join(clean['clusters'])} (International City)")
    for key, label in (("cheques", "Payment"), ("licences", "Licences"), ("viewing", "Viewing")):
        if clean[key]:
            lines.append(f"- {label}: {clean[key]}")
    return "\n".join(lines)


def brand_of(settings_row) -> str:
    text, error = clean_text(getattr(settings_row, "brand_name", ""), BRAND_MAX)
    return text if text and not error else DEFAULT_BRAND_NAME


def agent_of(settings_row) -> str:
    """The agent a booked client meets, '' for "our agent"."""
    text, error = clean_text(getattr(settings_row, "viewing_agent_name", ""), AGENT_MAX)
    return "" if error else text


def honesty_line(brand: str) -> str:
    """The build pack's answer to "are you a bot?", with the brand."""
    owner = f"{brand}'" if brand.endswith("s") else f"{brand}'s"
    return f"I'm the AI assistant for {owner} leasing team — happy to connect you to our agent directly if you prefer."


# The build pack's fixed answers (SHOPS_SYSTEM gives them word for word): said again
# whenever the same kind of question comes, so the no-repeat guard keeps them.
UNKNOWN_LINE = "Good question — I'll have our agent confirm that for you at the viewing."
DISCOUNT_LINE = "Our agent can discuss the best price for you at the viewing."
_HONESTY_START = "I'm the AI assistant for "


def _key(sentence: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(sentence or "").casefold()).split())


_FIXED_KEYS = {_key(UNKNOWN_LINE), _key(DISCOUNT_LINE)}


def is_fixed_line(sentence: str) -> bool:
    """One of the build pack's fixed answers (filters.drop_repeats keeps it)."""
    key = _key(sentence)
    return key in _FIXED_KEYS or key.startswith(_key(_HONESTY_START))


def objection_lines(facts) -> list[str]:
    """The two objection answers whose figures come from SHOP FACTS (the rest are fixed words in
    SHOPS_SYSTEM): our lowest type, its "from" price, its size and the cheques (the honest price line
    code sends for a price objection: claims.price_text), and how many clusters there are."""
    clean = facts_of(facts)
    cheapest = min(types_of(clean), key=lambda shop: shop.cheapest)
    pay = f", payable in {clean['cheques']}" if clean["cheques"] else ""
    clusters = clean["clusters"]
    where = f"in {len(clusters)} clusters" if len(clusters) > 1 else f"in the {clusters[0]} cluster"
    return [
        f'Too expensive, cheaper, higher than others: "I understand. Our lowest is Type {cheapest.number}, from AED '
        f'{cheapest.cheapest:,} a year ({cheapest.size_from:,}-{cheapest.size_to:,} sq ft){pay}. Would that size work for you?"',
        f'Comparing other shops: "Smart. Come and see ours too — we have options {where}, so you can compare in one visit."',
    ]


# MATCH ---------------------------------------------------------------------------------------------


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def match(known: dict, facts: dict) -> tuple[ShopType | None, str]:
    """(the type to recommend, why): the one they chose, else by the size they need,
    else by their yearly budget. (None, '') while neither is known."""
    shops = types_of(facts)
    chosen = type_by_key((known or {}).get("shop_type"), facts)
    if chosen is not None:
        return chosen, "they chose it"
    size = _number((known or {}).get("size_sqft"))
    if size is not None:
        for shop in shops:
            if shop.size_from <= size <= shop.size_to:
                return shop, f"their size of {int(size):,} sq ft"

        def distance(shop):
            return min(abs(size - shop.size_from), abs(size - shop.size_to))

        return min(shops, key=distance), f"their size of {int(size):,} sq ft (nearest range)"
    budget = _number((known or {}).get("budget_aed"))
    if budget is not None:
        yearly = budget * 12 if (known or {}).get("budget_basis") == "per_month" else budget
        if yearly < shops[1].cheapest:
            pick = shops[0]
        elif yearly < shops[2].cheapest:
            pick = shops[1]
        else:
            pick = shops[2]
        return pick, f"their budget of AED {int(yearly):,} a year"
    return None, ""


def match_line(known: dict, facts: dict) -> str:
    shop, why = match(known, facts)
    if shop is None:
        return "not yet: ask the size they need, or their budget"
    return f"{shop.name}, {shop.size_from:,}-{shop.size_to:,} sq ft, from AED {shop.cheapest:,} ({why})"


# The per-turn context ------------------------------------------------------------------------------


@dataclass
class Context:
    """What a shops turn's context adds (prompt.context_message)."""

    brand: str
    honesty: str
    facts: str
    match: str
    free: list = field(default_factory=list)  # FREE SLOTS lines
    taken: list = field(default_factory=list)  # TAKEN SLOTS lines
    agent: str = ""
    objections: list = field(default_factory=list)  # OBJECTION LINES, with SHOP FACTS' own figures
    history: list = field(default_factory=list)  # the old lead's LEAD FIRST ASKED and CRM NOTES (lead_history.lines)


def context(settings_row, known: dict, now, taken=(), history=()) -> Context:
    """The shops block of one turn's context. ``taken``: the other clients' office starts;
    ``history``: the old lead's lines from Bitrix (lead_history.lines), none when unknown."""
    facts = getattr(settings_row, "shops_facts", None) or DEFAULT_SHOPS_FACTS
    closed = getattr(settings_row, "closed_dates", None) or []
    brand = brand_of(settings_row)
    limit = hours.now_dubai(now) + hours.MAX_AHEAD
    taken_lines = [
        f"{start.astimezone(hours.DUBAI):%a %Y-%m-%d %H:%M}"
        for start in sorted(taken)
        if start >= hours.now_dubai(now) - hours.SLOT and start <= limit
    ][:30]
    return Context(
        brand=brand,
        honesty=honesty_line(brand),
        facts=facts_block(facts),
        match=match_line(known, facts),
        # An hour from now at least and an hour apart (launch review issue 17): any two the model takes may go.
        free=[
            hours.slot_line(start, now)
            for start in hours.spaced(hours.free_slots(now, closed, taken, count=hours.SLOTS_SHOWN * 4), hours.MIN_GAP, hours.SLOTS_SHOWN)
        ],
        taken=taken_lines,
        agent=agent_of(settings_row) or "our agent",
        objections=objection_lines(facts),
        history=list(history or ()),
    )


def known_amounts(settings_row) -> str:
    """The words whose amounts a shops reply may repeat: the SHOP FACTS block."""
    return facts_block(getattr(settings_row, "shops_facts", None) or DEFAULT_SHOPS_FACTS)


# Questions for the agent ------------------------------------------------------------------------


def merge_notes(old, new) -> list[str]:
    """The questions our agent answers at the viewing: the old ones, then the new ones not there yet."""
    out = [str(item) for item in old] if isinstance(old, list) else ([str(old)] if old else [])
    seen = {item.casefold() for item in out}
    for item in new or []:
        text = " ".join(str(item).split())
        if text and text.casefold() not in seen:
            out.append(text)
            seen.add(text.casefold())
    return out[-NOTES_KEPT:]


# Slots in a reply ---------------------------------------------------------------------------------

_SLOT_OFFER = {
    "en": "I can hold a slot for you {slots} — which is better?",
    "ar": "يمكنني حجز موعد لك {slots} — أيهما أنسب لك؟",
    "ur_latin": "Main aap ke liye {slots} ka slot rakh sakta hoon — kaunsa behtar rahega?",
    "ur": "میں آپ کے لیے {slots} کا سلاٹ رکھ سکتا ہوں — کون سا بہتر رہے گا؟",
    "hi_latin": "Main aapke liye {slots} ka slot rakh sakta hoon — kaunsa behtar rahega?",
    "hi": "मैं आपके लिए {slots} का स्लॉट रख सकता हूँ — कौन सा बेहतर रहेगा?",
}
# The same two slots asked about again (a plain "Yes" to them picks neither): never the same
# sentence twice in a chat (the build pack), so the second time in these words.
_SLOT_AGAIN = {
    "en": "Which one suits you better: {slots}?",
    "ar": "أيهما يناسبك أكثر: {slots}؟",
    "ur_latin": "Aap ke liye kaunsa behtar rahega: {slots}?",
    "ur": "آپ کے لیے کون سا بہتر رہے گا: {slots}؟",
    "hi_latin": "Aapke liye kaunsa behtar rahega: {slots}?",
    "hi": "आपके लिए कौन सा बेहतर रहेगा: {slots}?",
}
_SLOT_TAKEN = {
    "en": "Sorry, that time is already booked.",
    "ar": "عذراً، هذا الموعد محجوز.",
    "ur_latin": "Maazrat, yeh waqt pehle se book hai.",
    "ur": "معذرت، یہ وقت پہلے سے بک ہے۔",
    "hi_latin": "Maafi, yeh time pehle se book hai.",
    "hi": "माफ़ी, यह समय पहले से बुक है।",
}
# (today, tomorrow, another day, at, or)
_DAY_WORDS = {
    "en": ("today", "tomorrow", "on {day}", " at ", " or "),
    "ar": ("اليوم", "غداً", "يوم {day}", " الساعة ", " أو "),
    "ur_latin": ("aaj", "kal", "{day} ko", " ", " ya "),
    "ur": ("آج", "کل", "{day} کو", " ", " یا "),
    "hi_latin": ("aaj", "kal", "{day} ko", " ", " ya "),
    "hi": ("आज", "कल", "{day} को", " ", " या "),
}


def _lang(language: str, table: dict) -> str:
    return language if language in table else "en"


def _day_phrase(start: dt.datetime, now, lang: str) -> str:
    today_word, tomorrow_word, other, _, _ = _DAY_WORDS[lang]
    local = start.astimezone(hours.DUBAI).date()
    today = hours.now_dubai(now).date()
    if local == today:
        return today_word
    if local == today + dt.timedelta(days=1):
        return tomorrow_word
    return other.format(day=hours.day_label(start))


def slots_phrase(slots: list, now, language: str = "en") -> str:
    """'today at 4:00 PM or 6:00 PM', 'today at 7:00 PM or tomorrow at 10:00 AM'."""
    lang = _lang(language, _DAY_WORDS)
    _, _, _, at, joiner = _DAY_WORDS[lang]
    if not slots:
        return ""
    first = slots[0]
    head = f"{_day_phrase(first, now, lang)}{at}{hours.time_label(first)}"
    if len(slots) == 1:
        return head
    second = slots[1]
    if second.astimezone(hours.DUBAI).date() == first.astimezone(hours.DUBAI).date():
        return f"{head}{joiner}{hours.time_label(second)}"
    return f"{head}{joiner}{_day_phrase(second, now, lang)}{at}{hours.time_label(second)}"


# What the customer said that the earliest free pair could contradict: a part of the
# day, a week or a month, "later", "after work" (the open question then stays theirs).
_VAGUE_WHEN = re.compile(
    r"\b(morning|afternoon|evening|night|tonight|noon|midday|weekend|week|weeks|month|later|after|before|early|"
    r"subah|sham|shaam|dopahar|raat|hafte|hafta)\b"
    r"|صباح|مساء|الظهر|العصر|المغرب|الليل|الليلة|الأسبوع|الاسبوع|الشهر|شام|صبح|رات|ہفتے|हफ्ते|हफ़्ते|शाम|सुबह|रात",
    re.IGNORECASE,
)
# A clause that rules its day out ("I am busy today", "not tomorrow", "aaj nahi").
_RULED_OUT = re.compile(
    r"\b(not|no|never|can'?t|cannot|won'?t|busy|unable|except|nahi|nahin|nhi)\b|\bلا\b|\bمش\b|\bمو\b|نہیں|नहीं",
    re.IGNORECASE,
)
_CLAUSE = re.compile(r"[,.;:!?؟،۔\n]+|\b(?:but|lekin|magar)\b|لكن|مگر|لیکن|लेकिन", re.IGNORECASE)


def _first_of_each(days: set) -> set:
    """A weekday's next date only (hours.named_days also gives the one a week later)."""
    return {day for day in days if day - dt.timedelta(days=7) not in days}


def _days_said(said: str, now) -> tuple[set, set]:
    """(the days the customer's words ask for, the days they rule out), a clause at a time:
    "I am busy today, can I come on Thursday?" asks for Thursday and rules today out."""
    wanted, ruled_out = set(), set()
    for clause in _CLAUSE.split(said or ""):
        days = _first_of_each(hours.named_days(clause, now))
        (ruled_out if _RULED_OUT.search(hours.without_no_problem(clause)) else wanted).update(days)
    return wanted - ruled_out, ruled_out


def invitation_slots(said: str, asked: list, now, closed_dates=(), taken=()) -> list:
    """The two free slots that replace an open "when would you like to come?", fitted to
    what the customer said: on the day the question names, else the day they asked for
    (or the first open day after it), never on a day they ruled out ("I am busy today,
    can I come on Thursday?" is Thursday's two). ``said``: the customer's words this
    burst; ``asked``: the reply's open questions. [] when no pair fits ("next week",
    "in the evening"): the question then goes out as the model wrote it."""
    said = (said or "").replace("’", "'")
    if any(_VAGUE_WHEN.search(text or "") for text in [said, *asked]):
        return []
    wanted, ruled_out = _days_said(said, now)
    named = set()
    for sentence in asked:
        named |= _first_of_each(hours.named_days(sentence, now))
    named -= ruled_out
    day = min(named) if named else (min(wanted) if wanted else None)
    return hours.offer_pair(now, closed_dates, taken, day=day, avoid=ruled_out)


# "This evening": the first nudge's own words in its six languages (nudges._TYPED), and the
# customer's. Its slots start at 5 PM. Not a bare "مساء": "5 مساءً" is 5 PM.
EVENING_FROM = dt.time(17, 0)
_EVENING = re.compile(r"\b(?:evening|tonight|sham|shaam)\b|المساء|مساء اليوم|الليلة|شام|शाम", re.IGNORECASE)


def yes_slots(said: str, ours: str, now, closed_dates=(), taken=(), *, at: dt.time | None = None) -> list:
    """The two free slots for a yes that named no exact time: to a nudge's "Shall I book you
    for this evening?" or "today or tomorrow?", or a plain yes to two slots we offered
    (engine.unasked_confirm). On the day they asked for, else the first day our message
    names, never on a day they ruled out; from 5 PM when they said "this evening", or when
    our message did and they named no day or part of the day of their own. The earliest
    free pair of that day when its evening is full. ``said``: their words this burst;
    ``ours``: our message they answered; ``at``: the hour they named themselves, when the
    model booked another one: the pair starts from it."""
    said = (said or "").replace("’", "'")
    wanted, ruled_out = _days_said(said, now)
    day = min(wanted) if wanted else None
    if day is None:
        named = _first_of_each(hours.named_days(ours or "", now)) - ruled_out
        day = min(named) if named else None
    if at is not None:
        theirs = hours.offer_pair(now, closed_dates, taken, day=day, avoid=ruled_out, after=at)
        if theirs:
            return theirs
    theirs = bool(wanted) or bool(_VAGUE_WHEN.search(said))
    if _EVENING.search(said) or (not theirs and _EVENING.search(ours or "")):
        evening = hours.offer_pair(now, closed_dates, taken, day=day, avoid=ruled_out, after=EVENING_FROM)
        if evening:
            return evening
    return hours.offer_pair(now, closed_dates, taken, day=day, avoid=ruled_out)


def slot_offer(language: str, slots: list, now, *, again: bool = False) -> str:
    """The invitation's two concrete slots, or '' when there are none to offer; ``again``: in the
    words for the same two asked about again (_SLOT_AGAIN)."""
    if not slots:
        return ""
    table = _SLOT_AGAIN if again else _SLOT_OFFER
    lang = _lang(language, table)
    return table[lang].format(slots=slots_phrase(slots, now, lang))


def slot_taken(language: str, slots: list, now) -> str:
    """A slot another client has: say so, and offer the nearest free ones."""
    lang = _lang(language, _SLOT_TAKEN)
    offer = slot_offer(lang, slots, now)
    return f"{_SLOT_TAKEN[lang]} {offer}".strip()


# The booking confirmation --------------------------------------------------------------------------

_CONFIRM = {
    "en": {
        "head": "Your viewing is confirmed ✅",
        "labels": ("Date", "Time", "Shop type", "Place", "You will meet"),
        "our_agent": "our agent",
        "not_decided": "Not decided yet",
        "drive": "Our agent will drive you from the office to the shops — only 5 minutes away.",
        "bring": "If you like the shop, you can reserve it the same day. Please bring your trade license (DED or Trakhees), "
        "or your passport/Emirates ID if it's a new license, and your cheque book.",
        "see_you": "See you at {time}. If anything changes, just message me here.",
    },
    "ar": {
        "head": "تم تأكيد موعد المعاينة ✅",
        "labels": ("التاريخ", "الوقت", "نوع المحل", "المكان", "ستقابل"),
        "our_agent": "وكيلنا",
        "not_decided": "لم يُحدَّد بعد",
        "drive": "سيأخذك وكيلنا بالسيارة من المكتب إلى المحلات — على بُعد 5 دقائق فقط.",
        "bring": "إذا أعجبك المحل، يمكنك حجزه في اليوم نفسه. يرجى إحضار رخصتك التجارية (DED أو Trakhees)، "
        "أو جواز سفرك أو الهوية الإماراتية إذا كانت رخصة جديدة، ودفتر الشيكات.",
        "see_you": "نراك الساعة {time}. إذا تغيّر أي شيء، راسلني هنا.",
    },
    "ur_latin": {
        "head": "Aap ki viewing confirm ho gayi hai ✅",
        "labels": ("Date", "Time", "Shop type", "Jagah", "Aap se milenge"),
        "our_agent": "hamare agent",
        "not_decided": "Abhi tay nahi",
        "drive": "Hamare agent aap ko office se shops tak gaari mein le jayenge — sirf 5 minute ka rasta hai.",
        "bring": "Agar shop pasand aaye to aap usi din reserve kar sakte hain. Barah-e-karam apna trade license (DED ya Trakhees), "
        "ya naya license ho to passport/Emirates ID, aur apni cheque book saath layein.",
        "see_you": "{time} par milte hain. Agar kuch badle to bas yahin message kar dein.",
    },
    "ur": {
        "head": "آپ کی ویونگ کنفرم ہو گئی ہے ✅",
        "labels": ("تاریخ", "وقت", "دکان کی قسم", "جگہ", "آپ سے ملیں گے"),
        "our_agent": "ہمارے ایجنٹ",
        "not_decided": "ابھی طے نہیں",
        "drive": "ہمارے ایجنٹ آپ کو آفس سے دکانوں تک گاڑی میں لے جائیں گے — صرف 5 منٹ کا راستہ ہے۔",
        "bring": "اگر دکان پسند آئے تو آپ اسی دن ریزرو کر سکتے ہیں۔ براہ کرم اپنا ٹریڈ لائسنس (DED یا Trakhees)، "
        "یا نیا لائسنس ہو تو پاسپورٹ یا ایمریٹس آئی ڈی، اور اپنی چیک بک ساتھ لائیں۔",
        "see_you": "{time} پر ملتے ہیں۔ اگر کچھ بدلے تو بس یہیں میسج کر دیں۔",
    },
    "hi_latin": {
        "head": "Aapki viewing confirm ho gayi hai ✅",
        "labels": ("Date", "Time", "Shop type", "Jagah", "Aapse milenge"),
        "our_agent": "hamare agent",
        "not_decided": "Abhi tay nahi",
        "drive": "Hamare agent aapko office se shops tak gaadi mein le jayenge — sirf 5 minute ka rasta hai.",
        "bring": "Agar shop pasand aaye to aap usi din reserve kar sakte hain. Kripya apna trade license (DED ya Trakhees), "
        "ya naya license ho to passport/Emirates ID, aur apni cheque book saath laayein.",
        "see_you": "{time} par milte hain. Agar kuch badle to bas yahin message kar dijiye.",
    },
    "hi": {
        "head": "आपकी व्यूइंग कन्फ़र्म हो गई है ✅",
        "labels": ("तारीख़", "समय", "दुकान का प्रकार", "जगह", "आपसे मिलेंगे"),
        "our_agent": "हमारे एजेंट",
        "not_decided": "अभी तय नहीं",
        "drive": "हमारे एजेंट आपको ऑफ़िस से दुकानों तक गाड़ी में ले जाएँगे — सिर्फ़ 5 मिनट का रास्ता है।",
        "bring": "अगर दुकान पसंद आए तो आप उसी दिन रिज़र्व कर सकते हैं। कृपया अपना ट्रेड लाइसेंस (DED या Trakhees), "
        "या नया लाइसेंस हो तो पासपोर्ट या एमिरेट्स आईडी, और अपनी चेक बुक साथ लाएँ।",
        "see_you": "{time} पर मिलते हैं। अगर कुछ बदले तो बस यहीं मैसेज कर दीजिए।",
    },
}


def confirmation(
    language: str,
    start: dt.datetime,
    *,
    shop_type=None,
    facts: dict | None = None,
    office_address: str = "",
    maps_url: str = "",
    agent: str = "",
) -> str:
    """The build pack's booking message (a confirmation or a move), from the checked time.

    One WhatsApp message in three paragraphs: the details, what to bring, and
    "See you at ...". ``shop_type`` is facts.shop_type ("type_1"...), ``agent``
    the viewing agent's name ('' is "our agent").
    """
    words = _CONFIRM[_lang(language, _CONFIRM)]
    day_word, time_word, type_word, place_word, meet_word = words["labels"]
    shop = type_by_key(shop_type, facts or DEFAULT_SHOPS_FACTS)
    details = [
        words["head"],
        f"{day_word}: {hours.day_label(start)}",
        f"{time_word}: {hours.time_label(start)}",
        f"{type_word}: {shop.name if shop is not None else words['not_decided']}",
        f"{place_word}: {office_address}",
    ]
    if maps_url:
        details.append(maps_url)
    details += [f"{meet_word}: {agent or words['our_agent']}", words["drive"]]
    return "\n".join(details) + "\n\n" + words["bring"] + "\n\n" + words["see_you"].format(time=hours.time_label(start))


def type_label(value) -> str:
    """facts.shop_type for an agent ("Type 1", "Not sure")."""
    return {"type_1": "Type 1", "type_2": "Type 2", "type_3": "Type 3", "not_sure": "Not sure"}.get(str(value or ""), str(value or ""))


def licence_label(value) -> str:
    return {"ded": "DED", "trakhees": "Trakhees", "new": "New licence", "none": "None"}.get(str(value or ""), str(value or ""))
