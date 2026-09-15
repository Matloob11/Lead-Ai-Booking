<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$agents = [
	2560 => [2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303, 2560],
	2551 => [2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350, 2551],
	2297 => [2299, 2302, 2392, 2298, 2390, 2297],
];

// Stage IDs for cat 13
echo "=== stages cat 13 ===\n";
$q = $m->query(
	"SELECT STATUS_ID, NAME, SORT FROM b_crm_status
	 WHERE ENTITY_ID LIKE '%1042%C13%' OR ENTITY_ID LIKE '%DYNAMIC_1042_STAGE_13%'
	 ORDER BY SORT"
);
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}
$q = $m->query(
	"SELECT ENTITY_ID, STATUS_ID, NAME FROM b_crm_status
	 WHERE ENTITY_ID LIKE '%1042%' AND (NAME LIKE '%New Data%' OR NAME LIKE '%campaign%' OR ENTITY_ID LIKE '%13%')
	 LIMIT 40"
);
while ($r = $q->fetch_assoc()) {
	echo 's ' . json_encode($r) . "\n";
}

echo "=== stage counts ALL vs Hassan team ===\n";
$team = implode(',', $agents[2560]);
$q = $m->query(
	"SELECT STAGE_ID, COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=13 GROUP BY STAGE_ID ORDER BY c DESC"
);
$all = [];
while ($r = $q->fetch_assoc()) {
	$all[$r['STAGE_ID']] = (int)$r['c'];
}
$q = $m->query(
	"SELECT STAGE_ID, COUNT(*) c FROM b_crm_dynamic_items_1042
	 WHERE CATEGORY_ID=13 AND ASSIGNED_BY_ID IN ($team) GROUP BY STAGE_ID"
);
$hassan = [];
while ($r = $q->fetch_assoc()) {
	$hassan[$r['STAGE_ID']] = (int)$r['c'];
}
foreach ($all as $stage => $c) {
	$h = $hassan[$stage] ?? 0;
	echo "stage=$stage all=$c hassanTeam=$h\n";
}

echo "=== simulate kanban via factory+perms for Hassan ===\n";
$uid = 2560;
global $USER;
$USER = new CUser();
$USER->Authorize($uid);
$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);

// Get items through permission-aware getItemsRestrictedByPermissions if exists
$ref = new ReflectionObject($factory);
echo "factory class=" . get_class($factory) . "\n";

// Use Operation GetItems with permission
try {
	$items = $factory->getItemsFilteredByPermissions(
		[
			'select' => ['ID', 'ASSIGNED_BY_ID', 'STAGE_ID', 'TITLE'],
			'filter' => ['CATEGORY_ID' => 13],
			'limit' => 40,
			'order' => ['ID' => 'DESC'],
		],
		$uid
	);
	$assignees = [];
	$outside = 0;
	$teamSet = array_flip($agents[2560]);
	foreach ($items as $item) {
		$a = (int)$item->getAssignedById();
		$assignees[$a] = ($assignees[$a] ?? 0) + 1;
		if (!isset($teamSet[$a])) {
			$outside++;
			echo "OUTSIDER item={$item->getId()} assigned=$a\n";
		}
	}
	echo 'fetched=' . count($items) . " outside=$outside assignees=" . json_encode($assignees) . "\n";
} catch (Throwable $e) {
	echo 'getItemsFilteredByPermissions: ' . $e->getMessage() . "\n";
}

// Count with permission SQL
$sql = "
SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 i
WHERE i.CATEGORY_ID=13
  AND i.ID IN (
    SELECT P.ENTITY_ID FROM b_crm_access_attr_dynamic_1042 P
    WHERE P.USER_ID IN ($team) AND P.CATEGORY_ID IN (13)
  )
";
$q = $m->query($sql);
echo 'hassanPermCount=' . $q->fetch_assoc()['c'] . "\n";

// Non-team assignees among "visible" if someone bypasses
$sql2 = "
SELECT i.ASSIGNED_BY_ID, COUNT(*) c FROM b_crm_dynamic_items_1042 i
WHERE i.CATEGORY_ID=13
  AND i.ID IN (
    SELECT P.ENTITY_ID FROM b_crm_access_attr_dynamic_1042 P
    WHERE P.USER_ID IN ($team) AND P.CATEGORY_ID IN (13)
  )
  AND i.ASSIGNED_BY_ID NOT IN ($team)
GROUP BY i.ASSIGNED_BY_ID
ORDER BY c DESC LIMIT 10
";
$q = $m->query($sql2);
echo "non-team assignees in hassan-visible set:\n";
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
}

// Other roles for Hassan that might grant ALL on C13
echo "=== Hassan role relations + any ALL perms ===\n";
$ap = new \Bitrix\Crm\Security\AttributesProvider(2560);
$codes = $ap->getUserAttributesCodes();
$in = "'" . implode("','", array_map(fn($c) => $m->real_escape_string($c), $codes)) . "'";
$q = $m->query(
	"SELECT DISTINCT r.ID,r.NAME FROM b_crm_role_relation ru
	 JOIN b_crm_role r ON r.ID=ru.ROLE_ID
	 WHERE ru.RELATION IN ($in) OR ru.RELATION='U2560'"
);
$roleIds = [];
while ($r = $q->fetch_assoc()) {
	echo json_encode($r) . "\n";
	$roleIds[] = (int)$r['ID'];
}
if ($roleIds) {
	$rIn = implode(',', $roleIds);
	$q = $m->query(
		"SELECT ROLE_ID,ENTITY,PERM_TYPE,ATTR,SETTINGS FROM b_crm_role_perms
		 WHERE ROLE_ID IN ($rIn)
		   AND ENTITY IN ('DYNAMIC_1042','DYNAMIC_1042_C13','DYNAMIC_1042_C14')
		   AND PERM_TYPE='READ'"
	);
	while ($r = $q->fetch_assoc()) {
		echo 'perm ' . json_encode($r) . "\n";
	}
}
