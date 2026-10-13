<?php
/**
 * Publish Matloob Auto Timeman (JS + tool + lib + agent + init + optional cron).
 * Idempotent. Hard-gated to config user_id (2311).
 *
 * On AWS as bitrix:
 *   sudo -u bitrix php /tmp/deploy_auto_timeman.php
 * Then ensure minute cron (agents alone need page hits):
 *   * * * * * /usr/bin/php -f /home/bitrix/www/bitrix/php_interface/a7_auto_timeman_cron.php >/dev/null 2>&1
 */
$doc = '/home/bitrix/www';
$init = $doc . '/bitrix/php_interface/init.php';

$map = [
    'a7_auto_timeman.config.php' => $doc . '/bitrix/php_interface/a7_auto_timeman.config.php',
    'a7_auto_timeman_lib.php' => $doc . '/bitrix/php_interface/a7_auto_timeman_lib.php',
    'a7_auto_timeman_agent.php' => $doc . '/bitrix/php_interface/a7_auto_timeman_agent.php',
    'a7_auto_timeman_cron.php' => $doc . '/bitrix/php_interface/a7_auto_timeman_cron.php',
    'a7_auto_timeman.php' => $doc . '/bitrix/tools/a7_auto_timeman.php',
    'a7_auto_timeman.js' => $doc . '/bitrix/js/a7_auto_timeman.js',
];

$copied = [];
foreach ($map as $name => $dst) {
    $src = is_readable('/tmp/' . $name) ? '/tmp/' . $name : __DIR__ . '/' . $name;
    if (!is_readable($src)) {
        fwrite(STDERR, "missing $src\n");
        exit(1);
    }
    if (!copy($src, $dst)) {
        fwrite(STDERR, "copy failed $name → $dst\n");
        exit(1);
    }
    @chmod($dst, $name === 'a7_auto_timeman.config.php' ? 0640 : 0644);
    $copied[] = $name . ' ' . filesize($dst);
}
// Do not echo before Bitrix bootstrap — it breaks session/agent register.
file_put_contents('/tmp/a7_auto_tm_deploy.log', implode("\n", $copied) . "\n", FILE_APPEND);

$marker = 'A7_AUTO_TIMEMAN';
$block = <<<'PHP'
// A7_AUTO_TIMEMAN: Matloob (2311) profile Auto button + server clock-in/out agent.
require_once $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_auto_timeman_agent.php';
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        $cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_auto_timeman.config.php';
        $cfg = is_readable($cfgPath) ? include $cfgPath : [];
        $allowed = (int)(is_array($cfg) ? ($cfg['user_id'] ?? 2311) : 2311);
        if ((int)$USER->GetID() !== $allowed) {
            return;
        }
        if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
            return;
        }
        $scriptPath = '/bitrix/js/a7_auto_timeman.js';
        $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
        $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
        $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);
    });
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
    fwrite(STDERR, "cannot read init.php\n");
    exit(1);
}

$backup = $init . '.bak.auto_tm_' . date('Ymd_His');
if (!copy($init, $backup)) {
    fwrite(STDERR, "init backup failed\n");
    exit(1);
}

$start = strpos($src, '// A7_AUTO_TIMEMAN');
if ($start === false) {
    $start = strpos($src, $marker);
}
if ($start !== false) {
    // Replace from marker through the closing brace of the AddEventHandler if-block.
    $ifPos = strpos($src, "if (function_exists('AddEventHandler'))", $start);
    $brace = $ifPos === false ? false : strpos($src, '{', $ifPos);
    if ($brace === false) {
        fwrite(STDERR, "init marker found but block not parsed\n");
        exit(1);
    }
    $depth = 0;
    $end = $brace;
    $len = strlen($src);
    for ($i = $brace; $i < $len; $i++) {
        $ch = $src[$i];
        if ($ch === '{') {
            $depth++;
        } elseif ($ch === '}') {
            $depth--;
            if ($depth === 0) {
                $end = $i + 1;
                break;
            }
        }
    }
    $src = substr($src, 0, $start) . $block . substr($src, $end);
    echo "init block replaced backup=$backup\n";
} else {
    $src = rtrim($src) . "\n" . $block . "\n";
    echo "init patched backup=$backup\n";
}
if (file_put_contents($init, $src) === false) {
    fwrite(STDERR, "write init failed\n");
    exit(1);
}

$_SERVER['DOCUMENT_ROOT'] = $doc;
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require_once $doc . '/bitrix/modules/main/include/prolog_before.php';
require_once $doc . '/bitrix/php_interface/a7_auto_timeman_agent.php';

if (class_exists('CAgent')) {
    CAgent::RemoveAgent('A7AutoTimemanAgent::run();', '');
    $added = CAgent::AddAgent(
        'A7AutoTimemanAgent::run();',
        '',
        'N',
        60,
        '',
        'Y',
        ConvertTimeStamp(time() + 60, 'FULL'),
        30,
        false,
        true
    );
    echo $added ? "agent registered interval=60s\n" : "agent register failed (may already exist)\n";
} else {
    echo "CAgent missing — register manually\n";
}

foreach ([
    $doc . '/bitrix/tools/a7_auto_timeman.php',
    $doc . '/bitrix/php_interface/a7_auto_timeman_lib.php',
    $doc . '/bitrix/php_interface/a7_auto_timeman_agent.php',
    $doc . '/bitrix/php_interface/a7_auto_timeman_cron.php',
    $doc . '/bitrix/php_interface/a7_auto_timeman.config.php',
    $init,
] as $check) {
    passthru('php -l ' . escapeshellarg($check), $code);
    if ($code !== 0) {
        exit(1);
    }
}

echo "js_http=";
passthru('curl -sI https://crm.a7grouprealestatedxb.com/bitrix/js/a7_auto_timeman.js | head -n 1');
echo "DONE — add minute cron for a7_auto_timeman_cron.php if not already present\n";
exit(0);
