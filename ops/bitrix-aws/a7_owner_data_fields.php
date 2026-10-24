<?php
/**
 * A7 Owner Data Fields — on SPA 1042 *details cards* only:
 * admin password for Create field, Select field, Hide field, Delete section.
 * Field values and field settings stay free. Kanban/list are untouched.
 *
 * Deploy:
 *   /home/bitrix/www/bitrix/php_interface/include/a7_owner_data_fields.php
 *   /home/bitrix/www/bitrix/js/a7_owner_data_fields.js
 *   /home/bitrix/www/bitrix/css/a7_owner_data_fields.css
 * Loaded from init.php.
 */
declare(strict_types=1);

use Bitrix\Main\EventManager;

if (defined('A7_OWNER_DATA_FIELDS_LOADED')) {
	return;
}
define('A7_OWNER_DATA_FIELDS_LOADED', true);

final class A7OwnerDataFields
{
	public const VERSION = '1.1.0';
	public const ENTITY_ID = 'CRM_5';
	public const TYPE_ID = 1042;
	public const PARAM = 'a7_stage_admin_password';
	public const HEADER = 'HTTP_X_A7_STAGE_ADMIN_PASSWORD';
	public const JS_PATH = '/bitrix/js/a7_owner_data_fields.js';
	public const CSS_PATH = '/bitrix/css/a7_owner_data_fields.css';

	/** @var bool|null */
	private static $allowed = null;

	public static function register(): void
	{
		$em = EventManager::getInstance();
		$em->addEventHandler('main', 'OnBeforeProlog', [self::class, 'onBeforeProlog']);
		$em->addEventHandler('main', 'OnProlog', [self::class, 'onProlog']);
		// Create field only — Update (settings) and Delete UF stay free per Matloob.
		$em->addEventHandler('main', 'OnBeforeUserTypeAdd', [self::class, 'onBeforeUserTypeAdd']);
		$em->addEventHandler('main', 'OnEndBufferContent', [self::class, 'onEndBufferContent']);
	}

	public static function onBeforeUserTypeAdd(&$arFields)
	{
		try {
			if (!is_array($arFields)) {
				return true;
			}
			$entityId = (string)($arFields['ENTITY_ID'] ?? '');
			if (!self::isOwnerEntity($entityId)) {
				return true;
			}
			if (self::verifyPassword()) {
				return true;
			}
			$provided = self::passwordFromRequest() !== '';
			global $APPLICATION;
			if (is_object($APPLICATION) && method_exists($APPLICATION, 'ThrowException')) {
				$APPLICATION->ThrowException(self::denyMessage($provided, 'create'));
			}
			return false;
		} catch (\Throwable $e) {
			return false;
		}
	}

	public static function onBeforeProlog(): void
	{
		try {
			if (self::isBypassContext()) {
				return;
			}
			if (!self::isLockedFieldRequest()) {
				return;
			}
			if (self::verifyPassword()) {
				return;
			}
			$provided = self::passwordFromRequest() !== '';
			$kind = self::requestKind();
			self::abortJson(self::denyMessage($provided, $kind));
		} catch (\Throwable $e) {
		}
	}

	public static function onProlog(): void
	{
		try {
			global $USER;
			if (!is_object($USER) || !$USER->IsAuthorized()) {
				return;
			}
			if (!self::wantsPageJs()) {
				return;
			}
			self::injectAssets();
		} catch (\Throwable $e) {
		}
	}

	public static function onEndBufferContent(&$content): void
	{
		try {
			if (PHP_SAPI === 'cli' || !is_string($content) || $content === '' || !self::wantsPageJs()) {
				return;
			}
			if (stripos($content, 'a7_owner_data_fields.js') !== false) {
				return;
			}
			$pos = strripos($content, '</body>');
			if ($pos === false) {
				return;
			}
			$boot = self::bootPayload();
			$jsFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
			$cssFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::CSS_PATH;
			$jsV = is_readable($jsFile) ? (string)@filemtime($jsFile) : (string)time();
			$cssV = is_readable($cssFile) ? (string)@filemtime($cssFile) : (string)time();
			$tag = '<link rel="stylesheet" href="' . self::CSS_PATH . '?v=' . $cssV . '">'
				. '<script>window.A7_OWNER_DATA_FIELDS=' . json_encode($boot, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . ';</script>'
				. '<script src="' . self::JS_PATH . '?v=' . $jsV . '"></script>';
			$content = substr($content, 0, $pos) . $tag . "\n" . substr($content, $pos);
		} catch (\Throwable $e) {
		}
	}

	/** @return array<string,mixed> */
	public static function bootPayload(): array
	{
		return [
			'ok' => true,
			'version' => self::VERSION,
			'entityId' => self::ENTITY_ID,
			'typeId' => self::TYPE_ID,
			'lockFields' => true,
			'param' => self::PARAM,
			'title' => 'Admin password required',
			'text' => 'Enter admin password to Select field, Create field, Hide field, or Delete section:',
		];
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
		if ($pwd === '' && !empty($_SERVER['REDIRECT_HTTP_X_A7_STAGE_ADMIN_PASSWORD'])) {
			$pwd = (string)$_SERVER['REDIRECT_HTTP_X_A7_STAGE_ADMIN_PASSWORD'];
		}
		return $pwd;
	}

	public static function verifyPassword(?string $password = null): bool
	{
		if (self::$allowed === true) {
			return true;
		}
		$pwd = $password ?? self::passwordFromRequest();
		if ($pwd === '' && self::isBypassContext()) {
			self::$allowed = true;
			return true;
		}
		if ($pwd === '') {
			return false;
		}
		$hash = self::passwordHash();
		if ($hash === '' || str_contains($hash, 'PLACEHOLDER')) {
			return false;
		}
		$ok = password_verify($pwd, $hash);
		if ($ok) {
			self::$allowed = true;
		}
		return $ok;
	}

	public static function denyMessage(bool $wrong = false, string $kind = 'select'): string
	{
		$verb = match ($kind) {
			'create' => 'create a new field',
			'section' => 'delete a section',
			'select' => 'select or hide fields',
			default => 'change the Owner Data field layout',
		};
		if ($wrong) {
			return 'Incorrect admin password. Could not ' . $verb . '.';
		}
		return 'Admin password required to ' . $verb . '.';
	}

	public static function isBypassContext(): bool
	{
		if (defined('A7_OWNER_DATA_FIELDS_FORCE_WEB') && A7_OWNER_DATA_FIELDS_FORCE_WEB) {
			return false;
		}
		if (defined('A7_OWNER_DATA_FIELDS_BYPASS') && A7_OWNER_DATA_FIELDS_BYPASS) {
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

	public static function isOwnerEntity(string $entityId): bool
	{
		return strtoupper(trim($entityId)) === self::ENTITY_ID;
	}

	private static function passwordHash(): string
	{
		$path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_stage_admin.config.php';
		$cfg = is_file($path) ? include $path : [];
		if (!is_array($cfg)) {
			return '';
		}
		return (string)($cfg['password_hash'] ?? '');
	}

	/** JS only on details cards (and kanban host so SidePanel details still get the script). */
	private static function wantsPageJs(): bool
	{
		global $USER;
		if (!is_object($USER) || !$USER->IsAuthorized()) {
			return false;
		}
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		return (bool)preg_match('#/crm/type/1042/#i', $uri);
	}

	private static function injectAssets(): void
	{
		global $APPLICATION;
		if (!is_object($APPLICATION)) {
			return;
		}
		$boot = self::bootPayload();
		$jsFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::JS_PATH;
		$cssFile = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . self::CSS_PATH;
		$jsV = is_readable($jsFile) ? (string)@filemtime($jsFile) : (string)time();
		$cssV = is_readable($cssFile) ? (string)@filemtime($cssFile) : (string)time();
		if (method_exists($APPLICATION, 'SetAdditionalCSS')) {
			$APPLICATION->SetAdditionalCSS(self::CSS_PATH . '?v=' . $cssV);
		}
		if (method_exists($APPLICATION, 'AddHeadString')) {
			$APPLICATION->AddHeadString(
				'<script>window.A7_OWNER_DATA_FIELDS=' . json_encode($boot, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . ';</script>',
				true
			);
		}
		if (method_exists($APPLICATION, 'AddHeadScript')) {
			$APPLICATION->AddHeadScript(self::JS_PATH . '?v=' . $jsV);
		}
	}

	private static function isLockedFieldRequest(): bool
	{
		$method = strtoupper((string)($_SERVER['REQUEST_METHOD'] ?? 'GET'));
		if ($method !== 'POST') {
			return false;
		}
		$kind = self::requestKind();
		if ($kind === '') {
			return false;
		}
		return self::requestTargetsOwnerDataCard();
	}

	/**
	 * Locked AJAX kinds: create field, or card layout save (select / hide / delete section).
	 * Field settings update is NOT locked.
	 */
	private static function requestKind(): string
	{
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		$script = (string)($_SERVER['SCRIPT_NAME'] ?? '');
		$hay = strtolower($script . ' ' . $uri);
		$action = strtolower((string)($_REQUEST['action'] ?? $_POST['action'] ?? ''));
		if ($action === '' && preg_match('/[?&]action=([^&]+)/i', $uri, $m)) {
			$action = strtolower(urldecode($m[1]));
		}

		if (
			str_contains($action, 'userfieldconfig.add')
			|| str_contains($action, 'userfield.add')
			|| str_contains($action, 'user.type.add')
			|| (str_contains($hay, 'userfieldconfig') && str_contains($hay, 'add') && !str_contains($hay, 'update'))
		) {
			return 'create';
		}

		// Layout only — not userfieldconfig.update (field settings stay free).
		if (
			str_contains($action, 'entityeditor')
			|| str_contains($action, 'entity.editor')
			|| str_contains($action, 'entityform')
			|| str_contains($action, 'entity.form')
			|| str_contains($action, 'formconfiguration')
			|| str_contains($action, 'editorconfig')
			|| str_contains($action, 'ui.entityeditor')
		) {
			if (
				str_contains($action, 'get')
				|| str_contains($action, 'list')
				|| str_contains($action, 'load')
				|| str_contains($action, 'fetch')
			) {
				return '';
			}
			if (
				str_contains($action, 'set')
				|| str_contains($action, 'save')
				|| str_contains($action, 'update')
				|| str_contains($action, 'reset')
				|| str_contains($action, 'delete')
				|| str_contains($action, 'add')
			) {
				return 'select';
			}
		}
		return '';
	}

	private static function requestTargetsOwnerDataCard(): bool
	{
		$entity = self::entityFromRequest();
		if ($entity !== '' && !self::isOwnerEntity($entity)) {
			return false;
		}
		$typeId = self::typeIdFromRequest();
		if ($typeId > 0 && $typeId !== self::TYPE_ID) {
			return false;
		}
		$ref = (string)($_SERVER['HTTP_REFERER'] ?? '');
		$uri = (string)($_SERVER['REQUEST_URI'] ?? '');
		// Prefer details cards; still allow if entity/type clearly CRM_5 / 1042.
		if (preg_match('#/crm/type/1042/details/#i', $ref) || preg_match('#/crm/type/1042/details/#i', $uri)) {
			return true;
		}
		if (self::isOwnerEntity($entity) || $typeId === self::TYPE_ID) {
			return true;
		}
		return false;
	}

	private static function entityFromRequest(): string
	{
		$candidates = [];
		foreach (['ENTITY_ID', 'entityId', 'entity_id'] as $key) {
			if (isset($_REQUEST[$key]) && is_string($_REQUEST[$key])) {
				$candidates[] = (string)$_REQUEST[$key];
			}
			if (isset($_POST[$key]) && is_string($_POST[$key])) {
				$candidates[] = (string)$_POST[$key];
			}
		}
		foreach (['field', 'fields', 'data', 'params'] as $bag) {
			if (!isset($_REQUEST[$bag]) || !is_array($_REQUEST[$bag])) {
				continue;
			}
			$arr = $_REQUEST[$bag];
			foreach (['ENTITY_ID', 'entityId', 'entity_id'] as $key) {
				if (isset($arr[$key]) && is_string($arr[$key])) {
					$candidates[] = (string)$arr[$key];
				}
			}
			if (isset($arr['field']) && is_array($arr['field'])) {
				foreach (['ENTITY_ID', 'entityId'] as $key) {
					if (isset($arr['field'][$key]) && is_string($arr['field'][$key])) {
						$candidates[] = (string)$arr['field'][$key];
					}
				}
			}
		}
		foreach ($candidates as $c) {
			$c = strtoupper(trim($c));
			if ($c === self::ENTITY_ID || str_starts_with($c, 'CRM_')) {
				return $c;
			}
		}
		return '';
	}

	private static function typeIdFromRequest(): int
	{
		foreach (['entityTypeId', 'ENTITY_TYPE_ID', 'entityTypeID', 'typeId', 'TYPE_ID'] as $key) {
			if (isset($_REQUEST[$key]) && is_numeric($_REQUEST[$key])) {
				return (int)$_REQUEST[$key];
			}
			if (isset($_POST[$key]) && is_numeric($_POST[$key])) {
				return (int)$_POST[$key];
			}
		}
		foreach (['data', 'params', 'fields'] as $bag) {
			if (!isset($_REQUEST[$bag]) || !is_array($_REQUEST[$bag])) {
				continue;
			}
			foreach (['entityTypeId', 'ENTITY_TYPE_ID', 'typeId'] as $key) {
				if (isset($_REQUEST[$bag][$key]) && is_numeric($_REQUEST[$bag][$key])) {
					return (int)$_REQUEST[$bag][$key];
				}
			}
		}
		$ref = (string)($_SERVER['HTTP_REFERER'] ?? '');
		if (preg_match('#/crm/type/(\d+)/#i', $ref, $m)) {
			return (int)$m[1];
		}
		return 0;
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
			'status' => 'error',
			'errors' => [['message' => $message]],
			'a7_owner_data_fields' => true,
		], JSON_UNESCAPED_UNICODE);
		die();
	}
}

if (class_exists(EventManager::class)) {
	A7OwnerDataFields::register();
}
