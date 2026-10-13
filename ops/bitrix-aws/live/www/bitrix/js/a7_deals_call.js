/**
 * A7 Sales Deals dual Call buttons (deal category 1 kanban/details).
 * — Zadarma: BXIM.phoneTo → ONEXTERNALCALLSTART → Zadarma
 * — Voiso: POST deal-call-voiso → cc-ams04 click2call (does NOT fire phoneTo)
 */
(function () {
  if (window.A7_DEALS_CALL_LOADED) {
    return;
  }
  window.A7_DEALS_CALL_LOADED = true;

  var PATH = String(location.pathname || "");
  var SEARCH = String(location.search || "");
  if (!/\/crm\/deal\//i.test(PATH)) {
    return;
  }

  var isCat1Kanban =
    /\/crm\/deal\/kanban\/category\/1\/?/i.test(PATH) ||
    (/\/crm\/deal\/kanban\//i.test(PATH) && /[?&]category_id=1\b/i.test(SEARCH)) ||
    (/\/crm\/deal\/kanban\/?$/i.test(PATH) && !/[?&]category_id=\d+/i.test(SEARCH));
  var isDealDetails = /\/crm\/deal\/details\/\d+\//i.test(PATH);
  if (!isCat1Kanban && !isDealDetails) {
    return;
  }

  var ENDPOINT = "/bitrix/tools/a7_3cx_click_to_call.php";
  var FETCH_MS = 12000;
  var STYLE_ID = "a7-deal-call-style";
  var BTN_CLASS = "a7-deal-call-btn";
  var WRAP_CLASS = "a7-deal-call-btns";
  var PICKER_CLASS = "a7-deal-call-picker";
  var ENTITY_TYPE_ID = 2;
  var SALES_CATEGORY_ID = 1;

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
      console[ok === false ? "warn" : "log"]("[A7 Deals Call]", message);
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
      throw new Error("Zadarma dialer not ready. Open a7 cloud / Zadarma and refresh.");
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

  function dialViaVoiso(dealId, phone) {
    var dial = normalizeDialPhone(phone);
    if (!dial || dial.indexOf("+971") !== 0) {
      return Promise.reject(new Error("Invalid UAE phone (need +971…)"));
    }
    var body = new URLSearchParams();
    body.set("action", "deal-call-voiso");
    body.set("id", String(dealId));
    body.set("phone", dial);
    body.set("sessid", bitrixSessid());
    body.set("pageUrl", String(location.href || ""));
    return fetchJson(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: body.toString()
    }).then(function (res) {
      var data = parseJsonLoose(res.text);
      if (!res.ok || !data || !data.success) {
        throw new Error((data && data.message) || "Voiso call failed");
      }
      return { phone: dial, provider: "voiso", detail: data };
    });
  }

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = [
      "." + WRAP_CLASS + "{display:flex;flex-wrap:wrap;gap:6px;margin:8px 8px 4px;}",
      "." + WRAP_CLASS + "--detail{display:inline-flex;margin-left:8px;}",
      "." + BTN_CLASS + "{display:inline-flex;align-items:center;justify-content:center;gap:5px;height:28px;padding:0 10px;border-radius:14px;border:1px solid transparent;font-size:12px;font-weight:700;line-height:1;cursor:pointer;box-shadow:0 1px 2px rgba(15,23,42,.12);white-space:nowrap;}",
      "." + BTN_CLASS + "[disabled]{opacity:.65;cursor:wait;}",
      "." + BTN_CLASS + "--zadarma{background:#22c55e;border-color:#16a34a;color:#fff;}",
      "." + BTN_CLASS + "--zadarma:hover{background:#16a34a;}",
      "." + BTN_CLASS + "--voiso{background:#2563eb;border-color:#1d4ed8;color:#fff;}",
      "." + BTN_CLASS + "--voiso:hover{background:#1d4ed8;}",
      "." + BTN_CLASS + "--detail{height:32px;padding:0 12px;font-size:13px;border-radius:16px;}",
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

  function choosePhone(candidates, clientX, clientY, title) {
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
      head.appendChild(document.createTextNode(title || "Choose number"));
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
      if (data.skipped) {
        return [];
      }
      return Array.isArray(data.phones)
        ? data.phones
            .map(function (row) {
              return {
                phone: normalizeDialPhone(row.phone),
                label: row.label || "Phone",
                field: row.field || ""
              };
            })
            .filter(function (row) {
              return row.phone && row.phone.indexOf("+971") === 0;
            })
        : [];
    });
  }

  function runCallFlow(provider, dealId, clientX, clientY, button) {
    if (!dealId) {
      notify("Deal id missing", false);
      return;
    }
    if (button) {
      button.disabled = true;
    }
    var pickerTitle = provider === "voiso" ? "Call with Voiso" : "Call with Zadarma";
    loadPhones(dealId)
      .then(function (phones) {
        if (!phones.length) {
          notify("No phone number on this deal / linked contact", false);
          return null;
        }
        return choosePhone(phones, clientX, clientY, pickerTitle);
      })
      .then(function (chosen) {
        if (!chosen || !chosen.phone) {
          return null;
        }
        if (provider === "voiso") {
          return dialViaVoiso(dealId, chosen.phone).then(function (result) {
            notify("Voiso call: " + result.phone, true);
          });
        }
        var result = dialViaZadarma(dealId, chosen.phone);
        notify("Zadarma call: " + result.phone, true);
        return null;
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

  function makeButton(provider, kind) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      BTN_CLASS +
      " " +
      BTN_CLASS +
      "--" +
      provider +
      (kind === "detail" ? " " + BTN_CLASS + "--detail" : "");
    btn.setAttribute("data-a7-deal-call", provider);
    btn.appendChild(
      document.createTextNode(provider === "voiso" ? "Call with Voiso" : "Call with Zadarma")
    );
    return btn;
  }

  function bindButton(btn, provider, dealId) {
    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }
      var id = dealId || btn.getAttribute("data-a7-deal-item") || dealIdFromCard(btn);
      runCallFlow(provider, id, event.clientX, event.clientY, btn);
    });
  }

  function makeButtonPair(kind, dealId) {
    var wrap = document.createElement("div");
    wrap.className = WRAP_CLASS + (kind === "detail" ? " " + WRAP_CLASS + "--detail" : "");
    wrap.setAttribute("data-a7-deal-btns", "1");

    var zadarma = makeButton("zadarma", kind);
    var voiso = makeButton("voiso", kind);
    if (dealId) {
      zadarma.setAttribute("data-a7-deal-item", dealId);
      voiso.setAttribute("data-a7-deal-item", dealId);
    }
    bindButton(zadarma, "zadarma", dealId);
    bindButton(voiso, "voiso", dealId);
    wrap.appendChild(zadarma);
    wrap.appendChild(voiso);
    return wrap;
  }

  var detailProbeStarted = false;

  function mountDetailButton() {
    var dealId = dealIdFromLocation();
    if (!dealId) {
      return;
    }
    if (document.querySelector("." + WRAP_CLASS + "[data-a7-deal-detail='1']")) {
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
    var wrap = makeButtonPair("detail", dealId);
    wrap.setAttribute("data-a7-deal-detail", "1");

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
      if (Number(data.categoryId) !== SALES_CATEGORY_ID) {
        return;
      }
      if (document.querySelector("." + WRAP_CLASS + "[data-a7-deal-detail='1']")) {
        return;
      }
      host.appendChild(wrap);
    });
  }

  function mountKanbanButtons() {
    if (!isCat1Kanban) {
      return;
    }
    var cards = document.querySelectorAll(".crm-kanban-item, .main-kanban-item");
    for (var i = 0; i < cards.length; i += 1) {
      var card = cards[i];
      if (card.querySelector("." + WRAP_CLASS + "[data-a7-deal-btns='1']")) {
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
      var wrap = makeButtonPair("kanban", id);
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
