#!/usr/bin/env bash
# List Bitrix lead STATUS_ID options + recent Phase1 monitor leads.
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

echo "=== crm.status.list ENTITY_ID=STATUS ==="
"${SSH[@]}" "$HOST" "curl -sS -m 40 -X POST '${BASE}/crm.status.list.json' -H 'Content-Type: application/json' -d '{\"filter\":{\"ENTITY_ID\":\"STATUS\"}}'"
echo
echo "=== crm.lead.list Phase1 source ==="
"${SSH[@]}" "$HOST" "curl -sS -m 40 -X POST '${BASE}/crm.lead.list.json' -H 'Content-Type: application/json' -d '{\"filter\":{\"SOURCE_DESCRIPTION\":\"Conversation Health Phase 1\"},\"select\":[\"ID\",\"TITLE\",\"STATUS_ID\",\"DATE_CREATE\",\"SOURCE_DESCRIPTION\"],\"order\":{\"ID\":\"DESC\"},\"start\":0}'"
echo
