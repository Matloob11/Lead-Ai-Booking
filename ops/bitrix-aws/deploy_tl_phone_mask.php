<?php
/**
 * Inject A7 TL phone-mask OnProlog into Bitrix init.php (idempotent).
 */
$init = '/home/bitrix/www/bitrix/php_interface/init.php';
$configSrc = '/tmp/a7_tl_phone_mask.config.php';
$jsSrc = '/tmp/a7_tl_phone_mask.js';
$phpSrc = '/tmp/a7_tl_phone_mask.php';

$doc = '/home/bitrix/www';
@copy($configSrc, $doc . '/bitrix/php_interface/a7_tl_phone_mask.config.php');
@copy($jsSrc, $doc . '/bitrix/js/a7_tl_phone_mask.js');
@copy($phpSrc, $doc . '/bitrix/tools/a7_tl_phone_mask.php');
@chmod($doc . '/bitrix/php_interface/a7_tl_phone_mask.config.php', 0644);
@chmod($doc . '/bitrix/js/a7_tl_phone_mask.js', 0644);
@chmod($doc . '/bitrix/tools/a7_tl_phone_mask.php', 0644);

$marker = 'A7_TL_PHONE_MASK';
$block = <<<'PHP'

// A7_TL_PHONE_MASK: Team leads see masked phones (last 4 hidden) on CRM + Owner Data.
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        $onOwner = strpos($uri, '/crm/type/1042/') === 0;
        $onLead = strpos($uri, '/crm/lead/') === 0;
        if (!$onOwner && !$onLead) {
            return;
        }
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        $uid = (int)$USER->GetID();
        $cfgPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_tl_phone_mask.config.php';
        $cfg = is_readable($cfgPath) ? include $cfgPath : [];
        $leaders = (is_array($cfg) && isset($cfg['leaders']) && is_array($cfg['leaders'])) ? $cfg['leaders'] : [];
        if (!isset($leaders[$uid])) {
            return;
        }
        if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
            return;
        }
        $scriptPath = '/bitrix/js/a7_tl_phone_mask.js';
        $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
        $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
        $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);
    });
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
    fwrite(STDERR, "Cannot read init.php\n");
    exit(1);
}
if (strpos($src, $marker) !== false) {
    echo "init.php already has $marker\n";
} else {
    $backup = $init . '.bak.tl_mask_' . date('Ymd_His');
    if (!copy($init, $backup)) {
        fwrite(STDERR, "Backup failed\n");
        exit(1);
    }
    if (file_put_contents($init, rtrim($src) . "\n" . $block . "\n") === false) {
        fwrite(STDERR, "Write init failed\n");
        exit(1);
    }
    echo "Patched init.php (backup $backup)\n";
}

echo "Files:\n";
foreach ([
    '/bitrix/php_interface/a7_tl_phone_mask.config.php',
    '/bitrix/js/a7_tl_phone_mask.js',
    '/bitrix/tools/a7_tl_phone_mask.php',
] as $rel) {
    $p = $doc . $rel;
    echo (is_readable($p) ? 'OK' : 'MISSING') . " $rel mt=" . (@filemtime($p) ?: 0) . "\n";
}
echo "DONE\n";
