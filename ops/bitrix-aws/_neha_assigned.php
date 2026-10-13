<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

$q = $m->query("SELECT ID, NAME, LAST_NAME FROM b_user WHERE LAST_NAME LIKE '%Mhaskar%' OR (NAME LIKE '%Neha%' AND ACTIVE='Y')");
$ids = [];
while ($r = $q->fetch_assoc()) {
    echo 'USER ', implode(' | ', $r), "\n";
    $ids[] = (int)$r['ID'];
}
if (!$ids) {
    fwrite(STDERR, "no user\n");
    exit(1);
}
$in = '2251';

echo "=== assigned stage by source and origin ===\n";
$sql = "SELECT src.NAME portal,
  CASE WHEN l.ORIGINATOR_ID='a7-pf' THEN 'hostinger' ELSE 'other' END origin,
  COUNT(*) N
FROM b_crm_lead l
LEFT JOIN b_crm_status src ON src.STATUS_ID=l.SOURCE_ID AND src.ENTITY_ID='SOURCE'
WHERE l.ASSIGNED_BY_ID IN ($in) AND l.STATUS_ID='UC_MJDO60'
GROUP BY src.NAME, origin
ORDER BY N DESC";
$q = $m->query($sql);
if (!$q) { echo $m->error, "\n"; exit(1); }
while ($r = $q->fetch_assoc()) echo $r['N'], ' | ', $r['portal'], ' | ', $r['origin'], "\n";

echo "=== leads ===\n";
$q = $m->query("SELECT l.ID, l.TITLE, l.DATE_CREATE, l.ORIGINATOR_ID
FROM b_crm_lead l
WHERE l.ASSIGNED_BY_ID IN ($in) AND l.STATUS_ID='UC_MJDO60'
ORDER BY l.ID DESC");
while ($r = $q->fetch_assoc()) echo implode(' | ', $r), "\n";

echo "=== totals ===\n";
$q = $m->query("SELECT
  SUM(ORIGINATOR_ID='a7-pf') hostinger,
  SUM(ORIGINATOR_ID<>'a7-pf' OR ORIGINATOR_ID IS NULL OR ORIGINATOR_ID='') other,
  COUNT(*) total
FROM b_crm_lead WHERE ASSIGNED_BY_ID IN ($in) AND STATUS_ID='UC_MJDO60'");
echo implode(' | ', $q->fetch_assoc()), "\n";
