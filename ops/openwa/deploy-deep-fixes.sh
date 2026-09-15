#!/usr/bin/env bash
# Deploy OpenWA deep fixes: false-RED reclassify, health labels, login polish.
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

echo "=== 1) push ==="
tar -cf - -C "$ROOT/openwa" \
  src/modules/conversation-health/conversation-health.constants.ts \
  src/modules/conversation-health/conversation-health.enqueue.service.ts \
  src/modules/conversation-health/conversation-health.service.ts \
  src/modules/conversation-health/conversation-health.controller.ts \
  dashboard/src/services/api.ts \
  dashboard/src/components/ConversationHealthPanel.tsx \
  dashboard/src/components/ConversationHealthPanel.css \
  dashboard/src/i18n/locales/en.json \
  dashboard/src/pages/Login.css \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q reclassify_chat src/modules/conversation-health/conversation-health.constants.ts && \
      grep -q reclassify-false-red src/modules/conversation-health/conversation-health.controller.ts && \
      grep -q reclassifyFalseRed dashboard/src/services/api.ts && \
      echo deep-fixes-push-ok"

echo "=== 2) rebuild + recreate ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -25 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -12 && echo RECREATE_DONE"

echo "=== 3) prove ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
code=000
for i in $(seq 1 50); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo "readiness=$code"
test "$code" = "200"
docker compose exec -T openwa-api sh -c '
  grep -rq reclassify-false-red /app/dist && \
  grep -rq reclassifyFalseRed /app/dashboard/dist && \
  grep -rq "Re-check false RED" /app/dashboard/dist && \
  echo deep-fixes-ok
'
REMOTE

echo "DEPLOY_OK"
