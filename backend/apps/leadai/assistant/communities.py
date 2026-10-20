"""Community packs (the advance plan's workstream B), v1: the data layer and the decision.

A pack (LeadAiCommunity) is what the assistant knows of one community: the names customers write it by (aliases), its
sub-areas (International City's clusters, Mudon's phases, Villanova's districts), the unit types sold or rented there,
price bands for when the inventory has no match, free facts lines, the meeting point and the playbook knobs. The seed
(SEED, written by the migration) is International City with the cluster list, and the other communities the agency
lists on Property Finder with their aliases and nothing else: no band, no claim, until a person fills them in.

``for_turn`` decides which pack a chat is about — code, never the model — in this order: the pack the chat stored
(state.community), the lead context's Community field, the customer's own words this burst (an alias of exactly one
pack, and none of the stored pack's sub-areas), else the default pack. The engine stores it on the state, the inventory
match reads it (inventory.matches), and the panel shows it. The conversation flow itself is still International City's:
a home outside it goes to the OTHER track as before (tracks.other_area), until the flow per community lands (B2–B4).
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata

DEFAULT = "International City"
UNIT_WORDS = {"studio": "studio", "one_br": "one-bedroom", "two_plus": "two-bedroom and larger", "villa": "villa", "townhouse": "townhouse", "shop": "shop", "other": "other"}
STORED, LEAD, WORDS, DEFAULTED = "stored", "lead", "words", "default"
ALIAS_MAX = 60

# International City's clusters, as the residential facts list them (models.DEFAULT_RESIDENTIAL_FACTS) plus the names
# Property Finder's titles carry; the other communities are the agency's live listings' (inventory._COMMUNITY_WORDS).
IC_SUB_AREAS = (
    *(( f"{name} Cluster", (name.lower(),)) for name in ("Spain", "France", "England", "China", "Persia", "Morocco", "Emirates", "Greece", "Russia", "Italy")),
    ("CBD", ("cbd", "central business district")),
    ("Warsan Village", ("warsan village",)),
    ("International City Phase 2", ("phase 2", "ic phase 2", "international city 2", "warsan 4")),
    ("International City Phase 3", ("phase 3", "ic phase 3", "international city 3")),
)
SEED = (
    {
        "name": DEFAULT,
        "aliases": ["international city", "intl city", "int city", "ic", "al warsan", "warsan", "المدينة العالمية", "انٹرنیشنل سٹی", "इंटरनेशनल सिटी"],
        "sub_areas": [{"name": name, "aliases": list(aliases)} for name, aliases in IC_SUB_AREAS],
        "units": ["studio", "one_br", "two_plus", "shop"],
        "shops": True,
        "pf_location_ids": [63, 16333],
    },
    {"name": "Mudon", "aliases": ["mudon", "مدن"], "units": ["villa", "townhouse", "two_plus"]},
    {"name": "Damac Lagoons", "aliases": ["damac lagoons", "lagoons", "لاجونز"], "units": ["villa", "townhouse"]},
    {"name": "Villanova", "aliases": ["villanova", "villa nova", "la violeta", "la rosa", "amaranta"], "units": ["villa", "townhouse"]},
    {"name": "Dubai South", "aliases": ["dubai south", "expo village", "the pulse"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Arabian Ranches", "aliases": ["arabian ranches", "arabian ranches 2", "arabian ranches 3", "ranches"], "units": ["villa", "townhouse"]},
    {"name": "Town Square", "aliases": ["town square", "nshama"], "units": ["townhouse", "two_plus", "one_br", "studio"]},
    {"name": "JVC", "aliases": ["jvc", "jumeirah village circle", "jumeirah village"], "units": ["studio", "one_br", "two_plus", "townhouse"]},
    {"name": "Dubailand", "aliases": ["dubailand", "dubai land", "rukan", "remraam"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Al Furjan", "aliases": ["al furjan", "furjan"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "The Valley", "aliases": ["the valley", "emaar the valley"], "units": ["villa", "townhouse"]},
    {"name": "Haven by Aldar", "aliases": ["haven", "haven by aldar"], "units": ["villa", "townhouse"]},
    {"name": "Yas Island", "aliases": ["yas island", "yas", "جزيرة ياس"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    # Cursor's C43 map (2026-10-20): the Community spellings on leads with 30 or more of them, and the agency's live listings.
    {"name": "Serena", "aliases": ["serena", "bella casa", "casa dora", "casa viva"], "units": ["villa", "townhouse"]},
    {"name": "Dubai Hills Estate", "aliases": ["dubai hills estate", "dubai hills"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Nad Al Sheba", "aliases": ["nad al sheba", "nad al shiba", "nas"], "units": ["villa", "townhouse"]},
    {"name": "Al Jaddaf", "aliases": ["al jaddaf", "jaddaf", "jadaf"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Business Bay", "aliases": ["business bay"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Dubai Creek Harbour", "aliases": ["dubai creek harbour", "creek harbour", "creek harbor"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Liwan", "aliases": ["liwan", "queue point"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Al Satwa", "aliases": ["al satwa", "satwa"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Arjan", "aliases": ["arjan"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Dubai Silicon Oasis", "aliases": ["dubai silicon oasis", "silicon oasis", "dso"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Dubai Sports City", "aliases": ["dubai sports city", "sports city"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "City Walk", "aliases": ["city walk"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "The Greens", "aliases": ["the greens", "greens"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Meydan", "aliases": ["meydan", "meydan city"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Palm Jebel Ali", "aliases": ["palm jebel ali"], "units": ["villa"]},
    {"name": "Jebel Ali", "aliases": ["jebel ali", "jebel ali village"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Jumeirah Golf Estates", "aliases": ["jumeirah golf estates", "jge"], "units": ["villa", "townhouse"]},
    {"name": "Dubai Marina", "aliases": ["dubai marina", "marina"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "Mohammed Bin Rashid City", "aliases": ["mohammed bin rashid city", "mbr city", "mbr"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Damac Hills", "aliases": ["damac hills", "damac hills 2", "akoya"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
    {"name": "Downtown Dubai", "aliases": ["downtown dubai", "downtown"], "units": ["two_plus", "one_br", "studio"]},
    {"name": "The Acres", "aliases": ["the acres", "acres"], "units": ["villa"]},
    {"name": "Tilal Al Ghaf", "aliases": ["tilal al ghaf"], "units": ["villa", "townhouse"]},
    {"name": "Mirdif", "aliases": ["mirdif", "mirdiff"], "units": ["villa", "townhouse", "two_plus", "one_br", "studio"]},
)


@dataclasses.dataclass(frozen=True)
class Pack:
    """A read-only view of one LeadAiCommunity row (or of the seed's default while the table is empty)."""

    name: str
    aliases: tuple = ()
    sub_areas: tuple = ()  # ((name, (alias, ...)), ...)
    units: tuple = ()
    bands: dict = dataclasses.field(default_factory=dict)
    facts_text: str = ""
    meeting: str = "office"
    meeting_address: str = ""
    maps_url: str = ""
    shops: bool = False
    call_first_sale: bool = True
    pk: int | None = None

    @property
    def default(self) -> bool:
        return self.name == DEFAULT

    def sub_area_names(self) -> tuple:
        return tuple(name for name, _aliases in self.sub_areas)


def _norm(text) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())


def _sub_areas(value) -> tuple:
    out = []
    for item in value or ():
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            out.append((str(item["name"]).strip()[:80], tuple(_norm(alias) for alias in (item.get("aliases") or ()) if _norm(alias))))
        elif isinstance(item, str) and item.strip():
            out.append((item.strip()[:80], (_norm(item),)))
    return tuple(out)


def pack_of(row) -> Pack:
    """A Pack from a LeadAiCommunity row or a seed dict."""
    get = (lambda key, default=None: row.get(key, default)) if isinstance(row, dict) else (lambda key, default=None: getattr(row, key, default))
    return Pack(
        name=str(get("name") or "").strip()[:80],
        aliases=tuple(_norm(alias)[:ALIAS_MAX] for alias in (get("aliases") or ()) if _norm(alias)),
        sub_areas=_sub_areas(get("sub_areas")),
        units=tuple(str(unit) for unit in (get("units") or ()) if str(unit) in UNIT_WORDS),
        bands=dict(get("bands") or {}) if isinstance(get("bands"), dict) else {},
        facts_text=str(get("facts_text") or ""),
        meeting=str(get("meeting") or "office"),
        meeting_address=str(get("meeting_address") or ""),
        maps_url=str(get("maps_url") or ""),
        shops=bool(get("shops", False)),
        call_first_sale=bool(get("call_first_sale", True)),
        pk=get("pk") if not isinstance(row, dict) else None,
    )


def packs() -> list[Pack]:
    """The active packs, the default first; the seed's default alone while the table has no active row."""
    from ..models import LeadAiCommunity

    rows = [pack_of(row) for row in LeadAiCommunity.objects.filter(active=True).order_by("name")]
    rows = [pack for pack in rows if pack.name]
    if not any(pack.default for pack in rows):
        rows.insert(0, pack_of(SEED[0]))
    return sorted(rows, key=lambda pack: (not pack.default, pack.name))


def default_pack(listed=None) -> Pack:
    for pack in listed or packs():
        if pack.default:
            return pack
    return pack_of(SEED[0])


def by_name(name: str, listed=None) -> Pack | None:
    """The pack named exactly (or by an alias), else None."""
    wanted = _norm(name)
    if not wanted:
        return None
    for pack in listed or packs():
        if _norm(pack.name) == wanted or wanted in pack.aliases:
            return pack
    return None


def _alias_found(text: str, alias: str) -> bool:
    if not alias:
        return False
    if re.fullmatch(r"[a-z0-9 .'\-]+", alias):
        return re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text) is not None
    return alias in text


def named_in(texts, listed=None) -> list[Pack]:
    """The packs the customer's words name (an alias each), the longest alias first, each pack once."""
    joined = _norm(" ".join(str(text or "") for text in texts or ()))
    if not joined:
        return []
    found: list[tuple[int, str, Pack]] = []
    for pack in listed or packs():
        best = max((alias for alias in pack.aliases if _alias_found(joined, alias)), key=len, default="")
        if best:
            found.append((-len(best), pack.name, pack))
    return [pack for _length, _name, pack in sorted(found, key=lambda item: (item[0], item[1]))]


def sub_areas_in(texts, pack: Pack) -> tuple:
    """The pack's sub-areas the customer's words name, in the pack's order."""
    joined = _norm(" ".join(str(text or "") for text in texts or ()))
    if not joined:
        return ()
    return tuple(name for name, aliases in pack.sub_areas if any(_alias_found(joined, alias) for alias in (*aliases, _norm(name))))


def for_turn(*, stored: str = "", words=(), lead=None, listed=None) -> tuple[Pack, str]:
    """The chat's pack and why: stored, lead, words or default (the module note's order)."""
    listed = listed or packs()
    fallback = default_pack(listed)
    kept = by_name(stored, listed) if stored else None
    if kept is None and isinstance(lead, dict) and lead.get("community"):
        kept = by_name(str(lead.get("community")), listed)
        if kept is not None:
            return kept, LEAD
    current = kept or fallback
    named = [pack for pack in named_in(words, listed) if pack.name != current.name]
    if named and len(named) == 1 and not sub_areas_in(words, current) and not named_in(words, [current]):
        return named[0], WORDS
    if kept is not None:
        return kept, STORED
    return fallback, DEFAULTED


def label(pack: Pack | None) -> str:
    return pack.name if pack is not None else ""


# ---- the pack flow (round 17): what the turn reads for a home outside International City ------------------------------

MEETING_LINE = "Every visit starts at our office (OFFICE in the context): our agent meets the customer there and takes them to the unit."
NO_BAND_LINE = (
    "No price band is listed for this community: quote only the units INVENTORY lists (their price, size and reference); "
    "with none listed, say our agent will confirm the available options and prices, and invite them to our office."
)
BLOCK_HEAD = "COMMUNITY (this chat is about homes here, not International City; the system wrote these lines and they hold now):"


def named_packs(listed=None, *, with_units: bool = True) -> tuple:
    """The packs beside the default whose community has a live unit in the inventory (``with_units``), for tracks.decide
    (names and aliases; nothing else is read there): a home there takes the pack's flow and quotes the unit; a community
    with nothing listed stays another area, as before, until its units come (Matloob 2026-10-20: the pictures from
    Property Finder, the customer referred to our office)."""
    rows = [pack for pack in (listed or packs()) if not pack.default]
    if not with_units:
        return tuple(rows)
    from ..models import LeadAiUnit

    live = {str(name).casefold() for name in LeadAiUnit.objects.filter(active=True).exclude(community="").values_list("community", flat=True).distinct()}
    return tuple(pack for pack in rows if pack.name.casefold() in live)


def facts_block(pack: Pack, units=()) -> str:
    """RES FACTS for a pack: the community, the meeting point, its bands when a person filled them, its facts lines, and
    the rule that only INVENTORY's units carry a price."""
    lines = [f"- Community: {pack.name}." + (f" Sub-areas: {', '.join(pack.sub_area_names())}." if pack.sub_areas else ""), f"- {MEETING_LINE}"]
    bands = pack.bands if isinstance(pack.bands, dict) else {}
    for deal in ("rent", "sale"):
        table = bands.get(deal) if isinstance(bands.get(deal), dict) else {}
        for unit, band in table.items():
            if isinstance(band, dict) and band.get("from") and band.get("to"):
                when = " a year" if deal == "rent" else ""
                lines.append(f"- {UNIT_WORDS.get(unit, unit).capitalize()}s to {deal}: AED {int(band['from']):,}–{int(band['to']):,}{when} (a guide; the unit's own price is INVENTORY's).")
    lines += [f"- {text.strip()}" for text in str(pack.facts_text or "").splitlines() if text.strip()]
    lines.append(f"- {NO_BAND_LINE}" if not units else "- INVENTORY below lists the units we have in this community right now: quote those, and only those.")
    return "\n".join(lines)


def lines(pack: Pack) -> list[str]:
    """The COMMUNITY block (data) for a pack chat's context."""
    return [BLOCK_HEAD, f"- {pack.name}: the customer's community. Meeting point: our office." + (" The shops flow applies here too." if pack.shops else " No shops here.")]


def known_amounts(pack: Pack) -> str:
    """The pack's own figures (its bands), for the amount filter."""
    parts = []
    bands = pack.bands if isinstance(pack.bands, dict) else {}
    for table in bands.values():
        if isinstance(table, dict):
            for band in table.values():
                if isinstance(band, dict):
                    parts += [f"{int(value):,}" for value in band.values() if isinstance(value, (int, float))]
    return " ".join(parts)
