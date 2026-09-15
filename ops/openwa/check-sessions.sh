#!/usr/bin/env bash
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -s" <<'REMOTE'
set -e
echo "=== /app/data ==="
ls -la /app/data 2>/dev/null | head -30 || echo no-data
echo "=== session folders ==="
ls /app/data/sessions 2>/dev/null | head -40 || echo no-sessions-dir
echo "=== db files ==="
ls -la /app/data/*.sqlite /app/data/*.db /app/data/*.sqlite3 2>/dev/null || echo no-sqlite
DB=""
for f in /app/data/openwa.sqlite /app/data/database.sqlite /app/data/data.sqlite /app/data/db.sqlite; do
  if [ -f "$f" ]; then DB="$f"; break; fi
done
if [ -z "$DB" ]; then
  DB=$(ls /app/data/*.sqlite 2>/dev/null | head -1 || true)
fi
echo "DB=$DB"
if [ -n "$DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".tables"
  sqlite3 "$DB" "SELECT name, status, phone FROM session LIMIT 25;" 2>/dev/null \
    || sqlite3 "$DB" "SELECT name, status, phone FROM sessions LIMIT 25;" 2>/dev/null \
    || echo "query-failed"
fi
echo "=== health ==="
curl -sS http://127.0.0.1:2785/api/health/ready || true
echo
REMOTE
