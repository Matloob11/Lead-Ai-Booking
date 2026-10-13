/**
 * A7 Auto Timeman — Matloob (2311) only.
 * Profile sidebar: Auto ON/OFF next to Pause / Clock out.
 * Server agent/cron: 10:00 in / 19:30 out PKT; Sunday skipped.
 */
(function () {
  if (window.A7_AUTO_TIMEMAN_LOADED) {
    return;
  }
  window.A7_AUTO_TIMEMAN_LOADED = true;

  var ENDPOINT = "/bitrix/tools/a7_auto_timeman.php";
  var BTN_ID = "a7-auto-tm-btn";
  var WRAP_ID = "a7-auto-tm-btn-wrap";
  var STYLE_ID = "a7-auto-tm-style";
  var ALLOWED_USER_ID = 2311;
  var state = { enabled: false, loaded: false, allowed: false };
  var watchTimer = 0;

  function currentUserId() {
    try {
      if (window.BX && BX.message && BX.message.USER_ID) {
        return parseInt(BX.message.USER_ID, 10) || 0;
      }
    } catch (e) {}
    return 0;
  }

  function uidOk() {
    var id = currentUserId();
    // USER_ID sometimes missing until BX.init — allow until proven wrong.
    if (!id) {
      return true;
    }
    return id === ALLOWED_USER_ID;
  }

  if (currentUserId() && currentUserId() !== ALLOWED_USER_ID) {
    return;
  }

  function sessid() {
    try {
      if (window.BX && typeof BX.bitrix_sessid === "function") {
        return BX.bitrix_sessid();
      }
    } catch (e) {}
    return "";
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent =
      "#" +
      WRAP_ID +
      "{display:block;width:100%;box-sizing:border-box;padding:8px 0 0;margin:0}" +
      "#" +
      BTN_ID +
      "{display:inline-flex;align-items:center;justify-content:center;gap:6px;" +
      "margin:0;padding:8px 14px;min-height:36px;border-radius:8px;border:1px solid #dfe3e6;" +
      "background:#fff;color:#333;font:600 13px/1.2 system-ui,Segoe UI,Arial,sans-serif;" +
      "cursor:pointer;width:100%;box-sizing:border-box}" +
      "#" +
      BTN_ID +
      "[data-on='1']{background:#2fc6f6;border-color:#2fc6f6;color:#fff}" +
      "#" +
      BTN_ID +
      ":disabled{opacity:.6;cursor:wait}";
    (document.head || document.documentElement).appendChild(s);
  }

  function paintBtn() {
    var btn = document.getElementById(BTN_ID);
    if (!btn) {
      return;
    }
    btn.setAttribute("data-on", state.enabled ? "1" : "0");
    btn.textContent = state.enabled ? "Auto ON" : "Auto";
    btn.title = state.enabled
      ? "Auto ON — clocks in around 10:00 and out around 19:30 PKT (Sunday off). Click to turn off."
      : "Auto OFF — click to enable 10:00 / 19:30 PKT (Sunday skipped).";
  }

  function post(action) {
    var body = "action=" + encodeURIComponent(action) + "&sessid=" + encodeURIComponent(sessid());
    return fetch(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
      body: body
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || !j || j.ok === false) {
          var err = (j && j.error) || "http_" + r.status;
          throw new Error(err);
        }
        return j;
      });
    });
  }

  function applyPayload(j) {
    if (j && j.user_id && parseInt(j.user_id, 10) !== ALLOWED_USER_ID) {
      state.allowed = false;
      return;
    }
    state.allowed = true;
    state.enabled = !!(j && j.enabled);
    state.loaded = true;
    paintBtn();
  }

  function toggle() {
    var btn = document.getElementById(BTN_ID);
    if (!btn || btn.disabled) {
      return;
    }
    if (!uidOk()) {
      return;
    }
    btn.disabled = true;
    var next = state.enabled ? "disable" : "enable";
    post(next)
      .then(applyPayload)
      .catch(function () {})
      .then(function () {
        btn.disabled = false;
        paintBtn();
      });
  }

  function normText(el) {
    return ((el && el.textContent) || "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function isClockAction(el) {
    var t = normText(el);
    if (!t || t.length > 40) {
      return false;
    }
    return (
      t === "pause" ||
      t === "clock out" ||
      t === "clock in" ||
      t.indexOf("clock out") === 0 ||
      t.indexOf("clock in") === 0
    );
  }

  function findClockCard() {
    var nodes = document.querySelectorAll("button, a, [role='button'], .ui-btn, [class*='btn']");
    var i;
    var el;
    var best = null;
    for (i = 0; i < nodes.length; i++) {
      el = nodes[i];
      if (!isClockAction(el)) {
        continue;
      }
      // Prefer the card that holds Pause + Clock out together.
      var p = el.parentElement;
      var depth = 0;
      while (p && depth < 8) {
        var txt = normText(p);
        if (
          (txt.indexOf("pause") !== -1 && txt.indexOf("clock") !== -1) ||
          txt.indexOf("clocked in") !== -1 ||
          txt.indexOf("clocked out") !== -1
        ) {
          best = p;
          break;
        }
        p = p.parentElement;
        depth += 1;
      }
      if (best) {
        break;
      }
      best = el.parentElement || el;
    }
    if (best) {
      return best;
    }

    // Fallback: any node whose text starts with Clocked in/out.
    var all = document.querySelectorAll("div, section, aside, li");
    for (i = 0; i < all.length; i++) {
      el = all[i];
      var t = normText(el);
      if (
        (t.indexOf("clocked in") === 0 || t.indexOf("clocked out") === 0) &&
        t.length < 80
      ) {
        return el.parentElement || el;
      }
    }
    return null;
  }

  function mount() {
    if (!uidOk()) {
      return false;
    }
    if (document.getElementById(BTN_ID)) {
      paintBtn();
      return true;
    }
    var host = findClockCard();
    if (!host) {
      return false;
    }
    ensureStyle();
    var wrap = document.createElement("div");
    wrap.id = WRAP_ID;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = BTN_ID;
    btn.setAttribute("data-on", state.enabled ? "1" : "0");
    btn.textContent = state.enabled ? "Auto ON" : "Auto";
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggle();
    });
    wrap.appendChild(btn);
    host.appendChild(wrap);
    paintBtn();
    return true;
  }

  function refreshStatus() {
    if (!uidOk()) {
      return;
    }
    post("status")
      .then(applyPayload)
      .catch(function (err) {
        if (String(err && err.message) === "forbidden") {
          state.allowed = false;
        }
      });
  }

  function startWatch() {
    if (watchTimer) {
      return;
    }
    var tries = 0;
    watchTimer = setInterval(function () {
      tries += 1;
      if (!uidOk()) {
        clearInterval(watchTimer);
        watchTimer = 0;
        return;
      }
      mount();
      if (tries > 120) {
        clearInterval(watchTimer);
        watchTimer = 0;
      }
    }, 400);
  }

  function boot() {
    if (currentUserId() && currentUserId() !== ALLOWED_USER_ID) {
      return;
    }
    refreshStatus();
    startWatch();

    // Profile menu opens later — remount on click + DOM changes.
    document.addEventListener(
      "click",
      function () {
        if (!uidOk()) {
          return;
        }
        setTimeout(function () {
          mount();
          paintBtn();
        }, 200);
        setTimeout(function () {
          mount();
          paintBtn();
        }, 600);
      },
      true
    );

    try {
      var obs = new MutationObserver(function () {
        if (!uidOk()) {
          return;
        }
        if (document.getElementById(BTN_ID)) {
          return;
        }
        mount();
      });
      obs.observe(document.documentElement, { childList: true, subtree: true });
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
