<?php
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
define('DisableEventsCheck', true);
define('StopBuffer', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

header('Content-Type: application/json; charset=UTF-8');

const A7_HR_APPLIED_ENTITY_TYPE_IDS = [1156, 1210];
const A7_HR_APPLIED_FIELDS = [
    1156 => 'UF_CRM_32_APPLIED_POSITION',
    1210 => 'UF_CRM_45_APPLIED_POSITION',
];
const A7_HR_APPLIED_OPTION_MODULE = 'a7_hr';
const A7_HR_APPLIED_OPTION_NAME = 'applied_positions';

function a7_hr_applied_fail(string $message, int $status = 400): void
{
    http_response_code($status);
    echo json_encode(['ok' => false, 'error' => $message], JSON_UNESCAPED_UNICODE);
    die();
}

function a7_hr_applied_payload(): array
{
    $raw = file_get_contents('php://input');
    if (!is_string($raw) || $raw === '') {
        return [];
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : [];
}

function a7_hr_applied_clean_name(string $name): string
{
    $name = trim(preg_replace('/\s+/', ' ', $name) ?? '');
    return str_replace(["\0", '<', '>', "\r", "\n"], '', $name);
}

function a7_hr_applied_norm(string $name): string
{
    return mb_strtolower(a7_hr_applied_clean_name($name));
}

function a7_hr_applied_clean_color(string $color): string
{
    $color = trim($color);
    if (preg_match('/^#[0-9A-Fa-f]{6}$/', $color) !== 1) {
        return '';
    }
    return strtoupper($color);
}

function a7_hr_applied_defaults(): array
{
    return [
        ['name' => 'IT Team', 'color' => '#2F80ED'],
        ['name' => 'Sales Associate', 'color' => '#27AE60'],
        ['name' => 'Social Media', 'color' => '#9B51E0'],
        ['name' => 'HR', 'color' => '#EB6EA5'],
        ['name' => 'Finance', 'color' => '#F2C94C'],
        ['name' => 'Receptionist', 'color' => '#F2994A'],
    ];
}

function a7_hr_applied_catalog(): array
{
    $raw = (string)\Bitrix\Main\Config\Option::get(
        A7_HR_APPLIED_OPTION_MODULE,
        A7_HR_APPLIED_OPTION_NAME,
        ''
    );
    if ($raw === '') {
        $decoded = a7_hr_applied_defaults();
        a7_hr_applied_save_catalog($decoded);
    } else {
        $decoded = json_decode($raw, true);
        if (!is_array($decoded)) {
            $decoded = a7_hr_applied_defaults();
            a7_hr_applied_save_catalog($decoded);
        }
    }

    $out = [];
    $seen = [];
    foreach ($decoded as $row) {
        if (!is_array($row)) {
            continue;
        }
        $name = a7_hr_applied_clean_name((string)($row['name'] ?? ''));
        $color = a7_hr_applied_clean_color((string)($row['color'] ?? ''));
        $key = a7_hr_applied_norm($name);
        if ($name === '' || $color === '' || isset($seen[$key])) {
            continue;
        }
        $seen[$key] = true;
        $out[] = ['name' => $name, 'color' => $color];
    }
    return $out;
}

function a7_hr_applied_save_catalog(array $catalog): void
{
    \Bitrix\Main\Config\Option::set(
        A7_HR_APPLIED_OPTION_MODULE,
        A7_HR_APPLIED_OPTION_NAME,
        json_encode(array_values($catalog), JSON_UNESCAPED_UNICODE)
    );
}

function a7_hr_applied_find(array $catalog, string $name): ?array
{
    $wanted = a7_hr_applied_norm($name);
    if ($wanted === '') {
        return null;
    }
    foreach ($catalog as $row) {
        if (a7_hr_applied_norm((string)$row['name']) === $wanted) {
            return $row;
        }
    }
    return null;
}

function a7_hr_applied_item_value(\Bitrix\Crm\Item $item, string $field): string
{
    $value = null;
    try {
        $value = $item->get($field);
    } catch (\Throwable $e) {
        $value = null;
    }
    if ($value === null || $value === '') {
        $data = $item->getCompatibleData();
        $value = $data[$field] ?? '';
    }
    if (is_array($value)) {
        $value = implode(' ', $value);
    }
    return a7_hr_applied_clean_name((string)$value);
}

global $USER;
if (!is_object($USER) || !$USER->IsAuthorized()) {
    a7_hr_applied_fail('Not authenticated', 401);
}

$payload = a7_hr_applied_payload();
if (!empty($payload['sessid']) && empty($_REQUEST['sessid'])) {
    $_REQUEST['sessid'] = (string)$payload['sessid'];
    $_POST['sessid'] = (string)$payload['sessid'];
}
if (!check_bitrix_sessid()) {
    a7_hr_applied_fail('Session expired. Refresh the page and try again.', 403);
}
if (!\Bitrix\Main\Loader::includeModule('crm')) {
    a7_hr_applied_fail('CRM module is not available', 500);
}

$action = trim((string)($payload['action'] ?? 'list'));
$entityTypeId = (int)($payload['entityTypeId'] ?? 0);
$itemId = (int)($payload['itemId'] ?? 0);
$positionName = a7_hr_applied_clean_name((string)($payload['positionName'] ?? ''));
$color = a7_hr_applied_clean_color((string)($payload['color'] ?? ''));

if (!in_array($entityTypeId, A7_HR_APPLIED_ENTITY_TYPE_IDS, true)) {
    a7_hr_applied_fail('This field is only for Applicant CVs');
}

$field = A7_HR_APPLIED_FIELDS[$entityTypeId] ?? '';
if ($field === '') {
    a7_hr_applied_fail('Applied Position field is missing', 500);
}

$container = \Bitrix\Crm\Service\Container::getInstance();
$factory = $container->getFactory($entityTypeId);
if (!$factory) {
    a7_hr_applied_fail('Applicant board not found', 404);
}

if ($action === 'kanban') {
    $rawIds = $payload['itemIds'] ?? [];
    if (!is_array($rawIds)) {
        $rawIds = [];
    }
    $ids = [];
    foreach ($rawIds as $rawId) {
        $id = (int)$rawId;
        if ($id > 0) {
            $ids[$id] = $id;
        }
        if (count($ids) >= 80) {
            break;
        }
    }
    $catalog = a7_hr_applied_catalog();
    $map = [];
    if ($ids) {
        $items = $factory->getItems([
            'filter' => ['@ID' => array_values($ids)],
            'limit' => 80,
        ]);
        $userPermissions = $container->getUserPermissions();
        foreach ($items as $kanbanItem) {
            if (method_exists($userPermissions, 'item') && !$userPermissions->item()->canReadItem($kanbanItem)) {
                continue;
            }
            $value = a7_hr_applied_item_value($kanbanItem, $field);
            $row = a7_hr_applied_find($catalog, $value);
            $map[(string)$kanbanItem->getId()] = [
                'name' => $row['name'] ?? $value,
                'color' => $row['color'] ?? '',
            ];
        }
    }
    echo json_encode(['ok' => true, 'items' => $map], JSON_UNESCAPED_UNICODE);
    die();
}

if ($itemId <= 0) {
    a7_hr_applied_fail('CV not found');
}

$item = $factory->getItem($itemId);
if (!$item) {
    a7_hr_applied_fail('CV not found', 404);
}

$userPermissions = $container->getUserPermissions();
if (method_exists($userPermissions, 'item') && !$userPermissions->item()->canReadItem($item)) {
    a7_hr_applied_fail('You do not have permission to open this CV', 403);
}

$catalog = a7_hr_applied_catalog();
$selected = a7_hr_applied_item_value($item, $field);
$selectedRow = a7_hr_applied_find($catalog, $selected);

if ($action === 'list') {
    echo json_encode([
        'ok' => true,
        'selected' => $selectedRow['name'] ?? $selected,
        'color' => $selectedRow['color'] ?? '',
        'options' => $catalog,
    ], JSON_UNESCAPED_UNICODE);
    die();
}

if (!in_array($action, ['save', 'add', 'delete'], true)) {
    a7_hr_applied_fail('Unknown action');
}

if (method_exists($userPermissions, 'item') && !$userPermissions->item()->canUpdateItem($item)) {
    a7_hr_applied_fail('You do not have permission to change this CV', 403);
}

if ($action === 'add') {
    if ($positionName === '') {
        a7_hr_applied_fail('Enter a position name');
    }
    if (mb_strlen($positionName) > 80) {
        a7_hr_applied_fail('Position name is too long');
    }
    if ($color === '') {
        a7_hr_applied_fail('Pick a valid color');
    }
    if (a7_hr_applied_find($catalog, $positionName)) {
        a7_hr_applied_fail('This position already exists');
    }
    $catalog[] = ['name' => $positionName, 'color' => $color];
    a7_hr_applied_save_catalog($catalog);
}

if ($action === 'delete') {
    if ($positionName === '') {
        a7_hr_applied_fail('Select a position to delete');
    }
    $found = a7_hr_applied_find($catalog, $positionName);
    if (!$found) {
        a7_hr_applied_fail('Position not found');
    }
    $catalog = array_values(array_filter($catalog, static function (array $row) use ($positionName): bool {
        return a7_hr_applied_norm((string)$row['name']) !== a7_hr_applied_norm($positionName);
    }));
    a7_hr_applied_save_catalog($catalog);
    if (a7_hr_applied_norm($selected) === a7_hr_applied_norm($positionName)) {
        $positionName = '';
    } else {
        $positionName = $selected;
    }
}

if ($action === 'save' && $positionName !== '' && !a7_hr_applied_find($catalog, $positionName)) {
    a7_hr_applied_fail('Select a position from the list, or add a new one');
}

$item->set($field, $positionName);
$operation = $factory->getUpdateOperation($item);
if (method_exists($operation, 'disableAutomation')) {
    $operation->disableAutomation();
}
if (method_exists($operation, 'disableBizProc')) {
    $operation->disableBizProc();
}
$result = $operation->launch();
if (!$result->isSuccess()) {
    a7_hr_applied_fail(implode('; ', $result->getErrorMessages()), 500);
}

$selectedRow = a7_hr_applied_find($catalog, $positionName);
echo json_encode([
    'ok' => true,
    'selected' => $selectedRow['name'] ?? $positionName,
    'color' => $selectedRow['color'] ?? '',
    'options' => $catalog,
], JSON_UNESCAPED_UNICODE);
