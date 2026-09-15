#!/usr/bin/env bash
# Deploy Omni-matching glass theme for Linked WhatsApp (panel shell + OpenWA embed).
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
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "=== 1) panel ==="
bash "$ROOT/ops/wa.sh" panel
"${SSH[@]}" "$HOST" "grep -q linked__glass-bg /opt/a7-wa/panel/assets/modules/inbox.js && grep -q linked__blob /opt/a7-wa/panel/assets/modules/inbox.css && echo panel-glass-ok"

echo "=== 2) push OpenWA glass CSS ==="
tar -cf - -C "$ROOT/openwa" \
  dashboard/src/main.tsx \
  dashboard/src/a7-embedded.css \
  dashboard/src/a7-glass-embedded.css \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      test -f dashboard/src/a7-glass-embedded.css && \
      grep -q a7-glass-embedded dashboard/src/main.tsx && \
      echo openwa-glass-push-ok"

echo "=== 3) rebuild ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -18 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -10 && echo RECREATE_DONE"

echo "=== 4) prove ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && code=000; for i in \$(seq 1 40); do code=\$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true); test \"\$code\" = 200 && break; sleep 3; done; echo readiness=\$code; test \"\$code\" = 200"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c 'grep -rq liquid-glass /app/dashboard/dist || grep -rq 0a1020 /app/dashboard/dist; grep -rq a7-glass /app/dashboard/dist/assets/*.js 2>/dev/null || true; grep -rq \"37d39b\" /app/dashboard/dist && echo glass-bundle=ok'"

echo "DEPLOY_OK"
