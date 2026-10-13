<?php
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
define('DisableEventsCheck', true);
define('StopBuffer', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=UTF-8');

const A7_HR_ENTITY_TYPE_IDS = [1156, 1160, 1168, 1172, 1210, 1212, 1214, 1216];

function a7_hr_stage_remove_fail(string $message, int $status = 400): void
{
    http_response_code($status);
    echo json_encode(['ok' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    die();
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_hr_stage_remove_fail('Not authenticated', 401);
}

$raw = file_get_contents('php://input');
$payload = [];
if (is_string($raw) && $raw !== '') {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $payload = $decoded;
    }
}

if (!empty($payload['sessid']) && empty($_REQUEST['sessid'])) {
    $_REQUEST['sessid'] = (string)$payload['sessid'];
    $_POST['sessid'] = (string)$payload['sessid'];
}

if (!check_bitrix_sessid()) {
    a7_hr_stage_remove_fail('Session expired. Refresh the page and try again.', 403);
}

if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_hr_stage_remove_fail('CRM module is not available', 500);
}

$entityTypeId = (int)($payload['entityTypeId'] ?? $_POST['entityTypeId'] ?? 0);
$stageId = trim((string)($payload['stageId'] ?? $_POST['stageId'] ?? ''));

if (!in_array($entityTypeId, A7_HR_ENTITY_TYPE_IDS, true)) {
    a7_hr_stage_remove_fail('Remove is only allowed on HR boards');
}

if (!preg_match('/^DT(\d+)_(\d+):[A-Z0-9_]+$/', $stageId, $match)) {
    a7_hr_stage_remove_fail('Invalid column');
}

$parsedTypeId = (int)$match[1];
$categoryId = (int)$match[2];
if ($parsedTypeId !== $entityTypeId) {
    a7_hr_stage_remove_fail('Column does not belong to this board');
}

$container = \Bitrix\Crm\Service\Container::getInstance();
$factory = $container->getFactory($entityTypeId);
if (!$factory) {
    a7_hr_stage_remove_fail('Board not found', 404);
}

$userPermissions = $container->getUserPermissions();
$canManage = false;
if (method_exists($userPermissions, 'isAdminForEntity')) {
    $canManage = (bool)$userPermissions->isAdminForEntity($entityTypeId);
}
if (!$canManage && method_exists($userPermissions, 'checkAddPermissions')) {
    $canManage = (bool)$userPermissions->checkAddPermissions($entityTypeId, $categoryId);
}
if (!$canManage && method_exists($userPermissions, 'checkReadPermissions')) {
    $canManage = (bool)$userPermissions->checkReadPermissions($entityTypeId, 0, $categoryId);
}
if (!$canManage && class_exists('A7StageAdmin') && A7StageAdmin::isHrStageManager()) {
    $canManage = true;
}
if (!$canManage) {
    a7_hr_stage_remove_fail('You do not have permission to remove this column', 403);
}

$connection = \Bitrix\Main\Application::getConnection();
$sqlHelper = $connection->getSqlHelper();
$tableName = $factory->getDataClass()::getTableName();
if (!preg_match('/^b_crm_dynamic_items_\d+$/', $tableName)) {
    a7_hr_stage_remove_fail('Unsupported board table', 500);
}
$count = (int)$connection->queryScalar(
    'SELECT COUNT(*) FROM ' . $tableName
    . " WHERE STAGE_ID = '" . $sqlHelper->forSql($stageId) . "'"
);
if ($count > 0) {
    a7_hr_stage_remove_fail('This column has data, so it cannot be deleted.');
}

$statusEntityId = 'DYNAMIC_' . $entityTypeId . '_STAGE_' . $categoryId;
$status = new \CCrmStatus($statusEntityId);
$info = $status->GetStatusByStatusId($stageId);
if (!$info) {
    a7_hr_stage_remove_fail('Column not found', 404);
}
if (($info['SYSTEM'] ?? 'N') === 'Y') {
    a7_hr_stage_remove_fail('System columns cannot be deleted.');
}

$status->delete((int)$info['ID']);
$lastError = method_exists($status, 'GetLastError') ? (string)$status->GetLastError() : '';
if ($lastError !== '') {
    a7_hr_stage_remove_fail($lastError, 500);
}

echo json_encode([
    'ok' => true,
    'stageId' => $stageId,
], JSON_UNESCAPED_UNICODE);
