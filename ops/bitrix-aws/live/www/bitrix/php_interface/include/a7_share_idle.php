<?php
/**
 * A7 Share-idle alert — a lead was shared with someone (made Observer, Lead Guard share row) and
 * that person did no work on it for 4 hours -> sticky notification + popup on every CRM screen
 * until they open the lead or press Dismiss / "Got it".
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_share_idle.php
 * Loaded from: init.php (block A7_SHARE_IDLE, see deploy_share_idle.php)
 * Agent:       A7ShareIdle::agent();  every 300 s
 * Popup:       /bitrix/js/a7_share_idle.js + /bitrix/tools/a7_share_idle_api.php
 * Log:         /home/bitrix/a7_share_idle.log
 *
 * "Work" = anything the shared user did on the lead after the share: call (Bitrix telephony, 3CX),
 * activity / to-do created, stage change, own comment, field edit (Lead Guard note), WhatsApp note in
 * his name. Only shares created after the go-live time are watched (no flood of old shares).
 */

if (defined('A7_SHARE_IDLE_LOADED')) {
    return;
}
define('A7_SHARE_IDLE_LOADED', true);

final class A7ShareIdle
{
    public const IDLE_SECONDS = 4 * 3600;
    public const TABLE = 'a7_share_idle';
    public const JS_PATH = '/bitrix/js/a7_share_idle.js';
    public const TAG = 'A7_SHARE_IDLE';
    public const AGENT = 'A7ShareIdle::agent();';
    public const LOG = '/home/bitrix/a7_share_idle.log';
    public const WA_PREFIX = 'WhatsApp · Agent · ';

    public static function register(): void
    {
        $em = \Bitrix\Main\EventManager::getInstance();
        $em->addEventHandler('main', 'OnProlog', [__CLASS__, 'onProlog']);
        $em->addEventHandler('im', 'OnBeforeConfirmNotify', [__CLASS__, 'onConfirmNotify']);
    }

    /** Go-live (UTC 'Y-m-d H:i:s'): shares older than this are never alerted. Set by the deploy script. */
    public static function goLive(): string
    {
        $v = (string) \Bitrix\Main\Config\Option::get('main', 'a7_share_idle_go_live', '');
        return $v !== '' ? $v : gmdate('Y-m-d H:i:s');
    }

    public static function log(string $msg): void
    {
        @file_put_contents(self::LOG, gmdate('Y-m-d H:i:s') . ' ' . $msg . "\n", FILE_APPEND);
    }

    public static function ensureTable(): void
    {
        static $done = false;
        if ($done) {
            return;
        }
        \Bitrix\Main\Application::getConnection()->query('CREATE TABLE IF NOT EXISTS ' . self::TABLE . ' (
            LEAD_ID INT UNSIGNED NOT NULL,
            USER_ID INT UNSIGNED NOT NULL,
            SHARED DATETIME NOT NULL,
            SHARED_BY INT UNSIGNED NOT NULL DEFAULT 0,
            ALERTED DATETIME NOT NULL,
            ACKED DATETIME NULL,
            ACK_HOW VARCHAR(16) NULL,
            PRIMARY KEY (LEAD_ID, USER_ID, SHARED),
            KEY IX_USER_PENDING (USER_ID, ACKED)
        )');
        $done = true;
    }

    /* ------------------------------------------------------------------ */
    /* Agent: find idle shares                                              */
    /* ------------------------------------------------------------------ */

    public static function agent(): string
    {
        try {
            self::scan(true);
        } catch (\Throwable $e) {
            self::log('agent error: ' . $e->getMessage());
        }
        return self::AGENT;
    }

    /**
     * @param bool $apply false = dry run (returns what would be alerted, writes nothing)
     * @return array list of [lead, user, shared, sharedBy, title]
     */
    public static function scan(bool $apply, ?string $goLiveOverride = null): array
    {
        if (!\Bitrix\Main\Loader::includeModule('crm')) {
            return [];
        }
        $c = \Bitrix\Main\Application::getConnection();
        $has = $c->query("SHOW TABLES LIKE 'a7_lead_share'")->fetch();
        if (!$has) {
            return [];
        }
        self::ensureTable();
        $goLive = $goLiveOverride ?? self::goLive();
        $cut = gmdate('Y-m-d H:i:s', time() - self::IDLE_SECONDS);
        $sql = "
            SELECT s.LEAD_ID, s.USER_ID, s.SHARED_BY, s.CREATED, l.TITLE, l.ASSIGNED_BY_ID, l.STATUS_ID
            FROM a7_lead_share s
            JOIN b_crm_lead l ON l.ID = s.LEAD_ID
            JOIN b_user u ON u.ID = s.USER_ID AND u.ACTIVE = 'Y'
            JOIN b_crm_observer o ON o.ENTITY_TYPE_ID = 1 AND o.ENTITY_ID = s.LEAD_ID AND o.USER_ID = s.USER_ID
            LEFT JOIN " . self::TABLE . " a ON a.LEAD_ID = s.LEAD_ID AND a.USER_ID = s.USER_ID AND a.SHARED = s.CREATED
            WHERE s.CREATED >= '" . $c->getSqlHelper()->forSql($goLive) . "' AND s.CREATED <= '{$cut}'
              AND a.LEAD_ID IS NULL
              AND l.ASSIGNED_BY_ID <> s.USER_ID
              AND l.STATUS_ID NOT IN ('CONVERTED', 'JUNK')
              AND s.USER_ID NOT IN (SELECT USER_ID FROM b_user_group WHERE GROUP_ID = 1)
            ORDER BY s.CREATED
            LIMIT 200";
        $out = [];
        foreach ($c->query($sql)->fetchAll() as $r) {
            $lead = (int) $r['LEAD_ID'];
            $uid = (int) $r['USER_ID'];
            $shared = $r['CREATED'] instanceof \Bitrix\Main\Type\DateTime
                ? gmdate('Y-m-d H:i:s', $r['CREATED']->getTimestamp()) : (string) $r['CREATED'];
            if (self::workedSince($lead, $uid, $shared)) {
                continue;
            }
            $row = ['lead' => $lead, 'user' => $uid, 'shared' => $shared, 'sharedBy' => (int) $r['SHARED_BY'], 'title' => (string) $r['TITLE']];
            $out[] = $row;
            if ($apply) {
                self::alert($row);
            }
        }
        return $out;
    }

    /** Did $uid do any work on lead $lead after $since (UTC)? */
    public static function workedSince(int $lead, int $uid, string $since): bool
    {
        $c = \Bitrix\Main\Application::getConnection();
        $s = "'" . $c->getSqlHelper()->forSql($since) . "'";
        $checks = [
            // Bitrix telephony call by him
            "SELECT 1 FROM b_voximplant_statistic WHERE CRM_ENTITY_TYPE = 'LEAD' AND CRM_ENTITY_ID = {$lead} AND PORTAL_USER_ID = {$uid} AND CALL_START_DATE >= {$s} LIMIT 1",
            // any activity he created, or a 3CX call where he is responsible
            "SELECT 1 FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID = a.ID AND b.OWNER_TYPE_ID = 1 AND b.OWNER_ID = {$lead}
             WHERE a.CREATED >= {$s} AND (a.AUTHOR_ID = {$uid} OR (a.PROVIDER_ID = 'A7_3CX' AND a.RESPONSIBLE_ID = {$uid})) LIMIT 1",
            // stage change / comment / Lead Guard edit note written by him
            "SELECT 1 FROM b_crm_timeline t JOIN b_crm_timeline_bind b ON b.OWNER_ID = t.ID AND b.ENTITY_TYPE_ID = 1 AND b.ENTITY_ID = {$lead}
             WHERE t.CREATED >= {$s} AND t.AUTHOR_ID = {$uid} AND t.TYPE_ID IN (1, 3, 7) LIMIT 1",
        ];
        foreach ($checks as $q) {
            if ($c->query($q)->fetch()) {
                return true;
            }
        }
        // WhatsApp message sent by him (integration writes it as user 1 with his name in the text)
        $u = \CUser::GetByID($uid)->Fetch();
        if ($u) {
            $names = array_unique(array_filter([trim($u['NAME'] . ' ' . $u['LAST_NAME']), trim((string) $u['NAME'])]));
            foreach ($names as $n) {
                $like = "'" . $c->getSqlHelper()->forSql(self::WA_PREFIX . $n . ' · ') . "%'";
                $q = "SELECT 1 FROM b_crm_timeline t JOIN b_crm_timeline_bind b ON b.OWNER_ID = t.ID AND b.ENTITY_TYPE_ID = 1 AND b.ENTITY_ID = {$lead}
                      WHERE t.CREATED >= {$s} AND t.TYPE_ID = 7 AND t.AUTHOR_ID = 1 AND t.COMMENT LIKE {$like} LIMIT 1";
                if ($c->query($q)->fetch()) {
                    return true;
                }
            }
        }
        return false;
    }

    private static function alert(array $row): void
    {
        $c = \Bitrix\Main\Application::getConnection();
        $h = $c->getSqlHelper();
        $c->query('INSERT IGNORE INTO ' . self::TABLE . ' (LEAD_ID, USER_ID, SHARED, SHARED_BY, ALERTED) VALUES ('
            . (int) $row['lead'] . ', ' . (int) $row['user'] . ", '" . $h->forSql($row['shared']) . "', " . (int) $row['sharedBy'] . ', UTC_TIMESTAMP())');

        $title = trim($row['title']) !== '' ? trim($row['title']) : ('Lead #' . $row['lead']);
        $link = '/crm/lead/details/' . $row['lead'] . '/';
        $by = self::userName($row['sharedBy']);
        $msg = "⏰ You were added as observer on lead [URL={$link}]{$title}[/URL] (#{$row['lead']}) by {$by} 4 hours ago, "
            . "but there is no work on it from you yet. Please open the lead and work on it (call, comment, stage or activity).";
        self::notify((int) $row['user'], $msg, self::TAG . '|' . $row['lead'] . '|' . $row['user']);
        self::push((int) $row['user']);
        self::log("ALERT lead={$row['lead']} user={$row['user']} shared={$row['shared']} by={$row['sharedBy']}");
    }

    public static function notify(int $to, string $message, string $tag): void
    {
        if (!\Bitrix\Main\Loader::includeModule('im')) {
            return;
        }
        try {
            $fields = [
                'TO_USER_ID' => $to,
                'FROM_USER_ID' => 0,
                'NOTIFY_TYPE' => IM_NOTIFY_CONFIRM,
                'NOTIFY_MODULE' => 'crm',
                'NOTIFY_EVENT' => 'other',
                'NOTIFY_TAG' => $tag,
                'NOTIFY_MESSAGE' => $message,
                'NOTIFY_MESSAGE_OUT' => preg_replace('~\[/?URL[^\]]*\]~i', '', $message),
                'NOTIFY_BUTTONS' => [['TITLE' => 'Got it', 'VALUE' => 'Y', 'TYPE' => 'accept']],
            ];
            $id = \CIMNotify::Add($fields);
            if (!$id) {
                unset($fields['NOTIFY_BUTTONS']);
                $fields['NOTIFY_TYPE'] = IM_NOTIFY_SYSTEM;
                $id = \CIMNotify::Add($fields);
            }
            self::log("NOTIFY to={$to} tag={$tag} id=" . var_export($id, true));
        } catch (\Throwable $e) {
            self::log('notify error: ' . $e->getMessage());
        }
    }

    public static function push(int $to): void
    {
        try {
            if (\Bitrix\Main\Loader::includeModule('pull') && class_exists('\Bitrix\Pull\Event')) {
                \Bitrix\Pull\Event::add($to, ['module_id' => 'crm', 'command' => 'a7ShareIdle', 'params' => []]);
            }
        } catch (\Throwable $e) {
            self::log('push error: ' . $e->getMessage());
        }
    }

    /* ------------------------------------------------------------------ */
    /* Pending list / acknowledge                                           */
    /* ------------------------------------------------------------------ */

    public static function pending(int $uid): array
    {
        self::ensureTable();
        $c = \Bitrix\Main\Application::getConnection();
        $rows = $c->query('SELECT a.LEAD_ID, a.SHARED_BY, a.SHARED, a.ALERTED, l.TITLE FROM ' . self::TABLE . ' a
            JOIN b_crm_lead l ON l.ID = a.LEAD_ID
            WHERE a.USER_ID = ' . (int) $uid . ' AND a.ACKED IS NULL ORDER BY a.ALERTED DESC LIMIT 20')->fetchAll();
        $out = [];
        foreach ($rows as $r) {
            $shared = $r['SHARED'] instanceof \Bitrix\Main\Type\DateTime ? $r['SHARED']->getTimestamp() : strtotime((string) $r['SHARED'] . ' UTC');
            $out[] = [
                'lead' => (int) $r['LEAD_ID'],
                'title' => trim((string) $r['TITLE']) ?: ('Lead #' . $r['LEAD_ID']),
                'by' => self::userName((int) $r['SHARED_BY']),
                'hours' => max(4, (int) floor((time() - $shared) / 3600)),
                'url' => '/crm/lead/details/' . (int) $r['LEAD_ID'] . '/',
            ];
        }
        return $out;
    }

    /** Acknowledge one lead (or all when $lead = 0) for $uid; also removes the bell notification. */
    public static function ack(int $uid, int $lead, string $how): int
    {
        self::ensureTable();
        $c = \Bitrix\Main\Application::getConnection();
        $where = 'USER_ID = ' . (int) $uid . ' AND ACKED IS NULL' . ($lead > 0 ? ' AND LEAD_ID = ' . (int) $lead : '');
        $leads = array_map('intval', array_column($c->query('SELECT LEAD_ID FROM ' . self::TABLE . ' WHERE ' . $where)->fetchAll(), 'LEAD_ID'));
        if (!$leads) {
            return 0;
        }
        $c->query('UPDATE ' . self::TABLE . " SET ACKED = UTC_TIMESTAMP(), ACK_HOW = '" . $c->getSqlHelper()->forSql(substr($how, 0, 16)) . "' WHERE " . $where);
        if ($how !== 'notify' && \Bitrix\Main\Loader::includeModule('im') && class_exists('CIMNotify')) {
            foreach ($leads as $l) {
                try {
                    \CIMNotify::DeleteByTag(self::TAG . '|' . $l . '|' . $uid);
                } catch (\Throwable $e) {
                }
            }
        }
        self::log('ACK user=' . $uid . ' leads=' . implode(',', $leads) . ' how=' . $how);
        return count($leads);
    }

    /** im:OnBeforeConfirmNotify — "Got it" in the bell. */
    public static function onConfirmNotify($module, $tag, $value, $notification = [])
    {
        try {
            if ($module !== 'crm' || !is_string($tag) || strpos($tag, self::TAG . '|') !== 0) {
                return null;
            }
            [, $lead, $uid] = array_map('intval', explode('|', $tag) + [0, 0, 0]);
            if ($lead > 0 && $uid > 0) {
                self::ack($uid, $lead, 'notify');
            }
            return ['result' => true, 'text' => 'Reminder dismissed.'];
        } catch (\Throwable $e) {
            self::log('onConfirmNotify error: ' . $e->getMessage());
            return null;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Page script on CRM screens                                           */
    /* ------------------------------------------------------------------ */

    public static function onProlog(): void
    {
        global $APPLICATION, $USER;
        try {
            if (PHP_SAPI === 'cli' || !is_object($USER) || !$USER->IsAuthorized() || !is_object($APPLICATION)) {
                return;
            }
            $path = (string) parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH);
            if (strpos($path, '/crm/') !== 0) {
                return;
            }
            $file = (string) ($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
            if (is_file($file) && method_exists($APPLICATION, 'AddHeadScript')) {
                $APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . filemtime($file));
            }
        } catch (\Throwable $e) {
            self::log('onProlog error: ' . $e->getMessage());
        }
    }

    private static function userName(int $id): string
    {
        if ($id <= 0) {
            return 'someone';
        }
        $u = \CUser::GetByID($id)->Fetch();
        return $u ? (trim($u['NAME'] . ' ' . $u['LAST_NAME']) ?: (string) $u['LOGIN']) : ('#' . $id);
    }
}

A7ShareIdle::register();
