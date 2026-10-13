<?php
/**
 * Background job store + worker for team assign.
 * Loaded by tools/a7_team_assign.php and cron.
 */

function a7_ta_job_dir(array $cfg): string
{
    $dir = (string)($cfg['job_dir'] ?? '/home/bitrix/www/upload/a7_team_assign/jobs');
    if (!is_dir($dir)) {
        @mkdir($dir, 0755, true);
    }
    return $dir;
}

function a7_ta_job_path(array $cfg, string $jobId): string
{
    $jobId = preg_replace('/[^a-zA-Z0-9_-]/', '', $jobId);
    return a7_ta_job_dir($cfg) . '/' . $jobId . '.json';
}

function a7_ta_job_assign_path(array $cfg, string $jobId): string
{
    $jobId = preg_replace('/[^a-zA-Z0-9_-]/', '', $jobId);
    return a7_ta_job_dir($cfg) . '/' . $jobId . '.assignments.json';
}

function a7_ta_job_read(array $cfg, string $jobId): ?array
{
    $path = a7_ta_job_path($cfg, $jobId);
    if (!is_readable($path)) {
        return null;
    }
    $data = json_decode((string)file_get_contents($path), true);
    return is_array($data) ? $data : null;
}

function a7_ta_job_write(array $cfg, array $job): bool
{
    $jobId = (string)($job['id'] ?? '');
    if ($jobId === '') {
        return false;
    }
    $path = a7_ta_job_path($cfg, $jobId);
    $tmp = $path . '.tmp';
    $json = json_encode($job, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if ($json === false) {
        return false;
    }
    if (file_put_contents($tmp, $json) === false) {
        return false;
    }
    return @rename($tmp, $path);
}

/**
 * @param list<array{id:int,user_id:int}> $assignments
 */
function a7_ta_job_create(
    array $cfg,
    string $entity,
    int $userId,
    array $assignments,
    string $stage,
    array $agentStages
): array {
    $jobId = 'ta_' . date('Ymd_His') . '_' . bin2hex(random_bytes(4));
    $assignPath = a7_ta_job_assign_path($cfg, $jobId);
    $compact = [];
    foreach ($assignments as $row) {
        $compact[] = [(int)$row['id'], (int)$row['user_id']];
    }
    file_put_contents($assignPath, json_encode($compact, JSON_UNESCAPED_SLASHES));
    $job = [
        'id' => $jobId,
        'status' => 'pending',
        'entity' => $entity,
        'user_id' => $userId,
        'created' => time(),
        'updated' => time(),
        'total' => count($compact),
        'cursor' => 0,
        'ok' => 0,
        'fail' => 0,
        'stage' => $stage,
        'agent_stages' => $agentStages,
        'errors' => [],
        'assign_file' => basename($assignPath),
    ];
    a7_ta_job_write($cfg, $job);
    return $job;
}

function a7_ta_job_kick(array $cfg): void
{
    $cron = (string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www') . '/bitrix/php_interface/a7_team_assign_cron.php';
    if (!is_readable($cron)) {
        return;
    }
    $php = '/usr/bin/php';
    if (!is_executable($php)) {
        $php = 'php';
    }
    // Fire-and-forget; cron is the safety net.
    @exec('nohup ' . escapeshellarg($php) . ' -f ' . escapeshellarg($cron) . ' >/dev/null 2>&1 &');
}

/**
 * Process pending/running jobs for up to ~50s at configured pace.
 */
function a7_ta_job_run_worker(array $cfg, int $budgetSec = 50): array
{
    if (!function_exists('a7_ta_apply_one')) {
        $tool = (string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www') . '/bitrix/tools/a7_team_assign.php';
        // Cannot include tool (HTTP router). Apply helper must be loaded by cron bootstrap.
        return ['error' => 'apply helper missing'];
    }
    if (!\Bitrix\Main\Loader::includeModule('crm')) {
        return ['error' => 'crm missing'];
    }

    $dir = a7_ta_job_dir($cfg);
    $files = glob($dir . '/ta_*.json') ?: [];
    sort($files);
    $chunk = max(5, (int)($cfg['chunk'] ?? 25));
    $sleepUs = max(0, (int)($cfg['sleep_us'] ?? 70000));
    $started = time();
    $processed = 0;
    $jobsTouched = 0;

    foreach ($files as $path) {
        if ((time() - $started) >= $budgetSec) {
            break;
        }
        $job = json_decode((string)@file_get_contents($path), true);
        if (!is_array($job)) {
            continue;
        }
        $status = (string)($job['status'] ?? '');
        if (!in_array($status, ['pending', 'running'], true)) {
            continue;
        }
        $jobId = (string)$job['id'];
        $assignPath = a7_ta_job_assign_path($cfg, $jobId);
        if (!is_readable($assignPath)) {
            $job['status'] = 'failed';
            $job['errors'][] = 'assignments file missing';
            $job['updated'] = time();
            a7_ta_job_write($cfg, $job);
            continue;
        }
        $assignments = json_decode((string)file_get_contents($assignPath), true);
        if (!is_array($assignments)) {
            $job['status'] = 'failed';
            $job['errors'][] = 'assignments corrupt';
            $job['updated'] = time();
            a7_ta_job_write($cfg, $job);
            continue;
        }

        $job['status'] = 'running';
        $jobsTouched++;
        $entity = (string)$job['entity'];
        $stage = (string)($job['stage'] ?? '__KEEP__');
        $agentStages = is_array($job['agent_stages'] ?? null) ? $job['agent_stages'] : [];
        $cursor = (int)($job['cursor'] ?? 0);
        $total = count($assignments);
        $job['total'] = $total;

        // Authorize as the user who queued (robots / permissions).
        global $USER;
        $prevUser = $USER;
        $runAs = (int)($job['user_id'] ?? 0);
        if ($runAs > 0 && is_object($USER)) {
            $USER->Authorize($runAs);
        }

        while ($cursor < $total && (time() - $started) < $budgetSec) {
            $n = 0;
            while ($cursor < $total && $n < $chunk && (time() - $started) < $budgetSec) {
                $row = $assignments[$cursor];
                $id = (int)($row[0] ?? 0);
                $uid = (int)($row[1] ?? 0);
                $cursor++;
                $n++;
                $processed++;
                $rowStage = $stage;
                if (isset($agentStages[(string)$uid]) && $agentStages[(string)$uid] !== '') {
                    $rowStage = (string)$agentStages[(string)$uid];
                } elseif (isset($agentStages[$uid]) && $agentStages[$uid] !== '') {
                    $rowStage = (string)$agentStages[$uid];
                }
                try {
                    $result = a7_ta_apply_one($entity, $id, $uid, $rowStage);
                } catch (Throwable $e) {
                    $result = ['ok' => false, 'error' => $e->getMessage()];
                }
                if (!empty($result['ok'])) {
                    $job['ok'] = (int)$job['ok'] + 1;
                } else {
                    $job['fail'] = (int)$job['fail'] + 1;
                    if (count($job['errors']) < 12) {
                        $job['errors'][] = '#' . $id . ': ' . ($result['error'] ?? 'failed');
                    }
                }
                if ($sleepUs > 0) {
                    usleep($sleepUs);
                }
            }
            // Checkpoint after each chunk so UI poll sees progress.
            $job['cursor'] = $cursor;
            $job['updated'] = time();
            if ($cursor >= $total) {
                $job['status'] = ((int)$job['fail'] > 0) ? 'done_with_errors' : 'done';
                @unlink($assignPath);
            }
            a7_ta_job_write($cfg, $job);
        }

        if (is_object($prevUser) && method_exists($prevUser, 'GetID')) {
            $prevId = (int)$prevUser->GetID();
            if ($prevId > 0) {
                $USER->Authorize($prevId);
            }
        }

        // Finish this job later if budget ran out; cron/nohup will resume.
        if ($cursor < $total) {
            break;
        }
    }

    return [
        'ok' => true,
        'jobs_touched' => $jobsTouched,
        'processed' => $processed,
        'budget_sec' => $budgetSec,
    ];
}
