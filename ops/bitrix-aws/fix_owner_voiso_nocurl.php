<?php
/**
 * Replace curl_init block inside a7_handle_owner_data_call_voiso with a7_http_raw.
 */
$path = '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';
$src = file_get_contents($path);
if ($src === false) {
	fwrite(STDERR, "cannot read\n");
	exit(1);
}

if (strpos($src, "a7_http_raw(\n        'POST',\n        \$cfg['url']") !== false
	|| strpos($src, "a7_http_raw(\r\n        'POST',\r\n        \$cfg['url']") !== false
) {
	echo "already fixed\n";
	exit(0);
}

$new = <<<'PHP'
    // Apache PHP on this host has curl disabled; a7_http_raw falls back to streams.
    $http = a7_http_raw(
        'POST',
        $cfg['url'],
        ['Content-Type' => 'application/x-www-form-urlencoded'],
        http_build_query($payload)
    );
    $raw = (string)($http['raw'] ?? '');
    $status = (int)($http['status'] ?? 0);
    $error = (string)($http['error'] ?? '');

    if (empty($http['ok'])) {
        a7_log('owner-data voiso click2call failed', [
            'item_id' => $itemId,
            'phone' => a7_mask_phone($phone),
            'http' => $status,
            'error' => $error,
            'raw' => mb_substr($raw, 0, 400),
        ]);
        a7_json([
            'success' => false,
            'message' => 'Voiso rejected the call (' . ($status ?: 'net') . '). Be Available in Voiso Agent Panel.',
            'http' => $status,
            'detail' => mb_substr($raw !== '' ? $raw : $error, 0, 180),
        ], 502);
    }
PHP;

$pattern = '/\r?\n[ \t]*\$ch = curl_init\(\$cfg\[\'url\'\]\);.*?\r?\n[ \t]*curl_close\(\$ch\);\r?\n\r?\n[ \t]*if \(\$errno \|\| \$status < 200 \|\| \$status >= 300\) \{.*?\r?\n[ \t]*\], 502\);\r?\n[ \t]*\}/s';

if (!preg_match($pattern, $src)) {
	// Dump nearby lines for debug
	$pos = strpos($src, 'curl_init($cfg[\'url\'])');
	fwrite(STDERR, "regex no match pos=" . var_export($pos, true) . "\n");
	if ($pos !== false) {
		fwrite(STDERR, substr($src, $pos - 20, 900) . "\n");
	}
	exit(1);
}

$bak = $path . '.bak-voiso-nocurl-' . date('Ymd-His');
if (!copy($path, $bak)) {
	fwrite(STDERR, "backup failed\n");
	exit(1);
}

$src2 = preg_replace($pattern, "\n" . $new, $src, 1, $count);
if ($count !== 1) {
	fwrite(STDERR, "replace count=$count\n");
	exit(1);
}
if (file_put_contents($path, $src2) === false) {
	fwrite(STDERR, "write failed\n");
	exit(1);
}

echo "fixed ok backup=$bak\n";
echo "still_curl=" . (preg_match('/function a7_handle_owner_data_call_voiso.*?curl_init/s', $src2) ? 'Y' : 'N') . "\n";
echo "has_http_raw=" . (strpos($src2, "\$cfg['url']") !== false && strpos($src2, 'a7_http_raw') !== false ? 'Y' : 'N') . "\n";
