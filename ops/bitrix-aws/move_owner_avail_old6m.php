<?php
/**
 * Availability only (Owner Data category 14).
 * Items CREATED more than 6 months ago, still in working stages,
 * move to "Old Leads Before 6 Month". Closed stages stay put.
 * APPLY=0 dry-run; APPLY=1 move. Automation off.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$apply = getenv('APPLY') === '1';
$toStage = 'DT1042_14:UC_YCY8JG';
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
if ($m->connect_error) {
	fwrite(STDERR, "db fail\n");
	exit(2);
}

$st = $m->query(
	"SELECT STATUS_ID, NAME FROM b_crm_status
	 WHERE ENTITY_ID='DYNAMIC_1042_STAGE_14' AND STATUS_ID='" . $m->real_escape_string($toStage) . "'"
)->fetch_assoc();
if (!$st || stripos($st['NAME'], 'Old Leads') === false) {
	fwrite(STDERR, "old stage missing or renamed\n");
	exit(1);
}

$in = "'" . implode("','", array_map([$m, 'real_escape_string'], $working)) . "'";
$q = $m->query(
	"SELECT ID, TITLE, STAGE_ID, ASSIGNED_BY_ID, CREATED_TIME, CATEGORY_ID
	 FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID IN ($in)
	 ORDER BY ID"
);
$ids = [];
$wrongCat = 0;
while ($r = $q->fetch_assoc()) {
	if ((int)$r['CATEGORY_ID'] !== 14) {
		$wrongCat++;
		continue;
	}
	$ids[] = (int)$r['ID'];
}

$closedOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID NOT IN ($in)
	   AND STAGE_ID <> '" . $m->real_escape_string($toStage) . "'"
)->fetch_assoc()['c'];

echo "apply=" . ($apply ? 'yes' : 'no') . "\n";
echo "to_stage=$toStage name=" . $st['NAME'] . "\n";
echo "move_count=" . count($ids) . "\n";
echo "closed_old_left_in_place=$closedOld\n";
echo "wrong_category_skipped=$wrongCat\n";

if (!$apply) {
	echo "DRY_RUN\n";
	exit(0);
}

if ($wrongCat) {
	fwrite(STDERR, "refusing: non-14 ids\n");
	exit(1);
}

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$ok = 0;
$fail = 0;
$n = 0;
foreach ($ids as $id) {
	$n++;
	$item = $factory->getItem($id);
	if (!$item || (int)$item->getCategoryId() !== 14) {
		$fail++;
		echo "FAIL id=$id skip_not_cat14\n";
		continue;
	}
	$item->setStageId($toStage);
	$op = $factory->getUpdateOperation($item);
	$op->disableCheckAccess();
	if (method_exists($op, 'disableAutomation')) {
		$op->disableAutomation();
	}
	if (method_exists($op, 'disableBizProc')) {
		$op->disableBizProc();
	}
	$res = $op->launch();
	if ($res->isSuccess()) {
		$ok++;
	} else {
		$fail++;
		echo "FAIL id=$id " . implode('; ', $res->getErrorMessages()) . "\n";
	}
	if ($n % 200 === 0) {
		echo "progress $n/" . count($ids) . " ok=$ok fail=$fail\n";
	}
}
echo "moved_ok=$ok moved_fail=$fail\n";

$left = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID IN ($in)"
)->fetch_assoc()['c'];
$inOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID='" . $m->real_escape_string($toStage) . "'"
)->fetch_assoc()['c'];
$otherCat = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID<>14 AND STAGE_ID='" . $m->real_escape_string($toStage) . "'"
)->fetch_assoc()['c'];
echo "left_working_old=$left\n";
echo "now_in_old_stage=$inOld\n";
echo "old_stage_outside_cat14=$otherCat\n";
echo "DONE_MOVE\n";
