<?php
/**
 * C20: print one-off / remove names that still need stubbing (not live, not stub).
 * CLI only. No writes.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
$dir = '/home/bitrix/www/local/php_interface/include';
$stubMd5 = 'c99f9ec7c38fc00d82f48e3294d18cdd';
$keep = [
    'a7_hr_applied_badge.php' => 1,
    'a7_hr_cv_route.php' => 1,
    'a7_hr_cv_stage.php' => 1,
    'a7_hr_cv_upload.php' => 1,
    'a7_hr_field_labels.php' => 1,
    'a7_hr_stage_remove.php' => 1,
    'a7_listing_boot.php' => 1,
    'a7_listing_new_access.php' => 1,
];
foreach (scandir($dir) ?: [] as $name) {
    if ($name === '.' || $name === '..' || !is_file("$dir/$name")) {
        continue;
    }
    if (isset($keep[$name])) {
        continue;
    }
    $md5 = md5_file("$dir/$name");
    if ($md5 === $stubMd5) {
        continue;
    }
    echo $name, "\n";
}
