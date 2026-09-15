#!/usr/bin/env bash
# Panel: Linked devices → WhatsApp + drop subtitle. OpenWA: kill framed chats gap.
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

echo "=== 1) panel ==="
bash "$ROOT/ops/wa.sh" panel

echo "=== 2) prove panel strings ==="
bash "$ROOT/ops/wa.sh" sum /opt/a7-wa/panel/assets/modules/inbox.js
"${SSH[@]}" "$HOST" "grep -F 'span.linked__title' -A1 /opt/a7-wa/panel/assets/modules/inbox.js | head -5; grep -q 'QR-linked phones, separate' /opt/a7-wa/panel/assets/modules/inbox.js && echo FAIL-note-still-present && exit 1 || echo note-removed-ok; grep -q '[\"'\'']WhatsApp[\"'\'']' /opt/a7-wa/panel/assets/modules/inbox.js && echo title-whatsapp-ok"

echo "=== 3) push OpenWA embedded CSS ==="
tar -cf - -C "$ROOT/openwa" dashboard/src/a7-embedded.css \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && grep -q 'display: none !important' dashboard/src/a7-embedded.css && echo css-push-ok"

echo "=== 4) rebuild openwa-api ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -15 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -10 && echo RECREATE_DONE"

echo "=== 5) ready ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && code=000; for i in \$(seq 1 40); do code=\$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true); test \"\$code\" = 200 && break; sleep 3; done; echo readiness=\$code; test \"\$code\" = 200"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c 'grep -rq sidebar-header-box /app/dashboard/dist && echo embedded-css-bundle=ok'"

echo "DEPLOY_OK"
