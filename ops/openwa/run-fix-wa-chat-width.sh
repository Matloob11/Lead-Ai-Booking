#!/usr/bin/env bash
# Apply Bitrix WA_CHAT / AI_MONITOR field-width fix on the VPS (webhook-local).
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
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

echo "=== push + run fix-wa-chat-field-width.py --fix ==="
tar -cf - -C "$ROOT" ops/openwa/fix-wa-chat-field-width.py \
  | "${SSH[@]}" "$HOST" "cd /tmp && tar -xf - && BITRIX_WEBHOOK_BASE=$(printf %q "$BITRIX_WEBHOOK_BASE") python3 ops/openwa/fix-wa-chat-field-width.py --fix"

echo "=== prove ==="
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
    print(name, "SIZE", s.get("SIZE"), "ROWS", s.get("ROWS"), "TYPE", meta.get("USER_TYPE_ID"))
    print("SETTINGS_JSON", json.dumps(s))
PY
echo "DONE"
