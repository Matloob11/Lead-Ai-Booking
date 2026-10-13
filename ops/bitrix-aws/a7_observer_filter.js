(function () {
  "use strict";

  var TOKEN = "all-agents";
  var LABEL = "All agents";
  var SUB = "Leads with any observer";
  var TOKEN_SHARED = "shared-leads";
  var LABEL_SHARED = "Shared leads";
  var SUB_SHARED = "Leads with the Shared tag";

  function tokenOptions() {
    return {
      id: TOKEN,
      entityId: "user",
      title: LABEL,
      subtitle: SUB,
      tabs: "recents",
      searchable: true,
      saveable: false,
      avatarOptions: { bgColor: "#2fc6f6", bgSize: "cover" },
      customData: { a7AllAgents: true },
    };
  }

  function sharedTokenOptions() {
    return {
      id: TOKEN_SHARED,
      entityId: "user",
      title: LABEL_SHARED,
      subtitle: SUB_SHARED,
      tabs: "recents",
      searchable: true,
      saveable: false,
      avatarOptions: { bgColor: "#9dcf00", bgSize: "cover" },
      customData: { a7SharedLeads: true },
    };
  }

  function looksObserverDialog(dialog) {
    if (!dialog) return false;
    var blob = "";
    try {
      blob += " " + (dialog.getId ? dialog.getId() : dialog.id || "");
      blob += " " + (dialog.context || "");
      var ents = dialog.getEntities ? dialog.getEntities() : [];
      blob += " " + JSON.stringify(ents).slice(0, 400);
    } catch (e) {}
    try {
      var target = dialog.getTargetNode ? dialog.getTargetNode() : null;
      if (target) blob += " " + (target.id || "") + " " + (target.className || "");
    } catch (e2) {}
    blob = blob.toLowerCase();
    return blob.indexOf("observer") !== -1;
  }

  function ensureToken(dialog) {
    if (!dialog || !dialog.addItem) return null;
    var existing = null;
    try {
      existing = dialog.getItem({ id: TOKEN, entityId: "user" });
    } catch (e) {
      existing = null;
    }
    if (!existing) {
      try {
        existing = dialog.addItem(tokenOptions());
      } catch (e2) {}
    }
    try {
      if (!dialog.getItem({ id: TOKEN_SHARED, entityId: "user" })) {
        dialog.addItem(sharedTokenOptions());
      }
    } catch (e3) {}
    return existing;
  }

  function wrapDialog() {
    if (!window.BX || !BX.UI || !BX.UI.EntitySelector || !BX.UI.EntitySelector.Dialog) return false;
    var Proto = BX.UI.EntitySelector.Dialog.prototype;
    if (Proto.__a7ObsWrapped) return true;
    Proto.__a7ObsWrapped = true;

    var origShow = Proto.show;
    Proto.show = function () {
      if (looksObserverDialog(this)) {
        ensureToken(this);
      }
      var ret = origShow.apply(this, arguments);
      if (looksObserverDialog(this)) {
        var self = this;
        setTimeout(function () {
          ensureToken(self);
        }, 50);
        setTimeout(function () {
          ensureToken(self);
        }, 300);
      }
      return ret;
    };

    var origLoad = Proto.load;
    if (origLoad) {
      Proto.load = function () {
        var ret = origLoad.apply(this, arguments);
        if (looksObserverDialog(this)) ensureToken(this);
        return ret;
      };
    }
    return true;
  }

  function injectFallbackRow() {
    var popups = document.querySelectorAll(".ui-selector-dialog, .popup-window");
    for (var i = 0; i < popups.length; i++) {
      var root = popups[i];
      var text = (root.textContent || "").toLowerCase();
      if (text.indexOf("asma") === -1 && text.indexOf("observer") === -1 && text.indexOf("neha") === -1) {
        continue;
      }
      if (root.querySelector("[data-a7-all-agents]") && root.querySelector("[data-a7-shared-leads]")) continue;
      var list = root.querySelector(".ui-selector-items, .ui-selector-search-tab-content");
      if (!list) continue;
      function addRow(key, text, bg, token) {
        if (root.querySelector("[data-" + key + "]")) return;
        var row = document.createElement("div");
        row.className = "ui-selector-item";
        row.setAttribute("data-" + key, "1");
        row.style.cssText = "display:flex;align-items:center;gap:10px;padding:8px 12px;cursor:pointer;";
        var av = document.createElement("span");
        av.style.cssText =
          "width:28px;height:28px;border-radius:50%;background:" +
          bg +
          ";color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex:none;";
        av.textContent = text === LABEL ? "AA" : "SH";
        var title = document.createElement("span");
        title.textContent = text;
        title.style.fontSize = "14px";
        row.appendChild(av);
        row.appendChild(title);
        row.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          selectOpenDialog(token);
          try {
            row.style.background = "#e9f7fc";
          } catch (e3) {}
        });
        list.insertBefore(row, list.firstChild);
      }
      addRow("a7-shared-leads", LABEL_SHARED, "#9dcf00", TOKEN_SHARED);
      addRow("a7-all-agents", LABEL, "#2fc6f6", TOKEN);
    }
  }

  function selectOpenDialog(token) {
    token = token || TOKEN;
    try {
      var list = BX.UI.EntitySelector.Dialog.getInstances
        ? BX.UI.EntitySelector.Dialog.getInstances()
        : [];
      for (var i = 0; i < list.length; i++) {
        var d = list[i];
        if (!looksObserverDialog(d) && list.length > 1) continue;
        var item = null;
        try {
          item = d.getItem({ id: token, entityId: "user" });
        } catch (e0) {}
        if (!item && d.addItem) {
          item = d.addItem(token === TOKEN_SHARED ? sharedTokenOptions() : tokenOptions());
        }
        if (item && item.select) item.select();
        else if (d.selectItem) d.selectItem({ id: token, entityId: "user" });
      }
    } catch (e) {}
  }

  var tries = 0;
  function boot() {
    tries += 1;
    wrapDialog();
    if (tries < 40) setTimeout(boot, 250);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  document.addEventListener(
    "click",
    function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var field = t.closest(".main-ui-control-entity-selector, .main-ui-square-container, .ui-tag-selector-outer-container");
      var txt = "";
      try {
        var wrap = t.closest(".main-ui-filter-field, .main-ui-control-field");
        txt = wrap ? wrap.textContent || "" : "";
      } catch (e) {}
      if (!/observer/i.test(txt) && !(field && /observer/i.test((field.id || "") + (field.className || "")))) {
        return;
      }
      setTimeout(function () {
        wrapDialog();
        try {
          var inst = BX.UI.EntitySelector.Dialog.getInstances
            ? BX.UI.EntitySelector.Dialog.getInstances()
            : [];
          inst.forEach(function (d) {
            if (looksObserverDialog(d) || inst.length === 1) ensureToken(d);
          });
        } catch (e2) {}
        injectFallbackRow();
      }, 80);
      setTimeout(injectFallbackRow, 280);
    },
    true
  );
})();
