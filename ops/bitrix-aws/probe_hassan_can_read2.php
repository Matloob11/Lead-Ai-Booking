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
echo "canViewItemsInCategory13=" . ($up->canViewItemsInCategory(1042, 13) ? 'Y' : 'N') . "\n";
echo "canReadItem=" . ($up->canReadItem($item) ? 'Y' : 'N') . "\n";
echo "checkReadPermissions=" . ($up->checkReadPermissions(1042, 89463, 13) ? 'Y' : 'N') . "\n";

$available = $up->filterAvailableForReadingCategories(1042, [13, 14]);
echo "availableCats=" . json_encode($available) . "\n";

// Department employees
$deps = CIntranetUtils::GetUserDepartments(2560);
echo "deps=" . json_encode($deps) . "\n";
$emp = CIntranetUtils::GetDepartmentEmployees($deps, true, false, 'Y');
echo "emp class=" . (is_object($emp) ? get_class($emp) : gettype($emp)) . "\n";
if (is_object($emp) && method_exists($emp, 'Fetch')) {
    $ids = [];
    while ($r = $emp->Fetch()) {
        $ids[] = (int)$r['ID'];
    }
    sort($ids);
    echo "emp_count=" . count($ids) . " ids=" . implode(',', $ids) . "\n";
    echo "has2303=" . (in_array(2303, $ids, true) ? 'Y' : 'N') . "\n";
    echo "has2344=" . (in_array(2344, $ids, true) ? 'Y' : 'N') . "\n";
}

// Try GetDepartmentEmployees with head flag
$emp2 = CIntranetUtils::GetDepartmentEmployees(69, true, true, 'Y');
if (is_object($emp2) && method_exists($emp2, 'Fetch')) {
    $ids = [];
    while ($r = $emp2->Fetch()) {
        $ids[] = (int)$r['ID'];
    }
    sort($ids);
    echo "dept69 recursive head-mode count=" . count($ids) . " ids=" . implode(',', array_slice($ids, 0, 30)) . "\n";
}

// What does attr A mean in GetEntityAttr?
$perms = new CCrmPerms(2560);
echo "attrs C13=" . var_export($perms->GetEntityAttr('DYNAMIC_1042_C13', [89463]), true) . "\n";

// List permission SETTINGS parsed
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$q = $m->query("SELECT ENTITY,PERM_TYPE,ATTR,SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY IN ('DYNAMIC_1042_C13','DYNAMIC_1042') AND PERM_TYPE='READ'");
while ($r = $q->fetch_assoc()) {
    echo "perm " . json_encode($r) . "\n";
}

// Compare with a role that works - Head of department ATTR D
$q = $m->query("SELECT ENTITY,PERM_TYPE,ATTR,SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=5 AND ENTITY LIKE '%LEAD%' AND PERM_TYPE='READ'");
while ($r = $q->fetch_assoc()) {
    echo "role5 " . json_encode($r) . "\n";
}
