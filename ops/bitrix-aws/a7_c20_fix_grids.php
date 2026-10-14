<?php
/**
 * C20: restore Leads grid columns for admins whose list was collapsed to the
 * three shop columns. Copies a healthy admin's column list (user 1), appends
 * the three shop fields. CLI only. Does not touch user 2311 (Q23 default).
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

const A7_C20_GRID = 'CRM_LEAD_LIST_V12';
const A7_C20_SHOP = [
    'UF_CRM_A7_BOT_STATUS',
    'UF_CRM_A7_SHOP_TYPE',
    'UF_CRM_A7_WA_OPT_OUT',
];
const A7_C20_USERS = [26, 2196, 2633, 2637];
const A7_C20_TEMPLATE_USER = 1;

function a7_c20_find_columns(array $node): string
{
    if (isset($node['columns']) && is_string($node['columns']) && $node['columns'] !== '') {
        return $node['columns'];
    }
    if (isset($node['views']) && is_array($node['views'])) {
        foreach ($node['views'] as $view) {
            if (!is_array($view)) {
                continue;
            }
            $found = a7_c20_find_columns($view);
            if ($found !== '') {
                return $found;
            }
        }
    }
    foreach ($node as $value) {
        if (is_array($value)) {
            $found = a7_c20_find_columns($value);
            if ($found !== '') {
                return $found;
            }
        }
    }
    return '';
}

function a7_c20_set_columns(array &$node, string $columns): int
{
    $n = 0;
    foreach ($node as $key => &$value) {
        if ($key === 'columns' && is_string($value)) {
            $value = $columns;
            $n++;
        } elseif (is_array($value)) {
            $n += a7_c20_set_columns($value, $columns);
        }
    }
    return $n;
}

function a7_c20_with_shop(string $columns): string
{
    $parts = array_values(array_filter(array_map('trim', explode(',', $columns)), static fn ($p) => $p !== ''));
    foreach (A7_C20_SHOP as $col) {
        if (!in_array($col, $parts, true)) {
            $parts[] = $col;
        }
    }
    return implode(',', $parts);
}

$template = \CUserOptions::GetOption('main.interface.grid', A7_C20_GRID, false, A7_C20_TEMPLATE_USER);
if (!is_array($template)) {
    fwrite(STDERR, "no template grid for user " . A7_C20_TEMPLATE_USER . "\n");
    exit(1);
}
$base = a7_c20_find_columns($template);
if ($base === '') {
    fwrite(STDERR, "template user has empty columns\n");
    exit(1);
}
$defaults = a7_c20_with_shop($base);
echo "template_user=", A7_C20_TEMPLATE_USER, " base=", $base, "\n";
echo "default_columns={$defaults}\n";

foreach (A7_C20_USERS as $userId) {
    $grid = \CUserOptions::GetOption('main.interface.grid', A7_C20_GRID, false, $userId);
    $before = is_array($grid) ? a7_c20_find_columns($grid) : '';
    echo "user={$userId} before_cols=", ($before === '' ? '(none)' : $before), "\n";
    if (!is_array($grid)) {
        $grid = ['views' => ['default' => ['name' => 'default', 'columns' => $defaults]]];
    } else {
        $n = a7_c20_set_columns($grid, $defaults);
        if ($n === 0) {
            if (!isset($grid['views']) || !is_array($grid['views'])) {
                $grid['views'] = [];
            }
            if (!isset($grid['views']['default']) || !is_array($grid['views']['default'])) {
                $grid['views']['default'] = ['name' => 'default'];
            }
            $grid['views']['default']['columns'] = $defaults;
        }
    }
    \CUserOptions::SetOption('main.interface.grid', A7_C20_GRID, $grid, false, $userId);
    $after = \CUserOptions::GetOption('main.interface.grid', A7_C20_GRID, false, $userId);
    $afterCols = is_array($after) ? a7_c20_find_columns($after) : '';
    echo "user={$userId} after_cols={$afterCols}\n";
}
echo "ok\n";
