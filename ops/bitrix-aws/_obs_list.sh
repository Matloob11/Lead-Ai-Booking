#!/bin/bash
sed -n '140,360p' /home/bitrix/www/bitrix/modules/crm/lib/filter/listfilter.php
echo '===== provider ====='
grep -n "all-users\|getUserEntitySelectorParams" /home/bitrix/www/bitrix/modules/crm/lib/filter/dataprovider.php /home/bitrix/www/bitrix/modules/crm/lib/filter/entitydataprovider.php | head
