#!/bin/bash
echo '==== filter option rows ===='
mysql --defaults-file=/root/.my.cnf -e "SELECT ID, USER_ID, CATEGORY, NAME, LENGTH(VALUE) FROM b_user_option WHERE VALUE LIKE '%all-agents%';" sitemanager
python3 - <<'PY'
import subprocess
import php as _  # no
raw=subprocess.check_output(["mysql","--defaults-file=/root/.my.cnf","-N","-e","SELECT VALUE FROM b_user_option WHERE VALUE LIKE '%all-agents%' LIMIT 1;","sitemanager"])
text=raw.decode('utf-8','replace')
i=text.find('all-agents')
print('len',len(text),'idx',i)
print(text[max(0,i-500):i+500])
# also OBSERVER_IDS nearby
j=text.find('OBSERVER_IDS')
print('observer idx', j)
print(text[j:j+400] if j>=0 else 'none')
PY
echo '==== kanban getItems function ===='
python3 - <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
import re
for m in re.finditer(r'function getItems\w*\(', t):
    print(m.group(), m.start())
i=t.find('function getItems(')
print('exact', i)
print(t[i:i+3500] if i>=0 else 'NO')
print('--- GetListEx context ---')
j=t.find('GetListEx')
print(t[j-200:j+800])
PY
echo '==== Collection normalizeArrayValuesByInt ===='
grep -n "function normalizeArrayValuesByInt" -r /home/bitrix/www/bitrix/modules/main --include='*.php' | head
