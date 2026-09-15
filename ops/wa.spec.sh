#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
STUB_BIN="$ROOT/ops/test-bin"

run_wa() {
  PATH="$STUB_BIN:$PATH" bash "$ROOT/ops/wa.sh" "$@"
}

state=$(run_wa openwa-state)
[[ "$state" == *'docker compose ps -q openwa-api'* ]]
[[ "$state" == *'docker image inspect'* ]]
[[ "$state" == *'health='* ]]
[[ "$state" == *'readiness-http='* ]]
[[ "$state" == *'database-synchronize='* ]]

backup=$(run_wa openwa-cold-backup)
before_stop=${backup%%docker compose stop openwa-api*}
before_tar=${backup%%tar -C /var/lib/docker/volumes/openwa_openwa-data/_data*}
stop_at=${#before_stop}
tar_at=${#before_tar}
[[ "$stop_at" -gt 0 && "$tar_at" -gt "$stop_at" ]]
[[ "$backup" == *'test -f /var/lib/docker/volumes/openwa_openwa-data/_data/openwa.sqlite'* ]]
[[ "$backup" == *'md5sum'* ]]
[[ "$backup" == *'sqlite=present'* ]]

recreate=$(run_wa openwa-force-recreate)
[[ "$recreate" == *'docker compose up -d --force-recreate openwa-api'* ]]

grep -Fq -- '--network none' "$ROOT/ops/openwa/identity-audit.sh"
grep -Fq -- 'openwa_openwa-data:/app/data:ro' "$ROOT/ops/openwa/identity-audit.sh"
grep -Fq -- 'docker compose ps --status running -q openwa-api' "$ROOT/ops/openwa/identity-audit.sh"

echo 'wa ops fixed-command tests: PASS'
