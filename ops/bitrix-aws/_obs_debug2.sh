#!/bin/bash
echo '==== AfterPrepareSql OBSERVER block ===='
sed -n '750,790p' /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php
echo '==== listfilter entity_selector foreach ===='
python3 - <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/filter/listfilter.php').read_text()
i=t.find('foreach ($this->getFieldNamesByType(static::TYPE_ENTITY_SELECTOR)')
print(t[i:i+1200])
PY
echo '==== list builder afterPrepare call ===='
python3 - <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/classes/general/crm_entity_list_builder.php').read_text()
i=t.find('afterPrepareSqlCallback')
print('count', t.count('afterPrepareSqlCallback'))
idx=0
while True:
    j=t.find('afterPrepareSqlCallback', idx)
    if j<0: break
    print('---', j)
    print(t[j:j+500])
    print()
    idx=j+20
PY
echo '==== kanban class getFilter items ===='
python3 - <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/components/bitrix/crm.kanban/class.php').read_text()
for n in ['getFilter','GetListEx','OBSERVER','prepareFilter','FILTER']:
    print(n, t.find(n), t.count(n))
# print function around line 400
print(t[380:520])
PY
echo '==== ajax.php head ===='
head -80 /home/bitrix/www/bitrix/components/bitrix/crm.kanban/ajax.php
echo '==== saved filter options with all-agents ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT ID, USER_ID, CATEGORY, NAME, LEFT(VALUE,200) FROM b_user_option WHERE VALUE LIKE '%all-agents%' LIMIT 8;" sitemanager
mysql --defaults-file=/root/.my.cnf -N -e "SELECT ID, LEFT(FILTER,200) FROM b_filter WHERE FILTER LIKE '%all-agents%' OR FILTER LIKE '%OBSERVER%' LIMIT 8;" sitemanager 2>/dev/null || echo no_b_filter
