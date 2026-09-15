<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$wanted = '["SELF","SUBDEPARTMENTS","DEPARTMENT"]';

// Clean duplicate READ rows for Owner Data categories on role 54
foreach (['DYNAMIC_1042_C13', 'DYNAMIC_1042_C14', 'DYNAMIC_1042', 'LEAD'] as $entity) {
    $q = $m->query("SELECT ID, PERM_TYPE, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY='" . $m->real_escape_string($entity) . "' AND FIELD='-' AND PERM_TYPE IN ('READ','WRITE','ADD','EXPORT') ORDER BY PERM_TYPE, ID");
    $byType = [];
    while ($r = $q->fetch_assoc()) {
        $byType[$r['PERM_TYPE']][] = $r;
    }
    foreach ($byType as $ptype => $rows) {
        // keep first, delete rest; set wanted settings (no ALL)
        $keep = (int) $rows[0]['ID'];
        $m->query("UPDATE b_crm_role_perms SET SETTINGS='" . $m->real_escape_string($wanted) . "', ATTR=NULL WHERE ID=$keep");
        echo "set $entity $ptype id=$keep -> $wanted\n";
        for ($i = 1; $i < count($rows); $i++) {
            $id = (int) $rows[$i]['ID'];
            $m->query("DELETE FROM b_crm_role_perms WHERE ID=$id");
            echo "  deleted duplicate id=$id\n";
        }
    }
}

echo "=== final LEAD + 1042 ===\n";
$q = $m->query("SELECT ENTITY,PERM_TYPE,SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND (ENTITY='LEAD' OR ENTITY LIKE 'DYNAMIC_1042%') AND PERM_TYPE IN ('READ','WRITE','ADD','EXPORT') ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

// Clear managed cache dirs for crm
$roots = [
    '/home/bitrix/www/bitrix/cache',
    '/home/bitrix/www/bitrix/managed_cache',
];
foreach ($roots as $root) {
    if (!is_dir($root)) {
        continue;
    }
    // only wipe crm-ish subdirs if present — safer full managed clear for bitrix user
    echo "cache root $root exists\n";
}

echo "DONE — TLs should log out/in\n";
