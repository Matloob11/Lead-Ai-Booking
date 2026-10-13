<?php
/**
 * Publish the Leads-list WhatsApp button (JS + PHP tool + init.php).
 * Idempotent. Does not overwrite a live config that already has a secret.
 */
$doc = '/home/bitrix/www';
$init = $doc . '/bitrix/php_interface/init.php';
$jsDst = $doc . '/bitrix/js/a7_lead_wa.js';
$phpDst = $doc . '/bitrix/tools/a7_lead_wa.php';
$cfgDst = $doc . '/bitrix/php_interface/a7_lead_wa.config.php';

$jsSrc = is_readable('/tmp/a7_lead_wa.js') ? '/tmp/a7_lead_wa.js' : __DIR__ . '/a7_lead_wa.js';
$phpSrc = is_readable('/tmp/a7_lead_wa.php') ? '/tmp/a7_lead_wa.php' : __DIR__ . '/a7_lead_wa.php';
$cfgSrc = is_readable('/tmp/a7_lead_wa.config.php') ? '/tmp/a7_lead_wa.config.php' : __DIR__ . '/a7_lead_wa.config.php';

foreach ([$jsSrc, $phpSrc] as $src) {
    if (!is_readable($src)) {
        fwrite(STDERR, "missing $src\n");
        exit(1);
    }
}

if (!copy($jsSrc, $jsDst) || !copy($phpSrc, $phpDst)) {
    fwrite(STDERR, "copy js/php failed\n");
    exit(1);
}
@chmod($jsDst, 0644);
@chmod($phpDst, 0644);
echo "js " . filesize($jsDst) . " php " . filesize($phpDst) . "\n";

$keepSecret = '';
if (is_readable($cfgDst)) {
    $existing = include $cfgDst;
    if (is_array($existing)) {
        $keepSecret = trim((string)($existing['secret'] ?? ''));
    }
}
$incoming = is_readable($cfgSrc) ? include $cfgSrc : [];
$secret = $keepSecret !== '' ? $keepSecret : trim((string)($incoming['secret'] ?? ''));
$inbox = is_array($incoming) && !empty($incoming['inbox_url'])
    ? (string)$incoming['inbox_url']
    : 'https://wa.srv1802669.hstgr.cloud';
$cfgPhp = "<?php\nreturn [\n    'secret' => " . var_export($secret, true) .
    ",\n    'inbox_url' => " . var_export($inbox, true) . ",\n];\n";
if (file_put_contents($cfgDst, $cfgPhp) === false) {
    fwrite(STDERR, "write config failed\n");
    exit(1);
}
@chmod($cfgDst, 0640);
echo "config secret=" . ($secret !== '' ? "set" : "EMPTY") . "\n";

$marker = 'A7_LEAD_WA_BUTTON';
$block = <<<'PHP'
// A7_LEAD_WA_BUTTON: WhatsApp campaign on CRM lead + Owner Data / Availability list + kanban.
if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', static function () {
        global $APPLICATION, $USER;
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        $onLead = strpos($uri, '/crm/lead/') === 0;
        $onOwner = strpos($uri, '/crm/type/1042/') !== false;
        if (!$onLead && !$onOwner) {
            return;
        }
        if (preg_match('#/crm/lead/details/#', $uri) || preg_match('#/crm/type/1042/details/#', $uri)) {
            return;
        }
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
            return;
        }
        $scriptPath = '/bitrix/js/a7_lead_wa.js';
        $fullPath = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . $scriptPath;
        $version = is_readable($fullPath) ? (string)@filemtime($fullPath) : (string)time();
        $APPLICATION->AddHeadScript($scriptPath . '?v=' . $version);
    });
}
PHP;

$src = file_get_contents($init);
if ($src === false) {
    fwrite(STDERR, "cannot read init.php\n");
    exit(1);
}

$backup = $init . '.bak.lead_wa_' . date('Ymd_His');
if (!copy($init, $backup)) {
    fwrite(STDERR, "init backup failed\n");
    exit(1);
}

$start = strpos($src, '// A7_LEAD_WA_BUTTON');
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
    fwrite(STDERR, "write init failed\n");
    exit(1);
}

passthru('php -l ' . escapeshellarg($phpDst), $code1);
passthru('php -l ' . escapeshellarg($cfgDst), $code2);
passthru('php -l ' . escapeshellarg($init), $code3);
echo "js_http=";
passthru('curl -sI https://crm.a7grouprealestatedxb.com/bitrix/js/a7_lead_wa.js | head -n 1');
exit(($code1 === 0 && $code2 === 0 && $code3 === 0) ? 0 : 1);
