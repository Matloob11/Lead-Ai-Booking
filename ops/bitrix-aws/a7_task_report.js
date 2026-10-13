/**
 * A7 Task Report — buttons under the user names in the Worktime grid.
 * Deployed to: /bitrix/js/a7_task_report.js  (added on /timeman/ pages by a7_task_report.php)
 *   "Task report" -> /bitrix/tools/a7_task_report.php?user_id=ID  (own row; admins + heads: every row)
 *   "Lead report" -> /bitrix/tools/a7_lead_report.php?user_id=ID  (admins only, rows of lead agents)
 *   "Attendance report" (grid header, next to the month) -> /bitrix/tools/a7_attendance.php  (admins + HR viewers)
 * window.A7TaskReportCfg = {me, all, lead: [agent ids], admin, att} is printed by the server.
 */
(function () {
  'use strict';
  if (window.A7TaskReportLoaded) return;
  window.A7TaskReportLoaded = true;

  var PAGE = '/bitrix/tools/a7_task_report.php';
  var LEAD_PAGE = '/bitrix/tools/a7_lead_report.php';
  var ATT_PAGE = '/bitrix/tools/a7_attendance.php';
  var MARK = 'data-a7-task-report';

  function addStyle() {
    if (document.getElementById('a7-task-report-style')) return;
    var icon = 'url("data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 16 16\'>' +
      '<path d=\'M3 1h7l3 3v11H3z M5 7h6v1.5H5z M5 10h6v1.5H5z\'/></svg>") center/contain no-repeat';
    var css =
      '.a7-tr-btn{display:flex;align-items:center;gap:4px;margin-top:3px;padding:1px 8px;' +
      'border:1px solid #c6cdd3;border-radius:10px;background:#fff;color:#535c69;font-size:11px;' +
      'line-height:16px;cursor:pointer;white-space:nowrap;text-decoration:none;width:max-content}' +
      '.a7-tr-btn:hover{border-color:#2fc6f6;color:#0b66c3;background:#f0fbff}' +
      '.a7-tr-btn:before{content:"";width:10px;height:10px;background:currentColor;' +
      '-webkit-mask:' + icon + ';mask:' + icon + '}' +
      '.a7-tr-btns{display:flex;flex-wrap:wrap;gap:4px;margin-top:3px}.a7-tr-btns .a7-tr-btn{margin-top:0}' +
      '.a7-tr-btn.a7-lr{border-color:#9fd96a;color:#3d7a00}.a7-tr-btn.a7-lr:hover{border-color:#7bd500;background:#f4fce8}' +
      '.a7-att-btn{display:inline-flex;align-items:center;margin-left:14px;padding:5px 14px;border-radius:16px;' +
      'background:#3bc8f5;color:#fff;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;vertical-align:middle}' +
      '.a7-att-btn:hover{background:#12b1e3}';
    var st = document.createElement('style');
    st.id = 'a7-task-report-style';
    st.textContent = css;
    (document.head || document.documentElement).appendChild(st);
  }

  function userIdFromHref(href) {
    var m = /\/user\/(\d+)\/?/.exec(href || '');
    return m ? m[1] : null;
  }

  function openReport(uid, page) {
    var url = (page || PAGE) + (uid ? '?user_id=' + encodeURIComponent(uid) : '');
    var sp = null;
    try {
      sp = (window.top && window.top.BX && window.top.BX.SidePanel) ? window.top.BX.SidePanel
        : (window.BX && window.BX.SidePanel ? window.BX.SidePanel : null);
    } catch (e) { sp = window.BX && window.BX.SidePanel ? window.BX.SidePanel : null; }
    if (sp && sp.Instance) {
      sp.Instance.open(url, { width: page === ATT_PAGE ? 1250 : (page === LEAD_PAGE ? 1150 : 1000), cacheable: false, allowChangeHistory: false });
    } else {
      window.open(url, '_blank');
    }
  }

  function attendanceButton() {
    var cfg = window.A7TaskReportCfg || {};
    if (!cfg.att) return; // server decides (A7Attendance::canView), incl. the 'enabled' switch
    var nav = document.querySelector('[data-role="tm-grid-navigation-arrows"]');
    if (!nav || nav.querySelector('.a7-att-btn')) return;
    var btn = document.createElement('span');
    btn.className = 'a7-att-btn';
    btn.setAttribute('role', 'button');
    btn.setAttribute('tabindex', '0');
    btn.title = 'Present / absent / late for all employees';
    btn.textContent = 'Attendance report';
    function go(e) { e.preventDefault(); e.stopPropagation(); openReport(0, ATT_PAGE); }
    btn.addEventListener('click', go);
    btn.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') go(e); });
    nav.appendChild(btn);
  }

  function decorate(root) {
    attendanceButton();
    var links = (root || document).querySelectorAll('a.timeman-grid-user-name');
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      var info = a.closest('.timeman-grid-user-info') || a.parentNode;
      if (!info || info.hasAttribute(MARK)) continue;
      var uid = userIdFromHref(a.getAttribute('href'));
      if (!uid) continue;
      var cfg = window.A7TaskReportCfg || {};
      // Task report: own row for everyone; admins + department heads on every row (server checks again).
      var task = cfg.all || String(cfg.me) === uid;
      // Lead report: admins only (cfg.lead is empty for others), rows of people who work leads.
      var lead = (cfg.lead || []).map(String).indexOf(uid) !== -1;
      if (!task && !lead) continue;
      info.setAttribute(MARK, uid);
      var row = document.createElement('div');
      row.className = 'a7-tr-btns';
      if (task) row.appendChild(button('Task report', 'Open the task report', '', uid, PAGE));
      if (lead) row.appendChild(button('Lead report', 'Open the lead report', ' a7-lr', uid, LEAD_PAGE));
      info.appendChild(row);
    }
  }

  function button(text, title, extra, uid, page) {
    var btn = document.createElement('span');
    btn.className = 'a7-tr-btn' + extra;
    btn.setAttribute('role', 'button');
    btn.setAttribute('tabindex', '0');
    btn.title = title;
    btn.textContent = text;
    function go(e) { e.preventDefault(); e.stopPropagation(); openReport(uid, page); }
    btn.addEventListener('click', go);
    btn.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') go(e); });
    return btn;
  }

  var timer = null;
  function schedule() {
    if (timer) return;
    timer = setTimeout(function () { timer = null; decorate(document); }, 150);
  }

  function start() {
    addStyle();
    decorate(document);
    // The grid re-renders over AJAX (period change, filter, paging) — re-add buttons.
    if (window.MutationObserver && document.body) {
      new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
