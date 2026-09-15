#!/usr/bin/env bash
# Inspect Bitrix lead 72122 + local chat_leads mapping (no secrets printed).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOST="root@187.127.123.235"
KEY="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
: "${BITRIX_WEBHOOK_BASE:?missing}"

ssh.exe -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 \
  -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$HOST" "cd /opt/openwa-trial/OpenWA && docker compose exec -T openwa-api node -e '
const Database=require(\"better-sqlite3\");
const db=new Database(\"./data/openwa.sqlite\",{readonly:true});
const rows=db.prepare(\"select sessionId, chatId, phone, colour, bitrixLeadId, substr(chatName,1,40) name from chat_leads where bitrixLeadId=?\") .all(\"72122\");
console.log(\"localByLead\", rows);
console.log(\"totals\", db.prepare(\"select count(*) c, sum(colour is not null) coloured from chat_leads\").get());
console.log(\"sampleColoured\", db.prepare(\"select bitrixLeadId, colour, phone from chat_leads where colour is not null order by updatedAt desc limit 8\").all());
'"

BASE="${BITRIX_WEBHOOK_BASE%/}"
python3 - <<PY
import json, urllib.request
base = ${BITRIX_WEBHOOK_BASE@json}.rstrip("/")
url = base + "/crm.lead.get.json?ID=72122"
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.load(r)
lead = data.get("result") or {}
keys = [
    "ID","TITLE","STATUS_ID","NAME",
    "UF_CRM_CONVERSATION_HEALTH","UF_CRM_AI_MONITOR","UF_CRM_WA_CHAT",
]
out = {k: lead.get(k) for k in keys}
phone = lead.get("PHONE")
out["PHONE"] = phone
print("bitrixLead", json.dumps(out, ensure_ascii=False)[:2000])
# timeline comments
tc = base + "/crm.timeline.comment.list.json"
req = urllib.request.Request(
    tc,
    data=json.dumps({"filter": {"ENTITY_ID": 72122, "ENTITY_TYPE": "lead"}, "order": {"ID": "DESC"}, "select": ["ID","COMMENT","CREATED"]}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as r:
    comments = json.load(r).get("result") or []
print("commentCount", len(comments))
for c in comments[:5]:
    text = (c.get("COMMENT") or "")[:160].replace("\n", " | ")
    print("comment", c.get("ID"), text)
PY
