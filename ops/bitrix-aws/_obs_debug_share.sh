#!/bin/bash
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/classes/general/crm_entity_list_builder.php').read_text()
i=t.find("arUserSql['WHERE']")
print('count WHERE user', t.count("arUserSql['WHERE']"))
print(t[i:i+900])
print('==== PERMISSION UNION ====')
for n in ['UNION', 'PERMISSION', 'Add2SqlData']:
    print(n, t.count(n))
j=t.find('PERMISSION')
print(t[j:j+400] if j>=0 else '')
PY
echo '==== fillStageTotalSums lead/kanban ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t.find('function fillStageTotalSums')
print(t[i:i+2200])
PY
echo '==== alisha / bharat share ===='
mysql --defaults-file=/root/.my.cnf -N -e "
SELECT L.ID, LEFT(L.TITLE,60), L.ASSIGNED_BY_ID, L.STATUS_ID,
  (SELECT COUNT(*) FROM a7_lead_share S WHERE S.LEAD_ID=L.ID) shares
FROM b_crm_lead L
WHERE L.TITLE LIKE '%Alisha%' OR L.TITLE LIKE '%Bharat Kanar%' OR L.TITLE LIKE '%Bushra Bashir%'
ORDER BY L.ID DESC LIMIT 15;
" sitemanager
echo '==== share vs live leads ===='
mysql --defaults-file=/root/.my.cnf -N -e "
SELECT
 (SELECT COUNT(DISTINCT LEAD_ID) FROM a7_lead_share) share_ids,
 (SELECT COUNT(DISTINCT S.LEAD_ID) FROM a7_lead_share S JOIN b_crm_lead L ON L.ID=S.LEAD_ID) share_live,
 (SELECT COUNT(*) FROM b_crm_lead WHERE STATUS_ID='NEW') newc;
" sitemanager
echo '==== 2311 current filter snippet ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT USER_ID, NAME, LOCATE('shared-leads', VALUE), LOCATE('all-agents', VALUE), LOCATE('OBSERVER', VALUE) FROM b_user_option WHERE VALUE LIKE '%shared-leads%' OR (USER_ID=2311 AND NAME='CRM_LEAD_LIST_V12' AND CATEGORY='main.ui.filter');" sitemanager
