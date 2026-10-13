#!/bin/bash
echo '==== callers ===='
grep -n "breakDepartmentsToUsers\|applyTransformWrapper\|UserBasedField" -r /home/bitrix/www/bitrix/modules/crm --include='*.php' | head -40
echo '==== lead data provider observer dialog ===='
sed -n '560,640p' /home/bitrix/www/bitrix/modules/crm/lib/filter/leaddataprovider.php
echo '==== kanban filter prepare ===='
python3 <<'PY'
from pathlib import Path
import os
root='/home/bitrix/www/bitrix/modules/crm/lib/kanban'
for dp,ds,fs in os.walk(root):
    for f in fs:
        if not f.endswith('.php'): continue
        p=os.path.join(dp,f)
        t=open(p,encoding='utf-8',errors='replace').read()
        if 'breakDepartments' in t or 'prepareListFilter' in t or 'OBSERVER_IDS' in t or 'applyTransform' in t:
            print(p)
            for n in ['breakDepartmentsToUsers','prepareListFilter','OBSERVER_IDS','applyTransform']:
                if n in t:
                    print(' ', n, t.find(n))
PY
