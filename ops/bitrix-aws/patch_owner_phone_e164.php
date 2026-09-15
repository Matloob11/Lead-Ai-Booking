<?php
/**
 * Patch live a7_owner_data_normalize_phone_value to always return +971 E.164.
 */
$path = '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';
$text = file_get_contents($path);
if ($text === false) {
    fwrite(STDERR, "cannot read $path\n");
    exit(1);
}

$backup = $path . '.bak.zadarma_' . date('Ymd_His');
if (!copy($path, $backup)) {
    fwrite(STDERR, "backup failed\n");
    exit(1);
}

$newFn = <<<'PHP'
function a7_owner_data_normalize_phone_value($raw): string
{
    if ($raw === null) {
        return '';
    }
    if (is_array($raw)) {
        foreach ($raw as $part) {
            $phone = a7_owner_data_normalize_phone_value($part);
            if ($phone !== '') {
                return $phone;
            }
        }
        return '';
    }
    $text = trim((string)$raw);
    if ($text === '' || $text === '0') {
        return '';
    }
    $digits = preg_replace('/\D/', '', $text) ?? '';
    if ($digits === '') {
        return '';
    }
    if (str_starts_with($digits, '00')) {
        $digits = substr($digits, 2);
    }
    // Always UAE E.164 for Owner Data dial: +971… no spaces.
    if (str_starts_with($digits, '971')) {
        return '+' . $digits;
    }
    if (str_starts_with($digits, '0')) {
        return '+971' . substr($digits, 1);
    }
    if (strlen($digits) >= 8 && strlen($digits) <= 9) {
        return '+971' . $digits;
    }
    return '+' . $digits;
}
PHP;

// PHP 7.x may lack str_starts_with — use substr for live Bitrix.
$newFn = str_replace(
    ['str_starts_with($digits, \'00\')', 'str_starts_with($digits, \'971\')', 'str_starts_with($digits, \'0\')'],
    ['substr($digits, 0, 2) === \'00\'', 'substr($digits, 0, 3) === \'971\'', 'substr($digits, 0, 1) === \'0\''],
    $newFn
);

$pattern = '/function a7_owner_data_normalize_phone_value\(\$raw\): string\s*\{.*?\n\}/s';
if (!preg_match($pattern, $text)) {
    fwrite(STDERR, "function not found\n");
    exit(1);
}
$text2 = preg_replace($pattern, rtrim($newFn), $text, 1, $count);
if ($count !== 1) {
    fwrite(STDERR, "replace count=$count\n");
    exit(1);
}
file_put_contents($path, $text2);
echo "patched $path\nbackup $backup\n";

// Also patch handlers file if present and defines its own collector without E.164.
$handlers = '/home/bitrix/www/bitrix/tools/a7_owner_data_call_handlers.php';
if (is_readable($handlers)) {
    $h = file_get_contents($handlers);
    if (strpos($h, 'a7_clean_phone($raw)') !== false) {
        copy($handlers, $handlers . '.bak.zadarma_' . date('Ymd_His'));
        $h2 = str_replace(
            '$phone = a7_clean_phone($raw);',
            '$phone = function_exists(\'a7_owner_data_normalize_phone_value\') ? a7_owner_data_normalize_phone_value($raw) : a7_clean_phone($raw);',
            $h
        );
        file_put_contents($handlers, $h2);
        echo "patched handlers clean_phone call\n";
    }
}

echo "OK\n";
