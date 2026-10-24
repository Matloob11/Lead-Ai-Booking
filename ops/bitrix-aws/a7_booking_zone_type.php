<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') {
	http_response_code(404);
	exit;
}
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
$conn = \Bitrix\Main\Application::getConnection();
$sql = $conn->getSqlHelper();
$rent = $conn->query("SELECT USER_TYPE_ID, SETTINGS FROM b_user_field WHERE ID=2686")->fetch();
$zone = $conn->query("SELECT USER_TYPE_ID, SETTINGS FROM b_user_field WHERE ID=2687")->fetch();
echo "rent_type=" . $rent['USER_TYPE_ID'] . " zone_type=" . $zone['USER_TYPE_ID'] . "\n";
if ((string)$zone['USER_TYPE_ID'] !== 'enumeration') {
	$settings = $sql->forSql((string)$rent['SETTINGS']);
	$conn->queryExecute(
		"UPDATE b_user_field SET USER_TYPE_ID='enumeration', SETTINGS='{$settings}' WHERE ID=2687 AND ENTITY_ID='CRM_LEAD'"
	);
	echo "updated\n";
}
$zone = $conn->query("SELECT USER_TYPE_ID FROM b_user_field WHERE ID=2687")->fetch();
echo "zone_type_now=" . $zone['USER_TYPE_ID'] . "\n";
$rs = $conn->query("SELECT ID, VALUE, SORT FROM b_user_field_enum WHERE USER_FIELD_ID=2687 ORDER BY SORT, ID");
while ($row = $rs->fetch()) {
	echo $row['SORT'] . "\t" . $row['VALUE'] . "\t" . $row['ID'] . "\n";
}
global $CACHE_MANAGER;
if (is_object($CACHE_MANAGER) && method_exists($CACHE_MANAGER, 'CleanAll')) {
	$CACHE_MANAGER->CleanAll();
	echo "cache cleared\n";
}
if (function_exists('BXClearCache')) {
	BXClearCache(true);
	echo "bx cache cleared\n";
}
