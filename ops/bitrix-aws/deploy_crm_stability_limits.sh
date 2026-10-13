#!/bin/bash
# Deploy CRM stability limits on Bitrix Lightsail (run as root / via sudo).
set -euo pipefail
TS=$(date +%Y%m%d_%H%M%S)
SETTINGS_SRC=/tmp/a7_rate_limit_rest_flood.conf
LOC_SRC=/tmp/a7_rest_limit_locations.conf
TIMER_SRC=/tmp/a7-lead-shift.timer
SVC_SRC=/tmp/a7-lead-shift.service
LG_JS_SRC=/tmp/a7_lead_guard.js

SETTINGS_DST=/etc/nginx/bx/settings/a7_rate_limit_zadarma_voiso.conf
LOC_DST=/etc/nginx/bx/site_settings/default/a7_rest_limit_zadarma_voiso.conf
# Keep old filename so existing include glob still picks it up; content replaced.
TIMER_DST=/etc/systemd/system/a7-lead-shift.timer
SVC_DST=/etc/systemd/system/a7-lead-shift.service
LG_JS_DST=/home/bitrix/www/bitrix/js/a7_lead_guard.js

echo "=== backup ==="
cp -a "$SETTINGS_DST" "${SETTINGS_DST}.bak.${TS}"
cp -a "$LOC_DST" "${LOC_DST}.bak.${TS}"
cp -a "$TIMER_DST" "${TIMER_DST}.bak.${TS}"
cp -a "$SVC_DST" "${SVC_DST}.bak.${TS}"
if [[ -f "$LG_JS_DST" ]]; then
  cp -a "$LG_JS_DST" "${LG_JS_DST}.bak.${TS}"
fi

echo "=== install nginx limits ==="
install -m 644 -o root -g root "$SETTINGS_SRC" "$SETTINGS_DST"
install -m 644 -o root -g root "$LOC_SRC" "$LOC_DST"

echo "=== install lead-shift timer/service ==="
install -m 644 -o root -g root "$TIMER_SRC" "$TIMER_DST"
install -m 644 -o root -g root "$SVC_SRC" "$SVC_DST"

if [[ -f "$LG_JS_SRC" ]]; then
  echo "=== install lead_guard.js ==="
  install -m 644 -o bitrix -g bitrix "$LG_JS_SRC" "$LG_JS_DST"
fi

echo "=== nginx -t ==="
nginx -t

echo "=== reload nginx ==="
systemctl reload nginx

echo "=== systemd reload + restart timer ==="
systemctl daemon-reload
# Stop a long-running shift if one is chewing CPU right now
systemctl stop a7-lead-shift.service 2>/dev/null || true
systemctl restart a7-lead-shift.timer
systemctl status a7-lead-shift.timer --no-pager | head -20

echo "=== verify zones in nginx -T ==="
nginx -T 2>/dev/null | grep -E 'a7_host_api|a7_lg_api|a7_zv_api|187.127.123.235|a7_lead_guard_api' | head -40

echo "=== load snapshot ==="
uptime
ps -C httpd --no-headers | wc -l
curl -s -o /dev/null -w 'home=%{http_code} t=%{time_total}\n' --max-time 20 https://crm.a7grouprealestatedxb.com/
echo DONE
