<?php
/**
 * A7 Stage Admin — require a shared admin password before any new CRM stage/status
 * can be created (kanban "+", CRM status settings, REST/StatusTable::add).
 *
 * Deploy:
 *   /home/bitrix/www/bitrix/php_interface/include/a7_stage_admin.php
 *   /home/bitrix/www/bitrix/php_interface/a7_stage_admin.config.php
 *   /home/bitrix/www/bitrix/js/a7_stage_admin.js
 * Loaded from init.php.
 */
declare(strict_types=1);

use Bitrix\Main\EventManager;
use Bitrix\Main\ORM\EntityError;
use Bitrix\Main\ORM\Event as OrmEvent;
use Bitrix\Main\ORM\EventResult as OrmEventResult;

if (defined('A7_STAGE_ADMIN_LOADED')) {
	return;
}
define('A7_STAGE_ADMIN_LOADED', true);

final class A7StageAdmin
{
	public const VERSION = '1.2.0';
	public const PARAM = 'a7_stage_admin_password';
	public const HEADER = 'HTTP_X_A7_STAGE_ADMIN_PASSWORD';
	public const JS_PATH = '/bitrix/js/a7_stage_admin.js';
	/** HR PAK 1156/1160/1168/1172 and HR UAE 1210/1212/1214/1216 */
	public const HR_TYPE_IDS = [1156, 1160, 1168, 1172, 1210, 1212, 1214, 1216];

	/** @var array|null */
	private static $cfg = null;

	/** @var bool|null */
	private static $allowed = null;

	public static function register(): void
	{
		$em = EventManager::getInstance();
		$em->addEventHandler('main', 'OnBeforeProlog', [self::class, 'onBeforeProlog']);
		$em->addEventHandler('main', 'OnProlog', [self::class, 'onProlog']);
		// ORM sends both "StatusOnBeforeAdd" and "Bitrix\Crm\Status::OnBeforeAdd".
		// The class is StatusTable; the entity name is Status. Register every spelling.
		foreach ([
			'\Bitrix\Crm\Status::OnBeforeAdd',
			'Bitrix\Crm\Status::OnBeforeAdd',
			'\Bitrix\Crm\StatusTable::OnBeforeAdd',
			'Bitrix\Crm\StatusTable::OnBeforeAdd',
			'StatusOnBeforeAdd',
		] as $eventName) {
			$em->addEventHandler('crm', $eventName, [self::class, 'onStatusBeforeAdd']);
		}
		$em->addEventHandler('crm', 'OnBeforeCrmStatusAdd', [self::class, 'onBeforeCrmStatusAdd']);
		$em->addEventHandler('main', 'OnEndBufferContent', [self::class, 'onEndBufferContent']);
	}

	public static function cfg(): array
	{
		if (self::$cfg !== null) {
			return self::$cfg;
		}
		$path = $_SERVER['DOCUMENT_ROOT'] . '/bitrix/php_interface/a7_stage_admin.config.php';
		$cfg = is_file($path) ? include $path : [];
		self::$cfg = is_array($cfg) ? $cfg : [];
		return self::$cfg;
	}

	public static function isBypassContext(): bool
	{
		if (defined('A7_STAGE_ADMIN_FORCE_WEB') && A7_STAGE_ADMIN_FORCE_WEB) {
			return false;
		}
		if (defined('A7_STAGE_ADMIN_BYPASS') && A7_STAGE_ADMIN_BYPASS) {
			return true;
		}
		if (PHP_SAPI === 'cli' || PHP_SAPI === 'phpdbg') {
			return true;
		}
		if (defined('BX_CRONTAB') && BX_CRONTAB) {
			return true;
		}
		return false;
	}

	public static function isPipelineStageEntity(string $entityId): bool
	{
		$entityId = trim($entityId);
		if ($entityId === '') {
			return false;
		}

		static $notStages = [
			'SOURCE' => true,
			'HONORIFIC' => true,
			'DEAL_TYPE' => true,
			'COMPANY_TYPE' => true,
			'CONTACT_TYPE' => true,
			'INDUSTRY' => true,
			'EMPLOYEES' => true,
			'CALL_LIST' => true,
			'EVENT_LIST' => true,
			'PRODUCT' => true,
		];
		if (isset($notStages[$entityId])) {
			return false;
		}

		if ($entityId === 'STATUS' || $entityId === 'QUOTE_STATUS') {
			return true;
		}
		if (str_starts_with($entityId, 'DEAL_STAGE')) {
			return true;
		}
		if (str_contains($entityId, '_STAGE_') || str_ends_with($entityId, '_STAGE')) {
			return true;
		}
		if (str_starts_with($entityId, 'SMART_INVOICE')) {
			return true;
		}

		return false;
	}

	public static function passwordFromRequest(): string
	{
		$pwd = '';
		if (isset($_REQUEST[self::PARAM]) && is_string($_REQUEST[self::PARAM])) {
			$pwd = (string)$_REQUEST[self::PARAM];
		}
		if ($pwd === '' && isset($_POST[self::PARAM]) && is_string($_POST[self::PARAM])) {
			$pwd = (string)$_POST[self::PARAM];
		}
		if ($pwd === '' && !empty($_SERVER[self::HEADER]) && is_string($_SERVER[self::HEADER])) {
			$pwd = (string)$_SERVER[self::HEADER];
		}
		// Some proxies expose custom headers differently
		if ($pwd === '' && !empty($_SERVER['REDIRECT_HTTP_X_A7_STAGE_ADMIN_PASSWORD'])) {
			$pwd = (string)$_SERVER['REDIRECT_HTTP_X_A7_STAGE_ADMIN_PASSWORD'];
		}
		return $pwd;
	}

	public static function verifyPassword(?string $password = null, ?string $entityId = null): bool
	{
		if (self::$allowed === true) {
			return true;
		}

		$pwd = $password;
		if ($pwd === null) {
			$pwd = self::passwordFromRequest();
		}

		// CLI / cron / explicit bypass may create system stages with no password.
		if ($pwd === '' && self::isBypassContext()) {
			self::$allowed = true;
			return true;
		}

		if ($entityId !== null && $entityId !== '' && self::userMaySkipPasswordForEntity($entityId)) {
			return true;
		}
		$typeId = self::entityTypeIdFromRequest();
		if ($typeId !== null && self::isHrTypeId($typeId) && self::isHrStageManager()) {
			return true;
		}
		if (self::isHrStageManager() && self::refererIsHrPage()) {
			return true;
		}

		if ($pwd === '') {
			return false;
		}

		$hash = (string)(self::cfg()['password_hash'] ?? '');
		if ($hash === '' || str_contains($hash, 'PLACEHOLDER')) {
			return false;
		}
		$ok = password_verify($pwd, $hash);
		if ($ok) {
			self::$allowed = true;
		}
		return $ok;
	}

	public static function denyMessage(bool $wrong = false): string
	{
		$cfg = self::cfg();
		if ($wrong) {
			return (string)($cfg['wrong_text'] ?? 'Incorrect admin password. New stage was not created.');
		}
		return (string)($cfg['error_text'] ?? 'Admin password required to create a new stage.');
	}

	/** ORM: block StatusTable::add for pipeline stages without password. */
	public static function onStatusBeforeAdd(OrmEvent $event): OrmEventResult
	{
		$result = new OrmEventResult();
		try {
			$fields = $event->getParameter('fields');
			if (!is_array($fields)) {
				return $result;
			}
			$entityId = (string)($fields['ENTITY_ID'] ?? '');
			if (!self::isPipelineStageEntity($entityId)) {
				return $result;
			}
			if (self::verifyPassword(null, $entityId)) {
				return $result;
			}
			$provided = self::passwordFromRequest() !== '';
			$result->addError(new EntityError(self::denyMessage($provided)));
		} catch (\Throwable $e) {
			$result->addError(new EntityError(self::denyMessage(false)));
		}
		return $result;
	}

	/** Legacy CCrmStatus::Add — return false to cancel. */
	public static function onBeforeCrmStatusAdd(&$fields)
	{
		try {
			if (!is_array($fields)) {
				return true;
			}
			$entityId = (string)($fields['ENTITY_ID'] ?? '');
			if (!self::isPipelineStageEntity($entityId)) {
				return true;
			}
			if (self::verifyPassword(null, $entityId)) {
				return true;
			}
			$provided = self::passwordFromRequest() !== '';
			global $APPLICATION;
			if (is_object($APPLICATION) && method_exists($APPLICATION, 'ThrowException')) {
				$APPLICATION->ThrowException(self::denyMessage($provided));
			}
			return false;
		} catch (\Throwable $e) {
			return false;
		}
	}

	/** Early AJAX / settings gate for clearer errors before Bitrix creates anything. */
	public static function onBeforeProlog(): void
	{
		try {
			if (self::isBypassContext()) {
				return;
			}
			if (self::isKanbanStageCreateRequest() || self::isStatusSettingsCreateRequest()) {
				if (self::verifyPassword(null, (string)($_REQUEST['ENTITY_ID'] ?? $_POST['ENTITY_ID'] ?? ''))) {
					return;
				}
				$provided = self::passwordFromRequest() !== '';
				self::abortJson(self::denyMessage($provided));
			}
		} catch (\Throwable $e) {
			// never break the portal
		}
	}

	public static function onProlog(): void
	{
		try {
			global $APPLICATION, $USER;
			if (!is_object($USER) || !$USER->IsAuthorized()) {
				return;
			}
			if (!self::wantsJs()) {
				return;
			}
			self::injectHead();
		} catch (\Throwable $e) {
			// ignore
		}
	}

	public static function onEndBufferContent(&$content): void
	{
		try {
			if (PHP_SAPI === 'cli' || !is_string($content) || $content === '' || !self::wantsJs()) {
				return;
			}
			if (stripos($content, 'a7_stage_admin.js') !== false) {
				return;
			}
			$pos = strripos($content, '</body>');
			if ($pos === false) {
				return;
			}
			$file = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
			$version = is_readable($file) ? (string)@filemtime($file) : (string)time();
			$cfgJs = json_encode(self::jsConfig(), JSON_UNESCAPED_UNICODE);
			$tag = '<script>window.A7_STAGE_ADMIN=' . $cfgJs . ';</script>'
				. '<script src="' . self::JS_PATH . '?v=' . $version . '"></script>';
			$content = substr($content, 0, $pos) . $tag . "\n" . substr($content, $pos);
		} catch (\Throwable $e) {
		}
	}

	/** @return list<int> */
	public static function hrTypeIds(): array
	{
		$fromCfg = self::cfg()['hr_entity_type_ids'] ?? null;
		if (is_array($fromCfg) && $fromCfg) {
			return array_values(array_unique(array_map('intval', $fromCfg)));
		}
		return self::HR_TYPE_IDS;
	}

	public static function isHrTypeId(int $typeId): bool
	{
		return $typeId > 0 && in_array($typeId, self::hrTypeIds(), true);
	}

	public static function isHrStageEntity(string $entityId): bool
	{
		if (preg_match('/DYNAMIC_(\d+)/', $entityId, $m)) {
			return self::isHrTypeId((int)$m[1]);
		}
		return false;
	}

	public static function isHrStageManager(): bool
	{
		$uid = self::currentUserId();
		if ($uid <= 0) {
			return false;
		}
		$email = strtolower(self::currentUserEmail());
		$managers = self::cfg()['hr_stage_managers'] ?? [];
		if (!is_array($managers)) {
			return false;
		}
		foreach ($managers as $row) {
			if (!is_array($row)) {
				continue;
			}
			if ((int)($row['id'] ?? 0) !== $uid) {
				continue;
			}
			$want = strtolower(trim((string)($row['email'] ?? '')));
			if ($want === '' || $want === $email) {
				return true;
			}
		}
		return false;
	}

	public static function userMaySkipPasswordForEntity(string $entityId): bool
	{
		return $entityId !== '' && self::isHrStageManager() && self::isHrStageEntity($entityId);
	}

	public static function entityTypeIdFromRequest(): ?int
	{
		foreach (['entityTypeId', 'entity_type_id', 'ENTITY_TYPE_ID', 'entityTypeID'] as $key) {
			if (isset($_REQUEST[$key]) && (int)$_REQUEST[$key] > 0) {
				return (int)$_REQUEST[$key];
			}
			if (isset($_POST[$key]) && (int)$_POST[$key] > 0) {
				return (int)$_POST[$key];
			}
		}
		foreach (['ENTITY_ID', 'entityId', 'statusEntityId'] as $key) {
			$raw = (string)($_REQUEST[$key] ?? $_POST[$key] ?? '');
			if (preg_match('/DYNAMIC_(\d+)/', $raw, $m)) {
				return (int)$m[1];
			}
		}
		return null;
	}

	private static function refererIsHrPage(): bool
	{
		$ref = (string)($_SERVER['HTTP_REFERER'] ?? '');
		if ($ref === '') {
			return false;
		}
		if (str_contains($ref, '/page/hr_pak/') || str_contains($ref, '/page/hr_uae/')) {
			return true;
		}
		return (bool)preg_match('#/type/(1156|1160|1168|1172|1210|1212|1214|1216)(?:/|$)#', $ref);
	}

	private static function currentUserId(): int
	{
		global $USER;
		if (is_object($USER) && method_exists($USER, 'GetID')) {
			return (int)$USER->GetID();
		}
		return 0;
	}

	private static function currentUserEmail(): string
	{
		global $USER;
		if (is_object($USER) && method_exists($USER, 'GetEmail')) {
			return trim((string)$USER->GetEmail());
		}
		return '';
	}

	private static function wantsJs(): bool
	{
		global $USER;
		if (!is_object($USER) || !$USER->IsAuthorized()) {
			return false;
		}
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		if (str_starts_with($uri, '/crm/') || str_contains($uri, '/page/hr_')) {
			return true;
		}
		if (preg_match('#/type/(1156|1160|1168|1172|1210|1212|1214|1216)(?:/|$)#', $uri)) {
			return true;
		}
		return false;
	}

	/** @return array<string, mixed> */
	private static function jsConfig(): array
	{
		$cfg = self::cfg();
		return [
			'param' => self::PARAM,
			'title' => (string)($cfg['prompt_title'] ?? 'Admin password required'),
			'text' => (string)($cfg['prompt_text'] ?? 'Enter admin password to create a new stage:'),
			'version' => self::VERSION,
			'bypassHr' => self::isHrStageManager(),
			'hrTypes' => self::hrTypeIds(),
		];
	}

	private static function injectHead(): void
	{
		global $APPLICATION;
		if (!is_object($APPLICATION) || !method_exists($APPLICATION, 'AddHeadScript')) {
			return;
		}
		$file = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
		$version = is_readable($file) ? (string)@filemtime($file) : (string)time();
		$APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . $version);
		if (method_exists($APPLICATION, 'AddHeadString')) {
			$APPLICATION->AddHeadString(
				'<script>window.A7_STAGE_ADMIN=' . json_encode(self::jsConfig(), JSON_UNESCAPED_UNICODE) . ';</script>',
				true
			);
		}
	}

	private static function isKanbanStageCreateRequest(): bool
	{
		$script = (string)($_SERVER['SCRIPT_NAME'] ?? '');
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		$hay = $script . ' ' . $uri;
		if (!preg_match('~/bitrix/components/bitrix/crm\.kanban/(ajax\.old\.php|ajax\.php)~i', $hay)
			&& !str_contains($hay, 'crm.kanban')) {
			// also match when action is only in query
			if (!preg_match('~/crm\.kanban/~i', $hay) && !str_contains($hay, '/crm.kanban/')) {
				return false;
			}
		}

		$action = (string)($_REQUEST['action'] ?? $_GET['action'] ?? $_POST['action'] ?? '');
		if ($action === '' && preg_match('/[?&]action=([^&]+)/', $uri, $m)) {
			$action = urldecode($m[1]);
		}
		$actionLower = strtolower($action);
		$isCreate = $action === 'modifyStage'
			|| str_contains($actionLower, 'addstage')
			|| str_contains($actionLower, 'createstage')
			|| str_contains($actionLower, 'stage.add')
			|| str_contains($actionLower, 'stage.create');
		if (!$isCreate) {
			return false;
		}

		$delete = $_REQUEST['delete'] ?? $_POST['delete'] ?? null;
		if ($delete === '1' || $delete === 1 || $delete === true || $delete === 'Y') {
			return false;
		}
		if (str_contains($actionLower, 'delete') || str_contains($actionLower, 'remove')) {
			return false;
		}
		// Rename, recolor, and reorder all send columnId. The "+" create does not.
		$columnId = $_REQUEST['columnId'] ?? $_POST['columnId'] ?? null;
		if ($columnId !== null && $columnId !== '' && $columnId !== '0' && $columnId !== 0) {
			return false;
		}
		return true;
	}

	private static function isStatusSettingsCreateRequest(): bool
	{
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		$script = (string)($_SERVER['SCRIPT_NAME'] ?? '');
		$hay = $script . ' ' . $uri;
		if (!preg_match('~/crm/configs/status~i', $hay) && !str_contains($hay, 'crm.config.status')) {
			return false;
		}
		if (strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'POST') {
			return false;
		}
		$list = $_POST['LIST'] ?? null;
		if (!is_array($list)) {
			return false;
		}
		foreach ($list as $entityRows) {
			if (!is_array($entityRows)) {
				continue;
			}
			// New rows are keyed like n0, n1… under ADD or directly
			foreach (['ADD', 'FIELDS', 'NEW'] as $bucket) {
				if (!isset($entityRows[$bucket]) || !is_array($entityRows[$bucket])) {
					continue;
				}
				foreach ($entityRows[$bucket] as $key => $_) {
					if (is_string($key) && str_starts_with($key, 'n')) {
						return true;
					}
				}
			}
			foreach ($entityRows as $key => $row) {
				if (is_string($key) && str_starts_with($key, 'n') && is_array($row)) {
					return true;
				}
			}
		}
		return false;
	}

	private static function abortJson(string $message): void
	{
		while (ob_get_level() > 0) {
			ob_end_clean();
		}
		header('Content-Type: application/json; charset=UTF-8');
		http_response_code(200);
		echo json_encode([
			'ERROR' => $message,
			'error' => $message,
			'fatal' => false,
			'a7_stage_admin' => true,
		], JSON_UNESCAPED_UNICODE);
		die();
	}
}

A7StageAdmin::register();
