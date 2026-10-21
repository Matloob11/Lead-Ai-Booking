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
        'UF_CRM_LEAD_1737031634747' => [2467 => true, 804 => true, 805 => true],
        'UF_CRM_A7_RENT_SALE' => [2443 => true, 2444 => true, 2445 => true],
        'UF_CRM_1731838126127' => [26 => true, 27 => true],
        'UF_CRM_1756638760279' => [1220 => true, 972 => true],
        'UF_CRM_A7_CLUSTERS' => 'text',
        'UF_CRM_A7_TIMELINE' => 'text',
        'UF_CRM_A7_FULL_NAME' => 'text',
        'UF_CRM_A7_BALCONY' => [2501 => true, 2502 => true, 2503 => true],
        'UF_CRM_A7_VACANT_RENTED' => [2504 => true, 2505 => true, 2506 => true],
        'UF_CRM_A7_PAYMENT' => [2507 => true, 2508 => true],
        'UF_CRM_A7_OCCUPANCY' => [2509 => true, 2510 => true, 2511 => true, 2512 => true],
        'UF_CRM_A7_AI_BUSINESS_ACTIVITY' => 'text',
        'UF_CRM_A7_AI_TRADE_LICENSE_STATUS' => [2159 => true, 2160 => true, 2455 => true, 2456 => true, 2457 => true],
        'UF_CRM_1731838813769' => 'datetime',
        // C32: booking details (only_if_empty). Budget a number, Size text, Location https URL.
        'UF_CRM_1731838831905' => 'https_url', // Meeting Location/Link
        'UF_CRM_1731838581336' => 'number', // Budget
        'UF_CRM_1760707482053' => 'text', // Property Size
        'UF_CRM_A7_SHOP_TYPE' => [2471 => true, 2472 => true, 2473 => true, 2474 => true],
        'UF_CRM_A7_BOT_STATUS' => [2475 => true, 2476 => true, 2477 => true, 2478 => true, 2479 => true, 2480 => true, 2481 => true],
        'UF_CRM_A7_WA_OPT_OUT' => [2482 => true, 2483 => true],
        // C65 / C50: AI score (UF 2696) and why (UF 2697) for Claude F1.
        'UF_CRM_A7_AI_SCORE' => 'number',
        'UF_CRM_A7_AI_SCORE_WHY' => 'text',
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
    if ($rule === 'number') {
        if (is_string($value) && is_numeric(trim($value))) {
            $value = str_contains(trim($value), '.') ? (float)trim($value) : (int)trim($value);
        }
        if (!is_int($value) && !is_float($value)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        if (is_float($value) && (!is_finite($value) || $value < 0)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        if (is_int($value) && $value < 0) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        $writes[$code] = $value;
        continue;
    }
    if ($rule === 'https_url') {
        if (!is_string($value)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        $url = trim($value);
        if ($url === '' || strlen($url) > 2000 || !preg_match('#^https://[^\s<>\"\']+#i', $url)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad field value.'], 400);
        }
        $writes[$code] = a7_leadai_fields_safe($url, 2000);
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
        // C40: Offline 42 or Online 43. No todo_user_id, no meet_url.
        if (array_key_exists('todo_user_id', $in['booking']) || array_key_exists('meet_url', $in['booking'])) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
        }
        $mode = (int)($in['booking']['mode'] ?? 0);
        if ($meeting === null || !in_array($mode, [42, 43], true)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
        }
        $subject = (string)($in['booking']['todo_subject'] ?? 'Viewing/Meeting');
        if (!in_array($subject, ['Viewing/Meeting', 'Sales call'], true)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
        }
    } else {
        $mode = 42;
        $subject = (string)($in['booking']['todo_subject'] ?? '');
        if ($subject !== '' && !in_array($subject, ['Viewing/Meeting', 'Sales call'], true)) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Bad booking.'], 400);
        }
    }
    // C33: optional crm_todo_id moves/closes exactly that to-do; absent → today's newest-open rule.
    $crmTodoId = (int)($in['booking']['crm_todo_id'] ?? 0);
    $booking = [
        'event' => $event,
        'meeting' => $meeting,
        'mode' => $mode,
        'subject' => $subject,
        'crm_todo_id' => $crmTodoId > 0 ? $crmTodoId : null,
    ];
    if ($event !== 'cancelled') {
        $writes['UF_CRM_1731838813769'] = ['datetime' => $meeting];
        $writes['UF_CRM_1731838790184'] = $mode;
        $writes['UF_CRM_A7_BOT_STATUS'] = 2477;
    }
}

$plainTodo = null;
if (array_key_exists('todo', $in) && $in['todo'] !== null) {
    if (!is_array($in['todo']) || $booking !== null) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad to-do.'], 400);
    }
    $todoSubject = a7_leadai_fields_safe((string)($in['todo']['subject'] ?? ''), 120);
    $todoAt = a7_leadai_fields_datetime((string)($in['todo']['deadline'] ?? ''));
    if ($todoSubject === '' || $todoAt === null) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad to-do.'], 400);
    }
    $plainTodo = ['subject' => $todoSubject, 'deadline' => $todoAt];
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
$emailIn = '';
if (array_key_exists('email', $in) && $in['email'] !== null && $in['email'] !== '') {
    $emailIn = trim((string)$in['email']);
    if (!filter_var($emailIn, FILTER_VALIDATE_EMAIL)) {
        a7_leadai_fields_json(['ok' => false, 'error' => 'Bad email.'], 400);
    }
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
    // C39: 804/805 never replace Broker (2467), even without only_if_empty.
    if ($code === 'UF_CRM_LEAD_1737031634747' && in_array((int)$value, [804, 805], true)
        && (int)$item->get($code) === 2467) {
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

if ($emailIn !== '' && class_exists('CCrmFieldMulti')) {
    $hasEmail = \CCrmFieldMulti::GetList([], [
        'ENTITY_ID' => 'LEAD',
        'ELEMENT_ID' => $leadId,
        'TYPE_ID' => 'EMAIL',
    ])->Fetch();
    if ($hasEmail) {
        $skipped[] = 'email';
    } else {
        $fm = new \CCrmFieldMulti();
        $added = $fm->Add([
            'ENTITY_ID' => 'LEAD',
            'ELEMENT_ID' => $leadId,
            'TYPE_ID' => 'EMAIL',
            'VALUE_TYPE' => 'WORK',
            'VALUE' => $emailIn,
        ]);
        if (!$added) {
            a7_leadai_fields_json(['ok' => false, 'error' => 'Could not save the email.'], 502);
        }
        $updated[] = 'email';
    }
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

function a7_leadai_fields_subject_sql(string $subject): string
{
    if ($subject === '') {
        return "a.SUBJECT IN ('Viewing/Meeting','Sales call')";
    }
    $safe = str_replace(["\\", "'"], '', $subject);
    return "a.SUBJECT='" . $safe . "'";
}

function a7_leadai_fields_open_todo(int $leadId, string $subject = ''): int
{
    $sub = a7_leadai_fields_subject_sql($subject);
    $row = \Bitrix\Main\Application::getConnection()->query(
        "SELECT a.ID FROM b_crm_act a
         JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
         WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}
           AND a.PROVIDER_ID='CRM_TODO' AND {$sub} AND a.COMPLETED='N'
         ORDER BY a.ID DESC LIMIT 1"
    )->fetch();
    return is_array($row) ? (int)$row['ID'] : 0;
}

/** Open viewing or sales-call to-do by id on this lead, or 0 if missing/closed/wrong. */
function a7_leadai_fields_todo_if_open(int $leadId, int $todoId, string $subject = ''): int
{
    if ($todoId <= 0) {
        return 0;
    }
    $sub = a7_leadai_fields_subject_sql($subject);
    $row = \Bitrix\Main\Application::getConnection()->query(
        "SELECT a.ID FROM b_crm_act a
         JOIN b_crm_act_bind b ON b.ACTIVITY_ID=a.ID
         WHERE b.OWNER_TYPE_ID=1 AND b.OWNER_ID={$leadId}
           AND a.ID={$todoId}
           AND a.PROVIDER_ID='CRM_TODO' AND {$sub} AND a.COMPLETED='N'
         LIMIT 1"
    )->fetch();
    return is_array($row) ? (int)$row['ID'] : 0;
}

/** Prefer crm_todo_id when it is still our open to-do; else newest open of that subject. */
function a7_leadai_fields_resolve_todo(int $leadId, ?int $want, string $subject = ''): int
{
    if ($want !== null && $want > 0) {
        $hit = a7_leadai_fields_todo_if_open($leadId, $want, $subject);
        if ($hit > 0) {
            return $hit;
        }
    }
    return a7_leadai_fields_open_todo($leadId, $subject);
}

function a7_leadai_fields_todo_window(string $meeting): array
{
    $start = new \Bitrix\Main\Type\DateTime($meeting, 'Y-m-d H:i:s');
    $end = clone $start;
    $end->add('1 hour');
    return [$start->toString(), $end->toString()];
}

function a7_leadai_fields_plan_todo(int $leadId, int $responsible, string $meeting, ?int $wantTodo = null, string $subject = 'Viewing/Meeting'): int
{
    [$start, $end] = a7_leadai_fields_todo_window($meeting);
    $existing = a7_leadai_fields_resolve_todo($leadId, $wantTodo, $subject);
    $fields = [
        'DEADLINE' => $start,
        'START_TIME' => $start,
        'END_TIME' => $end,
        'RESPONSIBLE_ID' => $responsible,
        'COMPLETED' => 'N',
        'SUBJECT' => $subject,
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
        'SUBJECT' => $subject,
        'DESCRIPTION' => $subject,
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
    // C33: optional booking.crm_todo_id targets exactly that open to-do.
    $responsible = 2311;
    $wantTodo = isset($booking['crm_todo_id']) ? (int)$booking['crm_todo_id'] : null;
    $subject = (string)($booking['subject'] ?? 'Viewing/Meeting');
    if ($booking['event'] === 'cancelled') {
        $open = a7_leadai_fields_resolve_todo($leadId, $wantTodo, $subject);
        if ($open > 0) {
            $fields = ['COMPLETED' => 'Y'];
            $ok = \CCrmActivity::Update($open, $fields, false, false, ['REGISTER_SONET_EVENT' => false]);
            if (!$ok) {
                a7_leadai_fields_json(['ok' => false, 'error' => 'Could not close the viewing.'], 502);
            }
            $todoId = $open;
        }
    } else {
        $todoId = a7_leadai_fields_plan_todo(
            $leadId,
            $responsible,
            (string)$booking['meeting'],
            $wantTodo,
            $subject !== '' ? $subject : 'Viewing/Meeting'
        );
    }
}

if ($plainTodo !== null) {
    $todoId = a7_leadai_fields_plan_todo(
        $leadId,
        2311,
        (string)$plainTodo['deadline'],
        null,
        (string)$plainTodo['subject']
    );
}

a7_leadai_fields_json([
    'ok' => true,
    'lead_id' => $leadId,
    'updated' => $updated,
    'skipped' => $skipped,
    'lost' => $lostStatus,
    'todo_id' => $todoId,
]);
