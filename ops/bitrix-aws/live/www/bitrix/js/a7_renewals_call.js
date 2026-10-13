/**
 * A7 Renewals Deals custom Call button (deal category 9).
 * Reads tenant/owner phone UFs, dials via BXIM.phoneTo → Zadarma
 * (same path as lead / Owner Data custom Call button).
 */
(function () {
  if (window.A7_RENEWALS_CALL_LOADED) {
    return;
  }
  window.A7_RENEWALS_CALL_LOADED = true;

  var PATH = String(location.pathname || "");
  var SEARCH = String(location.search || "");
  var isDealPage = /\/crm\/deal\//i.test(PATH);
  if (!isDealPage) {
    return;
  }

  // Kanban category 9, or deal details (category checked server-side).
  var isCat9Kanban =
    /\/crm\/deal\/kanban\/category\/9\/?/i.test(PATH) ||
    (/\/crm\/deal\/kanban\//i.test(PATH) && /[?&]category_id=9\b/i.test(SEARCH));
  var isDealDetails = /\/crm\/deal\/details\/\d+\//i.test(PATH);
  if (!isCat9Kanban && !isDealDetails) {
    return;
  }

  var ENDPOINT = "/bitrix/tools/a7_3cx_click_to_call.php";
  var FETCH_MS = 10000;
  var STYLE_ID = "a7-od-call-style";
  var BTN_CLASS = "a7-od-call-btn";
  var PICKER_CLASS = "a7-od-call-picker";
  var ENTITY_TYPE_ID = 2; // DEAL

  function notify(message, ok) {
    try {
      if (window.BX && BX.UI && BX.UI.Notification && BX.UI.Notification.Center) {
        BX.UI.Notification.Center.notify({
          content: message,
          autoHideDelay: ok === false ? 6500 : 3500
        });
        return;
      }
    } catch (e) {}
    if (window.console) {
      console[ok === false ? "warn" : "log"]("[A7 Renewals Call]", message);
    }
  }

  function bitrixSessid() {
    try {
      if (window.BX && typeof BX.bitrix_sessid === "function") {
        return BX.bitrix_sessid();
      }
    } catch (e) {}
    return "";
  }

  function dealIdFromLocation() {
    var match = PATH.match(/\/crm\/deal\/details\/(\d+)\//i);
    return match ? match[1] : "";
  }

  function dealIdFromCard(node) {
    if (!node || !node.closest) {
      return "";
    }
    var card = node.closest(
      "[data-id], [data-item-id], .crm-kanban-item, .main-kanban-item"
    );
    if (!card) {
      return "";
    }
    var id =
      card.getAttribute("data-id") ||
      card.getAttribute("data-item-id") ||
      card.getAttribute("data-entity-id") ||
      "";
    return String(id || "").replace(/\D/g, "");
  }

  function fetchJson(url, options) {
    options = options || {};
    if (!window.AbortController) {
      return fetch(url, options).then(function (r) {
        return r.text().then(function (text) {
          return { ok: r.ok, status: r.status, text: text };
        });
      });
    }
    var controller = new AbortController();
    var timer = window.setTimeout(function () {
      controller.abort();
    }, FETCH_MS);
    var merged = {};
    Object.keys(options).forEach(function (key) {
      merged[key] = options[key];
    });
    merged.signal = controller.signal;
    return fetch(url, merged)
      .then(function (r) {
        return r.text().then(function (text) {
          return { ok: r.ok, status: r.status, text: text };
        });
      })
      .finally(function () {
        window.clearTimeout(timer);
      });
  }

  function parseJsonLoose(text) {
    try {
      return JSON.parse(text);
    } catch (e) {
      var match = String(text || "").match(/\{[\s\S]*\}/);
      if (match) {
        try {
          return JSON.parse(match[0]);
        } catch (ignored) {}
      }
    }
    return null;
  }

  /**
   * Always dial E.164 UAE: +971… with no spaces.
   */
  function normalizeDialPhone(raw) {
    var digits = String(raw || "").replace(/\D/g, "");
    if (!digits) {
      return "";
    }
    if (digits.indexOf("00") === 0) {
      digits = digits.slice(2);
    }
    if (digits.indexOf("971") === 0) {
      return "+" + digits;
    }
    if (digits.charAt(0) === "0") {
      return "+971" + digits.slice(1);
    }
    if (digits.length >= 8 && digits.length <= 9) {
      return "+971" + digits;
    }
    return "+" + digits;
  }

  function entityTypeName() {
    try {
      if (window.BX && BX.CrmEntityType && typeof BX.CrmEntityType.resolveName === "function") {
        var name = BX.CrmEntityType.resolveName(ENTITY_TYPE_ID);
        if (name) {
          return name;
        }
      }
    } catch (e) {}
    return "DEAL";
  }

  function getBxim() {
    try {
      if (window.top && window.top.BXIM) {
        return window.top.BXIM;
      }
    } catch (e) {}
    return window.BXIM || null;
  }

  function dialViaZadarma(dealId, phone) {
    var bxim = getBxim();
    if (!bxim || typeof bxim.phoneTo !== "function") {
      throw new Error("Zadarma / Bitrix telephony not ready. Open the Zadarma dialer (a7 cloud) and refresh.");
    }
    var dial = normalizeDialPhone(phone);
    if (!dial || dial.indexOf("+971") !== 0) {
      throw new Error("Invalid UAE phone (need +971…)");
    }
    bxim.phoneTo(dial, {
      ENTITY_TYPE_NAME: entityTypeName(),
      ENTITY_ID: parseInt(dealId, 10) || dealId,
      AUTO_FOLD: true
    });
    return { phone: dial };
  }

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = [
      "." + BTN_CLASS + "{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 14px;border:1px solid #16a34a;border-radius:16px;background:#22c55e;color:#fff;font-size:13px;font-weight:700;line-height:1;cursor:pointer;box-shadow:0 1px 2px rgba(15,23,42,.12);}",
      "." + BTN_CLASS + ":hover{background:#16a34a;}",
      "." + BTN_CLASS + "[disabled]{opacity:.65;cursor:wait;}",
      "." + BTN_CLASS + "--kanban{height:26px;padding:0 10px;font-size:12px;border-radius:14px;}",
      "." + BTN_CLASS + "-wrap{display:inline-flex;align-items:center;margin-left:8px;}",
      "." + BTN_CLASS + "-kanban-wrap{display:flex;margin:6px 8px 4px;}",
      "." + PICKER_CLASS + "{position:fixed;z-index:2147483647;min-width:280px;max-width:360px;background:#fff;border:1px solid #c8d2dc;border-radius:14px;box-shadow:0 12px 34px rgba(15,23,42,.22);font-family:var(--ui-font-family-primary,Arial,sans-serif);overflow:hidden;color:#263238;}",
      "." + PICKER_CLASS + "-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid #e5edf3;font-weight:700;font-size:14px;}",
      "." + PICKER_CLASS + "-close{border:0;background:transparent;color:#8b99a8;font-size:22px;line-height:1;cursor:pointer;padding:0 2px;}",
      "." + PICKER_CLASS + "-list{max-height:320px;overflow:auto;padding:6px;}",
      "." + PICKER_CLASS + "-btn{display:block;width:100%;border:0;background:#fff;text-align:left;border-radius:10px;padding:10px 12px;cursor:pointer;color:#263238;}",
      "." + PICKER_CLASS + "-btn:hover{background:#eef8ff;}",
      "." + PICKER_CLASS + "-label{display:block;font-size:12px;color:#8391a2;margin-bottom:3px;}",
      "." + PICKER_CLASS + "-phone{display:block;font-size:15px;font-weight:700;color:#1c5f91;}"
    ].join("\n");
    document.head.appendChild(style);
  }

  function removePicker() {
    var existing = document.querySelector("." + PICKER_CLASS);
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }
  }

  function choosePhone(candidates, clientX, clientY) {
    return new Promise(function (resolve) {
      removePicker();
      ensureStyles();
      if (!candidates || !candidates.length) {
        resolve(null);
        return;
      }
      if (candidates.length === 1) {
        resolve(candidates[0]);
        return;
      }

      var box = document.createElement("div");
      box.className = PICKER_CLASS;
      var head = document.createElement("div");
      head.className = PICKER_CLASS + "-head";
      head.appendChild(document.createTextNode("Choose number to call"));
      var close = document.createElement("button");
      close.type = "button";
      close.className = PICKER_CLASS + "-close";
      close.appendChild(document.createTextNode("\u00d7"));
      head.appendChild(close);
      box.appendChild(head);

      var list = document.createElement("div");
      list.className = PICKER_CLASS + "-list";
      candidates.forEach(function (candidate) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = PICKER_CLASS + "-btn";
        var label = document.createElement("span");
        label.className = PICKER_CLASS + "-label";
        label.textContent = candidate.label || "Phone";
        btn.appendChild(label);
        var phone = document.createElement("span");
        phone.className = PICKER_CLASS + "-phone";
        phone.textContent = candidate.phone;
        btn.appendChild(phone);
        btn.addEventListener("click", function () {
          removePicker();
          resolve(candidate);
        });
        list.appendChild(btn);
      });
      box.appendChild(list);

      function cancel() {
        removePicker();
        resolve(null);
      }
      close.addEventListener("click", cancel);
      document.addEventListener(
        "keydown",
        function onKey(event) {
          if (event.key === "Escape") {
            document.removeEventListener("keydown", onKey, true);
            cancel();
          }
        },
        true
      );

      document.body.appendChild(box);
      var left = Math.max(
        12,
        Math.min(window.innerWidth - box.offsetWidth - 12, Number(clientX || 0) - 20)
      );
      var top = Math.max(
        12,
        Math.min(window.innerHeight - box.offsetHeight - 12, Number(clientY || 0) + 16)
      );
      box.style.left = left + "px";
      box.style.top = top + "px";
    });
  }

  function loadPhones(dealId) {
    var params = new URLSearchParams();
    params.set("action", "deal-phones");
    params.set("id", String(dealId));
    params.set("sessid", bitrixSessid());
    return fetchJson(ENDPOINT + "?" + params.toString(), {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store"
    }).then(function (res) {
      var data = parseJsonLoose(res.text);
      if (!res.ok || !data || !data.success) {
        throw new Error((data && data.message) || "Could not load deal phones");
      }
      // Detail pages outside cat 9: server returns skip/empty — hide quietly.
      if (data.skipped) {
        return [];
      }
      return Array.isArray(data.phones) ? data.phones : [];
    });
  }

  function runCallFlow(dealId, clientX, clientY, button) {
    if (!dealId) {
      notify("Deal id missing", false);
      return;
    }
    if (button) {
      button.disabled = true;
    }
    loadPhones(dealId)
      .then(function (phones) {
        if (!phones.length) {
          notify("No phone number on this deal", false);
          return null;
        }
        return choosePhone(phones, clientX, clientY);
      })
      .then(function (chosen) {
        if (!chosen || !chosen.phone) {
          return null;
        }
        var result = dialViaZadarma(dealId, chosen.phone);
        notify("Zadarma call: " + result.phone, true);
      })
      .catch(function (error) {
        notify(error && error.message ? error.message : "Call error", false);
      })
      .finally(function () {
        if (button) {
          button.disabled = false;
        }
      });
  }

  function makeButton(kind) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = BTN_CLASS + (kind === "kanban" ? " " + BTN_CLASS + "--kanban" : "");
    btn.setAttribute("data-a7-renewals-call", "1");
    btn.appendChild(document.createTextNode(kind === "kanban" ? "Call" : "Call number"));
    return btn;
  }

  var detailProbeStarted = false;

  function mountDetailButton() {
    var dealId = dealIdFromLocation();
    if (!dealId) {
      return;
    }
    if (document.querySelector("." + BTN_CLASS + "[data-a7-renewals-detail='1']")) {
      return;
    }
    if (detailProbeStarted) {
      return;
    }
    detailProbeStarted = true;

    var hosts = [
      ".ui-toolbar-right-buttons",
      ".ui-toolbar-after-title-buttons",
      ".pagetitle-align-right-container",
      ".crm-entity-actions-container"
    ];
    var host = null;
    for (var i = 0; i < hosts.length; i += 1) {
      host = document.querySelector(hosts[i]);
      if (host) {
        break;
      }
    }
    if (!host) {
      host = document.querySelector(".pagetitle-inner") || document.querySelector(".ui-toolbar");
    }
    if (!host) {
      return;
    }

    ensureStyles();
    var wrap = document.createElement("span");
    wrap.className = BTN_CLASS + "-wrap";
    var btn = makeButton("detail");
    btn.setAttribute("data-a7-renewals-detail", "1");
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      runCallFlow(dealId, event.clientX, event.clientY, btn);
    });
    wrap.appendChild(btn);

    // Only show after we know phones endpoint accepts this deal (cat 9).
    var params = new URLSearchParams();
    params.set("action", "deal-phones");
    params.set("id", String(dealId));
    params.set("sessid", bitrixSessid());
    fetchJson(ENDPOINT + "?" + params.toString(), {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store"
    }).then(function (res) {
      var data = parseJsonLoose(res.text);
      if (!data || !data.success || data.skipped) {
        return;
      }
      if (document.querySelector("." + BTN_CLASS + "[data-a7-renewals-detail='1']")) {
        return;
      }
      host.appendChild(wrap);
    });
  }

  function mountKanbanButtons() {
    if (!isCat9Kanban) {
      return;
    }
    var cards = document.querySelectorAll(".crm-kanban-item, .main-kanban-item");
    for (var i = 0; i < cards.length; i += 1) {
      var card = cards[i];
      if (card.querySelector("." + BTN_CLASS + "[data-a7-renewals-call]")) {
        continue;
      }
      var id =
        card.getAttribute("data-id") ||
        card.getAttribute("data-item-id") ||
        "";
      id = String(id || "").replace(/\D/g, "");
      if (!id) {
        continue;
      }

      ensureStyles();
      var wrap = document.createElement("div");
      wrap.className = BTN_CLASS + "-kanban-wrap";
      var btn = makeButton("kanban");
      btn.setAttribute("data-a7-renewals-item", id);
      btn.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }
        var target = event.currentTarget;
        var dealId = target.getAttribute("data-a7-renewals-item") || dealIdFromCard(target);
        runCallFlow(dealId, event.clientX, event.clientY, target);
      });
      wrap.appendChild(btn);

      var body =
        card.querySelector(".crm-kanban-item-fields") ||
        card.querySelector(".main-kanban-item-container") ||
        card;
      body.appendChild(wrap);
    }
  }

  function refresh() {
    if (isDealDetails) {
      mountDetailButton();
    }
    mountKanbanButtons();
  }

  // Debounced remount only — sync MutationObserver refresh freezes large kanbans.
  var remountTimer = null;
  var remountBusy = false;
  function scheduleRefresh() {
    if (remountBusy) {
      return;
    }
    if (remountTimer) {
      window.clearTimeout(remountTimer);
    }
    remountTimer = window.setTimeout(function () {
      remountTimer = null;
      remountBusy = true;
      try {
        refresh();
      } finally {
        window.setTimeout(function () {
          remountBusy = false;
        }, 750);
      }
    }, 1000);
  }

  ensureStyles();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleRefresh);
  } else {
    scheduleRefresh();
  }
  window.setTimeout(scheduleRefresh, 1500);
  window.setTimeout(scheduleRefresh, 4500);

  if (window.MutationObserver) {
    var observer = new MutationObserver(function () {
      scheduleRefresh();
    });
    observer.observe(document.body || document.documentElement, {
      childList: true,
      subtree: false
    });
  }
})();
