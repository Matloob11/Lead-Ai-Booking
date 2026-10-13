#!/bin/bash
grep -n "OBSERVER_IDS\|filterObserver\|HAS_OBSERVER" /home/bitrix/www/bitrix/modules/crm/lib/filter/leaddataprovider.php 2>/dev/null | head -30
echo '===='
grep -n "OBSERVER" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php 2>/dev/null | head -20
echo '==== kanban'
grep -n "OBSERVER" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/class.php 2>/dev/null | head -25
