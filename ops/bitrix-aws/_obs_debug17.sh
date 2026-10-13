#!/bin/bash
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t.find('function prepareFilter')
print('idx', i)
print(t[i:i+700] if i>=0 else 'NO')
print('--- lead.php getItems ---')
t2=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity/lead.php').read_text()
j=t2.find('function getItems')
print(t2[j:j+500] if j>=0 else t2)
print('--- fillStageTotalSums sig ---')
k=t.find('function fillStageTotalSums')
print(t[k:k+250])
PY
echo '==== ServiceLocator addInstance replace? ===='
python3 <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/main/lib/di/servicelocator.php')
t=p.read_text()
i=t.find('function addInstance(')
print(t[i:i+700])
PY
