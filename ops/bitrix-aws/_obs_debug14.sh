#!/bin/bash
echo '==== lead listentity ===='
cat /home/bitrix/www/bitrix/modules/crm/lib/listentity/lead.php | head -80
echo '==== filter options class ===='
find /home/bitrix/www/bitrix/modules -name '*.php' | xargs grep -l "class Options" 2>/dev/null | grep -i filter | head
echo '==== UiFilterOptions ===='
grep -n "class Options" /home/bitrix/www/bitrix/modules/main/lib/ui/filter/*.php 2>/dev/null | head
ls /home/bitrix/www/bitrix/modules/main/lib/ui/filter/ 2>/dev/null | head
ls /home/bitrix/www/bitrix/modules/ui/lib/entityselector 2>/dev/null | head
