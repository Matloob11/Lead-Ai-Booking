#!/usr/bin/env python3
"""Inspect + repair Conversation Health section on shared lead card."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

base = (os.environ.get("BITRIX_WEBHOOK_BASE") or "").rstrip("/")
if not base:
    sys.exit("BITRIX_WEBHOOK_BASE missing")

HEALTH = "UF_CRM_CONVERSATION_HEALTH"
MONITOR = "UF_CRM_AI_MONITOR"
CHAT = "UF_CRM_WA_CHAT"
SECTION_NAME = "a7_conversation_health"
FIELDS = [HEALTH, MONITOR, CHAT]


def call(method: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def summarize(cfg: list) -> None:
    print("--- sections ---")
    for sec in cfg:
        elems = [e.get("name") for e in (sec.get("elements") or [])]
        print(
            f"sec name={sec.get('name')!r} title={sec.get('title')!r} "
            f"elems={len(elems)} has_health={HEALTH in elems} "
            f"has_monitor={MONITOR in elems} has_chat={CHAT in elems}"
        )
        if sec.get("name") == SECTION_NAME or "health" in str(sec.get("title") or "").lower():
            print("  elements:", elems[:30])


def ensure_section(cfg: list) -> list:
    cleaned = []
    for sec in cfg:
        elems = [
            e
            for e in (sec.get("elements") or [])
            if e.get("name") not in FIELDS
        ]
        if sec.get("name") == SECTION_NAME:
            continue
        # also drop empty title-only Conversation Health sections from manual UI edits
        title = str(sec.get("title") or "").strip().lower()
        if title in {"conversation health", "conversationhealth"} and not elems:
            continue
        cleaned.append({**sec, "elements": elems})

    section = {
        "name": SECTION_NAME,
        "title": "Conversation Health",
        "type": "section",
        # optionFlags "1" = always show (Bitrix hides "0" fields from the card)
        "elements": [{"name": f, "optionFlags": "1"} for f in FIELDS],
    }
    return [section] + cleaned


do_fix = "--fix" in sys.argv

for extras in ({}, {"leadCustomerType": 1}, {"leadCustomerType": 2}):
    get_payload: dict = {"scope": "C"}
    if extras:
        get_payload["extras"] = extras
    cfg = call("crm.lead.details.configuration.get", get_payload).get("result")
    print("=== get", extras or "default", "null?" if cfg is None else f"sections={len(cfg)}")
    if cfg is None:
        continue
    summarize(cfg)
    if not do_fix:
        continue
    new_data = ensure_section(cfg)
    set_payload: dict = {"scope": "C", "data": new_data}
    if extras:
        set_payload["extras"] = extras
    sett = call("crm.lead.details.configuration.set", set_payload)
    print("set", extras or "default", sett.get("result"), sett.get("error"), sett.get("error_description"))

if do_fix:
    force = call("crm.lead.details.configuration.forceCommonScopeForAll", {})
    print("forceCommonScopeForAll", force.get("result"), force.get("error"), force.get("error_description"))
    cfg = call("crm.lead.details.configuration.get", {"scope": "C"}).get("result") or []
    print("=== after fix ===")
    summarize(cfg)

# Timeline: also list via crm.timeline.item.list if available
lead_id = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "72122"
try:
    items = call(
        "crm.timeline.item.list",
        {
            "entityTypeId": 1,
            "entityId": int(lead_id),
            "filter": {},
        },
    )
    print("timeline.item.list keys", list(items.keys())[:8])
    result = items.get("result") or {}
    if isinstance(result, dict):
        print("itemCount", len(result.get("items") or result.get("items") or result))
        # print a compact sample
        raw = result.get("items") or result
        if isinstance(raw, dict):
            for i, (k, v) in enumerate(list(raw.items())[:6]):
                print("item", k, str(v)[:160].replace("\n", " "))
        elif isinstance(raw, list):
            for v in raw[:6]:
                print("item", str(v)[:160].replace("\n", " "))
    else:
        print("timelineResultType", type(result).__name__, str(result)[:300])
except Exception as e:
    print("timeline.item.list error", e)
