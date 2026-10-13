<?php
/**
 * Leads-list WhatsApp send — also Owner Data / Availability cards, Deals
 * (every pipeline except Renewals, which has a7_renewals_wa.php) and Contacts.
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
            'details' => is_array($row['details'] ?? null)
                ? $row['details']
                : a7_lead_wa_detail_pack(a7_lead_wa_display($row), $phone),
        ];
    }
    return $rows;
}

function a7_lead_wa_detail_pack(string $name, string $phone, array $more = []): array
{
    $pack = [
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
    foreach ($more as $key => $value) {
        if (array_key_exists($key, $pack)) {
            $pack[$key] = trim((string)$value);
        }
    }
    return $pack;
}

function a7_lead_wa_status_name(string $entityId, string $statusId): string
{
    static $lists = [];
    $statusId = trim($statusId);
    if ($statusId === '' || !class_exists('CCrmStatus')) {
        return '';
    }
    if (!isset($lists[$entityId])) {
        $list = CCrmStatus::GetStatusList($entityId);
        $lists[$entityId] = is_array($list) ? $list : [];
    }
    return trim((string)($lists[$entityId][$statusId] ?? ''));
}

function a7_lead_wa_enum_label(string $fieldName, $value): string
{
    static $maps = [];
    $id = (int)(is_array($value) ? reset($value) : $value);
    if ($id <= 0) {
        return '';
    }
    if (!isset($maps[$fieldName])) {
        $maps[$fieldName] = [];
        if (class_exists('CUserTypeEntity') && class_exists('CUserFieldEnum')) {
            $uf = CUserTypeEntity::GetList([], ['ENTITY_ID' => 'CRM_LEAD', 'FIELD_NAME' => $fieldName])->Fetch();
            if (is_array($uf)) {
                $rs = CUserFieldEnum::GetList([], ['USER_FIELD_ID' => (int)$uf['ID']]);
                while ($rs && ($enum = $rs->Fetch())) {
                    $maps[$fieldName][(int)$enum['ID']] = trim((string)($enum['VALUE'] ?? ''));
                }
            }
        }
    }
    return (string)($maps[$fieldName][$id] ?? '');
}

function a7_lead_wa_plain_number($value): string
{
    if (is_array($value)) {
        $value = reset($value);
    }
    $text = trim((string)$value);
    if ($text === '' || !is_numeric($text) || (float)$text == 0.0) {
        return '';
    }
    $text = rtrim(rtrim(number_format((float)$text, 2, '.', ''), '0'), '.');
    return $text;
}

function a7_lead_wa_crm_title(string $fieldName, $value): string
{
    static $types = [];
    $id = (int)(is_array($value) ? reset($value) : $value);
    if ($id <= 0) {
        return '';
    }
    if (!isset($types[$fieldName])) {
        $types[$fieldName] = 0;
        if (isset($GLOBALS['USER_FIELD_MANAGER']) && is_object($GLOBALS['USER_FIELD_MANAGER'])) {
            $ufs = $GLOBALS['USER_FIELD_MANAGER']->GetUserFields('CRM_LEAD', 0);
            $settings = is_array($ufs[$fieldName]['SETTINGS'] ?? null) ? $ufs[$fieldName]['SETTINGS'] : [];
            foreach ($settings as $key => $flag) {
                if ($flag === 'Y' && preg_match('/^DYNAMIC_(\d+)$/', (string)$key, $match)) {
                    $types[$fieldName] = (int)$match[1];
                    break;
                }
            }
        }
    }
    $typeId = (int)$types[$fieldName];
    if ($typeId <= 0 || !class_exists(\Bitrix\Crm\Service\Container::class)) {
        return '';
    }
    try {
        $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory($typeId);
        $item = $factory ? $factory->getItem($id) : null;
        if ($item && method_exists($item, 'getTitle')) {
            return trim((string)$item->getTitle());
        }
    } catch (Throwable $e) {
        return '';
    }
    return '';
}

function a7_lead_wa_lead_details(array $lead, string $phone, string $name): array
{
    return a7_lead_wa_detail_pack($name, $phone, [
        'source' => a7_lead_wa_status_name('SOURCE', (string)($lead['SOURCE_ID'] ?? '')),
        'stage' => a7_lead_wa_status_name('STATUS', (string)($lead['STATUS_ID'] ?? '')),
        'community' => trim((string)($lead['UF_CRM_1770537051525'] ?? '')),
        'sub_community' => a7_lead_wa_crm_title('UF_CRM_1763390179', $lead['UF_CRM_1763390179'] ?? ''),
        'bedrooms' => a7_lead_wa_enum_label('UF_CRM_1731838126127', $lead['UF_CRM_1731838126127'] ?? ''),
        'client_type' => a7_lead_wa_enum_label('UF_CRM_1756638760279', $lead['UF_CRM_1756638760279'] ?? ''),
        'deal_amount' => a7_lead_wa_plain_number($lead['UF_CRM_1736306439793'] ?? ''),
        'property_reference' => trim((string)($lead['UF_CRM_1760707563281'] ?? '')),
    ]);
}

function a7_lead_wa_row(int $leadId): ?array
{
    if ($leadId <= 0 || !class_exists('CCrmLead')) {
        return null;
    }
    if (!CCrmLead::CheckReadPermission($leadId)) {
        return null;
    }
    $res = CCrmLead::GetListEx(
        [],
        ['=ID' => $leadId, 'CHECK_PERMISSIONS' => 'N'],
        false,
        ['nTopCount' => 1],
        [
            'ID', 'TITLE', 'NAME', 'LAST_NAME', 'SOURCE_ID', 'STATUS_ID',
            'UF_CRM_1770537051525', 'UF_CRM_1763390179', 'UF_CRM_1731838126127',
            'UF_CRM_1756638760279', 'UF_CRM_1736306439793', 'UF_CRM_1760707563281',
        ]
    );
    $lead = $res ? $res->Fetch() : null;
    if (!is_array($lead)) {
        return null;
    }
    $row = [
        'id' => $leadId,
        'phone' => a7_lead_wa_phone($leadId),
        'name' => (string)($lead['TITLE'] ?? ''),
        'title' => (string)($lead['TITLE'] ?? ''),
        'first_name' => (string)($lead['NAME'] ?? ''),
        'last_name' => (string)($lead['LAST_NAME'] ?? ''),
    ];
    $row['details'] = a7_lead_wa_lead_details($lead, (string)$row['phone'], a7_lead_wa_display($row));
    return $row;
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
    if (in_array($raw, ['owner_data', '1042', 'dynamic_1042'], true)) {
        return 'owner_data';
    }
    if ($raw === 'deal' || $raw === 'contact') {
        return $raw;
    }
    return 'lead';
}

function a7_lead_wa_noun(string $entity): string
{
    switch ($entity) {
        case 'owner_data':
            return 'Owner Data cards';
        case 'deal':
            return 'deals';
        case 'contact':
            return 'contacts';
        default:
            return 'leads';
    }
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
    $phone = a7_lead_wa_owner_phone($item, $data);
    return [
        'id' => $itemId,
        'owner_data_id' => $itemId,
        'phone' => $phone,
        'name' => $title,
        'title' => $title,
        'first_name' => '',
        'last_name' => '',
        'details' => a7_lead_wa_detail_pack($title, $phone),
    ];
}

function a7_lead_wa_company_phone(int $companyId): string
{
    if ($companyId <= 0 || !class_exists('CCrmFieldMulti')) {
        return '';
    }
    $db = CCrmFieldMulti::GetList(
        ['ID' => 'ASC'],
        ['ENTITY_ID' => 'COMPANY', 'ELEMENT_ID' => $companyId, 'TYPE_ID' => 'PHONE']
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

function a7_lead_wa_contact_row(int $contactId): ?array
{
    if ($contactId <= 0 || !class_exists('CCrmContact')) {
        return null;
    }
    if (!CCrmContact::CheckReadPermission($contactId)) {
        return null;
    }
    $contact = CCrmContact::GetByID($contactId, false);
    if (!is_array($contact)) {
        return null;
    }
    $first = trim((string)($contact['NAME'] ?? ''));
    $last = trim((string)($contact['LAST_NAME'] ?? ''));
    $full = trim((string)($contact['FULL_NAME'] ?? ''));
    if ($full === '') {
        $full = trim($first . ' ' . $last);
    }
    $phone = a7_lead_wa_contact_phone($contactId);
    return [
        'id' => $contactId,
        'crm_contact_id' => $contactId,
        'phone' => $phone,
        'name' => $full,
        'title' => $full,
        'first_name' => $first,
        'last_name' => $last,
        'details' => a7_lead_wa_detail_pack($full, $phone),
    ];
}

function a7_lead_wa_deal_contact_ids(int $dealId, array $deal): array
{
    $ids = [];
    $primary = (int)($deal['CONTACT_ID'] ?? 0);
    if ($primary > 0) {
        $ids[] = $primary;
    }
    try {
        if (class_exists('\Bitrix\Crm\Binding\DealContactTable')) {
            foreach (\Bitrix\Crm\Binding\DealContactTable::getDealContactIDs($dealId) as $cid) {
                $cid = (int)$cid;
                if ($cid > 0 && !in_array($cid, $ids, true)) {
                    $ids[] = $cid;
                }
            }
        }
    } catch (Throwable $e) {
    }
    return $ids;
}

function a7_lead_wa_deal_row(int $dealId): ?array
{
    if ($dealId <= 0 || !class_exists('CCrmDeal')) {
        return null;
    }
    if (!CCrmDeal::CheckReadPermission($dealId)) {
        return null;
    }
    $deal = CCrmDeal::GetByID($dealId, false);
    if (!is_array($deal)) {
        return null;
    }
    $title = trim((string)($deal['TITLE'] ?? ''));
    $phone = '';
    $first = '';
    $last = '';
    // The deal's own contact(s) first, then the company switchboard.
    foreach (a7_lead_wa_deal_contact_ids($dealId, $deal) as $cid) {
        $phone = a7_lead_wa_contact_phone($cid);
        if ($phone === '') {
            continue;
        }
        if (class_exists('CCrmContact')) {
            $contact = CCrmContact::GetByID($cid, false);
            if (is_array($contact)) {
                $first = trim((string)($contact['NAME'] ?? ''));
                $last = trim((string)($contact['LAST_NAME'] ?? ''));
            }
        }
        break;
    }
    if ($phone === '') {
        $phone = a7_lead_wa_company_phone((int)($deal['COMPANY_ID'] ?? 0));
    }
    $person = trim($first . ' ' . $last);
    $name = $person !== '' ? $person : $title;
    return [
        'id' => $dealId,
        'crm_deal_id' => $dealId,
        'phone' => $phone,
        'name' => $name,
        'title' => $title,
        'first_name' => $first,
        'last_name' => $last,
        'details' => a7_lead_wa_detail_pack($name, $phone, [
            'stage' => a7_lead_wa_status_name('DEAL_STAGE', (string)($deal['STAGE_ID'] ?? '')),
        ]),
    ];
}

function a7_lead_wa_resolve_row(int $id, string $entity): ?array
{
    switch ($entity) {
        case 'owner_data':
            return a7_lead_wa_owner_row($id);
        case 'deal':
            return a7_lead_wa_deal_row($id);
        case 'contact':
            return a7_lead_wa_contact_row($id);
        default:
            return a7_lead_wa_row($id);
    }
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

function a7_lead_wa_write_all($fp, string $data): bool
{
    $total = strlen($data);
    $done = 0;
    while ($done < $total) {
        $wrote = @fwrite($fp, $done === 0 ? $data : substr($data, $done));
        if ($wrote === false || $wrote === 0) {
            return false;
        }
        $done += $wrote;
    }
    return true;
}

/**
 * POST a file's raw bytes without holding them in memory. A header document
 * may be 100 MB and this PHP has 256 MB for everything, so the bytes go from
 * the upload's temp file straight to the socket. HTTP/1.0, so the answer is
 * never chunked: it is read as it comes, like a7_lead_wa_http_socket does.
 */
function a7_lead_wa_stream_file(string $url, string $file, int $size, array $headerLines): array
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
    $ctx = stream_context_create([
        'ssl' => [
            'verify_peer' => true,
            'verify_peer_name' => true,
            'peer_name' => $host,
        ],
    ]);
    $errno = 0;
    $errstr = '';
    $target = ($https ? 'ssl://' : 'tcp://') . $host . ':' . $port;
    $fp = @stream_socket_client($target, $errno, $errstr, 15, STREAM_CLIENT_CONNECT, $ctx);
    if ($fp === false) {
        return [
            'raw' => '',
            'http' => 0,
            'error' => 'WhatsApp inbox did not answer' . ($errstr !== '' ? ' (' . $errstr . ')' : '') . '.',
        ];
    }
    stream_set_timeout($fp, 300);
    $head = "POST {$path} HTTP/1.0\r\n"
        . "Host: {$host}\r\n"
        . "Content-Length: {$size}\r\n"
        . "Connection: close\r\n";
    foreach ($headerLines as $line) {
        $head .= $line . "\r\n";
    }
    $ok = a7_lead_wa_write_all($fp, $head . "\r\n");
    $sent = 0;
    $in = $ok ? @fopen($file, 'rb') : false;
    if ($in === false) {
        $ok = false;
    } else {
        while ($ok && !feof($in)) {
            $chunk = fread($in, 262144);
            if ($chunk === false) {
                $ok = false;
                break;
            }
            if ($chunk === '') {
                continue;
            }
            $ok = a7_lead_wa_write_all($fp, $chunk);
            $sent += strlen($chunk);
        }
        fclose($in);
    }
    if (!$ok || $sent !== $size) {
        fclose($fp);
        return ['raw' => '', 'http' => 0, 'error' => 'The file could not be passed on to the WhatsApp inbox. Try again.'];
    }
    $resp = stream_get_contents($fp);
    $state = stream_get_meta_data($fp);
    fclose($fp);
    if (!is_string($resp) || $resp === '') {
        return [
            'raw' => '',
            'http' => 0,
            'error' => !empty($state['timed_out'])
                ? 'The WhatsApp inbox took too long to answer. Try a smaller file.'
                : 'WhatsApp inbox did not answer.',
        ];
    }
    $http = 0;
    if (preg_match('/^HTTP\/\S+\s+(\d{3})/', $resp, $m)) {
        $http = (int)$m[1];
    }
    $split = preg_split("/\r\n\r\n/", $resp, 2);
    return ['raw' => isset($split[1]) ? $split[1] : '', 'http' => $http, 'error' => ''];
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

if ($action === 'header-media') {
    // The image, video or document a media-header template goes out with.
    // Every CRM popup posts its file here (Leads, Owner Data, Deals, Contacts
    // and a7_renewals_wa.js too). The bytes are streamed on to the inbox and
    // signed over "ts.meta." plus the bytes; the inbox uploads them for the
    // chosen number and answers with a token the send call hands back.
    $secret = trim((string)($cfg['secret'] ?? ''));
    $base = rtrim((string)($cfg['inbox_url'] ?? ''), '/');
    if ($secret === '' || $base === '') {
        a7_lead_wa_json(['ok' => false, 'error' => 'WhatsApp send is not configured.'], 503);
    }
    $upload = $_FILES['file'] ?? null;
    $code = is_array($upload) ? (int)($upload['error'] ?? UPLOAD_ERR_NO_FILE) : UPLOAD_ERR_NO_FILE;
    if ($code === UPLOAD_ERR_INI_SIZE || $code === UPLOAD_ERR_FORM_SIZE) {
        a7_lead_wa_json(['ok' => false, 'error' => 'That file is larger than Bitrix accepts.'], 413);
    }
    if ($code !== UPLOAD_ERR_OK) {
        a7_lead_wa_json([
            'ok' => false,
            'error' => $code === UPLOAD_ERR_NO_FILE ? 'Choose a file first.' : 'The file did not arrive. Try again.',
        ], 400);
    }
    $tmp = (string)($upload['tmp_name'] ?? '');
    if ($tmp === '' || !is_uploaded_file($tmp)) {
        a7_lead_wa_json(['ok' => false, 'error' => 'The file did not arrive. Try again.'], 400);
    }
    $size = @filesize($tmp);
    $size = $size === false ? (int)($upload['size'] ?? 0) : (int)$size;
    if ($size <= 0) {
        a7_lead_wa_json(['ok' => false, 'error' => 'That file is empty.'], 400);
    }
    if ($size > 100 * 1024 * 1024) {
        a7_lead_wa_json(['ok' => false, 'error' => 'WhatsApp does not take a header file larger than 100 MB.'], 413);
    }
    $meta = json_encode([
        'bitrix_user_id' => $bitrixUserId,
        'number_id' => (int)($_POST['number_id'] ?? 0),
        'format' => strtoupper(trim((string)($_POST['format'] ?? ''))),
        'filename' => (string)($upload['name'] ?? ''),
        'mime' => (string)($upload['type'] ?? ''),
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if (!is_string($meta)) {
        a7_lead_wa_json(['ok' => false, 'error' => 'Could not encode the request.'], 500);
    }
    $meta = base64_encode($meta);
    $ts = (string)time();
    $mac = hash_init('sha256', HASH_HMAC, $secret);
    hash_update($mac, $ts . '.' . $meta . '.');
    if (!hash_update_file($mac, $tmp)) {
        a7_lead_wa_json(['ok' => false, 'error' => 'The file could not be read. Try again.'], 500);
    }
    $sig = hash_final($mac);
    $http = a7_lead_wa_stream_file($base . '/api/campaigns/crm-header-media/', $tmp, $size, [
        'Content-Type: application/octet-stream',
        'X-Crm-Ts: ' . $ts,
        'X-Crm-Sign: ' . $sig,
        'X-Crm-Meta: ' . $meta,
    ]);
    if ($http['raw'] === '' && (int)$http['http'] === 0) {
        a7_lead_wa_json([
            'ok' => false,
            'error' => $http['error'] !== '' ? $http['error'] : 'WhatsApp inbox did not answer.',
        ], 502);
    }
    $data = json_decode($http['raw'], true);
    if (!is_array($data)) {
        $data = ['detail' => (int)$http['http'] === 413
            ? 'That file is larger than the WhatsApp inbox accepts.'
            : 'Unexpected inbox reply.'];
    }
    $status = (int)$http['http'];
    if ($status < 200 || $status >= 300) {
        $detail = (string)($data['detail'] ?? 'The header file was not accepted.');
        a7_lead_wa_json(['ok' => false, 'error' => $detail], $status >= 400 ? $status : 502);
    }
    a7_lead_wa_json(['ok' => true] + $data, 201);
}

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
        } elseif ($hint === 'deal' || $hint === 'contact') {
            $entity = $hint;
        }
    }
    $noun = a7_lead_wa_noun($entity);
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
            'error' => 'You cannot read those ' . $noun . ', or they were not found.',
        ], 403);
    }

    $payload = [
        'bitrix_user_id' => $bitrixUserId,
        'entity' => $entity,
        'template_id' => (int)($input['template_id'] ?? 0),
        'number_id' => (int)($input['number_id'] ?? 0),
        'leads' => $leads,
        'variables' => is_array($input['variables'] ?? null) ? $input['variables'] : [],
        'variable_fields' => is_array($input['variable_fields'] ?? null) ? $input['variable_fields'] : [],
        'header_variables' => is_array($input['header_variables'] ?? null) ? $input['header_variables'] : [],
        'button_variables' => is_array($input['button_variables'] ?? null) ? $input['button_variables'] : [],
        // From the header-media action above; the inbox checks it belongs to
        // this user, this number and this template's header kind.
        'header_media_token' => (string)($input['header_media_token'] ?? ''),
        // The popup's "Lead AI" box: the chats go to the Lead AI screen.
        'lead_ai' => !empty($input['lead_ai']),
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
