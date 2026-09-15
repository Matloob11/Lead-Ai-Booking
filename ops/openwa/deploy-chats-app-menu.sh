#!/usr/bin/env bash
# Deploy pic-1 app menu: hide permanent sidebar, English-only, default Chats.
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

echo "=== 1) push sources ==="
tar -cf - -C "$ROOT/openwa" \
  dashboard/src/App.tsx \
  dashboard/src/a7-embedded.css \
  dashboard/src/hooks/useAppMenu.tsx \
  dashboard/src/components/Layout.tsx \
  dashboard/src/components/Layout.css \
  dashboard/src/components/chats/ChatSidebar.tsx \
  dashboard/src/components/chats/ChatThread.tsx \
  dashboard/src/components/chats/VoicePlayer.tsx \
  dashboard/src/components/chats/ChatVideo.tsx \
  dashboard/src/components/ConversationHealthPanel.tsx \
  dashboard/src/components/ConversationHealthPanel.css \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/pages/Chats.css \
  dashboard/src/pages/Login.tsx \
  dashboard/src/i18n/index.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      test -f dashboard/src/hooks/useAppMenu.tsx && \
      grep -q a7-menu-shell dashboard/src/components/Layout.tsx && \
      grep -q registerChatsActions dashboard/src/pages/Chats.tsx && \
      grep -q \"lng: 'en'\" dashboard/src/i18n/index.ts && \
      echo app-menu-push-ok"

echo "=== 2) rebuild ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -20 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -10 && echo RECREATE_DONE"

echo "=== 3) prove ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && code=000; for i in \$(seq 1 40); do code=\$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true); test \"\$code\" = 200 && break; sleep 3; done; echo readiness=\$code; test \"\$code\" = 200"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c 'grep -rq a7-app-menu /app/dashboard/dist && grep -rq Conversation.Health /app/dashboard/dist && echo app-menu-bundle=ok'"

echo "DEPLOY_OK"
