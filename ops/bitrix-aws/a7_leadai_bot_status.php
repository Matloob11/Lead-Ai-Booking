<?php
/**
 * A person changes Bot Status or WhatsApp Opt-out on a lead -> one signed
 * POST to the Lead AI inbox. The C6 tool sets $GLOBALS['A7_LEADAI_FIELDS_SAVE']
 * to the lead id and is skipped.
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_leadai_bot_status.php
 * Loaded from: bitrix/php_interface/init.php
 *
 * The POST waits at most 3 seconds and never fails the lead save. Until the
 * Django route exists it answers 404, and that is only written to the log.
 */

use Bitrix\Main\EventManager;

if (defined('A7_LEADAI_BOT_STATUS_LOADED')) {
    return;
}
define('A7_LEADAI_BOT_STATUS_LOADED', true);

final class A7LeadaiBotStatus
{
    public const VERSION = '1';
    public const URL = 'https://wa.srv1802669.hstgr.cloud/api/leadai/bitrix/bot-status/';
    public const LOG = '/tmp/a7_leadai_bot_status.log';
    /** @var array<int,array{bot:int,opt:int}> */
    private static array $before = [];

    public static function register(): void
    {
        $em = EventManager::getInstance();
        $em->addEventHandler('crm', 'OnBeforeCrmLeadUpdate', [__CLASS__, 'onBefore']);
        $em->addEventHandler('crm', 'OnAfterCrmLeadUpdate', [__CLASS__, 'onAfter']);
    }

    /** @param array<string,mixed> $arFields */
    public static function onBefore(&$arFields): bool
    {
        try {
            $id = (int)($arFields['ID'] ?? 0);
            if ($id <= 0) {
                return true;
            }
            if (!array_key_exists('UF_CRM_A7_BOT_STATUS', $arFields)
                && !array_key_exists('UF_CRM_A7_WA_OPT_OUT', $arFields)) {
                return true;
            }
            if (!class_exists('CCrmLead')) {
                return true;
            }
            $res = CCrmLead::GetListEx(
                [],
                ['=ID' => $id, 'CHECK_PERMISSIONS' => 'N'],
                false,
                ['nTopCount' => 1],
                ['ID', 'UF_CRM_A7_BOT_STATUS', 'UF_CRM_A7_WA_OPT_OUT']
            );
            $row = $res ? $res->Fetch() : null;
            self::$before[$id] = [
                'bot' => (int)(is_array($row) ? ($row['UF_CRM_A7_BOT_STATUS'] ?? 0) : 0),
                'opt' => (int)(is_array($row) ? ($row['UF_CRM_A7_WA_OPT_OUT'] ?? 0) : 0),
            ];
        } catch (\Throwable $e) {
            self::log('before error');
        }
        return true;
    }

    /** @param array<string,mixed> $arFields */
    public static function onAfter(&$arFields): void
    {
        try {
            $id = (int)($arFields['ID'] ?? 0);
            $old = self::$before[$id] ?? null;
            unset(self::$before[$id]);
            if ($id <= 0 || $old === null) {
                return;
            }
            if ((int)($GLOBALS['A7_LEADAI_FIELDS_SAVE'] ?? 0) === $id) {
                return;
            }
            $bot = array_key_exists('UF_CRM_A7_BOT_STATUS', $arFields)
                ? (int)$arFields['UF_CRM_A7_BOT_STATUS']
                : $old['bot'];
            $opt = array_key_exists('UF_CRM_A7_WA_OPT_OUT', $arFields)
                ? (int)$arFields['UF_CRM_A7_WA_OPT_OUT']
                : $old['opt'];
            $botHit = in_array($bot, [2478, 2479, 2480, 2481], true) && $bot !== $old['bot'];
            $optHit = $opt === 2482 && $opt !== $old['opt'];
            if (!$botHit && !$optHit) {
                return;
            }
            self::post($id, $bot, $opt);
        } catch (\Throwable $e) {
            self::log('after error');
        }
    }

    private static function post(int $leadId, int $bot, int $opt): void
    {
        $cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
        if (!is_file($cfgPath)) {
            $cfgPath = '/home/bitrix/www/bitrix/php_interface/a7_lead_wa.config.php';
        }
        $cfg = is_file($cfgPath) ? include $cfgPath : [];
        $secret = trim((string)(is_array($cfg) ? ($cfg['secret'] ?? '') : ''));
        if ($secret === '') {
            self::log('lead=' . $leadId . ' error=not_configured');
            return;
        }
        global $USER;
        $userId = (is_object($USER) && method_exists($USER, 'GetID')) ? (int)$USER->GetID() : 0;
        $at = (new \DateTime('now', new \DateTimeZone('Asia/Dubai')))->format('Y-m-d\TH:i:sP');
        $body = json_encode([
            'lead_id' => $leadId,
            'bot_status' => $bot > 0 ? $bot : null,
            'wa_opt_out' => $opt === 2482 ? 2482 : null,
            'changed_by' => $userId,
            'at' => $at,
        ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($body === false) {
            self::log('lead=' . $leadId . ' error=encode');
            return;
        }
        $ts = (string)time();
        $sign = hash_hmac('sha256', 'leadai-botstatus.' . $ts . '.' . $body, $secret);
        $code = self::send($body, $ts, $sign);
        if ($code < 200 || $code >= 300) {
            self::log('lead=' . $leadId . ' http=' . $code);
        }
    }

    private static function send(string $body, string $ts, string $sign): int
    {
        $header = "Content-Type: application/json\r\n"
            . 'X-Leadai-Ts: ' . $ts . "\r\n"
            . 'X-Leadai-Sign: ' . $sign . "\r\n"
            . 'Content-Length: ' . strlen($body) . "\r\n";
        $ctx = stream_context_create([
            'http' => [
                'method' => 'POST',
                'header' => $header,
                'content' => $body,
                'timeout' => 3,
                'ignore_errors' => true,
            ],
        ]);
        $raw = @file_get_contents(self::URL, false, $ctx);
        if (isset($http_response_header[0]) && preg_match('/\s(\d{3})\s/', (string)$http_response_header[0], $match)) {
            return (int)$match[1];
        }
        if ($raw !== false && $raw !== '') {
            return 0;
        }
        $tmp = tempnam(sys_get_temp_dir(), 'a7bot');
        if ($tmp === false) {
            return 0;
        }
        file_put_contents($tmp, $body);
        $cmd = 'curl -sS -o /dev/null -w %{http_code} --max-time 3 -X POST'
            . ' -H ' . escapeshellarg('Content-Type: application/json')
            . ' -H ' . escapeshellarg('X-Leadai-Ts: ' . $ts)
            . ' -H ' . escapeshellarg('X-Leadai-Sign: ' . $sign)
            . ' --data-binary @' . escapeshellarg($tmp)
            . ' ' . escapeshellarg(self::URL);
        $out = trim((string)shell_exec($cmd));
        @unlink($tmp);
        return ctype_digit($out) ? (int)$out : 0;
    }

    private static function log(string $line): void
    {
        @file_put_contents(self::LOG, date('Y-m-d H:i:s') . ' ' . $line . "\n", FILE_APPEND | LOCK_EX);
    }
}

A7LeadaiBotStatus::register();
