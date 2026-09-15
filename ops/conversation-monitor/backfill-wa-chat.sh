#!/usr/bin/env bash
# Fill UF_CRM_WA_CHAT (+ refresh AI Monitor emoji line) for Phase1 leads from live OpenWA.
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

# Reuse classifier helpers by invoking a tiny remote driver that imports nothing —
# push an inline backfill next to phase1.
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

# Ensure latest classifier is on the host (defines nothing we import; we ship backfill.py)
tar -cf - -C "$ROOT/ops/conversation-monitor" phase1_classify.py backfill_wa_chat.py \
  | "${SSH[@]}" "$HOST" "tar -xf - -C /opt/openwa-trial && echo push-ok"

"${SSH[@]}" "$HOST" \
  "cd '$OPENWA_DIR' && \
   OPENWA_KEY=\$(docker compose exec -T openwa-api printenv API_MASTER_KEY | tr -d '\\r') && \
   BITRIX_WEBHOOK_BASE=$(printf '%q' "$BITRIX_WEBHOOK_BASE") \
   OPENWA_API_KEY=\"\$OPENWA_KEY\" \
   OPENWA_BASE=http://127.0.0.1:2785 \
   BITRIX_AI_MONITOR_FIELD=$(printf '%q' "${BITRIX_AI_MONITOR_FIELD:-UF_CRM_AI_MONITOR}") \
   BITRIX_WA_CHAT_FIELD=$(printf '%q' "${BITRIX_WA_CHAT_FIELD:-UF_CRM_WA_CHAT}") \
   BITRIX_HEALTH_FIELD=$(printf '%q' "${BITRIX_HEALTH_FIELD:-UF_CRM_CONVERSATION_HEALTH}") \
   python3 /opt/openwa-trial/backfill_wa_chat.py"
