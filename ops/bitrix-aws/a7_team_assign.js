/**
 * A7 team bulk assign — progressive tree on CRM lists.
 * Leads, Owner Data (1042/13), Availability (1042/14), Renewals (deal cat 9).
 */
(function () {
  if (window.A7_TEAM_ASSIGN_V12) {
    return;
  }
  window.A7_TEAM_ASSIGN_V12 = true;

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
    scope: "all",
    picked: {},
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
    // When For all is on, IDs come from the server (the list's own filter), never DOM checkboxes.
    resolvedIds: null,
    resolvedTotal: 0,
    forAll: false,
    deferredForAll: false,
    gridId: "",
    jobId: "",
    filterWarning: "",
    // What the server needs to resolve For all again at preview/apply time.
    forAllCtx: null,
    // For all could not be resolved: the modal says why and offers no Apply.
    resolveError: ""
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
      // The grid keeps a hidden edit row, data-id="template_0", that For all ticks with
      // the rest. Its digits are not a card — it is what made 20 ticked rows read "21".
      if (/^template/i.test(raw)) {
        continue;
      }
      var id = /^\d+$/.test(raw) ? raw : ((raw.match(/(\d+)(?:\D*)$/) || [])[1] || "");
      if (!id || /^0+$/.test(id) || seen[id]) {
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

  /**
   * True only when Bitrix FOR ALL is explicitly on.
   * Do NOT use .main-grid-panel-counter-for-all-enable or "ALL ITEMS SELECTED" text —
   * those appear when the current PAGE is fully checked (e.g. SELECTED 10/10) and caused
   * false FOR ALL → resolve entire SPA list (9000+ cards) instead of the checked rows.
   */
  function isForAllChecked() {
    try {
      var grid = getActiveGrid();
      if (grid) {
        var panel = typeof grid.getActionsPanel === "function" ? grid.getActionsPanel() : null;
        if (panel && typeof panel.getForAllCheckbox === "function") {
          var cb = panel.getForAllCheckbox();
          if (cb && cb.checked) {
            return true;
          }
        }
        if (panel && typeof panel.getValues === "function") {
          var vals = panel.getValues() || {};
          var gid = typeof grid.getId === "function" ? grid.getId() : "";
          var key = "action_all_rows_" + gid;
          if (vals[key] === "Y" || vals.action_all_rows === "Y") {
            // Require matching visible checkbox when present — stale panel values
            // alone must not expand selection to the whole list.
            var root = typeof grid.getContainer === "function" ? grid.getContainer() : null;
            var box =
              (root && root.querySelector(".main-grid-for-all-checkbox input[type='checkbox']")) ||
              document.querySelector(".main-grid-for-all-checkbox input[type='checkbox']");
            if (!box || box.checked) {
              return true;
            }
          }
        }
      }
    } catch (e) {}
    try {
      var forAllInput = document.querySelector(
        ".main-grid-for-all-checkbox input[type='checkbox']:checked"
      );
      if (forAllInput) {
        return true;
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
    // For all never falls back to the ticked rows: those are one page of the answer,
    // and quietly assigning them is how "For all" once moved 20 leads out of 122.
    if (state.forAll) {
      return (state.resolvedIds || []).slice();
    }
    if (state.resolvedIds && state.resolvedIds.length) {
      return state.resolvedIds.slice();
    }
    return selectedIds();
  }

  function selectedCount() {
    if (state.forAll) {
      return state.resolvedTotal;
    }
    if (state.resolvedTotal > 0) {
      return state.resolvedTotal;
    }
    return workingIds().length;
  }

  // Every card row the active grid is showing, ticked or not. The server checks each
  // one is in what For all resolved — a row it lacks means the filter is not this page's.
  function pageRowIds() {
    var ids = [];
    try {
      var grid = getActiveGrid();
      var rows = grid && typeof grid.getRows === "function" ? grid.getRows() : null;
      var body = rows && typeof rows.getBodyChild === "function" ? rows.getBodyChild() : null;
      if (body && body.length) {
        for (var i = 0; i < body.length; i += 1) {
          ids.push(body[i] && typeof body[i].getId === "function" ? body[i].getId() : "");
        }
        return uniqueIds(ids);
      }
      var root = grid && typeof grid.getContainer === "function" ? grid.getContainer() : document;
      var nodes = (root || document).querySelectorAll(".main-grid-row.main-grid-row-body[data-id]");
      for (var j = 0; j < nodes.length; j += 1) {
        ids.push(nodes[j].getAttribute("data-id") || "");
      }
    } catch (e) {}
    return uniqueIds(ids);
  }

  // The list's own "Total: N", once somebody has clicked Show — read from its own
  // element. The footer's whole text runs the total into the page numbers.
  function readShownTotal() {
    try {
      var gid = String(activeGridId() || "").toLowerCase();
      var node = gid ? document.getElementById(gid + "_row_count_wrapper") : null;
      if (!node || node.querySelector("a")) {
        return 0;
      }
      var text = String(node.textContent || "").replace(/[\u00a0\u202f]/g, " ");
      var m = text.match(/:\s*(\d[\d,\s]*)\s*$/);
      return m ? parseInt(m[1].replace(/\D/g, ""), 10) || 0 : 0;
    } catch (e) {}
    return 0;
  }

  // The list's filter fingerprint as of the last time this tab drew its grid. FOR ALL
  // sends it back, and the server refuses if another tab has changed the filter since —
  // the page check alone cannot see a filter that was only widened.
  var drawn = { gridId: "", stamp: "", rows: "" };
  var stampSeq = 0;

  function rowsSignature() {
    return pageRowIds().join(",");
  }

  function fetchStamp() {
    var gid = activeGridId();
    if (!gid) {
      return Promise.resolve("");
    }
    var seq = (stampSeq += 1);
    var rows = rowsSignature();
    var body = new FormData();
    body.append("sessid", bitrixSessid());
    body.append("action", "filter_stamp");
    body.append("entity", entity);
    body.append("grid_id", gid);
    return fetch(ENDPOINT, { method: "POST", body: body, credentials: "same-origin", cache: "no-store" })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (seq === stampSeq && data && data.ok && data.stamp) {
          drawn = { gridId: gid, stamp: String(data.stamp), rows: rows };
        }
        return seq === stampSeq && data && data.stamp ? String(data.stamp) : "";
      })
      .catch(function () {
        return "";
      });
  }

  // Taken when the grid is drawn, not when FOR ALL is ticked: by then another tab may
  // already have changed the filter, and a fresh stamp would agree with it.
  function stampDrawnGrid() {
    var rows = rowsSignature();
    if (!rows || (drawn.gridId === activeGridId() && drawn.rows === rows)) {
      return;
    }
    fetchStamp();
  }

  function stampForForAll() {
    // Same grid, same rows as when the stamp was taken: this tab has not been redrawn since,
    // so the stamp is the filter on screen. If it was redrawn unseen, take one now — that
    // checks nothing, but it cannot refuse a page that is in fact current.
    if (drawn.stamp && drawn.gridId === activeGridId() && drawn.rows === rowsSignature()) {
      return Promise.resolve(drawn.stamp);
    }
    return fetchStamp();
  }

  function appendForAll(body) {
    var ctx = state.forAllCtx || {};
    body.append("for_all", "Y");
    body.append("grid_id", ctx.gridId || state.gridId || activeGridId());
    body.append("page_ids", JSON.stringify(ctx.pageIds || []));
    body.append("expected_total", String(ctx.shownTotal || 0));
    if (ctx.stamp) {
      body.append("filter_stamp", ctx.stamp);
    }
    // Set once a large For all is resolved: Preview/Apply then use the very IDs confirmed.
    if (ctx.selection) {
      body.append("selection", ctx.selection);
    }
  }

  var resolveGen = 0;

  function resolveSelection() {
    // A newer opening supersedes this one; its late answer must not paint over it.
    var gen = (resolveGen += 1);
    state.deferredForAll = false;
    state.resolveError = "";
    state.filterWarning = "";
    state.forAllCtx = null;
    state.gridId = activeGridId();

    // Only the FOR ALL checkbox itself turns this on — a fully ticked page is not For all.
    if (!isForAllChecked()) {
      state.forAll = false;
      state.resolvedIds = selectedIds();
      state.resolvedTotal = state.resolvedIds.length;
      return Promise.resolve(state.resolvedIds);
    }

    state.forAll = true;
    state.resolvedIds = [];
    state.resolvedTotal = 0;
    var ctx = {
      gridId: state.gridId,
      pageIds: pageRowIds(),
      shownTotal: readShownTotal(),
      stamp: "",
      selection: ""
    };
    state.forAllCtx = ctx;
    return stampForForAll().then(function (stamp) {
      ctx.stamp = stamp;
      var body = new FormData();
      body.append("sessid", bitrixSessid());
      body.append("action", "resolve");
      body.append("entity", entity);
      appendForAll(body);
      return fetch(ENDPOINT, {
        method: "POST",
        body: body,
        credentials: "same-origin",
        cache: "no-store"
      });
    }).then(function (res) {
      return res.text().then(function (text) {
        if (gen !== resolveGen) {
          throw new Error("superseded");
        }
        var data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          var snip = (text || "").replace(/\s+/g, " ").slice(0, 160);
          throw new Error("Server error (HTTP " + res.status + "): " + (snip || "empty response"));
        }
        if (!res.ok || !data || data.ok === false) {
          throw new Error((data && data.error) || "FOR ALL could not read this list's filter. Refresh the page (F5) and try again.");
        }
        state.filterWarning = data.warning || "";
        if (data.deferred) {
          state.deferredForAll = true;
          state.resolvedIds = null;
          state.resolvedTotal = Number(data.total) || 0;
          ctx.selection = data.selection || "";
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
      // Too many IDs to carry: the server resolves For all again, with the same checks.
      appendForAll(body);
      body.append("ids", JSON.stringify([]));
    } else {
      body.append("ids", JSON.stringify(workingIds()));
    }
    body.append("head_ids", JSON.stringify(state.scope === "all" ? [] : state.headIds));
    body.append("scope", state.scope === "all" ? "all" : "teams");
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

  function listedAgents() {
    if (state.scope === "all") {
      return (meta && meta.users) || [];
    }
    return selectedAgents();
  }

  function pickedAgents() {
    return listedAgents().filter(function (a) {
      return !!state.picked[a.id] || !!state.picked[String(a.id)];
    });
  }

  function agentCount() {
    var picked = pickedAgents();
    return picked.length || listedAgents().length;
  }

  function selectedAgents() {
    var out = [];
    var seen = {};
    var want = {};
    state.headIds.forEach(function (h) {
      want[h] = true;
    });
    (meta.teams || []).forEach(function (t) {
      if (!want[t.head_id]) {
        return;
      }
      (t.agents || []).forEach(function (a) {
        var id = Number(a.id);
        if (!id || seen[id]) {
          return;
        }
        seen[id] = true;
        out.push(a);
      });
    });
    return out;
  }

  function teamsAllSelected() {
    return state.scope === "all";
  }

  function countMath() {
    var planned = 0;
    Object.keys(state.counts || {}).forEach(function (k) {
      planned += Number(state.counts[k]) || 0;
    });
    var selected = selectedCount();
    return { selected: selected, planned: planned, left: selected - planned };
  }

  function tallyText(math) {
    var tail = math.left === 0 ? "Ready" : math.left > 0 ? math.left + " left" : Math.abs(math.left) + " extra";
    return "Selected " + math.selected + " · Planned " + math.planned + " · " + tail;
  }

  function tallyClass(math) {
    if (math.left === 0) {
      return "a7-ta-tally is-ok";
    }
    if (math.left > 0) {
      return "a7-ta-tally is-left";
    }
    return "a7-ta-tally is-over";
  }

  function countsNeedBalance() {
    if (state.mode === "community") {
      return false;
    }
    if (state.scope === "all") {
      return true;
    }
    return state.level >= 2;
  }

  function refreshTallyAndApply() {
    if (!overlay) {
      return;
    }
    var math = countMath();
    var tally = overlay.querySelector(".a7-ta-tally");
    if (tally) {
      tally.className = tallyClass(math);
      tally.textContent = tallyText(math);
    }
    var apply = overlay.querySelector(".a7-ta-primary");
    if (apply && !busy) {
      apply.disabled = countsNeedBalance() && math.left !== 0;
    }
  }

  function closeModal() {
    // Do not kill an in-flight background job poll — toast still reports completion.
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
    overlay = null;
    document.body.style.overflow = "";
    state.level = 1;
    state.error = "";
    state.message = "";
    state.filterWarning = "";
    state.resolvedIds = null;
    state.resolvedTotal = 0;
    state.forAll = false;
    state.deferredForAll = false;
    state.gridId = "";
    state.forAllCtx = null;
    state.resolveError = "";
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
    if (state.scope === "all") {
      var users = listedAgents().length;
      var picked = pickedAgents().length;
      if (!picked) {
        return n + " " + noun() + " · " + users + " users. Tick who should receive them, then Equal.";
      }
      var baseAll = Math.floor(n / picked);
      var remAll = n % picked;
      return n + " " + noun() + " → " + picked + " selected users (~" + baseAll + (remAll ? " or " + (baseAll + 1) : "") + " each).";
    }
    var m = listedAgents().length;
    if (!m) {
      return "Select at least one team.";
    }
    var base = Math.floor(n / m);
    var rem = n % m;
    return n + " " + noun() + " → " + m + " agents (~" + base + (rem ? " or " + (base + 1) : "") + " each).";
  }

  function afterTeamChange() {
    state.counts = {};
    state.picked = {};
    if (state.mode === "community") {
      paintModal();
      refreshPreview();
      return;
    }
    if (state.level >= 2 && state.scope !== "all") {
      syncCountsFromPreview();
      state.mode = "manual";
    }
    paintModal();
  }

  function pickTeam(headId) {
    var id = Number(headId);
    if (state.scope === "all") {
      state.scope = "teams";
      state.headIds = [id];
      afterTeamChange();
      return;
    }
    var idx = state.headIds.indexOf(id);
    if (idx >= 0) {
      if (state.headIds.length === 1) {
        return;
      }
      state.headIds.splice(idx, 1);
    } else {
      state.headIds.push(id);
    }
    afterTeamChange();
  }

  function selectAllTeams() {
    state.scope = "all";
    state.headIds = [];
    afterTeamChange();
  }

  function equalTargets() {
    var picked = pickedAgents();
    if (picked.length) {
      return picked;
    }
    if (state.scope === "all") {
      return [];
    }
    return listedAgents();
  }

  function equalizeCounts() {
    var chosen = equalTargets();
    if (!chosen.length) {
      state.error = "Tick the users who should receive these leads, then press Equal.";
      paintModal();
      return;
    }
    state.error = "";
    var n = selectedCount();
    var m = chosen.length || 1;
    var base = Math.floor(n / m);
    var rem = n % m;
    var chosenIds = {};
    chosen.forEach(function (a, i) {
      chosenIds[a.id] = base + (i < rem ? 1 : 0);
    });
    state.counts = {};
    state.picked = {};
    listedAgents().forEach(function (a) {
      state.counts[a.id] = chosenIds[a.id] || 0;
      if (chosenIds[a.id]) {
        state.picked[a.id] = true;
      }
    });
    state.mode = "manual";
    paintModal();
  }

  function clearCounts() {
    state.counts = {};
    state.picked = {};
    listedAgents().forEach(function (a) {
      state.counts[a.id] = 0;
    });
    state.mode = "manual";
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
            className: "a7-ta-chip" + (teamsAllSelected() ? " is-on" : ""),
            text: "All",
            onClick: selectAllTeams
          })
        ].concat(
          (meta.teams || []).map(function (t) {
            var teamOn = !teamsAllSelected() && state.headIds.indexOf(t.head_id) >= 0;
            return el("button", {
              type: "button",
              className: "a7-ta-chip" + (teamOn ? " is-on" : ""),
              text: t.label,
              onClick: function () {
                pickTeam(t.head_id);
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
    var agents = equalTargets();
    if (!agents.length) {
      agents = listedAgents();
    }
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
        className: state.mode === "manual" ? "is-on" : "",
        text: "Equal",
        onClick: equalizeCounts
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

    var agentsAll = listedAgents();
    if (state.mode !== "community" && state.scope !== "all" && !Object.keys(state.counts || {}).length) {
      syncCountsFromPreview();
      state.mode = "manual";
    }
    var math = countMath();
    var tally = el("div", { className: tallyClass(math), text: tallyText(math) });
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
            el("tr", null, [el("th", { text: "" }), el("th", { text: "Agent" }), el("th", { text: "Count" })])
          ])
        );
        var tbody = el("tbody");
        var agents = filterAgents(agentsAll, query);
        agents.forEach(function (a) {
          var box = el("input", { type: "checkbox" });
          box.checked = !!state.picked[a.id];
          box.addEventListener("change", function () {
            if (box.checked) {
              state.picked[a.id] = true;
            } else {
              delete state.picked[a.id];
            }
            paintModal();
          });
          var input = el("input", {
            type: "number",
            min: "0",
            value: String(state.counts[a.id] != null ? state.counts[a.id] : 0)
          });
          input.addEventListener("input", function () {
            var n = Math.max(0, parseInt(input.value, 10) || 0);
            state.counts[a.id] = n;
            if (n > 0) {
              state.picked[a.id] = true;
            }
            state.mode = "manual";
            refreshTallyAndApply();
          });
          tbody.appendChild(el("tr", null, [
            el("td", null, [box]),
            el("td", { text: a.name }),
            el("td", null, [input])
          ]));
        });
        if (!agents.length) {
          tbody.appendChild(
            el("tr", null, [el("td", { text: "No user matches.", colSpan: "3" })])
          );
        }
        table.appendChild(tbody);
        bodyNode.appendChild(table);
      }
    });
    panel.classList.add("a7-ta-agent-list");
    wrap.appendChild(
      el("div", { className: "a7-ta-count-block" }, [
        el("div", { className: "a7-ta-count-head" }, [
          el("span", { className: "a7-ta-label", text: "Per-agent counts" }),
          el("span", {
            className: "a7-ta-agent-n",
            text: agentsAll.length + (state.scope === "all" ? " users" : " agents")
          }),
          el("button", { type: "button", className: "a7-ta-mini", text: "Equal", onClick: equalizeCounts }),
          el("button", { type: "button", className: "a7-ta-mini", text: "Clear", onClick: clearCounts })
        ]),
        tally,
        panel,
        el("p", {
          className: "a7-ta-help",
          text: "Tick who should receive leads, then Equal. All lists every user. A team chip lists only that team. Apply stays off until Planned matches the selection."
        })
      ])
    );

    body.appendChild(wrap);
  }

  function buildLevel3(body) {
    var wrap = el("div", { className: "a7-ta-level" });
    wrap.appendChild(el("span", { className: "a7-ta-label", text: "Per-agent stage" }));
    var agentsAll = listedAgents();
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
    while (panel.firstChild) {
      panel.removeChild(panel.firstChild);
    }
    var count = selectedCount();
    var sub = state.resolveError
      ? "FOR ALL · " + entityLabel()
      : count +
        " " +
        noun() +
        " selected · " +
        entityLabel() +
        (state.forAll ? " · FOR ALL" : "") +
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
    if (state.resolveError) {
      panel.appendChild(
        el("div", { className: "a7-ta-body" }, [
          el("p", { className: "a7-ta-err", text: state.resolveError }),
          el("p", {
            className: "a7-ta-help",
            text:
              "Nothing was assigned. To assign only some cards: close this, untick FOR ALL, tick the rows you want on this page, then press Assign to team."
          })
        ])
      );
      panel.appendChild(
        el("div", { className: "a7-ta-foot" }, [el("button", { type: "button", text: "Close", onClick: closeModal })])
      );
      return;
    }
    var pageRows = state.forAll && state.forAllCtx ? (state.forAllCtx.pageIds || []).length : 0;
    if (state.forAll && count > pageRows) {
      panel.appendChild(
        el("p", {
          className: "a7-ta-sub",
          text:
            "All " +
            count +
            " " +
            noun() +
            " that match the list filter, on every page — not only the " +
            pageRows +
            " on screen.",
          style: "margin:0 16px 8px;font-weight:600;color:#0b6e99;"
        })
      );
    }
    if (state.filterWarning) {
      panel.appendChild(
        el("p", {
          className: "a7-ta-sub",
          text: state.filterWarning,
          style: "color:#b54708;margin:0 16px 8px;font-weight:600;"
        })
      );
    }
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
            if (state.mode === "community") {
              paintModal();
              refreshPreview();
              return;
            }
            if (!Object.keys(state.counts || {}).length) {
              syncCountsFromPreview();
            }
            state.mode = "manual";
            paintModal();
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
    var applyBlocked = busy || (countsNeedBalance() && countMath().left !== 0);
    foot.appendChild(
      el("button", {
        type: "button",
        className: "a7-ta-primary",
        text: busy ? "Working…" : "Apply",
        disabled: applyBlocked ? "disabled" : null,
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
      fetch(ENDPOINT, { method: "POST", body: body, credentials: "same-origin", cache: "no-store" })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          if (!data || !data.ok) {
            return;
          }
          if (!data.done) {
            return;
          }
          // busy is not this poll's to release: Apply already did, and by now it may
          // belong to a newer opening of the modal.
          window.clearInterval(jobPollTimer);
          jobPollTimer = 0;
          var msg =
            "Assign finished: " +
            (data.updated || 0) +
            " / " +
            (data.total || 0) +
            (data.failed ? " · " + data.failed + " failed" : "");
          notify(msg, !data.failed);
          if (!data.failed) {
            reloadListSoon();
          }
        })
        .catch(function () {});
    }
    tick();
    jobPollTimer = window.setInterval(tick, 4000);
  }

  function applyNow() {
    if (busy) {
      return;
    }
    var count = selectedCount();
    if (state.resolveError) {
      return;
    }
    if (!count && !state.deferredForAll) {
      notify("Select at least one card.", false);
      return;
    }
    // For all reaches past the page: make the number the person is about to move explicit.
    if (
      state.forAll &&
      !window.confirm(
        "Assign ALL " + count + " " + noun() + " that match the list filter — every page, not only the rows on screen?"
      )
    ) {
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
    state.message = "Queuing background assign…";
    paintModal();
    post("apply")
      .then(function (data) {
        // Always prefer background: user must not wait on this screen.
        if (data.background && data.job_id) {
          busy = false;
          var bgMsg =
            "Background assign started for " +
            (data.total || count) +
            " " +
            noun() +
            ". You can leave — it keeps running.";
          notify(bgMsg, true);
          try {
            closeModal();
          } catch (eClose) {}
          pollJob(data.job_id);
          return;
        }
        // Fallback inline (should be rare) — still finish without trapping the user.
        busy = false;
        var msg =
          "Assigned " +
          (data.updated || 0) +
          " " +
          noun() +
          (data.failed ? " · " + data.failed + " failed" : "") +
          (data.skipped ? " · " + data.skipped + " skipped" : "");
        notify(msg, !data.failed);
        try {
          closeModal();
        } catch (eClose2) {}
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
    notify(isForAllChecked() ? "Finding every card that matches the list filter…" : "Opening assign…", true);

    function show() {
      if (!meta) {
        return;
      }
      if (!state.scope) {
        state.scope = "all";
      }
      // closeModal clears selection state — keep it across overlay recreate.
      var keepIds = state.resolvedIds;
      var keepTotal = state.resolvedTotal;
      var keepForAll = state.forAll;
      var keepDeferred = state.deferredForAll;
      var keepGrid = state.gridId;
      var keepCtx = state.forAllCtx;
      var keepResolveError = state.resolveError;
      var keepWarning = state.filterWarning;
      if (overlay) {
        closeModal();
      }
      state.resolvedIds = keepIds;
      state.resolvedTotal = keepTotal;
      state.forAll = keepForAll;
      state.deferredForAll = keepDeferred;
      state.gridId = keepGrid;
      state.forAllCtx = keepCtx;
      state.resolveError = keepResolveError;
      state.filterWarning = keepWarning;
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
        resetChoices();
        show();
      }, function (err) {
        if (err && err.message === "superseded") {
          return;
        }
        busy = false;
        if (!state.forAll) {
          throw err;
        }
        // A For all that cannot be resolved is shown, not swallowed into a toast —
        // and never replaced by the rows ticked on the page.
        state.resolveError = (err && err.message) || "FOR ALL could not read this list's filter.";
        state.resolvedIds = [];
        state.resolvedTotal = 0;
        resetChoices();
        show();
      });
    }

    function resetChoices() {
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

    // Stamp the filter each time this tab's grid is drawn: once the first page is up, and
    // after every reload (filter, sort, page) — even one that leaves the same rows showing.
    var stampTimer = 0;
    function restamp(force) {
      window.clearTimeout(stampTimer);
      stampTimer = window.setTimeout(function () {
        if (force) {
          drawn.rows = "";
        }
        stampDrawnGrid();
      }, 300);
    }
    var firstTries = 0;
    (function stampFirstDraw() {
      if (rowsSignature()) {
        restamp(false);
      } else if ((firstTries += 1) < 20) {
        window.setTimeout(stampFirstDraw, 500);
      }
    })();
    try {
      if (window.BX && typeof BX.addCustomEvent === "function") {
        BX.addCustomEvent(window, "Grid::updated", function () {
          restamp(true);
        });
      }
    } catch (e3) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
