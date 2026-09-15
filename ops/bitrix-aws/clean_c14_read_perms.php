<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$wanted = '["SELF","SUBDEPARTMENTS","DEPARTMENT"]';
$q = $m->query("SELECT ID, FIELD, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY='DYNAMIC_1042_C14' AND PERM_TYPE='READ' ORDER BY ID");
$ids = [];
while ($r = $q->fetch_assoc()) {
    echo "before " . json_encode($r) . "\n";
    $ids[] = (int) $r['ID'];
}
if (!$ids) {
    $m->query("INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS) VALUES (54,'DYNAMIC_1042_C14','-',NULL,'READ',NULL,'" . $m->real_escape_string($wanted) . "')");
    echo "inserted fresh READ\n";
} else {
    $keep = $ids[0];
    $m->query("UPDATE b_crm_role_perms SET FIELD='-', FIELD_VALUE=NULL, ATTR=NULL, SETTINGS='" . $m->real_escape_string($wanted) . "' WHERE ID=$keep");
    for ($i = 1; $i < count($ids); $i++) {
        $m->query("DELETE FROM b_crm_role_perms WHERE ID=" . $ids[$i]);
        echo "deleted " . $ids[$i] . "\n";
    }
    echo "kept $keep\n";
}

echo "=== after ===\n";
$q = $m->query("SELECT ID, ENTITY, PERM_TYPE, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY='DYNAMIC_1042_C14' AND PERM_TYPE IN ('READ','WRITE','ADD','EXPORT')");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}
echo "DONE\n";
