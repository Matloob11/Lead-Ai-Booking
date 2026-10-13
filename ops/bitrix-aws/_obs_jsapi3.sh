#!/bin/bash
python3 - <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/js/ui/entity-selector/src/item/item.js').read_text()
print('select fn')
i=t.find('\tselect(')
print(t[i:i+700])
print('--- constructor id ---')
print(t[t.find('constructor'):t.find('constructor')+800])
PY
echo '==== kanban apply filter ===='
python3 - <<'PY'
from pathlib import Path
import os
root='/home/bitrix/www/bitrix/components/bitrix/crm.kanban'
for dirpath, dirs, files in os.walk(root):
    for f in files:
        if f.endswith(('.js','.php')):
            p=os.path.join(dirpath,f)
            try:
                t=open(p,encoding='utf-8',errors='replace').read()
            except Exception:
                continue
            if 'OBSERVER' in t or 'applyFilter' in t:
                if 'OBSERVER' in t:
                    print('OBS', p)
PY
echo '==== prepareObserversFieldFilter ===='
grep -n "prepareObserversFieldFilter\|all-users\|OBSERVER_IDS" /home/bitrix/www/bitrix/modules/crm/classes/general/entity_helper.php | head
