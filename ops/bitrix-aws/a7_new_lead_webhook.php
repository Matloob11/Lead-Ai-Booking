<?php
/**
 * C67 — New-lead outgoing webhook for Lead AI greet (round 22).
 *
 * On CRM lead CREATE (OnAfterCrmLeadAdd / Factory add / REST crm.lead.add),
 * POST signed JSON to Django:
 *   POST https://wa.srv1802669.hstgr.cloud/api/leadai/bitrix/new-lead/
 *   body  {"event":"add","id":<lead id>,"ts":<unix>}
 *   header X-A7-Signature = hex(hmac_sha256(secret, "leadai-newlead." + ts + "." + body))
 *   header X-A7-Ts
 * Secret = a7_lead_wa.config.php 'secret' (same as C46).
 *
 * DISABLED by default until Claude's "round 22 is live". Enable:
 *   in /bitrix/php_interface/a7_new_lead_webhook.config.php set 'enabled' => true
 *
 * Soft-fail: never blocks the CRM save. Log: /home/bitrix/a7_new_lead_webhook.log
 *
 * Deployed to: bitrix/php_interface/include/a7_new_lead_webhook.php
 * Wired from init.php (see a7_patch_init_new_lead_webhook.php).
 */
declare(strict_types=1);

if (defined('A7_NEW_LEAD_WEBHOOK_LOADED')) {
	return;
}
define('A7_NEW_LEAD_WEBHOOK_LOADED', true);

final class A7NewLeadWebhook
{
	public const VERSION = '1.0.0';
	public const URL = 'https://wa.srv1802669.hstgr.cloud/api/leadai/bitrix/new-lead/';

	/** @var array<int, int> lead id → unix ts of last post (dedupe dual handlers) */
	private static array $posted = [];

	public static function register(): void
	{
		try {
			$em = \Bitrix\Main\EventManager::getInstance();
			// Classic CRM lead add (UI, CCrmLead::Add, most REST paths).
			$em->addEventHandler('crm', 'OnAfterCrmLeadAdd', [self::class, 'onAfterLeadAdd']);
			$em->addEventHandler('crm', 'onAfterCrmLeadAdd', [self::class, 'onAfterLeadAdd']);
			// Factory Item path (some builds / CRM service).
			$em->addEventHandler('crm', 'onCrmDynamicItemAdd', [self::class, 'onFactoryAdd']);
			$em->addEventHandler('crm', 'OnCrmDynamicItemAdd', [self::class, 'onFactoryAdd']);
		} catch (\Throwable $e) {
			self::log('register error: ' . $e->getMessage());
		}
	}

	public static function enabled(): bool
	{
		$path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '/home/bitrix/www')
			. '/bitrix/php_interface/a7_new_lead_webhook.config.php';
		if (!is_readable($path)) {
			return false;
		}
		$cfg = include $path;
		return is_array($cfg) && !empty($cfg['enabled']);
	}

	/**
	 * @param mixed $arFields Event or &$fields array
	 */
	public static function onAfterLeadAdd($arFields = null): void
	{
		try {
			$id = 0;
			if ($arFields instanceof \Bitrix\Main\Event) {
				$id = (int)($arFields->getParameter('id')
					?? $arFields->getParameter('ID')
					?? 0);
				$fields = $arFields->getParameter('fields')
					?? $arFields->getParameter('FIELDS');
				if ($id <= 0 && is_array($fields)) {
					$id = (int)($fields['ID'] ?? $fields['id'] ?? 0);
				}
			} elseif (is_array($arFields)) {
				$id = (int)($arFields['ID'] ?? $arFields['id'] ?? 0);
			}
			if ($id <= 0) {
				self::log('onAfterLeadAdd skip: no id');
				return;
			}
			self::maybePost($id, 'OnAfterCrmLeadAdd');
		} catch (\Throwable $e) {
			self::log('onAfterLeadAdd error: ' . $e->getMessage());
		}
	}

	public static function onFactoryAdd(\Bitrix\Main\Event $event): void
	{
		try {
			$item = $event->getParameter('item') ?? $event->getParameter('ITEM');
			if (!is_object($item) || !method_exists($item, 'getEntityTypeId')) {
				return;
			}
			// Lead entity type id = 1
			if ((int)$item->getEntityTypeId() !== 1) {
				return;
			}
			$id = method_exists($item, 'getId') ? (int)$item->getId() : 0;
			if ($id <= 0) {
				return;
			}
			self::maybePost($id, 'FactoryAdd');
		} catch (\Throwable $e) {
			self::log('onFactoryAdd error: ' . $e->getMessage());
		}
	}

	public static function maybePost(int $id, string $via): void
	{
		if (!self::enabled()) {
			self::log("skip disabled id={$id} via={$via}");
			return;
		}
		self::post($id, $via);
	}

	public static function post(int $id, string $via = ''): void
	{
		$now = time();
		if (isset(self::$posted[$id]) && ($now - self::$posted[$id]) < 3) {
			self::log("dedupe id={$id} via={$via}");
			return;
		}
		$secret = self::secret();
		if ($secret === '') {
			self::log("no secret id={$id}");
			return;
		}
		$ts = (string)time();
		$body = json_encode([
			'event' => 'add',
			'id' => $id,
			'ts' => (int)$ts,
		], JSON_UNESCAPED_SLASHES);
		if ($body === false) {
			return;
		}
		$sign = hash_hmac('sha256', 'leadai-newlead.' . $ts . '.' . $body, $secret);
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
		$viaBit = $via !== '' ? " via={$via}" : '';
		self::log("post id={$id} http={$code} bytes=" . strlen((string)$raw) . $viaBit);
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
			'/home/bitrix/a7_new_lead_webhook.log',
			date('c') . ' ' . $line . "\n",
			FILE_APPEND
		);
	}
}

A7NewLeadWebhook::register();
