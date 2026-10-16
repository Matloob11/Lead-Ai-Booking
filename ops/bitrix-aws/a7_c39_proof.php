<?php
/**
 * C39 proof: fields write, rent/sale kept, unknown 400, no to-do. Deletes the lead.
 * CLI only.
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
    $tmp = tempnam(sys_get_temp_dir(), 'a7c39');
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
$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);
$item = $factory->createItem([
    'TITLE' => 'ZZ C39 res delete',
    'NAME' => 'Res',
    'ASSIGNED_BY_ID' => 1,
    'STATUS_ID' => 'IN_PROCESS',
]);
$add = $factory->getAddOperation($item, $context);
$add->disableCheckAccess();
$add->disableBizProc();
$add->disableAutomation();
$add->launch();
$leadId = (int)$item->getId();
$made = $factory->getItem($leadId);
$titleBefore = $made ? (string)$made->getTitle() : '';
$stageBefore = $made ? (string)$made->getStageId() : '';
say('LEAD ' . $leadId . ' stage=' . $stageBefore);

[$bad] = call_fields(json_encode([
    'lead_id' => $leadId,
    'fields' => ['UF_CRM_A7_NOT_A_FIELD' => 'x'],
]), $secret);
say('UNKNOWN ' . $bad);

[$code, $body] = call_fields(json_encode([
    'lead_id' => $leadId,
    'fields' => [
        'UF_CRM_A7_CLUSTERS' => 'England, France',
        'UF_CRM_A7_BALCONY' => 2503,
        'UF_CRM_A7_FULL_NAME' => 'Ada Test',
        'UF_CRM_A7_RENT_SALE' => 2444,
        'UF_CRM_1731838126127' => 26,
        'UF_CRM_1756638760279' => 1220,
    ],
    'email' => 'c39-proof@example.com',
]), $secret);
say('WRITE ' . $code . ' ' . json_encode($body['updated'] ?? []));
$row = $conn->query(
    "SELECT UF_CRM_A7_CLUSTERS C, UF_CRM_A7_BALCONY B, UF_CRM_A7_RENT_SALE RS,
            UF_CRM_1731838126127 BEDS, UF_CRM_1756638760279 CT
     FROM b_uts_crm_lead WHERE VALUE_ID={$leadId}"
)->fetch();
$fresh = $factory->getItem($leadId);
$todos = (int)$conn->query(
    "SELECT COUNT(*) n FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
     WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId} AND a.COMPLETED='N'"
)->fetch()['n'];
$email = $conn->query(
    "SELECT VALUE FROM b_crm_field_multi WHERE ENTITY_ID='LEAD' AND ELEMENT_ID={$leadId} AND TYPE_ID='EMAIL' LIMIT 1"
)->fetch();
say('CLUSTERS ' . ($row['C'] ?? '') . ' BALCONY ' . ($row['B'] ?? '') . ' RS ' . ($row['RS'] ?? ''));
say('STAGE ' . ($fresh ? $fresh->getStageId() : '') . ' TITLE ' . ($fresh ? $fresh->getTitle() : '') . ' TODOS ' . $todos);
say('EMAIL ' . ($email['VALUE'] ?? ''));
$ok = $bad === 400 && $code === 200
    && (string)$row['C'] === 'England, France'
    && (int)$row['B'] === 2503
    && (int)$row['RS'] === 2444
    && (int)$row['BEDS'] === 26
    && (int)$row['CT'] === 1220
    && $fresh && (string)$fresh->getStageId() === $stageBefore
    && (string)$fresh->getTitle() === $titleBefore
    && $todos === 0
    && ($email['VALUE'] ?? '') === 'c39-proof@example.com';

$del = $factory->getDeleteOperation($factory->getItem($leadId), $context);
$del->disableCheckAccess();
$del->disableBizProc();
$del->disableAutomation();
$del->launch();
say('DELETED ' . ($factory->getItem($leadId) === null ? 'yes' : 'no'));
say('PASS ' . ($ok ? 'yes' : 'no'));
say('DONE');
exit($ok ? 0 : 1);
