/**
 * Renewals (deal category 9) WhatsApp campaign.
 * Tick deals, then send a tenant template and an owner template
 * from one Official number. Same phone on both sides → owner only.
 * A template with an image, video or document header asks for that file;
 * it goes up through a7_lead_wa.php for the chosen number before anything
 * is queued, and each side keeps its own file.
 * The "Lead AI" box sends the chats this campaign reaches to the Lead AI
 * screen of the WhatsApp panel instead of the main inbox.
 */
(function () {
  if (window.A7_RENEWALS_WA_V6) {
    return;
  }
  window.A7_RENEWALS_WA_V6 = true;

  var DETAIL_FIELDS = [
    ["name", "Name"],
    ["phone", "Phone"],
    ["source", "Source"],
    ["stage", "Stage"],
    ["community", "Community"],
    ["sub_community", "Sub community"],
    ["bedrooms", "Bedrooms"],
    ["client_type", "Client type"],
    ["deal_amount", "Deal amount"],
    ["property_reference", "Property reference"]
  ];

  var PATH = String(location.pathname || "");
  if (!/^\/crm\/deal\/(?:kanban\/|list\/)?category\/9(?:\/|$)/i.test(PATH)) {
    return;
  }
  if (/\/crm\/deal\/details\//i.test(PATH)) {
    return;
  }

  var ENDPOINT = "/bitrix/tools/a7_renewals_wa.php";
  // Header files go through the Leads tool: one upload route for every popup.
  var UPLOAD_ENDPOINT = "/bitrix/tools/a7_lead_wa.php";
  var FETCH_MS = 20000;
  var UPLOAD_MS = 15 * 60 * 1000;
  var STYLE_ID = "a7-rwa-style-v5";
  var BTN_CLASS = "a7-rwa-btn";
  var SLOT_CLASS = "a7-rwa-slot";
  var MAX_DEALS = 500;
  var MB = 1024 * 1024;
  // What WhatsApp takes for a header of each kind; the inbox checks again.
  var MEDIA = {
    IMAGE: {
      word: "image",
      accept: "image/jpeg,image/png,image/webp,image/gif,image/bmp,.jpg,.jpeg,.png,.webp,.gif,.bmp",
      exts: ["jpg", "jpeg", "png"],
      limit: 5 * MB,
      hint: "JPEG or PNG, up to 5 MB"
    },
    VIDEO: {
      word: "video",
      accept: "video/mp4,video/3gpp,.mp4,.3gp",
      exts: ["mp4", "3gp", "3gpp"],
      limit: 16 * MB,
      hint: "MP4 or 3GP, up to 16 MB"
    },
    // Meta takes only PDF for a template's document header.
    DOCUMENT: {
      word: "document",
      accept: "application/pdf,.pdf",
      exts: ["pdf"],
      limit: 100 * MB,
      hint: "PDF, up to 100 MB"
    }
  };
  var overlay = null;
  var busy = false;
  var prevOverflow = "";
  // Set while a popup is open: stops its uploads and frees its previews.
  var studioCleanup = null;

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
      console[ok === false ? "warn" : "log"]("[A7 Renewals WA]", message);
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
      ids.push(checked[k].getAttribute("data-id") || checked[k].getAttribute("data-row-id") || "");
    }
    return uniqueIds(ids);
  }

  function selectedKanbanIds() {
    var ids = [];
    try {
      var Kanban = window.BX && BX.CRM && BX.CRM.Kanban && BX.CRM.Kanban.Grid;
      var inst =
        Kanban &&
        ((typeof Kanban.getInstance === "function" && Kanban.getInstance()) || Kanban.Instance);
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
      ids.push(cards[c].getAttribute("data-id") || cards[c].getAttribute("data-item-id") || "");
    }
    var boxes = document.querySelectorAll(
      ".crm-kanban-item input[type=checkbox]:checked, .main-kanban-item input[type=checkbox]:checked"
    );
    for (var b = 0; b < boxes.length; b += 1) {
      var card = boxes[b].closest ? boxes[b].closest(".crm-kanban-item, .main-kanban-item") : null;
      if (card) {
        ids.push(card.getAttribute("data-id") || card.getAttribute("data-item-id") || "");
      }
    }
    return uniqueIds(ids);
  }

  function selectedDealIds() {
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

  // fetch() cannot report upload progress, and a video takes long enough
  // that a frozen popup reads as a hang.
  function xhrUpload(url, form, onProgress) {
    var xhr = new XMLHttpRequest();
    var promise = new Promise(function (resolve, reject) {
      xhr.open("POST", url, true);
      xhr.withCredentials = true;
      xhr.timeout = UPLOAD_MS;
      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = function (ev) {
          if (ev.lengthComputable && ev.total > 0) {
            onProgress(ev.loaded / ev.total);
          }
        };
      }
      xhr.onload = function () {
        resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, text: xhr.responseText || "" });
      };
      xhr.onerror = function () {
        reject(new Error("The upload did not reach Bitrix. Check the connection and try again."));
      };
      xhr.ontimeout = function () {
        reject(new Error("The upload took too long. Try a smaller file."));
      };
      xhr.onabort = function () {
        reject(new Error("Upload cancelled."));
      };
      xhr.send(form);
    });
    return {
      promise: promise,
      abort: function () {
        try {
          xhr.abort();
        } catch (ignored) {}
      }
    };
  }

  function formatBytes(n) {
    n = Number(n || 0);
    if (n >= MB) {
      // Two decimals under 10 MB, so 5.01 MB never prints as the 5 MB it exceeds.
      return (n / MB).toFixed(n >= 10 * MB ? 1 : 2) + " MB";
    }
    if (n >= 1024) {
      return Math.round(n / 1024) + " KB";
    }
    return n + " B";
  }

  function imageAsJpeg(file) {
    return new Promise(function (resolve, reject) {
      var url = window.URL && URL.createObjectURL ? URL.createObjectURL(file) : "";
      if (!url) {
        reject(new Error("This browser cannot read that image. Save it as a JPEG and try again."));
        return;
      }
      var img = new Image();
      img.onload = function () {
        try {
          URL.revokeObjectURL(url);
        } catch (ignored) {}
        var w = img.naturalWidth || img.width || 1;
        var h = img.naturalHeight || img.height || 1;
        var maxW = 1600;
        if (w > maxW) {
          h = Math.max(1, Math.round(h * maxW / w));
          w = maxW;
        }
        var canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        var ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error("This browser cannot prepare that image. Save it as a JPEG and try again."));
          return;
        }
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, w, h);
        ctx.drawImage(img, 0, 0, w, h);
        function finish(quality) {
          canvas.toBlob(function (blob) {
            if (!blob) {
              reject(new Error("Could not read that image. Save it as a JPEG and try again."));
              return;
            }
            if (blob.size > 5 * MB && quality > 0.5) {
              finish(Math.round((quality - 0.15) * 100) / 100);
              return;
            }
            if (blob.size > 5 * MB) {
              reject(new Error("That image is still over 5 MB after compressing. Use a smaller picture."));
              return;
            }
            var base = String(file.name || "header").replace(/\.[^.]+$/, "") || "header";
            resolve(new File([blob], base + ".jpg", { type: "image/jpeg" }));
          }, "image/jpeg", quality);
        }
        finish(0.9);
      };
      img.onerror = function () {
        try {
          URL.revokeObjectURL(url);
        } catch (ignored) {}
        reject(new Error("That file is not a picture this browser can open. Save it as a JPEG or PNG and try again."));
      };
      img.src = url;
    });
  }

  function fileProblem(file, kind) {
    var rule = MEDIA[kind];
    if (!rule || !file) {
      return "Choose a file.";
    }
    var ext = String(file.name || "").toLowerCase().split(".").pop();
    if (rule.exts.indexOf(ext) === -1) {
      return "This " + rule.word + " header takes " + rule.hint + ".";
    }
    if (!file.size) {
      return "That file is empty.";
    }
    if (file.size > rule.limit) {
      return "That file is " + formatBytes(file.size) + ". This " + rule.word + " header takes " + rule.hint + ".";
    }
    return "";
  }

  function templateMediaKind(t) {
    var kind = t && t.requires_header_media && t.header ? String(t.header.format || "").toUpperCase() : "";
    return MEDIA[kind] ? kind : "";
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (key) {
      if (key === "className") {
        node.className = attrs[key];
      } else if (key === "text") {
        node.textContent = attrs[key];
      } else if (key === "title") {
        node.title = attrs[key];
      } else if (key === "type") {
        node.type = attrs[key];
      } else {
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

  function icon(name) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "a7-rwa-ic");
    svg.setAttribute("fill", "none");
    svg.setAttribute("aria-hidden", "true");
    var shapes = {
      image: ["M4 5h16v14H4z", "M4 17l5-5 4 4 2.5-2.5L20 17", "M9 8.4a1.6 1.6 0 110 3.2 1.6 1.6 0 010-3.2z"],
      video: ["M3 6h12v12H3z", "M15 10l6-3v10l-6-3z"],
      doc: ["M7 3h7l5 5v13H7z", "M14 3v5h5"]
    };
    if (shapes[name]) {
      svg.setAttribute("stroke", "currentColor");
      svg.setAttribute("stroke-width", "1.8");
      svg.setAttribute("stroke-linecap", "round");
      svg.setAttribute("stroke-linejoin", "round");
      shapes[name].forEach(function (d) {
        var line = document.createElementNS(ns, "path");
        line.setAttribute("d", d);
        svg.appendChild(line);
      });
      return svg;
    }
    var path = document.createElementNS(ns, "path");
    if (name === "close") {
      svg.setAttribute("stroke", "currentColor");
      svg.setAttribute("stroke-width", "1.8");
      path.setAttribute("d", "M6 6l12 12M18 6L6 18");
    } else {
      path.setAttribute("fill", "currentColor");
      path.setAttribute(
        "d",
        "M12 2a10 10 0 00-8.7 14.9L2 22l5.3-1.4A10 10 0 1012 2zm5.1 14.3c-.3.7-1.5 1.3-2.1 1.3-.5 0-1.1.2-3.6-.8-3.1-1.3-5.1-4.5-5.2-4.7-.2-.2-1.3-1.7-1.3-3.3 0-1.5.8-2.3 1.1-2.6.3-.3.6-.4.8-.4h.6c.2 0 .4 0 .6.5.2.5.8 1.9.8 2 0 .2 0 .4-.2.6l-.4.5c-.1.2-.3.3 0 .6.2.3.9 1.5 2 2.5 1.4 1.3 2.5 1.7 2.8 1.9.3.1.5.1.7-.1l.8-1c.2-.2.4-.2.7-.1.3 0 1.8.8 2.1 1 .3.1.5.2.6.4.1.3 0 .8-.3 1.4z"
      );
    }
    svg.appendChild(path);
    return svg;
  }

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = [
      "." + SLOT_CLASS + "{display:inline-flex !important;align-items:center;margin:0 8px;padding:3px;background:#fff;border:1px solid #d0d7de;border-radius:10px;box-shadow:0 1px 2px rgba(16,185,129,.12);vertical-align:middle;}",
      "." + BTN_CLASS + "{background:#fff !important;color:#334155 !important;border:1px solid #cbd5e1 !important;border-radius:8px;padding:0 12px;height:32px;font:600 13px/1 Segoe UI,Arial,sans-serif !important;cursor:pointer;white-space:nowrap;display:inline-flex !important;align-items:center;gap:7px;}",
      "." + BTN_CLASS + ":hover{background:#f0fdf4 !important;}",
      "." + BTN_CLASS + " .a7-rwa-ic{width:16px;height:16px;color:#25D366;}",
      ".a7-rwa-overlay,.a7-rwa-overlay *{box-sizing:border-box;letter-spacing:normal !important;font-stretch:normal !important;font-family:Segoe UI,Arial,sans-serif !important;}",
      ".a7-rwa-overlay{position:fixed;inset:0;z-index:30000;background:rgba(15,23,42,.48);display:flex;align-items:center;justify-content:center;padding:20px;color:#0f172a;}",
      ".a7-rwa-modal{width:min(1180px,100%);height:min(92vh,860px);background:#fff;border:1px solid #e2e8f0;border-radius:16px;box-shadow:0 24px 60px rgba(15,23,42,.28);display:flex;flex-direction:column;overflow:hidden;}",
      ".a7-rwa-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:16px 18px 10px;}",
      ".a7-rwa-brand{display:flex;gap:10px;align-items:flex-start;min-width:0;}",
      ".a7-rwa-brand h2{margin:0;font-size:18px;font-weight:700;color:#14532d;}",
      ".a7-rwa-sub{margin-top:3px;color:#475569;font-size:13px;line-height:1.35;}",
      ".a7-rwa-ic{width:18px;height:18px;display:block;color:#128C7E;margin-top:2px;}",
      ".a7-rwa-x{border:1px solid #e2e8f0;background:#fff;border-radius:10px;width:34px;height:34px;padding:0;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;color:#64748b;}",
      ".a7-rwa-x:hover{background:#f8fafc;}",
      ".a7-rwa-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0 18px 14px;border-bottom:1px solid #e2e8f0;}",
      ".a7-rwa-stat{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;min-width:0;}",
      ".a7-rwa-stat b{display:block;font-size:22px;line-height:1.1;font-weight:700;color:#0f172a;}",
      ".a7-rwa-stat span{display:block;margin-top:2px;font-size:12px;font-weight:650;color:#64748b;}",
      ".a7-rwa-stat small{display:block;margin-top:2px;font-size:11px;color:#64748b;}",
      ".a7-rwa-stat.is-warn{background:#fff7ed;border-color:#fdba74;}",
      ".a7-rwa-stat.is-warn b,.a7-rwa-stat.is-warn small{color:#c2410c;}",
      ".a7-rwa-stat.is-ok b{color:#166534;}",
      ".a7-rwa-grid{flex:1;min-height:0;display:grid;grid-template-columns:320px minmax(220px,1fr) minmax(220px,1fr) 250px;gap:14px;padding:14px 16px;overflow:hidden;}",
      ".a7-rwa-col,.a7-rwa-side{min-width:0;min-height:0;display:flex;flex-direction:column;gap:8px;overflow:hidden;}",
      ".a7-rwa-col{overflow-y:auto;}",
      ".a7-rwa-modal h3{margin:0;font-size:12px;font-weight:700;color:#64748b;}",
      ".a7-rwa-input{width:100%;border:1px solid #cbd5e1 !important;border-radius:10px;padding:8px 10px;font-size:13px !important;background:#fff !important;color:#0f172a !important;}",
      ".a7-rwa-input:focus{outline:none;border-color:#128C7E !important;box-shadow:0 0 0 3px rgba(18,140,126,.16);}",
      ".a7-rwa-from{display:flex;flex-direction:column;gap:8px;flex:0 0 auto;}",
      ".a7-rwa-picked{display:flex;align-items:center;justify-content:space-between;gap:8px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:8px 10px;}",
      ".a7-rwa-picked b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:700;}",
      ".a7-rwa-picked span{flex:0 0 auto;font-variant-numeric:tabular-nums;color:#166534;font-weight:700;font-size:12px;}",
      ".a7-rwa-num-list{max-height:132px;overflow:auto;border:1px solid #e2e8f0;border-radius:10px;background:#fff;}",
      ".a7-rwa-num{display:flex;width:100%;align-items:center;justify-content:space-between;gap:8px;border:0;border-bottom:1px solid #f1f5f9;background:#fff !important;color:#0f172a !important;padding:8px 10px;cursor:pointer;text-align:left;font:600 13px/1.3 Segoe UI,Arial,sans-serif !important;}",
      ".a7-rwa-num:hover{background:#f8fafc !important;}",
      ".a7-rwa-num.is-on{background:#ecfdf5 !important;box-shadow:inset 3px 0 0 #16a34a;}",
      ".a7-rwa-num b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:650;}",
      ".a7-rwa-num span{flex:0 0 auto;font-variant-numeric:tabular-nums;color:#0f766e;font-size:12px;font-weight:700;}",
      ".a7-rwa-people{flex:1;min-height:0;overflow:auto;border:1px solid #e2e8f0;border-radius:12px;background:#fff;padding:4px 6px;}",
      ".a7-rwa-deal{padding:4px 0;border-bottom:1px solid #f1f5f9;}",
      ".a7-rwa-deal:last-child{border-bottom:0;}",
      ".a7-rwa-line{display:grid;grid-template-columns:52px minmax(0,1fr) auto;gap:8px;align-items:center;padding:5px 6px;}",
      ".a7-rwa-role{font-size:10px;font-weight:700;color:#64748b;}",
      ".a7-rwa-line b{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;font-weight:650;}",
      ".a7-rwa-badge{font-size:11px;font-weight:700;border-radius:99px;padding:2px 8px;white-space:nowrap;}",
      ".a7-rwa-badge.is-miss{background:#ffedd5;color:#c2410c;}",
      ".a7-rwa-badge.is-ok{background:#dcfce7;color:#166534;}",
      ".a7-rwa-badge.is-same{background:#e0f2fe;color:#075985;}",
      ".a7-rwa-badge.is-dup{background:#f1f5f9;color:#475569;}",
      ".a7-rwa-list{flex:1;min-height:120px;overflow:auto;border:1px solid #e2e8f0;border-radius:10px;padding:4px;background:#fff;}",
      ".a7-rwa-item{display:block;width:100%;text-align:left;border:0;background:#fff !important;color:#0f172a !important;border-radius:8px;padding:8px 10px;cursor:pointer;font:600 13px/1.3 Segoe UI,Arial,sans-serif !important;}",
      ".a7-rwa-item div{font-size:13px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
      ".a7-rwa-item small{display:block;color:#64748b;font-size:11px;font-weight:600;}",
      ".a7-rwa-item.is-on{background:#ecfdf5 !important;box-shadow:inset 3px 0 0 #16a34a;}",
      ".a7-rwa-item.is-off{cursor:default;opacity:.65;}",
      ".a7-rwa-chips{display:flex;flex-wrap:wrap;gap:6px;}",
      ".a7-rwa-chip{border:1px solid #e2e8f0 !important;background:#fff !important;color:#334155 !important;border-radius:99px;padding:4px 10px;font:700 12px/1 Segoe UI,Arial,sans-serif !important;cursor:pointer;}",
      ".a7-rwa-chip.is-on{background:#166534 !important;color:#fff !important;border-color:#166534 !important;}",
      ".a7-rwa-note{font-size:12px;color:#92400e;background:#fffbeb;border-radius:10px;padding:8px 10px;}",
      ".a7-rwa-err{font-size:12px;color:#b91c1c;min-height:0;}",
      ".a7-rwa-empty{padding:12px 10px;color:#64748b;font-size:12px;}",
      ".a7-rwa-phone{flex:1;min-height:220px;border:8px solid #e2e8f0;border-radius:28px;background:#efeae2;overflow:hidden;display:flex;flex-direction:column;}",
      ".a7-rwa-phone-bar{background:#075e54;color:#fff;padding:10px 12px;font-size:13px;font-weight:700;}",
      ".a7-rwa-phone-bar small{display:block;margin-top:2px;font-size:11px;font-weight:500;opacity:.9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
      ".a7-rwa-screen{flex:1;min-height:0;overflow:auto;padding:12px;font-size:13px;white-space:pre-wrap;}",
      ".a7-rwa-bubble{background:#fff;border-radius:12px;padding:10px 12px;line-height:1.4;}",
      ".a7-rwa-footbar{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px 16px;border-top:1px solid #e2e8f0;background:#fff;}",
      ".a7-rwa-footbar .a7-rwa-sub{max-width:620px;margin:0;}",
      ".a7-rwa-actions{display:flex;gap:8px;flex:0 0 auto;align-items:center;}",
      ".a7-rwa-leadai{display:inline-flex;align-items:center;gap:6px;height:36px;border:1px solid #cbd5e1;border-radius:10px;padding:0 12px;font:700 13px/1 Segoe UI,Arial,sans-serif !important;color:#334155;cursor:pointer;user-select:none;background:#fff;white-space:nowrap;}",
      ".a7-rwa-leadai:hover{background:#f8fafc;}",
      ".a7-rwa-leadai.is-on{border-color:#7c3aed;background:#f5f3ff;color:#5b21b6;}",
      ".a7-rwa-leadai input{margin:0;width:15px;height:15px;accent-color:#7c3aed;cursor:pointer;}",
      ".a7-rwa-scriptwrap{display:inline-flex;align-items:center;gap:6px;height:36px;border:1px solid #ddd6fe;border-radius:10px;padding:0 8px;font:700 13px/1 Segoe UI,Arial,sans-serif !important;color:#5b21b6;background:#f5f3ff;}",
      ".a7-rwa-scriptwrap span{white-space:nowrap;}",
      ".a7-rwa-script{border:1px solid #c4b5fd;border-radius:6px;padding:4px 6px;font:600 13px/1.2 Segoe UI,Arial,sans-serif !important;color:#1e1b4b;background:#fff;max-width:220px;}",
      ".a7-rwa-cancel,.a7-rwa-send{height:36px;border-radius:10px;padding:0 14px;cursor:pointer;font:700 13px/1 Segoe UI,Arial,sans-serif !important;}",
      ".a7-rwa-cancel{background:#fff !important;color:#334155 !important;border:1px solid #cbd5e1 !important;}",
      ".a7-rwa-send{background:#166534 !important;color:#fff !important;border:0;}",
      ".a7-rwa-send:disabled{opacity:.55;cursor:not-allowed;}",
      ".a7-rwa-media{flex:0 0 auto;border:1px dashed #94a3b8;border-radius:10px;padding:8px 10px;background:#f8fafc;display:flex;flex-direction:column;gap:6px;}",
      ".a7-rwa-media.is-ready{border-style:solid;border-color:#86efac;background:#f0fdf4;}",
      ".a7-rwa-media.is-bad{border-color:#fca5a5;background:#fef2f2;}",
      ".a7-rwa-media-label{font-size:12px;font-weight:700;color:#475569;}",
      ".a7-rwa-media-row{display:flex;align-items:center;gap:8px;min-width:0;}",
      ".a7-rwa-media-pick{background:#fff !important;border:1px solid #cbd5e1 !important;border-radius:8px;padding:6px 10px;font:600 12px/1.2 Segoe UI,Arial,sans-serif !important;cursor:pointer;color:#334155 !important;display:inline-flex;align-items:center;gap:6px;flex:0 0 auto;}",
      ".a7-rwa-media-pick:hover{background:#f0fdf4 !important;}",
      ".a7-rwa-media-pick .a7-rwa-ic,.a7-rwa-hmedia .a7-rwa-ic{width:14px;height:14px;margin:0;}",
      ".a7-rwa-media-status{min-width:0;flex:1;font-size:12px;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
      ".a7-rwa-media.is-ready .a7-rwa-media-status{color:#166534;font-weight:600;}",
      ".a7-rwa-media.is-bad .a7-rwa-media-status{color:#b91c1c;white-space:normal;}",
      ".a7-rwa-media-bar{height:4px;border-radius:99px;background:#e2e8f0;overflow:hidden;}",
      ".a7-rwa-media-bar b{display:block;height:100%;width:0;background:#25D366;transition:width .2s;}",
      ".a7-rwa-media-hint{font-size:11px;color:#64748b;}",
      ".a7-rwa-tag{display:inline-block;margin-left:4px;padding:0 5px;border-radius:4px;background:#e0f2fe;color:#075985;font-size:10px;font-weight:700;}",
      ".a7-rwa-hmedia{margin:-10px -12px 8px;border-radius:12px 12px 0 0;overflow:hidden;background:#cfd8dc;white-space:normal;}",
      ".a7-rwa-hmedia img,.a7-rwa-hmedia video{display:block;width:100%;max-height:180px;object-fit:cover;background:#0f172a;}",
      ".a7-rwa-hmedia-ph{display:flex;align-items:center;justify-content:center;gap:6px;min-height:90px;color:#475569;font-size:12px;font-weight:600;padding:8px;text-align:center;}",
      ".a7-rwa-hmedia-ph.is-missing{background:repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0 6px,#f1f5f9 6px,#f1f5f9 12px);color:#64748b;}",
      ".a7-rwa-hmedia-doc{display:flex;align-items:center;gap:6px;background:#f1f5f9;padding:10px;font-size:12px;color:#334155;white-space:nowrap;}",
      ".a7-rwa-hmedia-doc span{overflow:hidden;text-overflow:ellipsis;}",
      "@media (max-width:1080px){.a7-rwa-grid{grid-template-columns:1fr;overflow:auto;}.a7-rwa-modal{height:min(96vh,920px);}.a7-rwa-people{max-height:240px;}.a7-rwa-stats{grid-template-columns:1fr;}}"
    ].join("");
    document.head.appendChild(style);
  }

  function closeStudio() {
    if (studioCleanup) {
      try {
        studioCleanup();
      } catch (ignored) {}
      studioCleanup = null;
    }
    if (overlay && overlay.parentNode) {
      overlay.parentNode.removeChild(overlay);
    }
    overlay = null;
    document.body.style.overflow = prevOverflow;
    document.removeEventListener("keydown", onEsc);
  }

  function onEsc(ev) {
    if (ev.key === "Escape") {
      closeStudio();
    }
  }

  function numberLabel(n) {
    if (!n) {
      return "Official number";
    }
    var title = n.title || n.display_name || n.label || n.account_username || "Official number";
    var phone = n.phone_number ? "+" + n.phone_number : "";
    return phone ? title + " · " + phone : title;
  }

  function fillVars(text, vars) {
    return String(text || "").replace(/\{\{(\d+)\}\}/g, function (_, n) {
      return vars[n] != null && vars[n] !== "" ? vars[n] : "{{" + n + "}}";
    });
  }

  function stateText(state, tail) {
    if (state === "send") {
      return "…" + (tail || "");
    }
    if (state === "same") {
      return "Same as owner";
    }
    if (state === "duplicate") {
      return "Duplicate";
    }
    if (state === "opted_out") {
      return "Opted out";
    }
    return "No phone";
  }

    function leftOutNote(data) {
      var rows = data && data.skipped;
      if (!rows || !rows.length) {
        return "";
      }
      var labels = [
        ["Opted out.", "opted out"],
        ["Broker.", "broker"],
        ["Lost.", "lost"],
        ["Sent this template in the last 30 days.", "already sent"]
      ];
      var counts = {};
      rows.forEach(function (row) {
        var reason = row && row.reason ? String(row.reason) : "";
        labels.forEach(function (pair) {
          if (reason === pair[0]) {
            counts[pair[0]] = (counts[pair[0]] || 0) + 1;
          }
        });
      });
      var parts = [];
      var total = 0;
      labels.forEach(function (pair) {
        var n = counts[pair[0]] || 0;
        if (n) {
          total += n;
          parts.push(pair[1] + " " + n);
        }
      });
      return total ? total + " left out: " + parts.join(", ") + "." : "";
    }

    function openStudio(dealIds, context) {
    ensureStyles();
    closeStudio();
    var preview = context.preview || {};
    var rows = preview.rows || [];
    var templates = context.templates || [];
    var numbers = context.numbers && context.numbers.length ? context.numbers : context.number ? [context.number] : [];
    var cap = Number(preview.cap || 300);
    var total = Number(preview.total || 0);
    var over = !!preview.over_cap || total > cap;
    var tenantCount = Number(preview.tenant_messages || 0);
    var ownerCount = Number(preview.owner_messages || 0);
    var sub = el("div", { className: "a7-rwa-sub" });
    var err = el("div", { className: "a7-rwa-err" });
    var note = el("div", { className: "a7-rwa-note" });
    var phoneChat = el("div", { className: "a7-rwa-screen" });
    var phoneHead = el("div", { className: "a7-rwa-phone-bar" });
    var previewRole = tenantCount ? "tenant" : "owner";

    var selectedNumberId = numbers.length ? String(numbers[0].id) : "";

    function countMissing() {
      var tenant = 0;
      var owner = 0;
      for (var i = 0; i < rows.length; i += 1) {
        if (rows[i].tenant_state === "missing") {
          tenant += 1;
        }
        if (rows[i].owner_state === "missing") {
          owner += 1;
        }
      }
      return { tenant: tenant, owner: owner, people: tenant + owner };
    }

    var missing = countMissing();

    function countWord(n, word) {
      return n + " " + word + (Number(n) === 1 ? "" : "s");
    }

    function missingSentence() {
      if (!missing.people) {
        return "No one in this selection is missing a phone number.";
      }
      var parts = [];
      if (missing.tenant) {
        parts.push(countWord(missing.tenant, "tenant"));
      }
      if (missing.owner) {
        parts.push(countWord(missing.owner, "owner"));
      }
      return parts.join(" and ") + " have no phone number.";
    }

    function optedOutSentence() {
      var n = 0;
      for (var i = 0; i < rows.length; i += 1) {
        if (rows[i].tenant_state === "opted_out") {
          n += 1;
        }
        if (rows[i].owner_state === "opted_out") {
          n += 1;
        }
      }
      return n ? n + " left out: opted out " + n : "";
    }

    function setSub() {
      var left = optedOutSentence();
      sub.textContent = missingSentence() + (left ? " · " + left : "");
    }
    setSub();

    function currentNumber() {
      for (var i = 0; i < numbers.length; i += 1) {
        if (String(numbers[i].id) === selectedNumberId) {
          return numbers[i];
        }
      }
      return numbers[0] || null;
    }

    function numberName(n) {
      if (!n) {
        return "No number";
      }
      return n.title || n.display_name || n.label || n.account_username || "Official number";
    }

    function numberPhone(n) {
      return n && n.phone_number ? "+" + n.phone_number : "";
    }

    function templatesForNumber() {
      var num = currentNumber();
      if (!num || !num.waba_business_id) {
        return templates;
      }
      return templates.filter(function (t) {
        return !t.waba_business_id || String(t.waba_business_id) === String(num.waba_business_id);
      });
    }

    function makePicker(title, noun) {
      var selected = null;
      var category = "ALL";
      var extraInputs = {};
      var typedInputs = {};
      var headerInputs = {};
      var buttonInputs = {};
      var search = el("input", { className: "a7-rwa-input", placeholder: "Search templates" });
      var chips = el("div", { className: "a7-rwa-chips" });
      var list = el("div", { className: "a7-rwa-list" });
      var extras = el("div", {});
      // This side's header file: kept as a File so it can go up again if the
      // agent switches number (a media id belongs to the number that uploaded it).
      var media = null;
      var mediaSeq = 0;
      var mediaStatus = null;
      var mediaBar = null;
      var mediaBox = el("div", { className: "a7-rwa-media" });
      mediaBox.style.display = "none";
      var mediaInput = el("input", { type: "file" });
      mediaInput.style.display = "none";

      function varsFrom(inputs) {
        var out = {};
        Object.keys(inputs).forEach(function (key) {
          out[key] = String(inputs[key].value || "").trim();
        });
        return out;
      }

      function mediaKind() {
        return templateMediaKind(selected);
      }

      function currentNumberId() {
        var num = currentNumber();
        return num && num.id ? String(num.id) : "";
      }

      function dropMedia() {
        mediaSeq += 1;
        if (media) {
          if (media.job) {
            media.job.abort();
          }
          if (media.previewUrl && window.URL && URL.revokeObjectURL) {
            try {
              URL.revokeObjectURL(media.previewUrl);
            } catch (ignored) {}
          }
        }
        media = null;
      }

      function startUpload() {
        if (!media || !media.file) {
          return;
        }
        if (media.job) {
          media.job.abort();
        }
        var seq = (mediaSeq += 1);
        media.numberId = currentNumberId();
        media.token = "";
        media.error = "";
        media.uploading = true;
        media.ratio = 0;
        var form = new FormData();
        form.append("action", "header-media");
        form.append("sessid", bitrixSessid());
        form.append("number_id", media.numberId);
        form.append("format", media.kind);
        form.append("file", media.file, media.file.name);
        var job = xhrUpload(UPLOAD_ENDPOINT, form, function (ratio) {
          if (seq === mediaSeq && media) {
            media.ratio = ratio;
            paintMediaStatus();
          }
        });
        media.job = job;
        job.promise
          .then(function (res) {
            if (seq !== mediaSeq || !media) {
              return;
            }
            var data = parseJsonLoose(res.text) || {};
            if (!res.ok || data.ok === false || !data.media_token) {
              throw new Error(
                data.error || data.detail || ("The file was not accepted (HTTP " + res.status + ").")
              );
            }
            media.token = String(data.media_token);
            media.uploading = false;
            media.job = null;
            err.textContent = "";
            renderCap();
          })
          .catch(function (e) {
            if (seq !== mediaSeq || !media) {
              return;
            }
            media.uploading = false;
            media.job = null;
            media.error = e && e.message ? e.message : "Upload failed.";
          })
          .then(function () {
            if (seq === mediaSeq) {
              renderMedia();
            }
          });
        renderMedia();
      }

      function syncMedia() {
        var kind = mediaKind();
        if (media && media.kind !== kind) {
          dropMedia();
        }
        if (media && media.file && media.numberId !== currentNumberId()) {
          startUpload();
          return;
        }
        renderMedia();
      }

      function paintMediaStatus() {
        if (!mediaStatus || !mediaBar) {
          return;
        }
        var rule = MEDIA[mediaKind()] || { word: "file" };
        var text = "No " + rule.word + " chosen yet.";
        var ratio = 0;
        if (media && media.error) {
          text = media.error;
        } else if (media && media.uploading) {
          ratio = media.ratio || 0;
          text = ratio >= 0.999
            ? "Sending " + media.name + " to WhatsApp…"
            : "Uploading " + media.name + "… " + Math.round(ratio * 100) + "%";
        } else if (media && media.token) {
          text = media.name + " · " + formatBytes(media.size) + " — ready";
        }
        mediaStatus.textContent = text;
        mediaStatus.title = text;
        mediaBar.style.display = media && media.uploading ? "" : "none";
        mediaBar.firstChild.style.width = Math.round(ratio * 100) + "%";
      }

      function renderMedia() {
        while (mediaBox.firstChild) {
          mediaBox.removeChild(mediaBox.firstChild);
        }
        mediaStatus = null;
        mediaBar = null;
        var kind = mediaKind();
        if (!kind) {
          mediaBox.style.display = "none";
          mediaChanged();
          return;
        }
        var rule = MEDIA[kind];
        var ready = !!(media && media.token && !media.uploading && !media.error);
        var bad = !!(media && media.error);
        mediaBox.style.display = "";
        mediaBox.className = "a7-rwa-media" + (ready ? " is-ready" : "") + (bad ? " is-bad" : "");
        mediaInput.setAttribute("accept", rule.accept);
        var pick = el("button", { className: "a7-rwa-media-pick", type: "button" }, [
          icon(kind === "VIDEO" ? "video" : kind === "DOCUMENT" ? "doc" : "image"),
          document.createTextNode((media && media.file ? "Replace " : "Choose ") + rule.word)
        ]);
        pick.addEventListener("click", function () {
          mediaInput.click();
        });
        mediaStatus = el("div", { className: "a7-rwa-media-status" });
        mediaBar = el("div", { className: "a7-rwa-media-bar" }, [el("b", {})]);
        mediaBox.appendChild(el("div", { className: "a7-rwa-media-label", text: "Header " + rule.word }));
        mediaBox.appendChild(el("div", { className: "a7-rwa-media-row" }, [pick, mediaStatus]));
        mediaBox.appendChild(mediaBar);
        mediaBox.appendChild(el("div", {
          className: "a7-rwa-media-hint",
          text: rule.hint + ". The same " + rule.word + " goes to every " + noun + "."
        }));
        mediaBox.appendChild(mediaInput);
        paintMediaStatus();
        mediaChanged();
      }

      function useHeaderFile(file, kind) {
        var problem = fileProblem(file, kind);
        if (problem && media && media.file && !media.error) {
          err.textContent = problem;
          return;
        }
        dropMedia();
        err.textContent = "";
        renderCap();
        media = {
          kind: kind,
          file: problem ? null : file,
          name: file.name,
          size: file.size,
          previewUrl: "",
          numberId: "",
          token: "",
          uploading: false,
          ratio: 0,
          error: problem,
          job: null
        };
        if (problem) {
          renderMedia();
          return;
        }
        if ((kind === "IMAGE" || kind === "VIDEO") && window.URL && URL.createObjectURL) {
          media.previewUrl = URL.createObjectURL(file);
        }
        startUpload();
      }

      mediaInput.addEventListener("change", function () {
        var file = mediaInput.files && mediaInput.files[0];
        mediaInput.value = "";
        var kind = mediaKind();
        if (!file || !kind) {
          return;
        }
        if (kind !== "IMAGE") {
          useHeaderFile(file, kind);
          return;
        }
        err.textContent = "";
        imageAsJpeg(file).then(function (jpeg) {
          if (mediaKind() !== "IMAGE") {
            return;
          }
          useHeaderFile(jpeg, "IMAGE");
        }).catch(function (e) {
          err.textContent = e && e.message ? e.message : "That image could not be prepared.";
        });
      });

      function mediaPreview(kind) {
        var rule = MEDIA[kind];
        var wrap = el("div", { className: "a7-rwa-hmedia" });
        var chosen = media && media.file && !media.error;
        if (chosen && kind === "IMAGE" && media.previewUrl) {
          wrap.appendChild(el("img", { src: media.previewUrl, alt: "" }));
        } else if (chosen && kind === "VIDEO" && media.previewUrl) {
          wrap.appendChild(el("video", { src: media.previewUrl, preload: "metadata", controls: "", muted: "" }));
        } else if (chosen) {
          wrap.appendChild(el("div", { className: "a7-rwa-hmedia-doc" }, [
            icon("doc"),
            el("span", { text: media.name + " · " + formatBytes(media.size), title: media.name })
          ]));
        } else {
          wrap.appendChild(el("div", { className: "a7-rwa-hmedia-ph is-missing" }, [
            icon(kind === "VIDEO" ? "video" : kind === "DOCUMENT" ? "doc" : "image"),
            el("span", { text: "Choose the " + rule.word + " for the header" })
          ]));
        }
        return wrap;
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
          var hay = (t.name || "") + " " + (t.language || "") + " " + (t.category || "");
          if (q && hay.toLowerCase().indexOf(q) === -1) {
            return;
          }
          shown += 1;
          var kind = templateMediaKind(t);
          var meta = el("small", {
            text: (t.language || "") + (t.category ? " · " + t.category : "")
          });
          if (kind) {
            meta.appendChild(el("span", { className: "a7-rwa-tag", text: MEDIA[kind].word + " header" }));
          }
          var item = el("button", {
            className: "a7-rwa-item" + (selected && selected.id === t.id ? " is-on" : ""),
            type: "button"
          }, [
            el("div", { text: t.name || "template", title: t.name || "" }),
            meta
          ]);
          item.addEventListener("click", function () {
            selected = t;
            renderList();
            renderExtras();
            renderPreview();
          });
          list.appendChild(item);
        });
        if (!shown) {
          list.appendChild(el("div", { className: "a7-rwa-item is-off", text: "No matching template on this number." }));
        }
      }

      function renderChips() {
        while (chips.firstChild) {
          chips.removeChild(chips.firstChild);
        }
        ["ALL", "UTILITY", "MARKETING"].forEach(function (name) {
          var chip = el("button", {
            className: "a7-rwa-chip" + (category === name ? " is-on" : ""),
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

      function renderExtras() {
        extraInputs = {};
        typedInputs = {};
        headerInputs = {};
        buttonInputs = {};
        while (extras.firstChild) {
          extras.removeChild(extras.firstChild);
        }
        // The file box follows the template: kept for another template of the
        // same kind, dropped otherwise, hidden for a text header.
        syncMedia();
        if (!selected) {
          return;
        }
        var needed = Number(selected.variable_count || 0);
        for (var i = 1; i <= needed; i += 1) {
          var input = el("select", { className: "a7-rwa-input" });
          DETAIL_FIELDS.forEach(function (pair) {
            var opt = el("option", { text: pair[1] });
            opt.value = pair[0];
            if (i === 1 && pair[0] === "name") {
              opt.selected = true;
            }
            input.appendChild(opt);
          });
          var typed = el("input", {
            className: "a7-rwa-input",
            placeholder: "Or type one value for everyone",
            style: "margin-top:6px"
          });
          extraInputs[String(i)] = input;
          typedInputs[String(i)] = typed;
          input.addEventListener("change", renderPreview);
          typed.addEventListener("input", renderPreview);
          extras.appendChild(el("div", { className: "a7-rwa-sub", text: "{{" + i + "}}" }));
          extras.appendChild(input);
          extras.appendChild(typed);
        }
        var header = selected.header;
        if (header && header.format === "TEXT" && header.variable_count) {
          for (var h = 1; h <= header.variable_count; h += 1) {
            var hInput = el("input", { className: "a7-rwa-input", placeholder: "Header {{" + h + "}}" });
            headerInputs[String(h)] = hInput;
            hInput.addEventListener("input", renderPreview);
            extras.appendChild(hInput);
          }
        }
        (selected.buttons || []).forEach(function (button) {
          if (!button.variable_count) {
            return;
          }
          var bInput = el("input", { className: "a7-rwa-input", placeholder: (button.text || "Button") + " URL suffix" });
          buttonInputs[String(button.index)] = bInput;
          extras.appendChild(bInput);
        });
      }

      search.addEventListener("input", renderList);
      renderChips();
      renderList();
      return {
        box: el("div", { className: "a7-rwa-col" }, [
          el("h3", { text: title }),
          search,
          chips,
          list,
          mediaBox,
          extras
        ]),
        refresh: function () {
          if (selected && currentNumber() && selected.waba_business_id &&
              String(selected.waba_business_id) !== String(currentNumber().waba_business_id)) {
            selected = null;
            renderExtras();
          }
          renderList();
          // A different number: the chosen file goes up again for it.
          syncMedia();
        },
        selected: function () { return selected; },
        bodyVars: function () {
          var out = {};
          Object.keys(typedInputs).forEach(function (key) {
            var value = String(typedInputs[key].value || "").trim();
            if (value) {
              out[key] = value;
            }
          });
          return out;
        },
        fieldMap: function () {
          var written = {};
          Object.keys(typedInputs).forEach(function (key) {
            if (String(typedInputs[key].value || "").trim()) {
              written[key] = true;
            }
          });
          var out = {};
          Object.keys(extraInputs).forEach(function (key) {
            if (!written[key]) {
              out[key] = String(extraInputs[key].value || "").trim();
            }
          });
          return out;
        },
        headerVars: function () { return varsFrom(headerInputs); },
        buttonVars: function () { return varsFrom(buttonInputs); },
        mediaToken: function () { return mediaKind() && media ? media.token : ""; },
        mediaNode: function () {
          var kind = mediaKind();
          return kind ? mediaPreview(kind) : null;
        },
        uploading: function () { return !!(media && media.uploading); },
        cleanup: dropMedia,
        validate: function (count) {
          if (!count) {
            return "";
          }
          if (!selected) {
            return "Pick a " + noun + " template.";
          }
          var kind = mediaKind();
          if (kind) {
            var word = MEDIA[kind].word;
            if (media && media.uploading) {
              return "Wait for the " + noun + " " + word + " to finish uploading.";
            }
            if (!media || !media.token) {
              return media && media.error ? media.error : "Choose the " + word + " for the " + noun + " template.";
            }
            if (media.numberId !== currentNumberId()) {
              startUpload();
              return "Uploading the " + noun + " " + word + " again for this number. Send once it is ready.";
            }
          }
          var needed = Number(selected.variable_count || 0);
          for (var i = 1; i <= needed; i += 1) {
            if (!String((extraInputs[String(i)] && extraInputs[String(i)].value) || "").trim()) {
              return "Choose a detail for {{" + i + "}} on the " + noun + " template.";
            }
          }
          return "";
        }
      };
    }

    // A header file was chosen, finished uploading or failed: redraw the phone
    // and hold the send button while either side is still uploading.
    function mediaChanged() {
      if (!tenantPicker || !ownerPicker) {
        return;
      }
      renderPreview();
      if (sendBtn && !busy) {
        sendBtn.disabled = over || !total || !numbers.length ||
          tenantPicker.uploading() || ownerPicker.uploading();
      }
    }

    var tenantPicker = makePicker("Tenant template", "tenant");
    var ownerPicker = makePicker("Owner template", "owner");

    function sampleName(role) {
      for (var i = 0; i < rows.length; i += 1) {
        if (rows[i][role + "_state"] === "send") {
          return rows[i][role + "_name"] || "Customer";
        }
      }
      return "Customer";
    }

    var peopleFilter = "all";
    var peopleBox = el("div", { className: "a7-rwa-people" });

    function statusBadge(state, tail) {
      var kind = "dup";
      if (state === "send") {
        kind = "ok";
      } else if (state === "missing") {
        kind = "miss";
      } else if (state === "same") {
        kind = "same";
      }
      return el("span", { className: "a7-rwa-badge is-" + kind, text: stateText(state, tail) });
    }

    function personLine(row, role) {
      var name = row[role + "_name"] || (role === "tenant" ? "Tenant" : "Owner");
      return el("div", { className: "a7-rwa-line" }, [
        el("span", { className: "a7-rwa-role", text: role === "tenant" ? "Tenant" : "Owner" }),
        el("b", { text: name, title: name }),
        statusBadge(row[role + "_state"], row[role + "_tail"])
      ]);
    }

    function paintPeople() {
      while (peopleBox.firstChild) {
        peopleBox.removeChild(peopleBox.firstChild);
      }
      var shown = 0;
      rows.forEach(function (row) {
        var miss = row.tenant_state === "missing" || row.owner_state === "missing";
        var ready = row.tenant_state === "send" || row.owner_state === "send";
        if (peopleFilter === "missing" && !miss) {
          return;
        }
        if (peopleFilter === "ready" && !ready) {
          return;
        }
        shown += 1;
        peopleBox.appendChild(el("div", { className: "a7-rwa-deal" }, [
          personLine(row, "tenant"),
          personLine(row, "owner")
        ]));
      });
      if (!shown) {
        peopleBox.appendChild(el("div", { className: "a7-rwa-empty", text: "Nothing in this view." }));
      }
    }

    function renderPreview() {
      while (phoneHead.firstChild) {
        phoneHead.removeChild(phoneHead.firstChild);
      }
      while (phoneChat.firstChild) {
        phoneChat.removeChild(phoneChat.firstChild);
      }
      var picker = previewRole === "owner" ? ownerPicker : tenantPicker;
      var selected = picker.selected();
      var who = sampleName(previewRole);
      phoneHead.appendChild(el("div", { text: (previewRole === "owner" ? "Owner" : "Tenant") + " · " + who }));
      phoneHead.appendChild(el("small", { text: "From " + numberLabel(currentNumber()) }));
      if (!selected) {
        phoneChat.appendChild(el("div", { text: "Pick a template to preview." }));
        return;
      }
      var vars = {};
      var written = picker.bodyVars();
      var typed = picker.fieldMap();
      var needed = Number(selected.variable_count || 0);
      for (var i = 1; i <= needed; i += 1) {
        if (written[String(i)]) {
          vars[String(i)] = written[String(i)];
          continue;
        }
        var field = typed[String(i)] || "name";
        vars[String(i)] = field === "name" ? who : ("each " + field.replace(/_/g, " "));
      }
      var bubble = el("div", { className: "a7-rwa-bubble" });
      var mediaNode = picker.mediaNode();
      if (mediaNode) {
        bubble.appendChild(mediaNode);
      }
      bubble.appendChild(document.createTextNode(fillVars(selected.body_text || "", vars)));
      phoneChat.appendChild(bubble);
      var marketing = (tenantPicker.selected() && /marketing/i.test(tenantPicker.selected().category || "")) ||
        (ownerPicker.selected() && /marketing/i.test(ownerPicker.selected().category || ""));
      note.textContent = marketing
        ? "Marketing templates share Meta’s daily cap per customer. An undelivered send is usually that cap."
        : "";
      note.style.display = marketing ? "" : "none";
    }

    function renderCap() {
      if (over) {
        err.textContent = "More numbers required. One Official number can send " + cap +
          " messages. This selection is " + total + ".";
        return;
      }
      if (!total) {
        err.textContent = "None of the selected deals have a usable phone number.";
      }
    }

    var sendBtn = el("button", {
      className: "a7-rwa-send",
      type: "button",
      text: total
        ? "Send " + total + " message" + (total === 1 ? "" : "s")
        : "Nothing to send: all left out"
    });
    if (over || !total || !numbers.length) {
      sendBtn.disabled = true;
    }
    // "Lead AI": the chats this campaign reaches go to the Lead AI screen of
    // the WhatsApp panel, not the main inbox. No AI answers them there.
    var leadAiBox = el("input", { type: "checkbox" });
    var leadAiToggle = el("label", {
      className: "a7-rwa-leadai",
      title: "Replies go to the Lead AI screen in the WhatsApp panel, not the main inbox. Agents answer them there."
    }, [leadAiBox, el("span", { text: "Lead AI" })]);
    var scriptSelect = el("select", {
      className: "a7-rwa-script",
      title: "Which script the assistant follows in these chats"
    });
    [["general", "General"], ["ic_shops", "International City shops"]].forEach(function (pair) {
      scriptSelect.appendChild(el("option", { value: pair[0], text: pair[1] }));
    });
    scriptSelect.value = "general";
    var scriptWrap = el("label", { className: "a7-rwa-scriptwrap" }, [
      el("span", { text: "Script" }),
      scriptSelect
    ]);
    scriptWrap.style.display = "none";
    function sendLabel() {
      if (!total) {
        return "Nothing to send: all left out";
      }
      return "Send " + total + " message" + (total === 1 ? "" : "s") + (leadAiBox.checked ? " to Lead AI" : "");
    }
    leadAiBox.addEventListener("change", function () {
      leadAiToggle.className = "a7-rwa-leadai" + (leadAiBox.checked ? " is-on" : "");
      scriptWrap.style.display = leadAiBox.checked ? "" : "none";
      if (!busy) {
        sendBtn.textContent = sendLabel();
      }
    });

    var numberSearch = el("input", {
      className: "a7-rwa-input",
      type: "search",
      placeholder: "Search name or number",
      autocomplete: "off",
      spellcheck: "false",
      "aria-label": "Search WhatsApp numbers"
    });
    var numberList = el("div", { className: "a7-rwa-num-list", role: "listbox" });
    var pickedName = el("b", { text: numberName(currentNumber()) });
    var pickedPhone = el("span", { text: numberPhone(currentNumber()) });

    function paintNumbers() {
      while (numberList.firstChild) {
        numberList.removeChild(numberList.firstChild);
      }
      var q = String(numberSearch.value || "").trim().toLowerCase();
      var qDigits = q.replace(/\D/g, "");
      var shown = 0;
      numbers.forEach(function (n) {
        var name = numberName(n);
        var phone = String(n.phone_number || "");
        var hay = (
          name + " " + phone + " " + (n.label || "") + " " +
          (n.account_username || "") + " " + (n.display_name || "")
        ).toLowerCase();
        if (q && hay.indexOf(q) === -1 && !(qDigits && phone.indexOf(qDigits) !== -1)) {
          return;
        }
        shown += 1;
        var on = String(n.id) === selectedNumberId;
        var row = el("button", {
          className: "a7-rwa-num" + (on ? " is-on" : ""),
          type: "button",
          role: "option",
          "aria-selected": on ? "true" : "false"
        }, [
          el("b", { text: name, title: name }),
          el("span", { text: numberPhone(n) })
        ]);
        row.addEventListener("click", function () {
          selectedNumberId = String(n.id);
          pickedName.textContent = numberName(n);
          pickedPhone.textContent = numberPhone(n);
          paintNumbers();
          tenantPicker.refresh();
          ownerPicker.refresh();
          renderPreview();
        });
        numberList.appendChild(row);
      });
      if (!shown) {
        numberList.appendChild(el("div", {
          className: "a7-rwa-empty",
          text: "No number matches that search."
        }));
      }
    }
    numberSearch.addEventListener("input", paintNumbers);
    paintNumbers();

    var filterRow = el("div", { className: "a7-rwa-chips" });
    function paintFilter() {
      while (filterRow.firstChild) {
        filterRow.removeChild(filterRow.firstChild);
      }
      [
        ["all", "All"],
        ["missing", "No phone"],
        ["ready", "Ready"]
      ].forEach(function (pair) {
        var chip = el("button", {
          className: "a7-rwa-chip" + (peopleFilter === pair[0] ? " is-on" : ""),
          type: "button",
          text: pair[1]
        });
        chip.addEventListener("click", function () {
          peopleFilter = pair[0];
          paintFilter();
          paintPeople();
        });
        filterRow.appendChild(chip);
      });
    }
    paintFilter();
    paintPeople();

    var roleTenant = el("button", { className: "a7-rwa-chip is-on", type: "button", text: "Tenant preview" });
    var roleOwner = el("button", { className: "a7-rwa-chip", type: "button", text: "Owner preview" });
    function setRole(role) {
      previewRole = role;
      roleTenant.className = "a7-rwa-chip" + (role === "tenant" ? " is-on" : "");
      roleOwner.className = "a7-rwa-chip" + (role === "owner" ? " is-on" : "");
      renderPreview();
    }
    roleTenant.addEventListener("click", function () { setRole("tenant"); });
    roleOwner.addEventListener("click", function () { setRole("owner"); });

    sendBtn.addEventListener("click", function () {
      if (busy || sendBtn.disabled) {
        return;
      }
      var problem = tenantPicker.validate(tenantCount) || ownerPicker.validate(ownerCount);
      if (problem) {
        err.textContent = problem;
        return;
      }
      var tenantVars = tenantPicker.bodyVars();
      var ownerVars = ownerPicker.bodyVars();
      var tenantFields = tenantPicker.fieldMap();
      var ownerFields = ownerPicker.fieldMap();
      busy = true;
      sendBtn.disabled = true;
      sendBtn.textContent = "Queuing…";
      err.textContent = "";
      var form = new URLSearchParams();
      form.set("action", "send");
      form.set("sessid", bitrixSessid());
      form.set("deal_ids", JSON.stringify(dealIds));
      form.set("payload", JSON.stringify({
        deal_ids: dealIds,
        number_id: currentNumber() ? currentNumber().id : 0,
        tenant_template_id: tenantPicker.selected() ? tenantPicker.selected().id : 0,
        owner_template_id: ownerPicker.selected() ? ownerPicker.selected().id : 0,
        tenant_variables: tenantVars,
        owner_variables: ownerVars,
        tenant_variable_fields: tenantFields,
        owner_variable_fields: ownerFields,
        tenant_header_variables: tenantPicker.headerVars(),
        owner_header_variables: ownerPicker.headerVars(),
        tenant_button_variables: tenantPicker.buttonVars(),
        owner_button_variables: ownerPicker.buttonVars(),
        tenant_header_media_token: tenantPicker.mediaToken(),
        owner_header_media_token: ownerPicker.mediaToken(),
        lead_ai: !!leadAiBox.checked,
        lead_ai_playbook: leadAiBox.checked ? (scriptSelect.value || "general") : ""
      }));
      fetchJson(ENDPOINT, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString()
      }).then(function (res) {
        var data = parseJsonLoose(res.text) || {};
        if (!res.ok || data.ok === false) {
          throw new Error(data.error || data.detail || "Send failed.");
        }
        var queued = Number(data.queued || 0);
        var parts = (data.campaigns || []).map(function (item) {
          return item.queued + " " + item.role;
        });
        notify(
          "Queued " + queued + " WhatsApp message" + (queued === 1 ? "" : "s") +
            (parts.length ? " (" + parts.join(", ") + ")." : ".") +
            (leftOutNote(data) ? " " + leftOutNote(data) : "") +
            (data.lead_ai ? " Replies will show in Lead AI." : ""),
          true
        );
        // closeStudio() does not clear busy here (an Esc mid-send must not let a
        // second popup open), so a sent campaign clears it, or the button stays
        // dead until the page is reloaded.
        busy = false;
        closeStudio();
      }).catch(function (e) {
        busy = false;
        sendBtn.disabled = over || !total;
        sendBtn.textContent = sendLabel();
        err.textContent = e && e.message ? e.message : "Send failed.";
      });
    });

    var closeBtn = el("button", { className: "a7-rwa-x", type: "button", title: "Close" });
    closeBtn.appendChild(icon("close"));
    closeBtn.addEventListener("click", closeStudio);

    var modal = el("div", { className: "a7-rwa-modal" }, [
      el("div", { className: "a7-rwa-top" }, [
        el("div", { className: "a7-rwa-brand" }, [
          icon("wa"),
          el("div", {}, [el("h2", { text: "WhatsApp campaign" }), sub])
        ]),
        closeBtn
      ]),
      el("div", { className: "a7-rwa-stats" }, [
        el("div", { className: "a7-rwa-stat" }, [
          el("b", { text: String(dealIds.length) }),
          el("span", { text: "Deals selected" })
        ]),
        el("div", { className: "a7-rwa-stat" + (missing.people ? " is-warn" : " is-ok") }, [
          el("b", { text: String(missing.people) }),
          el("span", { text: "Without a phone" }),
          el("small", { text: countWord(missing.tenant, "tenant") + " · " + countWord(missing.owner, "owner") })
        ]),
        el("div", { className: "a7-rwa-stat" + (total ? " is-ok" : "") }, [
          el("b", { text: String(total) }),
          el("span", { text: "Messages ready" }),
          el("small", { text: countWord(tenantCount, "tenant") + " · " + countWord(ownerCount, "owner") })
        ])
      ]),
      el("div", { className: "a7-rwa-grid" }, [
        el("div", { className: "a7-rwa-side" }, [
          el("div", { className: "a7-rwa-from" }, [
            el("h3", { text: "Send from" }),
            el("div", { className: "a7-rwa-picked" }, [pickedName, pickedPhone]),
            numberSearch,
            numberList
          ]),
          el("h3", { text: "Selected deals" }),
          filterRow,
          peopleBox,
          err,
          note
        ]),
        tenantPicker.box,
        ownerPicker.box,
        el("div", { className: "a7-rwa-col" }, [
          el("h3", { text: "Preview" }),
          el("div", { className: "a7-rwa-chips" }, [roleTenant, roleOwner]),
          el("div", { className: "a7-rwa-phone" }, [phoneHead, phoneChat])
        ])
      ]),
      el("div", { className: "a7-rwa-footbar" }, [
        el("div", {
          className: "a7-rwa-sub",
          text: "Blank {{1}} uses each person’s name. The same number on both sides gets the owner template only. Replies show on the deal timeline."
        }),
        el("div", { className: "a7-rwa-actions" }, [
          leadAiToggle,
          scriptWrap,
          el("button", { className: "a7-rwa-cancel", type: "button", text: "Cancel" }),
          sendBtn
        ])
      ])
    ]);
    modal.querySelector(".a7-rwa-cancel").addEventListener("click", closeStudio);

    overlay = el("div", { className: "a7-rwa-overlay" }, [modal]);
    overlay.addEventListener("click", function (ev) {
      if (ev.target === overlay) {
        closeStudio();
      }
    });
    studioCleanup = function () {
      tenantPicker.cleanup();
      ownerPicker.cleanup();
    };
    prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onEsc);
    document.body.appendChild(overlay);
    renderCap();
    renderPreview();
    try {
      numberSearch.focus();
    } catch (ignored) {}
  }

  function startSend() {
    if (busy) {
      return;
    }
    var ids = selectedDealIds();
    if (!ids.length) {
      notify("Select one or more deals first. This does not send to “For all”.", false);
      return;
    }
    if (ids.length > MAX_DEALS) {
      notify("Select at most " + MAX_DEALS + " deals.", false);
      return;
    }
    busy = true;
    var form = new URLSearchParams();
    form.set("action", "context");
    form.set("sessid", bitrixSessid());
    form.set("deal_ids", JSON.stringify(ids));
    fetchJson(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString()
    }).then(function (res) {
      var data = parseJsonLoose(res.text) || {};
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || data.detail || "Could not load templates.");
      }
      busy = false;
      openStudio(ids, data);
    }).catch(function (e) {
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
    return !!(btn && btn.closest(
      ".pagetitle-wrap, .pagetitle-inner-container, .pagetitle-container, .ui-toolbar, .crm-view-switcher, .a7-rwa-topbar"
    ));
  }

  function mountButton() {
    ensureStyles();
    var existing = document.querySelector("." + BTN_CLASS);
    if (isWellPlaced(existing)) {
      return;
    }
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing.parentNode.classList.contains(SLOT_CLASS) ? existing.parentNode : existing);
    }
    var slot = document.createElement("span");
    slot.className = SLOT_CLASS;
    slot.appendChild(makeButton());
    var host = findTitleHost();
    if (host) {
      if (host.firstChild) {
        host.insertBefore(slot, host.firstChild);
      } else {
        host.appendChild(slot);
      }
      return;
    }
    var bar = document.createElement("div");
    bar.className = "a7-rwa-topbar";
    bar.style.cssText = "position:sticky;top:0;z-index:50;display:flex;justify-content:flex-end;padding:8px 16px;";
    bar.appendChild(slot);
    var work = document.querySelector(".workarea-content, .pagetitle-below, #workarea-content");
    if (work && work.parentNode) {
      work.parentNode.insertBefore(bar, work);
    } else {
      document.body.insertBefore(bar, document.body.firstChild);
    }
  }

  function watch() {
    mountButton();
    var obs = new MutationObserver(function () {
      mountButton();
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watch);
  } else {
    watch();
  }
})();
