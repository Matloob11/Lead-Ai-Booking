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
        $item->setAssignedById($userId);
        if ($stage !== '' && $stage !== '__KEEP__') {
            $item->setStageId($stage);
        }
        $ctx = new \Bitrix\Crm\Service\Context();
        $ctx->setUserId((int)($GLOBALS['USER']->GetID() ?? 1));
        $op = $factory->getUpdateOperation($item, $ctx);
        $op->disableCheckAccess();
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

/**
 * Pick the active list filter for For-all.
 * Leads store via GridContext → $_SESSION['CRM_GRID_DATA'][$gridId]['FILTER'].
 * Empty array is valid (means "all rows matching permissions / no UI filter").
 *
 * @return array{ok:bool,filter?:array,grid_id?:string,source?:string,error?:string}
 */
function a7_ta_find_grid_filter(string $entity, string $gridId): array
{
    $gridId = trim($gridId);
    $candidates = [];
    if ($gridId !== '') {
        $candidates[] = $gridId;
    }
    // Known defaults when JS cannot read grid id yet.
    if ($entity === 'lead') {
        $candidates[] = 'CRM_LEAD_LIST_V12';
    } elseif ($entity === 'renewal') {
        $candidates[] = 'CRM_DEAL_LIST_V12_C_9';
        $candidates[] = 'CRM_DEAL_LIST_V12';
    } elseif ($entity === 'owner_data') {
        $candidates[] = 'crm-type-item-list-1042';
        $candidates[] = 'crm-type-item-list-1042-13';
    } elseif ($entity === 'availability') {
        $candidates[] = 'crm-type-item-list-1042';
        $candidates[] = 'crm-type-item-list-1042-14';
    }
    $candidates = array_values(array_unique($candidates));

    // 1) Exact / candidate session keys (incl. empty FILTER).
    if (!empty($_SESSION['CRM_GRID_DATA']) && is_array($_SESSION['CRM_GRID_DATA'])) {
        foreach ($candidates as $cid) {
            if (
                isset($_SESSION['CRM_GRID_DATA'][$cid])
                && is_array($_SESSION['CRM_GRID_DATA'][$cid])
                && array_key_exists('FILTER', $_SESSION['CRM_GRID_DATA'][$cid])
                && is_array($_SESSION['CRM_GRID_DATA'][$cid]['FILTER'])
            ) {
                return [
                    'ok' => true,
                    'filter' => $_SESSION['CRM_GRID_DATA'][$cid]['FILTER'],
                    'grid_id' => $cid,
                    'source' => 'session',
                ];
            }
        }
        // 2) Fuzzy: any session grid that matches entity prefix.
        $prefix = '';
        if ($entity === 'lead') {
            $prefix = 'CRM_LEAD_LIST';
        } elseif ($entity === 'renewal') {
            $prefix = 'CRM_DEAL_LIST';
        } elseif ($entity === 'owner_data' || $entity === 'availability') {
            $prefix = 'crm-type-item-list-1042';
        }
        if ($prefix !== '') {
            foreach ($_SESSION['CRM_GRID_DATA'] as $sid => $payload) {
                if (!is_array($payload) || !array_key_exists('FILTER', $payload) || !is_array($payload['FILTER'])) {
                    continue;
                }
                if (stripos((string)$sid, $prefix) === 0 || stripos((string)$sid, $prefix) !== false) {
                    return [
                        'ok' => true,
                        'filter' => $payload['FILTER'],
                        'grid_id' => (string)$sid,
                        'source' => 'session_fuzzy',
                    ];
                }
            }
        }
    }

    // 3) GridContext helper (same store, but null-safe API).
    if (class_exists(\Bitrix\Crm\Context\GridContext::class)) {
        foreach ($candidates as $cid) {
            $f = \Bitrix\Crm\Context\GridContext::getFilter($cid);
            if (is_array($f)) {
                return ['ok' => true, 'filter' => $f, 'grid_id' => $cid, 'source' => 'grid_context'];
            }
        }
    }

    // 4) Rebuild from saved UI filter options (works even if list AJAX did not hit GridContext yet).
    $rebuilt = a7_ta_rebuild_filter_from_options($entity, $candidates[0] ?? $gridId);
    if ($rebuilt !== null) {
        return [
            'ok' => true,
            'filter' => $rebuilt,
            'grid_id' => $candidates[0] ?? $gridId,
            'source' => 'ui_options',
        ];
    }

    // 5) Last resort for For-all: empty filter = all readable rows (permissions still apply).
    return [
        'ok' => true,
        'filter' => [],
        'grid_id' => $candidates[0] ?? $gridId,
        'source' => 'empty_fallback',
    ];
}

/**
 * Rebuild CRM list filter from Bitrix UI filter options (user's last applied filter).
 */
function a7_ta_rebuild_filter_from_options(string $entity, string $gridId): ?array
{
    $gridId = trim($gridId);
    if ($gridId === '' || !class_exists(\Bitrix\Crm\Filter\Factory::class)) {
        return null;
    }
    try {
        if ($entity === 'lead') {
            $settings = new \Bitrix\Crm\Filter\LeadSettings(['ID' => $gridId]);
        } elseif ($entity === 'renewal') {
            $settings = new \Bitrix\Crm\Filter\DealSettings([
                'ID' => $gridId,
                'categoryId' => 9,
            ]);
        } else {
            return null;
        }
        $entityFilter = \Bitrix\Crm\Filter\Factory::createEntityFilter($settings);
        $filterFields = [];
        foreach ($entityFilter->getFields() as $field) {
            $filterFields[] = $field->toArray();
        }
        if (!$filterFields) {
            return null;
        }
        $filterOptions = new \Bitrix\Crm\Filter\UiFilterOptions($gridId, []);
        $arFilter = $filterOptions->getFilter($filterFields);
        if (!is_array($arFilter)) {
            return null;
        }
        if (class_exists(\Bitrix\Crm\UI\Filter\EntityHandler::class)) {
            \Bitrix\Crm\UI\Filter\EntityHandler::internalize($filterFields, $arFilter);
        }
        // Strip UI-only keys Bitrix leaves in.
        foreach (['FILTER_ID', 'FILTER_APPLIED', 'PRESET_ID', 'FIND'] as $k) {
            // keep FIND — Bitrix often uses it; EntityHandler may have handled it
        }
        return $arFilter;
    } catch (Throwable $e) {
        return null;
    }
}

/**
 * Bitrix list screens stash the active filter in $_SESSION['CRM_GRID_DATA'][$gridId].
 * Native "FOR ALL" actions use that; we do the same so Assign gets every filtered ID,
 * not only rows already loaded via "Show more".
 *
 * @return array{ok:bool,ids?:int[],total?:int,truncated?:bool,error?:string,for_all?:bool}
 */
function a7_ta_resolve_for_all(string $entity, string $gridId, int $max): array
{
    $found = a7_ta_find_grid_filter($entity, $gridId);
    if (empty($found['ok']) || !isset($found['filter']) || !is_array($found['filter'])) {
        return [
            'ok' => false,
            'error' => 'List filter not ready. Refresh the page, wait for the list to finish loading, then use For all again.',
        ];
    }
    $filter = $found['filter'];
    $gridId = (string)($found['grid_id'] ?? $gridId);
    $ids = [];
    $truncated = false;

    if ($entity === 'lead') {
        if (!class_exists('CCrmLead')) {
            return ['ok' => false, 'error' => 'Lead module missing'];
        }
        $rs = CCrmLead::GetListEx(['ID' => 'ASC'], $filter, false, false, ['ID']);
        while ($row = $rs->Fetch()) {
            $ids[] = (int)$row['ID'];
            if ($max > 0 && count($ids) > $max) {
                $truncated = true;
                array_pop($ids);
                break;
            }
        }
    } elseif ($entity === 'renewal') {
        if (!class_exists('CCrmDeal')) {
            return ['ok' => false, 'error' => 'Deal module missing'];
        }
        // Ensure category 9 when filter came from empty fallback / options without category.
        if (!isset($filter['CATEGORY_ID']) && !isset($filter['=CATEGORY_ID'])) {
            $filter['CATEGORY_ID'] = 9;
        }
        $options = [];
        if (
            (isset($filter['IS_RECURRING']) && $filter['IS_RECURRING'] === 'Y')
            || (isset($filter['=IS_RECURRING']) && $filter['=IS_RECURRING'] === 'Y')
        ) {
            $options['FIELD_OPTIONS']['ADDITIONAL_FIELDS'][] = 'RECURRING';
        }
        $rs = CCrmDeal::GetListEx(['ID' => 'ASC'], $filter, false, false, ['ID'], $options);
        while ($row = $rs->Fetch()) {
            $ids[] = (int)$row['ID'];
            if ($max > 0 && count($ids) > $max) {
                $truncated = true;
                array_pop($ids);
                break;
            }
        }
    } elseif ($entity === 'owner_data' || $entity === 'availability') {
        if (!class_exists(\Bitrix\Crm\Service\Container::class)) {
            return ['ok' => false, 'error' => 'SPA factory missing'];
        }
        $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
        if (!$factory) {
            return ['ok' => false, 'error' => 'Owner Data factory missing'];
        }
        $categoryId = $entity === 'availability' ? 14 : 13;
        $ormFilter = $filter;
        $ormFilter['=categoryId'] = $categoryId;
        try {
            $q = [
                'select' => ['ID'],
                'filter' => $ormFilter,
                'order' => ['ID' => 'ASC'],
            ];
            if ($max > 0) {
                $q['limit'] = $max + 1;
            }
            $items = $factory->getItems($q);
            foreach ($items as $item) {
                $ids[] = (int)$item->getId();
                if ($max > 0 && count($ids) > $max) {
                    $truncated = true;
                    array_pop($ids);
                    break;
                }
            }
        } catch (Throwable $e) {
            $ids = [];
            $q = [
                'select' => ['ID'],
                'filter' => ['=categoryId' => $categoryId],
                'order' => ['ID' => 'ASC'],
            ];
            if ($max > 0) {
                $q['limit'] = $max + 1;
            }
            $items = $factory->getItems($q);
            foreach ($items as $item) {
                $ids[] = (int)$item->getId();
                if ($max > 0 && count($ids) > $max) {
                    $truncated = true;
                    array_pop($ids);
                    break;
                }
            }
            if (!$ids) {
                return ['ok' => false, 'error' => 'Could not resolve For all IDs: ' . $e->getMessage()];
            }
        }
    } else {
        return ['ok' => false, 'error' => 'Unsupported entity for For all'];
    }

    return [
        'ok' => true,
        'for_all' => true,
        'ids' => $ids,
        'total' => count($ids),
        'truncated' => $truncated,
        'max_ids' => $max,
        'grid_id' => $gridId,
        'filter_source' => $found['source'] ?? '',
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

if ($action === 'resolve') {
    $forAll = strtoupper((string)($_POST['for_all'] ?? $_REQUEST['for_all'] ?? 'N')) === 'Y';
    $gridId = (string)($_POST['grid_id'] ?? $_REQUEST['grid_id'] ?? '');
    if ($forAll) {
        @set_time_limit(180);
        $resolved = a7_ta_resolve_for_all($entity, $gridId, $max);
        if (!empty($resolved['ok']) && count($resolved['ids'] ?? []) > $clientIdsMax) {
            a7_ta_json([
                'ok' => true,
                'for_all' => true,
                'deferred' => true,
                'ids' => [],
                'total' => (int)($resolved['total'] ?? count($resolved['ids'])),
                'truncated' => !empty($resolved['truncated']),
                'max_ids' => $max,
                'grid_id' => $gridId,
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

$forAll = strtoupper((string)($_POST['for_all'] ?? $_REQUEST['for_all'] ?? 'N')) === 'Y';
$gridId = (string)($_POST['grid_id'] ?? $_REQUEST['grid_id'] ?? '');
$ids = a7_ta_ids_from_request();
if ($forAll && !$ids) {
    @set_time_limit(180);
    $resolved = a7_ta_resolve_for_all($entity, $gridId, $max);
    if (empty($resolved['ok'])) {
        a7_ta_json(['ok' => false, 'error' => $resolved['error'] ?? 'Could not resolve For all'], 400);
    }
    $ids = $resolved['ids'] ?? [];
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
$agents = a7_ta_receivers_for_heads($cfg, $headIds);
$agentIds = array_map(static function ($a) {
    return (int)$a['id'];
}, $agents);
if (!$agentIds) {
    a7_ta_json(['ok' => false, 'error' => 'No active agents in the selected teams.'], 400);
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

// Large runs → background job (cron + nohup). Small runs stay inline, slightly throttled.
if (count($assignments) > $inlineMax && function_exists('a7_ta_job_create')) {
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
