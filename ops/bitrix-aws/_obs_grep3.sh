#!/bin/bash
grep -n "function getUserEntitySelectorParams\|isEnableAllUsers\|all-users\|USER_TYPE_ALLUSERS\|enableAllUsers" /home/bitrix/www/bitrix/modules/crm/lib/filter/*.php | head -40
echo '==== main filter ===='
grep -rn "isEnableAllUsers" /home/bitrix/www/bitrix/modules/main/lib/filter /home/bitrix/www/bitrix/modules/ui/lib --include='*.php' 2>/dev/null | head -20
