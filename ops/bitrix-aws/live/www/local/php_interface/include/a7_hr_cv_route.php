<?php
if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    return;
}

/**
 * Route new Applicant CVs by phone:
 * - phone contains 971 → HR (UAE) Applicant 1210
 * - otherwise (when phone is filled) → HR (PAK) Applicant 1156, Pakistan CVS
 * Empty phone is left where it was created.
 */

if (!function_exists('a7_hr_cv_route_phone')) {
    function a7_hr_cv_route_phone(\Bitrix\Crm\Item $item, int $typeId): string
    {
        $field = $typeId === 1210 ? 'UF_CRM_45_1760525672592' : 'UF_CRM_32_1760525672592';
        $value = null;
        try {
            $value = $item->get($field);
        } catch (\Throwable $e) {
            $value = null;
        }
        if ($value === null || $value === '') {
            $data = $item->getCompatibleData();
            $value = $data[$field] ?? '';
        }
        if (is_array($value)) {
            $value = implode(' ', $value);
        }
        return trim((string)$value);
    }
}

if (!function_exists('a7_hr_cv_route_is_uae')) {
    function a7_hr_cv_route_is_uae(string $phone): bool
    {
        $phone = trim($phone);
        if ($phone === '') {
            return false;
        }
        if (str_contains($phone, '971')) {
            return true;
        }
        $digits = preg_replace('/\D+/', '', $phone) ?? '';
        return $digits !== '' && (bool)preg_match('/^(00)?971/', $digits);
    }
}

if (!function_exists('a7_hr_cv_route_move')) {
    function a7_hr_cv_route_move(\Bitrix\Crm\Item $srcItem, int $dstTypeId): void
    {
        if (!\Bitrix\Main\Loader::includeModule('crm')) {
            return;
        }

        $srcTypeId = (int)$srcItem->getEntityTypeId();
        $container = \Bitrix\Crm\Service\Container::getInstance();
        $srcFactory = $container->getFactory($srcTypeId);
        $dstFactory = $container->getFactory($dstTypeId);
        if (!$srcFactory || !$dstFactory) {
            return;
        }

        $srcPrefix = $srcTypeId === 1210 ? 'UF_CRM_45_' : 'UF_CRM_32_';
        $dstPrefix = $dstTypeId === 1210 ? 'UF_CRM_45_' : 'UF_CRM_32_';

        $data = $srcItem->getCompatibleData();
        $mapped = [
            'TITLE' => $data['TITLE'] ?? '',
            'ASSIGNED_BY_ID' => $data['ASSIGNED_BY_ID'] ?? 1,
            'OPENED' => $data['OPENED'] ?? 'Y',
            'STAGE_ID' => $dstTypeId === 1210 ? 'DT1210_58:NEW' : 'DT1156_44:NEW',
            'CATEGORY_ID' => $dstTypeId === 1210 ? 58 : 44,
            'XML_ID' => 'a7-routed-' . $srcTypeId . '-' . (int)$srcItem->getId(),
        ];
        foreach ($data as $key => $value) {
            $key = (string)$key;
            if (str_starts_with($key, $srcPrefix)) {
                $mapped[str_replace($srcPrefix, $dstPrefix, $key)] = $value;
            }
        }

        global $USER;
        $userId = (is_object($USER) && method_exists($USER, 'GetID') && (int)$USER->GetID() > 0)
            ? (int)$USER->GetID()
            : 1;
        $context = new \Bitrix\Crm\Service\Context();
        $context->setUserId($userId);

        $newItem = $dstFactory->createItem();
        $newItem->setFromCompatibleData($mapped);
        $addOp = $dstFactory->getAddOperation($newItem, $context);
        $addOp->disableCheckAccess();
        if (method_exists($addOp, 'disableAutomation')) {
            $addOp->disableAutomation();
        }
        if (method_exists($addOp, 'disableBizProc')) {
            $addOp->disableBizProc();
        }
        $addResult = $addOp->launch();
        if (!$addResult->isSuccess()) {
            AddMessage2Log(
                'A7 HR route add fail #' . $srcItem->getId() . ': ' . implode('; ', $addResult->getErrorMessages()),
                'a7_hr_cv_route'
            );
            return;
        }

        // Delete the wrong-section original after this request finishes.
        // Deleting inside onCrmDynamicItemAdd breaks the still-running add/update.
        a7_hr_cv_route_queue_delete($srcTypeId, (int)$srcItem->getId());
    }
}

if (!function_exists('a7_hr_cv_route_delete_item')) {
    function a7_hr_cv_route_delete_item(int $typeId, int $id): void
    {
        if ($typeId <= 0 || $id <= 0) {
            return;
        }
        if (!\Bitrix\Main\Loader::includeModule('crm')) {
            return;
        }
        $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory($typeId);
        if (!$factory) {
            return;
        }
        $item = $factory->getItem($id);
        if (!$item) {
            return;
        }
        $context = new \Bitrix\Crm\Service\Context();
        $context->setUserId(1);
        $delOp = $factory->getDeleteOperation($item, $context);
        $delOp->disableCheckAccess();
        if (method_exists($delOp, 'disableAutomation')) {
            $delOp->disableAutomation();
        }
        if (method_exists($delOp, 'disableBizProc')) {
            $delOp->disableBizProc();
        }
        $delResult = $delOp->launch();
        if (!$delResult->isSuccess()) {
            AddMessage2Log(
                'A7 HR route del fail #' . $id . ': ' . implode('; ', $delResult->getErrorMessages()),
                'a7_hr_cv_route'
            );
        }
    }
}

if (!function_exists('a7_hr_cv_route_queue_delete')) {
    function a7_hr_cv_route_queue_delete(int $typeId, int $id): void
    {
        static $queued = [];
        $key = $typeId . ':' . $id;
        if (isset($queued[$key]) || $typeId <= 0 || $id <= 0) {
            return;
        }
        $queued[$key] = true;
        register_shutdown_function(static function () use ($typeId, $id): void {
            a7_hr_cv_route_delete_item($typeId, $id);
        });
    }
}

if (!function_exists('a7_hr_cv_route_on_event')) {
    function a7_hr_cv_route_on_event($event): void
    {
        static $busy = false;
        if ($busy) {
            return;
        }
        if (!($event instanceof \Bitrix\Main\Event)) {
            return;
        }
        if (!\Bitrix\Main\Loader::includeModule('crm')) {
            return;
        }

        $item = $event->getParameter('item');
        if (!($item instanceof \Bitrix\Crm\Item)) {
            return;
        }

        $typeId = (int)$item->getEntityTypeId();
        if ($typeId !== 1156 && $typeId !== 1210) {
            return;
        }

        $phone = a7_hr_cv_route_phone($item, $typeId);
        if ($phone === '') {
            return;
        }

        $wantType = a7_hr_cv_route_is_uae($phone) ? 1210 : 1156;
        if ($typeId === $wantType) {
            return;
        }

        $busy = true;
        try {
            a7_hr_cv_route_move($item, $wantType);
        } catch (\Throwable $e) {
            AddMessage2Log('A7 HR route error: ' . $e->getMessage(), 'a7_hr_cv_route');
        }
        $busy = false;
    }
}

if (class_exists('\Bitrix\Main\EventManager')) {
    $a7HrCvRouteEm = \Bitrix\Main\EventManager::getInstance();
    $a7HrCvRouteEm->addEventHandler('crm', 'onCrmDynamicItemAdd', 'a7_hr_cv_route_on_event');
    $a7HrCvRouteEm->addEventHandler('crm', 'onCrmDynamicItemUpdate', 'a7_hr_cv_route_on_event');
}
