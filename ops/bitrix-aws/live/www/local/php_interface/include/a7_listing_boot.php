<?php
/**
 * Replace Bitrix's default wait.gif spinner with the A7 Property Listing boot screen
 * while the Hostinger iframe is still loading.
 */
declare(strict_types=1);

if (!function_exists('a7_listing_boot_html')) {
    function a7_listing_boot_html(): string
    {
        return <<<'HTML'
<div class="a7-gate" role="status" aria-live="polite" aria-busy="true">
  <div class="a7-gate-orb" aria-hidden="true">
    <svg class="a7-gate-orbit a7-gate-orbit-a" viewBox="0 0 120 120">
      <circle class="a7-gate-track" cx="60" cy="60" r="52"></circle>
      <circle class="a7-gate-bar" cx="60" cy="60" r="52"></circle>
    </svg>
    <svg class="a7-gate-orbit a7-gate-orbit-b" viewBox="0 0 120 120">
      <circle class="a7-gate-inner" cx="60" cy="60" r="42"></circle>
    </svg>
    <span class="a7-gate-mark">
      <svg viewBox="0 0 40 16" fill="none"><path d="M3 13.5 20 3l17 10.5" stroke="currentColor" stroke-width="1.6"></path></svg>
      <b>A7</b>
    </span>
  </div>
  <div class="a7-gate-copy">
    <em>A7 Group</em>
    <strong>Property Listing</strong>
    <p>Opening the desk</p>
  </div>
</div>
HTML;
    }
}

if (!function_exists('a7_listing_boot_css')) {
    function a7_listing_boot_css(): string
    {
        return <<<'CSS'
<style id="a7-listing-boot">
.app-loading-msg:before{display:none!important;width:0!important;height:0!important;min-width:0!important;min-height:0!important;margin:0!important;background:none!important;content:none!important}
.app-loading-msg{background:radial-gradient(ellipse 62% 46% at 50% 40%,rgba(201,162,77,.16),transparent 62%),#f6f3ec!important;color:transparent!important;font-size:0!important;left:0!important;right:0!important;top:0!important;bottom:0!important}
.app-loading-msg .a7-gate{min-height:100%;width:100%;display:grid;place-content:center;justify-items:center;gap:28px;padding:2rem 1.4rem 3rem;font-size:13px;color:#1c1712}
.a7-gate-orb{position:relative;width:136px;height:136px}
.a7-gate-orbit{position:absolute;inset:0;width:100%;height:100%}
.a7-gate-orbit-a{animation:a7-gate-spin 1.35s linear infinite}
.a7-gate-orbit-b{animation:a7-gate-spin-rev 2.35s linear infinite}
.a7-gate-track,.a7-gate-bar,.a7-gate-inner{fill:none}
.a7-gate-track{stroke:rgba(201,162,77,.22);stroke-width:1.5}
.a7-gate-bar{stroke:#c9a24d;stroke-width:2.6;stroke-linecap:round;stroke-dasharray:92 235}
.a7-gate-inner{stroke:#2a2218;stroke-width:1.7;stroke-linecap:round;stroke-dasharray:48 216}
.a7-gate-mark{position:absolute;inset:50%;width:60px;height:60px;margin:-30px 0 0 -30px;border-radius:14px;background:#1c1712;border:1.5px solid #c9a24d;color:#c9a24d;display:grid;place-content:center;justify-items:center;box-shadow:0 14px 32px rgba(28,23,18,.2);animation:a7-gate-pulse 2.2s ease-in-out infinite}
.a7-gate-mark svg{width:24px;height:10px;margin-bottom:-1px}
.a7-gate-mark b{font:700 15px/1 Poppins,Segoe UI,sans-serif;letter-spacing:.12em}
.a7-gate-copy{display:grid;justify-items:center;gap:6px;text-align:center}
.a7-gate-copy em{font:600 10px/1 Poppins,Segoe UI,sans-serif;letter-spacing:.32em;text-transform:uppercase;color:#c9a24d}
.a7-gate-copy strong{font:600 30px/1 "Cormorant Garamond",Georgia,serif;letter-spacing:.1em;text-transform:uppercase;color:#1c1712}
.a7-gate-copy p{margin:4px 0 0;color:#8a7d68;font:500 13px Poppins,Segoe UI,sans-serif}
@keyframes a7-gate-spin{to{transform:rotate(360deg)}}
@keyframes a7-gate-spin-rev{to{transform:rotate(-360deg)}}
@keyframes a7-gate-pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.04)}}
</style>
CSS;
    }
}

if (!function_exists('a7_listing_boot_buffer')) {
    function a7_listing_boot_buffer(&$content): void
    {
        if (!is_string($content) || $content === '') {
            return;
        }
        if (!str_contains($content, 'app-loading-msg') || !preg_match('/Property Listing/i', $content)) {
            return;
        }
        if (str_contains($content, 'id="a7-listing-boot"')) {
            return;
        }
        $content = preg_replace(
            '/(<div id="appframe_loading_[^"]+" class="app-loading-msg"[^>]*>).*?(<\/div>)/s',
            '$1' . a7_listing_boot_html() . '$2',
            $content,
            1
        ) ?? $content;
        $css = a7_listing_boot_css();
        if (str_contains($content, '</head>')) {
            $content = str_replace('</head>', $css . '</head>', $content);
        } else {
            $content = $css . $content;
        }
    }
}

if (function_exists('AddEventHandler')) {
    AddEventHandler('main', 'OnEndBufferContent', 'a7_listing_boot_buffer');
}
