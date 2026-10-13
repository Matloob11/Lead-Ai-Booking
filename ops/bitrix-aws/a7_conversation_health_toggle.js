(function () {
  'use strict';

  var TITLE_RE = /^\s*conversation health\s*$/i;
  var FIELD_NAME_RE = /UF_CRM_CONVERSATION_HEALTH|UF_CRM_WA_CHAT|UF_CRM_AI_MONITOR|UF_CRM_6A8AE76C58C28|UF_CRM_6A8AE76C75B37|UF_CRM_6A8AE76C8DF3D|UF_CRM_6A92B836F320E|UF_CRM_6A92B83A836B8|UF_CRM_6A92B83E0ED1A/i;
  var FIELD_LABEL_RE = /^\s*(conversation health|ai monitor|whatsapp chat)\s*$/i;

  function textOf(el) {
    return ((el && el.textContent) || '').replace(/\s+/g, ' ').trim();
  }

  function closestSection(el) {
    if (!el) {
      return null;
    }
    return el.closest(
      '.ui-entity-editor-section, .crm-entity-card-widget, .ui-entity-editor-widget, .ui-entity-editor-column-content > .ui-entity-editor-section'
    );
  }

  function sectionBody(section) {
    return section.querySelector(
      '.ui-entity-editor-section-content, .ui-entity-editor-content-block-wrap, .crm-entity-widget-content, .ui-entity-editor-section-content-wrap'
    ) || section.querySelector('.ui-entity-editor-content-block') || null;
  }

  function sectionTitleNode(section) {
    return section.querySelector(
      '.ui-entity-editor-header-title-text, .ui-entity-editor-header-title, .crm-entity-widget-title, .ui-entity-editor-section-header'
    );
  }

  function markSection(section) {
    if (!section || section.getAttribute('data-a7-ch') === '1') {
      return;
    }
    var body = sectionBody(section);
    var header = section.querySelector('.ui-entity-editor-section-header, .crm-entity-card-widget-title, .crm-entity-widget-title-container') || sectionTitleNode(section);
    if (!body || !header || header.contains(body)) {
      return;
    }
    section.setAttribute('data-a7-ch', '1');
    section.classList.add('a7-ch-wrap', 'a7-ch-collapsed');
    body.classList.add('a7-ch-body');
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'a7-ch-toggle';
    btn.setAttribute('data-a7-ch-btn', '1');
    btn.textContent = 'Expand';
    btn.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      var open = section.classList.toggle('a7-ch-collapsed');
      btn.textContent = open ? 'Expand' : 'Close';
    });
    header.appendChild(btn);
  }

  function enhance() {
    var nodes = document.querySelectorAll(
      '.ui-entity-editor-header-title-text, .ui-entity-editor-header-title, .crm-entity-widget-title'
    );
    Array.prototype.forEach.call(nodes, function (node) {
      if (TITLE_RE.test(textOf(node))) {
        markSection(closestSection(node));
      }
    });
    var fields = document.querySelectorAll('[data-cid], [data-name], [name]');
    Array.prototype.forEach.call(fields, function (el) {
      var cid = (el.getAttribute('data-cid') || '') + ' ' + (el.getAttribute('data-name') || '') + ' ' + (el.getAttribute('name') || '');
      if (FIELD_NAME_RE.test(cid)) {
        markSection(closestSection(el));
      }
    });
    var labels = document.querySelectorAll(
      '.ui-entity-editor-block-title-text, .ui-entity-editor-block-title, .ui-entity-editor-content-block-title'
    );
    Array.prototype.forEach.call(labels, function (node) {
      if (FIELD_LABEL_RE.test(textOf(node))) {
        markSection(closestSection(node));
      }
    });
  }

  function start() {
    enhance();
    var tries = 0;
    var timer = window.setInterval(function () {
      tries += 1;
      enhance();
      if (tries >= 40) {
        window.clearInterval(timer);
      }
    }, 400);
    if (window.BX && BX.addCustomEvent) {
      BX.addCustomEvent('SidePanel.Slider:onLoad', function () {
        window.setTimeout(enhance, 200);
      });
      BX.addCustomEvent('BX.UI.EntityEditor:onLayout', function () {
        window.setTimeout(enhance, 50);
      });
    }
    if (window.MutationObserver) {
      var pending = false;
      var observer = new MutationObserver(function () {
        if (pending) {
          return;
        }
        pending = true;
        window.setTimeout(function () {
          pending = false;
          enhance();
        }, 120);
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
