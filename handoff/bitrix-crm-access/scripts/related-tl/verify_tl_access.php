<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('humanresources');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== HR roles ===\n";
$q = $m->query('SELECT * FROM b_hr_structure_role');
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== member roles for heads ===\n";
$q = $m->query(
	"SELECT m.ENTITY_ID,m.NODE_ID,mr.* FROM b_hr_structure_node_member m
	 LEFT JOIN b_hr_structure_node_member_role mr ON mr.MEMBER_ID=m.ID
	 WHERE m.ENTITY_ID IN (2560,2551,2297) AND m.NODE_ID IN (59,60,61)"
);
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== clear caches + rebuild codes all TL ===\n";
BXClearCache(true, '/crm/');
$managed = \Bitrix\Main\Application::getInstance()->getManagedCache();
$managed->cleanDir('/crm/');
$managed->cleanDir('/crm/user_permission_roles/');
$managed->cleanDir('/crm/user_access_codes/');
try {
	\Bitrix\Crm\Security\Role\Model\RolePermissionTable::getEntity()->cleanCache();
} catch (Throwable $e) {
}

$access = new CAccess();
foreach ([2560, 2551, 2297] as $uid) {
	$access->UpdateCodes(['USER_ID' => $uid]);
}

echo "=== verify each head ===\n";
$cases = [
	2560 => [
		'team_lead' => 72765, // Sapna
		'team_owner' => 89463, // Ruqia
		'out_lead' => null,
		'out_owner' => 89483,
	],
	2551 => [
		'team_lead' => null,
		'team_owner' => null,
		'out_lead' => null,
		'out_owner' => null,
	],
	2297 => [
		'team_lead' => null,
		'team_owner' => null,
		'out_lead' => null,
		'out_owner' => null,
	],
];

// find samples
$q = $m->query('SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID=1 ORDER BY ID DESC LIMIT 1');
$outLead = (int)$q->fetch_assoc()['ID'];
$q = $m->query('SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID=2369 ORDER BY ID DESC LIMIT 1'); // Hussnain agent
$hussLead = (int)(($q->fetch_assoc()['ID'] ?? 0));
$q = $m->query('SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID=2299 ORDER BY ID DESC LIMIT 1'); // Jaweria agent
$jawLead = (int)(($q->fetch_assoc()['ID'] ?? 0));
$q = $m->query('SELECT ID FROM b_crm_dynamic_items_1042 WHERE ASSIGNED_BY_ID=2369 AND CATEGORY_ID=13 ORDER BY ID DESC LIMIT 1');
$hussOwner = (int)(($q->fetch_assoc()['ID'] ?? 0));
$q = $m->query('SELECT ID FROM b_crm_dynamic_items_1042 WHERE ASSIGNED_BY_ID=2299 AND CATEGORY_ID=13 ORDER BY ID DESC LIMIT 1');
$jawOwner = (int)(($q->fetch_assoc()['ID'] ?? 0));
$q = $m->query('SELECT ID FROM b_crm_dynamic_items_1042 WHERE ASSIGNED_BY_ID=1 AND CATEGORY_ID=13 ORDER BY ID DESC LIMIT 1');
$outOwner = (int)(($q->fetch_assoc()['ID'] ?? 0));

$cases[2551]['team_lead'] = $hussLead;
$cases[2551]['team_owner'] = $hussOwner;
$cases[2297]['team_lead'] = $jawLead;
$cases[2297]['team_owner'] = $jawOwner;
foreach ($cases as $uid => &$c) {
	$c['out_lead'] = $outLead;
	$c['out_owner'] = $outOwner ?: 89483;
}
unset($c);

foreach ($cases as $uid => $c) {
	echo "==== USER $uid ====\n";
	$ap = new \Bitrix\Crm\Security\AttributesProvider($uid);
	$attrs = $ap->getUserAttributes();
	echo 'INTRANET=' . json_encode($attrs['INTRANET'] ?? []) . "\n";
	echo 'HR_DEP=' . json_encode($attrs['HR_DEPARTMENTS'] ?? []) . "\n";
	echo 'HR_SUB=' . json_encode($attrs['HR_SUBDEPARTMENTS'] ?? []) . "\n";

	$perms = new CCrmPerms($uid);
	echo 'LEAD R/W=' . $perms->GetPermType('LEAD', 'READ') . '/' . $perms->GetPermType('LEAD', 'WRITE') . "\n";
	echo 'C13 R/W=' . $perms->GetPermType('DYNAMIC_1042_C13', 'READ') . '/' . $perms->GetPermType('DYNAMIC_1042_C13', 'WRITE') . "\n";

	$userPerms = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);

	// Lead checks
	foreach (['team_lead' => $c['team_lead'], 'out_lead' => $c['out_lead']] as $label => $id) {
		if (!$id) {
			echo "$label: none\n";
			continue;
		}
		$canR = $userPerms->item()->canRead(\CCrmOwnerType::Lead, $id) ? 'Y' : 'N';
		$canU = $userPerms->item()->canUpdate(\CCrmOwnerType::Lead, $id) ? 'Y' : 'N';
		echo "$label id=$id canRead=$canR canUpdate=$canU\n";
	}

	// Owner data
	foreach (['team_owner' => $c['team_owner'], 'out_owner' => $c['out_owner']] as $label => $id) {
		if (!$id) {
			echo "$label: none\n";
			continue;
		}
		$canR = $userPerms->item()->canRead(1042, $id) ? 'Y' : 'N';
		$canU = $userPerms->item()->canUpdate(1042, $id) ? 'Y' : 'N';
		echo "$label id=$id canRead=$canR canUpdate=$canU\n";
	}

	// Cross-team: Hassan should NOT read Hussnain agent lead
	if ($uid === 2560 && $hussLead) {
		$canR = $userPerms->item()->canRead(\CCrmOwnerType::Lead, $hussLead) ? 'Y' : 'N';
		echo "cross Hussnain lead=$hussLead canRead=$canR (want N)\n";
	}
	if ($uid === 2560 && $jawLead) {
		$canR = $userPerms->item()->canRead(\CCrmOwnerType::Lead, $jawLead) ? 'Y' : 'N';
		echo "cross Jaweria lead=$jawLead canRead=$canR (want N)\n";
	}
}

echo "=== opened leads count sample ===\n";
$q = $m->query("SELECT OPENED, COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID IN (2434,2303,2369,2299) GROUP BY OPENED");
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "DONE\n";
