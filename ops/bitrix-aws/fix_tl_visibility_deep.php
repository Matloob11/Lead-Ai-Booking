<?php
/**
 * Fix TL visibility for all 3 heads:
 * 1) Ensure UF_DEPARTMENT = only their TL section
 * 2) Rebuild CAccess codes (drop stale D41 etc.)
 * 3) Sync Human Resources nodes for depts 69/70/71 + heads
 * 4) Rebuild CRM access attrs for LEAD + Owner Data (1042)
 * 5) Keep role 54 READ=D WRITE=A, clear caches
 * 6) Verify team-only read / no write on agents
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('intranet');
\Bitrix\Main\Loader::includeModule('iblock');

$teams = [
	2560 => [
		'dept' => 69,
		'agents' => [2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303, 2560],
	],
	2551 => [
		'dept' => 70,
		'agents' => [2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350, 2551],
	],
	2297 => [
		'dept' => 71,
		'agents' => [2299, 2302, 2392, 2298, 2390, 2297],
	],
];

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

echo "=== 1. Force UF_DEPARTMENT ===\n";
$user = new CUser();
foreach ($teams as $headId => $t) {
	$all = array_unique($t['agents']);
	foreach ($all as $uid) {
		$ok = $user->Update((int)$uid, ['UF_DEPARTMENT' => [(int)$t['dept']]]);
		echo ($ok ? 'ok' : 'FAIL') . " user=$uid dept={$t['dept']} " . $user->LAST_ERROR . "\n";
	}
	// ensure UF_HEAD
	$m->query(
		'UPDATE b_uts_iblock_3_section SET UF_HEAD=' . (int)$headId
		. ' WHERE VALUE_ID=' . (int)$t['dept']
	);
}

echo "=== 2. Rebuild access codes ===\n";
$access = new CAccess();
foreach ($teams as $headId => $t) {
	foreach (array_unique($t['agents']) as $uid) {
		$access->UpdateCodes(['USER_ID' => (int)$uid]);
		echo "codes uid=$uid\n";
	}
}

echo "=== 3. HR structure sync (if API exists) ===\n";
$hrSynced = false;
if (\Bitrix\Main\Loader::includeModule('humanresources')) {
	try {
		// Prefer official sync from intranet departments
		if (class_exists(\Bitrix\HumanResources\Compat\Structure::class)
			&& method_exists(\Bitrix\HumanResources\Compat\Structure::class, 'syncAll')) {
			\Bitrix\HumanResources\Compat\Structure::syncAll();
			$hrSynced = true;
			echo "Compat\\Structure::syncAll done\n";
		} elseif (class_exists(\Bitrix\Intranet\HumanResources\DepartmentSynchronizer::class)) {
			echo "DepartmentSynchronizer class present\n";
		}

		// Fallback: find service sync
		$candidates = [
			'\\Bitrix\\HumanResources\\Service\\Sync\\DepartmentSyncService',
			'\\Bitrix\\HumanResources\\Install\\StructureInstaller',
			'\\Bitrix\\Intranet\\Service\\HumanResources\\Synchronizer',
		];
		foreach ($candidates as $cls) {
			if (class_exists($cls)) {
				echo "found $cls\n";
			}
		}

		// Node repository: link by iblock section id if columns exist
		$tbl = null;
		foreach (['b_hr_structure_node', 'b_humanresources_structure_node'] as $cand) {
			$chk = $m->query("SHOW TABLES LIKE '" . $m->real_escape_string($cand) . "'");
			if ($chk && $chk->num_rows) {
				$tbl = $cand;
				break;
			}
		}
		if ($tbl) {
			$cols = [];
			$cq = $m->query("SHOW COLUMNS FROM `$tbl`");
			while ($c = $cq->fetch_assoc()) {
				$cols[] = $c['Field'];
			}
			echo "HR table=$tbl cols=" . implode(',', $cols) . "\n";
			$q = $m->query("SELECT * FROM `$tbl` WHERE NAME LIKE '%Hassan%' OR NAME LIKE '%Hussnain%' OR NAME LIKE '%Jaweria%' OR NAME LIKE '%Sales%' LIMIT 30");
			while ($r = $q->fetch_assoc()) {
				echo 'node ' . json_encode($r) . "\n";
			}
		} else {
			$q = $m->query("SHOW TABLES LIKE '%structure_node%'");
			while ($r = $q->fetch_row()) {
				echo "maybe {$r[0]}\n";
			}
			$q = $m->query("SHOW TABLES LIKE 'b_hr%'");
			while ($r = $q->fetch_row()) {
				echo "hr {$r[0]}\n";
			}
		}
	} catch (Throwable $e) {
		echo 'HR sync err: ' . $e->getMessage() . "\n";
	}
} else {
	echo "humanresources module missing\n";
}

echo "=== 4. Clear CRM permission caches ===\n";
BXClearCache(true, '/crm/');
$managed = \Bitrix\Main\Application::getInstance()->getManagedCache();
$managed->cleanDir('/crm/');
$managed->cleanDir('/crm/user_permission_roles/');
$managed->cleanDir('/crm/user_access_codes/');
try {
	\Bitrix\Crm\Security\Role\Model\RolePermissionTable::getEntity()->cleanCache();
} catch (Throwable $e) {
	echo $e->getMessage() . "\n";
}

echo "=== 5. Rebuild entity access attributes (team assignees) ===\n";
// Leads
$agentIds = [];
foreach ($teams as $t) {
	$agentIds = array_merge($agentIds, $t['agents']);
}
$agentIds = array_unique(array_map('intval', $agentIds));
$in = implode(',', $agentIds);

$leadIds = [];
$q = $m->query("SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID IN ($in) ORDER BY ID DESC LIMIT 5000");
while ($r = $q->fetch_assoc()) {
	$leadIds[] = (int)$r['ID'];
}
echo 'leads to rebuild=' . count($leadIds) . "\n";

if (class_exists(\Bitrix\Crm\Security\Controller\Lead::class)
	|| true
) {
	$controller = \Bitrix\Crm\Service\Container::getInstance()
		->getUserPermissions()
		->getPermissionAttributesController(); // may not exist
}

// Use RegisterAccessAttributes / EntityController
$rebuilt = 0;
$failed = 0;
foreach (array_chunk($leadIds, 100) as $chunk) {
	foreach ($chunk as $leadId) {
		try {
			$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
			if (!$factory) {
				break 2;
			}
			$item = $factory->getItem($leadId);
			if (!$item) {
				continue;
			}
			\Bitrix\Crm\Service\Container::getInstance()
				->getUserPermissions()
				; // touch
			// Official API:
			\Bitrix\Crm\Security\Controller\Manager::getController(\CCrmOwnerType::Lead)
				->registerEntity($leadId, [
					'ASSIGNED_BY_ID' => $item->getAssignedById(),
					'OPENED' => $item->getOpened(),
					'CATEGORY_ID' => method_exists($item, 'getCategoryId') ? $item->getCategoryId() : 0,
				]);
			$rebuilt++;
		} catch (Throwable $e) {
			$failed++;
			if ($failed < 3) {
				echo 'lead rebuild err: ' . $e->getMessage() . "\n";
			}
		}
	}
}
echo "leads rebuilt=$rebuilt failed=$failed\n";

// Owner data dynamic 1042
$dynRebuilt = 0;
$dynFail = 0;
try {
	$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
	if ($factory) {
		$q = $m->query(
			"SELECT ID FROM b_crm_dynamic_items_1042 WHERE ASSIGNED_BY_ID IN ($in) ORDER BY ID DESC LIMIT 8000"
		);
		$ids = [];
		while ($r = $q->fetch_assoc()) {
			$ids[] = (int)$r['ID'];
		}
		echo 'owner items to rebuild=' . count($ids) . "\n";
		foreach ($ids as $id) {
			try {
				$item = $factory->getItem($id);
				if (!$item) {
					continue;
				}
				\Bitrix\Crm\Security\Controller\Manager::getController(1042)
					->registerEntity($id, [
						'ASSIGNED_BY_ID' => $item->getAssignedById(),
						'OPENED' => $item->getOpened(),
						'CATEGORY_ID' => $item->getCategoryId(),
					]);
				$dynRebuilt++;
			} catch (Throwable $e) {
				$dynFail++;
				if ($dynFail < 3) {
					echo 'dyn err: ' . $e->getMessage() . "\n";
				}
			}
		}
	}
} catch (Throwable $e) {
	echo 'dyn factory err: ' . $e->getMessage() . "\n";
}
echo "owner rebuilt=$dynRebuilt failed=$dynFail\n";

echo "=== 6. Verify access codes after rebuild ===\n";
foreach ([2560, 2551, 2297] as $uid) {
	echo "-- $uid --\n";
	$u = CUser::GetByID($uid)->Fetch();
	echo 'UF_DEPARTMENT=' . json_encode($u['UF_DEPARTMENT']) . "\n";
	$ap = new \Bitrix\Crm\Security\AttributesProvider($uid);
	$attrs = $ap->getUserAttributes();
	echo 'INTRANET=' . json_encode($attrs['INTRANET'] ?? []) . "\n";
	echo 'HR_DEPARTMENTS=' . json_encode($attrs['HR_DEPARTMENTS'] ?? []) . "\n";
	$perms = new CCrmPerms($uid);
	echo 'LEAD READ=' . $perms->GetPermType('LEAD', 'READ')
		. ' WRITE=' . $perms->GetPermType('LEAD', 'WRITE')
		. ' C13 READ=' . $perms->GetPermType('DYNAMIC_1042_C13', 'READ')
		. ' WRITE=' . $perms->GetPermType('DYNAMIC_1042_C13', 'WRITE')
		. "\n";
}

echo "DONE\n";
