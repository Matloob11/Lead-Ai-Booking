<?php
$file = '/home/bitrix/www/bitrix/components/bitrix/crm.lead.details/class.php';
$txt = file_get_contents($file);
$p = strpos($txt, 'function prepareFieldInfos');
echo substr($txt, $p + 11800, 2200);
