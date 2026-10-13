#!/bin/bash
echo '==== decode user entity selector ===='
grep -n "user\".*json\|json_decode\|entityId\|\[\"user\"" /home/bitrix/www/bitrix/modules/crm/lib/filter/listfilter.php | head
python3 <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/modules/crm/lib/filter/listfilter.php').read_text()
# print whole file length and search user
for n in ['json_decode','user_','EntitySelector','extractId','parseValue']:
    print(n, t.count(n), t.find(n))
print('--- file ---')
print(t[2000:4500])
PY
echo '==== ui filter conversion ===='
grep -rn "\[\"user\"" /home/bitrix/www/bitrix/modules/crm --include='*.php' | head -20
grep -rn "json_decode" /home/bitrix/www/bitrix/modules/crm/lib/filter --include='*.php' | head
echo '==== ListEntity entity getItems ===='
sed -n '1,160p' /home/bitrix/www/bitrix/modules/crm/lib/listentity/entity.php
