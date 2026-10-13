<?php
if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    die();
}

use Bitrix\Main\Loader;
use Bitrix\Main\Localization\Loc;

/**
 * Runs on the Owner Data document right after Copy SPA.
 * TargetItemId = return value of CrmCopyDynamicActivity (new Availability id).
 */
class CBPA7AttachSpaTimelineActivity extends CBPActivity
{
    public function __construct($name)
    {
        parent::__construct($name);
        $this->arProperties = [
            'Title' => '',
            'TargetItemId' => null,
        ];
    }

    public function Execute()
    {
        if (!Loader::includeModule('crm')) {
            return CBPActivityExecutionStatus::Closed;
        }

        $lib = (string)($_SERVER['DOCUMENT_ROOT'] ?? '') . '/bitrix/php_interface/include/a7_owner_avail_timeline_lib.php';
        if (!is_readable($lib)) {
            $this->WriteToTrackingService('A7 timeline lib missing.', 0, CBPTrackingType::Error);
            return CBPActivityExecutionStatus::Closed;
        }
        require_once $lib;

        $documentId = $this->GetDocumentId();
        $doc = is_array($documentId) ? (string)($documentId[2] ?? '') : '';
        $sourceId = 0;
        if (preg_match('/_(\d+)$/', $doc, $m)) {
            $sourceId = (int)$m[1];
        }

        $targetRaw = $this->TargetItemId;
        if (is_array($targetRaw)) {
            $targetRaw = reset($targetRaw);
        }
        $targetId = (int)$targetRaw;

        if ($sourceId <= 0 || $targetId <= 0) {
            $this->WriteToTrackingService(
                'A7 timeline: need source and target ids (got ' . $sourceId . ' → ' . $targetId . ').',
                0,
                CBPTrackingType::Error
            );
            return CBPActivityExecutionStatus::Closed;
        }

        $result = a7_owner_avail_after_copy($sourceId, $targetId);
        $timeline = $result['timeline'] ?? [];
        $title = $result['title'] ?? [];

        if (empty($timeline['ok'])) {
            $this->WriteToTrackingService(
                'A7 timeline attach failed: ' . ($timeline['error'] ?? 'unknown'),
                0,
                CBPTrackingType::Error
            );
        } else {
            $this->WriteToTrackingService(
                'A7 timeline copied ' . (int)($timeline['before'] ?? 0) .
                ' → ' . (int)($timeline['after'] ?? 0) . ' binds on Availability #' . $targetId,
                0,
                CBPTrackingType::Report
            );
        }

        if (!empty($title['ok'])) {
            $this->WriteToTrackingService(
                'A7 title set to "' . ($title['title'] ?? '') . '"',
                0,
                CBPTrackingType::Report
            );
        } elseif (!empty($title['error'])) {
            $this->WriteToTrackingService(
                'A7 title: ' . $title['error'],
                0,
                CBPTrackingType::Report
            );
        }

        return CBPActivityExecutionStatus::Closed;
    }

    public static function GetPropertiesDialog(
        $documentType,
        $activityName,
        $workflowTemplate,
        $workflowParameters,
        $workflowVariables,
        $currentValues = null,
        $formName = '',
        $popupWindow = null,
        $siteId = ''
    ) {
        $runtime = CBPRuntime::GetRuntime();
        $runtime->StartRuntime();

        if (!is_array($currentValues)) {
            $currentValues = ['target_item_id' => ''];
            $currentActivity = &CBPWorkflowTemplateLoader::FindActivityByName($workflowTemplate, $activityName);
            if (is_array($currentActivity) && isset($currentActivity['Properties']['TargetItemId'])) {
                $currentValues['target_item_id'] = $currentActivity['Properties']['TargetItemId'];
            }
        }

        return $runtime->ExecuteResourceFile(
            __FILE__,
            'properties_dialog.php',
            [
                'arCurrentValues' => $currentValues,
                'formName' => $formName,
            ]
        );
    }

    public static function GetPropertiesDialogValues(
        $documentType,
        $activityName,
        &$workflowTemplate,
        &$workflowParameters,
        &$workflowVariables,
        $currentValues,
        &$errors
    ) {
        $errors = [];
        $properties = [
            'TargetItemId' => $currentValues['target_item_id'] ?? '',
        ];
        $currentActivity = &CBPWorkflowTemplateLoader::FindActivityByName($workflowTemplate, $activityName);
        $currentActivity['Properties'] = $properties;
        return true;
    }
}
