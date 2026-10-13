<?php
/**
 * Renewals (deal category 9) WhatsApp campaign.
 *
 * The CRM page has a Bitrix session, not a Django cookie. This tool reads
 * the selected deals with the current user's CRM permissions, then HMAC-signs
 * the JSON body for the Official inbox. The secret is the same file the
 * Leads button already uses.
 *
 * Deploy to: /bitrix/tools/a7_renewals_wa.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=utf-8');

const A7_RENEWALS_CATEGORY = 9;
const A7_RENEWALS_MAX_DEALS = 500;
// GetByID drops every UF field, so the list can show a phone the campaign never sees.
// Each side uses its own primary field, then that side's secondary. Never the other side.
const A7_RENEWALS_TENANT_PHONES = ['UF_CRM_1734263575786', 'UF_CRM_1735379566357'];
const A7_RENEWALS_OWNER_PHONES = ['UF_CRM_1735377605713', 'UF_CRM_1735379548586'];
const A7_RENEWALS_TENANT_NAMES = ['UF_CRM_1734263559057', 'UF_CRM_1782041950987'];
const A7_RENEWALS_OWNER_NAMES = ['UF_CRM_1734263542611'];

function a7_renewals_wa_playbook($raw): string
{
    $value = strtolower(trim((string)$raw));
    return in_array($value, ['general', 'ic_shops'], true) ? $value : 'general';
}

function a7_renewals_wa_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function a7_renewals_wa_config(): array
{
    $path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
    $cfg = is_readable($path) ? include $path : null;
    return is_array($cfg) ? $cfg : [];
}

function a7_renewals_wa_details(string $name, string $phone): array
{
    return [
        'name' => trim($name),
        'phone' => trim($phone),
        'source' => '',
        'stage' => '',
        'community' => '',
        'sub_community' => '',
        'bedrooms' => '',
        'client_type' => '',
        'deal_amount' => '',
        'property_reference' => '',
    ];
}

function a7_renewals_wa_scalar($value): string
{
    if (is_array($value)) {
        foreach ($value as $part) {
            $text = a7_renewals_wa_scalar($part);
            if ($text !== '') {
                return $text;
            }
        }
        return '';
    }
    if ($value === null) {
        return '';
    }
    return trim((string)$value);
}

function a7_renewals_wa_ids(): array
{
    $raw = $_POST['deal_ids'] ?? $_REQUEST['deal_ids'] ?? [];
    if (is_string($raw)) {
        $decoded = json_decode($raw, true);
        $raw = is_array($decoded) ? $decoded : preg_split('/[,\s]+/', $raw);
    }
    if (!is_array($raw)) {
        return [];
    }
    $ids = [];
    foreach ($raw as $id) {
        $n = (int)$id;
        if ($n > 0 && !in_array($n, $ids, true)) {
            $ids[] = $n;
        }
    }
    return $ids;
}

function a7_renewals_wa_first(array $row, array $fields): string
{
    foreach ($fields as $field) {
        $text = a7_renewals_wa_scalar($row[$field] ?? '');
        if ($text !== '') {
            return $text;
        }
    }
    return '';
}

function a7_renewals_wa_deals(array $ids): array
{
    $allowed = [];
    $unreadable = 0;
    if (!class_exists('CCrmDeal')) {
        return [[], count($ids)];
    }
    foreach ($ids as $id) {
        $id = (int)$id;
        if ($id <= 0 || !CCrmDeal::CheckReadPermission($id)) {
            $unreadable++;
            continue;
        }
        $allowed[] = $id;
    }
    if (!$allowed) {
        return [[], $unreadable];
    }
    $select = array_merge(
        ['ID', 'TITLE', 'CATEGORY_ID'],
        A7_RENEWALS_TENANT_PHONES,
        A7_RENEWALS_OWNER_PHONES,
        A7_RENEWALS_TENANT_NAMES,
        A7_RENEWALS_OWNER_NAMES
    );
    $found = [];
    $res = CCrmDeal::GetListEx(
        ['ID' => 'ASC'],
        ['@ID' => $allowed, 'CHECK_PERMISSIONS' => 'N', '=CATEGORY_ID' => A7_RENEWALS_CATEGORY],
        false,
        false,
        $select
    );
    while ($res && ($row = $res->Fetch())) {
        $id = (int)($row['ID'] ?? 0);
        if ($id <= 0) {
            continue;
        }
        $ownerName = a7_renewals_wa_first($row, A7_RENEWALS_OWNER_NAMES);
        if ($ownerName === '') {
            $ownerName = a7_renewals_wa_scalar($row['TITLE'] ?? '');
        }
        $tenantName = [];
        foreach (A7_RENEWALS_TENANT_NAMES as $nameField) {
            $part = a7_renewals_wa_scalar($row[$nameField] ?? '');
            if ($part !== '') {
                $tenantName[] = $part;
            }
        }
        $tenantPhone = a7_renewals_wa_first($row, A7_RENEWALS_TENANT_PHONES);
        $ownerPhone = a7_renewals_wa_first($row, A7_RENEWALS_OWNER_PHONES);
        $tenantLabel = trim(implode(' ', $tenantName));
        $found[$id] = [
            'id' => $id,
            'tenant_phone' => $tenantPhone,
            'tenant_name' => $tenantLabel,
            'owner_phone' => $ownerPhone,
            'owner_name' => $ownerName,
            'title' => a7_renewals_wa_scalar($row['TITLE'] ?? ''),
            'tenant_details' => a7_renewals_wa_details($tenantLabel, $tenantPhone),
            'owner_details' => a7_renewals_wa_details($ownerName, $ownerPhone),
        ];
    }
    $deals = [];
    foreach ($allowed as $id) {
        if (isset($found[$id])) {
            $deals[] = $found[$id];
            continue;
        }
        $unreadable++;
    }
    return [$deals, $unreadable];
}

function a7_renewals_wa_http_socket(string $url, string $body, string $ts, string $sig): array
{
    $p = parse_url($url);
    $host = (string)($p['host'] ?? '');
    $path = (string)($p['path'] ?? '/');
    if (!empty($p['query'])) {
        $path .= '?' . $p['query'];
    }
    $https = (($p['scheme'] ?? 'https') === 'https');
    $port = (int)($p['port'] ?? ($https ? 443 : 80));
    if ($host === '') {
        return ['raw' => '', 'http' => 0, 'error' => 'WhatsApp inbox URL is invalid.'];
    }
    $target = ($https ? 'ssl://' : 'tcp://') . $host . ':' . $port;
    $ctx = stream_context_create([
        'ssl' => [
            'verify_peer' => true,
            'verify_peer_name' => true,
            'peer_name' => $host,
        ],
    ]);
    $fp = @stream_socket_client($target, $errno, $errstr, 15, STREAM_CLIENT_CONNECT, $ctx);
    if ($fp === false) {
        return [
            'raw' => '',
            'http' => 0,
            'error' => 'WhatsApp inbox did not answer' . ($errstr !== '' ? ' (' . $errstr . ')' : '') . '.',
        ];
    }
    stream_set_timeout($fp, 60);
    $req = "POST {$path} HTTP/1.1\r\n"
        . "Host: {$host}\r\n"
        . "Content-Type: application/json\r\n"
        . "Content-Length: " . strlen($body) . "\r\n"
        . "X-Crm-Ts: {$ts}\r\n"
        . "X-Crm-Sign: {$sig}\r\n"
        . "Connection: close\r\n\r\n"
        . $body;
    fwrite($fp, $req);
    $resp = stream_get_contents($fp);
    fclose($fp);
    if (!is_string($resp) || $resp === '') {
        return ['raw' => '', 'http' => 0, 'error' => 'WhatsApp inbox did not answer.'];
    }
    $http = 0;
    if (preg_match('/^HTTP\/\S+\s+(\d{3})/', $resp, $m)) {
        $http = (int)$m[1];
    }
    $split = preg_split("/\r\n\r\n/", $resp, 2);
    $raw = isset($split[1]) ? $split[1] : '';
    return ['raw' => $raw, 'http' => $http, 'error' => ''];
}

function a7_renewals_wa_http(string $url, string $body, string $ts, string $sig): array
{
    $headerLines = [
        'Content-Type: application/json',
        'Content-Length: ' . (string)strlen($body),
        'X-Crm-Ts: ' . $ts,
        'X-Crm-Sign: ' . $sig,
        'Connection: close',
    ];
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        if ($ch !== false) {
            curl_setopt_array($ch, [
                CURLOPT_POST => true,
                CURLOPT_HTTPHEADER => $headerLines,
                CURLOPT_POSTFIELDS => $body,
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_CONNECTTIMEOUT => 10,
                CURLOPT_TIMEOUT => 60,
            ]);
            $raw = curl_exec($ch);
            $http = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
            $err = curl_error($ch);
            curl_close($ch);
            return ['raw' => $raw === false ? '' : (string)$raw, 'http' => $http, 'error' => $err];
        }
    }
    $ctx = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => implode("\r\n", $headerLines),
            'content' => $body,
            'timeout' => 60,
            'ignore_errors' => true,
        ],
        'ssl' => [
            'verify_peer' => true,
            'verify_peer_name' => true,
        ],
    ]);
    $raw = @file_get_contents($url, false, $ctx);
    $http = 0;
    if (!empty($http_response_header[0]) && preg_match('/\s(\d{3})\s/', $http_response_header[0], $m)) {
        $http = (int)$m[1];
    }
    if ($raw === false) {
        return a7_renewals_wa_http_socket($url, $body, $ts, $sig);
    }
    return ['raw' => (string)$raw, 'http' => $http, 'error' => ''];
}

function a7_renewals_wa_inbox(string $path, array $payload, array $cfg): array
{
    $secret = trim((string)($cfg['secret'] ?? ''));
    $base = rtrim((string)($cfg['inbox_url'] ?? ''), '/');
    if ($secret === '' || $base === '') {
        a7_renewals_wa_json(['ok' => false, 'error' => 'WhatsApp send is not configured.'], 503);
    }
    $body = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if (!is_string($body)) {
        a7_renewals_wa_json(['ok' => false, 'error' => 'Could not encode the request.'], 500);
    }
    $ts = (string)time();
    $sig = hash_hmac('sha256', $ts . '.' . $body, $secret);
    $http = a7_renewals_wa_http($base . $path, $body, $ts, $sig);
    if ($http['raw'] === '' && (int)$http['http'] === 0) {
        a7_renewals_wa_json([
            'ok' => false,
            'error' => $http['error'] !== '' ? $http['error'] : 'WhatsApp inbox did not answer.',
        ], 502);
    }
    $decoded = json_decode($http['raw'], true);
    if (!is_array($decoded)) {
        $decoded = [
            'detail' => $http['error'] !== '' ? $http['error'] : 'Unexpected inbox reply.',
        ];
    }
    return ['http' => (int)$http['http'], 'data' => $decoded];
}

function a7_renewals_wa_input(): array
{
    $raw = (string)($_POST['payload'] ?? '');
    if ($raw === '') {
        $raw = (string)file_get_contents('php://input');
    }
    $input = $raw !== '' ? json_decode($raw, true) : null;
    return is_array($input) ? $input : [];
}

if (defined('A7_RENEWALS_WA_LIBRARY') && A7_RENEWALS_WA_LIBRARY) {
    return;
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_renewals_wa_json(['ok' => false, 'error' => 'Sign in to Bitrix first.'], 401);
}

$sessid = (string)($_REQUEST['sessid'] ?? '');
if ($sessid === '' || !check_bitrix_sessid()) {
    a7_renewals_wa_json(['ok' => false, 'error' => 'Refresh the page and try again.'], 403);
}

if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_renewals_wa_json(['ok' => false, 'error' => 'CRM module is not available.'], 500);
}

$cfg = a7_renewals_wa_config();
$action = (string)($_REQUEST['action'] ?? '');
$bitrixUserId = (string)$USER->GetID();

// A template with an image, video or document header: a7_renewals_wa.js
// uploads the file through a7_lead_wa.php (action "header-media"), which
// streams it to the inbox, and sends back the token it got for each side.

$ids = a7_renewals_wa_ids();
if (!$ids && $action === 'send') {
    $input = a7_renewals_wa_input();
    $posted = $input['deal_ids'] ?? [];
    if (is_array($posted)) {
        foreach ($posted as $id) {
            $n = (int)$id;
            if ($n > 0 && !in_array($n, $ids, true)) {
                $ids[] = $n;
            }
        }
    }
}
if (!$ids) {
    a7_renewals_wa_json(['ok' => false, 'error' => 'Select one or more deals first.'], 400);
}
if (count($ids) > A7_RENEWALS_MAX_DEALS) {
    a7_renewals_wa_json(['ok' => false, 'error' => 'Select at most 500 deals.'], 400);
}
[$deals, $unreadable] = a7_renewals_wa_deals($ids);
if (!$deals) {
    a7_renewals_wa_json([
        'ok' => false,
        'error' => 'You cannot read those deals, or they are not Renewals deals.',
    ], 403);
}

if ($action === 'context') {
    $reply = a7_renewals_wa_inbox(
        '/api/campaigns/crm-renewals/context/',
        ['bitrix_user_id' => $bitrixUserId, 'deals' => $deals],
        $cfg
    );
    if ($reply['http'] < 200 || $reply['http'] >= 300) {
        $detail = (string)($reply['data']['detail'] ?? $reply['data']['error'] ?? 'Could not load templates.');
        a7_renewals_wa_json(['ok' => false, 'error' => $detail], $reply['http'] >= 400 ? $reply['http'] : 502);
    }
    $out = ['ok' => true, 'unreadable' => $unreadable] + $reply['data'];
    a7_renewals_wa_json($out);
}

if ($action === 'send') {
    $input = a7_renewals_wa_input();
    $reply = a7_renewals_wa_inbox(
        '/api/campaigns/crm-renewals/send/',
        [
            'bitrix_user_id' => $bitrixUserId,
            'deals' => $deals,
            'number_id' => (int)($input['number_id'] ?? 0),
            'tenant_template_id' => (int)($input['tenant_template_id'] ?? 0),
            'owner_template_id' => (int)($input['owner_template_id'] ?? 0),
            'tenant_variables' => is_array($input['tenant_variables'] ?? null) ? $input['tenant_variables'] : [],
            'owner_variables' => is_array($input['owner_variables'] ?? null) ? $input['owner_variables'] : [],
            'tenant_variable_fields' => is_array($input['tenant_variable_fields'] ?? null) ? $input['tenant_variable_fields'] : [],
            'owner_variable_fields' => is_array($input['owner_variable_fields'] ?? null) ? $input['owner_variable_fields'] : [],
            'tenant_header_variables' => is_array($input['tenant_header_variables'] ?? null) ? $input['tenant_header_variables'] : [],
            'owner_header_variables' => is_array($input['owner_header_variables'] ?? null) ? $input['owner_header_variables'] : [],
            'tenant_button_variables' => is_array($input['tenant_button_variables'] ?? null) ? $input['tenant_button_variables'] : [],
            'owner_button_variables' => is_array($input['owner_button_variables'] ?? null) ? $input['owner_button_variables'] : [],
            'tenant_header_media_token' => (string)($input['tenant_header_media_token'] ?? ''),
            'owner_header_media_token' => (string)($input['owner_header_media_token'] ?? ''),
            // The popup's "Lead AI" box: both sides' chats go to the Lead AI screen.
            // Script is only forwarded for that box, and only as one of the two names.
            'lead_ai' => !empty($input['lead_ai']),
            'lead_ai_playbook' => !empty($input['lead_ai'])
                ? a7_renewals_wa_playbook($input['lead_ai_playbook'] ?? '')
                : '',
        ],
        $cfg
    );
    if ($reply['http'] < 200 || $reply['http'] >= 300) {
        $detail = (string)($reply['data']['detail'] ?? $reply['data']['error'] ?? 'WhatsApp send failed.');
        a7_renewals_wa_json(['ok' => false, 'error' => $detail], $reply['http'] >= 400 ? $reply['http'] : 502);
    }
    $out = ['ok' => true, 'unreadable' => $unreadable] + $reply['data'];
    a7_renewals_wa_json($out, 201);
}

a7_renewals_wa_json(['ok' => false, 'error' => 'Unknown action.'], 400);
