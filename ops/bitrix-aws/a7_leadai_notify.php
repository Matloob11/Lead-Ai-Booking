<?php
/**
 * Lead AI alerts -> one Bitrix notification (bell + mobile push) for one agent.
 *
 * Called only by the WhatsApp backend (apps/leadai/assistant/alerts.py), never
 * by a browser. The backend's own Bitrix webhook has the crm, lists and user
 * scopes but not "im", so it cannot notify anybody itself; this tool does it
 * with CIMNotify, the same call the A7 lead reminder uses.
 *
 * Signed with the secret the CRM campaign popups already share with the
 * backend (/bitrix/php_interface/a7_lead_wa.config.php 'secret', which is the
 * backend's CRM_LEAD_WA_SECRET). The signed text starts with "leadai-notify."
 * so a signature made for any other A7 route can never be replayed here.
 * The signature is checked BEFORE Bitrix is loaded, so an unsigned request
 * costs almost nothing.
 *
 * Request: POST, JSON body
 *   {"to_user_id": 2311, "title": "...", "message": "...", "push": "...",
 *    "tag": "LEADAI|...", "url": "/crm/lead/details/123/"}
 * Headers: X-Leadai-Ts (unix seconds, within 300 s of now) and
 *          X-Leadai-Sign = hex HMAC-SHA256(secret, "leadai-notify." . ts . "." . body)
 * Answers JSON {"ok": true, "id": <notification id>[, "duplicate": true]}
 * or {"ok": false, "error": "..."}. A tag that was already notified is not
 * notified again, so a retry never buzzes the agent's phone twice.
 *
 * Deploy to: /bitrix/tools/a7_leadai_notify.php
 */

function a7_leadai_notify_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

/** Text from the backend, made safe for a notification: no BB-code or tags of its own, bounded length. */
function a7_leadai_notify_text($value, int $limit): string
{
    $text = trim(str_replace(["\r\n", "\r"], "\n", (string)$value));
    // Customer names and messages travel in here; brackets would let them
    // open a [URL] or other BB-code inside the agent's notification, and
    // Bitrix turns <a href>, <b> and the like into BB-code itself.
    $text = strtr($text, ['[' => '(', ']' => ')', '<' => '‹', '>' => '›']);
    if (function_exists('mb_substr')) {
        return mb_substr($text, 0, $limit);
    }
    return substr($text, 0, $limit);
}

// 1. Method, size and signature, before Bitrix is loaded --------------------
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    a7_leadai_notify_json(['ok' => false, 'error' => 'POST only.'], 405);
}
$cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
$cfg = is_readable($cfgPath) ? include $cfgPath : null;
$secret = trim((string)((is_array($cfg) ? $cfg : [])['secret'] ?? ''));
if ($secret === '') {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Not configured.'], 503);
}
$raw = (string)file_get_contents('php://input');
if ($raw === '' || strlen($raw) > 8192) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Bad body.'], 400);
}
$ts = (string)($_SERVER['HTTP_X_LEADAI_TS'] ?? '');
$sign = strtolower((string)($_SERVER['HTTP_X_LEADAI_SIGN'] ?? ''));
if (!ctype_digit($ts) || abs(time() - (int)$ts) > 300 || !preg_match('/^[0-9a-f]{64}$/', $sign)) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Unauthorized.'], 401);
}
if (!hash_equals(hash_hmac('sha256', 'leadai-notify.' . $ts . '.' . $raw, $secret), $sign)) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Unauthorized.'], 401);
}
$in = json_decode($raw, true);
if (!is_array($in)) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Body is not JSON.'], 400);
}

// 2. Bitrix ----------------------------------------------------------------------
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

$to = (int)($in['to_user_id'] ?? 0);
if ($to <= 0) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'No user.'], 400);
}
$user = CUser::GetByID($to)->Fetch();
if (!is_array($user) || ($user['ACTIVE'] ?? 'N') !== 'Y') {
    a7_leadai_notify_json(['ok' => false, 'error' => 'No such active user.'], 404);
}

$title = a7_leadai_notify_text($in['title'] ?? '', 200);
$plain = a7_leadai_notify_text($in['message'] ?? '', 1000);
$push = a7_leadai_notify_text($in['push'] ?? $plain, 200);
if ($plain === '') {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Empty message.'], 400);
}
$tag = substr((string)preg_replace('/[^A-Za-z0-9_|:.\-]/', '', (string)($in['tag'] ?? '')), 0, 100);

global $DB;
if ($tag !== '' && is_object($DB)) {
    $seen = $DB->Query("SELECT ID FROM b_im_message WHERE NOTIFY_TAG = '" . $DB->ForSql($tag) . "' LIMIT 1")->Fetch();
    if (is_array($seen)) {
        a7_leadai_notify_json(['ok' => true, 'id' => (int)$seen['ID'], 'duplicate' => true]);
    }
}

// The body is HTML-escaped, as a7_lead_reminder_notify.php does: Bitrix turns
// HTML in NOTIFY_MESSAGE into BB-code and decodes &#91; &#93; into brackets
// when it shows it. The title is escaped by Bitrix itself and push is plain
// text, so escaping them here would show "&amp;". Only a link inside this
// portal, added by this tool itself after the escaping.
$message = htmlspecialcharsbx($plain);
$url = (string)($in['url'] ?? '');
if ($url !== '' && preg_match('#^/(crm|marketplace)/[A-Za-z0-9_/\-]+/?$#', $url)) {
    $message .= "\n[URL=" . $url . ']Open[/URL]';
}

if (!\Bitrix\Main\Loader::includeModule('im') || !class_exists('CIMNotify')) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'IM module unavailable.'], 503);
}

$fields = [
    'TO_USER_ID' => $to,
    'FROM_USER_ID' => 0,
    'NOTIFY_TYPE' => defined('IM_NOTIFY_SYSTEM') ? IM_NOTIFY_SYSTEM : 4,
    'NOTIFY_MODULE' => 'im',
    'NOTIFY_EVENT' => 'default',
    'NOTIFY_TITLE' => $title,
    'NOTIFY_MESSAGE' => $message,
    // E-mail and push show text as it is, so no BB-code there.
    'NOTIFY_MESSAGE_OUT' => $plain,
    'PUSH_MESSAGE' => $push,
];
if ($tag !== '') {
    $fields['NOTIFY_TAG'] = $tag;
}

$id = CIMNotify::Add($fields);
if (empty($id)) {
    a7_leadai_notify_json(['ok' => false, 'error' => 'Bitrix did not accept the notification.'], 502);
}
a7_leadai_notify_json(['ok' => true, 'id' => (int)$id]);
