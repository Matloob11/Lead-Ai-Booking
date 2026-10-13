#!/bin/bash
sed -n '750,820p' /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php
echo '======= FILTER FIELD ======='
sed -n '90,130p' /home/bitrix/www/bitrix/modules/crm/lib/filter/leaddataprovider.php
echo '======= PREPARE ======='
sed -n '570,620p' /home/bitrix/www/bitrix/modules/crm/lib/filter/leaddataprovider.php
