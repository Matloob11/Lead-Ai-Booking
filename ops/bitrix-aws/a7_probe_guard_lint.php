<?php
/**
 * php -l of the staged guard files (*.php.new under php_interface/include and tools) before they go live.
 * Read-only. Run: ops/bitrix.sh run a7_probe_guard_lint.php
 */
$files = [
    '/home/bitrix/www/bitrix/php_interface/include/a7_lead_guard.php.new',
    '/home/bitrix/www/bitrix/php_interface/include/a7_lead_guard_perms.php.new',
    '/home/bitrix/www/bitrix/tools/a7_lead_guard_api.php.new',
];
$bad = 0;
foreach ($files as $f) {
    if (!is_file($f)) {
        echo "MISSING $f\n";
        $bad++;
        continue;
    }
    $out = [];
    $code = 0;
    exec('php -l ' . escapeshellarg($f) . ' 2>&1', $out, $code);
    echo ($code === 0 ? 'OK   ' : 'FAIL ') . basename($f) . ': ' . trim(implode(' ', $out)) . ' (' . md5_file($f) . ")\n";
    $bad += $code === 0 ? 0 : 1;
}
echo $bad === 0 ? "LINT_OK\n" : "LINT_FAILED\n";
