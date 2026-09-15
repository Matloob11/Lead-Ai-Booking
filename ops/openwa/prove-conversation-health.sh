#!/usr/bin/env bash
# Prove Conversation Health API + enable Redis/queue if needed; enqueue backfill.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

HOST="root@187.127.123.235"
KEY="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
OPENWA_DIR="/opt/openwa-trial/OpenWA"
SSH=(ssh.exe -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

# scp.exe cannot read WSL /tmp — keep the snippet on the Windows-visible workspace.
TMP="$ROOT/ops/openwa/.conversation-health.env.tmp"
trap 'rm -f "$TMP"' EXIT
cat >"$TMP" <<EOF
QUEUE_ENABLED=true
REDIS_ENABLED=true
# Must be the OpenWA compose service DNS name that cannot collide with a7wa-redis on a7wa_default.
REDIS_HOST=openwa-redis
REDIS_PORT=6379
REDIS_BUILTIN=true
CONVERSATION_HEALTH_ENABLED=true
BITRIX_WEBHOOK_BASE=${BITRIX_WEBHOOK_BASE}
BITRIX_LEAD_URL_BASE=${BITRIX_LEAD_URL_BASE:-https://crm.a7grouprealestatedxb.com/crm/lead/details}
BITRIX_WA_LEAD_STATUS=${BITRIX_WA_LEAD_STATUS:-UC_WA_LEADS}
BITRIX_HEALTH_FIELD=${BITRIX_HEALTH_FIELD:-UF_CRM_CONVERSATION_HEALTH}
BITRIX_AI_MONITOR_FIELD=${BITRIX_AI_MONITOR_FIELD:-UF_CRM_AI_MONITOR}
BITRIX_WA_CHAT_FIELD=${BITRIX_WA_CHAT_FIELD:-UF_CRM_WA_CHAT}
OPENAI_API_KEY=${OPENAI_API_KEY}
OPENAI_MODEL=${OPENAI_MODEL:-gpt-4o-mini}
EOF
SCP_TMP="$TMP"
if command -v wslpath >/dev/null 2>&1; then
  case "$TMP" in
    /mnt/*) SCP_TMP=$(wslpath -w "$TMP") ;;
  esac
fi
scp.exe -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$SCP_TMP" "$HOST:$OPENWA_DIR/conversation-health.env"

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
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
Path('conversation-health.env').unlink(missing_ok=True)
print('env-merged', len(pairs))
PY
docker compose --profile redis up -d redis
docker compose --profile redis up -d --force-recreate openwa-api
code=000
for i in $(seq 1 40); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo "readiness=$code"
test "$code" = "200"
KEY=$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d '\r')
echo -n 'env='
docker compose exec -T openwa-api sh -c 'printf "%s " "$QUEUE_ENABLED" "$REDIS_ENABLED" "$REDIS_HOST" "$CONVERSATION_HEALTH_ENABLED"'
echo
echo -n 'summary='
curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary
echo
echo -n 'backfill='
curl -sS -m 180 -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  http://127.0.0.1:2785/api/conversation-health/backfill
echo
sleep 20
echo -n 'summary-after='
curl -sS -m 30 -H "X-API-Key: $KEY" http://127.0.0.1:2785/api/conversation-health/summary
echo
docker compose --profile redis ps --format '{{.Service}} {{.Status}}'
REMOTE
