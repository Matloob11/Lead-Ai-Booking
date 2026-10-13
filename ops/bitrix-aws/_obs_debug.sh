#!/bin/bash
echo '==== GetListEx OBSERVER ===='
grep -n "OBSERVER\|AfterPrepareSql\|ExecuteModuleEvent" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php | head -40
echo '==== list builder callbacks ===='
python3 - <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/crm/classes/general/crm_entity_list_builder.php')
t=p.read_text(errors='replace')
for n in ['AfterPrepareSql','ExecuteModuleEvent','arFilter','fnAfter']:
    print(n, t.count(n))
i=t.find('AfterPrepareSql')
print(t[max(0,i-400):i+800])
PY
echo '==== listfilter entity selector apply ===='
python3 - <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/crm/lib/filter/listfilter.php')
t=p.read_text(errors='replace')
i=t.find('TYPE_ENTITY_SELECTOR')
print(t[i:i+2500][:2500])
print('--- assigned all-users ---')
j=t.find('all-users')
print(t[j-400:j+600])
PY
echo '==== kanban ajax ===='
ls /home/bitrix/www/bitrix/components/bitrix/crm.kanban/
grep -n "action\|getitems\|filter" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/ajax.php 2>/dev/null | head
echo '==== lead data provider observer field ===='
grep -n "OBSERVER\|isEnableAllUsers" /home/bitrix/www/bitrix/modules/crm/lib/filter/leaddataprovider.php | head -20
echo '==== recent nginx kanban ===='
grep -l "crm.kanban\|kanban" /var/log/nginx/access.log 2>/dev/null | head
tail -c 200000 /var/log/nginx/access.log 2>/dev/null | grep -o "crm[^ ]*kanban[^ ]*" | sort | uniq -c | sort -nr | head
