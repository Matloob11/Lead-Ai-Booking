#!/usr/bin/env bash
# Recreate OpenWA session `asma` and start it for QR scan.
# Does not print API keys, phone numbers, or QR payloads.
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"

ssh.exe -i "$KEY_FILE" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$KNOWN_HOSTS" \
  "$HOST" "cd $OPENWA_DIR && bash -s" <<'REMOTE'
set -euo pipefail

if grep -q "on-demand media reload" dashboard/src/utils/chatMessages.ts; then
  echo "source-fix=present"
else
  echo "source-fix=MISSING"
  exit 1
fi

KEY=$(grep -E '^(API_KEY|API_MASTER_KEY)=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
test -n "$KEY"

api() {
  local method="$1"; shift
  local path="$1"; shift
  if [ "$method" = "POST" ]; then
    curl -sS -X POST -H "x-api-key: $KEY" -H "content-type: application/json" "$@" "http://127.0.0.1:2785$path"
  else
    curl -sS -H "x-api-key: $KEY" "http://127.0.0.1:2785$path"
  fi
}

api GET /api/sessions > /tmp/owa-sessions.json
python3 - <<'PY'
import json
rows=json.load(open("/tmp/owa-sessions.json"))
if isinstance(rows, dict):
    rows=rows.get("sessions", rows.get("data", []))
print("before:", ",".join(f"{x.get('name')}:{x.get('status')}" for x in rows))
print("has-asma:", "yes" if any(x.get("name")=="asma" for x in rows) else "no")
PY

HAS=$(python3 - <<'PY'
import json
rows=json.load(open("/tmp/owa-sessions.json"))
if isinstance(rows, dict):
    rows=rows.get("sessions", rows.get("data", []))
print("yes" if any(x.get("name")=="asma" for x in rows) else "no")
PY
)

if [ "$HAS" = "no" ]; then
  api POST /api/sessions -d '{"name":"asma"}' > /tmp/owa-asma-create.json
  python3 - <<'PY'
import json
x=json.load(open("/tmp/owa-asma-create.json"))
print("created:", x.get("name"), "status="+str(x.get("status")))
PY
fi

api GET /api/sessions > /tmp/owa-sessions.json
ASMA_ID=$(python3 - <<'PY'
import json
rows=json.load(open("/tmp/owa-sessions.json"))
if isinstance(rows, dict):
    rows=rows.get("sessions", rows.get("data", []))
print(next(x["id"] for x in rows if x.get("name")=="asma"))
PY
)
echo "asma-id-prefix=${ASMA_ID%%-*}"

api POST "/api/sessions/${ASMA_ID}/start" > /tmp/owa-asma-start.json || true
python3 - <<'PY'
import json
x=json.load(open("/tmp/owa-asma-start.json"))
if not isinstance(x, dict):
    print("start-status ok")
else:
    print("start-status", x.get("status"))
    print("has-qr-field", any("qr" in k.lower() for k in x.keys()))
PY

sleep 6
api GET /api/sessions > /tmp/owa-sessions.json
python3 - <<'PY'
import json
rows=json.load(open("/tmp/owa-sessions.json"))
if isinstance(rows, dict):
    rows=rows.get("sessions", rows.get("data", []))
print("after:", ",".join(f"{x.get('name')}:{x.get('status')}" for x in rows))
PY
REMOTE
