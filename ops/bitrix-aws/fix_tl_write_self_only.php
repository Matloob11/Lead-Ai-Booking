<?php
/**
 * TL can READ team leads, but WRITE only own (SELF).
 * Also mask-friendly: no department WRITE on LEAD / Owner Data.
 */
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$read = '["SELF","SUBDEPARTMENTS","DEPARTMENT"]';
$writeSelf = '["SELF"]';

$entities = ['LEAD', 'DYNAMIC_1042', 'DYNAMIC_1042_C13', 'DYNAMIC_1042_C14'];

foreach ($entities as $entity) {
    foreach (['READ', 'WRITE', 'ADD', 'EXPORT'] as $ptype) {
        $settings = ($ptype === 'READ' || $ptype === 'EXPORT') ? $read : $writeSelf;
        $q = $m->query(
            "SELECT ID FROM b_crm_role_perms
             WHERE ROLE_ID=54 AND ENTITY='" . $m->real_escape_string($entity) . "'
               AND PERM_TYPE='" . $m->real_escape_string($ptype) . "' AND FIELD='-'"
        );
        $ids = [];
        while ($r = $q->fetch_assoc()) {
            $ids[] = (int) $r['ID'];
        }
        if (!$ids) {
            $m->query(
                "INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS)
                 VALUES (54, '" . $m->real_escape_string($entity) . "', '-', NULL,
                 '" . $m->real_escape_string($ptype) . "', NULL,
                 '" . $m->real_escape_string($settings) . "')"
            );
            echo "INSERT $entity $ptype -> $settings\n";
            continue;
        }
        $keep = $ids[0];
        $m->query(
            "UPDATE b_crm_role_perms SET SETTINGS='" . $m->real_escape_string($settings) . "', ATTR=NULL
             WHERE ID=$keep"
        );
        echo "UPDATE $entity $ptype id=$keep -> $settings\n";
        for ($i = 1; $i < count($ids); $i++) {
            $m->query('DELETE FROM b_crm_role_perms WHERE ID=' . $ids[$i]);
            echo "  del dup {$ids[$i]}\n";
        }
    }
}

echo "=== verify ===\n";
$q = $m->query(
    "SELECT ENTITY, PERM_TYPE, SETTINGS FROM b_crm_role_perms
     WHERE ROLE_ID=54 AND (ENTITY='LEAD' OR ENTITY LIKE 'DYNAMIC_1042%')
       AND PERM_TYPE IN ('READ','WRITE','ADD','EXPORT') AND FIELD='-'
     ORDER BY ENTITY, PERM_TYPE"
);
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}
echo "DONE\n";
