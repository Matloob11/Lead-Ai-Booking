<?php
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
$p = '/home/bitrix/www/local/php_interface/include/a7_c13_auth.php';
$b = file_get_contents($p);
echo 'md5=' . md5($b) . "\n";
echo 'len=' . strlen($b) . "\n";
echo 'hex=' . bin2hex($b) . "\n";
echo 'raw=' . var_export($b, true) . "\n";
