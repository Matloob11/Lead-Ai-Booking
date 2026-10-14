<?php
/**
 * Shared Leads preset "IC shops — ready for Lead AI" and the three shop columns
 * on every administrator's saved Leads grid. Idempotent.
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

const A7_C15_PRESET = 'a7_ic_shops_ready';
const A7_C15_GRID = 'CRM_LEAD_LIST_V12';
const A7_C15_COLUMNS = [
    'UF_CRM_A7_BOT_STATUS',
    'UF_CRM_A7_SHOP_TYPE',
    'UF_CRM_A7_WA_OPT_OUT',
];

function a7_c15_preset(): array
{
    return [
        'name' => 'IC shops — ready for Lead AI',
        'for_all' => '1',
        'sort' => '50',
        'fields' => [
            'UF_CRM_1770537051525' => 'International City',
            'UF_CRM_1731838348693' => ['384'],
            'UF_CRM_1731838348693_label' => ['Shop'],
            'UF_CRM_A7_BOT_STATUS' => ['', '2475', '2476'],
            'UF_CRM_A7_BOT_STATUS_label' => ['Not filled', 'New', 'Qualifying'],
            'UF_CRM_A7_WA_OPT_OUT' => ['', '2483'],
            'UF_CRM_A7_WA_OPT_OUT_label' => ['Not filled', 'No'],
            'HAS_PHONE' => 'Y',
            'HAS_PHONE_label' => 'Yes',
        ],
        'filter_rows' => 'UF_CRM_1770537051525,UF_CRM_1731838348693,UF_CRM_A7_BOT_STATUS,UF_CRM_A7_WA_OPT_OUT,HAS_PHONE',
    ];
}

function a7_c15_add_preset(array $options): array
{
    if (!isset($options['filters']) || !is_array($options['filters'])) {
        $options['filters'] = [];
    }
    $options['filters'][A7_C15_PRESET] = a7_c15_preset();
    if (!isset($options['default_presets']) || !is_array($options['default_presets'])) {
        $options['default_presets'] = [];
    }
    $options['use_pin_preset'] = $options['use_pin_preset'] ?? true;
    return $options;
}

function a7_c15_add_columns(&$node): int
{
    $n = 0;
    if (!is_array($node)) {
        return 0;
    }
    foreach ($node as $key => &$value) {
        if ($key === 'columns' && is_string($value)) {
            foreach (A7_C15_COLUMNS as $column) {
                if (!preg_match('/(^|,)' . preg_quote($column, '/') . '(,|$)/', $value)) {
                    $value = $value === '' ? $column : $value . ',' . $column;
                    $n++;
                }
            }
        } elseif (is_array($value)) {
            $n += a7_c15_add_columns($value);
        }
    }
    return $n;
}

$common = \CUserOptions::GetOption('main.ui.filter.common', A7_C15_GRID, [], 0);
if (!is_array($common)) {
    $common = [];
}
$common = a7_c15_add_preset($common);
\CUserOptions::SetOption('main.ui.filter.common', A7_C15_GRID, $common, true, 0);
echo "common preset saved\n";

$admins = [];
$res = \CUser::GetList('ID', 'ASC', ['GROUPS_ID' => [1], 'ACTIVE' => 'Y']);
while ($row = $res->Fetch()) {
    $admins[] = (int)$row['ID'];
}
$filters = 0;
$grids = 0;
$columns = 0;
foreach ($admins as $userId) {
    $personal = \CUserOptions::GetOption('main.ui.filter', A7_C15_GRID, false, $userId);
    if (is_array($personal)) {
        $personal = a7_c15_add_preset($personal);
        \CUserOptions::SetOption('main.ui.filter', A7_C15_GRID, $personal, false, $userId);
        $filters++;
    }
    $grid = \CUserOptions::GetOption('main.interface.grid', A7_C15_GRID, false, $userId);
    if (is_array($grid)) {
        $added = a7_c15_add_columns($grid);
        \CUserOptions::SetOption('main.interface.grid', A7_C15_GRID, $grid, false, $userId);
        $grids++;
        $columns += $added;
    }
}
echo 'admins=', count($admins), ' filters=', $filters, ' grids=', $grids, ' columns_added=', $columns, "\n";
