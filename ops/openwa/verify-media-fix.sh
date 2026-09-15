#!/usr/bin/env bash
# Confirm the media-merge source is on the server and the running image is the fresh no-cache build.
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"

ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" \
  "$HOST" 'cd /opt/openwa-trial/OpenWA && bash -s' <<'REMOTE'
set -euo pipefail
grep -q "on-demand media reload" dashboard/src/utils/chatMessages.ts && echo source-fix=present
IMG=$(docker compose images -q openwa-api)
echo image=$IMG
CREATED=$(docker image inspect -f '{{.Created}}' "$IMG")
echo created=$CREATED
# Dashboard dist must exist and be newer than the cold-backup timestamp window
DIST=$(docker compose exec -T openwa-api sh -c 'ls -la /app/dashboard/dist/assets/*.js 2>/dev/null | head -3')
echo "$DIST"
HEALTH=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
echo readiness=$HEALTH
REMOTE
