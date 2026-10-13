<?php
/**
 * A7 lead auto-shift CLI.
 * Default: --dry-run (zero writes).
 * --apply shifts: backlog = 1 per owner per run; fresh timers = all expired.
 */
declare(strict_types=1);

$opt = getopt('', [
	'dry-run',
	'apply',
	'limit:',
	'max-per-owner:',
	'i-understand-backlog',
	'ignore-window',
	'go-live:',
]);
$apply = isset($opt['apply']) && !isset($opt['dry-run']);
$limit = isset($opt['limit']) ? max(0, (int)$opt['limit']) : 500;
$maxPerOwner = isset($opt['max-per-owner']) ? max(1, (int)$opt['max-per-owner']) : 1;
$ignoreWindow = isset($opt['ignore-window']);

$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

if (!\CModule::IncludeModule('crm')) {
	fwrite(STDERR, "crm module missing\n");
	exit(1);
}

$here = is_file(__DIR__ . '/../roster.json') ? dirname(__DIR__) : __DIR__;
if (!defined('A7_ROSTER_CONFIG')) {
	define('A7_ROSTER_CONFIG', json_decode((string)file_get_contents($here . '/roster.json'), true, 512, JSON_THROW_ON_ERROR));
}
if (!class_exists('A7LeadShiftRoster')) {
	require $here . '/src/Clock.php';
	require $here . '/src/RentSale.php';
	require $here . '/src/Roster.php';
	require $here . '/src/Decision.php';
	require $here . '/src/Drip.php';
	require $here . '/src/LastWork.php';
	require $here . '/src/ActivityFields.php';
	require $here . '/src/Notify.php';
	require $here . '/src/Visibility.php';
	require $here . '/src/Community.php';
	require $here . '/src/Presence.php';
	require $here . '/src/Intake.php';
}

$cfg = A7_ROSTER_CONFIG;
$roster = new A7LeadShiftRoster($cfg);
$clock = A7LeadShiftClock::karachi();
$rentSale = A7LeadShiftRentSale::default();
$community = A7LeadShiftCommunity::fromRoster($roster, is_array($cfg['communityAliases'] ?? null) ? $cfg['communityAliases'] : []);
$decision = new A7LeadShiftDecision($roster, $clock, $rentSale, $community);

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

$stateDir = '/var/lib/a7-lead-shift';
$stateFile = $stateDir . '/state.json';
$lockFile = $stateDir . '/job.lock';

if (!is_dir($stateDir)) {
	@mkdir($stateDir, 0750, true);
}

$lock = @fopen($lockFile, 'c');
if ($lock === false || !flock($lock, LOCK_EX | LOCK_NB)) {
	echo "EXIT locked writes=0\n";
	exit(0);
}

$utc = new DateTimeZone('UTC');
$nowUtc = new DateTimeImmutable('now', $utc);

$state = [
	'go_live_at' => $nowUtc->format('Y-m-d H:i:s'),
	'received' => [],
	'overflow_cursor' => 0,
];
$hadGoLive = false;
if (is_readable($stateFile)) {
	$raw = json_decode((string)file_get_contents($stateFile), true);
	if (is_array($raw)) {
		if (isset($raw['go_live_at']) || isset($raw['received'])) {
			if (!empty($raw['go_live_at'])) {
				$state['go_live_at'] = (string)$raw['go_live_at'];
				$hadGoLive = true;
			}
			$state['received'] = is_array($raw['received'] ?? null) ? $raw['received'] : [];
			$state['overflow_cursor'] = (int)($raw['overflow_cursor'] ?? 0);
		} else {
			$state['received'] = $raw;
		}
	}
}
if (isset($opt['go-live']) && is_string($opt['go-live']) && $opt['go-live'] !== '') {
	$state['go_live_at'] = $opt['go-live'];
	$hadGoLive = true;
}

$goLiveAt = new DateTimeImmutable($state['go_live_at'], $utc);
$drip = new A7LeadShiftDrip($goLiveAt, $maxPerOwner);
$received = $state['received'];
$overflowCursor = (int)$state['overflow_cursor'];

if (!$hadGoLive) {
	a7_lead_shift_save_state($stateFile, $state['go_live_at'], $received, (int)$state['overflow_cursor']);
}

$intake = new A7LeadShiftIntake($roster, $community);
$present = A7LeadShiftPresence::load($m, $nowUtc);
$intakeOwners = $roster->intakeOwnerIds();
$intakeIn = implode(',', $intakeOwners);
$intakeLeads = [];
$iq = $m->query(
	"SELECT l.ID, l.TITLE, l.STATUS_ID, l.ASSIGNED_BY_ID, l.DATE_CREATE,
	        u.UF_CRM_1770537051525 community
	 FROM b_crm_lead l
	 LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
	 WHERE l.STATUS_ID='NEW' AND l.ASSIGNED_BY_ID IN ({$intakeIn})
	 ORDER BY l.ID DESC"
);
if ($iq) {
	while ($row = $iq->fetch_assoc()) {
		$created = a7_dt((string)$row['DATE_CREATE'], $utc);
		if ($created === null) {
			continue;
		}
		$communityRaw = trim((string)($row['community'] ?? ''));
		$intakeLeads[] = [
			'id' => (int)$row['ID'],
			'owner' => (int)$row['ASSIGNED_BY_ID'],
			'status' => (string)$row['STATUS_ID'],
			'title' => (string)$row['TITLE'],
			'community' => $communityRaw !== '' ? $communityRaw : null,
			'createdAt' => $created,
		];
	}
}
$intakeSelected = $intake->select($intakeLeads, $present, $nowUtc);
$clockedReceivers = [];
foreach ($present as $uid => $at) {
	$uid = (int)$uid;
	if (!$roster->canReceive($uid)) {
		continue;
	}
	$clockedReceivers[] = [
		'id' => $uid,
		'hours' => round(($nowUtc->getTimestamp() - $at->getTimestamp()) / 3600, 2),
	];
}
usort($clockedReceivers, static fn(array $a, array $b): int => $a['hours'] <=> $b['hours']);

echo json_encode([
	'mode' => $apply ? 'apply' : 'dry-run',
	'pkt' => $nowUtc->setTimezone(new DateTimeZone('Asia/Karachi'))->format('c'),
	'job_window' => $clock->isJobWindow($nowUtc),
	'go_live_at_utc' => $goLiveAt->format('c'),
	'limit' => $limit,
	'max_backlog_per_owner' => $maxPerOwner,
	'intake_owners' => $intakeOwners,
	'clocked_in' => count($present),
	'clocked_receivers' => count($clockedReceivers),
	'clocked_receiver_hours' => $clockedReceivers,
	'intake_scanned' => count($intakeLeads),
	'intake_this_minute' => count($intakeSelected),
], JSON_UNESCAPED_UNICODE) . "\n";

foreach ($intakeSelected as $row) {
	echo json_encode([
		'id' => $row['id'],
		'from' => $row['owner'],
		'to' => $row['next'],
		'status' => $row['status'],
		'lane' => $row['lane'],
		'need' => $row['need'],
		'eligible' => $row['eligibleMinutes'],
		'worked' => false,
		'kind' => $row['kind'],
		'route' => $row['route'],
		'group' => $row['groupLane'] ?? null,
		'community' => $row['community'] ?? null,
		'title' => mb_substr((string)$row['title'], 0, 80),
	], JSON_UNESCAPED_UNICODE) . "\n";
}

$intakeShifted = 0;
if ($apply && $intakeSelected !== []) {
	[$intakeShifted, $received] = a7_lead_shift_commit($intakeSelected, $received, $nowUtc, $roster, $overflowCursor);
}

if (!$ignoreWindow && !$clock->isJobWindow($nowUtc)) {
	if ($apply) {
		a7_lead_shift_save_state($stateFile, $state['go_live_at'], $received, (int)$overflowCursor);
	}
	echo "EXIT outside_job_window intake=" . ($apply ? $intakeShifted : count($intakeSelected))
		. " writes=" . ($apply ? $intakeShifted : 0) . "\n";
	exit(0);
}

$memberIds = $roster->watchUserIds();
$in = implode(',', $memberIds);
if ($in === '') {
	fwrite(STDERR, "roster empty\n");
	exit(1);
}

$sql = "
SELECT l.ID, l.TITLE, l.STATUS_ID, l.ASSIGNED_BY_ID, l.DATE_CREATE, l.MOVED_TIME, l.MOVED_BY_ID,
       u.UF_CRM_1735126982325 offering, u.UF_CRM_1756638760279 client_type,
       u.UF_CRM_1770537051525 community,
       cmt.last_work_tl, act.last_act
FROM b_crm_lead l
LEFT JOIN b_uts_crm_lead u ON u.VALUE_ID=l.ID
LEFT JOIN (
  SELECT b.ENTITY_ID eid, MAX(t.CREATED) last_work_tl
  FROM b_crm_timeline_bind b
  JOIN b_crm_timeline t ON t.ID=b.OWNER_ID
  JOIN b_crm_lead l2 ON l2.ID=b.ENTITY_ID AND l2.ASSIGNED_BY_ID=t.AUTHOR_ID
  WHERE b.ENTITY_TYPE_ID=1 AND t.TYPE_ID IN (7, 27)
    AND l2.STATUS_ID IN ('NEW','UC_MJDO60','12') AND l2.ASSIGNED_BY_ID IN ($in)
  GROUP BY b.ENTITY_ID
) cmt ON cmt.eid=l.ID
LEFT JOIN (
  SELECT a.OWNER_ID eid, MAX(GREATEST(a.CREATED, a.LAST_UPDATED)) last_act
  FROM b_crm_act a
  JOIN b_crm_lead l3 ON l3.ID=a.OWNER_ID
  WHERE a.OWNER_TYPE_ID=1
    AND l3.STATUS_ID IN ('NEW','UC_MJDO60','12') AND l3.ASSIGNED_BY_ID IN ($in)
    AND (
      (
        l3.ASSIGNED_BY_ID = a.RESPONSIBLE_ID
        AND a.PROVIDER_ID NOT IN ('CRM_WEBFORM', 'CRM_BIZPROC_WORKFLOW')
        AND a.PROVIDER_TYPE_ID IN (
          'CALL','TODO','SMS','RECORDING','LIVE_CALL','S3_RECORDING',
          'EMAIL','EMAIL_COMPRESSED','VISIT','TASKS_TASK'
        )
      )
      OR (
        a.PROVIDER_ID = 'IMOPENLINES_SESSION'
        AND (a.AUTHOR_ID = l3.ASSIGNED_BY_ID OR a.EDITOR_ID = l3.ASSIGNED_BY_ID)
      )
    )
  GROUP BY a.OWNER_ID
) act ON act.eid=l.ID
WHERE l.STATUS_ID IN ('NEW','UC_MJDO60','12') AND l.ASSIGNED_BY_ID IN ($in)
ORDER BY l.ID ASC
";
$q = $m->query($sql);
if (!$q) {
	fwrite(STDERR, $m->error."\n");
	exit(1);
}

$receivers = $roster->receiverIds();

function a7_dt(?string $s, DateTimeZone $utc): ?DateTimeImmutable
{
	if (!$s || $s === '0000-00-00 00:00:00') {
		return null;
	}
	return new DateTimeImmutable($s, $utc);
}

function a7_lead_shift_save_state(string $file, string $goLiveAt, array $received, int $overflowCursor = 0): void
{
	$dir = dirname($file);
	if (!is_dir($dir)) {
		@mkdir($dir, 0750, true);
	}
	$tmp = $file . '.tmp';
	$ok = file_put_contents($tmp, json_encode([
		'go_live_at' => $goLiveAt,
		'received' => $received,
		'overflow_cursor' => $overflowCursor,
	], JSON_UNESCAPED_UNICODE));
	if ($ok === false) {
		fwrite(STDERR, "state write failed\n");
		return;
	}
	rename($tmp, $file);
}

$candidates = [];
$scanned = 0;
while ($row = $q->fetch_assoc()) {
	$scanned++;
	$owner = (int)$row['ASSIGNED_BY_ID'];
	$id = (int)$row['ID'];
	$receivedAt = null;
	if (isset($received[(string)$id]['at'], $received[(string)$id]['user'])
		&& (int)$received[(string)$id]['user'] === $owner) {
		$receivedAt = a7_dt($received[(string)$id]['at'], $utc);
	}
	$workAt = A7LeadShiftLastWork::latest(
		a7_dt($row['last_work_tl'] ?? null, $utc),
		a7_dt($row['last_act'] ?? null, $utc),
	);
	$movedAt = a7_dt($row['MOVED_TIME'] ?? null, $utc);
	$movedBy = (int)$row['MOVED_BY_ID'];
	$assignStart = A7LeadShiftLastWork::assignmentStart(
		$receivedAt,
		$movedAt,
		$movedBy,
		$owner,
		a7_dt($row['DATE_CREATE'], $utc),
	);
	$ownerMoved = $movedBy === $owner ? $movedAt : null;
	$ownerWorked = A7LeadShiftLastWork::ownerWorkedThisAssignment($workAt, $assignStart);
	$last = A7LeadShiftLastWork::clockStart($assignStart, $ownerMoved, $workAt);
	if ($last === null) {
		continue;
	}

	$laneHint = null;
	if (
		isset($received[(string)$id]['lane'], $received[(string)$id]['user'])
		&& (int)$received[(string)$id]['user'] === $owner
	) {
		$laneHint = (string)$received[(string)$id]['lane'];
	}
	$communityRaw = trim((string)($row['community'] ?? ''));
	$verdict = $decision->decide([
		'id' => $id,
		'statusId' => (string)$row['STATUS_ID'],
		'assignedById' => $owner,
		'offering' => $row['offering'],
		'clientType' => $row['client_type'] !== null ? (string)$row['client_type'] : null,
		'lastWorkAt' => $last,
		'now' => $nowUtc,
		'ownerWorked' => $ownerWorked,
		'ignoreWindow' => $ignoreWindow,
		'firstTalkerId' => 0,
		'overflowAfter' => $overflowCursor > 0 ? $overflowCursor : null,
		'lane' => $laneHint,
		'community' => $communityRaw !== '' ? $communityRaw : null,
	]);
	if ($verdict['action'] !== 'shift') {
		continue;
	}
	$next = (int)$verdict['nextUserId'];
	$route = (string)($verdict['route'] ?? 'group');
	if ($route !== 'overflow' && ($next < 1 || $next === $owner)) {
		continue;
	}
	$candidates[] = [
		'id' => $id,
		'owner' => $owner,
		'lastWorkAt' => $last,
		'ownerWorked' => $ownerWorked,
		'eligibleMinutes' => (float)$verdict['eligibleMinutes'],
		'next' => $next,
		'route' => $route,
		'status' => (string)$row['STATUS_ID'],
		'need' => $verdict['needMinutes'],
		'kind' => $verdict['kind'],
		'groupLane' => $verdict['lane'] ?? null,
		'laneHint' => $laneHint,
		'offering' => $row['offering'],
		'clientType' => $row['client_type'] !== null ? (string)$row['client_type'] : null,
		'community' => $communityRaw !== '' ? $communityRaw : null,
		'title' => (string)$row['TITLE'],
	];
}

$selected = $drip->select($candidates);
if ($limit > 0) {
	$selected = array_slice($selected, 0, $limit);
}

$talkEvents = a7_lead_shift_talk_events($m, array_column($selected, 'id'));
foreach ($selected as $i => $row) {
	$talker = A7LeadShiftLastWork::firstOtherTalker(
		$talkEvents[(int)$row['id']] ?? [],
		(int)$row['owner'],
		$receivers
	);
	$verdict = $decision->decide([
		'id' => (int)$row['id'],
		'statusId' => (string)$row['status'],
		'assignedById' => (int)$row['owner'],
		'offering' => $row['offering'] ?? null,
		'clientType' => $row['clientType'] ?? null,
		'lastWorkAt' => $row['lastWorkAt'],
		'now' => $nowUtc,
		'ownerWorked' => !empty($row['ownerWorked']),
		'ignoreWindow' => $ignoreWindow,
		'firstTalkerId' => $talker ?? 0,
		'overflowAfter' => $overflowCursor > 0 ? $overflowCursor : null,
		'lane' => isset($row['laneHint']) && is_string($row['laneHint']) ? $row['laneHint'] : null,
		'community' => isset($row['community']) && is_string($row['community']) ? $row['community'] : null,
	]);
	if ($verdict['action'] !== 'shift') {
		unset($selected[$i]);
		continue;
	}
	$next = (int)$verdict['nextUserId'];
	$route = (string)($verdict['route'] ?? 'group');
	if ($route !== 'overflow' && ($next < 1 || $next === (int)$row['owner'])) {
		unset($selected[$i]);
		continue;
	}
	$selected[$i]['next'] = $next;
	$selected[$i]['route'] = $route;
	$selected[$i]['groupLane'] = $verdict['lane'] ?? null;
	$selected[$i]['need'] = $verdict['needMinutes'];
	$selected[$i]['kind'] = $verdict['kind'];
	$selected[$i]['eligibleMinutes'] = (float)$verdict['eligibleMinutes'];
}
$selected = array_values($selected);

$cursor = $overflowCursor > 0 ? $overflowCursor : null;
foreach ($selected as $i => $row) {
	if (($row['route'] ?? '') !== 'overflow') {
		continue;
	}
	$n = $roster->nextOverflow($cursor, (int)$row['owner']);
	if ($n === null || $n === (int)$row['owner']) {
		unset($selected[$i]);
		continue;
	}
	$selected[$i]['next'] = $n;
	$home = $roster->primaryGroup($n);
	if ($home !== null) {
		$selected[$i]['groupLane'] = $home;
	}
	$cursor = $n;
}
$returnCursor = 0;
foreach ($selected as $i => $row) {
	if (($row['route'] ?? '') !== 'return') {
		continue;
	}
	$lane = (string)($row['groupLane'] ?? 'International City');
	$n = $returnCursor > 0
		? $roster->nextInGroup($returnCursor, $lane, true)
		: (int)$row['next'];
	if ($n < 1) {
		$n = $roster->firstInGroup($lane) ?? 0;
	}
	if ($n < 1 || $n === (int)$row['owner']) {
		unset($selected[$i]);
		continue;
	}
	$selected[$i]['next'] = $n;
	$selected[$i]['groupLane'] = $lane;
	$returnCursor = $n;
}
$selected = array_values($selected);

$laneCounts = ['backlog' => 0, 'fresh' => 0];
foreach ($candidates as $c) {
	$lane = $drip->isBacklog($c['lastWorkAt']) ? 'backlog' : 'fresh';
	$laneCounts[$lane]++;
}

echo json_encode([
	'scanned' => $scanned,
	'expired' => count($candidates),
	'expired_backlog' => $laneCounts['backlog'],
	'expired_fresh' => $laneCounts['fresh'],
	'this_minute' => count($selected),
], JSON_UNESCAPED_UNICODE) . "\n";

$shifted = 0;
foreach ($selected as $row) {
	$lane = $row['lane'] ?? ($drip->isBacklog($row['lastWorkAt']) ? 'backlog' : 'fresh');
	echo json_encode([
		'id' => $row['id'],
		'from' => $row['owner'],
		'to' => $row['next'],
		'status' => $row['status'],
		'lane' => $lane,
		'need' => $row['need'],
		'eligible' => $row['eligibleMinutes'],
		'worked' => !empty($row['ownerWorked']),
		'kind' => $row['kind'],
		'route' => $row['route'] ?? 'group',
		'group' => $row['groupLane'] ?? null,
		'title' => mb_substr($row['title'], 0, 80),
	], JSON_UNESCAPED_UNICODE) . "\n";
}

if ($apply && $selected !== []) {
	[$shifted, $received] = a7_lead_shift_commit($selected, $received, $nowUtc, $roster, $overflowCursor);
}
if ($apply) {
	a7_lead_shift_save_state($stateFile, $state['go_live_at'], $received, (int)$overflowCursor);
}

$totalPlanned = count($intakeSelected) + count($selected);
$totalApplied = $intakeShifted + $shifted;
echo ($apply ? "APPLIED=$totalApplied" : "DRY_PLANNED=$totalPlanned") . " writes=" . ($apply ? $totalApplied : 0) . "\n";

/** Cancel Bitrix IM to silent users (Neha). Other agents unchanged. */
function a7_lead_shift_block_silent_im(array &$fields)
{
	$to = (int)($fields['TO_USER_ID'] ?? 0);
	$hide = $GLOBALS['A7_LEAD_SHIFT_HIDE_NOTIFY'] ?? [];
	if (is_array($hide) && in_array($to, $hide, true)) {
		return false;
	}
	if (!A7LeadShiftNotify::shouldNotify($to)) {
		return false;
	}
	return true;
}

/**
 * Talk history only for leads this minute may move. Full roster scan is too heavy.
 *
 * @param list<int> $leadIds
 * @return array<int, list<array{at:string,by:int}>>
 */
function a7_lead_shift_talk_events(mysqli $m, array $leadIds): array
{
	$ids = [];
	foreach ($leadIds as $id) {
		$id = (int)$id;
		if ($id > 0) {
			$ids[$id] = $id;
		}
	}
	if ($ids === []) {
		return [];
	}
	$in = implode(',', $ids);
	$talkEvents = [];
	$tl = $m->query(
		"SELECT b.ENTITY_ID eid, t.AUTHOR_ID uid, t.CREATED at
		 FROM b_crm_timeline t
		 INNER JOIN b_crm_timeline_bind b ON b.OWNER_ID = t.ID
		 WHERE b.ENTITY_TYPE_ID = 1
		   AND b.ENTITY_ID IN ({$in})
		   AND t.TYPE_ID IN (7, 27)
		   AND t.AUTHOR_ID > 1"
	);
	if ($tl) {
		while ($ev = $tl->fetch_assoc()) {
			$talkEvents[(int)$ev['eid']][] = [
				'at' => (string)$ev['at'],
				'by' => (int)$ev['uid'],
			];
		}
	}
	$acts = $m->query(
		"SELECT a.OWNER_ID eid, a.PROVIDER_ID, a.PROVIDER_TYPE_ID,
		        a.RESPONSIBLE_ID, a.AUTHOR_ID, a.EDITOR_ID,
		        GREATEST(a.CREATED, a.LAST_UPDATED) at
		 FROM b_crm_act a
		 WHERE a.OWNER_TYPE_ID = 1
		   AND a.OWNER_ID IN ({$in})
		   AND a.PROVIDER_ID NOT IN ('CRM_WEBFORM','CRM_BIZPROC_WORKFLOW')
		   AND (
		        a.PROVIDER_ID = 'IMOPENLINES_SESSION'
		        OR a.PROVIDER_TYPE_ID IN (
		            'CALL','TODO','SMS','RECORDING','LIVE_CALL','S3_RECORDING',
		            'EMAIL','EMAIL_COMPRESSED','VISIT','TASKS_TASK'
		        )
		   )"
	);
	if ($acts) {
		while ($ev = $acts->fetch_assoc()) {
			$actor = A7LeadShiftActivityFields::actActor($ev);
			if (
				$actor < 2
				|| !A7LeadShiftLastWork::isAgentActivity(
					(string)$ev['PROVIDER_ID'],
					(string)$ev['PROVIDER_TYPE_ID'],
					$actor,
					(int)$ev['RESPONSIBLE_ID'],
					(int)$ev['AUTHOR_ID'],
					(int)$ev['EDITOR_ID']
				)
			) {
				continue;
			}
			$talkEvents[(int)$ev['eid']][] = [
				'at' => (string)$ev['at'],
				'by' => $actor,
			];
		}
	}
	return $talkEvents;
}

/**
 * @param list<array> $rows
 * @return array{0:int,1:array<string, mixed>}
 */
function a7_lead_shift_commit(
	array $rows,
	array $received,
	DateTimeImmutable $nowUtc,
	A7LeadShiftRoster $roster,
	int &$overflowCursor,
): array {
	if (!defined('A7_LEAD_SHIFT_SILENT_IM')) {
		define('A7_LEAD_SHIFT_SILENT_IM', true);
		AddEventHandler('im', 'OnBeforeMessageNotifyAdd', 'a7_lead_shift_block_silent_im');
	}
	$shifted = 0;
	foreach ($rows as $row) {
		$id = (int)$row['id'];
		$next = (int)$row['next'];
		$oldStatus = (string)$row['status'];
		$applied = a7_lead_shift_assign($id, $next, $oldStatus);
		if (isset($GLOBALS['APPLICATION']) && is_object($GLOBALS['APPLICATION'])) {
			$GLOBALS['APPLICATION']->ResetException();
		}
		if (!$applied['ok']) {
			echo json_encode(['id' => $id, 'error' => $applied['error']]) . "\n";
			continue;
		}

		$outLane = (string)($row['groupLane'] ?? '');
		if (($row['route'] ?? '') === 'overflow') {
			$overflowCursor = $next;
			$home = $roster->primaryGroup($next);
			if ($home !== null) {
				$outLane = $home;
			}
		}
		$received[(string)$id] = [
			'user' => $next,
			'at' => $nowUtc->format('Y-m-d H:i:s'),
			'lane' => $outLane,
		];
		$label = (($row['route'] ?? '') === 'intake') ? 'auto-assign' : 'auto-shift';
		if (A7LeadShiftNotify::shouldNotify($next) && \CModule::IncludeModule('im')) {
			try {
				\CIMNotify::Add([
					'TO_USER_ID' => $next,
					'FROM_USER_ID' => 0,
					'NOTIFY_TYPE' => IM_NOTIFY_SYSTEM,
					'NOTIFY_MODULE' => 'crm',
					'NOTIFY_EVENT' => 'a7_lead_shift',
					'NOTIFY_MESSAGE' => "Lead [url=/crm/lead/details/{$id}/]".htmlspecialcharsbx((string)$row['title'])."[/url] aap ko assign hui ({$label}). Pehli history timeline mein hai.",
				]);
			} catch (\Throwable $e) {
				echo json_encode(['id' => $id, 'warn' => 'notify_failed']) . "\n";
			}
		}
		$shifted++;
	}
	return [$shifted, $received];
}

/**
 * @return array{ok:bool,error?:string}
 */
function a7_lead_shift_assign(int $id, int $next, string $oldStatus): array
{
	$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
	if ($factory === null) {
		return ['ok' => false, 'error' => 'lead_factory_missing'];
	}
	$item = $factory->getItem($id);
	if ($item === null) {
		return ['ok' => false, 'error' => 'lead_not_found'];
	}
	$from = (int)$item->getAssignedById();
	$GLOBALS['A7_LEAD_SHIFT_HIDE_NOTIFY'] = $from > 1 && $from !== $next ? [$from] : [];
	$item->setAssignedById($next);
	// Admin (user 1) holds the lead in New Lead. Handing it to an agent
	// moves it to Assigned. Do not put the old New Lead stage back.
	$targetStatus = $oldStatus;
	if ($oldStatus === 'NEW' && $next !== 1) {
		$targetStatus = 'UC_MJDO60';
		$item->setStageId($targetStatus);
	}
	$context = new \Bitrix\Crm\Service\Context();
	$context->setUserId(1);
	$op = $factory->getUpdateOperation($item, $context);
	$op->disableCheckAccess();
	$op->disableAutomation();
	$op->disableBizProc();
	$result = $op->launch();
	if (!$result->isSuccess()) {
		$GLOBALS['A7_LEAD_SHIFT_HIDE_NOTIFY'] = [];
		return ['ok' => false, 'error' => implode('; ', $result->getErrorMessages()) ?: 'update_failed'];
	}

	$fresh = $factory->getItem($id);
	if ($fresh === null || (int)$fresh->getAssignedById() !== $next) {
		$GLOBALS['A7_LEAD_SHIFT_HIDE_NOTIFY'] = [];
		return ['ok' => false, 'error' => 'assign_not_persisted'];
	}
	if ((string)$fresh->getStageId() !== $targetStatus) {
		$fresh->setStageId($targetStatus);
		$op2 = $factory->getUpdateOperation($fresh, $context);
		$op2->disableCheckAccess();
		$op2->disableAutomation();
		$op2->disableBizProc();
		$op2->launch();
	}
	A7LeadShiftVisibility::afterReassign($id, $from, $next);
	$GLOBALS['A7_LEAD_SHIFT_HIDE_NOTIFY'] = [];
	return ['ok' => true];
}
