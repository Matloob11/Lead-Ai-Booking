"""Which need a mixed International City chat serves (batch 2e spec §1.2; board T90).

One campaign reaches every kind of customer (Q26, 2026-10-16): someone who wants a shop to rent, someone who wants a studio
or a one-bedroom in International City to rent or to buy, and everyone else (a bigger home, a villa, a room or a bed space,
another area, selling or letting their own property, buying a shop). Nobody is ever lost (Q25). Code decides which of these
a chat serves, and the unit; the model never writes either:

- ``shop``: today's shops flow, byte for byte;
- ``rent`` / ``sale``: a studio or a one-bedroom in International City (``unit`` "studio" or "one_br", or "" while the bot
  asks). Sale only once SALE_LIVE (slice C): until then a buyer is ``other`` and still gets 2d's office invitation;
- ``other``: everything else, 2d's office invitation and the team's alert;
- "" (not known yet): a chat of the mixed template whose customer has not said what they want.

``decide`` takes the first step that answers:

1. their own words in this burst (engine.need_texts: a tap by its label, a voice note as heard): an unnegated wish for a shop
   with no home in it is a shop; else needs.detect through ``from_need``; a rent word decides rent over a sale lead; two
   needs at once ("a shop and a studio") keep the stored track when it is one of them, else the first named;
2. the model's tag (2d's need tags, the residential schema's), read with the property type and bedrooms it recorded;
3. what the chat knows: the stored track, else 2d's facts.need (the chats of campaigns 448 and 449 move here);
4. the lead context (lead_context.py), which fills a missing deal or unit and decides on its own only for the first answer
   to the mixed template, or for "I never asked about a shop" (from_need);
5. the template (ic_templates.kind): a shops template is a shop, the mixed template "" (not known).

On a stored rent or sale track a new unit ("1BR instead") or cluster refines the track and never switches it; a community
outside International City (the model's facts.community, or a short list said with a home) is ``other``; a nationality is
never a cluster ("I am from China"). The lead context is read only when a step needs it (``lead`` may be a callable).

Slice A stores the decision in shadow (engine._apply: state.track, state.unit) and changes no reply, except the first answer
to the mixed template (``first_yes``, ``open_lead_text``): never the shops for-whom line by default. Plain functions on plain
data, so the eval (leadai_eval) decides exactly as the engine does.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from dataclasses import dataclass

from .. import ic_templates
from ..models import DEFAULT_RESIDENTIAL_FACTS, DEFAULT_SHOPS_FACTS
from . import needs, rules

SHOP = "shop"
RENT = "rent"
SALE = "sale"
OTHER = "other"
UNKNOWN = ""
TRACKS = (SHOP, RENT, SALE, OTHER)
STUDIO = "studio"
ONE_BR = "one_br"
TWO_PLUS = "two_plus"
# The community packs' units (assistant/communities.py, round 17): a villa or a townhouse in Mudon, Villanova, ...; never
# International City's own flow, whose units stay the studio and the one-bedroom (UNITS).
VILLA = "villa"
TOWNHOUSE = "townhouse"
PACK_UNITS = (STUDIO, ONE_BR, TWO_PLUS, VILLA, TOWNHOUSE)
PACK = "pack"  # the reason: a home in a community with a pack
# The units the rent and sale flows serve; any other home is OTHER.
UNITS = (STUDIO, ONE_BR)
# Slice C (T94) switches the sale flow on (sales.py, calls.py); with it off a buyer goes to OTHER (2d's invitation: nobody
# is lost).
SALE_LIVE = True

# Which step decided (Decision.reason), and where a deal came from (Decision.deal_from).
WORDS = "words"
BOTH = "two_needs"
TAG = "tag"
STORED = "stored"
FACTS = "facts"
LEAD = "lead"
TEMPLATE = "template"

# What answers a yes to the mixed template (first_yes): the shops for-whom line (rules), or one of these.
FOR_WHOM = "for_whom"
OPEN_LEAD = "res_open_lead"
WHAT_NEED = "res_what_need"

# The panel's and the alerts' words for a track (English: agents read them).
LABELS = {SHOP: "Shop", RENT: "Rent", SALE: "Sale", OTHER: "Other", UNKNOWN: "Not known yet"}
UNIT_LABELS = {STUDIO: "Studio", ONE_BR: "1BR"}


@dataclass(frozen=True)
class Decision:
    track: str
    unit: str = ""
    clusters: tuple = ()
    deal: str = ""  # RENT or SALE on a home need (a buyer stays SALE here while the track is OTHER until SALE_LIVE)
    deal_from: str = ""  # WORDS, TAG, STORED, LEAD, or "" (a home is rented unless something says otherwise)
    reason: str = ""  # the step that decided
    switched: bool = False  # the chat's known track changed
    sorry: bool = False  # we talked about the other thing, or they never asked about a shop: an opener apologises (slice B)
    community: str = ""  # a community pack's name (communities.py) when the home is there, "" for International City

    def as_dict(self) -> dict:
        """For the turn's actions and the eval's report: the set values only."""
        out = {"track": self.track, "unit": self.unit, "reason": self.reason}
        if self.clusters:
            out["clusters"] = list(self.clusters)
        for key in ("deal", "deal_from", "community"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        for key in ("switched", "sorry"):
            if getattr(self, key):
                out[key] = True
        return out


def label(track: str, unit: str = "") -> str:
    """"Rent · Studio", "Sale · 1BR", "Shop", "Other", "Not known yet" (spec §2.12.3)."""
    head = LABELS.get(track, LABELS[UNKNOWN])
    tail = UNIT_LABELS.get(unit, "") if track in (RENT, SALE) else ""
    return f"{head} · {tail}" if tail else head


class _Lead:
    """The lead context, asked for at most once and only when a step needs it (lead_context.for_turn reads Bitrix)."""

    def __init__(self, source):
        self._source = source
        self._value = None

    @classmethod
    def of(cls, source) -> "_Lead":
        return source if isinstance(source, cls) else cls(source)

    def get(self) -> dict:
        if self._value is None:
            try:
                value = self._source() if callable(self._source) else self._source
            except Exception:  # noqa: BLE001 - the lead context is a help, never a reason to fail a turn
                value = None
            self._value = value if isinstance(value, dict) else {}
        return self._value

    @property
    def loaded(self) -> bool:
        """Asked for already (or given as a dict): what it says costs nothing more."""
        return self._value is not None or isinstance(self._source, dict)


def lazy(source) -> _Lead:
    """The lead context for decide: a dict, or a callable read at most once and only when a step asks (the engine's
    lead_context.for_turn, which reads Bitrix); one per turn serves every decide of that turn."""
    return _Lead.of(source)


def _flat(text) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).replace("’", "'").replace("‘", "'")
    return " ".join(text.lower().split())


# Units -------------------------------------------------------------------------------------------------------------

def _noun_unit(noun: str) -> str:
    """The unit a needs.py noun key names: a studio, a one-bedroom, two or more bedrooms, else ''."""
    key, _, count = str(noun or "").partition(":")
    if key in ("studio", "studio_apartment"):
        return STUDIO
    if key in ("bedroom", "bhk") and count.isdigit():
        number = int(count)
        return STUDIO if number == 0 else ONE_BR if number == 1 else TWO_PLUS
    return ""


def unit_of(text) -> str:
    """The unit some words or a fact name ("studio", "1BR", "one bed", "غرفة وصالة", the bedrooms fact "1"): studio,
    one_br, two_plus, else '' (a flat or an apartment with no count is asked, never guessed)."""
    raw = unicodedata.normalize("NFKC", str(text or "")).strip()
    if raw.isdigit() and len(raw) <= 2:
        number = int(raw)
        return STUDIO if number == 0 else ONE_BR if number == 1 else TWO_PLUS
    return _noun_unit(needs.noun_of(raw)) if raw else ""


# International City and its clusters ---------------------------------------------------------------------------------

_IC = re.compile(
    r"\binternational\s+city\b|\bintl\.?\s+city\b|\bint'?l\s+city\b|\binternational\s+cty\b|\bic\b|\bdragon\s*mart\b"
    r"|المدينة\s+العالمية|انٹرنیشنل\s+سٹی|انٹرنیشنل\s+سیٹی|इंटरनेशनल\s+सिटी"
)
_CLUSTER_WORD = re.compile(r"^(?:cluster|clusters|clustor|cluser|clustr|clstr|culster|clauster)$")
# A building code after a cluster's name ("England X04", "France P07", "Greece K16").
_BUILDING = re.compile(r"^[a-z]-?\d{1,2}$")
# Only these say a bare name is a place ("a studio in France"); "from" never does ("I am from China" is a nationality).
_PLACE_BEFORE = frozenset({"in", "at", "near", "around", "inside", "nearby"})
# A cluster's name as part of another place's ("Emirates Hills", "Mall of the Emirates", "Emirates Road").
_NOT_A_CLUSTER_AFTER = frozenset({"mall", "hills", "hill", "towers", "tower", "road", "rd", "airline", "airlines", "golf", "living", "metro"})
# A cluster said as an adjective, only right before the word "cluster" ("Chinese cluster", "Russian cluster").
_ADJECTIVES = {
    "spanish": "spain", "french": "france", "english": "england", "chinese": "china", "persian": "persia",
    "moroccan": "morocco", "emirati": "emirates", "greek": "greece", "russian": "russia", "italian": "italy",
}
# The ten clusters in the other scripts, said with the word cluster ("كلستر إنجلترا", "انگلینڈ کلسٹر", "स्पेन क्लस्टर").
_SCRIPT_NAMES = {
    "England": ("إنجلترا", "انجلترا", "انكلترا", "انقلترا", "انگلینڈ", "انگلستان", "इंग्लैंड", "इंग्लैण्ड"),
    "France": ("فرنسا", "فرانس", "फ्रांस"),
    "China": ("الصين", "صين", "تشاينا", "چین", "چائنا", "चीन", "चाइना"),
    "Spain": ("إسبانيا", "اسبانيا", "اسپین", "سپین", "स्पेन"),
    "Russia": ("روسيا", "روس", "رشیا", "रूस", "रशिया"),
    "Persia": ("فارس", "بيرشيا", "پرشیا", "पर्शिया", "फारस"),
    "Morocco": ("المغرب", "مغرب", "مراكش", "مراکش", "मोरक्को"),
    "Emirates": ("الإمارات", "الامارات", "إمارات", "امارات", "अमीरात", "एमिरेट्स"),
    "Greece": ("اليونان", "يونان", "یونان", "ग्रीस", "यूनान"),
    "Italy": ("إيطاليا", "ايطاليا", "اٹلی", "اطالیہ", "इटली"),
}
_SCRIPT_CLUSTER_WORD = r"(?:كلستر|كلاستر|كلوستر|مجمع|کلسٹر|کلاسٹر|क्लस्टर)"
_TOKENS = re.compile(r"[a-z0-9]+(?:-[0-9]+)?")

DEFAULT_CLUSTERS = tuple(dict.fromkeys([*DEFAULT_RESIDENTIAL_FACTS["clusters"], *DEFAULT_SHOPS_FACTS["clusters"]]))


def cluster_names(settings_row=None) -> tuple:
    """International City's cluster names: the residential facts' and the shops facts' in the AI settings (Q42 added
    Greece to the shops' own), else the defaults; a broken entry is left out."""
    names = []
    for attr, default in (("residential_facts", DEFAULT_RESIDENTIAL_FACTS), ("shops_facts", DEFAULT_SHOPS_FACTS)):
        facts = getattr(settings_row, attr, None) if settings_row is not None else None
        given = facts.get("clusters") if isinstance(facts, dict) else None
        listed = given if isinstance(given, list) and given else default["clusters"]
        names += [str(name).strip() for name in listed if isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z ]{1,29}", name.strip())]
    return tuple(dict.fromkeys(names)) or DEFAULT_CLUSTERS


def _distance(left: str, right: str) -> int:
    """Edit distance, with a swap of two letters side by side as one ("Morroco")."""
    rows = [list(range(len(right) + 1))]
    for i, a in enumerate(left, 1):
        row = [i]
        for j, b in enumerate(right, 1):
            cost = 0 if a == b else 1
            row.append(min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + cost))
            if i > 1 and j > 1 and a == right[j - 2] and left[i - 2] == b:
                row[j] = min(row[j], rows[-2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


def _name_of(token: str, names: tuple) -> str:
    """The cluster a word spells, misspelt as people type ("Englund", "Moroco", "Morroco"), else ''."""
    for name in names:
        target = name.lower().replace(" ", "")
        if token == target:
            return name
        if len(target) >= 5 and token[:1] == target[:1] and abs(len(token) - len(target)) <= 2:
            if _distance(token, target) <= (2 if len(target) >= 7 else 1):
                return name
    return ""


# A cluster they turn down ("I dont want China cluster", "Not Spain cluster"), read past the words between ("don't want any").
_NEGATORS = frozenset({"not", "no", "dont", "don", "never", "nahi", "nahin", "without", "except", "avoid", "exclude", "excluding", "besides"})
_BETWEEN = frozenset({"in", "the", "a", "an", "any", "want", "like", "need", "prefer", "t", "really", "at", "for"})


def _turned_down(tokens, index: int) -> bool:
    for back in range(index - 1, max(-1, index - 5), -1):
        word = tokens[back]
        if word in _NEGATORS:
            return True
        if word not in _BETWEEN:
            return False
    return False


# Words that name where we meet, never the cluster they want ("see you at the Russia cluster", "on my way to Russia cluster").
_MEETING_WORDS = (("see", "you"), ("meet", "you"), ("meet", "at"), ("my", "way"))


def _our_office(tokens, index: int) -> bool:
    """The cluster names our office's place ("the Russia cluster office", "your office in Russia Cluster", "see you at the
    Russia cluster at 5"), not theirs."""
    after = [word for word in tokens[index + 1 : index + 3] if not _CLUSTER_WORD.match(word)]
    before = tokens[max(0, index - 2) : index]
    near = tokens[max(0, index - 5) : index]
    meeting = any(tuple(near[at : at + 2]) in _MEETING_WORDS for at in range(len(near) - 1))
    return (bool(after) and after[0] in ("office", "offices")) or "office" in before or "offices" in before or meeting


def clusters_in(texts, names: tuple = DEFAULT_CLUSTERS) -> tuple:
    """The clusters their words name as a place: the word "cluster" with it ("Englund x cluster"), a building code
    after it ("Spain T07"), or "in / at / near" before it in words about a home or International City ("a studio in
    France"); never where someone is from ("I am from China"), never one they turn down ("I dont want China cluster"),
    and never our office's place ("see you at the Russia cluster office": the CRM review of batch 2e). In order, each once."""
    found = []
    for text in texts or ():
        flat = _flat(text)
        if not flat:
            continue
        tokens = _TOKENS.findall(flat)
        about_a_home = bool(_IC.search(flat)) or needs.noun_of(flat) not in ("", "shop")
        for index, token in enumerate(tokens):
            before = tokens[index - 1] if index else ""
            after = tokens[index + 1 : index + 3]
            name = _name_of(token, names)
            if not name and token in _ADJECTIVES and after[:1] and _CLUSTER_WORD.match(after[0]):
                name = _name_of(_ADJECTIVES[token], names)
            of_the = before == "the" and index > 1 and tokens[index - 2] == "of"  # "Mall of the Emirates"
            if not name or (after[:1] and after[0] in _NOT_A_CLUSTER_AFTER) or of_the:
                continue
            if _turned_down(tokens, index) or _our_office(tokens, index):
                continue
            if any(_CLUSTER_WORD.match(word) for word in after) or (after and _BUILDING.match(after[0])):
                found.append(name)
            elif before in _PLACE_BEFORE and about_a_home:
                found.append(name)
        for name, spellings in _SCRIPT_NAMES.items():
            if name not in names:
                continue
            words = "|".join(re.escape(spelling) for spelling in spellings)
            if re.search(rf"{_SCRIPT_CLUSTER_WORD}\s*(?:{words})|(?:{words})\s*{_SCRIPT_CLUSTER_WORD}", flat):
                found.append(name)
    return tuple(dict.fromkeys(found))


def names_ic(text, names: tuple = DEFAULT_CLUSTERS) -> bool:
    """The words name International City, Dragon Mart or one of its clusters (as a place)."""
    return bool(_IC.search(_flat(text))) or bool(clusters_in([text], names))


# Communities outside International City, as customers name them (a short list: anything not on it is not "another area").
_OUTSIDE = re.compile(
    r"\b(?:dubai\s+marina|jbr|jvc|jumeirah\s+village|jvt|jlt|jumeirah\s+lakes?\s+towers?|business\s+bay|downtown|deira|"
    r"bur\s+dubai|karama|al\s+karama|satwa|al\s+barsha|barsha|tecom|al\s+qusais|qusais|al\s+nahda|nahda|mirdif|mirdiff|"
    r"rashidiya|al\s+rashidiya|silicon\s+oasis|dso|academic\s+city|discovery\s+gardens?|sports\s+city|motor\s+city|arjan|"
    r"al\s+furjan|furjan|palm\s+jumeirah|al\s+warqa|warqa|muhaisnah|mizhar|dubai\s+south|jebel\s+ali|al\s+quoz|oud\s+metha|"
    r"mankhool|jaddaf|al\s+jaddaf|umm\s+suqeim|meydan|damac\s+hills|arabian\s+ranches|town\s+square|remraam|mudon|"
    r"dubailand|dubai\s+land|festival\s+city|garhoud|al\s+garhoud|mamzar|al\s+twar|hor\s+al\s+anz|abu\s+hail|al\s+rigga|rigga|"
    r"sharjah|ajman|abu\s+dhabi|al\s+ain|ras\s+al\s+khaimah|rak|umm\s+al\s+quwain|fujairah)\b"
    r"|ديرة|بر\s+دبي|الكرامة|القصيص|النهدة|البرشاء|مرسى\s+دبي|الشارقة|عجمان|أبوظبي|ابوظبي|العين"
    r"|شارجہ|عجمان|ابو\s+ظہبی|دیرہ|शारजाह|अजमान|अबू\s+धाबी|देइरा"
)


def other_area(words, facts=None, names: tuple = DEFAULT_CLUSTERS) -> bool:
    """They want it in a community outside International City: their words name one together with a home ("a studio in
    JVC"), or the model's facts.community does; never when International City or a cluster is named as well."""
    texts = [str(text or "") for text in words or () if str(text or "").strip()]
    if any(names_ic(text, names) for text in texts):
        return False
    for text in texts:
        if _OUTSIDE.search(_flat(text)) and needs.noun_of(_flat(text)) not in ("", "shop"):
            return True
    community = (facts or {}).get("community")
    if isinstance(community, str) and community.strip() and not names_ic(community, names):
        return bool(_OUTSIDE.search(_flat(community)))
    return False


# A wish for a shop -----------------------------------------------------------------------------------------------------

_RETAIL_WISH = re.compile(
    r"\b(?:need|needs|want|wants|wanted|looking\s+for|look\s+for|searching\s+for|require|interested\s+in)\b"
    r"(?:\s+\w+){0,3}?\s+(?:retail\s+(?:space|unit|outlet)s?|showrooms?|commercial\s+(?:space|unit)s?)\b"
)
# The whole message is a shop ("Shop", "a shop for rent", "دکان", "दुकान"): the answer to "a shop, a studio or a one-bedroom?".
_BARE_SHOP = re.compile(
    r"^\W*(?:a\s+|an\s+|the\s+)?(?:retail\s+|commercial\s+)?(?:shops?|dukaa?n|stores?|showrooms?|retail\s+space)"
    r"(?:\s+(?:for\s+rent|to\s+rent|on\s+rent|please|pls|only|kiraye\s+(?:pe|par|pr)|chahiye))*\W*$"
    r"|^\W*(?:محل|دكان)(?:\s+(?:للإيجار|للايجار|تجاري))?\W*$|^\W*(?:دکان|شاپ)(?:\s+چاہیے)?\W*$|^\W*(?:दुकान|शॉप)(?:\s+चाहिए)?\W*$"
)


# A shop wanted besides something else, joined to it ("I need a studio and a shop", "flat ya dukaan", "شقة و محل").
_SHOP_ALSO = re.compile(
    r"\b(?:and|or|also|plus|aur|ya)\s+(?:also\s+)?(?:a\s+|an\s+|one\s+|the\s+)?(?:retail\s+)?(?:shops?|dukaa?n|stores?|showrooms?)\b"
    r"|(?:\s|^)(?:و|أو|او)\s*(?:محل|دكان)|(?:اور|یا)\s+(?:ایک\s+)?(?:دکان|شاپ)|(?:और|या)\s+(?:एक\s+)?(?:दुकान|शॉप)"
)
_WISH_WORD = re.compile(
    r"\b(?:need|needs|want|wants|looking|searching|require|interested|chahiye|chaiye)\b|أريد|اريد|أبحث|ابحث|أبغى|ابغى|محتاج"
    r"|چاہیے|ڈھونڈ|चाहिए|ढूंढ|ढूँढ"
)


def wants_shop(words) -> bool:
    """An unnegated wish for a shop, a dukaan, a retail space or a showroom, to rent (2d's needs.wants_a_shop, a retail
    space, a shop said alone, or a shop wanted besides a home: "I need a studio and a shop"): never a shop to buy or to
    sell, which is another need (from_need)."""
    texts = [str(text or "") for text in words or () if str(text or "").strip()]
    if not texts:
        return False
    need = needs.detect(texts)
    if need is not None and need.kind in (needs.BUY, needs.SELL):
        return False
    if any(needs.denies_shop(text) for text in texts):
        return False
    if needs.wants_a_shop(texts):
        return True
    flats = [_flat(text) for text in texts]
    if any(_BARE_SHOP.match(text) or _RETAIL_WISH.search(text) for text in flats):
        return True
    return any(_SHOP_ALSO.search(text) and _WISH_WORD.search(text) for text in flats)


# A shop and a home at once ("I need a shop and a studio"): the home is a second need unless it belongs to the shop.
_STRONG_HOME = ("studio", "studio_apartment", "apartment", "flat", "bedroom", "bhk", "villa", "townhouse", "penthouse", "house")
_SHOP_AT = re.compile(r"\b(?:shops?|dukaa?n\w*|stores?|showrooms?)\b|محل|دكان|دکان|दुकान|शॉप")
_HOME_AT = re.compile(
    r"\b(?:studios?|flats?|apartments?|\d\s*-?\s*bhk|bhk|(?:\d|one|two|three|ek)[\s-]*(?:bed\s*rooms?|bedrooms?|br|b/r|bed)"
    r"|villas?|town\s?houses?|pent\s?houses?|house)\b|استوديو|شقة|اسٹوڈیو|سٹوڈیو|فلیٹ|स्टूडियो|फ्लैट"
)
_ATTACHED = re.compile(r"\b(?:with|having|has|have|inside|including|attached)\b|\bمع\b|کے\s+ساتھ|के\s+साथ")


def _home_besides_shop(texts) -> tuple:
    """(the home need, True when the home is named before the shop) for a burst that wants a shop and a home at once,
    else (None, False). "A shop with an attached studio" is the shop's own."""
    flats = [_flat(text) for text in texts or () if str(text or "").strip()]
    joined = "\n".join(flats)
    for text in flats:
        noun = needs.noun_of(text)
        if noun.partition(":")[0] not in _STRONG_HOME:
            continue
        shop, home = _SHOP_AT.search(text), _HOME_AT.search(text)
        if shop and home and shop.start() < home.start() and _ATTACHED.search(text[shop.end() : home.start()]):
            continue
        shop_at, home_at = _SHOP_AT.search(joined), _HOME_AT.search(joined)
        first = bool(home_at) and (shop_at is None or home_at.start() < shop_at.start())
        return needs.Need(needs.HOME, noun), first
    return None, False


# Rent and sale -------------------------------------------------------------------------------------------------------

_RENT_WORD = re.compile(
    r"\b(?:rent|rental|renting|lease|leasing|kiraya|kiraye|kiraaya|kiraye\s?pe|kiray[ae]?\s+par)\b"
    r"|إيجار|ايجار|استئجار|للإيجار|للايجار|کرایہ|کرائے|किराया|किराए|किराये"
)
# A rent word that is no wish to rent a home (batch 2e review): a buyer's words about the unit's income or tenant, or a no.
# "No, not for rent", "the rental yield", "rent it out", "lease it out", "a rented unit", "how much rent can I get from it".
_RENT_NOT_A_WISH = re.compile(
    r"\bnot\s+(?:for|to|on)\s+(?:rent|lease)\b|\bnot\s+(?:rent|renting|leasing)\b|\bno\s+(?:rent|renting|rental)\b"
    r"|\b(?:rent|rental)\s+(?:yield|yields|income|return|returns|roi|potential|value)\b|\brental\s+investment\b"
    r"|\b(?:rent|lease|let)\s+(?:it|them|the\s+(?:unit|studio|flat|apartment|property))\s+out\b|\b(?:rent|rents|renting|lease|leasing|let|letting)\s+out\b"
    r"|\b(?:rented|tenanted|leased)\s+(?:one|unit|units|studio|flat|apartment|property)\b|\b(?:already|currently)\s+(?:rented|tenanted|leased)\b"
    r"|\b(?:earn|earns|fetch|fetches|generate|generates)\s+(?:\w+\s+){0,3}?(?:rent|rental)\b"
    r"|\b(?:rent|rental)\s+(?:can|will|would|could|does|do)\s+(?:i|we|it|you|they)\b|\bwhat\s+(?:is\s+the\s+|would\s+be\s+the\s+)?rent\s+(?:on|for)\s+it\b"
)
# An explicit wish to rent (what switches a stored sale track to rent): "I want to rent instead", "looking to rent", "rent,
# not buy", "for rent", "kiraye pe chahiye", "أريد استئجار".
_RENT_WISH = re.compile(
    r"\b(?:want|wants|wanted|wanna|need|needs|looking|look|searching|prefer|planning|plan|interested|like|would\s+like|rather)\b"
    r"(?:\s+\w+){0,3}?\s+(?:to\s+rent|to\s+lease|for\s+rent|on\s+rent|in\s+renting|renting|a\s+rental|leasing)\b"
    r"|\b(?:rent|renting|lease)\s+(?:it\s+)?instead\b|\binstead\s+(?:i\s+(?:want|need)\s+to\s+)?(?:rent|lease)\b|\brather\s+(?:rent|lease)\b"
    r"|\b(?:rent|renting)\s*,?\s+(?:not|no|instead\s+of)\s+(?:to\s+)?(?:buy|buying|purchase|sale)\b"
    r"|\b(?:not|no)\s+(?:to\s+)?(?:buy|buying|purchase|sale)\s*,?\s+(?:but\s+)?(?:to\s+)?(?:rent|renting|lease)\b"
    r"|^\W*(?:(?:a|for|to)\s+)?(?:rent|renting|rental|lease)(?:\s+(?:please|pls|only|it))?\W*$"
    r"|\b(?:studio|flat|apartment|one[\s-]?bedroom|1\s*-?\s*br|1\s*-?\s*bhk|unit)\s+(?:for|to|on)\s+rent\b"
    r"|\bkiray[ae]?\s+(?:pe|par|pr)\s+(?:chahiye|chaiye|lena|leni|lene)\b|\bkiraye?\s+(?:ka|ke\s+liye)\b"
    r"|(?:أريد|اريد|أبغى|ابغى|أبي|ابي|أبحث\s+عن|ابحث\s+عن)\s+(?:\S+\s+){0,2}?(?:إيجار|ايجار|استئجار|للإيجار|للايجار)"
    r"|کرائے\s+(?:پر|پہ)\s+(?:چاہیے|لینا)|किराए\s+(?:पर|पे)\s+(?:चाहिए|लेना)"
)


def said_rent(words) -> bool:
    """An explicit rent word ("rent", "kiraya", "إيجار", "lease"): it decides rent over a sale lead. Never a rent word that
    wishes no rent ("not for rent", "the rental yield", "rent it out", "a rented unit": _RENT_NOT_A_WISH)."""
    return any(_RENT_WORD.search(_RENT_NOT_A_WISH.sub(" ", _flat(text))) for text in words or ())


# An explicit wish to buy, the mirror of _RENT_WISH: "I would like to buy", "looking to purchase", "buy, not rent",
# "kharidna hai", "أريد شراء". Never "rent to buy" talk about the unit's yield, nor a no ("not buying").
_BUY_WISH = re.compile(
    r"\b(?:want|wants|wanted|wanna|need|needs|looking|look|searching|prefer|planning|plan|interested|like|would\s+like|rather)\b"
    r"(?:\s+\w+){0,3}?\s+(?:to\s+buy|to\s+purchase|in\s+buying|buying|purchasing|to\s+own|for\s+sale)\b"
    r"|\b(?:buy|buying|purchase)\s+(?:it\s+)?instead\b|\binstead\s+(?:i\s+(?:want|need)\s+to\s+)?(?:buy|purchase)\b"
    r"|\b(?:buy|buying|purchase)\s*,?\s+(?:not|no|instead\s+of)\s+(?:to\s+)?(?:rent|renting|lease)\b"
    r"|^\W*(?:(?:to|for)\s+)?(?:buy|buying|purchase|sale)(?:\s+(?:please|pls|only|it))?\W*$"
    r"|\bkhari?d(?:na|ni|ne|ein|o)\b|\bkhareed(?:na|ni|ne)\b|(?:أريد|اريد|أبي|ابغى|أبغى|نريد)\s+(?:أن\s+)?(?:أشتري|اشتري|شراء|نشتري)|خریدن|खरीदन",
    re.IGNORECASE,
)
_BUY_NOT_A_WISH = re.compile(r"\b(?:not|no|never|don'?t|do\s+not|can'?t|cannot)\s+(?:\w+\s+){0,2}?(?:buy|buying|purchase)\b|\brent\s+to\s+(?:own|buy)\b", re.IGNORECASE)


def wants_buy(words) -> bool:
    """An explicit wish to buy ("I would like to buy a studio", "looking to purchase", "buy, not rent"): on a stored rent
    track this switches the chat to sale (the first mixed campaign, 2026-10-19, chat 49732). Never a no ("not buying") nor
    "rent to own" talk."""
    return any(_BUY_WISH.search(_BUY_NOT_A_WISH.sub(" ", _flat(text))) for text in words or ())


def wants_rent(words) -> bool:
    """An explicit wish to rent ("I want to rent instead", "looking to rent", "rent, not buy"): on a stored sale track only
    this switches the chat to rent (batch 2e review: "No, not for rent. Vacant, own use", "Rented one is fine, I will lease
    it out anyway" and "What is the rental yield?" answer the sale flow's own question)."""
    return any(_RENT_WISH.search(_RENT_NOT_A_WISH.sub(" ", _flat(text))) for text in words or ())


_OTHER_NOUNS = ("villa", "townhouse", "penthouse", "house", "room", "bed_space", "accommodation")
_FLAT_NOUNS = ("apartment", "flat", "home", "bhk")


def home_wished(words) -> bool:
    """Their words wish for the home they name ("I need a flat", "I asked for a studio", "kamra chahiye"), or are no more
    than a home said alone ("Studio", "a 1BR please"): what a shop customer's words must do before the shop track moves
    (batch 2e review: "Is the rent flat or negotiable?", "Does it have a small room inside?" named no home they want)."""
    for text in words or ():
        flat = _flat(text)
        if not flat:
            continue
        if needs.wishes(flat):
            return True
        if "?" not in flat and "؟" not in flat and len(flat.split()) <= 4:
            return True
    return False


def _lead_home(context: dict) -> tuple | None:
    """(deal, unit) a lead context about a studio, a one-bedroom or an apartment gives, else None (a shop, a bigger home,
    a villa, or nothing said)."""
    unit = context.get("unit")
    if unit in UNITS:
        return context.get("deal") or "", unit
    if context.get("property") == "apartment" and unit in (None, ""):
        return context.get("deal") or "", ""
    return None


def _known_home(facts, lead, *, stored: str, template_kind: str) -> Decision | None:
    """The home the chat is on already when they say they never asked about a shop ("Not shops", "No shop!"): its stored
    rent or sale track, or 2d's home or purchase it knows (facts.need), kept with an apology; None when there is none
    (batch 2e review: chats 68 and 132's follow-ups pushed studio seekers onto 2d's other track)."""
    if stored in (RENT, SALE):
        return Decision(stored, deal=stored, deal_from=STORED, reason=STORED, sorry=True)
    had = needs.of(facts)
    if had is not None and had.kind in (needs.HOME, needs.BUY):
        known = from_need(had, facts, lead, stored=stored, template_kind=template_kind)
        if known.track in (RENT, SALE):
            return dataclasses.replace(known, reason=FACTS, sorry=True)
    return None


def _home(deal: str, unit: str, **fields) -> Decision:
    """A home to rent or to buy: the sale track only while SALE_LIVE (a buyer is OTHER until slice C)."""
    deal = deal or RENT
    track = deal if deal == RENT or SALE_LIVE else OTHER
    return Decision(track, unit, deal=deal, **fields)


def from_need(need, facts=None, lead=None, *, rent_said: bool = False, stored: str = "", template_kind: str = ic_templates.SHOP) -> Decision:
    """A need (needs.py: what they want instead of a shop to rent) as a track and unit (spec §1.2's table):

    - a studio or a one-bedroom (or a flat or an apartment, the unit asked) to rent; to buy (sale) when they said buy,
      or the lead context says sale and no rent word was said, or the chat's stored track is sale (a new unit refines a
      track, never switches it);
    - two or more bedrooms, a villa, a townhouse, a penthouse, a house, a room, a bed space, accommodation: other;
    - to buy a studio, a one-bedroom, a flat; or to buy with no noun on a residential lead or chat or a template that is
      no shops one: sale (other until SALE_LIVE). To buy a shop, or with no noun on a shops template: other (2d);
    - to sell or let their own: other;
    - "I never asked about a shop": the chat's own rent or sale track, or 2d's home or purchase it knows (facts.need), with
      an apology (batch 2e review: "Not shops" after the opener pushed a studio seeker off the rent flow); else rent or sale
      from a residential lead context, with an apology, else other.

    ``lead`` may be a callable: it is asked only when the deal or the never-asked need depends on it."""
    lead = _Lead.of(lead)
    if need is None:
        return Decision(UNKNOWN)
    unit = _noun_unit(need.noun)
    key = str(need.noun or "").partition(":")[0]
    if need.kind == needs.SELL:
        return Decision(OTHER, unit)
    if need.kind == needs.NEVER_ASKED:
        known = _known_home(facts, lead, stored=stored, template_kind=template_kind)
        if known is not None:
            return known
        home = _lead_home(lead.get())
        if home is not None:
            return _home(home[0], home[1], deal_from=LEAD if home[0] else "", reason=LEAD, sorry=True)
        return Decision(OTHER, sorry=True)
    if need.kind == needs.BUY:
        if key == "shop" or key in _OTHER_NOUNS or unit == TWO_PLUS:
            return Decision(OTHER, unit, deal=SALE, deal_from=WORDS)
        if unit in UNITS or key in _FLAT_NOUNS:
            return _home(SALE, unit, deal_from=WORDS)
        home = _lead_home(lead.get()) if stored not in (RENT, SALE) and template_kind == ic_templates.SHOP else None
        if stored in (RENT, SALE) or template_kind != ic_templates.SHOP or home is not None:
            return _home(SALE, home[1] if home else "", deal_from=WORDS)
        return Decision(OTHER, deal=SALE, deal_from=WORDS)
    if need.kind == needs.HOME:
        if key in _OTHER_NOUNS or unit == TWO_PLUS:
            return Decision(OTHER, unit)
        if rent_said:
            return _home(RENT, unit, deal_from=WORDS)
        if stored in (RENT, SALE):
            return _home(stored, unit, deal_from=STORED)
        deal = lead.get().get("deal")
        if deal == SALE:
            return _home(SALE, unit, deal_from=LEAD)
        return _home(RENT, unit, deal_from=LEAD if deal == RENT else "")
    return Decision(OTHER)


# The model's tags (2d's SHOPS reasons, and the residential schema's need_tag in slice B).
_SHOPS_TAGS = ("wrong_need", "wants_to_buy", "wants_to_sell", "never_asked")
_AREA_TAG = "other_area"


def _from_tag(tag: str, known: dict, lead, *, stored: str, template_kind: str) -> Decision | None:
    """The model's tag, read with the property type and bedrooms it recorded, else None."""
    tag = str(tag or "")
    noun = needs.noun_of(known.get("property_type")) or ""
    if not _noun_unit(noun) and unit_of(known.get("bedrooms")):
        count = {STUDIO: "0", ONE_BR: "1", TWO_PLUS: "2"}[unit_of(known.get("bedrooms"))]
        noun = f"bedroom:{count}"
    if tag == _AREA_TAG or tag == "other_need":
        return Decision(OTHER)
    if tag == "wants_shop":
        return Decision(SHOP)
    if tag == "wants_rent":
        return from_need(needs.Need(needs.HOME, "" if noun == "shop" else noun), known, lead, rent_said=True, stored=stored, template_kind=template_kind)
    if tag == "wants_buy":
        return from_need(needs.Need(needs.BUY, noun), known, lead, stored=stored, template_kind=template_kind)
    if tag in _SHOPS_TAGS:
        need = needs.from_reason(tag, known)
        if need is not None and need.kind == needs.HOME and not need.noun and _noun_unit(noun):
            need = needs.Need(needs.HOME, noun)
        return from_need(need, known, lead, stored=stored, template_kind=template_kind) if need is not None else None
    return None


def _from_lead(context: dict) -> Decision | None:
    """The lead context alone (the first answer to the mixed template): a shop lead is a shop, a studio, a one-bedroom or
    an apartment a home to rent or buy, a bigger home or a villa other; None when it says nothing."""
    if context.get("property") == "shop":
        return Decision(SHOP, reason=LEAD)
    home = _lead_home(context)
    if home is not None:
        return _home(home[0], home[1], deal_from=LEAD if home[0] else "", reason=LEAD)
    if context.get("unit") == TWO_PLUS or context.get("property") in ("villa", "townhouse"):
        # The lead's rent or sale rides along: a pack (pack_decision) makes a Serena villa for sale the sale track, never
        # rent by default (round 22e's review: a sale villa lead's "Is it still available?" ran as a rent chat).
        deal = context.get("deal") if context.get("deal") in (RENT, SALE) else ""
        unit = context.get("property") if context.get("property") in (VILLA, TOWNHOUSE) else context.get("unit") if context.get("unit") == TWO_PLUS else ""
        return Decision(OTHER, unit, deal=deal, deal_from=LEAD if deal else "", reason=LEAD)
    return None


def template_yes(texts, first_answer: bool) -> bool:
    """All they said is a yes to the campaign template (``first_answer``: nothing of ours since it): "Yes", "ok", "Sure", a
    positive tap ("Yes, still looking", "Yes, book a viewing"). Their words then name no need; a tap that names one ("Yes,
    show me shops") is read as their words first (decide step 1: wants_shop)."""
    words = [str(text or "").strip() for text in texts or () if str(text or "").strip()]
    return bool(first_answer and words) and all(rules.is_acceptance(text) or rules.is_positive_tap(text) for text in words)


def _home_known(stored: str, facts: dict, known: dict, lead, kwargs: dict) -> bool:
    """The chat knows a studio or one-bedroom to rent or buy: its stored track, else 2d's facts.need (decide step 3)."""
    if stored:
        return stored in (RENT, SALE)
    had = needs.of(facts)
    return had is not None and from_need(had, known, lead, **kwargs).track in (RENT, SALE)


def _facts_unit(facts: dict) -> str:
    """The unit the chat's facts hold: 2d's facts.wanted (code's), then the bedrooms, then the property type."""
    had = needs.of(facts)
    return (_noun_unit(had.noun) if had is not None else "") or unit_of(facts.get("bedrooms")) or unit_of(facts.get("property_type"))


_PACK_VILLA = re.compile(r"\bvillas?\b|فيلا|فلة|فلل|विला|ولا", re.IGNORECASE)
_PACK_TOWNHOUSE = re.compile(r"\btown\s?houses?\b|\bth\b|تاون\s?هاوس|टाउनहाउस", re.IGNORECASE)


def _pack_unit(need, texts, known: dict, fresh: dict) -> str:
    """A pack's unit: a villa or a townhouse named in their words or in the facts' property type, else the bedrooms as
    usual (two or more make two_plus; a studio or a one-bedroom stay what they are)."""
    joined = " ".join(_flat(text) for text in texts or ())
    typed = f"{joined} {known.get('property_type') or ''} {fresh.get('property_type') or ''}".lower()
    if _PACK_TOWNHOUSE.search(typed):
        return TOWNHOUSE
    if _PACK_VILLA.search(typed):
        return VILLA
    if need is not None and need.noun:
        return _noun_unit(need.noun)
    return unit_of(fresh.get("bedrooms")) or unit_of(known.get("bedrooms")) or ""


def pack_decision(decision, texts, known: dict, need, lead, *, packs=(), stored: str = "", stored_community: str = "", rent_said: bool = False):
    """A home in a community with a pack: its rent or sale track and the pack's name, else None. The community is read
    from their words (exactly one pack named, communities.named_in), the lead context's Community, or the chat's own
    stored community; the home from the need (a villa, a townhouse, a flat, bedrooms) or the track already decided. A
    shop stays a shop; a community nobody packs stays another area (OTHER), as before."""
    if not packs:
        return None
    from . import communities

    named = communities.named_in(texts, packs)
    pack = named[0] if len(named) == 1 else None
    if pack is None and isinstance(lead, _Lead):
        pack = communities.by_name(str((lead.get() or {}).get("community") or ""), packs) if lead.loaded or decision.track in (RENT, SALE, OTHER) else None
    if pack is None and stored_community:
        pack = communities.by_name(stored_community, packs)
    if pack is None or pack.default:
        return None
    is_home = decision.track in (RENT, SALE) or (decision.track == OTHER and (need is None or need.kind in (needs.HOME, needs.BUY, needs.NEVER_ASKED)))
    if decision.track == SHOP or not is_home:
        return None
    if need is not None and need.kind == needs.SELL:
        return None
    # The deal: a buy word or intent, else the stored track's own (a Villanova sale chat asking the villa's price stays a
    # sale), else rent; a rent word on anything but a stored sale track says rent.
    buying = (need is not None and need.kind == needs.BUY) or wants_buy(texts) or known.get("intent") == needs.BUY
    # ... else the lead's own rent or sale when a step read it already (a portal lead on a villa for sale; round 22e).
    lead_deal = str((lead.get() or {}).get("deal") or "") if isinstance(lead, _Lead) and lead.loaded else ""
    deal = decision.deal or (SALE if buying else stored if stored in (RENT, SALE) else lead_deal if lead_deal in (RENT, SALE) else RENT)
    if rent_said and deal == SALE and stored != SALE:
        deal = RENT
    track = deal if deal == RENT or SALE_LIVE else OTHER
    # The unit: a villa or a townhouse named wins over the bedrooms' count ("3 bedroom townhouse" is a townhouse).
    unit = _pack_unit(need, texts, known, {}) or decision.unit
    return Decision(track, unit, clusters=(), deal=deal, deal_from=decision.deal_from or WORDS, reason=PACK, sorry=decision.sorry, community=pack.name)


def decide(
    *,
    words=(),
    facts=None,
    stored: str = "",
    stored_unit: str = "",
    lead=None,
    template_kind: str = ic_templates.SHOP,
    first_answer: bool = False,
    model_tag: str = "",
    fresh=None,
    clusters=None,
    shop_tap: bool = False,
    packs=(),
    stored_community: str = "",
) -> Decision:
    """The chat's track and unit after this burst (the module note's five steps).

    ``packs``: the community packs beside International City (communities.named_packs: name and aliases), and
    ``stored_community`` the chat's own (state.community): a home in one of those communities is that pack's rent or sale
    track with the unit as named (a villa, a townhouse, two bedrooms or more too), never OTHER (round 17, pack_decision).

    ``words``: their own words in the burst (engine.need_texts); ``facts``: what the chat knows (state.facts); ``fresh``:
    the facts the model recorded in this turn, if it answered; ``stored`` / ``stored_unit``: state.track and state.unit;
    ``lead``: the lead context, or a callable that reads it; ``template_kind``: ic_templates.kind of the campaign template
    the chat answers; ``first_answer``: nothing of ours since that template; ``model_tag``: the model's need tag
    (answer["need_tag"]); ``clusters``: International City's cluster names (cluster_names); ``shop_tap``: the burst is taps
    on our shop types list or a type's card (engine.flow_taps): a shop wish in so many words (spec §1.4.2: those taps are
    the shop track's only, so one on another track switches it to shop, never a shop step there)."""
    texts = [str(text) for text in words or () if str(text or "").strip()]
    facts = {key: value for key, value in (facts or {}).items() if value not in (None, "", [])}
    fresh = {key: value for key, value in (fresh or {}).items() if value not in (None, "", [])}
    known = {**facts, **fresh}
    names = tuple(clusters or DEFAULT_CLUSTERS)
    lead = _Lead.of(lead)
    stored = stored if stored in TRACKS else UNKNOWN
    stored_unit = stored_unit if stored_unit in PACK_UNITS else ""
    # On a stored sale track only an explicit wish to rent switches it (batch 2e review: the sale flow's own question "Do
    # you prefer a rented unit or a vacant one?" is answered with rent words); elsewhere a rent word decides rent.
    rent_said = wants_rent(texts) if stored == SALE else said_rent(texts)
    kwargs = {"stored": stored, "template_kind": template_kind}
    decision = None
    sorry = False

    # 1. Their own words in this burst.
    need = needs.detect(texts) if texts else None
    if need is not None and need.kind == needs.HOME and stored == SHOP and not home_wished(texts):
        # A shop customer's words that only name a home ("Is the rent flat or negotiable?", "flats above the shop?", "a room
        # for my staff"): no wish for one, so the shop track stays (batch 2e review).
        need = None
    if shop_tap:
        decision = Decision(SHOP, reason=WORDS)
    elif wants_shop(texts):
        home, home_first = _home_besides_shop(texts)
        if home is None:
            decision = Decision(SHOP, reason=WORDS)
        else:
            # Two needs at once: the stored track when it is one of them, else the first named (the alert names both).
            other = from_need(home, known, lead, rent_said=rent_said, **kwargs) if stored != SHOP and (home_first or stored) else None
            if other is not None and (home_first or stored == other.track):
                decision = dataclasses.replace(other, reason=BOTH)
            else:
                decision = Decision(SHOP, reason=BOTH)
    elif need is not None:
        if need.kind == needs.HOME and SALE_LIVE and wants_buy(texts):
            # "I would like to buy a studio apartment": a home named with a wish to buy is the buyer's need, whatever track
            # the chat had (the first mixed campaign, 2026-10-19, chat 49732: a buyer on a stored rent track got the rent band).
            need = needs.Need(needs.BUY, need.noun, need.denies)
        decision = from_need(need, known, lead, rent_said=rent_said, **kwargs)
        sorry = need.denies
        if decision.reason != LEAD:
            decision = dataclasses.replace(decision, reason=WORDS)
    elif rent_said and stored == SALE:
        # "to rent instead": a rent word on the sale track switches it (a buyer's own words beat what we knew).
        decision = Decision(RENT, deal=RENT, deal_from=WORDS, reason=WORDS)
    elif stored == RENT and SALE_LIVE and wants_buy(texts):
        # "I would like to buy a studio": a wish to buy on the rent track switches it the same way (the first mixed
        # campaign, 2026-10-19, chat 49732: a buyer on a stored rent track got the yearly rent band).
        decision = Decision(SALE, deal=SALE, deal_from=WORDS, reason=WORDS)

    # 2. The model's tag; never over a home the chat knows when all they said is a yes to the template (template_yes: a yes
    # names no new need, and spec §1.4.2 gives a known track's yes that track's next step). The 2e real-model gate, round 2:
    # a studio seeker's "Yes" to a shops template was tagged wants_shop in both runs (shops-res-yes-to-shops-template).
    if decision is None and model_tag and not (template_yes(texts, first_answer) and _home_known(stored, facts, known, lead, kwargs)):
        tagged = _from_tag(model_tag, known, lead, **kwargs)
        # A home track already stored stays over a bare other_need / other_area tag: words that name another property
        # moved the track in step 1 already, so here the tag stands alone (the first mixed campaign, 2026-10-19, chat
        # 50169: "we need a decent family space" on a stored studio-rent track was tagged other_need, and the customer
        # got the "options across Dubai" line instead of the one-bedroom; chat 49953: "any units in cbd" the same).
        if tagged is not None and tagged.track == OTHER and stored in (RENT, SALE):
            tagged = None
        if tagged is not None and tagged.track != UNKNOWN:
            decision = dataclasses.replace(tagged, reason=tagged.reason if tagged.reason == LEAD else TAG)

    # 3. What the chat knows: the stored track, else 2d's facts.need.
    if decision is None and stored:
        decision = Decision(stored, reason=STORED, deal=stored if stored in (RENT, SALE) else "", deal_from=STORED if stored in (RENT, SALE) else "")
    if decision is None:
        had = needs.of(facts)
        if had is not None:
            decision = from_need(had, known, lead, **kwargs)
            decision = dataclasses.replace(decision, reason=decision.reason if decision.reason == LEAD else FACTS)

    # 4. The lead context decides on its own for the first answer to a template that is no shops one.
    if decision is None and first_answer and template_kind != ic_templates.SHOP:
        decision = _from_lead(lead.get())

    # 5. The template.
    if decision is None:
        if template_kind == ic_templates.SHOP:
            decision = Decision(SHOP, reason=TEMPLATE)
        elif template_kind in UNITS:  # the brief's T1 (studio) and T2 (one-bedroom), if they are ever submitted
            decision = Decision(RENT, template_kind, deal=RENT, reason=TEMPLATE)
        else:
            decision = Decision(UNKNOWN, reason=TEMPLATE)

    # A community outside International City is another area, whatever home it is.
    if decision.track in (RENT, SALE) or (decision.track == OTHER and decision.deal == SALE):
        if other_area(texts, known, names):
            decision = dataclasses.replace(decision, track=OTHER)
    # ... unless it is a community with a pack (communities.py): that pack's own rent or sale track (round 17).
    packed = pack_decision(decision, texts, known, need, lead, packs=packs, stored=stored, stored_community=stored_community, rent_said=rent_said)
    if packed is not None:
        decision = packed

    # The unit: their words, the model's facts of this turn, the stored one, the chat's facts, the lead context.
    unit = decision.unit
    if not unit and decision.community:
        unit = _pack_unit(need, texts, known, fresh) or (stored_unit if stored_community == decision.community else "")
    if not unit and (decision.track in (RENT, SALE) or decision.deal):
        unit = _facts_unit(fresh)
        if not unit and stored_unit and stored in (RENT, SALE, OTHER):
            unit = stored_unit
        if not unit:
            unit = _facts_unit(facts)
        if not unit and decision.track in (RENT, SALE):
            lead_unit = lead.get().get("unit")
            unit = lead_unit if lead_unit in UNITS else ""
    # The clusters: their words, the model's facts.community when it names one as a place ("China Cluster", never a bare
    # "China" it may have written for "I am from China"), the lead context on a home track when a step read it already
    # (never read for a cluster alone: the residential context reads it, slice B).
    found = clusters_in(texts, names)
    if not found:
        found = clusters_in([str(known.get("community") or "")], names)
    if not found and decision.track in (RENT, SALE) and lead.loaded and _lead_home(lead.get()) is not None:
        # Only a lead about an apartment: an old shop enquiry's cluster is no home's (batch 2e review: a France Cluster shop
        # lead's "I need a 1BR" got the European band, and a Morocco shop lead's buyer Morocco's studio price).
        cluster = lead.get().get("cluster")
        found = (cluster,) if isinstance(cluster, str) and cluster in names else ()
    switched = bool(stored) and decision.track != stored and decision.track != UNKNOWN
    sorry = sorry or decision.sorry or (stored == SHOP and switched)
    return dataclasses.replace(decision, unit=unit, clusters=found, switched=switched, sorry=sorry)


# The first answer to the mixed template (spec §1.4.2) ---------------------------------------------------------------------


def first_yes(decision: Decision, *, for_client_known: bool = False) -> str:
    """What answers a yes to the mixed template ("Yes, still looking", a typed yes): never the shops for-whom line by
    default. A shop chat: the shops' own (FOR_WHOM: the for-whom line while we do not know who the shop is for, the shop
    types for a known end user). A studio or a one-bedroom we know (the lead context, or the chat): OPEN_LEAD ("Is the
    studio in Spain Cluster for yourself, or ...?"), and nothing of code's once we know who it is for. A need the chat
    knows otherwise: the model's (2d). Anything else: WHAT_NEED ("What are you looking for: a shop, a studio or a
    one-bedroom, to rent or to buy?")."""
    if decision.track == SHOP:
        return FOR_WHOM
    if decision.track in (RENT, SALE):
        if for_client_known:
            return ""
        if decision.community:
            # A home in a community with a pack (a Mudon villa, a Serena townhouse: the portal greet's leads, round 22e):
            # the pack's own flow opens it with the model; the shops' "a shop, a studio or a one-bedroom" is no question there.
            return ""
        return OPEN_LEAD if decision.unit in UNITS else WHAT_NEED
    if decision.track == OTHER and decision.reason in (WORDS, BOTH, TAG, STORED, FACTS):
        return ""
    return WHAT_NEED


_LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")
# "Great! Is the {studio in Spain Cluster} for yourself, or are you checking for a client?" (Appendix C), per unit.
_OPEN_LEAD = {
    "en": ("Great! Is the {thing} for yourself, or are you checking for a client?",),
    "ar": ("رائع! هل {thing} لك شخصياً، أم تبحث عنه لعميل؟", "رائع! هل {thing} لك شخصياً، أم تبحث عنها لعميل؟"),
    "ur_latin": ("Behtareen! Kya {thing} aap ke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",),
    "ur": ("بہترین! کیا {thing} آپ کے اپنے لیے ہے، یا آپ کسی کلائنٹ کے لیے دیکھ رہے ہیں؟",),
    "hi_latin": ("Badhiya! Kya {thing} aapke apne liye hai, ya aap kisi client ke liye dekh rahe hain?",),
    "hi": ("बढ़िया! क्या {thing} आपके अपने लिए है, या आप किसी क्लाइंट के लिए देख रहे हैं?",),
}
_UNIT_WORDS = {
    STUDIO: {
        "en": "studio", "ar": "الاستوديو", "ur_latin": "studio", "ur": "اسٹوڈیو", "hi_latin": "studio", "hi": "स्टूडियो",
    },
    ONE_BR: {
        "en": "one-bedroom apartment", "ar": "الشقة بغرفة نوم واحدة", "ur_latin": "one-bedroom apartment",
        "ur": "ون بیڈروم اپارٹمنٹ", "hi_latin": "one-bedroom apartment", "hi": "वन-बेडरूम अपार्टमेंट",
    },
}
_CLUSTER_SCRIPT = {
    "Spain": ("إسبانيا", "اسپین", "स्पेन"), "France": ("فرنسا", "فرانس", "फ्रांस"), "England": ("إنجلترا", "انگلینڈ", "इंग्लैंड"),
    "China": ("الصين", "چائنا", "चाइना"), "Persia": ("فارس", "پرشیا", "पर्शिया"), "Morocco": ("المغرب", "مراکش", "मोरक्को"),
    "Emirates": ("الإمارات", "امارات", "एमिरेट्स"), "Greece": ("اليونان", "یونان", "ग्रीस"), "Russia": ("روسيا", "رشیا", "रशिया"),
    "Italy": ("إيطاليا", "اٹلی", "इटली"),
}


def _thing(language: str, unit: str, cluster: str) -> str:
    unit_words = _UNIT_WORDS[unit][language]
    if not cluster:
        return unit_words
    arabic, urdu, hindi = _CLUSTER_SCRIPT.get(cluster, (cluster, cluster, cluster))
    return {
        "en": f"{unit_words} in {cluster} Cluster",
        "ar": f"{unit_words} في كلستر {arabic}",
        "ur_latin": f"{cluster} Cluster wala {unit_words}",
        "ur": f"{urdu} کلسٹر والا {unit_words}",
        "hi_latin": f"{cluster} Cluster wala {unit_words}",
        "hi": f"{hindi} क्लस्टर वाला {unit_words}",
    }[language]


def open_lead_text(language: str, unit: str, clusters=()) -> str:
    """The opener for a lead whose studio or one-bedroom we know, in the customer's language: "Great! Is the studio in
    Spain Cluster for yourself, or are you checking for a client?" (the first cluster, when one is known)."""
    lang = language if language in _LANGS else "en"
    unit = unit if unit in UNITS else STUDIO
    cluster = next((name for name in clusters or () if isinstance(name, str) and name), "")
    forms = _OPEN_LEAD[lang]
    template = forms[1] if len(forms) > 1 and unit == ONE_BR else forms[0]
    return template.format(thing=_thing(lang, unit, cluster))
