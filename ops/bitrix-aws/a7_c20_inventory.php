<?php
/** C20 final inventory: name, size, md5, kind. CLI only. */
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
$dir = '/home/bitrix/www/local/php_interface/include';
$stub = 'c99f9ec7c38fc00d82f48e3294d18cdd';
$live = [
  'a7_hr_applied_badge.php','a7_hr_cv_route.php','a7_hr_cv_stage.php','a7_hr_cv_upload.php',
  'a7_hr_field_labels.php','a7_hr_stage_remove.php','a7_listing_boot.php','a7_listing_new_access.php',
];
foreach (scandir($dir) ?: [] as $name) {
  if ($name === '.' || $name === '..' || !is_file("$dir/$name")) continue;
  $md5 = md5_file("$dir/$name");
  $size = filesize("$dir/$name");
  $kind = 'stub';
  if (in_array($name, $live, true)) $kind = 'live';
  elseif ($name === 'a7_listing_new_access.php.bak-20260922-114148') $kind = ($md5 === $stub) ? 'bak-stubbed' : 'bak';
  elseif ($md5 !== $stub) $kind = 'other';
  echo "$kind\t$size\t$md5\t$name\n";
}
