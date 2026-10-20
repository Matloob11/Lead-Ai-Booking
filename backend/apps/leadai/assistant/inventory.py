"""The inventory: the units the company can offer right now, so the bot quotes a real unit — its price, size, cluster —
and never one it does not have (Matloob, 2026-10-20: "real inventory", the advance plan's workstream C; v1).

Sources (LeadAiUnit rows, refreshed by the sweep's sync):
- Property Finder (``sync_pf``): the agency's live listings through the Enterprise API — a bearer token from the key and
  secret (settings.LEADAI_PF_API_KEY / _SECRET; 30 minutes), then GET /v1/listings?filter[state]=live, 50 a page. On
  2026-10-20 that was 142 listings: villas, townhouses, shops, a few apartments; International City held 5 (4 shops,
  one townhouse). The community and the cluster are read from the listing's title (the API gives a location id only).
- Bitrix Owner Data → Availability (``sync_bitrix``, SPA 1042, category 14): the cards on the Rent Availability, Sale
  Availability and Sale/Rent availability stages, and only the clean ones — a bedrooms value, a unit type, a purpose
  and a price (most cards carry the details in their title or nowhere: those are skipped, counted, never guessed).
  Owner numbers are never read.

In the turn (``matches`` → ``lines``): up to three active units for the chat's community, sub-areas, unit and deal, as an
INVENTORY block of data, their figures allowed through the amount filter (``known_amounts``). No match: nothing is
added and the band answers as before. The bot is told to quote only these and to say our agent confirms availability.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time

import httpx
from django.conf import settings
from django.utils import timezone

from ..models import LeadAiUnit
from . import tracks

logger = logging.getLogger(__name__)

# The kill switch: off, the turn reads no unit and every answer is the band's, as before v1.
LIVE = True
# v1: every Lead AI chat is an International City chat (the shops and the mixed campaigns); the community packs (the
# advance plan's workstream B) replace this constant with the chat's own community.
DEFAULT_COMMUNITY = "International City"
PF_BASE = "https://atlas.propertyfinder.com"
PF_PAGE = 50
PF_TIMEOUT = 30.0
PHOTOS_KEPT = 5
SHOWN = 3
TITLE_MAX = 200
BLOCK_HEAD = "INVENTORY (units we have right now; quote only these and say our agent confirms availability; prices in AED):"

VILLA = "villa"
TOWNHOUSE = "townhouse"
SHOP = "shop"
OTHER = "other"
UNIT_WORDS = {
    tracks.STUDIO: "studio",
    tracks.ONE_BR: "one-bedroom apartment",
    tracks.TWO_PLUS: "apartment",
    VILLA: "villa",
    TOWNHOUSE: "townhouse",
    SHOP: "shop",
    OTHER: "unit",
}
# International City's clusters and the other names a title carries (sub-areas), as customers and listings write them.
_CLUSTER = re.compile(
    r"\b(spain|france|england|china|persia|morocco|emirates|greece|russia|italy|cbd|warsan village|phase 2|phase 3)\b(?:\s+cluster)?",
    re.IGNORECASE,
)
_COMMUNITY_WORDS = (
    ("international city", "International City"), ("warsan", "International City"), ("mudon", "Mudon"), ("damac lagoons", "Damac Lagoons"),
    ("lagoons", "Damac Lagoons"), ("villanova", "Villanova"), ("dubai south", "Dubai South"), ("arabian ranches", "Arabian Ranches"),
    ("town square", "Town Square"), ("jvc", "JVC"), ("jumeirah village circle", "JVC"), ("dubailand", "Dubailand"), ("al furjan", "Al Furjan"),
    ("the valley", "The Valley"), ("haven", "Haven by Aldar"), ("yas", "Yas Island"),
)


# ---- the sources ---------------------------------------------------------------------------------------------------


def pf_configured() -> bool:
    return bool(getattr(settings, "LEADAI_PF_API_KEY", "") and getattr(settings, "LEADAI_PF_API_SECRET", ""))


def pf_token(client: httpx.Client) -> str:
    response = client.post(
        f"{PF_BASE}/v1/auth/token",
        json={"apiKey": settings.LEADAI_PF_API_KEY, "apiSecret": settings.LEADAI_PF_API_SECRET},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    token = str(response.json().get("accessToken") or "")
    if not token:
        raise RuntimeError("Property Finder gave no access token")
    return token


def pf_listings(client: httpx.Client, token: str):
    """Every live listing, page by page (a generator of the API's own dicts)."""
    page = 1
    while True:
        response = client.get(
            f"{PF_BASE}/v1/listings",
            params={"page[size]": PF_PAGE, "page[number]": page, "filter[state]": "live"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        response.raise_for_status()
        body = response.json()
        for item in body.get("results") or []:
            yield item
        pagination = body.get("pagination") or {}
        page = pagination.get("nextPage")
        if not page:
            return


def unit_of(kind: str, bedrooms: str) -> str:
    """The bot's unit word for a listing's type and bedrooms."""
    kind = str(kind or "").lower()
    beds = str(bedrooms or "").lower().strip()
    if kind in ("shop", "retail"):
        return SHOP
    if kind == "villa":
        return VILLA
    if kind == "townhouse":
        return TOWNHOUSE
    if kind in ("apartment", "penthouse", "duplex", "hotel-apartment"):
        if beds in ("studio", "0"):
            return tracks.STUDIO
        if beds == "1":
            return tracks.ONE_BR
        if beds.isdigit() and int(beds) >= 2:
            return tracks.TWO_PLUS
        return OTHER
    return OTHER


def place_of(title: str) -> tuple[str, str]:
    """(community, sub-area) read from a listing's title: "Front-Facing Shop | China Cluster | International City"."""
    text = " ".join(str(title or "").split())
    low = text.lower()
    community = ""
    for word, name in _COMMUNITY_WORDS:
        if word in low:
            community = name
            break
    sub = ""
    match = _CLUSTER.search(text)
    if match:
        word = match.group(1)
        sub = "CBD" if word.lower() == "cbd" else (word.title() + (" Cluster" if word.lower() not in ("warsan village", "phase 2", "phase 3") else ""))
        if sub.lower().startswith("phase"):
            sub = "International City " + sub
        if not community:
            community = "International City"
    return community, sub


def pf_row(item: dict) -> dict | None:
    """A LeadAiUnit's fields from one Property Finder listing, or None when it carries no price."""
    price = item.get("price") or {}
    amounts = price.get("amounts") or {}
    kind = str(price.get("type") or "")
    if kind == "sale":
        deal, amount = LeadAiUnit.Deal.SALE, amounts.get("sale")
    elif kind in ("yearly", "monthly", "weekly", "daily"):
        deal = LeadAiUnit.Deal.RENT
        amount = amounts.get("yearly")
        if amount is None and amounts.get("monthly") is not None:
            amount = int(amounts["monthly"]) * 12
    else:
        return None
    if amount is None:
        return None
    title = str((item.get("title") or {}).get("en") or "")
    community, sub_area = place_of(title)
    images = ((item.get("media") or {}).get("images") or [])[:PHOTOS_KEPT]
    photos = [str((image.get("original") or {}).get("url") or "") for image in images if isinstance(image, dict)]
    updated = item.get("updatedAt")
    try:
        source_updated = dt.datetime.fromisoformat(str(updated).replace("Z", "+00:00")) if updated else None
    except ValueError:
        source_updated = None
    size = item.get("size")
    return {
        "reference": str(item.get("reference") or "")[:40],
        "community": community[:80],
        "sub_area": sub_area[:80],
        "unit": unit_of(item.get("type"), item.get("bedrooms")),
        "bedrooms": str(item.get("bedrooms") or "")[:12],
        "deal": deal,
        "price": int(amount),
        "size_sqft": int(size) if isinstance(size, (int, float)) and size > 0 else None,
        "furnished": str(item.get("furnishingType") or "")[:20],
        "title": title[:TITLE_MAX],
        "link": "",
        "photos": [url for url in photos if url],
        "agent_name": str((item.get("assignedTo") or {}).get("name") or "")[:80],
        "source_updated_at": source_updated,
    }


def sync_pf() -> dict:
    """The live Property Finder listings into LeadAiUnit (upserted; the rest of the source made inactive). Counts."""
    if not pf_configured():
        return {"skipped": "no Property Finder key"}
    seen: set[str] = set()
    upserted = 0
    with httpx.Client(timeout=PF_TIMEOUT) as client:
        token = pf_token(client)
        for item in pf_listings(client, token):
            source_id = str(item.get("id") or "")
            row = pf_row(item) if source_id else None
            if row is None:
                continue
            LeadAiUnit.objects.update_or_create(source=LeadAiUnit.Source.PF, source_id=source_id, defaults={**row, "active": True})
            seen.add(source_id)
            upserted += 1
    gone = LeadAiUnit.objects.filter(source=LeadAiUnit.Source.PF, active=True).exclude(source_id__in=seen).update(active=False)
    logger.info("Lead AI inventory: Property Finder %s live listings, %s gone", upserted, gone)
    return {"upserted": upserted, "gone": gone}


# Bitrix Owner Data → Availability (SPA 1042, category 14; the Owner Data user fields are UF_CRM_5_*).
BITRIX_ENTITY_TYPE = 1042
BITRIX_CATEGORY = 14
BITRIX_PAGE = 50
BITRIX_TRIES = 6
BITRIX_WAIT = 10
BITRIX_STAGES = {"DT1042_14:UC_73SP7H": "rent", "DT1042_14:PREPARATION": "sale", "DT1042_14:UC_G0PCBL": "both"}
BITRIX_FIELDS = {
    "bedrooms": "ufCrm5_1734246780476",
    "unit_type": "ufCrm5_1734246899822",
    "size": "ufCrm5_1734246988917",
    "sell": "ufCrm5_1734247021855",
    "lease": "ufCrm5_1734247036310",
    "purpose": "ufCrm5_1734247157896",
    "furnished": "ufCrm5_1734261990377",
    "area": "ufCrm5_1768487008300",
    "loc_name": "ufCrm5_1777563155595",
}
BITRIX_BEDROOMS = {430: "studio", 1575: "studio", 1636: "studio", 431: "1", 1573: "1", 1634: "1", 432: "2", 1570: "2", 1635: "2", 433: "3", 1565: "3", 2084: "3", 434: "4", 1564: "4", 435: "5", 1683: "5", 436: "6", 437: "7+", 1566: "7", 1567: "7+"}
BITRIX_TYPES = {438: "apartment", 439: "villa", 440: "building", 441: "plot", 442: "penthouse", 1674: "townhouse", 1563: "townhouse"}
BITRIX_PURPOSE = {445: "sale", 446: "rent", 447: "both", 1688: "sale", 1691: "rent"}
BITRIX_FURNISHED = {451: "furnished", 452: "semi-furnished", 453: "unfurnished", 1671: "unfurnished", 1689: "unfurnished", 1672: "furnished"}


def bitrix_rows(item: dict, stage: str) -> list[dict]:
    """The LeadAiUnit rows of one clean Availability card (one per deal it offers), or none when a field is missing."""
    def enum(name, table):
        value = item.get(BITRIX_FIELDS[name])
        try:
            return table.get(int(value)) if value not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            return None

    bedrooms = enum("bedrooms", BITRIX_BEDROOMS)
    kind = enum("unit_type", BITRIX_TYPES)
    purpose = enum("purpose", BITRIX_PURPOSE) or BITRIX_STAGES.get(stage)
    if not bedrooms or not kind or not purpose:
        return []
    title = str(item.get("title") or "")
    area = str(item.get(BITRIX_FIELDS["area"]) or item.get(BITRIX_FIELDS["loc_name"]) or "")
    community, sub_area = place_of(f"{area} {title}")
    if not community:
        return []
    size = item.get(BITRIX_FIELDS["size"])
    try:
        size_sqft = int(float(size)) if size not in (None, "", 0) and float(size) > 0 else None
    except (TypeError, ValueError):
        size_sqft = None
    furnished = enum("furnished", BITRIX_FURNISHED) or ""
    rows = []
    deals = ("rent", "sale") if purpose == "both" else (purpose,)
    for deal in deals:
        raw = item.get(BITRIX_FIELDS["lease" if deal == "rent" else "sell"])
        try:
            value = float(raw) if raw not in (None, "", 0) else 0.0
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0:
            continue
        if deal == "sale" and value < 1000:
            value *= 1_000_000  # "3.2" typed for 3.2 million
        price = int(round(value))
        rows.append({
            "reference": "",
            "community": community[:80],
            "sub_area": sub_area[:80],
            "unit": unit_of(kind, bedrooms),
            "bedrooms": bedrooms[:12],
            "deal": LeadAiUnit.Deal.RENT if deal == "rent" else LeadAiUnit.Deal.SALE,
            "price": price,
            "size_sqft": size_sqft,
            "furnished": furnished,
            "title": f"{kind} {bedrooms} {area}".strip()[:TITLE_MAX],
            "link": "",
            "photos": [],
            "agent_name": "",
            "source_updated_at": None,
        })
    return rows


def sync_bitrix() -> dict:
    """The clean Availability cards into LeadAiUnit through the Bitrix REST client (crm.item.list). Counts."""
    from apps.crmlink import client as bitrix

    if not bitrix.configured():
        return {"skipped": "no Bitrix webhook"}
    seen: set[str] = set()
    upserted = skipped = 0
    for stage in BITRIX_STAGES:
        start = 0
        while True:
            # client.call gives the result alone (no "next"): Bitrix pages by 50, so a short page is the last one. Background
            # work takes a request slot only when one is free beyond the reserve; a busy minute (a campaign, the mirror)
            # says "no slot" — a half-hourly job can wait and ask again (the first live sync, 2026-10-20, timed out at once).
            payload = {
                "entityTypeId": BITRIX_ENTITY_TYPE,
                "filter": {"categoryId": BITRIX_CATEGORY, "stageId": stage},
                "select": ["id", "title", "stageId", "updatedTime", *BITRIX_FIELDS.values()],
                "start": start,
            }
            result = None
            for attempt in range(BITRIX_TRIES):
                try:
                    with bitrix.background():
                        result = bitrix.call("crm.item.list", payload)
                    break
                except bitrix.BitrixTransient as exc:
                    if attempt + 1 == BITRIX_TRIES:
                        raise
                    logger.info("Lead AI inventory: Bitrix busy (%s); waiting %s s", str(exc)[:80], BITRIX_WAIT)
                    time.sleep(BITRIX_WAIT)
            items = (result or {}).get("items") or [] if isinstance(result, dict) else []
            for item in items:
                rows = bitrix_rows(item, stage)
                if not rows:
                    skipped += 1
                    continue
                for row in rows:
                    source_id = f"{item.get('id')}:{row['deal']}"
                    LeadAiUnit.objects.update_or_create(source=LeadAiUnit.Source.BITRIX, source_id=source_id, defaults={**row, "active": True})
                    seen.add(source_id)
                    upserted += 1
            if len(items) < BITRIX_PAGE:
                break
            start += BITRIX_PAGE
    gone = LeadAiUnit.objects.filter(source=LeadAiUnit.Source.BITRIX, active=True).exclude(source_id__in=seen).update(active=False)
    logger.info("Lead AI inventory: Bitrix Availability %s clean units, %s skipped (no bedrooms, type, purpose, place or price), %s gone", upserted, skipped, gone)
    return {"upserted": upserted, "skipped": skipped, "gone": gone}


def sync() -> dict:
    out = {}
    for name, job in (("pf", sync_pf), ("bitrix", sync_bitrix)):
        try:
            out[name] = job()
        except Exception as exc:  # noqa: BLE001 - one source must not stop the other
            logger.warning("Lead AI inventory sync (%s) failed: %s", name, exc)
            out[name] = {"error": str(exc)[:200]}
    return out


# ---- in the turn -----------------------------------------------------------------------------------------------------


def matches(community: str, sub_areas=(), unit: str = "", deal: str = "", *, budget: int | None = None, limit: int = SHOWN) -> list[LeadAiUnit]:
    """Up to ``limit`` active units for the chat: the community (always), the unit and the deal when known, the
    customer's clusters first, then the cheapest. Nothing without a community."""
    if not community:
        return []
    rows = LeadAiUnit.objects.filter(active=True, community__iexact=community)
    if unit:
        rows = rows.filter(unit=unit)
    if deal in (LeadAiUnit.Deal.RENT, LeadAiUnit.Deal.SALE):
        rows = rows.filter(deal=deal)
    if budget:
        rows = rows.filter(price__lte=int(budget * 1.15))
    wanted = {str(area or "").lower().replace(" cluster", "") for area in sub_areas or () if area}
    rows = list(rows.order_by("price", "pk")[: limit * 4])
    if wanted:
        rows.sort(key=lambda row: (0 if row.sub_area.lower().replace(" cluster", "") in wanted else 1, row.price or 0))
    return rows[:limit]


def line(row: LeadAiUnit) -> str:
    where = ", ".join(part for part in (row.sub_area, row.community) if part)
    price = f"AED {row.price:,}" + (" a year" if row.deal == LeadAiUnit.Deal.RENT else "")
    size = f", {row.size_sqft:,} sq ft" if row.size_sqft else ""
    furnished = f", {row.furnished}" if row.furnished else ""
    ref = row.reference or f"{row.get_source_display()} #{row.source_id}"
    photos = f", {len(row.photos)} photos" if row.photos else ""
    return f"- {ref}: {UNIT_WORDS.get(row.unit, row.unit)} for {row.deal} in {where}{size}{furnished}, {price}{photos}"


def lines(rows) -> list[str]:
    """The INVENTORY block's lines (data), or none."""
    rows = list(rows or ())
    if not rows:
        return []
    return [BLOCK_HEAD, *(line(row) for row in rows)]


def known_amounts(rows) -> str:
    """The units' figures, for the amount filter: a price, a size or a reference (a7group-1901 carries a number) quoted
    from the block is no invention."""
    parts = []
    for row in rows or ():
        if row.price:
            parts += [f"{row.price:,}", str(row.price)]
        if row.size_sqft:
            parts += [f"{row.size_sqft:,}", str(row.size_sqft)]
        if row.reference:
            parts += [row.reference, re.sub(r"\D", "", row.reference)]
    return " ".join(part for part in parts if part)


def deal_of(track: str) -> str:
    return {tracks.RENT: LeadAiUnit.Deal.RENT, tracks.SALE: LeadAiUnit.Deal.SALE}.get(track, "")
