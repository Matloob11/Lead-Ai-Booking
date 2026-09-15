"""Set simplified Owner Data card form (category 13 + 14)."""
from __future__ import annotations

import json
import os

from app.bitrix.client import BitrixClient

ENTITY = 1042
KEEP_TITLES = {
    "phone number",
    "phone number 1",
    "owner no 1,",
    "import owner mobile",
    "customer",
    "contact",
    "responsible person",
    "source",
    "stage",
    "amount",
    "lease price (in aed)",
    "selling price (in aed)",
}

# Always keep system fields needed for call + basics
KEEP_NAMES = {
    "title",
    "contactId",
    "assignedById",
    "stageId",
    "opportunity",
    "currencyId",
    "ufCrm5_1768317611513",  # phone number
    "ufCrm5_1769416533028",  # phone number 1
    "ufCrm5_1777563197150",  # Owner no 1,
    "ufCrm5_1768314841508",  # Import Owner Mobile
    "ufCrm5_1734247036310",  # lease price
    "ufCrm5_1734247021855",  # selling price
}


def field_map(client: BitrixClient) -> dict[str, dict]:
    payload = client._post("crm.item.fields", {"entityTypeId": ENTITY, "useOriginalUfNames": "N"})
    fields = (payload.get("result") or {}).get("fields") or payload.get("result") or {}
    return {k: v for k, v in fields.items() if isinstance(v, dict)}


def pick_elements(fields: dict[str, dict]) -> list[dict]:
    chosen: list[tuple[int, str, str]] = []
    order = [
        "title",
        "ufCrm5_1777563197150",
        "ufCrm5_1768317611513",
        "ufCrm5_1769416533028",
        "ufCrm5_1768314841508",
        "contactId",
        "assignedById",
        "stageId",
        "ufCrm5_1734247021855",
        "ufCrm5_1734247036310",
        "opportunity",
    ]
    seen: set[str] = set()
    for name in order:
        if name in fields and name not in seen:
            seen.add(name)
            title = str((fields[name].get("title") or name))
            chosen.append((len(chosen), name, title))
    for name, meta in sorted(fields.items()):
        if name in seen:
            continue
        title = str(meta.get("title") or "").strip()
        if title.lower() in KEEP_TITLES or name in KEEP_NAMES:
            seen.add(name)
            chosen.append((len(chosen), name, title))
    return [
        {"name": name, "optionFlags": 1 if name in (
            "title",
            "ufCrm5_1777563197150",
            "ufCrm5_1768317611513",
            "contactId",
        ) else 0}
        for _, name, _ in sorted(chosen)
    ]


def build_sections(elements: list[dict]) -> list[dict]:
    return [
        {
            "name": "main",
            "title": "Call & contact",
            "type": "section",
            "elements": elements,
        }
    ]


def categories(client: BitrixClient) -> list[dict]:
    payload = client._post("crm.category.list", {"entityTypeId": ENTITY})
    return (payload.get("result") or {}).get("categories") or []


def get_cfg(client: BitrixClient, *, scope: str, category_id: int | None, user_id: int | None) -> dict:
    params: dict = {"entityTypeId": ENTITY, "scope": scope}
    if user_id:
        params["userId"] = user_id
    if category_id is not None:
        params["extras"] = {"categoryId": category_id}
    payload = client._post("crm.item.details.configuration.get", params)
    return payload.get("result") or {}


def set_cfg(client: BitrixClient, *, scope: str, category_id: int, data: list[dict], user_id: int | None) -> dict:
    params: dict = {
        "entityTypeId": ENTITY,
        "scope": scope,
        "extras": {"categoryId": category_id},
        "data": data,
    }
    if user_id:
        params["userId"] = user_id
    return client._post("crm.item.details.configuration.set", params)


def main() -> None:
    client = BitrixClient(os.environ["AGENT_REPORT_BITRIX_WEBHOOK"])
    fields = field_map(client)
    elements = pick_elements(fields)
    sections = build_sections(elements)
    cats = categories(client)
    print("categories:", [(c.get("id"), c.get("name")) for c in cats])
    print("elements:", [e["name"] for e in elements])

    results = []
    for cat in cats:
        cid = int(cat["id"])
        if cid not in (13, 14):
            continue
        before = get_cfg(client, scope="C", category_id=cid, user_id=None)
        blen = len(before) if isinstance(before, list) else len(before.get("data") or [])
        print(f"\ncat {cid} before sections: {blen}")
        try:
            resp = set_cfg(client, scope="C", category_id=cid, data=sections, user_id=None)
            results.append({"categoryId": cid, "set": resp})
            print(f"cat {cid} SET ok", json.dumps(resp, ensure_ascii=False)[:500])
        except Exception as exc:
            results.append({"categoryId": cid, "error": str(exc)})
            print(f"cat {cid} SET ERR", exc)

    for cid in (13, 14):
        try:
            force = client._post(
                "crm.item.details.configuration.forceCommonScopeForAll",
                {"entityTypeId": ENTITY, "extras": {"categoryId": cid}},
            )
            print(f"forceCommon {cid}:", force)
        except Exception as exc:
            print(f"forceCommon {cid} ERR", exc)

    print("\nDONE", json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
