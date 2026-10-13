/**
 * A7 Share-idle alert popup — shown on every CRM screen while the user has shared leads
 * he did not work on for 4 hours. Stays until "Open lead" or "Dismiss" (or "Got it" in the bell).
 * Deployed to: /bitrix/js/a7_share_idle.js (added on /crm/ pages by a7_share_idle.php)
 */
(function () {
  'use strict';
  if (window.A7ShareIdleLoaded) return;
  window.A7ShareIdleLoaded = true;

  var API = '/bitrix/tools/a7_share_idle_api.php';
  var BOX_ID = 'a7-share-idle-box';
  var shown = {};

  function sessid() {
    try { return (window.BX && BX.bitrix_sessid) ? BX.bitrix_sessid() : ''; } catch (e) { return ''; }
  }

  function css() {
    if (document.getElementById('a7-share-idle-style')) return;
    var s = document.createElement('style');
    s.id = 'a7-share-idle-style';
    s.textContent =
      '#' + BOX_ID + '{position:fixed;right:18px;bottom:18px;z-index:10050;display:flex;flex-direction:column;gap:10px;max-width:380px;width:calc(100vw - 36px)}' +
      '.a7si-card{background:#fff;border-radius:12px;box-shadow:0 10px 32px rgba(0,0,0,.22);overflow:hidden;font:14px/1.45 "Open Sans","Helvetica Neue",Arial,sans-serif;color:#333;animation:a7siIn .25s ease-out}' +
      '.a7si-bar{height:4px;background:linear-gradient(90deg,#ff5752,#ffa900)}' +
      '.a7si-body{padding:14px 16px 12px}' +
      '.a7si-eyebrow{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#e0413c;margin-bottom:4px}' +
      '.a7si-title{font-weight:600;font-size:15px;margin-bottom:4px;word-break:break-word}' +
      '.a7si-meta{color:#6a737f;font-size:12.5px}' +
      '.a7si-actions{display:flex;gap:8px;justify-content:flex-end;padding:0 16px 14px}' +
      '.a7si-btn{border:0;border-radius:16px;padding:7px 16px;font:600 13px/1 inherit;cursor:pointer}' +
      '.a7si-open{background:#3bc8f5;color:#fff}.a7si-open:hover{background:#12b1e3}' +
      '.a7si-dismiss{background:#eef2f4;color:#535c69}.a7si-dismiss:hover{background:#e0e5e9}' +
      '@keyframes a7siIn{from{transform:translateY(12px);opacity:0}to{transform:none;opacity:1}}';
    (document.head || document.documentElement).appendChild(s);
  }

  function box() {
    var b = document.getElementById(BOX_ID);
    if (!b) {
      b = document.createElement('div');
      b.id = BOX_ID;
      document.body.appendChild(b);
    }
    return b;
  }

  function esc(t) {
    var d = document.createElement('div');
    d.textContent = String(t == null ? '' : t);
    return d.innerHTML;
  }

  function ack(lead, how, done) {
    var body = 'action=ack&lead=' + encodeURIComponent(lead) + '&how=' + encodeURIComponent(how) + '&sessid=' + encodeURIComponent(sessid());
    fetch(API, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: body })
      .then(function () { if (done) done(); })
      .catch(function () { if (done) done(); });
  }

  function openLead(url) {
    try {
      var top = window.top;
      if (top && top.BX && top.BX.SidePanel && top.BX.SidePanel.Instance) {
        top.BX.SidePanel.Instance.open(url);
        return;
      }
    } catch (e) {}
    window.location.href = url;
  }

  function remove(lead) {
    var card = document.querySelector('.a7si-card[data-lead="' + lead + '"]');
    if (card && card.parentNode) card.parentNode.removeChild(card);
    delete shown[lead];
  }

  function render(items) {
    css();
    var b = box();
    var keep = {};
    items.forEach(function (it) {
      keep[it.lead] = true;
      if (shown[it.lead]) return;
      shown[it.lead] = true;
      var card = document.createElement('div');
      card.className = 'a7si-card';
      card.setAttribute('data-lead', it.lead);
      card.innerHTML =
        '<div class="a7si-bar"></div>' +
        '<div class="a7si-body">' +
          '<div class="a7si-eyebrow">No work on shared lead</div>' +
          '<div class="a7si-title">' + esc(it.title) + ' <span class="a7si-meta">#' + esc(it.lead) + '</span></div>' +
          '<div class="a7si-meta">' + esc(it.by) + ' made you observer ' + esc(it.hours) + 'h ago — no call, comment, stage or activity from you yet.</div>' +
        '</div>' +
        '<div class="a7si-actions">' +
          '<button type="button" class="a7si-btn a7si-dismiss">Dismiss</button>' +
          '<button type="button" class="a7si-btn a7si-open">Open lead</button>' +
        '</div>';
      card.querySelector('.a7si-open').addEventListener('click', function () {
        ack(it.lead, 'open');
        remove(it.lead);
        openLead(it.url);
      });
      card.querySelector('.a7si-dismiss').addEventListener('click', function () {
        ack(it.lead, 'dismiss');
        remove(it.lead);
      });
      b.appendChild(card);
    });
    Object.keys(shown).forEach(function (l) { if (!keep[l]) remove(l); });
  }

  function currentLead() {
    var m = /\/crm\/lead\/details\/(\d+)\//.exec(window.location.pathname);
    return m ? m[1] : null;
  }

  function load() {
    fetch(API + '?action=pending&_=' + Date.now(), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) return;
        var items = d.items || [];
        // Opening the lead itself counts as "seen".
        var here = currentLead();
        if (here) {
          items = items.filter(function (it) {
            if (String(it.lead) === here) { ack(it.lead, 'open'); return false; }
            return true;
          });
          // Lead detail comments sit on the right; do not stack idle cards over them.
          var idleBox = document.getElementById(BOX_ID);
          if (idleBox) idleBox.textContent = '';
          return;
        }
        render(items);
      })
      .catch(function () {});
  }

  function start() {
    load();
    setInterval(function () { if (document.visibilityState === 'visible') load(); }, 60000);
    try {
      if (window.BX && BX.addCustomEvent) {
        BX.addCustomEvent('onPullEvent-crm', function (command) {
          if (command === 'a7ShareIdle') load();
        });
      }
    } catch (e) {}
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
