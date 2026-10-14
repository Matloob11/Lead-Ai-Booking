<?php
/**
 * Lead AI field writer. The assistant calls this; a browser does not.
 *
 * Signature is checked before Bitrix loads, same secret as a7_leadai_notify.php.
 * The signed text starts with "leadai-fields." so a notify signature cannot
 * be replayed here.
 *
 * POST /bitrix/tools/a7_leadai_fields.php
 * Headers: X-Leadai-Ts, X-Leadai-Sign = hex HMAC-SHA256(secret,
 *          "leadai-fields." . ts . "." . body)
 *
 * Deploy to: /bitrix/tools/a7_leadai_fields.php
 */

function a7_leadai_fields_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function a7_leadai_fields_datetime(string $text): ?string
{
    $text = trim($text);
    if ($text === '') {
        return null;
    }
    if (preg_match('/(?:Z|[+-]\d{2}:?\d{2})$/', $text)) {
        try {
            $when = new \DateTime($text);
        } catch (\Throwable $e) {
            return null;
        }
        $when->setTimezone(new \DateTimeZone('Asia/Dubai'));
        return $when->format('Y-m-d H:i:s');
    }
    foreach (['Y-m-d H:i:s', 'Y-m-d\TH:i:s', 'Y-m-d\TH:i'] as $format) {
        $when = \DateTime::createFromFormat('!' . $format, $text);
        $errors = \DateTime::getLastErrors();
        $bad = is_array($errors) && (($errors['warning_count'] ?? 0) > 0 || ($errors['error_count'] ?? 0) > 0);
        if ($when && !$bad) {
            return $when->format('Y-m-d H:i:s');
        }
    }
    return null;
}

function a7_leadai_fields_safe(string $text, int $limit): string
{
    $text = trim(str_replace(["\r\n", "\r"], "\n", $text));
    $text = strtr($text, ['[' => '(', ']' => ')', '<' => '‹', '>' => '›']);
    if (function_exists('mb_substr')) {
        return mb_substr($text, 0, $limit);
    }
    return substr($text, 0, $limit);
}

/** @return array<string, array<int, true>|string> */
function a7_leadai_fields_allow(): array
{
    return [
        'UF_CRM_LEAD_1737031634747' => [2467 => true],
        'UF_CRM_A7_AI_BUSINESS_ACTIVITY' => 'text',
        'UF_CRM_A7_AI_TRADE_LICENSE_STATUS' => [2159 => true, 2160 => true, 2455 => true, 2456 => true, 2457 => true],
        'UF_CRM_1731838813769' => 'datetime',
        'UF_CRM_A7_SHOP_TYPE' => [2471 => true, 2472 => true, 2473 => true, 2474 => true],
        'UF_CRM_A7_BOT_STATUS' => [2475 => true, 2476 => true, 2477 => true, 2478 => true, 2479 => true, 2480 => true, 2481 => true],
        'UF_CRM_A7_WA_OPT_OUT' => [2482 => true, 2483 => true],
    ];
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    a7_leadai_fields_json(['ok' => false, 'error' => 'POST only.'], 405);
}

$cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
$cfg = is_readable($cfgPath) ? include $cfgPath : null;
$secret = trim((string)((is_array($cfg) ? $cfg : [])['secret'] ?? ''));
if ($secret === '') {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Not configured.'], 503);
}

$raw = (string)file_get_contents('php://input');
if ($raw === '' || strlen($raw) > 8 * 1024 * 1024) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Bad body.'], 400);
}
$ts = (string)($_SERVER['HTTP_X_LEADAI_TS'] ?? '');
$sign = strtolower((string)($_SERVER['HTTP_X_LEADAI_SIGN'] ?? ''));
if (!ctype_digit($ts) || abs(time() - (int)$ts) > 300 || !preg_match('/^[0-9a-f]{64}$/', $sign)) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Unauthorized.'], 401);
}
if (!hash_equals(hash_hmac('sha256', 'leadai-fields.' . $ts . '.' . $raw, $secret), $sign)) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Unauthorized.'], 401);
}
$in = json_decode($raw, true);
if (!is_array($in)) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Body is not JSON.'], 400);
}

$leadId = (int)($in['lead_id'] ?? 0);
if ($leadId <= 0) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'No lead.'], 400);
}
// This request is the C6 tool. The lead-update handler must not tell the bot
// about a status the assistant just wrote itself.
$GLOBALS['A7_LEADAI_FIELDS_SAVE'] = $leadId;
$allow = a7_leadai_fields_allow();
$fieldsIn = $in['fields'] ?? [];
if ($fieldsIn === null) {
    $fieldsIn = [];
}
if (!is_array($fieldsIn)) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'fields must be an object.'], 400);
}
$onlyEmpty = $in['only_if_empty'] ?? [];
if ($onlyEmpty === null) {
    $onlyEmpty = [];
}
if (!is_array($onlyEmpty)) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'only_if_empty must be a list.'], 400);
}
$onlySet = [];
foreach ($onlyEmpty as $code) {
    $code = (string)$code;
    if (!isset($allow[$code]) && $code !== 'UF_CRM_A7_TRADE_LICENSE_FILE') {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Unknown field.'], 400);
    }
    $onlySet[$code] = true;
}

$writes = [];
foreach ($fieldsIn as $code => $value) {
    $code = (string)$code;
    if ($code === 'UF_CRM_A7_TRADE_LICENSE_FILE') {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Send the licence as license_file.'], 400);
    }
    if (!isset($allow[$code])) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Unknown field.'], 400);
    }
    $rule = $allow[$code];
    if ($rule === 'text') {
        if (!is_string($value)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        $text = a7_leadai_fields_safe($value, 1000);
        if ($text === '') {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        $writes[$code] = $text;
        continue;
    }
    if ($rule === 'datetime') {
        $stored = a7_leadai_fields_datetime(trim((string)$value));
        if ($stored === null) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        $writes[$code] = ['datetime' => $stored];
        continue;
    }
    if (is_string($value) && ctype_digit($value)) {
        $value = (int)$value;
    }
    if (!is_int($value) || !isset($rule[$value])) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Unknown enum.'], 400);
    }
    $writes[$code] = $value;
}

$license = $in['license_file'] ?? null;
$licenseBytes = '';
$licenseName = '';
if ($license !== null) {
    if (!is_array($license)) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad licence file.'], 400);
    }
    $encoded = (string)($license['content_base64'] ?? '');
    $decoded = base64_decode($encoded, true);
    if ($decoded === false || $decoded === '' || strlen($decoded) > 5 * 1024 * 1024) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad licence file.'], 400);
    }
    if (strncmp($decoded, '%PDF', 4) === 0) {
        $ext = 'pdf';
        $mime = 'application/pdf';
    } elseif (strncmp($decoded, "\xFF\xD8\xFF", 3) === 0) {
        $ext = 'jpg';
        $mime = 'image/jpeg';
    } elseif (strncmp($decoded, "\x89PNG\r\n\x1a\n", 8) === 0) {
        $ext = 'png';
        $mime = 'image/png';
    } else {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Licence must be a PDF, JPEG or PNG.'], 400);
    }
    $licenseBytes = $decoded;
    $licenseName = 'licence.' . $ext;
    $licenseMime = $mime;
}

$booking = null;
if (array_key_exists('booking', $in) && $in['booking'] !== null) {
    if (!is_array($in['booking'])) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
    }
    $event = (string)($in['booking']['event'] ?? '');
    if (!in_array($event, ['confirmed', 'rescheduled', 'cancelled'], true)) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
    }
    $meeting = null;
    if ($event !== 'cancelled') {
        $meeting = a7_leadai_fields_datetime((string)($in['booking']['meeting_at'] ?? ''));
        $mode = $in['booking']['mode'] ?? null;
        if ($meeting === null || (int)$mode !== 42) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
        }
    }
    $booking = ['event' => $event, 'meeting' => $meeting];
    if ($event !== 'cancelled') {
        $writes['UF_CRM_1731838813769'] = ['datetime' => $meeting];
        $writes['UF_CRM_1731838790184'] = 42;
        $writes['UF_CRM_A7_BOT_STATUS'] = 2477;
    }
}

$lostIn = $in['lost'] ?? null;
$lostStatus = null;
$lostReason = '';
if ($lostIn !== null) {
    if (!is_array($lostIn)) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad lost stage.'], 400);
    }
    $lostStatus = (string)($lostIn['status_id'] ?? '');
    if ($lostStatus !== '1' && $lostStatus !== 'JUNK') {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad lost stage.'], 400);
    }
    $lostReason = a7_leadai_fields_safe((string)($lostIn['reason'] ?? ''), 1000);
    if ($lostReason === '') {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Lost needs the customer\'s words.'], 400);
    }
}
if ($booking !== null && $lostStatus !== null) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'A booking cannot also mark the lead lost.'], 400);
}
$extraComment = '';
if (array_key_exists('comment', $in) && $in['comment'] !== null && $in['comment'] !== '') {
    $extraComment = a7_leadai_fields_safe((string)$in['comment'], 1000);
    if ($extraComment === '') {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad comment.'], 400);
    }
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$root = (string)($_SERVER['DOCUMENT_ROOT'] ?? '');
if ($root === '' || !is_file($root . '/bitrix/modules/main/include/prolog_before.php')) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Not configured.'], 503);
}
require $root . '/bitrix/modules/main/include/prolog_before.php';

if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'CRM unavailable.'], 503);
}

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
if ($factory === null) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'CRM unavailable.'], 503);
}
$item = $factory->getItem($leadId);
if ($item === null) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'No such lead.'], 404);
}

function a7_leadai_fields_empty($value): bool
{
    if ($value === null || $value === false) {
        return true;
    }
    if (is_array($value)) {
        return $value === [] || $value === [''];
    }
    $text = trim((string)$value);
    return $text === '' || $text === '0';
}

$updated = [];
$skipped = [];
$licenseFileId = 0;
try {
foreach ($writes as $code => $value) {
    $bookingForces = ($booking !== null && $booking['event'] !== 'cancelled'
        && in_array($code, ['UF_CRM_1731838813769', 'UF_CRM_1731838790184', 'UF_CRM_A7_BOT_STATUS'], true));
    if (!$bookingForces && isset($onlySet[$code]) && !a7_leadai_fields_empty($item->get($code))) {
        $skipped[] = $code;
        continue;
    }
    if (is_array($value) && isset($value['datetime'])) {
        $value = new \Bitrix\Main\Type\DateTime($value['datetime'], 'Y-m-d H:i:s');
    }
    $item->set($code, $value);
    $updated[] = $code;
}
if ($booking !== null && $booking['event'] !== 'cancelled') {
    $item->setStageId('10');
}

if ($licenseBytes !== '') {
    $fileCode = 'UF_CRM_A7_TRADE_LICENSE_FILE';
    if (isset($onlySet[$fileCode]) && !a7_leadai_fields_empty($item->get($fileCode))) {
        $skipped[] = $fileCode;
    } else {
        $tmp = tempnam(sys_get_temp_dir(), 'a7lic');
        if ($tmp === false || file_put_contents($tmp, $licenseBytes) === false) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Could not store the licence.'], 502);
        }
        $file = \CFile::MakeFileArray($tmp);
        if (!is_array($file)) {
            @unlink($tmp);
            a7_leadai_fields_json(['ok' => false, 'error' => 'Could not store the licence.'], 502);
        }
        $file['name'] = $licenseName;
        $file['type'] = $licenseMime;
        $file['MODULE_ID'] = 'crm';
        $fileId = (int)\CFile::SaveFile($file, 'crm');
        @unlink($tmp);
        if ($fileId <= 0) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Could not store the licence.'], 502);
        }
        $licenseFileId = $fileId;
    }
}

$context = new \Bitrix\Crm\Service\Context();
$context->setUserId(1);

if ($updated !== []) {
    $op = $factory->getUpdateOperation($item, $context);
    $op->disableCheckAccess();
    $op->disableBizProc();
    $op->disableAutomation();
    $result = $op->launch();
    if (!$result->isSuccess()) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bitrix did not save the fields.'], 502);
    }
}
} catch (\Throwable $e) {
    a7_leadai_fields_json(['ok' => false, 'error' => 'Bitrix did not save the fields.'], 502);
}

if ($licenseFileId > 0) {
    // The CRM item save drops a file id. The column write does not start BP 235.
    \Bitrix\Main\Application::getConnection()->queryExecute(
        'UPDATE b_uts_crm_lead SET UF_CRM_A7_TRADE_LICENSE_FILE=' . $licenseFileId
        . ' WHERE VALUE_ID=' . $leadId
    );
    $updated[] = 'UF_CRM_A7_TRADE_LICENSE_FILE';
}

if ($lostStatus !== null) {
    $fresh = $factory->getItem($leadId);
    if ($fresh === null) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'No such lead.'], 404);
    }
    $fresh->setStageId($lostStatus);
    $op = $factory->getUpdateOperation($fresh, $context);
    $op->disableCheckAccess();
    // BP 235 on JUNK and status 1 creates a Lead Pool item and rewrites TITLE.
    // The stage still changes. The customer's words go on the timeline instead.
    $op->disableBizProc();
    $op->disableAutomation();
    $result = $op->launch();
    if (!$result->isSuccess()) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bitrix did not move the lead.'], 502);
    }
}

function a7_leadai_fields_comment(int $leadId, string $text): void
{
    if ($text === '') {
        return;
    }
    if (!str_starts_with($text, 'Lead AI:')) {
        $text = 'Lead AI: ' . $text;
    }
    \Bitrix\Crm\Timeline\CommentEntry::create([
        'TEXT' => $text,
        'AUTHOR_ID' => 1,
        'SETTINGS' => [],
        'BINDINGS' => [['ENTITY_TYPE_ID' => \CCrmOwnerType::Lead, 'ENTITY_ID' => $leadId]],
    ]);
}

if ($lostReason !== '') {
    a7_leadai_fields_comment($leadId, $lostReason);
}
if ($extraComment !== '') {
    a7_leadai_fields_comment($leadId, $extraComment);
}

function a7_leadai_fields_open_todo(int $leadId): int
{
    $row = \Bitrix\Main\Application::getConnection()->query(
        "SELECT a.ID FROM b_crm_act a
         JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
         WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}
           AND a.PROVIDER_ID='CRM_TODO' AND a.SUBJECT='Viewing/Meeting' AND a.COMPLETED='N'
         ORDER BY a.ID DESC LIMIT 1"
    )->fetch();
    return is_array($row) ? (int)$row['ID'] : 0;
}

function a7_leadai_fields_todo_window(string $meeting): array
{
    $start = new \Bitrix\Main\Type\DateTime($meeting, 'Y-m-d H:i:s');
    $end = clone $start;
    $end->add('1 hour');
    return [$start->toString(), $end->toString()];
}

function a7_leadai_fields_plan_todo(int $leadId, int $responsible, string $meeting): int
{
    [$start, $end] = a7_leadai_fields_todo_window($meeting);
    $existing = a7_leadai_fields_open_todo($leadId);
    $fields = [
        'DEADLINE' => $start,
        'START_TIME' => $start,
        'END_TIME' => $end,
        'RESPONSIBLE_ID' => $responsible,
        'COMPLETED' => 'N',
    ];
    if ($existing > 0) {
        $ok = \CCrmActivity::Update($existing, $fields, false, false, ['REGISTER_SONET_EVENT' => false]);
        if (!$ok) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Could not move the viewing.'], 502);
        }
        return $existing;
    }
    $fields += [
        'TYPE_ID' => 6,
        'PROVIDER_ID' => 'CRM_TODO',
        'PROVIDER_TYPE_ID' => 'TODO',
        'SUBJECT' => 'Viewing/Meeting',
        'DESCRIPTION' => 'Viewing/Meeting',
        'DESCRIPTION_TYPE' => 2,
        'DIRECTION' => 0,
        'PRIORITY' => 1,
        'NOTIFY_TYPE' => 0,
        'OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
        'OWNER_ID' => $leadId,
        'BINDINGS' => [[
            'OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
            'OWNER_ID' => $leadId,
        ]],
    ];
    $id = (int)\CCrmActivity::Add($fields, false, false, ['REGISTER_SONET_EVENT' => false]);
    if ($id <= 0) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Could not plan the viewing.'], 502);
    }
    return $id;
}

$todoId = null;
if ($booking !== null) {
    // C26 / Q22: Viewing/Meeting to-do belongs to Matloob (2311). The lead's
    // responsible is unchanged. A reschedule updates the same to-do and keeps 2311.
    $responsible = 2311;
    if ($booking['event'] === 'cancelled') {
        $open = a7_leadai_fields_open_todo($leadId);
        if ($open > 0) {
            $fields = ['COMPLETED' => 'Y'];
            $ok = \CCrmActivity::Update($open, $fields, false, false, ['REGISTER_SONET_EVENT' => false]);
            if (!$ok) {
                a7_leadai_fields_json(['ok' => false, 'error' => 'Could not close the viewing.'], 502);
            }
            $todoId = $open;
        }
    } else {
        $todoId = a7_leadai_fields_plan_todo($leadId, $responsible, (string)$booking['meeting']);
    }
}

a7_leadai_fields_json([
    'ok' => true,
    'lead_id' => $leadId,
    'updated' => $updated,
    'skipped' => $skipped,
    'lost' => $lostStatus,
    'todo_id' => $todoId,
]);
