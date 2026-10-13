#!/bin/bash
sed -n '7880,7950p' /home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js
echo '==== addItem ===='
sed -n '9160,9220p' /home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js
echo '==== getItems ===='
sed -n '11790,11840p' /home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js
echo '==== Item select ===='
grep -n "selectItem\|select(" /home/bitrix/www/bitrix/js/ui/entity-selector/src/dialog/dialog.js | head
echo '==== filter entity selector ===='
grep -n "entity-selector\|EntitySelector\|OBSERVER" /home/bitrix/www/bitrix/js/main/filter/src/filter.js | head
ls /home/bitrix/www/bitrix/js/main/filter/src | head
