#!/bin/bash
grep -n "function prepareObserversFieldFilter\|function getDepartmentSelectorParams\|isEnableAllUsers\|enableAll" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_entity_helper.php /home/bitrix/www/bitrix/modules/crm/lib/filter/*.php 2>/dev/null | head -40
echo '==== helper ===='
grep -n "prepareObserversFieldFilter" -r /home/bitrix/www/bitrix/modules/crm --include='*.php' | head
