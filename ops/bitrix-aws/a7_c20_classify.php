<?php
/**
 * C20: classify every file under local/php_interface/include.
 * CLI only. No CRM writes. Greps init.php files and a short allowlist of trees.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

$dir = '/home/bitrix/www/local/php_interface/include';
$stubBody = "<?php\nhttp_response_code(404);\nexit;\n";
$realStubMd5 = md5($stubBody);

$haystacks = [];
foreach ([
    '/home/bitrix/www/bitrix/php_interface/init.php',
    '/home/bitrix/www/local/php_interface/init.php',
] as $p) {
    if (is_file($p)) {
        $haystacks[$p] = (string)file_get_contents($p);
    }
}
foreach (glob('/etc/systemd/system/a7-3cx-historical-*') ?: [] as $unit) {
    if (is_file($unit)) {
        $haystacks[$unit] = (string)file_get_contents($unit);
    }
}
$cronOut = [];
@exec('crontab -l -u bitrix 2>/dev/null', $cronOut);
$haystacks['crontab'] = implode("\n", $cronOut);

// Live include trees that may require() these names (bounded).
$extraDirs = [
    '/home/bitrix/www/local/php_interface',
    '/home/bitrix/www/bitrix/php_interface',
    '/home/bitrix/www/bitrix/tools',
];
foreach ($extraDirs as $root) {
    if (!is_dir($root)) {
        continue;
    }
    $it = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS)
    );
    foreach ($it as $file) {
        /** @var SplFileInfo $file */
        if (!$file->isFile() || strtolower($file->getExtension()) !== 'php') {
            continue;
        }
        $path = $file->getPathname();
        if (strpos($path, '/local/php_interface/include/') !== false) {
            continue;
        }
        if (filesize($path) > 500_000) {
            continue;
        }
        $haystacks[$path] = (string)@file_get_contents($path);
    }
}

function a7_c20_ref(string $name, array $haystacks): string
{
    $base = basename($name, '.php');
    foreach ($haystacks as $path => $text) {
        if ($text === '') {
            continue;
        }
        if (strpos($text, $name) !== false || strpos($text, $base) !== false) {
            return $path;
        }
    }
    return '';
}

$files = [];
foreach (scandir($dir) ?: [] as $name) {
    if ($name === '.' || $name === '..') {
        continue;
    }
    $path = $dir . '/' . $name;
    if (!is_file($path)) {
        continue;
    }
    $size = (int)filesize($path);
    $md5 = md5_file($path);
    $body = (string)@file_get_contents($path);
    $isStub = ($md5 === $realStubMd5)
        || ($size <= 60 && strpos($body, '404') !== false && strpos($body, 'exit') !== false);
    $ref = a7_c20_ref($name, $haystacks);
    $kind = 'one-off';
    if ($name === 'a7_listing_new_access.php.bak-20260922-114148') {
        $kind = 'remove';
    } elseif ($isStub) {
        $kind = 'stub';
    } elseif ($ref !== '') {
        $kind = 'live';
    } elseif (preg_match('/^a7_(hr_|listing_)/', $name)) {
        $kind = 'live-suspect';
    }
    $files[] = compact('name', 'size', 'md5', 'kind') + ['ref' => $ref === '' ? '-' : $ref];
}

usort($files, static fn ($a, $b) => strcmp($a['name'], $b['name']));
echo "stub_md5={$realStubMd5}\n";
echo 'count=' . count($files) . "\n";
foreach ($files as $f) {
    echo $f['kind'], "\t", $f['size'], "\t", $f['md5'], "\t", $f['ref'], "\t", $f['name'], "\n";
}
