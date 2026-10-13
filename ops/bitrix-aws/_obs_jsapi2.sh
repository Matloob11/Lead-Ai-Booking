#!/bin/bash
wc -l /home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js
echo '==== addItem fn ===='
python3 - <<'PY'
from pathlib import Path
t=Path('/home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js').read_text()
i=t.find('addItem(')
print(t[i:i+900])
print('---GETITEMS---')
j=t.find('getItems(')
print(t[j:j+400])
print('---SHOW---')
k=t.find('\tshow(')
print('k',k)
print(t[k:k+500] if k>=0 else t[t.find('show('):t.find('show(')+500])
print('---SELECT---')
for needle in ['item.select(','addItem(Item','new Item']:
    print(needle, t.find(needle))
PY
echo '==== Item class ===='
ls /home/bitrix/www/bitrix/js/ui/entity-selector/src/item | head
echo '==== filter dist ===='
ls /home/bitrix/www/bitrix/js/main/filter | head
