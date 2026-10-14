/**
 * A7 CRM list / kanban WhatsApp campaign popup — Leads, Owner Data /
 * Availability, Deals (every pipeline except Renewals, which has its own)
 * and Contacts.
 * The title-bar button is always on the list/kanban toolbar (greyed, with a
 * "tick leads first" hint) and becomes active with a count as soon as at
 * least one Lead or Owner Data / Availability card is selected; then one
 * Official campaign. It only falls back to its own top bar once something is
 * selected, so a slow toolbar never traps it there on page load.
 * A template with an image, video or document header asks for that file in
 * the popup; it is uploaded for the chosen number before anything is queued.
 * The "Lead AI" box sends the chats this campaign reaches to the Lead AI
 * screen of the WhatsApp panel instead of the main inbox.
 */
(function () {
  if (window.A7_LEAD_WA_V13) {
    return;
  }
  window.A7_LEAD_WA_V13 = true;

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
  var isDetails =
    /\/crm\/(?:lead|deal|contact)\/details\//i.test(PATH) ||
    /\/crm\/type\/1042\/details\//i.test(PATH);
  var onLeads = /\/crm\/lead\//i.test(PATH);
  var onOwner = /\/crm\/type\/1042\//i.test(PATH);
  // Renewals (deal category 9) keeps its own campaign button (a7_renewals_wa.js).
  var onDeals =
    /\/crm\/deal\//i.test(PATH) &&
    !/\/crm\/deal\/(?:kanban\/|list\/)?category\/9(?:\/|$)/i.test(PATH);
  var onContacts = /\/crm\/contact\//i.test(PATH);
  if (isDetails || (!onLeads && !onOwner && !onDeals && !onContacts)) {
    return;
  }
  var ENTITY = onOwner ? "owner_data" : onDeals ? "deal" : onContacts ? "contact" : "lead";
  var NOUN = onOwner ? "cards" : onDeals ? "deals" : onContacts ? "contacts" : "leads";
  var NOUN_ONE = onOwner ? "card" : onDeals ? "deal" : onContacts ? "contact" : "lead";

  var ENDPOINT = "/bitrix/tools/a7_lead_wa.php";
  var FETCH_MS = 20000;
  // A 100 MB document over an office line takes minutes, not seconds.
  var UPLOAD_MS = 15 * 60 * 1000;
  var STYLE_ID = "a7-lwa-style-v8";
  var BTN_CLASS = "a7-lwa-btn";
  var SLOT_CLASS = "a7-lwa-slot";
  var MAX_LEADS = 500;
  var MB = 1024 * 1024;
  // What WhatsApp takes for a header of each kind. The inbox checks again,
  // byte by byte, so this is only here to say no before a long upload.
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
  // Set while a popup is open: stops its upload and frees its preview.
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

  function mediaIcon(kind) {
    return icon(kind === "VIDEO" ? "video" : kind === "DOCUMENT" ? "doc" : "image");
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
      "." + BTN_CLASS + ".a7-lwa-idle{opacity:.55;cursor:not-allowed;}" +
      "." + BTN_CLASS + ".a7-lwa-idle:hover{background:#fff !important;}" +
      ".a7-lwa-count{min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:#25D366;" +
      "color:#fff;font-size:11px;line-height:18px;text-align:center;font-weight:700;}" +
      ".a7-lwa-count:empty{display:none;}" +
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
      ".a7-lwa-col{min-width:0;min-height:0;display:flex;flex-direction:column;gap:8px;overflow-x:hidden;overflow-y:auto;}" +
      ".a7-lwa-col h3{margin:0;font-size:12px;font-weight:600;color:#64748b;display:flex;" +
      "align-items:center;gap:6px;}" +
      ".a7-lwa-label{display:block;font-weight:600;margin-bottom:4px;font-size:12px;color:#475569;}" +
      ".a7-lwa-input,.a7-lwa-select{width:100%;max-width:100%;border:1px solid #cbd5e1;" +
      "border-radius:8px;padding:7px 9px;font-size:13px;background:#fff;color:#334155;}" +
      ".a7-lwa-typed{margin-top:6px;}" +
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
      ".a7-lwa-leads{flex:0 0 auto;max-height:140px;overflow:auto;border:1px solid #e5e7eb;border-radius:8px;padding:0 8px;}" +
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
      ".a7-lwa-leadai{display:inline-flex;align-items:center;gap:6px;border:1px solid #cbd5e1;" +
      "border-radius:8px;padding:7px 10px;font-size:13px;font-weight:600;color:#334155;cursor:pointer;" +
      "user-select:none;background:#fff;white-space:nowrap;}" +
      ".a7-lwa-leadai:hover{background:#f8fafc;}" +
      ".a7-lwa-leadai.is-on{border-color:#7c3aed;background:#f5f3ff;color:#5b21b6;}" +
      ".a7-lwa-leadai input{margin:0;width:15px;height:15px;accent-color:#7c3aed;cursor:pointer;}" +
      ".a7-lwa-scriptwrap{display:inline-flex;align-items:center;gap:6px;border:1px solid #ddd6fe;" +
      "border-radius:8px;padding:6px 8px;font-size:13px;font-weight:600;color:#5b21b6;background:#f5f3ff;}" +
      ".a7-lwa-scriptwrap span{white-space:nowrap;}" +
      ".a7-lwa-script{border:1px solid #c4b5fd;border-radius:6px;padding:4px 6px;font-size:13px;" +
      "color:#1e1b4b;background:#fff;max-width:220px;}" +
      ".a7-lwa-scriptnote{font-size:12px;color:#92400e;max-width:220px;line-height:1.3;}" +
      ".a7-lwa-send{background:#25D366;color:#fff;border:0;border-radius:8px;padding:8px 12px;" +
      "font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;}" +
      ".a7-lwa-send .a7-lwa-ic{color:#fff;}" +
      ".a7-lwa-send:disabled{opacity:.55;cursor:default;}" +
      ".a7-lwa-cancel{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:8px 12px;" +
      "font-size:13px;cursor:pointer;color:#334155;}" +
      ".a7-lwa-vars{flex:0 0 auto;max-height:160px;overflow:auto;}" +
      ".a7-lwa-media{flex:0 0 auto;border:1px dashed #94a3b8;border-radius:8px;padding:8px 10px;" +
      "background:#f8fafc;display:flex;flex-direction:column;gap:6px;}" +
      ".a7-lwa-media.is-ready{border-style:solid;border-color:#86efac;background:#f0fdf4;}" +
      ".a7-lwa-media.is-bad{border-color:#fca5a5;background:#fef2f2;}" +
      ".a7-lwa-media .a7-lwa-label{margin:0;}" +
      ".a7-lwa-media-row{display:flex;align-items:center;gap:8px;min-width:0;}" +
      ".a7-lwa-media-pick{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:6px 10px;" +
      "font-size:12px;font-weight:600;cursor:pointer;color:#334155;display:inline-flex;align-items:center;" +
      "gap:6px;flex:0 0 auto;}" +
      ".a7-lwa-media-pick:hover{background:#f0fdf4;}" +
      ".a7-lwa-media-pick .a7-lwa-ic{color:#128C7E;}" +
      ".a7-lwa-media-status{min-width:0;flex:1;font-size:12px;color:#475569;overflow:hidden;" +
      "text-overflow:ellipsis;white-space:nowrap;}" +
      ".a7-lwa-media.is-ready .a7-lwa-media-status{color:#166534;font-weight:600;}" +
      ".a7-lwa-media.is-bad .a7-lwa-media-status{color:#b91c1c;white-space:normal;}" +
      ".a7-lwa-media-bar{height:4px;border-radius:99px;background:#e2e8f0;overflow:hidden;}" +
      ".a7-lwa-media-bar b{display:block;height:100%;width:0;background:#25D366;transition:width .2s;}" +
      ".a7-lwa-media-hint{font-size:11px;color:#64748b;}" +
      ".a7-lwa-tag{display:inline-block;margin-left:4px;padding:0 5px;border-radius:4px;background:#e0f2fe;" +
      "color:#075985;font-size:10px;font-weight:700;vertical-align:1px;}" +
      ".a7-lwa-hmedia{margin:-7px -8px 6px;border-radius:8px 8px 0 0;overflow:hidden;background:#cfd8dc;}" +
      ".a7-lwa-hmedia img,.a7-lwa-hmedia video{display:block;width:100%;max-height:170px;object-fit:cover;" +
      "background:#0f172a;}" +
      ".a7-lwa-hmedia-ph{display:flex;align-items:center;justify-content:center;gap:6px;min-height:86px;" +
      "color:#475569;font-size:11px;font-weight:600;padding:8px;text-align:center;white-space:normal;}" +
      ".a7-lwa-hmedia-ph.is-missing{background:repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0 6px," +
      "#f1f5f9 6px,#f1f5f9 12px);color:#64748b;}" +
      ".a7-lwa-hmedia-doc{display:flex;align-items:center;gap:6px;background:#f1f5f9;padding:9px 8px;" +
      "font-size:11px;color:#334155;white-space:nowrap;}" +
      ".a7-lwa-hmedia-doc span{overflow:hidden;text-overflow:ellipsis;}" +
      "@media (max-width:720px){.a7-lwa-grid{grid-template-columns:1fr;}.a7-lwa-phone{height:360px;width:200px;}" +
      ".a7-lwa-modal{height:min(96vh,920px);}}";
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
    } else if (name === "image") {
      path("M4 5h16v14H4z");
      circle("9", "10", "1.6");
      path("M4 17l5-5 4 4 2.5-2.5L20 17");
    } else if (name === "video") {
      path("M3 6h12v12H3z");
      path("M15 10l6-3v10l-6-3z");
    } else if (name === "doc") {
      path("M7 3h7l5 5v13H7z");
      path("M14 3v5h5");
    }
    return svg;
  }

  function fieldBlock(label, input) {
    return el("label", {}, [
      el("span", { className: "a7-lwa-label", text: label }),
      input
    ]);
  }

  function detailSelect(slot) {
    var select = el("select", { className: "a7-lwa-input" });
    DETAIL_FIELDS.forEach(function (pair) {
      var opt = el("option", { text: pair[1] });
      opt.value = pair[0];
      if (slot === 1 && pair[0] === "name") {
        opt.selected = true;
      }
      select.appendChild(opt);
    });
    return select;
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
    var typedInputs = {};
    var headerInputs = {};
    var buttonInputs = {};
    // The header file of a media template: the File itself (kept so it can be
    // uploaded again if the agent switches number), the number it was uploaded
    // for, and the token the inbox gave back for it.
    var media = null;
    var mediaSeq = 0;
    var mediaStatus = null;
    var mediaBar = null;

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
    var mediaBox = el("div", { className: "a7-lwa-media" });
    mediaBox.style.display = "none";
    var mediaInput = el("input", { type: "file" });
    mediaInput.style.display = "none";
    // "Lead AI": the chats this campaign reaches go to the Lead AI screen of
    // the WhatsApp panel, not the main inbox. No AI answers them there.
    var leadAiBox = el("input", { type: "checkbox" });
    var leadAiToggle = el("label", {
      className: "a7-lwa-leadai",
      title: "Replies go to the Lead AI screen in the WhatsApp panel, not the main inbox. Agents answer them there."
    }, [leadAiBox, el("span", { text: "Lead AI" })]);
    var scriptSelect = el("select", {
      className: "a7-lwa-script",
      title: "Which script the assistant follows in these chats"
    });
    [["general", "General"], ["ic_shops", "International City shops"]].forEach(function (pair) {
      scriptSelect.appendChild(el("option", { value: pair[0], text: pair[1] }));
    });
    // C28: every Lead AI campaign Matloob sends is a shop campaign.
    scriptSelect.value = "ic_shops";
    var scriptWrap = el("label", { className: "a7-lwa-scriptwrap" }, [
      el("span", { text: "Script" }),
      scriptSelect
    ]);
    scriptWrap.style.display = "none";
    var scriptNote = el("div", {
      className: "a7-lwa-scriptnote",
      text: ""
    });
    scriptNote.style.display = "none";
    function syncScriptNote() {
      if (leadAiBox.checked && scriptSelect.value === "general") {
        scriptNote.textContent = "This chat will not get the shops script.";
        scriptNote.style.display = "";
      } else {
        scriptNote.textContent = "";
        scriptNote.style.display = "none";
      }
    }

    function setSendLabel(text) {
      while (sendBtn.firstChild) {
        sendBtn.removeChild(sendBtn.firstChild);
      }
      sendBtn.appendChild(icon("send"));
      sendBtn.appendChild(document.createTextNode(text));
    }

    var canSend = leadIds.length;
    function queueLabel() {
      if (!canSend) {
        return "Nothing to send: all left out";
      }
      return "Queue " + canSend + " message" + (canSend === 1 ? "" : "s") +
        (leadAiBox.checked ? " to Lead AI" : "");
    }
    function applySendState() {
      if (busy) {
        return;
      }
      setSendLabel(queueLabel());
      sendBtn.disabled = !canSend || !!(media && media.uploading);
    }
    applySendState();
    function refreshLeadAiBusy() {
      if (!leadAiBox.checked || !leads.length) {
        leads.forEach(function (row) {
          row.lead_ai_busy = false;
        });
        renderLeads();
        return;
      }
      var phones = [];
      leads.forEach(function (row) {
        var digits = String(row.phone || "").replace(/\D/g, "");
        if (digits.length >= 8) {
          phones.push(digits);
        }
      });
      if (!phones.length) {
        renderLeads();
        return;
      }
      var form = new URLSearchParams();
      form.set("action", "busy");
      form.set("sessid", bitrixSessid());
      form.set("payload", JSON.stringify({ phones: phones }));
      fetchJson(ENDPOINT, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString()
      }).then(function (res) {
        var data = parseJsonLoose(res.text) || {};
        var busyMap = {};
        if (res.ok && data.ok !== false) {
          ((data.phones) || []).forEach(function (p) {
            busyMap[String(p)] = true;
          });
        }
        leads.forEach(function (row) {
          var digits = String(row.phone || "").replace(/\D/g, "");
          row.lead_ai_busy = !!(digits && busyMap[digits]);
        });
        renderLeads();
      }).catch(function () {
        renderLeads();
      });
    }

    leadAiBox.addEventListener("change", function () {
      leadAiToggle.classList.toggle("is-on", leadAiBox.checked);
      scriptWrap.style.display = leadAiBox.checked ? "" : "none";
      if (leadAiBox.checked) {
        scriptSelect.value = "ic_shops";
      }
      syncScriptNote();
      refreshLeadAiBusy();
    });
    scriptSelect.addEventListener("change", syncScriptNote);

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

    function detailPreview(key) {
      var field = String((extraInputs[key] && extraInputs[key].value) || "name");
      for (var i = 0; i < leads.length; i += 1) {
        var details = leads[i].details || {};
        var value = String(details[field] || "").trim();
        if (value) {
          return value;
        }
        if (field === "name") {
          var name = String(leads[i].name || "").trim();
          if (name && !/^(untitled|unentitled)$/i.test(name)) {
            return name;
          }
        }
      }
      return "?";
    }

    function typedValue(key) {
      return String((typedInputs[key] && typedInputs[key].value) || "").trim();
    }

    function currentVars() {
      var vars = {};
      Object.keys(extraInputs).forEach(function (key) {
        vars[key] = typedValue(key) || detailPreview(key);
      });
      return vars;
    }

    function headerVars() {
      var vars = {};
      Object.keys(headerInputs).forEach(function (key) {
        vars[key] = String(headerInputs[key].value || "").trim();
      });
      return vars;
    }

    function mediaKind() {
      if (!selected || !selected.requires_header_media || !selected.header) {
        return "";
      }
      var kind = String(selected.header.format || "").toUpperCase();
      return MEDIA[kind] ? kind : "";
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
      var num = currentNumber();
      media.numberId = num && num.id ? String(num.id) : "";
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
      var job = xhrUpload(ENDPOINT, form, function (ratio) {
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

    // A media id belongs to the number that uploaded it, so a file chosen
    // before the agent switched number goes up again for the new one.
    function syncMedia() {
      var kind = mediaKind();
      if (media && media.kind !== kind) {
        dropMedia();
      }
      var num = currentNumber();
      var numberId = num && num.id ? String(num.id) : "";
      if (media && media.file && media.numberId !== numberId) {
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
      if (!busy) {
        applySendState();
      }
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
        if (!busy) {
          applySendState();
        }
        renderPreview();
        return;
      }
      var rule = MEDIA[kind];
      var ready = !!(media && media.token && !media.uploading && !media.error);
      var bad = !!(media && media.error);
      mediaBox.style.display = "";
      mediaBox.className = "a7-lwa-media" + (ready ? " is-ready" : "") + (bad ? " is-bad" : "");
      mediaInput.setAttribute("accept", rule.accept);
      var pick = el("button", { className: "a7-lwa-media-pick", type: "button" }, [
        mediaIcon(kind),
        document.createTextNode((media && media.file ? "Replace " : "Choose ") + rule.word)
      ]);
      pick.addEventListener("click", function () {
        mediaInput.click();
      });
      mediaStatus = el("div", { className: "a7-lwa-media-status" });
      mediaBar = el("div", { className: "a7-lwa-media-bar" }, [el("b", {})]);
      mediaBox.appendChild(el("span", { className: "a7-lwa-label", text: "Header " + rule.word }));
      mediaBox.appendChild(el("div", { className: "a7-lwa-media-row" }, [pick, mediaStatus]));
      mediaBox.appendChild(mediaBar);
      mediaBox.appendChild(el("div", {
        className: "a7-lwa-media-hint",
        text: rule.hint + ". The same " + rule.word + " goes to every selected " + NOUN_ONE + "."
      }));
      mediaBox.appendChild(mediaInput);
      paintMediaStatus();
      renderPreview();
    }

    function useHeaderFile(file, kind) {
      var problem = fileProblem(file, kind);
      if (problem && media && media.file && !media.error) {
        err.textContent = problem;
        return;
      }
      dropMedia();
      err.textContent = "";
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
      var wrap = el("div", { className: "a7-lwa-hmedia" });
      var chosen = media && media.file && !media.error;
      if (chosen && kind === "IMAGE" && media.previewUrl) {
        wrap.appendChild(el("img", { src: media.previewUrl, alt: "" }));
      } else if (chosen && kind === "VIDEO" && media.previewUrl) {
        wrap.appendChild(el("video", { src: media.previewUrl, preload: "metadata", controls: "", muted: "" }));
      } else if (chosen) {
        wrap.appendChild(el("div", { className: "a7-lwa-hmedia-doc" }, [
          mediaIcon(kind),
          el("span", { text: media.name + " · " + formatBytes(media.size), title: media.name })
        ]));
      } else {
        wrap.appendChild(el("div", { className: "a7-lwa-hmedia-ph is-missing" }, [
          mediaIcon(kind),
          el("span", { text: "Choose the " + rule.word + " for the header" })
        ]));
      }
      return wrap;
    }

    function leftOutReason(row) {
      var opt = Number(row.wa_opt_out || 0);
      var bot = Number(row.bot_status || 0);
      if (opt === 2482 || bot === 2481) {
        return "opted_out";
      }
      if (!leadAiBox.checked) {
        return "";
      }
      if (bot === 2479) {
        return "broker";
      }
      if (bot === 2480) {
        return "lost";
      }
      if (row.lead_ai_busy) {
        return "lead_ai_busy";
      }
      return "";
    }

    function leftOutLabel(reason) {
      if (reason === "opted_out") {
        return "Opted out";
      }
      if (reason === "broker") {
        return "Broker";
      }
      if (reason === "lost") {
        return "Lost";
      }
      if (reason === "lead_ai_busy") {
        return "Already talking to Lead AI";
      }
      return "";
    }

    function leftOutSentence(counts) {
      var order = [
        ["opted_out", "opted out"],
        ["broker", "broker"],
        ["lost", "lost"],
        ["lead_ai_busy", "already talking to Lead AI"]
      ];
      var parts = [];
      var total = 0;
      order.forEach(function (pair) {
        var n = counts[pair[0]] || 0;
        if (n) {
          total += n;
          parts.push(pair[1] + " " + n);
        }
      });
      if (!total) {
        return "";
      }
      return total + " left out: " + parts.join(", ");
    }

    function skipSentence(data) {
      var rows = data && data.skipped;
      if (!rows || !rows.length) {
        return "";
      }
      var labels = [
        ["Opted out.", "opted out"],
        ["Broker.", "broker"],
        ["Lost.", "lost"],
        ["Already talking to Lead AI.", "already talking to Lead AI"],
        ["Sent this template in the last 30 days.", "already sent"]
      ];
      var counts = {};
      var other = 0;
      rows.forEach(function (row) {
        var reason = row && row.reason ? String(row.reason) : "";
        var known = false;
        labels.forEach(function (pair) {
          if (reason === pair[0]) {
            counts[pair[0]] = (counts[pair[0]] || 0) + 1;
            known = true;
          }
        });
        if (!known) {
          other += 1;
        }
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
      var text = "";
      if (total) {
        text = total + " left out: " + parts.join(", ") + ".";
      }
      if (other) {
        text += (text ? " " : "") + "Skipped " + other + " without a usable phone.";
      }
      return text;
    }

    function renderLeads() {
      while (leadBox.firstChild) {
        leadBox.removeChild(leadBox.firstChild);
      }
      var usable = 0;
      var missing = 0;
      var leftCounts = { opted_out: 0, broker: 0, lost: 0, lead_ai_busy: 0 };
      leads.forEach(function (row) {
        var reason = leftOutReason(row);
        if (reason) {
          leftCounts[reason] += 1;
        } else if (row.phone_ok) {
          usable += 1;
        } else {
          missing += 1;
        }
      });
      var shown = leads.slice(0, 8);
      shown.forEach(function (row) {
        var name = row.name || "Untitled";
        var reason = leftOutReason(row);
        var line = el("div", { className: "a7-lwa-lead" + (row.phone_ok && !reason ? "" : " is-bad") }, [
          el("b", { text: name, title: name }),
          el("span", {
            text: reason
              ? leftOutLabel(reason)
              : (row.phone_ok ? "…" + (row.phone_tail || "") : "No phone")
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
      var messaged = usable;
      if (!leads.length) {
        messaged = leadIds.length;
      }
      var bits = [
        leadIds.length + " selected",
        messaged + " can be messaged"
      ];
      if (missing) {
        bits.push(missing + " missing a phone");
      }
      var left = leftOutSentence(leftCounts);
      if (left) {
        bits.push(left);
      }
      sub.textContent = bits.join(" · ");
      canSend = messaged;
      applySendState();
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
      var kind = mediaKind();
      if (kind) {
        bubbleKids.push(mediaPreview(kind));
      } else if (header && header.format === "TEXT" && header.text) {
        bubbleKids.push(
          el("div", { className: "a7-lwa-headtxt", text: fillVars(header.text, headerVars()) })
        );
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
        var kind = t.requires_header_media && t.header ? String(t.header.format || "").toUpperCase() : "";
        var meta = el("small", {
          text: (t.language || "") + (t.category ? " · " + t.category : "")
        });
        if (MEDIA[kind]) {
          meta.appendChild(el("span", { className: "a7-lwa-tag", text: MEDIA[kind].word + " header" }));
        }
        var item = el("button", {
          className: "a7-lwa-item" + (selected && selected.id === t.id ? " is-on" : ""),
          type: "button"
        }, [
          el("div", { text: t.name || "template", title: t.name || "template" }),
          meta
        ]);
        item.addEventListener("click", function () {
          selected = t;
          renderList();
          renderSelected();
        });
        list.appendChild(item);
      });
      if (!shown) {
        list.appendChild(el("div", { className: "a7-lwa-item is-off", text: "No matching template on this number." }));
      }
    }

    function renderSelected() {
      extraInputs = {};
      typedInputs = {};
      headerInputs = {};
      buttonInputs = {};
      while (extras.firstChild) {
        extras.removeChild(extras.firstChild);
      }
      err.textContent = "";
      renderNote();
      if (!selected) {
        syncMedia();
        return;
      }
      var needed = Number(selected.variable_count || 0);
      for (var i = 1; i <= needed; i += 1) {
        var input = detailSelect(i);
        var typed = el("input", {
          className: "a7-lwa-input a7-lwa-typed",
          type: "text",
          placeholder: "Or type one value for everyone"
        });
        extraInputs[String(i)] = input;
        typedInputs[String(i)] = typed;
        input.addEventListener("change", renderPreview);
        typed.addEventListener("input", renderPreview);
        extras.appendChild(fieldBlock("{{" + i + "}}", el("div", {}, [input, typed])));
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
      // Draws the file box (or hides it) and then the preview.
      syncMedia();
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
      if (busy || !canSend) {
        return;
      }
      if (!selected) {
        err.textContent = "Pick a template.";
        return;
      }
      var kind = mediaKind();
      if (kind) {
        var word = MEDIA[kind].word;
        if (media && media.uploading) {
          err.textContent = "Wait for the " + word + " to finish uploading.";
          return;
        }
        if (!media || !media.token) {
          err.textContent = media && media.error ? media.error : "Choose the " + word + " for the header.";
          return;
        }
        var chosenFor = currentNumber();
        if (!chosenFor || media.numberId !== String(chosenFor.id)) {
          // The number changed after the upload; send the file again for it.
          startUpload();
          err.textContent = "Uploading the " + word + " again for this number. Queue once it is ready.";
          return;
        }
      }
      var variables = {};
      var variableFields = {};
      var needed = Number(selected.variable_count || 0);
      for (var i = 1; i <= needed; i += 1) {
        var written = typedValue(String(i));
        if (written) {
          variables[String(i)] = written;
          continue;
        }
        var field = String((extraInputs[String(i)] && extraInputs[String(i)].value) || "").trim();
        if (!field) {
          err.textContent = "Choose a lead detail for {{" + i + "}}, or type a value.";
          return;
        }
        variableFields[String(i)] = field;
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
        variable_fields: variableFields,
        header_variables: headerVariables,
        button_variables: buttonVariables,
        header_media_token: kind && media ? media.token : "",
        lead_ai: !!leadAiBox.checked,
        lead_ai_playbook: leadAiBox.checked ? (scriptSelect.value || "general") : ""
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
          var queued = Number(data.queued || 0);
          var msg = "Queued " + queued + " WhatsApp message" + (queued === 1 ? "" : "s") + ".";
          var skippedNote = skipSentence(data);
          if (skippedNote) {
            msg += " " + skippedNote;
          }
          if (data.lead_ai) {
            msg += " Replies will show in Lead AI.";
          }
          notify(msg, true);
          closeStudio();
        })
        .catch(function (e) {
          busy = false;
          applySendState();
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
          mediaBox,
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
            "Type a value to send the same words to everyone. Leave it blank to use the detail you picked. An empty detail is sent as ?."
        }),
        el("div", { className: "a7-lwa-actions" }, [
          leadAiToggle,
          scriptWrap,
          scriptNote,
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
    studioCleanup = dropMedia;
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
    var count = document.createElement("span");
    count.className = "a7-lwa-count";
    btn.appendChild(count);
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

  function mountButton(allowFallback) {
    ensureStyles();
    var existing = document.querySelector("." + BTN_CLASS);
    var host = findTitleHost();
    if (existing && isWellPlaced(existing)) {
      // Re-home a fallback-bar button once the real toolbar has rendered.
      if (!(host && existing.closest(".a7-lwa-topbar"))) {
        return existing;
      }
    }
    dropOldButtons();
    var btn = makeButton();
    var slot = wrapButton(btn);
    if (host) {
      if (host.firstChild) {
        host.insertBefore(slot, host.firstChild);
      } else {
        host.appendChild(slot);
      }
      return btn;
    }
    if (!allowFallback) {
      return null;
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
    return btn;
  }

  function setButtonState(btn, count) {
    var idle = count < 1;
    if (btn.classList.contains("a7-lwa-idle") !== idle) {
      btn.classList.toggle("a7-lwa-idle", idle);
    }
    var aria = idle ? "true" : "false";
    if (btn.getAttribute("aria-disabled") !== aria) {
      btn.setAttribute("aria-disabled", aria);
    }
    var title = idle
      ? "Tick one or more " + NOUN + " first"
      : "Send a WhatsApp template to " + count + " " + (count === 1 ? NOUN_ONE : NOUN);
    if (btn.title !== title) {
      btn.title = title;
    }
    var badge = btn.querySelector(".a7-lwa-count");
    var text = idle ? "" : String(count);
    if (badge && badge.textContent !== text) {
      badge.textContent = text;
    }
  }

  function syncButton() {
    var count = 0;
    try {
      count = selectedLeadIds().length;
    } catch (e) {
      count = 0;
    }
    // Always on the toolbar; active (with a count) once something is ticked.
    var btn = mountButton(count > 0);
    if (!btn) {
      return;
    }
    setButtonState(btn, count);
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
