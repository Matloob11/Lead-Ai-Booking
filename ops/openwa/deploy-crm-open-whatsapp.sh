#!/usr/bin/env bash
# Deploy CRM tab dual buttons + OpenWA ?phone= deep link.
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

echo "=== 2) push OpenWA sources ==="
tar -cf - -C "$ROOT/openwa" \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/pages/Login.tsx \
  dashboard/src/main.tsx \
  dashboard/src/components/chats/NewContactModal.tsx \
  dashboard/src/utils/chatFilters.ts \
  dashboard/src/utils/chatFilters.test.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q chatMatchesPhone dashboard/src/utils/chatFilters.ts && \
      grep -q openwa_open_phone dashboard/src/pages/Chats.tsx && \
      grep -q initialPhone dashboard/src/components/chats/NewContactModal.tsx && \
      echo openwa-push-ok"

echo "=== 3) rebuild openwa-api (bundles dashboard) ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -15 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -10 && echo RECREATE_DONE"

echo "=== 4) ready + prove ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && code=000; for i in \$(seq 1 40); do code=\$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true); test \"\$code\" = 200 && break; sleep 3; done; echo readiness=\$code; test \"\$code\" = 200"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c 'grep -rq openwa_open_phone /app/dashboard/dist && echo deeplink-bundle=ok'"

echo "=== 5) panel file checksums ==="
bash "$ROOT/ops/wa.sh" sum /opt/a7-wa/panel/crm/crm-tab.js
bash "$ROOT/ops/wa.sh" sum /opt/a7-wa/panel/crm/crm-tab.css

echo "DEPLOY_OK"
