#!/usr/bin/env bash
# Deploy OpenWA UX batch: health legend/errors, false-RED guard, all-chats
# contact/profile, theme hide in embed, block confirm, empty-state copy.
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
  src/modules/conversation-health/openai-health.client.ts \
  dashboard/src/components/ConversationHealthPanel.tsx \
  dashboard/src/components/ConversationHealthPanel.css \
  dashboard/src/components/Layout.tsx \
  dashboard/src/components/chats/ContactProfilePanel.tsx \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/pages/Chats.css \
  dashboard/src/a7-glass-embedded.css \
  dashboard/src/i18n/locales/en.json \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q looksLikeCleanReason src/modules/conversation-health/openai-health.client.ts && \
      grep -q legendTitle dashboard/src/i18n/locales/en.json && \
      grep -q chp-legend dashboard/src/components/ConversationHealthPanel.tsx && \
      grep -q \"dataset.embedded\" dashboard/src/components/Layout.tsx && \
      echo ux-batch-push-ok"

echo "=== 2) rebuild + recreate ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -25 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -12 && echo RECREATE_DONE"

echo "=== 3) prove ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
code=000
for i in $(seq 1 45); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo "readiness=$code"
test "$code" = "200"
docker compose exec -T openwa-api sh -c '
  grep -rq looksLikeCleanReason /app/dist 2>/dev/null || grep -rq looksLikeCleanReason /app/src
  grep -rq chp-legend /app/dashboard/dist && \
  grep -rq redAllowHint /app/dashboard/dist && \
  echo ux-batch-ok
'
REMOTE

echo "DEPLOY_OK"
