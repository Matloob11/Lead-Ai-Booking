<?php
/**
 * Proof for the booking action. One test lead, then deleted. No secrets.
 * Run: ops/bitrix.sh run a7_probe_leadai_booking.php
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

$tool = '/home/bitrix/www/bitrix/tools/a7_leadai_fields.php';
passthru('php -l ' . escapeshellarg($tool));

$cfg = include '/home/bitrix/www/bitrix/php_interface/a7_lead_wa.config.php';
$secret = trim((string)($cfg['secret'] ?? ''));
if ($secret === '') {
    say('NO_SECRET');
    exit(1);
}

function call_tool(string $body, string $secret): array
{
    $ts = time();
    $sign = hash_hmac('sha256', 'leadai-fields.' . $ts . '.' . $body, $secret);
    $tmp = tempnam(sys_get_temp_dir(), 'a7book');
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
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$item = $factory->createItem([
    'TITLE' => 'ZZ C9 booking test delete',
    'NAME' => 'Sumon',
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
$title = (string)$item->getTitle();
say('LEAD ' . $leadId);

$conn = \Bitrix\Main\Application::getConnection();
$body = json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-02T16:30:00+04:00',
        'mode' => 42,
        'event' => 'confirmed',
    ],
]);
[$code, $raw] = call_tool($body, $secret);
say('CONFIRMED ' . $code . ' ' . $raw);
$fresh = $factory->getItem($leadId);
$meet = $conn->query("SELECT UF_CRM_1731838813769 M, UF_CRM_1731838790184 MODE, UF_CRM_A7_BOT_STATUS BOT FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}")->fetch();
say('TITLE_SAME ' . ($fresh && (string)$fresh->getTitle() === $title ? 'yes' : 'no'));
say('STAGE ' . ($fresh ? (string)$fresh->getStageId() : ''));
say('MEET ' . (is_array($meet) ? (string)$meet['M'] : ''));
say('MODE ' . (is_array($meet) ? (string)$meet['MODE'] : ''));
say('BOT ' . (is_array($meet) ? (string)$meet['BOT'] : ''));
$rows = $conn->query(
    "SELECT a.ID, a.SUBJECT, a.DEADLINE, a.COMPLETED, a.RESPONSIBLE_ID
     FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
     WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId} AND a.PROVIDER_ID='CRM_TODO'"
);
$open = 0;
$todoId = 0;
while ($rows && ($row = $rows->fetch())) {
    say('TODO ' . $row['ID'] . ' ' . $row['COMPLETED'] . ' ' . $row['DEADLINE'] . ' resp ' . $row['RESPONSIBLE_ID']);
    if ($row['COMPLETED'] === 'N' && $row['SUBJECT'] === 'Viewing/Meeting') {
        $open++;
        $todoId = (int)$row['ID'];
    }
}
say('OPEN_TODOS ' . $open);

$again = json_encode([
    'lead_id' => $leadId,
    'booking' => [
        'meeting_at' => '2026-11-03T11:00:00+04:00',
        'mode' => 42,
        'event' => 'rescheduled',
    ],
]);
[$code, $raw] = call_tool($again, $secret);
say('RESCHEDULED ' . $code . ' ' . $raw);
$open2 = 0;
$same = 0;
$rows = $conn->query(
    "SELECT a.ID, a.DEADLINE, a.COMPLETED, a.SUBJECT
     FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
     WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId} AND a.PROVIDER_ID='CRM_TODO' AND a.COMPLETED='N'"
);
while ($rows && ($row = $rows->fetch())) {
    $open2++;
    if ((int)$row['ID'] === $todoId) {
        $same = 1;
    }
    say('TODO2 ' . $row['ID'] . ' ' . $row['DEADLINE']);
}
say('STILL_ONE ' . ($open2 === 1 && $same === 1 ? 'yes' : 'no'));

$cancel = json_encode([
    'lead_id' => $leadId,
    'booking' => ['event' => 'cancelled'],
]);
[$code, $raw] = call_tool($cancel, $secret);
say('CANCELLED ' . $code . ' ' . $raw);
$after = $factory->getItem($leadId);
say('STAGE_AFTER_CANCEL ' . ($after ? (string)$after->getStageId() : ''));
$done = $conn->query("SELECT COMPLETED FROM b_crm_act WHERE ID={$todoId}")->fetch();
say('TODO_CLOSED ' . (is_array($done) && $done['COMPLETED'] === 'Y' ? 'yes' : 'no'));

$ids = $conn->query(
    "SELECT a.ID FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
     WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}"
);
while ($ids && ($row = $ids->fetch())) {
    $conn->queryExecute('DELETE FROM b_crm_act_bind WHERE ACTIVITY_ID=' . (int)$row['ID']);
    $conn->queryExecute('DELETE FROM b_crm_act WHERE ID=' . (int)$row['ID']);
}
$del = $factory->getDeleteOperation($factory->getItem($leadId), $context);
$del->disableCheckAccess();
$del->disableBizProc();
$del->disableAutomation();
$deleted = $del->launch();
say('DELETED ' . ($deleted->isSuccess() ? 'yes' : 'no'));
say('GONE ' . ($factory->getItem($leadId) === null ? 'yes' : 'no'));
say('DONE');
