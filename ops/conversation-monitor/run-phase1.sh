#!/usr/bin/env bash
# Push phase1_classify.py to the OpenWA host and run against live OpenWA + Bitrix + OpenAI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
OPENWA_DIR="/opt/openwa-trial/OpenWA"
REMOTE_SCRIPT="/opt/openwa-trial/phase1_classify.py"

SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

echo "pushing classifier…"
tar -cf - -C "$ROOT/ops/conversation-monitor" phase1_classify.py \
  | "${SSH[@]}" "$HOST" "tar -xf - -C /opt/openwa-trial && echo push-ok"

echo "running phase1…"
# Pass secrets only in the remote env for this process — not written to disk on the server.
"${SSH[@]}" "$HOST" \
  "cd '$OPENWA_DIR' && \
   OPENWA_KEY=\$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d '\\r') && \
   test -n \"\$OPENWA_KEY\" && \
   BITRIX_WEBHOOK_BASE=$(printf '%q' "$BITRIX_WEBHOOK_BASE") \
   OPENAI_API_KEY=$(printf '%q' "$OPENAI_API_KEY") \
   OPENAI_MODEL=$(printf '%q' "${OPENAI_MODEL:-gpt-4o-mini}") \
   BITRIX_HEALTH_FIELD=$(printf '%q' "${BITRIX_HEALTH_FIELD:-UF_CRM_CONVERSATION_HEALTH}") \
   BITRIX_AI_MONITOR_FIELD=$(printf '%q' "${BITRIX_AI_MONITOR_FIELD:-UF_CRM_AI_MONITOR}") \
   BITRIX_WA_CHAT_FIELD=$(printf '%q' "${BITRIX_WA_CHAT_FIELD:-UF_CRM_WA_CHAT}") \
   BITRIX_WA_LEAD_STATUS=$(printf '%q' "${BITRIX_WA_LEAD_STATUS:-UC_WA_LEADS}") \
   OPENWA_API_KEY=\"\$OPENWA_KEY\" \
   OPENWA_BASE=http://127.0.0.1:2785 \
   PHASE1_CHAT_LIMIT=${PHASE1_CHAT_LIMIT:-12} \
   PHASE1_MIN_MESSAGES=${PHASE1_MIN_MESSAGES:-4} \
   python3 '$REMOTE_SCRIPT'"
