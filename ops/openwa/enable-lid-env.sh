#!/usr/bin/env bash
# Push compose forward for RESOLVE_LID_TO_PHONE and recreate openwa-api (no rebuild).
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

echo "pushing docker-compose.yml…"
tar -cf - -C "$ROOT/openwa" docker-compose.yml \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && echo push-ok"

echo "recreating openwa-api with RESOLVE_LID_TO_PHONE…"
"${SSH[@]}" "$HOST" "cd $OPENWA_DIR && bash -s" <<'REMOTE'
set -euo pipefail
if grep -q '^RESOLVE_LID_TO_PHONE=' .env 2>/dev/null; then
  sed -i 's/^RESOLVE_LID_TO_PHONE=.*/RESOLVE_LID_TO_PHONE=true/' .env
else
  printf '\nRESOLVE_LID_TO_PHONE=true\n' >> .env
fi
grep -q '^RESOLVE_LID_TO_PHONE=true$' .env
grep -q 'RESOLVE_LID_TO_PHONE' docker-compose.yml
echo "compose-forward=ok"
docker compose up -d --force-recreate openwa-api
echo "recreate-ok"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 3
done
echo "readiness=$code"
docker compose exec -T openwa-api node -e 'console.log("resolve-lid-runtime="+(process.env.RESOLVE_LID_TO_PHONE||""))'
REMOTE
