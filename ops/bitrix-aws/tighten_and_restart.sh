#!/bin/bash
set -eu
TS=$(date +%Y%m%d_%H%M%S)
install -m 644 /tmp/a7_rate_limit_rest_flood.conf /etc/nginx/bx/settings/a7_rate_limit_zadarma_voiso.conf
install -m 644 /tmp/a7_rest_limit_locations.conf /etc/nginx/bx/site_settings/default/a7_rest_limit_zadarma_voiso.conf
nginx -t
systemctl reload nginx
echo "=== restart httpd to clear stuck workers ==="
systemctl restart httpd
sleep 3
echo "=== status ==="
uptime
echo httpd=$(ps -C httpd --no-headers | wc -l)
systemctl is-active nginx httpd
curl -s -o /dev/null -w 'home=%{http_code} t=%{time_total}\n' --max-time 20 https://crm.a7grouprealestatedxb.com/
echo DONE
