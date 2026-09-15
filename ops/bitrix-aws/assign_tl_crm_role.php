<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== DYNAMIC_1042 on role 54 ===\n";
$q = $m->query("SELECT ENTITY,PERM_TYPE,ATTR,SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY LIKE '%1042%' ORDER BY ENTITY, PERM_TYPE");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== Assign role 54 to TLs ===\n";
foreach ([2560, 2551, 2297] as $uid) {
    $rel = 'U' . $uid;
    $exists = $m->query("SELECT ID FROM b_crm_role_relation WHERE ROLE_ID=54 AND RELATION='" . $m->real_escape_string($rel) . "'")->fetch_assoc();
    if ($exists) {
        echo "already $rel\n";
        continue;
    }
    $m->query("INSERT INTO b_crm_role_relation (ROLE_ID, RELATION) VALUES (54, '" . $m->real_escape_string($rel) . "')");
    echo "inserted $rel id=" . $m->insert_id . "\n";
}

echo "=== verify relations ===\n";
$q = $m->query("SELECT * FROM b_crm_role_relation WHERE ROLE_ID=54 AND RELATION IN ('U2560','U2551','U2297')");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

// Ensure Owner Data SPA 1042 has department read if missing — clone from LEAD pattern
$need = [
    ['READ', '["SELF","SUBDEPARTMENTS","DEPARTMENT"]'],
    ['WRITE', '["SELF","SUBDEPARTMENTS","DEPARTMENT"]'],
    ['ADD', '["SELF","SUBDEPARTMENTS","DEPARTMENT"]'],
    ['EXPORT', '["SELF","SUBDEPARTMENTS","DEPARTMENT"]'],
];
// Bitrix smart process entities often named DYNAMIC_1042 and DYNAMIC_1042_C14 / C13
$entities = ['DYNAMIC_1042', 'DYNAMIC_1042_C13', 'DYNAMIC_1042_C14'];
foreach ($entities as $entity) {
    foreach ($need as [$ptype, $settings]) {
        $chk = $m->query("SELECT ID, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY='" . $m->real_escape_string($entity) . "' AND PERM_TYPE='" . $m->real_escape_string($ptype) . "' AND FIELD='-'")->fetch_assoc();
        if ($chk) {
            echo "perm exists $entity $ptype settings={$chk['SETTINGS']}\n";
            // upgrade settings if only SELF
            if ($chk['SETTINGS'] && strpos($chk['SETTINGS'], 'DEPARTMENT') === false) {
                $m->query("UPDATE b_crm_role_perms SET SETTINGS='" . $m->real_escape_string($settings) . "', ATTR=NULL WHERE ID=" . (int)$chk['ID']);
                echo "  upgraded settings\n";
            }
            continue;
        }
        $m->query("INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS) VALUES (54, '" . $m->real_escape_string($entity) . "', '-', NULL, '" . $m->real_escape_string($ptype) . "', NULL, '" . $m->real_escape_string($settings) . "')");
        echo "inserted perm $entity $ptype id=" . $m->insert_id . "\n";
    }
}

echo "=== clear CRM access cache hint ===\n";
// Bitrix caches permissions; touch option or leave note
if (is_dir('/home/bitrix/www/bitrix/cache')) {
    // safe: managed cache clear via bitrix if available
    echo "cache dir exists — user should re-login TL accounts\n";
}
echo "DONE\n";
