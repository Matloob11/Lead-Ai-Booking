<?php
$t = file_get_contents('/home/bitrix/www/bitrix/js/crm/kanban/src/grid.js');
foreach (['addColumn', 'column-add', 'add-column', 'plus'] as $n) {
    echo $n, ' ', substr_count($t, $n), "\n";
}
$j = strpos($t, 'addColumn');
if ($j !== false) {
    echo substr(preg_replace('/\s+/', ' ', substr($t, max(0, $j - 100), 400)), 0, 400), "\n";
}
