<?php
/**
 * Create 3 TL departments under Sales Department (60) and assign teams.
 * Run on CRM host as bitrix: php create_tl_departments.php
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';

if (!\Bitrix\Main\Loader::includeModule('iblock')) {
    fwrite(STDERR, "iblock module missing\n");
    exit(1);
}

const DEPT_IBLOCK = 3;
const PARENT_SALES = 60; // Sales Department

$teams = [
    [
        'code' => 'a7_tl_hassan',
        'name' => 'Hassan Team (TL)',
        'head' => 2560,
        'members' => [2560, 2380, 2344, 2434, 2291, 2378, 2376, 2379, 2303],
    ],
    [
        'code' => 'a7_tl_hussnain',
        'name' => 'Hussnain Team (TL)',
        'head' => 2551,
        'members' => [2551, 2381, 2369, 2371, 2535, 2368, 2367, 2351, 2350],
    ],
    [
        'code' => 'a7_tl_jaweria',
        'name' => 'Jaweria Team (TL)',
        'head' => 2297,
        'members' => [2297, 2299, 2302, 2392, 2298, 2390],
    ],
];

function findSectionByCode(string $code): ?array
{
    $res = CIBlockSection::GetList(
        [],
        ['IBLOCK_ID' => DEPT_IBLOCK, 'CODE' => $code, 'CHECK_PERMISSIONS' => 'N'],
        false,
        ['ID', 'NAME', 'CODE', 'IBLOCK_SECTION_ID', 'UF_HEAD']
    );
    $row = $res->Fetch();
    return $row ?: null;
}

function ensureDepartment(array $team): int
{
    $existing = findSectionByCode($team['code']);
    $fields = [
        'IBLOCK_ID' => DEPT_IBLOCK,
        'IBLOCK_SECTION_ID' => PARENT_SALES,
        'NAME' => $team['name'],
        'CODE' => $team['code'],
        'ACTIVE' => 'Y',
        'UF_HEAD' => (int) $team['head'],
    ];

    $bs = new CIBlockSection();
    if ($existing) {
        $ok = $bs->Update((int) $existing['ID'], $fields);
        if (!$ok) {
            throw new RuntimeException('Update failed ' . $team['code'] . ': ' . $bs->LAST_ERROR);
        }
        echo "UPDATED dept id={$existing['ID']} {$team['name']} head={$team['head']}\n";
        return (int) $existing['ID'];
    }

    $id = (int) $bs->Add($fields);
    if ($id <= 0) {
        throw new RuntimeException('Add failed ' . $team['code'] . ': ' . $bs->LAST_ERROR);
    }
    echo "CREATED dept id=$id {$team['name']} head={$team['head']}\n";
    return $id;
}

function setUserDepartments(int $userId, array $deptIds): void
{
    $deptIds = array_values(array_unique(array_map('intval', $deptIds)));
    $user = new CUser();
    $ok = $user->Update($userId, ['UF_DEPARTMENT' => $deptIds]);
    if (!$ok) {
        throw new RuntimeException("user $userId update failed: " . $user->LAST_ERROR);
    }
}

// Verify parent exists
$parent = CIBlockSection::GetList(
    [],
    ['IBLOCK_ID' => DEPT_IBLOCK, 'ID' => PARENT_SALES, 'CHECK_PERMISSIONS' => 'N'],
    false,
    ['ID', 'NAME']
)->Fetch();
if (!$parent) {
    fwrite(STDERR, "Parent Sales Department id=" . PARENT_SALES . " not found\n");
    exit(1);
}
echo "Parent: {$parent['ID']} {$parent['NAME']}\n";

$created = [];
foreach ($teams as $team) {
    $deptId = ensureDepartment($team);
    $created[$team['code']] = [
        'id' => $deptId,
        'head' => $team['head'],
        'name' => $team['name'],
        'members' => $team['members'],
    ];
    foreach ($team['members'] as $uid) {
        // Keep only the new TL team dept as primary structure for these users
        // (cleaner supervise tree). Sales parent is inherited via section hierarchy.
        setUserDepartments((int) $uid, [$deptId]);
        echo "  assigned user=$uid -> dept=$deptId\n";
    }
}

echo "=== VERIFY ===\n";
foreach ($created as $code => $info) {
    $sec = findSectionByCode($code);
    echo json_encode([
        'code' => $code,
        'id' => $sec['ID'] ?? null,
        'name' => $sec['NAME'] ?? null,
        'parent' => $sec['IBLOCK_SECTION_ID'] ?? null,
        'UF_HEAD' => $sec['UF_HEAD'] ?? null,
        'members' => $info['members'],
    ], JSON_UNESCAPED_UNICODE) . "\n";
}

// Dump UF_DEPARTMENT for heads
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$heads = '2560,2551,2297';
$q = $m->query("SELECT VALUE_ID, UF_DEPARTMENT FROM b_uts_user WHERE VALUE_ID IN ($heads)");
while ($r = $q->fetch_assoc()) {
    echo "UF_DEPARTMENT user={$r['VALUE_ID']} " . $r['UF_DEPARTMENT'] . "\n";
}

echo "DONE\n";
echo "NOTE: CRM permission role must allow viewing department/subordinate records for TLs to see team leads in list.\n";
