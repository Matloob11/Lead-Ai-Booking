<?php
/**
 * Read-only probe: how crm.lead.details hands file user fields to CCrmLead::Update on save (the guard compares
 * them with the stored value). Prints the component's file-handling code around the two hits. Stub after use.
 *
 * Run: ops/bitrix.sh run a7_probe_guard_filesave.php
 */
$root = '/home/bitrix/www';
function say(string $line): void
{
    echo $line, "\n";
}
function show(string $path, array $ranges): void
{
    global $root;
    $lines = file($root . $path, FILE_IGNORE_NEW_LINES) ?: [];
    say('=== ' . $path);
    foreach ($ranges as [$from, $to]) {
        for ($i = max(1, $from); $i <= min(count($lines), $to); $i++) {
            say(sprintf('%5d: %s', $i, rtrim($lines[$i - 1])));
        }
        say('   ...');
    }
}
show('/bitrix/components/bitrix/crm.lead.details/class.php', [[1440, 1500], [1895, 1935]]);
$ajax = file($root . '/bitrix/components/bitrix/crm.lead.details/ajax.php', FILE_IGNORE_NEW_LINES) ?: [];
say('=== ajax.php lines mentioning user fields, files or the update call');
foreach ($ajax as $i => $line) {
    if (preg_match('~(USER_FIELD|GetUserFields|userField|_FILES|->Update\(|DISABLE_|REGISTER_SONET|prepareFields|UF_)~', $line)) {
        say(sprintf('%5d: %s', $i + 1, trim($line)));
    }
}
say('DONE');
