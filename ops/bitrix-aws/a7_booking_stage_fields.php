<?php
/**
 * Booking-stage lead fields. The five fields exist on every lead for the
 * webhook, and the lead card shows them only while the stage is Booking.
 *
 * Deployed to: /home/bitrix/www/bitrix/php_interface/include/a7_booking_stage_fields.php
 * Loaded from init.php (A7_BOOKING_STAGE_FIELDS).
 */
declare(strict_types=1);

if (PHP_SAPI !== 'cli' && !defined('B_PROLOG_INCLUDED')) {
	http_response_code(404);
	exit;
}

if (defined('A7_BOOKING_STAGE_FIELDS_LOADED')) {
	return;
}
define('A7_BOOKING_STAGE_FIELDS_LOADED', true);

final class A7BookingStageFields
{
	public const STAGE = 'CONVERTED';
	public const JS_PATH = '/bitrix/js/a7_booking_stage_fields.js';

	public static function register(): void
	{
		\Bitrix\Main\EventManager::getInstance()->addEventHandler(
			'main',
			'OnProlog',
			[self::class, 'onProlog']
		);
	}

	public static function onProlog(): void
	{
		global $USER, $APPLICATION;
		if (!is_object($USER) || !$USER->IsAuthorized() || !is_object($APPLICATION)) {
			return;
		}
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		if (!preg_match('#/crm/(?:lead|type/1)/#', $uri)) {
			return;
		}
		$full = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
		$version = is_file($full) ? (string)filemtime($full) : (string)time();
		if (method_exists($APPLICATION, 'AddHeadScript')) {
			$APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . $version);
		}
	}
}

A7BookingStageFields::register();
