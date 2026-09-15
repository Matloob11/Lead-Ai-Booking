#!/usr/bin/env bash
# Prove Conversation Health + timeline comment on a lead (default: RED sample from phase1).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

LEAD_ID="${1:-71863}"
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

echo "=== lead.get $LEAD_ID ==="
"${SSH[@]}" "$HOST" "curl -sS -m 30 -G '${BASE}/crm.lead.get.json' \
  --data-urlencode 'id=${LEAD_ID}' \
  --data-urlencode 'select[]=ID' \
  --data-urlencode 'select[]=TITLE' \
  --data-urlencode 'select[]=UF_CRM_CONVERSATION_HEALTH'"

echo
echo "=== timeline comments (first page) ==="
"${SSH[@]}" "$HOST" "curl -sS -m 30 -X POST '${BASE}/crm.timeline.comment.list.json' \
  -H 'Content-Type: application/json' \
  -d '{\"filter\":{\"ENTITY_ID\":${LEAD_ID},\"ENTITY_TYPE\":\"lead\"},\"order\":{\"ID\":\"DESC\"},\"start\":0}'"
echo
