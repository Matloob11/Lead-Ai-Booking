<?php
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
define('DisableEventsCheck', true);
define('StopBuffer', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=UTF-8');

const A7_HR_CV_ENTITY_TYPE_IDS = [1156, 1210];
const A7_HR_CV_STAGE_COLORS = [
    '#2FC6F6',
    '#00C7F0',
    '#A8A4FF',
    '#9DCF00',
    '#47C964',
    '#FFA900',
    '#A8ADB4',
];

function a7_hr_cv_stage_fail(string $message, int $status = 400): void
{
    http_response_code($status);
    echo json_encode(['ok' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    die();
}

function a7_hr_cv_stage_payload(): array
{
    $raw = file_get_contents('php://input');
    $payload = [];
    if (is_string($raw) && $raw !== '') {
        $decoded = json_decode($raw, true);
        if (is_array($decoded)) {
            $payload = $decoded;
        }
    }
    return $payload;
}

function a7_hr_cv_stage_norm(string $name): string
{
    return mb_strtolower(trim(preg_replace('/\s+/', ' ', $name) ?? ''));
}

function a7_hr_cv_stage_clean_name(string $name): string
{
    $name = trim(preg_replace('/\s+/', ' ', $name) ?? '');
    $name = str_replace(["\0", '<', '>', "\r", "\n"], '', $name);
    return $name;
}

function a7_hr_cv_stage_load_statuses(int $entityTypeId, int $categoryId): array
{
    $statusEntityId = 'DYNAMIC_' . $entityTypeId . '_STAGE_' . $categoryId;
    $status = new \CCrmStatus($statusEntityId);
    $rows = \CCrmStatus::GetStatus($statusEntityId);
    if (!is_array($rows)) {
        $rows = [];
    }
    return [$statusEntityId, $status, $rows];
}

function a7_hr_cv_stage_find(array $rows, string $name): ?array
{
    $wanted = a7_hr_cv_stage_norm($name);
    if ($wanted === '') {
        return null;
    }
    foreach ($rows as $row) {
        if (a7_hr_cv_stage_norm((string)($row['NAME'] ?? '')) === $wanted) {
            return $row;
        }
    }
    return null;
}

function a7_hr_cv_stage_is_final(array $row): bool
{
    $statusId = (string)($row['STATUS_ID'] ?? '');
    $suffix = str_contains($statusId, ':') ? substr($statusId, strrpos($statusId, ':') + 1) : $statusId;
    $semantics = (string)($row['SEMANTICS'] ?? '');
    return in_array($suffix, ['SUCCESS', 'FAIL'], true)
        || in_array($semantics, ['S', 'F'], true);
}

function a7_hr_cv_stage_options(array $rows): array
{
    $list = array_values($rows);
    usort($list, static function (array $a, array $b): int {
        return ((int)($a['SORT'] ?? 0)) <=> ((int)($b['SORT'] ?? 0));
    });

    $options = [];
    foreach ($list as $row) {
        $name = trim((string)($row['NAME'] ?? ''));
        $stageId = (string)($row['STATUS_ID'] ?? '');
        if ($name === '' || $stageId === '') {
            continue;
        }
        $options[] = [
            'name' => $name,
            'stageId' => $stageId,
            'color' => (string)($row['COLOR'] ?? ''),
        ];
    }
    return $options;
}

function a7_hr_cv_stage_selected(array $options, string $currentStageId): string
{
    foreach ($options as $option) {
        if ($option['stageId'] === $currentStageId) {
            return $option['name'];
        }
    }
    return '';
}

function a7_hr_cv_stage_ensure(
    \CCrmStatus $status,
    string $statusEntityId,
    int $categoryId,
    array $rows,
    string $name
): array {
    $found = a7_hr_cv_stage_find($rows, $name);
    if ($found) {
        return $found;
    }

    $maxSort = 0;
    $colorIndex = 0;
    foreach ($rows as $row) {
        if (a7_hr_cv_stage_is_final($row)) {
            continue;
        }
        $sort = (int)($row['SORT'] ?? 0);
        if ($sort > $maxSort) {
            $maxSort = $sort;
        }
        $colorIndex++;
    }

    $id = $status->Add([
        'NAME' => $name,
        'SORT' => $maxSort + 10,
        'COLOR' => A7_HR_CV_STAGE_COLORS[$colorIndex % count(A7_HR_CV_STAGE_COLORS)],
        'SYSTEM' => 'N',
        'CATEGORY_ID' => $categoryId,
    ]);
    if (!$id) {
        $error = method_exists($status, 'GetLastError') ? (string)$status->GetLastError() : '';
        a7_hr_cv_stage_fail($error !== '' ? $error : 'Could not create category ' . $name, 500);
    }

    $fresh = \CCrmStatus::GetStatus($statusEntityId);
    $created = a7_hr_cv_stage_find(is_array($fresh) ? $fresh : [], $name);
    if (!$created) {
        a7_hr_cv_stage_fail('Category was created but could not be loaded', 500);
    }
    return $created;
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_hr_cv_stage_fail('Not authenticated', 401);
}

$payload = a7_hr_cv_stage_payload();
if (!empty($payload['sessid']) && empty($_REQUEST['sessid'])) {
    $_REQUEST['sessid'] = (string)$payload['sessid'];
    $_POST['sessid'] = (string)$payload['sessid'];
}
if (!check_bitrix_sessid()) {
    a7_hr_cv_stage_fail('Session expired. Refresh the page and try again.', 403);
}
if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_hr_cv_stage_fail('CRM module is not available', 500);
}

$action = trim((string)($payload['action'] ?? $_POST['action'] ?? 'list'));
$entityTypeId = (int)($payload['entityTypeId'] ?? $_POST['entityTypeId'] ?? 0);
$itemId = (int)($payload['itemId'] ?? $_POST['itemId'] ?? 0);
$stageName = a7_hr_cv_stage_clean_name((string)($payload['stageName'] ?? $_POST['stageName'] ?? ''));

if (!in_array($entityTypeId, A7_HR_CV_ENTITY_TYPE_IDS, true)) {
    a7_hr_cv_stage_fail('This dropdown is only for Applicant CVs');
}
if ($itemId <= 0) {
    a7_hr_cv_stage_fail('CV not found');
}

$container = \Bitrix\Crm\Service\Container::getInstance();
$factory = $container->getFactory($entityTypeId);
if (!$factory) {
    a7_hr_cv_stage_fail('Applicant board not found', 404);
}

$item = $factory->getItem($itemId);
if (!$item) {
    a7_hr_cv_stage_fail('CV not found', 404);
}

$userPermissions = $container->getUserPermissions();
if (method_exists($userPermissions, 'item') && !$userPermissions->item()->canReadItem($item)) {
    a7_hr_cv_stage_fail('You do not have permission to open this CV', 403);
}

$categoryId = (int)$item->getCategoryId();
[$statusEntityId, $status, $rows] = a7_hr_cv_stage_load_statuses($entityTypeId, $categoryId);
$options = a7_hr_cv_stage_options($rows);
$currentStageId = (string)$item->getStageId();

if ($action === 'list') {
    echo json_encode([
        'ok' => true,
        'currentStageId' => $currentStageId,
        'selected' => a7_hr_cv_stage_selected($options, $currentStageId),
        'options' => $options,
    ], JSON_UNESCAPED_UNICODE);
    die();
}

if ($action !== 'save') {
    a7_hr_cv_stage_fail('Unknown action');
}

if (method_exists($userPermissions, 'item') && !$userPermissions->item()->canUpdateItem($item)) {
    a7_hr_cv_stage_fail('You do not have permission to change this CV stage', 403);
}

if ($stageName === '') {
    a7_hr_cv_stage_fail('Enter a category name');
}
if (mb_strlen($stageName) > 80) {
    a7_hr_cv_stage_fail('Category name is too long');
}

$target = a7_hr_cv_stage_find($rows, $stageName);
$created = false;
if (!$target) {
    $target = a7_hr_cv_stage_ensure($status, $statusEntityId, $categoryId, $rows, $stageName);
    $created = true;
}

$item->setStageId((string)$target['STATUS_ID']);
$operation = $factory->getUpdateOperation($item);
$result = $operation->launch();
if (!$result->isSuccess()) {
    a7_hr_cv_stage_fail(implode('; ', $result->getErrorMessages()), 500);
}

$freshRows = \CCrmStatus::GetStatus($statusEntityId);
$options = a7_hr_cv_stage_options(is_array($freshRows) ? $freshRows : []);
echo json_encode([
    'ok' => true,
    'created' => $created,
    'stageId' => (string)$target['STATUS_ID'],
    'selected' => (string)($target['NAME'] ?? $stageName),
    'options' => $options,
], JSON_UNESCAPED_UNICODE);
