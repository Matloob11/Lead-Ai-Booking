<?php
/**
 * A person changes Bot Status or WhatsApp Opt-out on a lead -> signed POST to
 * the Lead AI inbox. The C6 tool sets $GLOBALS['A7_LEADAI_FIELDS_SAVE'] to the
 * lead id and is skipped.
 *
 * C34: a failed POST is queued and retried (up to 3 tries over 15 minutes) by
 * a Bitrix agent. Each failure is one log line without the body. Django's
 * endpoint is idempotent, so a repeat is harmless.
 *
 * C36: when a person moves a lead out of Not Interested / JUNK, into stage 10,
 * or sets Meeting Date & Time, set Bot Status Handed to agent (2478) in onAfter
 * (a follow-up Update — OnBefore cannot reliably add UF fields). C12 then posts.
 * C6 writes stay excluded. CCrmLead::Update merges the full row into $arFields,
 * so "field present" is not "field changed".
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_leadai_bot_status.php
 * Loaded from: bitrix/php_interface/init.php
 */

use Bitrix\Main\EventManager;

if (defined('A7_LEADAI_BOT_STATUS_LOADED')) {
    return;
}
define('A7_LEADAI_BOT_STATUS_LOADED', true);

final class A7LeadaiBotStatus
{
    public const VERSION = '6';
    public const URL = 'https://wa.srv1802669.hstgr.cloud/api/leadai/bitrix/bot-status/';
    public const LOG = '/tmp/a7_leadai_bot_status.log';
    public const QUEUE = '/home/bitrix/www/upload/a7_leadai_bot_status_queue.jsonl';
    public const MAX_TRIES = 3;
    public const WINDOW_SEC = 900;
    public const RETRY_GAP_SEC = 300;
    public const BOT_HANDED = 2478;
    public const MEET_FIELD = 'UF_CRM_1731838813769';
    /** @var callable|null Proof hook: fn(string $body, string $ts, string $sign, string $url): int */
    public static $sendHook = null;
    /** @var array<int,array{bot:int,opt:int,status:string,meet:string}> */
    private static array $before = [];
    /** @var array<int,true> C36: person takeover — set 2478 in onAfter (UF inject in onBefore is dropped). */
    private static array $pendingHand = [];

    public static function register(): void
    {
        $em = EventManager::getInstance();
        // Sort 10: before A7LeadStageOwner / others that may unset STATUS_ID from $arFields.
        $em->addEventHandler('crm', 'OnBeforeCrmLeadUpdate', [__CLASS__, 'onBefore'], false, 10);
        $em->addEventHandler('crm', 'OnAfterCrmLeadUpdate', [__CLASS__, 'onAfter'], false, 10);
        self::ensureAgent();
    }

    private static function ensureAgent(): void
    {
        if (!class_exists('CAgent')) {
            return;
        }
        $name = '\\A7LeadaiBotStatus::agent();';
        $exists = CAgent::GetList([], ['NAME' => $name])->Fetch();
        if ($exists) {
            return;
        }
        CAgent::AddAgent($name, '', 'N', self::RETRY_GAP_SEC, '', 'Y', '', 30);
    }

    /** Bitrix agent entry: retry queued bot-status POSTs. */
    public static function agent(): string
    {
        try {
            self::processQueue();
        } catch (\Throwable $e) {
            self::log('agent error');
        }
        return self::class . '::agent();';
    }

    /** @param array<string,mixed> $arFields */
    public static function onBefore(&$arFields): bool
    {
        try {
            $id = (int)($arFields['ID'] ?? 0);
            if ($id <= 0 || !class_exists('CCrmLead')) {
                return true;
            }
            // CCrmLead::Update merges the full row into $arFields — always snap when we have an ID.
            $res = CCrmLead::GetListEx(
                [],
                ['=ID' => $id, 'CHECK_PERMISSIONS' => 'N'],
                false,
                ['nTopCount' => 1],
                ['ID', 'STATUS_ID', 'UF_CRM_A7_BOT_STATUS', 'UF_CRM_A7_WA_OPT_OUT', self::MEET_FIELD]
            );
            $row = $res ? $res->Fetch() : null;
            if (!is_array($row)) {
                return true;
            }
            self::$before[$id] = [
                'bot' => (int)($row['UF_CRM_A7_BOT_STATUS'] ?? 0),
                'opt' => (int)($row['UF_CRM_A7_WA_OPT_OUT'] ?? 0),
                'status' => (string)($row['STATUS_ID'] ?? ''),
                'meet' => trim((string)($row[self::MEET_FIELD] ?? '')),
            ];
            self::queuePersonHandoff($arFields, self::$before[$id]);
        } catch (\Throwable $e) {
            self::log('before error');
        }
        return true;
    }

    /**
     * C36: mark a person takeover for onAfter (second Update writes 2478).
     *
     * @param array<string,mixed> $arFields
     * @param array{bot:int,opt:int,status:string,meet:string} $old
     */
    private static function queuePersonHandoff(array $arFields, array $old): void
    {
        $id = (int)($arFields['ID'] ?? 0);
        if ($id <= 0) {
            return;
        }
        if ((int)($GLOBALS['A7_LEADAI_FIELDS_SAVE'] ?? 0) === $id) {
            return;
        }
        if ((int)($GLOBALS['A7_LEADAI_PERSON_HANDOFF'] ?? 0) === $id) {
            return;
        }
        // Full-row merges always carry Bot Status; only skip when it actually changes.
        if (array_key_exists('UF_CRM_A7_BOT_STATUS', $arFields)
            && (int)$arFields['UF_CRM_A7_BOT_STATUS'] !== (int)$old['bot']) {
            return;
        }
        global $USER;
        $uid = (is_object($USER) && method_exists($USER, 'GetID') && $USER->IsAuthorized())
            ? (int)$USER->GetID()
            : 0;
        if ($uid <= 0) {
            return;
        }
        if ((int)$old['bot'] === self::BOT_HANDED) {
            return;
        }
        $hand = false;
        if (array_key_exists('STATUS_ID', $arFields)) {
            $newStatus = (string)$arFields['STATUS_ID'];
            $oldStatus = (string)$old['status'];
            if ($newStatus !== $oldStatus) {
                $wasLost = in_array($oldStatus, ['1', 'JUNK'], true);
                $nowLost = in_array($newStatus, ['1', 'JUNK'], true);
                if ($wasLost && !$nowLost) {
                    $hand = true;
                }
                if ($newStatus === '10') {
                    $hand = true;
                }
            }
        }
        if (array_key_exists(self::MEET_FIELD, $arFields)) {
            $newMeet = $arFields[self::MEET_FIELD];
            $newMeetStr = is_object($newMeet) && method_exists($newMeet, 'toString')
                ? (string)$newMeet->toString()
                : trim((string)$newMeet);
            if ($newMeetStr !== '' && $newMeetStr !== (string)$old['meet']) {
                $hand = true;
            }
        }
        if (!$hand) {
            return;
        }
        self::$pendingHand[$id] = true;
        self::log('lead=' . $id . ' c36_queue user=' . $uid . ' from_bot=' . (int)$old['bot']);
    }

    private static function applyPersonHandoff(int $leadId): void
    {
        if ($leadId <= 0 || !class_exists('CCrmLead')) {
            return;
        }
        $GLOBALS['A7_LEADAI_PERSON_HANDOFF'] = $leadId;
        try {
            $crm = new CCrmLead(false);
            $fields = ['UF_CRM_A7_BOT_STATUS' => self::BOT_HANDED];
            $crm->Update($leadId, $fields, true, true, [
                'CURRENT_USER' => 1,
                'DISABLE_USER_FIELD_CHECK' => true,
                'REGISTER_SONET_EVENT' => false,
            ]);
            self::log('lead=' . $leadId . ' c36_applied');
        } catch (\Throwable $e) {
            self::log('lead=' . $leadId . ' c36_apply_error');
        }
        unset($GLOBALS['A7_LEADAI_PERSON_HANDOFF']);
    }

    /** @param array<string,mixed> $arFields */
    public static function onAfter(&$arFields): void
    {
        try {
            $id = (int)($arFields['ID'] ?? 0);
            $old = self::$before[$id] ?? null;
            unset(self::$before[$id]);
            if ($id <= 0) {
                return;
            }
            if (!empty(self::$pendingHand[$id])
                && (int)($GLOBALS['A7_LEADAI_FIELDS_SAVE'] ?? 0) !== $id
                && (int)($GLOBALS['A7_LEADAI_PERSON_HANDOFF'] ?? 0) !== $id) {
                unset(self::$pendingHand[$id]);
                self::applyPersonHandoff($id);
                // applyPersonHandoff's Update posts via C12; nothing more here.
                return;
            }
            if ($old === null) {
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
        $built = self::buildBody($leadId, $bot, $opt);
        if ($built === null) {
            return;
        }
        [$body, $ts, $sign] = $built;
        $code = self::send($body, $ts, $sign, self::URL);
        if ($code >= 200 && $code < 300) {
            return;
        }
        self::log('lead=' . $leadId . ' http=' . $code);
        self::enqueue([
            'lead_id' => $leadId,
            'bot' => $bot,
            'opt' => $opt,
            'body' => $body,
            'tries' => 1,
            'first_at' => time(),
            'next_at' => time() + self::RETRY_GAP_SEC,
            'url' => self::URL,
        ]);
    }

    /** @return array{0:string,1:string,2:string}|null */
    private static function buildBody(int $leadId, int $bot, int $opt): ?array
    {
        $cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_lead_wa.config.php';
        if (!is_file($cfgPath)) {
            $cfgPath = '/home/bitrix/www/bitrix/php_interface/a7_lead_wa.config.php';
        }
        $cfg = is_file($cfgPath) ? include $cfgPath : [];
        $secret = trim((string)(is_array($cfg) ? ($cfg['secret'] ?? '') : ''));
        if ($secret === '') {
            self::log('lead=' . $leadId . ' error=not_configured');
            return null;
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
            return null;
        }
        $ts = (string)time();
        $sign = hash_hmac('sha256', 'leadai-botstatus.' . $ts . '.' . $body, $secret);
        return [$body, $ts, $sign];
    }

    private static function send(string $body, string $ts, string $sign, string $url): int
    {
        if (is_callable(self::$sendHook)) {
            return (int)(self::$sendHook)($body, $ts, $sign, $url);
        }
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
        $raw = @file_get_contents($url, false, $ctx);
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
            . ' ' . escapeshellarg($url);
        $out = trim((string)shell_exec($cmd));
        @unlink($tmp);
        return ctype_digit($out) ? (int)$out : 0;
    }

    /** @param array<string,mixed> $item */
    public static function enqueue(array $item): void
    {
        $dir = dirname(self::QUEUE);
        if (!is_dir($dir)) {
            @mkdir($dir, 0755, true);
        }
        $line = json_encode($item, JSON_UNESCAPED_SLASHES);
        if ($line === false) {
            return;
        }
        @file_put_contents(self::QUEUE, $line . "\n", FILE_APPEND | LOCK_EX);
    }

    /** Process due queue rows. Returns how many POSTs were attempted. */
    public static function processQueue(): int
    {
        if (!is_file(self::QUEUE)) {
            return 0;
        }
        $raw = @file_get_contents(self::QUEUE);
        if ($raw === false || trim($raw) === '') {
            return 0;
        }
        $lines = preg_split("/\r\n|\n|\r/", trim($raw)) ?: [];
        $keep = [];
        $attempted = 0;
        $now = time();
        foreach ($lines as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $item = json_decode($line, true);
            if (!is_array($item)) {
                continue;
            }
            $first = (int)($item['first_at'] ?? $now);
            $tries = (int)($item['tries'] ?? 0);
            $next = (int)($item['next_at'] ?? $now);
            $leadId = (int)($item['lead_id'] ?? 0);
            if ($tries >= self::MAX_TRIES || ($now - $first) > self::WINDOW_SEC) {
                self::log('lead=' . $leadId . ' drop tries=' . $tries);
                continue;
            }
            if ($next > $now) {
                $keep[] = $item;
                continue;
            }
            $body = (string)($item['body'] ?? '');
            $url = (string)($item['url'] ?? self::URL);
            if ($body === '') {
                continue;
            }
            // Fresh signature: the old ts may be outside Django's 300 s window.
            $rebuilt = self::buildBody(
                $leadId,
                (int)($item['bot'] ?? 0),
                (int)($item['opt'] ?? 0)
            );
            if ($rebuilt === null) {
                $keep[] = $item;
                continue;
            }
            [$body, $ts, $sign] = $rebuilt;
            $attempted++;
            $code = self::send($body, $ts, $sign, $url);
            if ($code >= 200 && $code < 300) {
                self::log('lead=' . $leadId . ' retry_ok http=' . $code . ' tries=' . ($tries + 1));
                continue;
            }
            self::log('lead=' . $leadId . ' http=' . $code . ' retry=' . ($tries + 1));
            $item['body'] = $body;
            $item['tries'] = $tries + 1;
            $item['next_at'] = $now + self::RETRY_GAP_SEC;
            if ($item['tries'] < self::MAX_TRIES && ($now - $first) <= self::WINDOW_SEC) {
                $keep[] = $item;
            } else {
                self::log('lead=' . $leadId . ' drop tries=' . $item['tries']);
            }
        }
        $out = '';
        foreach ($keep as $item) {
            $line = json_encode($item, JSON_UNESCAPED_SLASHES);
            if ($line !== false) {
                $out .= $line . "\n";
            }
        }
        if ($out === '') {
            @unlink(self::QUEUE);
        } else {
            @file_put_contents(self::QUEUE, $out, LOCK_EX);
        }
        return $attempted;
    }

    private static function log(string $line): void
    {
        @file_put_contents(self::LOG, date('Y-m-d H:i:s') . ' ' . $line . "\n", FILE_APPEND | LOCK_EX);
    }
}

A7LeadaiBotStatus::register();
