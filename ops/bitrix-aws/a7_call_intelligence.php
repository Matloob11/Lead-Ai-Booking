<?php

/**
 * A7 Call Intelligence for Telephony → Call details.
 *
 * Extends the first page only. Does not change recordings, CRM links,
 * comments, assessment, or native Bitrix transcript icons.
 */

if (!defined('B_PROLOG_INCLUDED') && !defined('A7_CI_LIB_ONLY')) {
    define('NO_KEEP_STATISTIC', true);
    define('STOP_STATISTICS', true);
    define('NO_AGENT_STATISTIC', true);
    define('DisableEventsCheck', true);
    require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
}

const A7_CI_STATUSES = ['PENDING', 'TRANSCRIBING', 'ANALYZING', 'COMPLETED', 'FAILED'];
const A7_CI_CUTOFF_VERSION = 'auto-new-20260905c';
const A7_CI_NEXT_ACTIONS = [
    'PROPERTY_VIEWING',
    'CALLBACK',
    'FOLLOW_UP',
    'SEND_PROPERTY_OPTIONS',
    'SEND_DETAILS',
    'NO_ACTION',
];
const A7_CI_SCORE_KEYS = [
    'greeting_intro',
    'company_intro',
    'requirement_understanding',
    'qualification',
    'listening',
    'communication',
    'manners',
    'product_knowledge',
    'closing_attempt',
    'next_step_confirmation',
    'customer_satisfaction',
    'compliance',
];
const A7_CI_REQ_KEYS = [
    'looking_for',
    'property_type',
    'community',
    'budget',
    'bedrooms',
    'move_in_date',
    'payment_method',
    'interest_level',
    'preferred_view',
    'proximity',
    'notes',
];

function a7_ci_settings(): array
{
    static $cached = null;
    if (is_array($cached)) {
        return $cached;
    }
    $settings = [
        'OPENAI_API_KEY' => '',
        'A7_CI_ENABLED' => '1',
        'A7_CI_MAX_PER_RUN' => '1',
        'A7_CI_MIN_DURATION' => '8',
        'A7_CI_MODEL_TRANSCRIBE' => 'whisper-1',
        'A7_CI_MODEL_ANALYZE' => 'gpt-4o-mini',
    ];
    $envPath = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/\\')
        . '/bitrix/php_interface/a7_call_intelligence.env';
    if (is_readable($envPath)) {
        $lines = file($envPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if (is_array($lines)) {
            foreach ($lines as $line) {
                $line = trim((string)$line);
                if ($line === '' || $line[0] === '#') {
                    continue;
                }
                $eq = strpos($line, '=');
                if ($eq === false) {
                    continue;
                }
                $name = trim(substr($line, 0, $eq));
                $value = trim(substr($line, $eq + 1));
                $value = trim($value, "\"'");
                if ($name !== '' && array_key_exists($name, $settings)) {
                    $settings[$name] = $value;
                }
            }
        }
    }
    $fromEnv = getenv('OPENAI_API_KEY');
    if (is_string($fromEnv) && $fromEnv !== '') {
        $settings['OPENAI_API_KEY'] = $fromEnv;
    }
    $cached = $settings;
    return $cached;
}

function a7_ci_table_ready(): bool
{
    global $DB;
    if (!is_object($DB)) {
        return false;
    }
    $res = $DB->Query("SHOW TABLES LIKE 'a7_call_intelligence'", true);
    return is_object($res) && (bool)$res->Fetch();
}

function a7_ci_agent_name(): string
{
    return 'require_once($_SERVER["DOCUMENT_ROOT"]."/bitrix/php_interface/include/a7_call_intelligence_agent.php"); return a7_call_intelligence_agent();';
}

function a7_ci_ensure_agent(): void
{
    static $done = false;
    if ($done || !class_exists('CAgent')) {
        return;
    }
    $done = true;
    global $DB;
    if (is_object($DB)) {
        $found = $DB->Query(
            "SELECT ID FROM b_agent WHERE NAME LIKE '%a7_call_intelligence_agent%' LIMIT 1",
            true
        );
        if (is_object($found) && $found->Fetch()) {
            return;
        }
    }
    \CAgent::AddAgent(a7_ci_agent_name(), '', 'N', 60);
}

function a7_ci_reclaim_stale(int $seconds = 180): void
{
    global $DB;
    if (!is_object($DB) || !a7_ci_table_ready()) {
        return;
    }
    $cut = date('Y-m-d H:i:s', time() - max(60, $seconds));
    $DB->Query(
        "UPDATE a7_call_intelligence
         SET ai_status='PENDING', updated_at=" . a7_ci_sql(a7_ci_now()) . "
         WHERE ai_status IN ('TRANSCRIBING','ANALYZING')
           AND updated_at < " . a7_ci_sql($cut),
        true
    );
}

function a7_ci_on_call_finished($call = null): void
{
    if (!a7_ci_ensure_table()) {
        return;
    }
    $statId = 0;
    $callId = '';
    if (is_array($call)) {
        $statId = (int)($call['STATISTIC_ID'] ?? 0);
        if ($statId <= 0) {
            $statId = (int)($call['ID'] ?? 0);
        }
        $callId = trim((string)($call['CALL_ID'] ?? $call['CALLID'] ?? ''));
    }
    if ($statId <= 0 && $callId !== '') {
        global $DB;
        $res = $DB->Query(
            "SELECT ID FROM b_voximplant_statistic WHERE CALL_ID=" . a7_ci_sql($callId) . " LIMIT 1",
            true
        );
        $row = is_object($res) ? $res->Fetch() : false;
        $statId = is_array($row) ? (int)$row['ID'] : 0;
    }
    if ($statId <= 0) {
        return;
    }
    $stat = a7_ci_load_statistic($statId);
    if (!a7_ci_is_new_call($stat) || !a7_ci_recording_ready($stat)) {
        return;
    }
    a7_ci_enqueue_statistic($statId);
}

function a7_ci_ensure_table(): bool
{
    global $DB;
    if (a7_ci_table_ready()) {
        a7_ci_ensure_req_column();
        a7_ci_ensure_agent();
        return true;
    }
    $sql = "CREATE TABLE IF NOT EXISTS a7_call_intelligence (
      id INT UNSIGNED NOT NULL AUTO_INCREMENT,
      statistic_id INT UNSIGNED NOT NULL,
      call_id VARCHAR(255) NOT NULL,
      recording_file_id INT UNSIGNED NULL,
      ai_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
      transcript MEDIUMTEXT NULL,
      transcript_language VARCHAR(16) NULL,
      ai_overall_score TINYINT UNSIGNED NULL,
      ai_score_breakdown TEXT NULL,
      ai_call_summary TEXT NULL,
      next_action_type VARCHAR(32) NULL,
      next_action_date DATE NULL,
      next_action_time VARCHAR(8) NULL,
      next_action_confidence DECIMAL(4,3) NULL,
      ai_processed_at DATETIME NULL,
      ai_error VARCHAR(255) NULL,
      created_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_a7_ci_call_id (call_id),
      UNIQUE KEY uk_a7_ci_statistic_id (statistic_id),
      KEY ix_a7_ci_status (ai_status, created_at)
    )";
    $DB->Query($sql, true);
    $ready = a7_ci_table_ready();
    if ($ready) {
        a7_ci_ensure_req_column();
        a7_ci_ensure_agent();
    }
    return $ready;
}

function a7_ci_ensure_req_column(): void
{
    global $DB;
    if (!is_object($DB) || !a7_ci_table_ready()) {
        return;
    }
    $check = $DB->Query("SHOW COLUMNS FROM a7_call_intelligence LIKE 'client_requirements'", true);
    if (is_object($check) && $check->Fetch()) {
        return;
    }
    $DB->Query('ALTER TABLE a7_call_intelligence ADD client_requirements TEXT NULL', true);
}

function a7_ci_sql(string $value): string
{
    global $DB;
    return "'" . $DB->ForSql($value) . "'";
}

function a7_ci_now(): string
{
    return date('Y-m-d H:i:s');
}

function a7_ci_safe_error(string $code): string
{
    $code = strtolower($code);
    if (preg_match('/auth|api.?key|unauthorized|forbidden|signature/', $code)) {
        return 'openai_authentication';
    }
    if (preg_match('/timeout|timed out/', $code)) {
        return 'openai_timeout';
    }
    if (preg_match('/invalid|schema|json|malformed/', $code)) {
        return 'invalid_ai_payload';
    }
    if (preg_match('/audio|format|file|recording/', $code)) {
        return 'recording_unreadable';
    }
    return 'processing_failed';
}

function a7_ci_public_row(?array $row, array $extra = []): array
{
    $base = [
        'ai_status' => '',
        'ai_overall_score' => null,
        'ai_call_summary' => '',
        'next_action_type' => '',
        'next_action_date' => '',
        'next_action_time' => '',
        'next_action_confidence' => null,
        'has_transcript' => false,
        'manual' => false,
        'can_analyze' => false,
        'needs_reanalyze' => false,
        'awaiting_auto' => false,
        'is_new' => false,
        'has_recording' => false,
        'waiting_recording' => false,
        'comment_line' => '',
    ];
    if (!is_array($row)) {
        return array_merge($base, $extra);
    }
    $status = (string)($row['ai_status'] ?? '');
    $completed = $status === 'COMPLETED';
    $failed = $status === 'FAILED';
    $transcriptText = (string)($row['transcript'] ?? '');
    $wrongLanguage = $completed && (
        a7_ci_forbidden_script($transcriptText)
        || a7_ci_has_arabic_script($transcriptText)
        || a7_ci_is_prompt_leak($transcriptText)
    );
    return array_merge($base, [
        'ai_status' => $status,
        'ai_overall_score' => $completed ? (int)$row['ai_overall_score'] : null,
        'ai_call_summary' => $completed ? (string)($row['ai_call_summary'] ?? '') : '',
        'next_action_type' => $completed ? (string)($row['next_action_type'] ?? '') : '',
        'next_action_date' => $completed ? a7_ci_sanitize_action_date((string)($row['next_action_date'] ?? '')) : '',
        'next_action_time' => $completed ? a7_ci_sanitize_action_time((string)($row['next_action_time'] ?? '')) : '',
        'next_action_confidence' => $completed && $row['next_action_confidence'] !== null
            ? (float)$row['next_action_confidence']
            : null,
        'has_transcript' => $completed && trim((string)($row['transcript'] ?? '')) !== '',
        'can_analyze' => $failed || $wrongLanguage || (!empty($extra['can_analyze']) && $status === ''),
        'needs_reanalyze' => $wrongLanguage,
        'manual' => !empty($extra['manual']) || $failed || $wrongLanguage,
        'awaiting_auto' => !empty($extra['awaiting_auto']),
        'is_new' => !empty($extra['is_new']),
        'has_recording' => !empty($extra['has_recording']),
        'waiting_recording' => !empty($extra['waiting_recording']),
        'comment_line' => $completed ? a7_ci_comment_from_row($row) : '',
    ], $extra);
}

function a7_ci_sanitize_action_date(string $date): string
{
    $date = trim($date);
    if ($date === '' || !preg_match('/^(\d{4})-\d{2}-\d{2}$/', $date, $match)) {
        return '';
    }
    if ((int)$match[1] < (int)date('Y')) {
        return '';
    }
    return $date;
}

function a7_ci_sanitize_action_time(string $time): string
{
    $time = trim($time);
    if ($time === '' || !preg_match('/^\d{2}:\d{2}$/', $time)) {
        return '';
    }
    if ($time === '00:00') {
        return '';
    }
    return $time;
}

function a7_ci_comment_from_row(array $row): string
{
    $comment = trim((string)($row['stat_comment'] ?? $row['COMMENT'] ?? ''));
    if ($comment !== '' && strncmp($comment, 'AI:', 3) === 0) {
        $comment = trim(substr($comment, 3));
    } elseif ($comment !== '' && strpos($comment, 'AI:') !== false) {
        $parts = preg_split('/\s*\|\s*AI:\s*/', $comment, 2);
        $comment = trim((string)($parts[1] ?? $comment));
    }
    if ($comment === '') {
        $comment = trim((string)($row['ai_call_summary'] ?? ''));
    }
    if ($comment === '') {
        return '';
    }
    return mb_substr($comment, 0, 500);
}

function a7_ci_fetch_by_statistic_ids(array $ids): array
{
    global $DB;
    $clean = [];
    foreach ($ids as $id) {
        $id = (int)$id;
        if ($id > 0) {
            $clean[$id] = $id;
        }
    }
    if (!$clean || !a7_ci_table_ready()) {
        return [];
    }
    $in = implode(',', $clean);
    $res = $DB->Query(
        "SELECT statistic_id, ai_status, transcript, transcript_language, ai_overall_score, ai_call_summary,
                next_action_type, next_action_date, next_action_time, next_action_confidence
         FROM a7_call_intelligence
         WHERE statistic_id IN (" . $in . ")",
        true
    );
    $out = [];
    if (is_object($res)) {
        while ($row = $res->Fetch()) {
            $out[(int)$row['statistic_id']] = $row;
        }
    }
    return $out;
}

function a7_ci_datetime_string($value): string
{
    if ($value instanceof \Bitrix\Main\Type\DateTime) {
        return $value->format('Y-m-d H:i:s');
    }
    return trim((string)$value);
}

function a7_ci_load_statistic(int $id): ?array
{
    if ($id <= 0 || !\Bitrix\Main\Loader::includeModule('voximplant')) {
        return null;
    }
    try {
        $row = \Bitrix\Voximplant\StatisticTable::getList([
            'select' => [
                'ID',
                'CALL_ID',
                'CALL_RECORD_ID',
                'CALL_DURATION',
                'CALL_START_DATE',
                'CRM_ENTITY_TYPE',
                'CRM_ENTITY_ID',
            ],
            'filter' => ['=ID' => $id],
            'limit' => 1,
        ])->fetch();
    } catch (Throwable $error) {
        $row = \Bitrix\Voximplant\StatisticTable::getList([
            'select' => ['ID', 'CALL_ID', 'CALL_RECORD_ID', 'CALL_DURATION', 'CALL_START_DATE'],
            'filter' => ['=ID' => $id],
            'limit' => 1,
        ])->fetch();
    }
    if (is_array($row)) {
        $url = a7_ci_statistic_record_url((int)$row['ID']);
        if ($url !== '') {
            $row['CALL_RECORD_URL'] = $url;
        }
    }
    return is_array($row) ? $row : null;
}

function a7_ci_statistic_record_url(int $id): string
{
    if ($id <= 0) {
        return '';
    }
    global $DB;
    if (!is_object($DB)) {
        return '';
    }
    $res = $DB->Query(
        'SELECT CALL_RECORD_URL FROM b_voximplant_statistic WHERE ID=' . $id . ' LIMIT 1',
        true
    );
    $row = is_object($res) ? $res->Fetch() : false;
    return is_array($row) ? trim((string)($row['CALL_RECORD_URL'] ?? '')) : '';
}

function a7_ci_has_recording(?array $stat): bool
{
    if (!is_array($stat)) {
        return false;
    }
    if ((int)($stat['CALL_RECORD_ID'] ?? 0) > 0) {
        return true;
    }
    return trim((string)($stat['CALL_RECORD_URL'] ?? '')) !== '';
}

function a7_ci_recording_ready(?array $stat): bool
{
    return a7_ci_has_recording($stat);
}

function a7_ci_active_job(): ?array
{
    global $DB;
    if (!is_object($DB) || !a7_ci_table_ready()) {
        return null;
    }
    a7_ci_reclaim_stale(180);
    $res = $DB->Query(
        "SELECT * FROM a7_call_intelligence
         WHERE ai_status IN ('TRANSCRIBING','ANALYZING')
         ORDER BY updated_at DESC
         LIMIT 1",
        true
    );
    $row = is_object($res) ? $res->Fetch() : false;
    return is_array($row) ? $row : null;
}

function a7_ci_is_new_call(?array $stat): bool
{
    if (!is_array($stat)) {
        return false;
    }
    $start = a7_ci_datetime_string($stat['CALL_START_DATE'] ?? '');
    if ($start === '') {
        return false;
    }
    $startTs = strtotime($start);
    $cutTs = strtotime(a7_ci_not_before());
    if ($startTs && $cutTs) {
        return $startTs >= $cutTs;
    }
    return $start >= a7_ci_not_before();
}

function a7_ci_list_public_rows(array $ids): array
{
    $found = a7_ci_fetch_by_statistic_ids($ids);
    $rows = [];
    foreach ($ids as $id) {
        $id = (int)$id;
        $stat = a7_ci_load_statistic($id);
        $isNew = a7_ci_is_new_call($stat);
        $ready = a7_ci_recording_ready($stat);
        if (isset($found[$id])) {
            $status = (string)($found[$id]['ai_status'] ?? '');
            $done = in_array($status, ['COMPLETED', 'FAILED'], true);
            $rows[(string)$id] = a7_ci_public_row($found[$id], [
                'is_new' => $isNew,
                'has_recording' => $ready,
                'waiting_recording' => $isNew && !$ready && !$done,
                'manual' => !$isNew || $status === 'FAILED',
                'can_analyze' => !$isNew && $status !== 'COMPLETED' && $ready,
                'awaiting_auto' => $isNew && $ready && !$done,
            ]);
            continue;
        }
        if ($isNew && $ready) {
            $job = a7_ci_enqueue_statistic($id);
            if (is_array($job)) {
                $status = (string)($job['ai_status'] ?? '');
                $done = in_array($status, ['COMPLETED', 'FAILED'], true);
                $rows[(string)$id] = a7_ci_public_row($job, [
                    'is_new' => true,
                    'has_recording' => true,
                    'awaiting_auto' => !$done,
                    'can_analyze' => $status === 'FAILED',
                ]);
                continue;
            }
        }
        $rows[(string)$id] = a7_ci_public_row(null, [
            'is_new' => $isNew,
            'has_recording' => $ready,
            'waiting_recording' => $isNew && !$ready,
            'awaiting_auto' => false,
            'manual' => !$isNew,
            'can_analyze' => !$isNew && $ready,
        ]);
    }
    return $rows;
}

function a7_ci_enqueue_statistic(int $statisticId): ?array
{
    global $DB;
    $stat = a7_ci_load_statistic($statisticId);
    if (!is_array($stat)) {
        return null;
    }
    $callId = trim((string)$stat['CALL_ID']);
    $fileId = (int)$stat['CALL_RECORD_ID'];
    if ($callId === '' || !a7_ci_has_recording($stat)) {
        return null;
    }
    $existing = $DB->Query(
        "SELECT * FROM a7_call_intelligence WHERE statistic_id=" . $statisticId . " OR call_id=" . a7_ci_sql($callId) . " LIMIT 1",
        true
    );
    $row = is_object($existing) ? $existing->Fetch() : false;
    if (is_array($row)) {
        $status = (string)$row['ai_status'];
        if ($status === 'FAILED') {
            a7_ci_update((int)$row['id'], [
                'ai_status' => 'PENDING',
                'transcript' => null,
                'transcript_language' => null,
                'ai_overall_score' => null,
                'ai_score_breakdown' => null,
                'ai_call_summary' => null,
                'next_action_type' => null,
                'next_action_date' => null,
                'next_action_time' => null,
                'next_action_confidence' => null,
                'ai_processed_at' => null,
                'ai_error' => null,
                'recording_file_id' => (string)$fileId,
            ]);
            $reload = $DB->Query(
                "SELECT * FROM a7_call_intelligence WHERE id=" . (int)$row['id'],
                true
            );
            $fresh = is_object($reload) ? $reload->Fetch() : false;
            return is_array($fresh) ? $fresh : $row;
        }
        return $row;
    }
    $now = a7_ci_now();
    $DB->Query(
        "INSERT INTO a7_call_intelligence
            (statistic_id, call_id, recording_file_id, ai_status, created_at, updated_at)
         VALUES (" . $statisticId . ", " . a7_ci_sql($callId) . ", " . $fileId . ", 'PENDING', "
        . a7_ci_sql($now) . ", " . a7_ci_sql($now) . ")",
        true
    );
    $created = $DB->Query(
        "SELECT * FROM a7_call_intelligence WHERE statistic_id=" . $statisticId . " LIMIT 1",
        true
    );
    $row = is_object($created) ? $created->Fetch() : false;
    return is_array($row) ? $row : null;
}

function a7_ci_claim_job_by_id(int $id): ?array
{
    global $DB;
    $now = a7_ci_now();
    $DB->Query(
        "UPDATE a7_call_intelligence
         SET ai_status='TRANSCRIBING', updated_at=" . a7_ci_sql($now) . "
         WHERE id=" . $id . " AND ai_status='PENDING'",
        true
    );
    $check = $DB->Query(
        "SELECT * FROM a7_call_intelligence WHERE id=" . $id . " AND ai_status='TRANSCRIBING'",
        true
    );
    $claimed = is_object($check) ? $check->Fetch() : false;
    return is_array($claimed) ? $claimed : null;
}

function a7_ci_analyze_on_demand(int $statisticId, bool $force = false): array
{
    if ($statisticId <= 0) {
        return ['ok' => false, 'error' => 'invalid_call'];
    }
    $found = a7_ci_fetch_by_statistic_ids([$statisticId]);
    $existing = $found[$statisticId] ?? null;
    if (is_array($existing) && (string)$existing['ai_status'] === 'COMPLETED' && !$force) {
        return ['ok' => true, 'cached' => true, 'row' => a7_ci_public_row($existing, ['has_recording' => true])];
    }
    $stat = a7_ci_load_statistic($statisticId);
    if (!a7_ci_recording_ready($stat)) {
        return [
            'ok' => true,
            'waiting_recording' => true,
            'row' => a7_ci_public_row(is_array($existing) ? $existing : null, [
                'is_new' => a7_ci_is_new_call($stat),
                'has_recording' => false,
                'waiting_recording' => true,
                'awaiting_auto' => false,
            ]),
        ];
    }
    $job = a7_ci_enqueue_statistic($statisticId);
    if ($job === null) {
        return ['ok' => false, 'error' => 'recording_unreadable'];
    }
    $status = (string)$job['ai_status'];
    if ($status === 'COMPLETED' && !$force) {
        return ['ok' => true, 'cached' => true, 'row' => a7_ci_public_row($job, ['has_recording' => true])];
    }
    if (in_array($status, ['TRANSCRIBING', 'ANALYZING'], true) && !$force) {
        a7_ci_reclaim_stale(180);
        $reload = $GLOBALS['DB']->Query(
            'SELECT * FROM a7_call_intelligence WHERE id=' . (int)$job['id'],
            true
        );
        $fresh = is_object($reload) ? $reload->Fetch() : false;
        $job = is_array($fresh) ? $fresh : $job;
        $status = (string)$job['ai_status'];
        if (in_array($status, ['TRANSCRIBING', 'ANALYZING'], true)) {
            return ['ok' => true, 'row' => a7_ci_public_row($job)];
        }
    }
    if ($status === 'COMPLETED' || $status === 'FAILED') {
        if (!$force && $status === 'FAILED') {
            return ['ok' => true, 'row' => a7_ci_public_row($job)];
        }
        a7_ci_update((int)$job['id'], [
            'ai_status' => 'PENDING',
            'transcript' => null,
            'transcript_language' => null,
            'ai_overall_score' => null,
            'ai_score_breakdown' => null,
            'ai_call_summary' => null,
            'next_action_type' => null,
            'next_action_date' => null,
            'next_action_time' => null,
            'next_action_confidence' => null,
            'ai_processed_at' => null,
            'ai_error' => null,
        ]);
        $reload = $GLOBALS['DB']->Query(
            'SELECT * FROM a7_call_intelligence WHERE id=' . (int)$job['id'],
            true
        );
        $fresh = is_object($reload) ? $reload->Fetch() : false;
        $job = is_array($fresh) ? $fresh : $job;
        $status = (string)$job['ai_status'];
    }
    if (in_array($status, ['TRANSCRIBING', 'ANALYZING'], true)) {
        return ['ok' => true, 'row' => a7_ci_public_row($job)];
    }
    if (a7_ci_openai_key() === '') {
        return ['ok' => false, 'error' => 'openai_key_missing', 'row' => a7_ci_public_row($job)];
    }
    $active = a7_ci_active_job();
    if (is_array($active) && (int)$active['id'] !== (int)$job['id']) {
        return [
            'ok' => true,
            'queued' => true,
            'row' => a7_ci_public_row($job, [
                'has_recording' => true,
                'awaiting_auto' => true,
            ]),
        ];
    }
    @set_time_limit(180);
    $claimed = a7_ci_claim_job_by_id((int)$job['id']);
    if ($claimed === null) {
        $found = a7_ci_fetch_by_statistic_ids([$statisticId]);
        return ['ok' => true, 'row' => a7_ci_public_row($found[$statisticId] ?? $job)];
    }
    a7_ci_process_one($claimed);
    $found = a7_ci_fetch_by_statistic_ids([$statisticId]);
    return ['ok' => true, 'row' => a7_ci_public_row($found[$statisticId] ?? $claimed)];
}

function a7_ci_json(array $payload, int $status = 200): void
{
    while (ob_get_level() > 0) {
        ob_end_clean();
    }
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

function a7_ci_require_user(): bool
{
    global $USER;
    return is_object($USER) && $USER->IsAuthorized();
}

function a7_ci_handle_http(): void
{
    if (!a7_ci_require_user()) {
        a7_ci_json(['ok' => false, 'error' => 'unauthorized'], 401);
        return;
    }
    if (!check_bitrix_sessid()) {
        a7_ci_json(['ok' => false, 'error' => 'bad_sessid'], 403);
        return;
    }
    a7_ci_ensure_table();
    a7_ci_ensure_agent();
    a7_ci_reclaim_stale(180);
    $action = (string)($_REQUEST['action'] ?? 'list');
    if ($action === 'list') {
        $raw = (string)($_REQUEST['ids'] ?? '');
        $ids = array_filter(array_map('intval', preg_split('/[^\d]+/', $raw) ?: []));
        $ids = array_slice(array_values(array_unique($ids)), 0, 80);
        a7_ci_json(['ok' => true, 'rows' => a7_ci_list_public_rows($ids)]);
        return;
    }
    if ($action === 'analyze') {
        $id = (int)($_REQUEST['id'] ?? 0);
        $force = (string)($_REQUEST['force'] ?? '') === '1';
        $result = a7_ci_analyze_on_demand($id, $force);
        a7_ci_json($result, !empty($result['ok']) ? 200 : 400);
        return;
    }
    if ($action === 'detail') {
        $id = (int)($_REQUEST['id'] ?? 0);
        $found = a7_ci_fetch_by_statistic_ids([$id]);
        $row = $found[$id] ?? null;
        $public = a7_ci_public_row($row);
        if ($public['has_transcript']) {
            $public['transcript'] = (string)($row['transcript'] ?? '');
        } else {
            $public['transcript'] = '';
        }
        a7_ci_json(['ok' => true, 'row' => $public]);
        return;
    }
    if ($action === 'crm_panel') {
        $type = (string)($_REQUEST['entity_type'] ?? '');
        $entityId = (int)($_REQUEST['entity_id'] ?? 0);
        a7_ci_json(a7_ci_crm_panel($type, $entityId));
        return;
    }
    if ($action === 'crm_calls') {
        $type = (string)($_REQUEST['entity_type'] ?? '');
        $entityId = (int)($_REQUEST['entity_id'] ?? 0);
        a7_ci_json(a7_ci_crm_calls($type, $entityId));
        return;
    }
    a7_ci_json(['ok' => false, 'error' => 'unknown_action'], 400);
}

function a7_ci_not_before(): string
{
    $version = \COption::GetOptionString('a7.call.intelligence', 'cutoff_version', '');
    $stored = \COption::GetOptionString('a7.call.intelligence', 'not_before', '');
    if ($version === A7_CI_CUTOFF_VERSION && $stored !== '') {
        return $stored;
    }
    $value = a7_ci_now();
    \COption::SetOptionString('a7.call.intelligence', 'not_before', $value);
    \COption::SetOptionString('a7.call.intelligence', 'cutoff_version', A7_CI_CUTOFF_VERSION);
    return $value;
}

function a7_ci_queue_new_calls(int $limit = 20): int
{
    global $DB;
    $notBefore = a7_ci_not_before();
    if ($notBefore === '' || !is_object($DB)) {
        return 0;
    }
    $limit = max(1, min(50, $limit));
    $minDuration = max(1, (int)a7_ci_settings()['A7_CI_MIN_DURATION']);
    $cursor = $DB->Query(
        "SELECT ID, CALL_ID, CALL_RECORD_ID, CALL_DURATION, CALL_START_DATE
         FROM b_voximplant_statistic
         WHERE CALL_START_DATE >= " . a7_ci_sql($notBefore) . "
           AND IFNULL(CALL_RECORD_ID, 0) > 0
           AND CALL_DURATION >= " . $minDuration . "
         ORDER BY ID DESC
         LIMIT " . $limit,
        true
    );
    if (!is_object($cursor)) {
        return 0;
    }
    $queued = 0;
    $now = a7_ci_now();
    while ($row = $cursor->Fetch()) {
        $statisticId = (int)$row['ID'];
        $callId = trim((string)$row['CALL_ID']);
        $fileId = (int)$row['CALL_RECORD_ID'];
        if ($statisticId <= 0 || $callId === '' || $fileId <= 0) {
            continue;
        }
        $exists = $DB->Query(
            "SELECT id FROM a7_call_intelligence WHERE statistic_id=" . $statisticId . " OR call_id=" . a7_ci_sql($callId) . " LIMIT 1",
            true
        );
        if (is_object($exists) && $exists->Fetch()) {
            continue;
        }
        $ok = $DB->Query(
            "INSERT INTO a7_call_intelligence
                (statistic_id, call_id, recording_file_id, ai_status, created_at, updated_at)
             VALUES (" . $statisticId . ", " . a7_ci_sql($callId) . ", " . $fileId . ", 'PENDING', "
            . a7_ci_sql($now) . ", " . a7_ci_sql($now) . ")",
            true
        );
        if ($ok) {
            $queued++;
        }
    }
    return $queued;
}

function a7_ci_recording_path(int $fileId): string
{
    if ($fileId <= 0) {
        return '';
    }
    $file = \CFile::GetFileArray($fileId);
    if (!is_array($file) || empty($file['SRC'])) {
        return '';
    }
    $root = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/\\');
    $src = (string)$file['SRC'];
    if (preg_match('#^https?://#i', $src)) {
        return a7_ci_download_recording($src);
    }
    $path = $root . $src;
    if (!is_readable($path) || filesize($path) <= 0) {
        return '';
    }
    return $path;
}

function a7_ci_download_recording(string $url): string
{
    $url = trim($url);
    if ($url === '' || !preg_match('#^https?://#i', $url)) {
        return '';
    }
    $tmpDir = rtrim(sys_get_temp_dir(), '/\\') . DIRECTORY_SEPARATOR . 'a7_ci_rec';
    if (!is_dir($tmpDir) && !@mkdir($tmpDir, 0700, true) && !is_dir($tmpDir)) {
        return '';
    }
    $dest = $tmpDir . DIRECTORY_SEPARATOR . hash('sha256', $url) . '.bin';
    if (is_readable($dest) && filesize($dest) > 800) {
        return $dest;
    }
    $data = '';
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        if ($ch === false) {
            return '';
        }
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_MAXREDIRS => 5,
            CURLOPT_CONNECTTIMEOUT => 15,
            CURLOPT_TIMEOUT => 90,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_USERAGENT => 'A7-Call-Intelligence/1.0',
        ]);
        $raw = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if ($code >= 400 || !is_string($raw)) {
            return '';
        }
        $data = $raw;
    } else {
        $ctx = stream_context_create([
            'http' => [
                'timeout' => 90,
                'follow_location' => 1,
                'user_agent' => 'A7-Call-Intelligence/1.0',
            ],
        ]);
        $raw = @file_get_contents($url, false, $ctx);
        if (!is_string($raw)) {
            return '';
        }
        $data = $raw;
    }
    $len = strlen($data);
    if ($len < 800 || $len > 80 * 1024 * 1024) {
        return '';
    }
    if (@file_put_contents($dest, $data) === false) {
        return '';
    }
    return $dest;
}

function a7_ci_resolve_recording(?array $stat): string
{
    if (!is_array($stat)) {
        return '';
    }
    $fileId = (int)($stat['CALL_RECORD_ID'] ?? 0);
    $local = a7_ci_recording_path($fileId);
    if ($local !== '') {
        return $local;
    }
    $url = trim((string)($stat['CALL_RECORD_URL'] ?? ''));
    if ($url === '') {
        $url = a7_ci_statistic_record_url((int)($stat['ID'] ?? 0));
    }
    if ($url === '') {
        return '';
    }
    return a7_ci_download_recording($url);
}

function a7_ci_openai_key(): string
{
    $key = trim((string)a7_ci_settings()['OPENAI_API_KEY']);
    if (strlen($key) < 20) {
        return '';
    }
    return $key;
}

function a7_ci_header_map(array $headers): array
{
    $map = [];
    foreach ($headers as $header) {
        $parts = explode(':', (string)$header, 2);
        if (count($parts) !== 2) {
            continue;
        }
        $name = trim($parts[0]);
        $value = trim($parts[1]);
        if ($name !== '') {
            $map[$name] = $value;
        }
    }
    return $map;
}

function a7_ci_decode_http_json(string $raw, int $status): array
{
    $decoded = json_decode($raw, true);
    if ($status >= 400) {
        $type = is_array($decoded)
            ? (string)($decoded['error']['type'] ?? $decoded['error']['code'] ?? 'http_' . $status)
            : 'http_' . $status;
        throw new RuntimeException($type);
    }
    if (!is_array($decoded)) {
        throw new RuntimeException('invalid_ai_payload');
    }
    return $decoded;
}

function a7_ci_http_json(string $url, array $headers, $body, int $timeout, bool $multipart = false): array
{
    $payload = is_string($body) ? $body : json_encode($body);
    if (!is_string($payload)) {
        throw new RuntimeException('http_failed');
    }

    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_POSTFIELDS => $payload,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_CONNECTTIMEOUT => 15,
        ]);
        $raw = curl_exec($ch);
        $errno = curl_errno($ch);
        $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if ($errno) {
            throw new RuntimeException($errno === CURLE_OPERATION_TIMEDOUT ? 'timeout' : 'http_failed');
        }
        return a7_ci_decode_http_json((string)$raw, $status);
    }

    if (class_exists('\Bitrix\Main\Web\HttpClient')) {
        $http = new \Bitrix\Main\Web\HttpClient([
            'socketTimeout' => 15,
            'streamTimeout' => $timeout,
            'waitResponse' => true,
        ]);
        foreach (a7_ci_header_map($headers) as $name => $value) {
            $http->setHeader($name, $value, true);
        }
        $raw = $http->post($url, $payload);
        $status = (int)$http->getStatus();
        if ($raw === false || $status <= 0) {
            throw new RuntimeException('http_failed');
        }
        return a7_ci_decode_http_json((string)$raw, $status);
    }

    $headerLines = implode("\r\n", $headers);
    $context = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => $headerLines,
            'content' => $payload,
            'timeout' => $timeout,
            'ignore_errors' => true,
        ],
    ]);
    $raw = @file_get_contents($url, false, $context);
    if ($raw === false) {
        throw new RuntimeException('http_failed');
    }
    $status = 0;
    if (isset($http_response_header[0]) && preg_match('/\s(\d{3})\s/', (string)$http_response_header[0], $m)) {
        $status = (int)$m[1];
    }
    return a7_ci_decode_http_json((string)$raw, $status);
}

function a7_ci_multipart_body(array $fields, string $fileField, string $path, string $filename, string $mime): array
{
    $boundary = 'a7ci' . bin2hex(random_bytes(12));
    $audio = file_get_contents($path);
    if (!is_string($audio) || $audio === '') {
        throw new RuntimeException('recording_unreadable');
    }
    $body = '';
    foreach ($fields as $name => $value) {
        $body .= '--' . $boundary . "\r\n";
        $body .= 'Content-Disposition: form-data; name="' . $name . '"' . "\r\n\r\n";
        $body .= $value . "\r\n";
    }
    $body .= '--' . $boundary . "\r\n";
    $body .= 'Content-Disposition: form-data; name="' . $fileField . '"; filename="' . $filename . '"' . "\r\n";
    $body .= 'Content-Type: ' . $mime . "\r\n\r\n";
    $body .= $audio . "\r\n";
    $body .= '--' . $boundary . "--\r\n";
    return [$body, $boundary];
}

function a7_ci_transcribe(string $path): array
{
    $key = a7_ci_openai_key();
    if ($key === '') {
        throw new RuntimeException('openai_authentication');
    }
    $size = filesize($path);
    if ($size === false || $size < 44 || $size > 20971520) {
        throw new RuntimeException('recording_unreadable');
    }
    $model = (string)a7_ci_settings()['A7_CI_MODEL_TRANSCRIBE'];
    if ($model === '') {
        $model = 'whisper-1';
    }
    $mime = function_exists('mime_content_type') ? (string)mime_content_type($path) : '';
    if ($mime === '' || $mime === 'application/octet-stream') {
        $mime = 'audio/mpeg';
    }
    $response = a7_ci_whisper_request($path, $mime, $model, $key, 'en', '', true);
    $text = trim((string)($response['text'] ?? ''));
    if (
        $text === ''
        || a7_ci_forbidden_script($text)
        || a7_ci_has_arabic_script($text)
        || a7_ci_is_prompt_leak($text)
    ) {
        $retry = a7_ci_whisper_request($path, $mime, $model, $key, 'en', '', false);
        $retryText = trim((string)($retry['text'] ?? ''));
        if (
            $retryText !== ''
            && !a7_ci_forbidden_script($retryText)
            && !a7_ci_has_arabic_script($retryText)
            && !a7_ci_is_prompt_leak($retryText)
        ) {
            $text = $retryText;
        }
    }
    $text = a7_ci_strip_prompt_leak($text);
    if (
        $text === ''
        || a7_ci_forbidden_script($text)
        || a7_ci_is_prompt_leak($text)
        || a7_ci_is_no_conversation($text)
    ) {
        return [
            'text' => a7_ci_no_conversation_text(),
            'language' => 'en',
            'no_conversation' => true,
        ];
    }
    return [
        'text' => mb_substr($text, 0, 200000),
        'language' => 'en',
        'no_conversation' => false,
    ];
}

function a7_ci_whisper_request(
    string $path,
    string $mime,
    string $model,
    string $key,
    string $language,
    string $prompt,
    bool $translate = true
): array {
    $fields = [
        'model' => $model,
        'response_format' => 'verbose_json',
    ];
    if (trim($prompt) !== '') {
        $fields['prompt'] = $prompt;
    }
    $url = 'https://api.openai.com/v1/audio/translations';
    if (!$translate) {
        $url = 'https://api.openai.com/v1/audio/transcriptions';
        if ($language === 'en') {
            $fields['language'] = 'en';
        }
    }
    [$body, $boundary] = a7_ci_multipart_body(
        $fields,
        'file',
        $path,
        'recording.mp3',
        $mime
    );
    return a7_ci_http_json(
        $url,
        [
            'Authorization: Bearer ' . $key,
            'Content-Type: multipart/form-data; boundary=' . $boundary,
        ],
        $body,
        180
    );
}

function a7_ci_has_arabic_script(string $text): bool
{
    return (bool)preg_match('/[\x{0600}-\x{06FF}]/u', $text);
}

function a7_ci_forbidden_script(string $text): bool
{
    return (bool)preg_match(
        '/[\x{1780}-\x{17FF}\x{0E00}-\x{0E7F}\x{3040}-\x{30FF}\x{4E00}-\x{9FFF}\x{AC00}-\x{D7AF}]/u',
        $text
    );
}

function a7_ci_no_conversation_text(): string
{
    return 'No conversation was detected. The call may not have connected, '
        . 'or only a system/voicemail message was recorded.';
}

function a7_ci_is_prompt_leak(string $text): bool
{
    $t = strtolower($text);
    $needles = [
        'translate any urdu',
        'never write khmer',
        'non-english script',
        'transcribe this phone call',
        'transcribe in the original',
        'if the speakers use urdu',
    ];
    foreach ($needles as $needle) {
        if (strpos($t, $needle) !== false) {
            return true;
        }
    }
    return false;
}

function a7_ci_strip_prompt_leak(string $text): string
{
    $lines = preg_split('/\r\n|\r|\n|(?<=[.!?])\s+/', $text) ?: [];
    $kept = [];
    foreach ($lines as $line) {
        $line = trim((string)$line);
        if ($line === '' || a7_ci_is_prompt_leak($line)) {
            continue;
        }
        $kept[] = $line;
    }
    return trim(implode(' ', $kept));
}

function a7_ci_is_no_conversation(string $text): bool
{
    $t = strtolower(trim($text));
    if ($t === '') {
        return true;
    }
    $needles = [
        'speech is not available',
        'please record your message',
        'you have finished recording',
        'the person you are calling',
        'leave a message after the tone',
        'mailbox is full',
        'number you have dialed',
        'could not be connected',
        'no conversation was detected',
        'your call cannot be completed',
        'the subscriber you have',
    ];
    foreach ($needles as $needle) {
        if (strpos($t, $needle) !== false) {
            return true;
        }
    }
    $words = preg_split('/\s+/u', $t) ?: [];
    return count(array_filter($words)) < 3;
}

function a7_ci_empty_requirements(): array
{
    $empty = [];
    foreach (A7_CI_REQ_KEYS as $key) {
        $empty[$key] = null;
    }
    return $empty;
}

function a7_ci_has_no_conversation_marker(string $text): bool
{
    $t = strtolower(trim($text));
    if ($t === '') {
        return true;
    }
    $needles = [
        'speech is not available',
        'please record your message',
        'you have finished recording',
        'the person you are calling',
        'leave a message after the tone',
        'mailbox is full',
        'number you have dialed',
        'could not be connected',
        'no conversation was detected',
        'your call cannot be completed',
        'the subscriber you have',
        'the call may not have connected',
        'the call did not connect',
    ];
    foreach ($needles as $needle) {
        if (strpos($t, $needle) !== false) {
            return true;
        }
    }
    return false;
}

function a7_ci_is_real_conversation(string $text): bool
{
    $text = trim($text);
    if ($text === '' || a7_ci_is_prompt_leak($text) || a7_ci_has_no_conversation_marker($text)) {
        return false;
    }
    $words = preg_split('/\s+/u', $text) ?: [];
    return count(array_filter($words)) >= 4;
}

function a7_ci_infer_interest(string $text): ?string
{
    if (!a7_ci_is_real_conversation($text)) {
        return null;
    }
    $t = mb_strtolower($text);
    $low = [
        'not interested',
        'already bought',
        'already rented',
        'already purchased',
        'stop calling',
        'do not call',
        "don't call",
        'wrong number',
        'no thank',
        'not looking',
    ];
    foreach ($low as $needle) {
        if (strpos($t, $needle) !== false) {
            return 'Low';
        }
    }
    $high = [
        'i want',
        'i need',
        'send me',
        'book a',
        'viewing',
        'i am interested',
        "i'm interested",
        'how much',
        'what is the price',
        'ready to',
        'i will take',
        'confirm',
        'one-year',
        'one year',
        'inquired about',
        'asked about',
        'looking for',
    ];
    foreach ($high as $needle) {
        if (strpos($t, $needle) !== false) {
            return 'High';
        }
    }
    return 'Medium';
}

function a7_ci_notes_from_conversation(string $summary): ?string
{
    if (!a7_ci_is_real_conversation($summary)) {
        return null;
    }
    $summary = trim(a7_ci_strip_prompt_leak($summary));
    if ($summary === '' || a7_ci_forbidden_script($summary)) {
        return null;
    }
    if (preg_match('/^(.+?[.!?])(?:\s|$)/u', $summary, $match) === 1) {
        $note = trim((string)$match[1]);
    } else {
        $note = $summary;
    }
    if (mb_strlen($note) < 8) {
        $note = mb_substr($summary, 0, 180);
    }
    $note = mb_substr(trim($note), 0, 400);
    if ($note === '' || a7_ci_has_no_conversation_marker($note) || a7_ci_is_prompt_leak($note)) {
        return null;
    }
    return $note;
}

function a7_ci_req_empty(?string $value): bool
{
    return $value === null || trim($value) === '';
}

function a7_ci_set_req_if_empty(array $reqs, string $key, ?string $value): array
{
    if (!a7_ci_req_empty($reqs[$key] ?? null)) {
        return $reqs;
    }
    $value = $value !== null ? trim($value) : '';
    if ($value === '' || a7_ci_is_prompt_leak($value) || a7_ci_forbidden_script($value)) {
        return $reqs;
    }
    $reqs[$key] = mb_substr($value, 0, $key === 'notes' ? 400 : 240);
    return $reqs;
}

function a7_ci_enrich_requirements_from_text(array $reqs, string $transcript, string $summary): array
{
    $text = trim($transcript . "\n" . $summary);
    if (!a7_ci_is_real_conversation($summary) && !a7_ci_is_real_conversation($text)) {
        return $reqs;
    }
    $lower = mb_strtolower($text);

    if (preg_match('/\b(rent|rental|leasing|lease|yearly rent)\b/', $lower) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'looking_for', 'rent');
    } elseif (preg_match('/\b(sale|buy|buying|purchase|purchasing|to own)\b/', $lower) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'looking_for', 'sale');
    } elseif (preg_match('/\b(invest|investment|investor)\b/', $lower) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'looking_for', 'investment');
    }

    $types = [
        'studio' => 'studio',
        'penthouse' => 'penthouse',
        'townhouse' => 'townhouse',
        'villa' => 'villa',
        'duplex' => 'duplex',
        'apartment' => 'apartment',
        'flat' => 'apartment',
        'office' => 'office',
        'shop' => 'shop',
        'warehouse' => 'warehouse',
        'plot' => 'plot',
    ];
    foreach ($types as $needle => $label) {
        if (strpos($lower, $needle) !== false) {
            $reqs = a7_ci_set_req_if_empty($reqs, 'property_type', $label);
            if ($needle === 'studio') {
                $reqs = a7_ci_set_req_if_empty($reqs, 'bedrooms', 'studio');
            }
            break;
        }
    }
    if (preg_match('/\b([1-9]|1[0-2])\s*(?:bed|beds|br|bedroom|bedrooms)\b/', $lower, $match) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'bedrooms', $match[1]);
        if (a7_ci_req_empty($reqs['property_type'] ?? null)) {
            $reqs = a7_ci_set_req_if_empty($reqs, 'property_type', $match[1] . ' bedroom');
        }
    }

    $communities = [
        'arabian ranches', 'arabian district', 'arabian registry', 'dubai hills',
        'palm jumeirah', 'business bay', 'downtown', 'dubai marina', 'jbr',
        'jvc', 'jvt', 'jlt', 'difc', 'al barsha', 'sports city', 'motor city',
        'town square', 'creek harbour', 'dubai harbour', 'dubai south',
        'damac hills', 'silicon oasis', 'international city', 'discovery gardens',
        'al furjan', 'mirdif', 'meydan', 'bluewaters', 'city walk',
        'sobha hartland', 'tilal al ghaf', 'emaar beachfront', 'dubai islands',
        'production city', 'studio city', 'academic city', 'arjan', 'mudon',
        'remraam', 'impz',
    ];
    foreach ($communities as $name) {
        if (strpos($lower, $name) !== false) {
            $reqs = a7_ci_set_req_if_empty($reqs, 'community', ucwords($name));
            break;
        }
    }
    if (a7_ci_req_empty($reqs['community'] ?? null)
        && preg_match('/\b((?:t|a|b|c)-\d{1,3})\b/i', $text, $match) === 1
    ) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'community', strtoupper($match[1]));
    }
    if (a7_ci_req_empty($reqs['community'] ?? null)
        && preg_match('/\b(?:in|at|near)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\b/', $text, $match) === 1
    ) {
        $place = trim($match[1]);
        $skip = ['The', 'This', 'That', 'They', 'There', 'English', 'Arabic'];
        if (!in_array($place, $skip, true) && mb_strlen($place) >= 3) {
            $reqs = a7_ci_set_req_if_empty($reqs, 'community', $place);
        }
    }

    if (preg_match('/\b(?:budget|price|aed|dhs|dirhams?)\s*(?:of|is|around|about|under)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(k|m|million)?\b/i', $lower, $match) === 1
        || preg_match('/\b([0-9]{1,3}(?:\.[0-9]+)?)\s*(million|m)\b/i', $lower, $match) === 1
        || preg_match('/\b([0-9]{4,8})\b/', $lower, $match) === 1
    ) {
        $amount = str_replace(',', '', (string)$match[1]);
        $suffix = strtolower((string)($match[2] ?? ''));
        $numeric = (float)$amount;
        if ($suffix === 'k') {
            $amount .= 'k';
        } elseif ($suffix === 'm' || $suffix === 'million') {
            $amount .= ' million';
        }
        $looksLikeYear = $suffix === '' && $numeric >= 2020 && $numeric <= 2039;
        if (!$looksLikeYear && ($numeric >= 10 || $suffix !== '')) {
            $reqs = a7_ci_set_req_if_empty($reqs, 'budget', trim($amount));
        }
    }

    if (preg_match('/\b(cash|mortgage|installments?|payment plan|cheques?)\b/', $lower, $match) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'payment_method', $match[1]);
    }
    if (preg_match('/\b(immediately|asap|this month|next month|move[- ]in[^.]{0,40})\b/i', $text, $match) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'move_in_date', trim($match[1]));
    }
    if (preg_match('/\b(sea view|marina view|city view|park view|golf view|waterfront|burj view)\b/', $lower, $match) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'preferred_view', $match[1]);
    }
    if (preg_match('/\bnear (?:the )?(metro|school|beach|mall|hospital|park|mosque)\b/', $lower, $match) === 1) {
        $reqs = a7_ci_set_req_if_empty($reqs, 'proximity', 'near ' . $match[1]);
    }

    return $reqs;
}

function a7_ci_complete_requirements(array $reqs, string $transcript, string $summary): array
{
    $reqs = a7_ci_ensure_conversation_fields($reqs, $transcript, $summary);
    return a7_ci_enrich_requirements_from_text($reqs, $transcript, $summary);
}

function a7_ci_ensure_conversation_fields(array $reqs, string $transcript, string $summary): array
{
    $text = trim($transcript . "\n" . $summary);
    if (!a7_ci_is_real_conversation($summary) && !a7_ci_is_real_conversation($text)) {
        return $reqs;
    }
    if (($reqs['interest_level'] ?? null) === null) {
        $reqs['interest_level'] = a7_ci_infer_interest($text !== '' ? $text : $summary);
    }
    if (($reqs['notes'] ?? null) === null || trim((string)$reqs['notes']) === '') {
        $source = $summary !== '' ? $summary : $transcript;
        $reqs['notes'] = a7_ci_notes_from_conversation($source);
    }
    return $reqs;
}

function a7_ci_validate_requirements($raw): array
{
    $out = a7_ci_empty_requirements();
    if (!is_array($raw)) {
        return $out;
    }
    foreach (A7_CI_REQ_KEYS as $key) {
        if (!array_key_exists($key, $raw) || $raw[$key] === null) {
            continue;
        }
        $value = trim((string)$raw[$key]);
        $value = a7_ci_strip_prompt_leak($value);
        if ($value === '' || strtolower($value) === 'null' || strtolower($value) === 'n/a') {
            continue;
        }
        if (a7_ci_forbidden_script($value) || a7_ci_is_prompt_leak($value)) {
            continue;
        }
        if ($key === 'interest_level') {
            $norm = ucfirst(strtolower($value));
            if (!in_array($norm, ['High', 'Medium', 'Low'], true)) {
                continue;
            }
            $value = $norm;
        }
        $out[$key] = mb_substr($value, 0, $key === 'notes' ? 400 : 240);
    }
    return $out;
}

function a7_ci_merge_requirements(array $base, array $incoming): array
{
    foreach (A7_CI_REQ_KEYS as $key) {
        $value = $incoming[$key] ?? null;
        if ($value !== null && trim((string)$value) !== '') {
            $base[$key] = $value;
        }
    }
    return $base;
}

function a7_ci_norm_entity_type(string $type): string
{
    $type = strtoupper(trim($type));
    if ($type === '1' || $type === 'LEAD') {
        return 'LEAD';
    }
    if ($type === '3' || $type === 'CONTACT') {
        return 'CONTACT';
    }
    if ($type === '4' || $type === 'COMPANY') {
        return 'COMPANY';
    }
    if ($type === '2' || $type === 'DEAL') {
        return 'DEAL';
    }
    return $type;
}

function a7_ci_crm_panel(string $entityType, int $entityId): array
{
    $entityType = a7_ci_norm_entity_type($entityType);
    if ($entityId <= 0 || !in_array($entityType, ['CONTACT', 'LEAD'], true)) {
        return ['ok' => false, 'error' => 'invalid_entity'];
    }
    a7_ci_ensure_req_column();
    global $DB;
    $typeSql = $entityType === 'CONTACT'
        ? "IN ('CONTACT','3')"
        : "IN ('LEAD','1')";
    $res = $DB->Query(
        "SELECT i.client_requirements, i.ai_processed_at, i.ai_call_summary,
                i.ai_overall_score, i.next_action_type, i.next_action_date, i.next_action_time,
                s.COMMENT AS stat_comment,
                LEFT(i.transcript, 4000) AS transcript_snip
         FROM a7_call_intelligence i
         INNER JOIN b_voximplant_statistic s ON s.ID = i.statistic_id
         WHERE i.ai_status='COMPLETED'
           AND s.CRM_ENTITY_ID=" . $entityId . "
           AND s.CRM_ENTITY_TYPE " . $typeSql . "
         ORDER BY i.ai_processed_at ASC, i.id ASC",
        true
    );
    $merged = a7_ci_empty_requirements();
    $updated = '';
    $hasJob = false;
    $analysis = [
        'score' => null,
        'summary' => '',
        'next_action_type' => '',
        'next_action_label' => '',
        'next_action_date' => '',
        'next_action_time' => '',
        'comment' => '',
    ];
    if (is_object($res)) {
        while ($row = $res->Fetch()) {
            if (!is_array($row)) {
                continue;
            }
            $hasJob = true;
            $decoded = json_decode((string)($row['client_requirements'] ?? ''), true);
            $reqs = a7_ci_validate_requirements(is_array($decoded) ? $decoded : null);
            $reqs = a7_ci_complete_requirements(
                $reqs,
                (string)($row['transcript_snip'] ?? ''),
                (string)($row['ai_call_summary'] ?? '')
            );
            $merged = a7_ci_merge_requirements($merged, $reqs);
            if (trim((string)($row['ai_processed_at'] ?? '')) !== '') {
                $updated = (string)$row['ai_processed_at'];
            }
            $type = (string)($row['next_action_type'] ?? '');
            $analysis = [
                'score' => isset($row['ai_overall_score']) && $row['ai_overall_score'] !== null && $row['ai_overall_score'] !== ''
                    ? (int)$row['ai_overall_score']
                    : null,
                'summary' => (string)($row['ai_call_summary'] ?? ''),
                'next_action_type' => $type,
                'next_action_label' => a7_ci_action_label($type),
                'next_action_date' => a7_ci_sanitize_action_date((string)($row['next_action_date'] ?? '')),
                'next_action_time' => a7_ci_sanitize_action_time((string)($row['next_action_time'] ?? '')),
                'comment' => a7_ci_comment_from_row($row),
            ];
        }
    }
    $filled = 0;
    foreach ($merged as $value) {
        if ($value !== null && $value !== '') {
            $filled++;
        }
    }
    return [
        'ok' => true,
        'has_data' => $hasJob,
        'entity_type' => $entityType,
        'entity_id' => $entityId,
        'fields' => $merged,
        'analysis' => $analysis,
        'filled' => $filled,
        'updated_at' => $updated,
        'source' => 'AI Call Intelligence',
    ];
}

function a7_ci_digits(string $value): string
{
    return (string)preg_replace('/\D+/', '', $value);
}

function a7_ci_crm_calls(string $entityType, int $entityId): array
{
    $entityType = a7_ci_norm_entity_type($entityType);
    if ($entityId <= 0 || !in_array($entityType, ['CONTACT', 'LEAD'], true)) {
        return ['ok' => false, 'error' => 'invalid_entity'];
    }
    global $DB;
    $typeSql = $entityType === 'CONTACT'
        ? "IN ('CONTACT','3')"
        : "IN ('LEAD','1')";
    $res = $DB->Query(
        "SELECT s.ID AS statistic_id,
                s.CALL_ID,
                s.PHONE_NUMBER,
                s.PORTAL_NUMBER,
                s.CALL_START_DATE,
                s.CALL_DURATION,
                s.CRM_ACTIVITY_ID,
                s.CALL_RECORD_ID,
                s.CALL_RECORD_URL,
                t.ID AS timeline_id
         FROM b_voximplant_statistic s
         LEFT JOIN b_crm_timeline t
           ON t.ASSOCIATED_ENTITY_ID = s.CRM_ACTIVITY_ID
          AND t.ASSOCIATED_ENTITY_TYPE_ID = 6
          AND t.ASSOCIATED_ENTITY_CLASS_NAME = 'VOXIMPLANT_CALL'
         WHERE s.CRM_ENTITY_ID=" . $entityId . "
           AND s.CRM_ENTITY_TYPE " . $typeSql . "
           AND (
             IFNULL(s.CALL_RECORD_ID, 0) > 0
             OR IFNULL(s.CALL_RECORD_URL, '') <> ''
           )
         ORDER BY s.ID DESC
         LIMIT 80",
        true
    );
    $ids = [];
    $meta = [];
    if (is_object($res)) {
        while ($row = $res->Fetch()) {
            if (!is_array($row)) {
                continue;
            }
            $id = (int)($row['statistic_id'] ?? 0);
            if ($id <= 0 || isset($meta[$id])) {
                continue;
            }
            $ids[] = $id;
            $phone = (string)($row['PHONE_NUMBER'] ?? '');
            $portal = (string)($row['PORTAL_NUMBER'] ?? '');
            $meta[$id] = [
                'statistic_id' => $id,
                'call_id' => (string)($row['CALL_ID'] ?? ''),
                'phone_number' => $phone,
                'phone_digits' => a7_ci_digits($phone),
                'portal_number' => $portal,
                'portal_digits' => a7_ci_digits($portal),
                'call_start' => (string)($row['CALL_START_DATE'] ?? ''),
                'call_duration' => (int)($row['CALL_DURATION'] ?? 0),
                'crm_activity_id' => (int)($row['CRM_ACTIVITY_ID'] ?? 0),
                'timeline_id' => (int)($row['timeline_id'] ?? 0),
                'call_record_id' => (int)($row['CALL_RECORD_ID'] ?? 0),
                'call_record_url' => (string)($row['CALL_RECORD_URL'] ?? ''),
            ];
        }
    }
    $public = a7_ci_list_public_rows($ids);
    $rows = [];
    foreach ($ids as $id) {
        $row = $public[(string)$id] ?? a7_ci_public_row(null);
        $rows[] = array_merge($meta[$id], $row);
    }
    return [
        'ok' => true,
        'entity_type' => $entityType,
        'entity_id' => $entityId,
        'rows' => $rows,
    ];
}

function a7_ci_action_label(string $type): string
{
    $map = [
        'PROPERTY_VIEWING' => 'Property Viewing',
        'CALLBACK' => 'Callback',
        'FOLLOW_UP' => 'Follow-up Required',
        'SEND_PROPERTY_OPTIONS' => 'Send Property Options',
        'SEND_DETAILS' => 'Send Details',
        'NO_ACTION' => 'No Action Required',
    ];
    return $map[$type] ?? $type;
}

function a7_ci_parse_crm_entity(): ?array
{
    $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
    if (preg_match('#/crm/(contact|lead)/details/(\d+)#i', $uri, $match) === 1) {
        return ['type' => strtoupper($match[1]), 'id' => (int)$match[2]];
    }
    $type = strtoupper((string)($_REQUEST['entityTypeName'] ?? $_REQUEST['entityType'] ?? ''));
    $id = (int)($_REQUEST['entityId'] ?? $_REQUEST['entity_id'] ?? 0);
    if (in_array($type, ['CONTACT', 'LEAD'], true) && $id > 0) {
        return ['type' => $type, 'id' => $id];
    }
    return null;
}

function a7_ci_crm_boot_script(): string
{
    $entity = a7_ci_parse_crm_entity();
    if ($entity === null) {
        return '';
    }
    $payload = a7_ci_crm_panel($entity['type'], $entity['id']);
    return '<script>window.A7_CI_CRM_BOOT='
        . json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
        . ';</script>';
}

function a7_ci_refresh_requirements_from_transcript(array $job): bool
{
    $id = (int)($job['id'] ?? 0);
    $text = trim((string)($job['transcript'] ?? ''));
    if ($id <= 0 || $text === '' || a7_ci_is_no_conversation($text) || a7_ci_is_prompt_leak($text)) {
        return false;
    }
    $analysis = a7_ci_analyze($text, 'en');
    a7_ci_update($id, [
        'client_requirements' => json_encode(
            $analysis['client_requirements'],
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
        ),
    ]);
    a7_ci_write_crm_requirements((int)$job['statistic_id'], $analysis['client_requirements']);
    return true;
}

function a7_ci_write_crm_requirements(int $statisticId, array $requirements): void
{
    if ($statisticId <= 0) {
        return;
    }
    $hasValue = false;
    foreach ($requirements as $value) {
        if ($value !== null && trim((string)$value) !== '') {
            $hasValue = true;
            break;
        }
    }
    if (!$hasValue) {
        return;
    }
    // Intentionally do not patch native CRM user fields.
    // The Contact/Lead page reads these values from a7_call_intelligence.
}

function a7_ci_empty_analysis(string $reason): array
{
    $breakdown = [];
    foreach (A7_CI_SCORE_KEYS as $name) {
        $breakdown[$name] = 0;
    }
    return [
        'overall_score' => 0,
        'score_breakdown' => $breakdown,
        'call_summary' => $reason,
        'comment_line' => 'No conversation was detected on this recording. The call may not have connected.',
        'next_action' => [
            'type' => 'NO_ACTION',
            'date' => '',
            'time' => '',
            'confidence' => 1.0,
        ],
        'client_requirements' => a7_ci_empty_requirements(),
    ];
}

function a7_ci_choose_transcript_language(string $detected, string $text): string
{
    return 'en';
}

function a7_ci_analyze(string $transcript, string $language = ''): array
{
    $key = a7_ci_openai_key();
    if ($key === '') {
        throw new RuntimeException('openai_authentication');
    }
    $model = (string)a7_ci_settings()['A7_CI_MODEL_ANALYZE'];
    if ($model === '') {
        $model = 'gpt-4o-mini';
    }
    $schemaKeys = implode(', ', A7_CI_SCORE_KEYS);
    $actions = implode(', ', A7_CI_NEXT_ACTIONS);
    $payload = [
        'model' => $model,
        'temperature' => 0.1,
        'response_format' => ['type' => 'json_object'],
        'messages' => [
            [
                'role' => 'system',
                'content' =>
                    'You are A7 Group Real Estate call-quality analyst. '
                    . 'Analyze only the transcript. Never invent facts, names, prices, or promises. '
                    . 'Never use accent, gender, ethnicity, nationality, religion, age, or personal characteristics. '
                    . 'Score only professional call quality. '
                    . 'Write call_summary in English only. '
                    . 'If the transcript says no conversation was detected or the call did not connect, '
                    . 'say that clearly and do not invent a conversation. '
                    . 'Otherwise restate only what was actually said, in 2-4 sentences. '
                    . 'Return JSON with overall_score (0-100), score_breakdown object with keys: '
                    . $schemaKeys . ' (each 0-100), call_summary, comment_line, '
                    . 'and next_action {type, date, time, confidence}. '
                    . 'comment_line is a short English summary of the call only, 1-2 sentences. '
                    . 'Summarize only what was said. Do not say what did not happen, '
                    . 'and do not mention progress or no progress. '
                    . 'next_action.type must be one of: ' . $actions . '. '
                    . 'Today is ' . date('Y-m-d') . '. '
                    . 'next_action.date is YYYY-MM-DD or empty. time is HH:MM 24h or empty. '
                    . 'Only set date or time if the speakers named a real date or time. '
                    . 'Never invent a date, never use year 2023, never use a past year. '
                    . 'If no date was said, leave date and time empty. '
                    . 'confidence is 0-1. Do not propose CRM updates. '
                    . 'Also return client_requirements object with keys: '
                    . implode(', ', A7_CI_REQ_KEYS) . '. '
                    . 'For looking_for, property_type, community, budget, bedrooms, '
                    . 'move_in_date, payment_method, preferred_view, and proximity: '
                    . 'extract EVERY fact the CLIENT said on this call. Do not skip a mentioned '
                    . 'community, budget, bedrooms, property type, or buy/rent intent. '
                    . 'If the client did not say that field, set it to null. '
                    . 'Never guess those fields, never copy agent suggestions unless the client confirmed them. '
                    . 'interest_level is required when there was a real conversation: High, Medium, or Low. '
                    . 'High: client asked for a property, confirmed budget/community, requested viewing/details, or said they want it. '
                    . 'Medium: client spoke and is considering, asked questions, or said call later / not decided. '
                    . 'Low: client said not interested, already bought/rented, wrong number, or asked to stop calling. '
                    . 'null only if there was no real client conversation (voicemail, no connect, silence). '
                    . 'Never leave interest_level null when the client actually spoke. '
                    . 'notes is required when there was a real conversation: one short English sentence '
                    . 'of what the client said or how they responded. '
                    . 'Include extra detail that does not fit another field when available. '
                    . 'Never invent notes. Never copy the full summary into notes. '
                    . 'null notes only if there was no real client conversation. '
                    . 'All requirement values must be English or null.',
            ],
            [
                'role' => 'user',
                'content' => $transcript,
            ],
        ],
    ];
    $response = a7_ci_http_json(
        'https://api.openai.com/v1/chat/completions',
        [
            'Authorization: Bearer ' . $key,
            'Content-Type: application/json',
        ],
        $payload,
        90
    );
    $content = (string)($response['choices'][0]['message']['content'] ?? '');
    $decoded = json_decode($content, true);
    if (!is_array($decoded)) {
        throw new RuntimeException('invalid_ai_payload');
    }
    return a7_ci_validate_analysis($decoded, $transcript);
}

function a7_ci_validate_analysis(array $raw, string $transcript = ''): array
{
    $score = isset($raw['overall_score']) ? (int)round((float)$raw['overall_score']) : -1;
    if ($score < 0 || $score > 100) {
        throw new RuntimeException('invalid_ai_payload');
    }
    $breakdownRaw = is_array($raw['score_breakdown'] ?? null) ? $raw['score_breakdown'] : [];
    $breakdown = [];
    foreach (A7_CI_SCORE_KEYS as $name) {
        $value = isset($breakdownRaw[$name]) ? (int)round((float)$breakdownRaw[$name]) : 0;
        $breakdown[$name] = max(0, min(100, $value));
    }
    $summary = trim((string)($raw['call_summary'] ?? ''));
    $summary = mb_substr($summary, 0, 4000);
    if (
        $summary === ''
        || a7_ci_forbidden_script($summary)
        || a7_ci_has_arabic_script($summary)
        || a7_ci_is_prompt_leak($summary)
    ) {
        throw new RuntimeException('invalid_ai_payload');
    }
    $action = is_array($raw['next_action'] ?? null) ? $raw['next_action'] : [];
    $type = strtoupper(trim((string)($action['type'] ?? 'NO_ACTION')));
    if (!in_array($type, A7_CI_NEXT_ACTIONS, true)) {
        $type = 'NO_ACTION';
    }
    $date = a7_ci_sanitize_action_date(trim((string)($action['date'] ?? '')));
    $time = a7_ci_sanitize_action_time(trim((string)($action['time'] ?? '')));
    $confidence = isset($action['confidence']) ? (float)$action['confidence'] : 0.0;
    $confidence = max(0, min(1, $confidence));
    $commentLine = trim((string)($raw['comment_line'] ?? ''));
    $commentLine = a7_ci_strip_prompt_leak($commentLine);
    if ($commentLine === '' || a7_ci_forbidden_script($commentLine) || a7_ci_is_prompt_leak($commentLine)) {
        $commentLine = $summary;
    }
    $commentLine = mb_substr(trim($commentLine), 0, 500);
    return [
        'overall_score' => $score,
        'score_breakdown' => $breakdown,
        'call_summary' => $summary,
        'comment_line' => $commentLine,
        'next_action' => [
            'type' => $type,
            'date' => $date,
            'time' => $time,
            'confidence' => $confidence,
        ],
        'client_requirements' => a7_ci_complete_requirements(
            a7_ci_validate_requirements($raw['client_requirements'] ?? null),
            $transcript,
            $summary
        ),
    ];
}

function a7_ci_write_call_comment(int $statisticId, string $line): void
{
    global $DB;
    $line = trim($line);
    if ($statisticId <= 0 || $line === '') {
        return;
    }
    $line = 'AI: ' . mb_substr($line, 0, 500);
    $res = $DB->Query(
        'SELECT COMMENT FROM b_voximplant_statistic WHERE ID=' . $statisticId,
        true
    );
    $row = is_object($res) ? $res->Fetch() : false;
    $existing = is_array($row) ? trim((string)($row['COMMENT'] ?? '')) : '';
    if ($existing !== '' && strncmp($existing, 'AI:', 3) !== 0) {
        if (strpos($existing, 'AI:') !== false) {
            $existing = trim((string)preg_replace('/\s*\|\s*AI:.*$/s', '', $existing));
        }
        $line = mb_substr($existing . ' | ' . $line, 0, 800);
    }
    $DB->Query(
        'UPDATE b_voximplant_statistic SET COMMENT=' . a7_ci_sql($line) . ' WHERE ID=' . $statisticId,
        true
    );
}

function a7_ci_update(int $id, array $fields): void
{
    global $DB;
    $parts = [];
    foreach ($fields as $name => $value) {
        if ($value === null) {
            $parts[] = $name . '=NULL';
        } else {
            $parts[] = $name . '=' . a7_ci_sql((string)$value);
        }
    }
    $parts[] = 'updated_at=' . a7_ci_sql(a7_ci_now());
    $DB->Query(
        'UPDATE a7_call_intelligence SET ' . implode(',', $parts) . ' WHERE id=' . $id,
        true
    );
}

function a7_ci_claim_job(): ?array
{
    global $DB;
    $res = $DB->Query(
        "SELECT * FROM a7_call_intelligence
         WHERE ai_status='PENDING'
         ORDER BY id DESC
         LIMIT 50",
        true
    );
    if (!is_object($res)) {
        return null;
    }
    while ($row = $res->Fetch()) {
        if (!is_array($row)) {
            continue;
        }
        $stat = a7_ci_load_statistic((int)$row['statistic_id']);
        if (!a7_ci_is_new_call($stat) || !a7_ci_recording_ready($stat)) {
            continue;
        }
        $id = (int)$row['id'];
        $now = a7_ci_now();
        $DB->Query(
            "UPDATE a7_call_intelligence
             SET ai_status='TRANSCRIBING', updated_at=" . a7_ci_sql($now) . "
             WHERE id=" . $id . " AND ai_status='PENDING'",
            true
        );
        $check = $DB->Query(
            "SELECT * FROM a7_call_intelligence WHERE id=" . $id . " AND ai_status='TRANSCRIBING'",
            true
        );
        $claimed = is_object($check) ? $check->Fetch() : false;
        if (is_array($claimed)) {
            return $claimed;
        }
    }
    return null;
}

function a7_ci_process_one(array $job): void
{
    $id = (int)$job['id'];
    if ((string)$job['ai_status'] === 'COMPLETED' && trim((string)($job['transcript'] ?? '')) !== '') {
        return;
    }
    $existingTranscript = trim((string)($job['transcript'] ?? ''));
    try {
        if ($existingTranscript !== '' && !a7_ci_is_prompt_leak($existingTranscript)) {
            $transcript = [
                'text' => $existingTranscript,
                'language' => (string)($job['transcript_language'] ?? 'en'),
                'no_conversation' => a7_ci_is_no_conversation($existingTranscript),
            ];
        } else {
            $fileId = (int)$job['recording_file_id'];
            $stat = a7_ci_load_statistic((int)($job['statistic_id'] ?? 0));
            $path = a7_ci_resolve_recording($stat);
            if ($path === '') {
                $path = a7_ci_recording_path($fileId);
            }
            if ($path === '') {
                a7_ci_update($id, [
                    'ai_status' => 'FAILED',
                    'ai_error' => 'recording_unreadable',
                ]);
                return;
            }
            $transcript = a7_ci_transcribe($path);
            a7_ci_update($id, [
                'ai_status' => 'ANALYZING',
                'transcript' => $transcript['text'],
                'transcript_language' => $transcript['language'],
            ]);
        }
        if (!empty($transcript['no_conversation']) || a7_ci_is_no_conversation((string)$transcript['text'])) {
            $analysis = a7_ci_empty_analysis(a7_ci_no_conversation_text());
            $transcript['text'] = a7_ci_no_conversation_text();
        } else {
            $analysis = a7_ci_analyze($transcript['text'], (string)($transcript['language'] ?? ''));
        }
        a7_ci_update($id, [
            'ai_status' => 'COMPLETED',
            'transcript' => $transcript['text'],
            'transcript_language' => 'en',
            'ai_overall_score' => (string)$analysis['overall_score'],
            'ai_score_breakdown' => json_encode($analysis['score_breakdown'], JSON_UNESCAPED_UNICODE),
            'ai_call_summary' => $analysis['call_summary'],
            'next_action_type' => $analysis['next_action']['type'],
            'next_action_date' => $analysis['next_action']['date'] !== '' ? $analysis['next_action']['date'] : null,
            'next_action_time' => $analysis['next_action']['time'] !== '' ? $analysis['next_action']['time'] : null,
            'next_action_confidence' => (string)$analysis['next_action']['confidence'],
            'client_requirements' => json_encode(
                $analysis['client_requirements'],
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            ),
            'ai_processed_at' => a7_ci_now(),
            'ai_error' => null,
        ]);
        a7_ci_write_crm_requirements((int)$job['statistic_id'], $analysis['client_requirements']);
    } catch (Throwable $error) {
        a7_ci_update($id, [
            'ai_status' => 'FAILED',
            'ai_error' => a7_ci_safe_error($error->getMessage()),
        ]);
    }
}

function a7_call_intelligence_agent(): string
{
    $settings = a7_ci_settings();
    if ((string)$settings['A7_CI_ENABLED'] !== '1') {
        return 'a7_call_intelligence_agent();';
    }
    if (!a7_ci_ensure_table()) {
        return 'a7_call_intelligence_agent();';
    }
    a7_ci_ensure_agent();
    a7_ci_reclaim_stale(180);
    try {
        a7_ci_queue_new_calls(20);
    } catch (Throwable $error) {
    }
    if (a7_ci_openai_key() === '') {
        return 'a7_call_intelligence_agent();';
    }
    if (a7_ci_active_job() !== null) {
        return 'a7_call_intelligence_agent();';
    }
    $job = a7_ci_claim_job();
    if ($job !== null) {
        a7_ci_process_one($job);
    }
    return 'a7_call_intelligence_agent();';
}

if (!defined('A7_CI_LIB_ONLY') && PHP_SAPI !== 'cli' && isset($_REQUEST['action'])) {
    a7_ci_handle_http();
}
