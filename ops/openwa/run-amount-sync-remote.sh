#!/bin/bash
set -euo pipefail
ENV_FILE=/opt/a7-wa/agent-reports/.env
WEBHOOK=$(
  python3 - <<'PY'
from pathlib import Path
raw = Path("/opt/a7-wa/agent-reports/.env").read_text(encoding="utf-8-sig")
for line in raw.splitlines():
    if line.startswith("AGENT_REPORT_BITRIX_WEBHOOK="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
    if line.startswith("BITRIX_WEBHOOK_BASE="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'"))
        break
PY
)
if [[ -z "$WEBHOOK" ]]; then
  echo "missing webhook in $ENV_FILE" >&2
  exit 1
fi
export BITRIX_WEBHOOK_BASE="$WEBHOOK"
export AGENT_REPORT_BITRIX_WEBHOOK="$WEBHOOK"
exec python3 /opt/a7-wa/ops/openwa/fix-owner-data-kanban-amounts.py "$@"
