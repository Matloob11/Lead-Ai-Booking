#!/bin/bash
sed -n '160,230p' /home/bitrix/www/bitrix/php_interface/include/a7_stage_admin.php
echo '==== init stage ===='
sed -n '615,640p' /home/bitrix/www/bitrix/php_interface/init.php
