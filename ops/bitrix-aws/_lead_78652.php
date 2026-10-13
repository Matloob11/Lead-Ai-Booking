<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');
$id = 78652;
$q = $m->query("SELECT l.ID, l.TITLE, l.NAME, l.LAST_NAME, l.DATE_CREATE, l.SOURCE_ID, src.NAME SOURCE_NAME,
  l.STATUS_ID, st.NAME STAGE, l.ASSIGNED_BY_ID, TRIM(CONCAT(ag.NAME,' ',ag.LAST_NAME)) AGENT,
  l.ORIGINATOR_ID, l.ORIGIN_ID, l.CREATED_BY_ID, LEFT(l.COMMENTS, 400) COMMENTS
  FROM b_crm_lead l
  LEFT JOIN b_crm_status src ON src.STATUS_ID=l.SOURCE_ID AND src.ENTITY_ID='SOURCE'
  LEFT JOIN b_crm_status st ON st.STATUS_ID=l.STATUS_ID AND st.ENTITY_ID='STATUS'
  LEFT JOIN b_user ag ON ag.ID=l.ASSIGNED_BY_ID
  WHERE l.ID=$id");
$r = $q->fetch_assoc();
if (!$r) { echo "NOT_FOUND\n"; exit(0); }
foreach ($r as $k => $v) {
    if ($k === 'COMMENTS') continue;
    echo $k, '=', str_replace(["\n","\r"], ' ', (string)$v), "\n";
}
echo "COMMENTS=", str_replace(["\n","\r"], ' | ', (string)$r['COMMENTS']), "\n";
echo "=== phones ===\n";
$q = $m->query("SELECT VALUE FROM b_crm_field_multi WHERE ENTITY_ID='LEAD' AND ELEMENT_ID=$id AND TYPE_ID='PHONE'");
while ($p = $q->fetch_assoc()) echo $p['VALUE'], "\n";
echo "=== key fields ===\n";
$q = $m->query("SELECT UF_CRM_1731838126127 beds, UF_CRM_1736306439793 budget, UF_CRM_1770537051525 community, UF_CRM_1763390140 community2, UF_CRM_1760707563281 ref, UF_CRM_1760707872553 portal
FROM b_uts_crm_lead WHERE VALUE_ID=$id");
$u = $q->fetch_assoc();
if ($u) foreach ($u as $k => $v) echo $k, '=', $v, "\n";
