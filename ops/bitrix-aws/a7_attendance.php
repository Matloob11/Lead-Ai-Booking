<?php
/**
 * A7 Attendance — monthly (or any period) attendance of all employees from Bitrix clock-in / clock-out.
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_attendance.php
 * Page:        /bitrix/tools/a7_attendance.php (a7_attendance_page.php), admins + config 'viewers' (HR).
 * Settings:    /bitrix/php_interface/a7_attendance.config.php (office hours, grace, holidays …)
 *
 * Data: b_timeman_entries (DATE_START / DATE_FINISH in UTC). A day belongs to the Pakistan date of the clock-in.
 * Per working day (not weekend, not holiday, not before the user registered, not in the future):
 *   Present  = at least one clock-in that day
 *   Late     = first clock-in after office start (hours valid that day, see 'history') + late threshold (page filter, default grace_minutes);
 *              lateBy = minutes after office start, summed per user as lateMin
 *   Early    = last clock-out before office end
 *   No out   = the day was never closed
 *   Leave    = no clock-in but an Absence-chart entry covers the day
 *   Off      = no clock-in, no leave. Today counts once office start + grace has passed.
 * Working days so far = Mon–Sat (minus holidays) from the period start up to today — the same number for everyone,
 * except people who joined inside the period.
 */

if (defined('A7_ATTENDANCE_LOADED')) {
    return;
}
define('A7_ATTENDANCE_LOADED', true);

final class A7Attendance
{
    public const TZ = 'Asia/Karachi';

    public static function config(): array
    {
        static $cfg = null;
        if ($cfg === null) {
            $path = (string) ($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_attendance.config.php';
            $cfg = is_readable($path) ? (array) include $path : [];
            $cfg += [
                'offices' => [
                    'pk' => ['name' => 'Pakistan office', 'start' => '10:00', 'end' => '19:30',
                        'history' => [['until' => '2026-09-20', 'start' => '09:00', 'end' => '19:00']]],
                    'dxb' => ['name' => 'Dubai office', 'start' => '11:00', 'end' => '20:00'],
                ],
                'default_office' => 'pk', 'dubai_timezones' => ['Asia/Dubai'], 'user_office' => [],
                'grace_minutes' => 15, 'weekend' => [7], 'holidays' => [], 'auto_users' => [],
                'exclude_users' => [1], 'active_days' => 60, 'viewers' => [], 'enabled' => true,
            ];
        }
        return $cfg;
    }

    /** Admins (group 1) and the users listed in config 'viewers' (e.g. HR). */
    public static function canView(int $uid): bool
    {
        if ($uid <= 0 || empty(self::config()['enabled'])) {
            return false; // switched off in config: nobody sees the report
        }
        if (in_array($uid, array_map('intval', (array) self::config()['viewers']), true)) {
            return true;
        }
        return in_array(1, array_map('intval', \CUser::GetUserGroup($uid)), true);
    }

    /** Office hours valid on $day: the first 'history' entry with until >= $day, else the current hours. */
    public static function hoursOn(array $office, string $day): array
    {
        $hist = (array) ($office['history'] ?? []);
        usort($hist, static fn($a, $b) => strcmp((string) $a['until'], (string) $b['until']));
        foreach ($hist as $h) {
            if ($day <= (string) $h['until']) {
                return [(string) $h['start'], (string) $h['end']];
            }
        }
        return [(string) $office['start'], (string) $office['end']];
    }

    private static function hm(string $v): int
    {
        [$h, $m] = array_map('intval', explode(':', $v) + [0, 0]);
        return $h * 3600 + $m * 60;
    }

    /**
     * @return array{users: array<int, array>, days: string[]}
     *   users[uid] = [name, office, officeName, auto, totals…, days => [Y-m-d => day row]]
     */
    /**
     * @param int|null $lateMinutes late threshold in minutes after office start (null = config grace_minutes)
     */
    public static function build(string $from, string $to, ?int $onlyUser = null, ?int $lateMinutes = null): array
    {
        $cfg = self::config();
        $lateMinutes ??= (int) $cfg['grace_minutes'];
        $tz = new \DateTimeZone(self::TZ);
        $c = \Bitrix\Main\Application::getConnection();
        $fromTs = (new \DateTime($from . ' 00:00:00', $tz))->getTimestamp();
        $toTs = (new \DateTime($to . ' 00:00:00', $tz))->modify('+1 day')->getTimestamp();
        $f = gmdate('Y-m-d H:i:s', $fromTs);
        $t = gmdate('Y-m-d H:i:s', $toTs);
        $now = time();
        $today = (new \DateTime('now', $tz))->format('Y-m-d');
        $exclude = array_map('intval', (array) $cfg['exclude_users']);

        /* ---------- who is listed ---------- */
        $activeSince = gmdate('Y-m-d H:i:s', $now - (int) $cfg['active_days'] * 86400);
        $userFilter = $onlyUser ? ' AND u.ID = ' . (int) $onlyUser : '';
        $users = $c->query("
            SELECT u.ID, u.NAME, u.LAST_NAME, u.LOGIN, u.TIME_ZONE, u.DATE_REGISTER, u.WORK_POSITION
            FROM b_user u
            WHERE u.ACTIVE = 'Y' AND (u.EXTERNAL_AUTH_ID IS NULL OR u.EXTERNAL_AUTH_ID = ''){$userFilter}
              AND EXISTS (SELECT 1 FROM b_timeman_entries e WHERE e.USER_ID = u.ID
                          AND ((e.DATE_START >= '{$activeSince}') OR (e.DATE_START >= '{$f}' AND e.DATE_START < '{$t}')))
        ")->fetchAll();

        /* ---------- calendar of the period ---------- */
        $days = [];
        for ($d = new \DateTime($from . ' 00:00:00', $tz); $d->getTimestamp() < $toTs; $d->modify('+1 day')) {
            $days[] = $d->format('Y-m-d');
        }
        $holidays = (array) $cfg['holidays'];
        $weekend = array_map('intval', (array) $cfg['weekend']);

        /* ---------- clock-ins ---------- */
        $ids = array_map('intval', array_column($users, 'ID'));
        $entries = [];
        if ($ids) {
            $rs = $c->query("
                SELECT USER_ID, DATE_START, DATE_FINISH, DURATION, TIME_LEAKS
                FROM b_timeman_entries
                WHERE DATE_START >= '{$f}' AND DATE_START < '{$t}' AND USER_ID IN (" . implode(',', $ids) . ")
                ORDER BY DATE_START
            ");
            while ($r = $rs->fetch()) {
                $s = $r['DATE_START'] instanceof \Bitrix\Main\Type\DateTime ? $r['DATE_START']->getTimestamp() : 0;
                $e = $r['DATE_FINISH'] instanceof \Bitrix\Main\Type\DateTime ? $r['DATE_FINISH']->getTimestamp() : 0;
                if ($s <= 0) {
                    continue;
                }
                $day = (new \DateTime('@' . $s))->setTimezone($tz)->format('Y-m-d');
                $worked = (int) $r['DURATION'] > 0 ? (int) $r['DURATION'] : ($e > $s ? $e - $s - (int) $r['TIME_LEAKS'] : 0);
                $entries[(int) $r['USER_ID']][$day][] = ['in' => $s, 'out' => $e, 'worked' => max(0, $worked)];
            }
        }

        /* ---------- leave (Absence chart) ---------- */
        $leave = self::leaves($ids, $from, $to);

        /* ---------- per user ---------- */
        $out = [];
        foreach ($users as $u) {
            $uid = (int) $u['ID'];
            if (in_array($uid, $exclude, true)) {
                continue;
            }
            $office = $cfg['user_office'][$uid]
                ?? (in_array((string) $u['TIME_ZONE'], (array) $cfg['dubai_timezones'], true) ? 'dxb' : $cfg['default_office']);
            $o = $cfg['offices'][$office] ?? reset($cfg['offices']);
            $reg = $u['DATE_REGISTER'] instanceof \Bitrix\Main\Type\DateTime
                ? (new \DateTime('@' . $u['DATE_REGISTER']->getTimestamp()))->setTimezone($tz)->format('Y-m-d') : '';

            $row = [
                'id' => $uid,
                'name' => trim(\CUser::FormatName('#NAME# #LAST_NAME#', $u, true, false)) ?: (string) $u['LOGIN'],
                'position' => (string) $u['WORK_POSITION'],
                'office' => $office,
                'officeName' => $o['name'],
                'officeHours' => $o['start'] . '–' . $o['end'],
                'auto' => (string) ($cfg['auto_users'][$uid] ?? ''),
                'joined' => ($reg !== '' && $reg > $from && $reg <= $to) ? $reg : '', // joined inside the period
                'working' => 0, 'present' => 0, 'absent' => 0, 'leave' => 0, 'late' => 0, 'early' => 0,
                'noOut' => 0, 'offDayWork' => 0, 'workedSec' => 0, 'inSum' => 0, 'inCount' => 0, 'lateMin' => 0,
                'days' => [],
            ];
            foreach ($days as $day) {
                $dt = new \DateTime($day . ' 00:00:00', $tz);
                $dayTs = $dt->getTimestamp();
                $isOff = in_array((int) $dt->format('N'), $weekend, true);
                $holiday = $holidays[$day] ?? null;
                $e = $entries[$uid][$day] ?? [];
                [$hStart, $hEnd] = self::hoursOn($o, $day);                     // office hours valid that day
                $startSec = self::hm($hStart);
                $endSec = self::hm($hEnd);
                $lateAfter = $startSec + $lateMinutes * 60 + 59;                  // late filter (15 / 30 / 60 min …)
                $countAfter = $startSec + (int) $cfg['grace_minutes'] * 60 + 59;  // today becomes a counted day after this
                $d = ['hours' => $hStart . '–' . $hEnd, 'status' => '', 'in' => 0, 'out' => 0, 'worked' => 0, 'late' => false, 'lateBy' => 0, 'early' => false, 'noOut' => false, 'note' => ''];

                if ($e) {
                    $first = $e[0]['in'];
                    $lastOut = 0;
                    $open = false;
                    foreach ($e as $x) {
                        $d['worked'] += $x['worked'];
                        if ($x['out'] > 0) {
                            $lastOut = max($lastOut, $x['out']);
                        } else {
                            $open = true;
                        }
                    }
                    $d['in'] = $first;
                    $d['out'] = $open ? 0 : $lastOut;
                    $inSec = $first - $dayTs;
                    $d['late'] = !$isOff && !$holiday && $inSec > $lateAfter;
                    $d['lateBy'] = $d['late'] ? intdiv($inSec - $startSec, 60) : 0; // minutes after office start
                    $d['early'] = !$isOff && !$holiday && !$open && $lastOut > 0 && ($lastOut - $dayTs) < $endSec;
                    $d['noOut'] = $open && $day < $today;
                    $row['workedSec'] += $d['worked'];
                    if ($isOff || $holiday) {
                        $d['status'] = 'offwork';
                        $d['note'] = $holiday ?: 'Worked on day off';
                        $row['offDayWork']++;
                    } else {
                        $d['status'] = $d['late'] ? 'late' : 'present';
                        $row['working']++;
                        $row['present']++;
                        $row['inSum'] += $inSec;
                        $row['inCount']++;
                        if ($d['late']) {
                            $row['late']++;
                            $row['lateMin'] += $d['lateBy'];
                        }
                        if ($d['early']) {
                            $row['early']++;
                        }
                    }
                    if ($d['noOut']) {
                        $row['noOut']++;
                    }
                } elseif ($isOff) {
                    $d['status'] = 'weekend';
                } elseif ($holiday) {
                    $d['status'] = 'holiday';
                    $d['note'] = $holiday;
                } elseif ($reg !== '' && $day < $reg) {
                    $d['status'] = 'notjoined';
                } elseif ($day > $today || ($day === $today && $now <= $dayTs + $countAfter)) {
                    $d['status'] = 'upcoming'; // future, or today before office start + grace

                } elseif (isset($leave[$uid][$day])) {
                    $d['status'] = 'leave';
                    $d['note'] = $leave[$uid][$day];
                    $row['working']++;
                    $row['leave']++;
                } else {
                    $d['status'] = 'off';
                    $row['working']++;
                    $row['absent']++;
                }
                $row['days'][$day] = $d;
            }
            $row['avgIn'] = $row['inCount'] ? intdiv($row['inSum'], $row['inCount']) : null;
            $out[$uid] = $row;
        }
        uasort($out, static fn($a, $b) => strcasecmp($a['name'], $b['name']));

        // Period calendar for the header: all working days, and the ones that have started so far.
        $all = $sofar = 0;
        $pkStart = self::hm((string) (reset($cfg['offices'])['start'] ?? '10:00')) + (int) $cfg['grace_minutes'] * 60;
        foreach ($days as $day) {
            $dt = new \DateTime($day . ' 00:00:00', $tz);
            if (in_array((int) $dt->format('N'), $weekend, true) || isset($holidays[$day])) {
                continue;
            }
            $all++;
            if ($day < $today || ($day === $today && $now >= $dt->getTimestamp() + $pkStart)) {
                $sofar++;
            }
        }

        return ['users' => $out, 'days' => $days, 'workingAll' => $all, 'workingSoFar' => $sofar, 'lateMinutes' => $lateMinutes];
    }

    /** Absence chart entries: [uid][Y-m-d] = type/name. Empty when the chart is not used. */
    private static function leaves(array $ids, string $from, string $to): array
    {
        $out = [];
        if (!$ids || !\Bitrix\Main\Loader::includeModule('iblock')) {
            return $out;
        }
        $iblock = (int) \Bitrix\Main\Config\Option::get('intranet', 'iblock_absence', 0);
        if ($iblock <= 0) {
            return $out;
        }
        $tz = new \DateTimeZone(self::TZ);
        try {
            $rs = \CIBlockElement::GetList([], [
                'IBLOCK_ID' => $iblock,
                'ACTIVE' => 'Y',
                '<=DATE_ACTIVE_FROM' => ConvertTimeStamp((new \DateTime($to . ' 23:59:59', $tz))->getTimestamp(), 'FULL'),
                '>=DATE_ACTIVE_TO' => ConvertTimeStamp((new \DateTime($from . ' 00:00:00', $tz))->getTimestamp(), 'FULL'),
                'PROPERTY_USER' => $ids,
            ], false, false, ['ID', 'NAME', 'DATE_ACTIVE_FROM', 'DATE_ACTIVE_TO', 'PROPERTY_USER', 'PROPERTY_ABSENCE_TYPE']);
            while ($r = $rs->Fetch()) {
                $uid = (int) $r['PROPERTY_USER_VALUE'];
                $a = MakeTimeStamp($r['DATE_ACTIVE_FROM']);
                $b = MakeTimeStamp($r['DATE_ACTIVE_TO']);
                if (!$uid || !$a || !$b) {
                    continue;
                }
                $label = trim((string) ($r['PROPERTY_ABSENCE_TYPE_VALUE'] ?: $r['NAME'])) ?: 'Leave';
                for ($d = (new \DateTime('@' . $a))->setTimezone($tz)->setTime(0, 0); $d->getTimestamp() <= $b; $d->modify('+1 day')) {
                    $out[$uid][$d->format('Y-m-d')] = $label;
                }
            }
        } catch (\Throwable $e) {
            // leave data is optional
        }
        return $out;
    }
}
