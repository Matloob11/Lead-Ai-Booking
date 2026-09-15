#!/usr/bin/env php
<?php
/**
 * Verify heads see team / agents see self-only for LEAD + Owner Data 1042.
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

$teams = [
	2560 => [
		'name' => 'Hassan TL',
		'agents' => [2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303, 2560], // Uzma 2291
	],
	2551 => [
		'name' => 'Hussnain TL',
		'agents' => [2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350, 2551], // mehnaz 2381
	],
	2297 => [
		'name' => 'Jaweria TL',
		'agents' => [2299, 2302, 2392, 2298, 2390, 2297],
	],
];

$agentsOnly = [
	2291 => 'Uzma (Hassan team)',
	2381 => 'mehnaz (Hussnain team)',
	2367 => 'Warda (Hussnain team)',
	2299 => 'Farhat (Jaweria team)',
];

function attrsLabel(array $attrs): string
{
	$flat = [];
	foreach ($attrs as $group) {
		$flat[] = '[' . implode(',', (array)$group) . ']';
	}
	return implode(' | ', $flat) ?: '(none)';
}

function hasDeptScope(array $attrs): bool
{
	foreach ($attrs as $group) {
		foreach ((array)$group as $code) {
			$c = (string)$code;
			if ($c !== '' && ($c[0] === 'D' || str_starts_with($c, 'SND'))) {
				return true;
			}
		}
	}
	return false;
}

function isSelfOnly(array $attrs, int $uid): bool
{
	if (!$attrs) {
		return false;
	}
	$want = 'U' . $uid;
	foreach ($attrs as $group) {
		$g = array_map('strval', (array)$group);
		// self-only groups are exactly [U{uid}] (LEAD) or may include STAGE_ID* + U{uid}
		$hasUser = in_array($want, $g, true);
		$hasDept = false;
		foreach ($g as $c) {
			if ($c !== '' && ($c[0] === 'D' || str_starts_with($c, 'SND'))) {
				$hasDept = true;
			}
		}
		if ($hasDept) {
			return false;
		}
		if (!$hasUser) {
			return false;
		}
	}
	return true;
}

echo "======== PERMISSION ATTRS ========\n";
foreach ($teams as $uid => $t) {
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$leadA = $pm->getPermissionLevel('LEAD', 'READ')->getEntityAttributesToCheckInListMode();
	$c13A = $pm->getPermissionLevel('DYNAMIC_1042_C13', 'READ')->getEntityAttributesToCheckInListMode();
	echo sprintf(
		"HEAD %s (%d) LEAD=%s OD=%s deptScopeLead=%s deptScopeOD=%s\n  leadAttrs=%s\n  odAttrs=%s\n",
		$t['name'],
		$uid,
		$up->entityType()->canReadItems(\CCrmOwnerType::Lead) ? 'Y' : 'N',
		$up->entityType()->canReadItems(1042) ? 'Y' : 'N',
		hasDeptScope($leadA) ? 'Y' : 'N',
		hasDeptScope($c13A) ? 'Y' : 'N',
		attrsLabel($leadA),
		attrsLabel($c13A)
	);
}

foreach ($agentsOnly as $uid => $name) {
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$leadA = $pm->getPermissionLevel('LEAD', 'READ')->getEntityAttributesToCheckInListMode();
	$c13A = $pm->getPermissionLevel('DYNAMIC_1042_C13', 'READ')->getEntityAttributesToCheckInListMode();
	echo sprintf(
		"AGENT %s (%d) LEAD=%s OD=%s selfOnlyLead=%s selfOnlyOD=%s\n  leadAttrs=%s\n",
		$name,
		$uid,
		$up->entityType()->canReadItems(\CCrmOwnerType::Lead) ? 'Y' : 'N',
		$up->entityType()->canReadItems(1042) ? 'Y' : 'N',
		isSelfOnly($leadA, $uid) ? 'Y' : 'N',
		isSelfOnly($c13A, $uid) ? 'Y' : 'N',
		attrsLabel($leadA)
	);
}

echo "\n======== COUNT CHECK (assigned vs teammate) ========\n";

// For each agent: count own leads; for their head: count team leads
foreach ($teams as $headId => $t) {
	$teamIds = array_map('intval', $t['agents']);
	$in = implode(',', $teamIds);
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID IN ($in)");
	$teamLeads = (int)$q->fetch_assoc()['c'];
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID=" . (int)$headId);
	$headOwn = (int)$q->fetch_assoc()['c'];
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=13 AND ASSIGNED_BY_ID IN ($in)");
	$teamOd = (int)$q->fetch_assoc()['c'];
	echo "{$t['name']}: teamLeads=$teamLeads headOwnLeads=$headOwn teamOwnerDataC13=$teamOd\n";
}

foreach ($agentsOnly as $uid => $name) {
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID=" . (int)$uid);
	$ownL = (int)$q->fetch_assoc()['c'];
	// teammate sample: pick another agent from same team
	$teammate = null;
	$headId = null;
	foreach ($teams as $hid => $t) {
		if (in_array($uid, $t['agents'], true)) {
			$headId = $hid;
			foreach ($t['agents'] as $a) {
				if ((int)$a !== (int)$uid) {
					$teammate = (int)$a;
					break;
				}
			}
			break;
		}
	}
	$mateL = 0;
	if ($teammate) {
		$q = $m->query("SELECT COUNT(*) c FROM b_crm_lead WHERE ASSIGNED_BY_ID=$teammate");
		$mateL = (int)$q->fetch_assoc()['c'];
	}
	$q = $m->query("SELECT COUNT(*) c FROM b_crm_dynamic_items_1042 WHERE CATEGORY_ID=13 AND ASSIGNED_BY_ID=" . (int)$uid);
	$ownOd = (int)$q->fetch_assoc()['c'];

	// Permission canRead on a specific item owned by self vs teammate
	$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
	$selfItemId = 0;
	$mateItemId = 0;
	$q = $m->query("SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID=" . (int)$uid . " ORDER BY ID DESC LIMIT 1");
	if ($r = $q->fetch_assoc()) {
		$selfItemId = (int)$r['ID'];
	}
	if ($teammate) {
		$q = $m->query("SELECT ID FROM b_crm_lead WHERE ASSIGNED_BY_ID=$teammate ORDER BY ID DESC LIMIT 1");
		if ($r = $q->fetch_assoc()) {
			$mateItemId = (int)$r['ID'];
		}
	}

	$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($uid);
	$selfOk = '?';
	$mateOk = '?';
	$headOkOnMate = '?';
	try {
		if ($selfItemId) {
			$item = $factory->getItem($selfItemId);
			$selfOk = $up->item()->canReadItem($item) ? 'Y' : 'N';
		} else {
			$selfOk = 'no-item';
		}
		if ($mateItemId) {
			$item = $factory->getItem($mateItemId);
			$mateOk = $up->item()->canReadItem($item) ? 'Y' : 'N';
			$upHead = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions($headId);
			$headOkOnMate = $upHead->item()->canReadItem($item) ? 'Y' : 'N';
		} else {
			$mateOk = 'no-item';
			$headOkOnMate = 'no-item';
		}
	} catch (Throwable $e) {
		$selfOk = 'err:' . $e->getMessage();
		$mateOk = $selfOk;
	}

	echo "$name: ownLeads=$ownL ownOD=$ownOd teammate=$teammate mateLeads=$mateL "
		. "canReadOwnLead=$selfOk canReadTeammateLead=$mateOk headCanReadTeammateLead=$headOkOnMate\n";
}

echo "\n======== VERDICT ========\n";
$fail = 0;
foreach ($teams as $uid => $t) {
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$leadA = $pm->getPermissionLevel('LEAD', 'READ')->getEntityAttributesToCheckInListMode();
	$c13A = $pm->getPermissionLevel('DYNAMIC_1042_C13', 'READ')->getEntityAttributesToCheckInListMode();
	if (!hasDeptScope($leadA) && !hasDeptScope($c13A)) {
		echo "FAIL head {$t['name']}: no department scope\n";
		$fail++;
	} else {
		echo "OK head {$t['name']}: team/department scope present\n";
	}
}
foreach ($agentsOnly as $uid => $name) {
	$pm = \Bitrix\Crm\Security\Role\PermissionsManager::getInstance($uid);
	$leadA = $pm->getPermissionLevel('LEAD', 'READ')->getEntityAttributesToCheckInListMode();
	if (!isSelfOnly($leadA, $uid)) {
		echo "FAIL agent $name: not self-only LEAD\n";
		$fail++;
	} else {
		echo "OK agent $name: self-only LEAD\n";
	}
}
echo $fail === 0 ? "ALL CHECKS PASSED\n" : "FAILURES=$fail\n";
