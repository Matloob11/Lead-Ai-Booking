#!/bin/bash
echo '==== options file ===='
find /home/bitrix/www/bitrix/modules/main -name 'options.php' | head
echo '==== factory around transform ===='
sed -n '380,450p' /home/bitrix/www/bitrix/modules/crm/lib/filter/factory.php
echo '==== kanban.php around 700-760 ===='
sed -n '680,760p' /home/bitrix/www/bitrix/modules/crm/lib/kanban.php
echo '==== kanban.php 930-980 ===='
sed -n '920,980p' /home/bitrix/www/bitrix/modules/crm/lib/kanban.php
echo '==== entitydataprovider 70-110 ===='
sed -n '70,120p' /home/bitrix/www/bitrix/modules/crm/lib/filter/entitydataprovider.php
echo '==== settings UserBasedField ===='
sed -n '580,620p' /home/bitrix/www/bitrix/modules/crm/.settings.php
