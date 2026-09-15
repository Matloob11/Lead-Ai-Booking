<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== CRM roles ===\n";
$q = $m->query("SELECT ID, NAME, IS_SYSTEM FROM b_crm_role ORDER BY ID");
if ($q) {
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r) . "\n";
    }
}

echo "=== role relations for TLs 2560,2551,2297 ===\n";
$q = $m->query("SELECT * FROM b_crm_role_relation WHERE RELATION IN ('U2560','U2551','U2297') OR RELATION LIKE 'D69%' OR RELATION LIKE 'D70%' OR RELATION LIKE 'D71%' OR RELATION LIKE 'DR69%' OR RELATION LIKE 'DR70%' OR RELATION LIKE 'DR71%'");
if ($q) {
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r) . "\n";
    }
}

echo "=== sample perms for roles linked to group 12/14/15 (common) ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_crm_role_perms'");
if ($q && $q->num_rows) {
    $q2 = $m->query("SELECT ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR FROM b_crm_role_perms WHERE ENTITY IN ('LEAD','DYNAMIC_1042','DEAL') AND ROLE_ID IN (SELECT DISTINCT ROLE_ID FROM b_crm_role_relation WHERE RELATION IN ('U2560','U2551','U2297','G12','G14','G15','G11')) LIMIT 80");
    if ($q2) {
        while ($r = $q2->fetch_assoc()) {
            echo json_encode($r) . "\n";
        }
    }
}

echo "=== all relations mentioning TL users via groups ===\n";
// groups of TLs
foreach ([2560, 2551, 2297] as $uid) {
    $g = $m->query("SELECT GROUP_ID FROM b_user_group WHERE USER_ID=$uid");
    $gs = [];
    while ($r = $g->fetch_assoc()) {
        $gs[] = (int) $r['GROUP_ID'];
    }
    echo "user $uid groups=" . implode(',', $gs) . "\n";
    if ($gs) {
        $in = implode(',', array_map(static function ($x) {
            return "'G$x'";
        }, $gs));
        $q = $m->query("SELECT rr.ROLE_ID, rr.RELATION, r.NAME FROM b_crm_role_relation rr JOIN b_crm_role r ON r.ID=rr.ROLE_ID WHERE rr.RELATION IN ($in, 'U$uid')");
        while ($r = $q->fetch_assoc()) {
            echo "  role={$r['ROLE_ID']} {$r['NAME']} via {$r['RELATION']}\n";
        }
    }
}

// ATTR legend: X=all, O=open, D=department, F=personal, etc.
echo "=== LEAD/DYNAMIC_1042 READ attrs for those roles ===\n";
$q = $m->query("SELECT DISTINCT rr.ROLE_ID FROM b_crm_role_relation rr WHERE rr.RELATION IN ('U2560','U2551','U2297','G3','G4','G5','G11','G12','G14','G15','G16')");
$roleIds = [];
while ($r = $q->fetch_assoc()) {
    $roleIds[] = (int) $r['ROLE_ID'];
}
if ($roleIds) {
    $in = implode(',', $roleIds);
    $q2 = $m->query("SELECT ROLE_ID, ENTITY, PERM_TYPE, ATTR FROM b_crm_role_perms WHERE ROLE_ID IN ($in) AND ENTITY IN ('LEAD','DYNAMIC_1042') AND PERM_TYPE IN ('READ','WRITE','ADD','EXPORT') ORDER BY ROLE_ID, ENTITY, PERM_TYPE");
    while ($r = $q2->fetch_assoc()) {
        echo json_encode($r) . "\n";
    }
}
