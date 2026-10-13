<?php
/**
 * Bitrix OnCrmLeadAdd → Official leadbot (replaces n8n outreach).
 *
 * Deploy to: /home/bitrix/www/bitrix/tools/a7_leadbot_outreach.php
 * Config:    /home/bitrix/www/bitrix/php_interface/a7_lead_wa.config.php
 *            keys: secret (same as CRM_LEAD_WA_SECRET), inbox_url
 *
 * Robot (bizproc, lead, on create):
 *   PHP code or webhook GET/POST this URL with lead id:
 *     /bitrix/tools/a7_leadbot_outreach.php?lead_id={=Document:ID}
 *
 * After this path is proven, unpublish the n8n workflow
 * "A7 WhatsApp CRM Automation v9" outreach webhook
 * (/a7-bitrix-lead-outreach-v2). Do not run both.
 */

function a7_leadbot_config(): array
{
    $path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
    if (!is_file($path)) {
        $path = __DIR__ . '/../php_interface/a7_lead_wa.config.php';
    }
    $cfg = is_file($path) ? include $path : [];
    return is_array($cfg) ? $cfg : [];
}

function a7_leadbot_json(array $payload, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

$leadId = (int)($_REQUEST['lead_id'] ?? $_REQUEST['leadId'] ?? $_REQUEST['ID'] ?? 0);
if ($leadId <= 0 && !empty($_SERVER['CONTENT_TYPE']) && stripos($_SERVER['CONTENT_TYPE'], 'json') !== false) {
    $raw = file_get_contents('php://input') ?: '';
    $body = json_decode($raw, true);
    if (is_array($body)) {
        $leadId = (int)($body['lead_id'] ?? $body['leadId'] ?? $body['ID'] ?? 0);
    }
}
if ($leadId <= 0) {
    a7_leadbot_json(['ok' => false, 'detail' => 'lead_id required'], 400);
}

$cfg = a7_leadbot_config();
$secret = trim((string)($cfg['secret'] ?? ''));
$base = rtrim((string)($cfg['inbox_url'] ?? 'https://wa.srv1802669.hstgr.cloud'), '/');
if ($secret === '') {
    a7_leadbot_json(['ok' => false, 'detail' => 'leadbot secret missing'], 500);
}

$payload = json_encode(['leadId' => $leadId], JSON_UNESCAPED_UNICODE);
$ts = (string)time();
$sign = hash_hmac('sha256', $ts . '.' . $payload, $secret);
$url = $base . '/api/leadbot/outreach/';

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $payload,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 40,
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json',
        'X-Crm-Ts: ' . $ts,
        'X-Crm-Sign: ' . $sign,
    ],
]);
$raw = curl_exec($ch);
$code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
$err = curl_error($ch);
curl_close($ch);

if ($raw === false) {
    a7_leadbot_json(['ok' => false, 'detail' => $err ?: 'curl failed'], 502);
}
$decoded = json_decode($raw, true);
a7_leadbot_json(
    is_array($decoded) ? $decoded : ['ok' => false, 'detail' => substr((string)$raw, 0, 500)],
    $code >= 200 && $code < 300 ? 200 : ($code ?: 502)
);
