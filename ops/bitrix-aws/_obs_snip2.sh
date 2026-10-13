#!/bin/bash
sed -n '200,280p' /home/bitrix/www/bitrix/modules/crm/lib/filter/entitydataprovider.php
echo '===== SQL ====='
sed -n '500,560p' /home/bitrix/www/bitrix/modules/crm/classes/general/entity_helper.php
