#!/bin/bash
set -euo pipefail
echo "=== exceptions curl ==="
grep -i 'curl_init\|owner-data\|voiso' /var/log/php/exceptions.log | tail -n 30 || true
echo "=== curl.ini ==="
cat /etc/php.d/20-curl.ini
echo ---
ls -la /etc/php.d/*curl*
echo "=== http helpers in tools ==="
grep -n 'HttpClient\|curl_init\|file_get_contents\|a7_bitrix_webhook_call\|a7_http' /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php | head -60
echo "=== webhook_call body ==="
# print function a7_bitrix_webhook_call
START=$(grep -n 'function a7_bitrix_webhook_call' /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php | head -1 | cut -d: -f1)
sed -n "${START},$((START+80))p" /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php
echo "=== log path upload ==="
ls -la /home/bitrix/www/upload/a7_3cx_click_to_call.log 2>/dev/null || true
tail -n 20 /home/bitrix/www/upload/a7_3cx_click_to_call.log 2>/dev/null || true
echo "=== member_id ==="
# try sitemanager db name
mysql -e 'SHOW DATABASES;' 2>/dev/null | head
for DB in sitemanager bitrix db; do
  mysql "$DB" -e 'SELECT 1' >/dev/null 2>&1 || continue
  echo "DB=$DB"
  mysql "$DB" -e 'SELECT * FROM a7_rest_event_voiso_backup\G' 2>/dev/null || true
done
