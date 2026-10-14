<?php
/**
 * C32 + C33 proof on one test lead, then delete it.
 * CLI only. Run: ops/bitrix.sh run a7_c32_c33_proof.php
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

function say(string $line): void
{
    echo $line, "\n";
}

function call_fields(string $body, string $secret): array
{
    $ts = time();
    $sign = hash_hmac('sha256', 'leadai-fields.' . $ts . '.' . $body, $secret);
    $tmp = tempnam(sys_get_temp_dir(), 'a7c32');
    file_put_contents($tmp, $body);
    $cmd = 'curl -sk -D - --max-time 60 -o - -X POST'
        . ' -H ' . escapeshellarg('Host: crm.a7grouprealestatedxb.com')
        . ' -H ' . escapeshellarg('Content-Type: application/json')
        . ' -H ' . escapeshellarg('X-Leadai-Ts: ' . $ts)
        . ' -H ' . escapeshellarg('X-Leadai-Sign: ' . $sign)
        . ' --data-binary @' . escapeshellarg($tmp)
        . ' https://127.0.0.1/bitrix/tools/a7_leadai_fields.php';
    $raw = (string)shell_exec($cmd);
    @unlink($tmp);
    $code = 0;
    if (preg_match('#^HTTP/\S+\s+(\d+)#m', $raw, $match)) {
        $code = (int)$match[1];
    }
    $parts = preg_split("#\r\n\r\n#", $raw, 2);
    return [$code, isset($parts[1]) ? $parts[1] : ''];
}

\Bitrix\Main\Loader::includeModule('crm');
$cfg = include '/home/bitrix/www/bitrix/php_interface/a7_lead_wa.config.php';
$secret = trim((string)($cfg['secret'] ?? ''));
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$conn = \Bitrix\Main\Application::getConnection();

$item = $factory->createItem([
    'TITLE' => 'ZZ C32 C33 proof delete',
    'NAME' => 'Sumon',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'IN_PROCESS',
]);
$add = $factory->getAddOperation($item, $context);
$add->disableCheckAccess();
$add->disableBizProc();
$add->disableAutomation();
$add->launch();
$leadId = (int)$item->getId();
say('LEAD ' . $leadId);

// Agent's newer Viewing/Meeting to-do (responsible 1).
[$start, $end] = [
    (new \Bitrix\Main\Type\DateTime('2026-11-10 10:00:00', 'Y-m-d H:i:s'))->toString(),
    (new \Bitrix\Main\Type\DateTime('2026-11-10 11:00:00', 'Y-m-d H:i:s'))->toString(),
];
$agentFields = [
    'TYPE_ID' => 6,
    'PROVIDER_ID' => 'CRM_TODO',
    'PROVIDER_TYPE_ID' => 'TODO',
    'SUBJECT' => 'Viewing/Meeting',
    'DESCRIPTION' => 'Agent viewing',
    'DESCRIPTION_TYPE' => 2,
    'RESPONSIBLE_ID' => 1,
    'PRIORITY' => 1,
    'COMPLETED' => 'N',
    'DEADLINE' => $start,
    'START_TIME' => $start,
    'END_TIME' => $end,
    'OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
    'OWNER_ID' => $leadId,
    'BINDINGS' => [['OWNER_TYPE_ID' => \CCrmOwnerType::Lead, 'OWNER_ID' => $leadId]],
];
$agentTodo = (int)\CCrmActivity::Add($agentFields, false, false, ['REGISTER_SONET_EVENT' => false]);
say('AGENT_TODO ' . $agentTodo);

// Book without crm_todo_id first → creates ours (2311), doesn't close agent's? 
// Newest open is agent's, so without crm_todo_id the book would MOVE the agent todo.
// So: book with fields only first? Order: create our todo via booking when no open? 
// Agent already open → plan_todo would move agent. Create ours first with bizproc off via Add, then agent is newer.

// Delete agent for a moment, book to create ours, re-add agent as newer.
\CCrmActivity::Delete($agentTodo, false);
[$code, $raw] = call_fields(json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-02T16:30:00+04:00',
        'mode' => 42,
        'event' => 'confirmed',
    ],
    'fields' => [
        'UF_CRM_1731838831905' => 'https://maps.example.com/ic-office',
        'UF_CRM_1731838581336' => 85000,
        'UF_CRM_1760707482053' => '450 sqft',
    ],
    'only_if_empty' => [
        'UF_CRM_1731838831905',
        'UF_CRM_1731838581336',
        'UF_CRM_1760707482053',
    ],
]), $secret);
say('BOOK1 ' . $code . ' ' . substr($raw, 0, 240));
$book1 = json_decode($raw, true);
$ourTodo = (int)($book1['todo_id'] ?? 0);
say('OUR_TODO ' . $ourTodo);

$uts = $conn->query(
    "SELECT UF_CRM_1731838831905 L, UF_CRM_1731838581336 B, UF_CRM_1760707482053 S,
            UF_CRM_1731838813769 M
     FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
)->fetch();
say('C32_AFTER_EMPTY loc=' . ($uts['L'] ?? '') . ' budget=' . ($uts['B'] ?? '') . ' size=' . ($uts['S'] ?? ''));
$c32ok = str_contains((string)($uts['L'] ?? ''), 'https://maps.example.com')
    && (string)($uts['B'] ?? '') !== ''
    && (string)($uts['S'] ?? '') === '450 sqft';
say('C32_FILL ' . ($c32ok ? 'yes' : 'no'));

// Agent value must be kept (only_if_empty).
[$code, $raw] = call_fields(json_encode([
    'lead_id' => $leadId,
    'fields' => [
        'UF_CRM_1731838831905' => 'https://maps.example.com/should-skip',
        'UF_CRM_1731838581336' => 1,
        'UF_CRM_1760707482053' => 'skip me',
    ],
    'only_if_empty' => [
        'UF_CRM_1731838831905',
        'UF_CRM_1731838581336',
        'UF_CRM_1760707482053',
    ],
]), $secret);
say('BOOK_SKIP ' . $code . ' ' . substr($raw, 0, 200));
$uts2 = $conn->query(
    "SELECT UF_CRM_1731838831905 L, UF_CRM_1731838581336 B, UF_CRM_1760707482053 S
     FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
)->fetch();
$kept = ((string)($uts2['L'] ?? '') === (string)($uts['L'] ?? ''))
    && ((string)($uts2['B'] ?? '') === (string)($uts['B'] ?? ''))
    && ((string)($uts2['S'] ?? '') === (string)($uts['S'] ?? ''));
say('C32_KEEP ' . ($kept ? 'yes' : 'no'));

// Re-add agent's newer to-do.
$agentFields2 = [
    'TYPE_ID' => 6,
    'PROVIDER_ID' => 'CRM_TODO',
    'PROVIDER_TYPE_ID' => 'TODO',
    'SUBJECT' => 'Viewing/Meeting',
    'DESCRIPTION' => 'Agent viewing newer',
    'DESCRIPTION_TYPE' => 2,
    'RESPONSIBLE_ID' => 1,
    'PRIORITY' => 1,
    'COMPLETED' => 'N',
    'DEADLINE' => $start,
    'START_TIME' => $start,
    'END_TIME' => $end,
    'OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
    'OWNER_ID' => $leadId,
    'BINDINGS' => [['OWNER_TYPE_ID' => \CCrmOwnerType::Lead, 'OWNER_ID' => $leadId]],
];
$agentTodo = (int)\CCrmActivity::Add($agentFields2, false, false, ['REGISTER_SONET_EVENT' => false]);
say('AGENT_TODO2 ' . $agentTodo);

// Reschedule with crm_todo_id = ours.
[$code, $raw] = call_fields(json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-03T17:00:00+04:00',
        'mode' => 42,
        'event' => 'rescheduled',
        'crm_todo_id' => $ourTodo,
    ],
]), $secret);
say('RESCHED ' . $code . ' ' . substr($raw, 0, 200));
$book2 = json_decode($raw, true);
say('RESCHED_TODO ' . ($book2['todo_id'] ?? ''));

$ourRow = $conn->query(
    "SELECT DEADLINE, COMPLETED, RESPONSIBLE_ID FROM b_crm_act WHERE ID=" . (int)$ourTodo
)->fetch();
$agentRow = $conn->query(
    "SELECT DEADLINE, COMPLETED, RESPONSIBLE_ID FROM b_crm_act WHERE ID=" . (int)$agentTodo
)->fetch();
say('OUR after deadline=' . ($ourRow['DEADLINE'] ?? '') . ' done=' . ($ourRow['COMPLETED'] ?? '') . ' resp=' . ($ourRow['RESPONSIBLE_ID'] ?? ''));
say('AGENT after deadline=' . ($agentRow['DEADLINE'] ?? '') . ' done=' . ($agentRow['COMPLETED'] ?? '') . ' resp=' . ($agentRow['RESPONSIBLE_ID'] ?? ''));
$c33ok = ((int)($book2['todo_id'] ?? 0) === $ourTodo)
    && ((string)($ourRow['COMPLETED'] ?? '') === 'N')
    && ((int)($ourRow['RESPONSIBLE_ID'] ?? 0) === 2311)
    && ((string)($agentRow['COMPLETED'] ?? '') === 'N')
    && str_contains((string)($agentRow['DEADLINE'] ?? ''), '10/11/2026');
say('C33_MOVE_OURS_ONLY ' . ($c33ok ? 'yes' : 'no'));

// Meeting time still set; stage still 10 (no wipe from field-only write earlier).
$fresh = $factory->getItem($leadId);
say('STAGE ' . ($fresh ? $fresh->getStageId() : ''));
say('MEET ' . (string)($uts['M'] ?? ''));

// Cleanup todos + lead.
foreach ([$ourTodo, $agentTodo] as $tid) {
    if ($tid > 0) {
        $conn->queryExecute('DELETE FROM b_crm_act_bind WHERE ACTIVITY_ID=' . (int)$tid);
        $conn->queryExecute('DELETE FROM b_crm_act WHERE ID=' . (int)$tid);
    }
}
$del = $factory->getDeleteOperation($factory->getItem($leadId), $context);
$del->disableCheckAccess();
$del->disableBizProc();
$del->disableAutomation();
$del->launch();
say('DELETED ' . ($factory->getItem($leadId) === null ? 'yes' : 'no'));
say('PASS ' . ($c32ok && $kept && $c33ok ? 'yes' : 'no'));
say('DONE');
