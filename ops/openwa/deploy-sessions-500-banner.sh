#!/usr/bin/env bash
# Push Sessions.tsx sticky HTTP-500 banner fix. Host-built SPA via nginx overlay.
# Does not recreate openwa-api.
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=25 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "=== 1) push Sessions.tsx ==="
tar -cf - -C "$ROOT/openwa" dashboard/src/pages/Sessions.tsx \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q 'setError(null)' dashboard/src/pages/Sessions.tsx && \
      echo sessions-tsx-push-ok"

echo "=== 2) build SPA (openwa-api stays up) ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker run --rm \
  -v '$OPENWA_DIR:/src' -w /src/dashboard node:20-bookworm \
  bash -lc 'if [ -d node_modules ]; then npm run build; else npm ci && npm run build; fi' 2>&1 | tail -40 && \
  grep -q setError.null dashboard/src/pages/Sessions.tsx && \
  test -f dashboard/dist/index.html && echo DASHBOARD_BUILD_OK"

echo "=== 3) prove overlay + API still up ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && \
  cid=\$(docker compose ps -q openwa-api) && \
  docker inspect --format 'openwa={{.State.Status}} started={{.State.StartedAt}}' \"\$cid\" && \
  grep -q 'alias /opt/openwa-trial/OpenWA/dashboard/dist/assets/' /etc/nginx/conf.d/a7-openwa.conf && \
  echo nginx-overlay=ok"

echo DEPLOY_OK
