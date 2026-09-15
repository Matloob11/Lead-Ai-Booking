<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== lead UFs bedroom/community/client/comment ===\n";
$q = $m->query(
	"SELECT f.FIELD_NAME, f.USER_TYPE_ID, l.EDIT_FORM_LABEL
	 FROM b_user_field f
	 LEFT JOIN b_user_field_lang l ON l.USER_FIELD_ID=f.ID AND l.LANGUAGE_ID='en'
	 WHERE f.ENTITY_ID='CRM_LEAD'
	   AND (
	     l.EDIT_FORM_LABEL LIKE '%Bedroom%'
	     OR l.EDIT_FORM_LABEL LIKE '%Community%'
	     OR l.EDIT_FORM_LABEL LIKE '%Client%'
	     OR l.EDIT_FORM_LABEL LIKE '%Comment%'
	     OR l.EDIT_FORM_LABEL LIKE '%Note%'
	     OR f.FIELD_NAME IN ('UF_CRM_WA_CHAT','UF_CRM_WA_SUMMARY','UF_CRM_AI_MONITOR')
	   )
	 ORDER BY f.FIELD_NAME"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
}

$cols = [];
$q = $m->query(
	"SELECT f.FIELD_NAME
	 FROM b_user_field f
	 LEFT JOIN b_user_field_lang l ON l.USER_FIELD_ID=f.ID AND l.LANGUAGE_ID='en'
	 WHERE f.ENTITY_ID='CRM_LEAD'
	   AND (
	     l.EDIT_FORM_LABEL LIKE '%Bedroom%'
	     OR l.EDIT_FORM_LABEL LIKE '%Community%'
	     OR l.EDIT_FORM_LABEL LIKE '%Client Type%'
	     OR l.EDIT_FORM_LABEL LIKE '%Client type%'
	   )"
);
while ($r = $q->fetch_assoc()) {
	$cols[] = $r['FIELD_NAME'];
}

if (!$cols) {
	echo "no_card_fields\n";
	exit(0);
}

$parts = ["TRIM(COALESCE(l.COMMENTS,'')) <> ''"];
foreach ($cols as $col) {
	$parts[] = "(u.`$col` IS NOT NULL AND TRIM(CAST(u.`$col` AS CHAR)) <> '' AND CAST(u.`$col` AS CHAR) NOT IN ('0','a:0:{}'))";
}
$detailSql = implode(' OR ', $parts);
$in = "'UC_WA_LEADS'";

$sql = "SELECT
	COUNT(*) total,
	SUM(CASE WHEN ($detailSql) THEN 1 ELSE 0 END) with_details,
	SUM(CASE WHEN NOT ($detailSql) THEN 1 ELSE 0 END) blank,
	SUM(CASE WHEN TRIM(COALESCE(l.COMMENTS,'')) <> '' THEN 1 ELSE 0 END) has_comment
FROM b_crm_lead l
LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
WHERE l.STATUS_ID IN ($in)";
echo "card_fields=" . implode(',', $cols) . "\n";
echo "=== recount with card fields + comments ===\n";
$q = $m->query($sql);
echo json_encode($q->fetch_assoc()) . "\n";
echo "DONE\n";
