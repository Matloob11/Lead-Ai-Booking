<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== access attr cols ===\n";
$q = $m->query('SHOW COLUMNS FROM b_crm_access_attr_dynamic_1042');
while ($r = $q->fetch_assoc()) {
    echo $r['Field'] . "\t" . $r['Type'] . "\n";
}

echo "=== sample attrs for item 89463 (agent 2303) ===\n";
$q = $m->query('SELECT * FROM b_crm_access_attr_dynamic_1042 WHERE ENTITY_ID=89463 LIMIT 20');
if ($q) {
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r) . "\n";
    }
} else {
    // try ID column names
    $q = $m->query('SELECT * FROM b_crm_access_attr_dynamic_1042 LIMIT 3');
    while ($r = $q->fetch_assoc()) {
        echo 'samplerow ' . json_encode($r) . "\n";
    }
}

echo "=== count attrs ===\n";
$q = $m->query('SELECT COUNT(*) c FROM b_crm_access_attr_dynamic_1042');
echo 'attr_rows=' . $q->fetch_assoc()['c'] . "\n";

echo "=== find rebuild classes ===\n";
\Bitrix\Main\Loader::includeModule('crm');
$candidates = [
    'Bitrix\\Crm\\Agent\\Security\\DynamicTypes\\ClearDynamicTypesAttrAgent',
    'Bitrix\\Crm\\Agent\\Security\\AccessAttr\\RebuildEntityAccessAttrsAgent',
    'Bitrix\\Crm\\Security\\Controller\\Register',
    'Bitrix\\Crm\\Service\\Container',
];
foreach ($candidates as $c) {
    echo $c . ' exists=' . (class_exists($c) ? 'Y' : 'N') . "\n";
}

// List files matching Rebuild*Access*
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator('/home/bitrix/www/bitrix/modules/crm/lib/agent/security', FilesystemIterator::SKIP_DOTS));
foreach ($it as $f) {
    if ($f->isFile() && stripos($f->getFilename(), 'attr') !== false) {
        echo 'file ' . $f->getPathname() . "\n";
    }
}
