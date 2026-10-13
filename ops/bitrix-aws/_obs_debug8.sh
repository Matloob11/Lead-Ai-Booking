#!/bin/bash
echo '==== parse ["user" ===='
grep -rn 'json_decode' /home/bitrix/www/bitrix/modules/crm/lib --include='*.php' | grep -i 'filter\|entity\|user' | head -30
echo '==== EntitySelector conversion ===='
grep -rn "all-users\|entityId.*user\|\[0\].*user" /home/bitrix/www/bitrix/modules/crm/lib/filter --include='*.php' | head
echo '==== main filter FieldAdapter ===='
grep -rn "\[\"user\"" /home/bitrix/www/bitrix/modules --include='*.php' | head -25
echo '==== ItemIdentifier / convertFilter ===='
grep -n "OBSERVER_IDS" /home/bitrix/www/bitrix/modules/crm/lib/filter/factory.php /home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php | head
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t.find('prepareFilter')
print('prepareFilter', i)
print(t[i:i+1500] if i>=0 else '')
# getFilter method
j=t.find('function getFilter(')
print('getFilter', j)
print(t[j:j+900] if j>=0 else '')
PY
