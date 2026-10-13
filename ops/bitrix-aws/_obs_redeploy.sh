#!/bin/bash
set -euo pipefail
install -o bitrix -g bitrix -m 644 /tmp/a7_observer_filter.php /home/bitrix/www/bitrix/php_interface/include/a7_observer_filter.php
install -o bitrix -g bitrix -m 644 /tmp/a7_observer_filter.js /home/bitrix/www/bitrix/js/a7_observer_filter.js
php -l /home/bitrix/www/bitrix/php_interface/include/a7_observer_filter.php
install -o bitrix -g bitrix -m 644 /tmp/_obs_php_test.php /tmp/_obs_php_test.php
cd /home/bitrix/www
sudo -u bitrix php /tmp/_obs_php_test.php
