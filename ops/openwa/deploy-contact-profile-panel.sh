#!/usr/bin/env bash
# Deploy OpenWA contact side panel (header click → right drawer + chat_profiles API).
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

echo "=== 1) push sources ==="
tar -cf - -C "$ROOT/openwa" \
  src/modules/conversation-health/entities/chat-profile.entity.ts \
  src/modules/conversation-health/chat-profile.service.ts \
  src/modules/conversation-health/chat-profile.controller.ts \
  src/modules/conversation-health/conversation-health.module.ts \
  src/database/migrations/1786700000000-CreateChatProfiles.ts \
  src/database/migrations/1786900000000-AddChatProfilePinned.ts \
  src/database/migrations/__tests__/1786700000000-CreateChatProfiles.spec.ts \
  src/database/migrations/__tests__/1786900000000-AddChatProfilePinned.spec.ts \
  dashboard/src/components/chats/ContactProfilePanel.tsx \
  dashboard/src/components/chats/ChatSidebar.tsx \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/pages/Chats.css \
  dashboard/src/services/api.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      test -f src/modules/conversation-health/chat-profile.controller.ts && \
      test -f dashboard/src/components/chats/ContactProfilePanel.tsx && \
      test -f src/database/migrations/1786900000000-AddChatProfilePinned.ts && \
      grep -q ContactProfilePanel dashboard/src/pages/Chats.tsx && \
      grep -q chatProfileApi dashboard/src/services/api.ts && \
      grep -q a7-cp__backdrop dashboard/src/pages/Chats.css && \
      grep -q AddChatProfilePinned1786900000000 src/database/migrations/1786900000000-AddChatProfilePinned.ts && \
      echo contact-profile-push-ok"

echo "=== 2) rebuild + recreate openwa-api ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -25 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -12 && echo RECREATE_DONE"

echo "=== 3) readiness + migration + bundle prove ==="
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
  grep -rq a7-cp__ /app/dashboard/dist && \
  grep -rq a7-cp__backdrop /app/dashboard/dist && \
  grep -rq a7-cp__quick /app/dashboard/dist && \
  grep -rq a7-cp__grid /app/dashboard/dist && \
  grep -rq Contact.info /app/dashboard/dist && \
  grep -rq chat-profiles /app/dist && \
  grep -rq "#008069" /app/dashboard/dist && \
  echo bundle-ok
'

docker compose exec -T openwa-api node -e '
const Database=require("better-sqlite3");
const db=new Database(process.env.DATABASE_NAME||"/app/data/openwa.sqlite",{readonly:true});
const has=db.prepare("SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"chat_profiles\"").get();
if(!has){ console.error("chat_profiles=MISSING"); process.exit(1); }
const cols=db.prepare("PRAGMA table_info(chat_profiles)").all().map(c=>c.name);
if(!cols.includes("pinned")){ console.error("pinned=MISSING cols="+cols.join(",")); process.exit(1); }
console.log("chat_profiles=ok cols="+cols.join(","));
'

KEY=$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d "\r")
# Pick any session+chat if present; otherwise just prove route exists (404/400 ok as long as not 404 for controller).
SID=$(docker compose exec -T openwa-api node -e '
const Database=require("better-sqlite3");
const db=new Database(process.env.DATABASE_NAME||"/app/data/openwa.sqlite",{readonly:true});
const row=db.prepare("SELECT sessionId, chatId FROM messages WHERE chatId NOT LIKE \"%@g.us\" ORDER BY timestamp DESC LIMIT 1").get();
if(!row){ process.stdout.write(""); process.exit(0); }
process.stdout.write(row.sessionId+"|"+row.chatId);
' | tr -d "\r")
if [ -n "$SID" ]; then
  SESSION="${SID%%|*}"
  CHAT="${SID#*|}"
  ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=\"\"))" "$CHAT")
  echo -n "profile-get="
  curl -sS -m 30 -H "X-API-Key: $KEY" \
    "http://127.0.0.1:2785/api/sessions/${SESSION}/chats/${ENC}/profile" | head -c 240
  echo
  echo -n "profile-patch="
  PATCH_BODY='{"displayName":"__probe_save__","notes":"probe"}'
  PATCH_CODE=$(curl -sS -m 30 -o /tmp/cp-patch.json -w '%{http_code}' \
    -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    -d "$PATCH_BODY" \
    "http://127.0.0.1:2785/api/sessions/${SESSION}/chats/${ENC}/profile" || true)
  echo "http=$PATCH_CODE body=$(head -c 180 /tmp/cp-patch.json)"
  test "$PATCH_CODE" = "200"
  # Clear probe name so we do not leave junk on a live chat.
  curl -sS -m 20 -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    -d '{"displayName":"","notes":""}' \
    "http://127.0.0.1:2785/api/sessions/${SESSION}/chats/${ENC}/profile" >/dev/null || true
  echo -n "names-get="
  curl -sS -m 20 -H "X-API-Key: $KEY" \
    "http://127.0.0.1:2785/api/sessions/${SESSION}/chat-profiles" | head -c 120
  echo
else
  echo "no-messages-to-probe-profile"
fi
docker compose --profile redis ps --format "{{.Service}} {{.State}} {{.Status}}" | head -10
REMOTE

echo "DEPLOY_OK"
