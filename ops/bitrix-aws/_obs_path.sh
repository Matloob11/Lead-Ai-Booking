#!/bin/bash
echo '==== entity_helper observers ===='
grep -n -A 25 "prepareObserversFieldFilter" /home/bitrix/www/bitrix/modules/crm/classes/general/entity_helper.php | head -40
echo '==== listfilter OBSERVER ===='
grep -n "OBSERVER\|all-users\|TYPE_ENTITY_SELECTOR" /home/bitrix/www/bitrix/modules/crm/lib/filter/listfilter.php | head -30
echo '==== kanban getFilter ===='
grep -n "getFilter\|FILTER\|applyFilter" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/class.php | head -25
echo '==== js public ===='
curl -skI "https://crm.a7grouprealestatedxb.com/bitrix/js/a7_observer_filter.js" | head -15
