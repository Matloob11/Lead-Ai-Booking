#!/usr/bin/env bash
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

tar -cf - -C "$ROOT/openwa" src/modules/conversation-health/conversation-health.service.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && grep -q ForbiddenException src/modules/conversation-health/conversation-health.service.ts && echo push-ok"

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose build openwa-api 2>&1 | tail -12 && docker compose up -d --force-recreate openwa-api 2>&1 | tail -10"

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
for i in $(seq 1 40); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo readiness=$code
test "$code" = "200"
docker compose exec -T openwa-api sh -c 'grep -rq ForbiddenException /app/dist/modules/conversation-health && echo forbid-ok'
docker compose exec -T openwa-api node -e '
const Database=require("better-sqlite3");
const db=new Database(process.env.DATABASE_NAME||"/app/data/openwa.sqlite",{readonly:true});
const cols=db.prepare("PRAGMA table_info(chat_leads)").all().map(c=>c.name);
console.log("colourLocked="+cols.includes("colourLocked"));
'
docker compose exec -T openwa-api printenv CONVERSATION_HEALTH_OVERRIDE_PASSWORD | tr -d "\r" | sed "s/./*/g" | awk "{print \"password_len=\" length(\$0)}"
REMOTE
