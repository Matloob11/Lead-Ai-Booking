#!/bin/bash
python3 <<'PY'
import subprocess
raw=subprocess.check_output(["mysql","--defaults-file=/root/.my.cnf","-N","-e","SELECT VALUE FROM b_user_option WHERE ID=1068925;","sitemanager"])
text=raw.decode('latin1','replace')
print('len',len(text))
i=text.find('all-agents')
print('idx',i)
print(repr(text[max(0,i-600):i+400]))
print('\n==== OBSERVER_IDS snippets ====')
start=0
while True:
    j=text.find('OBSERVER', start)
    if j<0: break
    print(repr(text[j:j+180]))
    start=j+8
PY
echo '==== ListEntity getItems ===='
python3 <<'PY'
from pathlib import Path
import os
root='/home/bitrix/www/bitrix/modules/crm/lib/listentity'
for dirpath,_,files in os.walk(root):
    for f in files:
        if f.endswith('.php'):
            p=os.path.join(dirpath,f)
            t=open(p,encoding='utf-8',errors='replace').read()
            if 'getItems' in t or 'OBSERVER' in t:
                print(p, 'getItems', t.count('getItems'), 'OBS', t.count('OBSERVER'))
PY
echo '==== normalizeArrayValuesByInt ===='
sed -n '150,200p' /home/bitrix/www/bitrix/modules/main/lib/Type/Collection.php
echo '==== lead GetListEx filter remap around 400-590 ===='
sed -n '400,594p' /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php | head -80
grep -n "OBSERVER\|trimFilter\|PrepareFilter\|arFilter\[" /home/bitrix/www/bitrix/modules/crm/lib/listentity -r | head
