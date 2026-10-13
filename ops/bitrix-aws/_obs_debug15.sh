#!/bin/bash
grep -n "kanban.entity.lead\|Kanban\\\\Entity\\\\Lead" /home/bitrix/www/bitrix/modules/crm/.settings.php | head
echo '==== Options GetFilter ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/main/lib/UI/Filter/Options.php').read_text()
print('len', len(t))
for n in ['function GetFilter','function getFilter','Event','Execute']:
    print(n, t.find(n), t.count(n))
i=t.find('function GetFilter')
if i<0: i=t.find('function getFilter')
print(t[i:i+1200])
PY
echo '==== listentity services ===='
grep -n "listEntity" /home/bitrix/www/bitrix/modules/crm/.settings.php | head
