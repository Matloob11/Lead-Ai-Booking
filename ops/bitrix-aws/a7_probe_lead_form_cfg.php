<?php
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('ui');

$conn = \Bitrix\Main\Application::getConnection();
$res = $conn->query(
	"SELECT ID, CATEGORY, ENTITY_TYPE_ID, NAME, COMMON, OPTION_CATEGORY, LENGTH(CONFIG) AS len
	 FROM b_ui_entity_editor_config
	 WHERE ENTITY_TYPE_ID IN ('1','LEAD','CRM_LEAD')
	    OR NAME LIKE '%lead%'
	    OR CATEGORY LIKE '%lead%'
	 ORDER BY ID DESC LIMIT 50"
);
echo "=== rows ===\n";
$rows = [];
while ($row = $res->fetch()) {
	$rows[] = $row;
	echo json_encode($row, JSON_UNESCAPED_UNICODE), "\n";
}

function dumpConfig(string $label, string $json): void
{
	echo "\n=== $label ===\n";
	$cfg = json_decode($json, true);
	if (!is_array($cfg)) {
		echo "not json head=", substr($json, 0, 200), "\n";
		return;
	}
	$sections = $cfg;
	if (isset($cfg[0]) && is_array($cfg[0])) {
		$sections = $cfg;
	} elseif (isset($cfg['data']) && is_array($cfg['data'])) {
		$sections = $cfg['data'];
	} else {
		echo "keys=", implode(',', array_keys($cfg)), "\n";
		return;
	}
	foreach ($sections as $sec) {
		if (!is_array($sec)) {
			continue;
		}
		$title = $sec['title'] ?? $sec['name'] ?? '?';
		$names = [];
		foreach ($sec['elements'] ?? [] as $e) {
			if (is_array($e) && isset($e['name'])) {
				$names[] = $e['name'];
			} elseif (is_string($e)) {
				$names[] = $e;
			}
		}
		echo "SEC [$title] ", implode(', ', $names), "\n";
	}
}

// Prefer common configs
foreach ($rows as $row) {
	if (($row['COMMON'] ?? '') === 'Y' || stripos((string)$row['NAME'], 'lead_details') !== false) {
		$full = $conn->query("SELECT CONFIG FROM b_ui_entity_editor_config WHERE ID=" . (int)$row['ID'])->fetch();
		dumpConfig('ID ' . $row['ID'] . ' ' . $row['NAME'] . ' common=' . $row['COMMON'], (string)$full['CONFIG']);
	}
}

// Also try REST-style internal API
if (class_exists(\CCrmEntityConfigurationManager::class) || true) {
	try {
		if (!function_exists('restCommand') && class_exists(\Bitrix\Crm\Integration\Rest\AppPlacementManager::class)) {
			// skip
		}
	} catch (\Throwable $e) {
	}
}

// Bitrix\Crm\Entity\EntityEditorConfig or similar
foreach ([
	'Bitrix\\Crm\\Component\\EntityDetails\\Config\\Scope',
	'Bitrix\\Ui\\EntityForm\\Scope',
	'Bitrix\\Crm\\Entity\\EntityEditorConfig',
] as $cls) {
	echo class_exists($cls) ? "class $cls YES\n" : "class $cls no\n";
}
