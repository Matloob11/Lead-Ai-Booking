<?php
foreach ([
    '/home/bitrix/www/bitrix/tools/a7_lead_wa.php',
    '/home/bitrix/www/bitrix/tools/a7_renewals_wa.php',
] as $path) {
    passthru('php -l ' . escapeshellarg($path));
}
$js = file_get_contents('/home/bitrix/www/bitrix/js/a7_lead_wa.js');
echo str_contains($js, 'variable_fields') ? "lead js field map yes\n" : "lead js MISSING\n";
echo str_contains($js, 'A7_LEAD_WA_V13') ? "lead js v13 yes\n" : "lead js version MISSING\n";
$r = file_get_contents('/home/bitrix/www/bitrix/js/a7_renewals_wa.js');
echo str_contains($r, 'tenant_variable_fields') ? "renewals js field map yes\n" : "renewals js MISSING\n";
echo "OK\n";
