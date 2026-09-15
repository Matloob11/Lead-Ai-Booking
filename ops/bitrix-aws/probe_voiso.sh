#!/usr/bin/env bash
set -euo pipefail
echo '=== modules ==='
ls /home/bitrix/www/bitrix/modules | grep -iE 'tele|vox|voip|call|rest' | head -40
echo '=== rest events voiso/external ==='
mysql -N bitrix -e "SELECT ID, EVENT_NAME, LEFT(EVENT_HANDLER,160), APP_ID FROM b_rest_event WHERE EVENT_NAME LIKE '%EXTERNAL%' OR EVENT_HANDLER LIKE '%voiso%' OR EVENT_HANDLER LIKE '%ams04%' OR EVENT_HANDLER LIKE '%click2call%' LIMIT 50;"
echo '=== rest apps ==='
mysql -N bitrix -e "SELECT ID, APP_ID, CODE, ACTIVE FROM b_rest_app WHERE ACTIVE='Y' ORDER BY ID DESC LIMIT 40;"
echo '=== options telephony ==='
mysql -N bitrix -e "SELECT NAME, LEFT(VALUE,200) FROM b_option WHERE MODULE_ID='voximplant' OR MODULE_ID='telephony' OR NAME LIKE '%DEFAULT_LINE%' OR NAME LIKE '%PORTAL_NUMBER%' LIMIT 40;"
echo '=== js hits ==='
grep -ril 'voiso\|cc-ams04\|click2call' /home/bitrix/www/bitrix/js /home/bitrix/www/local /home/bitrix/www/bitrix/templates /home/bitrix/www/bitrix/php_interface 2>/dev/null | head -40
echo '=== done ==='
