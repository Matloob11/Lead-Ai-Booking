<?php
/**
 * Publish team bulk assign (JS + CSS + PHP tool + config + jobs + cron + init.php block).
 *
 *   sudo -u bitrix php deploy_team_assign.php --src=/tmp/a7ta_XXXX [--force]
 *
 * --src is required: the six sources are read from that directory only. Fixed /tmp names
 * are not used, because old copies left there were silently deployed in their place.
 *
 * Refuses to overwrite a live file that changed since the last deploy through this script
 * (md5 manifest in /home/bitrix). On 2026-10-01 the live JS and PHP were edited in place,
 * never came back to the repo, and broke FOR ALL on Leads; a deploy from the repo would
 * have silently undone them instead. Pull the live file, merge, then rerun with --force.
 * With no manifest yet, it refuses unless --force, and prints the live md5s to compare.
 *
 * Order: everything is linted and checked writable first; live files are backed up;
 * server-side files are copied before the CSS and JS, so the browser never gets new JS
 * against an old tool; a failed copy restores what was already replaced.
 */
$doc = '/home/bitrix/www';
$init = $doc . '/bitrix/php_interface/init.php';
$manifestPath = '/home/bitrix/.a7_team_assign.deployed.json';
$backupRoot = '/home/bitrix/a7_team_assign_backups';

$args = array_slice($argv ?? [], 1);
$force = in_array('--force', $args, true);
$srcDir = '';
foreach ($args as $arg) {
    if (strpos($arg, '--src=') === 0) {
        $srcDir = rtrim(substr($arg, 6), '/');
    }
}

function fail(string $message, int $code = 1): void
{
    fwrite(STDERR, $message . "\n");
    exit($code);
}

$docOwner = fileowner($doc . '/bitrix');
if (function_exists('posix_geteuid') && posix_geteuid() !== $docOwner) {
    fail('Run as the docroot owner: sudo -u bitrix php ' . ($argv[0] ?? 'deploy_team_assign.php') . ' --src=DIR');
}
if ($srcDir === '' || !is_dir($srcDir)) {
    fail('Pass the directory holding the uploaded sources: --src=DIR');
}

// Server-side first, browser-side last.
$pairs = [
    $srcDir . '/a7_team_assign.config.php' => $doc . '/bitrix/php_interface/a7_team_assign.config.php',
    $srcDir . '/a7_team_assign_jobs.php' => $doc . '/bitrix/php_interface/a7_team_assign_jobs.php',
    $srcDir . '/a7_team_assign_cron.php' => $doc . '/bitrix/php_interface/a7_team_assign_cron.php',
    $srcDir . '/a7_team_assign.php' => $doc . '/bitrix/tools/a7_team_assign.php',
    $srcDir . '/a7_team_assign.css' => $doc . '/bitrix/css/a7_team_assign.css',
    $srcDir . '/a7_team_assign.js' => $doc . '/bitrix/js/a7_team_assign.js',
];

// 1) Preflight — nothing on the site changes until all of this passes.
foreach ($pairs as $src => $dst) {
    if (!is_readable($src)) {
        fail("missing source $src");
    }
    echo 'source ' . basename($src) . ' ' . filesize($src) . ' ' . md5_file($src) . "\n";
    if (substr($src, -4) === '.php') {
        exec('php -l ' . escapeshellarg($src) . ' 2>&1', $out, $code);
        if ($code !== 0) {
            fail("lint failed: $src\n" . implode("\n", $out));
        }
    }
    if (is_file($dst) ? !is_writable($dst) : !is_writable(dirname($dst))) {
        fail("cannot write $dst");
    }
}
if (!is_writable($init) || !is_writable(dirname($init))) {
    fail("cannot write $init");
}

$manifest = null;
if (is_file($manifestPath)) {
    $manifest = json_decode((string)file_get_contents($manifestPath), true);
    if (!is_array($manifest)) {
        fail("manifest $manifestPath is unreadable — inspect it, then rerun with --force");
    }
}
$drift = [];
foreach ($pairs as $dst) {
    if (!is_file($dst)) {
        continue;
    }
    $live = md5_file($dst);
    if ($manifest === null) {
        $drift[] = $dst . ' live ' . $live . ' (no manifest yet)';
    } elseif (isset($manifest[$dst]) && $live !== $manifest[$dst]) {
        $drift[] = $dst . ' live ' . $live . ', last deployed ' . $manifest[$dst];
    }
}
if ($drift && !$force) {
    fail("REFUSED — live files not known to match the last deploy:\n  " . implode("\n  ", $drift)
        . "\nCompare with the repo; once the live edits are merged (or known disposable), rerun with --force.", 2);
}

// 2) Backup.
$backupDir = $backupRoot . '/' . date('Ymd_His');
if (!is_dir($backupDir) && !mkdir($backupDir, 0750, true)) {
    fail("cannot create $backupDir");
}
foreach ($pairs as $dst) {
    if (is_file($dst) && !copy($dst, $backupDir . '/' . basename($dst))) {
        fail("backup failed: $dst -> $backupDir");
    }
}
echo "backup=$backupDir\n";

// 3) Copy, recording each file in the manifest as it lands; restore on failure.
$deployed = is_array($manifest) ? $manifest : [];
$writeManifest = static function (array $data) use ($manifestPath): bool {
    $tmp = $manifestPath . '.tmp';
    return file_put_contents($tmp, json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)) !== false
        && rename($tmp, $manifestPath);
};
$done = [];
foreach ($pairs as $src => $dst) {
    if (!copy($src, $dst)) {
        foreach ($done as $restored) {
            $saved = $backupDir . '/' . basename($restored);
            if (is_file($saved)) {
                copy($saved, $restored);
                $deployed[$restored] = md5_file($restored);
            }
        }
        $writeManifest($deployed);
        fail("copy failed: $dst — restored " . count($done) . ' file(s) from ' . $backupDir);
    }
    @chmod($dst, 0644);
    $done[] = $dst;
    $deployed[$dst] = md5_file($dst);
    if (!$writeManifest($deployed)) {
        fail("could not write $manifestPath after copying $dst");
    }
    echo 'deployed ' . basename($dst) . ' ' . filesize($dst) . ' ' . $deployed[$dst] . "\n";
}

// The old FOR ALL wrote its last filter here, inside the public /upload tree.
@unlink($doc . '/upload/a7_team_assign/last_resolve_debug.json');

// 4) init.php hook — only rewritten when the block actually differs, and linted before it replaces anything.
$marker = 'A7_TEAM_ASSIGN';
$block = <<<'PHP'
// A7_TEAM_ASSIGN: bulk assign to Pakistan TL teams on CRM lists.
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        $onLead = strpos($uri, '/crm/lead/') === 0;
        $onOwner = strpos($uri, '/crm/type/1042/') !== false;
        $onRenewal = (bool)preg_match('#/crm/deal/(?:kanban/|list/)?category/9(?:/|\?|$)#', $uri);
        if (!$onLead && !$onOwner && !$onRenewal) {
            return;
        }
        if (
            preg_match('#/crm/lead/details/#', $uri)
            || preg_match('#/crm/type/1042/details/#', $uri)
            || preg_match('#/crm/deal/details/#', $uri)
        ) {
            return;
        }
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
            return;
        }
        $cssPath = '/bitrix/css/a7_team_assign.css';
        $jsPath = '/bitrix/js/a7_team_assign.js';
        $cssFull = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $cssPath;
        $jsFull = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $jsPath;
        $cssV = is_readable($cssFull) ? (string)@filemtime($cssFull) : (string)time();
        $jsV = is_readable($jsFull) ? (string)@filemtime($jsFull) : (string)time();
        if (method_exists($APPLICATION, 'SetAdditionalCSS')) {
            $APPLICATION->SetAdditionalCSS($cssPath . '?v=' . $cssV);
        } else {
            $APPLICATION->AddHeadString(
                '<link rel="stylesheet" href="' . htmlspecialcharsbx($cssPath . '?v=' . $cssV) . '">',
                true
            );
        }
        $APPLICATION->AddHeadScript($jsPath . '?v=' . $jsV);
    });
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
    fail('cannot read init.php');
}
$start = strpos($src, '// A7_TEAM_ASSIGN');
if ($start === false) {
    $start = strpos($src, $marker);
}
$current = null;
$end = null;
if ($start !== false) {
    $ifPos = strpos($src, "if (function_exists('AddEventHandler'))", $start);
    $brace = $ifPos === false ? false : strpos($src, '{', $ifPos);
    if ($brace === false) {
        fail('init marker found but block not parsed');
    }
    $depth = 0;
    $len = strlen($src);
    for ($i = $brace; $i < $len; $i++) {
        if ($src[$i] === '{') {
            $depth++;
        } elseif ($src[$i] === '}') {
            $depth--;
            if ($depth === 0) {
                $end = $i + 1;
                break;
            }
        }
    }
    if ($end === null) {
        fail('init block has no closing brace');
    }
    $current = substr($src, $start, $end - $start);
}
if ($current === $block) {
    echo "init block unchanged\n";
} else {
    $patched = $current === null ? rtrim($src) . "\n" . $block . "\n" : substr($src, 0, $start) . $block . substr($src, $end);
    $tmp = $init . '.tmp_team_assign';
    if (file_put_contents($tmp, $patched) === false) {
        fail('write init temp failed');
    }
    exec('php -l ' . escapeshellarg($tmp) . ' 2>&1', $out, $code);
    if ($code !== 0) {
        @unlink($tmp);
        fail("patched init.php does not lint — left untouched:\n" . implode("\n", $out));
    }
    if (!copy($init, $backupDir . '/init.php') || !rename($tmp, $init)) {
        fail('init.php replace failed');
    }
    echo "init block " . ($current === null ? 'added' : 'replaced') . " (old init in $backupDir)\n";
}

// 5) Prove what the site now serves: same bytes as deployed, and the tool answers.
$ok = true;
foreach (['/bitrix/js/a7_team_assign.js', '/bitrix/css/a7_team_assign.css'] as $path) {
    $body = (string)shell_exec('curl -s ' . escapeshellarg('https://crm.a7grouprealestatedxb.com' . $path . '?check=' . time()));
    $want = $deployed[$doc . $path] ?? '';
    $same = $want !== '' && md5($body) === $want;
    $ok = $ok && $same;
    echo 'served ' . $path . ' ' . md5($body) . ($same ? ' == deployed' : ' != deployed ' . $want) . "\n";
}
$tool = (string)shell_exec('curl -s -w "\n%{http_code}" https://crm.a7grouprealestatedxb.com/bitrix/tools/a7_team_assign.php');
$toolOk = (bool)preg_match('/"Not logged in".*\n401$/s', $tool);
$ok = $ok && $toolOk;
echo 'tool anonymous ' . ($toolOk ? '401 Not logged in (loads without fatals)' : 'UNEXPECTED: ' . substr(str_replace("\n", ' ', $tool), 0, 200)) . "\n";

exit($ok ? 0 : 1);
