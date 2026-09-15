#!/usr/bin/env bash
# Inspect + try to surface UF_CRM_CONVERSATION_HEALTH on the lead card.
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
bx() {
  local method="$1"
  local data="${2:-}"
  if [[ -n "$data" ]]; then
    "${SSH[@]}" "$HOST" "curl -sS -m 40 -X POST '${BASE}/${method}.json' -H 'Content-Type: application/json' -d $(printf '%q' "$data")"
  else
    "${SSH[@]}" "$HOST" "curl -sS -m 40 '${BASE}/${method}.json'"
  fi
  echo
}

echo "=== userfield.list (Conversation Health) ==="
bx "crm.lead.userfield.list" '{"filter":{"FIELD_NAME":"UF_CRM_CONVERSATION_HEALTH"}}'

echo "=== lead.get select health ==="
bx "crm.lead.get" '{"id":71863,"select":["ID","TITLE","UF_CRM_CONVERSATION_HEALTH"]}'

echo "=== details.configuration.get (common) ==="
bx "crm.lead.details.configuration.get" '{"scope":"C","entityTypeId":1}' || true

echo "=== details.configuration.get (personal admin) ==="
bx "crm.lead.details.configuration.get" '{"scope":"P","userId":1,"entityTypeId":1}' || true
