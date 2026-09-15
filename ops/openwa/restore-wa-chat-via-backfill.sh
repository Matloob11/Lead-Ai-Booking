#!/usr/bin/env bash
# After UF recreate wiped values: re-pin form section + enqueue OpenWA health backfill.
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPENWA_DIR="/opt/openwa-trial/OpenWA"

KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
: "${BITRIX_WEBHOOK_BASE:?BITRIX_WEBHOOK_BASE missing}"

echo "=== 1) re-pin Conversation Health section on lead card ==="
tar -cf - -C "$ROOT" ops/openwa/fix-lead-form-ui.py \
  | "${SSH[@]}" "$HOST" "cd /tmp && tar -xf - && BITRIX_WEBHOOK_BASE=$(printf %q "$BITRIX_WEBHOOK_BASE") python3 ops/openwa/fix-lead-form-ui.py --fix"

echo "=== 2) enqueue conversation-health backfill ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
KEY=$(grep -E '^API_KEYS=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" | cut -d, -f1)
test -n "$KEY"
echo -n summary_before=
curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary
echo
echo -n backfill=
curl -sS -m 180 -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  http://127.0.0.1:2785/api/conversation-health/backfill
echo
REMOTE

echo "=== 3) sample lead check (may still be empty until queue drains) ==="
tar -cf - -C "$ROOT" ops/openwa/inspect-wa-chat-field.py \
  | "${SSH[@]}" "$HOST" "cd /tmp && tar -xf - && BITRIX_WEBHOOK_BASE=$(printf %q "$BITRIX_WEBHOOK_BASE") python3 ops/openwa/inspect-wa-chat-field.py 71945 71909 71967" || true

echo "RESTORE_TRIGGERED"
