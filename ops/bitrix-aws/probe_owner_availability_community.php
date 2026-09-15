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

echo "=== community UFs on owner data ===\n";
$q = $m->query(
	"SELECT f.ID, f.ENTITY_ID, f.FIELD_NAME, f.USER_TYPE_ID, f.SETTINGS, l.EDIT_FORM_LABEL
	 FROM b_user_field f
	 LEFT JOIN b_user_field_lang l ON l.USER_FIELD_ID=f.ID AND l.LANGUAGE_ID='en'
	 WHERE (
	     f.ENTITY_ID IN ('CRM_1042','CRM_DYNAMIC_1042','DYNAMIC_1042')
	     OR f.ENTITY_ID LIKE '%1042%'
	   )
	   AND (
	     l.EDIT_FORM_LABEL LIKE '%Communit%'
	     OR f.FIELD_NAME LIKE '%COMMUNIT%'
	     OR f.FIELD_NAME LIKE '%COMMUNITY%'
	   )
	 ORDER BY f.ENTITY_ID, f.FIELD_NAME"
);
$fields = [];
while ($r = $q->fetch_assoc()) {
	$fields[] = $r;
	echo json_encode([
		'id' => $r['ID'],
		'entity' => $r['ENTITY_ID'],
		'field' => $r['FIELD_NAME'],
		'type' => $r['USER_TYPE_ID'],
		'label' => $r['EDIT_FORM_LABEL'],
	], JSON_UNESCAPED_UNICODE) . "\n";
}

echo "=== uts tables ===\n";
$tq = $m->query("SHOW TABLES LIKE 'b_uts%1042%'");
$uts = [];
while ($r = $tq->fetch_row()) {
	$uts[] = $r[0];
	echo $r[0] . "\n";
}
$tq = $m->query("SHOW TABLES LIKE 'b_uts_crm_dynamic%'");
while ($r = $tq->fetch_row()) {
	echo "also " . $r[0] . "\n";
}

if (!$fields) {
	echo "NO_COMMUNITY_FIELD\n";
	exit(0);
}

$utsTable = null;
foreach (['b_uts_crm_1042', 'b_uts_crm_dynamic_items_1042', 'b_uts_crm_item_1042'] as $cand) {
	if (in_array($cand, $uts, true)) {
		$utsTable = $cand;
		break;
	}
}
if (!$utsTable && $uts) {
	$utsTable = $uts[0];
}
echo "using_uts=$utsTable\n";

$colsQ = $m->query("SHOW COLUMNS FROM `$utsTable`");
$utsCols = [];
while ($c = $colsQ->fetch_assoc()) {
	$utsCols[] = $c['Field'];
}

$commCols = [];
foreach ($fields as $f) {
	if (in_array($f['FIELD_NAME'], $utsCols, true)) {
		$commCols[] = $f;
	}
}
if (!$commCols) {
	echo "community_cols_missing_in_uts\n";
	echo "uts_col_count=" . count($utsCols) . "\n";
	exit(0);
}

function filledSql(array $cols): string
{
	$parts = [];
	foreach ($cols as $col) {
		$parts[] = "(u.`$col` IS NOT NULL AND TRIM(CAST(u.`$col` AS CHAR)) <> '' AND CAST(u.`$col` AS CHAR) NOT IN ('0','a:0:{}'))";
	}
	return implode(' OR ', $parts);
}

$colNames = array_column($commCols, 'FIELD_NAME');
$filled = filledSql($colNames);

$sql = "SELECT
	COUNT(*) total,
	SUM(CASE WHEN ($filled) THEN 1 ELSE 0 END) with_community,
	SUM(CASE WHEN NOT ($filled) THEN 1 ELSE 0 END) blank_community
FROM b_crm_dynamic_items_1042 i
LEFT JOIN `$utsTable` u ON u.VALUE_ID=i.ID
WHERE i.CATEGORY_ID=14";
$q = $m->query($sql);
echo "=== category 14 community filled ===\n";
echo json_encode($q->fetch_assoc()) . "\n";

$availStages = [
	'DT1042_14:NEW',
	'DT1042_14:UC_73SP7H',
	'DT1042_14:PREPARATION',
	'DT1042_14:UC_G0PCBL',
	'DT1042_14:UC_76AZKL',
];
$in = "'" . implode("','", $availStages) . "'";
$sql2 = "SELECT
	COUNT(*) total,
	SUM(CASE WHEN ($filled) THEN 1 ELSE 0 END) with_community,
	SUM(CASE WHEN NOT ($filled) THEN 1 ELSE 0 END) blank_community
FROM b_crm_dynamic_items_1042 i
LEFT JOIN `$utsTable` u ON u.VALUE_ID=i.ID
WHERE i.CATEGORY_ID=14 AND i.STAGE_ID IN ($in)";
$q = $m->query($sql2);
echo "=== availability-named stages community ===\n";
echo json_encode($q->fetch_assoc()) . "\n";

echo "=== per community field ===\n";
foreach ($commCols as $f) {
	$col = $f['FIELD_NAME'];
	$one = filledSql([$col]);
	$q = $m->query(
		"SELECT
			SUM(CASE WHEN ($one) THEN 1 ELSE 0 END) filled,
			SUM(CASE WHEN NOT ($one) THEN 1 ELSE 0 END) blank
		 FROM b_crm_dynamic_items_1042 i
		 LEFT JOIN `$utsTable` u ON u.VALUE_ID=i.ID
		 WHERE i.CATEGORY_ID=14"
	);
	$row = $q->fetch_assoc();
	echo $col . "\t" . $f['EDIT_FORM_LABEL'] . "\t" . $f['USER_TYPE_ID'] . "\tfilled=" . $row['filled'] . "\tblank=" . $row['blank'] . "\n";
}

$main = $colNames[0];
foreach ($commCols as $f) {
	$lab = strtolower((string)$f['EDIT_FORM_LABEL']);
	if ($lab === 'community' || $f['FIELD_NAME'] === 'UF_CRM_1763390140') {
		$main = $f['FIELD_NAME'];
		break;
	}
}

echo "=== top values $main ===\n";
$q = $m->query(
	"SELECT CAST(u.`$main` AS CHAR) v, COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN `$utsTable` u ON u.VALUE_ID=i.ID
	 WHERE i.CATEGORY_ID=14
	   AND u.`$main` IS NOT NULL AND TRIM(CAST(u.`$main` AS CHAR)) <> ''
	   AND CAST(u.`$main` AS CHAR) NOT IN ('0','a:0:{}')
	 GROUP BY v
	 ORDER BY c DESC
	 LIMIT 30"
);
$vals = [];
while ($r = $q->fetch_assoc()) {
	$vals[] = $r;
	echo $r['c'] . "\t" . $r['v'] . "\n";
}

$mudon = 0;
$q = $m->query(
	"SELECT COUNT(*) c
	 FROM b_crm_dynamic_items_1042 i
	 LEFT JOIN `$utsTable` u ON u.VALUE_ID=i.ID
	 WHERE i.CATEGORY_ID=14
	   AND (
	     CAST(u.`$main` AS CHAR) LIKE '%[Mm]udon%'
	     OR CAST(u.`$main` AS CHAR) LIKE '%MUDON%'
	   )"
);
if ($q) {
	$mudon = (int)$q->fetch_assoc()['c'];
}
echo "mudon_text_on_$main=$mudon\n";

$types = [];
foreach ($commCols as $f) {
	$types[$f['FIELD_NAME']] = $f['USER_TYPE_ID'];
}
if (($types[$main] ?? '') === 'crm' && $vals) {
	$ids = [];
	foreach ($vals as $r) {
		if (preg_match('/^\d+$/', (string)$r['v'])) {
			$ids[] = (int)$r['v'];
		}
	}
	if ($ids) {
		echo "=== resolve crm community names ===\n";
		$idIn = implode(',', $ids);
		foreach (['b_crm_dynamic_items_1048', 'b_crm_dynamic_items_1050', 'b_iblock_element'] as $t) {
			$chk = $m->query("SHOW TABLES LIKE '$t'");
			if (!$chk || !$chk->num_rows) {
				continue;
			}
			if (strpos($t, 'iblock') !== false) {
				$rq = $m->query("SELECT ID, NAME FROM $t WHERE ID IN ($idIn)");
			} else {
				$rq = $m->query("SELECT ID, TITLE NAME FROM $t WHERE ID IN ($idIn)");
			}
			if (!$rq) {
				continue;
			}
			$n = 0;
			while ($r = $rq->fetch_assoc()) {
				echo $t . "\t" . $r['ID'] . "\t" . $r['NAME'] . "\n";
				$n++;
			}
			if ($n) {
				$mudQ = $m->query("SELECT ID, TITLE FROM $t WHERE TITLE LIKE '%Mudon%' OR TITLE LIKE '%MUDON%' LIMIT 20");
				if ($mudQ) {
					echo "=== $t mudon rows ===\n";
					$mudIds = [];
					while ($r = $mudQ->fetch_assoc()) {
						echo $r['ID'] . "\t" . $r['TITLE'] . "\n";
						$mudIds[] = (int)$r['ID'];
					}
					if ($mudIds) {
						$mIn = implode(',', $mudIds);
						$cnt = $m->query(
							"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 i
							 LEFT JOIN `$utsTable` u ON u.VALUE_ID=i.ID
							 WHERE i.CATEGORY_ID=14 AND u.`$main` IN ($mIn)"
						);
						echo "mudon_by_id_in_cat14=" . $cnt->fetch_assoc()['c'] . "\n";
					}
				}
			}
		}
	}
}

echo "DONE\n";
