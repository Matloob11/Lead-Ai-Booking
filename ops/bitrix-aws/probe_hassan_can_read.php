<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$hassan = 2560;
$itemId = 89463; // assigned to 2303 Ruqia, cat 13

// Force user context
global $USER;
if (!is_object($USER)) {
    $USER = new CUser();
}
$USER->Authorize($hassan);
echo "auth_user=" . $USER->GetID() . "\n";

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
if (!$factory) {
    fwrite(STDERR, "no factory 1042\n");
    exit(1);
}
$item = $factory->getItem($itemId);
echo "item=" . ($item ? $item->getId() . ' assigned=' . $item->getAssignedById() . ' cat=' . $item->getCategoryId() : 'null') . "\n";

$userPerms = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($hassan);
echo "class userPerms=" . get_class($userPerms) . "\n";

// Try common methods
$methods = get_class_methods($userPerms);
foreach ($methods as $m) {
    if (stripos($m, 'read') !== false || stripos($m, 'item') !== false || stripos($m, 'check') !== false) {
        // only list interesting
        if (stripos($m, 'Read') !== false || stripos($m, 'Item') !== false || stripos($m, 'Check') !== false) {
            echo "method $m\n";
        }
    }
}

if (method_exists($userPerms, 'itemIsReadable')) {
    echo "itemIsReadable=" . ($userPerms->itemIsReadable($item) ? 'Y' : 'N') . "\n";
}
if (method_exists($userPerms, 'checkReadPermissions')) {
    try {
        echo "checkReadPermissions entity=" . json_encode($userPerms->checkReadPermissions(\CCrmOwnerType::ResolveName(1042) ?: 1042)) . "\n";
    } catch (Throwable $e) {
        echo "checkReadPermissions err " . $e->getMessage() . "\n";
    }
}

// Entity permission
try {
    $entityName = $factory->getEntityName(); // DYNAMIC_1042
    echo "entityName=$entityName\n";
} catch (Throwable $e) {
    echo "entityName err\n";
}

// CCrmPerms legacy
$perms = new \CCrmPerms($hassan);
$attr = $perms->GetPermType('DYNAMIC_1042_C13', 'READ');
echo "CCrmPerms DYNAMIC_1042_C13 READ attr=" . var_export($attr, true) . "\n";
$attr2 = $perms->GetPermType('DYNAMIC_1042', 'READ');
echo "CCrmPerms DYNAMIC_1042 READ attr=" . var_export($attr2, true) . "\n";
$attr3 = $perms->GetPermType('LEAD', 'READ');
echo "CCrmPerms LEAD READ attr=" . var_export($attr3, true) . "\n";

// Department members for Hassan
$deps = \CIntranetUtils::GetUserDepartments($hassan);
echo "hassan deps=" . json_encode($deps) . "\n";
if ($deps) {
    $employees = \CIntranetUtils::GetDepartmentEmployees($deps, true, false, 'Y');
    // may return different shapes
    echo "dept employees type=" . gettype($employees) . "\n";
    if (is_array($employees)) {
        $ids = [];
        foreach ($employees as $k => $v) {
            if (is_numeric($k)) {
                $ids[] = (int)$k;
            } elseif (is_array($v) && isset($v['ID'])) {
                $ids[] = (int)$v['ID'];
            } elseif (is_numeric($v)) {
                $ids[] = (int)$v;
            }
        }
        $ids = array_values(array_unique($ids));
        sort($ids);
        echo "employee_ids=" . implode(',', $ids) . "\n";
        echo "contains 2303=" . (in_array(2303, $ids, true) ? 'Y' : 'N') . "\n";
    }
}

// Head check
$sub = \CIntranetUtils::GetSubordinateDepartments($deps[0] ?? 0, true);
echo "subdepts=" . json_encode($sub) . "\n";
