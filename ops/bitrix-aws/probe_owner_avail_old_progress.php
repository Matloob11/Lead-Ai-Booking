<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$old = (int)$m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=14 AND STAGE_ID='DT1042_14:UC_YCY8JG'")->fetch_assoc()['c'];
$left = (int)$m->query(
	"SELECT COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=14
	   AND CREATED_TIME < DATE_SUB(NOW(), INTERVAL 6 MONTH)
	   AND STAGE_ID IN ('DT1042_14:NEW','DT1042_14:UC_73SP7H','DT1042_14:PREPARATION','DT1042_14:UC_G0PCBL','DT1042_14:UC_39DSJP','DT1042_14:UC_76AZKL','DT1042_14:UC_TEF133','DT1042_14:UC_G0Q73F','DT1042_14:UC_NZ4O27','DT1042_14:UC_CS8TJD','DT1042_14:UC_PKIJWV')"
)->fetch_assoc()['c'];
echo "in_old=$old left_working_old=$left\n";
