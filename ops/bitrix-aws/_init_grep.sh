#!/bin/bash
grep -n "A7_" /home/bitrix/www/bitrix/php_interface/init.php | head -40
echo '===='
grep -n "require\|include" /home/bitrix/www/bitrix/php_interface/init.php | head -40
