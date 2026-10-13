/**
 * A7 CRM list / kanban WhatsApp campaign popup.
 * The title-bar button stays off the page until at least one Lead or
 * Owner Data / Availability card is selected, then one Official campaign.
 */
(function () {
  if (window.A7_LEAD_WA_V8) {
    return;
  }
  window.A7_LEAD_WA_V8 = true;

  var PATH = String(location.pathname || "");
  var onLeads = /\/crm\/lead\//i.test(PATH) && !/\/crm\/lead\/details\//i.test(PATH);
  var onOwner =
    /\/crm\/type\/1042\//i.test(PATH) && !/\/crm\/type\/1042\/details\//i.test(PATH);
  if (!onLeads && !onOwner) {
    return;
  }
  var ENTITY = onOwner ? "owner_data" : "lead";
  var NOUN = onOwner ? "cards" : "leads";
  var NOUN_ONE = onOwner ? "card" : "lead";

  var ENDPOINT = "/bitrix/tools/a7_lead_wa.php";
  var FETCH_MS = 20000;
  var STYLE_ID = "a7-lwa-style-v5";
  var BTN_CLASS = "a7-lwa-btn";
  var SLOT_CLASS = "a7-lwa-slot";
  var MAX_LEADS = 500;
  var overlay = null;
  var busy = false;
  var prevOverflow = "";

  function notify(message, ok) {
    try {
      if (window.BX && BX.UI && BX.UI.Notification && BX.UI.Notification.Center) {
        BX.UI.Notification.Center.notify({
          content: message,
          autoHideDelay: ok === false ? 7000 : 3500
        });
        return;
      }
    } catch (e) {}
    if (window.console) {
      console[ok === false ? "warn" : "log"]("[A7 Lead WA]", message);
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

  function uniqueIds(list) {
    var seen = {};
    var out = [];
    for (var i = 0; i < list.length; i += 1) {
      var raw = String(list[i] || "").trim();
      var id = /^\d+$/.test(raw)
        ? raw
        : ((raw.match(/(\d+)(?:\D*)$/) || [])[1] || "");
      if (!id || seen[id]) {
        continue;
      }
      seen[id] = true;
      out.push(id);
    }
    return out;
  }

  function selectedGridIds() {
    var ids = [];
    try {
      var mgr = window.BX && BX.Main && BX.Main.gridManager;
      var data = mgr && (mgr.data || mgr.list);
      if (data && data.length) {
        for (var i = 0; i < data.length; i += 1) {
          var grid = data[i] && data[i].instance;
          if (!grid || typeof grid.getRows !== "function") {
            continue;
          }
          var rows = grid.getRows();
          if (!rows || typeof rows.getSelectedIds !== "function") {
            continue;
          }
          var picked = rows.getSelectedIds() || [];
          for (var j = 0; j < picked.length; j += 1) {
            ids.push(picked[j]);
          }
        }
      }
    } catch (e) {}
    var checked = document.querySelectorAll(
      ".main-grid-row-checked[data-id], .main-grid-row.main-grid-row-checked"
    );
    for (var k = 0; k < checked.length; k += 1) {
      ids.push(
        checked[k].getAttribute("data-id") ||
          checked[k].getAttribute("data-row-id") ||
          ""
      );
    }
    return uniqueIds(ids);
  }

  function selectedKanbanIds() {
    var ids = [];
    try {
      var Kanban = window.BX && BX.CRM && BX.CRM.Kanban && BX.CRM.Kanban.Grid;
      var inst =
        Kanban &&
        ((typeof Kanban.getInstance === "function" && Kanban.getInstance()) ||
          Kanban.Instance);
      if (inst) {
        if (typeof inst.getChecked === "function") {
          var checked = inst.getChecked() || [];
          for (var i = 0; i < checked.length; i += 1) {
            var item = checked[i];
            ids.push((item && (item.id || (item.getId && item.getId()))) || "");
          }
        } else if (typeof inst.getItems === "function") {
          var items = inst.getItems() || [];
          for (var n = 0; n < items.length; n += 1) {
            var row = items[n];
            if (row && typeof row.isChecked === "function" && row.isChecked()) {
              ids.push(row.getId ? row.getId() : row.id);
            }
          }
        }
      }
    } catch (e) {}
    var cards = document.querySelectorAll(
      ".crm-kanban-item.main-kanban-item-checked, .main-kanban-item.main-kanban-item-checked, .crm-kanban-item--checked"
    );
    for (var c = 0; c < cards.length; c += 1) {
      ids.push(
        cards[c].getAttribute("data-id") ||
          cards[c].getAttribute("data-item-id") ||
          ""
      );
    }
    var boxes = document.querySelectorAll(
      ".crm-kanban-item input[type=checkbox]:checked, .main-kanban-item input[type=checkbox]:checked"
    );
    for (var b = 0; b < boxes.length; b += 1) {
      var card = boxes[b].closest
        ? boxes[b].closest(".crm-kanban-item, .main-kanban-item")
        : null;
      if (card) {
        ids.push(card.getAttribute("data-id") || card.getAttribute("data-item-id") || "");
      }
    }
    return uniqueIds(ids);
  }

  function selectedLeadIds() {
    return uniqueIds(selectedGridIds().concat(selectedKanbanIds()));
  }

  function fetchJson(url, options) {
    options = options || {};
    var controller = window.AbortController ? new AbortController() : null;
    var timer = null;
    var merged = {};
    Object.keys(options).forEach(function (key) {
      merged[key] = options[key];
    });
    if (controller) {
      merged.signal = controller.signal;
      timer = window.setTimeout(function () {
        controller.abort();
      }, FETCH_MS);
    }
    return fetch(url, merged)
      .then(function (r) {
        return r.text().then(function (text) {
          return { ok: r.ok, status: r.status, text: text };
        });
      })
      .finally(function () {
        if (timer) {
          window.clearTimeout(timer);
        }
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

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent =
      "." + SLOT_CLASS + "{display:inline-flex !important;align-items:center;margin:0 8px;" +
      "padding:3px;background:#fff;border:1px solid #d0d7de;border-radius:10px;" +
      "box-shadow:0 1px 2px rgba(16,185,129,.12);vertical-align:middle;width:auto !important;}" +
      "." + BTN_CLASS + "{background:#fff !important;color:#334155 !important;" +
      "border:1px solid #cbd5e1 !important;border-radius:8px;padding:0 12px;height:32px;" +
      "font:600 13px/1 Segoe UI,Arial,sans-serif !important;cursor:pointer;white-space:nowrap;" +
      "display:inline-flex !important;align-items:center;gap:7px;box-shadow:none !important;}" +
      "." + BTN_CLASS + ":hover{background:#f0fdf4 !important;}" +
      "." + BTN_CLASS + " .a7-lwa-ic{color:#25D366;}" +
      ".a7-lwa-overlay,.a7-lwa-overlay *{box-sizing:border-box;letter-spacing:normal !important;" +
      "font-family:Segoe UI,Arial,sans-serif !important;font-stretch:normal !important;}" +
      ".a7-lwa-overlay{position:fixed;inset:0;z-index:12000;background:rgba(20,131,110,.22);" +
      "display:flex;align-items:center;justify-content:center;padding:16px;color:#334155;}" +
      ".a7-lwa-modal{width:min(980px,100%);height:min(94vh,920px);max-height:94vh;background:#fff;" +
      "border-radius:12px;box-shadow:0 18px 48px rgba(20,131,110,.22);display:flex;" +
      "flex-direction:column;overflow:hidden;}" +
      ".a7-lwa-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;" +
      "padding:16px 18px 12px;border-bottom:1px solid #e5e7eb;flex:0 0 auto;}" +
      ".a7-lwa-brand{display:flex;align-items:flex-start;gap:10px;min-width:0;}" +
      ".a7-lwa-brand h2{margin:0;font-size:16px;font-weight:600;color:#166534;}" +
      ".a7-lwa-sub{margin-top:2px;color:#64748b;font-size:12px;}" +
      ".a7-lwa-ic{width:16px;height:16px;display:block;flex:0 0 auto;}" +
      ".a7-lwa-ic-lg{width:20px;height:20px;color:#25D366;margin-top:1px;}" +
      ".a7-lwa-x{border:1px solid #e5e7eb;background:#fff;border-radius:8px;width:32px;height:32px;" +
      "padding:0;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;color:#64748b;}" +
      ".a7-lwa-grid{flex:1;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 250px;" +
      "gap:14px;padding:14px 18px;overflow:hidden;}" +
      ".a7-lwa-col{min-width:0;min-height:0;display:flex;flex-direction:column;gap:8px;overflow:hidden;}" +
      ".a7-lwa-col h3{margin:0;font-size:12px;font-weight:600;color:#64748b;display:flex;" +
      "align-items:center;gap:6px;}" +
      ".a7-lwa-label{display:block;font-weight:600;margin-bottom:4px;font-size:12px;color:#475569;}" +
      ".a7-lwa-input,.a7-lwa-select{width:100%;max-width:100%;border:1px solid #cbd5e1;" +
      "border-radius:8px;padding:7px 9px;font-size:13px;background:#fff;color:#334155;}" +
      ".a7-lwa-select{text-overflow:ellipsis;}" +
      ".a7-lwa-chips{display:flex;flex-wrap:wrap;gap:6px;}" +
      ".a7-lwa-chip{border:1px solid #e5e7eb;background:#f8fafc;border-radius:999px;padding:3px 9px;" +
      "font-size:12px;font-weight:600;cursor:pointer;color:#334155;}" +
      ".a7-lwa-chip.is-on{background:#128C7E;color:#fff;border-color:#128C7E;}" +
      ".a7-lwa-list{flex:1;min-height:180px;max-height:none;overflow:auto;border:1px solid #e5e7eb;" +
      "border-radius:8px;}" +
      ".a7-lwa-item{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #f1f5f9;" +
      "background:#fff;padding:8px 10px;cursor:pointer;color:#334155;font-size:13px;}" +
      ".a7-lwa-item div{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}" +
      ".a7-lwa-item small{display:block;color:#64748b;font-size:11px;}" +
      ".a7-lwa-item.is-on{background:#ecfdf5;}" +
      ".a7-lwa-item.is-off{color:#94a3b8;cursor:not-allowed;}" +
      ".a7-lwa-leads{max-height:140px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px;padding:0 8px;}" +
      ".a7-lwa-lead{display:flex;justify-content:space-between;gap:8px;padding:5px 0;" +
      "border-bottom:1px solid #f1f5f9;font-size:12px;}" +
      ".a7-lwa-lead b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;}" +
      ".a7-lwa-lead span{color:#64748b;flex:0 0 auto;}" +
      ".a7-lwa-lead.is-bad{color:#b91c1c;}" +
      ".a7-lwa-note{background:#fff7ed;color:#9a3412;border-radius:8px;padding:6px 8px;font-size:12px;}" +
      ".a7-lwa-err{color:#b91c1c;font-size:12px;}" +
      ".a7-lwa-preview{align-items:center;justify-content:flex-start;}" +
      ".a7-lwa-phone{width:228px;height:560px;background:#e2e8f0;border-radius:28px;padding:10px;" +
      "display:flex;flex-direction:column;flex:0 0 auto;border:1px solid #cbd5e1;}" +
      ".a7-lwa-phone-bar{height:14px;display:flex;justify-content:center;align-items:center;}" +
      ".a7-lwa-phone-bar b{width:56px;height:5px;border-radius:99px;background:#94a3b8;}" +
      ".a7-lwa-screen{flex:1;min-height:0;background:#ece5dd;border-radius:20px;overflow:hidden;" +
      "display:flex;flex-direction:column;}" +
      ".a7-lwa-wa-head{background:#128C7E;color:#fff;padding:8px 10px;font-size:12px;font-weight:600;}" +
      ".a7-lwa-wa-head div,.a7-lwa-wa-head small{display:block;overflow:hidden;text-overflow:ellipsis;" +
      "white-space:nowrap;}" +
      ".a7-lwa-wa-head small{font-weight:400;color:#d1fae5;font-size:10px;}" +
      ".a7-lwa-wa-chat{flex:1;overflow:auto;padding:10px 8px;background:#ece5dd;}" +
      ".a7-lwa-bubble{margin-left:16px;background:#dcf8c6;color:#166534;border-radius:8px 8px 2px 8px;" +
      "padding:7px 8px;white-space:pre-wrap;font-size:12px;overflow-wrap:anywhere;}" +
      ".a7-lwa-headtxt{font-weight:700;margin-bottom:4px;}" +
      ".a7-lwa-foot{color:#5b7a6e;font-size:10px;margin-top:5px;}" +
      ".a7-lwa-btns{display:flex;flex-direction:column;gap:5px;margin-top:6px;}" +
      ".a7-lwa-wabtn{background:#fff;color:#128C7E;border-radius:6px;padding:5px 6px;text-align:center;font-size:11px;}" +
      ".a7-lwa-empty{color:#64748b;font-size:12px;text-align:center;padding:28px 8px;}" +
      ".a7-lwa-footbar{display:flex;justify-content:space-between;align-items:center;gap:10px;" +
      "padding:12px 18px;border-top:1px solid #e5e7eb;flex:0 0 auto;}" +
      ".a7-lwa-actions{display:flex;align-items:center;gap:8px;}" +
      ".a7-lwa-send{background:#25D366;color:#fff;border:0;border-radius:8px;padding:8px 12px;" +
      "font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;}" +
      ".a7-lwa-send .a7-lwa-ic{color:#fff;}" +
      ".a7-lwa-send:disabled{opacity:.55;cursor:default;}" +
      ".a7-lwa-cancel{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:8px 12px;" +
      "font-size:13px;cursor:pointer;color:#334155;}" +
      ".a7-lwa-vars{max-height:160px;overflow:auto;}" +
      "@media (max-width:720px){.a7-lwa-grid{grid-template-columns:1fr;}.a7-lwa-phone{height:360px;width:200px;}" +
      ".a7-lwa-modal{height:min(96vh,920px);}}";
    document.head.appendChild(style);
  }

  function closeStudio() {
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
    overlay = null;
    busy = false;
    document.body.style.overflow = prevOverflow;
    document.removeEventListener("keydown", onEsc);
  }

  function onEsc(ev) {
    if (ev.key === "Escape" && overlay) {
      closeStudio();
    }
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      if (key === "className") {
        node.className = attrs[key];
      } else if (key === "text") {
        node.textContent = attrs[key];
      } else if (key.slice(0, 2) === "on") {
        node.addEventListener(key.slice(2).toLowerCase(), attrs[key]);
      } else if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, attrs[key]);
      }
    });
    (children || []).forEach(function (child) {
      if (child) {
        node.appendChild(child);
      }
    });
    return node;
  }

  function icon(name, extraClass) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "a7-lwa-ic" + (extraClass ? " " + extraClass : ""));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    function path(d, fill) {
      var n = document.createElementNS(ns, "path");
      n.setAttribute("d", d);
      if (fill) {
        n.setAttribute("fill", fill);
        n.setAttribute("stroke", "none");
      }
      svg.appendChild(n);
    }
    function circle(cx, cy, r) {
      var n = document.createElementNS(ns, "circle");
      n.setAttribute("cx", cx);
      n.setAttribute("cy", cy);
      n.setAttribute("r", r);
      svg.appendChild(n);
    }
    if (name === "close") {
      path("M6 6l12 12");
      path("M18 6L6 18");
    } else if (name === "wa") {
      svg.setAttribute("stroke", "none");
      path(
        "M12 2a10 10 0 00-8.7 14.9L2 22l5.3-1.4A10 10 0 1012 2zm5.1 14.3c-.3.7-1.5 1.3-2.1 1.3-.5 0-1.1.2-3.6-.8-3.1-1.3-5.1-4.5-5.2-4.7-.2-.2-1.3-1.7-1.3-3.3 0-1.5.8-2.3 1.1-2.6.3-.3.6-.4.8-.4h.6c.2 0 .4 0 .6.5.2.5.8 1.9.8 2 0 .2 0 .4-.2.6l-.4.5c-.1.2-.3.3 0 .6.2.3.9 1.5 2 2.5 1.4 1.3 2.5 1.7 2.8 1.9.3.1.5.1.7-.1l.8-1c.2-.2.4-.2.7-.1.3 0 1.8.8 2.1 1 .3.1.5.2.6.4.1.3 0 .8-.3 1.4z",
        "currentColor"
      );
    } else if (name === "phone") {
      path("M6.6 3.8h3.1l1.4 3.4-2 1.1a12.2 12.2 0 006.6 6.6l1.1-2 3.4 1.4v3.1A15.8 15.8 0 016.6 3.8z");
    } else if (name === "users") {
      circle("9", "8", "3");
      path("M3.2 19a5.8 5.8 0 0111.6 0");
      circle("17", "8.2", "2.3");
      path("M16.2 13.2a4.8 4.8 0 014.6 5.8");
    } else if (name === "search") {
      circle("11", "11", "6");
      path("M20 20l-3.4-3.4");
    } else if (name === "send") {
      path("M4 12l16-8-6 16-2.4-6.6L4 12z");
    }
    return svg;
  }

  function fieldBlock(label, input) {
    return el("label", {}, [
      el("span", { className: "a7-lwa-label", text: label }),
      input
    ]);
  }

  function templateHay(t) {
    return [t.name, t.language, t.category, t.body_text].join(" ").toLowerCase();
  }

  function dialHint(phone) {
    var d = String(phone || "").replace(/\D/g, "");
    if (d.indexOf("971") === 0) {
      return "UAE";
    }
    if (d.indexOf("44") === 0) {
      return "UK";
    }
    return "";
  }

  function numberLabel(n) {
    if (!n) {
      return "Official number";
    }
    var title = n.title || n.display_name || n.label || "Official number";
    var phone = n.phone_number ? "+" + n.phone_number : "";
    var hint = dialHint(n.phone_number);
    return (title + (hint ? " · " + hint : "") + (phone ? " " + phone : "")).trim();
  }

  function fillVars(text, vars) {
    return String(text || "").replace(/\{\{(\d+)\}\}/g, function (_, n) {
      var value = vars[n];
      return value != null && String(value) !== "" ? String(value) : "{{" + n + "}}";
    });
  }

  function sampleName(leads) {
    for (var i = 0; i < leads.length; i += 1) {
      var name = String(leads[i].name || "").trim();
      if (name && !/^(untitled|unentitled)$/i.test(name)) {
        return name;
      }
    }
    return "Customer";
  }

  function openStudio(leadIds, context) {
    ensureStyles();
    closeStudio();
    var templates = context.templates || [];
    var numbers = context.numbers && context.numbers.length
      ? context.numbers
      : context.number
        ? [context.number]
        : [];
    var leads = context.leads || [];
    var selectedNumber = numbers[0] || context.number || null;
    if (context.number && context.number.id) {
      for (var ni = 0; ni < numbers.length; ni += 1) {
        if (String(numbers[ni].id) === String(context.number.id)) {
          selectedNumber = numbers[ni];
          break;
        }
      }
    }
    var selected = null;
    var category = "ALL";
    var extraInputs = {};
    var headerInputs = {};
    var buttonInputs = {};

    var numberSelect = el("select", { className: "a7-lwa-select" });
    numbers.forEach(function (n) {
      var opt = el("option", { text: numberLabel(n) });
      opt.value = String(n.id);
      numberSelect.appendChild(opt);
    });
    if (selectedNumber) {
      numberSelect.value = String(selectedNumber.id);
    }

    var search = el("input", {
      className: "a7-lwa-input",
      type: "search",
      placeholder: "Search templates"
    });
    var chips = el("div", { className: "a7-lwa-chips" });
    var list = el("div", { className: "a7-lwa-list" });
    var extras = el("div", { className: "a7-lwa-vars" });
    var err = el("div", { className: "a7-lwa-err" });
    var note = el("div", { className: "a7-lwa-note" });
    var leadBox = el("div", { className: "a7-lwa-leads" });
    var phoneHead = el("div", { className: "a7-lwa-wa-head" });
    var phoneChat = el("div", { className: "a7-lwa-wa-chat" });
    var sendBtn = el("button", { className: "a7-lwa-send", type: "button" });
    var sub = el("div", { className: "a7-lwa-sub" });

    function setSendLabel(text) {
      while (sendBtn.firstChild) {
        sendBtn.removeChild(sendBtn.firstChild);
      }
      sendBtn.appendChild(icon("send"));
      sendBtn.appendChild(document.createTextNode(text));
    }
    setSendLabel("Queue " + leadIds.length + " message" + (leadIds.length === 1 ? "" : "s"));

    function currentNumber() {
      var id = numberSelect.value;
      for (var i = 0; i < numbers.length; i += 1) {
        if (String(numbers[i].id) === String(id)) {
          return numbers[i];
        }
      }
      return selectedNumber;
    }

    function templatesForNumber() {
      var num = currentNumber();
      var waba = num && num.waba_business_id;
      if (!waba) {
        return templates;
      }
      return templates.filter(function (t) {
        return !t.waba_business_id || t.waba_business_id === waba;
      });
    }

    function currentVars() {
      var vars = {};
      Object.keys(extraInputs).forEach(function (key) {
        vars[key] = String(extraInputs[key].value || "").trim();
      });
      // Empty {{1}} still previews as a sample card name.
      if (selected && Number(selected.variable_count || 0) >= 1 && !vars["1"]) {
        vars["1"] = sampleName(leads);
      }
      return vars;
    }

    function headerVars() {
      var vars = {};
      Object.keys(headerInputs).forEach(function (key) {
        vars[key] = String(headerInputs[key].value || "").trim();
      });
      return vars;
    }

    function renderLeads() {
      while (leadBox.firstChild) {
        leadBox.removeChild(leadBox.firstChild);
      }
      var usable = 0;
      leads.forEach(function (row) {
        if (row.phone_ok) {
          usable += 1;
        }
      });
      var shown = leads.slice(0, 8);
      shown.forEach(function (row) {
        var name = row.name || "Untitled";
        var line = el("div", { className: "a7-lwa-lead" + (row.phone_ok ? "" : " is-bad") }, [
          el("b", { text: name, title: name }),
          el("span", {
            text: row.phone_ok ? "…" + (row.phone_tail || "") : "No phone"
          })
        ]);
        leadBox.appendChild(line);
      });
      if (leads.length > 8) {
        leadBox.appendChild(
          el("div", {
            className: "a7-lwa-lead",
            text: "+" + (leads.length - 8) + " more"
          })
        );
      }
      if (!leads.length) {
        leadBox.appendChild(
          el("div", { className: "a7-lwa-lead", text: leadIds.length + " selected" })
        );
      }
      var skipped = leads.filter(function (row) { return !row.phone_ok; }).length;
      sub.textContent =
        leadIds.length + " selected · " +
        (usable || leadIds.length) + " can be messaged" +
        (skipped ? " · " + skipped + " missing a phone" : "");
    }

    function renderNote() {
      if (selected && /marketing/i.test(selected.category || "")) {
        note.textContent =
          "Marketing templates share Meta’s daily cap per customer. An undelivered send is usually that cap, not a bug.";
        note.style.display = "";
      } else {
        note.textContent = "";
        note.style.display = "none";
      }
    }

    function renderPreview() {
      while (phoneHead.firstChild) {
        phoneHead.removeChild(phoneHead.firstChild);
      }
      while (phoneChat.firstChild) {
        phoneChat.removeChild(phoneChat.firstChild);
      }
      var num = currentNumber();
      var who = sampleName(leads);
      var from = numberLabel(num);
      phoneHead.appendChild(el("div", { text: who, title: who }));
      phoneHead.appendChild(el("small", { text: "From " + from, title: from }));
      if (!selected) {
        phoneChat.appendChild(
          el("div", { className: "a7-lwa-empty", text: "Pick a template to preview." })
        );
        return;
      }
      var body = fillVars(selected.body_text || "", currentVars());
      var bubbleKids = [];
      var header = selected.header;
      if (header && header.format === "TEXT" && header.text) {
        bubbleKids.push(
          el("div", { className: "a7-lwa-headtxt", text: fillVars(header.text, headerVars()) })
        );
      } else if (selected.requires_header_media) {
        bubbleKids.push(el("div", { className: "a7-lwa-headtxt", text: "Header media — use Campaigns" }));
      }
      bubbleKids.push(document.createTextNode(body));
      if (selected.footer_text) {
        bubbleKids.push(el("div", { className: "a7-lwa-foot", text: selected.footer_text }));
      }
      phoneChat.appendChild(el("div", { className: "a7-lwa-bubble" }, bubbleKids));
      var buttons = selected.buttons || [];
      if (buttons.length) {
        var wrap = el("div", { className: "a7-lwa-btns" });
        buttons.forEach(function (button) {
          wrap.appendChild(el("div", { className: "a7-lwa-wabtn", text: button.text || "Button" }));
        });
        phoneChat.appendChild(wrap);
      }
    }

    function renderList() {
      while (list.firstChild) {
        list.removeChild(list.firstChild);
      }
      var q = String(search.value || "").trim().toLowerCase();
      var shown = 0;
      templatesForNumber().forEach(function (t) {
        if (category !== "ALL" && String(t.category || "").toUpperCase() !== category) {
          return;
        }
        if (q && templateHay(t).indexOf(q) === -1) {
          return;
        }
        shown += 1;
        var media = !!t.requires_header_media;
        var item = el("button", {
          className: "a7-lwa-item" +
            (selected && selected.id === t.id ? " is-on" : "") +
            (media ? " is-off" : ""),
          type: "button"
        }, [
          el("div", { text: t.name || "template", title: t.name || "template" }),
          el("small", {
            text: (t.language || "") +
              (t.category ? " · " + t.category : "") +
              (media ? " · header media — use Campaigns" : "")
          })
        ]);
        if (!media) {
          item.addEventListener("click", function () {
            selected = t;
            renderList();
            renderSelected();
          });
        }
        list.appendChild(item);
      });
      if (!shown) {
        list.appendChild(el("div", { className: "a7-lwa-item is-off", text: "No matching template on this number." }));
      }
    }

    function renderSelected() {
      extraInputs = {};
      headerInputs = {};
      buttonInputs = {};
      while (extras.firstChild) {
        extras.removeChild(extras.firstChild);
      }
      err.textContent = "";
      renderNote();
      if (!selected) {
        renderPreview();
        return;
      }
      var needed = Number(selected.variable_count || 0);
      for (var i = 1; i <= needed; i += 1) {
        var input = el("input", {
          className: "a7-lwa-input",
          type: "text",
          placeholder:
            i === 1
              ? "Leave blank = each " + NOUN_ONE + "’s name, or type one value for everyone"
              : "Same value for every selected " + NOUN_ONE
        });
        extraInputs[String(i)] = input;
        input.addEventListener("input", renderPreview);
        extras.appendChild(
          fieldBlock(i === 1 ? "{{1}} — name / greeting" : "{{" + i + "}}", input)
        );
      }
      var header = selected.header;
      if (header && header.format === "TEXT" && header.variable_count) {
        for (var h = 1; h <= header.variable_count; h += 1) {
          var hInput = el("input", {
            className: "a7-lwa-input",
            type: "text",
            placeholder: "Header {{" + h + "}}"
          });
          headerInputs[String(h)] = hInput;
          hInput.addEventListener("input", renderPreview);
          extras.appendChild(fieldBlock("Header {{" + h + "}}", hInput));
        }
      }
      (selected.buttons || []).forEach(function (button) {
        if (!button.variable_count) {
          return;
        }
        var bInput = el("input", {
          className: "a7-lwa-input",
          type: "text",
          placeholder: "URL suffix"
        });
        buttonInputs[String(button.index)] = bInput;
        extras.appendChild(fieldBlock((button.text || "Button") + " URL suffix", bInput));
      });
      renderPreview();
    }

    function renderChips() {
      while (chips.firstChild) {
        chips.removeChild(chips.firstChild);
      }
      ["ALL", "UTILITY", "MARKETING", "AUTHENTICATION"].forEach(function (name) {
        var chip = el("button", {
          className: "a7-lwa-chip" + (category === name ? " is-on" : ""),
          type: "button",
          text: name === "ALL" ? "All" : name.charAt(0) + name.slice(1).toLowerCase()
        });
        chip.addEventListener("click", function () {
          category = name;
          renderChips();
          renderList();
        });
        chips.appendChild(chip);
      });
    }

    numberSelect.addEventListener("change", function () {
      var waba = (currentNumber() || {}).waba_business_id;
      if (selected && selected.waba_business_id && waba && selected.waba_business_id !== waba) {
        selected = null;
      }
      renderList();
      renderSelected();
      renderPreview();
    });
    search.addEventListener("input", renderList);

    sendBtn.addEventListener("click", function () {
      if (busy) {
        return;
      }
      if (!selected) {
        err.textContent = "Pick a template.";
        return;
      }
      if (selected.requires_header_media) {
        err.textContent = "This template needs header media. Send it from Campaigns.";
        return;
      }
      var variables = {};
      var needed = Number(selected.variable_count || 0);
      for (var i = 1; i <= needed; i += 1) {
        var value = String((extraInputs[String(i)] && extraInputs[String(i)].value) || "").trim();
        if (i === 1) {
          // Blank {{1}} → backend uses each card/lead name. Filled → same for everyone.
          if (value) {
            variables["1"] = value;
          }
          continue;
        }
        if (!value) {
          err.textContent = "Fill {{" + i + "}} — the same value is sent to every " + NOUN_ONE + ".";
          return;
        }
        variables[String(i)] = value;
      }
      var headerVariables = {};
      Object.keys(headerInputs).forEach(function (key) {
        headerVariables[key] = String(headerInputs[key].value || "").trim();
      });
      var buttonVariables = {};
      Object.keys(buttonInputs).forEach(function (key) {
        buttonVariables[key] = String(buttonInputs[key].value || "").trim();
      });
      var num = currentNumber();
      busy = true;
      sendBtn.disabled = true;
      setSendLabel("Queuing…");
      err.textContent = "";
      var form = new URLSearchParams();
      form.set("action", "send");
      form.set("sessid", bitrixSessid());
      form.set("entity", ENTITY);
      form.set("payload", JSON.stringify({
        entity: ENTITY,
        lead_ids: leadIds,
        template_id: selected.id,
        number_id: num && num.id ? num.id : 0,
        variables: variables,
        header_variables: headerVariables,
        button_variables: buttonVariables
      }));
      fetchJson(ENDPOINT, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString()
      })
        .then(function (res) {
          var data = parseJsonLoose(res.text) || {};
          if (!res.ok || data.ok === false) {
            throw new Error(data.error || data.detail || "Send failed.");
          }
          var skipped = Number(data.skipped_count || 0);
          var queued = Number(data.queued || 0);
          var msg = "Queued " + queued + " WhatsApp message" + (queued === 1 ? "" : "s") + ".";
          if (skipped) {
            msg += " Skipped " + skipped + " without a usable phone.";
          }
          notify(msg, true);
          closeStudio();
        })
        .catch(function (e) {
          busy = false;
          sendBtn.disabled = false;
          setSendLabel("Queue " + leadIds.length + " message" + (leadIds.length === 1 ? "" : "s"));
          err.textContent = e && e.message ? e.message : "Send failed.";
        });
    });

    renderChips();
    renderList();
    renderSelected();
    renderLeads();
    renderPreview();

    var closeBtn = el("button", { className: "a7-lwa-x", type: "button", title: "Close" });
    closeBtn.appendChild(icon("close"));
    closeBtn.addEventListener("click", closeStudio);

    var modal = el("div", { className: "a7-lwa-modal" }, [
      el("div", { className: "a7-lwa-top" }, [
        el("div", { className: "a7-lwa-brand" }, [
          icon("wa", "a7-lwa-ic-lg"),
          el("div", {}, [
            el("h2", { text: "WhatsApp campaign" }),
            sub
          ])
        ]),
        closeBtn
      ]),
      el("div", { className: "a7-lwa-grid" }, [
        el("div", { className: "a7-lwa-col" }, [
          el("h3", {}, [icon("phone"), document.createTextNode("Send from")]),
          fieldBlock("Official number", numberSelect),
          el("h3", {}, [icon("users"), document.createTextNode("Selected " + NOUN)]),
          leadBox,
          el("h3", {}, [icon("search"), document.createTextNode("Template")]),
          search,
          chips,
          list,
          extras,
          note,
          err
        ]),
        el("div", { className: "a7-lwa-col a7-lwa-preview" }, [
          el("div", { className: "a7-lwa-phone" }, [
            el("div", { className: "a7-lwa-phone-bar" }, [el("b", {})]),
            el("div", { className: "a7-lwa-screen" }, [phoneHead, phoneChat])
          ])
        ])
      ]),
      el("div", { className: "a7-lwa-footbar" }, [
        el("div", {
          className: "a7-lwa-sub",
          text:
            "Every field is editable. Blank {{1}} uses each " +
            NOUN_ONE +
            "’s name; any typed {{1}} is sent to everyone."
        }),
        el("div", { className: "a7-lwa-actions" }, [
          el("button", { className: "a7-lwa-cancel", type: "button", text: "Cancel", onClick: closeStudio }),
          sendBtn
        ])
      ])
    ]);

    overlay = el("div", { className: "a7-lwa-overlay" }, [modal]);
    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) {
        closeStudio();
      }
    });
    prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onEsc);
    document.body.appendChild(overlay);
    try {
      search.focus();
    } catch (ignored) {}
  }

  function startSend() {
    if (busy) {
      return;
    }
    var ids = selectedLeadIds();
    if (!ids.length) {
      notify("Select one or more " + NOUN + " first. This does not send to “For all”.", false);
      return;
    }
    if (ids.length > MAX_LEADS) {
      notify("Select at most " + MAX_LEADS + " " + NOUN + ".", false);
      return;
    }
    busy = true;
    var form = new URLSearchParams();
    form.set("action", "context");
    form.set("sessid", bitrixSessid());
    form.set("entity", ENTITY);
    form.set("lead_ids", JSON.stringify(ids));
    fetchJson(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString()
    })
      .then(function (res) {
        var data = parseJsonLoose(res.text) || {};
        if (!res.ok || data.ok === false) {
          throw new Error(
            data.error || data.detail || ("Could not load templates (HTTP " + res.status + ").")
          );
        }
        busy = false;
        openStudio(ids, data);
      })
      .catch(function (e) {
        busy = false;
        notify(e && e.message ? e.message : "Could not load templates.", false);
      });
  }

  function makeButton() {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = BTN_CLASS;
    btn.appendChild(icon("wa"));
    btn.appendChild(document.createTextNode("WhatsApp campaign"));
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      startSend();
    });
    return btn;
  }

  function wrapButton(btn) {
    var slot = document.createElement("span");
    slot.className = SLOT_CLASS;
    slot.appendChild(btn);
    return slot;
  }

  function findTitleHost() {
    var hosts = [
      ".pagetitle-container.pagetitle-align-right-container",
      ".pagetitle-menu",
      ".ui-toolbar-right-buttons",
      ".ui-toolbar .ui-toolbar-after-title",
      ".ui-toolbar",
      ".pagetitle-inner-container",
      ".pagetitle-wrap",
      ".crm-view-switcher"
    ];
    for (var i = 0; i < hosts.length; i += 1) {
      var node = document.querySelector(hosts[i]);
      if (node) {
        return node;
      }
    }
    return null;
  }

  function isWellPlaced(btn) {
    return !!(
      btn &&
      btn.closest(
        ".pagetitle-wrap, .pagetitle-inner-container, .pagetitle-container, .ui-toolbar, .crm-view-switcher, .a7-lwa-topbar"
      )
    );
  }

  function dropOldButtons() {
    var nodes = document.querySelectorAll("." + BTN_CLASS + ", ." + SLOT_CLASS + ", .a7-lwa-topbar");
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i] && nodes[i].parentNode) {
        nodes[i].parentNode.removeChild(nodes[i]);
      }
    }
  }

  function mountButton() {
    ensureStyles();
    var existing = document.querySelector("." + BTN_CLASS);
    if (isWellPlaced(existing)) {
      return;
    }
    dropOldButtons();
    var host = findTitleHost();
    var slot = wrapButton(makeButton());
    if (host) {
      if (host.firstChild) {
        host.insertBefore(slot, host.firstChild);
      } else {
        host.appendChild(slot);
      }
      return;
    }
    var bar = document.createElement("div");
    bar.className = "a7-lwa-topbar";
    bar.style.cssText = "position:sticky;top:0;z-index:50;display:flex;justify-content:flex-end;padding:8px 16px;";
    bar.appendChild(slot);
    var work = document.querySelector(".workarea-content, .pagetitle-below, #workarea-content");
    if (work && work.parentNode) {
      work.parentNode.insertBefore(bar, work);
    } else {
      document.body.insertBefore(bar, document.body.firstChild);
    }
  }

  function syncButton() {
    var count = 0;
    try {
      count = selectedLeadIds().length;
    } catch (e) {
      count = 0;
    }
    if (count < 1) {
      dropOldButtons();
      return;
    }
    mountButton();
  }

  function watch() {
    var pending = 0;
    function schedule() {
      if (pending) {
        return;
      }
      pending = window.setTimeout(function () {
        pending = 0;
        syncButton();
      }, 40);
    }
    function poke() {
      schedule();
      window.setTimeout(syncButton, 160);
    }
    syncButton();
    document.addEventListener("click", poke, true);
    document.addEventListener("change", poke, true);
    document.addEventListener("keyup", poke, true);
    try {
      if (window.BX && typeof BX.addCustomEvent === "function") {
        var names = [
          "Grid::selectRow",
          "Grid::unselectRow",
          "Grid::allRowsSelected",
          "Grid::allRowsUnselected",
          "Grid::updated"
        ];
        for (var n = 0; n < names.length; n += 1) {
          BX.addCustomEvent(window, names[n], schedule);
        }
      }
    } catch (ignored) {}
    var obs = new MutationObserver(schedule);
    obs.observe(document.body, { childList: true, subtree: true });
    window.setInterval(syncButton, 200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
