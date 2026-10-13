(function () {
  'use strict';

  var GRID_ID = 'voximplant_statistic_detail';
  var COLUMNS = [];
  var STALE_COLUMNS = ['A7_AI_SCORE', 'A7_CALL_SUMMARY', 'A7_NEXT_ACTION', 'A7_TRANSCRIPT'];
  var ACTION_LABELS = {
    PROPERTY_VIEWING: 'Property Viewing',
    CALLBACK: 'Callback',
    FOLLOW_UP: 'Follow-up Required',
    SEND_PROPERTY_OPTIONS: 'Send Property Options',
    SEND_DETAILS: 'Send Details',
    NO_ACTION: 'No Action Required'
  };

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

  var autoStarted = {};
  var rowCache = {};
  var analyzeQueue = [];
  var analyzeActive = false;
  var DISK_KEY = 'a7ci_completed_v1';

  function readDisk() {
    try {
      var raw = window.localStorage.getItem(DISK_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (err) {
      return {};
    }
  }

  function writeDiskRow(id, data) {
    if (!id || !data || data.ai_status !== 'COMPLETED') {
      return;
    }
    try {
      var all = readDisk();
      all[String(id)] = {
        ai_status: 'COMPLETED',
        ai_overall_score: data.ai_overall_score,
        ai_call_summary: data.ai_call_summary || '',
        comment_line: data.comment_line || '',
        next_action_type: data.next_action_type || '',
        next_action_date: data.next_action_date || '',
        next_action_time: data.next_action_time || '',
        next_action_confidence: data.next_action_confidence,
        has_transcript: !!data.has_transcript,
        is_new: !!data.is_new,
        awaiting_auto: false,
        can_analyze: false
      };
      var keys = Object.keys(all);
      if (keys.length > 400) {
        keys.slice(0, keys.length - 400).forEach(function (key) {
          delete all[key];
        });
      }
      window.localStorage.setItem(DISK_KEY, JSON.stringify(all));
      window.sessionStorage.setItem('a7ci_done_' + id, '1');
    } catch (err) {
      return;
    }
  }

  function cachedCompleted(id) {
    if (!id) {
      return null;
    }
    var mem = rowCache[String(id)];
    if (mem && mem.ai_status === 'COMPLETED') {
      return mem;
    }
    var disk = readDisk()[String(id)];
    return disk && disk.ai_status === 'COMPLETED' ? disk : null;
  }

  function rememberRow(id, data) {
    if (!id || !data) {
      return;
    }
    var key = String(id);
    var prev = rowCache[key] || cachedCompleted(id) || {};
    if (prev.ai_status === 'COMPLETED' && data.ai_status && data.ai_status !== 'COMPLETED') {
      return;
    }
    rowCache[key] = Object.assign({}, prev, data);
    if (rowCache[key].ai_status === 'COMPLETED') {
      autoStarted[id] = 'done';
      writeDiskRow(id, rowCache[key]);
    }
  }

  function alreadyDone(id) {
    if (!id) {
      return false;
    }
    if (autoStarted[id] === 'done' || cachedCompleted(id)) {
      return true;
    }
    try {
      return window.sessionStorage.getItem('a7ci_done_' + id) === '1';
    } catch (err) {
      return false;
    }
  }

  function hydrateCache() {
    var all = readDisk();
    Object.keys(all).forEach(function (id) {
      if (all[id] && all[id].ai_status === 'COMPLETED') {
        rowCache[id] = all[id];
        autoStarted[id] = 'done';
      }
    });
  }

  hydrateCache();

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

  function shouldShowAnalyze(row) {
    if (!row) {
      return true;
    }
    if (row.needs_reanalyze || row.ai_status === 'FAILED') {
      return true;
    }
    if (row.ai_status === 'COMPLETED') {
      return false;
    }
    if (row.is_new || row.awaiting_auto) {
      return false;
    }
    return row.ai_status !== 'TRANSCRIBING' && row.ai_status !== 'ANALYZING';
  }

  function conversationTone(row) {
    if (!row || row.ai_status !== 'COMPLETED' || row.ai_overall_score == null) {
      return '';
    }
    var score = Number(row.ai_overall_score);
    if (score >= 70) {
      return 'green';
    }
    if (score >= 40) {
      return 'blue';
    }
    return 'red';
  }

  function actionTone(row) {
    var type = row && row.next_action_type ? row.next_action_type : '';
    if (type === 'FOLLOW_UP' || type === 'CALLBACK') {
      return 'red';
    }
    if (type === 'PROPERTY_VIEWING' || type === 'NO_ACTION') {
      return 'green';
    }
    if (type === 'SEND_PROPERTY_OPTIONS' || type === 'SEND_DETAILS') {
      return 'blue';
    }
    return conversationTone(row);
  }

  function dotHtml(tone) {
    if (!tone) {
      return '';
    }
    return '<span class="a7-ci-dot a7-ci-dot-' + tone + '" title="' + escapeHtml(tone) + '"></span>';
  }

  function analyzeButtonHtml(label) {
    return '<button type="button" class="a7-ci-analyze" data-a7-ci="analyze">' +
      escapeHtml(label || 'Analyze') + '</button>';
  }

  function rowHasRecording(row, data) {
    if (data && (data.has_recording || data.ai_status === 'COMPLETED')) {
      return true;
    }
    if (!row) {
      return false;
    }
    var cell = row.querySelector(
      '[data-name="RECORD"], [data-name="CALL_RECORD"], [data-name="RECORDFILE"], [data-name="CALL_RECORD_ID"]'
    );
    if (!cell) {
      return false;
    }
    if (cell.querySelector('audio, source, a[href], button, .ui-icon, .im-phone-call-icon')) {
      return true;
    }
    var text = (cell.textContent || '').replace(/\s+/g, ' ').trim();
    return text !== '' && text !== '-' && text.toLowerCase() !== 'n/a';
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

  function scoreHtml(row) {
    if (row && row.needs_reanalyze) {
      return analyzeButtonHtml('Retry AI');
    }
    if (row && row.ai_status === 'COMPLETED' && row.ai_overall_score != null) {
      return '<span class="a7-ci-score-wrap">' + dotHtml(conversationTone(row)) +
        '<span class="a7-ci-score">' + escapeHtml(row.ai_overall_score) + '/100</span></span>';
    }
    if (shouldShowAnalyze(row)) {
      return analyzeButtonHtml(row && row.ai_status === 'FAILED' ? 'Retry AI' : 'Analyze');
    }
    if (isBusy(row)) {
      return statusHtml(row) || '<span class="a7-ci-status">Pending</span>';
    }
    return statusHtml(row) || '<span class="a7-ci-empty">-</span>';
  }

  function viewButtonHtml(kind, label, text) {
    var extra = text ? ' data-a7-text="' + escapeHtml(text) + '"' : '';
    return '<a href="#" class="a7-ci-btn a7-ci-btn-' + kind + '" data-a7-ci="' + kind + '"' + extra + '>' +
      '<span class="a7-ci-btn-ic" aria-hidden="true"></span>' +
      '<span>' + escapeHtml(label) + '</span></a>';
  }

  function summaryHtml(row) {
    if (row && row.ai_status === 'COMPLETED' && row.ai_call_summary) {
      return '<span class="a7-ci-summary-wrap">' + dotHtml(conversationTone(row)) +
        viewButtonHtml('summary', 'Summary', row.ai_call_summary) + '</span>';
    }
    if (shouldShowAnalyze(row)) {
      return '<span class="a7-ci-empty">-</span>';
    }
    return statusHtml(row) || '<span class="a7-ci-empty">-</span>';
  }

  function nextActionHtml(row) {
    if (!row || row.ai_status !== 'COMPLETED' || !row.next_action_type) {
      if (shouldShowAnalyze(row)) {
        return '<span class="a7-ci-empty">-</span>';
      }
      return statusHtml(row) || '<span class="a7-ci-empty">-</span>';
    }
    var label = ACTION_LABELS[row.next_action_type] || row.next_action_type;
    var extra = [];
    if (row.next_action_date) {
      extra.push(formatDate(row.next_action_date));
    }
    if (row.next_action_time) {
      extra.push(formatTime(row.next_action_time));
    }
    return '<div class="a7-ci-next">' +
      (extra.length ? '<div class="a7-ci-next-meta">' + extra.map(escapeHtml).join('<br>') + '</div>' : '') +
      '<div class="a7-ci-next-line">' + dotHtml(actionTone(row)) +
      '<strong>' + escapeHtml(label) + '</strong></div></div>';
  }

  function transcriptHtml(row) {
    var parts = [];
    if (row && row.has_transcript) {
      parts.push(viewButtonHtml('transcript', 'Transcript'));
    }
    if (shouldShowAnalyze(row)) {
      parts.push(analyzeButtonHtml(row && row.ai_status === 'FAILED' ? 'Retry AI' : 'Analyze'));
    } else if (row && row.needs_reanalyze) {
      parts.push(analyzeButtonHtml('Retry AI'));
    } else if (!row || !row.has_transcript) {
      var status = statusHtml(row);
      if (status) {
        parts.push(status);
      }
    }
    if (!parts.length) {
      return '<span class="a7-ci-empty">-</span>';
    }
    return '<span class="a7-ci-transcript-cell">' + parts.join(' ') + '</span>';
  }

  function cellHtml(columnId, row) {
    return transcriptHtml(row);
  }

  function cellList(row) {
    return Array.prototype.filter.call(row.children, function (el) {
      return el.tagName === 'TD' || el.tagName === 'TH';
    });
  }

  function removeNamedCells(row, names) {
    names.forEach(function (id) {
      var el = namedRowCell(row, [id]);
      if (el && el.parentNode === row) {
        el.parentNode.removeChild(el);
      }
    });
  }

  function removeOurCells(row) {
    removeNamedCells(row, COLUMNS.map(function (column) { return column.id; }));
    removeNamedCells(row, STALE_COLUMNS);
  }

  function fillHeadContent(cell, title) {
    var titleNode = cell.querySelector('.main-grid-head-title');
    if (titleNode) {
      titleNode.textContent = title;
      return;
    }
    cell.innerHTML = '<div class="main-grid-cell-inner">' +
      '<span class="main-grid-cell-head-container">' +
      '<span class="main-grid-head-title">' + escapeHtml(title) + '</span>' +
      '</span></div>';
  }

  function fillCell(cell, columnId, data, isHead) {
    if (isHead) {
      var column = COLUMNS.filter(function (item) { return item.id === columnId; })[0];
      fillHeadContent(cell, column ? column.title : columnId);
      return;
    }
    cell.innerHTML = '<div class="main-grid-cell-inner"><span class="main-grid-cell-content">' +
      cellHtml(columnId, data) + '</span></div>';
  }

  function styleOurCell(cell, isHead) {
    cell.classList.add('a7-ci-col');
    cell.classList.remove('main-grid-cell-hidden', 'main-grid-hide');
    cell.style.display = 'table-cell';
    cell.style.visibility = 'visible';
    cell.style.opacity = '1';
    cell.style.minWidth = '118px';
    cell.style.width = '118px';
    cell.style.height = 'auto';
    cell.style.overflow = 'visible';
    if (isHead) {
      cell.style.background = '#d9e6f3';
      cell.style.color = '#1d3348';
      cell.style.fontWeight = '700';
      cell.style.zIndex = '13';
    }
  }

  function commentCells(row) {
    return row.querySelectorAll('[data-name="COMMENT"], [data-name="comment"], [data-name="Comment"]');
  }

  function protectedColumnName(name) {
    name = String(name || '').toUpperCase();
    return name.indexOf('A7_') === 0 ||
      name === 'CRM' || name === 'CRM_ENTITY' || name === 'CLIENT' ||
      name === 'RECORD' || name === 'RECORDFILE' || name === 'CALL_RECORD' ||
      name === 'INCOMING' || name === 'STATUS' || name === 'PHONE_NUMBER' ||
      name === 'COMMENT';
  }

  function isCommentCell(cell) {
    if (!cell) {
      return false;
    }
    var name = (cell.getAttribute('data-name') || '').toUpperCase();
    if (name === 'COMMENT') {
      return true;
    }
    return !!(cell.closest && cell.closest('[data-name="COMMENT"], [data-name="comment"], [data-name="Comment"]'));
  }

  function headerCellTitle(cell) {
    if (!cell) {
      return '';
    }
    var title = cell.querySelector('.main-grid-head-title');
    return ((title && title.textContent) || cell.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
  }

  function commentCellByHeader(row) {
    var table = row && row.closest ? row.closest('table') : null;
    if (!table) {
      return null;
    }
    var head = table.querySelector('tr.main-grid-row-head') || table.querySelector('thead tr');
    if (!head) {
      return null;
    }
    var heads = cellList(head);
    var cells = cellList(row);
    var i;
    for (i = 0; i < heads.length && i < cells.length; i++) {
      var name = (heads[i].getAttribute('data-name') || '').toUpperCase();
      var title = headerCellTitle(heads[i]);
      if (name === 'COMMENT' || title === 'comment' || title === 'comments') {
        return cells[i];
      }
    }
    return null;
  }

  function nativeCommentCell(row) {
    return namedRowCell(row, ['COMMENT', 'comment', 'Comment']) || commentCellByHeader(row);
  }

  function ensureCommentCell(row) {
    var cell = nativeCommentCell(row);
    if (cell) {
      return cell;
    }
    if (!row) {
      return null;
    }
    cell = document.createElement('td');
    cell.className = 'main-grid-cell';
    cell.setAttribute('data-name', 'COMMENT');
    cell.innerHTML = '<div class="main-grid-cell-inner"><span class="main-grid-cell-content"></span></div>';
    var crm = crmCell(row);
    if (crm && crm.parentNode === row && crm.nextSibling) {
      row.insertBefore(cell, crm.nextSibling);
    } else {
      row.appendChild(cell);
    }
    return cell;
  }

  function commentAiHtml(data) {
    if (data && data.ai_status === 'COMPLETED') {
      var score = data.ai_overall_score != null ? String(data.ai_overall_score) + '/100' : '—';
      return '<div class="a7-ci-comment-ai">' +
        '<span class="a7-ci-score-wrap">' + dotHtml(conversationTone(data)) +
        '<span class="a7-ci-score">AI Score ' + escapeHtml(score) + '</span></span>' +
        '<a href="#" class="a7-ci-btn a7-ci-btn-details" data-a7-ci="details">View</a>' +
        '</div>';
    }
    if (data && data.ai_status === 'FAILED') {
      return '<div class="a7-ci-comment-ai"><span class="a7-ci-status a7-ci-failed">AI failed</span></div>';
    }
    if (isBusy(data) || (data && data.awaiting_auto)) {
      return '<div class="a7-ci-comment-ai">' +
        (statusHtml(data) || '<span class="a7-ci-status">Analyzing...</span>') +
        '</div>';
    }
    if (data && data.waiting_recording) {
      return '<div class="a7-ci-comment-ai"><span class="a7-ci-status">Waiting for recording</span></div>';
    }
    return '<div class="a7-ci-comment-ai">' +
      '<span class="a7-ci-score-wrap"><span class="a7-ci-score">AI Score —</span></span>' +
      '<span class="a7-ci-status">Pending</span>' +
      '</div>';
  }

  function enhanceCommentCell(row, data) {
    var cell = ensureCommentCell(row);
    if (!cell) {
      return;
    }
    var html = commentAiHtml(data || {});
    var existing = cell.querySelector('.a7-ci-comment-ai');
    if (existing) {
      existing.outerHTML = html;
      return;
    }
    var inner = cell.querySelector('.main-grid-cell-content') ||
      cell.querySelector('.main-grid-cell-inner') ||
      cell;
    inner.insertAdjacentHTML('beforeend', html);
  }

  function namedRowCell(row, names) {
    var cells = cellList(row);
    var upper = names.map(function (name) { return String(name).toUpperCase(); });
    var i;
    for (i = 0; i < cells.length; i++) {
      if (upper.indexOf((cells[i].getAttribute('data-name') || '').toUpperCase()) !== -1) {
        return cells[i];
      }
    }
    for (i = 0; i < names.length; i++) {
      var inner = row.querySelector('[data-name="' + names[i] + '"]');
      if (!inner) {
        continue;
      }
      var td = inner.closest('td, th');
      if (td && td.parentNode === row) {
        return td;
      }
    }
    return null;
  }

  function crmCell(row) {
    return namedRowCell(row, ['CRM', 'CRM_ENTITY', 'CLIENT']);
  }

  function ourTranscriptCell(row) {
    return namedRowCell(row, ['A7_TRANSCRIPT']);
  }

  function pullLeakedTranscript(row) {
    var crm = crmCell(row);
    if (!crm) {
      return;
    }
    crm.querySelectorAll('.a7-ci-col, .a7-ci-transcript-cell, .a7-ci-btn, .a7-ci-analyze, [data-name="A7_TRANSCRIPT"]').forEach(function (node) {
      if (node === crm) {
        return;
      }
      if (node.parentNode) {
        node.parentNode.removeChild(node);
      }
    });
  }

  function placeAfterCrm(row, cell) {
    if (!row || !cell) {
      return;
    }
    pullLeakedTranscript(row);
    if (cell.parentNode && cell.parentNode !== row) {
      cell.parentNode.removeChild(cell);
    }
    cellList(row).forEach(function (td) {
      if (td !== cell && (td.getAttribute('data-name') || '') === 'A7_TRANSCRIPT') {
        td.parentNode.removeChild(td);
      }
    });
    var crm = crmCell(row);
    if (!crm || crm.parentNode !== row) {
      if (cell.parentNode !== row) {
        row.appendChild(cell);
      }
      return;
    }
    if (crm.nextElementSibling !== cell) {
      row.insertBefore(cell, crm.nextElementSibling);
    }
  }

  function transcriptAfterCrm(row) {
    var crm = crmCell(row);
    var transcript = ourTranscriptCell(row);
    return !!(crm && transcript && transcript.parentNode === row && crm.nextElementSibling === transcript);
  }

  function makeCell(column, isHead, data, sampleHead) {
    var cell;
    if (isHead && sampleHead) {
      cell = sampleHead.cloneNode(true);
      cell.removeAttribute('data-sort-by');
      cell.removeAttribute('data-sort-url');
      cell.removeAttribute('data-grid-column-sort');
      cell.classList.remove('main-grid-cell-sortable', 'main-grid-cell-action');
    } else {
      cell = document.createElement(isHead ? 'th' : 'td');
      cell.className = isHead ? 'main-grid-cell-head a7-ci-col' : 'main-grid-cell a7-ci-col';
    }
    cell.setAttribute('data-name', column.id);
    cell.setAttribute('data-visible', 'true');
    styleOurCell(cell, isHead);
    fillCell(cell, column.id, data, isHead);
    return cell;
  }

  function sampleHeadCell(row) {
    return row.querySelector('th.main-grid-cell-head:not([data-name^="A7_"])');
  }

  function appendOurColumns(row, isHead, data) {
    var sample = isHead ? sampleHeadCell(row) : null;
    COLUMNS.forEach(function (column) {
      var existing = namedRowCell(row, [column.id]);
      if (existing) {
        styleOurCell(existing, isHead);
        if (isHead) {
          fillHeadContent(existing, column.title);
        }
        placeAfterCrm(row, existing);
        return;
      }
      placeAfterCrm(row, makeCell(column, isHead, data, sample));
    });
  }

  function ourColumnsAligned(row, headRow) {
    if (!headRow) {
      return false;
    }
    var headCells = cellList(headRow);
    var rowCells = cellList(row);
    var headIndex = -1;
    var rowIndex = -1;
    var i;
    for (i = 0; i < headCells.length; i++) {
      if (headCells[i].getAttribute('data-name') === 'A7_TRANSCRIPT') {
        headIndex = i;
      }
    }
    for (i = 0; i < rowCells.length; i++) {
      if (rowCells[i].getAttribute('data-name') === 'A7_TRANSCRIPT') {
        rowIndex = i;
      }
    }
    return headIndex >= 0 && headIndex === rowIndex &&
      transcriptAfterCrm(headRow) && transcriptAfterCrm(row);
  }

  function headRows(table) {
    var rows = table.querySelectorAll('thead tr, tr.main-grid-row-head');
    if (rows.length) {
      return rows;
    }
    var fallback = table.querySelector('.main-grid-row-head');
    return fallback ? [fallback] : [];
  }

  function stripOutsideTranscript(table) {
    if (!table) {
      return;
    }
    table.querySelectorAll('[data-name^="A7_"], .a7-ci-col, col[data-name^="A7_"]').forEach(function (el) {
      if (el.parentNode) {
        el.parentNode.removeChild(el);
      }
    });
    table.querySelectorAll('.a7-ci-transcript-cell, .a7-ci-btn, .a7-ci-analyze, .a7-ci-status').forEach(function (el) {
      if (el.closest('.a7-ci-comment-ai') || isCommentCell(el.closest('td, th'))) {
        return;
      }
      var cell = el.closest('td, th');
      if (cell && cell.parentNode && !protectedColumnName(cell.getAttribute('data-name'))) {
        cell.parentNode.removeChild(cell);
        return;
      }
      if (el.parentNode) {
        el.parentNode.removeChild(el);
      }
    });
    Array.prototype.forEach.call(headRows(table), function (headRow) {
      cellList(headRow).forEach(function (cell) {
        var titleNode = cell.querySelector('.main-grid-head-title');
        var title = ((titleNode ? titleNode.textContent : cell.textContent) || '').replace(/\s+/g, ' ').trim().toLowerCase();
        if (title === 'transcript' && !protectedColumnName(cell.getAttribute('data-name'))) {
          if (cell.parentNode) {
            cell.parentNode.removeChild(cell);
          }
        }
      });
    });
    bodyRows(table).forEach(function (row) {
      pullLeakedTranscript(row);
    });
  }

  function ensureHead(table) {
    stripOutsideTranscript(table);
    clampPortalPhoneColumn(table);
    var rows = headRows(table);
    return rows.length ? rows[0] : null;
  }

  function portalPhoneColumnIndex(table) {
    var head = table.querySelector('tr.main-grid-row-head') || table.querySelector('thead tr');
    if (!head) {
      return -1;
    }
    var heads = cellList(head);
    var i;
    for (i = 0; i < heads.length; i++) {
      var name = (heads[i].getAttribute('data-name') || '').toUpperCase();
      var title = headerCellTitle(heads[i]);
      if (
        name === 'PORTAL_NUMBER' ||
        name === 'PORTAL_PHONE' ||
        name === 'SEARCH_ID' ||
        title === 'bitrix24 phone' ||
        title.indexOf('bitrix24 phone') !== -1
      ) {
        return i;
      }
    }
    return -1;
  }

  function clampPortalPhoneColumn(table) {
    var idx = portalPhoneColumnIndex(table);
    if (idx < 0) {
      return;
    }
    var rows = table.querySelectorAll('tr.main-grid-row, tr.main-grid-row-body, tr.main-grid-row-head');
    Array.prototype.forEach.call(rows, function (row) {
      var cells = cellList(row);
      var cell = cells[idx];
      if (!cell) {
        return;
      }
      cell.classList.add('a7-ci-portal-phone');
      var text = (cell.textContent || '').replace(/\s+/g, ' ').trim();
      if (text) {
        cell.setAttribute('title', text);
        var content = cell.querySelector('.main-grid-cell-content');
        if (content) {
          content.setAttribute('title', text);
        }
      }
    });
  }

  function updateOurCells(row, data) {
    enhanceCommentCell(row, data);
    COLUMNS.forEach(function (column) {
      var cell = namedRowCell(row, [column.id]);
      if (!cell) {
        return;
      }
      var content = cell.querySelector('.main-grid-cell-content');
      if (content) {
        content.innerHTML = cellHtml(column.id, data);
      } else {
        fillCell(cell, column.id, data, false);
      }
    });
  }

  function ensureRowCells(row, data, headRow) {
    pullLeakedTranscript(row);
    removeOurCells(row);
    enhanceCommentCell(row, data || {});
  }

  function extractPositiveInt(value) {
    var raw = String(value || '').trim();
    if (/^\d+$/.test(raw)) {
      var direct = parseInt(raw, 10);
      return direct > 0 && direct < 2000000000 ? direct : 0;
    }
    var match = raw.match(/(?:^|[^\d])(\d{4,9})(?:[^\d]|$)/);
    return match ? parseInt(match[1], 10) : 0;
  }

  function rowId(row) {
    if (!row) {
      return 0;
    }
    var id = extractPositiveInt(row.getAttribute('data-id'));
    if (id > 0) {
      return id;
    }
    id = extractPositiveInt(row.getAttribute('data-row-id'));
    if (id > 0) {
      return id;
    }
    id = extractPositiveInt(row.id);
    if (id > 0) {
      return id;
    }
    var checkbox = row.querySelector('input[type="checkbox"][name="ID[]"], input.main-grid-row-checkbox');
    if (checkbox) {
      id = extractPositiveInt(checkbox.value);
      if (id > 0) {
        return id;
      }
    }
    var idCell = namedRowCell(row, ['ID']);
    if (idCell) {
      id = extractPositiveInt((idCell.textContent || '').trim());
      if (id > 0) {
        return id;
      }
    }
    return 0;
  }

  function bodyRows(table) {
    return Array.prototype.filter.call(
      table.querySelectorAll('tr.main-grid-row, tr.main-grid-row-body'),
      function (row) {
        if (row.classList.contains('main-grid-row-head') || row.classList.contains('main-grid-row-foot')) {
          return false;
        }
        if (row.querySelector('.main-grid-head-title')) {
          return false;
        }
        var rawId = String(row.getAttribute('data-id') || row.id || '');
        if (rawId.indexOf('template') !== -1) {
          return false;
        }
        return true;
      }
    );
  }

  function collectIds(table) {
    var ids = [];
    bodyRows(table).forEach(function (row) {
      var id = rowId(row);
      if (id > 0) {
        ids.push(id);
      }
    });
    return ids;
  }

  function popupMeta(kind) {
    if (kind === 'transcript') {
      return { title: 'Call Transcript', sub: 'Full English transcript of the call', cls: 'transcript' };
    }
    if (kind === 'comment') {
      return { title: 'Call Comment', sub: 'Short summary of what was discussed', cls: 'comment' };
    }
    if (kind === 'details') {
      return { title: 'Call Intelligence', sub: 'Saved score, summary, next action, and transcript', cls: 'details' };
    }
    return { title: 'Call Summary', sub: 'AI analysis of this conversation', cls: 'summary' };
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
      '\n\nNext Action:\n' + action + (when ? ' (' + when + ')' : '') +
      '\n\nCall Transcription:\n' + (data.transcript || (data.has_transcript ? 'Loading...' : '—'));
  }

  function detailsBodyHtml(data) {
    var action = ACTION_LABELS[(data && data.next_action_type) || ''] || (data && data.next_action_type) || '—';
    var when = [formatDate(data && data.next_action_date), formatTime(data && data.next_action_time)].filter(Boolean).join(' · ');
    var score = data && data.ai_overall_score != null ? String(data.ai_overall_score) + '/100' : '—';
    var summary = escapeHtml((data && data.ai_call_summary) || '—').replace(/\n/g, '<br>');
    var transcript = escapeHtml((data && data.transcript) || '—').replace(/\n/g, '<br>');
    return '<div class="a7-ci-modal a7-ci-modal-details">' +
      '<div class="a7-ci-modal-head">' +
        '<span class="a7-ci-modal-icon" aria-hidden="true"></span>' +
        '<div class="a7-ci-modal-copy">' +
          '<div class="a7-ci-modal-title">Call Intelligence</div>' +
          '<div class="a7-ci-modal-sub">AI listened to the recording, scored the agent, then saved the analysis</div>' +
        '</div>' +
      '</div>' +
      '<div class="a7-ci-modal-body">' +
        '<div class="a7-ci-detail-block"><div class="a7-ci-detail-label">AI Score</div>' +
          '<div class="a7-ci-detail-value">' + escapeHtml(score) + '</div></div>' +
        '<div class="a7-ci-detail-block"><div class="a7-ci-detail-label">Call Summary</div>' +
          '<div class="a7-ci-detail-value">' + summary + '</div></div>' +
        '<div class="a7-ci-detail-block"><div class="a7-ci-detail-label">Next Action</div>' +
          '<div class="a7-ci-detail-value">' + escapeHtml(action) +
          (when ? '<div class="a7-ci-next-meta">' + escapeHtml(when) + '</div>' : '') +
          '</div></div>' +
        '<div class="a7-ci-detail-block"><div class="a7-ci-detail-label">Call Transcription</div>' +
          '<div class="a7-ci-detail-value a7-ci-detail-transcript">' + transcript + '</div></div>' +
      '</div>' +
    '</div>';
  }

  function popupBodyHtml(kind, text, data) {
    if (kind === 'details') {
      return detailsBodyHtml(data || {});
    }
    var meta = popupMeta(kind);
    var safe = escapeHtml(text || '-').replace(/\n/g, '<br>');
    return '<div class="a7-ci-modal a7-ci-modal-' + meta.cls + '">' +
      '<div class="a7-ci-modal-head">' +
        '<span class="a7-ci-modal-icon" aria-hidden="true"></span>' +
        '<div class="a7-ci-modal-copy">' +
          '<div class="a7-ci-modal-title">' + escapeHtml(meta.title) + '</div>' +
          '<div class="a7-ci-modal-sub">' + escapeHtml(meta.sub) + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="a7-ci-modal-body">' + safe + '</div>' +
    '</div>';
  }

  function showPopup(kind, text, data) {
    var bodyText = kind === 'details' ? detailsCopyText(data) : (text || '-');
    if (window.BX && BX.PopupWindow) {
      var popup = new BX.PopupWindow('a7-ci-popup-' + Date.now(), null, {
        className: 'a7-ci-overlay-popup',
        content: popupBodyHtml(kind, bodyText, data),
        closeIcon: true,
        closeByEsc: true,
        autoHide: true,
        maxWidth: kind === 'transcript' || kind === 'details' ? 760 : 640,
        overlay: { backgroundColor: '#102040', opacity: 55 },
        buttons: [
          new BX.PopupWindowButton({
            text: 'Copy',
            className: 'popup-window-button a7-ci-popup-copy',
            events: {
              click: function () {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                  navigator.clipboard.writeText(bodyText);
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
    window.alert(bodyText);
  }

  function popupText(kind, data) {
    if (!data) {
      return '';
    }
    if (kind === 'summary') {
      return data.ai_call_summary || '';
    }
    if (kind === 'comment') {
      return data.comment_line || data.ai_call_summary || '';
    }
    return data.transcript || '';
  }

  function loadDetail(id, kind, link) {
    var cached = rowCache[String(id)] || cachedCompleted(id);
    if (kind === 'details') {
      if (cached && cached.ai_status === 'COMPLETED' && cached.transcript) {
        showPopup('details', '', cached);
        return;
      }
      if (cached && cached.ai_status === 'COMPLETED') {
        showPopup('details', '', cached);
      }
    } else {
      var instant = popupText(kind, cached);
      if (!instant && link) {
        instant = link.getAttribute('data-a7-text') || '';
      }
      if (instant) {
        showPopup(kind, instant, cached);
        return;
      }
    }
    var body = new URLSearchParams();
    body.set('action', 'detail');
    body.set('id', String(id));
    body.set('sessid', sessid());
    fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      if (!payload || !payload.ok || !payload.row) {
        return;
      }
      rememberRow(id, payload.row);
      if (kind === 'details') {
        showPopup('details', '', Object.assign({}, cached || {}, payload.row));
        return;
      }
      showPopup(kind, popupText(kind, payload.row) || '-', payload.row);
    }).catch(function () {
      return null;
    });
  }

  function bindLinks(table) {
    table.querySelectorAll('.a7-ci-link, .a7-ci-btn').forEach(function (link) {
      if (link.getAttribute('data-a7-bound') === '1') {
        return;
      }
      link.setAttribute('data-a7-bound', '1');
      link.addEventListener('click', function (event) {
        event.preventDefault();
        var row = link.closest('.main-grid-row');
        var id = rowId(row);
        if (id > 0) {
          loadDetail(id, link.getAttribute('data-a7-ci'), link);
        }
      });
    });
    table.querySelectorAll('.a7-ci-analyze').forEach(function (button) {
      if (button.getAttribute('data-a7-bound') === '1') {
        return;
      }
      button.setAttribute('data-a7-bound', '1');
      button.addEventListener('click', function (event) {
        event.preventDefault();
        startAnalyze(button);
      });
    });
  }

  function findTable() {
    return document.querySelector('#tel-stat-grid-container table.main-grid-table') ||
      document.querySelector('[id^="voximplant_statistic_detail"] table.main-grid-table') ||
      document.querySelector('#voximplant_statistic_detail_table') ||
      document.querySelector('table.main-grid-table');
  }

  function findScroller(table) {
    return document.querySelector('#tel-stat-grid-container .main-grid-container') ||
      (table && table.closest('.main-grid-container')) ||
      document.querySelector('.main-grid-container');
  }

  function findWrap(table) {
    return document.querySelector('#tel-stat-grid-container') ||
      (table && table.closest('.main-grid')) ||
      document.body;
  }

  function restoreOriginalHeader(table) {
    var headRow = table.querySelector('.main-grid-row-head');
    if (headRow) {
      headRow.classList.remove('a7-ci-head-spacer');
    }
    var wrap = findWrap(table);
    if (!wrap) {
      return;
    }
    var clone = wrap.querySelector('.a7-ci-sticky-head');
    if (clone && clone.parentNode) {
      clone.parentNode.removeChild(clone);
    }
  }

  function ensureScrollControls(table) {
    var wrap = findWrap(table);
    if (!wrap) {
      return;
    }
    wrap.classList.add('a7-ci-grid-wrap');
    restoreOriginalHeader(table);
    var bar = wrap.querySelector('.a7-ci-hscroll');
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'a7-ci-hscroll a7-ci-hscroll-visible';
      bar.innerHTML =
        '<button type="button" class="a7-ci-hscroll-btn" data-dir="-1" title="Scroll left">◀</button>' +
        '<button type="button" class="a7-ci-hscroll-btn" data-dir="1" title="Scroll right">▶</button>';
      wrap.appendChild(bar);
      bar.addEventListener('click', function (event) {
        var btn = event.target.closest('[data-dir]');
        if (!btn) {
          return;
        }
        var scroller = findScroller(table);
        if (!scroller) {
          return;
        }
        scroller.scrollBy({
          left: parseInt(btn.getAttribute('data-dir'), 10) * 320,
          behavior: 'smooth'
        });
      });
    } else {
      bar.classList.add('a7-ci-hscroll-visible');
    }
  }

  function startAnalyze(button) {
    var row = button.closest('.main-grid-row');
    if (button) {
      button.disabled = true;
      button.textContent = 'Starting...';
    }
    queueAnalyzeRow(row, true);
  }

  function queueAnalyzeRow(row, force) {
    var id = rowId(row);
    if (id <= 0 || alreadyDone(id) || autoStarted[id] === 'running') {
      return;
    }
    if (!force && !rowHasRecording(row, rowCache[String(id)])) {
      return;
    }
    if (analyzeQueue.some(function (item) { return rowId(item.row) === id; })) {
      return;
    }
    analyzeQueue.push({ row: row, force: !!force });
    pumpAnalyze();
  }

  function pumpAnalyze() {
    if (analyzeActive) {
      return;
    }
    while (analyzeQueue.length) {
      var next = analyzeQueue.shift();
      var nextRow = next && next.row;
      var nextId = rowId(nextRow);
      if (!nextRow || alreadyDone(nextId)) {
        continue;
      }
      if (!next.force && !rowHasRecording(nextRow, rowCache[String(nextId)])) {
        continue;
      }
      analyzeActive = true;
      startAnalyzeRow(nextRow, next.force, function () {
        analyzeActive = false;
        window.setTimeout(pumpAnalyze, 400);
      });
      return;
    }
  }

  function startAnalyzeRow(row, force, done) {
    var table = row ? row.closest('table') : findTable();
    var headRow = table ? ensureHead(table) : null;
    var id = rowId(row);
    var finish = function () {
      if (typeof done === 'function') {
        done();
      }
    };
    if (id <= 0 || autoStarted[id] === 'running') {
      finish();
      return;
    }
    if (!force && alreadyDone(id)) {
      var cached = cachedCompleted(id);
      if (cached) {
        ensureRowCells(row, cached, headRow);
        bindLinks(table || document);
      }
      finish();
      return;
    }
    autoStarted[id] = 'running';
    var busy = {
      ai_status: 'TRANSCRIBING',
      can_analyze: false,
      awaiting_auto: true,
      is_new: true
    };
    ensureRowCells(row, busy, headRow);
    var body = new URLSearchParams();
    body.set('action', 'analyze');
    body.set('id', String(id));
    body.set('sessid', sessid());
    if (force) {
      body.set('force', '1');
    }
    fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      if (payload && payload.waiting_recording) {
        autoStarted[id] = '';
        if (payload.row) {
          rememberRow(id, payload.row);
          ensureRowCells(row, payload.row, headRow);
        }
        finish();
        return;
      }
      if (payload && payload.queued) {
        autoStarted[id] = '';
        if (payload.row) {
          ensureRowCells(row, payload.row, headRow);
        }
        finish();
        return;
      }
      if (payload && payload.row && payload.row.ai_status === 'COMPLETED') {
        rememberRow(id, payload.row);
      } else if (!alreadyDone(id)) {
        autoStarted[id] = '';
      }
      if (payload && payload.row) {
        if (payload.row.ai_status === 'COMPLETED' || !alreadyDone(id)) {
          ensureRowCells(row, payload.row, headRow);
        } else {
          ensureRowCells(row, cachedCompleted(id), headRow);
        }
        bindLinks(table || document);
        finish();
        return;
      }
      refresh();
      finish();
    }).catch(function () {
      if (!alreadyDone(id)) {
        autoStarted[id] = '';
      }
      refresh();
      finish();
    });
  }

  function apply(table, rows) {
    var headRow = ensureHead(table);
    var busy = false;
    bodyRows(table).forEach(function (row) {
      var id = String(rowId(row));
      var data = (rows && (rows[id] || rows[row.getAttribute('data-id')])) || {
        can_analyze: true,
        is_new: false
      };
      var cached = cachedCompleted(id);
      if (cached && data.ai_status !== 'COMPLETED') {
        data = Object.assign({}, data, cached, {
          awaiting_auto: false,
          can_analyze: false,
          is_new: !!(data.is_new || cached.is_new)
        });
      }
      rememberRow(id, data);
      if (isBusy(data)) {
        busy = true;
      }
      ensureRowCells(row, data, headRow);
    });
    clampPortalPhoneColumn(table);
    bindLinks(table);
    ensureHead(table);
    ensureScrollControls(table);
    autoAnalyzeNew(table, rows || {});
    table.setAttribute('data-a7-ci-busy', busy ? '1' : '0');
  }

  function autoAnalyzeNew(table, rows) {
    bodyRows(table).forEach(function (row) {
      var id = String(rowId(row));
      var data = rows && (rows[id] || rows[row.getAttribute('data-id')]);
      if (!data || !data.is_new) {
        return;
      }
      if (alreadyDone(id) || data.ai_status === 'COMPLETED' || data.ai_status === 'FAILED') {
        return;
      }
      if (!data.awaiting_auto && !data.has_recording && !rowHasRecording(row, data)) {
        return;
      }
      if (data.waiting_recording && !rowHasRecording(row, data) && !data.has_recording) {
        return;
      }
      if (data.ai_status === 'TRANSCRIBING' || data.ai_status === 'ANALYZING') {
        return;
      }
      queueAnalyzeRow(row, false);
    });
  }

  function paintFromCache(table) {
    var headRow = ensureHead(table);
    bodyRows(table).forEach(function (row) {
      var id = rowId(row);
      var cached = cachedCompleted(id) || rowCache[String(id)] || {};
      ensureRowCells(row, cached, headRow);
    });
    bindLinks(table);
  }

  function refresh() {
    var table = findTable();
    if (!table) {
      return false;
    }
    paintFromCache(table);
    var ids = collectIds(table);
    if (!ids.length) {
      apply(table, {});
      return true;
    }
    var body = new URLSearchParams();
    body.set('action', 'list');
    body.set('ids', ids.join(','));
    body.set('sessid', sessid());
    fetch('/bitrix/tools/a7_call_intelligence.php', {
      method: 'POST',
      headers: { 'X-Bitrix-Csrf-Token': sessid() },
      body: body,
      credentials: 'same-origin'
    }).then(function (response) {
      return response.json();
    }).then(function (payload) {
      apply(table, payload && payload.rows ? payload.rows : {});
    }).catch(function () {
      apply(table, {});
    });
    return true;
  }

  function start() {
    if (window.__a7CiStarted) {
      refresh();
      return;
    }
    window.__a7CiStarted = true;
    var tries = 0;
    var timer = window.setInterval(function () {
      tries += 1;
      if (refresh() || tries >= 20) {
        window.clearInterval(timer);
      }
    }, 400);
    if (window.BX && BX.addCustomEvent) {
      BX.addCustomEvent('Grid::updated', function (grid) {
        if (!grid || grid.getId && grid.getId() === GRID_ID) {
          window.setTimeout(refresh, 50);
        }
      });
      BX.addCustomEvent('Grid::ready', function (grid) {
        if (!grid || grid.getId && grid.getId() === GRID_ID) {
          window.setTimeout(refresh, 50);
        }
      });
      BX.addCustomEvent('SidePanel.Slider:onLoad', function () {
        window.setTimeout(refresh, 200);
      });
    }
    if (window.MutationObserver) {
      var headFixTimer = 0;
      var observer = new MutationObserver(function () {
        var table = findTable();
        if (!table) {
          return;
        }
        if (table.querySelector('[data-name^="A7_"], .a7-ci-col') && !headFixTimer) {
          headFixTimer = window.setTimeout(function () {
            headFixTimer = 0;
            stripOutsideTranscript(table);
          }, 200);
        }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }
    window.setInterval(refresh, 8000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
