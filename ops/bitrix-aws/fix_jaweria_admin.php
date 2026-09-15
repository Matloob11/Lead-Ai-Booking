<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== groups ===\n";
$q = $m->query('SELECT ID,NAME,STRING_ID,ACTIVE FROM b_group WHERE ID IN (1,2,3,4,5,11,12,13,14,15,16,17)');
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== admin checks ===\n";
foreach ([2560, 2551, 2297] as $uid) {
	echo "$uid IsAdmin=" . (CCrmPerms::IsAdmin($uid) ? 'Y' : 'N')
		. ' groups=' . json_encode(CUser::GetUserGroup($uid)) . "\n";
}

// Remove Jaweria from Administrators (group 1) only — keep other groups
echo "=== remove 2297 from group 1 ===\n";
$groups = CUser::GetUserGroup(2297);
$groups = array_values(array_filter(array_map('intval', $groups), fn($g) => $g !== 1));
// Ensure employees-ish groups remain; always keep group 2 (everyone) if present
if (!in_array(2, $groups, true)) {
	$groups[] = 2;
}
$user = new CUser();
$ok = $user->Update(2297, ['GROUP_ID' => $groups]);
echo ($ok ? 'ok' : 'FAIL') . ' newGroups=' . json_encode(CUser::GetUserGroup(2297)) . ' err=' . $user->LAST_ERROR . "\n";

// Clear caches
BXClearCache(true, '/crm/');
$managed = \Bitrix\Main\Application::getInstance()->getManagedCache();
$managed->cleanDir('/crm/');
$access = new CAccess();
$access->UpdateCodes(['USER_ID' => 2297]);

echo "=== after: IsAdmin=" . (CCrmPerms::IsAdmin(2297) ? 'Y' : 'N') . " ===\n";
$perms = new CCrmPerms(2297);
echo 'LEAD R/W=' . $perms->GetPermType('LEAD', 'READ') . '/' . $perms->GetPermType('LEAD', 'WRITE') . "\n";
echo 'C13 R/W=' . $perms->GetPermType('DYNAMIC_1042_C13', 'READ') . '/' . $perms->GetPermType('DYNAMIC_1042_C13', 'WRITE') . "\n";

$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(2297);
$teamLead = 73123;
$outLead = 73148;
$teamOwner = 80505;
$outOwner = 89483;
echo 'team_lead canRead=' . ($up->item()->canRead(\CCrmOwnerType::Lead, $teamLead) ? 'Y' : 'N')
	. ' canUpdate=' . ($up->item()->canUpdate(\CCrmOwnerType::Lead, $teamLead) ? 'Y' : 'N') . "\n";
echo 'out_lead canRead=' . ($up->item()->canRead(\CCrmOwnerType::Lead, $outLead) ? 'Y' : 'N')
	. ' canUpdate=' . ($up->item()->canUpdate(\CCrmOwnerType::Lead, $outLead) ? 'Y' : 'N') . "\n";
echo 'team_owner canRead=' . ($up->item()->canRead(1042, $teamOwner) ? 'Y' : 'N')
	. ' canUpdate=' . ($up->item()->canUpdate(1042, $teamOwner) ? 'Y' : 'N') . "\n";
echo 'out_owner canRead=' . ($up->item()->canRead(1042, $outOwner) ? 'Y' : 'N')
	. ' canUpdate=' . ($up->item()->canUpdate(1042, $outOwner) ? 'Y' : 'N') . "\n";

// Hussnain samples
echo "=== Hussnain 2551 samples ===\n";
$q = $m->query(
	'SELECT ID,ASSIGNED_BY_ID FROM b_crm_lead
	 WHERE ASSIGNED_BY_ID IN (2381,2369,2371,2535,2368,2367,2351,2350)
	 ORDER BY ID DESC LIMIT 3'
);
$hussLeads = [];
while ($r = $q->fetch_assoc()) {
	$hussLeads[] = $r;
	echo 'lead ' . json_encode($r) . "\n";
}
$q = $m->query(
	'SELECT ID,ASSIGNED_BY_ID FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=13 AND ASSIGNED_BY_ID IN (2381,2369,2371,2535,2368,2367,2351,2350)
	 ORDER BY ID DESC LIMIT 3'
);
$hussOwners = [];
while ($r = $q->fetch_assoc()) {
	$hussOwners[] = $r;
	echo 'owner ' . json_encode($r) . "\n";
}
$up2 = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(2551);
foreach ($hussLeads as $r) {
	$id = (int)$r['ID'];
	echo "huss lead $id canRead=" . ($up2->item()->canRead(\CCrmOwnerType::Lead, $id) ? 'Y' : 'N')
		. ' canUpdate=' . ($up2->item()->canUpdate(\CCrmOwnerType::Lead, $id) ? 'Y' : 'N') . "\n";
}
foreach ($hussOwners as $r) {
	$id = (int)$r['ID'];
	echo "huss owner $id canRead=" . ($up2->item()->canRead(1042, $id) ? 'Y' : 'N')
		. ' canUpdate=' . ($up2->item()->canUpdate(1042, $id) ? 'Y' : 'N') . "\n";
}
echo 'huss out lead canRead=' . ($up2->item()->canRead(\CCrmOwnerType::Lead, $outLead) ? 'Y' : 'N') . "\n";

echo "DONE\n";
