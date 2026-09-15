<?php
echo "sapi=" . php_sapi_name() . "\n";
echo "curl=" . (function_exists('curl_init') ? 'Y' : 'N') . "\n";
echo "php=" . PHP_VERSION . "\n";
echo "ini=" . php_ini_loaded_file() . "\n";
