#!/usr/bin/env bash
# Deploy Conversation Health Nest module + dashboard panel; wire Bitrix/OpenAI/Redis/queue; backfill.
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

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

: "${BITRIX_WEBHOOK_BASE:?BITRIX_WEBHOOK_BASE missing in root .env}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY missing in root .env}"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Snippet merged into remote openwa .env (never printed).
cat >"$TMP/conversation-health.env" <<EOF
QUEUE_ENABLED=true
REDIS_ENABLED=true
# Pin to OpenWA redis container — hostname "redis" also resolves to a7wa-redis on a7wa_default.
REDIS_HOST=openwa-redis
REDIS_PORT=6379
REDIS_BUILTIN=true
CONVERSATION_HEALTH_ENABLED=true
BITRIX_WEBHOOK_BASE=${BITRIX_WEBHOOK_BASE}
BITRIX_LEAD_URL_BASE=${BITRIX_LEAD_URL_BASE:-https://crm.a7grouprealestatedxb.com/crm/lead/details}
BITRIX_OWNER_DATA_TYPE_ID=${BITRIX_OWNER_DATA_TYPE_ID:-1042}
BITRIX_OWNER_DATA_URL_BASE=${BITRIX_OWNER_DATA_URL_BASE:-https:crm.a7grouprealestatedxb.com/crm/type/1042/de//tails}
BITRIX_WA_LEAD_STATUS=${BITRIX_WA_LEAD_STATUS:-UC_WA_LEADS}
BITRIX_HEALTH_FIELD=${BITRIX_HEALTH_FIELD:-UF_CRM_CONVERSATION_HEALTH}
BITRIX_AI_MONITOR_FIELD=${BITRIX_AI_MONITOR_FIELD:-UF_CRM_AI_MONITOR}
BITRIX_WA_CHAT_FIELD=${BITRIX_WA_CHAT_FIELD:-UF_CRM_WA_CHAT}
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_MODEL=${OPENAI_MODEL:-gpt-4o-mini}
EOF

echo "pushing sources + env snippet…"
tar -cf - -C "$ROOT/openwa" \
  docker-compose.yml \
  src/app.module.ts \
  src/config/env-precedence.ts \
  src/modules/queue/queue-names.ts \
  src/modules/queue/queue.module.ts \
  src/modules/session/session.module.ts \
  src/modules/session/message-projector.service.ts \
  src/modules/auth/global-route-fence-coverage.spec.ts \
  src/modules/conversation-health \
  src/database/migrations/1786500000000-CreateChatLeads.ts \
  src/database/migrations/1786600000000-AddChatLeadBitrixEntityType.ts \
  src/database/migrations/__tests__/1786500000000-CreateChatLeads.spec.ts \
  src/database/migrations/__tests__/1786600000000-AddChatLeadBitrixEntityType.spec.ts \
  dashboard/src/components/ConversationHealthPanel.tsx \
  dashboard/src/components/ConversationHealthPanel.css \
  dashboard/src/pages/Dashboard.tsx \
  dashboard/src/pages/Chats.tsx \
  dashboard/src/pages/Chats.css \
  dashboard/src/services/api.ts \
  dashboard/src/i18n/locales/en.json \
  -C "$TMP" conversation-health.env \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && echo push-ok"

echo "merge env + redis + rebuild…"
# SKIP_BACKFILL=1 avoids re-posting history comments on every redeploy.
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && SKIP_BACKFILL=${SKIP_BACKFILL:-1} bash -s" <<'REMOTE'
set -euo pipefail
grep -q ConversationHealthModule src/app.module.ts
grep -q conversation-health-queue src/modules/queue/queue-names.ts
grep -q ConversationHealthPanel dashboard/src/pages/Dashboard.tsx
grep -q 'QUEUE_ENABLED=\${QUEUE_ENABLED:-}' docker-compose.yml
test -f conversation-health.env
python3 - <<'PY'
from pathlib import Path
snippet = Path('conversation-health.env').read_text().splitlines()
pairs = {}
for line in snippet:
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    pairs[k] = v
p = Path('.env')
text = p.read_text() if p.exists() else ''
out, seen = [], set()
for line in text.splitlines():
    if not line or line.lstrip().startswith('#') or '=' not in line:
        out.append(line)
        continue
    k = line.split('=', 1)[0]
    if k in pairs:
        out.append(f'{k}={pairs[k]}')
        seen.add(k)
    else:
        out.append(line)
for k, v in pairs.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out) + '\n')
# Also pin dashboard-saved layer so a recreate without host .env still keeps queue on.
gen = Path('data/.env.generated')
# data/ is only inside the volume; patch via a temp that compose will not see — use docker volume path.
Path('conversation-health.env').unlink(missing_ok=True)
print('env-merged', len(pairs))
PY

# Start built-in Redis (profile) before API expects BullMQ.
docker compose --profile redis up -d redis
for i in $(seq 1 30); do
  if docker compose --profile redis exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
    echo redis-ok
    break
  fi
  sleep 1
done
docker compose --profile redis exec -T redis redis-cli ping | grep -q PONG

# Pin queue/redis in the data volume generated env (below host .env in precedence, still useful).
GEN=/var/lib/docker/volumes/openwa_openwa-data/_data/.env.generated
if [ -f "$GEN" ]; then
  python3 - <<'PY'
from pathlib import Path
p = Path('/var/lib/docker/volumes/openwa_openwa-data/_data/.env.generated')
pairs = {
    'QUEUE_ENABLED': 'true',
    'REDIS_ENABLED': 'true',
    'REDIS_HOST': 'redis',
    'REDIS_PORT': '6379',
    'REDIS_BUILTIN': 'true',
}
text = p.read_text() if p.exists() else ''
out, seen = [], set()
for line in text.splitlines():
    if not line or line.lstrip().startswith('#') or '=' not in line:
        out.append(line)
        continue
    k = line.split('=', 1)[0]
    if k in pairs:
        out.append(f'{k}={pairs[k]}')
        seen.add(k)
    else:
        out.append(line)
for k, v in pairs.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out) + '\n')
print('generated-patched')
PY
fi

docker compose build openwa-api
echo build-ok
docker compose --profile redis up -d --force-recreate openwa-api
echo recreate-ok
code=000
for i in $(seq 1 40); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo "readiness=$code"
test "$code" = "200"

KEY=$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d '\r')
echo -n 'env-check='
docker compose exec -T openwa-api printenv QUEUE_ENABLED REDIS_ENABLED REDIS_HOST CONVERSATION_HEALTH_ENABLED BITRIX_WA_LEAD_STATUS BITRIX_OWNER_DATA_TYPE_ID | tr '\n' ' '
echo
echo -n 'summary='
curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary
echo
# Prove Owner Data match path is in the baked image.
docker compose exec -T openwa-api sh -c 'grep -q findOwnerDataByPhone /app/dist/modules/conversation-health/bitrix-lead.client.js && echo owner-data-code=ok'
# Prove migration column exists (SQLite).
docker compose exec -T openwa-api node -e '
const Database=require("better-sqlite3");
const db=new Database(process.env.DATABASE_NAME||"/app/data/openwa.sqlite",{readonly:true});
const cols=db.prepare("PRAGMA table_info(chat_leads)").all().map(c=>c.name);
console.log("chat_leads_cols", cols.includes("bitrixEntityType")?"bitrixEntityType=ok":"bitrixEntityType=MISSING", cols.join(","));
'
if [ "${SKIP_BACKFILL:-}" = "1" ]; then
  echo 'backfill=skipped'
else
  echo -n 'backfill='
  curl -sS -m 180 -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
    http://127.0.0.1:2785/api/conversation-health/backfill
  echo
  sleep 15
  echo -n 'summary-after='
  curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary
  echo
fi
docker compose --profile redis ps --format '{{.Service}} {{.State}} {{.Status}}'
REMOTE
