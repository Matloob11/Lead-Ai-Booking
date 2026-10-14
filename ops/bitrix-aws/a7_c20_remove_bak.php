<?php
/** C20: remove the non-.php backup. CLI only. Uses sudo when bitrix cannot unlink. */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
$path = '/home/bitrix/www/local/php_interface/include/a7_listing_new_access.php.bak-20260922-114148';
if (!is_file($path)) {
    echo "missing\n";
    exit(0);
}
if (@unlink($path)) {
    echo "removed\n";
    exit(0);
}
$out = [];
$code = 0;
exec('sudo -n rm -f ' . escapeshellarg($path) . ' 2>&1', $out, $code);
echo implode("\n", $out), "\n";
echo is_file($path) ? "still_there code={$code}\n" : "removed_via_sudo\n";
exit(is_file($path) ? 1 : 0);
