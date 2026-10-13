#!/bin/bash
sed -n '595,610p' /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php
echo '==== list builder AfterPrepareSql ===='
grep -n "AfterPrepareSql\|__AfterPrepareSql" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_entity_list_builder.php | head
echo '==== kanban filter ===='
grep -n "OBSERVER\|arFilter\|FILTER" /home/bitrix/www/bitrix/components/bitrix/crm.kanban/class.php | head -25
