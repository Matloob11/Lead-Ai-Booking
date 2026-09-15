#!/usr/bin/env bash
# Trigger POST /api/conversation-health/backfill on the live OpenWA API (admin master key).
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
OPENWA_DIR="/opt/openwa-trial/OpenWA"
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "enqueueing conversation-health backfill…"
"${SSH[@]}" "$HOST" \
  "cd '$OPENWA_DIR' && \
   KEY=\$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d '\\r') && \
   curl -sS -m 120 -X POST http://127.0.0.1:2785/api/conversation-health/backfill \
     -H \"X-API-Key: \$KEY\" -H 'Content-Type: application/json'"
echo
