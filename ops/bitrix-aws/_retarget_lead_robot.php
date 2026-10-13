<?php
/**
 * Point the NEW-stage lead robot off n8n and onto Official leadbot.
 * Backup first. Walk the inflated template so serialized string lengths stay valid.
 */
$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);
$m->set_charset('utf8mb4');

const TEMPLATE_ID = 6;
const NEW_URL = 'https://crm.a7grouprealestatedxb.com/bitrix/tools/a7_leadbot_outreach.php?lead_id={=Document:ID}';

function inflate(string $raw): string
{
    $try = @gzuncompress($raw);
    return $try === false ? $raw : $try;
}

function deflate(string $raw): string
{
    return gzcompress($raw, 9);
}

function rewrite($node, int &$hits): mixed
{
    if (is_string($node)) {
        if (str_contains($node, 'n8n.srv1802669.hstgr.cloud/webhook/a7-bitrix-lead-outreach')) {
            $hits++;
            return NEW_URL;
        }
        return $node;
    }
    if (is_array($node)) {
        foreach ($node as $k => $v) {
            $node[$k] = rewrite($v, $hits);
        }
    }
    return $node;
}

$q = $m->query('SELECT ID, NAME, ACTIVE, TEMPLATE FROM b_bp_workflow_template WHERE ID=' . TEMPLATE_ID);
$row = $q->fetch_assoc();
if (!$row) {
    fwrite(STDERR, "template missing\n");
    exit(1);
}

$plain = inflate($row['TEMPLATE']);
$data = @unserialize($plain, ['allowed_classes' => false]);
if (!is_array($data)) {
    fwrite(STDERR, "template is not a PHP array\n");
    exit(1);
}

$backup = '/home/ec2-user/bp-template-6-' . gmdate('YmdHis') . '.bin';
if (file_put_contents($backup, $row['TEMPLATE']) === false) {
    fwrite(STDERR, "backup failed\n");
    exit(1);
}
chown($backup, 'ec2-user');

$hits = 0;
$data = rewrite($data, $hits);
if ($hits !== 1) {
    fwrite(STDERR, "expected 1 n8n url, found $hits\n");
    exit(1);
}

$packed = deflate(serialize($data));
$id = TEMPLATE_ID;
$stmt = $m->prepare('UPDATE b_bp_workflow_template SET TEMPLATE=? WHERE ID=?');
$stmt->bind_param('si', $packed, $id);
$stmt->execute();
if ($stmt->affected_rows < 1 && $stmt->errno) {
    fwrite(STDERR, $stmt->error . "\n");
    exit(1);
}

$check = $m->query('SELECT TEMPLATE FROM b_bp_workflow_template WHERE ID=' . TEMPLATE_ID)->fetch_assoc();
$again = unserialize(inflate($check['TEMPLATE']), ['allowed_classes' => false]);
$hits2 = 0;
rewrite($again, $hits2);
$flat = json_encode($again);
$ok = str_contains($flat, 'a7_leadbot_outreach.php') && !str_contains($flat, 'a7-bitrix-lead-outreach');
echo $ok ? "PROOF_OK hits_replaced=1 backup=$backup\n" : "PROOF_FAIL\n";
if (!$ok) {
    exit(1);
}
