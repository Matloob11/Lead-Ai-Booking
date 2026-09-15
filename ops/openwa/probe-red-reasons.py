#!/usr/bin/env python3
"""Print RED Conversation Health rows from OpenWA sqlite + Bitrix AI monitor reason."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from collections import Counter

DB = os.environ.get("DATABASE_NAME", "/app/data/openwa.sqlite")
BASE = os.environ["BITRIX_WEBHOOK_BASE"].rstrip("/")
HEALTH = os.environ.get("BITRIX_HEALTH_FIELD", "UF_CRM_CONVERSATION_HEALTH")
MONITOR = os.environ.get("BITRIX_AI_MONITOR_FIELD", "UF_CRM_AI_MONITOR")
OWNER_TYPE = os.environ.get("BITRIX_OWNER_DATA_TYPE_ID", "1042")
RED_ENUM = "2307"


def bx(method: str, params: dict) -> dict:
    url = f"{BASE}/{method}.json"
    data = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT sessionId, chatId, phone, chatName, bitrixLeadId, bitrixEntityType,
               lastClassifiedAt, updatedAt
        FROM chat_leads
        WHERE colour = 'red'
        ORDER BY updatedAt DESC
        """
    ).fetchall()
    print(f"sqlite_red={len(rows)}")

    reasons: list[str] = []
    for r in rows:
        entity = (r["bitrixEntityType"] or "lead").strip()
        lid = str(r["bitrixLeadId"])
        reason = ""
        monitor = ""
        try:
            if entity.startswith("DYNAMIC_") or entity == "DYNAMIC_1042" or entity == OWNER_TYPE:
                res = bx(
                    "crm.item.get",
                    {
                        "entityTypeId": OWNER_TYPE,
                        "id": lid,
                    },
                )
                item = (res.get("result") or {}).get("item") or {}
                # SPA field codes are often camelCase ufCrm…
                monitor = (
                    item.get(MONITOR)
                    or item.get(MONITOR.lower())
                    or item.get("ufCrmAiMonitor")
                    or item.get("ufCrmConversationHealth")
                    or ""
                )
                # Find any field containing 'monitor' / health text
                if not monitor:
                    for k, v in item.items():
                        if not isinstance(v, str):
                            continue
                        if "monitor" in k.lower() or "AI Monitor" in v or "Reason:" in v:
                            monitor = v
                            break
            else:
                res = bx(
                    "crm.lead.get",
                    {"id": lid},
                )
                item = res.get("result") or {}
                monitor = item.get(MONITOR) or ""
        except Exception as e:
            monitor = f"ERR:{e}"

        # Prefer Reason: line from monitor / timeline-style text
        text = str(monitor).replace("\r", "")
        for line in text.split("\n"):
            if line.strip().lower().startswith("reason:"):
                reason = line.split(":", 1)[1].strip()
                break
        if not reason and text and not text.startswith("ERR:"):
            reason = text.strip().split("\n")[0][:220]

        reasons.append(reason or "(no reason stored)")
        print(
            json.dumps(
                {
                    "phone": r["phone"],
                    "name": r["chatName"],
                    "session": r["sessionId"],
                    "lead": lid,
                    "entity": entity,
                    "reason": reason or text[:220],
                },
                ensure_ascii=False,
            )
        )

    print("--- common ---")
    # crude keyword buckets
    buckets = Counter()
    for reason in reasons:
        low = reason.lower()
        if any(w in low for w in ("outside", "personal", "private number", "direct", "bypass", "off book", "commission")):
            buckets["outside_company / personal deal"] += 1
        elif any(w in low for w in ("cash", "without", "broker", "side deal", "cut company")):
            buckets["side / cash deal"] += 1
        elif "err:" in low:
            buckets["could_not_fetch_bitrix"] += 1
        elif reason == "(no reason stored)":
            buckets["no_reason_stored"] += 1
        else:
            buckets["other"] += 1
    for k, v in buckets.most_common():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
