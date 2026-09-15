#!/usr/bin/env bash
# Install a VPS cron that keeps Owner Data kanban Amount (AED) in sync with
# Lease/Selling Price UFs — so new New-Availability cards get a non-zero total.
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_DIR="/opt/a7-wa/ops/openwa"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "=== 1) install sync scripts ==="
tar -cf - -C "$ROOT" \
  ops/openwa/fix-owner-data-kanban-amounts.py \
  ops/openwa/run-owner-data-amount-sync.sh \
  | "${SSH[@]}" "$HOST" "mkdir -p '$DEST_DIR' && cd /tmp && tar -xf - && \
      cp -f ops/openwa/fix-owner-data-kanban-amounts.py ops/openwa/run-owner-data-amount-sync.sh '$DEST_DIR/' && \
      chmod 755 '$DEST_DIR/fix-owner-data-kanban-amounts.py' '$DEST_DIR/run-owner-data-amount-sync.sh' && \
      ls -la '$DEST_DIR' && echo script-ok"

echo "=== 2) crontab every 15 minutes ==="
"${SSH[@]}" "$HOST" 'CRON_LINE="*/15 * * * * /opt/a7-wa/ops/openwa/run-owner-data-amount-sync.sh"; \
  (crontab -l 2>/dev/null | grep -v owner-data-amount-sync || true; echo "$CRON_LINE") | crontab -; \
  echo "crontab:"; crontab -l | grep owner-data-amount || true'

echo "=== 3) run once now ==="
"${SSH[@]}" "$HOST" "/opt/a7-wa/ops/openwa/run-owner-data-amount-sync.sh; tail -n 30 /var/log/owner-data-amount-sync.log"

echo "CRON_INSTALLED"
