#!/usr/bin/env bash
# Cron entrypoint: sync Owner Data Amount from Lease/Selling Price UFs.
set -euo pipefail
DIR=/opt/a7-wa/ops/openwa
LOG=/var/log/owner-data-amount-sync.log
ENV_FILE=
for c in /opt/openwa-trial/OpenWA/.env /opt/a7-wa/openwa/.env /opt/a7-wa/.env; do
  if [[ -f "$c" ]] && grep -q '^BITRIX_WEBHOOK_BASE=' "$c"; then
    ENV_FILE="$c"
    break
  fi
done
if [[ -z "$ENV_FILE" ]]; then
  echo "$(date -Is) missing BITRIX_WEBHOOK_BASE" >>"$LOG"
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
# New Availability every run; full Availability + calling board once an hour.
ARGS=(--fix --only-new)
minute=$(date +%M)
if [[ "$minute" == "00" ]]; then
  ARGS=(--fix)
fi
{
  echo "$(date -Is) start ${ARGS[*]}"
  python3 "$DIR/fix-owner-data-kanban-amounts.py" "${ARGS[@]}"
  echo "$(date -Is) done"
} >>"$LOG" 2>&1
