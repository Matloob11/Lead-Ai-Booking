#!/bin/bash
sed -n '760,850p' /home/bitrix/www/bitrix/modules/crm/lib/Service/UserPermissions.php
echo '==== grep PermissionAttr ==='
grep -rn "DEPARTMENT\|SUBDEPARTMENT\|class Permission" /home/bitrix/www/bitrix/modules/crm/lib/Security/Role -n 2>/dev/null | head -40
echo '==== BX_CRM_PERM ==='
grep -rn "BX_CRM_PERM_DEPARTMENT\|BX_CRM_PERM_SUBDEPARTMENT\|define.*CRM_PERM" /home/bitrix/www/bitrix/modules/crm --include='*.php' 2>/dev/null | head -30
echo '==== settings decode ==='
grep -rn "SUBDEPARTMENTS\|DEPARTMENT\|PermissionSettings" /home/bitrix/www/bitrix/modules/crm/lib/Security --include='*.php' 2>/dev/null | head -40
