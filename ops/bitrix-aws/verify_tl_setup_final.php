<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== departments ===\n";
$q = $m->query("SELECT ID, NAME, IBLOCK_SECTION_ID, CODE FROM b_iblock_section WHERE ID IN (69,70,71)");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
}

echo "=== UF_HEAD ===\n";
$q = $m->query("SELECT VALUE_ID, UF_HEAD FROM b_uts_iblock_3_section WHERE VALUE_ID IN (69,70,71)");
if ($q) {
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r) . "\n";
    }
} else {
    // try alternate table naming
    $tq = $m->query("SHOW TABLES LIKE 'b_uts_iblock%section%'");
    while ($t = $tq->fetch_row()) {
        echo "table {$t[0]}\n";
        $q2 = $m->query("SELECT * FROM `{$t[0]}` WHERE VALUE_ID IN (69,70,71) LIMIT 5");
        if ($q2) {
            while ($r = $q2->fetch_assoc()) {
                echo json_encode($r) . "\n";
            }
        }
    }
}

echo "=== TL dept + role ===\n";
foreach ([2560 => 69, 2551 => 70, 2297 => 71] as $uid => $dept) {
    $u = $m->query("SELECT UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID=$uid")->fetch_assoc();
    $rel = $m->query("SELECT ID FROM b_crm_role_relation WHERE ROLE_ID=54 AND RELATION='U$uid'")->fetch_assoc();
    echo "user=$uid dept_raw={$u['UF_DEPARTMENT']} role54=" . ($rel ? 'YES' : 'NO') . " expect_dept=$dept\n";
}

echo "=== mask files ===\n";
foreach ([
    '/home/bitrix/www/bitrix/js/a7_tl_phone_mask.js',
    '/home/bitrix/www/bitrix/tools/a7_tl_phone_mask.php',
    '/home/bitrix/www/bitrix/php_interface/a7_tl_phone_mask.config.php',
] as $p) {
    echo (is_readable($p) ? 'OK' : 'MISS') . " $p\n";
}
$init = file_get_contents('/home/bitrix/www/bitrix/php_interface/init.php');
echo (strpos($init, 'A7_TL_PHONE_MASK') !== false ? 'OK' : 'MISS') . " init hook\n";

echo "=== LEAD/1042 READ role54 ===\n";
$q = $m->query("SELECT ENTITY,FIELD,PERM_TYPE,SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND (ENTITY='LEAD' OR ENTITY LIKE 'DYNAMIC_1042%') AND PERM_TYPE='READ' AND FIELD='-'");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}
echo "DONE\n";
