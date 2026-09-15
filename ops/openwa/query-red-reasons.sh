#!/usr/bin/env bash
# List RED Conversation Health rows + Bitrix AI Monitor reason (if present).
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=25 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

# Push helper into container via stdin execute
tar -cf - -C "$ROOT/ops/openwa" query-red-health.js \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && docker compose cp query-red-health.js openwa-api:/tmp/query-red-health.js && docker compose exec -T openwa-api node /tmp/query-red-health.js"

echo "=== bitrix monitor snippets ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
BASE=$(grep -E '^BITRIX_WEBHOOK_BASE=' .env | head -1 | cut -d= -f2- | tr -d '\r')
HEALTH=$(grep -E '^BITRIX_HEALTH_FIELD=' .env | head -1 | cut -d= -f2- | tr -d '\r')
MONITOR=$(grep -E '^BITRIX_AI_MONITOR_FIELD=' .env | head -1 | cut -d= -f2- | tr -d '\r')
HEALTH=${HEALTH:-UF_CRM_CONVERSATION_HEALTH}
MONITOR=${MONITOR:-UF_CRM_AI_MONITOR}
test -n "$BASE"

# Enum id for red
RED_ENUM=2307

# Pull Owner Data items with red colour (SPA 1042) — filter client-side
python3 - <<PY
import json, os, urllib.request, urllib.parse

base = os.environ.get("BASE") or """$BASE""".rstrip("/")
health = """$HEALTH"""
monitor = """$MONITOR"""
red = """$RED_ENUM"""

def call(method, params=None):
    url = f"{base}/{method}.json"
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)

# Owner Data list
start = 0
rows = []
while True:
    res = call("crm.item.list", {
        "entityTypeId": "1042",
        "select[0]": "id",
        "select[1]": "title",
        f"select[2]": health,
        f"select[3]": monitor,
        f"filter[{health}]": red,
        "start": str(start),
    })
    batch = res.get("result", {}).get("items") or res.get("result") or []
    if isinstance(batch, dict):
        batch = batch.get("items") or []
    rows.extend(batch)
    nxt = res.get("next")
    if nxt is None:
        break
    start = int(nxt)
    if len(rows) > 200:
        break

print(f"owner_data_red={len(rows)}")
reasons = []
for it in rows[:40]:
    mid = it.get(monitor) or it.get(monitor.lower()) or ""
    title = it.get("title") or ""
    iid = it.get("id")
    text = str(mid).replace("\n", " | ")[:280]
    print(f"OD#{iid} | {title[:40]} | {text}")
    if text:
        reasons.append(text)

# Also classic leads if any
start = 0
leads = []
while True:
    res = call("crm.lead.list", {
        "select[]": "ID",
        "select[]": "TITLE",
        "select[]": health,
        "select[]": monitor,
        f"filter[{health}]": red,
        "start": str(start),
    })
    # crm.lead.list uses different select encoding — retry simpler
    break

print("--- reason themes (from monitor field) ---")
PY
REMOTE
