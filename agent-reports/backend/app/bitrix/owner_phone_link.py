"""Link Owner Data SPA phone UF fields to CRM Contacts (enables call button).

Owner Data (entityTypeId=1042) stores phones in Number UFs, not Lead-style
`fm` multifields. Bitrix toolbar call/email icons only activate when a Client
Contact with PHONE is bound. This module finds/creates that Contact and sets
`contactId` on the SPA item.

Uses Bitrix `batch` where possible — Owner Data volume is large and each
webhook round-trip from outside the CRM host is expensive.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Any, Iterator

from .client import BitrixClient, BitrixError

logger = logging.getLogger(__name__)

ENTITY_TYPE_ID = 1042
PHONE_UF_PRIMARY = "ufCrm5_1768317611513"
PHONE_UF_SECONDARY = "ufCrm5_1769416533028"
PHONE_UF_OWNER_NO1 = "ufCrm5_1777563197150"  # string "Owner no 1," — often filled on imports
PHONE_UF_IMPORT_MOBILE = "ufCrm5_1768314841508"
PHONE_UFS = (
    PHONE_UF_PRIMARY,
    PHONE_UF_SECONDARY,
    PHONE_UF_OWNER_NO1,
    PHONE_UF_IMPORT_MOBILE,
)


def normalize_uae(raw: Any) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits or digits == "0":
        return ""
    if digits.startswith("971"):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 10:
        return f"+971{digits[1:]}"
    if len(digits) == 9 and digits.startswith("5"):
        return f"+971{digits}"
    if len(digits) >= 8:
        return f"+{digits}"
    return ""


def phone_from_item(item: dict[str, Any]) -> tuple[Any, str]:
    for key in PHONE_UFS:
        raw = item.get(key)
        phone = normalize_uae(raw)
        if phone:
            return raw, phone
    return None, ""


def _q(params: dict[str, Any]) -> str:
    """Encode nested Bitrix batch command query string."""
    return urllib.parse.urlencode(params, doseq=True)


def batch_call(client: BitrixClient, cmds: dict[str, str]) -> dict[str, Any]:
    if not cmds:
        return {}
    payload = client._post("batch", {"halt": 0, "cmd": cmds})
    result = payload.get("result") or {}
    if isinstance(result, dict) and "result" in result:
        return result.get("result") or {}
    return result if isinstance(result, dict) else {}


def find_contact_by_phone(client: BitrixClient, phone: str) -> int | None:
    variants = [phone, phone.lstrip("+"), re.sub(r"\D", "", phone)]
    for value in variants:
        if not value:
            continue
        try:
            payload = client._post(
                "crm.duplicate.findbycomm",
                {"type": "PHONE", "values": [value], "entity_type": "CONTACT"},
            )
            ids = ((payload.get("result") or {}).get("CONTACT")) or []
            if ids:
                return int(ids[0])
        except BitrixError:
            continue
        except Exception:
            logger.exception("duplicate.findbycomm failed for %s", value)

    for value in variants:
        if not value:
            continue
        try:
            payload = client._post(
                "crm.contact.list",
                {
                    "filter": {"PHONE": value},
                    "select": ["ID", "NAME", "LAST_NAME"],
                    "start": 0,
                },
            )
        except BitrixError:
            continue
        batch = payload.get("result") or []
        if isinstance(batch, list) and batch:
            return int(batch[0]["ID"])
    return None


def _contact_phone_fields(phone: str) -> dict[str, Any]:
    return {
        "PHONE": [{"VALUE": phone, "VALUE_TYPE": "MOBILE"}],
    }


def ensure_contact(client: BitrixClient, phone: str, title: str) -> int:
    existing = find_contact_by_phone(client, phone)
    if existing:
        _ensure_contact_phone(client, existing, phone)
        return existing
    name = (title or "").replace("Owner Data #", "Owner ").strip() or "Owner"
    payload = client._post(
        "crm.contact.add",
        {
            "fields": {
                "NAME": name[:100],
                "OPENED": "Y",
                "TYPE_ID": "CLIENT",
                **_contact_phone_fields(phone),
            }
        },
    )
    return int(payload["result"])


def _ensure_contact_phone(client: BitrixClient, contact_id: int, phone: str) -> None:
    ct = client._post("crm.contact.get", {"id": contact_id}).get("result") or {}
    if str(ct.get("HAS_PHONE") or "").upper() == "Y" and ct.get("PHONE"):
        return
    client._post(
        "crm.contact.update",
        {"id": contact_id, "fields": _contact_phone_fields(phone)},
    )


def link_item(client: BitrixClient, item: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    item_id = int(item.get("id") or item.get("ID") or 0)
    raw, phone = phone_from_item(item)
    if not phone:
        return {"item_id": item_id, "status": "skip_no_phone"}

    current = int(item.get("contactId") or item.get("contact_id") or 0)
    contact_id = ensure_contact(client, phone, str(item.get("title") or ""))
    if current == contact_id:
        return {
            "item_id": item_id,
            "status": "already_linked",
            "contact_id": contact_id,
            "phone_e164": phone,
        }

    if dry_run:
        return {
            "item_id": item_id,
            "status": "would_link",
            "contact_id": contact_id,
            "phone_uf": raw,
            "phone_e164": phone,
            "previous_contact_id": current,
        }

    client._post(
        "crm.item.update",
        {
            "entityTypeId": ENTITY_TYPE_ID,
            "id": item_id,
            "fields": {
                "contactId": contact_id,
                "contactIds": [contact_id],
            },
        },
    )
    return {
        "item_id": item_id,
        "status": "linked",
        "contact_id": contact_id,
        "phone_uf": raw,
        "phone_e164": phone,
        "previous_contact_id": current,
    }


def _list_page(client: BitrixClient, filter_: dict[str, Any], start: int) -> tuple[list[dict], int | None]:
    payload = client._post(
        "crm.item.list",
        {
            "entityTypeId": ENTITY_TYPE_ID,
            "select": ["id", "title", "contactId", *PHONE_UFS],
            "filter": filter_,
            "start": start,
            "order": {"id": "ASC"},
        },
    )
    result = payload.get("result") or {}
    items = result.get("items") if isinstance(result, dict) else result
    if not isinstance(items, list):
        items = []
    nxt = payload.get("next")
    return items, (int(nxt) if nxt is not None else None)


def iter_owner_items_with_phone(
    client: BitrixClient,
    *,
    only_unlinked: bool = False,
    category_id: int | None = None,
    created_since: str | None = None,
    id_min: int | None = None,
    id_max: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield phone-bearing Owner Data items.

    Uses ``>id`` cursor pagination (always ``start=0``). Bitrix ``start``
    offsets stop around 500 rows — workers were exiting early after one page
    window even when thousands remained in the id range.
    """
    seen: set[int] = set()
    for phone_key in PHONE_UFS:
        if phone_key in (PHONE_UF_OWNER_NO1, PHONE_UF_IMPORT_MOBILE):
            base: dict[str, Any] = {f"!{phone_key}": ""}
        else:
            base = {f">{phone_key}": 0}
        if only_unlinked:
            base["contactId"] = 0
        if category_id is not None:
            base["categoryId"] = category_id
        if created_since:
            base[">=createdTime"] = created_since
        if id_min is not None:
            base[">=id"] = id_min
        if id_max is not None:
            base["<id"] = id_max

        # Cursor just below the floor so the first page includes id_min.
        cursor = (id_min - 1) if id_min is not None else 0
        empty_streak = 0
        while True:
            filt = dict(base)
            filt[">id"] = cursor
            items, _nxt = _list_page(client, filt, 0)
            if not items:
                empty_streak += 1
                if empty_streak >= 1:
                    break
                continue
            empty_streak = 0
            page_max = cursor
            yielded = 0
            for item in items:
                item_id = int(item.get("id") or 0)
                if not item_id:
                    continue
                page_max = max(page_max, item_id)
                if item_id in seen:
                    continue
                if not phone_from_item(item)[1]:
                    continue
                if only_unlinked and int(item.get("contactId") or 0):
                    continue
                seen.add(item_id)
                yielded += 1
                yield item
            if page_max <= cursor:
                break
            cursor = page_max
            # Full Bitrix page is usually 50; shorter page ⇒ end of this filter.
            if len(items) < 50:
                break


def _resolve_phones_batch(client: BitrixClient, phones: list[str]) -> dict[str, int]:
    """Map E.164 phone → contact id via batch duplicate.findbycomm."""
    found: dict[str, int] = {}
    pending = [p for p in phones if p]
    for i in range(0, len(pending), 40):
        chunk = pending[i : i + 40]
        cmds = {
            f"d{j}": (
                "crm.duplicate.findbycomm?"
                + _q({"type": "PHONE", "values": [p], "entity_type": "CONTACT"})
            )
            for j, p in enumerate(chunk)
        }
        results = batch_call(client, cmds)
        for j, phone in enumerate(chunk):
            row = results.get(f"d{j}") or {}
            if isinstance(row, dict):
                ids = row.get("CONTACT") or []
                if ids:
                    found[phone] = int(ids[0])
    return found


def _create_contacts_batch(
    client: BitrixClient, to_create: list[tuple[str, str]]
) -> dict[str, int]:
    """Create contacts for (phone, title) pairs; return phone → id."""
    created: dict[str, int] = {}
    for i in range(0, len(to_create), 40):
        chunk = to_create[i : i + 40]
        cmds: dict[str, str] = {}
        for j, (phone, title) in enumerate(chunk):
            name = (title or "").replace("Owner Data #", "Owner ").strip() or "Owner"
            # Nested fields in batch query: fields[NAME]=…&fields[FM][n0][VALUE]=…
            params = {
                "fields[NAME]": name[:100],
                "fields[OPENED]": "Y",
                "fields[TYPE_ID]": "CLIENT",
                "fields[PHONE][0][VALUE]": phone,
                "fields[PHONE][0][VALUE_TYPE]": "MOBILE",
            }
            cmds[f"c{j}"] = "crm.contact.add?" + urllib.parse.urlencode(params)
        results = batch_call(client, cmds)
        for j, (phone, _title) in enumerate(chunk):
            cid = results.get(f"c{j}")
            if cid:
                created[phone] = int(cid)
    return created


def _update_items_batch(client: BitrixClient, links: list[tuple[int, int]]) -> int:
    """Set contactId for (item_id, contact_id) pairs. Returns success count."""
    ok = 0
    for i in range(0, len(links), 40):
        chunk = links[i : i + 40]
        cmds = {}
        for j, (item_id, contact_id) in enumerate(chunk):
            params = {
                "entityTypeId": ENTITY_TYPE_ID,
                "id": item_id,
                "fields[contactId]": contact_id,
                "fields[contactIds][0]": contact_id,
            }
            cmds[f"u{j}"] = "crm.item.update?" + urllib.parse.urlencode(params)
        results = batch_call(client, cmds)
        for j, _ in enumerate(chunk):
            if results.get(f"u{j}") is not None:
                ok += 1
    return ok


def sync_owner_phone_links(
    client: BitrixClient,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    sleep_s: float = 0.05,
    only_unlinked: bool = False,
    category_id: int | None = None,
    created_since: str | None = None,
    id_min: int | None = None,
    id_max: int | None = None,
) -> dict[str, Any]:
    """Bulk/periodic sync using batched Bitrix calls per list page."""
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
        for item in page_items:
            raw, phone = phone_from_item(item)
            if not phone:
                counts["skip_no_phone"] += 1
                continue
            current = int(item.get("contactId") or 0)
            if only_unlinked and current:
                counts["already_linked"] += 1
                continue
            work.append((item, phone, raw))

        if not work:
            return

        phones = list({p for _, p, _ in work})
        try:
            phone_to_contact = _resolve_phones_batch(client, phones)
        except Exception as exc:
            counts["errors"] += len(work)
            errors.append({"error": f"resolve_batch: {exc}"})
            logger.exception("resolve batch failed")
            return

        to_create: list[tuple[str, str]] = []
        seen_m: set[str] = set()
        for item, phone, _raw in work:
            if phone in phone_to_contact or phone in seen_m:
                continue
            seen_m.add(phone)
            to_create.append((phone, str(item.get("title") or "")))

        if to_create and not dry_run:
            try:
                created = _create_contacts_batch(client, to_create)
                phone_to_contact.update(created)
                counts["contacts_created"] += len(created)
            except Exception as exc:
                counts["errors"] += len(to_create)
                errors.append({"error": f"create_batch: {exc}"})
                logger.exception("create batch failed")

        links: list[tuple[int, int]] = []
        for item, phone, raw in work:
            item_id = int(item.get("id") or 0)
            contact_id = phone_to_contact.get(phone)
            if not contact_id:
                if dry_run:
                    counts["would_link"] += 1
                else:
                    counts["errors"] += 1
                    errors.append({"item_id": item_id, "error": "no_contact"})
                continue
            current = int(item.get("contactId") or 0)
            if current == contact_id:
                counts["already_linked"] += 1
                continue
            if dry_run:
                counts["would_link"] += 1
                continue
            links.append((item_id, contact_id))

        if links:
            try:
                ok = _update_items_batch(client, links)
                counts["linked"] += ok
                if ok < len(links):
                    counts["errors"] += len(links) - ok
            except Exception as exc:
                counts["errors"] += len(links)
                errors.append({"error": f"update_batch: {exc}"})
                logger.exception("update batch failed")

        if sleep_s:
            time.sleep(sleep_s)

    for item in iter_owner_items_with_phone(
        client,
        only_unlinked=only_unlinked,
        category_id=category_id,
        created_since=created_since,
        id_min=id_min,
        id_max=id_max,
    ):
        counts["seen"] += 1
        page.append(item)
        if len(page) >= 40:
            flush(page)
            page = []
            logger.info("owner phone sync progress %s", counts)
        if limit is not None and counts["seen"] >= limit:
            break

    flush(page)
    return {"counts": counts, "errors": errors[:50]}
