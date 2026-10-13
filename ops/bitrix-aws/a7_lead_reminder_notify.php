<?php

/**
 * Lead responsible: first ping 2 minutes before reminder time (with sound),
 * then every 2 hours until 7pm Dubai if they missed it / no lead activity.
 * Sunday off for follow-ups. Does not change activity assignee or other CRM behavior.
 */

if (!defined('B_PROLOG_INCLUDED') && !defined('A7_LEAD_REMINDER_LIB')) {
    return;
}

const A7_LEAD_REMINDER_OFFSET_SECONDS = 120;
const A7_LEAD_REMINDER_GRACE_SECONDS = 60;
const A7_LEAD_REMINDER_FOLLOWUP_SECONDS = 7200;
const A7_LEAD_REMINDER_TZ = 'Asia/Dubai';
const A7_LEAD_REMINDER_FOLLOWUP_START_HOUR = 7;
const A7_LEAD_REMINDER_FOLLOWUP_END_HOUR = 19;
const A7_LEAD_REMINDER_AGENT = 'a7_lead_reminder_scan();';

function a7_lead_reminder_ensure_agent(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;

    if (!class_exists('CAgent')) {
        return;
    }

    $existing = CAgent::GetList([], ['NAME' => A7_LEAD_REMINDER_AGENT])->Fetch();
    if (!is_array($existing) || empty($existing['ID'])) {
        CAgent::AddAgent(A7_LEAD_REMINDER_AGENT, '', 'N', 60, '', 'Y');
        return;
    }

    $update = [];
    if (($existing['ACTIVE'] ?? 'Y') !== 'Y') {
        $update['ACTIVE'] = 'Y';
    }
    $nextTs = 0;
    if (!empty($existing['NEXT_EXEC']) && function_exists('MakeTimeStamp')) {
        $nextTs = (int)MakeTimeStamp($existing['NEXT_EXEC'], FORMAT_DATETIME);
    }
    if ($nextTs > 0 && $nextTs < (time() - 90)) {
        $update['NEXT_EXEC'] = ConvertTimeStamp(time() + 15, 'FULL');
    }
    if ($update) {
        CAgent::Update((int)$existing['ID'], $update);
    }
}

function a7_lead_reminder_ensure_table(): void
{
    static $ready = false;
    if ($ready) {
        return;
    }
    global $DB;
    if (!is_object($DB)) {
        return;
    }
    $DB->Query(
        'CREATE TABLE IF NOT EXISTS a7_lead_reminder_state (
            ACTIVITY_ID INT UNSIGNED NOT NULL PRIMARY KEY,
            LEAD_ID INT UNSIGNED NOT NULL,
            ASSIGNED_BY_ID INT UNSIGNED NOT NULL,
            DEADLINE_TS INT UNSIGNED NOT NULL,
            FIRST_SENT_AT INT UNSIGNED NOT NULL,
            LAST_SENT_AT INT UNSIGNED NOT NULL,
            STOPPED CHAR(1) NOT NULL DEFAULT "N",
            INDEX ix_a7_lr_follow (STOPPED, LAST_SENT_AT)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8',
        true
    );
    $ready = true;
}

function a7_lead_reminder_scan(): string
{
    a7_lead_reminder_ensure_agent();
    a7_lead_reminder_ensure_table();

    if (!class_exists('\Bitrix\Main\Loader')) {
        return A7_LEAD_REMINDER_AGENT;
    }
    if (!\Bitrix\Main\Loader::includeModule('crm') || !\Bitrix\Main\Loader::includeModule('im')) {
        return A7_LEAD_REMINDER_AGENT;
    }
    if (!class_exists('\Bitrix\Crm\ActivityTable')) {
        return A7_LEAD_REMINDER_AGENT;
    }

    $nowTs = time();
    $windowStart = \Bitrix\Main\Type\DateTime::createFromTimestamp($nowTs - A7_LEAD_REMINDER_GRACE_SECONDS);
    $windowEnd = \Bitrix\Main\Type\DateTime::createFromTimestamp($nowTs + A7_LEAD_REMINDER_OFFSET_SECONDS);

    $rows = \Bitrix\Crm\ActivityTable::getList([
        'select' => [
            'ID',
            'OWNER_TYPE_ID',
            'OWNER_ID',
            'SUBJECT',
            'DEADLINE',
            'AUTHOR_ID',
            'RESPONSIBLE_ID',
            'COMPLETED',
        ],
        'filter' => [
            '=OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
            '=COMPLETED' => 'N',
            '>=DEADLINE' => $windowStart,
            '<=DEADLINE' => $windowEnd,
        ],
        'limit' => 120,
    ]);

    while ($activity = $rows->fetch()) {
        a7_lead_reminder_notify_if_needed($activity, 'first');
    }

    try {
        $tz = new \DateTimeZone(A7_LEAD_REMINDER_TZ);
        $dayStart = (new \DateTime('today', $tz))->getTimestamp();
    } catch (\Throwable $e) {
        $dayStart = $nowTs - 86400;
    }
    $catchRows = \Bitrix\Crm\ActivityTable::getList([
        'select' => [
            'ID',
            'OWNER_TYPE_ID',
            'OWNER_ID',
            'SUBJECT',
            'DEADLINE',
            'AUTHOR_ID',
            'RESPONSIBLE_ID',
            'COMPLETED',
        ],
        'filter' => [
            '=OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
            '=COMPLETED' => 'N',
            '>=DEADLINE' => \Bitrix\Main\Type\DateTime::createFromTimestamp($dayStart),
            '<=DEADLINE' => \Bitrix\Main\Type\DateTime::createFromTimestamp($nowTs),
        ],
        'limit' => 120,
    ]);
    while ($activity = $catchRows->fetch()) {
        a7_lead_reminder_notify_if_needed($activity, 'first');
    }

    a7_lead_reminder_process_followups();

    return A7_LEAD_REMINDER_AGENT;
}

function a7_lead_reminder_on_activity_saved($activityId, $fields = null): void
{
    a7_lead_reminder_ensure_agent();
    a7_lead_reminder_ensure_table();

    $activityId = (int)$activityId;
    if ($activityId <= 0) {
        return;
    }
    if (!class_exists('\Bitrix\Main\Loader') || !\Bitrix\Main\Loader::includeModule('crm')) {
        return;
    }
    if (!class_exists('\Bitrix\Crm\ActivityTable')) {
        return;
    }

    $activity = \Bitrix\Crm\ActivityTable::getList([
        'select' => [
            'ID',
            'OWNER_TYPE_ID',
            'OWNER_ID',
            'SUBJECT',
            'DEADLINE',
            'AUTHOR_ID',
            'RESPONSIBLE_ID',
            'COMPLETED',
        ],
        'filter' => ['=ID' => $activityId],
        'limit' => 1,
    ])->fetch();

    if (!is_array($activity)) {
        return;
    }

    if ((string)($activity['COMPLETED'] ?? 'N') === 'Y') {
        a7_lead_reminder_stop((int)$activity['ID']);
        return;
    }

    $deadlineTs = a7_lead_reminder_deadline_ts($activity['DEADLINE'] ?? null);
    if ($deadlineTs === null) {
        return;
    }

    $secondsLeft = $deadlineTs - time();
    if ($secondsLeft <= A7_LEAD_REMINDER_OFFSET_SECONDS) {
        if ($secondsLeft >= -A7_LEAD_REMINDER_GRACE_SECONDS || a7_lead_reminder_is_same_dubai_day($deadlineTs)) {
            a7_lead_reminder_notify_if_needed($activity, 'first');
        }
    }
}

function a7_lead_reminder_notify_if_needed(array $activity, string $kind = 'first'): void
{
    if ((string)($activity['COMPLETED'] ?? 'N') === 'Y') {
        a7_lead_reminder_stop((int)($activity['ID'] ?? 0));
        return;
    }
    if ((int)($activity['OWNER_TYPE_ID'] ?? 0) !== (int)\CCrmOwnerType::Lead) {
        return;
    }

    $activityId = (int)($activity['ID'] ?? 0);
    $leadId = (int)($activity['OWNER_ID'] ?? 0);
    if ($activityId <= 0 || $leadId <= 0) {
        return;
    }

    $deadlineTs = a7_lead_reminder_deadline_ts($activity['DEADLINE'] ?? null);
    if ($deadlineTs === null || $deadlineTs > 2000000000) {
        return;
    }

    if ($kind === 'first') {
        $secondsLeft = $deadlineTs - time();
        if ($secondsLeft > A7_LEAD_REMINDER_OFFSET_SECONDS) {
            return;
        }
        if ($secondsLeft < -A7_LEAD_REMINDER_GRACE_SECONDS && !a7_lead_reminder_is_same_dubai_day($deadlineTs)) {
            return;
        }
    }

    $lead = a7_lead_reminder_load_lead($leadId);
    if ($lead === null) {
        return;
    }

    $recipients = a7_lead_reminder_recipient_ids($activity, $lead);
    if (!$recipients) {
        return;
    }

    if ($kind === 'followup') {
        if (a7_lead_reminder_lead_has_activity($leadId, $activityId, $deadlineTs)) {
            a7_lead_reminder_stop($activityId);
            return;
        }
        if (!a7_lead_reminder_is_followup_hours()) {
            return;
        }
    }

    if ($kind === 'first' && a7_lead_reminder_first_already_marked($activityId, $deadlineTs)) {
        return;
    }

    $slot = $kind === 'first' ? 'first' : ('fu' . (int)floor(time() / 60));
    $tag = 'A7|LEAD_REMINDER|' . $activityId . '|' . $deadlineTs . '|' . $slot;
    if (a7_lead_reminder_already_sent($tag)) {
        return;
    }

    $heading = $lead['heading'];
    $url = '/crm/lead/details/' . $leadId . '/';
    $when = a7_lead_reminder_format_deadline($activity['DEADLINE'] ?? null, (int)$lead['assignedById']);
    $subject = trim((string)($activity['SUBJECT'] ?? ''));
    if ($subject === '') {
        $subject = 'Action required';
    }

    if ($kind === 'followup') {
        $title = 'Missed lead reminder';
        $message = 'No activity on this lead yet. Time to call / action required: [url='
            . $url . ']' . htmlspecialcharsbx($heading) . '[/url]';
        $push = 'Missed reminder: action required on ' . $heading;
    } else {
        $title = 'Lead reminder';
        $message = 'Time to call / action required: [url='
            . $url . ']' . htmlspecialcharsbx($heading) . '[/url]';
        $push = 'Time to call / action required: ' . $heading;
    }
    if ($when !== '') {
        $message .= "\nWhen: " . htmlspecialcharsbx($when);
    }
    if ($subject !== '') {
        $message .= "\n" . htmlspecialcharsbx($subject);
    }

    $sent = false;
    foreach ($recipients as $toUserId) {
        $when = a7_lead_reminder_format_deadline($activity['DEADLINE'] ?? null, $toUserId);
        $userTag = $tag . '|' . $toUserId;
        if (a7_lead_reminder_already_sent($userTag)) {
            $sent = true;
            continue;
        }
        if (a7_lead_reminder_send_notify(
            $toUserId,
            $userTag,
            $title,
            $message,
            $push,
            [
                'title' => $title,
                'text' => $heading,
                'subject' => $subject,
                'when' => $when,
                'url' => $url,
                'leadId' => $leadId,
                'kind' => $kind,
            ]
        )) {
            $sent = true;
        }
    }
    if (!$sent) {
        return;
    }

    $nowTs = time();
    $ownerId = (int)$lead['assignedById'];
    if ($kind === 'first') {
        a7_lead_reminder_mark_first($activityId, $leadId, $ownerId > 0 ? $ownerId : (int)$recipients[0], $deadlineTs, $nowTs);
    } else {
        a7_lead_reminder_touch_last($activityId, $nowTs);
    }
}

function a7_lead_reminder_process_followups(): void
{
    global $DB;
    if (!is_object($DB) || !a7_lead_reminder_is_followup_hours()) {
        return;
    }

    $cutoff = time() - A7_LEAD_REMINDER_FOLLOWUP_SECONDS;
    $res = $DB->Query(
        'SELECT ACTIVITY_ID, LEAD_ID, ASSIGNED_BY_ID, DEADLINE_TS, FIRST_SENT_AT, LAST_SENT_AT
         FROM a7_lead_reminder_state
         WHERE STOPPED="N" AND LAST_SENT_AT<=' . (int)$cutoff . '
         LIMIT 40'
    );
    if (!$res) {
        return;
    }

    while ($state = $res->Fetch()) {
        $activityId = (int)$state['ACTIVITY_ID'];
        if (!a7_lead_reminder_is_same_dubai_day((int)$state['FIRST_SENT_AT'])) {
            a7_lead_reminder_stop($activityId);
            continue;
        }
        $activity = \Bitrix\Crm\ActivityTable::getList([
            'select' => [
                'ID',
                'OWNER_TYPE_ID',
                'OWNER_ID',
                'SUBJECT',
                'DEADLINE',
                'AUTHOR_ID',
                'RESPONSIBLE_ID',
                'COMPLETED',
            ],
            'filter' => ['=ID' => $activityId],
            'limit' => 1,
        ])->fetch();

        if (!is_array($activity) || (string)($activity['COMPLETED'] ?? 'N') === 'Y') {
            a7_lead_reminder_stop($activityId);
            continue;
        }

        a7_lead_reminder_notify_if_needed($activity, 'followup');
    }
}

function a7_lead_reminder_is_same_dubai_day(int $firstSentAt): bool
{
    if ($firstSentAt <= 0) {
        return false;
    }
    try {
        $tz = new \DateTimeZone(A7_LEAD_REMINDER_TZ);
        $first = (new \DateTime('@' . $firstSentAt))->setTimezone($tz);
        $now = new \DateTime('now', $tz);
    } catch (\Throwable $e) {
        return false;
    }

    return $first->format('Y-m-d') === $now->format('Y-m-d');
}

function a7_lead_reminder_is_followup_hours(): bool
{
    try {
        $local = new \DateTime('now', new \DateTimeZone(A7_LEAD_REMINDER_TZ));
    } catch (\Throwable $e) {
        return false;
    }

    if ((int)$local->format('w') === 0) {
        return false;
    }

    $hour = (int)$local->format('G');
    return $hour >= A7_LEAD_REMINDER_FOLLOWUP_START_HOUR && $hour < A7_LEAD_REMINDER_FOLLOWUP_END_HOUR;
}

function a7_lead_reminder_lead_has_activity(int $leadId, int $reminderActivityId, int $sinceTs): bool
{
    if ($leadId <= 0 || !class_exists('\Bitrix\Crm\ActivityTable')) {
        return false;
    }

    $since = \Bitrix\Main\Type\DateTime::createFromTimestamp($sinceTs);
    $row = \Bitrix\Crm\ActivityTable::getList([
        'select' => ['ID'],
        'filter' => [
            '=OWNER_TYPE_ID' => \CCrmOwnerType::Lead,
            '=OWNER_ID' => $leadId,
            '!=ID' => $reminderActivityId,
            '>CREATED' => $since,
        ],
        'limit' => 1,
    ])->fetch();

    return is_array($row);
}

function a7_lead_reminder_send_notify(
    int $toUserId,
    string $tag,
    string $title,
    string $message,
    string $push,
    array $popup = []
): bool {
    if ($toUserId <= 0) {
        return false;
    }

    $ok = false;
    if (class_exists('CIMNotify') && \Bitrix\Main\Loader::includeModule('im')) {
        $notifyType = defined('IM_NOTIFY_SYSTEM') ? IM_NOTIFY_SYSTEM : 4;
        $id = CIMNotify::Add([
            'TO_USER_ID' => $toUserId,
            'FROM_USER_ID' => 0,
            'NOTIFY_TYPE' => $notifyType,
            'NOTIFY_MODULE' => 'im',
            'NOTIFY_EVENT' => 'default',
            'NOTIFY_TAG' => $tag,
            'NOTIFY_TITLE' => $title,
            'NOTIFY_MESSAGE' => $message,
            'NOTIFY_MESSAGE_OUT' => $message,
            'PUSH_MESSAGE' => $push,
        ]);
        $ok = !empty($id);
    }

    if (\Bitrix\Main\Loader::includeModule('pull') && class_exists('\Bitrix\Pull\Event')) {
        \Bitrix\Pull\Event::add($toUserId, [
            'module_id' => 'a7leadreminder',
            'command' => 'popup',
            'params' => [
                'title' => (string)($popup['title'] ?? $title),
                'text' => (string)($popup['text'] ?? ''),
                'subject' => (string)($popup['subject'] ?? ''),
                'when' => (string)($popup['when'] ?? ''),
                'url' => (string)($popup['url'] ?? ''),
                'leadId' => (int)($popup['leadId'] ?? 0),
                'kind' => (string)($popup['kind'] ?? 'first'),
            ],
        ]);
        if (method_exists('\Bitrix\Pull\Event', 'send')) {
            \Bitrix\Pull\Event::send();
        }
        $ok = true;
    }

    return $ok;
}

function a7_lead_reminder_first_already_marked(int $activityId, int $deadlineTs): bool
{
    global $DB;
    if (!is_object($DB) || $activityId <= 0) {
        return false;
    }
    a7_lead_reminder_ensure_table();
    $res = $DB->Query(
        'SELECT FIRST_SENT_AT, DEADLINE_TS FROM a7_lead_reminder_state
         WHERE ACTIVITY_ID=' . $activityId . ' LIMIT 1'
    );
    if (!$res) {
        return false;
    }
    $row = $res->Fetch();
    if (!is_array($row)) {
        return false;
    }

    return (int)$row['DEADLINE_TS'] === $deadlineTs && (int)$row['FIRST_SENT_AT'] > 0;
}

function a7_lead_reminder_mark_first(int $activityId, int $leadId, int $assignedById, int $deadlineTs, int $nowTs): void
{
    global $DB;
    if (!is_object($DB) || $activityId <= 0) {
        return;
    }
    a7_lead_reminder_ensure_table();
    $DB->Query(
        'INSERT INTO a7_lead_reminder_state
            (ACTIVITY_ID, LEAD_ID, ASSIGNED_BY_ID, DEADLINE_TS, FIRST_SENT_AT, LAST_SENT_AT, STOPPED)
         VALUES ('
            . $activityId . ',' . $leadId . ',' . $assignedById . ','
            . $deadlineTs . ',' . $nowTs . ',' . $nowTs . ',"N")
         ON DUPLICATE KEY UPDATE
            LEAD_ID=' . $leadId . ',
            ASSIGNED_BY_ID=' . $assignedById . ',
            DEADLINE_TS=' . $deadlineTs . ',
            LAST_SENT_AT=' . $nowTs . ',
            STOPPED="N"',
        true
    );
}

function a7_lead_reminder_touch_last(int $activityId, int $nowTs): void
{
    global $DB;
    if (!is_object($DB) || $activityId <= 0) {
        return;
    }
    $DB->Query(
        'UPDATE a7_lead_reminder_state SET LAST_SENT_AT=' . (int)$nowTs
        . ' WHERE ACTIVITY_ID=' . (int)$activityId,
        true
    );
}

function a7_lead_reminder_stop(int $activityId): void
{
    global $DB;
    if (!is_object($DB) || $activityId <= 0) {
        return;
    }
    a7_lead_reminder_ensure_table();
    $DB->Query(
        'UPDATE a7_lead_reminder_state SET STOPPED="Y" WHERE ACTIVITY_ID=' . (int)$activityId,
        true
    );
}

function a7_lead_reminder_load_lead(int $leadId): ?array
{
    if ($leadId <= 0 || !class_exists('\Bitrix\Crm\Service\Container')) {
        return null;
    }

    $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
    if ($factory === null) {
        return null;
    }

    $item = $factory->getItem($leadId);
    if ($item === null) {
        return null;
    }

    $heading = trim((string)$item->getHeading());
    if ($heading === '') {
        $heading = 'Lead #' . $leadId;
    }

    return [
        'assignedById' => (int)$item->getAssignedById(),
        'heading' => $heading,
    ];
}

function a7_lead_reminder_already_sent(string $tag): bool
{
    global $DB;
    if (!is_object($DB) || $tag === '') {
        return false;
    }

    $sql = "SELECT ID FROM b_im_message WHERE NOTIFY_TAG='" . $DB->ForSql($tag) . "' LIMIT 1";
    $res = $DB->Query($sql);
    if (!$res) {
        return false;
    }

    return (bool)$res->Fetch();
}

function a7_lead_reminder_deadline_ts($deadline): ?int
{
    if ($deadline instanceof \Bitrix\Main\Type\DateTime) {
        $ts = $deadline->getTimestamp();
        return $ts > 0 ? $ts : null;
    }
    if ($deadline instanceof \DateTimeInterface) {
        return $deadline->getTimestamp();
    }
    if (!is_string($deadline) || $deadline === '') {
        return null;
    }
    if (strpos($deadline, '9999') === 0) {
        return null;
    }
    $ts = strtotime($deadline);
    return $ts !== false ? $ts : null;
}

function a7_lead_reminder_format_deadline($deadline, int $userId): string
{
    if ($deadline instanceof \Bitrix\Main\Type\DateTime && class_exists('CCrmDateTimeHelper')) {
        try {
            return CCrmDateTimeHelper::getUserTime($deadline, $userId > 0 ? $userId : null, true)
                ->format('d.m.Y H:i');
        } catch (\Throwable $e) {
            return $deadline->format('d.m.Y H:i');
        }
    }
    $ts = a7_lead_reminder_deadline_ts($deadline);
    return $ts ? date('d.m.Y H:i', $ts) : '';
}

function a7_lead_reminder_recipient_ids(array $activity, array $lead): array
{
    $ids = [];
    foreach ([
        (int)($lead['assignedById'] ?? 0),
        (int)($activity['RESPONSIBLE_ID'] ?? 0),
        (int)($activity['AUTHOR_ID'] ?? 0),
    ] as $uid) {
        if ($uid > 0) {
            $ids[$uid] = $uid;
        }
    }
    return array_values($ids);
}

function a7_lead_reminder_user_is_recipient(int $userId, array $activity, array $lead): bool
{
    if ($userId <= 0) {
        return false;
    }
    return in_array($userId, a7_lead_reminder_recipient_ids($activity, $lead), true);
}

function a7_lead_reminder_pending_for_user(int $userId): array
{
    global $DB;
    if ($userId <= 0 || !is_object($DB)) {
        return [];
    }
    a7_lead_reminder_ensure_table();
    if (!class_exists('\Bitrix\Main\Loader') || !\Bitrix\Main\Loader::includeModule('crm')) {
        return [];
    }
    if (!class_exists('\Bitrix\Crm\ActivityTable')) {
        return [];
    }

    $since = time() - 2700;
    $res = $DB->Query(
        'SELECT ACTIVITY_ID, LEAD_ID, ASSIGNED_BY_ID, DEADLINE_TS, LAST_SENT_AT
         FROM a7_lead_reminder_state
         WHERE STOPPED="N" AND LAST_SENT_AT>=' . (int)$since . '
         ORDER BY LAST_SENT_AT DESC
         LIMIT 12',
        true
    );
    if (!$res) {
        return [];
    }

    $items = [];
    while ($state = $res->Fetch()) {
        $activityId = (int)$state['ACTIVITY_ID'];
        $leadId = (int)$state['LEAD_ID'];
        $activity = \Bitrix\Crm\ActivityTable::getList([
            'select' => [
                'ID',
                'OWNER_TYPE_ID',
                'OWNER_ID',
                'SUBJECT',
                'DEADLINE',
                'AUTHOR_ID',
                'RESPONSIBLE_ID',
                'COMPLETED',
            ],
            'filter' => ['=ID' => $activityId],
            'limit' => 1,
        ])->fetch();
        if (!is_array($activity) || (string)($activity['COMPLETED'] ?? 'N') === 'Y') {
            continue;
        }
        $lead = a7_lead_reminder_load_lead($leadId);
        if ($lead === null || !a7_lead_reminder_user_is_recipient($userId, $activity, $lead)) {
            continue;
        }
        $subject = trim((string)($activity['SUBJECT'] ?? ''));
        if ($subject === '') {
            $subject = 'Action required';
        }
        $items[] = [
            'title' => 'Lead reminder',
            'text' => $lead['heading'],
            'subject' => $subject,
            'when' => a7_lead_reminder_format_deadline($activity['DEADLINE'] ?? null, $userId),
            'url' => '/crm/lead/details/' . $leadId . '/',
            'leadId' => $leadId,
            'activityId' => $activityId,
            'deadlineTs' => (int)$state['DEADLINE_TS'],
            'kind' => 'first',
        ];
        if (count($items) >= 3) {
            break;
        }
    }

    return $items;
}

function a7_lead_reminder_on_prolog(): void
{
    global $APPLICATION, $USER;
    a7_lead_reminder_ensure_agent();
    if (!is_object($USER) || !$USER->IsAuthorized()) {
        return;
    }
    if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
        return;
    }
    $scriptPath = '/bitrix/js/a7_lead_reminder.js';
    $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
    $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
    $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);

    $items = a7_lead_reminder_pending_for_user((int)$USER->GetID());
    if ($items && class_exists('\Bitrix\Main\Web\Json')) {
        $json = \Bitrix\Main\Web\Json::encode($items);
        $APPLICATION->AddHeadString(
            '<script>window.A7_LEAD_REMINDER_BOOT=' . $json . ';</script>',
            true
        );
    }
}

