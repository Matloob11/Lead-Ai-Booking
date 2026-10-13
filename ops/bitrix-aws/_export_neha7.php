<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
$ids = [77578, 77566, 77564, 77496, 77495, 77494, 77416];
$in = implode(',', $ids);
$q = $m->query("SELECT l.ID, l.TITLE, l.NAME, l.LAST_NAME, l.STATUS_ID, s.NAME STAGE,
  l.ASSIGNED_BY_ID, TRIM(CONCAT(ag.NAME,' ',ag.LAST_NAME)) AGENT,
  l.DATE_CREATE, l.ORIGIN_ID, l.COMMENTS, l.SOURCE_ID
  FROM b_crm_lead l
  LEFT JOIN b_crm_status s ON s.STATUS_ID=l.STATUS_ID AND s.ENTITY_ID='STATUS'
  LEFT JOIN b_user ag ON ag.ID=l.ASSIGNED_BY_ID
  WHERE l.ID IN ($in) AND l.ASSIGNED_BY_ID=2251 AND l.STATUS_ID='UC_MJDO60' AND l.ORIGINATOR_ID='a7-pf'");
$rows = [];
while ($r = $q->fetch_assoc()) $rows[(int)$r['ID']] = $r;
$pq = $m->query("SELECT ELEMENT_ID, VALUE FROM b_crm_field_multi WHERE ENTITY_ID='LEAD' AND TYPE_ID='PHONE' AND ELEMENT_ID IN ($in)");
while ($p = $pq->fetch_assoc()) {
    $id = (int)$p['ELEMENT_ID'];
    if (!isset($rows[$id])) continue;
    $rows[$id]['PHONES'][] = preg_replace('/\D/', '', $p['VALUE']);
}
foreach ($rows as &$row) {
    $row['TWIN_IDS'] = [];
    if (!isset($row['PHONES'])) $row['PHONES'] = [];
}
unset($row);
$out = array_values($rows);
file_put_contents('/tmp/neha-assigned-7.json', json_encode($out, JSON_UNESCAPED_UNICODE));
echo 'EXPORT ' . count($out) . "\n";
foreach ($out as $r) echo $r['ID'], ' ', $r['TITLE'], "\n";
if (count($out) !== 7) exit(1);
