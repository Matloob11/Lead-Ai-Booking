<?php
/**
 * C46 — Availability outgoing webhook for Lead AI inventory refresh.
 *
 * On SPA 1042 (Owner Data) add / update, when the card is in one of the three
 * available stages (or just left/entered them), POST a signed ping to Django:
 *   POST https://wa.srv1802669.hstgr.cloud/api/leadai/inventory/bitrix/
 *   body  {"event":"update","id":<card id>,"stageId":"<stage>","ts":<unix>}
 *   header X-A7-Signature = hex(hmac_sha256(secret, "leadai-inventory." + ts + "." + body))
 * Secret = a7_lead_wa.config.php 'secret' (CRM_LEAD_WA_SECRET).
 *
 * DISABLED by default until Claude's round 20 endpoint is live. Enable:
 *   in /bitrix/php_interface/a7_inventory_webhook.config.php set 'enabled' => true
 *   (or create that file from the .example). Soft-fail: never blocks the CRM save.
 *
 * Deployed to: bitrix/php_interface/include/a7_inventory_webhook.php
 * Wired from init.php (see a7_patch_init_inventory_webhook.php).
 */
declare(strict_types=1);

if (defined('A7_INVENTORY_WEBHOOK_LOADED')) {
	return;
}
define('A7_INVENTORY_WEBHOOK_LOADED', true);

final class A7InventoryWebhook
{
	public const VERSION = '1.0.5';

	/** @var array<int, int> card id → unix ts of last successful post (dedupe dual event spellings) */
	private static array $posted = [];
	public const TYPE = 1042;
	public const CATEGORY = 14;
	public const URL = 'https://wa.srv1802669.hstgr.cloud/api/leadai/inventory/bitrix/';
	public const STAGES = [
		'DT1042_14:UC_73SP7H' => true,
		'DT1042_14:PREPARATION' => true,
		'DT1042_14:UC_G0PCBL' => true,
	];

	public static function register(): void
	{
		try {
			$em = \Bitrix\Main\EventManager::getInstance();
			// Live Bitrix fires onCrmDynamicItemUpdate (not onAfter…) — proved C46 2026-10-21.
			$em->addEventHandler('crm', 'onCrmDynamicItemAdd', [self::class, 'onAfterItem']);
			$em->addEventHandler('crm', 'onCrmDynamicItemUpdate', [self::class, 'onAfterItem']);
			$em->addEventHandler('crm', 'OnCrmDynamicItemAdd', [self::class, 'onAfterItemLegacy']);
			$em->addEventHandler('crm', 'OnCrmDynamicItemUpdate', [self::class, 'onAfterItemLegacy']);
			$em->addEventHandler('crm', 'onAfterCrmDynamicItemAdd', [self::class, 'onAfterItem']);
			$em->addEventHandler('crm', 'onAfterCrmDynamicItemUpdate', [self::class, 'onAfterItem']);
		} catch (\Throwable $e) {
			self::log('register error: ' . $e->getMessage());
		}
	}

	public static function enabled(): bool
	{
		$path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www')
			. '/bitrix/php_interface/a7_inventory_webhook.config.php';
		if (!is_readable($path)) {
			return false;
		}
		$cfg = include $path;
		return is_array($cfg) && !empty($cfg['enabled']);
	}

	/** Stage/category via get(); getStageId is magic __call and method_exists is false. */
	private static function itemStage(object $item): string
	{
		if (method_exists($item, 'get')) {
			return (string)($item->get('STAGE_ID') ?? '');
		}
		return '';
	}

	private static function itemCategory(object $item): int
	{
		if (method_exists($item, 'get')) {
			return (int)($item->get('CATEGORY_ID') ?? 0);
		}
		return 0;
	}

	public static function onAfterItem(\Bitrix\Main\Event $event): void
	{
		try {
			$item = $event->getParameter('item') ?? $event->getParameter('ITEM');
			if (!is_object($item) || !method_exists($item, 'getEntityTypeId')) {
				self::log('onAfterItem skip: no item');
				return;
			}
			$typeId = (int)$item->getEntityTypeId();
			$id = method_exists($item, 'getId') ? (int)$item->getId() : 0;
			$stage = self::itemStage($item);
			$category = self::itemCategory($item);
			if ($typeId !== self::TYPE) {
				return;
			}
			if (!self::enabled() || $id <= 0) {
				return;
			}
			if ($category === self::CATEGORY || isset(self::STAGES[$stage])) {
				self::post('update', $id, $stage);
			}
		} catch (\Throwable $e) {
			self::log('onAfterItem error: ' . $e->getMessage());
		}
	}

	/**
	 * Legacy &$arFields form, or Event (Compatible) — Bitrix spelling varies.
	 * @param mixed $arFields
	 */
	public static function onAfterItemLegacy($arFields = null): void
	{
		try {
			if ($arFields instanceof \Bitrix\Main\Event) {
				self::onAfterItem($arFields);
				return;
			}
			if (!self::enabled() || !is_array($arFields)) {
				return;
			}
			$id = (int)($arFields['ID'] ?? $arFields['id'] ?? 0);
			$stage = (string)($arFields['STAGE_ID'] ?? $arFields['stageId'] ?? '');
			$category = (int)($arFields['CATEGORY_ID'] ?? $arFields['categoryId'] ?? 0);
			$typeId = (int)($arFields['ENTITY_TYPE_ID'] ?? $arFields['entityTypeId'] ?? 0);
			if ($id <= 0) {
				return;
			}
			if ($typeId && $typeId !== self::TYPE) {
				return;
			}
			if ($category === self::CATEGORY || isset(self::STAGES[$stage])) {
				self::post('update', $id, $stage);
			}
		} catch (\Throwable $e) {
			self::log('onAfterItemLegacy error: ' . $e->getMessage());
		}
	}

	public static function post(string $event, int $id, string $stageId): void
	{
		$now = time();
		if (isset(self::$posted[$id]) && ($now - self::$posted[$id]) < 3) {
			return;
		}
		$secret = self::secret();
		if ($secret === '') {
			self::log('no secret');
			return;
		}
		$ts = (string)time();
		$body = json_encode([
			'event' => $event,
			'id' => $id,
			'stageId' => $stageId,
			'ts' => (int)$ts,
		], JSON_UNESCAPED_SLASHES);
		if ($body === false) {
			return;
		}
		$sign = hash_hmac('sha256', 'leadai-inventory.' . $ts . '.' . $body, $secret);
		$ctx = stream_context_create([
			'http' => [
				'method' => 'POST',
				'header' =>
					"Content-Type: application/json\r\n"
					. 'X-A7-Signature: ' . $sign . "\r\n"
					. 'X-A7-Ts: ' . $ts . "\r\n"
					. "Connection: close\r\n",
				'content' => $body,
				'timeout' => 3,
				'ignore_errors' => true,
			],
		]);
		$raw = @file_get_contents(self::URL, false, $ctx);
		$code = 0;
		if (isset($http_response_header[0]) && preg_match('/\s(\d{3})\s/', $http_response_header[0], $m)) {
			$code = (int)$m[1];
		}
		if ($code === 200) {
			self::$posted[$id] = $now;
		}
		self::log("post id={$id} stage={$stageId} http={$code} bytes=" . strlen((string)$raw));
	}

	private static function secret(): string
	{
		$path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www')
			. '/bitrix/php_interface/a7_lead_wa.config.php';
		if (!is_readable($path)) {
			return '';
		}
		$cfg = include $path;
		return trim((string)((is_array($cfg) ? $cfg : [])['secret'] ?? ''));
	}

	private static function log(string $line): void
	{
		@file_put_contents(
			'/home/bitrix/a7_inventory_webhook.log',
			date('c') . ' ' . $line . "\n",
			FILE_APPEND
		);
	}
}

A7InventoryWebhook::register();
