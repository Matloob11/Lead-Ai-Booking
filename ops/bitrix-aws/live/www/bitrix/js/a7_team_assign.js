/**
 * A7 team bulk assign — progressive tree on CRM lists.
 * Leads, Owner Data (1042/13), Availability (1042/14), Renewals (deal cat 9).
 */
(function () {
  if (window.A7_TEAM_ASSIGN_V8) {
    return;
  }
  window.A7_TEAM_ASSIGN_V8 = true;

  var PATH = String(location.pathname || "");
  var SEARCH = String(location.search || "");
  var entity = detectEntity();
  if (!entity) {
    return;
  }

  var ENDPOINT = "/bitrix/tools/a7_team_assign.php";
  var CSS_HREF = "/bitrix/css/a7_team_assign.css";
  var BTN_CLASS = "a7-ta-btn";
  var SLOT_CLASS = "a7-ta-slot";
  var MAX_IDS = 0;
  var CLIENT_IDS_MAX = 400;
  var overlay = null;
  var busy = false;
  var meta = null;
  var jobPollTimer = 0;
  var state = {
    headIds: [],
    stage: "__KEEP__",
    level: 1,
    mode: "equal",
    noCommunity: "rr",
    noCommunityUser: 0,
    counts: {},
    agentStages: {},
    agentQuery: "",
    stageQuery: "",
    stageOpen: false,
    noCommOpen: false,
    noCommQuery: "",
    noCommUserOpen: false,
    noCommUserQuery: "",
    preview: null,
    error: "",
    message: "",
    // When For all is on, IDs come from the server (session list filter), not DOM checkboxes.
    resolvedIds: null,
    resolvedTotal: 0,
    forAll: false,
    deferredForAll: false,
    gridId: "",
    jobId: ""
  };

  function detectEntity() {
    if (/\/crm\/lead\//i.test(PATH) && !/\/crm\/lead\/details\//i.test(PATH)) {
      return "lead";
    }
    if (/\/crm\/type\/1042\//i.test(PATH) && !/\/crm\/type\/1042\/details\//i.test(PATH)) {
      var cat = categoryFromUrl();
      if (cat === 14) {
        return "availability";
      }
      return "owner_data";
    }
    if (/^\/crm\/deal\/(?:kanban\/|list\/)?category\/9(?:\/|$)/i.test(PATH) && !/\/crm\/deal\/details\//i.test(PATH)) {
      return "renewal";
    }
    return "";
  }

  function categoryFromUrl() {
    var m = PATH.match(/\/category\/(\d+)/i) || SEARCH.match(/[?&]categoryId=(\d+)/i);
    return m ? parseInt(m[1], 10) : 0;
  }

  function noun() {
    if (entity === "renewal") {
      return "deals";
    }
    if (entity === "lead") {
      return "leads";
    }
    return "cards";
  }

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
      console[ok === false ? "warn" : "log"]("[A7 Team Assign]", message);
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
      var id = /^\d+$/.test(raw) ? raw : ((raw.match(/(\d+)(?:\D*)$/) || [])[1] || "");
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
      ids.push(checked[k].getAttribute("data-id") || checked[k].dataset.id || "");
    }
    return uniqueIds(ids);
  }

  function selectedKanbanIds() {
    var ids = [];
    try {
      var grid =
        (window.BX && BX.CRM && BX.CRM.Kanban && BX.CRM.Kanban.Grid && BX.CRM.Kanban.Grid.getInstance) ||
        null;
      var inst = null;
      if (typeof grid === "function") {
        inst = grid();
      }
      if (!inst && window.BX && BX.Kanban && BX.Kanban.GridManager) {
        var mgr = BX.Kanban.GridManager;
        if (mgr.getInstances) {
          var list = mgr.getInstances() || [];
          inst = list[0] || null;
        }
      }
      if (inst) {
        if (typeof inst.getChecked === "function") {
          var checked = inst.getChecked() || [];
          for (var i = 0; i < checked.length; i += 1) {
            var item = checked[i];
            ids.push(item && (item.getId ? item.getId() : item.id || item));
          }
        } else if (typeof inst.getSelectedItems === "function") {
          var sel = inst.getSelectedItems() || [];
          for (var s = 0; s < sel.length; s += 1) {
            ids.push(sel[s] && (sel[s].getId ? sel[s].getId() : sel[s].id));
          }
        }
      }
    } catch (e) {}
    var cards = document.querySelectorAll(
      ".crm-kanban-item.crm-kanban-item-checked[data-id], .main-kanban-item.main-kanban-item-checked[data-id], .crm-kanban-item-checked[data-id]"
    );
    for (var c = 0; c < cards.length; c += 1) {
      ids.push(cards[c].getAttribute("data-id") || "");
    }
    return uniqueIds(ids);
  }

  function selectedIds() {
    var ids = uniqueIds(selectedGridIds().concat(selectedKanbanIds()));
    if (MAX_IDS > 0 && ids.length > MAX_IDS) {
      return ids.slice(0, MAX_IDS);
    }
    return ids;
  }

  function getActiveGrid() {
    try {
      var mgr = window.BX && BX.Main && BX.Main.gridManager;
      var data = mgr && (mgr.data || mgr.list);
      if (!data || !data.length) {
        return null;
      }
      var first = null;
      for (var i = 0; i < data.length; i += 1) {
        var grid = data[i] && data[i].instance;
        if (!grid || typeof grid.getRows !== "function") {
          continue;
        }
        if (!first) {
          first = grid;
        }
        // Prefer the grid whose For-all checkbox is on.
        try {
          var panel = typeof grid.getActionsPanel === "function" ? grid.getActionsPanel() : null;
          if (panel && typeof panel.getForAllCheckbox === "function") {
            var cb = panel.getForAllCheckbox();
            if (cb && cb.checked) {
              return grid;
            }
          }
        } catch (e2) {}
      }
      return first;
    } catch (e) {}
    return null;
  }

  function isForAllChecked() {
    try {
      var grid = getActiveGrid();
      if (!grid) {
        return false;
      }
      var panel = typeof grid.getActionsPanel === "function" ? grid.getActionsPanel() : null;
      if (panel && typeof panel.getForAllCheckbox === "function") {
        var cb = panel.getForAllCheckbox();
        if (cb && cb.checked) {
          return true;
        }
      }
      if (panel && typeof panel.getValues === "function") {
        var vals = panel.getValues() || {};
        var key = "action_all_rows_" + (typeof grid.getId === "function" ? grid.getId() : "");
        if (vals[key] === "Y") {
          return true;
        }
      }
      var root = typeof grid.getContainer === "function" ? grid.getContainer() : null;
      if (root && root.querySelector && root.querySelector(".main-grid-panel-counter-for-all-enable")) {
        return true;
      }
    } catch (e) {}
    try {
      var forAllInput = document.querySelector(".main-grid-for-all-checkbox input[type='checkbox']");
      if (forAllInput && forAllInput.checked) {
        return true;
      }
      var labels = document.querySelectorAll(".main-grid-panel, .main-grid-action-panel");
      for (var i = 0; i < labels.length; i += 1) {
        var t = ((labels[i].textContent || "") + "").toUpperCase();
        if (t.indexOf("ALL ITEMS SELECTED") !== -1) {
          return true;
        }
      }
    } catch (e2) {}
    return false;
  }

  function activeGridId() {
    var grid = getActiveGrid();
    if (grid && typeof grid.getId === "function") {
      var gid = String(grid.getId() || "");
      if (gid) {
        return gid;
      }
    }
    var node = document.querySelector(".main-grid[id]");
    if (node && node.id) {
      return String(node.id);
    }
    // Entity defaults when DOM grid is not ready yet.
    if (entity === "lead") {
      return "CRM_LEAD_LIST_V12";
    }
    if (entity === "renewal") {
      return "CRM_DEAL_LIST_V12_C_9";
    }
    return "";
  }

  function workingIds() {
    if (state.resolvedIds && state.resolvedIds.length) {
      return state.resolvedIds.slice();
    }
    return selectedIds();
  }

  function selectedCount() {
    if (state.resolvedTotal > 0) {
      return state.resolvedTotal;
    }
    return workingIds().length;
  }

  function resolveSelection() {
    state.forAll = isForAllChecked();
    state.deferredForAll = false;
    state.gridId = activeGridId();
    if (!state.forAll) {
      state.resolvedIds = selectedIds();
      state.resolvedTotal = state.resolvedIds.length;
      return Promise.resolve(state.resolvedIds);
    }
    var body = new FormData();
    body.append("sessid", bitrixSessid());
    body.append("action", "resolve");
    body.append("entity", entity);
    body.append("grid_id", state.gridId);
    body.append("for_all", "Y");
    return fetch(ENDPOINT, {
      method: "POST",
      body: body,
      credentials: "same-origin"
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          var snip = (text || "").replace(/\s+/g, " ").slice(0, 160);
          throw new Error("Server error (HTTP " + res.status + "): " + (snip || "empty response"));
        }
        if (!res.ok || !data || data.ok === false) {
          throw new Error((data && data.error) || "Could not resolve For all selection");
        }
        state.resolvedTotal = Number(data.total) || 0;
        if (data.deferred) {
          state.deferredForAll = true;
          state.resolvedIds = null;
          return [];
        }
        state.resolvedIds = uniqueIds(data.ids || []);
        state.resolvedTotal = state.resolvedIds.length;
        return state.resolvedIds;
      });
    });
  }

  function ensureCss() {
    if (document.getElementById("a7-ta-css")) {
      return;
    }
    var link = document.createElement("link");
    link.id = "a7-ta-css";
    link.rel = "stylesheet";
    link.href = CSS_HREF + "?v=" + Date.now();
    document.head.appendChild(link);
  }

  function post(action, extra) {
    var body = new FormData();
    body.append("sessid", bitrixSessid());
    body.append("action", action);
    body.append("entity", entity);
    if (state.forAll && state.deferredForAll) {
      body.append("for_all", "Y");
      body.append("grid_id", state.gridId || activeGridId());
      body.append("ids", JSON.stringify([]));
    } else {
      body.append("ids", JSON.stringify(workingIds()));
    }
    body.append("head_ids", JSON.stringify(state.headIds));
    body.append("mode", state.mode);
    body.append("stage", state.stage);
    body.append("no_community", state.noCommunity);
    body.append("no_community_user", String(state.noCommunityUser || 0));
    if (state.mode === "manual") {
      body.append("counts", JSON.stringify(state.counts || {}));
    }
    body.append("agent_stages", JSON.stringify(state.agentStages || {}));
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        body.append(k, extra[k]);
      });
    }
    return fetch(ENDPOINT, {
      method: "POST",
      body: body,
      credentials: "same-origin"
    }).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          var snip = (text || "").replace(/\s+/g, " ").slice(0, 160);
          throw new Error("Server error (HTTP " + res.status + "): " + (snip || "empty response"));
        }
        if (!res.ok || !data || data.ok === false) {
          throw new Error((data && (data.error || (data.errors && data.errors[0]))) || "Request failed");
        }
        return data;
      });
    });
  }

  function defaultHeads(teams) {
    return (teams || []).map(function (t) {
      return t.head_id;
    });
  }

  function agentCount() {
    if (!meta || !meta.teams) {
      return 0;
    }
    var n = 0;
    var want = {};
    state.headIds.forEach(function (h) {
      want[h] = true;
    });
    meta.teams.forEach(function (t) {
      if (want[t.head_id]) {
        n += (t.agents || []).length;
      }
    });
    return n;
  }

  function selectedAgents() {
    var out = [];
    var want = {};
    state.headIds.forEach(function (h) {
      want[h] = true;
    });
    (meta.teams || []).forEach(function (t) {
      if (!want[t.head_id]) {
        return;
      }
      (t.agents || []).forEach(function (a) {
        out.push(a);
      });
    });
    return out;
  }

  function closeModal() {
    if (jobPollTimer) {
      window.clearInterval(jobPollTimer);
      jobPollTimer = 0;
    }
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
    overlay = null;
    state.resolvedIds = null;
    state.resolvedTotal = 0;
    state.forAll = false;
    state.deferredForAll = false;
    state.jobId = "";
    document.body.style.overflow = "";
  }

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "className") {
          node.className = attrs[k];
        } else if (k === "text") {
          node.textContent = attrs[k];
        } else if (k === "html") {
          node.textContent = attrs.html;
        } else if (k.slice(0, 2) === "on" && typeof attrs[k] === "function") {
          node.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else if (attrs[k] !== null && attrs[k] !== undefined) {
          node.setAttribute(k, attrs[k]);
        }
      });
    }
    (kids || []).forEach(function (child) {
      if (child == null) {
        return;
      }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function renderPreviewText() {
    var n = selectedCount();
    var m = agentCount();
    if (!m) {
      return "Select at least one team.";
    }
    var base = Math.floor(n / m);
    var rem = n % m;
    return n + " " + noun() + " → " + m + " agents (~" + base + (rem ? " or " + (base + 1) : "") + " each).";
  }

  function toggleHead(headId) {
    var id = Number(headId);
    var idx = state.headIds.indexOf(id);
    if (idx >= 0) {
      if (state.headIds.length === 1) {
        return;
      }
      state.headIds.splice(idx, 1);
    } else {
      state.headIds.push(id);
    }
    state.counts = {};
    paintModal();
  }

  function selectPakistan() {
    state.headIds = defaultHeads(meta.teams);
    state.counts = {};
    paintModal();
  }

  function stageName(id) {
    var list = (meta && meta.stages) || [];
    for (var i = 0; i < list.length; i += 1) {
      if (String(list[i].id) === String(id)) {
        return list[i].name;
      }
    }
    return id === "__KEEP__" ? "Keep current stage" : String(id || "");
  }

  function quickStages() {
    var want = {
      __KEEP__: true,
      NEW: true,
      UC_MJDO60: true
    };
    var out = [];
    var seen = {};
    ((meta && meta.stages) || []).forEach(function (s) {
      if (want[s.id] && !seen[s.id]) {
        seen[s.id] = true;
        out.push(s);
      }
    });
    return out;
  }

  function buildSearchSelect(opts) {
    var value = opts.value;
    var items = opts.items || [];
    var placeholder = opts.placeholder || "Search…";
    var emptyText = opts.emptyText || "No matches.";
    var onPick = opts.onPick;
    var openKey = opts.openKey;
    var queryKey = opts.queryKey;
    var isOpen = !!state[openKey];
    var query = state[queryKey] || "";

    var root = el("div", { className: "a7-ta-dd" + (isOpen ? " is-open" : "") });
    var trigger = el("button", {
      type: "button",
      className: "a7-ta-dd-trigger",
      onClick: function (ev) {
        ev.preventDefault();
        state[openKey] = !state[openKey];
        if (state[openKey]) {
          state[queryKey] = "";
        }
        paintModal();
        if (state[openKey]) {
          window.setTimeout(function () {
            var inp = overlay && overlay.querySelector(".a7-ta-dd.is-open .a7-ta-dd-search");
            if (inp) {
              inp.focus();
            }
          }, 0);
        }
      }
    });
    trigger.appendChild(el("span", { className: "a7-ta-dd-value", text: opts.labelFor(value) }));
    trigger.appendChild(el("span", { className: "a7-ta-dd-caret", text: "▾" }));
    root.appendChild(trigger);

    if (isOpen) {
      var menu = el("div", { className: "a7-ta-dd-menu" });
      var search = el("input", {
        className: "a7-ta-dd-search",
        type: "search",
        placeholder: placeholder,
        value: query,
        autocomplete: "off"
      });
      var list = el("div", { className: "a7-ta-dd-items" });
      function fill(q) {
        while (list.firstChild) {
          list.removeChild(list.firstChild);
        }
        var needle = String(q || "")
          .trim()
          .toLowerCase();
        var shown = 0;
        items.forEach(function (item) {
          var label = String(item.name || item.label || "");
          var id = String(item.id);
          if (
            needle &&
            label.toLowerCase().indexOf(needle) < 0 &&
            id.toLowerCase().indexOf(needle) < 0
          ) {
            return;
          }
          shown += 1;
          list.appendChild(
            el("button", {
              type: "button",
              className: "a7-ta-dd-item" + (String(value) === id ? " is-on" : ""),
              text: label,
              onClick: function (ev) {
                ev.preventDefault();
                ev.stopPropagation();
                state[openKey] = false;
                state[queryKey] = "";
                onPick(item.id);
              }
            })
          );
        });
        if (!shown) {
          list.appendChild(el("div", { className: "a7-ta-dd-empty", text: emptyText }));
        }
      }
      search.addEventListener("input", function () {
        state[queryKey] = search.value;
        fill(search.value);
      });
      search.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") {
          state[openKey] = false;
          state[queryKey] = "";
          paintModal();
        }
      });
      search.addEventListener("click", function (ev) {
        ev.stopPropagation();
      });
      fill(query);
      menu.appendChild(search);
      menu.appendChild(list);
      root.appendChild(menu);
    }
    return root;
  }

  function buildStagePicker() {
    var wrap = el("div", { className: "a7-ta-combo" });
    var quick = el("div", { className: "a7-ta-chips a7-ta-quick" });
    quickStages().forEach(function (s) {
      quick.appendChild(
        el("button", {
          type: "button",
          className: "a7-ta-chip" + (String(state.stage) === String(s.id) ? " is-on" : ""),
          text: s.id === "__KEEP__" ? "Keep current" : s.name,
          onClick: function () {
            state.stage = s.id;
            state.stageQuery = "";
            state.stageOpen = false;
            paintModal();
          }
        })
      );
    });
    wrap.appendChild(quick);
    wrap.appendChild(
      buildSearchSelect({
        value: state.stage,
        items: (meta && meta.stages) || [],
        openKey: "stageOpen",
        queryKey: "stageQuery",
        placeholder: "Search stages…",
        emptyText: "No stage matches.",
        labelFor: stageName,
        onPick: function (id) {
          state.stage = id;
          paintModal();
        }
      })
    );
    wrap.appendChild(
      el("p", {
        className: "a7-ta-help",
        text: "Keep current leaves each card’s stage as it is. Choosing a stage applies it to every assigned card."
      })
    );
    return wrap;
  }

  function buildFilterPanel(opts) {
    var query = opts.query || "";
    var panel = el("div", { className: "a7-ta-filter-panel" });
    var search = el("input", {
      className: "a7-ta-dd-search",
      type: "search",
      placeholder: opts.placeholder || "Search…",
      value: query,
      autocomplete: "off"
    });
    var body = el("div", { className: "a7-ta-filter-body" });
    opts.renderBody(body, query);
    search.addEventListener("input", function () {
      opts.onQuery(search.value);
      while (body.firstChild) {
        body.removeChild(body.firstChild);
      }
      opts.renderBody(body, search.value);
    });
    search.addEventListener("click", function (ev) {
      ev.stopPropagation();
    });
    panel.appendChild(search);
    panel.appendChild(body);
    return panel;
  }

  function filterAgents(agents, query) {
    var q = String(query || "")
      .trim()
      .toLowerCase();
    if (!q) {
      return agents;
    }
    return agents.filter(function (a) {
      return String(a.name || "")
        .toLowerCase()
        .indexOf(q) >= 0;
    });
  }

  function buildLevel1(body) {
    body.appendChild(
      el("div", { className: "a7-ta-row" }, [
        el("span", { className: "a7-ta-label", text: "Team" }),
        el("div", { className: "a7-ta-chips" }, [
          el("button", {
            type: "button",
            className: "a7-ta-chip" + (state.headIds.length === (meta.teams || []).length ? " is-on" : ""),
            text: "Pakistan team",
            onClick: selectPakistan
          })
        ].concat(
          (meta.teams || []).map(function (t) {
            return el("button", {
              type: "button",
              className: "a7-ta-chip" + (state.headIds.indexOf(t.head_id) >= 0 ? " is-on" : ""),
              text: t.label,
              onClick: function () {
                toggleHead(t.head_id);
              }
            });
          })
        ))
      ])
    );

    body.appendChild(
      el("div", { className: "a7-ta-row" }, [
        el("span", { className: "a7-ta-label", text: "Stage" }),
        buildStagePicker()
      ])
    );

    body.appendChild(
      el("div", { className: "a7-ta-row" }, [
        el("span", { className: "a7-ta-label", text: "Preview" }),
        el("div", { className: "a7-ta-preview", text: renderPreviewText() })
      ])
    );
  }

  function syncCountsFromPreview() {
    var agents = selectedAgents();
    var n = selectedCount();
    var m = agents.length || 1;
    var base = Math.floor(n / m);
    var rem = n % m;
    state.counts = {};
    agents.forEach(function (a, i) {
      state.counts[a.id] = base + (i < rem ? 1 : 0);
    });
  }

  function buildLevel2(body) {
    var wrap = el("div", { className: "a7-ta-level" });
    wrap.appendChild(el("span", { className: "a7-ta-label", text: "More details" }));

    var modeRow = el("div", { className: "a7-ta-mode" }, [
      el("button", {
        type: "button",
        className: state.mode === "equal" || state.mode === "manual" ? "is-on" : "",
        text: "Equal",
        onClick: function () {
          state.mode = "equal";
          syncCountsFromPreview();
          paintModal();
        }
      }),
      el("button", {
        type: "button",
        className: state.mode === "community" ? "is-on" : "",
        text: "Community-wise",
        onClick: function () {
          state.mode = "community";
          paintModal();
          refreshPreview();
        }
      })
    ]);
    wrap.appendChild(modeRow);

    if (state.mode === "community") {
      var noComm = (state.preview && state.preview.no_community) || 0;
      wrap.appendChild(
        el("div", {
          className: "a7-ta-banner" + (noComm ? " is-warn" : ""),
          text: noComm
            ? noComm + " selected " + noun() + " have no community."
            : "Every selected card has a community."
        })
      );

      wrap.appendChild(
        el("div", { className: "a7-ta-row" }, [
          el("span", { className: "a7-ta-label", text: "No community" }),
          buildSearchSelect({
            value: state.noCommunity,
            items: [
              { id: "rr", name: "Round-robin across selected agents" },
              { id: "skip", name: "Skip (leave unassigned)" },
              { id: "user", name: "Give all to one agent" }
            ],
            openKey: "noCommOpen",
            queryKey: "noCommQuery",
            placeholder: "Search option…",
            emptyText: "No matches.",
            labelFor: function (id) {
              if (id === "skip") {
                return "Skip (leave unassigned)";
              }
              if (id === "user") {
                return "Give all to one agent";
              }
              return "Round-robin across selected agents";
            },
            onPick: function (id) {
              state.noCommunity = id;
              paintModal();
            }
          })
        ])
      );

      if (state.noCommunity === "user") {
        wrap.appendChild(
          el("div", { className: "a7-ta-row" }, [
            buildSearchSelect({
              value: state.noCommunityUser || (selectedAgents()[0] && selectedAgents()[0].id) || 0,
              items: selectedAgents().map(function (a) {
                return { id: a.id, name: a.name };
              }),
              openKey: "noCommUserOpen",
              queryKey: "noCommUserQuery",
              placeholder: "Search agent…",
              emptyText: "No agent matches.",
              labelFor: function (id) {
                var agents = selectedAgents();
                for (var i = 0; i < agents.length; i += 1) {
                  if (Number(agents[i].id) === Number(id)) {
                    return agents[i].name;
                  }
                }
                return "Choose agent";
              },
              onPick: function (id) {
                state.noCommunityUser = Number(id);
                paintModal();
              }
            })
          ])
        );
      }
    }

    var agentsAll = selectedAgents();
    if (!Object.keys(state.counts || {}).length) {
      syncCountsFromPreview();
    }
    function countTotalText() {
      var total = 0;
      Object.keys(state.counts || {}).forEach(function (k) {
        total += Number(state.counts[k]) || 0;
      });
      return "Planned " + total + " / selected " + selectedCount();
    }
    var totalEl = el("p", { className: "a7-ta-help", text: countTotalText() });
    var panel = buildFilterPanel({
      query: state.agentQuery || "",
      placeholder: "Search agent…",
      onQuery: function (q) {
        state.agentQuery = q;
      },
      renderBody: function (bodyNode, query) {
        var table = el("table", { className: "a7-ta-table" });
        table.appendChild(
          el("thead", null, [
            el("tr", null, [el("th", { text: "Agent" }), el("th", { text: "Count" })])
          ])
        );
        var tbody = el("tbody");
        var agents = filterAgents(agentsAll, query);
        agents.forEach(function (a) {
          var input = el("input", {
            type: "number",
            min: "0",
            value: String(state.counts[a.id] != null ? state.counts[a.id] : 0)
          });
          input.addEventListener("change", function () {
            state.counts[a.id] = Math.max(0, parseInt(input.value, 10) || 0);
            state.mode = "manual";
            totalEl.textContent = countTotalText();
          });
          tbody.appendChild(el("tr", null, [el("td", { text: a.name }), el("td", null, [input])]));
        });
        if (!agents.length) {
          tbody.appendChild(
            el("tr", null, [el("td", { text: "No agent matches.", colSpan: "2" })])
          );
        }
        table.appendChild(tbody);
        bodyNode.appendChild(table);
      }
    });
    wrap.appendChild(
      el("div", { className: "a7-ta-row" }, [
        el("span", { className: "a7-ta-label", text: "Per-agent counts" }),
        panel,
        totalEl,
        el("p", {
          className: "a7-ta-help",
          text: "Totals must match the selection. Editing a count switches to manual split."
        })
      ])
    );

    body.appendChild(wrap);
  }

  function buildLevel3(body) {
    var wrap = el("div", { className: "a7-ta-level" });
    wrap.appendChild(el("span", { className: "a7-ta-label", text: "Per-agent stage" }));
    var agentsAll = selectedAgents();
    var panel = buildFilterPanel({
      query: state.agentQuery || "",
      placeholder: "Search agent…",
      onQuery: function (q) {
        state.agentQuery = q;
      },
      renderBody: function (bodyNode, query) {
        var table = el("table", { className: "a7-ta-table" });
        table.appendChild(
          el("thead", null, [
            el("tr", null, [
              el("th", { text: "Agent" }),
              el("th", { text: "Stage override" })
            ])
          ])
        );
        var tbody = el("tbody");
        filterAgents(agentsAll, query).forEach(function (a) {
          var openKey = "agentStageOpen_" + a.id;
          var queryKey = "agentStageQuery_" + a.id;
          if (state[openKey] === undefined) {
            state[openKey] = false;
          }
          if (state[queryKey] === undefined) {
            state[queryKey] = "";
          }
          var stageItems = [{ id: "", name: "Use stage from above" }].concat(
            ((meta && meta.stages) || []).map(function (s) {
              return { id: s.id, name: s.name };
            })
          );
          var current = state.agentStages[a.id] || "";
          var picker = buildSearchSelect({
            value: current,
            items: stageItems,
            openKey: openKey,
            queryKey: queryKey,
            placeholder: "Search stage…",
            emptyText: "No stage matches.",
            labelFor: function (id) {
              if (!id) {
                return "Use stage from above";
              }
              return stageName(id);
            },
            onPick: function (id) {
              if (!id) {
                delete state.agentStages[a.id];
              } else {
                state.agentStages[a.id] = id;
              }
              paintModal();
            }
          });
          tbody.appendChild(el("tr", null, [el("td", { text: a.name }), el("td", null, [picker])]));
        });
        table.appendChild(tbody);
        bodyNode.appendChild(table);
      }
    });
    wrap.appendChild(panel);
    body.appendChild(wrap);
  }

  function paintModal() {
    if (!overlay) {
      return;
    }
    var panel = overlay.querySelector(".a7-ta-panel");
    if (!panel) {
      return;
    }
    panel.innerHTML = "";
    var count = selectedCount();
    var sub =
      count +
      " " +
      noun() +
      " selected · " +
      entityLabel() +
      (state.forAll ? " · For all" : "") +
      (state.deferredForAll || count > 120 ? " · background for large runs" : "");
    panel.appendChild(
      el("div", { className: "a7-ta-head" }, [
        el("div", null, [
          el("h2", { text: "Assign to team" }),
          el("p", {
            className: "a7-ta-sub",
            text: sub
          })
        ]),
        el("button", { type: "button", className: "a7-ta-x", text: "×", onClick: closeModal })
      ])
    );
    var body = el("div", { className: "a7-ta-body" });
    buildLevel1(body);
    if (state.level >= 2) {
      buildLevel2(body);
    }
    if (state.level >= 3) {
      buildLevel3(body);
    }
    if (state.error) {
      body.appendChild(el("p", { className: "a7-ta-err", text: state.error }));
    }
    if (state.message) {
      body.appendChild(el("p", { className: "a7-ta-ok", text: state.message }));
    }
    panel.appendChild(body);

    var foot = el("div", { className: "a7-ta-foot" });
    if (state.level === 1) {
      foot.appendChild(
        el("button", {
          type: "button",
          text: "More details",
          onClick: function () {
            state.level = 2;
            state.mode = state.mode === "manual" ? "manual" : "equal";
            syncCountsFromPreview();
            paintModal();
            refreshPreview();
          }
        })
      );
    } else if (state.level === 2) {
      foot.appendChild(
        el("button", {
          type: "button",
          text: "More",
          onClick: function () {
            state.level = 3;
            paintModal();
          }
        })
      );
      foot.appendChild(
        el("button", {
          type: "button",
          text: "Back",
          onClick: function () {
            state.level = 1;
            paintModal();
          }
        })
      );
    } else {
      foot.appendChild(
        el("button", {
          type: "button",
          text: "Back",
          onClick: function () {
            state.level = 2;
            paintModal();
          }
        })
      );
    }
    foot.appendChild(
      el("button", {
        type: "button",
        className: "a7-ta-primary",
        text: busy ? "Working…" : "Apply",
        disabled: busy ? "disabled" : null,
        onClick: applyNow
      })
    );
    panel.appendChild(foot);
  }

  function entityLabel() {
    if (entity === "lead") {
      return "Leads";
    }
    if (entity === "owner_data") {
      return "Owner Data";
    }
    if (entity === "availability") {
      return "Availability";
    }
    return "Renewals";
  }

  function refreshPreview() {
    post("preview")
      .then(function (data) {
        state.preview = data;
        if (state.mode === "community" && data.by_agent) {
          state.counts = {};
          data.by_agent.forEach(function (row) {
            state.counts[row.user_id] = row.count;
          });
        }
        paintModal();
      })
      .catch(function (err) {
        state.error = err.message || String(err);
        paintModal();
      });
  }

  function reloadListSoon() {
    window.setTimeout(function () {
      try {
        if (window.BX && BX.Main && BX.Main.gridManager) {
          var dataGrids = BX.Main.gridManager.data || BX.Main.gridManager.list || [];
          dataGrids.forEach(function (entry) {
            if (entry && entry.instance && entry.instance.reloadTable) {
              entry.instance.reloadTable();
            }
          });
        }
      } catch (e) {}
      window.location.reload();
    }, 900);
  }

  function pollJob(jobId) {
    state.jobId = jobId;
    if (jobPollTimer) {
      window.clearInterval(jobPollTimer);
    }
    function tick() {
      var body = new FormData();
      body.append("sessid", bitrixSessid());
      body.append("action", "job_status");
      body.append("job_id", jobId);
      body.append("entity", entity);
      fetch(ENDPOINT, { method: "POST", body: body, credentials: "same-origin" })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (!data || !data.ok) {
            return;
          }
          var msg =
            "Background assign: " +
            (data.updated || 0) +
            " / " +
            (data.total || 0) +
            (data.failed ? " · " + data.failed + " failed" : "") +
            " · " +
            (data.status || "");
          state.message = msg;
          paintModal();
          if (data.done) {
            window.clearInterval(jobPollTimer);
            jobPollTimer = 0;
            busy = false;
            notify(msg, !data.failed);
            if (!data.failed) {
              reloadListSoon();
            }
          }
        })
        .catch(function () {});
    }
    tick();
    jobPollTimer = window.setInterval(tick, 2500);
  }

  function applyNow() {
    if (busy) {
      return;
    }
    var count = selectedCount();
    if (!count && !state.deferredForAll) {
      notify("Select at least one card.", false);
      return;
    }
    if (state.level >= 2 && state.mode === "manual" && !state.deferredForAll) {
      var total = 0;
      Object.keys(state.counts).forEach(function (k) {
        total += Number(state.counts[k]) || 0;
      });
      if (total !== workingIds().length) {
        state.error = "Counts add up to " + total + " but " + workingIds().length + " are selected.";
        paintModal();
        return;
      }
    }
    busy = true;
    state.error = "";
    state.message = state.deferredForAll || count > 120 ? "Queuing background assign…" : "";
    paintModal();
    post("apply")
      .then(function (data) {
        if (data.background && data.job_id) {
          state.message =
            "Background assign started for " +
            (data.total || count) +
            " " +
            noun() +
            ". You can leave — it keeps running.";
          paintModal();
          notify(state.message, true);
          pollJob(data.job_id);
          return;
        }
        busy = false;
        var msg =
          "Assigned " +
          (data.updated || 0) +
          " " +
          noun() +
          (data.failed ? " · " + data.failed + " failed" : "") +
          (data.skipped ? " · " + data.skipped + " skipped" : "");
        state.message = msg;
        paintModal();
        notify(msg, !data.failed);
        if (!data.failed) {
          reloadListSoon();
        }
      })
      .catch(function (err) {
        busy = false;
        state.error = err.message || String(err);
        paintModal();
        notify(state.error, false);
      });
  }

  function openModal() {
    ensureCss();
    if (busy) {
      return;
    }
    busy = true;
    notify(isForAllChecked() ? "Loading all selected cards…" : "Opening assign…", true);

    function show() {
      if (!meta) {
        return;
      }
      if (!state.headIds.length) {
        state.headIds = defaultHeads(meta.teams);
      }
      // closeModal clears selection state — keep it across overlay recreate.
      var keepIds = state.resolvedIds;
      var keepTotal = state.resolvedTotal;
      var keepForAll = state.forAll;
      var keepDeferred = state.deferredForAll;
      var keepGrid = state.gridId;
      if (overlay) {
        closeModal();
      }
      state.resolvedIds = keepIds;
      state.resolvedTotal = keepTotal;
      state.forAll = keepForAll;
      state.deferredForAll = keepDeferred;
      state.gridId = keepGrid;
      overlay = el("div", { className: "a7-ta-overlay" });
      overlay.addEventListener("click", function (ev) {
        if (ev.target === overlay) {
          closeModal();
        }
      });
      overlay.appendChild(el("div", { className: "a7-ta-panel" }));
      document.body.appendChild(overlay);
      document.body.style.overflow = "hidden";
      paintModal();
    }

    function afterMeta() {
      return resolveSelection().then(function (ids) {
        busy = false;
        if (!selectedCount() && !(ids && ids.length)) {
          notify("Select at least one card first.", false);
          return;
        }
        state.level = 1;
        state.mode = "equal";
        state.error = "";
        state.message = "";
        state.counts = {};
        state.agentStages = {};
        state.agentQuery = "";
        state.stageQuery = "";
        state.stageOpen = false;
        state.noCommOpen = false;
        state.noCommQuery = "";
        state.noCommUserOpen = false;
        state.noCommUserQuery = "";
        state.preview = null;
        show();
      });
    }

    var chain;
    if (meta) {
      chain = afterMeta();
    } else {
      chain = post("meta", { ids: JSON.stringify([]) }).then(function (data) {
        meta = data;
        if (typeof data.max_ids === "number") {
          MAX_IDS = data.max_ids;
        }
        if (data.client_ids_max) {
          CLIENT_IDS_MAX = data.client_ids_max;
        }
        return afterMeta();
      });
    }
    chain.catch(function (err) {
      busy = false;
      notify(err.message || "Could not load selection.", false);
    });
  }

  function findTitleHost() {
    return (
      document.querySelector(".pagetitle-container .pagetitle-menu") ||
      document.querySelector(".ui-toolbar-right-buttons") ||
      document.querySelector(".pagetitle-inner-container") ||
      document.querySelector(".pagetitle")
    );
  }

  function makeButton() {
    var btn = el("button", {
      type: "button",
      className: BTN_CLASS,
      text: "Assign to team",
      onClick: openModal
    });
    return btn;
  }

  function dropOldButtons() {
    var nodes = document.querySelectorAll("." + SLOT_CLASS + ", ." + BTN_CLASS);
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i] && nodes[i].parentNode) {
        nodes[i].parentNode.removeChild(nodes[i]);
      }
    }
  }

  function mountButton() {
    ensureCss();
    var existing = document.querySelector("." + BTN_CLASS);
    if (existing && existing.closest("." + SLOT_CLASS)) {
      return;
    }
    dropOldButtons();
    var host = findTitleHost();
    var slot = el("span", { className: SLOT_CLASS }, [makeButton()]);
    if (host) {
      if (host.firstChild) {
        host.insertBefore(slot, host.firstChild);
      } else {
        host.appendChild(slot);
      }
      return;
    }
    var bar = el("div");
    bar.style.cssText =
      "position:sticky;top:0;z-index:50;display:flex;justify-content:flex-end;padding:8px 16px;";
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
    var forAll = false;
    try {
      count = selectedIds().length;
      forAll = isForAllChecked();
    } catch (e) {
      count = 0;
    }
    // For all can mean thousands of rows with only a page of checkboxes in the DOM.
    if (count < 1 && !forAll) {
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
        [
          "Grid::selectRow",
          "Grid::unselectRow",
          "Grid::allRowsSelected",
          "Grid::allRowsUnselected",
          "Grid::updated"
        ].forEach(function (name) {
          BX.addCustomEvent(window, name, schedule);
        });
      }
    } catch (e) {}
    try {
      var mo = new MutationObserver(schedule);
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (e2) {}
    window.setInterval(syncButton, 200);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
