(function () {
  'use strict';

  var LABELS = [
    { key: 'looking_for', label: 'Looking For' },
    { key: 'property_type', label: 'Property Type' },
    { key: 'community', label: 'Community' },
    { key: 'budget', label: 'Budget' },
    { key: 'bedrooms', label: 'Bedrooms' },
    { key: 'move_in_date', label: 'Move-in Date' },
    { key: 'payment_method', label: 'Payment Method' },
    { key: 'interest_level', label: 'Interest Level' },
    { key: 'preferred_view', label: 'Preferred View' },
    { key: 'proximity', label: 'Proximity Preference' },
    { key: 'notes', label: 'Notes' }
  ];
  var ACTION_LABELS = {
    PROPERTY_VIEWING: 'Property Viewing',
    CALLBACK: 'Callback',
    FOLLOW_UP: 'Follow-up Required',
    SEND_PROPERTY_OPTIONS: 'Send Property Options',
    SEND_DETAILS: 'Send Details',
    NO_ACTION: 'No Action Required'
  };
  var timelineRows = [];
  var timelineTimer = 0;
  var timelinePending = false;
  var detailsPopup = null;
  var analyzeLocks = {};
  var injectRetryTimer = 0;

  function sessid() {
    if (window.BX && BX.bitrix_sessid) {
      return BX.bitrix_sessid();
    }
    return '';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function parseEntity() {
    var href = String(window.location.href || '');
    var path = String(window.location.pathname || '');
    var match = (path + ' ' + href).match(/\/crm\/(contact|lead)\/details\/(\d+)/i);
    if (match) {
      return { type: match[1].toUpperCase(), id: parseInt(match[2], 10) };
    }
    var params = new URLSearchParams(window.location.search);
    var type = String(params.get('entityTypeName') || params.get('entityType') || '');
    var id = parseInt(params.get('entityId') || params.get('entity_id') || '0', 10);
    if ((type === 'CONTACT' || type === 'LEAD') && id > 0) {
      return { type: type, id: id };
    }
    return null;
  }

  function formatStamp(value) {
    if (!value) {
      return '';
    }
    return String(value).replace('T', ' ').replace(/:\d{2}$/, '');
  }

  function formatDate(date) {
    if (!date) {
      return '';
    }
    var parts = String(date).split('-');
    if (parts.length !== 3) {
      return date;
    }
    var year = parseInt(parts[0], 10);
    if (!year || year < new Date().getFullYear()) {
      return '';
    }
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var month = months[parseInt(parts[1], 10) - 1] || parts[1];
    return parseInt(parts[2], 10) + ' ' + month + ' ' + parts[0];
  }

  function formatTime(time) {
    if (!time || time === '00:00') {
      return '';
    }
    var bits = String(time).split(':');
    var hour = parseInt(bits[0], 10);
    if (isNaN(hour)) {
      return time;
    }
    var suffix = hour >= 12 ? 'PM' : 'AM';
    var display = hour % 12;
    if (display === 0) {
      display = 12;
    }
    return display + ':' + (bits[1] || '00') + ' ' + suffix;
  }

  function fieldHtml(item, fields) {
    var raw = fields && fields[item.key];
    var empty = raw == null || String(raw).trim() === '';
    var extra = '';
    if (!empty && item.key === 'interest_level') {
      extra = ' a7-ci-crm-val-' + String(raw).toLowerCase();
    }
    return '<div class="a7-ci-crm-row">' +
      '<div class="a7-ci-crm-label">' + escapeHtml(item.label) + '</div>' +
      '<div class="a7-ci-crm-value' + extra + (empty ? ' a7-ci-crm-empty' : '') + '">' +
        (empty ? '—' : escapeHtml(raw)) +
      '</div>' +
    '</div>';
  }

  function scoreTone(score) {
    if (score == null) {
      return '';
    }
    if (score >= 70) {
      return 'green';
    }
    if (score >= 40) {
      return 'blue';
    }
    return 'red';
  }

  function renderRequirements(payload) {
    var fields = (payload && payload.fields) || {};
    var rows = LABELS.map(function (item) {
      return fieldHtml(item, fields);
    }).join('');
    var meta = [];
    if (payload && payload.updated_at) {
      meta.push('<div class="a7-ci-crm-meta"><span>Last Updated</span><strong>' +
        escapeHtml(formatStamp(payload.updated_at)) + '</strong></div>');
    }
    meta.push('<div class="a7-ci-crm-meta"><span>Source</span><strong>AI Call Intelligence</strong></div>');
    return '<div class="a7-ci-crm-card">' +
      '<div class="a7-ci-crm-head">' +
        '<div>' +
          '<div class="a7-ci-crm-title">Client Requirements</div>' +
          '<div class="a7-ci-crm-sub">Most important details the client said on calls</div>' +
        '</div>' +
        '<span class="a7-ci-crm-badge">AI Extracted</span>' +
      '</div>' +
      '<div class="a7-ci-crm-rows">' + rows + '</div>' +
      '<div class="a7-ci-crm-foot">' + meta.join('') + '</div>' +
    '</div>';
  }

  function transcriptRowHtml(transcript) {
    if (!transcript) {
      return '<div class="a7-ci-crm-row"><div class="a7-ci-crm-label">Transcript</div>' +
        '<div class="a7-ci-crm-value"><span class="a7-ci-crm-empty">—</span></div></div>';
    }
    return '<div class="a7-ci-crm-row"><div class="a7-ci-crm-label">Transcript</div>' +
      '<div class="a7-ci-crm-value">' +
        '<button type="button" class="a7-ci-btn a7-ci-btn-transcript a7-ci-crm-transcript-btn">' +
          '<span class="a7-ci-btn-ic" aria-hidden="true"></span>Transcript</button>' +
        '<textarea class="a7-ci-crm-transcript-src" hidden readonly>' + escapeHtml(transcript) + '</textarea>' +
      '</div></div>';
  }

  function popupBodyHtml(text) {
    var safe = escapeHtml(text || '-').replace(/\n/g, '<br>');
    return '<div class="a7-ci-modal a7-ci-modal-transcript">' +
      '<div class="a7-ci-modal-head">' +
        '<span class="a7-ci-modal-icon" aria-hidden="true"></span>' +
        '<div class="a7-ci-modal-copy">' +
          '<div class="a7-ci-modal-title">Call Transcript</div>' +
          '<div class="a7-ci-modal-sub">Full English transcript of the call</div>' +
        '</div>' +
      '</div>' +
      '<div class="a7-ci-modal-body">' + safe + '</div>' +
    '</div>';
  }

  function showTranscript(text) {
    var bodyText = text || '-';
    showBxPopup('a7-ci-crm-transcript-' + Date.now(), popupBodyHtml(bodyText), bodyText, 760);
  }

  function bindTranscriptButton(panel) {
    var btn = panel.querySelector('.a7-ci-crm-transcript-btn');
    if (!btn || btn.getAttribute('data-bound') === '1') {
      return;
    }
    btn.setAttribute('data-bound', '1');
    btn.addEventListener('click', function (event) {
      event.preventDefault();
      var src = panel.querySelector('.a7-ci-crm-transcript-src');
      showTranscript(src ? src.value : '');
    });
  }

  function renderAnalysis(payload) {
    var analysis = (payload && payload.analysis) || {};
    var score = analysis.score;
    var summary = String(analysis.summary || '').trim();
    var comment = String(analysis.comment || '').trim();
    var transcript = String(analysis.transcript || '').trim();
    var actionLabel = analysis.next_action_label || ACTION_LABELS[analysis.next_action_type] || analysis.next_action_type || '';
    var when = [formatDate(analysis.next_action_date), formatTime(analysis.next_action_time)]
      .filter(Boolean).join(' · ');
    var tone = scoreTone(score);
    var scoreHtml = score == null
      ? '<span class="a7-ci-crm-empty">—</span>'
      : '<span class="a7-ci-crm-score a7-ci-crm-val-' + tone + '">' + escapeHtml(score) + '/100</span>';
    return '<div class="a7-ci-crm-card a7-ci-crm-card-analysis">' +
      '<div class="a7-ci-crm-head a7-ci-crm-head-analysis">' +
        '<div>' +
          '<div class="a7-ci-crm-title">Call Intelligence</div>' +
          '<div class="a7-ci-crm-sub">Saved from the latest analyzed call</div>' +
        '</div>' +
        '<span class="a7-ci-crm-badge a7-ci-crm-badge-blue">AI Score</span>' +
      '</div>' +
      '<div class="a7-ci-crm-rows">' +
        '<div class="a7-ci-crm-row"><div class="a7-ci-crm-label">AI Score</div>' +
          '<div class="a7-ci-crm-value">' + scoreHtml + '</div></div>' +
        '<div class="a7-ci-crm-row a7-ci-crm-row-block"><div class="a7-ci-crm-label">Call Summary</div>' +
          '<div class="a7-ci-crm-value a7-ci-crm-summary">' +
            (summary ? escapeHtml(summary) : '<span class="a7-ci-crm-empty">—</span>') +
          '</div></div>' +
        transcriptRowHtml(transcript) +
        '<div class="a7-ci-crm-row"><div class="a7-ci-crm-label">Next Action</div>' +
          '<div class="a7-ci-crm-value">' +
            (actionLabel ? escapeHtml(actionLabel) : '<span class="a7-ci-crm-empty">—</span>') +
            (when ? '<div class="a7-ci-crm-action-when">' + escapeHtml(when) + '</div>' : '') +
          '</div></div>' +
        '<div class="a7-ci-crm-row a7-ci-crm-row-block"><div class="a7-ci-crm-label">Comment</div>' +
          '<div class="a7-ci-crm-value a7-ci-crm-summary">' +
            (comment ? escapeHtml(comment) : '<span class="a7-ci-crm-empty">—</span>') +
          '</div></div>' +
      '</div>' +
    '</div>';
  }

  function renderPanel(payload) {
    return renderRequirements(payload) + renderAnalysis(payload);
  }

  function crmDocuments() {
    var docs = [document];
    try {
      Array.prototype.forEach.call(document.querySelectorAll('iframe'), function (frame) {
        try {
          // A slider iframe that runs its own copy of this script manages itself.
          if (frame.contentWindow && frame.contentWindow.A7_CI_CRM_OWNED) {
            return;
          }
          if (frame.contentDocument && docs.indexOf(frame.contentDocument) === -1) {
            docs.push(frame.contentDocument);
          }
        } catch (err) {}
      });
    } catch (err) {}
    docs.forEach(ensureDocAssets);
    return docs;
  }

  function ensureDocAssets(doc) {
    if (!doc || !doc.documentElement) {
      return;
    }
    if (doc.getElementById('a7-ci-iframe-css')) {
      return;
    }
    var css = doc.querySelector('link[href*="a7_call_intelligence.css"]');
    if (css) {
      return;
    }
    var link = doc.createElement('link');
    link.id = 'a7-ci-iframe-css';
    link.rel = 'stylesheet';
    link.href = '/bitrix/css/a7_call_intelligence.css?v=' + String(Date.now());
    (doc.head || doc.documentElement).appendChild(link);
  }

  function findHost() {
    var host = null;
    crmDocuments().some(function (doc) {
      host = doc.querySelector('.ui-entity-editor-column-left') ||
        doc.querySelector('.crm-entity-card-container') ||
        doc.querySelector('.crm-entity-section-info') ||
        doc.querySelector('.ui-entity-editor-column');
      return !!host;
    });
    return host;
  }

  function mount(payload) {
    if (isCrmDetailsPage(parseEntity())) {
      return false;
    }
    var host = findHost();
    if (!host) {
      return false;
    }
    var existing = document.getElementById('a7-ci-crm-panel');
    var panel = existing || document.createElement('div');
    panel.id = 'a7-ci-crm-panel';
    panel.className = 'a7-ci-crm-panel';
    panel.innerHTML = renderPanel(payload);
    bindTranscriptButton(panel);
    if (!existing) {
      var firstSection = host.querySelector('.ui-entity-editor-section, .crm-entity-card-widget');
      if (firstSection && firstSection.parentNode === host) {
        host.insertBefore(panel, firstSection.nextSibling);
      } else if (firstSection && firstSection.parentNode) {
        firstSection.parentNode.insertBefore(panel, firstSection.nextSibling);
      } else {
        host.insertBefore(panel, host.firstChild);
      }
    }
    return true;
  }

  function bootPayload(entity) {
    var boot = window.A7_CI_CRM_BOOT;
    if (!boot || !boot.ok || !boot.has_data || !entity) {
      return null;
    }
    if (boot.entity_type && boot.entity_id) {
      if (boot.entity_type !== entity.type || parseInt(boot.entity_id, 10) !== entity.id) {
        return null;
      }
    }
    return boot;
  }

  function isCrmDetailsPage(entity) {
    return !!(entity && (entity.type === 'LEAD' || entity.type === 'CONTACT'));
  }

  function hideCallRecordingSection(doc) {
    Array.prototype.forEach.call(
      doc.querySelectorAll('.ui-entity-editor-section, .crm-entity-card-widget'),
      function (section) {
        // Portal lead "Other fields" keeps Call Recording visible there.
        if (section.getAttribute('data-a7-plf') === 'other' || section.getAttribute('data-a7-keep') === '1') {
          return;
        }
        if (section.getAttribute('data-a7-hidden') === 'call-recording') {
          return;
        }
        var titleEl = section.querySelector(
          '.ui-entity-editor-header-title, .ui-entity-editor-header-title-text, .ui-entity-editor-section-title, .crm-entity-card-widget-title'
        );
        var title = ((titleEl && titleEl.innerText) || '').replace(/\s+/g, ' ').trim();
        var text = (section.innerText || '').replace(/\s+/g, ' ');
        var fieldCount = section.querySelectorAll('.ui-entity-editor-content-block').length;
        var isCallRec = /Call Recording/i.test(text) || /Call Recording/i.test(title);
        var isNewSection = /NEW SECTION/i.test(title);
        if (isCallRec && (isNewSection || fieldCount <= 2)) {
          section.style.display = 'none';
          section.setAttribute('data-a7-hidden', 'call-recording');
        }
        if (/Client Requirements/i.test(title)) {
          section.style.display = 'none';
          section.setAttribute('data-a7-hidden', 'ai-fields');
        }
      }
    );
  }

  function cleanCrmExtras() {
    if (!isCrmDetailsPage(parseEntity())) {
      return;
    }
    crmDocuments().forEach(function (doc) {
      var panel = doc.getElementById('a7-ci-crm-panel');
      if (panel && panel.parentNode) {
        panel.parentNode.removeChild(panel);
      }
      hideCallRecordingSection(doc);
    });
  }

  function scheduleMount(payload) {
    if (!payload || !payload.ok || !payload.has_data) {
      return;
    }
    if (isCrmDetailsPage(parseEntity())) {
      return;
    }
    if (mount(payload)) {
      return;
    }
    var tries = 0;
    var timer = window.setInterval(function () {
      tries += 1;
      if (mount(payload) || tries >= 80) {
        window.clearInterval(timer);
      }
    }, 50);
  }

  function fetchPanel(entity) {
    var body = new URLSearchParams();
    body.set('action', 'crm_panel');
    body.set('entity_type', entity.type);
    body.set('entity_id', String(entity.id));
    body.set('sessid', sessid());
    fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      scheduleMount(payload);
    }).catch(function () {
      return null;
    });
  }

  function digits(value) {
    return String(value == null ? '' : value).replace(/\D+/g, '');
  }

  function isBusy(row) {
    var status = row && row.ai_status ? row.ai_status : '';
    if (row && row.waiting_recording) {
      return true;
    }
    if (status === 'PENDING' || status === 'TRANSCRIBING' || status === 'ANALYZING') {
      return true;
    }
    return !!(row && row.awaiting_auto && status !== 'COMPLETED' && status !== 'FAILED');
  }

  function conversationTone(row) {
    if (!row || row.ai_status !== 'COMPLETED' || row.ai_overall_score == null) {
      return '';
    }
    return scoreTone(row.ai_overall_score);
  }

  function dotHtml(tone) {
    if (!tone) {
      return '';
    }
    return '<span class="a7-ci-dot a7-ci-dot-' + tone + '" title="' + escapeHtml(tone) + '"></span>';
  }

  function statusHtml(row) {
    var status = row && row.ai_status ? row.ai_status : '';
    if (row && row.waiting_recording) {
      return '<span class="a7-ci-status">Waiting for recording</span>';
    }
    if (status === 'PENDING' || (row && row.awaiting_auto && !status)) {
      return '<span class="a7-ci-status">Pending</span>';
    }
    if (status === 'TRANSCRIBING') {
      return '<span class="a7-ci-status a7-ci-busy">Transcribing...</span>';
    }
    if (status === 'ANALYZING') {
      return '<span class="a7-ci-status a7-ci-busy">Analyzing...</span>';
    }
    if (status === 'FAILED') {
      return '<span class="a7-ci-status a7-ci-failed">Failed</span>';
    }
    return '';
  }

  function viewDetailsLink() {
    return '<a href="#" class="a7-ci-btn a7-ci-btn-details" data-a7-ci="details">View details</a>';
  }

  function commentAiHtml(data) {
    if (data && data.waiting_recording) {
      return '<div class="a7-ci-comment-ai"><span class="a7-ci-status">Waiting for recording</span></div>';
    }
    if (data && data.ai_status === 'COMPLETED') {
      var score = data.ai_overall_score != null ? String(data.ai_overall_score) + '/100' : '—';
      return '<div class="a7-ci-comment-ai">' +
        '<span class="a7-ci-score-wrap">' + dotHtml(conversationTone(data)) +
        '<span class="a7-ci-score">AI Score ' + escapeHtml(score) + '</span></span>' +
        viewDetailsLink() +
        '</div>';
    }
    if (data && data.ai_status === 'FAILED') {
      return '<div class="a7-ci-comment-ai">' +
        '<span class="a7-ci-status a7-ci-failed">AI failed</span>' +
        viewDetailsLink() +
        '</div>';
    }
    if (isBusy(data) || (data && data.awaiting_auto)) {
      return '<div class="a7-ci-comment-ai">' +
        (statusHtml(data) || '<span class="a7-ci-status">Analyzing...</span>') +
        viewDetailsLink() +
        '</div>';
    }
    return '<div class="a7-ci-comment-ai">' + viewDetailsLink() + '</div>';
  }

  function detailsCopyText(data) {
    if (!data) {
      return '';
    }
    var action = ACTION_LABELS[data.next_action_type] || data.next_action_type || '—';
    var when = [formatDate(data.next_action_date), formatTime(data.next_action_time)].filter(Boolean).join(' · ');
    var score = data.ai_overall_score != null ? String(data.ai_overall_score) + '/100' : '—';
    return 'AI Score: ' + score +
      '\n\nCall Summary:\n' + (data.ai_call_summary || '—') +
      '\n\nNext Action:\n' + action + (when ? ' (' + when + ')' : '');
  }

  function scoreHint(tone, score) {
    if (score == null) {
      return 'Not scored yet';
    }
    if (tone === 'green') {
      return 'Strong call quality';
    }
    if (tone === 'blue') {
      return 'Average call quality';
    }
    return 'Needs improvement';
  }

  function detailsBodyHtml(data) {
    var rawScore = data && data.ai_overall_score != null ? parseInt(data.ai_overall_score, 10) : null;
    if (rawScore != null && isNaN(rawScore)) {
      rawScore = null;
    }
    var tone = scoreTone(rawScore);
    var ringScore = rawScore != null ? Math.max(0, Math.min(100, rawScore)) : 0;
    var action = ACTION_LABELS[(data && data.next_action_type) || ''] || (data && data.next_action_type) || '—';
    var when = [formatDate(data && data.next_action_date), formatTime(data && data.next_action_time)].filter(Boolean).join(' · ');
    var summary = escapeHtml((data && data.ai_call_summary) || '—').replace(/\n/g, '<br>');
    return '<div class="a7-ci-sheet">' +
      '<div class="a7-ci-sheet-head">' +
        '<div class="a7-ci-sheet-kicker">Call Intelligence</div>' +
        '<div class="a7-ci-sheet-title">Call details</div>' +
        '<div class="a7-ci-sheet-sub">From this recording only</div>' +
      '</div>' +
      '<div class="a7-ci-sheet-body">' +
        '<div class="a7-ci-sheet-score">' +
          '<div class="a7-ci-sheet-ring a7-ci-sheet-ring-' + escapeHtml(tone || 'empty') +
            '" style="--score:' + ringScore + '" aria-label="AI Score ' +
            escapeHtml(rawScore != null ? String(rawScore) + ' out of 100' : 'not scored') + '">' +
            '<div class="a7-ci-sheet-ring-inner">' +
              '<strong>' + escapeHtml(rawScore != null ? String(rawScore) : '—') + '</strong>' +
              (rawScore != null ? '<span>/100</span>' : '') +
            '</div>' +
          '</div>' +
          '<div class="a7-ci-sheet-score-copy">' +
            '<div class="a7-ci-sheet-label">AI Score</div>' +
            '<div class="a7-ci-sheet-score-hint">' + escapeHtml(scoreHint(tone, rawScore)) + '</div>' +
          '</div>' +
        '</div>' +
        '<section class="a7-ci-sheet-card">' +
          '<div class="a7-ci-sheet-label">Call Summary</div>' +
          '<p class="a7-ci-sheet-text">' + summary + '</p>' +
        '</section>' +
        '<section class="a7-ci-sheet-card a7-ci-sheet-card-action">' +
          '<div class="a7-ci-sheet-label">Next Action</div>' +
          '<div class="a7-ci-sheet-action">' + escapeHtml(action) + '</div>' +
          (when ? '<div class="a7-ci-sheet-when">' + escapeHtml(when) + '</div>' : '') +
        '</section>' +
      '</div>' +
    '</div>';
  }

  function showBxPopup(id, content, copyText, maxWidth) {
    if (window.BX && BX.PopupWindow) {
      var popup = new BX.PopupWindow(id, null, {
        className: 'a7-ci-overlay-popup',
        content: content,
        closeIcon: true,
        closeByEsc: true,
        autoHide: true,
        maxWidth: maxWidth || 760,
        overlay: { backgroundColor: '#102040', opacity: 55 },
        buttons: [
          new BX.PopupWindowButton({
            text: 'Copy',
            className: 'popup-window-button a7-ci-popup-copy',
            events: {
              click: function () {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(copyText || '');
                }
                this.buttonNode.textContent = 'Copied';
                var btn = this;
                window.setTimeout(function () {
                  btn.buttonNode.textContent = 'Copy';
                }, 1400);
              }
            }
          }),
          new BX.PopupWindowButton({
            text: 'Close',
            className: 'popup-window-button-accept a7-ci-popup-close',
            events: {
              click: function () {
                popup.close();
              }
            }
          })
        ]
      });
      popup.show();
      return;
    }
    window.alert(copyText || '-');
  }

  function detailsLoadingHtml(message) {
    return '<div class="a7-ci-sheet">' +
      '<div class="a7-ci-sheet-head">' +
        '<div class="a7-ci-sheet-kicker">Call Intelligence</div>' +
        '<div class="a7-ci-sheet-title">Call details</div>' +
        '<div class="a7-ci-sheet-sub">From this recording only</div>' +
      '</div>' +
      '<div class="a7-ci-sheet-body">' +
        '<div class="a7-ci-sheet-loading">' +
          '<div class="a7-ci-sheet-spin" aria-hidden="true"></div>' +
          '<div class="a7-ci-sheet-loading-title">Analyzing…</div>' +
          '<div class="a7-ci-sheet-loading-text">' +
            escapeHtml(message || 'Listening to this recording and preparing the score, summary, and next action.') +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function detailsErrorHtml(message) {
    return '<div class="a7-ci-sheet">' +
      '<div class="a7-ci-sheet-head">' +
        '<div class="a7-ci-sheet-kicker">Call Intelligence</div>' +
        '<div class="a7-ci-sheet-title">Call details</div>' +
      '</div>' +
      '<div class="a7-ci-sheet-body">' +
        '<section class="a7-ci-sheet-card">' +
          '<div class="a7-ci-sheet-label">Could not analyze</div>' +
          '<p class="a7-ci-sheet-text">' + escapeHtml(message || 'Try again in a moment.') + '</p>' +
        '</section>' +
      '</div>' +
    '</div>';
  }

  function findRow(id) {
    var found = null;
    timelineRows.forEach(function (row) {
      if (row && parseInt(row.statistic_id, 10) === id) {
        found = row;
      }
    });
    return found;
  }

  function mergeRow(id, incoming) {
    var merged = Object.assign({}, findRow(id) || {}, incoming || {}, { statistic_id: id });
    var replaced = false;
    timelineRows = timelineRows.map(function (row) {
      if (row && parseInt(row.statistic_id, 10) === id) {
        replaced = true;
        return merged;
      }
      return row;
    });
    if (!replaced) {
      timelineRows.push(merged);
    }
    return merged;
  }

  function showDetailsPopup(data, mode) {
    var html = mode === 'loading'
      ? detailsLoadingHtml()
      : (mode === 'error' ? detailsErrorHtml((data && data.error) || '') : detailsBodyHtml(data || {}));
    var copyText = mode === 'ready' || !mode ? detailsCopyText(data) : '';
    if (detailsPopup && detailsPopup.setContent) {
      try {
        detailsPopup.setContent(html);
        detailsPopup._a7Copy = copyText;
        return detailsPopup;
      } catch (err) {}
    }
    if (window.BX && BX.PopupWindow) {
      detailsPopup = new BX.PopupWindow('a7-ci-crm-details-live', null, {
        className: 'a7-ci-crm-sheet',
        content: html,
        closeIcon: true,
        closeByEsc: true,
        autoHide: true,
        maxWidth: 540,
        overlay: { backgroundColor: '#0b1524', opacity: 62 },
        events: {
          onPopupClose: function () {
            detailsPopup = null;
          }
        },
        buttons: [
          new BX.PopupWindowButton({
            text: 'Copy',
            className: 'popup-window-button a7-ci-popup-copy',
            events: {
              click: function () {
                var text = (detailsPopup && detailsPopup._a7Copy) || copyText || '';
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(text);
                }
                this.buttonNode.textContent = 'Copied';
                var btn = this;
                window.setTimeout(function () {
                  btn.buttonNode.textContent = 'Copy';
                }, 1400);
              }
            }
          }),
          new BX.PopupWindowButton({
            text: 'Close',
            className: 'popup-window-button-accept a7-ci-popup-close',
            events: {
              click: function () {
                if (detailsPopup) {
                  detailsPopup.close();
                }
              }
            }
          })
        ]
      });
      detailsPopup._a7Copy = copyText;
      detailsPopup.show();
      return detailsPopup;
    }
    showBxPopup('a7-ci-crm-details-live', html, copyText, 540);
    return null;
  }

  function applyReady(id, incoming) {
    var merged = mergeRow(id, incoming);
    injectTimelineWidgets(timelineRows);
    var ready = merged.ai_status === 'COMPLETED' || merged.ai_status === 'FAILED';
    if (!ready) {
      return false;
    }
    // Only refresh the popup while the user still has it open. If they closed it
    // (detailsPopup is null after onPopupClose), just update the card; the popup
    // must reappear only when they click View details again.
    if (!detailsPopup) {
      return true;
    }
    if (merged.ai_status === 'COMPLETED') {
      showDetailsPopup(merged, 'ready');
    } else {
      showDetailsPopup({ error: 'Analysis failed. Click View details to try again.' }, 'error');
    }
    return true;
  }

  function fetchDetail(id) {
    var body = new URLSearchParams();
    body.set('action', 'detail');
    body.set('id', String(id));
    body.set('sessid', sessid());
    return fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      if (!payload || !payload.ok || !payload.row) {
        return null;
      }
      return payload.row;
    }).catch(function () {
      return null;
    });
  }

  function requestAnalyze(id, force) {
    if (analyzeLocks[id]) {
      return analyzeLocks[id];
    }
    var body = new URLSearchParams();
    body.set('action', 'analyze');
    body.set('id', String(id));
    if (force) {
      body.set('force', '1');
    }
    body.set('sessid', sessid());
    analyzeLocks[id] = fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      return payload;
    }).catch(function () {
      return null;
    }).then(function (payload) {
      delete analyzeLocks[id];
      return payload;
    });
    return analyzeLocks[id];
  }

  function pollUntilReady(id, tries) {
    tries = tries || 0;
    if (tries > 40) {
      if (detailsPopup) {
        showDetailsPopup({ error: 'Still working. Close this and try View details again in a minute.' }, 'error');
      }
      return;
    }
    window.setTimeout(function () {
      fetchDetail(id).then(function (row) {
        if (row && applyReady(id, row)) {
          return;
        }
        pollUntilReady(id, tries + 1);
      });
    }, tries < 4 ? 2000 : 4000);
  }

  function openRecordingDetails(id) {
    if (!(id > 0)) {
      showDetailsPopup({ error: 'This recording is not linked yet. Refresh the page and try again.' }, 'error');
      return;
    }
    var cached = findRow(id);
    if (cached && cached.ai_status === 'COMPLETED') {
      showDetailsPopup(cached, 'ready');
      fetchDetail(id).then(function (row) {
        if (row) {
          applyReady(id, row);
        }
      });
      return;
    }
    showDetailsPopup(cached, 'loading');
    requestAnalyze(id, !!(cached && cached.ai_status === 'FAILED')).then(function (payload) {
      if (payload && payload.ok && payload.row && applyReady(id, payload.row)) {
        return;
      }
      if (payload && payload.ok === false) {
        if (detailsPopup) {
          showDetailsPopup({ error: payload.error || 'Could not start analysis.' }, 'error');
        }
        return;
      }
      pollUntilReady(id, 0);
    });
  }

  function bindTimelineWidget(wrap, data) {
    var link = wrap.querySelector('.a7-ci-btn-details');
    if (!link || link.getAttribute('data-a7-bound') === '1') {
      return;
    }
    link.setAttribute('data-a7-bound', '1');
    link.addEventListener('click', function (event) {
      event.preventDefault();
      event.stopPropagation();
      var id = parseInt(wrap.getAttribute('data-a7-stat') || (data && data.statistic_id) || '0', 10);
      var timelineId = parseInt(wrap.getAttribute('data-a7-timeline') || (data && data.timeline_id) || '0', 10);
      if (!(id > 0) && timelineId > 0) {
        var hit = null;
        timelineRows.forEach(function (row) {
          if (row && parseInt(row.timeline_id, 10) === timelineId) {
            hit = row;
          }
        });
        if (hit) {
          id = parseInt(hit.statistic_id, 10);
        }
      }
      openRecordingDetails(id);
    });
  }

  function findPlayerBox(card) {
    return card.querySelector('.crm-audio-player-container') ||
      card.querySelector('.ui-vue-audioplayer-container') ||
      card.querySelector('.ui-vue-audioplayer-controls-container') ||
      card.querySelector('.ui-vue-audioplayer') ||
      card.querySelector('audio');
  }

  function cardTimelineId(card) {
    var el = card;
    var i;
    for (i = 0; i < 6 && el; i++) {
      var id = parseInt(el.getAttribute && el.getAttribute('data-id') || '0', 10);
      if (id > 0) {
        return id;
      }
      el = el.parentElement;
    }
    return 0;
  }

  function findAudioCards() {
    var cards = [];
    var seen = {};
    crmDocuments().forEach(function (doc) {
      var nodes = doc.querySelectorAll(
        '.crm-timeline__card .crm-audio-player-container, ' +
        '.crm-timeline__card .ui-vue-audioplayer-controls-container, ' +
        '.crm-timeline__card .ui-vue-audioplayer-container, ' +
        '.crm-timeline__card audio, ' +
        '.crm-entity-stream-section audio, ' +
        '.crm-timeline-card audio, ' +
        '.crm-timeline__card [class*="audioplayer"], ' +
        '.crm-entity-stream-section [class*="audioplayer"]'
      );
      Array.prototype.forEach.call(nodes, function (el) {
        // 3CX click-to-call recordings render their own card (with their own AI score) and mark it
        // with a7-3cx-ignore so other A7 scripts leave it alone. They are not telephony statistic rows.
        if (el.closest('.a7-3cx-ignore, .a7-3cx-recording-card')) {
          return;
        }
        var card = el.closest('.crm-timeline__card') ||
          el.closest('.crm-timeline__card-wrapper') ||
          el.closest('.crm-entity-stream-section') ||
          el.closest('.crm-timeline-card') ||
          el.closest('[data-id]');
        if (!card) {
          return;
        }
        var key = card.getAttribute('data-id') || card.getAttribute('data-a7-key');
        if (!key) {
          key = 'n' + cards.length;
          card.setAttribute('data-a7-key', key);
        }
        if (seen[key]) {
          return;
        }
        seen[key] = true;
        cards.push(card);
      });
    });
    return cards;
  }

  function audioSrc(card) {
    var audio = card.querySelector('audio');
    if (!audio) {
      return '';
    }
    return audio.getAttribute('src') || audio.currentSrc || '';
  }

  function matchRow(card, rows, used) {
    var timelineId = cardTimelineId(card);
    var i;
    var row;
    if (timelineId > 0) {
      for (i = 0; i < rows.length; i++) {
        row = rows[i];
        if (!used[row.statistic_id] && parseInt(row.timeline_id, 10) === timelineId) {
          return row;
        }
      }
    }
    var src = audioSrc(card);
    if (src) {
      for (i = 0; i < rows.length; i++) {
        row = rows[i];
        if (used[row.statistic_id]) {
          continue;
        }
        var url = String(row.call_record_url || '');
        var recId = String(row.call_record_id || '');
        if (url && src.indexOf(url) !== -1) {
          return row;
        }
        if (recId && recId !== '0' && src.indexOf('/' + recId) !== -1) {
          return row;
        }
      }
    }
    var text = digits(card.textContent);
    var phoneHits = [];
    for (i = 0; i < rows.length; i++) {
      row = rows[i];
      if (used[row.statistic_id]) {
        continue;
      }
      var phone = row.phone_digits || digits(row.phone_number);
      if (phone && phone.length >= 8 && text.indexOf(phone) !== -1) {
        phoneHits.push(row);
      }
    }
    if (phoneHits.length === 1) {
      return phoneHits[0];
    }
    if (phoneHits.length > 1) {
      return phoneHits[0];
    }
    return null;
  }

  function injectTimelineWidgets(rows) {
    rows = rows || timelineRows;
    var cards = findAudioCards();
    var used = {};
    var injected = 0;
    cards.forEach(function (card) {
      var player = findPlayerBox(card);
      if (!player || !player.parentNode) {
        return;
      }
      var row = matchRow(card, rows, used);
      if (row && row.statistic_id) {
        used[row.statistic_id] = true;
      } else {
        row = {
          statistic_id: 0,
          timeline_id: cardTimelineId(card),
          has_recording: true
        };
      }
      var wrap = card.querySelector('.a7-ci-timeline-ai');
      if (!wrap) {
        wrap = card.ownerDocument.createElement('div');
        wrap.className = 'a7-ci-timeline-ai';
        player.parentNode.insertBefore(wrap, player);
      }
      var stamp = String(row.statistic_id || 0) + ':' + (row.ai_status || '') + ':' +
        String(row.ai_overall_score == null ? '' : row.ai_overall_score);
      wrap.setAttribute('data-a7-stat', String(row.statistic_id || 0));
      if (row.timeline_id) {
        wrap.setAttribute('data-a7-timeline', String(row.timeline_id));
      }
      if (wrap.getAttribute('data-a7-stamp') !== stamp) {
        wrap.setAttribute('data-a7-stamp', stamp);
        wrap.innerHTML = commentAiHtml(row);
      }
      bindTimelineWidget(wrap, row);
      injected += 1;
    });
    injected += injectThreeCxWidgets(rows);
    return injected;
  }

  // 3CX click-to-call cards (a7_3cx_click_to_call.js) show the same recording as the native
  // telephony card. When that recording is linked to a telephony statistic row, show the
  // Call Intelligence widget on the 3CX card too and hide its own (offline) "AI score" row.
  function threeCxCards() {
    var cards = [];
    crmDocuments().forEach(function (doc) {
      Array.prototype.forEach.call(doc.querySelectorAll('.a7-3cx-recording-card[data-recording-id]'), function (card) {
        cards.push(card);
      });
    });
    return cards;
  }

  function threeCxRow(card, rows) {
    var recId = String(card.getAttribute('data-recording-id') || '').replace(/\D/g, '');
    if (!recId) {
      return null;
    }
    var pattern = new RegExp('(^|/)' + recId + '\\.(wav|mp3|m4a|ogg)(\\?|$)', 'i');
    var i;
    for (i = 0; i < (rows || []).length; i++) {
      var url = String(rows[i].call_record_url || '');
      if (url && pattern.test(url.split('?')[0] + '?')) {
        return rows[i];
      }
    }
    return null;
  }

  function injectThreeCxWidgets(rows) {
    var injected = 0;
    threeCxCards().forEach(function (card) {
      var row = threeCxRow(card, rows);
      if (!row || !row.statistic_id) {
        return;
      }
      var player = card.querySelector('.a7-3cx-recording-player') || card.querySelector('.a7-3cx-recording-native-audio');
      if (!player || !player.parentNode) {
        return;
      }
      var scoreRow = card.querySelector('.a7-3cx-recording-score-row');
      if (scoreRow && scoreRow.getAttribute('data-a7-ci-replaced') !== '1') {
        scoreRow.setAttribute('data-a7-ci-replaced', '1');
        scoreRow.style.display = 'none';
      }
      var wrap = card.querySelector('.a7-ci-timeline-ai');
      if (!wrap) {
        wrap = card.ownerDocument.createElement('div');
        wrap.className = 'a7-ci-timeline-ai a7-ci-timeline-ai-3cx';
        player.parentNode.insertBefore(wrap, player);
      }
      var stamp = String(row.statistic_id || 0) + ':' + (row.ai_status || '') + ':' +
        String(row.ai_overall_score == null ? '' : row.ai_overall_score);
      wrap.setAttribute('data-a7-stat', String(row.statistic_id || 0));
      if (row.timeline_id) {
        wrap.setAttribute('data-a7-timeline', String(row.timeline_id));
      }
      if (wrap.getAttribute('data-a7-stamp') !== stamp) {
        wrap.setAttribute('data-a7-stamp', stamp);
        wrap.innerHTML = commentAiHtml(row);
      }
      bindTimelineWidget(wrap, row);
      injected += 1;
    });
    return injected;
  }

  function cardsNeedWidget() {
    var native = findAudioCards().some(function (card) {
      return !card.querySelector('.a7-ci-timeline-ai');
    });
    if (native) {
      return true;
    }
    return threeCxCards().some(function (card) {
      return !card.querySelector('.a7-ci-timeline-ai') && !!threeCxRow(card, timelineRows);
    });
  }

  function scheduleInjectRetries() {
    if (injectRetryTimer) {
      return;
    }
    var tries = 0;
    injectRetryTimer = window.setInterval(function () {
      tries += 1;
      injectTimelineWidgets(timelineRows);
      if ((!cardsNeedWidget() && timelineRows.length) || tries >= 12) {
        window.clearInterval(injectRetryTimer);
        injectRetryTimer = 0;
      }
    }, 700);
  }

  function anyBusy(rows) {
    return (rows || []).some(function (row) {
      return isBusy(row);
    });
  }

  function scheduleTimelinePoll() {
    if (timelineTimer) {
      return;
    }
    timelineTimer = window.setInterval(function () {
      var entity = parseEntity();
      if (!entity) {
        return;
      }
      if (!anyBusy(timelineRows) && !cardsNeedWidget() && document.querySelectorAll('.a7-ci-timeline-ai').length) {
        return;
      }
      fetchCalls(entity, true);
    }, 8000);
  }

  function fetchCalls(entity, silent) {
    if (timelinePending) {
      return;
    }
    timelinePending = true;
    var body = new URLSearchParams();
    body.set('action', 'crm_calls');
    body.set('entity_type', entity.type);
    body.set('entity_id', String(entity.id));
    body.set('sessid', sessid());
    fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      timelinePending = false;
      if (!payload || !payload.ok || !payload.rows) {
        return;
      }
      timelineRows = payload.rows;
      injectTimelineWidgets(timelineRows);
      scheduleInjectRetries();
      if (!silent) {
        scheduleTimelinePoll();
      }
    }).catch(function () {
      timelinePending = false;
    });
  }

  function load() {
    var entity = parseEntity();
    if (!entity) {
      return;
    }
    cleanCrmExtras();
    fetchCalls(entity, false);
  }

  if (window.A7_CI_CRM_OWNED) {
    // Already running in this window (double include). Do not start a second instance.
    return;
  }
  if (parseEntity()) {
    // This window is a Lead/Contact details page (top page or slider iframe): own it,
    // so a parent page running this script leaves this document alone.
    window.A7_CI_CRM_OWNED = true;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
  if (window.BX && BX.addCustomEvent) {
    BX.addCustomEvent('SidePanel.Slider:onLoad', function () {
      load();
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
        var entity = parseEntity();
        if (isCrmDetailsPage(entity)) {
          cleanCrmExtras();
        }
        if (entity && timelineRows.length) {
          injectTimelineWidgets(timelineRows);
        }
      }, 200);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
})();
