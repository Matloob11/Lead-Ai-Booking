<?php

define('NO_KEEP_STATISTIC', true);
define('STOP_STATISTICS', true);
define('NO_AGENT_STATISTIC', true);
define('DisableEventsCheck', true);

require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
define('A7_CI_LIB_ONLY', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/include/a7_call_intelligence.php';

a7_ci_handle_http();
