#!/usr/bin/env bash
# Push All-chats / LID-phone / soft-remove sources, enable RESOLVE_LID_TO_PHONE, no-cache rebuild.
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

SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "pushing sources…"
# Paths relative to openwa/ so they land correctly under OpenWA/
tar -cf - -C "$ROOT/openwa" \
  docker-compose.yml \
  src/modules/session/entities/session.entity.ts \
  src/database/migrations/1786400000000-AddSessionRemovedAt.ts \
  src/modules/session/session-engine-controls.ts \
  src/modules/session/session.service.ts \
  src/modules/session/session-engine-lifecycle.service.ts \
  src/modules/session/session.controller.ts \
  src/modules/session/dto/session-response.dto.ts \
  src/modules/session/chat-list-overlay.ts \
  src/modules/session/message-row.mapper.ts \
  src/modules/message/message.service.ts \
  dashboard/src/utils/chatFilters.ts \
  dashboard/src/services/api.ts \
  dashboard/src/components/chats/ChatSidebar.tsx \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/pages/Chats.css \
  dashboard/src/pages/Sessions.tsx \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && echo push-ok"

echo "rebuilding openwa-api (no cache)…"
"${SSH[@]}" "$HOST" "cd $OPENWA_DIR && bash -s" <<'REMOTE'
set -euo pipefail
grep -q 'getAllChats' src/modules/session/session.service.ts
grep -q 'enrichLidChatNames' src/modules/session/session.service.ts
grep -q 'ALL_CHATS_SESSION_ID' dashboard/src/components/chats/ChatSidebar.tsx
grep -q 'senderPhone' src/modules/session/message-row.mapper.ts
grep -q 'displayNameForStoredChat' src/modules/session/chat-list-overlay.ts
echo "source-markers=ok"

# env_file is read on container create — set the flag before force-recreate.
if grep -q '^RESOLVE_LID_TO_PHONE=' .env 2>/dev/null; then
  sed -i 's/^RESOLVE_LID_TO_PHONE=.*/RESOLVE_LID_TO_PHONE=true/' .env
else
  printf '\nRESOLVE_LID_TO_PHONE=true\n' >> .env
fi
grep -q '^RESOLVE_LID_TO_PHONE=true$' .env
echo "resolve-lid-env=ok"

docker compose build --no-cache openwa-api
echo "build-ok"
docker compose up -d --force-recreate openwa-api
echo "recreate-ok"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo "readiness=$code"
docker compose exec -T openwa-api node -e 'console.log("resolve-lid-runtime="+(process.env.RESOLVE_LID_TO_PHONE||""))'
docker compose ps --format '{{.Service}} {{.State}} {{.Status}}'
REMOTE
