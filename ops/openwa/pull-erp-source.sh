#!/usr/bin/env bash
# Pull Frappe/ERPNext app source from Hostinger VPS to local Desktop folder.
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
DEST="${1:-}"
if [[ -n "${ERP_DEST:-}" ]]; then
  DEST="$ERP_DEST"
fi
if [[ -z "$DEST" ]]; then
  if [[ -d /mnt/c/Users/Matloob/Desktop ]]; then
    DEST="/mnt/c/Users/Matloob/Desktop/sheikhmahboob-erp"
  else
    DEST="/c/Users/Matloob/Desktop/sheikhmahboob-erp"
  fi
fi

KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
  case "$DEST" in
    [A-Za-z]:/*|[A-Za-z]:\\*) DEST=$(wslpath -u "$DEST") ;;
  esac
fi
# Normalize Windows DEST for Git Bash / MSYS when not already /mnt/c
case "$DEST" in
  /mnt/*) ;;
  [A-Za-z]:/*|[A-Za-z]:\\*)
    drive=$(echo "${DEST:0:1}" | tr 'A-Z' 'a-z')
    rest="${DEST:2}"
    rest="${rest//\\//}"
    DEST="/${drive}${rest}"
    ;;
esac

mkdir -p "$DEST"
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=30 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "=== pulling ERP source -> $DEST ==="
# apps = real source (frappe, erpnext, di). Skip env/node_modules junk.
"${SSH[@]}" "$HOST" "cd /home/frappe/frappe-bench && tar -cf - \
  --exclude='*/__pycache__' \
  --exclude='*.pyc' \
  --exclude='*/node_modules' \
  --exclude='*/.pyc' \
  apps \
  sites/apps.txt \
  sites/apps.json \
  sites/common_site_config.json \
  Procfile \
  config 2>/dev/null" \
  | tar -xf - -C "$DEST"

# README so Matloob knows what this is
cat > "$DEST/README.txt" <<EOF
Sheikh Mahboob ERP (Frappe / ERPNext) — source copy from Hostinger VPS
Pulled: $(date -Is 2>/dev/null || date)
Server path: /home/frappe/frappe-bench
Live site: https://sheikhmahboob.com

Contents:
  apps/frappe     - Frappe framework
  apps/erpnext    - ERPNext
  apps/di         - custom app
  sites/apps.*    - installed apps list
  config/         - bench nginx/supervisor config templates (if present)
  Procfile

NOT included (on purpose):
  env/            - Python virtualenv (recreate with bench)
  sites/*/        - site data, files, DB credentials
  MariaDB dump    - ask if you need a DB backup separately
EOF

echo "=== sizes ==="
du -sh "$DEST" "$DEST/apps"/* 2>/dev/null || true
ls -la "$DEST" "$DEST/apps"
echo "PULL_OK"
