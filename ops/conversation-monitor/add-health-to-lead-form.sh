#!/usr/bin/env bash
# Put UF_CRM_CONVERSATION_HEALTH on the shared lead card (top section).
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
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return json.loads(resp.read().decode())

# 1) Labels on the UF so the card shows a clear English title
upd = call(
    "crm.lead.userfield.update",
    {
        "id": 2522,
        "fields": {
            "EDIT_FORM_LABEL": {"en": "Conversation Health"},
            "LIST_COLUMN_LABEL": {"en": "Conversation Health"},
            "LIST_FILTER_LABEL": {"en": "Conversation Health"},
            "SHOW_IN_LIST": "Y",
            "EDIT_IN_LIST": "Y",
            "SETTINGS": {
                "DISPLAY": "UI",
                "LIST_HEIGHT": 1,
                "CAPTION_NO_VALUE": "Not classified",
                "SHOW_NO_VALUE": "Y",
            },
        },
    },
)
print("userfield.update", upd.get("result"), upd.get("error"), upd.get("error_description"))

FIELD = "UF_CRM_CONVERSATION_HEALTH"
SECTION = {
    "name": "a7_conversation_health",
    "title": "Conversation Health",
    "type": "section",
    "elements": [{"name": FIELD, "optionFlags": "0"}],
}

for extras in ({}, {"leadCustomerType": 1}, {"leadCustomerType": 2}):
    get_payload = {"scope": "C"}
    if extras:
        get_payload["extras"] = extras
    cfg = call("crm.lead.details.configuration.get", get_payload)
    data = cfg.get("result")
    if data is None:
        print("skip config (null)", extras)
        continue
    # Drop old copy of our section / field wherever it sits, then prepend section.
    cleaned = []
    for sec in data:
        elems = [
            e
            for e in (sec.get("elements") or [])
            if e.get("name") != FIELD
        ]
        if sec.get("name") == SECTION["name"]:
            continue
        cleaned.append({**sec, "elements": elems})
    new_data = [SECTION] + cleaned
    set_payload = {"scope": "C", "data": new_data}
    if extras:
        set_payload["extras"] = extras
    sett = call("crm.lead.details.configuration.set", set_payload)
    print("configuration.set", extras or "default", sett.get("result"), sett.get("error"), sett.get("error_description"))

# Force common card for everyone so personal layouts don't hide it
force = call("crm.lead.details.configuration.forceCommonScopeForAll", {})
print("forceCommonScopeForAll", force.get("result"), force.get("error"), force.get("error_description"))

# Re-check lead value + whether field appears in get config
check = call(
    "crm.lead.details.configuration.get",
    {"scope": "C"},
)
names = []
for sec in check.get("result") or []:
    for e in sec.get("elements") or []:
        names.append(e.get("name"))
print("field_on_card", FIELD in names)
print("section_titles", [s.get("title") for s in (check.get("result") or [])][:6])
lead = call("crm.lead.get", {"id": 71863, "select": ["ID", "UF_CRM_CONVERSATION_HEALTH"]})
print("lead_health", (lead.get("result") or {}).get("UF_CRM_CONVERSATION_HEALTH"))
PY
)

# Push + run on VPS (Python has clean JSON; local PowerShell quoting is hostile).
printf '%s\n' "$REMOTE_PY" | "${SSH[@]}" "$HOST" "cat > /tmp/add_health_form.py"
"${SSH[@]}" "$HOST" "BITRIX_BASE=$(printf '%q' "$BASE") python3 /tmp/add_health_form.py"
