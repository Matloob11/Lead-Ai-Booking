#!/bin/bash
echo '==== =OBSERVER_IDS occurrences ===='
grep -n "=OBSERVER_IDS\|OBSERVER_IDS" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php | head -40
echo '==== entity helper / listfilter more ===='
grep -rn "OBSERVER_IDS" /home/bitrix/www/bitrix/modules/crm --include='*.php' | grep -v lang | grep -v install | head -50
echo '==== kanban Entity Lead getItems ===='
ls /home/bitrix/www/bitrix/modules/crm/lib/kanban/entity/
grep -n "GetListEx\|getItems\|Filter\|OBSERVER" /home/bitrix/www/bitrix/modules/crm/lib/kanban/entity/lead.php | head -30
echo '==== user option dump all-agents ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT USER_ID, NAME, LENGTH(VALUE), VALUE LIKE '%all-agents%', VALUE LIKE '%OBSERVER%' FROM b_user_option WHERE VALUE LIKE '%all-agents%' LIMIT 20;" sitemanager
echo '==== extract observer part ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT USER_ID, NAME FROM b_user_option WHERE VALUE LIKE '%all-agents%';" sitemanager
