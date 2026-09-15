<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== Team Leader role 54 perms ===\n";
$q = $m->query("SELECT * FROM b_crm_role_perms WHERE ROLE_ID=54 ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== Head of department role 5 perms LEAD/DYNAMIC ===\n";
$q = $m->query("SELECT * FROM b_crm_role_perms WHERE ROLE_ID IN (5,7,27,28,29) AND ENTITY IN ('LEAD','DYNAMIC_1042','CONTACT','COMPANY') ORDER BY ROLE_ID, ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== Employee role 6 LEAD/DYNAMIC ===\n";
$q = $m->query("SELECT * FROM b_crm_role_perms WHERE ROLE_ID=6 AND ENTITY IN ('LEAD','DYNAMIC_1042') ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== Agent role 36 LEAD/DYNAMIC ===\n";
$q = $m->query("SELECT * FROM b_crm_role_perms WHERE ROLE_ID=36 AND ENTITY IN ('LEAD','DYNAMIC_1042') ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== relations for role 54 ===\n";
$q = $m->query("SELECT * FROM b_crm_role_relation WHERE ROLE_ID=54");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== columns b_crm_role_perms ===\n";
$q = $m->query("SHOW COLUMNS FROM b_crm_role_perms");
while ($r = $q->fetch_assoc()) {
    echo $r['Field'] . "\t" . $r['Type'] . "\n";
}
