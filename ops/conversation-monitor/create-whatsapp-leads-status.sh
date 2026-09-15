#!/usr/bin/env bash
# Create "WhatsApp Leads" kanban status (like New Lead / Assigned) and move
# Conversation Health Phase 1 leads out of NEW into it.
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
STATUS_ID="${BITRIX_WA_LEAD_STATUS:-UC_WA_LEADS}"

REMOTE_PY=$(cat <<'PY'
import json, os, ssl, urllib.request

base = os.environ["BITRIX_BASE"].rstrip("/")
wanted = os.environ["STATUS_ID"]
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

statuses = call("crm.status.list", {"filter": {"ENTITY_ID": "STATUS"}})
by_id = {s["STATUS_ID"]: s for s in (statuses.get("result") or [])}
by_name = {s["NAME"].strip().lower(): s for s in (statuses.get("result") or [])}

status = by_id.get(wanted) or by_name.get("whatsapp leads")
if status:
    status_id = status["STATUS_ID"]
    print(f"status_exists id={status_id} name={status['NAME']}")
else:
    added = call(
        "crm.status.add",
        {
            "fields": {
                "ENTITY_ID": "STATUS",
                "STATUS_ID": wanted,
                "NAME": "WhatsApp Leads",
                "SORT": 25,
                "COLOR": "#25D366",
            }
        },
    )
    if added.get("error"):
        raise SystemExit(f"crm.status.add failed: {added}")
    status_id = wanted
    print(f"status_created id={status_id} result={added.get('result')}")

# Move monitor-created leads still sitting in NEW
start = 0
moved = 0
ids = []
while True:
    page = call(
        "crm.lead.list",
        {
            "filter": {
                "SOURCE_DESCRIPTION": "Conversation Health Phase 1",
                "STATUS_ID": "NEW",
            },
            "select": ["ID", "TITLE", "STATUS_ID"],
            "order": {"ID": "ASC"},
            "start": start,
        },
    )
    rows = page.get("result") or []
    if not rows:
        break
    for row in rows:
        lid = row["ID"]
        upd = call("crm.lead.update", {"id": lid, "fields": {"STATUS_ID": status_id}})
        if upd.get("error"):
            print(f"FAIL update {lid}: {upd.get('error_description') or upd}")
            continue
        moved += 1
        ids.append(str(lid))
        print(f"moved lead={lid} -> {status_id}")
    if len(rows) < 50:
        break
    start += 50

print(f"moved_count={moved}")
print(f"status_id={status_id}")
# Prove one
if ids:
    got = call("crm.lead.get", {"id": ids[0], "select": ["ID", "STATUS_ID", "TITLE"]})
    print("prove", got.get("result"))
PY
)

printf '%s\n' "$REMOTE_PY" | "${SSH[@]}" "$HOST" "cat > /tmp/create_wa_status.py"
"${SSH[@]}" "$HOST" "BITRIX_BASE=$(printf '%q' "$BASE") STATUS_ID=$(printf '%q' "$STATUS_ID") python3 /tmp/create_wa_status.py"
