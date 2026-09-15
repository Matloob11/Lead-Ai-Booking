<?php
$path = '/home/bitrix/www/bitrix/tools/a7_3cx_click_to_call.php';
$src = file_get_contents($path);
if ($src === false) {
    fwrite(STDERR, "cannot read\n");
    exit(1);
}

$old = <<<'OLD'
    $categoryId = (int)($deal['CATEGORY_ID'] ?? 0);
    if ($categoryId !== a7_renewals_category_id()) {
        a7_json([
            'success' => true,
            'skipped' => true,
            'reason' => 'not_renewals_category',
            'categoryId' => $categoryId,
            'phones' => [],
            'count' => 0,
        ]);
    }

    $phones = a7_deal_collect_phones($deal);
OLD;

$new = <<<'NEW'
    $categoryId = (int)($deal['CATEGORY_ID'] ?? 0);
    if ($categoryId === a7_renewals_category_id()) {
        $phones = a7_deal_collect_phones($deal);
    } elseif (function_exists('a7_sales_deal_category_id') && $categoryId === a7_sales_deal_category_id()) {
        $phones = a7_sales_deal_collect_phones($deal);
    } else {
        a7_json([
            'success' => true,
            'skipped' => true,
            'reason' => 'unsupported_deal_category',
            'categoryId' => $categoryId,
            'phones' => [],
            'count' => 0,
        ]);
    }
NEW;

if (str_contains($src, 'unsupported_deal_category')) {
    echo "already widened\n";
    exit(0);
}
if (!str_contains($src, $old)) {
    fwrite(STDERR, "OLD block missing\n");
    exit(1);
}

$bak = $path . '.bak.widen-' . date('Ymd-His');
copy($path, $bak);
file_put_contents($path, str_replace($old, $new, $src));
echo "widened\n";
passthru('php -l ' . escapeshellarg($path));
