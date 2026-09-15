#!/usr/bin/env bash
# Read-only look at Linked-phones 500s + QR load. Does not change sessions.
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
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "=== nginx 500 URIs (no bodies) ==="
"${SSH[@]}" "$HOST" "awk '\$9==500 {print \$7}' /var/log/nginx/a7-openwa.access.log 2>/dev/null | tail -30 | sort | uniq -c | sort -nr | head -20"

echo "=== openwa error lines ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose logs openwa-api --tail 800 --no-log-prefix" \
  | grep '"level":"error"' | tail -20

echo "=== pids / ready ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c 'echo pids=\$(ps aux | wc -l); curl -sS -o /dev/null -w ready=%{http_code} http://127.0.0.1:2785/api/health/ready'"
