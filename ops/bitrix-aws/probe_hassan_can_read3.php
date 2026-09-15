<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('intranet');

global $USER;
$USER = new CUser();
$USER->Authorize(2560);

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$item = $factory->getItem(89463);
$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(2560);

echo "canReadType=" . ($up->canReadType(1042) ? 'Y' : 'N') . "\n";
echo "canReadTypeInCategory13=" . ($up->canReadTypeInCategory(1042, 13) ? 'Y' : 'N') . "\n";
echo "canReadItem=" . ($up->canReadItem($item) ? 'Y' : 'N') . "\n";
echo "checkReadPermissions=" . ($up->checkReadPermissions(1042, 89463, 13) ? 'Y' : 'N') . "\n";
echo "canUpdateItem=" . ($up->canUpdateItem($item) ? 'Y' : 'N') . "\n";

$deps = CIntranetUtils::GetUserDepartments(2560);
echo "deps=" . json_encode($deps) . "\n";
$emp = CIntranetUtils::GetDepartmentEmployees($deps, true, false, 'Y');
if (is_object($emp) && method_exists($emp, 'Fetch')) {
    $ids = [];
    while ($r = $emp->Fetch()) {
        $ids[] = (int) $r['ID'];
    }
    sort($ids);
    echo "emp_count=" . count($ids) . " ids=" . implode(',', $ids) . "\n";
    echo "has2303=" . (in_array(2303, $ids, true) ? 'Y' : 'N') . "\n";
}

$emp2 = CIntranetUtils::GetDepartmentEmployees(69, true, true, 'Y');
if (is_object($emp2) && method_exists($emp2, 'Fetch')) {
    $ids = [];
    while ($r = $emp2->Fetch()) {
        $ids[] = (int) $r['ID'];
    }
    sort($ids);
    echo "dept69 count=" . count($ids) . " ids=" . implode(',', $ids) . "\n";
}

$perms = new CCrmPerms(2560);
echo "C13 READ=" . var_export($perms->GetPermType('DYNAMIC_1042_C13', 'READ'), true) . "\n";
echo "C13 WRITE=" . var_export($perms->GetPermType('DYNAMIC_1042_C13', 'WRITE'), true) . "\n";

// Try ATTR D like classic head-of-dept
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

// Temporarily set ATTR=D and see
$m->query("UPDATE b_crm_role_perms SET ATTR='D' WHERE ROLE_ID=54 AND ENTITY='DYNAMIC_1042_C13' AND PERM_TYPE='READ' AND FIELD='-'");
// clear perms cache for user
if (class_exists('CCrmPerms') && method_exists('CCrmPerms', 'ClearUserCache')) {
    CCrmPerms::ClearUserCache(2560);
}
$perms2 = new CCrmPerms(2560);
echo "after ATTR=D C13 READ=" . var_export($perms2->GetPermType('DYNAMIC_1042_C13', 'READ'), true) . "\n";
$up2 = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(2560);
// need new instance - may cache
echo "after canReadItem=" . ($up2->canReadItem($item) ? 'Y' : 'N') . "\n";
echo "after checkRead=" . ($up2->checkReadPermissions(1042, 89463, 13) ? 'Y' : 'N') . "\n";
