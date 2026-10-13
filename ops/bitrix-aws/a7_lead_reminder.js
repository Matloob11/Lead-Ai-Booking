(function () {
  if (window.A7_LEAD_REMINDER_LOADED) {
    return;
  }
  window.A7_LEAD_REMINDER_LOADED = true;

  var STYLE_ID = 'a7-lead-reminder-style';
  var STORAGE_KEY = 'a7_lead_reminder_active';
  var RINGTONE_SRC = '/bitrix/sounds/a7_lead_reminder_bell.wav';
  var CLIP_MS = 3100;
  var MAX_PLAYS = 2;
  var ringingAudio = null;
  var ringRepeatTimer = null;
  var playsDone = 0;
  var audioUnlocked = false;

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent =
      '#a7-lead-reminder-popup{position:fixed;z-index:100000;right:24px;top:24px;width:380px;max-width:calc(100vw - 32px);' +
      'background:#1e2530;color:#fff;border-radius:14px;box-shadow:0 16px 40px rgba(0,0,0,.35);font-family:Arial,sans-serif;' +
      'overflow:hidden;animation:a7LeadReminderIn .25s ease-out}' +
      '@keyframes a7LeadReminderIn{from{transform:translateY(-12px);opacity:0}to{transform:none;opacity:1}}' +
      '#a7-lead-reminder-popup .a7-lr-head{display:flex;align-items:center;gap:10px;padding:14px 16px 8px}' +
      '#a7-lead-reminder-popup .a7-lr-bell{width:34px;height:34px;border-radius:50%;background:#2fc6f6;display:flex;' +
      'align-items:center;justify-content:center;font-size:18px;flex:0 0 auto}' +
      '#a7-lead-reminder-popup .a7-lr-title{font-size:16px;font-weight:700;line-height:1.3}' +
      '#a7-lead-reminder-popup .a7-lr-body{padding:0 16px 14px;font-size:14px;line-height:1.45;color:#d7dde5}' +
      '#a7-lead-reminder-popup .a7-lr-lead{color:#fff;font-weight:700;margin-bottom:4px}' +
      '#a7-lead-reminder-popup .a7-lr-actions{display:flex;gap:8px;padding:0 16px 16px}' +
      '#a7-lead-reminder-popup .a7-lr-btn{flex:1;border:0;border-radius:8px;padding:10px 12px;cursor:pointer;font-weight:700}' +
      '#a7-lead-reminder-popup .a7-lr-open{background:#2fc6f6;color:#112}' +
      '#a7-lead-reminder-popup .a7-lr-close{background:#3a4452;color:#fff}';
    document.head.appendChild(style);
  }

  function persistPopup(params) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        params: params,
        savedAt: Date.now()
      }));
    } catch (e) {}
  }

  function clearPersisted() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
  }

  function readPersisted() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return null;
      }
      var data = JSON.parse(raw);
      return data && data.params ? data : null;
    } catch (e) {
      return null;
    }
  }

  function stopRingtone() {
    if (ringRepeatTimer) {
      clearTimeout(ringRepeatTimer);
      ringRepeatTimer = null;
    }
    if (ringingAudio) {
      try {
        ringingAudio.pause();
        ringingAudio.currentTime = 0;
      } catch (e) {}
      ringingAudio = null;
    }
  }

  function dismissPopup() {
    stopRingtone();
    clearPersisted();
    var box = document.getElementById('a7-lead-reminder-popup');
    if (box) {
      box.remove();
    }
  }

  function unlockAudio() {
    if (audioUnlocked) {
      return;
    }
    try {
      var probe = new Audio(RINGTONE_SRC);
      probe.volume = 0.01;
      var play = probe.play();
      if (play && typeof play.then === 'function') {
        play.then(function () {
          probe.pause();
          probe.currentTime = 0;
          audioUnlocked = true;
        }).catch(function () {});
      } else {
        audioUnlocked = true;
      }
    } catch (e) {}
  }

  function playRingtone() {
    stopRingtone();
    playsDone = 0;
    var audio = new Audio(RINGTONE_SRC);
    audio.preload = 'auto';
    audio.loop = false;
    audio.volume = 1;
    ringingAudio = audio;

    function playNext() {
      if (!ringingAudio || playsDone >= MAX_PLAYS) {
        return;
      }
      playsDone += 1;
      try {
        ringingAudio.currentTime = 0;
      } catch (e) {}
      var play = ringingAudio.play();
      if (play && typeof play.then === 'function') {
        play.catch(function () {});
      }
      if (playsDone < MAX_PLAYS) {
        ringRepeatTimer = setTimeout(playNext, CLIP_MS + 400);
      }
    }

    audio.addEventListener('ended', function () {
      if (ringRepeatTimer) {
        clearTimeout(ringRepeatTimer);
        ringRepeatTimer = null;
      }
      playNext();
    });

    playNext();
  }

  function showBrowserNotify(params) {
    if (!window.Notification || Notification.permission !== 'granted') {
      return;
    }
    try {
      var n = new Notification(params.title || 'Lead reminder', {
        body: [params.text, params.subject, params.when].filter(Boolean).join('\n'),
        requireInteraction: true,
        tag: 'a7-lead-reminder-' + String(params.leadId || '')
      });
      n.onclick = function () {
        window.focus();
        if (params.url) {
          window.location.href = params.url;
        }
        n.close();
      };
    } catch (e) {}
  }

  function showPopup(params, fromRestore, withSound) {
    ensureStyles();
    var existing = document.getElementById('a7-lead-reminder-popup');
    if (existing) {
      existing.remove();
    }

    var box = document.createElement('div');
    box.id = 'a7-lead-reminder-popup';
    box.innerHTML =
      '<div class="a7-lr-head"><div class="a7-lr-bell">&#128276;</div>' +
      '<div class="a7-lr-title"></div></div>' +
      '<div class="a7-lr-body"><div class="a7-lr-lead"></div>' +
      '<div class="a7-lr-meta"></div></div>' +
      '<div class="a7-lr-actions">' +
      '<button type="button" class="a7-lr-btn a7-lr-open">Open lead</button>' +
      '<button type="button" class="a7-lr-btn a7-lr-close">Dismiss</button>' +
      '</div>';

    box.querySelector('.a7-lr-title').textContent = params.title || 'Lead reminder';
    box.querySelector('.a7-lr-lead').textContent = params.text || '';
    var meta = [params.subject, params.when].filter(Boolean).join(' · ');
    box.querySelector('.a7-lr-meta').textContent = meta;
    box.querySelector('.a7-lr-open').onclick = function () {
      var url = params.url;
      dismissPopup();
      if (url) {
        window.location.href = url;
      }
    };
    box.querySelector('.a7-lr-close').onclick = function () {
      dismissPopup();
    };

    document.body.appendChild(box);
    if (!fromRestore) {
      persistPopup(params);
    }
    if (withSound !== false) {
      playRingtone();
    }
    showBrowserNotify(params);
  }

  var subscribed = false;
  function subscribePull() {
    if (subscribed) {
      return true;
    }
    var pull = window.BX && BX.PULL ? BX.PULL : null;
    if (!pull || typeof pull.subscribe !== 'function') {
      return false;
    }
    pull.subscribe({
      moduleId: 'a7leadreminder',
      command: 'popup',
      callback: function (params) {
        showPopup(params || {}, false, true);
      }
    });
    subscribed = true;
    return true;
  }

  function seenKey(params) {
    return 'a7lr_seen_' + String((params && params.activityId) || '') + '_' + String((params && params.deadlineTs) || (params && params.leadId) || '');
  }

  function wasSeen(params) {
    try {
      return sessionStorage.getItem(seenKey(params)) === '1';
    } catch (e) {
      return false;
    }
  }

  function markSeen(params) {
    try {
      sessionStorage.setItem(seenKey(params), '1');
    } catch (e) {}
  }

  function showBootItems(items) {
    if (!items || !items.length) {
      return false;
    }
    var params = items[0];
    if (wasSeen(params) || document.getElementById('a7-lead-reminder-popup')) {
      return true;
    }
    showPopup(params, false, true);
    markSeen(params);
    return true;
  }

  function boot() {
    subscribePull();
    if (showBootItems(window.A7_LEAD_REMINDER_BOOT)) {
      return;
    }
    try {
      fetch('/bitrix/tools/a7_lead_reminder_pending.php', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (items) { showBootItems(items); })
        .catch(function () {});
    } catch (e) {}
    var saved = readPersisted();
    if (saved && saved.params && !document.getElementById('a7-lead-reminder-popup')) {
      var replay = Date.now() - (saved.savedAt || 0) < 70000;
      showPopup(saved.params, true, replay);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  if (window.BX && typeof BX.ready === 'function') {
    BX.ready(function () {
      subscribePull();
    });
  }

  document.addEventListener('click', function requestNotifyOnce() {
    unlockAudio();
    if (window.Notification && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    document.removeEventListener('click', requestNotifyOnce);
  });

  window.A7LeadReminderTest = function () {
    unlockAudio();
    showPopup({
      title: 'Lead reminder',
      text: 'Bell test — mixkit notification ring, 2 times',
      subject: 'Contact customer',
      when: 'now',
      url: '/crm/lead/'
    }, false);
  };
})();
