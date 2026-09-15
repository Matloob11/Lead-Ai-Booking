<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
	fwrite(STDERR, "db fail\n");
	exit(2);
}

echo "=== lead stages ===\n";
$q = $m->query("SELECT STATUS_ID, NAME, SORT FROM b_crm_status WHERE ENTITY_ID='STATUS' ORDER BY SORT");
$wa = [];
while ($r = $q->fetch_assoc()) {
	echo $r['STATUS_ID'] . "\t" . $r['NAME'] . "\n";
	if (stripos($r['NAME'], 'whatsapp') !== false || stripos($r['STATUS_ID'], 'WA_LEAD') !== false) {
		$wa[] = $r['STATUS_ID'];
	}
}
if (!$wa) {
	echo "NO_WA_STAGE\n";
	exit(1);
}
echo "using=" . implode(',', $wa) . "\n";

$in = "'" . implode("','", array_map([$m, 'real_escape_string'], $wa)) . "'";

echo "=== counts by stage ===\n";
$q = $m->query("SELECT STATUS_ID, COUNT(*) c FROM b_crm_lead WHERE STATUS_ID IN ($in) GROUP BY STATUS_ID");
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

$uts = $m->query("SHOW TABLES LIKE 'b_uts_crm_lead'");
$hasUts = $uts && $uts->num_rows;
$detailCols = [];
if ($hasUts) {
	$cols = $m->query("SHOW COLUMNS FROM b_uts_crm_lead");
	echo "=== uts columns ===\n";
	while ($c = $cols->fetch_assoc()) {
		$field = $c['Field'];
		echo $field . "\n";
		$low = strtolower($field);
		if (preg_match('/comment|bedroom|client|community|budget|area|location|property|type|note|source|opp/i', $field)) {
			$detailCols[] = $field;
		}
	}
}

echo "detail_cols=" . implode(',', $detailCols) . "\n";

$detailSql = "TRIM(COALESCE(l.COMMENTS,'')) <> ''";
if ($detailCols) {
	$parts = [];
	foreach ($detailCols as $col) {
		$parts[] = "(u.`$col` IS NOT NULL AND TRIM(CAST(u.`$col` AS CHAR)) <> '' AND CAST(u.`$col` AS CHAR) NOT IN ('0','a:0:{}'))";
	}
	$detailSql .= " OR " . implode(' OR ', $parts);
}

$join = $hasUts ? "LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID" : "";
$sql = "SELECT
	COUNT(*) total,
	SUM(CASE WHEN ($detailSql) THEN 1 ELSE 0 END) with_details,
	SUM(CASE WHEN NOT ($detailSql) THEN 1 ELSE 0 END) blank
FROM b_crm_lead l
$join
WHERE l.STATUS_ID IN ($in)";
echo "=== WhatsApp Leads stage ===\n";
$q = $m->query($sql);
if (!$q) {
	echo "query_error " . $m->error . "\n";
	exit(1);
}
echo json_encode($q->fetch_assoc()) . "\n";

echo "=== sample blank ===\n";
$q = $m->query(
	"SELECT l.ID, l.TITLE, LEFT(l.COMMENTS,80) COMMENTS
	 FROM b_crm_lead l $join
	 WHERE l.STATUS_ID IN ($in) AND NOT ($detailSql)
	 ORDER BY l.ID DESC LIMIT 5"
);
if ($q) {
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
	}
}

echo "=== sample details ===\n";
$q = $m->query(
	"SELECT l.ID, l.TITLE, LEFT(l.COMMENTS,80) COMMENTS
	 FROM b_crm_lead l $join
	 WHERE l.STATUS_ID IN ($in) AND ($detailSql)
	 ORDER BY l.ID DESC LIMIT 5"
);
if ($q) {
	while ($r = $q->fetch_assoc()) {
		echo json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
	}
}

echo "DONE\n";
