#!/usr/bin/env bash
# Push Owner Data match sources, rebuild openwa-api, prove code + column + readiness.
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

echo "1) push sources…"
tar -cf - -C "$ROOT/openwa" \
  docker-compose.yml \
  src/modules/conversation-health/bitrix-lead.client.ts \
  src/modules/conversation-health/bitrix-lead.client.spec.ts \
  src/modules/conversation-health/conversation-health.service.ts \
  src/modules/conversation-health/conversation-health.constants.ts \
  src/modules/conversation-health/entities/chat-lead.entity.ts \
  src/database/migrations/1786600000000-AddChatLeadBitrixEntityType.ts \
  src/database/migrations/__tests__/1786600000000-AddChatLeadBitrixEntityType.spec.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q findOwnerDataByPhone src/modules/conversation-health/bitrix-lead.client.ts && \
      test -f src/database/migrations/1786600000000-AddChatLeadBitrixEntityType.ts && \
      echo push-ok"

echo "2) merge Owner Data env keys…"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && python3 - <<'PY'
from pathlib import Path
pairs = {
    'BITRIX_OWNER_DATA_TYPE_ID': '1042',
    'BITRIX_OWNER_DATA_URL_BASE': 'https://crm.a7grouprealestatedxb.com/crm/type/1042/details',
    'REDIS_HOST': 'openwa-redis',
    'QUEUE_ENABLED': 'true',
    'CONVERSATION_HEALTH_ENABLED': 'true',
}
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
p.write_text('\\n'.join(out) + '\\n')
print('env-ok', sorted(pairs))
PY"

echo "3) build (long)…"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -20 && echo BUILD_DONE"

echo "4) recreate…"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -12 && echo RECREATE_DONE"

echo "5) wait ready…"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && code=000; for i in \$(seq 1 40); do code=\$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true); test \"\$code\" = 200 && break; sleep 3; done; echo readiness=\$code; test \"\$code\" = 200"

echo "6) prove…"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && \
  docker compose exec -T openwa-api sh -c 'grep -q findOwnerDataByPhone /app/dist/modules/conversation-health/bitrix-lead.client.js && echo owner-data-code=ok' && \
  docker compose exec -T openwa-api node -e \"
const Database=require('better-sqlite3');
const db=new Database(process.env.DATABASE_NAME||'/app/data/openwa.sqlite',{readonly:true});
const cols=db.prepare('PRAGMA table_info(chat_leads)').all().map(c=>c.name);
console.log(cols.includes('bitrixEntityType')?'bitrixEntityType=ok':'bitrixEntityType=MISSING');
const n=db.prepare(\\\"SELECT COUNT(*) AS c FROM chat_leads\\\").get();
console.log('chat_leads', n.c);
\" && \
  echo -n env= && docker compose exec -T openwa-api printenv BITRIX_OWNER_DATA_TYPE_ID REDIS_HOST CONVERSATION_HEALTH_ENABLED QUEUE_ENABLED && \
  KEY=\$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d '\\r') && \
  echo -n summary= && curl -sS -m 30 -H \"X-API-Key: \$KEY\" http://127.0.0.1:2785/api/conversation-health/summary && echo && \
  docker compose --profile redis ps --format '{{.Service}} {{.State}} {{.Status}}'"

echo "DEPLOY_OK"
