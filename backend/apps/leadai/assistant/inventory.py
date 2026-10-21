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
PF_PAGES_AT_MOST = 40  # 2,000 listings: a nextPage that never ends cannot hold the half-hourly task past its limit
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
    ("town square", "Town Square"), ("jvc", "JVC"), ("jumeirah village circle", "JVC"), ("dubai land residence complex", "Dubai Land Residence Complex"),
    ("dubailand", "Dubailand"), ("dubai land", "Dubailand"), ("al furjan", "Al Furjan"),
    ("the valley", "The Valley"), ("haven", "Haven by Aldar"), ("yas", "Yas Island"),
)
# A Property Finder reference as the agency writes it (a7group-1633): the one key a Bitrix card and a listing share.
_PF_REF = re.compile(r"a7group-\d{1,8}", re.IGNORECASE)


def community_name(name: str) -> str:
    """The bot's spelling of a community name as Bitrix or Property Finder wrote it (_COMMUNITY_WORDS: "Dubai Land" and
    "Dubailand" are Dubailand, "Jumeirah Village Circle" is JVC, "Al Warsan" is International City), else the name as
    given, title-cased when it came all in lower case ("palm jebel ali")."""
    text = " ".join(str(name or "").split())
    low = text.lower()
    for word, canonical in _COMMUNITY_WORDS:
        if word in low:
            return canonical
    return text.title() if text and text == low else text


def pf_reference(value) -> str:
    """"a7group-1633" from a card's Property Finder ref field (C62), lower case; '' for anything else."""
    match = _PF_REF.search(str(value or ""))
    return match.group(0).lower() if match else ""


def pack_names(rows, listed=None) -> list:
    """The rows' community as the packs name it (communities.by_name: a card's "Damac Hills 2" is the Damac Hills pack's,
    a listing's "DAMAC Hills 2" too, "Greens" is The Greens', "Rukan" is Dubailand's), so the unit counts as the pack's
    (communities.named_packs, matches, both by the pack's name); a name no pack knows stays as it is. ``listed``: the
    packs, read once per sync (the round-20 review: four of the C59 names were stored under a name no pack uses)."""
    from . import communities

    packs = communities.packs() if listed is None else listed
    for row in rows:
        pack = communities.by_name(row.get("community") or "", packs)
        if pack is not None:
            row["community"] = pack.name[:80]
    return rows


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
    pages = 0
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
        pages += 1
        if not page or pages >= PF_PAGES_AT_MOST:
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


# The location tree (GET /v1/locations?filter[id]=): a listing gives a location id only; the tree names the community
# ("Villanova") and the sub-community ("La Violeta"). Read once per id per process, at most this many ids a sync.
PF_LOCATIONS_AT_MOST = 300
_LOCATIONS: dict = {}


def pf_location(client: httpx.Client, token: str, location_id) -> dict | None:
    """The location's {id, name, type, tree: [{id, name, type}]} from Property Finder, None when it gives none."""
    try:
        response = client.get(
            f"{PF_BASE}/v1/locations",
            params={"filter[id]": location_id},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # noqa: BLE001 - a nameless location is a unit without a community, never a lost sync
        logger.info("Lead AI inventory: location %s not read (%s)", location_id, str(exc)[:80])
        return None
    data = body.get("data") if isinstance(body, dict) else None
    first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    return first if first is not None and str(first.get("id")) == str(location_id) else None


def place_from_tree(location: dict | None) -> tuple[str, str]:
    """(community, sub-area) from a location's tree: the COMMUNITY node, as the bot names it when it knows the name
    (_COMMUNITY_WORDS: "International City Phase 2 (Al Warsan 4)" is International City), and the first SUBCOMMUNITY."""
    if not isinstance(location, dict):
        return "", ""
    tree = [node for node in (location.get("tree") or []) if isinstance(node, dict)]
    community = next((str(node.get("name") or "") for node in tree if node.get("type") == "COMMUNITY"), "")
    low = community.lower()
    for word, name in _COMMUNITY_WORDS:
        if word in low:
            community = name
            break
    subs = [str(node.get("name") or "") for node in tree if node.get("type") == "SUBCOMMUNITY"]
    sub = subs[0] if subs else (str(location.get("name") or "") if location.get("type") == "SUBCOMMUNITY" else "")
    return community[:80], sub[:80]


def pf_row(item: dict, location: dict | None = None) -> dict | None:
    """A LeadAiUnit's fields from one Property Finder listing, or None when it carries no price. ``location``: the
    listing's location tree (pf_location), which names the community and the sub-area the title does not."""
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
    tree_community, tree_sub = place_from_tree(location)
    community, sub_area = community or tree_community, sub_area or tree_sub
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
    from . import communities

    seen: set[str] = set()
    upserted = repeated = 0
    listed = communities.packs()
    with httpx.Client(timeout=PF_TIMEOUT) as client:
        token = pf_token(client)
        for item in pf_listings(client, token):
            source_id = str(item.get("id") or "")
            if source_id in seen:
                repeated += 1  # the API's pages overlap (2026-10-20: 394 rows for 144 listings): each listing once
                continue
            location_id = (item.get("location") or {}).get("id") if isinstance(item.get("location"), dict) else None
            if location_id and location_id not in _LOCATIONS and len(_LOCATIONS) < PF_LOCATIONS_AT_MOST:
                _LOCATIONS[location_id] = pf_location(client, token, location_id)
            row = pf_row(item, _LOCATIONS.get(location_id)) if source_id else None
            if row is None:
                continue
            pack_names([row], listed)
            LeadAiUnit.objects.update_or_create(source=LeadAiUnit.Source.PF, source_id=source_id, defaults={**row, "active": True, "synced_at": timezone.now()})
            seen.add(source_id)
            upserted += 1
    gone = LeadAiUnit.objects.filter(source=LeadAiUnit.Source.PF, active=True).exclude(source_id__in=seen).update(active=False)
    logger.info("Lead AI inventory: Property Finder %s live listings, %s gone, %s repeated across pages", upserted, gone, repeated)
    out = {"upserted": upserted, "gone": gone}
    if repeated:
        out["repeated"] = repeated
    return out


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
    # Cursor's C59 (2026-10-20): the card's own Community name (UF_CRM_A7_AVAIL_COMMUNITY, 2691; its enum ids below), filled
    # on 316 of 557 cards; and C62: the Property Finder ref (UF 2698; Bitrix refused a named field for a string on CRM_5).
    "community": "ufCrmA7AvailCommunity",
    "pf_ref": "ufCrm5_1792564962558",
}
# The Community name enum (ops/bitrix-aws/a7_c59_enum_ids.md), id → the name as Bitrix lists it; community_name gives
# the bot's spelling. The six International City clusters name the community and the cluster.
BITRIX_COMMUNITY = {
    2526: "International City", 2527: "Dubai Land", 2528: "Mudon", 2529: "Arabian Ranches 3", 2530: "Serena", 2531: "Damac Lagoons",
    2532: "Al Warsan", 2533: "Dubai Hills Estate", 2534: "Villanova", 2535: "Nad Al Sheba", 2536: "Al Jaddaf",
    2537: "Dubai Land Residence Complex", 2538: "Business Bay", 2539: "Dubai Creek Harbour", 2540: "Liwan", 2541: "Al Satwa",
    2542: "Arjan", 2543: "The Valley", 2544: "Dubailand", 2545: "Dubai Silicon Oasis", 2546: "Dubai Sports City", 2547: "City Walk",
    2548: "Greens", 2549: "Meydan", 2550: "palm jebel ali", 2551: "Jumeirah Golf Estates", 2552: "Dubai Marina",
    2553: "Mohammed Bin Rashid City", 2554: "Damac Hills 2", 2555: "Downtown Dubai", 2556: "Jebel Ali", 2557: "The Greens",
    2558: "Arabian Ranches 2", 2559: "Jumeirah Village Triangle", 2560: "Town Square", 2561: "Dubai Science Park",
    2562: "Tilal Al Ghaf", 2563: "DAMAC Hills", 2564: "Jumeirah", 2565: "Jumeirah Village Circle", 2566: "Mirdif",
    2567: "Sobha Hartland", 2568: "The Hills", 2569: "Meydan City", 2570: "Rukan", 2571: "Dubai South (Dubai World Central)",
    2572: "France Cluster", 2573: "Dubai Harbour", 2574: "England Cluster", 2575: "Greece Cluster", 2576: "Morocco Cluster",
    2577: "Persia Cluster", 2578: "Spain Cluster", 2579: "Zabeel",
}
IC_CLUSTERS = frozenset({"France Cluster", "England Cluster", "Greece Cluster", "Morocco Cluster", "Persia Cluster", "Spain Cluster"})


def bitrix_place(named: str, text: str) -> tuple[str, str]:
    """(community, sub-area) of an Availability card: its Community name field first (C59; an International City cluster
    there names the community and the cluster; another name takes the bot's spelling, with the cluster from the area and
    title only when it is International City), else the area and title read as before (place_of)."""
    community, sub = place_of(text)
    if named in IC_CLUSTERS:
        return "International City", named
    if named:
        community = community_name(named)
        return community, (sub if community == "International City" else "")
    return community, sub
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
    community, sub_area = bitrix_place(enum("community", BITRIX_COMMUNITY) or "", f"{area} {title}")
    if not community:
        return []
    reference = pf_reference(item.get(BITRIX_FIELDS["pf_ref"]))
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
            "reference": reference,
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
    from . import communities

    started = timezone.now()
    listed = communities.packs()
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
                rows = pack_names(bitrix_rows(item, stage), listed)
                if not rows:
                    skipped += 1
                    continue
                for row in rows:
                    source_id = f"{item.get('id')}:{row['deal']}"
                    LeadAiUnit.objects.update_or_create(source=LeadAiUnit.Source.BITRIX, source_id=source_id, defaults={**row, "active": True, "synced_at": timezone.now()})
                    seen.add(source_id)
                    upserted += 1
            if len(items) < BITRIX_PAGE:
                break
            start += BITRIX_PAGE
    # Only rows nothing touched since the sync began retire: a card the webhook refreshed meanwhile (refresh_bitrix, after
    # its stage was paged) keeps its rows (the round-20 review).
    gone = (
        LeadAiUnit.objects.filter(source=LeadAiUnit.Source.BITRIX, active=True, synced_at__lt=started)
        .exclude(source_id__in=seen)
        .update(active=False)
    )
    logger.info("Lead AI inventory: Bitrix Availability %s clean units, %s skipped (no bedrooms, type, purpose, place or price), %s gone", upserted, skipped, gone)
    return {"upserted": upserted, "skipped": skipped, "gone": gone}


def refresh_bitrix(card_id: int) -> dict:
    """One Availability card read again (crm.item.get) after Bitrix's own webhook said it changed (Cursor's C46,
    bitrix_views.inventory_event): its clean rows upserted and active, any other row it had retired; a card that is gone
    (Bitrix: not found), dirty, in another category or off the available stages retires every row it had. Any other
    refusal (a token without the scope, a card we may not read) leaves its rows for the half-hourly sync, which still
    reads them all. Counts; raises BitrixTransient for the task to try again."""
    from apps.crmlink import client as bitrix

    from . import communities

    if not bitrix.configured():
        return {"skipped": "no Bitrix webhook"}
    card_id = int(card_id)
    try:
        with bitrix.background():
            result = bitrix.call("crm.item.get", {"entityTypeId": BITRIX_ENTITY_TYPE, "id": card_id})
    except bitrix.BitrixTransient:
        raise
    except bitrix.BitrixError as exc:
        if "not found" not in str(exc).lower():
            logger.warning("Lead AI inventory: Availability card %s not read (%s): its units stay for the sync", card_id, str(exc)[:80])
            return {"card": card_id, "error": str(exc)[:120]}
        logger.info("Lead AI inventory: Availability card %s is gone (%s): its units retire", card_id, str(exc)[:80])
        result = None
    item = (result.get("item") if isinstance(result, dict) else None) or {}
    stage = str(item.get("stageId") or "")
    category = item.get("categoryId")
    in_category = category in (None, "", BITRIX_CATEGORY, str(BITRIX_CATEGORY))
    rows = pack_names(bitrix_rows(item, stage), communities.packs()) if item and stage in BITRIX_STAGES and in_category else []
    seen: set[str] = set()
    for row in rows:
        source_id = f"{card_id}:{row['deal']}"
        LeadAiUnit.objects.update_or_create(source=LeadAiUnit.Source.BITRIX, source_id=source_id, defaults={**row, "active": True, "synced_at": timezone.now()})
        seen.add(source_id)
    gone = (
        LeadAiUnit.objects.filter(source=LeadAiUnit.Source.BITRIX, active=True, source_id__startswith=f"{card_id}:")
        .exclude(source_id__in=seen)
        .update(active=False)
    )
    return {"card": card_id, "stage": stage, "upserted": len(rows), "gone": gone}


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
    if isinstance(unit, (tuple, list, set)):
        rows = rows.filter(unit__in=[item for item in unit if item]) if any(unit) else rows
    elif unit:
        rows = rows.filter(unit=unit)
    if deal in (LeadAiUnit.Deal.RENT, LeadAiUnit.Deal.SALE):
        rows = rows.filter(deal=deal)
    if budget:
        rows = rows.filter(price__lte=int(budget * 1.15))
    wanted = {str(area or "").lower().replace(" cluster", "") for area in sub_areas or () if area}
    rows = list(rows.order_by("price", "pk"))
    # A card published on Property Finder (C62: the same a7group reference, for the same deal) is one unit: the listing,
    # with its photos and link, stands for both. Before any cut, so the twin is dropped whatever its price; a card offered
    # for rent and sale keeps the deal the listing is not for (the round-20 review).
    published = {(row.reference.casefold(), row.deal) for row in rows if row.reference and row.source == LeadAiUnit.Source.PF}
    rows = [row for row in rows if not (row.source == LeadAiUnit.Source.BITRIX and ((row.reference or "").casefold(), row.deal) in published)]
    if wanted:
        rows.sort(key=lambda row: (0 if row.sub_area.lower().replace(" cluster", "") in wanted else 1, row.price or 0))
    return rows[:limit]


def line(row: LeadAiUnit) -> str:
    where = ", ".join(part for part in (row.sub_area, row.community) if part)
    price = f"AED {row.price:,}" + (" a year" if row.deal == LeadAiUnit.Deal.RENT else "")
    size = f", {row.size_sqft:,} sq ft" if row.size_sqft else ""
    furnished = f", {row.furnished}" if row.furnished else ""
    ref = row.reference or f"{row.get_source_display()} #{row.source_id}"
    # No photo count: "1 photos" read as "1-bedroom" in the 2e gate's round 17; the system sends the photos itself.
    return f"- {ref}: {unit_words(row)} for {row.deal} in {where}{size}{furnished}, {price}"


def unit_words(row: LeadAiUnit) -> str:
    """"3-bedroom townhouse", "studio", "one-bedroom apartment": the unit with its bedrooms when they say more than the
    unit word does (a pack customer asks for "3 bedrooms": the line must say the unit has them)."""
    noun = UNIT_WORDS.get(row.unit, row.unit)
    beds = str(row.bedrooms or "").strip()
    if beds.isdigit() and int(beds) >= 1 and row.unit in (tracks.TWO_PLUS, VILLA, TOWNHOUSE):
        return f"{beds}-bedroom {noun}"
    return noun


def lines(rows, enquired=None) -> list[str]:
    """The INVENTORY block's lines (data), or none. ``enquired``: the listing the lead enquired about (a portal lead's
    comment, lead_context; round 22), marked as such — and as no longer listed when it is not active."""
    rows = list(rows or ())
    if not rows:
        return []
    out = [BLOCK_HEAD]
    for row in rows:
        text = line(row)
        if enquired is not None and row.pk == enquired.pk:
            text += " (the listing they enquired about" + ("" if row.active else "; no longer listed, offer the others") + ")"
        out.append(text)
    return out


def enquired(context: dict | None):
    """The unit a portal lead enquired about (lead_context: A7's reference, or Property Finder's listing id), active or
    not, else None. Round 22: a new lead's first turn quotes the listing they asked about."""
    context = context or {}
    ref = str(context.get("listing_ref") or "").strip().lower()
    listing_id = str(context.get("listing_id") or "").strip()
    if ref:
        row = LeadAiUnit.objects.filter(reference__iexact=ref).order_by("-active", "-pk").first()
        if row is not None:
            return row
    if listing_id:
        return LeadAiUnit.objects.filter(source=LeadAiUnit.Source.PF, source_id__iexact=listing_id).order_by("-active", "-pk").first()
    return None


def known_amounts(rows) -> str:
    """The units' figures, for the amount filter: a price, a size or a reference (a7group-1901 carries a number) quoted
    from the block is no invention."""
    parts = []
    for row in rows or ():
        beds = str(row.bedrooms or "").strip()
        if beds.isdigit():
            parts.append(beds)  # "a 4-bedroom villa": the count is the unit's own (the residential floor checks from 100 down)
        if row.price:
            parts += [f"{row.price:,}", str(row.price)]
        if row.size_sqft:
            parts += [f"{row.size_sqft:,}", str(row.size_sqft)]
        if row.reference:
            parts += [row.reference, re.sub(r"\D", "", row.reference)]
    return " ".join(part for part in parts if part)


def deal_of(track: str) -> str:
    return {tracks.RENT: LeadAiUnit.Deal.RENT, tracks.SALE: LeadAiUnit.Deal.SALE}.get(track, "")


def pack_units(unit: str) -> tuple:
    """The units a pack chat's wish matches (the community packs' flow): two bedrooms or more are an apartment, a townhouse
    or a villa alike (a "3 bedroom in Mudon" is a townhouse there); a villa or a townhouse its own; a studio or a
    one-bedroom its own; nothing named, every unit but a shop."""
    if unit == tracks.TWO_PLUS:
        return (tracks.TWO_PLUS, VILLA, TOWNHOUSE)
    if unit in (VILLA, TOWNHOUSE, tracks.STUDIO, tracks.ONE_BR):
        return (unit,)
    return (tracks.STUDIO, tracks.ONE_BR, tracks.TWO_PLUS, VILLA, TOWNHOUSE)


def by_reference(rows, text: str):
    """The unit among ``rows`` whose reference the text names (a7group-1806), else the first row, else None."""
    rows = list(rows or ())
    low = str(text or "").lower()
    for row in rows:
        if row.reference and row.reference.lower() in low:
            return row
    return rows[0] if rows else None
