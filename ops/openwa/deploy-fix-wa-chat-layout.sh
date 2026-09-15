#!/usr/bin/env bash
# Fix Bitrix WhatsApp Chat field width (SIZE 20 → 80) + deploy safer thread formatting.
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

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
: "${BITRIX_WEBHOOK_BASE:?BITRIX_WEBHOOK_BASE missing}"

echo "=== 1) try widen Bitrix UF fields (needs userfieldconfig scope) ==="
# Legacy crm.*.userfield.* cannot change SIZE (stays 20). Prefer userfieldconfig.
tar -cf - -C "$ROOT" ops/openwa/widen-wa-chat-userfieldconfig.py ops/openwa/fix-wa-chat-field-width.py \
  | "${SSH[@]}" "$HOST" "cd /tmp && tar -xf - && BITRIX_WEBHOOK_BASE=$(printf %q "$BITRIX_WEBHOOK_BASE") \
      BITRIX_USERFIELDCONFIG_WEBHOOK=$(printf %q "${BITRIX_USERFIELDCONFIG_WEBHOOK:-}") \
      python3 ops/openwa/widen-wa-chat-userfieldconfig.py --fix || true"

echo "=== 2) push OpenWA format helpers ==="
tar -cf - -C "$ROOT/openwa" \
  src/modules/conversation-health/conversation-health.format.ts \
  src/modules/conversation-health/conversation-health.format.spec.ts \
  src/modules/conversation-health/conversation-health.service.ts \
  | "${SSH[@]}" "$HOST" "cd $OPENWA_DIR && tar -xf - --overwrite && \
      grep -q formatThreadForBitrixField src/modules/conversation-health/conversation-health.service.ts && \
      echo format-push-ok"

echo "=== 3) rebuild openwa-api ==="
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d redis && docker compose build openwa-api 2>&1 | tail -15 && echo BUILD_DONE"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose --profile redis up -d --force-recreate openwa-api 2>&1 | tail -10 && echo RECREATE_DONE"

echo "=== 4) prove field SIZE + readiness ==="
"${SSH[@]}" "$HOST" "BITRIX_BASE=$(printf %q "${BITRIX_WEBHOOK_BASE%/}") python3 -" <<'PY'
import json, os, urllib.request
base = os.environ["BITRIX_BASE"].rstrip("/")
def post(method, payload):
    req = urllib.request.Request(f"{base}/{method}.json", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)
for name in ("UF_CRM_WA_CHAT", "UF_CRM_AI_MONITOR"):
    meta = (post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": name}}).get("result") or [{}])[0]
    s = meta.get("SETTINGS") or {}
    print(name, "SIZE", s.get("SIZE"), "ROWS", s.get("ROWS"))
if all(int(((post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": n}}).get("result") or [{}])[0].get("SETTINGS") or {}).get("SIZE") or 0) >= 60 for n in ("UF_CRM_WA_CHAT", "UF_CRM_AI_MONITOR")):
    print("field-width-ok")
else:
    print("field-width-STILL-20 (set Size=80 in Bitrix UI or webhook userfieldconfig)")
PY

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && code=000; for i in \$(seq 1 40); do code=\$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true); test \"\$code\" = 200 && break; sleep 3; done; echo readiness=\$code; test \"\$code\" = 200"
"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api sh -c 'grep -rq formatThreadForBitrixField /app/dist && echo format-bundle=ok'"

echo "DEPLOY_OK"
