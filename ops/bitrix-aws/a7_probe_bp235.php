<?php
/**
 * Read-only: what Lead Automation (BP 235) does on an edit.
 * Run: ops/bitrix.sh run a7_probe_bp235.php
 */
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

\Bitrix\Main\Loader::includeModule('bizproc');
\Bitrix\Main\Loader::includeModule('crm');

$row = \Bitrix\Main\Application::getConnection()->query(
    "SELECT ID, NAME, AUTO_EXECUTE, ACTIVE, TEMPLATE FROM b_bp_workflow_template WHERE ID=235"
)->fetch();
if (!is_array($row)) {
    echo "missing\n";
    exit(1);
}
echo "name={$row['NAME']} auto={$row['AUTO_EXECUTE']} active={$row['ACTIVE']}\n";
$raw = (string)$row['TEMPLATE'];
echo 'prefix=' . bin2hex(substr($raw, 0, 12)) . ' len=' . strlen($raw) . "\n";
if (strncmp($raw, "\x78\xda", 2) === 0 || strncmp($raw, "\x78\x9c", 2) === 0) {
    $decoded = @gzuncompress($raw);
    if (is_string($decoded)) {
        $raw = $decoded;
        echo "gzuncompress len=" . strlen($raw) . "\n";
    }
}
$tpl = @unserialize($raw);
if (!is_array($tpl)) {
    echo "template did not unserialize\n";
    exit(1);
}

function walk($node, int $depth = 0): void
{
    if (!is_array($node)) {
        return;
    }
    $type = (string)($node['Type'] ?? '');
    $name = (string)($node['Name'] ?? '');
    $props = is_array($node['Properties'] ?? null) ? $node['Properties'] : [];
    $title = (string)($props['Title'] ?? $props['SetStatus'] ?? '');
    if ($type !== '') {
        echo str_repeat('  ', $depth) . $type;
        if ($name !== '') {
            echo " {$name}";
        }
        if ($title !== '') {
            echo " | {$title}";
        }
        echo "\n";
        foreach (['fieldcondition', 'Fieldcondition', 'StatusId', 'TargetStatus', 'SetStatus', 'DocumentStatus'] as $key) {
            if (isset($props[$key])) {
                echo str_repeat('  ', $depth) . "  {$key}=" . json_encode($props[$key], JSON_UNESCAPED_UNICODE) . "\n";
            }
        }
        if (isset($props['Conditions'])) {
            echo str_repeat('  ', $depth) . '  Conditions=' . json_encode($props['Conditions'], JSON_UNESCAPED_UNICODE) . "\n";
        }
        if ($type === 'SetFieldActivity' && isset($props['FieldValue'])) {
            echo str_repeat('  ', $depth) . '  FieldValue=' . json_encode($props['FieldValue'], JSON_UNESCAPED_UNICODE) . "\n";
        }
        if ($type === 'CrmCreateToDoActivity') {
            $todo = [];
            foreach (['Subject', 'Description', 'Deadline', 'Responsible', 'AutoComplete'] as $key) {
                if (isset($props[$key])) {
                    $todo[$key] = $props[$key];
                }
            }
            echo str_repeat('  ', $depth) . '  todo=' . json_encode($todo, JSON_UNESCAPED_UNICODE) . "\n";
        }
    }
    foreach ($node['Children'] ?? [] as $child) {
        walk($child, $depth + 1);
    }
}

walk($tpl[0] ?? $tpl);
echo "DONE\n";
