<?php
/**
 * Owner Data (SPA 1042) custom click-to-call handlers.
 * Included from a7_3cx_click_to_call.php — do not call directly.
 */

if (!function_exists('a7_owner_data_phone_fields_extended')) {
    function a7_owner_data_phone_fields_extended(): array
    {
        return [
            'ufCrm5_1768317611513' => 'phone number',
            'ufCrm5_1769416533028' => 'phone number 1',
            'ufCrm5_1768314841508' => 'Import Owner Mobile',
            'ufCrm5_1768317656051' => 'mobile number 2',
            'ufCrm5_1777563197150' => 'Owner no 1',
            'ufCrm5_1779805546251' => 'Owner phone extra',
        ];
    }
}

if (!function_exists('a7_owner_data_collect_phones')) {
    function a7_owner_data_collect_phones(array $item): array
    {
        $out = [];
        $seen = [];

        foreach (a7_owner_data_phone_fields_extended() as $field => $label) {
            $value = $item[$field] ?? null;
            $values = is_array($value) ? $value : [$value];
            foreach ($values as $candidate) {
                if ($candidate === null) {
                    continue;
                }
                $raw = trim((string)$candidate);
                if ($raw === '' || $raw === '0') {
                    continue;
                }
                $phone = function_exists('a7_owner_data_normalize_phone_value')
                    ? a7_owner_data_normalize_phone_value($raw)
                    : a7_clean_phone($raw);
                $digits = preg_replace('/\D/', '', $phone) ?? '';
                if (strlen($digits) < 6) {
                    continue;
                }
                $key = strlen($digits) > 10 ? substr($digits, -10) : $digits;
                if (isset($seen[$key])) {
                    continue;
                }
                $seen[$key] = true;
                $out[] = [
                    'phone' => $phone,
                    'label' => $label,
                    'field' => $field,
                ];
            }
        }

        return $out;
    }
}

if (!function_exists('a7_owner_data_get_item')) {
    function a7_owner_data_get_item(int $itemId): ?array
    {
        if ($itemId <= 0) {
            return null;
        }

        $response = a7_bitrix_webhook_call('crm.item.get', [
            'entityTypeId' => A7_OWNER_DATA_ENTITY_TYPE_ID,
            'id' => $itemId,
        ]);
        $item = $response['json']['result']['item'] ?? null;
        if (!$response['ok'] || !is_array($item)) {
            return null;
        }

        return $item;
    }
}

if (!function_exists('a7_handle_owner_data_phones')) {
    function a7_handle_owner_data_phones(): void
    {
        a7_require_bitrix_user();
        $itemId = (int)a7_request_value('id', 0);
        if ($itemId <= 0) {
            a7_json(['success' => false, 'message' => 'Owner Data item id missing'], 400);
        }

        $item = a7_owner_data_get_item($itemId);
        if (!$item) {
            a7_json(['success' => false, 'message' => 'Owner Data item not found'], 404);
        }

        $phones = a7_owner_data_collect_phones($item);
        a7_json([
            'success' => true,
            'id' => $itemId,
            'title' => (string)($item['title'] ?? ''),
            'categoryId' => (int)($item['categoryId'] ?? 0),
            'phones' => $phones,
            'count' => count($phones),
        ]);
    }
}

if (!function_exists('a7_handle_owner_data_call')) {
    function a7_handle_owner_data_call(): void
    {
        $userId = a7_require_bitrix_user();
        $itemId = (int)a7_request_value('id', 0);
        $phone = a7_clean_phone((string)a7_request_value('phone', ''));
        $pageUrl = (string)a7_request_value('pageUrl', '');

        if ($itemId <= 0) {
            a7_json(['success' => false, 'message' => 'Owner Data item id missing'], 400);
        }
        if ($phone === '' || strlen(preg_replace('/\D/', '', $phone) ?? '') < 6) {
            a7_json(['success' => false, 'message' => 'Valid phone number missing'], 400);
        }

        $item = a7_owner_data_get_item($itemId);
        if (!$item) {
            a7_json(['success' => false, 'message' => 'Owner Data item not found'], 404);
        }

        $phones = a7_owner_data_collect_phones($item);
        $allowed = false;
        $requestDigits = preg_replace('/\D/', '', $phone) ?? '';
        $requestKey = strlen($requestDigits) > 10 ? substr($requestDigits, -10) : $requestDigits;
        foreach ($phones as $row) {
            $digits = preg_replace('/\D/', '', (string)$row['phone']) ?? '';
            $key = strlen($digits) > 10 ? substr($digits, -10) : $digits;
            if ($key !== '' && $key === $requestKey) {
                $allowed = true;
                $phone = (string)$row['phone'];
                break;
            }
        }
        if (!$allowed) {
            a7_json(['success' => false, 'message' => 'Phone is not on this Owner Data card'], 400);
        }

        try {
            $assignedById = (int)($item['assignedById'] ?? 0);
            $callOwner = a7_resolve_owner_extension('', 0, $assignedById > 0 ? $assignedById : $userId);
            // Prefer current user extension so agent hears their own softphone ring.
            try {
                $selfOwner = a7_resolve_owner_extension('', 0, $userId);
                $callOwner = $selfOwner;
            } catch (Throwable $ignored) {
                // keep entity/fallback owner
            }

            $makeCall = a7_3cx_make_call($phone, [
                'source' => 'owner_data_custom_button',
                'bitrix_user_id' => $userId,
                'call_owner_user_id' => $callOwner['bitrix_user_id'],
                'entity_type' => 'owner_data',
                'entity_id' => $itemId,
                'page_url' => $pageUrl,
            ], $callOwner['extension']);

            if (!$makeCall['ok']) {
                a7_log('owner-data 3CX makecall failed', [
                    'item_id' => $itemId,
                    'phone' => a7_mask_phone($phone),
                    'extension' => $callOwner['extension'],
                    'status' => $makeCall['status'],
                    'raw' => mb_substr((string)$makeCall['raw'], 0, 300),
                ]);
                a7_json(['success' => false, 'message' => '3CX makecall failed'], 502);
            }

            // Timeline activity on SPA item (OWNER_TYPE_ID = 1042).
            $description = 'Outbound call started from Owner Data Call button.'
                . "\nExtension: " . $callOwner['extension']
                . "\nPhone: " . $phone;
            a7_bitrix_webhook_call('crm.activity.add', [
                'fields' => [
                    'OWNER_TYPE_ID' => A7_OWNER_DATA_ENTITY_TYPE_ID,
                    'OWNER_ID' => $itemId,
                    'TYPE_ID' => 2,
                    'SUBJECT' => 'Owner Data outbound call started',
                    'START_TIME' => date('c'),
                    'END_TIME' => date('c'),
                    'COMPLETED' => 'N',
                    'DIRECTION' => 2,
                    'RESPONSIBLE_ID' => $callOwner['bitrix_user_id'],
                    'DESCRIPTION' => $description,
                    'COMMUNICATIONS' => [[
                        'ENTITY_TYPE_ID' => A7_OWNER_DATA_ENTITY_TYPE_ID,
                        'ENTITY_ID' => $itemId,
                        'TYPE' => 'PHONE',
                        'VALUE' => $phone,
                    ]],
                ],
            ]);

            a7_log('owner-data 3CX makecall started', [
                'item_id' => $itemId,
                'phone' => a7_mask_phone($phone),
                'bitrix_user_id' => $userId,
                'extension' => $callOwner['extension'],
            ]);

            a7_json([
                'success' => true,
                'message' => 'Call started',
                'phone' => $phone,
                'extension' => $callOwner['extension'],
                'call_owner_user_id' => $callOwner['bitrix_user_id'],
                'call_owner_name' => $callOwner['name'],
                'itemId' => $itemId,
            ]);
        } catch (Throwable $e) {
            a7_log('owner-data call exception', [
                'item_id' => $itemId,
                'error' => $e->getMessage(),
            ]);
            a7_json(['success' => false, 'message' => $e->getMessage()], 500);
        }
    }
}

/**
 * Voiso path for Owner Data — POSTs Bitrix-shaped ONEXTERNALCALLSTART to
 * cc-ams04 click2call. Does not re-register Voiso on Bitrix events (Zadarma
 * keeps exclusive phoneTo / ONEXTERNALCALLSTART).
 *
 * Live copy lives inside bitrix/tools/a7_3cx_click_to_call.php
 * (action=owner-data-call-voiso). Keep this file as the readable mirror.
 */
if (!function_exists('a7_voiso_click2call_config')) {
    function a7_voiso_click2call_config(): array
    {
        return [
            'url' => 'https://cc-ams04.voiso.com/api/v2/bitrix/click2call',
            'application_token' => 'h41vbi4n0mqo0l2411h17ki21d4kj0lo',
            'event_handler_id' => '786',
        ];
    }
}

/**
 * Live handler uses a7_http_raw (not curl_init) — Apache PHP here has curl disabled
 * (/etc/php.d/20-curl.ini empty). See fix_owner_voiso_nocurl.php.
 */
