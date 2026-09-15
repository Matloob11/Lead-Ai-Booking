#!/usr/bin/env bash
# 1) Colour emoji on Conversation Health enum values
# 2) Create AI Monitor (reason) + WhatsApp Chat fields
# 3) Put both under Conversation Health section on lead card
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
BASE="${BITRIX_WEBHOOK_BASE%/}"
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

REMOTE_PY=$(cat <<'PY'
import json, os, ssl, urllib.request

base = os.environ["BITRIX_BASE"].rstrip("/")
ctx = ssl.create_default_context()

def call(method, payload=None):
    req = urllib.request.Request(
        f"{base}/{method}.json",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
        return json.loads(resp.read().decode())

def ensure_string_field(field_name: str, label: str, rows: int) -> str:
    listed = call(
        "crm.lead.userfield.list",
        {"filter": {"FIELD_NAME": field_name}},
    )
    rows_found = listed.get("result") or []
    if rows_found:
        fid = rows_found[0]["ID"]
        call(
            "crm.lead.userfield.update",
            {
                "id": fid,
                "fields": {
                    "EDIT_FORM_LABEL": {"en": label},
                    "LIST_COLUMN_LABEL": {"en": label},
                    "LIST_FILTER_LABEL": {"en": label},
                    "SHOW_IN_LIST": "Y",
                    "EDIT_IN_LIST": "Y",
                    "SETTINGS": {"SIZE": 60, "ROWS": rows},
                },
            },
        )
        print(f"field_ok {field_name} id={fid}")
        return field_name
    added = call(
        "crm.lead.userfield.add",
        {
            "fields": {
                "FIELD_NAME": field_name.replace("UF_CRM_", "", 1)
                if field_name.startswith("UF_CRM_")
                else field_name,
                "USER_TYPE_ID": "string",
                "XML_ID": field_name,
                "EDIT_FORM_LABEL": {"en": label},
                "LIST_COLUMN_LABEL": {"en": label},
                "LIST_FILTER_LABEL": {"en": label},
                "MULTIPLE": "N",
                "MANDATORY": "N",
                "SHOW_FILTER": "Y",
                "SHOW_IN_LIST": "Y",
                "EDIT_IN_LIST": "Y",
                "SETTINGS": {"SIZE": 60, "ROWS": rows},
            }
        },
    )
    if added.get("error"):
        # Bitrix wants FIELD_NAME without UF_CRM_ prefix sometimes; try raw short name
        short = field_name
        if short.startswith("UF_CRM_"):
            short = short[len("UF_CRM_") :]
        added = call(
            "crm.lead.userfield.add",
            {
                "fields": {
                    "FIELD_NAME": short,
                    "USER_TYPE_ID": "string",
                    "XML_ID": field_name,
                    "EDIT_FORM_LABEL": {"en": label},
                    "LIST_COLUMN_LABEL": {"en": label},
                    "LIST_FILTER_LABEL": {"en": label},
                    "MULTIPLE": "N",
                    "MANDATORY": "N",
                    "SHOW_FILTER": "Y",
                    "SHOW_IN_LIST": "Y",
                    "EDIT_IN_LIST": "Y",
                    "SETTINGS": {"SIZE": 60, "ROWS": rows},
                }
            },
        )
    if added.get("error"):
        raise SystemExit(f"userfield.add {field_name}: {added}")
    print(f"field_created {field_name} id={added.get('result')}")
    return field_name

# --- enum colour lights (Bitrix has no native colour swatch on enum; emoji is visible) ---
enum_upd = call(
    "crm.lead.userfield.update",
    {
        "id": 2522,
        "fields": {
            "EDIT_FORM_LABEL": {"en": "Conversation Health"},
            "LIST_COLUMN_LABEL": {"en": "Conversation Health"},
            "LIST_FILTER_LABEL": {"en": "Conversation Health"},
            "SETTINGS": {
                "DISPLAY": "UI",
                "LIST_HEIGHT": 1,
                "CAPTION_NO_VALUE": "Not classified",
                "SHOW_NO_VALUE": "Y",
            },
            "LIST": [
                {"ID": "2307", "VALUE": "🔴 RED", "SORT": "100", "DEF": "N", "XML_ID": "red"},
                {"ID": "2308", "VALUE": "🩷 PINK", "SORT": "200", "DEF": "N", "XML_ID": "pink"},
                {"ID": "2309", "VALUE": "🟡 YELLOW", "SORT": "300", "DEF": "N", "XML_ID": "yellow"},
                {"ID": "2310", "VALUE": "⚪ WHITE", "SORT": "400", "DEF": "N", "XML_ID": "white"},
                {"ID": "2311", "VALUE": "🟢 GREEN", "SORT": "500", "DEF": "N", "XML_ID": "green"},
            ],
        },
    },
)
print("enum_update", enum_upd.get("result"), enum_upd.get("error"), enum_upd.get("error_description"))

REASON_FIELD = "UF_CRM_AI_MONITOR"
CHAT_FIELD = "UF_CRM_WA_CHAT"
ensure_string_field(REASON_FIELD, "AI Monitor", rows=4)
ensure_string_field(CHAT_FIELD, "WhatsApp Chat", rows=12)

# Confirm actual FIELD_NAMEs (Bitrix may prefix)
for want in (REASON_FIELD, CHAT_FIELD, "UF_CRM_CONVERSATION_HEALTH"):
    found = call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": want}})
    if not found.get("result"):
        # search by XML_ID / label
        allf = call("crm.lead.userfield.list", {"order": {"ID": "DESC"}, "start": 0})
        hits = [
            f
            for f in (allf.get("result") or [])
            if f.get("FIELD_NAME") == want
            or f.get("XML_ID") == want
            or want.replace("UF_CRM_", "") in (f.get("FIELD_NAME") or "")
        ]
        print("lookup", want, [(h.get("ID"), h.get("FIELD_NAME")) for h in hits[:3]])
    else:
        print("confirmed", want, found["result"][0]["ID"])

SECTION_NAME = "a7_conversation_health"
SECTION = {
    "name": SECTION_NAME,
    "title": "Conversation Health",
    "type": "section",
    "elements": [
        {"name": "UF_CRM_CONVERSATION_HEALTH", "optionFlags": "0"},
        {"name": REASON_FIELD, "optionFlags": "0"},
        {"name": CHAT_FIELD, "optionFlags": "0"},
    ],
}

for extras in ({}, {"leadCustomerType": 1}, {"leadCustomerType": 2}):
    get_payload = {"scope": "C"}
    if extras:
        get_payload["extras"] = extras
    cfg = call("crm.lead.details.configuration.get", get_payload)
    data = cfg.get("result")
    if data is None:
        print("skip null config", extras)
        continue
    drop = {"UF_CRM_CONVERSATION_HEALTH", REASON_FIELD, CHAT_FIELD}
    cleaned = []
    for sec in data:
        if sec.get("name") == SECTION_NAME:
            continue
        elems = [e for e in (sec.get("elements") or []) if e.get("name") not in drop]
        cleaned.append({**sec, "elements": elems})
    new_data = [SECTION] + cleaned
    set_payload = {"scope": "C", "data": new_data}
    if extras:
        set_payload["extras"] = extras
    sett = call("crm.lead.details.configuration.set", set_payload)
    print("form_set", extras or "default", sett.get("result"), sett.get("error"))

force = call("crm.lead.details.configuration.forceCommonScopeForAll", {})
print("forceCommon", force.get("result"), force.get("error"))

# Backfill reason from latest [AI Monitor] timeline comment on Phase1 leads
start = 0
filled = 0
while True:
    page = call(
        "crm.lead.list",
        {
            "filter": {"SOURCE_DESCRIPTION": "Conversation Health Phase 1"},
            "select": ["ID", REASON_FIELD],
            "order": {"ID": "DESC"},
            "start": start,
        },
    )
    rows = page.get("result") or []
    if not rows:
        break
    for row in rows:
        lid = int(row["ID"])
        if (row.get(REASON_FIELD) or "").strip():
            continue
        comments = call(
            "crm.timeline.comment.list",
            {
                "filter": {"ENTITY_ID": lid, "ENTITY_TYPE": "lead"},
                "order": {"ID": "DESC"},
                "start": 0,
            },
        )
        reason = ""
        colour = ""
        for c in comments.get("result") or []:
            text = c.get("COMMENT") or ""
            if "[AI Monitor]" not in text:
                continue
            for line in text.splitlines():
                if line.startswith("[AI Monitor]"):
                    colour = line.replace("[AI Monitor]", "").strip()
                if line.startswith("Reason:"):
                    reason = line[len("Reason:") :].strip()
            break
        if not reason and not colour:
            continue
        body = reason or colour
        if colour and reason:
            body = f"{colour}: {reason}"
        elif colour:
            body = colour
        call("crm.lead.update", {"id": lid, "fields": {REASON_FIELD: body[:2000]}})
        filled += 1
        print(f"backfill_reason lead={lid}")
    if len(rows) < 50:
        break
    start += 50
print(f"backfill_reason_count={filled}")

# Prove enum labels
uf = call("crm.lead.userfield.list", {"filter": {"FIELD_NAME": "UF_CRM_CONVERSATION_HEALTH"}})
print("enum_values", [x.get("VALUE") for x in ((uf.get("result") or [{}])[0].get("LIST") or [])])
PY
)

printf '%s\n' "$REMOTE_PY" | "${SSH[@]}" "$HOST" "cat > /tmp/upgrade_health_ui.py"
"${SSH[@]}" "$HOST" "BITRIX_BASE=$(printf '%q' "$BASE") python3 /tmp/upgrade_health_ui.py"
