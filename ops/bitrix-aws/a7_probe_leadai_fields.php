<?php
/**
 * Proof for a7_leadai_fields.php. Creates one test lead, calls the tool, deletes the lead.
 * Prints status codes and field checks. Does not print the signing secret.
 *
 * Run: ops/bitrix.sh run a7_probe_leadai_fields.php
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

function call_tool(string $method, string $body, ?string $secret, ?int $ts = null, ?string $sign = null): array
{
    $tmp = tempnam(sys_get_temp_dir(), 'a7fld');
    if ($tmp === false) {
        return [0, ''];
    }
    file_put_contents($tmp, $body);
    $cmd = 'curl -sk -D - --max-time 60 -o - -X ' . escapeshellarg($method)
        . ' -H ' . escapeshellarg('Host: crm.a7grouprealestatedxb.com')
        . ' -H ' . escapeshellarg('Content-Type: application/json');
    if ($ts !== null) {
        $cmd .= ' -H ' . escapeshellarg('X-Leadai-Ts: ' . (string)$ts);
    }
    if ($sign !== null) {
        $cmd .= ' -H ' . escapeshellarg('X-Leadai-Sign: ' . $sign);
    }
    if ($method !== 'GET') {
        $cmd .= ' --data-binary @' . escapeshellarg($tmp);
    }
    $cmd .= ' https://127.0.0.1/bitrix/tools/a7_leadai_fields.php';
    $raw = (string)shell_exec($cmd);
    @unlink($tmp);
    $code = 0;
    if (preg_match('#^HTTP/\S+\s+(\d+)#m', $raw, $match)) {
        $code = (int)$match[1];
    }
    $parts = preg_split("#\r\n\r\n#", $raw, 2);
    return [$code, isset($parts[1]) ? $parts[1] : ''];
}

function signed(string $body, string $secret, ?int $ts = null): array
{
    $ts = $ts ?? time();
    $sign = hash_hmac('sha256', 'leadai-fields.' . $ts . '.' . $body, $secret);
    return call_tool('POST', $body, $secret, $ts, $sign);
}

[$code, $body] = call_tool('GET', '', null);
say('GET ' . $code);

[$code, $body] = call_tool('POST', '{"lead_id":1,"fields":{}}', null);
say('UNSIGNED ' . $code);

$bad = hash_hmac('sha256', 'leadai-fields.' . time() . '.{"lead_id":1}', $secret);
$bad[0] = $bad[0] === 'a' ? 'b' : 'a';
[$code, $body] = call_tool('POST', '{"lead_id":1}', null, time(), $bad);
say('WRONG ' . $code);

[$code, $body] = signed('{"lead_id":1,"fields":{"NOPE":1}}', $secret, time() - 400);
say('OLD ' . $code);

[$code, $raw] = signed('{"lead_id":1,"fields":{"NOPE":1}}', $secret);
say('UNKNOWN_FIELD ' . $code . ' ' . $raw);

\Bitrix\Main\Loader::includeModule('crm');
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$item = $factory->createItem([
    'TITLE' => 'ZZ C6 fields test delete',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'NEW',
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

$meetPayload = json_encode([
    'lead_id' => $leadId,
    'fields' => ['UF_CRM_1731838813769' => '2026-11-01 10:00:00'],
]);
[$code, $raw] = signed($meetPayload, $secret);
say('MEET_WRITE ' . $code . ' ' . $raw);

$conn = \Bitrix\Main\Application::getConnection();
$before = $factory->getItem($leadId);
$titleBefore = (string)$before->getTitle();
$stageBefore = (string)$before->getStageId();
$meetBefore = (string)$before->get('UF_CRM_1731838813769');
$todosBefore = (int)$conn->query(
    "SELECT COUNT(*) C FROM b_crm_act_bind WHERE OWNER_TYPE_ID=1 AND OWNER_ID={$leadId}"
)->fetch()['C'];

$payload = json_encode([
    'lead_id' => $leadId,
    'fields' => ['UF_CRM_A7_SHOP_TYPE' => 2471, 'UF_CRM_A7_BOT_STATUS' => 2476],
]);
[$code, $raw] = signed($payload, $secret);
say('WRITE ' . $code . ' ' . $raw);
$after = $factory->getItem($leadId);
$todosAfter = (int)$conn->query(
    "SELECT COUNT(*) C FROM b_crm_act_bind WHERE OWNER_TYPE_ID=1 AND OWNER_ID={$leadId}"
)->fetch()['C'];
say('TITLE_SAME ' . ($after->getTitle() === $titleBefore ? 'yes' : 'no'));
say('STAGE_SAME ' . ($after->getStageId() === $stageBefore ? 'yes' : 'no'));
say('MEET_SAME ' . ((string)$after->get('UF_CRM_1731838813769') === $meetBefore ? 'yes' : 'no'));
say('TODOS ' . $todosBefore . ' ' . $todosAfter);
say('SHOP ' . (string)$after->get('UF_CRM_A7_SHOP_TYPE'));
say('BOT ' . (string)$after->get('UF_CRM_A7_BOT_STATUS'));

$lost = json_encode([
    'lead_id' => $leadId,
    'lost' => ['status_id' => '1', 'reason' => 'test customer said not now'],
]);
[$code, $raw] = signed($lost, $secret);
say('LOST ' . $code . ' ' . $raw);
$moved = $factory->getItem($leadId);
say('STAGE_NOW ' . (string)$moved->getStageId());
$comment = $conn->query(
    "SELECT t.COMMENT C FROM b_crm_timeline t
     JOIN b_crm_timeline_bind b ON b.OWNER_ID=t.ID
     WHERE b.ENTITY_TYPE_ID=1 AND b.ENTITY_ID={$leadId}
     ORDER BY t.ID DESC LIMIT 1"
)->fetch();
$commentText = is_array($comment) ? (string)$comment['C'] : '';
say('COMMENT_OK ' . (str_contains($commentText, 'Lead AI:') && str_contains($commentText, 'not now') ? 'yes' : 'no'));

$pdf = "%PDF-1.1\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF";
$filePayload = json_encode([
    'lead_id' => $leadId,
    'license_file' => ['name' => 'licence.pdf', 'content_base64' => base64_encode($pdf)],
]);
[$code, $raw] = signed($filePayload, $secret);
say('FILE ' . $code . ' ' . $raw);
$withFile = $factory->getItem($leadId);
$fileValue = $withFile->get('UF_CRM_A7_TRADE_LICENSE_FILE');
$col = $conn->query(
    "SELECT UF_CRM_A7_TRADE_LICENSE_FILE F FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
)->fetch();
$colId = is_array($col) ? (int)$col['F'] : 0;
say('FILE_COL ' . $colId);
say('FILE_GET ' . (is_scalar($fileValue) || $fileValue === null ? var_export($fileValue, true) : gettype($fileValue)));
say('FILE_SET ' . ($colId > 0 ? 'yes' : 'no'));
if ($colId > 0) {
    \CFile::Delete($colId);
}

$delItem = $factory->getItem($leadId);
$del = $factory->getDeleteOperation($delItem, $context);
$del->disableCheckAccess();
$del->disableBizProc();
$del->disableAutomation();
$deleted = $del->launch();
say('DELETED ' . ($deleted->isSuccess() ? 'yes' : 'no'));
$gone = $factory->getItem($leadId);
say('GONE ' . ($gone === null ? 'yes' : 'no'));
say('DONE');
