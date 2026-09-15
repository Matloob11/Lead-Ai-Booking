#!/usr/bin/env bash
set -euo pipefail

echo "=== JS owner call ==="
ls -la /home/bitrix/www/bitrix/js/a7_owner_data_call.js* 2>/dev/null || true
ls -la /home/bitrix/www/bitrix/js/a7_renewals_call.js* 2>/dev/null || true

echo "=== init.php inject ==="
grep -n "a7_owner_data_call\|a7_renewals_call\|voiso\|zadarma\|DISABLED" \
  /home/bitrix/www/bitrix/php_interface/init.php 2>/dev/null | head -50 || true

echo "=== rest events ==="
mysql -N bitrix -e "
SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,140), APP_ID
FROM b_rest_event
WHERE EVENT_NAME LIKE '%EXTERNAL%'
   OR EVENT_HANDLER LIKE '%voiso%'
   OR EVENT_HANDLER LIKE '%zadarma%'
   OR EVENT_HANDLER LIKE '%ams04%'
   OR EVENT_HANDLER LIKE '%click%'
LIMIT 60;"

echo "=== rest apps ==="
mysql -N bitrix -e "
SELECT ID, CODE, ACTIVE, LEFT(APP_NAME,80)
FROM b_rest_app
WHERE APP_NAME LIKE '%voiso%'
   OR APP_NAME LIKE '%Voiso%'
   OR APP_NAME LIKE '%zadarma%'
   OR APP_NAME LIKE '%Zadarma%'
   OR CODE LIKE '%voiso%'
   OR CODE LIKE '%zadarma%'
   OR APP_NAME LIKE '%cloud%'
ORDER BY ID DESC
LIMIT 40;"

echo "=== telephony options ==="
mysql -N bitrix -e "
SELECT MODULE_ID, NAME, LEFT(VALUE,180)
FROM b_option
WHERE MODULE_ID IN ('voximplant','telephony')
   OR NAME LIKE '%DEFAULT_LINE%'
   OR NAME LIKE '%PORTAL_NUMBER%'
LIMIT 50;"

echo "=== file hits voiso/zadarma ==="
grep -ril 'voiso\|zadarma\|cc-ams04\|a7 cloud' \
  /home/bitrix/www/bitrix/js \
  /home/bitrix/www/local \
  /home/bitrix/www/bitrix/php_interface \
  /home/bitrix/www/bitrix/templates \
  2>/dev/null | head -50 || true

echo "=== normalize in live JS ==="
grep -n "971\|normalizeDialPhone\|phoneTo\|Voiso\|Zadarma\|dialVia" \
  /home/bitrix/www/bitrix/js/a7_owner_data_call.js 2>/dev/null | head -40 || true

echo "=== clean_phone in tools ==="
grep -n "function a7_clean_phone\|971\|normalize" \
  /home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php 2>/dev/null | head -40 || true

echo "=== done ==="
