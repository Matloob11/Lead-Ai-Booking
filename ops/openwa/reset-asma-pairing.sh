#!/usr/bin/env bash
# Clear asma IDENTITY_BUFFER_* quarantine and start a fresh pairing generation.
# Never prints API keys, phones, or pairing codes.
set -euo pipefail

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"

# Write remote script beside this file so Windows scp.exe can read it (not WSL /tmp).
REMOTE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_asma_reset_remote.sh"
cleanup() { rm -f "$REMOTE_SCRIPT"; }
trap cleanup EXIT

cat > "$REMOTE_SCRIPT" <<'REMOTE'
set -euo pipefail
cd /opt/openwa-trial/OpenWA
echo "step=health-wait"
for i in 1 2 3 4 5 6 7 8 9 10; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:2785/api/health/ready || true)
  test "$code" = "200" && break
  sleep 2
done
echo "step=health-ok code=$code"

KEY=$(grep -E '^(API_KEY|API_MASTER_KEY)=' .env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
test -n "$KEY"
echo "step=key-loaded"

curl -sS -H "x-api-key: $KEY" http://127.0.0.1:2785/api/sessions > /tmp/owa-sessions.json
ASMA_ID=$(python3 -c 'import json; rows=json.load(open("/tmp/owa-sessions.json")); rows=rows if isinstance(rows,list) else rows.get("sessions", rows.get("data", [])); print(next(x["id"] for x in rows if x.get("name")=="asma"))')
echo "asma-id-prefix=${ASMA_ID%%-*}"

echo "step=force-kill"
curl -sS -X POST -H "x-api-key: $KEY" "http://127.0.0.1:2785/api/sessions/${ASMA_ID}/force-kill" >/dev/null || true
echo "step=stop"
curl -sS -X POST -H "x-api-key: $KEY" "http://127.0.0.1:2785/api/sessions/${ASMA_ID}/stop" >/dev/null || true
sleep 2

echo "step=wipe-profile"
docker compose exec -T openwa-api sh -c 'rm -rf /app/data/sessions/session-asma /app/data/baileys/asma' >/dev/null || true

echo "step=clear-db-error"
docker compose exec -T openwa-api node -e 'const Database=require("better-sqlite3"); const db=new Database("/app/data/openwa.sqlite"); const r=db.prepare("UPDATE sessions SET status=?, historySyncError=NULL, historySyncToken=NULL WHERE name=?").run("disconnected","asma"); const row=db.prepare("SELECT status, historySyncError FROM sessions WHERE name=?").get("asma"); console.log("db-updated="+r.changes+" status="+row.status+" err="+(row.historySyncError||"none"));'

echo "step=start"
curl -sS -X POST -H "x-api-key: $KEY" "http://127.0.0.1:2785/api/sessions/${ASMA_ID}/start" > /tmp/owa-asma-start.json || true
python3 -c 'import json; x=json.load(open("/tmp/owa-asma-start.json")); print("start-status", x.get("status") if isinstance(x, dict) else "ok")'

sleep 8
curl -sS -H "x-api-key: $KEY" http://127.0.0.1:2785/api/sessions > /tmp/owa-sessions.json
python3 -c 'import json; rows=json.load(open("/tmp/owa-sessions.json")); rows=rows if isinstance(rows,list) else rows.get("sessions", rows.get("data", [])); print("after:", next("%s:%s" % (x.get("name"), x.get("status")) for x in rows if x.get("name")=="asma"))'
REMOTE

# scp.exe is Windows-native; convert WSL /mnt/c paths when needed.
SCP_LOCAL="$REMOTE_SCRIPT"
if command -v wslpath >/dev/null 2>&1; then
  case "$REMOTE_SCRIPT" in
    /mnt/*) SCP_LOCAL=$(wslpath -w "$REMOTE_SCRIPT") ;;
  esac
fi
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi

scp.exe -i "$KEY_FILE" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$SCP_LOCAL" "$HOST:/tmp/asma-reset.sh"

ssh.exe -i "$KEY_FILE" \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$KNOWN_HOSTS_WIN" \
  "$HOST" 'bash /tmp/asma-reset.sh; ec=$?; rm -f /tmp/asma-reset.sh; exit $ec'
