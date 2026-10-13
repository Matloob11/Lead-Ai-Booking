<?php
$file = '/home/bitrix/www/bitrix/components/bitrix/crm.lead.details/ajax.php';
$txt = file_get_contents($file);
$p = strpos($txt, 'PREPARE_EDITOR_HTML');
echo substr($txt, $p + 3200, 4500);
