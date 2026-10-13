<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_CRONTAB', true);
ini_set('display_errors', '0');
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$path = '/tmp/a7pf-remaining-20261001.json';
$rows = json_decode(file_get_contents($path), true);
$ids = [];
foreach ($rows as $row) {
    $id = (int)($row['ID'] ?? 0);
    if ($id > 0) $ids[] = $id;
}
$m = $GLOBALS['DB'];
$left = [];
foreach (array_chunk($ids, 400) as $chunk) {
    $in = implode(',', $chunk);
    $rs = $m->Query("SELECT ID FROM b_crm_lead WHERE ID IN ($in)");
    while ($r = $rs->Fetch()) $left[] = (int)$r['ID'];
}
echo 'STILL ' . count($left) . "\n";
$crm = new CCrmLead(false);
$ok = 0;
$fail = 0;
foreach ($left as $id) {
    try {
        $deleted = $crm->Delete($id, [
            'ENABLE_SYSTEM_EVENTS' => false,
            'PROCESS_BIZPROC' => false,
            'REGISTER_SONET_EVENT' => false,
        ]);
    } catch (Throwable $e) {
        $deleted = false;
        if ($fail < 8) fwrite(STDERR, "EX $id " . $e->getMessage() . "\n");
    }
    if ($deleted) $ok++;
    else {
        $fail++;
        if ($fail <= 8) fwrite(STDERR, "FAIL $id " . $crm->LAST_ERROR . "\n");
    }
    if (($ok + $fail) % 200 === 0) {
        fwrite(STDERR, "progress ok=$ok fail=$fail\n");
    }
}
echo "DELETED $ok FAIL $fail\n";
