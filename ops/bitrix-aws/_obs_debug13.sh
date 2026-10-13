#!/bin/bash
echo '==== entity_helper subquery ===='
sed -n '480,532p' /home/bitrix/www/bitrix/modules/crm/classes/general/entity_helper.php
echo '==== EntityHandler internalize ===='
sed -n '1,120p' /home/bitrix/www/bitrix/modules/crm/lib/ui/filter/entityhandler.php
echo '==== applySubQueryBasedFilters fn ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t.find('function applySubQueryBasedFilters')
print('idx', i)
print(t[i:i+1800] if i>=0 else 'NO')
PY
echo '==== convertEntityFilterValues ===='
grep -n "function convertEntityFilterValues" -r /home/bitrix/www/bitrix/modules/crm --include='*.php' | head
