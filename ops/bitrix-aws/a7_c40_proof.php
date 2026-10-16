<?php
/**
 * C40: online Sales call booking, move, cancel, plain to-do. Deletes the lead.
 * Relabels Bot Status 2477. CLI only.
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

function say(string $l): void
{
    echo $l, "\n";
}

function call_fields(string $body, string $secret): array
{
    $ts = time();
    $sign = hash_hmac('sha256', 'leadai-fields.' . $ts . '.' . $body, $secret);
    $tmp = tempnam(sys_get_temp_dir(), 'a7c40');
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
    if (preg_match('#^HTTP/\S+\s+(\d+)#m', $raw, $m)) {
        $code = (int)$m[1];
    }
    $parts = preg_split("#\r\n\r\n#", $raw, 2);
    $json = json_decode($parts[1] ?? '', true);
    return [$code, is_array($json) ? $json : []];
}

\Bitrix\Main\Loader::includeModule('crm');
$conn = \Bitrix\Main\Application::getConnection();
$cfg = include '/home/bitrix/www/bitrix/php_interface/a7_lead_wa.config.php';
$secret = trim((string)($cfg['secret'] ?? ''));
if ($secret === '') {
    say('NO_SECRET');
    exit(1);
}

$conn->queryExecute(
    "UPDATE b_user_field_enum SET VALUE='Booked (viewing or call)' WHERE ID=2477 AND XML_ID='45e1733d47249547eca2bbf5253d2c2b'"
);
$enum = $conn->query("SELECT VALUE, XML_ID FROM b_user_field_enum WHERE ID=2477")->fetch();
say('LABEL ' . ($enum['VALUE'] ?? '') . ' XML ' . ($enum['XML_ID'] ?? ''));
$labelOk = (($enum['VALUE'] ?? '') === 'Booked (viewing or call)')
    && (($enum['XML_ID'] ?? '') === '45e1733d47249547eca2bbf5253d2c2b');

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$item = $factory->createItem([
    'TITLE' => 'ZZ C40 call delete',
    'NAME' => 'Call',
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

[$code, $body] = call_fields(json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-12T15:00:00+04:00',
        'mode' => 43,
        'event' => 'confirmed',
        'todo_subject' => 'Sales call',
    ],
]), $secret);
say('BOOK ' . $code . ' todo=' . (int)($body['todo_id'] ?? 0));
$todo = (int)($body['todo_id'] ?? 0);
$row = $conn->query(
    "SELECT UF_CRM_1731838790184 MODE, UF_CRM_A7_BOT_STATUS BOT, UF_CRM_1731838813769 MEET
     FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
)->fetch();
$act = $conn->query(
    "SELECT SUBJECT, RESPONSIBLE_ID, COMPLETED, DEADLINE FROM b_crm_act WHERE ID={$todo}"
)->fetch();
say('MODE ' . ($row['MODE'] ?? '') . ' BOT ' . ($row['BOT'] ?? '') . ' MEET ' . ($row['MEET'] ?? ''));
say('TODO sub=' . ($act['SUBJECT'] ?? '') . ' resp=' . ($act['RESPONSIBLE_ID'] ?? '') . ' done=' . ($act['COMPLETED'] ?? ''));
$bookOk = $code === 200 && (int)$row['MODE'] === 43 && (int)$row['BOT'] === 2477
    && ($act['SUBJECT'] ?? '') === 'Sales call' && (int)($act['RESPONSIBLE_ID'] ?? 0) === 2311;

[$code2, $body2] = call_fields(json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-12T16:30:00+04:00',
        'mode' => 43,
        'event' => 'rescheduled',
        'todo_subject' => 'Sales call',
        'crm_todo_id' => $todo,
    ],
]), $secret);
$act2 = $conn->query("SELECT ID, SUBJECT, RESPONSIBLE_ID FROM b_crm_act WHERE ID={$todo}")->fetch();
$moved = $code2 === 200 && (int)($body2['todo_id'] ?? 0) === $todo && ($act2['SUBJECT'] ?? '') === 'Sales call';
say('MOVE ' . ($moved ? 'yes' : 'no') . ' http=' . $code2);

[$code3] = call_fields(json_encode([
    'lead_id' => $leadId,
    'booking' => ['event' => 'cancelled', 'todo_subject' => 'Sales call', 'crm_todo_id' => $todo],
]), $secret);
$act3 = $conn->query("SELECT COMPLETED FROM b_crm_act WHERE ID={$todo}")->fetch();
$cancelled = $code3 === 200 && ($act3['COMPLETED'] ?? '') === 'Y';
say('CANCEL ' . ($cancelled ? 'yes' : 'no'));

[$code4, $body4] = call_fields(json_encode([
    'lead_id' => $leadId,
    'todo' => ['subject' => 'PDPL deletion', 'deadline' => '2026-11-20T10:00:00+04:00'],
]), $secret);
$plainId = (int)($body4['todo_id'] ?? 0);
$act4 = $plainId ? $conn->query("SELECT SUBJECT, RESPONSIBLE_ID, COMPLETED FROM b_crm_act WHERE ID={$plainId}")->fetch() : [];
$plainOk = $code4 === 200 && ($act4['SUBJECT'] ?? '') === 'PDPL deletion' && (int)($act4['RESPONSIBLE_ID'] ?? 0) === 2311;
say('PLAIN ' . ($plainOk ? 'yes' : 'no') . ' id=' . $plainId);

// Old body (mode 42, no subject) still 200.
[$code5] = call_fields(json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-13T11:00:00+04:00',
        'mode' => 42,
        'event' => 'confirmed',
    ],
]), $secret);
say('OLD_BODY ' . $code5);

$ids = $conn->query(
    "SELECT a.ID FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
     WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}"
);
while ($ids && ($r = $ids->fetch())) {
    $conn->queryExecute('DELETE FROM b_crm_act_bind WHERE ACTIVITY_ID=' . (int)$r['ID']);
    $conn->queryExecute('DELETE FROM b_crm_act WHERE ID=' . (int)$r['ID']);
}
$del = $factory->getDeleteOperation($factory->getItem($leadId), $context);
$del->disableCheckAccess();
$del->disableBizProc();
$del->disableAutomation();
$del->launch();
$gone = $factory->getItem($leadId) === null;
say('DELETED ' . ($gone ? 'yes' : 'no'));
$pass = $labelOk && $bookOk && $moved && $cancelled && $plainOk && $code5 === 200 && $gone;
say('PASS ' . ($pass ? 'yes' : 'no'));
say('DONE');
exit($pass ? 0 : 1);
