<?php
/**
 * Replay the assistant's confirmed-booking crm.lead.update on one test lead.
 * Prints the meeting time, to-do count and title. Deletes the lead. No secrets.
 *
 * Run: ops/bitrix.sh run a7_probe_booking_bp.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

function say(string $line): void
{
    echo $line, "\n";
}

\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$item = $factory->createItem([
    'TITLE' => 'ZZ C7 booking test delete',
    'NAME' => 'Sumon',
    'LAST_NAME' => 'Khan',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'IN_PROCESS',
]);
$add = $factory->getAddOperation($item, $context);
$add->disableCheckAccess();
$add->disableBizProc();
$add->disableAutomation();
$added = $add->launch();
if (!$added->isSuccess()) {
    say('CREATE_FAIL ' . implode('; ', $added->getErrorMessages()));
    exit(1);
}
$leadId = (int)$item->getId();
say('LEAD ' . $leadId);

$cfg = include '/home/bitrix/www/bitrix/php_interface/a7_3cx.config.php';
$base = rtrim((string)($cfg['bitrix_webhook_url'] ?? ''), '/');
if ($base === '') {
    say('NO_WEBHOOK');
    exit(1);
}
// The same three fields booking_fields() sends when the lead has no details yet.
// The time is what Django's isoformat() produces for 16:30 Asia/Dubai.
$payload = json_encode([
    'id' => $leadId,
    'fields' => [
        'STATUS_ID' => '10',
        'UF_CRM_1731838813769' => '2026-11-02T16:30:00+04:00',
        'UF_CRM_1731838790184' => 42,
    ],
]);
$tmp = tempnam(sys_get_temp_dir(), 'a7book');
file_put_contents($tmp, $payload);
$cmd = 'curl -sk --max-time 60 -o - -w "\nHTTP %{http_code}" -X POST -H '
    . escapeshellarg('Content-Type: application/json')
    . ' --data-binary @' . escapeshellarg($tmp)
    . ' ' . escapeshellarg($base . '/crm.lead.update.json');
$raw = (string)shell_exec($cmd);
@unlink($tmp);
$code = 0;
if (preg_match('/HTTP (\d+)\s*$/', $raw, $match)) {
    $code = (int)$match[1];
    $raw = trim(substr($raw, 0, -strlen($match[0])));
}
$decoded = json_decode($raw, true);
$err = is_array($decoded) ? (string)($decoded['error_description'] ?? $decoded['error'] ?? '') : 'not-json';
say('REST ' . $code . ' ' . ($err !== '' ? $err : 'ok'));

$conn = \Bitrix\Main\Application::getConnection();
$fresh = $factory->getItem($leadId);
$meet = $conn->query(
    "SELECT UF_CRM_1731838813769 M, UF_CRM_1731838790184 MODE FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
)->fetch();
say('TITLE ' . ($fresh ? (string)$fresh->getTitle() : 'missing'));
say('STAGE ' . ($fresh ? (string)$fresh->getStageId() : 'missing'));
say('MEET ' . (is_array($meet) ? (string)$meet['M'] : ''));
say('MODE ' . (is_array($meet) ? (string)$meet['MODE'] : ''));
$todos = $conn->query(
    "SELECT a.ID, a.SUBJECT, a.DEADLINE FROM b_crm_act a
     JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
     WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}"
);
$n = 0;
while ($todos && ($row = $todos->fetch())) {
    $n++;
    say('TODO ' . $row['ID'] . ' ' . $row['SUBJECT'] . ' ' . $row['DEADLINE']);
    $conn->queryExecute('DELETE FROM b_crm_act_bind WHERE ACTIVITY_ID=' . (int)$row['ID']);
    $conn->queryExecute('DELETE FROM b_crm_act WHERE ID=' . (int)$row['ID']);
}
say('TODO_COUNT ' . $n);

if ($fresh !== null) {
    $del = $factory->getDeleteOperation($fresh, $context);
    $del->disableCheckAccess();
    $del->disableBizProc();
    $del->disableAutomation();
    $deleted = $del->launch();
    say('DELETED ' . ($deleted->isSuccess() ? 'yes' : 'no'));
}
$gone = $factory->getItem($leadId);
say('GONE ' . ($gone === null ? 'yes' : 'no'));
say('DONE');
