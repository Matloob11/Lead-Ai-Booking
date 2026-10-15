<?php
/**
 * C36 / Matloob yes: extend BP 235 stage-10 wipe skip from Bot Status 2477
 * to 2477 or 2478 (Handed to agent). Backup live template first. CLI only.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('NO_AGENT_CHECK', true);
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';

function say(string $l): void
{
    echo $l, "\n";
}

\Bitrix\Main\Loader::includeModule('bizproc');
$conn = \Bitrix\Main\Application::getConnection();

$row = $conn->query('SELECT TEMPLATE FROM b_bp_workflow_template WHERE ID=235')->fetch();
if (!is_array($row) || empty($row['TEMPLATE'])) {
    say('NO_TEMPLATE');
    exit(1);
}
$raw = (string)$row['TEMPLATE'];
$wasGz = strncmp($raw, "\x78", 1) === 0;
$plain = $wasGz ? gzuncompress($raw) : $raw;
if ($plain === false || $plain === '') {
    say('UNCOMPRESS_FAIL');
    exit(1);
}

$bakDir = '/home/bitrix/a7_bp235_bak_' . date('Ymd_His');
if (!@mkdir($bakDir, 0755, true) && !is_dir($bakDir)) {
    say('BAK_MKDIR_FAIL');
    exit(1);
}
file_put_contents($bakDir . '/template.bin', $raw);
say('BACKUP ' . $bakDir . '/template.bin bytes=' . strlen($raw));

$tpl = unserialize($plain);
if (!is_array($tpl) || !isset($tpl[0])) {
    say('UNSERIALIZE_FAIL');
    exit(1);
}

// Viewing booked (2477) and Handed to agent (2478) XML_IDs.
$xml2477 = '45e1733d47249547eca2bbf5253d2c2b';
$xml2478 = '576619e6f28f307d2a7841e1d525a197';
$found = 0;

function a7_c36_patch_skip(array &$node, string $xml2477, string $xml2478, int &$found): void
{
    $name = (string)($node['Name'] ?? '');
    if (($node['Type'] ?? '') === 'IfElseBranchActivity' && $name === 'A7C26SKIP2477') {
        $found++;
        $node['Properties']['Title'] = 'Bot Status Viewing booked or Handed to agent';
        // OR-chain: 2477 (=|contain) or 2478 (=|contain). Trailing flag 1 = OR.
        $node['Properties']['fieldcondition'] = [
            ['UF_CRM_A7_BOT_STATUS', '=', $xml2477, '0'],
            ['UF_CRM_A7_BOT_STATUS', 'contain', $xml2477, '1'],
            ['UF_CRM_A7_BOT_STATUS', '=', $xml2478, '1'],
            ['UF_CRM_A7_BOT_STATUS', 'contain', $xml2478, '1'],
        ];
        say('PATCHED A7C26SKIP2477 +2478');
        return;
    }
    if (!isset($node['Children']) || !is_array($node['Children'])) {
        return;
    }
    foreach (array_keys($node['Children']) as $k) {
        if (is_array($node['Children'][$k])) {
            a7_c36_patch_skip($node['Children'][$k], $xml2477, $xml2478, $found);
        }
    }
}

a7_c36_patch_skip($tpl[0], $xml2477, $xml2478, $found);
if ($found !== 1) {
    say('FOUND ' . $found . ' (expected 1 — is C26 skip live?)');
    exit(1);
}

$newPlain = serialize($tpl);
$stored = $wasGz ? gzcompress($newPlain) : $newPlain;
$conn->queryExecute(
    "UPDATE b_bp_workflow_template
     SET TEMPLATE=UNHEX('" . bin2hex($stored) . "'), MODIFIED=NOW(), IS_MODIFIED='Y'
     WHERE ID=235"
);
$again = (string)$conn->query('SELECT TEMPLATE FROM b_bp_workflow_template WHERE ID=235')->fetch()['TEMPLATE'];
$ap = (strncmp($again, "\x78", 1) === 0) ? gzuncompress($again) : $again;
say('HAS_2477 ' . (str_contains((string)$ap, $xml2477) ? 'yes' : 'no'));
say('HAS_2478 ' . (str_contains((string)$ap, $xml2478) ? 'yes' : 'no'));
say('HAS_MARKER ' . (str_contains((string)$ap, 'A7C26SKIP2477') ? 'yes' : 'no'));
if (function_exists('BXClearCache')) {
    BXClearCache(true);
}
say('OK');
