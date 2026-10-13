<?php
/**
 * A7 Lead Report — what one agent did on CRM leads in a period (admins only).
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_lead_report.php
 * Used by: /bitrix/tools/a7_lead_report.php (a7_lead_report_page.php) and the Worktime button
 *          (A7TaskReport::cfgTag passes the agent list to a7_task_report.js).
 *
 * Only the agent's OWN work counts (checked on live data 2026-09-26):
 *   call       b_voximplant_statistic  PORTAL_USER_ID = agent, CRM_ENTITY_TYPE = LEAD
 *   call       b_crm_act PROVIDER_ID = A7_3CX, RESPONSIBLE_ID = agent (3CX recordings)
 *   stage      b_crm_timeline TYPE 3 (FIELD STATUS_ID), AUTHOR_ID = agent
 *   comment    b_crm_timeline TYPE 7, AUTHOR_ID = agent, not a Lead Guard note
 *   edit       b_crm_timeline TYPE 7 Lead Guard "field_edit" note, AUTHOR_ID = agent (the editor),
 *              + comment edits (SETTINGS.A7_EDITS) on the agent's own comments
 *   whatsapp   b_crm_timeline TYPE 7 "WhatsApp · Agent · <agent name> · …" (written by the integration as user 1)
 *   follow-up  b_crm_act PROVIDER_ID = CRM_TODO created by the agent
 * Automation (user 1 notes, WhatsApp retries/summaries, "Edited by Admin …", reminders) is never counted.
 *
 * Leads received = distinct leads that became the agent's in the period:
 *   b_crm_event "Responsible person changed" with EVENT_TEXT_2 = agent name (names only are stored there),
 *   plus leads created in the period whose first responsible was the agent.
 * A received lead is "worked" when the agent did any of the above on it after receiving it (inside the period).
 * All DB dates are UTC; days are Asia/Karachi.
 */

if (defined('A7_LEAD_REPORT_LOADED')) {
    return;
}
define('A7_LEAD_REPORT_LOADED', true);

final class A7LeadReport
{
    /** Automation account: every bulk note / rotation runs as this user, so it is never an "agent". */
    public const EXCLUDE_USERS = [1];
    public const LIST_LIMIT = 400;
    public const WA_PREFIX = 'WhatsApp · Agent · ';

    public static function isAdmin(int $uid): bool
    {
        return $uid > 0 && in_array(1, array_map('intval', \CUser::GetUserGroup($uid)), true);
    }

    /** Users who work leads (owner of a lead touched in 90 days, or lead calls in 90 days). Cached 10 min. */
    public static function workerIds(): array
    {
        $cache = \Bitrix\Main\Data\Cache::createInstance();
        if ($cache->initCache(600, 'a7_lead_report_workers_v2', '/a7_lead_report')) {
            return (array) $cache->getVars();
        }
        $c = \Bitrix\Main\Application::getConnection();
        $ids = [];
        $sqls = [
            "SELECT DISTINCT ASSIGNED_BY_ID U FROM b_crm_lead WHERE DATE_MODIFY > UTC_TIMESTAMP() - INTERVAL 90 DAY",
            "SELECT DISTINCT PORTAL_USER_ID U FROM b_voximplant_statistic WHERE CRM_ENTITY_TYPE = 'LEAD' AND CALL_START_DATE > UTC_TIMESTAMP() - INTERVAL 90 DAY",
            "SELECT DISTINCT a.RESPONSIBLE_ID U FROM b_crm_act a WHERE a.PROVIDER_ID = 'A7_3CX' AND a.CREATED > UTC_TIMESTAMP() - INTERVAL 90 DAY",
        ];
        foreach ($sqls as $sql) {
            foreach ($c->query($sql)->fetchAll() as $r) {
                $ids[(int) $r['U']] = true;
            }
        }
        $ids = array_diff(array_keys($ids), self::EXCLUDE_USERS, [0]);
        if ($ids) {
            // Real employees only: open-line widget users, bots, e-mail users etc. have EXTERNAL_AUTH_ID.
            $active = $c->query("SELECT ID FROM b_user WHERE ACTIVE = 'Y' AND (EXTERNAL_AUTH_ID IS NULL OR EXTERNAL_AUTH_ID = '')
                AND ID IN (" . implode(',', array_map('intval', $ids)) . ")")->fetchAll();
            $ids = array_map('intval', array_column($active, 'ID'));
        }
        sort($ids);
        if ($cache->startDataCache()) {
            $cache->endDataCache($ids);
        }
        return $ids;
    }

    /**
     * Names under which Bitrix wrote this user into b_crm_event / WhatsApp notes.
     * Variants that belong to more than one user are dropped (never guess).
     */
    public static function nameVariants(int $uid): array
    {
        static $byName = null;
        if ($byName === null) {
            $byName = [];
            $rs = \CUser::GetList('id', 'asc', [], ['FIELDS' => ['ID', 'NAME', 'LAST_NAME', 'SECOND_NAME', 'LOGIN']]);
            while ($u = $rs->Fetch()) {
                foreach (self::rawVariants($u) as $v) {
                    $byName[mb_strtolower($v)][(int) $u['ID']] = $v;
                }
            }
        }
        $u = \CUser::GetByID($uid)->Fetch();
        if (!$u) {
            return [];
        }
        $out = [];
        foreach (self::rawVariants($u) as $v) {
            $owners = $byName[mb_strtolower($v)] ?? [];
            if (count($owners) === 1 && isset($owners[$uid])) {
                $out[] = $v;
            }
        }
        return array_values(array_unique($out));
    }

    private static function rawVariants(array $u): array
    {
        $name = trim((string) $u['NAME']);
        $last = trim((string) $u['LAST_NAME']);
        $v = [
            trim(\CUser::FormatName('#NAME# #LAST_NAME#', $u, true, false)),
            trim(\CUser::FormatName(\CSite::GetNameFormat(false), $u, true, false)),
            trim($name . ' ' . $last),
        ];
        // Older renames seen in b_crm_event: "SAPNA" (now "SAPNA SAPNA"), "NABIHA NABIHA" (now "NABIHA").
        if ($name !== '' && ($last === '' || mb_strtolower($last) === mb_strtolower($name))) {
            $v[] = $name;
            $v[] = $name . ' ' . $name;
        }
        return array_values(array_filter(array_unique($v), static fn($x) => $x !== ''));
    }

    /**
     * @return array{summary: array, days: array, worked: array, notWorked: array, leads: array, names: array}
     */
    public static function build(int $uid, string $from, string $to): array
    {
        $tz = new \DateTimeZone('Asia/Karachi');
        $utc = new \DateTimeZone('UTC');
        $fromTs = (new \DateTime($from . ' 00:00:00', $tz))->getTimestamp();
        $toTs = (new \DateTime($to . ' 00:00:00', $tz))->modify('+1 day')->getTimestamp();
        $f = gmdate('Y-m-d H:i:s', $fromTs);
        $t = gmdate('Y-m-d H:i:s', $toTs);
        $c = \Bitrix\Main\Application::getConnection();
        $sq = static fn(string $s) => "'" . $c->getSqlHelper()->forSql($s) . "'";
        $ts = static fn($v) => $v instanceof \Bitrix\Main\Type\DateTime ? $v->getTimestamp()
            : (is_string($v) && $v !== '' ? (new \DateTime($v, $utc))->getTimestamp() : 0);
        $names = self::nameVariants($uid);
        $namesLower = array_map('mb_strtolower', $names);

        /* ---------- received ---------- */
        $received = [];   // leadId => first receive ts in period
        $receivedDays = []; // Y-m-d (PKT) => leadId => first receive ts that day (rotation: same lead on many days)
        $day = static fn(int $x) => (new \DateTime('@' . $x))->setTimezone($tz)->format('Y-m-d');
        $addReceived = static function (int $l, int $x) use (&$received, &$receivedDays, $day): void {
            if (!isset($received[$l]) || $x < $received[$l]) {
                $received[$l] = $x;
            }
            $dk = $day($x);
            if (!isset($receivedDays[$dk][$l]) || $x < $receivedDays[$dk][$l]) {
                $receivedDays[$dk][$l] = $x;
            }
        };
        $assignments = 0; // raw "responsible changed to agent" events (rotation makes this large)
        if ($names) {
            $in = implode(',', array_map($sq, $names));
            $rows = $c->query("
                SELECT r.ENTITY_ID L, e.DATE_CREATE D
                FROM b_crm_event e
                JOIN b_crm_event_relations r ON r.EVENT_ID = e.ID AND r.ENTITY_TYPE = 'LEAD' AND r.ENTITY_FIELD = 'ASSIGNED_BY_ID'
                WHERE e.DATE_CREATE >= '{$f}' AND e.DATE_CREATE < '{$t}' AND e.EVENT_TEXT_2 IN ({$in})
            ")->fetchAll();
            foreach ($rows as $r) {
                $assignments++;
                $l = (int) $r['L'];
                $x = $ts($r['D']);
                $addReceived($l, $x);
            }
        }
        // Leads created in the period whose FIRST responsible was the agent.
        $created = $c->query("SELECT ID, DATE_CREATE, ASSIGNED_BY_ID FROM b_crm_lead WHERE DATE_CREATE >= '{$f}' AND DATE_CREATE < '{$t}'")->fetchAll();
        $firstOwnerName = [];
        foreach (array_chunk(array_map('intval', array_column($created, 'ID')), 1000) as $chunk) {
            $rs = $c->query("
                SELECT r.ENTITY_ID L, e.EVENT_TEXT_1 N
                FROM b_crm_event_relations r JOIN b_crm_event e ON e.ID = r.EVENT_ID
                WHERE r.ENTITY_TYPE = 'LEAD' AND r.ENTITY_FIELD = 'ASSIGNED_BY_ID' AND r.ENTITY_ID IN (" . implode(',', $chunk) . ")
                ORDER BY e.ID ASC
            ");
            while ($r = $rs->fetch()) {
                $firstOwnerName[(int) $r['L']] ??= mb_strtolower(trim((string) $r['N']));
            }
        }
        foreach ($created as $r) {
            $l = (int) $r['ID'];
            $first = isset($firstOwnerName[$l]) ? in_array($firstOwnerName[$l], $namesLower, true) : ((int) $r['ASSIGNED_BY_ID'] === $uid);
            if ($first) {
                $x = $ts($r['DATE_CREATE']);
                $addReceived($l, $x);
            }
        }

        /* ---------- the agent's own actions ---------- */
        $actions = []; // [lead, ts, kind, detail]
        $calls = $c->query("
            SELECT CRM_ENTITY_ID L, CALL_START_DATE D, CALL_DURATION S, CALL_FAILED_CODE C
            FROM b_voximplant_statistic
            WHERE PORTAL_USER_ID = {$uid} AND CALL_START_DATE >= '{$f}' AND CALL_START_DATE < '{$t}' AND CRM_ENTITY_TYPE = 'LEAD'
        ")->fetchAll();
        foreach ($calls as $r) {
            $ok = (string) $r['C'] === '200' && (int) $r['S'] > 0;
            $actions[] = [(int) $r['L'], $ts($r['D']), 'call', $ok ? 'answered' : 'not answered'];
        }
        $acts = $c->query("
            SELECT b.OWNER_ID L, a.CREATED D, a.PROVIDER_ID P
            FROM b_crm_act a JOIN b_crm_act_bind b ON b.ACTIVITY_ID = a.ID AND b.OWNER_TYPE_ID = 1
            WHERE a.RESPONSIBLE_ID = {$uid} AND a.CREATED >= '{$f}' AND a.CREATED < '{$t}'
              AND (a.PROVIDER_ID = 'A7_3CX' OR (a.PROVIDER_ID = 'CRM_TODO' AND a.AUTHOR_ID = {$uid}))
        ")->fetchAll();
        foreach ($acts as $r) {
            $actions[] = [(int) $r['L'], $ts($r['D']), $r['P'] === 'A7_3CX' ? 'call' : 'followup', $r['P'] === 'A7_3CX' ? '3CX' : ''];
        }
        $waLike = $sq(self::WA_PREFIX . '%');
        $tl = $c->query("
            SELECT t.TYPE_ID, t.CREATED D, t.AUTHOR_ID A, t.SETTINGS S, LEFT(t.COMMENT, 160) M, b.ENTITY_ID L
            FROM b_crm_timeline t JOIN b_crm_timeline_bind b ON b.OWNER_ID = t.ID AND b.ENTITY_TYPE_ID = 1
            WHERE t.CREATED >= '{$f}' AND t.CREATED < '{$t}'
              AND ((t.TYPE_ID IN (3, 7) AND t.AUTHOR_ID = {$uid})
                OR (t.TYPE_ID = 7 AND t.AUTHOR_ID = 1 AND t.COMMENT LIKE {$waLike}))
        ")->fetchAll();
        foreach ($tl as $r) {
            $l = (int) $r['L'];
            $x = $ts($r['D']);
            if ((int) $r['A'] !== $uid) { // WhatsApp integration note: agent name is in the text
                $rest = mb_substr((string) $r['M'], mb_strlen(self::WA_PREFIX));
                $who = mb_strtolower(trim(explode(' · ', $rest, 2)[0]));
                if (in_array($who, $namesLower, true)) {
                    $actions[] = [$l, $x, 'whatsapp', ''];
                }
                continue;
            }
            $s = @unserialize((string) $r['S'], ['allowed_classes' => false]);
            $s = is_array($s) ? $s : [];
            if ((int) $r['TYPE_ID'] === 3) {
                if (($s['FIELD'] ?? '') === 'STATUS_ID') {
                    $actions[] = [$l, $x, 'stage', (string) ($s['FINISH_NAME'] ?? '')];
                }
                continue;
            }
            if (isset($s['A7_GUARD'])) {
                if (($s['A7_GUARD']['kind'] ?? '') === 'field_edit') {
                    $actions[] = [$l, $x, 'edit', ''];
                }
                continue; // other Lead Guard notes (shares …) are not lead work
            }
            $actions[] = [$l, $x, 'comment', ''];
        }
        // Edits of the agent's own comments (Lead Guard keeps them in SETTINGS.A7_EDITS, 'at' = server UTC).
        $f60 = gmdate('Y-m-d H:i:s', $fromTs - 60 * 86400);
        $ce = $c->query("
            SELECT t.SETTINGS S, b.ENTITY_ID L
            FROM b_crm_timeline t JOIN b_crm_timeline_bind b ON b.OWNER_ID = t.ID AND b.ENTITY_TYPE_ID = 1
            WHERE t.TYPE_ID = 7 AND t.AUTHOR_ID = {$uid} AND t.CREATED >= '{$f60}' AND t.CREATED < '{$t}'
              AND t.SETTINGS LIKE '%A7_EDITS%'
        ")->fetchAll();
        foreach ($ce as $r) {
            $s = @unserialize((string) $r['S'], ['allowed_classes' => false]);
            foreach ((array) ($s['A7_EDITS'] ?? []) as $e) {
                $dt = \DateTime::createFromFormat('d.m.Y H:i', (string) ($e['at'] ?? ''), $utc);
                if ($dt && $dt->getTimestamp() >= $fromTs && $dt->getTimestamp() < $toTs) {
                    $actions[] = [(int) $r['L'], $dt->getTimestamp(), 'edit', 'comment'];
                }
            }
        }

        /* ---------- aggregate ---------- */
        $kinds = ['call' => 0, 'answered' => 0, 'stage' => 0, 'comment' => 0, 'edit' => 0, 'whatsapp' => 0, 'followup' => 0];
        $perLead = [];   // lead => counts + first/last ts + stages
        $days = [];      // Y-m-d => counts
        $blankDay = ['received' => [], 'worked' => [], 'notWorked' => 0] + $kinds;
        usort($actions, static fn($a, $b) => $a[1] <=> $b[1]);
        foreach ($actions as [$l, $x, $k, $detail]) {
            if ($l <= 0) {
                continue;
            }
            $perLead[$l] ??= ['first' => $x, 'last' => $x, 'stages' => []] + $kinds;
            $perLead[$l][$k]++;
            $perLead[$l]['last'] = $x;
            $kinds[$k]++;
            $dk = $day($x);
            $days[$dk] ??= $blankDay;
            $days[$dk][$k]++;
            $days[$dk]['worked'][$l] = true;
            if ($k === 'call' && $detail === 'answered') {
                $perLead[$l]['answered']++;
                $kinds['answered']++;
                $days[$dk]['answered']++;
            }
            if ($k === 'stage' && $detail !== '') {
                $perLead[$l]['stages'][] = $detail;
            }
        }
        $leadActionTimes = [];
        foreach ($actions as [$al, $ax]) {
            $leadActionTimes[$al][] = $ax;
        }
        $workedSince = static function (int $l, int $since) use ($leadActionTimes): bool {
            foreach ($leadActionTimes[$l] ?? [] as $ax) {
                if ($ax >= $since) {
                    return true;
                }
            }
            return false;
        };
        // Period totals: each lead once, from its first arrival in the period.
        $notWorked = [];
        $workedReceived = 0;
        foreach ($received as $l => $x) {
            if ($workedSince($l, $x)) {
                $workedReceived++;
            } else {
                $notWorked[$l] = $x;
            }
        }
        // Day rows: leads that arrived that day (a rotated lead can arrive on several days).
        foreach ($receivedDays as $dk => $list) {
            $days[$dk] ??= $blankDay;
            foreach ($list as $l => $x) {
                $days[$dk]['received'][$l] = true;
                if (!$workedSince($l, $x)) {
                    $days[$dk]['notWorked']++;
                }
            }
        }
        krsort($days);
        foreach ($days as &$dd) {
            $dd['received'] = count($dd['received']);
            $dd['worked'] = count($dd['worked']);
        }
        unset($dd);

        /* ---------- lead details for the lists ---------- */
        uasort($perLead, static fn($a, $b) => $b['last'] <=> $a['last']);
        arsort($notWorked);
        $workedList = array_slice($perLead, 0, self::LIST_LIMIT, true);
        $notWorkedList = array_slice($notWorked, 0, self::LIST_LIMIT, true);
        $ids = array_unique(array_merge(array_keys($workedList), array_keys($notWorkedList)));
        $leads = [];
        if ($ids) {
            $status = [];
            foreach ($c->query("SELECT STATUS_ID, NAME FROM b_crm_status WHERE ENTITY_ID = 'STATUS'")->fetchAll() as $s) {
                $status[$s['STATUS_ID']] = $s['NAME'];
            }
            $owners = [];
            foreach (array_chunk(array_map('intval', $ids), 1000) as $chunk) {
                foreach ($c->query("SELECT ID, TITLE, STATUS_ID, ASSIGNED_BY_ID FROM b_crm_lead WHERE ID IN (" . implode(',', $chunk) . ")")->fetchAll() as $r) {
                    $leads[(int) $r['ID']] = [
                        'title' => (string) $r['TITLE'],
                        'stage' => $status[$r['STATUS_ID']] ?? (string) $r['STATUS_ID'],
                        'owner' => (int) $r['ASSIGNED_BY_ID'],
                    ];
                    $owners[(int) $r['ASSIGNED_BY_ID']] = true;
                }
            }
            $ownerNames = [];
            if ($owners) {
                $rs = \CUser::GetList('id', 'asc', ['ID' => implode('|', array_keys($owners))], ['FIELDS' => ['ID', 'NAME', 'LAST_NAME', 'SECOND_NAME', 'LOGIN']]);
                while ($u = $rs->Fetch()) {
                    $ownerNames[(int) $u['ID']] = trim(\CUser::FormatName('#NAME# #LAST_NAME#', $u, true, false)) ?: $u['LOGIN'];
                }
            }
            foreach ($leads as &$ld) {
                $ld['ownerName'] = $ownerNames[$ld['owner']] ?? ('#' . $ld['owner']);
            }
            unset($ld);
        }

        return [
            'summary' => [
                'received' => count($received),
                'assignments' => $assignments,
                'workedReceived' => $workedReceived,
                'notWorked' => count($notWorked),
                'workedTotal' => count($perLead),
            ] + $kinds,
            'days' => $days,
            'worked' => $workedList,
            'notWorked' => $notWorkedList,
            'leads' => $leads,
            'names' => $names,
            'truncated' => count($perLead) > self::LIST_LIMIT || count($notWorked) > self::LIST_LIMIT,
        ];
    }
}
