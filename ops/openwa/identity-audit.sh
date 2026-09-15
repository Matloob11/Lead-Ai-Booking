#!/usr/bin/env bash
#
# Read-only pre-deploy identity gate for legacy OpenWA sessions.
#
# The audited TypeScript source is transpiled locally, carried over SSH as
# base64 on stdin, and executed as a one-off Node process in the running OpenWA
# container. `--cold` instead requires the API stopped and mounts the same data
# volume read-only into a networkless one-off container. SQLite itself opens the
# database read-only. Only sanitized counts and decisions can pass the local
# output allowlist.

set -uo pipefail

HOST="root@187.127.123.235"
KEY="C:/Users/Matloob/.ssh/hostinger_codex"
APP="/opt/openwa-trial/OpenWA"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
AUDIT_SOURCE="$REPO_ROOT/openwa/src/modules/session/legacy-identity-audit.ts"
TYPESCRIPT="$REPO_ROOT/openwa/node_modules/typescript"
KNOWN_HOSTS="$REPO_ROOT/ops/known_hosts"

AUDIT_OUTPUT=""
AUDIT_STATUS=1
NODE_COMMAND=()
NODE_AUDIT_SOURCE=""
NODE_TYPESCRIPT=""
SSH_KNOWN_HOSTS=""

remote() {
  ssh.exe -i "$KEY" \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
    "$HOST" "$@"
}

resolve_ssh() {
  command -v ssh.exe >/dev/null 2>&1 || return 1
  [ -f "$KNOWN_HOSTS" ] || return 1
  if command -v wslpath >/dev/null 2>&1; then
    SSH_KNOWN_HOSTS=$(wslpath -w "$KNOWN_HOSTS" 2>/dev/null) || return 1
  else
    SSH_KNOWN_HOSTS="$KNOWN_HOSTS"
  fi
}

resolve_node() {
  if command -v node >/dev/null 2>&1; then
    NODE_COMMAND=(node)
    NODE_AUDIT_SOURCE="$AUDIT_SOURCE"
    NODE_TYPESCRIPT="$TYPESCRIPT"
    return 0
  fi

  local windows_node="/mnt/c/Program Files/nodejs/node.exe"
  command -v wslpath >/dev/null 2>&1 || return 1
  [ -x "$windows_node" ] || return 1
  NODE_COMMAND=("$windows_node")
  NODE_AUDIT_SOURCE=$(wslpath -w "$AUDIT_SOURCE" 2>/dev/null) || return 1
  NODE_TYPESCRIPT=$(wslpath -w "$TYPESCRIPT" 2>/dev/null) || return 1
}

compile_payload() {
  "${NODE_COMMAND[@]}" - "$NODE_AUDIT_SOURCE" "$NODE_TYPESCRIPT" 2>/dev/null <<'NODE'
const fs = require('node:fs');
const sourcePath = process.argv[2];
const typescriptPath = process.argv[3];
const ts = require(typescriptPath);
const source = `${fs.readFileSync(sourcePath, 'utf8')}\nprocess.exitCode = runCli('/app/data/openwa.sqlite');\n`;
const result = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2023,
  },
  reportDiagnostics: true,
});
if ((result.diagnostics ?? []).some(diagnostic => diagnostic.category === ts.DiagnosticCategory.Error)) {
  process.exit(1);
}
process.stdout.write(Buffer.from(result.outputText, 'utf8').toString('base64'));
NODE
}

validate_output() {
  local output="$1"
  local status="$2"
  local line overall="" saw_overall=0
  local session_pattern='^session (session-[0-9]+|[A-Za-z][A-Za-z._-]{0,99}) rows [0-9]+ resolved [0-9]+ unresolved [0-9]+ (PASS|FAIL|INCONCLUSIVE)$'
  local overall_pattern='^overall: (PASS|FAIL|INCONCLUSIVE)$'

  while IFS= read -r line; do
    if [[ "$line" =~ $session_pattern ]] && [ "$saw_overall" -eq 0 ]; then
      continue
    fi
    if [[ "$line" =~ $overall_pattern ]] && [ "$saw_overall" -eq 0 ]; then
      overall="${BASH_REMATCH[1]}"
      saw_overall=1
      continue
    fi
    return 1
  done <<<"$output"

  [ "$saw_overall" -eq 1 ] || return 1
  case "$overall:$status" in
    PASS:0|INCONCLUSIVE:1|FAIL:2) return 0 ;;
    *) return 1 ;;
  esac
}

run_audit() {
  local mode="live"
  if [ "$#" -eq 1 ] && [ "$1" = "--cold" ]; then
    mode="cold"
  elif [ "$#" -ne 0 ]; then
    return 1
  fi
  [ -f "$AUDIT_SOURCE" ] || return 1
  [ -d "$TYPESCRIPT" ] || return 1
  resolve_node || return 1
  resolve_ssh || return 1

  local payload output status
  payload=$(compile_payload) || return 1
  [ -n "$payload" ] || return 1

  if [ "$mode" = "cold" ]; then
    output=$(printf '%s' "$payload" | remote \
      "set -eu; cd $APP; \
       running=\$(docker compose ps --status running -q openwa-api); test -z \"\$running\"; \
       image=\$(docker compose images -q openwa-api); test -n \"\$image\"; \
       base64 -d | docker run --rm -i --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
         -e NODE_NO_WARNINGS=1 -v openwa_openwa-data:/app/data:ro --entrypoint node \"\$image\" -" \
      2>/dev/null)
  else
    output=$(printf '%s' "$payload" | remote \
      "cd $APP && base64 -d | docker compose exec -T -e NODE_NO_WARNINGS=1 openwa-api node -" \
      2>/dev/null)
  fi
  status=$?

  case "$status" in
    0|1|2) ;;
    *) return 1 ;;
  esac
  validate_output "$output" "$status" || return 1

  AUDIT_OUTPUT="$output"
  AUDIT_STATUS="$status"
  return 0
}

if run_audit "$@"; then
  printf '%s\n' "$AUDIT_OUTPUT"
  exit "$AUDIT_STATUS"
fi

printf '%s\n' 'overall: INCONCLUSIVE'
exit 1
