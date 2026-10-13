#!/bin/bash
echo '==== lead getGridId ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity/lead.php').read_text()
print('getGridId' in t)
t2=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t2.find('function getGridId')
print(t2[i:i+700])
PY
echo '==== all all-agents options ===='
mysql --defaults-file=/root/.my.cnf -e "SELECT USER_ID, CATEGORY, NAME, LENGTH(VALUE) FROM b_user_option WHERE VALUE LIKE '%all-agents%';" sitemanager
echo '==== ajax.old get action ===='
grep -n "function\|action\|Kanban" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/ajax.old.php | head -40
echo '==== Entity getInstance cache key ===='
sed -n '2046,2085p' /home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php
