<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$ids = [2560, 2551, 2297, 2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303, 2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350, 2299, 2302, 2392, 2298, 2390];
$idList = implode(',', $ids);

echo "=== users + dept ===\n";
$q = $m->query("SELECT u.ID, TRIM(CONCAT(IFNULL(u.NAME,''),' ',IFNULL(u.LAST_NAME,''))) N, u.EMAIL,
  (SELECT GROUP_CONCAT(ug.GROUP_ID) FROM b_user_group ug WHERE ug.USER_ID=u.ID) GIDS
FROM b_user u WHERE u.ID IN ($idList) ORDER BY u.ID");
while ($r = $q->fetch_assoc()) {
    echo $r['ID'] . "\t" . $r['N'] . "\t" . $r['EMAIL'] . "\tgroups=" . $r['GIDS'] . "\n";
}

echo "=== departments (iblock structure) ===\n";
// Bitrix departments often in b_uts_user UF_DEPARTMENT or b_iblock_section
$c = $m->query("SHOW COLUMNS FROM b_uts_user LIKE 'UF_DEPARTMENT'");
if ($c && $c->num_rows) {
    $q = $m->query("SELECT VALUE_ID, UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID IN ($idList)");
    while ($r = $q->fetch_assoc()) {
        echo "UF_DEPARTMENT user=" . $r['VALUE_ID'] . " raw=" . substr(str_replace(["\n","\r"], '', print_r($r['UF_DEPARTMENT'], true)), 0, 120) . "\n";
    }
}

echo "=== dept sections sample ===\n";
$q = $m->query("SELECT ID, IBLOCK_ID, IBLOCK_SECTION_ID, NAME, DEPTH_LEVEL, ACTIVE FROM b_iblock_section WHERE ACTIVE='Y' AND (NAME LIKE '%Hassan%' OR NAME LIKE '%Hussnain%' OR NAME LIKE '%Jaweria%' OR NAME LIKE '%Javeria%' OR NAME LIKE '%Sales%' OR NAME LIKE '%Team%' OR NAME LIKE '%TL%') ORDER BY IBLOCK_ID, LEFT_MARGIN LIMIT 40");
if ($q) {
    while ($r = $q->fetch_assoc()) {
        echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
    }
}
