<?php
/**
 * Probe Voiso click2call with the same payload shape we send from Owner Data.
 * Run: php /tmp/probe_voiso_payload.php
 */
$url = 'https://cc-ams04.voiso.com/api/v2/bitrix/click2call';
$token = 'h41vbi4n0mqo0l2411h17ki21d4kj0lo';
$handlerId = '786';
$phone = '+971551054133';
$userId = '1';
$itemId = '89539';
$callId = 'externalCall.a7voiso.test.' . time();
$ts = (string) time();

$nested = [
	'event' => 'ONEXTERNALCALLSTART',
	'event_handler_id' => $handlerId,
	'data' => [
		'PHONE_NUMBER' => $phone,
		'PHONE_NUMBER_INTERNATIONAL' => $phone,
		'EXTENSION' => '',
		'USER_ID' => $userId,
		'CALL_LIST_ID' => '0',
		'LINE_NUMBER' => '',
		'IS_MOBILE' => '0',
		'CALL_ID' => $callId,
		'CRM_ENTITY_TYPE' => 'DYNAMIC_1042',
		'CRM_ENTITY_ID' => $itemId,
	],
	'ts' => $ts,
	'auth' => [
		'domain' => 'crm.a7grouprealestatedxb.com',
		'client_endpoint' => 'https://crm.a7grouprealestatedxb.com/rest/',
		'server_endpoint' => 'https://oauth.bitrix.info/rest/',
		'member_id' => '',
		'application_token' => $token,
	],
];

function post_voiso(string $url, $body, string $contentType): array
{
	$ch = curl_init($url);
	curl_setopt_array($ch, [
		CURLOPT_POST => true,
		CURLOPT_RETURNTRANSFER => true,
		CURLOPT_TIMEOUT => 20,
		CURLOPT_CONNECTTIMEOUT => 8,
		CURLOPT_HTTPHEADER => ['Content-Type: ' . $contentType],
		CURLOPT_POSTFIELDS => is_string($body) ? $body : http_build_query($body),
	]);
	$raw = curl_exec($ch);
	$errno = curl_errno($ch);
	$error = curl_error($ch);
	$status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
	curl_close($ch);
	return [
		'http' => $status,
		'errno' => $errno,
		'error' => $error,
		'raw' => mb_substr((string) $raw, 0, 800),
	];
}

echo "url=$url\n";
echo "=== nested_form ===\n";
echo json_encode(post_voiso($url, $nested, 'application/x-www-form-urlencoded'), JSON_UNESCAPED_SLASHES) . "\n";

echo "=== json ===\n";
echo json_encode(post_voiso($url, json_encode($nested), 'application/json'), JSON_UNESCAPED_SLASHES) . "\n";

$flat = [
	'event' => 'ONEXTERNALCALLSTART',
	'event_handler_id' => $handlerId,
	'data[PHONE_NUMBER]' => $phone,
	'data[PHONE_NUMBER_INTERNATIONAL]' => $phone,
	'data[USER_ID]' => $userId,
	'data[CALL_ID]' => $callId,
	'data[CRM_ENTITY_TYPE]' => 'DYNAMIC_1042',
	'data[CRM_ENTITY_ID]' => $itemId,
	'data[IS_MOBILE]' => '0',
	'ts' => $ts,
	'auth[domain]' => 'crm.a7grouprealestatedxb.com',
	'auth[application_token]' => $token,
	'auth[member_id]' => '',
];
echo "=== flat ===\n";
echo json_encode(post_voiso($url, $flat, 'application/x-www-form-urlencoded'), JSON_UNESCAPED_SLASHES) . "\n";

// Without leading +
$nestedNoPlus = $nested;
$nestedNoPlus['data']['PHONE_NUMBER'] = '971551054133';
$nestedNoPlus['data']['PHONE_NUMBER_INTERNATIONAL'] = '971551054133';
echo "=== nested_no_plus ===\n";
echo json_encode(post_voiso($url, $nestedNoPlus, 'application/x-www-form-urlencoded'), JSON_UNESCAPED_SLASHES) . "\n";
