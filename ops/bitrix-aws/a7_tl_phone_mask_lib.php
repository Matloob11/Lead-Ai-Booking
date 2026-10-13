<?php
/**
 * Shared helpers for A7 phone mask (TL list + Admin & Finance auto-dept).
 */

function a7_tl_mask_config(): array
{
    $path = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/a7_tl_phone_mask.config.php';
    if (!is_readable($path)) {
        $path = __DIR__ . '/a7_tl_phone_mask.config.php';
    }
    $cfg = is_readable($path) ? include $path : null;
    return is_array($cfg) ? $cfg : [];
}

/**
 * Collect user IDs in a department tree (recursive).
 *
 * @return list<int>
 */
function a7_tl_mask_dept_member_ids(int $deptId): array
{
    static $cache = [];
    if (isset($cache[$deptId])) {
        return $cache[$deptId];
    }
    $uids = [];
    if ($deptId <= 0 || !class_exists('CIntranetUtils')) {
        return $cache[$deptId] = $uids;
    }
    if (!\Bitrix\Main\Loader::includeModule('intranet')) {
        return $cache[$deptId] = $uids;
    }
    $emp = CIntranetUtils::GetDepartmentEmployees($deptId, true, false, 'Y');
    if (is_array($emp)) {
        foreach ($emp as $uid) {
            $n = (int)$uid;
            if ($n > 0) {
                $uids[] = $n;
            }
        }
    } elseif (is_object($emp) && method_exists($emp, 'Fetch')) {
        while ($row = $emp->Fetch()) {
            $n = (int)($row['ID'] ?? $row['USER_ID'] ?? 0);
            if ($n > 0) {
                $uids[] = $n;
            }
        }
    }
    $uids = array_values(array_unique($uids));
    return $cache[$deptId] = $uids;
}

/**
 * Whether this user must see masked phones.
 * Exempts always win. Then: hardcoded leaders OR auto department membership.
 */
function a7_tl_mask_should_apply(int $uid, ?array $cfg = null): bool
{
    if ($uid <= 0) {
        return false;
    }
    $cfg = $cfg ?? a7_tl_mask_config();
    $exempt = array_map('intval', $cfg['exempt_user_ids'] ?? [1, 2237]);
    if (in_array($uid, $exempt, true)) {
        return false;
    }
    $leaders = (isset($cfg['leaders']) && is_array($cfg['leaders'])) ? $cfg['leaders'] : [];
    if (isset($leaders[$uid])) {
        return true;
    }
    $extra = array_map('intval', $cfg['extra_mask_user_ids'] ?? []);
    if (in_array($uid, $extra, true)) {
        return true;
    }
    $autoDepts = array_map('intval', $cfg['auto_department_ids'] ?? [2]);
    foreach ($autoDepts as $deptId) {
        if ($deptId <= 0) {
            continue;
        }
        if (in_array($uid, a7_tl_mask_dept_member_ids($deptId), true)) {
            return true;
        }
    }
    return false;
}
