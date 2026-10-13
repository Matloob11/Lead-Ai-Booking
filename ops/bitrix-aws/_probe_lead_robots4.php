<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

$ids = [235, 330, 280, 238, 93, 89, 12, 281];
foreach ($ids as $id) {
    $q = $m->query("SELECT NAME, AUTO_EXECUTE, ACTIVE, TEMPLATE FROM b_bp_workflow_template WHERE ID=" . (int)$id);
    $r = $q->fetch_assoc();
    $raw = $r['TEMPLATE'];
    if (substr($raw, 0, 2) === "\x1f\x8b") {
        $raw = gzdecode($raw);
    }
    preg_match_all('#https?://[^\\s"\']+#', $raw, $urls);
    echo "ID=$id {$r['NAME']} auto={$r['AUTO_EXECUTE']} active={$r['ACTIVE']}\n";
    $found = array_unique($urls[0] ?? []);
    if (!$found) {
        echo "  (no urls) len=" . strlen($raw) . " head=" . substr(preg_replace('/\s+/', ' ', $raw), 0, 180) . "\n";
    }
    foreach ($found as $u) {
        echo "  " . substr($u, 0, 200) . "\n";
    }
}
