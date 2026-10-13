<?php
/**
 * Publish phone-mask (config + lib + JS + tool) and replace init.php OnProlog block.
 * Idempotent.
 */
$doc = '/home/bitrix/www';
$init = $doc . '/bitrix/php_interface/init.php';

$files = [
    'a7_tl_phone_mask.config.php' => $doc . '/bitrix/php_interface/a7_tl_phone_mask.config.php',
    'a7_tl_phone_mask_lib.php' => $doc . '/bitrix/php_interface/a7_tl_phone_mask_lib.php',
    'a7_tl_phone_mask.js' => $doc . '/bitrix/js/a7_tl_phone_mask.js',
    'a7_tl_phone_mask.php' => $doc . '/bitrix/tools/a7_tl_phone_mask.php',
];

foreach ($files as $name => $dst) {
    $src = is_readable('/tmp/' . $name) ? '/tmp/' . $name : __DIR__ . '/' . $name;
    if (!is_readable($src)) {
        fwrite(STDERR, "missing $src\n");
        exit(1);
    }
    if (!@copy($src, $dst)) {
        fwrite(STDERR, "copy failed $dst\n");
        exit(1);
    }
    @chmod($dst, 0644);
    echo 'OK ' . $dst . ' ' . filesize($dst) . "\n";
}

$marker = 'A7_TL_PHONE_MASK';
$block = <<<'PHP'
// A7_TL_PHONE_MASK: last-4 phone mask for TLs + Admin&Finance dept (auto), except exempt.
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        if (strpos($uri, '/bitrix/admin/') !== false) {
            return;
        }
        if (preg_match('#/(login|auth)(/|\?|$)#', $uri)) {
            return;
        }
        $lib = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_tl_phone_mask_lib.php';
        if (!is_readable($lib)) {
            return;
        }
        require_once $lib;
        $uid = (int)$USER->GetID();
        if (!a7_tl_mask_should_apply($uid)) {
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

$backup = $init . '.bak.tl_mask_' . date('Ymd_His');
if (!copy($init, $backup)) {
    fwrite(STDERR, "Backup failed\n");
    exit(1);
}

$start = strpos($src, '// A7_TL_PHONE_MASK');
if ($start === false) {
    $start = strpos($src, $marker);
}
if ($start !== false) {
    $ifPos = strpos($src, "if (function_exists('AddEventHandler'))", $start);
    $brace = $ifPos === false ? false : strpos($src, '{', $ifPos);
    if ($brace === false) {
        fwrite(STDERR, "init marker found but block not parsed\n");
        exit(1);
    }
    $depth = 0;
    $end = $brace;
    $len = strlen($src);
    for ($i = $brace; $i < $len; $i++) {
        $ch = $src[$i];
        if ($ch === '{') {
            $depth++;
        } elseif ($ch === '}') {
            $depth--;
            if ($depth === 0) {
                $end = $i + 1;
                break;
            }
        }
    }
    $src = substr($src, 0, $start) . $block . substr($src, $end);
    echo "init block replaced backup=$backup\n";
} else {
    $src = rtrim($src) . "\n" . $block . "\n";
    echo "init patched backup=$backup\n";
}

if (file_put_contents($init, $src) === false) {
    fwrite(STDERR, "Write init failed\n");
    exit(1);
}

passthru('php -l ' . escapeshellarg($doc . '/bitrix/php_interface/a7_tl_phone_mask_lib.php'));
passthru('php -l ' . escapeshellarg($doc . '/bitrix/tools/a7_tl_phone_mask.php'));
passthru('php -l ' . escapeshellarg($init));
echo "DONE\n";
