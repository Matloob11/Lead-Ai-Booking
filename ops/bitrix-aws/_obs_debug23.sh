#!/bin/bash
sed -n '1,90p' /home/bitrix/www/bitrix/components/bitrix/crm.kanban/ajax.old.php
echo '==== GridId value for lead ===='
grep -n "CRM_LEAD_LIST" /home/bitrix/www/bitrix/modules/crm/lib/component/entitylist/gridid.php | head
