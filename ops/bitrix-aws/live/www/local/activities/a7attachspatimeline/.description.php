<?php
if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    die();
}

$arActivityDescription = [
    'NAME' => 'A7: Attach Owner Data timeline',
    'DESCRIPTION' => 'After Copy SPA to Availability: duplicate timeline/comments/calls/tasks and keep the source name.',
    'TYPE' => ['activity', 'robot_activity'],
    'CLASS' => 'A7AttachSpaTimelineActivity',
    'JSCLASS' => 'BizProcActivity',
    'CATEGORY' => [
        'ID' => 'document',
        'OWN_ID' => 'crm',
        'OWN_NAME' => 'CRM',
    ],
    'FILTER' => [
        'INCLUDE' => [
            ['crm', 'Bitrix\\Crm\\Integration\\BizProc\\Document\\Dynamic'],
        ],
    ],
    'ROBOT_SETTINGS' => [
        'CATEGORY' => 'employee',
    ],
];
