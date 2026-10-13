<?php
/**
 * Team bulk assign tool — Pakistan TL teams equal / community-wise.
 * Deploy to: /bitrix/tools/a7_team_assign.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);

if (!defined('A7_TEAM_ASSIGN_AS_LIB') || !A7_TEAM_ASSIGN_AS_LIB) {
    require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
    header('Content-Type: application/json; charset=utf-8');
}

function a7_ta_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function a7_ta_config(): array
{
    $candidates = [
        (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_team_assign.config.php',
        (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/tools/a7_team_assign.config.php',
        __DIR__ . '/a7_team_assign.config.php',
    ];
    foreach ($candidates as $candidate) {
        if (is_readable($candidate)) {
            $cfg = include $candidate;
            return is_array($cfg) ? $cfg : [];
        }
    }
    return [];
}

function a7_ta_user(): ?CUser
{
    global $USER;
    return (is_object($USER) && $USER->IsAuthorized()) ? $USER : null;
}

function a7_ta_ids_from_request(): array
{
    $raw = $_POST['ids'] ?? $_REQUEST['ids'] ?? [];
    if (is_string($raw)) {
        $decoded = json_decode($raw, true);
        $raw = is_array($decoded) ? $decoded : preg_split('/[,\s]+/', $raw);
    }
    if (!is_array($raw)) {
        return [];
    }
    $out = [];
    foreach ($raw as $id) {
        $n = (int)$id;
        if ($n > 0 && !in_array($n, $out, true)) {
            $out[] = $n;
        }
    }
    return $out;
}

function a7_ta_entity(): string
{
    $raw = strtolower(trim((string)($_REQUEST['entity'] ?? 'lead')));
    if (in_array($raw, ['owner_data', 'owner', '1042_13'], true)) {
        return 'owner_data';
    }
    if (in_array($raw, ['availability', 'avail', '1042_14'], true)) {
        return 'availability';
    }
    if (in_array($raw, ['renewal', 'renewals', 'deal'], true)) {
        return 'renewal';
    }
    return 'lead';
}

function a7_ta_json_body(string $key, $default = null)
{
    $raw = $_POST[$key] ?? null;
    if (is_string($raw)) {
        $decoded = json_decode($raw, true);
        return $decoded !== null ? $decoded : $default;
    }
    return $raw !== null ? $raw : $default;
}

function a7_ta_user_name(int $uid): string
{
    if ($uid <= 0) {
        return '';
    }
    $u = CUser::GetByID($uid)->Fetch();
    if (!is_array($u)) {
        return 'User ' . $uid;
    }
    $name = trim((string)($u['NAME'] ?? '') . ' ' . (string)($u['LAST_NAME'] ?? ''));
    return $name !== '' ? $name : ('User ' . $uid);
}

function a7_ta_active_user(int $uid): bool
{
    if ($uid <= 0) {
        return false;
    }
    $u = CUser::GetByID($uid)->Fetch();
    return is_array($u) && ($u['ACTIVE'] ?? 'N') === 'Y';
}

function a7_ta_dept_members(int $deptId, array $fallback): array
{
    $ids = [];
    if ($deptId > 0 && class_exists('CIntranetUtils')) {
        try {
            $emp = CIntranetUtils::GetDepartmentEmployees($deptId, true, false, 'Y');
            if (is_array($emp)) {
                foreach ($emp as $uid) {
                    $n = (int)$uid;
                    if ($n > 0) {
                        $ids[] = $n;
                    }
                }
            } elseif (is_object($emp) && method_exists($emp, 'Fetch')) {
                while ($row = $emp->Fetch()) {
                    $n = (int)($row['ID'] ?? $row['USER_ID'] ?? 0);
                    if ($n > 0) {
                        $ids[] = $n;
                    }
                }
            }
        } catch (Throwable $e) {
            $ids = [];
        }
    }
    if (!$ids) {
        $ids = array_map('intval', $fallback);
    }
    $out = [];
    foreach ($ids as $uid) {
        if ($uid > 0 && a7_ta_active_user($uid) && !in_array($uid, $out, true)) {
            $out[] = $uid;
        }
    }
    return $out;
}

function a7_ta_all_users(): array
{
    static $cache = null;
    if ($cache !== null) {
        return $cache;
    }
    $ids = [];
    $by = 'last_name';
    $order = 'asc';
    $rs = CUser::GetList(
        $by,
        $order,
        ['ACTIVE' => 'Y'],
        ['FIELDS' => ['ID', 'NAME', 'LAST_NAME', 'LOGIN', 'ACTIVE'], 'SELECT' => ['UF_DEPARTMENT']]
    );
    while ($rs && ($row = $rs->Fetch())) {
        $uid = (int)($row['ID'] ?? 0);
        if ($uid <= 0 || ($row['ACTIVE'] ?? 'N') !== 'Y') {
            continue;
        }
        $dept = $row['UF_DEPARTMENT'] ?? null;
        $hasDept = is_array($dept) ? count($dept) > 0 : ($dept !== null && $dept !== '' && $dept !== '0' && $dept !== false);
        if (!$hasDept) {
            continue;
        }
        $name = trim((string)($row['NAME'] ?? '') . ' ' . (string)($row['LAST_NAME'] ?? ''));
        if ($name === '') {
            continue;
        }
        $ids[$uid] = $name;
    }
    $users = [];
    foreach ($ids as $uid => $name) {
        $users[] = ['id' => (int)$uid, 'name' => $name];
    }
    usort($users, static function ($a, $b) {
        return strcasecmp($a['name'], $b['name']);
    });
    $cache = $users;
    return $cache;
}

function a7_ta_teams(array $cfg): array
{
    $teams = [];
    foreach ((array)($cfg['teams'] ?? []) as $team) {
        $head = (int)($team['head_id'] ?? 0);
        $dept = (int)($team['dept_id'] ?? 0);
        $fallback = array_map('intval', (array)($team['member_ids'] ?? []));
        $members = a7_ta_dept_members($dept, $fallback);
        $receivers = [];
        foreach ($members as $uid) {
            if ($uid === $head) {
                continue;
            }
            $receivers[] = [
                'id' => $uid,
                'name' => a7_ta_user_name($uid),
            ];
        }
        $teams[] = [
            'key' => (string)($team['key'] ?? ''),
            'label' => (string)($team['label'] ?? ''),
            'head_id' => $head,
            'head_name' => a7_ta_user_name($head),
            'dept_id' => $dept,
            'agents' => $receivers,
        ];
    }
    return $teams;
}

function a7_ta_receivers_for_heads(array $cfg, array $headIds): array
{
    $want = [];
    foreach ($headIds as $h) {
        $want[(int)$h] = true;
    }
    if (!$want) {
        foreach ((array)($cfg['teams'] ?? []) as $team) {
            $want[(int)($team['head_id'] ?? 0)] = true;
        }
    }
    $agents = [];
    foreach (a7_ta_teams($cfg) as $team) {
        if (empty($want[(int)$team['head_id']])) {
            continue;
        }
        foreach ($team['agents'] as $agent) {
            $id = (int)$agent['id'];
            if ($id > 0) {
                $agents[$id] = $agent;
            }
        }
    }
    return array_values($agents);
}

function a7_ta_stages(string $entity): array
{
    $stages = [['id' => '__KEEP__', 'name' => 'Keep current stage']];
    if (!\Bitrix\Main\Loader::includeModule('crm')) {
        return $stages;
    }
    if ($entity === 'lead' && class_exists('CCrmStatus')) {
        $db = CCrmStatus::GetList(['SORT' => 'ASC'], ['ENTITY_ID' => 'STATUS']);
        while ($row = $db->Fetch()) {
            $stages[] = [
                'id' => (string)$row['STATUS_ID'],
                'name' => (string)$row['NAME'],
            ];
        }
        return $stages;
    }
    if (($entity === 'owner_data' || $entity === 'availability') && class_exists(\Bitrix\Crm\Service\Container::class)) {
        $categoryId = $entity === 'availability' ? 14 : 13;
        $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
        if ($factory) {
            foreach ($factory->getStages($categoryId) as $stage) {
                $stages[] = [
                    'id' => (string)$stage->getStatusId(),
                    'name' => (string)$stage->getName(),
                ];
            }
        }
        return $stages;
    }
    if ($entity === 'renewal' && class_exists('CCrmStatus')) {
        $db = CCrmStatus::GetList(['SORT' => 'ASC'], ['ENTITY_ID' => 'DEAL_STAGE_9']);
        $any = false;
        while ($row = $db->Fetch()) {
            $any = true;
            $stages[] = [
                'id' => (string)$row['STATUS_ID'],
                'name' => (string)$row['NAME'],
            ];
        }
        if (!$any) {
            $db = CCrmStatus::GetList(['SORT' => 'ASC'], ['ENTITY_ID' => 'DEAL_STAGE']);
            while ($row = $db->Fetch()) {
                $stages[] = [
                    'id' => (string)$row['STATUS_ID'],
                    'name' => (string)$row['NAME'],
                ];
            }
        }
    }
    return $stages;
}

function a7_ta_community_bucket(?string $name): string
{
    if ($name === null || $name === '' || $name === '(no community)') {
        return 'other';
    }
    $n = mb_strtolower(trim($name));
    if (strpos($n, 'international city') !== false) {
        return 'international_city';
    }
    if (strpos($n, 'villanova') !== false) {
        return 'villanova';
    }
    if (strpos($n, 'lagoon') !== false) {
        return 'lagoons';
    }
    if (strpos($n, 'serena') !== false) {
        return 'serena';
    }
    if (strpos($n, 'the valley') !== false || $n === 'valley') {
        return 'valley';
    }
    if (
        strpos($n, 'arabian ranches') !== false
        || $n === 'caya' || $n === 'raya' || $n === 'joy' || $n === 'anya' || $n === 'sun'
        || strpos($n, 'bliss') !== false
    ) {
        return 'ranches';
    }
    if (strpos($n, 'mudon') !== false) {
        return 'mudon';
    }
    if (strpos($n, 'hills') !== false) {
        return 'hills';
    }
    if (strpos($n, 'haven') !== false) {
        return 'haven';
    }
    if (strpos($n, 'acres') !== false) {
        return 'acres';
    }
    return 'other';
}

function a7_ta_comm_titles(): array
{
    static $cache = null;
    if ($cache !== null) {
        return $cache;
    }
    $cache = [];
    global $DB;
    if (!is_object($DB)) {
        return $cache;
    }
    $q = $DB->Query('SELECT ID, TITLE FROM b_crm_dynamic_items_1058');
    while ($r = $q->Fetch()) {
        $cache[(int)$r['ID']] = trim((string)$r['TITLE']);
    }
    return $cache;
}

function a7_ta_lead_community(int $id, array $cfg): string
{
    global $DB;
    $linkField = (string)($cfg['lead_community_link'] ?? 'UF_CRM_1763390140');
    $textField = (string)($cfg['lead_community_text'] ?? 'UF_CRM_1770537051525');
    $cols = [];
    $cq = $DB->Query('SHOW COLUMNS FROM b_uts_crm_lead');
    while ($c = $cq->Fetch()) {
        $cols[$c['Field']] = true;
    }
    $select = ['VALUE_ID'];
    if (!empty($cols[$linkField])) {
        $select[] = '`' . $DB->ForSql($linkField) . '` AS link_v';
    }
    if (!empty($cols[$textField])) {
        $select[] = '`' . $DB->ForSql($textField) . '` AS text_v';
    }
    if (count($select) < 2) {
        return '';
    }
    $row = $DB->Query(
        'SELECT ' . implode(', ', $select) . ' FROM b_uts_crm_lead WHERE VALUE_ID=' . (int)$id
    )->Fetch();
    if (!is_array($row)) {
        return '';
    }
    $link = $row['link_v'] ?? null;
    if (is_string($link) && $link !== '' && ctype_digit($link)) {
        $titles = a7_ta_comm_titles();
        return $titles[(int)$link] ?? '';
    }
    if (is_numeric($link) && (int)$link > 0) {
        $titles = a7_ta_comm_titles();
        return $titles[(int)$link] ?? '';
    }
    if (is_string($link) && $link !== '' && isset($link[0]) && $link[0] === 'a') {
        $un = @unserialize($link);
        if (is_array($un)) {
            foreach ($un as $v) {
                if (is_numeric($v) && (int)$v > 0) {
                    $titles = a7_ta_comm_titles();
                    return $titles[(int)$v] ?? '';
                }
            }
        }
    }
    return trim((string)($row['text_v'] ?? ''));
}

function a7_ta_spa_community(int $id): string
{
    if (!class_exists(\Bitrix\Crm\Service\Container::class)) {
        return '';
    }
    $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
    if (!$factory) {
        return '';
    }
    $item = $factory->getItem($id);
    if (!$item) {
        return '';
    }
    $cid = (int)$item->get('PARENT_ID_1058');
    if ($cid > 0) {
        $titles = a7_ta_comm_titles();
        return $titles[$cid] ?? ('community #' . $cid);
    }
    return '';
}

function a7_ta_deal_community(int $id): string
{
    // Best-effort: search deal UTS columns whose value matches a community title length,
    // else empty → no-community bucket.
    global $DB;
    $row = $DB->Query('SELECT * FROM b_uts_crm_deal WHERE VALUE_ID=' . (int)$id)->Fetch();
    if (!is_array($row)) {
        return '';
    }
    $titles = a7_ta_comm_titles();
    $byTitle = [];
    foreach ($titles as $tid => $title) {
        if ($title !== '') {
            $byTitle[mb_strtolower($title)] = $title;
        }
    }
    foreach ($row as $key => $val) {
        if ($key === 'VALUE_ID' || $val === null || $val === '') {
            continue;
        }
        if (is_numeric($val) && isset($titles[(int)$val])) {
            return $titles[(int)$val];
        }
        if (is_string($val)) {
            $low = mb_strtolower(trim($val));
            if (isset($byTitle[$low])) {
                return $byTitle[$low];
            }
        }
    }
    $deal = class_exists('CCrmDeal') ? CCrmDeal::GetByID($id, false) : null;
    if (is_array($deal)) {
        $title = mb_strtolower((string)($deal['TITLE'] ?? ''));
        foreach ($byTitle as $low => $pretty) {
            if ($low !== '' && mb_strpos($title, $low) !== false) {
                return $pretty;
            }
        }
    }
    return '';
}

function a7_ta_load_cards(string $entity, array $ids, array $cfg): array
{
    $cards = [];
    foreach ($ids as $id) {
        $id = (int)$id;
        if ($id <= 0) {
            continue;
        }
        if ($entity === 'lead') {
            if (!class_exists('CCrmLead') || !CCrmLead::CheckUpdatePermission($id)) {
                continue;
            }
            $lead = CCrmLead::GetByID($id, false);
            if (!is_array($lead)) {
                continue;
            }
            $comm = a7_ta_lead_community($id, $cfg);
            $cards[] = [
                'id' => $id,
                'title' => (string)($lead['TITLE'] ?? ''),
                'stage_id' => (string)($lead['STATUS_ID'] ?? ''),
                'assigned_by' => (int)($lead['ASSIGNED_BY_ID'] ?? 0),
                'community' => $comm,
                'bucket' => a7_ta_community_bucket($comm !== '' ? $comm : null),
            ];
            continue;
        }
        if ($entity === 'owner_data' || $entity === 'availability') {
            if (!class_exists(\Bitrix\Crm\Service\Container::class)) {
                continue;
            }
            $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
            if (!$factory) {
                continue;
            }
            $item = $factory->getItem($id);
            if (!$item) {
                continue;
            }
            $wantCat = $entity === 'availability' ? 14 : 13;
            if ((int)$item->getCategoryId() !== $wantCat) {
                // Still allow if user selected from mixed URL; keep item.
            }
            if (!$factory->getItemPermissionChecker() || true) {
                // Permission: rely on factory update later.
            }
            $comm = a7_ta_spa_community($id);
            $cards[] = [
                'id' => $id,
                'title' => (string)$item->getTitle(),
                'stage_id' => (string)$item->getStageId(),
                'assigned_by' => (int)$item->getAssignedById(),
                'community' => $comm,
                'bucket' => a7_ta_community_bucket($comm !== '' ? $comm : null),
            ];
            continue;
        }
        if ($entity === 'renewal') {
            if (!class_exists('CCrmDeal') || !CCrmDeal::CheckUpdatePermission($id)) {
                continue;
            }
            $deal = CCrmDeal::GetByID($id, false);
            if (!is_array($deal)) {
                continue;
            }
            $comm = a7_ta_deal_community($id);
            $cards[] = [
                'id' => $id,
                'title' => (string)($deal['TITLE'] ?? ''),
                'stage_id' => (string)($deal['STAGE_ID'] ?? ''),
                'assigned_by' => (int)($deal['ASSIGNED_BY_ID'] ?? 0),
                'community' => $comm,
                'bucket' => a7_ta_community_bucket($comm !== '' ? $comm : null),
            ];
        }
    }
    return $cards;
}

function a7_ta_equal_plan(array $cardIds, array $agentIds): array
{
    $agentIds = array_values(array_unique(array_map('intval', $agentIds)));
    $cardIds = array_values(array_map('intval', $cardIds));
    $assignments = [];
    $counts = [];
    foreach ($agentIds as $uid) {
        $counts[$uid] = 0;
    }
    if (!$agentIds || !$cardIds) {
        return ['assignments' => [], 'counts' => $counts, 'skipped' => []];
    }
    $n = count($agentIds);
    foreach ($cardIds as $i => $cid) {
        $uid = $agentIds[$i % $n];
        $assignments[] = ['id' => $cid, 'user_id' => $uid];
        $counts[$uid]++;
    }
    return ['assignments' => $assignments, 'counts' => $counts, 'skipped' => []];
}

function a7_ta_community_plan(array $cards, array $agentIds, array $cfg, string $noCommMode, int $noCommUser): array
{
    $agentSet = [];
    foreach ($agentIds as $uid) {
        $agentSet[(int)$uid] = true;
    }
    $pools = (array)($cfg['community_pools'] ?? []);
    $byBucket = [];
    $noComm = [];
    foreach ($cards as $card) {
        $b = (string)($card['bucket'] ?? 'other');
        if ($b === 'other' || ($card['community'] ?? '') === '') {
            $noComm[] = $card;
            continue;
        }
        $byBucket[$b][] = $card;
    }
    $assignments = [];
    $counts = [];
    foreach ($agentIds as $uid) {
        $counts[(int)$uid] = 0;
    }
    $rr = [];
    foreach ($byBucket as $bucket => $list) {
        $pool = array_values(array_filter(
            array_map('intval', (array)($pools[$bucket] ?? [])),
            static function ($uid) use ($agentSet) {
                return !empty($agentSet[$uid]);
            }
        ));
        if (!$pool) {
            $pool = array_map('intval', $agentIds);
        }
        if (!$pool) {
            continue;
        }
        foreach ($list as $card) {
            $i = $rr[$bucket] ?? 0;
            $uid = $pool[$i % count($pool)];
            $rr[$bucket] = $i + 1;
            $assignments[] = ['id' => (int)$card['id'], 'user_id' => $uid];
            $counts[$uid] = ($counts[$uid] ?? 0) + 1;
        }
    }
    $skipped = [];
    if ($noComm) {
        if ($noCommMode === 'skip') {
            foreach ($noComm as $card) {
                $skipped[] = (int)$card['id'];
            }
        } elseif ($noCommMode === 'user' && $noCommUser > 0 && !empty($agentSet[$noCommUser])) {
            foreach ($noComm as $card) {
                $assignments[] = ['id' => (int)$card['id'], 'user_id' => $noCommUser];
                $counts[$noCommUser] = ($counts[$noCommUser] ?? 0) + 1;
            }
        } else {
            // round-robin across selected agents
            $pool = array_map('intval', $agentIds);
            $i = 0;
            foreach ($noComm as $card) {
                if (!$pool) {
                    $skipped[] = (int)$card['id'];
                    continue;
                }
                $uid = $pool[$i % count($pool)];
                $i++;
                $assignments[] = ['id' => (int)$card['id'], 'user_id' => $uid];
                $counts[$uid] = ($counts[$uid] ?? 0) + 1;
            }
        }
    }
    return [
        'assignments' => $assignments,
        'counts' => $counts,
        'skipped' => $skipped,
        'no_community' => count($noComm),
        'by_bucket' => array_map('count', $byBucket),
    ];
}

function a7_ta_plan_from_counts(array $cardIds, array $countMap): array
{
    $cardIds = array_values(array_map('intval', $cardIds));
    $queue = $cardIds;
    $assignments = [];
    $counts = [];
    $needed = 0;
    foreach ($countMap as $uid => $n) {
        $uid = (int)$uid;
        $n = max(0, (int)$n);
        $counts[$uid] = $n;
        $needed += $n;
    }
    if ($needed !== count($cardIds)) {
        return ['error' => 'Count total (' . $needed . ') must equal selected cards (' . count($cardIds) . ').'];
    }
    foreach ($countMap as $uid => $n) {
        $uid = (int)$uid;
        $n = max(0, (int)$n);
        for ($i = 0; $i < $n; $i++) {
            if (!$queue) {
                break;
            }
            $cid = array_shift($queue);
            $assignments[] = ['id' => $cid, 'user_id' => $uid];
        }
    }
    return ['assignments' => $assignments, 'counts' => $counts, 'skipped' => []];
}

function a7_ta_apply_one(string $entity, int $id, int $userId, string $stage): array
{
    if ($entity === 'lead') {
        if (!class_exists('CCrmLead') || !CCrmLead::CheckUpdatePermission($id)) {
            return ['ok' => false, 'error' => 'no permission'];
        }
        $fields = ['ASSIGNED_BY_ID' => $userId];
        if ($stage !== '' && $stage !== '__KEEP__') {
            $fields['STATUS_ID'] = $stage;
        }
        // PHP 8.2: CCrmLead::Update is an instance method — static call fatals with HTML <pre>.
        $crmLead = new CCrmLead(false);
        $ok = $crmLead->Update($id, $fields, true, true, [
            'DISABLE_USER_FIELD_CHECK' => true,
            'REGISTER_SONET_EVENT' => false,
        ]);
        if ($ok) {
            return ['ok' => true, 'error' => ''];
        }
        global $APPLICATION;
        $ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
        return ['ok' => false, 'error' => $ex ? (string)$ex->GetString() : 'lead update failed'];
    }
    if ($entity === 'owner_data' || $entity === 'availability') {
        $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
        if (!$factory) {
            return ['ok' => false, 'error' => 'factory missing'];
        }
        $item = $factory->getItem($id);
        if (!$item) {
            return ['ok' => false, 'error' => 'item missing'];
        }
        if ((int)$item->getCategoryId() !== ($entity === 'availability' ? 14 : 13)) {
            return ['ok' => false, 'error' => 'not a card of this list'];
        }
        $actingUserId = is_object($GLOBALS['USER'] ?? null) ? (int)$GLOBALS['USER']->GetID() : 0;
        if ($actingUserId <= 0) {
            return ['ok' => false, 'error' => 'no signed-in user'];
        }
        $item->setAssignedById($userId);
        if ($stage !== '' && $stage !== '__KEEP__') {
            $item->setStageId($stage);
        }
        $ctx = new \Bitrix\Crm\Service\Context();
        $ctx->setUserId($actingUserId);
        $op = $factory->getUpdateOperation($item, $ctx);
        // Access stays on, as it is for leads and deals: without it anyone logged in could
        // reassign any Owner Data card by ID. The background worker runs as the job's owner.
        $op->disableCheckFields();
        $result = $op->launch();
        return ['ok' => $result->isSuccess(), 'error' => $result->isSuccess() ? '' : implode('; ', $result->getErrorMessages())];
    }
    if ($entity === 'renewal') {
        if (!class_exists('CCrmDeal') || !CCrmDeal::CheckUpdatePermission($id)) {
            return ['ok' => false, 'error' => 'no permission'];
        }
        $fields = ['ASSIGNED_BY_ID' => $userId];
        if ($stage !== '' && $stage !== '__KEEP__') {
            $fields['STAGE_ID'] = $stage;
        }
        $crmDeal = new CCrmDeal(false);
        $ok = $crmDeal->Update($id, $fields, true, true, [
            'DISABLE_USER_FIELD_CHECK' => true,
            'REGISTER_SONET_EVENT' => false,
        ]);
        if ($ok) {
            return ['ok' => true, 'error' => ''];
        }
        global $APPLICATION;
        $ex = is_object($APPLICATION) ? $APPLICATION->GetException() : null;
        return ['ok' => false, 'error' => $ex ? (string)$ex->GetString() : 'deal update failed'];
    }
    return ['ok' => false, 'error' => 'unknown entity'];
}

/*
 * FOR ALL — every card the list on screen matches, across all of its pages.
 *
 * The filter is never rebuilt from what the browser posts. Bitrix's filter widget hands
 * out UI values, not query values: Responsible arrives as the string ["user","2344"],
 * dates as _datesel/_from/_to. Passed to GetListEx they match nothing. On 2026-10-02 the
 * Leads list filtered to Responsible = Aila (122 leads) resolved FOR ALL to 0, and the
 * modal fell back to the 20 rows ticked on the page without saying so.
 *
 * Each list is asked for the filter it used itself — the one Bitrix's own "Total: Show"
 * counts with:
 *   lead     GridContext, which crm.lead.list writes on every render
 *   renewal  $_SESSION['CRM_GRID_DATA'], which crm.deal.list writes on every render
 *   1042     crm.item.list's own getListFilter(), from the user's saved filter
 * Every row on the page must then be in the answer, and the filter must be the one the
 * tab drew its page with (a7_ta_filter_stamp), or it is refused. There is no fallback:
 * a filter that cannot be found is an error, never "everything".
 */

/**
 * The grid the browser is on, if it is one FOR ALL works on — never a stand-in. A report
 * drill-down (report_<n>_grid) or Owner Data's "All items" (crm-type-item-list-1042) keeps
 * its own filter; substituting the main list's would assign a different set of cards.
 */
function a7_ta_list_grid_id(string $entity, string $posted): string
{
    $patterns = [
        'lead' => '/^CRM_LEAD_LIST_V\d+$/',
        'renewal' => '/^CRM_DEAL_LIST_V\d+_C_9$/',
        'owner_data' => '/^crm-type-item-list-1042-13$/',
        'availability' => '/^crm-type-item-list-1042-14$/',
    ];
    $posted = trim($posted);
    return isset($patterns[$entity]) && preg_match($patterns[$entity], $posted) ? $posted : '';
}

/**
 * Fingerprint of what a list was last drawn from. The browser takes it each time its grid
 * is drawn and sends it back with FOR ALL; if another tab has redrawn the list with another
 * filter since, the two differ and FOR ALL is refused — the check Bitrix's own bulk delete
 * makes with USER_FILTER_HASH, which this version no longer hands to scripts.
 * Leads/Renewals: the session filter the list wrote. Owner Data/Availability keep none in
 * the session, so the saved filter they are built from (UI values, not dates resolved to
 * today, so the stamp does not drift on its own).
 */
function a7_ta_filter_stamp(string $entity, string $gridId): string
{
    if ($gridId === '') {
        return '';
    }
    if ($entity === 'lead' || $entity === 'renewal') {
        $filter = $_SESSION['CRM_GRID_DATA'][$gridId]['FILTER'] ?? null;
        return is_array($filter) ? md5(serialize($filter)) : '';
    }
    try {
        $options = new \Bitrix\Main\UI\Filter\Options($gridId);
        $current = (string)$options->getCurrentFilterId();
        $settings = $options->getFilterSettings($current);
        $fields = is_array($settings) ? (array)($settings['fields'] ?? []) : [];
        $fields = array_filter($fields, static function ($value) {
            return $value !== '' && $value !== null && $value !== [];
        });
        ksort($fields);
        return md5(json_encode([$current, $fields, (string)$options->getSearchString()]));
    } catch (Throwable $e) {
        return '';
    }
}

/**
 * IDs of every row the browser's grid was showing, ticked or not.
 */
function a7_ta_page_ids(): array
{
    $raw = $_POST['page_ids'] ?? '';
    $list = is_string($raw) ? json_decode($raw, true) : $raw;
    if (!is_array($list)) {
        return [];
    }
    $out = [];
    foreach ($list as $value) {
        $id = (int)$value;
        if ($id > 0) {
            $out[$id] = $id;
        }
    }
    return array_values($out);
}

function a7_ta_for_all_lead(string $gridId): array
{
    $filter = \Bitrix\Crm\Context\GridContext::getFilter($gridId);
    if (!is_array($filter)) {
        return [
            'ok' => false,
            'error' => 'This browser session has no Leads list filter yet. Refresh the page (F5), then tick FOR ALL again.',
        ];
    }
    $ids = [];
    $rs = CCrmLead::GetListEx(['ID' => 'ASC'], $filter, false, false, ['ID']);
    while ($rs && ($row = $rs->Fetch())) {
        $ids[] = (int)$row['ID'];
    }
    return ['ok' => true, 'ids' => $ids, 'source' => 'grid_context'];
}

function a7_ta_for_all_renewal(string $gridId): array
{
    $filter = $_SESSION['CRM_GRID_DATA'][$gridId]['FILTER'] ?? null;
    if (!is_array($filter)) {
        return [
            'ok' => false,
            'error' => 'This browser session has no Renewals list filter yet. Refresh the page (F5), then tick FOR ALL again.',
        ];
    }
    // The Renewals list is pipeline 9. A filter that does not say so is not this list's.
    $category = $filter['CATEGORY_ID'] ?? ($filter['=CATEGORY_ID'] ?? null);
    $categories = array_values(array_unique(array_map('intval', (array)$category)));
    if ($categories !== [9]) {
        return [
            'ok' => false,
            'error' => 'The saved list filter is not the Renewals pipeline. Refresh the page (F5), then tick FOR ALL again.',
        ];
    }
    $options = [];
    if (($filter['IS_RECURRING'] ?? null) === 'Y' || ($filter['=IS_RECURRING'] ?? null) === 'Y') {
        $options['FIELD_OPTIONS']['ADDITIONAL_FIELDS'][] = 'RECURRING';
    }
    $ids = [];
    $rs = CCrmDeal::GetListEx(['ID' => 'ASC'], $filter, false, false, ['ID'], $options);
    while ($rs && ($row = $rs->Fetch())) {
        $ids[] = (int)$row['ID'];
    }
    return ['ok' => true, 'ids' => $ids, 'source' => 'session_grid_data'];
}

/**
 * Owner Data / Availability: the item list keeps no filter in the session, so its own
 * filter builder is run — the same code that drew the page, reading the same saved filter.
 * Its methods are protected, hence reflection; if Bitrix renames them this says so
 * instead of guessing.
 */
function a7_ta_for_all_spa(int $categoryId): array
{
    $broken = 'FOR ALL cannot read this list\'s filter (Bitrix may have been updated). Tick the cards on the page instead, and tell IT.';
    try {
        if (!class_exists('CrmItemListComponent')) {
            CBitrixComponent::includeComponentClass('bitrix:crm.item.list');
        }
        if (!class_exists('CrmItemListComponent')) {
            return ['ok' => false, 'error' => $broken, 'detail' => 'CrmItemListComponent missing'];
        }
        $component = new CrmItemListComponent();
        $component->arParams = $component->onPrepareComponentParams([
            'entityTypeId' => 1042,
            'categoryId' => $categoryId,
        ]);
        // PHP 8.1+: reflection reaches protected/private methods without setAccessible().
        $call = static function (string $method, array $args = []) use ($component) {
            return (new ReflectionMethod($component, $method))->invokeArgs($component, $args);
        };
        $call('init');
        $errors = $call('getErrors');
        if ($errors) {
            $first = reset($errors);
            return [
                'ok' => false,
                'error' => 'This list refused to load: ' . (is_object($first) && method_exists($first, 'getMessage') ? $first->getMessage() : 'access denied'),
            ];
        }
        $gridId = (string)$call('getGridId');
        if ($gridId !== 'crm-type-item-list-1042-' . $categoryId) {
            return ['ok' => false, 'error' => $broken, 'detail' => 'item list grid is ' . $gridId];
        }
        $applied = $call('applyRelatedEntitiesFilter', [$call('getListFilter'), 1042]);
    } catch (Throwable $e) {
        return ['ok' => false, 'error' => $broken, 'detail' => $e->getMessage()];
    }

    $filter = (array)($applied['filter'] ?? []);
    if ((int)($filter['=CATEGORY_ID'] ?? 0) !== $categoryId) {
        return ['ok' => false, 'error' => $broken, 'detail' => 'filter has no =CATEGORY_ID ' . $categoryId];
    }
    // Owner Data runs to ~95,000 cards; each Item is an object, so read them a batch at a
    // time, walking the ID upward, instead of holding them all at once. Stop only on an
    // empty batch: a filter on observers, contacts or products joins rows, so LIMIT counts
    // doubled rows and a short batch does not mean the end.
    $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
    $userId = (int)$GLOBALS['USER']->GetID();
    $ids = [];
    $lastId = 0;
    do {
        $batchFilter = $filter;
        if ($lastId > 0) {
            $batchFilter[] = ['>ID' => $lastId];
        }
        $batch = $factory->getItemsFilteredByPermissions(
            [
                'select' => ['ID'],
                'filter' => $batchFilter,
                'order' => ['ID' => 'ASC'],
                'limit' => 5000,
                'runtime' => (array)($applied['runtime'] ?? []),
            ],
            $userId,
            \Bitrix\Crm\Service\UserPermissions::OPERATION_READ
        );
        $before = $lastId;
        foreach ($batch as $item) {
            $id = (int)$item->getId();
            $ids[$id] = $id;
            $lastId = max($lastId, $id);
        }
    } while ($batch && $lastId > $before);
    return ['ok' => true, 'ids' => array_values($ids), 'source' => 'item_list_filter', 'grid_id' => $gridId];
}

/*
 * A FOR ALL too large to send to the browser is kept here, outside the web root, so
 * Preview and Apply use the very IDs the person confirmed instead of resolving again
 * (12 s each on all of Owner Data, and possibly a different answer by then).
 */
function a7_ta_selection_dir(): string
{
    return dirname((string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www')) . '/a7_team_assign_sel';
}

/**
 * One live selection per user and list: saving a new one drops the previous, and anything
 * past the two-hour limit goes on every save.
 */
function a7_ta_selection_save(string $entity, array $resolved): string
{
    $dir = a7_ta_selection_dir();
    if (!is_dir($dir) && !@mkdir($dir, 0750, true)) {
        return '';
    }
    $userId = (int)$GLOBALS['USER']->GetID();
    $prefix = 'sel_' . $userId . '_' . $entity . '_';
    foreach ((array)glob($dir . '/sel_*.json') as $old) {
        if (strpos(basename($old), $prefix) === 0 || @filemtime($old) < time() - 7200) {
            @unlink($old);
        }
    }
    $token = bin2hex(random_bytes(16));
    $written = @file_put_contents($dir . '/' . $prefix . $token . '.json', json_encode([
        'user' => $userId,
        'entity' => $entity,
        'at' => time(),
        'grid' => (string)($resolved['grid_id'] ?? ''),
        'ids' => array_values(array_map('intval', (array)($resolved['ids'] ?? []))),
    ]), LOCK_EX);
    return $written ? $token : '';
}

/**
 * @return int[]|null null when the token is unknown, someone else's, another list's, or over two hours old
 */
function a7_ta_selection_load(string $entity, string $token): ?array
{
    if (!preg_match('/^[a-f0-9]{32}$/', $token)) {
        return null;
    }
    $userId = (int)$GLOBALS['USER']->GetID();
    $file = a7_ta_selection_dir() . '/sel_' . $userId . '_' . $entity . '_' . $token . '.json';
    $data = is_readable($file) ? json_decode((string)file_get_contents($file), true) : null;
    if (
        !is_array($data)
        || (int)($data['user'] ?? 0) !== $userId
        || (string)($data['entity'] ?? '') !== $entity
        || (int)($data['at'] ?? 0) < time() - 7200
    ) {
        return null;
    }
    return array_values(array_map('intval', (array)($data['ids'] ?? [])));
}

/**
 * One line per FOR ALL, outside the web root — the question "what did it resolve to,
 * and from what" should never again need a session file read by hand.
 */
function a7_ta_log_resolve(array $row): void
{
    $file = dirname((string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www')) . '/a7_team_assign_resolve.log';
    if (@filesize($file) > 2000000) {
        @rename($file, $file . '.1');
    }
    $row = ['at' => gmdate('Y-m-d\TH:i:s\Z'), 'user' => (int)($GLOBALS['USER'] ? $GLOBALS['USER']->GetID() : 0)] + $row;
    @file_put_contents($file, json_encode($row, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n", FILE_APPEND | LOCK_EX);
}

/**
 * @param int[] $pageIds rows the browser's grid was showing
 * @param int $shownTotal the list's own "Total: N" if somebody clicked Show, else 0
 * @param string $stamp a7_ta_filter_stamp as the browser took it when its grid was drawn
 */
function a7_ta_resolve_for_all(string $entity, string $postedGridId, array $pageIds, int $max, int $shownTotal = 0, string $stamp = ''): array
{
    $nouns = ['lead' => 'leads', 'renewal' => 'deals', 'owner_data' => 'cards', 'availability' => 'cards'];
    $noun = $nouns[$entity] ?? 'cards';
    $gridId = a7_ta_list_grid_id($entity, $postedGridId);
    $log = [
        'entity' => $entity,
        'grid' => $gridId !== '' ? $gridId : 'refused:' . substr(trim($postedGridId), 0, 60),
        'source' => '',
        'page' => count($pageIds),
        'shown_total' => $shownTotal,
        'stamp' => $stamp !== '' ? 'sent' : 'none',
    ];
    $fail = static function (string $error, array $extra = []) use (&$log): array {
        a7_ta_log_resolve($log + $extra + ['ok' => false, 'error' => $error]);
        return ['ok' => false, 'error' => $error];
    };

    if ($gridId === '') {
        $where = ['lead' => 'the Leads list', 'renewal' => 'the Renewals list'][$entity] ?? 'the Owner Data or Availability list itself, not on All items';
        return $fail('FOR ALL works on ' . $where . '. Open it there, filter, and tick FOR ALL again.');
    }
    // FOR ALL only exists on a grid with rows; no rows means the page could not be read,
    // and without them nothing below can tell whether the filter is the one on screen.
    if (!$pageIds) {
        return $fail('FOR ALL could not read the rows on this page. Refresh the page (F5) and try again.');
    }
    if ($stamp !== '') {
        $now = a7_ta_filter_stamp($entity, $gridId);
        if ($now !== '' && !hash_equals($now, $stamp)) {
            return $fail('The list filter was changed in another tab after this page was drawn. Refresh this page (F5) and tick FOR ALL again.');
        }
    }

    try {
        if ($entity === 'lead') {
            $got = a7_ta_for_all_lead($gridId);
        } elseif ($entity === 'renewal') {
            $got = a7_ta_for_all_renewal($gridId);
        } else {
            $got = a7_ta_for_all_spa($entity === 'availability' ? 14 : 13);
        }
    } catch (Throwable $e) {
        return $fail('FOR ALL could not read this list. Try again, or tell IT.', ['detail' => $e->getMessage()]);
    }
    $log['source'] = (string)($got['source'] ?? '');

    if (empty($got['ok'])) {
        return $fail((string)($got['error'] ?? 'FOR ALL could not read the list filter.'), ['detail' => $got['detail'] ?? '']);
    }
    $ids = $got['ids'];
    if (!$ids) {
        return $fail('FOR ALL found no ' . $noun . ' for this list\'s filter. Refresh the page (F5) and try again.');
    }
    // A row on screen that the filter does not return means the filter is not this page's.
    $have = array_flip($ids);
    $missing = 0;
    foreach ($pageIds as $id) {
        if (!isset($have[$id])) {
            $missing++;
        }
    }
    if ($missing) {
        return $fail(
            'This page no longer matches the list filter (' . $missing . ' of the ' . count($pageIds)
            . ' rows on screen are not in it — was the filter changed in another tab?). Refresh the page (F5) and tick FOR ALL again.',
            ['total' => count($ids), 'missing' => $missing]
        );
    }
    // The list's own Total, when shown, is the other side of that check: a filter much
    // broader than what the list counted is not the one on screen. A few cards more is
    // just new work arriving since Show was clicked.
    if ($shownTotal > 0 && count($ids) > $shownTotal + max(5, (int)ceil($shownTotal * 0.1))) {
        return $fail(
            'This list showed Total: ' . $shownTotal . ', but its filter now matches ' . count($ids)
            . '. The filter was probably changed in another tab — refresh the page (F5) and tick FOR ALL again.',
            ['total' => count($ids)]
        );
    }
    if ($max > 0 && count($ids) > $max) {
        return $fail(
            'FOR ALL matches ' . count($ids) . ' ' . $noun . ', more than the ' . $max . ' this tool takes in one run. Narrow the filter.',
            ['total' => count($ids)]
        );
    }

    $warning = null;
    if ($shownTotal > 0 && $shownTotal !== count($ids)) {
        $warning = 'The list showed Total: ' . $shownTotal . ' when Show was clicked; it now matches ' . count($ids)
            . ' (cards were added or changed since). FOR ALL uses the ' . count($ids) . '.';
    }
    a7_ta_log_resolve($log + ['ok' => true, 'total' => count($ids)]);

    return [
        'ok' => true,
        'for_all' => true,
        'ids' => $ids,
        'total' => count($ids),
        'truncated' => false,
        'max_ids' => $max,
        'grid_id' => $gridId,
        'filter_source' => (string)($got['source'] ?? ''),
        'warning' => $warning,
    ];
}

function a7_ta_summarize_plan(array $plan, array $agents): array
{
    $byName = [];
    foreach ($agents as $a) {
        $byName[(int)$a['id']] = $a['name'];
    }
    $rows = [];
    foreach ((array)($plan['counts'] ?? []) as $uid => $n) {
        $rows[] = [
            'user_id' => (int)$uid,
            'name' => $byName[(int)$uid] ?? a7_ta_user_name((int)$uid),
            'count' => (int)$n,
        ];
    }
    usort($rows, static function ($a, $b) {
        return strcmp($a['name'], $b['name']);
    });
    return $rows;
}

// ---------------------------------------------------------------------------

if (defined('A7_TEAM_ASSIGN_AS_LIB') && A7_TEAM_ASSIGN_AS_LIB) {
    return;
}

$jobsLib = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_team_assign_jobs.php';
if (is_readable($jobsLib)) {
    require_once $jobsLib;
}

$user = a7_ta_user();
if (!$user) {
    a7_ta_json(['ok' => false, 'error' => 'Not logged in'], 401);
}

if (!check_bitrix_sessid()) {
    a7_ta_json(['ok' => false, 'error' => 'Bad session. Refresh the page.'], 403);
}

if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_ta_json(['ok' => false, 'error' => 'CRM module missing'], 500);
}

$cfg = a7_ta_config();
$action = strtolower(trim((string)($_REQUEST['action'] ?? 'meta')));
$entity = a7_ta_entity();
$max = (int)($cfg['max_ids'] ?? 0);
$clientIdsMax = (int)($cfg['client_ids_max'] ?? 400);
$inlineMax = (int)($cfg['inline_max'] ?? 120);
$sleepUs = max(0, (int)($cfg['sleep_us'] ?? 70000));

if ($action === 'meta') {
    $teams = a7_ta_teams($cfg);
    a7_ta_json([
        'ok' => true,
        'entity' => $entity,
        'teams' => $teams,
        'users' => a7_ta_all_users(),
        'stages' => a7_ta_stages($entity),
        'max_ids' => $max,
        'client_ids_max' => $clientIdsMax,
        'inline_max' => $inlineMax,
        'help' => 'Large selections run in the background. Keep current stage leaves each card as it is.',
    ]);
}

if ($action === 'job_status') {
    $jobId = (string)($_POST['job_id'] ?? $_REQUEST['job_id'] ?? '');
    if (!function_exists('a7_ta_job_read')) {
        a7_ta_json(['ok' => false, 'error' => 'Jobs module missing'], 500);
    }
    $job = a7_ta_job_read($cfg, $jobId);
    if (!$job) {
        a7_ta_json(['ok' => false, 'error' => 'Job not found'], 404);
    }
    a7_ta_json([
        'ok' => true,
        'job_id' => $job['id'],
        'status' => $job['status'],
        'total' => (int)($job['total'] ?? 0),
        'cursor' => (int)($job['cursor'] ?? 0),
        'updated' => (int)($job['ok'] ?? 0),
        'failed' => (int)($job['fail'] ?? 0),
        'errors' => $job['errors'] ?? [],
        'done' => in_array((string)$job['status'], ['done', 'done_with_errors', 'failed'], true),
    ]);
}

$forAll = strtoupper((string)($_POST['for_all'] ?? $_REQUEST['for_all'] ?? 'N')) === 'Y';
$gridId = (string)($_POST['grid_id'] ?? $_REQUEST['grid_id'] ?? '');
$pageIds = a7_ta_page_ids();
$shownTotal = max(0, (int)($_POST['expected_total'] ?? 0));
$stamp = preg_match('/^[a-f0-9]{32}$/', (string)($_POST['filter_stamp'] ?? '')) ? (string)$_POST['filter_stamp'] : '';

// Taken by the browser each time its grid is drawn; see a7_ta_filter_stamp.
if ($action === 'filter_stamp') {
    a7_ta_json(['ok' => true, 'stamp' => a7_ta_filter_stamp($entity, a7_ta_list_grid_id($entity, $gridId))]);
}

if ($action === 'resolve') {
    if ($forAll) {
        @set_time_limit(180);
        $resolved = a7_ta_resolve_for_all($entity, $gridId, $pageIds, $max, $shownTotal, $stamp);
        if (empty($resolved['ok'])) {
            a7_ta_json(['ok' => false, 'error' => $resolved['error'] ?? 'FOR ALL could not read the list filter.'], 400);
        }
        if (count($resolved['ids']) > $clientIdsMax) {
            $selection = a7_ta_selection_save($entity, $resolved);
            if ($selection === '') {
                a7_ta_json(['ok' => false, 'error' => 'Could not hold this FOR ALL selection on the server; nothing was assigned. Try again, or tell IT.'], 500);
            }
            a7_ta_json([
                'ok' => true,
                'for_all' => true,
                'deferred' => true,
                'ids' => [],
                'total' => (int)$resolved['total'],
                'truncated' => false,
                'max_ids' => $max,
                'grid_id' => $resolved['grid_id'],
                'filter_source' => $resolved['filter_source'],
                'warning' => $resolved['warning'],
                'selection' => $selection,
            ]);
        }
        a7_ta_json($resolved + ['deferred' => false]);
    }
    $ids = a7_ta_ids_from_request();
    a7_ta_json([
        'ok' => true,
        'for_all' => false,
        'deferred' => false,
        'ids' => $ids,
        'total' => count($ids),
        'truncated' => false,
        'max_ids' => $max,
    ]);
}

$ids = a7_ta_ids_from_request();
if ($forAll && !$ids) {
    $selection = trim((string)($_POST['selection'] ?? ''));
    if ($selection !== '') {
        $ids = a7_ta_selection_load($entity, $selection);
        if ($ids === null) {
            a7_ta_json(['ok' => false, 'error' => 'This FOR ALL selection has expired. Close this window and press Assign to team again.'], 400);
        }
    } else {
        // Only a tab still running the script from before selections existed gets here.
        @set_time_limit(180);
        $resolved = a7_ta_resolve_for_all($entity, $gridId, $pageIds, $max, $shownTotal, $stamp);
        if (empty($resolved['ok'])) {
            a7_ta_json(['ok' => false, 'error' => $resolved['error'] ?? 'FOR ALL could not read the list filter.'], 400);
        }
        $ids = $resolved['ids'];
    }
}
if ($max > 0 && count($ids) > $max) {
    a7_ta_json(['ok' => false, 'error' => 'Too many selected (max ' . $max . '). Narrow the filter or split the run.'], 400);
}
if (!$ids) {
    a7_ta_json(['ok' => false, 'error' => 'Select at least one card.'], 400);
}

$headIds = a7_ta_json_body('head_ids', []);
if (!is_array($headIds)) {
    $headIds = [];
}
$headIds = array_values(array_unique(array_map('intval', $headIds)));
$scope = strtolower(trim((string)($_POST['scope'] ?? 'teams')));
if ($scope === 'all') {
    $agents = a7_ta_all_users();
} else {
    $agents = a7_ta_receivers_for_heads($cfg, $headIds);
}
$agentIds = array_map(static function ($a) {
    return (int)$a['id'];
}, $agents);
if (!$agentIds) {
    a7_ta_json(['ok' => false, 'error' => $scope === 'all'
        ? 'No active users to assign to.'
        : 'No active agents in the selected teams.'], 400);
}

$mode = strtolower(trim((string)($_POST['mode'] ?? 'equal')));
if (!in_array($mode, ['equal', 'community', 'manual'], true)) {
    $mode = 'equal';
}
$stage = trim((string)($_POST['stage'] ?? '__KEEP__'));
$noCommMode = strtolower(trim((string)($_POST['no_community'] ?? 'rr')));
$noCommUser = (int)($_POST['no_community_user'] ?? 0);
$countMap = a7_ta_json_body('counts', null);
$agentStages = a7_ta_json_body('agent_stages', []);
if (!is_array($agentStages)) {
    $agentStages = [];
}

$cards = [];
$cardIds = [];
$noCommunityCount = 0;

// Equal / manual: plan from IDs only (fast for large For-all). Community still loads cards.
if ($mode === 'community') {
    @set_time_limit(300);
    $cards = a7_ta_load_cards($entity, $ids, $cfg);
    if (!$cards) {
        a7_ta_json(['ok' => false, 'error' => 'None of the selected cards are readable/updatable.'], 400);
    }
    $cardIds = array_map(static function ($c) {
        return (int)$c['id'];
    }, $cards);
    $plan = a7_ta_community_plan($cards, $agentIds, $cfg, $noCommMode, $noCommUser);
    foreach ($cards as $c) {
        if (($c['community'] ?? '') === '') {
            $noCommunityCount++;
        }
    }
} elseif ($mode === 'manual' && is_array($countMap)) {
    // Manual counts name agents directly; only the selected teams' agents may receive.
    foreach ($countMap as $uid => $n) {
        if ((int)$n > 0 && !in_array((int)$uid, $agentIds, true)) {
            a7_ta_json(['ok' => false, 'error' => 'User ' . (int)$uid . ' is not in the list you are assigning to.'], 400);
        }
    }
    $cardIds = array_values(array_map('intval', $ids));
    $plan = a7_ta_plan_from_counts($cardIds, $countMap);
    if (!empty($plan['error'])) {
        a7_ta_json(['ok' => false, 'error' => $plan['error']], 400);
    }
} else {
    $cardIds = array_values(array_map('intval', $ids));
    $plan = a7_ta_equal_plan($cardIds, $agentIds);
}

$summary = a7_ta_summarize_plan($plan, $agents);

if ($action === 'preview') {
    $payload = [
        'ok' => true,
        'entity' => $entity,
        'mode' => $mode,
        'selected' => count($cardIds),
        'agents' => count($agentIds),
        'no_community' => $noCommunityCount,
        'skipped' => count($plan['skipped'] ?? []),
        'by_agent' => $summary,
        'by_bucket' => $plan['by_bucket'] ?? new stdClass(),
        'background' => count($cardIds) > $inlineMax,
    ];
    // Do not ship tens of thousands of assignment rows to the browser.
    if (count($cardIds) <= $clientIdsMax) {
        $payload['assignments'] = $plan['assignments'];
    } else {
        $payload['assignments'] = [];
    }
    a7_ta_json($payload);
}

if ($action !== 'apply') {
    a7_ta_json(['ok' => false, 'error' => 'Unknown action'], 400);
}

$assignments = $plan['assignments'] ?? [];
if (!$assignments) {
    a7_ta_json(['ok' => false, 'error' => 'Nothing to assign.'], 400);
}

// Every Apply → background job when worker exists (inline_max=0 means always).
// Small inline runs forced users to wait on "Working…" — not acceptable.
if (function_exists('a7_ta_job_create') && count($assignments) > (int)$inlineMax) {
    @set_time_limit(180);
    $job = a7_ta_job_create(
        $cfg,
        $entity,
        (int)$user->GetID(),
        $assignments,
        $stage,
        $agentStages
    );
    a7_ta_job_kick($cfg);
    a7_ta_json([
        'ok' => true,
        'background' => true,
        'job_id' => $job['id'],
        'total' => (int)$job['total'],
        'updated' => 0,
        'failed' => 0,
        'by_agent' => $summary,
        'message' => 'Assign started in the background. You can leave this page — it will keep going.',
    ]);
}

@set_time_limit(300);
$ok = 0;
$fail = 0;
$errors = [];
try {
    foreach ($assignments as $row) {
        $id = (int)$row['id'];
        $uid = (int)$row['user_id'];
        $rowStage = $stage;
        if (isset($agentStages[(string)$uid]) && $agentStages[(string)$uid] !== '') {
            $rowStage = (string)$agentStages[(string)$uid];
        } elseif (isset($agentStages[$uid]) && $agentStages[$uid] !== '') {
            $rowStage = (string)$agentStages[$uid];
        }
        try {
            $result = a7_ta_apply_one($entity, $id, $uid, $rowStage);
        } catch (Throwable $e) {
            $result = ['ok' => false, 'error' => $e->getMessage()];
        }
        if ($result['ok']) {
            $ok++;
        } else {
            $fail++;
            if (count($errors) < 8) {
                $errors[] = '#' . $id . ': ' . ($result['error'] ?: 'failed');
            }
        }
        if ($sleepUs > 0) {
            usleep($sleepUs);
        }
    }
} catch (Throwable $e) {
    a7_ta_json([
        'ok' => false,
        'error' => 'Assign failed: ' . $e->getMessage(),
        'updated' => $ok,
        'failed' => $fail,
        'errors' => $errors,
    ], 500);
}

a7_ta_json([
    'ok' => $fail === 0,
    'background' => false,
    'updated' => $ok,
    'failed' => $fail,
    'skipped' => count($plan['skipped'] ?? []),
    'by_agent' => $summary,
    'errors' => $errors,
]);
