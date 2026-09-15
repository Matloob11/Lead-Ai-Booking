#!/usr/bin/env bash
# Force OpenWA image rebuild without cache, then recreate the API container.
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"

ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" \
  "$HOST" "cd $OPENWA_DIR && bash -s" <<'REMOTE'
set -euo pipefail
test -f dashboard/src/utils/chatMessages.ts
grep -q "on-demand media reload" dashboard/src/utils/chatMessages.ts
echo "source-ok"
# Bust any stale builder cache for the dashboard change
docker compose build --no-cache openwa-api
echo "build-ok"
docker compose up -d --force-recreate openwa-api
echo "recreate-ok"
sleep 12
docker compose ps --format '{{.Service}} {{.State}} {{.Status}}'
REMOTE
