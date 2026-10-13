<?php
/**
 * Show Property Listing New to everyone, directly under old Property Listing.
 * Never pin it first.
 */
declare(strict_types=1);

if (!defined('A7_LISTING_NEW_ITEM_ID')) {
    define('A7_LISTING_NEW_ITEM_ID', '4259460310');
}
if (!defined('A7_LISTING_OLD_ITEM_ID')) {
    define('A7_LISTING_OLD_ITEM_ID', '1084955501');
}

if (!function_exists('a7_listing_new_in_list')) {
    function a7_listing_new_in_list(array $list, string $itemId): bool
    {
        foreach ($list as $id) {
            if ((string)$id === $itemId) {
                return true;
            }
        }
        return false;
    }
}

if (!function_exists('a7_listing_new_without')) {
    function a7_listing_new_without(array $list, string $itemId): array
    {
        $out = [];
        foreach ($list as $id) {
            if ((string)$id !== $itemId) {
                $out[] = $id;
            }
        }
        return $out;
    }
}

if (!function_exists('a7_listing_new_fix_sorted')) {
    function a7_listing_new_fix_sorted(array $sorted): array
    {
        if (!isset($sorted['show']) || !is_array($sorted['show'])) {
            $sorted['show'] = [];
        }
        if (!isset($sorted['hide']) || !is_array($sorted['hide'])) {
            $sorted['hide'] = [];
        }
        $show = a7_listing_new_without($sorted['show'], A7_LISTING_NEW_ITEM_ID);
        $hide = a7_listing_new_without($sorted['hide'], A7_LISTING_NEW_ITEM_ID);
        $next = [];
        $inserted = false;
        foreach ($show as $id) {
            $next[] = $id;
            if ((string)$id === A7_LISTING_OLD_ITEM_ID) {
                $next[] = A7_LISTING_NEW_ITEM_ID;
                $inserted = true;
            }
        }
        if (!$inserted) {
            if ($next) {
                array_splice($next, 1, 0, [A7_LISTING_NEW_ITEM_ID]);
            } else {
                $next[] = A7_LISTING_NEW_ITEM_ID;
            }
        }
        $sorted['show'] = array_values($next);
        $sorted['hide'] = array_values($hide);
        return $sorted;
    }
}

if (!function_exists('a7_listing_new_sorted_ok')) {
    function a7_listing_new_sorted_ok(array $sorted): bool
    {
        $show = isset($sorted['show']) && is_array($sorted['show']) ? array_values($sorted['show']) : [];
        $hide = isset($sorted['hide']) && is_array($sorted['hide']) ? $sorted['hide'] : [];
        if (a7_listing_new_in_list($hide, A7_LISTING_NEW_ITEM_ID)) {
            return false;
        }
        $posNew = false;
        $posOld = false;
        foreach ($show as $i => $id) {
            if ((string)$id === A7_LISTING_NEW_ITEM_ID) {
                $posNew = $i;
            }
            if ((string)$id === A7_LISTING_OLD_ITEM_ID) {
                $posOld = $i;
            }
        }
        if ($posNew === false) {
            return false;
        }
        if ($posOld !== false) {
            return $posNew === $posOld + 1;
        }
        return $posNew !== 0 || count($show) === 1;
    }
}

if (!function_exists('a7_listing_new_on_prolog')) {
    function a7_listing_new_on_prolog(): void
    {
        global $USER;
        if (!is_object($USER) || !$USER->IsAuthorized()) {
            return;
        }
        $uid = (int)$USER->GetID();
        if ($uid <= 0) {
            return;
        }
        $key = 'left_menu_sorted_items_s1';
        $sorted = \CUserOptions::GetOption('intranet', $key, false, $uid);
        if (!is_array($sorted)) {
            $presetRaw = \Bitrix\Main\Config\Option::get('intranet', 'left_menu_custom_preset_sort', '', 's1');
            $preset = @unserialize($presetRaw, ['allowed_classes' => false]);
            $sorted = is_array($preset) ? $preset : ['show' => [], 'hide' => []];
        }
        if (a7_listing_new_sorted_ok($sorted)) {
            return;
        }
        \CUserOptions::SetOption('intranet', $key, a7_listing_new_fix_sorted($sorted), false, $uid);
    }
}

if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', 'a7_listing_new_on_prolog');
}
