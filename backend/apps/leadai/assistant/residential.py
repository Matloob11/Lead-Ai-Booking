"""International City studios and one-bedrooms: the facts, words and guards of the rent flow (batch 2e spec §2; board T92).

One campaign reaches every kind of customer (Q26). A chat on the rent track (tracks.py) talks about a studio or a
one-bedroom to rent in International City the way Matloob's rental brief (v2.1) does, with what he decided after it:
AR Properties everywhere (Q29), nobody named (Q30), no phone number ever given (Q38: our team replies in this chat, and
the office address and Maps link go instead), the figures as confirmed (Q27, Q28) with the studio band of Q41
(AED 29,000-33,000 a year, average 31,000). The model writes words; code decides (spec §0.4):

- ``residential_facts`` (``validate``, ``facts_of``, ``rent_band``, ``sale_band``, ``commission``, ``facts_block``,
  ``charge_lines``, ``known_amounts``): what a reply may quote, by track and unit, and nothing else;
- every fixed line, in six languages: the openers (res_open_rent, res_open_rent_any, res_open_sale; res_open_lead is
  tracks.open_lead_text), the commission and VAT lines, the full-name ask and hold, the confirmations (a viewing, an
  office meeting, a call), the handover, and the special cases (already rented, paying online, documents, a deleted
  number, an unheard voice note, a phone number asked for, a switch to shops);
- the full-name gate (brief Part 5, step 5): a rent or sale booking needs the customer's full name, from their own
  words or the lead's NAME and LAST_NAME; without it the time is held (a tentative at it) and the name asked;
- ``settle``: the code guards of spec §2.9 on the model's words (figures by unit and deal, code-only commission and
  VAT, no shop words, no availability claimed, no "booked" or "sent" claimed, no document or bank asks, no screening),
  and the special cases' lines.

Plain functions on plain data, so the eval (leadai_eval) runs exactly what the engine runs, with no database.
``RENT_LIVE`` is the deploy's kill switch: off, a rent chat goes back to batch 2d's office invitation (slice A).
"""

from __future__ import annotations

import copy
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

from ..models import DEFAULT_BRAND_NAME, DEFAULT_RESIDENTIAL_FACTS, default_residential_facts
from . import filters, hours, needs, people, rules, tracks

# The rent flow is live (spec §9, slice B). False sends rent chats back to 2d's office invitation (the slice A shadow).
RENT_LIVE = True

LANGS = ("en", "ar", "ur_latin", "ur", "hi_latin", "hi")
RENT, SALE, UNKNOWN = tracks.RENT, tracks.SALE, tracks.UNKNOWN
STUDIO, ONE_BR = tracks.STUDIO, tracks.ONE_BR
# The tracks this module answers (the shop and other tracks are 2d's).
TRACKS = (RENT, SALE, UNKNOWN)


def _lang(language: str) -> str:
    return language if language in LANGS else "en"


def live_track(track: str) -> bool:
    """The chat's track takes the residential path: rent, sale (once tracks.SALE_LIVE) or not known yet."""
    return RENT_LIVE and track in TRACKS


# The facts (spec §2.2) -------------------------------------------------------------------------------------------------

TEXT_MAX = 300
LABEL_MAX = 40
CLUSTERS_MAX = 12
NUMBER_MAX = 10_000_000
VAT_MAX = 100
_MARKUP = re.compile(r"[<>\[\]{}\\]")
# The bands, and the keys each holds (a studio's rent has its average).
BANDS = {
    "rent": {STUDIO: ("from", "to", "average"), ONE_BR: ("from", "to"), "one_br_european": ("from", "to")},
    "sale": {STUDIO: ("from", "to"), "studio_morocco": ("from", "to"), ONE_BR: ("from", "to")},
}
CHARGE_NUMBERS = ("vat_percent", "ejari", "dewa_deposit")
CHARGE_TEXTS = ("cheques", "chiller", "documents")


def _whole(value) -> int | None:
    """A whole number above 0 ("33,000" and 33000.0 too), else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        value = int(value) if value.is_integer() else None
    elif isinstance(value, str):
        text = value.replace(",", "").replace(" ", "").strip()
        value = int(text) if text.isdecimal() and len(text) <= 12 else None
    if not isinstance(value, int) or not 0 < value < NUMBER_MAX:
        return None
    return value


def _text(value, limit: int = TEXT_MAX) -> tuple[str, str]:
    """(text on one line, '' or why it cannot be used)."""
    text = " ".join(str(value if value is not None else "").split())
    if len(text) > limit:
        return text, f"At most {limit} characters."
    if _MARKUP.search(text):
        return text, "Use words and simple punctuation only (no < > [ ] { } or backslash)."
    return text, ""


def _names(value) -> tuple[list[str], str]:
    """Cluster names from a list or from text separated by commas, each once."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return [], "Give the clusters separated by commas."
    out: list[str] = []
    for item in value:
        name, error = _text(item, LABEL_MAX)
        if error:
            return [], f"'{name[:40]}': {error}"
        if name and name.casefold() not in {known.casefold() for known in out}:
            out.append(name)
    return out, ""


def _band(value, prefix: str, keys) -> tuple[dict, dict]:
    """(band, errors): whole numbers above 0, from <= average <= to."""
    errors: dict[str, str] = {}
    item = value if isinstance(value, dict) else {}
    band = {key: _whole(item.get(key)) for key in keys}
    for key, number in band.items():
        if number is None:
            errors[f"{prefix}.{key}"] = "Give a whole number above 0."
    low, high = band.get("from"), band.get("to")
    if low and high and low > high:
        errors[f"{prefix}.to"] = "Must not be smaller than the from."
    average = band.get("average")
    if "average" in keys and low and high and average and not low <= average <= high:
        errors[f"{prefix}.average"] = "Must be between the from and the to."
    return band, errors


def validate(raw) -> tuple[dict, dict]:
    """(facts, errors) for the residential facts an admin sent (as shops.validate): the cleaned facts, and for each part
    that is wrong its key ("residential_facts.rent.studio.to") and why."""
    if not isinstance(raw, dict):
        return {}, {"residential_facts": "Send the residential facts as an object."}
    errors: dict[str, str] = {}
    facts: dict = {}
    clusters, error = _names(raw.get("clusters"))
    if error:
        errors["residential_facts.clusters"] = error
    elif not clusters:
        errors["residential_facts.clusters"] = "Give at least one cluster."
    elif len(clusters) > CLUSTERS_MAX:
        errors["residential_facts.clusters"] = f"Give at most {CLUSTERS_MAX} clusters."
    facts["clusters"] = clusters
    european, error = _names(raw.get("european_clusters"))
    if error:
        errors["residential_facts.european_clusters"] = error
    else:
        stray = [name for name in european if name.casefold() not in {known.casefold() for known in clusters}]
        if stray:
            errors["residential_facts.european_clusters"] = f"'{stray[0][:40]}' is not one of the clusters."
    facts["european_clusters"] = european
    for deal, units in BANDS.items():
        part = raw.get(deal)
        if not isinstance(part, dict):
            errors[f"residential_facts.{deal}"] = "Send the bands as an object."
            part = {}
        facts[deal] = {}
        for unit, keys in units.items():
            band, problems = _band(part.get(unit), f"residential_facts.{deal}.{unit}", keys)
            errors.update(problems)
            facts[deal][unit] = band
    charges_in = raw.get("charges")
    if not isinstance(charges_in, dict):
        errors["residential_facts.charges"] = "Send the charges as an object."
        charges_in = {}
    charges: dict = {}
    charges["deposit"], problems = _band(charges_in.get("deposit"), "residential_facts.charges.deposit", ("from", "to"))
    errors.update(problems)
    commission_in = charges_in.get("commission") if isinstance(charges_in.get("commission"), dict) else {}
    charges["commission"] = {}
    for unit in (STUDIO, ONE_BR):
        charges["commission"][unit], problems = _band(
            commission_in.get(unit), f"residential_facts.charges.commission.{unit}", ("from", "to")
        )
        errors.update(problems)
    for key in CHARGE_NUMBERS:
        number = _whole(charges_in.get(key))
        if number is None or (key == "vat_percent" and number > VAT_MAX):
            errors[f"residential_facts.charges.{key}"] = "Give a whole number above 0." if key != "vat_percent" else "Give a percentage from 1 to 100."
        charges[key] = number
    for key in CHARGE_TEXTS:
        text, error = _text(charges_in.get(key))
        if key not in charges_in:
            error = "Missing: send it, empty if it does not apply."
        if error:
            errors[f"residential_facts.charges.{key}"] = error
        charges[key] = text
    facts["charges"] = charges
    return facts, errors


def _broken(errors: dict, key: str) -> bool:
    return any(name == key or name.startswith(f"{key}.") for name in errors)


def facts_of(raw) -> dict:
    """The facts to use: what the settings hold, each part that does not check out (an edit in the Django admin, an
    older shape) replaced by the confirmed defaults (Q27, Q28, Q41), part by part."""
    facts, errors = validate(raw)
    out = default_residential_facts()
    if not facts:
        return out
    prefix = "residential_facts"
    if not _broken(errors, f"{prefix}.clusters"):
        out["clusters"] = facts["clusters"]
    if not _broken(errors, f"{prefix}.european_clusters") and not _broken(errors, f"{prefix}.clusters"):
        out["european_clusters"] = facts["european_clusters"]
    else:
        known = {name.casefold() for name in out["clusters"]}
        out["european_clusters"] = [name for name in out["european_clusters"] if name.casefold() in known]
    for deal, units in BANDS.items():
        for unit in units:
            if not _broken(errors, f"{prefix}.{deal}.{unit}") and not (f"{prefix}.{deal}" in errors):
                out[deal][unit] = facts[deal][unit]
    charges = facts["charges"]
    if f"{prefix}.charges" not in errors:
        if not _broken(errors, f"{prefix}.charges.deposit"):
            out["charges"]["deposit"] = charges["deposit"]
        for unit in (STUDIO, ONE_BR):
            if not _broken(errors, f"{prefix}.charges.commission.{unit}"):
                out["charges"]["commission"][unit] = charges["commission"][unit]
        for key in (*CHARGE_NUMBERS, *CHARGE_TEXTS):
            if f"{prefix}.charges.{key}" not in errors:
                out["charges"][key] = charges[key]
    return out


def _clean(facts) -> dict:
    """``facts`` as facts_of gives them: a settings row's raw value, or None for the defaults."""
    return facts_of(facts if facts is not None else DEFAULT_RESIDENTIAL_FACTS)


def facts_from(settings_row) -> dict:
    """The residential facts of a settings row (or of the eval's SimpleNamespace)."""
    return _clean(getattr(settings_row, "residential_facts", None))


# Bands -----------------------------------------------------------------------------------------------------------------


def _named(clusters) -> list[str]:
    return [str(name) for name in clusters or () if isinstance(name, str) and name.strip()]


def european(clusters, facts=None) -> bool:
    """Every cluster named is one of the European clusters (and one is named): a one-bedroom there averages
    AED 42,000-43,000 a year (brief Part 4)."""
    names = _named(clusters)
    euro = {name.casefold() for name in _clean(facts)["european_clusters"]}
    return bool(names) and all(name.casefold() in euro for name in names)


def morocco(clusters) -> bool:
    names = _named(clusters)
    return bool(names) and all(name.casefold() == "morocco" for name in names)


def rent_band(unit: str, clusters=(), facts=None) -> dict:
    """The yearly rent band of a unit in these clusters: a studio's (with its average), a one-bedroom's, or the European
    clusters' one-bedroom band; {} for no unit."""
    clean = _clean(facts)
    if unit == STUDIO:
        return dict(clean["rent"][STUDIO])
    if unit == ONE_BR:
        return dict(clean["rent"]["one_br_european" if european(clusters, clean) else ONE_BR])
    return {}


def sale_band(unit: str, clusters=(), facts=None) -> dict:
    """The sale band of a unit in these clusters: a studio's (Morocco Cluster's own), a one-bedroom's; {} for no unit."""
    clean = _clean(facts)
    if unit == STUDIO:
        return dict(clean["sale"]["studio_morocco" if morocco(clusters) else STUDIO])
    if unit == ONE_BR:
        return dict(clean["sale"][ONE_BR])
    return {}


def commission(unit: str, facts=None) -> dict:
    """The agency commission band of a unit, before VAT (Q28); {} for no unit."""
    clean = _clean(facts)
    return dict(clean["charges"]["commission"][unit]) if unit in (STUDIO, ONE_BR) else {}


def money(value) -> str:
    return f"{int(value):,}"


def band_text(band: dict) -> str:
    """'29,000–33,000'."""
    return f"{money(band['from'])}–{money(band['to'])}" if band else ""


def _figures(band: dict) -> set[int]:
    return {int(value) for value in (band or {}).values() if isinstance(value, int)}


def rent_figures(unit: str, facts=None) -> set[int]:
    """Every figure of a unit's rent bands (both one-bedroom bands for a one-bedroom)."""
    clean = _clean(facts)
    if unit == STUDIO:
        return _figures(clean["rent"][STUDIO])
    if unit == ONE_BR:
        return _figures(clean["rent"][ONE_BR]) | _figures(clean["rent"]["one_br_european"])
    return set()


def sale_figures(unit: str, facts=None) -> set[int]:
    clean = _clean(facts)
    if unit == STUDIO:
        return _figures(clean["sale"][STUDIO]) | _figures(clean["sale"]["studio_morocco"])
    if unit == ONE_BR:
        return _figures(clean["sale"][ONE_BR])
    return set()


def charge_figures(facts=None) -> set[int]:
    clean = _clean(facts)["charges"]
    return _figures(clean["deposit"]) | {clean["ejari"], clean["dewa_deposit"]}


# The context (spec §2.3) -----------------------------------------------------------------------------------------------


def facts_block(track: str, unit: str = "", clusters=(), facts=None, shops_facts=None) -> str:
    """RES FACTS as the model reads them: that track's and unit's part only (both units, each labelled, while the unit
    is not known; the three "from" prices while the track is not known)."""
    clean = _clean(facts)
    lines: list[str] = []
    if track == RENT:
        if unit in (STUDIO, ""):
            studio = clean["rent"][STUDIO]
            lines.append(
                f"- Studios to rent: AED {band_text(studio)} a year, around AED {money(studio['average'])} on average"
            )
        if unit in (ONE_BR, ""):
            lines.append(f"- One-bedrooms to rent: AED {band_text(clean['rent'][ONE_BR])} a year")
            euro = ", ".join(clean["european_clusters"])
            lines.append(
                f"- One-bedrooms in the European clusters ({euro}): around AED {band_text(clean['rent']['one_br_european'])} a year"
            )
        lines.append(
            "- Rent depends on the cluster, the unit and its condition, the balcony, the floor and view, the number of "
            "cheques and the owner's final price. Rent is yearly."
        )
        if clean["charges"]["cheques"]:
            lines.append(f"- Payment: {clean['charges']['cheques']}")
    elif track == SALE:
        if unit in (STUDIO, ""):
            lines.append(
                f"- Studios for sale: AED {band_text(clean['sale'][STUDIO])}; in Morocco Cluster AED "
                f"{band_text(clean['sale']['studio_morocco'])}"
            )
        if unit in (ONE_BR, ""):
            lines.append(f"- One-bedrooms for sale: AED {band_text(clean['sale'][ONE_BR])}")
        lines.append(
            "- The price depends on the cluster, whether the unit is vacant or rented (tenanted), and for a one-bedroom "
            "the balcony. Rented units suit investors who want rental income from day one; vacant units suit buyers who "
            "want to live in it or choose their own tenant."
        )
    else:
        from . import shops

        cheapest = min(shop.cheapest for shop in shops.types_of(shops_facts or shops.DEFAULT_SHOPS_FACTS))
        lines.append(
            f"- Studios to rent from around AED {money(clean['rent'][STUDIO]['from'])} a year; one-bedrooms to rent from "
            f"around AED {money(clean['rent'][ONE_BR]['from'])} a year; shops to rent from AED {money(cheapest)} a year"
        )
    lines.append(f"- Clusters: {', '.join(clean['clusters'])} (International City)")
    return "\n".join(lines)


def charge_lines(facts=None) -> list[str]:
    """CHARGE LINES (brief Part 7, Q27 and Q28's figures): the model says them in the customer's language; the
    commission and VAT lines are code's (commission_answer)."""
    charges = _clean(facts)["charges"]
    lines = [
        f'Deposit: "Normally the security deposit in International City is around AED {band_text(charges["deposit"])}, '
        "depending on the owner and the unit. It's refundable at the end of the tenancy, subject to the apartment's "
        'condition. We\'ll confirm the exact amount before you proceed."',
        f'Ejari: "Ejari is AED {money(charges["ejari"])}, and we handle the registration for you."',
        f'DEWA: "DEWA takes a refundable deposit of around AED {money(charges["dewa_deposit"])} for an apartment, plus a '
        'small connection fee, paid directly to DEWA."',
    ]
    if charges["chiller"]:
        lines.append(f"Chiller: {charges['chiller']}")
    if charges["documents"]:
        lines.append(f"Documents: {charges['documents']}")
    if charges["cheques"]:
        lines.append(
            f'Cheques: "Usually {charges["cheques"]}. Fewer cheques can sometimes mean a better price; our agent '
            'confirms it for the unit you like."'
        )
    return lines


def known_amounts(settings_row, track: str, unit: str = "", clusters=()) -> str:
    """The words whose amounts a residential reply may repeat (filters.clean_reply's allow-list): that track's and
    unit's figures only, with the charges and the unit's commission on the rent track (code's commission line)."""
    facts = getattr(settings_row, "residential_facts", None)
    shops_facts = getattr(settings_row, "shops_facts", None)
    parts = [facts_block(track, unit, clusters, facts, shops_facts)]
    if track == RENT:
        parts += charge_lines(facts)
        for each in ((unit,) if unit in (STUDIO, ONE_BR) else (STUDIO, ONE_BR)):
            parts.append(f"Commission: AED {band_text(commission(each, facts))}")
    return "\n".join(parts)


def honesty_line(brand: str) -> str:
    """The brief's answer to "are you a bot?", with the brand (Q29) and no personal name (Q3)."""
    owner = f"{brand}'" if brand.endswith("s") else f"{brand}'s"
    return f"I'm {owner} virtual assistant — I can help with options and viewings, and connect you to our agent anytime."


def track_line(track: str, unit: str = "", clusters=()) -> str:
    """TRACK: 'rent (unit: studio; clusters: Spain)', 'rent (unit: not known yet)', or 'not known yet'."""
    if track not in (RENT, SALE):
        return "not known yet"
    names = ", ".join(_named(clusters)) or "not known yet"
    shown = {STUDIO: "studio", ONE_BR: "one-bedroom"}.get(unit, "not known yet")
    return f"{track} (unit: {shown}; clusters: {names})"


@dataclass
class Context:
    """What a residential turn's context adds (prompt.residential_lines)."""

    brand: str
    honesty: str
    track: str
    facts: str
    charges: list = field(default_factory=list)  # CHARGE LINES, rent only
    lead: list = field(default_factory=list)  # the LEAD CONTEXT line (lead_context.lines)
    full_name: str = "no"  # FULL NAME KNOWN
    free: list = field(default_factory=list)  # FREE SLOTS lines
    taken: list = field(default_factory=list)  # TAKEN SLOTS lines
    history: list = field(default_factory=list)  # LEAD FIRST ASKED and CRM NOTES (lead_history.lines)
    calls: list = field(default_factory=list)  # CALL SLOTS (the sale track's call pool, slice C)
    held: str = ""  # a time held for the full name ("Monday 12 October 2026, 5:00 PM")
    sale_step: str = ""  # SALE STEP: the buyer's next questions in the brief's order (sales.step_line, slice C)


def context(
    settings_row, track: str, unit: str, clusters, now, taken=(), *, lead=None, full_name: str = "", history=(),
    calls=(), held=None, sale_step: str = "",
) -> Context:
    """The residential block of one turn's context. ``taken``: the other clients' office starts; ``lead``: the lead
    context (lead_context.parse's dict); ``full_name``: the customer's full name when known (full_name_known);
    ``calls``: CALL SLOTS lines (the sale track's, slice C); ``held``: the start held for their full name;
    ``sale_step``: the sale track's SALE STEP line (sales.context_parts, slice C)."""
    from . import lead_context, shops

    facts = getattr(settings_row, "residential_facts", None)
    closed = getattr(settings_row, "closed_dates", None) or []
    brand = shops.brand_of(settings_row) if settings_row is not None else DEFAULT_BRAND_NAME
    limit = hours.now_dubai(now) + hours.MAX_AHEAD
    taken_lines = [
        f"{start.astimezone(hours.DUBAI):%a %Y-%m-%d %H:%M}"
        for start in sorted(taken or ())
        if start >= hours.now_dubai(now) - hours.SLOT and start <= limit
    ][:30]
    return Context(
        brand=brand,
        honesty=honesty_line(brand),
        track=track_line(track, unit, clusters),
        facts=facts_block(track, unit, clusters, facts, getattr(settings_row, "shops_facts", None)),
        charges=charge_lines(facts) if track == RENT else [],
        lead=lead_context.lines(lead or {}),
        full_name=f"yes ({full_name})" if full_name else "no",
        free=[
            hours.slot_line(start, now)
            for start in hours.spaced(hours.free_slots(now, closed, taken, count=hours.SLOTS_SHOWN * 4), hours.MIN_GAP, hours.SLOTS_SHOWN)
        ],
        taken=taken_lines,
        history=list(history or ()),
        calls=list(calls or ()),
        held=hours.describe(held) if held is not None else "",
        sale_step=" ".join(str(sale_step or "").split()),
    )


# Code's lines (Appendix C), six languages each -------------------------------------------------------------------------

LINES = {
    "res_commission_first": {
        "en": "Our normal agency commission applies once you choose an apartment you like. The exact amount depends on the unit.",
        "ar": "تُطبَّق عمولة الوكالة المعتادة لدينا عندما تختار الشقة التي تعجبك. ويعتمد المبلغ الدقيق على الوحدة.",
        "ur_latin": "Jab aap koi pasandeeda apartment chun lete hain to hamari normal agency commission lagti hai. Sahi amount unit par depend karta hai.",
        "ur": "جب آپ کوئی پسندیدہ اپارٹمنٹ چن لیتے ہیں تو ہماری نارمل ایجنسی کمیشن لگتی ہے۔ صحیح رقم یونٹ پر منحصر ہے۔",
        "hi_latin": "Jab aap koi pasand ka apartment chun lete hain to hamari normal agency commission lagti hai. Sahi amount unit par depend karta hai.",
        "hi": "जब आप कोई पसंद का अपार्टमेंट चुन लेते हैं तो हमारी सामान्य एजेंसी कमीशन लगती है। सही रक़म यूनिट पर निर्भर करती है।",
    },
    "res_commission_sale": {
        "en": "Our agent will go through all the costs with you on the call.",
        "ar": "سيشرح لك وكيلنا جميع التكاليف خلال المكالمة.",
        "ur_latin": "Hamare agent call par aap ko saari costs tafseel se bata denge.",
        "ur": "ہمارے ایجنٹ کال پر آپ کو تمام اخراجات تفصیل سے بتا دیں گے۔",
        "hi_latin": "Hamare agent call par aapko saari costs detail mein bata denge.",
        "hi": "हमारे एजेंट कॉल पर आपको सारी लागतें विस्तार से बता देंगे।",
    },
    "res_vat": {
        "en": "{vat}% VAT applies only to the agency commission. There is no VAT on the rent, the deposit, Ejari or DEWA.",
        "ar": "تُطبَّق ضريبة القيمة المضافة {vat}% على عمولة الوكالة فقط. لا توجد ضريبة على الإيجار أو التأمين أو إيجاري أو ديوا.",
        "ur_latin": "{vat}% VAT sirf agency commission par lagta hai. Rent, deposit, Ejari ya DEWA par koi VAT nahi hai.",
        "ur": "{vat}% VAT صرف ایجنسی کمیشن پر لگتا ہے۔ کرائے، ڈپازٹ، ایجاری یا DEWA پر کوئی VAT نہیں ہے۔",
        "hi_latin": "{vat}% VAT sirf agency commission par lagta hai. Rent, deposit, Ejari ya DEWA par koi VAT nahi hai.",
        "hi": "{vat}% VAT सिर्फ़ एजेंसी कमीशन पर लगता है। किराए, डिपॉज़िट, Ejari या DEWA पर कोई VAT नहीं है।",
    },
    "res_full_name": {
        "en": "Great! May I have your full name for the booking?",
        "ar": "رائع! هل يمكنني معرفة اسمك الكامل للحجز؟",
        "ur_latin": "Behtareen! Booking ke liye kya main aap ka poora naam jaan sakta hoon?",
        "ur": "بہترین! بکنگ کے لیے کیا میں آپ کا پورا نام جان سکتا ہوں؟",
        "hi_latin": "Badhiya! Booking ke liye kya main aapka poora naam jaan sakta hoon?",
        "hi": "बढ़िया! बुकिंग के लिए क्या मैं आपका पूरा नाम जान सकता हूँ?",
    },
    "res_name_hold": {
        "en": "No problem — I've noted {when} for you, and our agent will confirm it with you here.",
        "ar": "لا مشكلة — سجّلت لك {when}، وسيؤكده وكيلنا معك هنا.",
        "ur_latin": "Koi baat nahi — main ne aap ke liye {when} note kar liya hai, hamare agent yahin aap se confirm kar lenge.",
        "ur": "کوئی بات نہیں — میں نے آپ کے لیے {when} نوٹ کر لیا ہے، ہمارے ایجنٹ یہیں آپ سے کنفرم کر لیں گے۔",
        "hi_latin": "Koi baat nahi — maine aapke liye {when} note kar liya hai, hamare agent yahin aapse confirm kar lenge.",
        "hi": "कोई बात नहीं — मैंने आपके लिए {when} नोट कर लिया है, हमारे एजेंट यहीं आपसे कन्फ़र्म कर लेंगे।",
    },
    "res_already_rented": {
        "en": "Glad you found a place! Thanks for letting us know.",
        "ar": "يسعدنا أنك وجدت مكاناً! شكراً لإبلاغنا.",
        "ur_latin": "Khushi hui ke aap ko jagah mil gayi! Batane ka shukriya.",
        "ur": "خوشی ہوئی کہ آپ کو جگہ مل گئی! بتانے کا شکریہ۔",
        "hi_latin": "Khushi hui ki aapko jagah mil gayi! Batane ke liye shukriya.",
        "hi": "ख़ुशी हुई कि आपको जगह मिल गई! बताने के लिए शुक्रिया।",
    },
    "res_pay_online": {
        "en": "Our agent will guide you on payment through the company's official process after you choose the unit.",
        "ar": "سيرشدك وكيلنا إلى طريقة الدفع عبر الإجراءات الرسمية للشركة بعد أن تختار الوحدة.",
        "ur_latin": "Unit chunne ke baad hamare agent company ke official process ke zariye payment mein aap ki rehnumai karenge.",
        "ur": "یونٹ چننے کے بعد ہمارے ایجنٹ کمپنی کے آفیشل پراسیس کے ذریعے ادائیگی میں آپ کی رہنمائی کریں گے۔",
        "hi_latin": "Unit chunne ke baad hamare agent company ke official process se payment mein aapko guide karenge.",
        "hi": "यूनिट चुनने के बाद हमारे एजेंट कंपनी की आधिकारिक प्रक्रिया से भुगतान में आपको गाइड करेंगे।",
    },
    "res_no_documents": {
        "en": "Thank you — please don't share ID or bank details here. Our agent collects documents in person, through the company's official process.",
        "ar": "شكراً لك — يرجى عدم مشاركة بيانات الهوية أو البنك هنا. يستلم وكيلنا المستندات شخصياً عبر الإجراءات الرسمية للشركة.",
        "ur_latin": "Shukriya — barah-e-karam yahan ID ya bank ki details share na karein. Hamare agent documents company ke official process ke zariye khud lete hain.",
        "ur": "شکریہ — براہ کرم یہاں آئی ڈی یا بینک کی تفصیلات شیئر نہ کریں۔ ہمارے ایجنٹ دستاویزات کمپنی کے آفیشل پراسیس کے ذریعے خود لیتے ہیں۔",
        "hi_latin": "Shukriya — kripya yahan ID ya bank ki details share na karein. Hamare agent documents company ke official process se khud lete hain.",
        "hi": "शुक्रिया — कृपया यहाँ आईडी या बैंक की जानकारी शेयर न करें। हमारे एजेंट दस्तावेज़ कंपनी की आधिकारिक प्रक्रिया से ख़ुद लेते हैं।",
    },
    "res_deleted": {
        "en": "Done — we won't message you again, and we've asked our team to delete your details.",
        "ar": "تم — لن نرسل لك رسائل أخرى، وطلبنا من فريقنا حذف بياناتك.",
        "ur_latin": "Ho gaya — hum aap ko dobara message nahi karenge, aur hum ne apni team ko aap ki details delete karne ka keh diya hai.",
        "ur": "ہو گیا — ہم آپ کو دوبارہ میسج نہیں کریں گے، اور ہم نے اپنی ٹیم کو آپ کی تفصیلات ڈیلیٹ کرنے کا کہہ دیا ہے۔",
        "hi_latin": "Ho gaya — hum aapko dobara message nahi karenge, aur humne apni team ko aapki details delete karne ke liye keh diya hai.",
        "hi": "हो गया — हम आपको दोबारा मैसेज नहीं करेंगे, और हमने अपनी टीम से आपकी जानकारी डिलीट करने के लिए कह दिया है।",
    },
    "res_voice_failed": {
        "en": "Sorry, I couldn't hear your voice note. Could you type your message here?",
        "ar": "عذراً، لم أتمكن من سماع رسالتك الصوتية. هل يمكنك كتابة رسالتك هنا؟",
        "ur_latin": "Maazrat, main aap ka voice note sun nahi saka. Kya aap apna message yahan likh sakte hain?",
        "ur": "معذرت، میں آپ کا وائس نوٹ سن نہیں سکا۔ کیا آپ اپنا میسج یہاں لکھ سکتے ہیں؟",
        "hi_latin": "Maafi, main aapka voice note sun nahi paya. Kya aap apna message yahan likh sakte hain?",
        "hi": "माफ़ी, मैं आपका वॉइस नोट सुन नहीं पाया। क्या आप अपना मैसेज यहाँ लिख सकते हैं?",
    },
    # Q38: no phone number is ever given; our team replies in this chat, and the office address and Maps link go instead.
    "res_no_number": {
        "en": "Our team will reply to you here in this chat. You're also welcome at our office:",
        "ar": "سيرد عليك فريقنا هنا في هذه المحادثة. ويسعدنا أيضاً أن تزور مكتبنا:",
        "ur_latin": "Hamari team yahin isi chat mein aap ko jawab degi. Aap hamare office bhi tashreef la sakte hain:",
        "ur": "ہماری ٹیم یہیں اسی چیٹ میں آپ کو جواب دے گی۔ آپ ہمارے آفس بھی تشریف لا سکتے ہیں:",
        "hi_latin": "Hamari team yahin isi chat mein aapko jawab degi. Aap hamare office bhi aa sakte hain:",
        "hi": "हमारी टीम यहीं इसी चैट में आपको जवाब देगी। आप हमारे ऑफ़िस भी आ सकते हैं:",
    },
    # A switch to shops (spec §1.5), before the shops' for-whom question or the list.
    "res_switch_shop": {
        "en": "Sure! We have shops in International City too.",
        "ar": "أكيد! لدينا محلات في المدينة العالمية أيضاً.",
        "ur_latin": "Ji zaroor! Hamare paas International City mein shops bhi hain.",
        "ur": "جی ضرور! ہمارے پاس انٹرنیشنل سٹی میں دکانیں بھی ہیں۔",
        "hi_latin": "Ji zaroor! Hamare paas International City mein shops bhi hain.",
        "hi": "जी ज़रूर! हमारे पास इंटरनेशनल सिटी में दुकानें भी हैं।",
    },
    # The neutral invitation after a second unclear answer on the not-known track (Q25's own words), before two slots.
    "res_invite_neutral": {
        "en": "We have many options in International City and across Dubai. Visit our office and we'll give you the best option.",
        "ar": "لدينا خيارات كثيرة في المدينة العالمية وفي جميع أنحاء دبي. تفضل بزيارة مكتبنا وسنقدم لك أفضل خيار.",
        "ur_latin": "Hamare paas International City aur poore Dubai mein bohat se options hain. Hamare office tashreef layein, hum aap ko sab se behtar option denge.",
        "ur": "ہمارے پاس انٹرنیشنل سٹی اور پورے دبئی میں بہت سے آپشنز ہیں۔ ہمارے آفس تشریف لائیں، ہم آپ کو سب سے بہتر آپشن دیں گے۔",
        "hi_latin": "Hamare paas International City aur poore Dubai mein bahut saare options hain. Hamare office aaiye, hum aapko sabse behtar option denge.",
        "hi": "हमारे पास इंटरनेशनल सिटी और पूरे दुबई में बहुत सारे विकल्प हैं। हमारे ऑफ़िस आइए, हम आपको सबसे बेहतर विकल्प देंगे।",
    },
    # The rent invitation (spec §2.5), before code's two free slots.
    "res_invite": {
        "en": "Our agent will meet you at our office in Russia Cluster and take you to the available apartments.",
        "ar": "سيقابلك وكيلنا في مكتبنا في كلستر روسيا ويأخذك إلى الشقق المتاحة.",
        "ur_latin": "Hamare agent aap se Russia Cluster mein hamare office mein milenge aur aap ko available apartments dikhane le jayenge.",
        "ur": "ہمارے ایجنٹ آپ سے رشیا کلسٹر میں ہمارے آفس میں ملیں گے اور آپ کو دستیاب اپارٹمنٹس دکھانے لے جائیں گے۔",
        "hi_latin": "Hamare agent aapse Russia Cluster mein hamare office mein milenge aur aapko available apartments dikhane le jayenge.",
        "hi": "हमारे एजेंट आपसे रशिया क्लस्टर में हमारे ऑफ़िस में मिलेंगे और आपको उपलब्ध अपार्टमेंट दिखाने ले जाएँगे।",
    },
}
# res_handover (spec §2.11): our rental or sales team, never a person's name (Q30) nor a number (Q38).
HANDOVER = {
    "en": "Sure, no problem. I've passed your details to our {team} team, so you don't need to explain again. Our agent will reply to you here.",
    "ar": "بالتأكيد، لا مشكلة. أرسلت بياناتك إلى فريق {team} لدينا، فلن تحتاج إلى الشرح مرة أخرى. سيرد عليك وكيلنا هنا.",
    "ur_latin": "Zaroor, koi masla nahi. Main ne aap ki details hamari {team} team ko de di hain, taa ke aap ko dobara samjhana na pade. Hamare agent yahin aap ko jawab denge.",
    "ur": "ضرور، کوئی مسئلہ نہیں۔ میں نے آپ کی تفصیلات ہماری {team} ٹیم کو دے دی ہیں، تاکہ آپ کو دوبارہ سمجھانا نہ پڑے۔ ہمارے ایجنٹ یہیں آپ کو جواب دیں گے۔",
    "hi_latin": "Zaroor, koi dikkat nahi. Maine aapki details hamari {team} team ko de di hain, taaki aapko dobara samjhana na pade. Hamare agent yahin aapko jawab denge.",
    "hi": "ज़रूर, कोई दिक़्क़त नहीं। मैंने आपकी जानकारी हमारी {team} टीम को दे दी है, ताकि आपको दोबारा समझाना न पड़े। हमारे एजेंट यहीं आपको जवाब देंगे।",
}
TEAMS = {
    "en": ("rental", "sales"),
    "ar": ("التأجير", "المبيعات"),
    "ur_latin": ("rental", "sales"),
    "ur": ("رینٹل", "سیلز"),
    "hi_latin": ("rental", "sales"),
    "hi": ("रेंटल", "सेल्स"),
}
# res_commission_figure (spec §2.4): (a studio's, a one-bedroom's, both while the unit is not known), then the close.
COMMISSION_FIGURE = {
    "en": (
        "For a studio, commission is normally around AED {studio} plus {vat}% VAT, depending on the unit.",
        "For a one-bedroom, commission is normally around AED {one_br} plus {vat}% VAT, depending on the unit.",
        "Commission is normally around AED {studio} for a studio and AED {one_br} for a one-bedroom, plus {vat}% VAT, depending on the unit.",
        "You're welcome to see the flat first — we'll confirm every charge clearly before you decide.",
    ),
    "ar": (
        "للاستوديو، تكون العمولة عادةً حوالي AED {studio} بالإضافة إلى {vat}% ضريبة القيمة المضافة، حسب الوحدة.",
        "للشقة بغرفة نوم واحدة، تكون العمولة عادةً حوالي AED {one_br} بالإضافة إلى {vat}% ضريبة القيمة المضافة، حسب الوحدة.",
        "تكون العمولة عادةً حوالي AED {studio} للاستوديو وAED {one_br} للشقة بغرفة نوم واحدة، بالإضافة إلى {vat}% ضريبة القيمة المضافة، حسب الوحدة.",
        "يسعدنا أن تشاهد الشقة أولاً، وسنوضح لك كل الرسوم بوضوح قبل أن تقرر.",
    ),
    "ur_latin": (
        "Studio ke liye commission aam taur par AED {studio} ke qareeb hoti hai, plus {vat}% VAT, unit ke hisaab se.",
        "One-bedroom ke liye commission aam taur par AED {one_br} ke qareeb hoti hai, plus {vat}% VAT, unit ke hisaab se.",
        "Commission aam taur par studio ke liye AED {studio} aur one-bedroom ke liye AED {one_br} ke qareeb hoti hai, plus {vat}% VAT, unit ke hisaab se.",
        "Aap pehle flat dekh lein — faisle se pehle hum har charge saaf saaf confirm kar denge.",
    ),
    "ur": (
        "اسٹوڈیو کے لیے کمیشن عام طور پر تقریباً AED {studio} ہوتی ہے، جمع {vat}% VAT، یونٹ کے حساب سے۔",
        "ون بیڈروم کے لیے کمیشن عام طور پر تقریباً AED {one_br} ہوتی ہے، جمع {vat}% VAT، یونٹ کے حساب سے۔",
        "کمیشن عام طور پر اسٹوڈیو کے لیے تقریباً AED {studio} اور ون بیڈروم کے لیے AED {one_br} ہوتی ہے، جمع {vat}% VAT، یونٹ کے حساب سے۔",
        "آپ پہلے فلیٹ دیکھ لیں — فیصلے سے پہلے ہم ہر چارج صاف صاف کنفرم کر دیں گے۔",
    ),
    "hi_latin": (
        "Studio ke liye commission aam taur par lagbhag AED {studio} hoti hai, plus {vat}% VAT, unit ke hisaab se.",
        "One-bedroom ke liye commission aam taur par lagbhag AED {one_br} hoti hai, plus {vat}% VAT, unit ke hisaab se.",
        "Commission aam taur par studio ke liye lagbhag AED {studio} aur one-bedroom ke liye AED {one_br} hoti hai, plus {vat}% VAT, unit ke hisaab se.",
        "Aap pehle flat dekh lijiye — faisle se pehle hum har charge saaf-saaf confirm kar denge.",
    ),
    "hi": (
        "स्टूडियो के लिए कमीशन आम तौर पर लगभग AED {studio} होती है, साथ में {vat}% VAT, यूनिट के हिसाब से।",
        "वन-बेडरूम के लिए कमीशन आम तौर पर लगभग AED {one_br} होती है, साथ में {vat}% VAT, यूनिट के हिसाब से।",
        "कमीशन आम तौर पर स्टूडियो के लिए लगभग AED {studio} और वन-बेडरूम के लिए AED {one_br} होती है, साथ में {vat}% VAT, यूनिट के हिसाब से।",
        "आप पहले फ्लैट देख लीजिए — फ़ैसले से पहले हम हर चार्ज साफ़-साफ़ कन्फ़र्म कर देंगे।",
    ),
}


def line(kind: str, language: str, **params) -> str:
    """Code's fixed line ``kind`` in the customer's language, its parameters filled ("{when}", "{vat}")."""
    table = LINES[kind]
    text = table.get(_lang(language)) or table["en"]
    if kind == "res_vat":
        params.setdefault("vat", DEFAULT_RESIDENTIAL_FACTS["charges"]["vat_percent"])
    return text.format(**params) if params else text


def handover_line(language: str, track: str = RENT) -> str:
    """res_handover: our rental team (the sales team on the sale track); no name, no number."""
    lang = _lang(language)
    team = TEAMS[lang][1 if track == SALE else 0]
    return HANDOVER[lang].format(team=team)


def commission_figure_line(language: str, unit: str, facts=None) -> str:
    """res_commission_figure: the unit's commission and VAT (both units, each labelled, while the unit is not known)."""
    lang = _lang(language)
    clean = _clean(facts)
    studio, one_br, both, close = COMMISSION_FIGURE[lang]
    values = {
        "studio": band_text(clean["charges"]["commission"][STUDIO]),
        "one_br": band_text(clean["charges"]["commission"][ONE_BR]),
        "vat": clean["charges"]["vat_percent"],
    }
    head = {STUDIO: studio, ONE_BR: one_br}.get(unit, both)
    return f"{head.format(**values)} {close}"


def vat_line(language: str, facts=None) -> str:
    return line("res_vat", language, vat=_clean(facts)["charges"]["vat_percent"])


# The openers (Appendix C) ---------------------------------------------------------------------------------------------

_SORRY = {
    "en": "Sorry for the confusion! ",
    "ar": "نعتذر عن اللبس! ",
    "ur_latin": "Ghalat-fehmi ke liye maazrat! ",
    "ur": "غلط فہمی کے لیے معذرت! ",
    "hi_latin": "Galatfehmi ke liye maafi! ",
    "hi": "ग़लतफ़हमी के लिए माफ़ी! ",
}
_SURE = {"en": "Sure!", "ar": "أكيد!", "ur_latin": "Ji zaroor!", "ur": "جی ضرور!", "hi_latin": "Ji zaroor!", "hi": "जी ज़रूर!"}
# "{Studios|One-bedrooms} in {where} are generally around AED {band} a year."
_RENT_BAND = {
    "en": ("Studios in {where} are generally around AED {band} a year.", "One-bedrooms in {where} are generally around AED {band} a year."),
    "ar": ("الاستوديوهات في {where} تكون عادةً حوالي AED {band} سنوياً.", "الشقق بغرفة نوم واحدة في {where} تكون عادةً حوالي AED {band} سنوياً."),
    "ur_latin": (
        "{where} mein studios aam taur par AED {band} saalana ke qareeb hote hain.",
        "{where} mein one-bedroom apartments aam taur par AED {band} saalana ke qareeb hote hain.",
    ),
    "ur": ("{where} میں اسٹوڈیو عام طور پر تقریباً AED {band} سالانہ کے ہوتے ہیں۔", "{where} میں ون بیڈروم اپارٹمنٹ عام طور پر تقریباً AED {band} سالانہ کے ہوتے ہیں۔"),
    "hi_latin": (
        "{where} mein studios aam taur par lagbhag AED {band} saalana hote hain.",
        "{where} mein one-bedroom apartments aam taur par lagbhag AED {band} saalana hote hain.",
    ),
    "hi": ("{where} में स्टूडियो आम तौर पर लगभग AED {band} सालाना होते हैं।", "{where} में वन-बेडरूम अपार्टमेंट आम तौर पर लगभग AED {band} सालाना होते हैं।"),
}
_IC = {"en": "International City", "ar": "المدينة العالمية", "ur_latin": "International City", "ur": "انٹرنیشنل سٹی", "hi_latin": "International City", "hi": "इंटरनेशनल सिटी"}
_FOR_WHOM = {
    "en": "Are you looking for yourself or for a client?",
    "ar": "هل تبحث لنفسك أم لعميل؟",
    "ur_latin": "Kya aap apne liye dekh rahe hain ya kisi client ke liye?",
    "ur": "کیا آپ اپنے لیے دیکھ رہے ہیں یا کسی کلائنٹ کے لیے؟",
    "hi_latin": "Kya aap apne liye dekh rahe hain ya kisi client ke liye?",
    "hi": "क्या आप अपने लिए देख रहे हैं या किसी क्लाइंट के लिए?",
}
# Brief Part 5, step 2: the next questions once we know who it is for.
_BALCONY_MOVE = {
    "en": "Do you prefer a balcony, and when are you planning to move?",
    "ar": "هل تفضّل شقة مع شرفة، ومتى تخطط للانتقال؟",
    "ur_latin": "Kya aap balcony pasand karenge, aur aap kab shift hona chahte hain?",
    "ur": "کیا آپ بالکونی پسند کریں گے، اور آپ کب شفٹ ہونا چاہتے ہیں؟",
    "hi_latin": "Kya aap balcony pasand karenge, aur aap kab shift hona chahte hain?",
    "hi": "क्या आप बालकनी पसंद करेंगे, और आप कब शिफ़्ट होना चाहते हैं?",
}
# res_open_rent_any: the unit not known yet.
_RENT_ANY = {
    "en": ("Sure! We can help with studios and one-bedroom apartments in International City.", "Are you looking for a studio or a one-bedroom, and is it for yourself or for a client?", "Are you looking for a studio or a one-bedroom?"),
    "ar": ("أكيد! يمكننا مساعدتك في الاستوديوهات والشقق بغرفة نوم واحدة في المدينة العالمية.", "هل تبحث عن استوديو أم شقة بغرفة نوم واحدة، وهل هي لك أم لعميل؟", "هل تبحث عن استوديو أم شقة بغرفة نوم واحدة؟"),
    "ur_latin": ("Ji zaroor! Hum International City mein studio aur one-bedroom apartments mein madad kar sakte hain.", "Aap ko studio chahiye ya one-bedroom, aur kya yeh aap ke apne liye hai ya kisi client ke liye?", "Aap ko studio chahiye ya one-bedroom?"),
    "ur": ("جی ضرور! ہم انٹرنیشنل سٹی میں اسٹوڈیو اور ون بیڈروم اپارٹمنٹس میں مدد کر سکتے ہیں۔", "آپ کو اسٹوڈیو چاہیے یا ون بیڈروم، اور کیا یہ آپ کے اپنے لیے ہے یا کسی کلائنٹ کے لیے؟", "آپ کو اسٹوڈیو چاہیے یا ون بیڈروم؟"),
    "hi_latin": ("Ji zaroor! Hum International City mein studio aur one-bedroom apartments mein madad kar sakte hain.", "Aapko studio chahiye ya one-bedroom, aur kya yeh aapke apne liye hai ya kisi client ke liye?", "Aapko studio chahiye ya one-bedroom?"),
    "hi": ("जी ज़रूर! हम इंटरनेशनल सिटी में स्टूडियो और वन-बेडरूम अपार्टमेंट में मदद कर सकते हैं।", "आपको स्टूडियो चाहिए या वन-बेडरूम, और क्या यह आपके अपने लिए है या किसी क्लाइंट के लिए?", "आपको स्टूडियो चाहिए या वन-बेडरूम?"),
}
# res_open_sale: (a cluster acknowledged, none known); brief Part 5B, message 1.
_SALE_OPEN = {
    "en": ("{where} is a great choice, and we can check other clusters too.", "We can help you buy a studio or a one-bedroom in International City."),
    "ar": ("{where} خيار ممتاز، ويمكننا أيضاً البحث في كلسترات أخرى.", "يمكننا مساعدتك في شراء استوديو أو شقة بغرفة نوم واحدة في المدينة العالمية."),
    "ur_latin": ("{where} behtareen choice hai, aur hum doosre clusters bhi dekh sakte hain.", "Hum International City mein studio ya one-bedroom khareedne mein aap ki madad kar sakte hain."),
    "ur": ("{where} بہترین انتخاب ہے، اور ہم دوسرے کلسٹر بھی دیکھ سکتے ہیں۔", "ہم انٹرنیشنل سٹی میں اسٹوڈیو یا ون بیڈروم خریدنے میں آپ کی مدد کر سکتے ہیں۔"),
    "hi_latin": ("{where} badhiya choice hai, aur hum doosre clusters bhi dekh sakte hain.", "Hum International City mein studio ya one-bedroom kharidne mein aapki madad kar sakte hain."),
    "hi": ("{where} बढ़िया विकल्प है, और हम दूसरे क्लस्टर भी देख सकते हैं।", "हम इंटरनेशनल सिटी में स्टूडियो या वन-बेडरूम ख़रीदने में आपकी मदद कर सकते हैं।"),
}
# Brief Part 5B, message 2: a buyer we know is no broker (Q2 and Q3).
_SALE_NEXT = {
    "en": "Are you a cash buyer or planning to use finance? And how soon are you looking to buy?",
    "ar": "هل ستشتري نقداً أم بتمويل؟ ومتى تخطط للشراء؟",
    "ur_latin": "Kya aap cash buyer hain ya finance (mortgage) lenge? Aur aap kitni jaldi khareedna chahte hain?",
    "ur": "کیا آپ کیش خریدار ہیں یا فنانس (مارگیج) لیں گے؟ اور آپ کتنی جلدی خریدنا چاہتے ہیں؟",
    "hi_latin": "Kya aap cash buyer hain ya finance (mortgage) lenge? Aur aap kitni jaldi kharidna chahte hain?",
    "hi": "क्या आप कैश ख़रीदार हैं या फ़ाइनेंस (मॉर्गेज) लेंगे? और आप कितनी जल्दी ख़रीदना चाहते हैं?",
}


def cluster_words(language: str, cluster: str) -> str:
    """'Spain Cluster' in the customer's language (tracks' script names)."""
    lang = _lang(language)
    arabic, urdu, hindi = tracks._CLUSTER_SCRIPT.get(cluster, (cluster, cluster, cluster))
    return {
        "en": f"{cluster} Cluster", "ar": f"كلستر {arabic}", "ur_latin": f"{cluster} Cluster", "ur": f"{urdu} کلسٹر",
        "hi_latin": f"{cluster} Cluster", "hi": f"{hindi} क्लस्टर",
    }[lang]


def _one_cluster(clusters) -> str:
    names = _named(clusters)
    return names[0] if len(names) == 1 else ""


def opener_kind(track: str, unit: str) -> str:
    if track == SALE:
        return "res_open_sale"
    return "res_open_rent" if unit in (STUDIO, ONE_BR) else "res_open_rent_any"


# Rent asked by the month (launch chat 57): the opener says how it is paid.
_YEARLY = {
    "en": "Rent here is paid yearly, in 1 to 4 cheques depending on the owner.",
    "ar": "الإيجار هنا سنوي، ويُدفع على 1 إلى 4 شيكات حسب المالك.",
    "ur_latin": "Yahan rent saalana hota hai, owner ke hisaab se 1 se 4 cheques mein.",
    "ur": "یہاں کرایہ سالانہ ہوتا ہے، مالک کے حساب سے 1 سے 4 چیکس میں۔",
    "hi_latin": "Yahan rent saalana hota hai, owner ke hisaab se 1 se 4 cheques mein.",
    "hi": "यहाँ किराया सालाना होता है, मालिक के हिसाब से 1 से 4 चेक में।",
}
_MONTHLY = re.compile(r"\bmonthly\b|\bper\s+month\b|\ba\s+month\b|\bmonth\s+(?:rent|basis|wise)\b|\bmahina\w*|\bmaheena\w*|شهري|بالشهر|ماہانہ|महीना|मासिक", re.IGNORECASE)


def asks_monthly(texts) -> bool:
    return any(_MONTHLY.search(str(text or "")) for text in texts or ())


def opener_text(
    language: str, track: str, unit: str = "", clusters=(), *, for_client_known: bool = False, sorry: bool = False, facts=None,
    monthly: bool = False,
) -> str:
    """The first reply on a rent or sale track, code's with no model (spec §1.4.3, Appendix C), skipping what is known:

    - res_open_rent: "Sure! Studios in Spain Cluster are generally around AED 29,000–33,000 a year. Are you looking for
      yourself or for a client?" (a one-bedroom in a European cluster gets that band); once we know who it is for, the
      balcony and move-in question instead;
    - res_open_rent_any: the unit not known yet, "Are you looking for a studio or a one-bedroom, and is it for yourself or
      for a client?";
    - res_open_sale: "Sure! Spain Cluster is a great choice, and we can check other clusters too. Are you looking for
      yourself or for a client?", then the cash-or-finance and how-soon questions once we know.
    ``sorry``: we talked about the other thing, or they never asked about a shop: the opener apologises first;
    ``monthly``: they asked for a monthly rent (launch chat 57): the yearly band, and how it is paid."""
    lang = _lang(language)
    head = _SORRY[lang] if sorry else ""
    cluster = _one_cluster(clusters)
    kind = opener_kind(track, unit)
    if kind == "res_open_sale":
        known, none = _SALE_OPEN[lang]
        body = known.format(where=cluster_words(lang, cluster)) if cluster else none
        question = _SALE_NEXT[lang] if for_client_known else _FOR_WHOM[lang]
        return f"{head}{_SURE[lang]} {body} {question}"
    if kind == "res_open_rent_any":
        intro, ask, ask_unit = _RENT_ANY[lang]
        return f"{head}{intro} {ask_unit if for_client_known else ask}"
    band = rent_band(unit, clusters, facts)
    where = cluster_words(lang, cluster) if cluster else _IC[lang]
    sentence = _RENT_BAND[lang][0 if unit == STUDIO else 1].format(where=where, band=band_text(band))
    if monthly:
        sentence = f"{sentence} {_YEARLY[lang]}"
    question = _BALCONY_MOVE[lang] if for_client_known else _FOR_WHOM[lang]
    return f"{head}{_SURE[lang]} {sentence} {question}"


def invite_text(language: str, slots, now, office_address: str = "") -> str:
    """The rent invitation (spec §2.5): "Our agent will meet you at our office in Russia Cluster and take you to the
    available apartments." and code's two free slots (shops.slot_offer). The office's cluster is named only while
    OFFICE says Russia Cluster."""
    from . import shops

    lang = _lang(language)
    first = line("res_invite", lang)
    if office_address and "russia" not in office_address.casefold():
        first = {
            "en": "Our agent will meet you at our office and take you to the available apartments.",
            "ar": "سيقابلك وكيلنا في مكتبنا ويأخذك إلى الشقق المتاحة.",
            "ur_latin": "Hamare agent aap se hamare office mein milenge aur aap ko available apartments dikhane le jayenge.",
            "ur": "ہمارے ایجنٹ آپ سے ہمارے آفس میں ملیں گے اور آپ کو دستیاب اپارٹمنٹس دکھانے لے جائیں گے۔",
            "hi_latin": "Hamare agent aapse hamare office mein milenge aur aapko available apartments dikhane le jayenge.",
            "hi": "हमारे एजेंट आपसे हमारे ऑफ़िस में मिलेंगे और आपको उपलब्ध अपार्टमेंट दिखाने ले जाएँगे।",
        }[lang]
    offer = shops.slot_offer(lang, list(slots or ()), now)
    return f"{first} {offer}".strip()


def neutral_text(language: str, slots, now) -> str:
    """res_invite_neutral: Q25's own words and two free slots (the question for a time when none is free)."""
    from . import shops

    lang = _lang(language)
    offer = shops.slot_offer(lang, list(slots or ()), now) if slots else rules.line("ask_time", lang)
    return f"{line('res_invite_neutral', lang)} {offer}".strip()


def switch_shop_text(language: str, *, ask_for_whom: bool = True) -> str:
    """A switch to shops (spec §1.5): "Sure! We have shops in International City too." and the shops' for-whom question
    while we do not know who the shop is for."""
    lang = _lang(language)
    head = line("res_switch_shop", lang)
    if not ask_for_whom:
        return head
    question = filters.split_sentences(rules.line("for_whom", lang))[-1]
    return f"{head} {question}"


def no_number_text(language: str, office_address: str, maps_url: str = "") -> str:
    """Q38: a customer who asks for a number gets none: our team replies in this chat, and the office address and the
    Maps link."""
    where = "\n".join(part for part in (office_address, maps_url) if part)
    return f"{line('res_no_number', language)}\n{where}".strip()


def name_hold_text(language: str, start, now) -> str:
    """res_name_hold: the time they wanted is noted, and our agent confirms it here (no name, no booking)."""
    from . import shops

    lang = _lang(language)
    when = shops.slots_phrase([start], now, lang) if start is not None else hours.time_label(now)
    return line("res_name_hold", lang, when=when)


# Confirmations (spec §2.7, §3.3) --------------------------------------------------------------------------------------

_CONFIRM = {
    "en": {
        "visit": "Perfect{name}! Your viewing is confirmed ✅",
        "meeting": "Perfect{name}! Your meeting is confirmed ✅",
        "visit_moved": "Done{name}! Your viewing is now on:",
        "meeting_moved": "Done{name}! Your meeting is now on:",
        "labels": ("Date", "Time", "Place"),
        "visit_close": "Our agent will meet you at the office and take you to the available apartments, a short drive away. See you soon!",
        "meeting_close": "Our agent will meet you at the office. See you soon!",
        "call": "Perfect{name}! Your 5-minute call with our sales team is booked for {day} at {time}. We'll call you on this number. Speak soon!",
    },
    "ar": {
        "visit": "ممتاز{name}! تم تأكيد موعد المعاينة ✅",
        "meeting": "ممتاز{name}! تم تأكيد موعدك ✅",
        "visit_moved": "تم{name}! أصبح موعد المعاينة:",
        "meeting_moved": "تم{name}! أصبح موعدك:",
        "labels": ("التاريخ", "الوقت", "المكان"),
        "visit_close": "سيقابلك وكيلنا في المكتب ويأخذك إلى الشقق المتاحة، على مسافة قصيرة بالسيارة. نراك قريباً!",
        "meeting_close": "سيقابلك وكيلنا في المكتب. نراك قريباً!",
        "call": "ممتاز{name}! تم حجز مكالمة لمدة 5 دقائق مع فريق المبيعات لدينا يوم {day} الساعة {time}. سنتصل بك على هذا الرقم. إلى اللقاء!",
    },
    "ur_latin": {
        "visit": "Perfect{name}! Aap ki viewing confirm ho gayi hai ✅",
        "meeting": "Perfect{name}! Aap ki meeting confirm ho gayi hai ✅",
        "visit_moved": "Ho gaya{name}! Aap ki viewing ab is waqt hai:",
        "meeting_moved": "Ho gaya{name}! Aap ki meeting ab is waqt hai:",
        "labels": ("Date", "Time", "Jagah"),
        "visit_close": "Hamare agent aap se office mein milenge aur aap ko available apartments dikhane le jayenge, thodi si drive par. Jald milte hain!",
        "meeting_close": "Hamare agent aap se office mein milenge. Jald milte hain!",
        "call": "Perfect{name}! Hamari sales team ke saath aap ki 5 minute ki call {day}, {time} ke liye book ho gayi hai. Hum aap ko isi number par call karenge. Jald baat hoti hai!",
    },
    "ur": {
        "visit": "بہت خوب{name}! آپ کی ویونگ کنفرم ہو گئی ہے ✅",
        "meeting": "بہت خوب{name}! آپ کی میٹنگ کنفرم ہو گئی ہے ✅",
        "visit_moved": "ہو گیا{name}! آپ کی ویونگ اب اس وقت ہے:",
        "meeting_moved": "ہو گیا{name}! آپ کی میٹنگ اب اس وقت ہے:",
        "labels": ("تاریخ", "وقت", "جگہ"),
        "visit_close": "ہمارے ایجنٹ آپ سے آفس میں ملیں گے اور آپ کو دستیاب اپارٹمنٹس دکھانے لے جائیں گے، تھوڑی سی ڈرائیو پر۔ جلد ملتے ہیں!",
        "meeting_close": "ہمارے ایجنٹ آپ سے آفس میں ملیں گے۔ جلد ملتے ہیں!",
        "call": "بہت خوب{name}! ہماری سیلز ٹیم کے ساتھ آپ کی 5 منٹ کی کال {day}، {time} کے لیے بک ہو گئی ہے۔ ہم آپ کو اسی نمبر پر کال کریں گے۔ جلد بات ہوتی ہے!",
    },
    "hi_latin": {
        "visit": "Perfect{name}! Aapki viewing confirm ho gayi hai ✅",
        "meeting": "Perfect{name}! Aapki meeting confirm ho gayi hai ✅",
        "visit_moved": "Ho gaya{name}! Aapki viewing ab is time par hai:",
        "meeting_moved": "Ho gaya{name}! Aapki meeting ab is time par hai:",
        "labels": ("Date", "Time", "Jagah"),
        "visit_close": "Hamare agent aapse office mein milenge aur aapko available apartments dikhane le jayenge, thodi si drive par. Jald milte hain!",
        "meeting_close": "Hamare agent aapse office mein milenge. Jald milte hain!",
        "call": "Perfect{name}! Hamari sales team ke saath aapki 5 minute ki call {day}, {time} ke liye book ho gayi hai. Hum aapko isi number par call karenge. Jald baat karte hain!",
    },
    "hi": {
        "visit": "बहुत बढ़िया{name}! आपकी व्यूइंग कन्फ़र्म हो गई है ✅",
        "meeting": "बहुत बढ़िया{name}! आपकी मीटिंग कन्फ़र्म हो गई है ✅",
        "visit_moved": "हो गया{name}! आपकी व्यूइंग अब इस समय है:",
        "meeting_moved": "हो गया{name}! आपकी मीटिंग अब इस समय है:",
        "labels": ("तारीख़", "समय", "जगह"),
        "visit_close": "हमारे एजेंट आपसे ऑफ़िस में मिलेंगे और आपको उपलब्ध अपार्टमेंट दिखाने ले जाएँगे, थोड़ी ही ड्राइव पर। जल्द मिलते हैं!",
        "meeting_close": "हमारे एजेंट आपसे ऑफ़िस में मिलेंगे। जल्द मिलते हैं!",
        "call": "बहुत बढ़िया{name}! हमारी सेल्स टीम के साथ आपकी 5 मिनट की कॉल {day}, {time} के लिए बुक हो गई है। हम आपको इसी नंबर पर कॉल करेंगे। जल्द बात करते हैं!",
    },
}
# How a name follows the head's first word ("Perfect, Ahmed Khan!", "ممتاز يا أحمد خان!").
_NAME_JOIN = {"en": ", {name}", "ar": " {name}", "ur_latin": ", {name}", "ur": " {name}", "hi_latin": ", {name}", "hi": " {name}"}
VISIT, CALL = "visit", "call"
OFFICE = "office"  # an appointment's place (LeadAiAppointment.Place: "office", and "call" for a buyer's call, slice C)


def confirmation(
    language: str,
    start,
    *,
    kind: str = VISIT,
    full_name: str = "",
    unit: str = "",
    clusters=(),
    office_address: str = "",
    maps_url: str = "",
    track: str = RENT,
    rescheduled: bool = False,
) -> str:
    """The booking message of the rent and sale tracks, from the checked time, in six languages; it names no agent
    (Q30) and promises no travel time (brief Part 8):

    - ``kind`` "visit": a rent viewing ("Perfect, Ahmed Khan! Your viewing is confirmed ✅", the date, the time, our
      office and its Maps link, "Our agent will meet you at the office and take you to the available apartments, a short
      drive away. See you soon!"), or on the sale track an office meeting ("Our agent will meet you at the office.");
      ``rescheduled``: the same for a move ("Done, Ahmed Khan! Your viewing is now on:");
    - ``kind`` "call": the sale track's 5-minute call (res_call_booked, spec §3.3): "Perfect, Ahmed Khan! Your 5-minute
      call with our sales team is booked for Monday 19 October at 4:00 PM. We'll call you on this number. Speak soon!"
    ``full_name``: the name it is booked under (full_name_known); ``unit`` and ``clusters`` are kept for the callers'
    symmetry with the sales flow and change no word today."""
    lang = _lang(language)
    words = _CONFIRM[lang]
    name = filters.cased(" ".join(str(full_name or "").split()))[:FULL_NAME_MAX]
    joined = _NAME_JOIN[lang].format(name=name) if name else ""
    if kind == CALL:
        return words["call"].format(name=joined, day=hours.day_label(start), time=hours.time_label(start))
    what = "visit" if track != SALE else "meeting"
    head = words[f"{what}_moved" if rescheduled else what].format(name=joined)
    day_word, time_word, place_word = words["labels"]
    lines = [head, f"{day_word}: {hours.day_label(start)}", f"{time_word}: {hours.time_label(start)}"]
    if office_address:
        lines.append(f"{place_word}: {office_address}")
    if maps_url:
        lines.append(maps_url)
    if not rescheduled:
        lines.append(words[f"{what}_close"])
    return "\n".join(lines)


# The full name (spec §2.6) -------------------------------------------------------------------------------------------

FULL_NAME_MAX = 80
# A hold nobody answers lapses this long after our ask (tasks.lapse_name_holds).
NAME_HOLD_LAPSES = dt.timedelta(minutes=30)
# Our message that asked for the full name carries this payload, read back by the next turn.
FULL_NAME_STEP = "full_name"
HELD_FOR_NAME = "held_for_name"
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$")
_NAME_WORD = re.compile(r"^[^\W\d_]+(?:['’\-.][^\W\d_]+)*\.?$", re.UNICODE)
_HONORIFIC = frozenset({"mr", "mrs", "ms", "miss", "dr", "sir", "madam", "maam", "mam", "eng", "engr", "prof", "capt", "sheikh"})
# Words of a reply that is no name ("yes ok", "why need", "no thanks", "kal aaunga").
_NOT_NAME_WORDS = frozenset(
    """
    yes yeah yep ok okay sure fine no not nope why what how when where which who whom please pls plz thanks thank
    thankyou you your u ur me my mine i am im is are it its this that the a an and or but so for to of in on at
    sir madam bro dear hi hello hey salam salaam assalam alaikum habibi good morning evening afternoon night
    need want book booking name full later now today tomorrow tonight come coming visit viewing time slot pm am
    studio flat apartment room bedroom shop rent buy yes. no. ok. ji haan han nahi nahin hai hain kal aaj theek thik
    acha achha shukriya dont don't won't cant can't great perfect deal sounds done alright cool nice wow wait hold
    moment minute send share give tell call agent office location address
    """.split()
)
_NAME_PREFIX = re.compile(
    r"^\s*(?:(?:my\s+)?(?:full\s+)?name\s+is|my\s+name['’]?s|name\s*[:\-]|it['’]?s|its|this\s+is|i\s+am|i['’]?m|im"
    r"|mera\s+naam|my\s+name|اسمي|اسم\s*:|میرا\s+نام|मेरा\s+नाम)\s*",
    re.IGNORECASE,
)
_NAME_SUFFIX = re.compile(r"\s*(?:hai|hain|he|ہے|है)\s*[.!]*\s*$", re.IGNORECASE)


def clean_full_name(value) -> str:
    """facts.full_name as kept: one line, at most FULL_NAME_MAX characters, no digits and no markup, its case put
    right; '' when it cannot be a name."""
    text = " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    if not text or len(text) > FULL_NAME_MAX or any(ch.isdigit() for ch in text) or _MARKUP.search(text) or "@" in text:
        return ""
    return filters.cased(text)


def name_words(name: str) -> list[str]:
    """The words of a name that are a person's: letters only, never an honorific or a placeholder ("Mr", "Lead")."""
    out = []
    for word in str(name or "").split():
        bare = word.strip(".,")
        if not bare or not _NAME_WORD.match(bare):
            continue
        folded = bare.casefold().strip(".")
        if folded in _HONORIFIC or filters.person_name(bare) == "":
            continue
        out.append(bare)
    return out


def is_full_name(name: str) -> bool:
    """At least two alphabetic words of a person's (spec §2.6)."""
    return len(name_words(name)) >= 2


def full_name_known(facts: dict | None, lead: dict | None = None) -> str:
    """The customer's full name, when it is known: facts.full_name with two alphabetic words or more (their own words),
    else the lead's NAME and LAST_NAME when both are a person's (lead_context: filters.person_name, no portal words);
    '' otherwise, and the rent or sale booking waits for it (full_name_gate)."""
    own = clean_full_name((facts or {}).get("full_name"))
    if own and is_full_name(own):
        return own
    lead = lead or {}
    first, last = str(lead.get("name") or "").strip(), str(lead.get("last_name") or "").strip()
    if first and last and name_words(first) and name_words(last) and first.casefold() != last.casefold():
        return clean_full_name(f"{first} {last}")
    return ""


def name_from_reply(text: str) -> str:
    """Code's fallback for the full name, right after our ask (spec §2.6): a reply of two to four alphabetic words, with
    no digits and no question mark ("Ahmed Khan", "my name is Ahmed Khan", "mera naam Ahmed Raza hai"), else ''."""
    raw = " ".join(unicodedata.normalize("NFKC", str(text or "")).split())
    if not raw or any(ch.isdigit() for ch in raw) or any(mark in raw for mark in filters.QUESTION_MARKS):
        return ""
    body = _NAME_SUFFIX.sub("", _NAME_PREFIX.sub("", raw)).strip(" .,!")
    words = body.split()
    if not 2 <= len(words) <= 4:
        return ""
    if any(not _NAME_WORD.match(word.strip(",")) for word in words):
        return ""
    if any(word.casefold().strip(".,") in _NOT_NAME_WORDS for word in words):
        return ""
    name = clean_full_name(body)
    return name if is_full_name(name) else ""


_REFUSES_NAME = re.compile(
    r"\b(?:no|nope|not\s+now|later|skip|never\s*mind|why\s+(?:do\s+)?(?:you\s+)?(?:need|want)|what\s+for|no\s+need"
    r"|(?:do\s*n'?t|dont|do\s+not|won'?t|will\s+not|can'?t|cannot)\s+(?:want\s+to\s+)?(?:give|share|tell|say)"
    r"|private|not\s+necessary|unnecessary|nahi|nahin|nhi|zaroorat\s+nahi|naam\s+(?:nahi|nahin))\b"
    r"|^\W*(?:no|nope|nahi|nahin)\W*$|لا\b|ليش|لماذا|نہیں|کیوں|नहीं|क्यों",
    re.IGNORECASE,
)


def refuses_name(texts) -> bool:
    """They will not give their full name: a no, or "why do you need it?" (spec §2.6)."""
    return any(_REFUSES_NAME.search(" ".join(str(text or "").split())) for text in texts or ())


ASK, BOOK = "ask", ""


def full_name_gate(*, track: str, action: str, when, facts: dict | None, lead: dict | None = None) -> str:
    """The brief's must (Part 5, step 5) on the rent and sale tracks only: a confirm or a move to a new time with no full
    name known is no booking (ASK: the time is held as a tentative and code asks for the name); else BOOK ('')."""
    if track not in (RENT, SALE) or action not in ("confirm", "reschedule") or when is None:
        return BOOK
    return BOOK if full_name_known(facts, lead) else ASK


def clean_email(value) -> str:
    """facts.email, kept only when it reads as an address (spec §2.6), else ''."""
    text = str(value or "").strip().lower()
    return text if EMAIL.match(text) else ""


# PDPL (spec §6.3) -------------------------------------------------------------------------------------------------------

# An Emirates ID (784-XXXX-XXXXXXX-X), an IBAN (AE and 21 digits) or a card number (13 to 19 digits that pass Luhn).
_EID = re.compile(r"(?<!\d)784[\s-]?\d{4}[\s-]?\d{7}[\s-]?\d(?!\d)")
_IBAN = re.compile(r"\bAE\s?\d{2}(?:\s?\d){19}\b", re.IGNORECASE)
_CARD = re.compile(r"(?<!\d)(?:\d[\s-]?){12,18}\d(?!\d)")
MASK = "[number removed]"


def _luhn(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        value = int(ch)
        if double:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
        double = not double
    return total % 10 == 0


def _cards(text: str):
    for match in _CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits) and not digits.startswith("971"):
            yield match


def has_private_number(text: str) -> bool:
    """An Emirates ID, an IBAN or a card number in what they sent."""
    text = str(text or "")
    return bool(_EID.search(text) or _IBAN.search(text) or any(True for _ in _cards(text)))


def mask(text):
    """The words with every Emirates ID, IBAN and card number masked (what Lead AI writes: facts, notes, alerts, comments).
    Anything that is no string comes back as it was."""
    if not isinstance(text, str) or not text:
        return text
    out = _EID.sub(MASK, text)
    out = _IBAN.sub(MASK, out)
    for match in sorted(_cards(out), key=lambda m: m.start(), reverse=True):
        out = out[: match.start()] + MASK + out[match.end() :]
    return out


def mask_facts(facts: dict) -> list[str]:
    """Masks the numbers in a turn's facts in place (strings, and the notes list); the keys it changed."""
    changed = []
    for key, value in list((facts or {}).items()):
        if isinstance(value, str) and has_private_number(value):
            facts[key] = mask(value)
            changed.append(key)
        elif isinstance(value, list) and any(isinstance(item, str) and has_private_number(item) for item in value):
            facts[key] = [mask(item) if isinstance(item, str) else item for item in value]
            changed.append(key)
    return changed


_DELETE_DATA = re.compile(
    r"\b(?:delete|remove|erase|wipe|clear)\s+(?:all\s+)?(?:my|our)\s+(?:data|details|information|info|number|contact|records?|personal\s+data)\b"
    r"|\b(?:my|mera|meri)\s+(?:data|details|number|info)\s+(?:delete|remove|hata\w*|mita\w*)\b"
    r"|\bdata\s+(?:delete|remove)\s+(?:karo|kar\s+do|kardo|karein|kijiye)\b"
    r"|احذف\s+(?:بياناتي|رقمي|معلوماتي)|امسح\s+(?:بياناتي|رقمي)|حذف\s+بياناتي"
    r"|(?:میرا|میری)\s+(?:ڈیٹا|نمبر|معلومات)\s+(?:ڈیلیٹ|ختم|مٹا)"
    r"|(?:मेरा|मेरी)\s+(?:डेटा|नंबर|जानकारी)\s+(?:डिलीट|हटा|मिटा)",
    re.IGNORECASE,
)


def asks_deletion(text: str) -> bool:
    """"Delete my data", "remove my number", "احذف بياناتي", "mera data delete karo": a stop on every number (spec §6.3)."""
    return bool(_DELETE_DATA.search(" ".join(str(text or "").replace("’", "'").split())))


# The model's words (spec §2.9) ------------------------------------------------------------------------------------------

_SENTENCES = re.compile(r"(?<=[.!?؟۔])\s+|\n+")


def _split(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCES.split(str(text or "")) if part.strip()]


def _key(sentence: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(sentence or "").casefold()).split())


def _fixed_sentences() -> set[str]:
    texts = []
    for table in LINES.values():
        texts += [text.format(vat=5, when="", where="") if "{" in text else text for text in table.values()]
    texts += [text.format(team=team) for lang, text in HANDOVER.items() for team in TEAMS[lang]]
    for lang in LANGS:
        texts += [_FOR_WHOM[lang], _BALCONY_MOVE[lang], _SALE_NEXT[lang], *_RENT_ANY[lang]]
        texts.append(COMMISSION_FIGURE[lang][3])
    keys = set()
    for text in texts:
        keys |= {_key(part) for part in [text, *_split(text)] if _key(part)}
    return keys


_FIXED = None


def is_fixed_line(sentence: str) -> bool:
    """One of code's residential lines (or a sentence of one): said again whenever it fits, so the no-repeat guard keeps
    it (engine.settle's ``keep``)."""
    global _FIXED
    if _FIXED is None:
        _FIXED = _fixed_sentences()
    return _key(sentence) in _FIXED


# Commission and VAT: only code's lines (spec §2.4).
_COMMISSION = re.compile(r"\bcommi?ss?ion\w*|\bagency\s+fees?\b|\bbrokerage\b|\bbroker\s+fees?\b|عمولة|العمولة|کمیشن|कमीशन", re.IGNORECASE)
_VAT = re.compile(r"\bvat\b|\bvalue\s+added\s+tax\b|ضريبة|ویٹ|वैट", re.IGNORECASE)
_ASKS_FIGURE = re.compile(
    r"\bhow\s+much\b|\bwhat\s+is\s+the\s+(?:exact\s+)?(?:amount|figure|commission)\b|\bexact\b|\bfigure\b|\bamount\b|\bpercent|\b%"
    r"|\bkitn[aie]\b|\bkitni\b|\bkya\s+hai\b|كم|کتن|कितन",
    re.IGNORECASE,
)


def asks_commission(texts) -> bool:
    return any(_COMMISSION.search(str(text or "")) for text in texts or ())


def asks_vat(texts) -> bool:
    return any(_VAT.search(str(text or "")) for text in texts or ())


def commission_asked_before(earlier) -> bool:
    """An earlier message of theirs asked about the commission, and a message of ours came after it (asked again now)."""
    asked = False
    for author, text in earlier or ():
        if author == "customer" and _COMMISSION.search(str(text or "")):
            asked = True
        elif asked and author in ("assistant", "agent"):
            return True
    return False


def commission_answer(track: str, unit: str, earlier, new_texts, *, language: str = "en", facts=None, shops_facts=None) -> str:
    """The commission line the current track's rule gives when the customer asks about it now, else '' (spec §2.4); the
    caller cuts every commission sentence of the model's first:

    - rent, the first ask: res_commission_first ("Our normal agency commission applies once you choose an apartment you
      like. ..."); asked again (in this chat, on any track before), or for a number: res_commission_figure, the unit's
      AED band plus VAT (both, each labelled, while the unit is not known);
    - shop: Matloob's line (Q24), every time; sale: res_commission_sale until Q33; not known: the first ask's line."""
    from . import claims

    texts = [str(text or "") for text in new_texts or ()]
    if not asks_commission(texts):
        return ""
    if track == tracks.SHOP:
        return claims.commission_line(language)
    if track == SALE:
        return line("res_commission_sale", language)
    figure = commission_asked_before(earlier) or any(_ASKS_FIGURE.search(text) for text in texts)
    if track == RENT and figure:
        return commission_figure_line(language, unit, facts)
    return line("res_commission_first", language)


# Shop words (guard 5): on the rent and sale tracks every sentence about shops; on the not-known track the shop pitch only.
_SHOP_WORDS = re.compile(r"\bshops?\b|\bdukaa?n\w*|\bshowrooms?\b|\bretail\b|محل|محلات|دكان|دکان|دکانیں|शॉप|दुकान", re.IGNORECASE)
_SHOP_PITCH = re.compile(
    r"\btype\s*[123]\b|\bshop\s+types?\b|\btypes?\s+of\s+shops?\b|\bdrive\s+you\b|\b5\s+minutes?\s+away\b"
    r"|\btrade\s+licen[cs]e\b|\bDED\b|\btrakhees\b|\bbusiness\s+activity\b|\bwhat\s+business\b",
    re.IGNORECASE,
)
# The company-documents line names the trade licence and stays (brief Part 7).
_DOCUMENTS_LINE = re.compile(r"\bsignatory\b|\bcompany\s+contract\b|\bcompany's\s+documents\b", re.IGNORECASE)


def drop_shop_words(reply: str, track: str) -> tuple[str, bool]:
    """The reply without its sentences about shops, shop types or the drive to the shops (spec §2.9.5); it keeps "Are you
    looking for yourself or for a client?" and the company-documents line, which 2d's needs.drop_shop_pitch would cut."""
    sentences = _split(reply)

    def cut(sentence: str) -> bool:
        if _DOCUMENTS_LINE.search(sentence):
            return False
        if track in (RENT, SALE) and _SHOP_WORDS.search(sentence):
            return True
        return bool(_SHOP_PITCH.search(sentence))

    kept = [sentence for sentence in sentences if not cut(sentence)]
    if len(kept) == len(sentences):
        return str(reply or "").strip(), False
    return " ".join(kept), True


# Availability, denied by default (guard 6): there is no inventory (D13).
_AVAILABLE = re.compile(
    r"\b(?:is|are|'s|'re|its|it\s+is|they\s+are)\s+(?:still\s+|currently\s+|now\s+|already\s+)?(?:available|vacant|ready|free|empty|there)\b"
    r"|\b(?:currently|now|right\s+now|immediately)\s+(?:available|vacant)\b|\bavailable\s+(?:now|today|immediately|right\s+now)\b"
    r"|\bready\s+to\s+move\b|\bstill\s+available\b"
    r"|\bwe\s+(?:have|'ve\s+got|got|do\s+have)\s+(?:a\s+|an\s+|one\s+|two\s+|some\s+|several\s+|many\s+|few\s+|nice\s+|good\s+)?"
    r"(?:\w+\s+){0,2}(?:studios?|apartments?|flats?|units?|one-?bedrooms?|1\s*-?\s*b\.?h\.?k|1\s*br)\b"
    r"|\b(?:yes|yeah|sure)[,!.]?\s+(?:it|the\s+(?:studio|flat|apartment|unit))\s+(?:is|'s)\b"
    r"|متاح|متاحة|متوفر|متوفرة|شاغر|شاغرة|دستیاب\s+ہے|available\s+hai|available\s+hain|उपलब्ध\s+है|खाली\s+है",
    re.IGNORECASE,
)
_MAY_BE = re.compile(
    r"\b(?:may|might|could|can)\s+(?:also\s+)?be\s+(?:available|vacant)\b|\bif\s+(?:it'?s\s+|they'?re\s+)?(?:still\s+)?available\b"
    r"|\b(?:show|take|bring)\s+you\s+(?:to\s+)?(?:the\s+|all\s+the\s+)?available\s+(?:apartments?|options?|units?|flats?|studios?)\b"
    r"|\bwhat'?s\s+available\b|\bwhich\s+(?:ones?\s+)?(?:are\s+)?available\b|\bcheck\s+(?:the\s+)?availab",
    re.IGNORECASE,
)


def claims_availability(sentence: str) -> bool:
    """The sentence says a unit is available, vacant or ready, or "we have a studio in ..." (spec §2.9.6); "may be
    available" and "our agent will show you the available apartments" do not."""
    text = " ".join(str(sentence or "").replace("’", "'").split())
    return bool(_AVAILABLE.search(text)) and not _MAY_BE.search(text)


# Claims (guard 7): booked, confirmed, reserved, scheduled, sent; never in the model's words unless code booked or sends.
_CLAIM = re.compile(
    r"\b(?:booked|confirmed|reserved|scheduled)\b|\b(?:i'?ve|i\s+have|we'?ve|we\s+have|i|we)\s+(?:just\s+|already\s+)?(?:sent|shared|forwarded)\b"
    r"|\bhere\s+(?:are|is)\s+(?:the\s+)?(?:photos?|pictures?|pics|videos?|images?)\b"
    r"|تم\s+(?:الحجز|التأكيد|حجز|تأكيد)|حجزت|أكدت|أرسلت|ارسلت|بک\s+(?:ہو\s+گئی|کر\s+دی|کر\s+دیا)|کنفرم\s+(?:ہو\s+گئی|کر\s+دی)"
    r"|book\s+(?:ho\s+gayi|kar\s+di|kar\s+diya)|confirm\s+(?:ho\s+gayi|kar\s+di|kar\s+diya)|बुक\s+(?:हो\s+गई|कर\s+दी)|कन्फ़र्म\s+(?:हो\s+गई|कर\s+दी)",
    re.IGNORECASE,
)
_NEGATED_CLAIM = re.compile(r"\b(?:not|n't|yet|once|after|before|until|when|if)\b", re.IGNORECASE)


def claims_done(sentence: str) -> bool:
    """The sentence says something is booked, confirmed, reserved or scheduled, or that we sent something (brief rule 2),
    and not as a condition or a no ("once it's confirmed", "it's not booked yet")."""
    text = " ".join(str(sentence or "").replace("’", "'").split())
    return bool(_CLAIM.search(text)) and not _NEGATED_CLAIM.search(text)


# PDPL asks (guard 8): never for a passport, an Emirates ID, a visa copy or number, bank or card details, an OTP, a password
# or a salary. "Our agent collects them in person" names them and asks nothing.
_PRIVATE = re.compile(
    r"\bpassports?\b|\bemirates\s+id\b|\beid\b|\bvisa\s+(?:copy|number|page|details?)\b|\b(?:copy|copies|photo|scan)\s+of\s+(?:your\s+)?(?:visa|id|passport)\b"
    r"|\bbank\s+(?:details?|account|statement)\b|\biban\b|\b(?:card|credit\s+card|debit\s+card)\s+(?:details?|number)\b|\bcvv\b"
    r"|\botp\b|\bpassword\b|\bsalary\b|\bincome\b"
    r"|جواز|الهوية|هوية|حساب\s+بنكي|آيبان|ايبان|راتب|کارڈ\s+نمبر|پاسپورٹ|شناختی|تنخواہ|पासपोर्ट|आईडी|सैलरी|वेतन",
    re.IGNORECASE,
)
_ASKS_FOR = re.compile(
    r"[?؟]|\b(?:send|share|provide|give|upload|forward|attach|submit|tell|need|require|requires|required|enter|type|confirm|what\s+is|what'?s|may\s+i\s+have|can\s+i\s+have|could\s+you)\b"
    r"|أرسل|ارسل|ابعث|زودنا|بھیج|بتائیں|भेज|बताइए",
    re.IGNORECASE,
)
_IN_PERSON = re.compile(r"\bin\s+person\b|\bcollects?\b|\bdo\s*n'?t\s+share\b|\bplease\s+don'?t\b|\bnever\s+share\b|\bat\s+the\s+viewing\b|\bofficial\s+process\b", re.IGNORECASE)


def asks_private(sentence: str) -> bool:
    """The sentence asks for documents, an ID, bank or card details, an OTP, a password or a salary (spec §2.9.8)."""
    text = " ".join(str(sentence or "").replace("’", "'").split())
    return bool(_PRIVATE.search(text)) and bool(_ASKS_FOR.search(text)) and not _IN_PERSON.search(text)


# Screening (guard 9): never nationality, religion or marital status, nor "family only" or "bachelor" (brief rule 7).
_SCREENING = re.compile(
    r"\bnationalit\w*|\bwhere\s+are\s+you\s+from\b|\bwhich\s+country\b|\breligio\w*|\bmuslim\b|\bhindu\b|\bchristian\b"
    r"|\bmarried\b|\bmarital\b|\bsingle\s+or\b|\bbachelors?\b|\bfamily\s+only\b|\bfamilies\s+only\b|\bonly\s+(?:for\s+)?famil"
    r"|\bshaadi\b|\bjinsiyat\b|جنسية|جنسيتك|متزوج|عزاب|عزوبي|عائلات\s+فقط|قومیت|شادی\s+شدہ|बैचलर|शादीशुदा|राष्ट्रीयता",
    re.IGNORECASE,
)


def screens(sentence: str) -> bool:
    return bool(_SCREENING.search(" ".join(str(sentence or "").split())))


def _drop(reply: str, test) -> tuple[str, bool]:
    sentences = _split(reply)
    kept = [sentence for sentence in sentences if not test(sentence)]
    if len(kept) == len(sentences):
        return str(reply or "").strip(), False
    return " ".join(kept), True


def other_unit_figures(track: str, unit: str, facts=None) -> set[int]:
    """The figures a reply on this unit never carries (guard 2): the other unit's bands and commission, less any figure
    this unit's own facts hold too (a deposit of AED 3,000 is no one-bedroom's commission)."""
    if unit not in (STUDIO, ONE_BR) or track not in (RENT, SALE):
        return set()
    other = ONE_BR if unit == STUDIO else STUDIO
    if track == RENT:
        theirs = rent_figures(other, facts) | _figures(commission(other, facts))
        ours = rent_figures(unit, facts) | _figures(commission(unit, facts)) | charge_figures(facts)
    else:
        theirs = sale_figures(other, facts)
        ours = sale_figures(unit, facts)
    return theirs - ours


def wrong_deal(sentence: str, track: str, facts=None) -> bool:
    """Guard 3: a rent reply carries no figure of 300,000 or more; a sale reply no rent band."""
    values = {value for value, _ in filters.numbers_in(sentence)}
    if track == RENT:
        return any(value >= 300_000 for value in values)
    if track == SALE:
        rents = rent_figures(STUDIO, facts) | rent_figures(ONE_BR, facts)
        return bool(values & rents)
    return False


def _cuts_unit(sentence: str, banned: set[int]) -> bool:
    return bool(banned) and bool({value for value, _ in filters.numbers_in(sentence)} & banned)


def _theirs(name: str, texts) -> bool:
    """Every word of the name is in their own words (a full name of theirs, never CUSTOMER NAME from our records)."""
    said = " ".join(str(text or "") for text in texts or ()).casefold()
    words = [word.casefold() for word in name_words(name)]
    return bool(words) and all(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", said) for word in words)


def our_figures(facts=None) -> set[int]:
    """Every figure of ours: the bands, the charges and the commissions (a budget the customer never gave is none of
    theirs)."""
    clean = _clean(facts)
    out: set[int] = set()
    for deal in BANDS:
        for band in clean[deal].values():
            out |= _figures(band)
    out |= charge_figures(clean) | _figures(clean["charges"]["commission"][STUDIO]) | _figures(clean["charges"]["commission"][ONE_BR])
    return out


def settle_facts(answer: dict, earlier, new_texts, *, facts=None) -> list[str]:
    """A residential answer's facts with only what is theirs (before any guard reads them): a full name in their own
    words, cleaned (never the CRM name the context shows); an e-mail only when it reads as one; a budget that is no figure
    of ours they never wrote; every Emirates ID, IBAN and card number masked. Returns the keys it dropped or changed."""
    out = []
    data = answer.get("facts") if isinstance(answer.get("facts"), dict) else None
    if data is None:
        return out
    theirs = [text for author, text in earlier or () if author == "customer"] + list(new_texts or ())
    name = clean_full_name(data.get("full_name"))
    if data.get("full_name") and (not name or not _theirs(name, theirs)):
        data["full_name"] = None
        out.append("full_name")
    elif name:
        data["full_name"] = name
    if data.get("email") and not clean_email(data.get("email")):
        data["email"] = None
        out.append("email")
    budget = data.get("budget_aed")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        said = {value for value, _ in filters.numbers_in(" ".join(str(text or "") for text in theirs))}
        if int(round(budget)) in our_figures(facts) and int(round(budget)) not in said:
            data["budget_aed"] = None
            data["budget_basis"] = None
            out.append("budget")
    out += [f"masked:{key}" for key in mask_facts(data)]
    return out


# What decides the whole reply (spec §2.10) --------------------------------------------------------------------------

_PAY_NOW = re.compile(
    r"\bpay\s+(?:online|now|the\s+deposit|deposit|by\s+card|by\s+transfer)\b|\b(?:send|transfer)\s+(?:the\s+)?(?:deposit|money|payment|advance)\b"
    r"|\bbank\s+(?:details|account)\b|\baccount\s+(?:number|details)\b|\b(?:i\s+)?want\s+to\s+take\s+it\b"
    r"|\bonline\s+payment\b|\bpayment\s+link\b|\bdeposit\s+now\b"
    r"|ادفع|الدفع\s+(?:أونلاين|اونلاين)|حوالة|تحويل\s+(?:العربون|المبلغ)|پیسے\s+بھیج|ایڈوانس|पेमेंट\s+(?:ऑनलाइन|लिंक)|एडवांस",
    re.IGNORECASE,
)


def wants_to_pay(texts) -> bool:
    """They want to pay online, send the deposit now or take the unit (brief Part 10): res_pay_online and a handover."""
    return any(_PAY_NOW.search(" ".join(str(text or "").replace("’", "'").split())) for text in texts or ())


_NUMBER_ASK = re.compile(
    r"\b(?:your|ur|agent'?s?|office|contact|phone|mobile|cell|whatsapp|direct|personal|landline|owner'?s?)\s+(?:phone\s+)?(?:number|no\.?|num)\b"
    r"|\b(?:number|no\.?)\s+(?:please|pls|plz|of\s+(?:the\s+)?(?:agent|office|owner|landlord))\b|\b(?:give|send|share)\s+(?:me\s+)?(?:the\s+|your\s+)?(?:number|contact)\b"
    r"|\bcan\s+i\s+call\s+(?:you|someone|the\s+agent|your\s+office)\b|\bwhich\s+number\b"
    r"|\b(?:aap|ap|aapka|apka|apna|apne)\s+(?:ka\s+|ke\s+)?(?:number|no)\b"
    r"|رقم\s+(?:الهاتف|التلفون|الوكيل|المكتب|المالك|جوالك|تلفونك)|رقمك|نمبر\s+(?:دیں|دے|بھیج)|آپ\s+کا\s+نمبر|नंबर\s+(?:दो|दीजिए|भेज)|आपका\s+नंबर",
    re.IGNORECASE,
)


def asks_for_number(texts) -> bool:
    """They ask for a phone number (ours, an agent's, the owner's): none is given (Q38)."""
    return any(_NUMBER_ASK.search(" ".join(str(text or "").replace("’", "'").split())) for text in texts or ())


_RENTED_ELSEWHERE = re.compile(
    r"\b(?:already|alredy)\s+(?:rented|found|took|taken|got|moved)\b|\b(?:found|rented|took|got)\s+(?:a|an|another|one)\s+(?:place|flat|studio|apartment|room)\b"
    r"|\bnot\s+(?:looking|searching)\s+(?:anymore|any\s+more)\b|\bno\s+longer\s+(?:looking|need)\b|\bdeal\s+(?:is\s+)?done\b"
    r"|وجدت\s+(?:شقة|سكن|مكان)|استأجرت|مل\s+گیا|مل\s+gaya|mil\s+gaya|le\s+liya|मिल\s+गया|ले\s+लिया",
    re.IGNORECASE,
)


_STILL_WANTS = re.compile(
    r"\b(?:need|needs|want|wants|looking\s+for|searching\s+for|require|chahiye|chaiye)\b|أريد|اريد|أبحث|ابحث|چاہیے|चाहिए", re.IGNORECASE
)


def rented_elsewhere(texts) -> bool:
    """They already rented or found a place ("found a flat already", "not looking anymore"): res_already_rented and Lost
    "rented elsewhere" (Q10); never with a wish in the same words ("I already rented a shop, now I need a studio")."""
    for text in texts or ():
        flat = " ".join(str(text or "").replace("’", "'").split())
        match = _RENTED_ELSEWHERE.search(flat)
        if not match:
            continue
        rest = flat[: match.start()] + " " + flat[match.end() :]
        if _STILL_WANTS.search(rest) and not re.search(r"\b(?:not|no\s+longer)\b", match.group(0), re.IGNORECASE):
            continue
        return True
    return False


RENTED_REASON = "rented elsewhere"
# The model's handovers that go with res_handover (brief Part 9); a broker gets the broker line and a call request people's.
RES_HANDOVERS = (
    "customer_asked_human", "complaint_or_upset", "legal_visa_licence_contract", "price_or_details_insisted", "tenancy_issue",
    "renewal_terms", "meet_at_building", "complex_occupancy", "abroad_cannot_visit", "unclear", "media_received",
)


def code_line(spec: dict, answer: dict) -> None:
    """The answer's words become code's residential line ``spec`` (rendered by ``render`` in the language code writes in):
    no invitation unless the line is one, no location unless it carries it, no shop step."""
    answer["res_line"] = dict(spec)
    answer["converted"] = spec.get("kind") or "res_line"
    answer["invited_to_meeting"] = bool(spec.get("invite"))
    answer["share_office_location"] = bool(spec.get("location"))
    answer["send"] = True
    answer.pop("shop_step", None)
    answer.pop("sale", None)  # a sale step's line (sales._code_line) written before it no longer goes


# The full-name gate's own lines (name_turn, hold_for_name): they stand for a booking, so they go even while a person has
# the chat (engine._run_claimed), as the booking would.
NAME_GATE_LINES = ("res_full_name", "res_name_hold")


def name_gate_line(answer: dict) -> bool:
    """The answer's words are the full-name gate's (the name asked, or the time noted for our agent)."""
    return (answer.get("res_line") or {}).get("kind") in NAME_GATE_LINES


def render(spec: dict, language: str, *, now=None, office_address: str = "", maps_url: str = "", facts=None) -> str:
    """What a res_line answer says, in ``language`` (engine._run_claimed and the eval's outgoing)."""
    kind = spec.get("kind") or ""
    lang = _lang(language)
    slots = [dt.datetime.fromisoformat(value) for value in spec.get("slots") or ()]
    if kind == "open":
        return opener_text(
            lang, spec.get("track") or RENT, spec.get("unit") or "", spec.get("clusters") or (),
            for_client_known=bool(spec.get("for_client_known")), sorry=bool(spec.get("sorry")), facts=facts,
            monthly=bool(spec.get("monthly")),
        )
    if kind == "open_lead":
        return tracks.open_lead_text(lang, spec.get("unit") or "", spec.get("clusters") or ())
    if kind == "res_handover":
        apology = str(spec.get("apology") or "")
        text = handover_line(lang, spec.get("track") or RENT)
        return f"{apology} {text}".strip() if apology else text
    if kind == "res_name_hold":
        start = dt.datetime.fromisoformat(spec["start"]) if spec.get("start") else None
        return name_hold_text(lang, start, now)
    if kind == "res_no_number":
        return no_number_text(lang, office_address, maps_url)
    if kind == "res_invite_neutral":
        return neutral_text(lang, slots, now)
    if kind == "res_invite":
        return invite_text(lang, slots, now, office_address)
    if kind == "res_switch_shop":
        return switch_shop_text(lang, ask_for_whom=bool(spec.get("ask_for_whom", True)))
    if kind == "res_commission_figure":
        return commission_figure_line(lang, spec.get("unit") or "", facts)
    if kind == "res_vat":
        return vat_line(lang, facts)
    return line(kind, lang)


def _reply_with(answer: dict, add: list[str]) -> None:
    """Code's sentences go before the model's first question, so its question stays last (people.with_kept's order)."""
    if not add:
        return
    parts = _split(answer.get("reply") or "")
    for index, sentence in enumerate(parts):
        if rules.asks_question(sentence):
            answer["reply"] = " ".join([*parts[:index], *add, *parts[index:]])
            break
    else:
        answer["reply"] = " ".join([*parts, *add])
    answer["send"] = True


def settle(
    answer: dict,
    earlier,
    new_texts,
    *,
    track: str,
    unit: str = "",
    clusters=(),
    facts: dict | None = None,
    residential_facts=None,
    shops_facts=None,
    booked: bool = False,
    sending: bool = False,
    when=None,
    still_invalid: bool = False,
) -> list[str]:
    """The code guards on a rent, sale or not-known answer (spec §2.9), after engine.settle and before people.settle,
    live and in the eval with the same values. Returns what it changed (also in ``answer["trimmed"]``).

    - Their facts only (settle_facts): a full name of theirs, an e-mail, a budget, the masked numbers.
    - The whole reply goes to a code line for: a handover (res_handover, our rental or sales team, never a name or a
      number; a complaint keeps its apology), a phone number asked for (Q38), a payment now (res_pay_online and a
      legal_visa_licence_contract handover), a place rented elsewhere (res_already_rented, not interested, Lost
      "rented elsewhere").
    - Otherwise the model's sentences lose: a figure of the other unit's band (guard 2), a figure of the wrong deal
      (guard 3), any commission or VAT words (guard 4: code's line for the current track goes instead when they asked),
      shop words (guard 5), an availability claim (guard 6), a "booked" or "sent" claim unless code ``booked`` or a step
      is ``sending`` (guard 7), a document, ID, bank or salary ask (guard 8), screening (guard 9). Two questions at most
      and the amounts by track are clean_reply's (max_questions, amount_floor), at the send.
    ``when`` / ``still_invalid``: a booking, or a time to refuse, goes instead of any of these lines (code writes it)."""
    done: list[str] = []
    texts = [str(text or "") for text in new_texts or ()]
    dropped = settle_facts(answer, earlier, texts, facts=residential_facts)
    if dropped:
        answer["facts_dropped"] = [*(answer.get("facts_dropped") or []), *dropped]
    if answer["opt_out"] != "none" or answer.get("broker") or answer.get("converted"):
        return done
    if when is not None or still_invalid or answer.get("slot_taken"):
        return done  # code's booking, its refusal or the two free slots go: the model's words do not
    handover = answer["handover"]
    team_track = SALE if track == SALE else RENT
    if wants_to_pay(texts):
        answer["handover"] = {"needed": True, "reason": "legal_visa_licence_contract"}
        code_line({"kind": "res_pay_online"}, answer)
        done.append("pay_online")
    elif handover["needed"] and handover["reason"] in RES_HANDOVERS and not people.asks_for_call(" ".join(texts)):
        apology = ""
        if handover["reason"] == "complaint_or_upset":
            apology = " ".join(sentence for sentence in _split(answer["reply"]) if people.is_apology(sentence) and not rules.asks_question(sentence))
        code_line({"kind": "res_handover", "track": team_track, "apology": apology[:200]}, answer)
        done.append("handover")
    elif asks_for_number(texts) and not handover["needed"]:
        code_line({"kind": "res_no_number"}, answer)  # the line carries the address and the Maps link itself (Q38)
        done.append("no_number")
    elif track in (RENT, UNKNOWN) and (answer["facts"].get("already_rented") is True or rented_elsewhere(texts)):
        answer["opt_out"] = rules.NOT_INTERESTED
        answer["lost_reason"] = RENTED_REASON
        answer["opt_out_line"] = "res_already_rented"
        answer["lost_ok"] = track == RENT  # Lost "rented elsewhere" (Q10), never 2d's NEVER_LOST on the rent track
        answer["facts"]["already_rented"] = True
        answer["send"] = True
        done.append("already_rented")
    if done:
        answer["trimmed"] = [*(answer.get("trimmed") or []), *done]
        return done

    reply = answer["reply"] if answer["send"] else ""
    cut: list[str] = []
    if reply:
        banned = other_unit_figures(track, unit, residential_facts)
        reply, changed = _drop(reply, lambda s: _cuts_unit(s, banned))
        if changed:
            cut.append("other_unit")
        reply, changed = _drop(reply, lambda s: wrong_deal(s, track, residential_facts))
        if changed:
            cut.append("wrong_deal")
        reply, changed = _drop(reply, lambda s: bool(_COMMISSION.search(s)))
        if changed:
            cut.append("commission_words")
        reply, changed = _drop(reply, lambda s: bool(_VAT.search(s)))
        if changed:
            cut.append("vat_words")
        reply, changed = drop_shop_words(reply, track)
        if changed:
            cut.append("shop_words")
        reply, changed = _drop(reply, claims_availability)
        if changed:
            cut.append("availability")
        if not (booked or sending):
            reply, changed = _drop(reply, claims_done)
            if changed:
                cut.append("claim")
        reply, changed = _drop(reply, asks_private)
        if changed:
            cut.append("private_ask")
        reply, changed = _drop(reply, screens)
        if changed:
            cut.append("screening")
    add: list[str] = []
    language = answer.get("language") or "en"
    money_line = commission_answer(track, unit, earlier, texts, language=language, facts=residential_facts, shops_facts=shops_facts)
    if money_line:
        add.append(money_line)
        cut.append("commission")
    if asks_vat(texts) and track in (RENT, UNKNOWN):
        add.append(vat_line(language, residential_facts))
        cut.append("vat")
    elif asks_vat(texts) and track == SALE and not money_line:
        add.append(line("res_commission_sale", language))
        cut.append("vat")
    if cut:
        answer["reply"] = reply
        _reply_with(answer, add)
        if not answer["reply"]:
            answer["send"] = False
        answer["trimmed"] = [*(answer.get("trimmed") or []), *dict.fromkeys(cut)]
    return cut


def record_need(answer: dict, known: dict | None, decision, texts=()) -> bool:
    """A rent or sale chat keeps 2d's facts.need and facts.wanted (spec §1.4.10: followups.holds, the nudges, licence_first
    and panel_note read them), written when the chat's want is new or its unit changed; and its property type, intent and
    clusters when the model left them out. True when the want changed (engine._apply alerts the team)."""
    if decision is None or decision.track not in (RENT, SALE):
        return False
    known = known or {}
    data = answer["facts"]
    noun = {STUDIO: "studio", ONE_BR: "bedroom:1"}.get(decision.unit, "")
    kind = needs.HOME if decision.track == RENT else needs.BUY
    had = needs.of(known)
    said = needs.detect(list(texts or ()))
    if not noun and said is not None and said.noun and said.kind in (needs.HOME, needs.BUY):
        noun = said.noun
    if not noun:
        noun = "apartment" if had is None else had.noun
    need = needs.Need(kind, noun)
    changed = False
    same = had is not None and had.kind == kind and tracks._noun_unit(had.noun) == decision.unit and (decision.unit or had.noun)
    if not same:
        merged = {**known, **{key: value for key, value in data.items() if value not in (None, "", [])}}
        data[needs.NEED] = need.kind
        data[needs.WANTED] = needs.summary(need, merged)
        answer["need_words"] = " ".join(str(text or "") for text in texts or ())[:200]
        changed = True
    if decision.unit in (STUDIO, ONE_BR) and not needs.is_home_type(data.get("property_type") or known.get("property_type")):
        data["property_type"] = needs.property_words(noun)
    if not data.get("intent") and not known.get("intent"):
        data["intent"] = "rent" if decision.track == RENT else "buy"
    if decision.clusters and not data.get("clusters") and not known.get("clusters"):
        data["clusters"] = list(decision.clusters)
    if "business_activity" in data:
        data["business_activity"] = None  # a studio is no business (2d's chats 44, 49, 57, 68)
    return changed


# The agents' summary (brief Part 14; spec §2.11) ---------------------------------------------------------------------

_UNIT_WORDS = {STUDIO: "Studio", ONE_BR: "1BR"}
_LABELS = {
    "balcony": {"yes": "Yes", "no": "No", "either": "Either"},
    "occupancy": {"myself": "Myself", "family": "Family", "company_staff": "Company staff", "sharing": "Sharing"},
    "contract": {"individual": "Individual", "company": "Company"},
    "occupancy_status": {"vacant": "Vacant", "tenanted": "Rented", "either": "Either"},
    "payment": {"cash": "Cash", "mortgage": "Mortgage", "cheques": "Cheques"},
    "purpose": {"investment": "Investment", "personal": "Own use"},
}


def summary_lines(facts: dict | None, lead: dict | None = None, appointment=None, *, track: str = RENT, unit: str = "") -> list[str]:
    """The brief's handover summary (Part 14) for the agents' alerts: name, source and listing ref, type, cluster,
    balcony, budget, occupancy, contract, move-in, the viewing, customer type and their pending questions; only what is
    known."""
    facts = facts or {}
    lead = lead or {}
    lines = []
    name = clean_full_name(facts.get("full_name")) or full_name_known(facts, lead)
    if name:
        lines.append(f"Full name: {name}")
    source = " ".join(part for part in (lead.get("source"), lead.get("listing_ref")) if part)
    if source:
        lines.append(f"Source: {source}")
    if lead.get("listing_url"):
        lines.append(f"Listing: {lead['listing_url']}")
    shown = _UNIT_WORDS.get(unit or "", "")
    if shown:
        lines.append(f"Type: {shown} ({'to buy' if track == SALE else 'to rent'})")
    clusters = facts.get("clusters") or ([lead["cluster"]] if lead.get("cluster") else [])
    if isinstance(clusters, list) and clusters:
        lines.append(f"Cluster: {', '.join(str(name) for name in clusters)}")
    elif facts.get("cluster_flexible") is True:
        lines.append("Cluster: any")
    for key, label in (("balcony", "Balcony"), ("occupancy_status", "Rented or vacant"), ("payment", "Payment"), ("purpose", "Purpose")):
        value = facts.get(key)
        if value:
            lines.append(f"{label}: {_LABELS[key].get(value, value)}")
    budget = facts.get("budget_aed")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        basis = {"per_month": " a month", "per_year": " a year"}.get(facts.get("budget_basis") or "", "")
        lines.append(f"Budget: AED {int(budget):,}{basis}")
    occupancy = facts.get("occupancy")
    if occupancy:
        people_count = facts.get("occupants")
        extra = f" ({int(people_count)} people)" if isinstance(people_count, (int, float)) and not isinstance(people_count, bool) and people_count > 0 else ""
        lines.append(f"Occupancy: {_LABELS['occupancy'].get(occupancy, occupancy)}{extra}")
    if facts.get("contract"):
        lines.append(f"Contract: {_LABELS['contract'].get(facts['contract'], facts['contract'])}")
    for key, label in (("move_in", "Move-in"), ("buy_timeline", "Buying timeline")):
        if facts.get(key):
            lines.append(f"{label}: {facts[key]}")
    if appointment is not None and getattr(appointment, "starts_at", None):
        held = (getattr(appointment, "details", None) or {}).get(HELD_FOR_NAME)
        lines.append(f"{'Held (no full name yet)' if held else 'Viewing'}: {hours.describe(appointment.starts_at)}")
    if facts.get("for_client") is True:
        lines.append("Customer type: Broker")
    elif facts.get("for_client") is False:
        lines.append("Customer type: Direct")
    notes = facts.get("notes")
    if isinstance(notes, list) and notes:
        lines.append("Questions: " + "; ".join(str(note) for note in notes))
    return lines


def title_prefix(track: str, unit: str = "") -> str:
    """An alert title's head on a residential track ("Rent · Studio: "), '' elsewhere (spec §2.11)."""
    return f"{tracks.label(track, unit)}: " if track in (RENT, SALE) else ""


def copy_facts(facts) -> dict:
    return copy.deepcopy(facts or {})


# The engine's hooks (engine._run_claimed, and the eval with the same values) ------------------------------------------

RULE = "res_rule"
# people.settle's ``need`` on the residential path: set, so a charge question is answered, never a must-answer handover.
RES_NEED = needs.Need(needs.HOME, "")
AMOUNT_FLOOR = 100


def max_questions(track: str) -> int:
    """Questions a reply may ask (spec §1.3): two on the rent and sale tracks, one while the track is not known."""
    return 2 if track in (RENT, SALE) else 1


def segment_of(track: str) -> str:
    """The segment a residential answer is forced into (spec §1.4.4), so _shape never turns a booking into a holding
    handover: residential_tenant on the rent track, buyer on the sale track, '' (the model's) while not known."""
    return {RENT: "residential_tenant", SALE: "buyer"}.get(track, "")


def opener_spec(decision, facts: dict | None, *, sorry: bool = False, monthly: bool = False) -> dict:
    """The res_line of a track's opener (opener_text), from the chat's track and what it knows."""
    spec = {
        "kind": "open",
        "track": decision.track,
        "unit": decision.unit if decision.unit in (STUDIO, ONE_BR) else "",
        "clusters": list(decision.clusters),
        "for_client_known": (facts or {}).get("for_client") is not None,
        "sorry": bool(sorry),
    }
    if monthly and decision.track == RENT and spec["unit"]:
        spec["monthly"] = True
    return spec


def pre_model_rule(
    decision, facts: dict | None, *, words=(), typed=(), unheard: bool = False, entered: bool = False, plain: bool = False,
    ours: int = 0, slots=(), handed_over: bool = False, talked_shops: bool = False,
) -> dict | None:
    """The rent flow's words before any model (spec §1.4.3, §2.10), else None:

    - every message a voice note nobody could hear: res_voice_failed;
    - an Emirates ID, IBAN or card number typed: res_no_documents (PDPL, spec §6.3);
    - a rent or sale track entered this turn (``entered``) with a plain burst (engine.residential_plain): the opener,
      skipping what is known, with an apology when we misread them, they never asked about a shop, or we talked shops to
      them already (``talked_shops``);
    - the not-known track, our second message answered with nothing clearer and nothing asked: res_invite_neutral and
      two free slots (``slots``: a list, or a callable giving one).
    Nothing while a person has the chat (``handed_over``)."""
    if handed_over or decision is None:
        return None
    if unheard:
        return {"kind": "res_voice_failed"}
    if any(has_private_number(text) for text in typed or ()):
        return {"kind": "res_no_documents"}
    if decision.track in (RENT, SALE) and entered and plain:
        sorry = decision.sorry or talked_shops or needs.misread(list(words or ()))
        return opener_spec(decision, facts, sorry=sorry, monthly=asks_monthly(words))
    if decision.track == UNKNOWN and plain and ours >= 2:
        pair = slots() if callable(slots) else list(slots or ())
        return {"kind": "res_invite_neutral", "slots": [start.isoformat() for start in pair], "invite": True, "location": True}
    return None


_ASKS_PERSON = re.compile(
    r"\b(?:talk|speak|chat)\s+(?:to|with)\s+(?:a\s+|an\s+|the\s+|your\s+|some\s*)?(?:person|human|agent|someone|somebody|manager|"
    r"real\s+person|representative|staff|owner)\b|\breal\s+person\b|\bhuman\b|\bnot\s+a\s+bot\b"
    r"|\binsaan\s+se\b|\bbanda\b|انسان|شخص\s+حقيقي|موظف|کسی\s+انسان|किसी\s+इंसान",
    re.IGNORECASE,
)
_COMPLAINS = re.compile(
    r"\b(?:complain\w*|worst|fraud|cheat\w*|scam\w*|disappoint\w*|rude|useless|wasting\s+my\s+time|not\s+happy|unhappy|angry|upset|"
    r"nobody\s+(?:called|replied|answered)|no\s+one\s+(?:called|replied|answered)|stop\s+wasting)\b|شكوى|محتال|نصاب|دھوکہ|शिकायत|धोखा",
    re.IGNORECASE,
)


def needs_model(texts) -> bool:
    """Words the opener must not answer for the model (spec §1.4.3: none of who_they_are's plain exclusions): a request
    for a person, a complaint, or a broker's words (brokers.declares)."""
    from . import brokers

    flat = [" ".join(str(text or "").replace("’", "'").split()) for text in texts or () if str(text or "").strip()]
    if any(_ASKS_PERSON.search(text) or _COMPLAINS.search(text) for text in flat):
        return True
    try:
        return bool(flat) and brokers.declares(flat)
    except Exception:  # noqa: BLE001 - a reading aid, never a reason to fail a turn: the model then answers
        return True


_BALCONY_YES = re.compile(r"\bwith\s+(?:a\s+)?balcon(?:y|ies)\b|\bbalcon(?:y|ies)\s+(?:needed|required|please|must)\b|مع\s+(?:شرفة|بلكونة)|بالکونی\s+والا|बालकनी\s+वाला", re.IGNORECASE)
_BALCONY_NO = re.compile(r"\b(?:without|no)\s+(?:a\s+)?balcon(?:y|ies)\b|بدون\s+(?:شرفة|بلكونة)|بغیر\s+بالکونی|बिना\s+बालकनी", re.IGNORECASE)


def balcony_of(texts) -> str:
    """A balcony said in their own words ("Studio apartment with balcony": yes; "no balcony needed": no), else ''."""
    joined = " ".join(str(text or "") for text in texts or ())
    if _BALCONY_NO.search(joined):
        return "no"
    return "yes" if _BALCONY_YES.search(joined) else ""


def rule_answer(spec: dict, language: str, decision=None, *, facts: dict | None = None, words=()) -> dict:
    """A pre_model_rule spec shaped like the model's answer (as engine.shops_answer shapes a shops rule's). An opener also
    records what code read in their words: 2d's want on the rent and sale tracks (record_need) and a balcony."""
    from . import schema

    segment = segment_of(decision.track if decision is not None else UNKNOWN) or "other"
    answer = schema.normalize({"language": language, "segment": segment, "send": True, "reply": "-"}, residential=True)
    answer["rule"] = f"{RULE}:{spec.get('kind')}"
    code_line(spec, answer)
    if spec.get("kind") == "open" and decision is not None:
        record_need(answer, facts, decision, words)
        balcony = balcony_of(words)
        if balcony and not (facts or {}).get("balcony"):
            answer["facts"]["balcony"] = balcony
    return answer


def held_start(appointment):
    """The start of a tentative held for the full name (spec §2.6), else None."""
    if appointment is None or getattr(appointment, "status", "") != "tentative":
        return None
    if not (getattr(appointment, "details", None) or {}).get(HELD_FOR_NAME):
        return None
    return appointment.starts_at


def held_of(appointment) -> dict | None:
    """What a full-name hold keeps: its start, their words for it, how often we asked, and its place (a buyer's call is held
    at place "call", slice C: booked there once the name comes); None when there is none."""
    start = held_start(appointment)
    if start is None:
        return None
    details = appointment.details or {}
    place = CALL if getattr(appointment, "place", "") == CALL else OFFICE
    return {"start": start, "words": appointment.customer_words or "", "asks": int(details.get("name_asks") or 0), "place": place}


HELD_KEYS = (HELD_FOR_NAME, "held_at", "asked_at", "name_asks", "name_refused")


def held_details(details) -> dict:
    """A tentative's full-name marks, kept when its facts are written again."""
    return {key: value for key, value in (details or {}).items() if key in HELD_KEYS}


def held_lapsed(appointment, now) -> bool:
    """A time held for the full name that nobody answered (spec §2.6): NAME_HOLD_LAPSES after our last ask, through 2d's
    tentative-lapse sweep (tasks._lapse_shops_tentatives). One they refused the name for stays for our agent to confirm,
    until its time passes."""
    details = getattr(appointment, "details", None) or {}
    if not details.get(HELD_FOR_NAME) or details.get("name_refused"):
        return False
    try:
        asked = dt.datetime.fromisoformat(str(details.get("asked_at") or details.get("held_at") or ""))
    except ValueError:
        return False
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=dt.timezone.utc)
    return asked < now - NAME_HOLD_LAPSES


def mark_hold(appointment, answer: dict, now, *, sent: bool = True) -> bool:
    """engine._apply on a tentative: the marks of a full-name hold (``answer["hold_for_name"]``: held now, and how often we
    asked) and of their no (``answer["name_refused"]``). True when the details changed (the caller saves them)."""
    hold, refused = answer.get("hold_for_name"), answer.get("name_refused")
    if not (hold or refused) or not sent:
        return False
    details = dict(appointment.details or {})
    if hold:
        details[HELD_FOR_NAME] = True
        details.setdefault("held_at", now.isoformat())
        details["asked_at"] = now.isoformat()
        details["name_asks"] = int(details.get("name_asks") or 0) + 1
    if refused:
        details[HELD_FOR_NAME] = True
        details["name_refused"] = True
    if details == (appointment.details or {}):
        return False
    appointment.details = details
    return True


def hold_for_name(answer: dict, when) -> None:
    """A rent or sale booking with no full name (full_name_gate): the time becomes a tentative held at it (no other chat
    takes it: engine.taken_slots for a visit, calls.taken for a buyer's call, held at place "call"), and code asks for the
    name (res_full_name)."""
    local = when.astimezone(hours.DUBAI)
    place = CALL if answer["appointment"].get("place") == CALL else OFFICE
    answer["appointment"] = {
        "action": "tentative", "place": place, "date": f"{local:%Y-%m-%d}", "time": f"{local:%H:%M}",
        "customer_words": answer["appointment"].get("customer_words"),
    }
    answer["hold_for_name"] = True
    code_line({"kind": "res_full_name"}, answer)


_NO_TIME = {"action": "none", "place": None, "date": None, "time": None, "customer_words": None}


@dataclass
class NameStep:
    kind: str = ""  # "", "fallback" (code read the name), "book_held", "held_gone", "refused", "ask_again"
    full_name: str = ""
    when: dt.datetime | None = None


def name_turn(
    answer: dict, facts: dict | None, lead: dict | None, *, held: dict | None, asked: bool, texts=(), said: str = "",
    when=None, still_invalid: bool = False, rule: bool = False, now=None, closed_dates=(), taken=(),
) -> NameStep:
    """The full name on a rent or sale turn (spec §2.6), live and in the eval:

    - known from their words, the model's facts or the lead (full_name_known); else, right after our ask (``asked``),
      code's reading of a bare name (name_from_reply), written to the answer's facts;
    - a time ``held`` for it, the name now known, and no other time of theirs: that time is booked (``when``) at its place
      (a buyer's call at place "call"), checked again for the hours (a time gone by gets two free slots instead: res_invite,
      or for a call the sale track's two free call slots from ``taken``, the call pool);
    - held, asked, and no name: their no ("why do you need it?"), or a second answer with none, gets res_name_hold (the
      hold stays, the team is alerted); anything else that asks nothing gets the ask once more."""
    data = answer["facts"]
    merged = {**(facts or {}), **{key: value for key, value in data.items() if value not in (None, "", [])}}
    full = full_name_known(merged, lead)
    kind = ""
    if not full and asked and not rule:
        guess = name_from_reply(said)
        if guess:
            data["full_name"] = guess
            full, kind = guess, "fallback"
    if held is None or rule or answer["opt_out"] != "none" or answer.get("broker"):
        return NameStep(kind, full, None)
    if not full and asked and when is None and refuses_name(texts):
        # Their no to our ask ("why do you need my name?") is no booking (the brief's must) and never lost: the hold stays and
        # the team is alerted, whatever the model made of it.
        answer["handover"] = {"needed": False, "reason": None}
        answer.pop("res_line", None)
        code_line({"kind": "res_name_hold", "start": held["start"].isoformat()}, answer)
        answer["name_refused"] = True
        answer["appointment"] = dict(_NO_TIME)
        return NameStep("refused", "", None)
    if answer["handover"]["needed"] or answer.get("converted"):
        return NameStep(kind, full, None)
    proposal = answer["appointment"]
    if full and when is None and not still_invalid and proposal["action"] not in ("confirm", "reschedule"):
        start = held["start"].astimezone(hours.DUBAI)
        try:
            checked = hours.check_slot(f"{start:%Y-%m-%d}", f"{start:%H:%M}", now=now, closed_dates=closed_dates)
        except hours.SlotError:
            checked = None
        place = held.get("place") or OFFICE
        if checked is not None:
            answer["appointment"] = {
                "action": "confirm", "place": place, "date": f"{start:%Y-%m-%d}", "time": f"{start:%H:%M}",
                "customer_words": held.get("words") or None,
            }
            return NameStep("book_held", full, checked)
        pair = hours.offer_pair(now, closed_dates, taken)
        answer["appointment"] = dict(_NO_TIME)
        if place == CALL:
            # A buyer's call held for the name whose time went by (slice C): two free call slots, as sales.call_step offers.
            from . import sales

            sales.offer_call_slots(answer, pair)
            return NameStep("held_gone", full, None)
        code_line({"kind": "res_invite", "slots": [slot.isoformat() for slot in pair], "invite": bool(pair)}, answer)
        return NameStep("held_gone", full, None)
    if not full and asked and when is None:
        if held.get("asks", 0) >= 2:
            code_line({"kind": "res_name_hold", "start": held["start"].isoformat()}, answer)
            answer["name_refused"] = True
            answer["appointment"] = dict(_NO_TIME)
            return NameStep("refused", "", None)
        if not rules.asks_question(said):
            code_line({"kind": "res_full_name"}, answer)
            answer["hold_for_name"] = "again"
            answer["appointment"] = dict(_NO_TIME)
            return NameStep("ask_again", "", None)
    return NameStep(kind, full, None)
