#!/usr/bin/env bash
# Recreate Bitrix WA_CHAT / AI_MONITOR with SIZE=80 (update API cannot change SIZE).
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

MODE="${1:---dry}"
ARGS=()
if [[ "$MODE" == "--fix" ]]; then
  ARGS=(--fix)
fi

echo "=== push recreate-wa-chat-fields.py (${MODE}) ==="
tar -cf - -C "$ROOT" ops/openwa/recreate-wa-chat-fields.py \
  | "${SSH[@]}" "$HOST" "cd /tmp && tar -xf - && BITRIX_WEBHOOK_BASE=$(printf %q "$BITRIX_WEBHOOK_BASE") python3 ops/openwa/recreate-wa-chat-fields.py ${ARGS[*]:-}"

REQUIRE_SIZE=0
if [[ "$MODE" == "--fix" ]]; then
  REQUIRE_SIZE=1
fi
echo "=== field meta ==="
"${SSH[@]}" "$HOST" "REQUIRE_SIZE=$REQUIRE_SIZE BITRIX_BASE=$(printf %q "${BITRIX_WEBHOOK_BASE%/}") python3 -" <<'PY'
import json, os, urllib.request, sys
base = os.environ["BITRIX_BASE"].rstrip("/")
require = os.environ.get("REQUIRE_SIZE", "0") == "1"
def post(method, payload):
    req = urllib.request.Request(f"{base}/{method}.json", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)
ok = True
for name in ("UF_CRM_WA_CHAT", "UF_CRM_AI_MONITOR"):
    meta = (post("crm.lead.userfield.list", {"filter": {"FIELD_NAME": name}}).get("result") or [{}])[0]
    s = meta.get("SETTINGS") or {}
    print(name, "SIZE", s.get("SIZE"), "ROWS", s.get("ROWS"), "ID", meta.get("ID"))
    if require and int(s.get("SIZE") or 0) < 60:
        ok = False
if require:
    assert ok, "SIZE still < 60"
    print("field-width-ok")
PY
