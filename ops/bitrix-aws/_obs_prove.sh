#!/bin/bash
mysql --defaults-file=/root/.my.cnf -N -e "SELECT COUNT(DISTINCT USER_ID) AS users, COUNT(DISTINCT ENTITY_ID) AS leads FROM b_crm_observer WHERE ENTITY_TYPE_ID=1;" sitemanager
echo '==== sample observer users ===='
mysql --defaults-file=/root/.my.cnf -N -e "SELECT USER_ID, COUNT(*) c FROM b_crm_observer WHERE ENTITY_TYPE_ID=1 GROUP BY USER_ID ORDER BY c DESC LIMIT 8;" sitemanager
echo '==== kanban ajax script names ===='
grep -n "crm.kanban\|FILTER\|OBSERVER" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/ajax.php | head -20
echo '==== js served ===='
head -c 80 /home/bitrix/www/bitrix/js/a7_observer_filter.js; echo
echo '==== entity selector Dialog methods ===='
python3 - <<'PY'
from pathlib import Path
p=Path('/home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js')
if not p.exists():
    p=Path('/home/bitrix/www/bitrix/js/ui/entity-selector/dist/entity-selector.bundle.js')
print('exists', p.exists(), p)
text=p.read_text(errors='replace') if p.exists() else ''
for needle in ['selectItem(','addItem(','setItems(','getItems(','show()']:
    print(needle, text.find(needle))
PY
