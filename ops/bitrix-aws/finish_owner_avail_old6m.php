<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$to = 'DT1042_14:UC_YCY8JG';
$in = "'DT1042_14:NEW','DT1042_14:UC_73SP7H','DT1042_14:PREPARATION','DT1042_14:UC_G0PCBL','DT1042_14:UC_39DSJP','DT1042_14:UC_76AZKL','DT1042_14:UC_TEF133','DT1042_14:UC_G0Q73F','DT1042_14:UC_NZ4O27','DT1042_14:UC_CS8TJD','DT1042_14:UC_PKIJWV'";

$before = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID IN ($in)"
)->fetch_assoc()['c'];
echo "before_left=$before\n";

$m->query(
	"UPDATE b_crm_dynamic_items_1042
	 SET PREVIOUS_STAGE_ID=STAGE_ID,
	     STAGE_ID='$to',
	     MOVED_TIME=NOW(),
	     MOVED_BY=1
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID IN ($in)"
);
echo "affected=" . $m->affected_rows . "\n";

$left = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID IN ($in)"
)->fetch_assoc()['c'];
$inOld = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14 AND STAGE_ID='$to'"
)->fetch_assoc()['c'];
$other = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID<>14 AND STAGE_ID='$to'"
)->fetch_assoc()['c'];
$cat13 = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=13")->fetch_assoc()['c'];
echo "left_working_old=$left\n";
echo "now_in_old_stage=$inOld\n";
echo "old_stage_outside_cat14=$other\n";
echo "owner_data_cat13_untouched=$cat13\n";
echo "DONE\n";
