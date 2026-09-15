<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$hassanAgents = [2560, 2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303];
$in = implode(',', $hassanAgents);

echo "=== Owner Data table ===\n";
$tq = $m->query("SHOW TABLES LIKE '%1042%'");
while ($t = $tq->fetch_row()) {
    echo $t[0] . "\n";
}
$tq = $m->query("SHOW TABLES LIKE 'b_crm_dynamic_items_1042'");
echo "items table exists=" . ($tq && $tq->num_rows ? 'Y' : 'N') . "\n";

$tables = [];
$tq = $m->query("SHOW TABLES");
while ($r = $tq->fetch_row()) {
    if (stripos($r[0], '1042') !== false || stripos($r[0], 'dynamic') !== false) {
        $tables[] = $r[0];
    }
}
echo "dynamic-ish: " . implode(', ', array_slice($tables, 0, 40)) . "\n";

$itemTable = null;
foreach (['b_crm_dynamic_items_1042', 'b_crm_item_1042'] as $cand) {
    $c = $m->query("SHOW TABLES LIKE '$cand'");
    if ($c && $c->num_rows) {
        $itemTable = $cand;
        break;
    }
}
if (!$itemTable) {
    // search
    $tq = $m->query("SHOW TABLES LIKE 'b_crm_dynamic_items_%'");
    while ($r = $tq->fetch_row()) {
        echo "found {$r[0]}\n";
        if (substr($r[0], -4) === '1042' || strpos($r[0], '1042') !== false) {
            $itemTable = $r[0];
        }
    }
}
echo "itemTable=$itemTable\n";

if ($itemTable) {
    $cols = [];
    $q = $m->query("SHOW COLUMNS FROM `$itemTable`");
    while ($r = $q->fetch_assoc()) {
        $cols[] = $r['Field'];
    }
    echo "cols sample: " . implode(',', array_slice($cols, 0, 30)) . "\n";
    $assignedCol = in_array('ASSIGNED_BY_ID', $cols, true) ? 'ASSIGNED_BY_ID' : (in_array('RESPONSIBLE_ID', $cols, true) ? 'RESPONSIBLE_ID' : null);
    $catCol = in_array('CATEGORY_ID', $cols, true) ? 'CATEGORY_ID' : null;
    echo "assignedCol=$assignedCol catCol=$catCol\n";
    if ($assignedCol) {
        $sql = "SELECT $assignedCol" . ($catCol ? ", $catCol" : "") . ", COUNT(*) c FROM `$itemTable` WHERE $assignedCol IN ($in) GROUP BY $assignedCol" . ($catCol ? ", $catCol" : "") . " ORDER BY c DESC LIMIT 40";
        $q = $m->query($sql);
        echo "=== counts by assignee/category ===\n";
        while ($r = $q->fetch_assoc()) {
            echo json_encode($r) . "\n";
        }
        $q = $m->query("SELECT COUNT(*) c FROM `$itemTable` WHERE $assignedCol IN ($in)" . ($catCol ? " AND $catCol=13" : ""));
        echo "team items cat13=" . $q->fetch_assoc()['c'] . "\n";
        $q = $m->query("SELECT COUNT(*) c FROM `$itemTable` WHERE $assignedCol IN ($in)" . ($catCol ? " AND $catCol=14" : ""));
        echo "team items cat14=" . $q->fetch_assoc()['c'] . "\n";
        $q = $m->query("SELECT ID, $assignedCol" . ($catCol ? ", $catCol" : "") . ", STAGE_ID, TITLE FROM `$itemTable` WHERE $assignedCol IN ($in) ORDER BY ID DESC LIMIT 8");
        echo "=== sample items ===\n";
        while ($r = $q->fetch_assoc()) {
            echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
        }
    }
}

echo "=== role54 C13 all READ rows ===\n";
$q = $m->query("SELECT ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY LIKE '%1042%' AND PERM_TYPE='READ' ORDER BY ENTITY, FIELD, ID");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== Hassan roles ===\n";
$q = $m->query("SELECT rr.ROLE_ID, r.NAME, rr.RELATION FROM b_crm_role_relation rr JOIN b_crm_role r ON r.ID=rr.ROLE_ID WHERE rr.RELATION IN ('U2560','G12','G3','G4','G5','G14','G15','G16')");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "=== Employee role6 DYNAMIC_1042 ===\n";
$q = $m->query("SELECT ENTITY, FIELD, PERM_TYPE, ATTR, SETTINGS FROM b_crm_role_perms WHERE ROLE_ID=6 AND ENTITY LIKE '%1042%' LIMIT 30");
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

echo "DONE\n";
