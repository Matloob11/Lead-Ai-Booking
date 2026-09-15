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
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=25 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

tar -cf - -C "$ROOT/openwa" docker-compose.yml src/config/env-precedence.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && grep -q CONVERSATION_HEALTH_OVERRIDE_PASSWORD docker-compose.yml && echo push-ok"

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose up -d --force-recreate openwa-api 2>&1 | tail -10"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && bash -s" <<'REMOTE'
set -euo pipefail
for i in $(seq 1 40); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo readiness=$code
val=$(docker compose exec -T openwa-api printenv CONVERSATION_HEALTH_OVERRIDE_PASSWORD | tr -d '\r')
echo "password_in_container=$val"
test "$val" = "222007"
REMOTE
