#!/usr/bin/env bash
# Create Bitrix enumeration field Conversation Health on Lead (Phase 1).
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

"${SSH[@]:-}" 2>/dev/null || true
ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$HOST" bash -s -- "$BASE" <<'REMOTE'
set -euo pipefail
BASE="${1%/}"
# List existing UF fields; skip create if already present.
list=$(curl -sS -m 40 "$BASE/crm.lead.userfield.list.json")
echo "$list" | grep -q 'CONVERSATION_HEALTH' && {
  echo "field-exists=UF_CRM_CONVERSATION_HEALTH"
  echo "$list" | python3 -c 'import sys,json; d=json.load(sys.stdin); 
fields=d.get("result") or [];
hits=[f for f in fields if "CONVERSATION_HEALTH" in str(f.get("FIELD_NAME","")) or "CONVERSATION_HEALTH" in str(f.get("XML_ID",""))];
print("match", hits[0].get("FIELD_NAME") if hits else "none", "id", hits[0].get("ID") if hits else "")' 2>/dev/null || true
  exit 0
}

payload='{"fields":{"FIELD_NAME":"CONVERSATION_HEALTH","EDIT_FORM_LABEL":{"en":"Conversation Health"},"LIST_COLUMN_LABEL":{"en":"Conversation Health"},"LIST_FILTER_LABEL":{"en":"Conversation Health"},"USER_TYPE_ID":"enumeration","XML_ID":"CONVERSATION_HEALTH","MULTIPLE":"N","MANDATORY":"N","SHOW_FILTER":"Y","SHOW_IN_LIST":"Y","EDIT_IN_LIST":"Y","IS_SEARCHABLE":"N","SETTINGS":{"DISPLAY":"LIST","LIST_HEIGHT":5},"LIST":[{"VALUE":"RED","XML_ID":"red","SORT":100,"DEF":"N"},{"VALUE":"PINK","XML_ID":"pink","SORT":200,"DEF":"N"},{"VALUE":"YELLOW","XML_ID":"yellow","SORT":300,"DEF":"N"},{"VALUE":"WHITE","XML_ID":"white","SORT":400,"DEF":"N"},{"VALUE":"GREEN","XML_ID":"green","SORT":500,"DEF":"N"}]}}'
echo "creating-field…"
resp=$(curl -sS -m 40 -X POST "$BASE/crm.lead.userfield.add.json" -H 'Content-Type: application/json' -d "$payload")
echo "$resp"
echo "$resp" | grep -q '"error"' && exit 1
echo "field-created=UF_CRM_CONVERSATION_HEALTH"
REMOTE
