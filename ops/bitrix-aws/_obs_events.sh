#!/bin/bash
grep -n "OnAfterCrmLeadFilter\|OnBeforeCrmLeadList\|OnBuildCrmFilterSql\|ExecuteModuleEventEx.*LeadFilter" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php | head
echo '==== helper events ===='
grep -n "OnBuildCrmFilterSql\|ExecuteModuleEventEx" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php /home/bitrix/www/bitrix/modules/crm/classes/general/entity_helper.php | head -30
echo '==== GetListEx start ===='
grep -n "function GetListEx\|arFilter" /home/bitrix/www/bitrix/modules/crm/classes/general/crm_lead.php | head -20
