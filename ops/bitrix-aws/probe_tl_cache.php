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

echo "=== clear caches ===\n";
BXClearCache(true, '/crm/');
$cache = \Bitrix\Main\Application::getInstance()->getManagedCache();
$cache->cleanDir('b_crm_role_perms');
$cache->cleanDir('/crm/');
\Bitrix\Crm\Security\Role\Model\RolePermissionTable::getEntity()->cleanCache();
\CAccess::UpdateCodes(['USER_ID' => 2560]);
\CAccess::UpdateCodes(['USER_ID' => 2551]);
\CAccess::UpdateCodes(['USER_ID' => 2297]);
echo "cleared\n";

echo "=== isAdmin / groups ===\n";
foreach ([2560, 2551, 2297] as $uid) {
	$u = CUser::GetByID($uid)->Fetch();
	echo "$uid admin=" . (CCrmPerms::IsAdmin($uid) ? 'Y' : 'N')
		. ' groups=' . json_encode(CUser::GetUserGroup($uid))
		. "\n";
	$perms = new CCrmPerms($uid);
	echo "  LEAD READ=" . $perms->GetPermType('LEAD', 'READ')
		. ' C13 READ=' . $perms->GetPermType('DYNAMIC_1042_C13', 'READ') . "\n";
}

echo "=== role 6 sample ===\n";
$q = $m->query("SELECT ENTITY,PERM_TYPE,ATTR,LEFT(SETTINGS,80) S FROM b_crm_role_perms WHERE ROLE_ID=6 LIMIT 30");
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== G12 roles ===\n";
$q = $m->query(
	"SELECT r.ID,r.NAME,ru.RELATION FROM b_crm_role_relation ru
	 JOIN b_crm_role r ON r.ID=ru.ROLE_ID WHERE ru.RELATION='G12'"
);
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== HR nodes linked to iblock 69/70/71 ===\n";
// humanresources node table
foreach (['b_hr_structure_node', 'b_hr_structure', 'b_humanresources_node'] as $t) {
	$chk = $m->query("SHOW TABLES LIKE '$t'");
	if ($chk && $chk->num_rows) echo "table $t exists\n";
}
$q = $m->query('SHOW TABLES LIKE "%hr%"');
while ($r = $q->fetch_row()) echo $r[0] . "\n";

echo "=== access attr sample team lead 72765 ===\n";
$q = $m->query("SHOW TABLES LIKE 'b_crm_access_attr%'");
while ($r = $q->fetch_row()) echo $r[0] . "\n";
