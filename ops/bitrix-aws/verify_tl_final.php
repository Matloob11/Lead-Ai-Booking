<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

echo "Jaweria groups=" . json_encode(CUser::GetUserGroup(2297)) . "\n";
echo "Jaweria IsAdmin=" . (CCrmPerms::IsAdmin(2297) ? 'Y' : 'N') . "\n";

$checks = [
	2560 => [
		'name' => 'Hassan',
		'team_lead' => 72765,
		'team_owner' => 89463,
		'out_lead' => 73148,
		'out_owner' => 89483,
		'cross_lead' => 73123,
	],
	2551 => [
		'name' => 'Hussnain',
		'team_lead' => 73051,
		'team_owner' => 86868,
		'out_lead' => 73148,
		'out_owner' => 89483,
		'cross_lead' => 72765,
	],
	2297 => [
		'name' => 'Jaweria',
		'team_lead' => 73123,
		'team_owner' => 80505,
		'out_lead' => 73148,
		'out_owner' => 89483,
		'cross_lead' => 72765,
	],
];

foreach ($checks as $uid => $c) {
	echo "==== {$c['name']} ($uid) ====\n";
	$perms = new CCrmPerms($uid);
	echo 'LEAD R/W=' . $perms->GetPermType('LEAD', 'READ') . '/' . $perms->GetPermType('LEAD', 'WRITE') . "\n";
	echo 'C13 R/W=' . $perms->GetPermType('DYNAMIC_1042_C13', 'READ') . '/' . $perms->GetPermType('DYNAMIC_1042_C13', 'WRITE') . "\n";
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	foreach (['team_lead' => [\CCrmOwnerType::Lead, $c['team_lead']], 'out_lead' => [\CCrmOwnerType::Lead, $c['out_lead']], 'cross_lead' => [\CCrmOwnerType::Lead, $c['cross_lead']], 'team_owner' => [1042, $c['team_owner']], 'out_owner' => [1042, $c['out_owner']]] as $label => $pair) {
		[$type, $id] = $pair;
		$r = $up->item()->canRead($type, $id) ? 'Y' : 'N';
		$w = $up->item()->canUpdate($type, $id) ? 'Y' : 'N';
		echo "$label id=$id read=$r write=$w\n";
	}
}

// phone mask config present?
echo "=== mask config ===\n";
$cfg = include '/home/bitrix/www/bitrix/php_interface/a7_tl_phone_mask.config.php';
echo 'leaders=' . json_encode($cfg['leader_ids'] ?? $cfg) . "\n";
echo 'js=' . (file_exists('/home/bitrix/www/bitrix/js/a7_tl_phone_mask.js') ? 'Y' : 'N') . ' size=' . filesize('/home/bitrix/www/bitrix/js/a7_tl_phone_mask.js') . "\n";
echo 'php=' . (file_exists('/home/bitrix/www/bitrix/tools/a7_tl_phone_mask.php') ? 'Y' : 'N') . "\n";
$init = file_get_contents('/home/bitrix/www/bitrix/php_interface/init.php');
echo 'init inject=' . (str_contains($init, 'a7_tl_phone_mask') ? 'Y' : 'N') . "\n";
