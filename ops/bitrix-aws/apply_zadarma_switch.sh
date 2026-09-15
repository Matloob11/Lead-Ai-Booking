#!/usr/bin/env bash
set -eu
sed -i 's/\r$//' /tmp/disable_voiso_handlers.php /tmp/patch_owner_phone_e164.php /tmp/a7_owner_data_call.js /tmp/a7_renewals_call.js

echo "=== 1 disable voiso ==="
php /tmp/disable_voiso_handlers.php

echo "=== 2 patch e164 ==="
php /tmp/patch_owner_phone_e164.php

echo "=== 3 deploy js ==="
cp -a /home/bitrix/www/bitrix/js/a7_owner_data_call.js "/home/bitrix/www/bitrix/js/a7_owner_data_call.js.bak.pre_zadarma_$(date +%Y%m%d_%H%M%S)"
cp -a /home/bitrix/www/bitrix/js/a7_renewals_call.js "/home/bitrix/www/bitrix/js/a7_renewals_call.js.bak.pre_zadarma_$(date +%Y%m%d_%H%M%S)"
cp /tmp/a7_owner_data_call.js /home/bitrix/www/bitrix/js/a7_owner_data_call.js
cp /tmp/a7_renewals_call.js /home/bitrix/www/bitrix/js/a7_renewals_call.js
chown bitrix:bitrix /home/bitrix/www/bitrix/js/a7_owner_data_call.js /home/bitrix/www/bitrix/js/a7_renewals_call.js
chmod 644 /home/bitrix/www/bitrix/js/a7_owner_data_call.js /home/bitrix/www/bitrix/js/a7_renewals_call.js

echo "=== 4 verify js ==="
grep -n "Zadarma\|Voiso\|dialVia" /home/bitrix/www/bitrix/js/a7_owner_data_call.js | head -20

echo "=== 5 verify events ==="
php /tmp/probe_call_handlers.php

echo "DONE"
