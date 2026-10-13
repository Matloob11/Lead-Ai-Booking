/**
 * A7 Lead Guard — UI layer (Bitrix24 CRM Leads).
 * Deployed to: /bitrix/js/a7_lead_guard.js  (injected by include/a7_lead_guard.php on /crm/lead/*)
 *
 *  - Lead card: "SHARED LEAD" badge in the title area + "Shared with: …" line under Responsible.
 *  - Shared user (observer): read-only banner; locked fields visually disabled.
 *  - Lead list / kanban: small "Shared" tag next to shared leads.
 *  - Non-admins: every "Delete" control (menus, timeline, grid actions) is hidden.
 *    (This is cosmetic — the server refuses the delete anyway.)
 */
(function () {
  if (window.A7_LEAD_GUARD_LOADED) {
    return;
  }
  window.A7_LEAD_GUARD_LOADED = true;

  var API = "/bitrix/tools/a7_lead_guard_api.php";
  var STYLE_ID = "a7-lead-guard-style";
  var DELETE_RX = /^(delete|remove|delete lead|delete item|удалить|حذف|hapus|eliminar|supprimer)\s*$/i;
  var RESPONSIBLE_RX = /^(responsible( person)?|ответственный|المسؤول)\s*:?\s*$/i;

  var me = null;          // { userId, isAdmin, canDelete }
  var leadId = detectLeadId();
  var info = null;        // info for the open lead
  var scanTimer = 0;
  var batchTimer = 0;
  var batchCache = {};    // id -> {shared, names, mine}
  var batchAsked = {};    // id -> true

  /* ------------------------------------------------------------------ */
  function detectLeadId() {
    var m = (location.pathname || "").match(/\/crm\/lead\/details\/(\d+)\//);
    return m ? parseInt(m[1], 10) : 0;
  }

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin", cache: "no-store" }).then(function (r) {
      return r.json();
    });
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var css = [
      ".a7lg-badge{display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding:3px 10px;border-radius:999px;",
      "background:#fff3cd;color:#7a4b00;border:1px solid #f0c36d;font:600 11px/16px -apple-system,Segoe UI,Roboto,sans-serif;",
      "letter-spacing:.04em;text-transform:uppercase;vertical-align:middle;white-space:nowrap}",
      ".a7lg-badge .a7lg-dot{width:7px;height:7px;border-radius:50%;background:#f39c12;display:inline-block}",
      ".a7lg-badge .a7lg-with{text-transform:none;letter-spacing:0;font-weight:500;color:#5a3a00}",
      ".a7lg-float{position:fixed;top:64px;right:24px;z-index:9999;box-shadow:0 4px 14px rgba(0,0,0,.12)}",
      ".a7lg-shared-line{margin:6px 0 2px;padding:6px 10px;border-radius:8px;background:#fff8e6;border:1px dashed #f0c36d;",
      "color:#5a3a00;font:500 12px/16px -apple-system,Segoe UI,Roboto,sans-serif}",
      ".a7lg-shared-line b{font-weight:700}",
      ".a7lg-banner{margin:0 0 10px;padding:10px 14px;border-radius:10px;background:#eef6ff;border:1px solid #b7d7ff;color:#0b3d6b;",
      "font:500 13px/18px -apple-system,Segoe UI,Roboto,sans-serif}",
      ".a7lg-tag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:999px;background:#fff3cd;color:#7a4b00;",
      "border:1px solid #f0c36d;font:600 10px/14px -apple-system,Segoe UI,Roboto,sans-serif;text-transform:uppercase;vertical-align:middle}",
      ".a7lg-tag.a7lg-mine{background:#e6f4ea;color:#1e5e2e;border-color:#9fd3ad}",
      ".a7lg-hidden{display:none !important}",
      /* ── share popup (list/kanban: top-right; lead card: compact left tray so comments stay usable) ── */
      ".a7lg-pending{position:fixed;right:24px;top:72px;z-index:1100;width:352px;max-width:calc(100vw - 32px);display:flex;flex-direction:column;gap:10px;",
      "font:13px/1.45 -apple-system,'Segoe UI',Inter,Roboto,sans-serif;color:#1c2430;pointer-events:none}",
      "html.a7lg-on-lead-card .a7lg-pending{right:auto;left:12px;top:auto;bottom:12px;width:300px;max-height:42vh;z-index:1050}",
      ".a7lg-tray-toggle{pointer-events:auto;display:none;align-items:center;justify-content:space-between;gap:8px;width:100%;padding:10px 12px;border:0;border-radius:12px;",
      "background:#111827;color:#fff;font:600 13px/1.3 -apple-system,'Segoe UI',Inter,Roboto,sans-serif;cursor:pointer;box-shadow:0 8px 24px rgba(16,24,40,.22)}",
      "html.a7lg-on-lead-card .a7lg-tray-toggle{display:flex}",
      "html.a7lg-on-lead-card .a7lg-pending:not(.a7lg-open) .a7lg-tray-list{display:none}",
      "html.a7lg-on-lead-card .a7lg-tray-list{pointer-events:auto;overflow:auto;max-height:calc(42vh - 48px);display:flex;flex-direction:column;gap:8px}",
      "html.a7lg-on-lead-card #a7-share-idle-box{display:none !important}",
      "html.a7lg-on-lead-card .bx-notifier-panel,html.a7lg-on-lead-card .bx-im-notify-panel,html.a7lg-on-lead-card .bx-im-balloon-container{left:12px !important;right:auto !important;bottom:56px !important;top:auto !important;max-height:36vh;overflow:auto}",
      ".a7lg-card{pointer-events:auto;display:flex;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 1px 2px rgba(16,24,40,.06),0 18px 44px -12px rgba(16,24,40,.28);",
      "border:1px solid rgba(16,24,40,.08);animation:a7lgIn .42s cubic-bezier(.2,.8,.2,1) both}",
      ".a7lg-card-out{animation:a7lgOut .22s ease-in forwards}",
      "@keyframes a7lgIn{from{transform:translateX(24px) scale(.98);opacity:0}to{transform:none;opacity:1}}",
      "@keyframes a7lgOut{to{transform:translateX(24px);opacity:0}}",
      ".a7lg-card-accent{width:5px;flex:0 0 5px;background:linear-gradient(180deg,#2f6bff,#7c3aed)}",
      ".a7lg-card-body{padding:14px 16px 14px 14px;flex:1;min-width:0}",
      ".a7lg-card-top{display:flex;align-items:center;gap:10px;margin-bottom:10px}",
      ".a7lg-avatar{width:36px;height:36px;border-radius:50%;flex:0 0 36px;display:flex;align-items:center;justify-content:center;",
      "background:linear-gradient(135deg,#2f6bff,#7c3aed);color:#fff;font-weight:700;font-size:13px;letter-spacing:.03em}",
      ".a7lg-eyebrow{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#6b7280}",
      ".a7lg-name{font-size:15px;font-weight:700;color:#111827;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".a7lg-lead{display:block;font-size:14px;font-weight:600;color:#1d4ed8;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".a7lg-lead:hover{text-decoration:underline}.a7lg-lead-id{margin-left:6px;font-weight:500;color:#9ca3af;font-size:12px}",
      ".a7lg-meta{margin-top:4px;font-size:12px;color:#6b7280;display:flex;align-items:center;gap:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".a7lg-sep{width:3px;height:3px;border-radius:50%;background:#cbd5e1;display:inline-block;flex:0 0 3px}",
      ".a7lg-actions{margin-top:12px;display:flex;gap:8px}",
      ".a7lg-btn{display:inline-flex;align-items:center;justify-content:center;padding:7px 14px;border-radius:10px;font:600 13px/1 -apple-system,'Segoe UI',Inter,Roboto,sans-serif;",
      "cursor:pointer;text-decoration:none;border:1px solid transparent;transition:background .15s,transform .05s}",
      ".a7lg-btn:active{transform:translateY(1px)}",
      ".a7lg-btn-primary{background:#111827;color:#fff}.a7lg-btn-primary:hover{background:#000}",
      ".a7lg-btn-ghost{background:#fff;color:#374151;border-color:#e5e7eb}.a7lg-btn-ghost:hover{background:#f3f4f6}",
      "body.a7lg-observer .a7lg-locked{pointer-events:none;opacity:.55;position:relative}",
      "body.a7lg-observer .a7lg-locked::after{content:'🔒';position:absolute;right:8px;top:6px;font-size:11px;opacity:.8}",
    ].join("");
    var st = document.createElement("style");
    st.id = STYLE_ID;
    st.textContent = css;
    document.head.appendChild(st);
  }

  /* ------------------------------------------------------------------ */
  /* Hide delete controls for non-admins                                  */
  /* ------------------------------------------------------------------ */
  function hideDeleteControls(root) {
    if (!me || me.canDelete) {
      return;
    }
    root = root || document;
    var items = root.querySelectorAll(
      ".menu-popup-item, .crm-entity-stream-content-detail-delete, .crm-timeline__card_context-menu-item, " +
        ".main-grid-panel-select option, .ui-btn-menu .menu-popup-item, [data-role='delete'], [data-action='delete']"
    );
    for (var i = 0; i < items.length; i++) {
      var el = items[i];
      if (el.getAttribute("data-a7lg-checked")) {
        continue;
      }
      var txt = (el.querySelector(".menu-popup-item-text") || el).textContent || "";
      txt = txt.replace(/\s+/g, " ").trim();
      var idAttr = (el.id || "") + " " + (el.className || "") + " " + (el.getAttribute("data-role") || "") + " " + (el.getAttribute("data-action") || "");
      if (DELETE_RX.test(txt) || /(^|[\s_-])delete([\s_-]|$)/i.test(idAttr)) {
        el.classList.add("a7lg-hidden");
        if (el.tagName === "OPTION") {
          el.disabled = true;
        }
      }
      el.setAttribute("data-a7lg-checked", "1");
    }
  }

  /* ------------------------------------------------------------------ */
  /* Lead card: badge + shared-with line + observer banner                */
  /* ------------------------------------------------------------------ */
  function badgeHtml() {
    var names = info.observers.map(function (o) { return o.name; }).join(", ");
    return (
      '<span class="a7lg-dot"></span>Shared lead' +
      '<span class="a7lg-with">· Responsible: <b>' + esc(info.responsible.name) + "</b> · Shared with: <b>" + esc(names) + "</b></span>"
    );
  }

  function renderCard() {
    if (!info) {
      return;
    }
    var existing = document.querySelectorAll(".a7lg-badge");
    if (!info.shared) {
      for (var i = 0; i < existing.length; i++) {
        existing[i].remove();
      }
      var l = document.querySelector(".a7lg-shared-line");
      if (l) { l.remove(); }
      return;
    }

    // 1. title badge
    var host =
      document.querySelector("#pagetitle") ||
      document.querySelector(".pagetitle-inner-container .pagetitle") ||
      document.querySelector(".pagetitle-inner") ||
      document.querySelector(".crm-entity-section-title") ||
      document.querySelector(".ui-entity-editor-header-title");
    var badge = document.querySelector(".a7lg-badge");
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "a7lg-badge";
    }
    badge.innerHTML = badgeHtml();
    if (host) {
      badge.classList.remove("a7lg-float");
      if (badge.parentNode !== host.parentNode || badge.previousSibling !== host) {
        host.parentNode.insertBefore(badge, host.nextSibling);
      }
    } else {
      badge.classList.add("a7lg-float");
      if (!badge.parentNode) {
        document.body.appendChild(badge);
      }
    }

    // 2. "Shared with" line under Responsible
    var titles = document.querySelectorAll(".ui-entity-editor-block-title-text, .crm-entity-widget-content-block-title-text");
    for (var t = 0; t < titles.length; t++) {
      var txt = (titles[t].textContent || "").trim();
      if (!RESPONSIBLE_RX.test(txt)) {
        continue;
      }
      var block = titles[t].closest(".ui-entity-editor-block, .crm-entity-widget-content-block");
      if (!block) {
        continue;
      }
      var line = block.querySelector(".a7lg-shared-line");
      if (!line) {
        line = document.createElement("div");
        line.className = "a7lg-shared-line";
        block.appendChild(line);
      }
      var names = info.observers.map(function (o) { return esc(o.name); }).join(", ");
      line.innerHTML = "🔗 <b>Shared with:</b> " + names + " <span style='opacity:.7'>(read-only access)</span>";
      break;
    }

    // 3. shared user: banner + lock every left-side field that is not stage-related
    if (info.isObserver && !info.isResponsible && !info.isAdmin) {
      document.body.classList.add("a7lg-observer");
      if (!document.querySelector(".a7lg-banner")) {
        var editor = document.querySelector(".ui-entity-editor-container, .crm-entity-card-container, .crm-entity-section");
        if (editor) {
          var b = document.createElement("div");
          b.className = "a7lg-banner";
          b.innerHTML = info.sharedWrite
            ? "🔗 This lead was <b>shared with you</b>. You can change the <b>stage</b> and its details and add comments. " +
              "Other fields are locked and nothing can be deleted. Responsible: <b>" + esc(info.responsible.name) + "</b>."
            : "🔗 This lead was <b>shared with you</b> (read-only). Responsible: <b>" + esc(info.responsible.name) + "</b>.";
          editor.parentNode.insertBefore(b, editor);
        }
      }
      lockFields(info.allowedFields || []);
    }
  }

  /** Visually lock entity-editor fields that the shared user may not change (server enforces anyway). */
  function lockFields(allowed) {
    var allow = {};
    allowed.forEach(function (f) { allow[String(f).toUpperCase()] = true; });
    var fields = document.querySelectorAll(".ui-entity-editor-field[data-cid], .ui-entity-editor-content-block[data-cid], [data-cid].ui-entity-editor-block");
    for (var i = 0; i < fields.length; i++) {
      var el = fields[i];
      var cid = String(el.getAttribute("data-cid") || "").toUpperCase();
      if (!cid || allow[cid] || /^(STATUS_ID|STAGE_ID|OBSERVER)/.test(cid)) {
        continue;
      }
      if (!el.classList.contains("a7lg-locked")) {
        el.classList.add("a7lg-locked");
        el.title = "Locked for shared users";
      }
    }
    // section-level "edit" links / pencils
    var pencils = document.querySelectorAll(".ui-entity-editor-header-edit, .ui-entity-editor-block-title-edit, .crm-entity-widget-actions-btn-edit");
    for (var p = 0; p < pencils.length; p++) {
      pencils[p].classList.add("a7lg-hidden");
    }
  }

  function loadInfo() {
    if (!leadId) {
      return;
    }
    getJSON(API + "?action=info&id=" + leadId + "&_=" + Date.now())
      .then(function (d) {
        if (d && d.ok) {
          info = d;
          renderCard();
        }
      })
      .catch(function () {});
  }

  /* ------------------------------------------------------------------ */
  /* List / kanban tags                                                   */
  /* ------------------------------------------------------------------ */
  function collectListLinks() {
    var out = {};
    var links = document.querySelectorAll('a[href*="/crm/lead/details/"]');
    for (var i = 0; i < links.length; i++) {
      var m = (links[i].getAttribute("href") || "").match(/\/crm\/lead\/details\/(\d+)\//);
      if (!m) {
        continue;
      }
      var id = m[1];
      if (leadId && parseInt(id, 10) === leadId) {
        continue; // the open card itself
      }
      var a = links[i];
      // only title-like links (skip avatars / icons)
      if (!(a.textContent || "").trim()) {
        continue;
      }
      if (!out[id]) {
        out[id] = [];
      }
      out[id].push(a);
    }
    return out;
  }

  function applyTags(map) {
    for (var id in map) {
      if (!map.hasOwnProperty(id)) {
        continue;
      }
      var data = batchCache[id];
      var anchors = map[id];
      for (var i = 0; i < anchors.length; i++) {
        var a = anchors[i];
        var next = a.nextSibling;
        var hasTag = next && next.nodeType === 1 && next.classList && next.classList.contains("a7lg-tag");
        if (data && data.shared) {
          if (!hasTag) {
            var tag = document.createElement("span");
            tag.className = "a7lg-tag" + (data.mine ? " a7lg-mine" : "");
            tag.title = "Shared with: " + data.names.join(", ");
            tag.textContent = data.mine ? "Shared with me" : "Shared";
            a.parentNode.insertBefore(tag, a.nextSibling);
          }
        } else if (hasTag && data === null) {
          next.remove();
        }
      }
    }
  }

  function scanList() {
    var map = collectListLinks();
    var ask = [];
    for (var id in map) {
      if (map.hasOwnProperty(id) && !batchAsked[id]) {
        ask.push(id);
        batchAsked[id] = true;
      }
    }
    applyTags(map);
    if (!ask.length) {
      return;
    }
    // chunks of 100
    var chunks = [];
    while (ask.length) {
      chunks.push(ask.splice(0, 100));
    }
    chunks.forEach(function (chunk) {
      getJSON(API + "?action=batch&ids=" + chunk.join(","))
        .then(function (d) {
          if (!d || !d.ok) {
            return;
          }
          chunk.forEach(function (id) {
            batchCache[id] = d.items && d.items[id] ? d.items[id] : null;
          });
          applyTags(collectListLinks());
        })
        .catch(function () {
          chunk.forEach(function (id) { delete batchAsked[id]; });
        });
    });
  }

  function refreshListCache() {
    // forget answers so that structure changes (new shares) show up on the next scan
    batchAsked = {};
    batchCache = {};
    scanList();
  }

  /* ------------------------------------------------------------------ */
  /* Sticky "lead shared with you" popup — stays until Dismiss             */
  /* ------------------------------------------------------------------ */
  var pendingBox = null;
  var trayOpen = false;

  function sessid() {
    try { return window.BX && BX.bitrix_sessid ? BX.bitrix_sessid() : ""; } catch (e) { return ""; }
  }

  function ackLead(lead) {
    var body = "lead=" + encodeURIComponent(lead) + "&sessid=" + encodeURIComponent(sessid());
    fetch(API + "?action=ack", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body
    }).catch(function () {});
  }

  function renderPending(items) {
    if (!items || !items.length) {
      if (pendingBox) { pendingBox.remove(); pendingBox = null; }
      return;
    }
    if (!pendingBox) {
      pendingBox = document.createElement("div");
      pendingBox.className = "a7lg-pending";
      document.body.appendChild(pendingBox);
    }
    var n = items.length;
    var label = n === 1 ? "1 shared lead" : n + " shared leads";
    var html =
      '<button type="button" class="a7lg-tray-toggle" aria-expanded="' + (trayOpen ? "true" : "false") + '">' +
      "<span>" + esc(label) + "</span><span>" + (trayOpen ? "Hide" : "Show") + "</span></button>" +
      '<div class="a7lg-tray-list">';
    items.forEach(function (it, idx) {
      html +=
        '<div class="a7lg-card" data-lead="' + it.lead + '" style="animation-delay:' + (idx * 80) + 'ms">' +
        '<div class="a7lg-card-accent"></div>' +
        '<div class="a7lg-card-body">' +
        '<div class="a7lg-card-top">' +
        '<div class="a7lg-avatar">' + esc(it.initials || "•") + "</div>" +
        '<div class="a7lg-card-who"><div class="a7lg-eyebrow">Lead shared with you</div>' +
        '<div class="a7lg-name">' + esc(it.by) + "</div></div>" +
        "</div>" +
        '<a class="a7lg-lead" href="' + esc(it.url) + '">' + esc(it.title || "Lead #" + it.lead) + '<span class="a7lg-lead-id">#' + it.lead + "</span></a>" +
        '<div class="a7lg-meta">' + esc(it.at) + '<span class="a7lg-sep"></span>Responsible: ' + esc(it.responsible) + "</div>" +
        '<div class="a7lg-actions">' +
        '<a class="a7lg-btn a7lg-btn-primary" href="' + esc(it.url) + '">Open lead</a>' +
        '<button type="button" class="a7lg-btn a7lg-btn-ghost a7lg-btn-dismiss" data-lead="' + it.lead + '">Got it</button>' +
        "</div>" +
        "</div></div>";
    });
    html += "</div>";
    pendingBox.innerHTML = html;
    pendingBox.classList.toggle("a7lg-open", trayOpen);
    var tog = pendingBox.querySelector(".a7lg-tray-toggle");
    if (tog) {
      tog.addEventListener("click", function () {
        trayOpen = !trayOpen;
        pendingBox.classList.toggle("a7lg-open", trayOpen);
        tog.setAttribute("aria-expanded", trayOpen ? "true" : "false");
        tog.lastChild.textContent = trayOpen ? "Hide" : "Show";
      });
    }
    var btns = pendingBox.querySelectorAll(".a7lg-btn-dismiss");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function (e) {
        var lead = e.currentTarget.getAttribute("data-lead");
        ackLead(lead);
        var item = e.currentTarget.closest(".a7lg-card");
        if (item) {
          item.classList.add("a7lg-card-out");
          window.setTimeout(function () {
            item.remove();
            if (pendingBox && !pendingBox.querySelector(".a7lg-card")) { pendingBox.remove(); pendingBox = null; }
          }, 220);
        }
      });
    }
  }

  function loadPending() {
    getJSON(API + "?action=pending&_=" + Date.now())
      .then(function (d) {
        if (!d || !d.ok) {
          return;
        }
        var items = d.items || [];
        if (leadId) {
          var rest = [];
          items.forEach(function (it) {
            if (parseInt(it.lead, 10) === leadId) {
              ackLead(it.lead);
            } else {
              rest.push(it);
            }
          });
          items = rest;
        }
        renderPending(items);
      })
      .catch(function () {});
  }

  function scan() {
    ensureStyle();
    hideDeleteControls(document);
    if (leadId) {
      renderCard();
    }
    scanList();
  }

  function scheduleScan() {
    if (scanTimer) {
      return;
    }
    scanTimer = window.setTimeout(function () {
      scanTimer = 0;
      try { scan(); } catch (e) {}
    }, 250);
  }

  var LEAD_PAGE = /^\/crm\/lead\//.test(location.pathname || "");

  function listenPush() {
    // Instant popup when a share happens while this tab is open (Bitrix Pull).
    if (window.BX && BX.addCustomEvent) {
      BX.addCustomEvent("onPullEvent-crm", function (command, params) {
        if (command === "a7LeadShare") { loadPending(); }
      });
    }
  }

  function boot() {
    ensureStyle();
    if (leadId) {
      document.documentElement.classList.add("a7lg-on-lead-card");
    }
    // The share popup works on EVERY portal page: one light request + push listener.
    loadPending();
    listenPush();
    window.setInterval(function () { try { loadPending(); } catch (e) {} }, 180000);
    if (!LEAD_PAGE) {
      return; // nothing else to do outside the lead pages
    }
    getJSON(API + "?action=me")
      .then(function (d) {
        me = d && d.ok ? d : { isAdmin: false, canDelete: false };
        scan();
        loadInfo();
        if (window.MutationObserver) {
          var obs = new MutationObserver(function () { scheduleScan(); });
          obs.observe(document.documentElement, { childList: true, subtree: true });
        }
        window.setInterval(function () {
          try { loadInfo(); } catch (e) {}
        }, 180000);
        window.setInterval(function () {
          try { refreshListCache(); } catch (e) {}
        }, 300000);
        // re-check after the entity editor saves (observers may have changed)
        if (window.BX && BX.addCustomEvent) {
          BX.addCustomEvent(window, "BX.Crm.EntityEditor:onEntityUpdate", function () { window.setTimeout(loadInfo, 800); });
          BX.addCustomEvent(window, "onCrmEntityUpdate", function () { window.setTimeout(loadInfo, 800); });
          BX.addCustomEvent(window, "Crm.Kanban.Grid:onItemUpdated", function () { window.setTimeout(refreshListCache, 800); });
          BX.addCustomEvent(window, "Grid::updated", function () { window.setTimeout(scanList, 300); });
        }
      })
      .catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
