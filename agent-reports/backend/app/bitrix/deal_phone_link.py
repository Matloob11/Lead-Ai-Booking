"""Link Renewals deal phone UFs to CRM Contacts (Voiso / Bitrix call button).

Category 9 deals store tenant/owner phones in string UFs, not CONTACT_ID.
Bitrix kanban call icon only activates when a Client Contact with PHONE is bound.
No form/layout changes — only CONTACT_ID on the deal.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any, Iterator

from .owner_phone_link import (
    _create_contacts_batch,
    _ensure_contact_phone,
    _resolve_phones_batch,
    batch_call,
    normalize_uae,
)

logger = logging.getLogger(__name__)

RENEWAL_CATEGORY_ID = 9

# Stages user asked to fix (Overdue excluded).
RENEWAL_TARGET_STAGES: tuple[str, ...] = (
    "C9:NEW",
    "C9:UC_D741T1",
    "C9:UC_2K6PKD",
    "C9:UC_4UL8U1",
    "C9:UC_J5K36J",
    "C9:UC_POOVSR",
    "C9:UC_AEF7BS",
    "C9:UC_UU1TA3",
    "C9:UC_DFB2KB",
    "C9:UC_B8A27G",
    "C9:UC_CUSEPM",
    "C9:UC_DO7BK8",
    "C9:UC_QP6G66",
    "C9:UC_D20ZZG",
    "C9:UC_PPKS2U",
    "C9:UC_ZI2JUI",
)

# Tenant phone first, owner phone fallback (verified on deal #39064).
PHONE_UF_TENANT = "UF_CRM_1734263575786"
PHONE_UF_OWNER = "UF_CRM_1735377605713"
PHONE_UFS = (PHONE_UF_TENANT, PHONE_UF_OWNER)
NAME_UF_TENANT = "UF_CRM_1734263542611"


def phone_from_deal(deal: dict[str, Any]) -> tuple[Any, str]:
    for key in PHONE_UFS:
        raw = deal.get(key)
        phone = normalize_uae(raw)
        if phone:
            return raw, phone
    return None, ""


def contact_title(deal: dict[str, Any]) -> str:
    name = str(deal.get(NAME_UF_TENANT) or "").strip()
    if name:
        return name
    return str(deal.get("TITLE") or deal.get("title") or "Renewal tenant").strip()


def _list_deals_page(
    client: Any, *, filter_: dict[str, Any], start: int
) -> tuple[list[dict[str, Any]], int | None]:
    payload = client._post(
        "crm.deal.list",
        {
            "filter": filter_,
            "select": ["ID", "TITLE", "CONTACT_ID", "STAGE_ID", NAME_UF_TENANT, *PHONE_UFS],
            "start": start,
            "order": {"ID": "ASC"},
        },
    )
    rows = payload.get("result") or []
    if not isinstance(rows, list):
        rows = []
    nxt = payload.get("next")
    return rows, (int(nxt) if nxt is not None else None)


def iter_renewal_deals(
    client: Any,
    *,
    stages: tuple[str, ...] = RENEWAL_TARGET_STAGES,
    only_unlinked: bool = True,
) -> Iterator[dict[str, Any]]:
    filt: dict[str, Any] = {
        "CATEGORY_ID": RENEWAL_CATEGORY_ID,
        "@STAGE_ID": list(stages),
    }
    if only_unlinked:
        filt["CONTACT_ID"] = False
    start = 0
    while True:
        rows, nxt = _list_deals_page(client, filter_=filt, start=start)
        for row in rows:
            if phone_from_deal(row)[1]:
                yield row
        if nxt is None:
            break
        start = nxt


def _update_deals_batch(client: Any, links: list[tuple[int, int]]) -> int:
    ok = 0
    chunk_size = 20
    for i in range(0, len(links), chunk_size):
        chunk = links[i : i + chunk_size]
        cmds: dict[str, str] = {}
        for j, (deal_id, contact_id) in enumerate(chunk):
            params = {
                "id": deal_id,
                "fields[CONTACT_ID]": contact_id,
            }
            cmds[f"u{j}"] = "crm.deal.update?" + urllib.parse.urlencode(params)
        results = batch_call(client, cmds)
        for j, _ in enumerate(chunk):
            if results.get(f"u{j}") is not None:
                ok += 1
    return ok


def link_deal(client: Any, deal: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    deal_id = int(deal.get("ID") or deal.get("id") or 0)
    raw, phone = phone_from_deal(deal)
    if not phone:
        return {"deal_id": deal_id, "status": "skip_no_phone"}

    current = int(deal.get("CONTACT_ID") or 0)
    from .owner_phone_link import ensure_contact

    contact_id = ensure_contact(client, phone, contact_title(deal))
    if current == contact_id:
        return {
            "deal_id": deal_id,
            "status": "already_linked",
            "contact_id": contact_id,
            "phone_e164": phone,
        }

    if dry_run:
        return {
            "deal_id": deal_id,
            "status": "would_link",
            "contact_id": contact_id,
            "phone_uf": raw,
            "phone_e164": phone,
            "previous_contact_id": current,
        }

    client._post(
        "crm.deal.update",
        {"id": deal_id, "fields": {"CONTACT_ID": contact_id}},
    )
    return {
        "deal_id": deal_id,
        "status": "linked",
        "contact_id": contact_id,
        "phone_uf": raw,
        "phone_e164": phone,
        "previous_contact_id": current,
    }


def sync_renewal_deal_phones(
    client: Any,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    sleep_s: float = 0.05,
    only_unlinked: bool = True,
    stages: tuple[str, ...] = RENEWAL_TARGET_STAGES,
) -> dict[str, Any]:
    counts: dict[str, int] = {
        "seen": 0,
        "linked": 0,
        "already_linked": 0,
        "would_link": 0,
        "skip_no_phone": 0,
        "errors": 0,
        "contacts_created": 0,
    }
    errors: list[dict[str, Any]] = []
    page: list[dict[str, Any]] = []

    def flush(page_items: list[dict[str, Any]]) -> None:
        nonlocal counts
        if not page_items:
            return
        work: list[tuple[dict[str, Any], str, Any]] = []
        for deal in page_items:
            raw, phone = phone_from_deal(deal)
            if not phone:
                counts["skip_no_phone"] += 1
                continue
            current = int(deal.get("CONTACT_ID") or 0)
            if only_unlinked and current:
                counts["already_linked"] += 1
                continue
            work.append((deal, phone, raw))

        if not work:
            return

        phones = list({p for _, p, _ in work})
        try:
            phone_to_contact = _resolve_phones_batch(client, phones)
        except Exception as exc:
            counts["errors"] += len(work)
            errors.append({"error": f"resolve_batch: {exc}"})
            logger.exception("renewal deal resolve batch failed")
            return

        to_create: list[tuple[str, str]] = []
        seen_m: set[str] = set()
        for deal, phone, _raw in work:
            if phone in phone_to_contact or phone in seen_m:
                continue
            seen_m.add(phone)
            to_create.append((phone, contact_title(deal)))

        if to_create and not dry_run:
            try:
                created = _create_contacts_batch(client, to_create)
                phone_to_contact.update(created)
                counts["contacts_created"] += len(created)
                for phone, contact_id in created.items():
                    try:
                        _ensure_contact_phone(client, contact_id, phone)
                    except Exception as exc:
                        errors.append({"contact_id": contact_id, "error": f"ensure_phone: {exc}"})
            except Exception as exc:
                counts["errors"] += len(to_create)
                errors.append({"error": f"create_batch: {exc}"})
                logger.exception("renewal deal create batch failed")

        links: list[tuple[int, int]] = []
        for deal, phone, _raw in work:
            deal_id = int(deal.get("ID") or 0)
            contact_id = phone_to_contact.get(phone)
            if not contact_id:
                if dry_run:
                    counts["would_link"] += 1
                else:
                    counts["errors"] += 1
                    errors.append({"deal_id": deal_id, "error": "no_contact"})
                continue
            current = int(deal.get("CONTACT_ID") or 0)
            if current == contact_id:
                counts["already_linked"] += 1
                continue
            if dry_run:
                counts["would_link"] += 1
                continue
            links.append((deal_id, contact_id))

        if links:
            try:
                ok = _update_deals_batch(client, links)
                counts["linked"] += ok
                if ok < len(links):
                    counts["errors"] += len(links) - ok
            except Exception as exc:
                counts["errors"] += len(links)
                errors.append({"error": f"update_batch: {exc}"})
                logger.exception("renewal deal update batch failed")

        if sleep_s:
            time.sleep(sleep_s)

    for deal in iter_renewal_deals(client, stages=stages, only_unlinked=only_unlinked):
        counts["seen"] += 1
        page.append(deal)
        if len(page) >= 40:
            flush(page)
            page = []
            logger.info("renewal deal phone sync progress %s", counts)
        if limit is not None and counts["seen"] >= limit:
            break

    flush(page)
    return {"counts": counts, "errors": errors[:50]}
