<?php
/**
 * A7 Task Report — per-user task history for the Worktime grid (Time and reports → Worktime).
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_task_report.php
 * Loaded from: init.php (A7_TASK_REPORT block, see deploy_task_report.php)
 *
 *   - main:OnProlog -> adds /bitrix/js/a7_task_report.js on /timeman/ pages
 *                      (the script puts a "Task report" button under every user name in the grid)
 *   - A7TaskReport::fetch() -> tasks the user CREATED or is RESPONSIBLE for, listed on the day they were
 *                              added and the day they were completed (PKT)
 *   - A7TaskReport::canView() -> everyone sees his own report; admins + department heads see all
 *
 * The report page itself is /bitrix/tools/a7_task_report.php (a7_task_report_page.php).
 */

use Bitrix\Main\EventManager;

// Guard on a constant, not class_exists(): PHP declares the class below before this line runs,
// so a class_exists() guard would always return early and register() would never be called.
if (defined('A7_TASK_REPORT_LOADED')) {
    return;
}
define('A7_TASK_REPORT_LOADED', true);

final class A7TaskReport
{
    public const JS_PATH = '/bitrix/js/a7_task_report.js';
    public const TZ = 'Asia/Karachi';
    public const MAX_DAYS = 366;
    public const MAX_ROWS = 2000;

    /** b_tasks.STATUS => [label, css class] */
    public const STATUSES = [
        1 => ['New', 'new'],
        2 => ['Pending', 'pending'],
        3 => ['In progress', 'progress'],
        4 => ['Awaiting control', 'control'],
        5 => ['Completed', 'done'],
        6 => ['Deferred', 'deferred'],
        7 => ['Declined', 'declined'],
    ];

    public static function register(): void
    {
        $em = EventManager::getInstance();
        $em->addEventHandler('main', 'OnProlog', [__CLASS__, 'onProlog']);
        // Fallback: the head script does not reach every page (same as Lead Guard) — add it before </body>.
        $em->addEventHandler('main', 'OnEndBufferContent', [__CLASS__, 'onEndBufferContent']);
    }

    /** main:OnEndBufferContent(&$content): make sure /timeman/ pages carry the config + script. */
    public static function onEndBufferContent(&$content): void
    {
        global $USER;
        try {
            if (PHP_SAPI === 'cli' || !is_string($content) || $content === '') {
                return;
            }
            $path = (string) parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH);
            if (strpos($path, '/timeman/') !== 0 || !is_object($USER) || !$USER->IsAuthorized()) {
                return;
            }
            $pos = strripos($content, '</body>');
            if ($pos === false || strpos($content, 'a7_task_report.js') !== false) {
                return; // not an HTML page, or the head script is already there
            }
            $file = (string) ($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
            if (!is_file($file)) {
                return;
            }
            $tag = self::cfgTag((int) $USER->GetID())
                . '<script src="' . self::JS_PATH . '?v=' . filemtime($file) . '"></script>';
            $content = substr($content, 0, $pos) . $tag . "\n" . substr($content, $pos);
        } catch (\Throwable $e) {
            self::log(__FUNCTION__ . " error: " . $e->getMessage() . " @" . $e->getFile() . ":" . $e->getLine()); // never break a portal page
        }
    }

    private static function cfgTag(int $me): string
    {
        $cfg = ['me' => $me, 'all' => self::canViewAll($me), 'lead' => [], 'admin' => false, 'att' => false];
        // Lead report: admins only, button only on rows of people who work leads.
        try {
            $lib = (string) ($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/include/a7_lead_report.php';
            if (is_readable($lib)) {
                require_once $lib;
            }
            if (class_exists('A7LeadReport') && A7LeadReport::isAdmin($me)) {
                $cfg['lead'] = A7LeadReport::workerIds();
                $cfg['admin'] = true; // attendance report button
            }
        } catch (\Throwable $e) {
            self::log('lead cfg error: ' . $e->getMessage());
        }
        // Attendance report: admins + HR viewers from a7_attendance.config.php.
        try {
            $lib = (string) ($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/include/a7_attendance.php';
            if (is_readable($lib)) {
                require_once $lib;
            }
            $cfg['att'] = class_exists('A7Attendance') && A7Attendance::canView($me);
        } catch (\Throwable $e) {
            self::log('attendance cfg error: ' . $e->getMessage());
        }
        return '<script>window.A7TaskReportCfg=' . json_encode($cfg) . ';</script>';
    }

    /** main:OnProlog — script only on Time and reports pages, for logged-in users. */
    public static function onProlog(): void
    {
        global $APPLICATION, $USER;
        try {
            $path = (string) parse_url((string) ($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH);
            if (strpos($path, '/timeman/') !== 0) {
                return;
            }
            if (!is_object($USER) || !$USER->IsAuthorized()) {
                return;
            }
            if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
                return;
            }
            if (method_exists($APPLICATION, 'AddHeadString')) {
                $APPLICATION->AddHeadString(self::cfgTag((int) $USER->GetID()), true);
            }
            $file = (string) ($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
            $version = is_readable($file) ? (string) @filemtime($file) : (string) time();
            $APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . $version);
        } catch (\Throwable $e) {
            self::log(__FUNCTION__ . " error: " . $e->getMessage() . " @" . $e->getFile() . ":" . $e->getLine()); // never break a portal page
        }
    }

    /** May $viewerId open the task report of $targetId? Everyone: own report. Admins + department heads: everyone. */
    public static function canView(int $viewerId, int $targetId): bool
    {
        if ($viewerId <= 0 || $targetId <= 0) {
            return false;
        }
        return $viewerId === $targetId || self::canViewAll($viewerId);
    }

    /** Admin (group 1) or head (UF_HEAD) of at least one company-structure department. */
    public static function canViewAll(int $viewerId): bool
    {
        static $cache = [];
        if ($viewerId <= 0) {
            return false;
        }
        if (isset($cache[$viewerId])) {
            return $cache[$viewerId];
        }
        $ok = in_array(1, array_map('intval', \CUser::GetUserGroup($viewerId)), true);
        if (!$ok && \Bitrix\Main\Loader::includeModule('intranet')) {
            try {
                $ok = count((array) \CIntranetUtils::GetSubordinateDepartments($viewerId, false)) > 0;
            } catch (\Throwable $e) {
                $ok = false;
            }
        }
        return $cache[$viewerId] = $ok;
    }

    /**
     * Task activity of a user between $from and $to (Y-m-d, PKT, inclusive).
     * A task (user is creator or responsible) is listed on the day it was ADDED and on the day it was
     * COMPLETED (once, with both marks, when that is the same day).
     *
     * @param string $show all | completed | added | open
     * @return array{days: array<string, array>, summary: array, truncated: bool}
     */
    public static function fetch(int $userId, string $from, string $to, string $show = 'all'): array
    {
        $tz = new \DateTimeZone(self::TZ);
        $utc = new \DateTimeZone('UTC');
        $fromLocal = new \DateTime($from . ' 00:00:00', $tz);
        $toLocal = (new \DateTime($to . ' 00:00:00', $tz))->modify('+1 day');
        $fromUtc = (clone $fromLocal)->setTimezone($utc)->format('Y-m-d H:i:s');
        $toUtc = (clone $toLocal)->setTimezone($utc)->format('Y-m-d H:i:s');

        $sql = "SELECT ID, TITLE, STATUS, CREATED_BY, RESPONSIBLE_ID, CREATED_DATE, CLOSED_DATE, DEADLINE
                FROM b_tasks
                WHERE ZOMBIE = 'N'
                  AND (CREATED_BY = {$userId} OR RESPONSIBLE_ID = {$userId})
                  AND (
                        (CREATED_DATE >= '{$fromUtc}' AND CREATED_DATE < '{$toUtc}')
                     OR (STATUS = 5 AND CLOSED_DATE >= '{$fromUtc}' AND CLOSED_DATE < '{$toUtc}')
                  )
                ORDER BY ID DESC
                LIMIT " . (self::MAX_ROWS + 1);
        $rows = \Bitrix\Main\Application::getConnection()->query($sql)->fetchAll();
        $truncated = count($rows) > self::MAX_ROWS;
        $rows = array_slice($rows, 0, self::MAX_ROWS);

        $userIds = [];
        foreach ($rows as $r) {
            $userIds[(int) $r['CREATED_BY']] = true;
            $userIds[(int) $r['RESPONSIBLE_ID']] = true;
        }
        $names = self::userNames(array_keys($userIds));

        $inRange = static fn(?\DateTime $d) => $d !== null && $d >= $fromLocal && $d < $toLocal;
        $now = new \DateTime('now', $tz);
        $days = [];
        $summary = ['added' => 0, 'completed' => 0, 'open' => 0, 'overdue' => 0];
        foreach ($rows as $r) {
            $created = self::toLocal($r['CREATED_DATE'], $tz);
            $closed = self::toLocal($r['CLOSED_DATE'], $tz);
            $deadline = self::toLocal($r['DEADLINE'], $tz);
            $status = (int) $r['STATUS'];
            $isDone = $status === 5;
            $isOpen = !$isDone && $status !== 7;
            $isOverdue = $isOpen && $deadline !== null && $deadline < $now;
            $addedIn = $inRange($created);
            $doneIn = $isDone && $inRange($closed);

            if ($addedIn) {
                $summary['added']++;
                if ($isOpen) {
                    $summary['open']++;
                }
                if ($isOverdue) {
                    $summary['overdue']++;
                }
            }
            if ($doneIn) {
                $summary['completed']++;
            }

            $createdBy = (int) $r['CREATED_BY'];
            $responsible = (int) $r['RESPONSIBLE_ID'];
            $base = [
                'id' => (int) $r['ID'],
                'title' => (string) $r['TITLE'],
                'status' => $status,
                'statusLabel' => self::STATUSES[$status][0] ?? ('Status ' . $status),
                'statusCss' => self::STATUSES[$status][1] ?? 'pending',
                'role' => $createdBy === $userId ? ($responsible === $userId ? 'self' : 'created') : 'assigned',
                'createdBy' => $names[$createdBy] ?? ('#' . $createdBy),
                'responsible' => $names[$responsible] ?? ('#' . $responsible),
                'createdAt' => $created ? $created->format('d M, h:i A') : '',
                'deadline' => $deadline ? $deadline->format('d M, h:i A') : '',
                'closedAt' => $closed ? $closed->format('d M, h:i A') : '',
                'overdue' => $isOverdue,
            ];

            // One entry per (day, task): the add day and/or the completion day.
            $entries = [];
            if ($addedIn && ($show === 'all' || $show === 'added' || ($show === 'open' && $isOpen))) {
                $entries[$created->format('Y-m-d')] = ['added' => true, 'completed' => false, 'ts' => $created->getTimestamp()];
            }
            if ($doneIn && ($show === 'all' || $show === 'completed')) {
                $k = $closed->format('Y-m-d');
                if (isset($entries[$k])) {
                    $entries[$k]['completed'] = true;
                    $entries[$k]['ts'] = max($entries[$k]['ts'], $closed->getTimestamp());
                } else {
                    $entries[$k] = ['added' => false, 'completed' => true, 'ts' => $closed->getTimestamp()];
                }
            }
            foreach ($entries as $day => $e) {
                $time = $e['completed'] ? $closed : $created;
                $days[$day][] = $base + [
                    'added' => $e['added'],
                    'completed' => $e['completed'],
                    'time' => $time->format('h:i A'),
                    'ts' => $e['ts'],
                ];
            }
        }

        krsort($days);
        foreach ($days as &$list) {
            usort($list, static fn($a, $b) => $b['ts'] <=> $a['ts']);
        }
        unset($list);

        return ['days' => $days, 'summary' => $summary, 'truncated' => $truncated];
    }

    /**
     * Day / Week / Month / Custom period from GET (used by the task and the lead report pages). Dates PKT.
     *
     * @return array{mode:string,date:string,month:string,from:string,to:string,title:string,
     *               prev:array,next:array,isCurrent:bool,today:string,months:array}
     *   prev/next = GET overrides for the ‹ › links.
     */
    public static function period(array $get): array
    {
        $tz = new \DateTimeZone(self::TZ);
        $now = new \DateTime('now', $tz);
        $t = $now->format('Y-m-d');
        $d = static fn(string $ymd) => new \DateTime($ymd . ' 00:00:00', $tz);
        $validDate = static fn($v) => is_string($v) && preg_match('/^\d{4}-\d{2}-\d{2}$/', $v)
            && ($x = \DateTime::createFromFormat('!Y-m-d', $v)) && $x->format('Y-m-d') === $v;
        $validMonth = static fn($v) => is_string($v) && preg_match('/^\d{4}-(0[1-9]|1[0-2])$/', $v);

        $mode = in_array($get['mode'] ?? '', ['day', 'week', 'month', 'range'], true) ? $get['mode'] : 'month';
        $date = $validDate($get['date'] ?? null) ? $get['date'] : $t;
        $month = $validMonth($get['month'] ?? null) ? $get['month'] : $now->format('Y-m');

        switch ($mode) {
            case 'day':
                $from = $to = $date;
                $title = $d($date)->format('l, d F Y');
                $prev = ['date' => $d($date)->modify('-1 day')->format('Y-m-d')];
                $next = ['date' => $d($date)->modify('+1 day')->format('Y-m-d')];
                break;
            case 'week':
                $mon = $d($date)->modify('-' . ((int) $d($date)->format('N') - 1) . ' days');
                $from = $mon->format('Y-m-d');
                $to = (clone $mon)->modify('+6 days')->format('Y-m-d');
                $title = 'Week ' . $mon->format('d M') . ' – ' . $d($to)->format('d M Y');
                $prev = ['date' => $d($date)->modify('-7 days')->format('Y-m-d')];
                $next = ['date' => $d($date)->modify('+7 days')->format('Y-m-d')];
                break;
            case 'range':
                $from = $validDate($get['from'] ?? null) ? $get['from'] : $d($t)->modify('-6 days')->format('Y-m-d');
                $to = $validDate($get['to'] ?? null) ? $get['to'] : $t;
                if ($from > $to) {
                    [$from, $to] = [$to, $from];
                }
                if ((int) $d($from)->diff($d($to))->days >= self::MAX_DAYS) {
                    $from = $d($to)->modify('-' . (self::MAX_DAYS - 1) . ' days')->format('Y-m-d');
                }
                $title = $d($from)->format('d M Y') . ' – ' . $d($to)->format('d M Y');
                $len = (int) $d($from)->diff($d($to))->days + 1;
                $prev = ['from' => $d($from)->modify("-{$len} days")->format('Y-m-d'), 'to' => $d($from)->modify('-1 day')->format('Y-m-d')];
                $next = ['from' => $d($to)->modify('+1 day')->format('Y-m-d'), 'to' => $d($to)->modify("+{$len} days")->format('Y-m-d')];
                break;
            default: // month
                $from = $month . '-01';
                $to = $d($from)->modify('last day of this month')->format('Y-m-d');
                $title = $d($from)->format('F Y');
                $prev = ['month' => $d($from)->modify('-1 month')->format('Y-m')];
                $next = ['month' => $d($from)->modify('+1 month')->format('Y-m')];
        }

        $months = [];
        for ($i = 0, $m = $d($now->format('Y-m-01')); $i < 24; $i++, $m->modify('-1 month')) {
            $months[$m->format('Y-m')] = $m->format('F Y');
        }

        return [
            'mode' => $mode, 'date' => $date, 'month' => $month, 'from' => $from, 'to' => $to, 'title' => $title,
            'prev' => $prev, 'next' => $next, 'isCurrent' => $to >= $t, 'today' => $t, 'months' => $months,
        ];
    }

    /** Query string for a report page: keeps only the GET keys the mode needs. */
    public static function periodQuery(array $state, array $over = []): string
    {
        $q = array_merge($state, $over);
        $keep = array_merge(['user_id', 'mode', 'show', 'late'], match ($q['mode'] ?? 'month') {
            'day', 'week' => ['date'],
            'month' => ['month'],
            default => ['from', 'to'],
        });
        return '?' . http_build_query(array_filter(array_intersect_key($q, array_flip($keep)), static fn($v) => $v !== '' && $v !== null));
    }

    public static function log(string $msg): void
    {
        @file_put_contents('/home/bitrix/a7_task_report.log', gmdate('Y-m-d H:i:s') . ' ' . $msg . "\n", FILE_APPEND);
    }

    public static function userName(int $id): string
    {
        return self::userNames([$id])[$id] ?? ('#' . $id);
    }

    /** @return array<int, string> */
    private static function userNames(array $ids): array
    {
        $ids = array_values(array_filter(array_map('intval', $ids)));
        if (!$ids) {
            return [];
        }
        $out = [];
        $rs = \CUser::GetList('id', 'asc', ['ID' => implode('|', $ids)], ['FIELDS' => ['ID', 'NAME', 'LAST_NAME', 'SECOND_NAME', 'LOGIN']]);
        while ($u = $rs->Fetch()) {
            $name = trim(\CUser::FormatName(\CSite::GetNameFormat(false), $u, true, false));
            $out[(int) $u['ID']] = $name !== '' ? $name : (string) $u['LOGIN'];
        }
        return $out;
    }

    /** Bitrix DateTime (UTC in DB) -> PHP DateTime in PKT. */
    private static function toLocal($value, \DateTimeZone $tz): ?\DateTime
    {
        if ($value instanceof \Bitrix\Main\Type\DateTime) {
            return (new \DateTime('@' . $value->getTimestamp()))->setTimezone($tz);
        }
        if (is_string($value) && $value !== '') {
            return (new \DateTime($value, new \DateTimeZone('UTC')))->setTimezone($tz);
        }
        return null;
    }
}

A7TaskReport::register();
