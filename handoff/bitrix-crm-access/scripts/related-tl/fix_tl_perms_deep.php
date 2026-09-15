<?php
/**
 * Deep-fix Team Leader (role 54) access for all 3 heads:
 * - READ: department only (ATTR=D) for LEAD + Owner Data
 * - WRITE/ADD: self only (ATTR=A)
 * - Clear CRM permission caches
 * - Verify Hassan can read team item, cannot read outsider item
 */
$_SERVER['DOCUMENT_ROOT'] = '/home/bitrix/www';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
require '/home/bitrix/www/bitrix/modules/main/include/prolog_before.php';
\Bitrix\Main\Loader::includeModule('crm');
\Bitrix\Main\Loader::includeModule('intranet');

$s = include '/home/bitrix/www/bitrix/.settings.php';
$db = $s['connections']['value']['default'];
$m = new mysqli($db['host'], $db['login'], $db['password'], $db['database']);

// Classic Bitrix ATTR codes:
// A=SELF, D=DEPARTMENT, F=SUBDEPARTMENT, O=OPEN, X=ALL
$entities = [
    'LEAD',
    'DYNAMIC_1042',
    'DYNAMIC_1042_C13',
    'DYNAMIC_1042_C14',
];

function upsertPerm(mysqli $m, string $entity, string $ptype, string $attr, string $settings): void
{
    // Remove ALL rows for this entity/perm on role 54 (including STAGE_ID field rows that force SELF/ALL)
    if ($ptype === 'READ' || $ptype === 'WRITE') {
        // Keep stage-level rows but force same attr/settings for FIELD=STAGE_ID too
        $q = $m->query(
            "SELECT ID, FIELD, FIELD_VALUE FROM b_crm_role_perms
             WHERE ROLE_ID=54 AND ENTITY='" . $m->real_escape_string($entity) . "'
               AND PERM_TYPE='" . $m->real_escape_string($ptype) . "'"
        );
        $foundDash = false;
        while ($r = $q->fetch_assoc()) {
            if ($r['FIELD'] === '-' || $r['FIELD'] === '' || $r['FIELD'] === null) {
                $m->query(
                    "UPDATE b_crm_role_perms
                     SET ATTR='" . $m->real_escape_string($attr) . "',
                         SETTINGS='" . $m->real_escape_string($settings) . "',
                         FIELD='-', FIELD_VALUE=NULL
                     WHERE ID=" . (int) $r['ID']
                );
                if ($foundDash) {
                    $m->query('DELETE FROM b_crm_role_perms WHERE ID=' . (int) $r['ID']);
                    echo "del dup $entity $ptype {$r['ID']}\n";
                } else {
                    $foundDash = true;
                    echo "upd $entity $ptype id={$r['ID']} ATTR=$attr\n";
                }
            } else {
                // STAGE_ID etc — align to same attr so stages don't widen/narrow wrongly
                $m->query(
                    "UPDATE b_crm_role_perms
                     SET ATTR='" . $m->real_escape_string($attr) . "',
                         SETTINGS='" . $m->real_escape_string($settings) . "'
                     WHERE ID=" . (int) $r['ID']
                );
                echo "upd field {$r['FIELD']}={$r['FIELD_VALUE']} $entity $ptype ATTR=$attr\n";
            }
        }
        if (!$foundDash) {
            $m->query(
                "INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS)
                 VALUES (54, '" . $m->real_escape_string($entity) . "', '-', NULL,
                 '" . $m->real_escape_string($ptype) . "',
                 '" . $m->real_escape_string($attr) . "',
                 '" . $m->real_escape_string($settings) . "')"
            );
            echo "ins $entity $ptype ATTR=$attr\n";
        }
        return;
    }

    // ADD / EXPORT
    $q = $m->query(
        "SELECT ID FROM b_crm_role_perms WHERE ROLE_ID=54 AND ENTITY='" . $m->real_escape_string($entity) . "'
         AND PERM_TYPE='" . $m->real_escape_string($ptype) . "' AND (FIELD='-' OR FIELD='' OR FIELD IS NULL)"
    );
    $ids = [];
    while ($r = $q->fetch_assoc()) {
        $ids[] = (int) $r['ID'];
    }
    if ($ids) {
        $keep = $ids[0];
        $m->query(
            "UPDATE b_crm_role_perms SET ATTR='" . $m->real_escape_string($attr) . "',
             SETTINGS='" . $m->real_escape_string($settings) . "', FIELD='-', FIELD_VALUE=NULL WHERE ID=$keep"
        );
        for ($i = 1; $i < count($ids); $i++) {
            $m->query('DELETE FROM b_crm_role_perms WHERE ID=' . $ids[$i]);
        }
        echo "upd $entity $ptype ATTR=$attr\n";
    } else {
        $m->query(
            "INSERT INTO b_crm_role_perms (ROLE_ID, ENTITY, FIELD, FIELD_VALUE, PERM_TYPE, ATTR, SETTINGS)
             VALUES (54, '" . $m->real_escape_string($entity) . "', '-', NULL,
             '" . $m->real_escape_string($ptype) . "',
             '" . $m->real_escape_string($attr) . "',
             '" . $m->real_escape_string($settings) . "')"
        );
        echo "ins $entity $ptype ATTR=$attr\n";
    }
}

$readSettings = '["SELF","DEPARTMENT","SUBDEPARTMENTS"]';
$writeSettings = '["SELF"]';

foreach ($entities as $entity) {
    upsertPerm($m, $entity, 'READ', 'D', $readSettings);   // department
    upsertPerm($m, $entity, 'WRITE', 'A', $writeSettings); // self only
    upsertPerm($m, $entity, 'ADD', 'A', $writeSettings);
    upsertPerm($m, $entity, 'EXPORT', 'D', $readSettings);
}

// Ensure all 3 heads on role 54
foreach ([2560, 2551, 2297] as $uid) {
    $rel = 'U' . $uid;
    $ex = $m->query("SELECT ID FROM b_crm_role_relation WHERE ROLE_ID=54 AND RELATION='" . $m->real_escape_string($rel) . "'")->fetch_assoc();
    if (!$ex) {
        $m->query("INSERT INTO b_crm_role_relation (ROLE_ID, RELATION) VALUES (54, '" . $m->real_escape_string($rel) . "')");
        echo "bound $rel\n";
    } else {
        echo "bound ok $rel\n";
    }
    if (method_exists('CCrmPerms', 'ClearUserCache')) {
        CCrmPerms::ClearUserCache($uid);
    }
}

// Clear crm perms cache files if any
$cacheDirs = [
    '/home/bitrix/www/bitrix/cache/crm',
    '/home/bitrix/www/bitrix/managed_cache/MYSQL/crm',
];
foreach ($cacheDirs as $dir) {
    if (!is_dir($dir)) {
        continue;
    }
    echo "cache dir $dir\n";
}

echo "=== verify role54 attrs ===\n";
$q = $m->query(
    "SELECT ENTITY, FIELD, PERM_TYPE, ATTR, LEFT(SETTINGS,80) S FROM b_crm_role_perms
     WHERE ROLE_ID=54 AND (ENTITY='LEAD' OR ENTITY LIKE 'DYNAMIC_1042%')
       AND PERM_TYPE IN ('READ','WRITE','ADD','EXPORT') AND FIELD='-'
     ORDER BY ENTITY, PERM_TYPE"
);
while ($r = $q->fetch_assoc()) {
    echo json_encode($r) . "\n";
}

// Functional checks as Hassan
global $USER;
$USER = new CUser();
$USER->Authorize(2560);

$factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(1042);
$up = \Bitrix\Crm\Service\Container::getInstance()->getUserPermissions(2560);

// Team item (Ruqia 2303)
$teamItem = $factory->getItem(89463);
// Find an outsider Owner Data item (not in Hassan team)
$outQ = $m->query(
    "SELECT ID, ASSIGNED_BY_ID FROM b_crm_dynamic_items_1042
     WHERE CATEGORY_ID=13 AND ASSIGNED_BY_ID NOT IN (2560,2380,2344,2434,2291,2378,2376,2379,2303)
     ORDER BY ID DESC LIMIT 1"
);
$outRow = $outQ->fetch_assoc();
$outItem = $outRow ? $factory->getItem((int) $outRow['ID']) : null;

echo "=== Hassan Owner Data ===\n";
echo "perms C13 READ=" . var_export((new CCrmPerms(2560))->GetPermType('DYNAMIC_1042_C13', 'READ'), true) . "\n";
echo "perms LEAD READ=" . var_export((new CCrmPerms(2560))->GetPermType('LEAD', 'READ'), true) . "\n";
echo "perms LEAD WRITE=" . var_export((new CCrmPerms(2560))->GetPermType('LEAD', 'WRITE'), true) . "\n";
if ($teamItem) {
    echo "team item {$teamItem->getId()} assigned={$teamItem->getAssignedById()} canRead=" . ($up->canReadItem($teamItem) ? 'Y' : 'N') . " canUpdate=" . ($up->canUpdateItem($teamItem) ? 'Y' : 'N') . "\n";
}
if ($outItem) {
    echo "out item {$outItem->getId()} assigned={$outItem->getAssignedById()} canRead=" . ($up->canReadItem($outItem) ? 'Y' : 'N') . " canUpdate=" . ($up->canUpdateItem($outItem) ? 'Y' : 'N') . "\n";
}

// CRM Lead checks: find lead assigned to Hassan agent vs outsider
$leadTeam = $m->query(
    "SELECT ID, ASSIGNED_BY_ID FROM b_crm_lead WHERE ASSIGNED_BY_ID IN (2380,2344,2434,2291,2378,2376,2379,2303) AND STATUS_SEMANTIC_ID<>'S' ORDER BY ID DESC LIMIT 1"
)->fetch_assoc();
$leadOut = $m->query(
    "SELECT ID, ASSIGNED_BY_ID FROM b_crm_lead WHERE ASSIGNED_BY_ID NOT IN (2560,2380,2344,2434,2291,2378,2376,2379,2303) AND STATUS_SEMANTIC_ID<>'S' ORDER BY ID DESC LIMIT 1"
)->fetch_assoc();

$leadFactory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(\CCrmOwnerType::Lead);
echo "=== Hassan CRM Leads ===\n";
if ($leadTeam && $leadFactory) {
    $li = $leadFactory->getItem((int) $leadTeam['ID']);
    if ($li) {
        echo "team lead {$li->getId()} assigned={$li->getAssignedById()} canRead=" . ($up->canReadItem($li) ? 'Y' : 'N') . " canUpdate=" . ($up->canUpdateItem($li) ? 'Y' : 'N') . "\n";
    }
}
if ($leadOut && $leadFactory) {
    $li = $leadFactory->getItem((int) $leadOut['ID']);
    if ($li) {
        echo "out lead {$li->getId()} assigned={$li->getAssignedById()} canRead=" . ($up->canReadItem($li) ? 'Y' : 'N') . " canUpdate=" . ($up->canUpdateItem($li) ? 'Y' : 'N') . "\n";
    }
}

echo "DONE\n";
