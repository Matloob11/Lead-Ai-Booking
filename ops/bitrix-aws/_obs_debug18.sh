#!/bin/bash
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/kanban/entity.php').read_text()
idx=0
while True:
    i=t.find('prepareFilter', idx)
    if i<0: break
    print('---', i, t[i-80:i+180].replace('\n',' '))
    idx=i+12
print('count', t.count('prepareFilter'))
PY
echo '==== locator ===='
ls /home/bitrix/www/bitrix/modules/main/lib/DI 2>/dev/null
ls /home/bitrix/www/bitrix/modules/main/lib/di 2>/dev/null
grep -n "function addInstance" /home/bitrix/www/bitrix/modules/main/lib/DI/ServiceLocator.php /home/bitrix/www/bitrix/vendor/bitrix/main/lib/DI/servicelocator.php 2>/dev/null | head
find /home/bitrix/www/bitrix/modules/main -name '*ervicelocator*' | head
