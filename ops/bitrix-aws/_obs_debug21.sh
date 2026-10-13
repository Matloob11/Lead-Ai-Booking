#!/bin/bash
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/main/lib/DI/ServiceLocator.php').read_text()
i=t.find('function get(')
print(t[i:i+1200])
print('--- Entity instances ---')
t2=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
print('static $instances', t2.find('static $instances'), t2.find('$instances'))
print(t2[t2.find('protected static'):t2.find('protected static')+250])
PY
echo '==== kanban.php who calls prepareFilter vs getItems ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban.php').read_text()
for n in ['prepareFilter','fillStageTotalSums','getItems(','OBSERVER']:
    idx=0
    print('==', n, 'count', t.count(n))
    while True:
        i=t.find(n, idx)
        if i<0: break
        print(t[max(0,i-120):i+80].replace('\n',' | '))
        print('---')
        idx=i+len(n)
        if idx>i+5000: break
PY
echo '==== recent ajax around 12:20 utc ===='
grep "15:2[0-2].*kanban\|12:2[0-2].*kanban" /var/log/nginx/access.log | tail -20
echo '==== ajax.php actions ===='
grep -n "Action\|class " /home/bitrix/www/bitrix/modules/crm/lib/controller/kanban*.php 2>/dev/null | head
ls /home/bitrix/www/bitrix/modules/crm/lib/controller | grep -i kanban
