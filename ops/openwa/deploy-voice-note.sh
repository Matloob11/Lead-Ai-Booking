#!/usr/bin/env bash
# Push Linked-phones voice-note UI and copy the built SPA into the *running*
# openwa-api container. Does not recreate the container and does not restart
# Chromium sessions.
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

echo "=== 1) push dashboard sources ==="
tar -cf - -C "$ROOT/openwa" \
  dashboard/src/components/chats/ChatComposer.tsx \
  dashboard/src/services/api.ts \
  dashboard/src/pages/Chats.css \
  dashboard/src/a7-glass-embedded.css \
  dashboard/src/i18n/locales \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q voiceTitle dashboard/src/components/chats/ChatComposer.tsx && \
      grep -q convertVoice dashboard/src/services/api.ts && \
      grep -q voice-rec dashboard/src/pages/Chats.css && \
      echo voice-note-push-ok"

echo "=== 2) build SPA in a throwaway Node container (openwa-api stays up) ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker run --rm \
  -v '$OPENWA_DIR:/src' -w /src/dashboard node:20-bookworm \
  bash -lc 'npm ci && npm run build' 2>&1 | tail -30 && \
  test -f dashboard/dist/index.html && echo DASHBOARD_BUILD_OK"

echo "=== 3) serve host-built SPA via nginx — openwa-api stays running ==="
tar -cf - -C "$ROOT/openwa" a7/nginx-a7-openwa.conf \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      test -f dashboard/dist/index.html && \
      test -f a7/nginx-a7-openwa.conf && \
      conf=\$(grep -l 'listen 2786' /etc/nginx/conf.d/*.conf | head -1) && \
      test -n \"\$conf\" && cp -a \"\$conf\" \"\$conf.bak.voice\" && \
      cp a7/nginx-a7-openwa.conf \"\$conf\" && \
      nginx -t && systemctl reload nginx && \
      echo nginx-overlay=\$conf && \
      grep -q convert/voice dashboard/dist/assets/*.js && \
      echo voice-note-bundle=ok && \
      cid=\$(docker compose ps -q openwa-api) && \
      docker inspect --format 'openwa={{.State.Status}} started={{.State.StartedAt}}' \"\$cid\""

echo "DEPLOY_OK"
