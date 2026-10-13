#!/bin/bash
python3 <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/main/lib/db/connection.php')
t=p.read_text(errors='replace')
print('exists', p.exists(), 'len', len(t))
for n in ['Event','query(','OnSql','executeModule']:
    print(n, t.count(n))
i=t.find('public function query')
print(t[i:i+900] if i>=0 else 'no query')
PY
echo '==== mysqli ===='
python3 <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/main/lib/db/mysqliconnection.php')
t=p.read_text(errors='replace') if p.exists() else ''
print('len', len(t))
i=t.find('function query')
print(t[i:i+600])
PY
echo '==== EntityHandler internalize ===='
grep -n "function internalize\|OBSERVER\|json_decode" /home/bitrix/www/bitrix/modules/crm/lib/ui/filter/entityhandler.php | head
echo '==== applySubQueryBasedFilters ===='
grep -n "function applySubQueryBasedFilters\|OBSERVER" /home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php | head
echo '==== applyFilterDataProviderSubQueryFilter ===='
grep -n "function applyFilterDataProviderSubQueryFilter" -r /home/bitrix/www/bitrix/modules/crm --include='*.php' | head
