#!/bin/bash
head -40 /home/bitrix/www/bitrix/modules/main/lib/UI/Filter/Options.php
echo '==== getFilter method ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/main/lib/UI/Filter/Options.php').read_text()
i=t.find('public function getFilter(')
print('idx', i)
print(t[i:i+900])
print('--- GetFilter ---')
print('GetFilter' in t)
PY
echo '==== kanban entity getFilterOptions ===='
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity/lead.php').read_text()
print(t[t.find('getFilterOptions'):t.find('getFilterOptions')+400])
t2=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t2.find('function getFilterOptions')
print('parent', i)
print(t2[i:i+400])
PY
