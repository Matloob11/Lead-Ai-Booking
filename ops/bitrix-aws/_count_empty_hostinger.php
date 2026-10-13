<?php
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

$where = "l.ORIGINATOR_ID='a7-pf'
  AND (l.COMMENTS LIKE '%PF lead %' OR l.COMMENTS LIKE 'Agent:%')
  AND (u.UF_CRM_1731838126127 IS NULL OR u.UF_CRM_1731838126127='')
  AND (u.UF_CRM_1770537051525 IS NULL OR u.UF_CRM_1770537051525='')
  AND (u.UF_CRM_1763390140 IS NULL OR u.UF_CRM_1763390140='')
  AND (u.UF_CRM_1736306439793 IS NULL OR u.UF_CRM_1736306439793='' OR u.UF_CRM_1736306439793='0')";

echo "=== empty hostinger ===\n";
$q = $m->query("SELECT COUNT(*) N FROM b_crm_lead l LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID WHERE $where");
echo $q->fetch_assoc()['N'], "\n";

echo "=== by stage ===\n";
$q = $m->query("SELECT s.NAME stage, COUNT(*) N
FROM b_crm_lead l
LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
LEFT JOIN b_crm_status s ON s.STATUS_ID=l.STATUS_ID AND s.ENTITY_ID='STATUS'
WHERE $where
GROUP BY s.NAME ORDER BY N DESC");
while ($r = $q->fetch_assoc()) echo $r['N'], ' | ', $r['stage'], "\n";

echo "=== by assignee ===\n";
$q = $m->query("SELECT TRIM(CONCAT(u2.NAME, ' ', u2.LAST_NAME)) agent, COUNT(*) N
FROM b_crm_lead l
LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
LEFT JOIN b_user u2 ON u2.ID=l.ASSIGNED_BY_ID
WHERE $where
GROUP BY l.ASSIGNED_BY_ID ORDER BY N DESC");
while ($r = $q->fetch_assoc()) echo $r['N'], ' | ', $r['agent'], "\n";
