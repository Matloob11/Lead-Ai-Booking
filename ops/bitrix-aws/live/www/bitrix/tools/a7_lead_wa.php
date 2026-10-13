<?php
/**
 * Leads-list WhatsApp send.
 *
 * The CRM page has a Bitrix session, not a Django cookie. This tool reads
 * selected leads with the current user's CRM permissions, then HMAC-signs
 * the JSON body for the Official inbox.
 *
 * Deploy to: /bitrix/tools/a7_lead_wa.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=utf-8');

function a7_lead_wa_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function a7_lead_wa_config(): array
{
    $path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
    if (!is_readable($path)) {
        $path = __DIR__ . '/a7_lead_wa.config.php';
    }
    $cfg = is_readable($path) ? include $path : null;
    return is_array($cfg) ? $cfg : [];
}

function a7_lead_wa_digits(string $raw): string
{
    return preg_replace('/\D+/', '', $raw) ?? '';
}

function a7_lead_wa_phone(int $leadId): string
{
    if (!class_exists('CCrmFieldMulti')) {
        return '';
    }
    $db = CCrmFieldMulti::GetList(
        ['ID' => 'ASC'],
        ['ENTITY_ID' => 'LEAD', 'ELEMENT_ID' => $leadId, 'TYPE_ID' => 'PHONE']
    );
    if (!$db) {
        return '';
    }
    while ($row = $db->Fetch()) {
        $digits = a7_lead_wa_digits((string)($row['VALUE'] ?? ''));
        if (strlen($digits) >= 8) {
            return $digits;
        }
    }
    return '';
}

function a7_lead_wa_display(array $row): string
{
    $title = trim((string)($row['name'] ?? $row['title'] ?? ''));
    if ($title !== '' && !preg_match('/^(untitled|unentitled)$/i', $title)) {
        return $title;
    }
    $joined = trim(
        trim((string)($row['first_name'] ?? '')) . ' ' . trim((string)($row['last_name'] ?? ''))
    );
    return $joined !== '' ? $joined : 'Untitled';
}

function a7_lead_wa_requested_ids(): array
{
    $raw = $_POST['lead_ids'] ?? $_REQUEST['lead_ids'] ?? [];
    if (is_string($raw)) {
        $decoded = json_decode($raw, true);
        $raw = is_array($decoded) ? $decoded : preg_split('/[,\s]+/', $raw);
    }
    if (!is_array($raw)) {
        return [];
    }
    $out = [];
    foreach ($raw as $id) {
        $n = (int)$id;
        if ($n > 0 && !in_array($n, $out, true)) {
            $out[] = $n;
        }
    }
    return $out;
}

function a7_lead_wa_summaries(array $ids, string $entity = 'lead'): array
{
    $rows = [];
    foreach ($ids as $id) {
        $row = a7_lead_wa_resolve_row($id, $entity);
        if ($row === null) {
            continue;
        }
        $phone = (string)($row['phone'] ?? '');
        $rows[] = [
            'id' => $row['id'],
            'name' => a7_lead_wa_display($row),
            'phone_ok' => strlen($phone) >= 8,
            'phone_tail' => strlen($phone) >= 4 ? substr($phone, -4) : '',
        ];
    }
    return $rows;
}

function a7_lead_wa_row(int $leadId): ?array
{
    if ($leadId <= 0 || !class_exists('CCrmLead')) {
        return null;
    }
    if (!CCrmLead::CheckReadPermission($leadId)) {
        return null;
    }
    $lead = CCrmLead::GetByID($leadId, false);
    if (!is_array($lead)) {
        return null;
    }
    return [
        'id' => $leadId,
        'phone' => a7_lead_wa_phone($leadId),
        'name' => (string)($lead['TITLE'] ?? ''),
        'title' => (string)($lead['TITLE'] ?? ''),
        'first_name' => (string)($lead['NAME'] ?? ''),
        'last_name' => (string)($lead['LAST_NAME'] ?? ''),
    ];
}

function a7_lead_wa_entity(): string
{
    $raw = (string)($_REQUEST['entity'] ?? '');
    if ($raw === '') {
        $payload = (string)($_POST['payload'] ?? '');
        if ($payload !== '') {
            $decoded = json_decode($payload, true);
            if (is_array($decoded)) {
                $raw = (string)($decoded['entity'] ?? '');
            }
        }
    }
    $raw = strtolower(trim($raw));
    return in_array($raw, ['owner_data', '1042', 'dynamic_1042'], true) ? 'owner_data' : 'lead';
}

function a7_lead_wa_owner_phone_fields(): array
{
    return [
        'ufCrm5_1768317611513',
        'ufCrm5_1769416533028',
        'ufCrm5_1768314841508',
        'ufCrm5_1768317656051',
        'ufCrm5_1777563197150',
        'ufCrm5_1779805546251',
        'UF_CRM_5_1768317611513',
        'UF_CRM_5_1769416533028',
        'UF_CRM_5_1768314841508',
        'UF_CRM_5_1768317656051',
        'UF_CRM_5_1777563197150',
        'UF_CRM_5_1779805546251',
    ];
}

function a7_lead_wa_first_phone($value): string
{
    $values = is_array($value) ? $value : [$value];
    foreach ($values as $candidate) {
        if ($candidate === null || $candidate === '' || $candidate === '0') {
            continue;
        }
        $digits = a7_lead_wa_digits((string)$candidate);
        if (strlen($digits) >= 8) {
            return $digits;
        }
    }
    return '';
}

function a7_lead_wa_contact_phone(int $contactId): string
{
    if ($contactId <= 0 || !class_exists('CCrmFieldMulti')) {
        return '';
    }
    $db = CCrmFieldMulti::GetList(
        ['ID' => 'ASC'],
        ['ENTITY_ID' => 'CONTACT', 'ELEMENT_ID' => $contactId, 'TYPE_ID' => 'PHONE']
    );
    if (!$db) {
        return '';
    }
    while ($row = $db->Fetch()) {
        $digits = a7_lead_wa_digits((string)($row['VALUE'] ?? ''));
        if (strlen($digits) >= 8) {
            return $digits;
        }
    }
    return '';
}

function a7_lead_wa_can_read_owner($item): bool
{
    if (!is_object($item)) {
        return false;
    }
    $up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions();
    if (method_exists($up, 'canReadItem')) {
        return (bool)$up->canReadItem($item);
    }
    if (method_exists($up, 'item')) {
        $itemPerms = $up->item();
        if (is_object($itemPerms) && method_exists($itemPerms, 'canRead')) {
            return (bool)$itemPerms->canRead($item->getEntityTypeId(), $item->getId());
        }
    }
    return false;
}

function a7_lead_wa_owner_phone($item, array $data): string
{
    foreach (a7_lead_wa_owner_phone_fields() as $field) {
        $value = $data[$field] ?? null;
        $phone = a7_lead_wa_first_phone($value);
        if ($phone !== '') {
            return $phone;
        }
        if (is_object($item) && method_exists($item, 'get')) {
            try {
                $phone = a7_lead_wa_first_phone($item->get($field));
            } catch (Throwable $e) {
                $phone = '';
            }
            if ($phone !== '') {
                return $phone;
            }
        }
    }
    $contactId = 0;
    if (is_object($item) && method_exists($item, 'getContactId')) {
        $contactId = (int)$item->getContactId();
    } elseif (!empty($data['CONTACT_ID'])) {
        $contactId = (int)$data['CONTACT_ID'];
    } elseif (!empty($data['contactId'])) {
        $contactId = (int)$data['contactId'];
    }
    return a7_lead_wa_contact_phone($contactId);
}

function a7_lead_wa_owner_row(int $itemId): ?array
{
    if ($itemId <= 0) {
        return null;
    }
    $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
    if (!$factory) {
        return null;
    }
    $item = $factory->getItem($itemId);
    if (!$item || !a7_lead_wa_can_read_owner($item)) {
        return null;
    }
    $data = [];
    if (method_exists($item, 'getCompatibleData')) {
        $compat = $item->getCompatibleData();
        if (is_array($compat)) {
            $data = $compat;
        }
    }
    if (!$data && method_exists($item, 'getData')) {
        $got = $item->getData();
        if (is_array($got)) {
            $data = $got;
        }
    }
    $title = '';
    if (method_exists($item, 'getTitle')) {
        $title = trim((string)$item->getTitle());
    }
    if ($title === '') {
        $title = trim((string)($data['TITLE'] ?? $data['title'] ?? ''));
    }
    return [
        'id' => $itemId,
        'owner_data_id' => $itemId,
        'phone' => a7_lead_wa_owner_phone($item, $data),
        'name' => $title,
        'title' => $title,
        'first_name' => '',
        'last_name' => '',
    ];
}

function a7_lead_wa_resolve_row(int $id, string $entity): ?array
{
    return $entity === 'owner_data' ? a7_lead_wa_owner_row($id) : a7_lead_wa_row($id);
}

function a7_lead_wa_http(string $url, string $body, string $ts, string $sig): array
{
    $headerLines = [
        'Content-Type: application/json',
        'Content-Length: ' . (string)strlen($body),
        'X-Crm-Ts: ' . $ts,
        'X-Crm-Sign: ' . $sig,
        'Connection: close',
    ];

    // Apache PHP on this host has curl disabled (same as Voiso). Streams first.
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
    $err = '';
    if ($raw === false) {
        return a7_lead_wa_http_socket($url, $body, $ts, $sig);
    }
    return ['raw' => (string)$raw, 'http' => $http, 'error' => $err];
}

function a7_lead_wa_http_socket(string $url, string $body, string $ts, string $sig): array
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

function a7_lead_wa_inbox(string $path, array $payload, array $cfg): array
{
    $secret = trim((string)($cfg['secret'] ?? ''));
    $base = rtrim((string)($cfg['inbox_url'] ?? ''), '/');
    if ($secret === '' || $base === '') {
        a7_lead_wa_json(['ok' => false, 'error' => 'WhatsApp send is not configured.'], 503);
    }
    $body = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if (!is_string($body)) {
        a7_lead_wa_json(['ok' => false, 'error' => 'Could not encode the request.'], 500);
    }
    $ts = (string)time();
    $sig = hash_hmac('sha256', $ts . '.' . $body, $secret);
    $http = a7_lead_wa_http($base . $path, $body, $ts, $sig);
    if ($http['raw'] === '' && (int)$http['http'] === 0) {
        a7_lead_wa_json([
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

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_lead_wa_json(['ok' => false, 'error' => 'Sign in to Bitrix first.'], 401);
}

$sessid = (string)($_REQUEST['sessid'] ?? '');
if ($sessid === '' || !check_bitrix_sessid()) {
    a7_lead_wa_json(['ok' => false, 'error' => 'Refresh the page and try again.'], 403);
}

if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_lead_wa_json(['ok' => false, 'error' => 'CRM module is not available.'], 500);
}

$cfg = a7_lead_wa_config();
$action = (string)($_REQUEST['action'] ?? '');
$bitrixUserId = (string)$USER->GetID();

if ($action === 'context') {
    $entity = a7_lead_wa_entity();
    $leadIds = a7_lead_wa_requested_ids();
    $reply = a7_lead_wa_inbox(
        '/api/campaigns/crm-leads/context/',
        ['bitrix_user_id' => $bitrixUserId],
        $cfg
    );
    if ($reply['http'] < 200 || $reply['http'] >= 300) {
        $detail = (string)($reply['data']['detail'] ?? 'Could not load templates.');
        a7_lead_wa_json(['ok' => false, 'error' => $detail], $reply['http'] >= 400 ? $reply['http'] : 502);
    }
    $out = ['ok' => true] + $reply['data'];
    $out['entity'] = $entity;
    $out['leads'] = a7_lead_wa_summaries($leadIds, $entity);
    a7_lead_wa_json($out);
}

if ($action === 'send') {
    $raw = (string)($_POST['payload'] ?? '');
    if ($raw === '') {
        $raw = (string)file_get_contents('php://input');
    }
    $input = $raw !== '' ? json_decode($raw, true) : null;
    if (!is_array($input)) {
        $input = $_POST;
    }
    $ids = $input['lead_ids'] ?? [];
    if (!is_array($ids)) {
        $ids = [];
    }
    $cleanIds = [];
    foreach ($ids as $id) {
        $n = (int)$id;
        if ($n > 0 && !in_array($n, $cleanIds, true)) {
            $cleanIds[] = $n;
        }
    }
    $entity = a7_lead_wa_entity();
    if ($entity === 'lead' && isset($input['entity'])) {
        $hint = strtolower(trim((string)$input['entity']));
        if (in_array($hint, ['owner_data', '1042', 'dynamic_1042'], true)) {
            $entity = 'owner_data';
        }
    }
    $noun = $entity === 'owner_data' ? 'Owner Data cards' : 'leads';
    if (!$cleanIds) {
        a7_lead_wa_json(['ok' => false, 'error' => 'Select one or more ' . $noun . ' first.'], 400);
    }
    if (count($cleanIds) > 500) {
        a7_lead_wa_json(['ok' => false, 'error' => 'Select at most 500 ' . $noun . '.'], 400);
    }

    $leads = [];
    $unreadable = 0;
    foreach ($cleanIds as $id) {
        $row = a7_lead_wa_resolve_row($id, $entity);
        if ($row === null) {
            $unreadable++;
            continue;
        }
        $leads[] = $row;
    }
    if (!$leads) {
        a7_lead_wa_json([
            'ok' => false,
            'error' => $entity === 'owner_data'
                ? 'You cannot read those Owner Data cards, or they were not found.'
                : 'You cannot read those leads, or they were not found.',
        ], 403);
    }

    $payload = [
        'bitrix_user_id' => $bitrixUserId,
        'entity' => $entity,
        'template_id' => (int)($input['template_id'] ?? 0),
        'number_id' => (int)($input['number_id'] ?? 0),
        'leads' => $leads,
        'variables' => is_array($input['variables'] ?? null) ? $input['variables'] : [],
        'header_variables' => is_array($input['header_variables'] ?? null) ? $input['header_variables'] : [],
        'button_variables' => is_array($input['button_variables'] ?? null) ? $input['button_variables'] : [],
    ];
    $reply = a7_lead_wa_inbox('/api/campaigns/crm-leads/send/', $payload, $cfg);
    if ($reply['http'] < 200 || $reply['http'] >= 300) {
        $detail = (string)($reply['data']['detail'] ?? 'WhatsApp send failed.');
        a7_lead_wa_json(['ok' => false, 'error' => $detail], $reply['http'] >= 400 ? $reply['http'] : 502);
    }
    $out = ['ok' => true, 'unreadable' => $unreadable] + $reply['data'];
    a7_lead_wa_json($out, 201);
}

a7_lead_wa_json(['ok' => false, 'error' => 'Unknown action.'], 400);
