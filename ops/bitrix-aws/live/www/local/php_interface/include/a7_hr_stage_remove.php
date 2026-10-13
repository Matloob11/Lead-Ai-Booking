<?php
if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    return;
}

if (!function_exists('a7_hr_stage_remove_on_prolog')) {
    function a7_hr_stage_remove_on_prolog(): void
    {
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        if ($uri === '' || !preg_match('#/(page/|crm/)#i', $uri)) {
            return;
        }

        global $APPLICATION;
        if (!is_object($APPLICATION)) {
            return;
        }

        $doc = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/\\');
        $js = $doc . '/local/js/a7_hr_stage_remove.js';
        $css = $doc . '/local/css/a7_hr_stage_remove.css';
        $jsVer = is_file($js) ? (string)filemtime($js) : '1';
        $cssVer = is_file($css) ? (string)filemtime($css) : '1';

        if (method_exists($APPLICATION, 'SetAdditionalCSS')) {
            $APPLICATION->SetAdditionalCSS('/local/css/a7_hr_stage_remove.css?v=' . $cssVer);
        }
        if (method_exists($APPLICATION, 'AddHeadScript')) {
            $APPLICATION->AddHeadScript('/local/js/a7_hr_stage_remove.js?v=' . $jsVer);
        }
    }
}

if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', 'a7_hr_stage_remove_on_prolog');
}
