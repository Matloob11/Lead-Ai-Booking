#!/usr/bin/env bash
# Admin-only Conversation Health + password-gated RED→GREEN allow.
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
  src/modules/conversation-health/entities/chat-lead.entity.ts \
  src/modules/conversation-health/conversation-health.service.ts \
  src/modules/conversation-health/conversation-health.controller.ts \
  src/modules/auth/global-route-fence-coverage.spec.ts \
  src/database/migrations/1786800000000-AddChatLeadColourLocked.ts \
  src/database/migrations/__tests__/1786800000000-AddChatLeadColourLocked.spec.ts \
  dashboard/src/components/ConversationHealthPanel.tsx \
  dashboard/src/components/ConversationHealthPanel.css \
  dashboard/src/components/Layout.tsx \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/services/api.ts \
  dashboard/src/i18n/locales/en.json \
  .env.example \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q allowRedAsGreen src/modules/conversation-health/conversation-health.service.ts && \
      grep -q allow-green src/modules/conversation-health/conversation-health.controller.ts && \
      grep -q colourLocked src/modules/conversation-health/entities/chat-lead.entity.ts && \
      grep -q allowAsGreen dashboard/src/components/ConversationHealthPanel.tsx && \
      grep -q allow-green src/modules/conversation-health/conversation-health.controller.ts && \
      echo push-ok"

echo "=== 2) env password ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
if grep -q '^CONVERSATION_HEALTH_OVERRIDE_PASSWORD=' .env; then
  sed -i 's/^CONVERSATION_HEALTH_OVERRIDE_PASSWORD=.*/CONVERSATION_HEALTH_OVERRIDE_PASSWORD=222007/' .env
else
  printf '\nCONVERSATION_HEALTH_OVERRIDE_PASSWORD=222007\n' >> .env
fi
grep -q '^CONVERSATION_HEALTH_OVERRIDE_PASSWORD=222007$' .env && echo env-password-ok
REMOTE

echo "=== 3) rebuild + recreate ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -25 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -12 && echo RECREATE_DONE"

echo "=== 4) prove ==="
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
  grep -rq allow-green /app/dist && \
  grep -rq colourLocked /app/dist && \
  grep -rq allowAsGreen /app/dashboard/dist && \
  grep -rq Allow.as.green /app/dashboard/dist && \
  echo bundle-ok
'

docker compose exec -T openwa-api node -e '
const Database=require("better-sqlite3");
const db=new Database(process.env.DATABASE_NAME||"/app/data/openwa.sqlite",{readonly:true});
const cols=db.prepare("PRAGMA table_info(chat_leads)").all().map(c=>c.name);
if(!cols.includes("colourLocked")){ console.error("colourLocked=MISSING"); process.exit(1); }
console.log("colourLocked=ok");
'

PASS=$(docker compose exec -T openwa-api printenv CONVERSATION_HEALTH_OVERRIDE_PASSWORD | tr -d "\r")
echo "override_password_set=$([ -n \"$PASS\" ] && echo yes || echo no)"
test -n "$PASS"
REMOTE

echo "DEPLOY_OK"
