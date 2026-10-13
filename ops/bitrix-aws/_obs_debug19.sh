#!/bin/bash
sed -n '40,80p' /home/bitrix/www/bitrix/modules/main/lib/DI/ServiceLocator.php
echo '==== lead list component filter after transform ===='
sed -n '900,930p' /home/bitrix/www/bitrix/modules/crm/install/components/bitrix/crm.lead.list/component.php
