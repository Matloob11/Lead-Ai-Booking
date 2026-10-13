<?php
/**
 * Owner Data (cat 13) → Availability (cat 14): duplicate timeline onto the copy.
 *
 * Bitrix "Copy SPA" copies fields only. Deal copy has CopyTimeline=Y; SPA copy
 * does not. This library is the same attach Bitrix uses for deals, for entity 1042.
 *
 * Deploy to: /home/bitrix/www/bitrix/php_interface/include/a7_owner_avail_timeline_lib.php
 */

if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    // Allow CLI/tools that include this after prolog.
}

const A7_OWNER_AVAIL_ENTITY_TYPE = 1042;
const A7_OWNER_AVAIL_SOURCE_CATEGORY = 13;
const A7_OWNER_AVAIL_TARGET_CATEGORY = 14;

/**
 * Every public TimelineType constant except UNDEFINED — same set Deal CopyTimeline uses.
 */
function a7_owner_avail_timeline_types(): array
{
    if (!class_exists('\\Bitrix\\Crm\\Timeline\\TimelineType')) {
        return [];
    }
    $exclude = [\Bitrix\Crm\Timeline\TimelineType::UNDEFINED];
    $reflection = new \ReflectionClass(\Bitrix\Crm\Timeline\TimelineType::class);
    $constants = $reflection->getConstants(\ReflectionClassConstant::IS_PUBLIC);
    $constants = array_filter($constants, 'is_int');
    return array_values(array_diff($constants, $exclude));
}

function a7_owner_avail_timeline_bind_count(int $itemId): int
{
    if ($itemId <= 0 || !\Bitrix\Main\Loader::includeModule('crm')) {
        return 0;
    }
    global $DB;
    $itemId = (int)$itemId;
    $type = (int)A7_OWNER_AVAIL_ENTITY_TYPE;
    $res = $DB->Query(
        "SELECT COUNT(*) AS C FROM b_crm_timeline_bind
         WHERE ENTITY_TYPE_ID={$type} AND ENTITY_ID={$itemId}"
    );
    if ($res && ($row = $res->Fetch())) {
        return (int)$row['C'];
    }
    return 0;
}

function a7_owner_avail_source_title(int $sourceId): string
{
    if ($sourceId <= 0 || !\Bitrix\Main\Loader::includeModule('crm')) {
        return '';
    }
    $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(A7_OWNER_AVAIL_ENTITY_TYPE);
    if (!$factory) {
        return '';
    }
    $item = $factory->getItem($sourceId);
    if (!$item) {
        return '';
    }
    $title = trim((string)$item->getTitle());
    if ($title === '' || preg_match('/^Owner Data #\d+$/i', $title)) {
        return '';
    }
    return $title;
}

/**
 * Duplicate timeline entries, CRM activities, tasks and calendar links onto the copy.
 * Source keeps its own timeline (attach adds bindings; it does not move).
 */
function a7_owner_avail_attach_timeline(int $sourceId, int $targetId): array
{
    $out = [
        'ok' => false,
        'source_id' => $sourceId,
        'target_id' => $targetId,
        'before' => 0,
        'after' => 0,
        'error' => '',
    ];
    if ($sourceId <= 0 || $targetId <= 0 || $sourceId === $targetId) {
        $out['error'] = 'Bad source/target id.';
        return $out;
    }
    if (!\Bitrix\Main\Loader::includeModule('crm')) {
        $out['error'] = 'CRM module missing.';
        return $out;
    }

    $entityTypeId = (int)A7_OWNER_AVAIL_ENTITY_TYPE;
    $out['before'] = a7_owner_avail_timeline_bind_count($targetId);

    try {
        \Bitrix\Crm\Timeline\Entity\TimelineBindingTable::attach(
            $entityTypeId,
            $sourceId,
            $entityTypeId,
            $targetId,
            a7_owner_avail_timeline_types()
        );
    } catch (\Throwable $e) {
        $out['error'] = 'Timeline attach failed: ' . $e->getMessage();
        return $out;
    }

    try {
        if (class_exists('CCrmActivity') && method_exists('CCrmActivity', 'AttachBinding')) {
            \CCrmActivity::AttachBinding($entityTypeId, $sourceId, $entityTypeId, $targetId);
        }
    } catch (\Throwable $e) {
        // Timeline is the main ask; activity bind is best-effort.
    }

    a7_owner_avail_attach_task_bindings($sourceId, $targetId);
    a7_owner_avail_attach_calendar_bindings($sourceId, $targetId);

    try {
        \Bitrix\Crm\Timeline\LogMessageController::getInstance()->onCreate(
            [
                'ENTITY_TYPE_ID' => $entityTypeId,
                'ENTITY_ID' => $sourceId,
                'SETTINGS' => [
                    'COPY_TARGET' => [
                        'ENTITY_TYPE_ID' => $entityTypeId,
                        'ENTITY_ID' => $targetId,
                    ],
                ],
            ],
            \Bitrix\Crm\Timeline\LogMessageType::COPIED
        );
    } catch (\Throwable $e) {
        // Log line is optional.
    }

    $out['after'] = a7_owner_avail_timeline_bind_count($targetId);
    $out['ok'] = true;
    return $out;
}

function a7_owner_avail_attach_task_bindings(int $sourceId, int $targetId): void
{
    if (!\Bitrix\Main\Loader::includeModule('crm')) {
        return;
    }
    $entityTypeId = (int)A7_OWNER_AVAIL_ENTITY_TYPE;
    $providers = [];
    if (class_exists('\\Bitrix\\Crm\\Activity\\Provider\\Task')) {
        $providers[] = \Bitrix\Crm\Activity\Provider\Task::getId();
    }
    if (class_exists('\\Bitrix\\Crm\\Activity\\Provider\\Tasks\\Task')) {
        $providers[] = \Bitrix\Crm\Activity\Provider\Tasks\Task::getId();
    }
    if (!$providers) {
        return;
    }

    try {
        $rows = \Bitrix\Crm\ActivityTable::query()
            ->addSelect('ASSOCIATED_ENTITY_ID')
            ->whereIn('PROVIDER_ID', $providers)
            ->where('BINDINGS.OWNER_TYPE_ID', $entityTypeId)
            ->where('BINDINGS.OWNER_ID', $sourceId)
            ->where('ASSOCIATED_ENTITY_ID', '>', 0)
            ->exec();
    } catch (\Throwable $e) {
        return;
    }

    $newBinding = [
        ['OWNER_TYPE_ID' => $entityTypeId, 'OWNER_ID' => $targetId],
    ];
    while ($row = $rows->fetch()) {
        $taskId = (int)$row['ASSOCIATED_ENTITY_ID'];
        if ($taskId <= 0) {
            continue;
        }
        try {
            if (class_exists('\\Bitrix\\Crm\\Activity\\Provider\\Task')) {
                \Bitrix\Crm\Activity\Provider\Task::bindExternalEntity($taskId, $newBinding);
            }
        } catch (\Throwable $e) {
            // continue
        }
    }
}

function a7_owner_avail_attach_calendar_bindings(int $sourceId, int $targetId): void
{
    if (!\Bitrix\Main\Loader::includeModule('crm') || !\Bitrix\Main\Loader::includeModule('calendar')) {
        return;
    }
    $entityTypeId = (int)A7_OWNER_AVAIL_ENTITY_TYPE;
    try {
        $rows = \Bitrix\Crm\ActivityTable::query()
            ->addSelect('CALENDAR_EVENT_ID')
            ->where('BINDINGS.OWNER_TYPE_ID', $entityTypeId)
            ->where('BINDINGS.OWNER_ID', $sourceId)
            ->where('CALENDAR_EVENT_ID', '>', 0)
            ->exec();
    } catch (\Throwable $e) {
        return;
    }

    $eventIds = [];
    while ($row = $rows->fetch()) {
        $eventId = (int)$row['CALENDAR_EVENT_ID'];
        if ($eventId > 0) {
            $eventIds[] = $eventId;
        }
    }
    if (!$eventIds) {
        return;
    }

    $abbr = class_exists('CCrmOwnerTypeAbbr')
        ? (string)\CCrmOwnerTypeAbbr::ResolveByTypeID($entityTypeId)
        : 'T80';
    if ($abbr === '') {
        $abbr = 'T80';
    }
    $newSlug = $abbr . '_' . $targetId;

    foreach (array_chunk($eventIds, 50) as $chunk) {
        try {
            $events = \CCalendarEvent::GetList([
                'arFilter' => ['ID' => $chunk, '=DELETED' => 'N'],
                'arSelect' => ['ID'],
                'getUserfields' => true,
                'checkPermissions' => false,
            ]);
        } catch (\Throwable $e) {
            continue;
        }
        foreach ($events as $event) {
            $crmBindings = is_array($event['UF_CRM_CAL_EVENT'] ?? null) ? $event['UF_CRM_CAL_EVENT'] : [];
            if (!in_array($newSlug, $crmBindings, true)) {
                $crmBindings[] = $newSlug;
                try {
                    \CCalendarEvent::UpdateUserFields((int)$event['ID'], ['UF_CRM_CAL_EVENT' => $crmBindings]);
                } catch (\Throwable $e) {
                    // continue
                }
            }
        }
    }
}

/**
 * Set Availability card title to the Owner Data person's name.
 */
function a7_owner_avail_fix_title_from_source(int $sourceId, int $targetId): array
{
    $out = ['ok' => false, 'title' => '', 'error' => ''];
    $title = a7_owner_avail_source_title($sourceId);
    if ($title === '') {
        $out['error'] = 'Source has no usable title.';
        return $out;
    }
    $factory = \Bitrix\Crm\Service\Container::getInstance()->getFactory(A7_OWNER_AVAIL_ENTITY_TYPE);
    if (!$factory) {
        $out['error'] = 'Factory missing.';
        return $out;
    }
    $item = $factory->getItem($targetId);
    if (!$item) {
        $out['error'] = 'Target item missing.';
        return $out;
    }
    if (trim((string)$item->getTitle()) === $title) {
        $out['ok'] = true;
        $out['title'] = $title;
        return $out;
    }
    $item->setTitle($title);
    $op = $factory->getUpdateOperation($item);
    $op->disableCheckAccess()->disableCheckFields()->disableBizProc();
    $result = $op->launch();
    if (!$result->isSuccess()) {
        $out['error'] = implode('; ', $result->getErrorMessages());
        return $out;
    }
    $out['ok'] = true;
    $out['title'] = $title;
    return $out;
}

/**
 * One shot after Copy SPA: timeline + source name on the new Availability card.
 */
function a7_owner_avail_after_copy(int $sourceId, int $targetId): array
{
    $timeline = a7_owner_avail_attach_timeline($sourceId, $targetId);
    $title = a7_owner_avail_fix_title_from_source($sourceId, $targetId);
    return [
        'timeline' => $timeline,
        'title' => $title,
    ];
}

/**
 * Parse "Owner Data #92578" → 92578.
 */
function a7_owner_avail_parse_source_from_title(string $title): int
{
    if (preg_match('/^Owner Data #(\d+)\s*$/i', trim($title), $m)) {
        return (int)$m[1];
    }
    return 0;
}
