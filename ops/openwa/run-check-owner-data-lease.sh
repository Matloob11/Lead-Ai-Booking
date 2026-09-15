#!/usr/bin/env bash
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
tar -cf - -C "$ROOT" ops/openwa/check-owner-data-lease-filled.py \
  | "${SSH[@]}" "$HOST" "cd /tmp && tar -xf - && BITRIX_WEBHOOK_BASE=$(printf %q "$BITRIX_WEBHOOK_BASE") python3 ops/openwa/check-owner-data-lease-filled.py"
