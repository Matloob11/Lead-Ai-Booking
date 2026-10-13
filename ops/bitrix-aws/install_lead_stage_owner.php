<?php
/**
 * Register the New Lead / Assigned owner rule and move leads that are
 * already in New Lead but owned by someone other than user 1.
 */
$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$src = file_get_contents($init);
if ($src === false) {
    fwrite(STDERR, "cannot read init.php\n");
    exit(1);
}
$marker = 'A7_LEAD_STAGE_OWNER';
if (strpos($src, $marker) === false) {
    $bak = $init . '.bak.stage_owner_' . date('Ymd_His');
    if (!copy($init, $bak)) {
        fwrite(STDERR, "init backup failed\n");
        exit(1);
    }
    echo "init_backup=$bak\n";
    $block = <<<'PHP'

// A7_LEAD_STAGE_OWNER: Malik (user 1) keeps New Lead; any other owner moves New Lead to Assigned.
if (is_file(__DIR__ . '/include/a7_lead_stage_owner.php')) {
    require_once __DIR__ . '/include/a7_lead_stage_owner.php';
}
PHP;
    $needle = "require_once __DIR__ . '/include/a7_neha_community_leads.php';";
    $pos = strpos($src, $needle);
    if ($pos === false) {
        fwrite(STDERR, "neha include not found\n");
        exit(1);
    }
    $lineEnd = strpos($src, "\n", $pos);
    if ($lineEnd === false) {
        fwrite(STDERR, "neha line end not found\n");
        exit(1);
    }
    $src = substr($src, 0, $lineEnd + 1) . $block . substr($src, $lineEnd + 1);
    if (file_put_contents($init, $src) === false) {
        fwrite(STDERR, "write init failed\n");
        exit(1);
    }
    echo "init inserted\n";
} else {
    echo "init already has marker\n";
}

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
$stage = $m->query("SELECT STATUS_ID, NAME FROM b_crm_status WHERE ENTITY_ID='STATUS' AND STATUS_ID='UC_MJDO60'")->fetch_assoc();
if (!$stage || $stage['NAME'] !== 'Assigned') {
    fwrite(STDERR, "assigned stage missing\n");
    exit(1);
}
$before = (int)$m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE STATUS_ID='NEW' AND ASSIGNED_BY_ID<>1")->fetch_assoc()['c'];
echo "new_not_admin=$before\n";
if ($before > 0) {
    $ok = $m->query(
        "UPDATE b_crm_lead
         SET STATUS_ID='UC_MJDO60', MOVED_BY_ID=1, MOVED_TIME=NOW(), MODIFY_BY_ID=1, DATE_MODIFY=NOW()
         WHERE STATUS_ID='NEW' AND ASSIGNED_BY_ID<>1"
    );
    if (!$ok) {
        fwrite(STDERR, $m->error . "\n");
        exit(1);
    }
    echo "moved=" . $m->affected_rows . "\n";
}
echo "new_total=" . $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE STATUS_ID='NEW'")->fetch_assoc()['c'] . "\n";
echo "new_on_admin=" . $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE STATUS_ID='NEW' AND ASSIGNED_BY_ID=1")->fetch_assoc()['c'] . "\n";
echo "assigned_total=" . $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE STATUS_ID='UC_MJDO60'")->fetch_assoc()['c'] . "\n";
echo "DONE\n";
