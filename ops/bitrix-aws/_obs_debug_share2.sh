#!/bin/bash
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t.find('function getDataToCalculateTotalSums')
print(t[i:i+2500])
print('==== getItems Entity ====')
j=t.find('function getItems(array $parameters)')
print(t[j:j+800])
PY
echo '==== users with shared-leads option ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT USER_ID, NAME, LOCATE('shared-leads',VALUE) s, LOCATE('all-agents',VALUE) a FROM b_user_option WHERE VALUE LIKE '%shared-leads%';" sitemanager
echo '==== contacted stage id ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT STATUS_ID, NAME, SORT FROM b_crm_status WHERE ENTITY_ID='STATUS' ORDER BY SORT;" sitemanager | head -20
echo '==== IN_PROCESS count shared vs all ===='
mysql --defaults-file=/root/.my.cnf -N -e "
SELECT
 (SELECT COUNT(*) FROM b_crm_lead WHERE STATUS_ID='IN_PROCESS') all_inp,
 (SELECT COUNT(*) FROM b_crm_lead L JOIN (SELECT DISTINCT LEAD_ID FROM a7_lead_share) S ON S.LEAD_ID=L.ID WHERE L.STATUS_ID='IN_PROCESS') share_inp;
" sitemanager
