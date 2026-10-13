from pathlib import Path
p = Path('/home/bitrix/www/bitrix/modules/crm/lib/filter/entitydataprovider.php')
t = p.read_text()
i = t.find('function getUserEntitySelectorParams')
print('idx', i)
print(t[i:i+2800] if i>=0 else 'MISSING')
