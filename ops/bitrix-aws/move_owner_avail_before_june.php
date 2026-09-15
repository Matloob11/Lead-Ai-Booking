<?php
/**
 * Availability only (category 14): working-stage cards created before 2026-06-01
 * → Old Leads Before 6 Month. Sold/Failed/Not Interested stay put.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$apply = getenv('APPLY') === '1';
$to = 'DT1042_14:UC_YCY8JG';
$cutoff = '2026-06-01 00:00:00';
$working = [
	'DT1042_14:NEW',
	'DT1042_14:UC_73SP7H',
	'DT1042_14:PREPARATION',
	'DT1042_14:UC_G0PCBL',
	'DT1042_14:UC_39DSJP',
	'DT1042_14:UC_76AZKL',
	'DT1042_14:UC_TEF133',
	'DT1042_14:UC_G0Q73F',
	'DT1042_14:UC_NZ4O27',
	'DT1042_14:UC_CS8TJD',
	'DT1042_14:UC_PKIJWV',
];

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$st = $m->query(
	"SELECT NAME FROM b_crm_status
	 WHERE ENTITY_ID='DYNAMIC_1042_STAGE_14' AND STATUS_ID='$to'"
)->fetch_assoc();
if (!$st || stripos($st['NAME'], 'Old Leads') === false) {
	fwrite(STDERR, "old stage missing\n");
	exit(1);
}

$in = "'" . implode("','", array_map([$m, 'real_escape_string'], $working)) . "'";
$cut = $m->real_escape_string($cutoff);

$q = $m->query(
	"SELECT STAGE_ID, COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND CREATED_TIME < '$cut' AND STAGE_ID IN ($in)
	 GROUP BY STAGE_ID"
);
echo "cutoff=$cutoff apply=" . ($apply ? 'yes' : 'no') . "\n";
echo "=== to move by stage ===\n";
$move = 0;
while ($r = $q->fetch_assoc()) {
	$move += (int)$r['c'];
	echo $r['c'] . "\t" . $r['STAGE_ID'] . "\n";
}
echo "move_count=$move\n";

$alreadyOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID='$to'"
)->fetch_assoc()['c'];
$closedBefore = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND CREATED_TIME < '$cut'
	   AND STAGE_ID NOT IN ($in) AND STAGE_ID <> '$to'"
)->fetch_assoc()['c'];
$workingNow = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID IN ($in)"
)->fetch_assoc()['c'];
echo "already_in_old=$alreadyOld\n";
echo "closed_before_june_left=$closedBefore\n";
echo "working_now=$workingNow\n";

if (!$apply) {
	echo "DRY_RUN\n";
	exit(0);
}

$m->query(
	"UPDATE b_crm_dynamic_items_1042
	 SET PREVIOUS_STAGE_ID=STAGE_ID,
	     STAGE_ID='$to',
	     MOVED_TIME=NOW(),
	     MOVED_BY=1
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < '$cut'
	   AND STAGE_ID IN ($in)"
);
echo "affected=" . $m->affected_rows . "\n";

$leftWorkingOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND CREATED_TIME < '$cut' AND STAGE_ID IN ($in)"
)->fetch_assoc()['c'];
$inOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID='$to'"
)->fetch_assoc()['c'];
$outside = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID<>14 AND STAGE_ID='$to'"
)->fetch_assoc()['c'];
$cat13 = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=13"
)->fetch_assoc()['c'];
$remainWorking = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID IN ($in)"
)->fetch_assoc()['c'];
$remainAllExceptOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID <> '$to'"
)->fetch_assoc()['c'];
echo "left_working_before_june=$leftWorkingOld\n";
echo "now_in_old=$inOld\n";
echo "old_outside_cat14=$outside\n";
echo "cat13=$cat13\n";
echo "remain_working=$remainWorking\n";
echo "remain_except_old=$remainAllExceptOld\n";
echo "DONE\n";
