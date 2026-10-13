<?php
/**
 * Wire a7_leadai_bot_status.php into bitrix/php_interface/init.php (idempotent).
 * Run once on the box. Does not print secrets.
 */
$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$module = '/home/bitrix/www/bitrix/php_interface/include/a7_leadai_bot_status.php';
if (!is_file($module)) {
    fwrite(STDERR, "missing module\n");
    exit(1);
}
if (!is_file($init)) {
    fwrite(STDERR, "missing init.php\n");
    exit(1);
}

$marker = 'A7_LEADAI_BOT_STATUS';
$block = <<<'PHP'
// A7_LEADAI_BOT_STATUS: a person's Bot Status / WhatsApp Opt-out change notifies Lead AI.
if (is_file(__DIR__ . '/include/a7_leadai_bot_status.php')) {
	require_once __DIR__ . '/include/a7_leadai_bot_status.php';
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
    fwrite(STDERR, "cannot read init.php\n");
    exit(1);
}
if (str_contains($src, $marker) && str_contains($src, 'a7_leadai_bot_status.php')) {
    echo "init already wired\n";
} else {
    $backup = '/tmp/a7_init_bak_leadai_bot_status_' . date('Ymd_His') . '.php';
    if (!copy($init, $backup)) {
        fwrite(STDERR, "backup failed\n");
        exit(1);
    }
    $patched = rtrim($src) . "\n" . $block . "\n";
    $tmp = $init . '.tmp_botstatus';
    file_put_contents($tmp, $patched);
    exec('php -l ' . escapeshellarg($tmp) . ' 2>&1', $out, $code);
    if ($code !== 0) {
        @unlink($tmp);
        fwrite(STDERR, "lint failed\n" . implode("\n", $out) . "\n");
        exit(1);
    }
    if (!rename($tmp, $init)) {
        @unlink($tmp);
        fwrite(STDERR, "init.php replace failed\n");
        exit(1);
    }
    @chmod($init, 0644);
    echo "init wired\n";
}
exec('php -l ' . escapeshellarg($module) . ' 2>&1', $lint, $lc);
echo implode("\n", $lint), "\n";
exit($lc === 0 ? 0 : 1);
