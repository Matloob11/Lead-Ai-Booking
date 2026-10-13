#!/bin/bash
echo '==== userbasedfield ===='
cat /home/bitrix/www/bitrix/modules/crm/lib/filter/fieldstransform/userbasedfield.php
echo '==== ajax.old get filter ===='
grep -n "filter\|Filter\|OBSERVER" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/ajax.old.php | head -40
echo '==== Options getFilter event ===='
grep -n "Event\|ExecuteModule\|getFilter\|tmp_filter" /home/bitrix/www/bitrix/modules/main/lib/ui/filter/options.php | head -40
echo '==== extract entity selector value ===='
grep -n "json_decode\|EntitySelector\|user\"," /home/bitrix/www/bitrix/modules/crm/lib/filter/fieldstransform -r | head
ls /home/bitrix/www/bitrix/modules/crm/lib/filter/fieldstransform/
echo '==== convertFilterValue ===='
grep -rn "function convert\|json_decode" /home/bitrix/www/bitrix/modules/crm/lib/component/entitylist --include='*.php' | head
