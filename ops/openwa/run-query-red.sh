#!/usr/bin/env bash
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

echo "=== sqlite red ==="
cat "$ROOT/ops/openwa/query-red-health.js" | "${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api node"

echo "=== bitrix reasons ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
BASE=$(grep -E '^BITRIX_WEBHOOK_BASE=' .env | head -1 | cut -d= -f2- | tr -d '\r"')
MONITOR=$(grep -E '^BITRIX_AI_MONITOR_FIELD=' .env | head -1 | cut -d= -f2- | tr -d '\r"' || true)
MONITOR=${MONITOR:-UF_CRM_AI_MONITOR}
OWNER=$(grep -E '^BITRIX_OWNER_DATA_TYPE_ID=' .env | head -1 | cut -d= -f2- | tr -d '\r"' || true)
OWNER=${OWNER:-1042}
export BASE MONITOR OWNER

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

docker compose exec -T openwa-api node >"$TMP" <<'NODE'
const Database=require('better-sqlite3');
const db=new Database(process.env.DATABASE_NAME||'/app/data/openwa.sqlite',{readonly:true});
for (const r of db.prepare("SELECT bitrixLeadId, bitrixEntityType, phone, chatName FROM chat_leads WHERE colour='red'").all()) {
  console.log([r.bitrixLeadId, r.bitrixEntityType||'lead', r.phone||'', (r.chatName||'').replace(/\|/g,'/')].join('|'));
}
NODE

python3 - "$TMP" <<'PY'
import json, os, urllib.parse, urllib.request, sys
from collections import Counter

base = os.environ["BASE"].rstrip("/")
monitor = os.environ["MONITOR"]
owner = os.environ["OWNER"]
path = sys.argv[1]
lines = open(path, encoding="utf-8", errors="replace").read().strip().splitlines()

def bx(method, params):
    url = f"{base}/{method}.json"
    data = urllib.parse.urlencode(params, doseq=True).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)

print(f"fetching={len(lines)}")
themes = Counter()
buckets = Counter()
for line in lines:
    parts = line.split("|", 3)
    if len(parts) < 2:
        continue
    while len(parts) < 4:
        parts.append("")
    lid, entity, phone, name = parts[:4]
    reason = ""
    try:
        if "DYNAMIC" in entity.upper() or entity == owner:
            res = bx("crm.item.get", {"entityTypeId": owner, "id": lid})
            item = (res.get("result") or {}).get("item") or {}
        else:
            res = bx("crm.lead.get", {"id": lid})
            item = res.get("result") or {}
        text = item.get(monitor) or ""
        if not text:
            for k, v in item.items():
                if isinstance(v, str) and ("Reason:" in v or "AI Monitor" in v or "monitor" in k.lower()):
                    text = v
                    break
        for ln in str(text).splitlines():
            if ln.strip().lower().startswith("reason:"):
                reason = ln.split(":", 1)[1].strip()
                break
        if not reason:
            reason = str(text).strip().splitlines()[0][:200] if str(text).strip() else "(empty monitor)"
    except Exception as e:
        reason = f"ERR {e}"
    print(f"{phone or '-'} | {name[:36]} | {reason}")
    themes[reason[:100]] += 1
    low = reason.lower()
    if any(w in low for w in ("outside", "personal", "private", "bypass", "off the book", "direct deal", "without company", "commission cut")):
        buckets["agent trying deal outside company"] += 1
    elif "empty monitor" in low or low.startswith("err "):
        buckets["no reason readable"] += 1
    else:
        buckets["other / see line"] += 1

print("--- repeated reasons ---")
for k, v in themes.most_common(12):
    print(f"{v}x | {k}")
print("--- buckets ---")
for k, v in buckets.most_common():
    print(f"{v}x | {k}")
PY
REMOTE
