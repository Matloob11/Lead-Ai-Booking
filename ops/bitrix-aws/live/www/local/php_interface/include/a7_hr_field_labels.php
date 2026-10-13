<?php
if (!defined('B_PROLOG_INCLUDED') || B_PROLOG_INCLUDED !== true) {
    return;
}

if (!function_exists('a7_hr_field_labels_on_prolog')) {
    function a7_hr_field_labels_on_prolog(): void
    {
        $uri = (string)($_SERVER['REQUEST_URI'] ?? '');
        if ($uri === '') {
            return;
        }

        $isHr = (bool)preg_match('#/(page/hr|/type/(1156|1160|1168|1172|1210|1212|1214|1216)/)#i', $uri);
        if (!$isHr) {
            return;
        }

        global $APPLICATION;
        if (!is_object($APPLICATION)) {
            return;
        }

        $doc = rtrim((string)($_SERVER['DOCUMENT_ROOT'] ?? ''), '/\\');
        $css = $doc . '/local/css/a7_hr_field_labels.css';
        $cssVer = is_file($css) ? (string)filemtime($css) : '1';

        if (method_exists($APPLICATION, 'SetAdditionalCSS')) {
            $APPLICATION->SetAdditionalCSS('/local/css/a7_hr_field_labels.css?v=' . $cssVer);
        }
    }
}

if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnProlog', 'a7_hr_field_labels_on_prolog');
}
