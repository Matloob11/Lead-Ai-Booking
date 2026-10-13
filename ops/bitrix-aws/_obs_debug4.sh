#!/bin/bash
python3 - <<'PY'
import subprocess,re
raw=subprocess.check_output(["mysql","--defaults-file=/root/.my.cnf","-N","-e","SELECT VALUE FROM b_user_option WHERE USER_ID=2311 AND NAME='CRM_LEAD_LIST_V12' LIMIT 1;","sitemanager"],text=True,errors='replace')
print('len', len(raw))
# find all-agents context
i=raw.find('all-agents')
print('idx', i)
print(raw[max(0,i-400):i+400])
print('--- OBSERVER keys ---')
for m in re.finditer(r'OBSERVER.{0,80}', raw):
    if m.start()>0 and m.start()<len(raw):
        s=m.group(0)
        if 'all-agents' in s or 'user_' in s or 'IDS' in s:
            print(s[:120])
PY
echo '==== how kanban maps filter to list ===='
python3 - <<'PY'
from pathlib import Path
# parent Entity getItems
p=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php')
t=p.read_text(errors='replace')
print('file', p, 'len', len(t))
for n in ['GetListEx','OBSERVER','prepareFilter','getFilter','=OBSERVER','applyFilter']:
    print(n, t.count(n))
i=t.find('function getItems')
print('getItems', i)
print(t[i:i+2500] if i>=0 else 'no getItems')
PY
echo '==== filter converter OBSERVER ===='
grep -n "OBSERVER_IDS" /home/bitrix/www/bitrix/modules/crm/lib/filter/*.php | head
grep -rn "OBSERVER_IDS" /home/bitrix/www/bitrix/modules/crm/lib --include='*.php' | grep -i 'filter\|convert\|prepare' | head -40
