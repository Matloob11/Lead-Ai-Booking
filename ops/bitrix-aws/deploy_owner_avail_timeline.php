<?php
/**
 * Install timeline-on-copy for Owner Data → Availability, patch robot 98, backfill.
 *
 * Run on Bitrix host: sudo php /tmp/deploy_owner_avail_timeline.php
 */
$doc = '/home/bitrix/www';
$libDst = $doc . '/bitrix/php_interface/include/a7_owner_avail_timeline_lib.php';
$actDir = $doc . '/local/activities/a7attachspatimeline';
$srcRoot = is_dir('/tmp/a7-owner-avail-timeline')
    ? '/tmp/a7-owner-avail-timeline'
    : __DIR__;

$libSrc = $srcRoot . '/a7_owner_avail_timeline_lib.php';
$actSrc = $srcRoot . '/a7attachspatimeline';

foreach ([$libSrc, $actSrc . '/a7attachspatimeline.php', $actSrc . '/.description.php'] as $need) {
    if (!is_readable($need)) {
        fwrite(STDERR, "missing $need\n");
        exit(1);
    }
}

@mkdir($doc . '/bitrix/php_interface/include', 0755, true);
@mkdir($actDir, 0755, true);
@mkdir($doc . '/local/activities', 0755, true);

if (!copy($libSrc, $libDst)) {
    fwrite(STDERR, "copy lib failed\n");
    exit(1);
}
foreach (['a7attachspatimeline.php', '.description.php', 'properties_dialog.php'] as $f) {
    $from = $actSrc . '/' . $f;
    if (!is_readable($from)) {
        continue;
    }
    if (!copy($from, $actDir . '/' . $f)) {
        fwrite(STDERR, "copy activity $f failed\n");
        exit(1);
    }
}
@chmod($libDst, 0644);
$copyNote = 'lib ' . filesize($libDst) . " activity_dir=$actDir";

$_SERVER['DOCUMENT_ROOT'] = $doc;
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_SECURITY_SESSION_VIRTUAL', true);
require $doc . '/bitrix/modules/main/include/prolog_before.php';

echo $copyNote . "\n";

\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('bizproc');

if (class_exists('CBPRuntime')) {
    try {
        CBPRuntime::getRuntime()->clearActivitiesCache();
    } catch (Throwable $e) {
        // older builds
    }
}
BXClearCache(true);
echo "activity cache cleared\n";

require_once $libDst;

/**
 * Patch automation template 98 (Create Availability):
 * - ItemTitle = source TITLE
 * - After Copy SPA, attach timeline + fix title
 */
function a7_patch_create_availability_template(mysqli $m): void
{
    $tplId = 98;
    $row = $m->query("SELECT ID, NAME, TEMPLATE FROM b_bp_workflow_template WHERE ID={$tplId}")->fetch_assoc();
    if (!$row) {
        throw new RuntimeException("template $tplId missing");
    }
    $raw = $row['TEMPLATE'];
    $bin = @gzuncompress($raw);
    if ($bin === false) {
        $bin = @gzdecode($raw);
    }
    if ($bin === false) {
        throw new RuntimeException('cannot gunzip template 98');
    }
    $data = @unserialize($bin);
    if (!is_array($data)) {
        throw new RuntimeException('cannot unserialize template 98');
    }

    $copyName = null;
    $already = false;
    $stack = [&$data];
    while ($stack) {
        $ref = &$stack[array_key_last($stack)];
        unset($stack[array_key_last($stack)]);
        if (!is_array($ref)) {
            continue;
        }
        if (($ref['Type'] ?? '') === 'CrmCopyDynamicActivity') {
            $copyName = (string)($ref['Name'] ?? '');
            if (!isset($ref['Properties']) || !is_array($ref['Properties'])) {
                $ref['Properties'] = [];
            }
            $ref['Properties']['ItemTitle'] = '{=Document:TITLE}';
        }
        if (($ref['Type'] ?? '') === 'A7AttachSpaTimelineActivity') {
            $already = true;
        }
        foreach ($ref as $k => &$v) {
            if (is_array($v)) {
                $stack[] = &$v;
            }
        }
        unset($v);
        unset($ref);
    }

    if ($copyName === null || $copyName === '') {
        throw new RuntimeException('CrmCopyDynamicActivity not found in template 98');
    }

    if (!$already) {
        $attach = [
            'Type' => 'A7AttachSpaTimelineActivity',
            'Name' => 'A7AttachSpaTimeline_' . substr(md5($copyName), 0, 8),
            'Properties' => [
                'Title' => 'A7 Attach Owner Data timeline',
                'TargetItemId' => '{=' . $copyName . ':ItemId}',
            ],
            'Children' => [],
        ];

        // Insert attach activity immediately after the Copy SPA node in its parent Children list.
        $inserted = a7_insert_after_named_child($data, $copyName, $attach);
        if (!$inserted) {
            throw new RuntimeException('could not insert attach activity after Copy SPA');
        }
        echo "inserted A7AttachSpaTimeline after $copyName\n";
    } else {
        echo "A7AttachSpaTimeline already present\n";
    }

    // Always refresh TargetItemId expression + ItemTitle even when attach already exists.
    a7_walk_fix_attach_target($data, $copyName);

    $serialized = serialize($data);
    $compressed = gzcompress($serialized, 9);
    if ($compressed === false) {
        throw new RuntimeException('gzcompress failed');
    }

    $backupPath = '/home/bitrix/www/bitrix/php_interface/a7_bp_template_98.bak.' . date('Ymd_His');
    file_put_contents($backupPath, $raw);
    echo "template backup $backupPath (" . strlen($raw) . " bytes)\n";

    $hex = bin2hex($compressed);
    $ok = $m->query("UPDATE b_bp_workflow_template SET TEMPLATE=UNHEX('{$hex}') WHERE ID={$tplId}");
    if (!$ok) {
        throw new RuntimeException('update failed: ' . $m->error);
    }

    $check = $m->query("SELECT LENGTH(TEMPLATE) L FROM b_bp_workflow_template WHERE ID={$tplId}")->fetch_assoc();
    echo "template 98 updated length=" . ($check['L'] ?? '?') . " ItemTitle=Document:TITLE\n";
}

function a7_insert_after_named_child(array &$node, string $copyName, array $attach): bool
{
    if (!is_array($node)) {
        return false;
    }
    foreach ($node as $key => &$child) {
        if ($key === 'Children' && is_array($child)) {
            $keys = array_keys($child);
            foreach ($keys as $i => $ck) {
                $c = $child[$ck];
                if (is_array($c) && (string)($c['Name'] ?? '') === $copyName) {
                    // Rebuild children with attach inserted after copy.
                    $new = [];
                    foreach ($child as $idx => $item) {
                        $new[] = $item;
                        if (is_array($item) && (string)($item['Name'] ?? '') === $copyName) {
                            $new[] = $attach;
                        }
                    }
                    $child = $new;
                    return true;
                }
            }
        }
        if (is_array($child) && a7_insert_after_named_child($child, $copyName, $attach)) {
            return true;
        }
    }
    unset($child);
    return false;
}

function a7_walk_fix_attach_target(array &$node, string $copyName): void
{
    if (($node['Type'] ?? '') === 'A7AttachSpaTimelineActivity') {
        $node['Properties']['TargetItemId'] = '{=' . $copyName . ':ItemId}';
        $node['Properties']['Title'] = 'A7 Attach Owner Data timeline';
    }
    if (($node['Type'] ?? '') === 'CrmCopyDynamicActivity') {
        $node['Properties']['ItemTitle'] = '{=Document:TITLE}';
    }
    foreach ($node as &$v) {
        if (is_array($v)) {
            a7_walk_fix_attach_target($v, $copyName);
        }
    }
    unset($v);
}

$s = include $doc . '/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
if ($m->connect_error) {
    fwrite(STDERR, "db fail\n");
    exit(1);
}

try {
    a7_patch_create_availability_template($m);
} catch (Throwable $e) {
    fwrite(STDERR, 'patch failed: ' . $e->getMessage() . "\n");
    exit(1);
}

/**
 * Backfill Availability cards titled "Owner Data #N".
 */
echo "\n=== backfill ===\n";
$q = $m->query(
    "SELECT ID, TITLE FROM b_crm_dynamic_items_1042
     WHERE CATEGORY_ID=14 AND TITLE REGEXP '^Owner Data #[0-9]+$'
     ORDER BY ID ASC"
);
$total = 0;
$ok = 0;
$skip = 0;
$fail = 0;
$samples = [];
while ($row = $q->fetch_assoc()) {
    $total++;
    $targetId = (int)$row['ID'];
    $sourceId = a7_owner_avail_parse_source_from_title((string)$row['TITLE']);
    if ($sourceId <= 0 || $sourceId === $targetId) {
        $skip++;
        continue;
    }
    $src = $m->query(
        "SELECT ID, TITLE, CATEGORY_ID FROM b_crm_dynamic_items_1042 WHERE ID={$sourceId}"
    )->fetch_assoc();
    if (!$src) {
        $skip++;
        continue;
    }

    $before = a7_owner_avail_timeline_bind_count($targetId);
    $srcBinds = a7_owner_avail_timeline_bind_count($sourceId);
    // Already has at least as many binds as source (minus maybe the COPIED log) — still fix title.
    $result = a7_owner_avail_after_copy($sourceId, $targetId);
    $after = (int)($result['timeline']['after'] ?? a7_owner_avail_timeline_bind_count($targetId));
    if (!empty($result['timeline']['ok'])) {
        $ok++;
        if (count($samples) < 8) {
            $samples[] = "#{$targetId} <- #{$sourceId} binds {$before}->{$after} title=" .
                ($result['title']['title'] ?? '');
        }
    } else {
        $fail++;
        echo "FAIL #{$targetId}: " . ($result['timeline']['error'] ?? 'unknown') . "\n";
    }
}

echo "backfill total=$total ok=$ok skip=$skip fail=$fail\n";
foreach ($samples as $line) {
    echo "  $line\n";
}

// Prove on known pair if still present
$proveSrc = 92578;
$proveTgt = 111565;
$exists = $m->query("SELECT ID, TITLE FROM b_crm_dynamic_items_1042 WHERE ID IN ($proveSrc,$proveTgt)");
$got = [];
while ($r = $exists->fetch_assoc()) {
    $got[(int)$r['ID']] = $r['TITLE'];
}
if (isset($got[$proveSrc], $got[$proveTgt])) {
    echo "\nprove #{$proveTgt} title={$got[$proveTgt]} binds=" . a7_owner_avail_timeline_bind_count($proveTgt) .
        " source_binds=" . a7_owner_avail_timeline_bind_count($proveSrc) . "\n";
}

echo "DONE\n";
