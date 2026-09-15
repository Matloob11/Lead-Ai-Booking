<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== Jaweria 2297 identity ===\n";
$u = CUser::GetByID(2297)->Fetch();
echo 'active=' . $u['ACTIVE'] . ' login=' . $u['LOGIN'] . ' email=' . $u['EMAIL'] . "\n";
echo 'groups=' . json_encode(CUser::GetUserGroup(2297)) . "\n";
echo 'IsAdmin=' . (CCrmPerms::IsAdmin(2297) ? 'Y' : 'N') . "\n";
echo 'IsAuthorizedAdmin=' . (\CCrmAuthorized::IsAdmin(2297) ? 'Y' : 'N') . "\n";

$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(2297);
$ref = new ReflectionObject($up);
foreach (['isAdmin', 'isCrmAdmin', 'getUserId'] as $mth) {
	if ($ref->hasMethod($mth)) {
		$meth = $ref->getMethod($mth);
		$meth->setAccessible(true);
		$v = $meth->invoke($up);
		echo "UserPermissions::$mth=" . json_encode($v) . "\n";
	}
}

echo "=== all role relations matching Jaweria access codes ===\n";
$ap = new \Bitrix\Crm\Security\AttributesProvider(2297);
$codes = $ap->getUserAttributesCodes();
echo 'codes count=' . count($codes) . "\n";
echo 'sample codes=' . json_encode(array_slice($codes, 0, 40)) . "\n";

$in = "'" . implode("','", array_map(function ($c) use ($m) {
	return $m->real_escape_string($c);
}, $codes)) . "'";
$q = $m->query(
	"SELECT r.ID,r.NAME,ru.RELATION FROM b_crm_role_relation ru
	 JOIN b_crm_role r ON r.ID=ru.ROLE_ID
	 WHERE ru.RELATION IN ($in) OR ru.RELATION='U2297' OR ru.RELATION='G12'
	 ORDER BY r.ID"
);
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== roles with LEAD READ ATTR=X ===\n";
$q = $m->query(
	"SELECT rp.ROLE_ID,r.NAME,rp.ENTITY,rp.PERM_TYPE,rp.ATTR,rp.SETTINGS
	 FROM b_crm_role_perms rp JOIN b_crm_role r ON r.ID=rp.ROLE_ID
	 WHERE rp.ENTITY='LEAD' AND rp.PERM_TYPE='READ'
	   AND (rp.ATTR='X' OR rp.SETTINGS LIKE '%ALL%')
	   AND (rp.FIELD='-' OR rp.FIELD='' OR rp.FIELD IS NULL)"
);
while ($r = $q->fetch_assoc()) echo json_encode($r) . "\n";

echo "=== PermissionsManager roles for 2297 ===\n";
$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance(2297);
$ref = new ReflectionObject($pm);
$meth = $ref->getMethod('getUserRoles');
$meth->setAccessible(true);
echo 'roleIds=' . json_encode($meth->invoke($pm)) . "\n";

echo "=== Hussnain team lead samples ===\n";
foreach ([2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350] as $aid) {
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID=$aid");
	$c1 = $q->fetch_assoc()['c'];
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE ASSIGNED_BY_ID=$aid AND CATEGORY_ID=13");
	$c2 = $q->fetch_assoc()['c'];
	if ($c1 || $c2) {
		echo "agent=$aid leads=$c1 owner13=$c2\n";
	}
}
