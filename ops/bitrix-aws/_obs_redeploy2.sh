#!/bin/bash
set -euo pipefail
install -o bitrix -g bitrix -m 644 /tmp/a7_observer_filter.php /home/bitrix/www/bitrix/php_interface/include/a7_observer_filter.php
install -o bitrix -g bitrix -m 644 /tmp/a7_observer_filter.js /home/bitrix/www/bitrix/js/a7_observer_filter.js
php -l /home/bitrix/www/bitrix/php_interface/include/a7_observer_filter.php
cd /home/bitrix/www
sudo -u bitrix php /tmp/_obs_php_test.php
ls -la /home/bitrix/www/bitrix/js/a7_observer_filter.js /home/bitrix/www/bitrix/php_interface/include/a7_observer_filter.php
grep -n a7_observer_filter /home/bitrix/www/bitrix/php_interface/init.php
