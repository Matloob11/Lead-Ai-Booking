#!/usr/bin/env bash
# Ships bitrix/public/ to the Hostinger VPS as the static panel root.
#
#   ./bitrix/deploy/deploy-panel.sh
#
# Only touches /opt/a7-wa/panel/. The nginx location block that serves it is in
# a7-wa-panel.location.conf and has to be added to /etc/nginx/conf.d/a7-wa.conf
# once, by hand — this script never edits nginx config.

set -euo pipefail

SSH_KEY="${SSH_KEY:-$HOME/.ssh/hostinger_codex}"
HOST="${HOST:-root@187.127.123.235}"
REMOTE_DIR="/opt/a7-wa/panel"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../public" && pwd)"

echo "→ $LOCAL_DIR  ⇒  $HOST:$REMOTE_DIR"

ssh -i "$SSH_KEY" "$HOST" "mkdir -p '$REMOTE_DIR'"
rsync -az --delete -e "ssh -i $SSH_KEY" "$LOCAL_DIR/" "$HOST:$REMOTE_DIR/"
ssh -i "$SSH_KEY" "$HOST" "chown -R www-data:www-data '$REMOTE_DIR' && nginx -t && systemctl reload nginx"

echo "✓ https://wa.srv1802669.hstgr.cloud/app/ updated"
