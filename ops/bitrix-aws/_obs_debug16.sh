#!/bin/bash
echo '==== kanban entity lead class ===='
sed -n '400,430p' /home/bitrix/www/bitrix/modules/crm/.settings.php
python3 <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity/lead.php')
print('exists', p.exists())
t=p.read_text() if p.exists() else ''
print('final' if 'final class' in t else 'open class')
print(t[:800])
print('--- getItems override', 'function getItems' in t)
print('fillStage', 'function fillStageTotalSums' in t)
PY
echo '==== how kanban gets entity ===='
grep -n "getInstance\|crm.kanban.entity.lead" /home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php | head
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
i=t.find('function getInstance')
print(t[i:i+900])
PY
echo '==== listentity Lead ===='
python3 <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/modules/crm/lib/listentity/entity/lead.php')
print('exists', p.exists())
print(p.read_text()[:600] if p.exists() else '')
PY
