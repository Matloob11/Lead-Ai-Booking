(function () {
  if (window.A7_3CX_CLICK_TO_CALL_LOADED) {
    return;
  }
  window.A7_3CX_CLICK_TO_CALL_LOADED = true;

  var CLICK_TO_CALL_ENABLED = false;
  var LIVE_CALL_MONITOR_ENABLED = false;
  var ENDPOINT = "/bitrix/tools/a7_3cx_click_to_call.php?action=manual";
  var RECORDING_SYNC_ENDPOINT = "/bitrix/tools/a7_3cx_click_to_call.php?action=recording-agent-ping";
  var RECORDING_PLAY_ENDPOINT = "/bitrix/tools/a7_3cx_click_to_call.php?action=recording&id=";
  var AI_SCORE_ENDPOINT = "/bitrix/tools/a7_3cx_ai_recording_analyzer.php?action=score&id=";
  var LIVE_CALLS_ENDPOINT = "/bitrix/tools/a7_3cx_click_to_call.php?action=live-calls-ping";
  var RECORDING_SYNC_LOCK_KEY = "A7_3CX_RECORDING_SYNC_MONITOR_LOCK";
  var LIVE_CALLS_LOCK_KEY = "A7_3CX_LIVE_CALL_MONITOR_LOCK";
  var RECORDING_SYNC_TAB_ID = String(Date.now()) + ":" + String(Math.random()).slice(2);
  var LIVE_CALLS_TAB_ID = String(Date.now()) + ":" + String(Math.random()).slice(2);
  var RECORDING_SYNC_POLL_MS = 300000;
  var RECORDING_SYNC_LOCK_TTL_MS = 285000;
  var LIVE_CALLS_POLL_MS = 60000;
  var LIVE_CALLS_LOCK_TTL_MS = 25000;
  var A7_FETCH_TIMEOUT_MS = 8000;
  var AI_SCORE_CACHE = {};
  var AI_SCORE_DETAIL_CACHE = {};
  var PHONE_RE = /(?:\+?\d[\d\s().-]{5,}\d)/;
  var PHONE_GLOBAL_RE = /(?:\+?\d[\d\s().-]{5,}\d)/g;
  var ALLOWED_PHONE_LABELS = [
    "phone",
    "work phone",
    "work phone number",
    "registered buyer phone",
    "secondary phone",
    "secondary phone number",
    "seller phone number",
    "tenant phone",
    "tenant secondary phone",
    "owner phone",
    "owner secondary phone",
    "phone owner data",
    "phone (owner data)"
  ];

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
      console[ok === false ? "warn" : "log"]("[A7 3CX]", message);
    }
  }

  function cleanPhone(value) {
    value = String(value || "").replace(/\u00a0/g, " ").trim();
    var match = value.match(PHONE_RE);
    if (!match) {
      return "";
    }
    var phone = match[0].replace(/[^\d+]/g, "");
    if (phone.indexOf("+") > 0) {
      phone = phone.replace(/\+/g, "");
    }
    return phone;
  }

  function phoneKey(phone) {
    var digits = String(phone || "").replace(/\D/g, "");
    if (digits.length > 10) {
      return digits.slice(-10);
    }
    return digits;
  }

  function normalizeLabel(text) {
    return String(text || "")
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ")
      .replace(/[:：]/g, "")
      .trim()
      .toLowerCase();
  }

  function isAllowedPhoneLabel(text) {
    var label = normalizeLabel(text);
    if (!label) {
      return false;
    }

    for (var i = 0; i < ALLOWED_PHONE_LABELS.length; i += 1) {
      if (label === ALLOWED_PHONE_LABELS[i] || label.indexOf(ALLOWED_PHONE_LABELS[i]) !== -1) {
        return true;
      }
    }
    return false;
  }

  function extractPhones(text) {
    var out = [];
    var seen = {};
    var source = String(text || "");
    var matches = source.match(PHONE_GLOBAL_RE) || [];

    for (var i = 0; i < matches.length; i += 1) {
      var phone = cleanPhone(matches[i]);
      var key = phoneKey(phone);
      if (phone && key && !seen[key]) {
        seen[key] = true;
        out.push(phone);
      }
    }

    return out;
  }

  function addPhoneCandidate(candidates, phone, label, source) {
    var key = phoneKey(phone);
    if (!key || key.length < 6) {
      return;
    }

    for (var i = 0; i < candidates.length; i += 1) {
      if (candidates[i].key === key) {
        if (!candidates[i].label && label) {
          candidates[i].label = label;
        }
        return;
      }
    }

    candidates.push({
      key: key,
      phone: phone,
      label: String(label || "Phone").replace(/\s+/g, " ").trim(),
      source: source || ""
    });
  }

  function readAttr(el, names) {
    for (var i = 0; i < names.length; i += 1) {
      var value = el && el.getAttribute && el.getAttribute(names[i]);
      var phone = cleanPhone(value);
      if (phone) {
        return phone;
      }
    }
    return "";
  }

  function phoneFromNode(node) {
    if (!node) {
      return "";
    }

    return (
      readAttr(node, ["href", "data-phone", "data-phone-number", "data-value", "title", "aria-label"]) ||
      cleanPhone(node.textContent)
    );
  }

  function labelFromContainer(container) {
    if (!container) {
      return "";
    }

    var labelSelectors = [
      ".ui-entity-editor-block-title-text",
      ".crm-entity-widget-content-block-title",
      ".crm-entity-widget-content-block-field-title",
      ".crm-entity-widget-content-block-label",
      ".main-grid-cell-head-container",
      ".field-name",
      ".label",
      "label"
    ];

    for (var i = 0; i < labelSelectors.length; i += 1) {
      var labelNode = container.querySelector && container.querySelector(labelSelectors[i]);
      var labelText = labelNode && labelNode.textContent ? labelNode.textContent : "";
      if (labelText && isAllowedPhoneLabel(labelText)) {
        return labelText;
      }
    }

    var text = (container.textContent || "").replace(/\s+/g, " ").trim();
    if (text.length <= 180 && isAllowedPhoneLabel(text)) {
      for (var j = 0; j < ALLOWED_PHONE_LABELS.length; j += 1) {
        if (normalizeLabel(text).indexOf(ALLOWED_PHONE_LABELS[j]) !== -1) {
          return ALLOWED_PHONE_LABELS[j].replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
        }
      }
    }

    return "";
  }

  function closestPhoneRow(node) {
    if (!node || !node.closest) {
      return null;
    }

    return node.closest([
      ".ui-entity-editor-content-block",
      ".crm-entity-widget-content-block",
      ".crm-entity-widget-client-box",
      ".crm-entity-widget-client-contact",
      ".crm-entity-widget-content-block-inner",
      ".main-grid-row",
      "tr",
      "td",
      "li",
      "div"
    ].join(","));
  }

  function collectAllowedPhoneCandidates(root) {
    root = root || document;
    var candidates = [];

    var explicitNodes = root.querySelectorAll ? root.querySelectorAll([
      "a[href^='tel:']",
      "a[href^='callto:']",
      "a[href^='sip:']",
      "[data-phone]",
      "[data-phone-number]",
      "a.crm-entity-phone-number",
      ".crm-entity-phone-number",
      ".crm-entity-widget-content-block-phone",
      ".crm-entity-widget-client-contact-phone"
    ].join(",")) : [];

    for (var i = 0; i < explicitNodes.length; i += 1) {
      var explicitNode = explicitNodes[i];
      if (explicitNode.closest && explicitNode.closest(".a7-3cx-ignore")) {
        continue;
      }

      var phone = phoneFromNode(explicitNode);
      var row = closestPhoneRow(explicitNode);
      var label = labelFromContainer(row) || labelFromContainer(explicitNode) || "Phone";
      if (phone) {
        addPhoneCandidate(candidates, phone, label, "explicit");
      }
    }

    var nodes = root.querySelectorAll ? root.querySelectorAll("div, span, p, td, tr, li") : [];
    var maxNodes = Math.min(nodes.length, 3000);
    for (var j = 0; j < maxNodes; j += 1) {
      var node = nodes[j];
      if (!node || (node.closest && node.closest(".a7-3cx-ignore"))) {
        continue;
      }

      var text = (node.textContent || "").replace(/\s+/g, " ").trim();
      if (text.length < 8 || text.length > 260 || !PHONE_RE.test(text)) {
        continue;
      }

      var allowedLabel = labelFromContainer(node);
      if (!allowedLabel && !isAllowedPhoneLabel(text)) {
        continue;
      }

      var phones = extractPhones(text);
      for (var k = 0; k < phones.length; k += 1) {
        addPhoneCandidate(candidates, phones[k], allowedLabel || "Phone", "allowed-field");
      }
    }

    return candidates;
  }

  function candidatesFromClickedAllowedField(target) {
    var row = closestPhoneRow(target);
    if (!row) {
      return [];
    }

    var text = (row.textContent || "").replace(/\s+/g, " ").trim();
    if (text.length > 260 || !PHONE_RE.test(text)) {
      return [];
    }

    var label = labelFromContainer(row);
    if (!label && !isAllowedPhoneLabel(text)) {
      return [];
    }

    var candidates = [];
    var phones = extractPhones(text);
    for (var i = 0; i < phones.length; i += 1) {
      addPhoneCandidate(candidates, phones[i], label || "Phone", "clicked-allowed-field");
    }
    return candidates;
  }

  function findCallCandidatesFromClick(target) {
    if (!target || target.closest && target.closest(".a7-3cx-ignore")) {
      return [];
    }

    var clickedTopCallButton = target.closest && target.closest("button.ui-btn-icon-phone-call, .ui-btn-icon-phone-call");

    // Keep this intentionally narrow. Broad container matching or reading
    // target.textContent can start a call when the user clicks anywhere in a
    // CRM card that happens to contain a phone number.
    var explicitPhoneSelector = [
      "a[href^='tel:']",
      "a[href^='callto:']",
      "a[href^='sip:']",
      "[data-phone]",
      "[data-phone-number]",
      "a.crm-entity-phone-number",
      ".crm-entity-phone-number",
      ".crm-entity-phone",
      ".crm-entity-widget-content-block-phone",
      ".crm-entity-widget-client-contact-phone"
    ].join(",");

    var explicitPhoneNode = target.closest && target.closest(explicitPhoneSelector);
    if (explicitPhoneNode) {
      var explicitPhone = phoneFromNode(explicitPhoneNode);
      var explicitCandidates = [];
      if (explicitPhone) {
        addPhoneCandidate(explicitCandidates, explicitPhone, labelFromContainer(closestPhoneRow(explicitPhoneNode)) || "Phone", "clicked-explicit");
      }
      return explicitCandidates;
    }

    if (clickedTopCallButton) {
      return collectAllowedPhoneCandidates(document);
    }

    return candidatesFromClickedAllowedField(target);
  }

  function findPhoneFromClick(target) {
    var candidates = findCallCandidatesFromClick(target);
    return candidates.length ? candidates[0].phone : "";
  }

  function entityFromLocation() {
    var match = String(location.pathname).match(/\/crm\/(lead|deal|contact|company)\/details\/(\d+)\//i);
    if (match) {
      var entityType = match[1].toLowerCase();
      var ownerTypes = { lead: "1", deal: "2", contact: "3", company: "4" };
      return {
        entityType: entityType,
        entityId: match[2],
        ownerTypeId: ownerTypes[entityType] || "",
        ownerId: match[2]
      };
    }
    match = String(location.pathname).match(/\/crm\/type\/1042\/details\/(\d+)\//i);
    if (match) {
      return {
        entityType: "",
        entityId: "",
        ownerTypeId: "1042",
        ownerId: match[1]
      };
    }
    return {
      entityType: "",
      entityId: "",
      ownerTypeId: "",
      ownerId: ""
    };
  }

  function bitrixSessid() {
    try {
      if (window.BX && typeof BX.bitrix_sessid === "function") {
        return BX.bitrix_sessid();
      }
    } catch (e) {}
    return "";
  }

  function fetchWithTimeout(url, options, timeoutMs) {
    options = options || {};
    timeoutMs = timeoutMs || A7_FETCH_TIMEOUT_MS;

    if (!window.AbortController) {
      return fetch(url, options);
    }

    var controller = new AbortController();
    var timer = window.setTimeout(function () {
      controller.abort();
    }, timeoutMs);

    var merged = {};
    Object.keys(options).forEach(function (key) {
      merged[key] = options[key];
    });
    merged.signal = controller.signal;

    return fetch(url, merged).finally(function () {
      window.clearTimeout(timer);
    });
  }

  function ensurePhoneChoiceStyles() {
    if (document.getElementById("a7-3cx-phone-choice-style")) {
      return;
    }

    var style = document.createElement("style");
    style.id = "a7-3cx-phone-choice-style";
    style.textContent = [
      ".a7-3cx-phone-choice{position:fixed;z-index:2147483647;min-width:280px;max-width:360px;background:#fff;border:1px solid #c8d2dc;border-radius:14px;box-shadow:0 12px 34px rgba(15,23,42,.22);font-family:var(--ui-font-family-primary,Arial,sans-serif);overflow:hidden;color:#263238;}",
      ".a7-3cx-phone-choice-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid #e5edf3;font-weight:700;font-size:14px;}",
      ".a7-3cx-phone-choice-close{border:0;background:transparent;color:#8b99a8;font-size:22px;line-height:1;cursor:pointer;padding:0 2px;}",
      ".a7-3cx-phone-choice-list{max-height:320px;overflow:auto;padding:6px;}",
      ".a7-3cx-phone-choice-btn{display:block;width:100%;border:0;background:#fff;text-align:left;border-radius:10px;padding:10px 12px;cursor:pointer;color:#263238;}",
      ".a7-3cx-phone-choice-btn:hover{background:#eef8ff;}",
      ".a7-3cx-phone-choice-label{display:block;font-size:12px;color:#8391a2;margin-bottom:3px;}",
      ".a7-3cx-phone-choice-phone{display:block;font-size:15px;font-weight:700;color:#1c5f91;}"
    ].join("\n");
    document.head.appendChild(style);
  }

  function removePhoneChoice() {
    var existing = document.querySelector(".a7-3cx-phone-choice");
    if (existing && existing.parentNode) {
      existing.parentNode.removeChild(existing);
    }
  }

  function choosePhone(candidates, clientX, clientY) {
    return new Promise(function (resolve) {
      removePhoneChoice();
      ensurePhoneChoiceStyles();

      if (!candidates || !candidates.length) {
        resolve("");
        return;
      }

      if (candidates.length === 1) {
        resolve(candidates[0].phone);
        return;
      }

      var box = document.createElement("div");
      box.className = "a7-3cx-phone-choice a7-3cx-ignore";

      var head = document.createElement("div");
      head.className = "a7-3cx-phone-choice-head";
      head.appendChild(document.createTextNode("Kis number par call karni hai?"));

      var close = document.createElement("button");
      close.type = "button";
      close.className = "a7-3cx-phone-choice-close";
      close.innerHTML = "&times;";
      head.appendChild(close);
      box.appendChild(head);

      var list = document.createElement("div");
      list.className = "a7-3cx-phone-choice-list";
      for (var i = 0; i < candidates.length; i += 1) {
        (function (candidate) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "a7-3cx-phone-choice-btn";

          var label = document.createElement("span");
          label.className = "a7-3cx-phone-choice-label";
          label.textContent = candidate.label || "Phone";
          btn.appendChild(label);

          var phone = document.createElement("span");
          phone.className = "a7-3cx-phone-choice-phone";
          phone.textContent = candidate.phone;
          btn.appendChild(phone);

          btn.addEventListener("click", function () {
            removePhoneChoice();
            resolve(candidate.phone);
          });
          list.appendChild(btn);
        })(candidates[i]);
      }
      box.appendChild(list);

      function cancel() {
        removePhoneChoice();
        resolve("");
      }

      close.addEventListener("click", cancel);
      document.addEventListener("keydown", function onKeydown(event) {
        if (event.key === "Escape") {
          document.removeEventListener("keydown", onKeydown, true);
          cancel();
        }
      }, true);

      document.body.appendChild(box);

      var left = Math.max(12, Math.min(window.innerWidth - box.offsetWidth - 12, Number(clientX || 0) - 20));
      var top = Math.max(12, Math.min(window.innerHeight - box.offsetHeight - 12, Number(clientY || 0) + 16));
      box.style.left = left + "px";
      box.style.top = top + "px";
    });
  }

  function ensureRecordingPlayerStyles() {
    if (document.getElementById("a7-3cx-recording-player-style")) {
      return;
    }

    var style = document.createElement("style");
    style.id = "a7-3cx-recording-player-style";
    style.textContent = [
      ".a7-3cx-recording-card{margin:4px 0 2px;padding:0;background:#fff;color:#263238;font-family:var(--ui-font-family-primary,var(--ui-font-family-helvetica));}",
      ".a7-3cx-recording-header{display:flex;align-items:center;gap:12px;margin:0 0 14px;}",
      ".a7-3cx-recording-call-title{font-size:18px;line-height:22px;font-weight:600;color:#111827;}",
      ".a7-3cx-recording-time{margin-left:auto;font-size:16px;color:#9aa4b2;font-weight:400;white-space:nowrap;}",
      ".a7-3cx-recording-body{display:flex;gap:18px;align-items:flex-start;}",
      ".a7-3cx-recording-art{position:relative;width:86px;height:86px;min-width:86px;border-radius:14px;background:#dff8ff;overflow:hidden;display:flex;align-items:center;justify-content:center;}",
      ".a7-3cx-recording-art-bars{position:absolute;left:16px;right:16px;bottom:22px;height:40px;display:flex;align-items:flex-end;gap:5px;}",
      ".a7-3cx-recording-art-bars i{display:block;width:4px;border-radius:5px;background:#27c0ef;opacity:.85;}",
      ".a7-3cx-recording-art-bars i:nth-child(1){height:28px}.a7-3cx-recording-art-bars i:nth-child(2){height:40px}.a7-3cx-recording-art-bars i:nth-child(3){height:32px}.a7-3cx-recording-art-bars i:nth-child(4){height:48px}.a7-3cx-recording-art-bars i:nth-child(5){height:30px}.a7-3cx-recording-art-bars i:nth-child(6){height:38px}",
      ".a7-3cx-recording-art-play{position:relative;z-index:1;width:50px;height:50px;border-radius:50%;background:rgba(255,255,255,.88);box-shadow:0 2px 8px rgba(31,120,160,.18);display:flex;align-items:center;justify-content:center;color:#23bdf1;font-size:22px;line-height:1;}",
      ".a7-3cx-recording-content{flex:1;min-width:0;}",
      ".a7-3cx-recording-row{display:grid;grid-template-columns:138px 1fr;gap:12px;margin:0 0 6px;align-items:baseline;}",
      ".a7-3cx-recording-label{color:#8b99a8;font-size:15px;line-height:20px;}",
      ".a7-3cx-recording-value{color:#2f3f52;font-size:15px;line-height:20px;font-weight:500;word-break:break-word;}",
      ".a7-3cx-recording-pill{display:inline-flex;align-items:center;border-radius:18px;background:#17bee8;color:#fff;font-weight:700;font-size:13px;line-height:18px;padding:4px 16px;margin-top:2px;}",
      ".a7-3cx-recording-score-row{display:none;}",
      ".a7-3cx-recording-score-row.is-visible{display:grid;}",
      ".a7-3cx-recording-score-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}",
      ".a7-3cx-recording-score-badge{display:inline-flex;align-items:center;min-height:26px;border-radius:16px;background:#eef8f2;color:#207246;border:1px solid #bfe8cd;font-weight:700;font-size:13px;line-height:16px;padding:4px 12px;}",
      ".a7-3cx-recording-score-meta{color:#8b99a8;font-size:12px;line-height:16px;}",
      ".a7-3cx-recording-score-btn{display:inline-flex;align-items:center;justify-content:center;height:28px;border-radius:16px;border:1px solid #2ebdeb;background:#fff;color:#168acb;font-size:12px;font-weight:700;padding:0 12px;cursor:pointer;}",
      ".a7-3cx-recording-score-btn[disabled]{opacity:.65;cursor:wait;}",
      ".a7-3cx-recording-score-btn:hover{background:#eefaff;}",
      ".a7-3cx-recording-player{display:grid;grid-template-columns:40px 1fr auto;gap:10px;align-items:center;margin:16px 0 10px;}",
      ".a7-3cx-recording-play{width:36px;height:36px;border:0;border-radius:50%;background:#2ebdeb;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;line-height:1;box-shadow:none;}",
      ".a7-3cx-recording-play:hover{background:#21addc;}",
      ".a7-3cx-recording-progress-wrap{min-width:0;}",
      ".a7-3cx-recording-range{width:100%;height:5px;accent-color:#35c2ee;cursor:pointer;vertical-align:middle;}",
      ".a7-3cx-recording-times{display:flex;justify-content:space-between;margin-top:5px;color:#9aa4b2;font-size:12px;line-height:16px;}",
      ".a7-3cx-recording-speed{border:0;background:transparent;color:#9aa4b2;font-weight:600;font-size:14px;white-space:nowrap;cursor:pointer;}",
      ".a7-3cx-recording-sub{margin-top:8px;color:#8b99a8;font-size:14px;line-height:20px;}",
      ".a7-3cx-recording-actions{display:flex;gap:12px;align-items:center;margin-top:14px;}",
      ".a7-3cx-recording-call-btn{display:inline-flex;align-items:center;justify-content:center;min-width:118px;height:34px;border-radius:18px;border:1px solid #c6d0da;background:#fff;color:#526274;font-size:13px;font-weight:600;text-transform:uppercase;text-decoration:none;}",
      ".a7-3cx-recording-open{color:#168acb;text-decoration:none;font-size:13px;}",
      ".a7-3cx-recording-open:hover{text-decoration:underline;}",
      ".a7-3cx-ai-modal-backdrop{position:fixed;inset:0;z-index:2147483000;background:rgba(15,23,42,.42);display:flex;align-items:center;justify-content:center;padding:24px;}",
      ".a7-3cx-ai-modal{width:min(760px,calc(100vw - 32px));max-height:min(760px,calc(100vh - 32px));overflow:auto;background:#fff;border-radius:10px;box-shadow:0 24px 70px rgba(15,23,42,.28);color:#1f2937;font-family:var(--ui-font-family-primary,var(--ui-font-family-helvetica));}",
      ".a7-3cx-ai-modal-head{position:sticky;top:0;z-index:1;background:#fff;display:flex;align-items:center;gap:12px;padding:18px 22px;border-bottom:1px solid #e7edf3;}",
      ".a7-3cx-ai-modal-title{font-size:20px;line-height:26px;font-weight:700;color:#111827;}",
      ".a7-3cx-ai-modal-close{margin-left:auto;width:34px;height:34px;border:0;border-radius:50%;background:#eef3f8;color:#526274;font-size:22px;line-height:1;cursor:pointer;}",
      ".a7-3cx-ai-modal-body{padding:18px 22px 22px;}",
      ".a7-3cx-ai-score-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 16px;}",
      ".a7-3cx-ai-score-box{border:1px solid #e0e8f0;border-radius:8px;padding:12px;background:#f8fbfd;}",
      ".a7-3cx-ai-score-label{color:#7b8794;font-size:12px;line-height:16px;text-transform:uppercase;font-weight:700;}",
      ".a7-3cx-ai-score-value{margin-top:4px;color:#0f172a;font-size:24px;line-height:30px;font-weight:800;}",
      ".a7-3cx-ai-section{margin-top:16px;}",
      ".a7-3cx-ai-section h4{margin:0 0 8px;color:#111827;font-size:14px;line-height:20px;font-weight:800;}",
      ".a7-3cx-ai-section p{margin:0;color:#334155;font-size:14px;line-height:21px;white-space:pre-wrap;}",
      ".a7-3cx-ai-list{margin:0;padding-left:18px;color:#334155;font-size:14px;line-height:21px;}",
      ".a7-3cx-ai-kv{display:grid;grid-template-columns:170px 1fr;gap:8px 12px;color:#334155;font-size:14px;line-height:20px;}",
      ".a7-3cx-ai-kv b{color:#64748b;font-weight:700;}",
      ".a7-3cx-ai-transcript{margin:0;max-height:300px;overflow:auto;border:1px solid #e0e8f0;border-radius:8px;background:#f8fbfd;padding:12px;color:#172033;font-size:13px;line-height:20px;white-space:pre-wrap;}",
      "@media(max-width:640px){.a7-3cx-recording-body{gap:12px}.a7-3cx-recording-row{grid-template-columns:112px 1fr}.a7-3cx-ai-score-grid{grid-template-columns:1fr}.a7-3cx-ai-kv{grid-template-columns:1fr}.a7-3cx-ai-modal-backdrop{padding:12px}}",
      ".a7-3cx-recording-native-audio{display:none;}"
    ].join("\n");
    document.head.appendChild(style);
  }

  function parseRecordingText(text) {
    text = String(text || "").replace(/\s+/g, " ").trim();
    if (text.indexOf("3CX recording synced") === -1) {
      return null;
    }

    var id = (text.match(/Recording\s*ID:\s*(\d+)/i) || [])[1] || "";
    if (!id) {
      return null;
    }

    return {
      id: id,
      callType: (text.match(/Call\s*type:\s*([A-Za-z]+)/i) || [])[1] || "",
      extension: (text.match(/3CX\s*extension:\s*(\d+)/i) || [])[1] || "",
      phone: ((text.match(/Phone:\s*(.*?)(?:Start:|$)/i) || [])[1] || "").trim(),
      start: ((text.match(/Start:\s*([0-9T:+-]+)/i) || [])[1] || "").trim()
    };
  }

  function recordingIdFromPlaybackLink(node) {
    if (!node || !node.querySelectorAll || !window.location || !window.location.href) {
      return "";
    }

    var pageUrl = null;
    try {
      pageUrl = new URL(window.location.href);
    } catch (ignored) {
      return "";
    }

    var links = node.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i += 1) {
      var rawHref = links[i].getAttribute("href") || "";
      var parsed = null;
      try {
        parsed = new URL(rawHref, pageUrl.href);
      } catch (ignored) {
        continue;
      }

      var actions = parsed.searchParams.getAll("action");
      var ids = parsed.searchParams.getAll("id");
      var signatures = parsed.searchParams.getAll("sig");
      if (
        parsed.origin !== pageUrl.origin ||
        parsed.pathname !== "/bitrix/tools/a7_3cx_click_to_call.php" ||
        parsed.username ||
        parsed.password ||
        parsed.hash ||
        actions.length !== 1 ||
        actions[0] !== "recording" ||
        ids.length !== 1 ||
        !/^[1-9]\d*$/.test(ids[0]) ||
        !Number.isSafeInteger(Number(ids[0])) ||
        signatures.length > 1 ||
        (signatures.length === 1 && !/^[a-f0-9]{64}$/.test(signatures[0]))
      ) {
        continue;
      }

      var allowedQuery = true;
      parsed.searchParams.forEach(function (_value, key) {
        if (key !== "action" && key !== "id" && key !== "sig") {
          allowedQuery = false;
        }
      });
      if (allowedQuery) {
        return ids[0];
      }
    }

    return "";
  }

  function maskedRecordingPhone(text) {
    var phone = cleanPhone(text);
    var digits = String(phone || "").replace(/\D/g, "");
    if (digits.length < 8) {
      return "";
    }
    return (phone.charAt(0) === "+" ? "+" : "") + digits.slice(0, 3) + "***" + digits.slice(-4);
  }

  function parseHistoricalRecordingNode(node, text) {
    text = String(text || "").replace(/\s+/g, " ").trim();
    if (
      text.indexOf("3CX recording stored securely") === -1 ||
      text.indexOf("Secure recording archive") === -1
    ) {
      return null;
    }

    var id = recordingIdFromPlaybackLink(node);
    if (!id) {
      return null;
    }

    var callType = "";
    if (/Outbound call processed/i.test(text)) {
      callType = "OutboundExternal";
    } else if (/Inbound call processed/i.test(text)) {
      callType = "InboundExternal";
    }

    var customerText = ((text.match(/Customer\s+(.*?)(?:3CX recording stored securely|$)/i) || [])[1] || "").trim();
    return {
      id: id,
      callType: callType,
      extension: "",
      phone: maskedRecordingPhone(customerText),
      start: ""
    };
  }

  function parseRecordingNode(node, normalizedText) {
    var text = normalizedText || String((node && node.textContent) || "").replace(/\s+/g, " ").trim();
    return parseRecordingText(text) || parseHistoricalRecordingNode(node, text);
  }

  function appendText(parent, text) {
    parent.appendChild(document.createTextNode(text));
  }

  function formatSeconds(seconds) {
    seconds = Number(seconds || 0);
    if (!isFinite(seconds) || seconds < 0) {
      seconds = 0;
    }
    var minutes = Math.floor(seconds / 60);
    var rest = Math.floor(seconds % 60);
    return String(minutes) + ":" + (rest < 10 ? "0" : "") + String(rest);
  }

  function formatDurationLong(seconds) {
    seconds = Number(seconds || 0);
    if (!isFinite(seconds) || seconds <= 0) {
      return "";
    }
    var minutes = Math.floor(seconds / 60);
    var rest = Math.floor(seconds % 60);
    var parts = [];
    if (minutes > 0) {
      parts.push(String(minutes).padStart(2, "0") + " min");
    }
    parts.push(String(rest).padStart(2, "0") + " sec");
    return parts.join(" ");
  }

  function formatStartTime(value) {
    if (!value) {
      return "";
    }
    var date = new Date(value);
    if (isNaN(date.getTime())) {
      return "";
    }
    try {
      return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
    } catch (e) {
      return "";
    }
  }

  function callTitle(callType) {
    callType = String(callType || "").toLowerCase();
    if (callType.indexOf("outbound") !== -1) {
      return "Outbound call processed";
    }
    if (callType.indexOf("inbound") !== -1) {
      return "Inbound call processed";
    }
    return "3CX call recording";
  }

  function prettyCallType(callType) {
    callType = String(callType || "").trim();
    return callType
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/^./, function (ch) { return ch.toUpperCase(); }) || "-";
  }

  function makeInfoRow(label, value) {
    var row = document.createElement("div");
    row.className = "a7-3cx-recording-row";

    var labelNode = document.createElement("div");
    labelNode.className = "a7-3cx-recording-label";
    labelNode.textContent = label;
    row.appendChild(labelNode);

    var valueNode = document.createElement("div");
    valueNode.className = "a7-3cx-recording-value";
    valueNode.textContent = value || "-";
    row.appendChild(valueNode);

    return row;
  }

  function makeRecordingArt() {
    var art = document.createElement("div");
    art.className = "a7-3cx-recording-art";

    var bars = document.createElement("div");
    bars.className = "a7-3cx-recording-art-bars";
    for (var i = 0; i < 6; i += 1) {
      bars.appendChild(document.createElement("i"));
    }
    art.appendChild(bars);

    var play = document.createElement("div");
    play.className = "a7-3cx-recording-art-play";
    play.innerHTML = "&#9658;";
    art.appendChild(play);

    return art;
  }

  function makeScoreRow() {
    var row = document.createElement("div");
    row.className = "a7-3cx-recording-row a7-3cx-recording-score-row";

    var label = document.createElement("div");
    label.className = "a7-3cx-recording-label";
    label.textContent = "AI score";
    row.appendChild(label);

    var value = document.createElement("div");
    value.className = "a7-3cx-recording-value";
    row.appendChild(value);

    return row;
  }

  function scoreNumber(score, key) {
    var scores = score && score.scores ? score.scores : {};
    var value = Number(scores[key] || 0);
    if (!isFinite(value) || value < 0) {
      return 0;
    }
    return Math.min(100, Math.round(value));
  }

  function fetchAiScore(recordingId, includeDetails) {
    recordingId = String(recordingId || "");
    if (!recordingId) {
      return Promise.resolve(null);
    }
    var cache = includeDetails ? AI_SCORE_DETAIL_CACHE : AI_SCORE_CACHE;
    if (Object.prototype.hasOwnProperty.call(cache, recordingId)) {
      return Promise.resolve(cache[recordingId]);
    }

    var endpoint = AI_SCORE_ENDPOINT + encodeURIComponent(recordingId);
    var entity = entityFromLocation();
    if (
      (entity.ownerTypeId === "1" || entity.ownerTypeId === "1042") &&
      entity.ownerId
    ) {
      endpoint += "&ownerTypeId=" + encodeURIComponent(entity.ownerTypeId);
      endpoint += "&ownerId=" + encodeURIComponent(entity.ownerId);
    }
    if (!includeDetails) {
      endpoint += "&summary=1";
    }
    endpoint += "&cb=" + Date.now();

    return fetchWithTimeout(endpoint, {
      credentials: "same-origin"
    }, 5000)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("AI score HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (payload) {
        var score = payload && payload.success && payload.found && payload.score ? payload.score : null;
        if (score) {
          cache[recordingId] = score;
        } else {
          delete cache[recordingId];
        }
        return score;
      })
      .catch(function (error) {
        if (window.console && console.debug) {
          console.debug("[A7 3CX] AI score unavailable", error && error.message ? error.message : error);
        }
        return null;
      });
  }

  function appendModalSection(parent, titleText, bodyText) {
    bodyText = String(bodyText || "").trim();
    if (!bodyText) {
      return;
    }

    var section = document.createElement("section");
    section.className = "a7-3cx-ai-section";
    var title = document.createElement("h4");
    title.textContent = titleText;
    section.appendChild(title);
    var body = document.createElement("p");
    body.textContent = bodyText;
    section.appendChild(body);
    parent.appendChild(section);
  }

  function appendModalList(parent, titleText, items) {
    if (!items || !items.length) {
      return;
    }

    var section = document.createElement("section");
    section.className = "a7-3cx-ai-section";
    var title = document.createElement("h4");
    title.textContent = titleText;
    section.appendChild(title);
    var list = document.createElement("ul");
    list.className = "a7-3cx-ai-list";
    for (var i = 0; i < items.length; i += 1) {
      var item = document.createElement("li");
      item.textContent = String(items[i] || "");
      list.appendChild(item);
    }
    section.appendChild(list);
    parent.appendChild(section);
  }

  function appendModalKeyValues(parent, titleText, values) {
    if (!values || typeof values !== "object") {
      return;
    }

    var keys = Object.keys(values).filter(function (key) {
      return values[key] !== null && values[key] !== "";
    });
    if (!keys.length) {
      return;
    }

    var section = document.createElement("section");
    section.className = "a7-3cx-ai-section";
    var title = document.createElement("h4");
    title.textContent = titleText;
    section.appendChild(title);
    var box = document.createElement("div");
    box.className = "a7-3cx-ai-kv";
    for (var i = 0; i < keys.length; i += 1) {
      var key = document.createElement("b");
      key.textContent = keys[i];
      var value = document.createElement("span");
      value.textContent = String(values[keys[i]]);
      box.appendChild(key);
      box.appendChild(value);
    }
    section.appendChild(box);
    parent.appendChild(section);
  }

  function addScoreBox(parent, label, value) {
    var box = document.createElement("div");
    box.className = "a7-3cx-ai-score-box";
    var labelNode = document.createElement("div");
    labelNode.className = "a7-3cx-ai-score-label";
    labelNode.textContent = label;
    var valueNode = document.createElement("div");
    valueNode.className = "a7-3cx-ai-score-value";
    valueNode.textContent = String(value) + "%";
    box.appendChild(labelNode);
    box.appendChild(valueNode);
    parent.appendChild(box);
  }

  function openAiScoreModal(score) {
    if (!score) {
      return;
    }

    var old = document.querySelector(".a7-3cx-ai-modal-backdrop");
    if (old && old.parentNode) {
      old.parentNode.removeChild(old);
    }

    var backdrop = document.createElement("div");
    backdrop.className = "a7-3cx-ai-modal-backdrop a7-3cx-ignore";
    var modal = document.createElement("div");
    modal.className = "a7-3cx-ai-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");

    var head = document.createElement("div");
    head.className = "a7-3cx-ai-modal-head";
    var title = document.createElement("div");
    title.className = "a7-3cx-ai-modal-title";
    title.textContent = "AI Call Score";
    head.appendChild(title);
    var close = document.createElement("button");
    close.type = "button";
    close.className = "a7-3cx-ai-modal-close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "x";
    head.appendChild(close);
    modal.appendChild(head);

    var body = document.createElement("div");
    body.className = "a7-3cx-ai-modal-body";
    var grid = document.createElement("div");
    grid.className = "a7-3cx-ai-score-grid";
    addScoreBox(grid, "Overall", scoreNumber(score, "overall"));
    addScoreBox(grid, "Agent", scoreNumber(score, "agent"));
    addScoreBox(grid, "Client", scoreNumber(score, "client"));
    body.appendChild(grid);

    appendModalKeyValues(body, "Call info", {
      Outcome: score.callOutcome || "-",
      Qualified: score.qualified ? "Yes" : "No",
      Broker: score.brokerFlag ? "Yes" : "No"
    });
    appendModalSection(body, "Summary", score.summary);
    appendModalSection(body, "Next action", score.nextAction);
    appendModalKeyValues(body, "Detected details", score.details);
    appendModalList(body, "Agent strengths", score.agentStrengths || []);
    appendModalList(body, "Agent improvements", score.agentImprovements || []);
    appendModalList(body, "Client signals", score.clientSignals || []);
    appendModalList(body, "Missing questions", score.missingQuestions || []);
    appendModalSection(body, "Transcript quality", score.transcriptQuality);

    if (score.transcript) {
      var transcriptSection = document.createElement("section");
      transcriptSection.className = "a7-3cx-ai-section";
      var transcriptTitle = document.createElement("h4");
      transcriptTitle.textContent = "Transcript";
      transcriptSection.appendChild(transcriptTitle);
      var transcript = document.createElement("pre");
      transcript.className = "a7-3cx-ai-transcript";
      transcript.textContent = String(score.transcript || "");
      transcriptSection.appendChild(transcript);
      body.appendChild(transcriptSection);
    }

    modal.appendChild(body);
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);

    function closeModal() {
      document.removeEventListener("keydown", onKeyDown, true);
      if (backdrop.parentNode) {
        backdrop.parentNode.removeChild(backdrop);
      }
    }

    function onKeyDown(event) {
      if (event.key === "Escape") {
        closeModal();
      }
    }

    close.addEventListener("click", closeModal);
    backdrop.addEventListener("click", function (event) {
      if (event.target === backdrop) {
        closeModal();
      }
    });
    document.addEventListener("keydown", onKeyDown, true);
  }

  function renderAiScoreRow(row, score) {
    if (!row || !score) {
      return;
    }

    var value = row.querySelector(".a7-3cx-recording-value");
    if (!value) {
      return;
    }
    while (value.firstChild) {
      value.removeChild(value.firstChild);
    }

    var line = document.createElement("div");
    line.className = "a7-3cx-recording-score-line";
    var badge = document.createElement("span");
    badge.className = "a7-3cx-recording-score-badge";
    badge.textContent = "Overall " + scoreNumber(score, "overall") + "%";
    line.appendChild(badge);

    var meta = document.createElement("span");
    meta.className = "a7-3cx-recording-score-meta";
    meta.textContent = "Agent " + scoreNumber(score, "agent") + "% / Client " + scoreNumber(score, "client") + "%";
    line.appendChild(meta);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "a7-3cx-recording-score-btn a7-3cx-ignore";
    button.textContent = "View Score";
    button.addEventListener("click", function () {
      var recordingId = String(score.recordingId || "");
      if (!recordingId) {
        return;
      }
      button.disabled = true;
      button.textContent = "Loading...";
      fetchAiScore(recordingId, true)
        .then(function (fullScore) {
          if (!fullScore) {
            throw new Error("AI score details unavailable");
          }
          openAiScoreModal(fullScore);
          button.disabled = false;
          button.textContent = "View Score";
        })
        .catch(function (error) {
          button.disabled = false;
          button.textContent = "View Score";
          notify(error && error.message ? error.message : "AI score details unavailable", false);
        });
    });
    line.appendChild(button);

    value.appendChild(line);
    row.classList.add("is-visible");
  }

  function renderAiAnalyzeRow(row, recordingId) {
    if (!row) {
      return;
    }

    var value = row.querySelector(".a7-3cx-recording-value");
    if (!value) {
      return;
    }
    while (value.firstChild) {
      value.removeChild(value.firstChild);
    }

    var line = document.createElement("div");
    line.className = "a7-3cx-recording-score-line";

    var meta = document.createElement("span");
    meta.className = "a7-3cx-recording-score-meta";
    meta.textContent = "Queued for automatic AI analysis";
    line.appendChild(meta);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "a7-3cx-recording-score-btn a7-3cx-ignore";
    button.textContent = "Refresh Score";
    button.addEventListener("click", function () {
      button.disabled = true;
      button.textContent = "Checking...";
      meta.textContent = "Checking automatic AI result";
      delete AI_SCORE_CACHE[String(recordingId)];
      delete AI_SCORE_DETAIL_CACHE[String(recordingId)];

      fetchAiScore(recordingId)
        .then(function (score) {
          if (!score) {
            button.disabled = false;
            button.textContent = "Refresh Score";
            meta.textContent = "Queued for automatic AI analysis";
            notify("AI score abhi queue mein hai.", true);
            return;
          }
          renderAiScoreRow(row, score);
          notify("AI score ready hai.", true);
        })
        .catch(function (error) {
          button.disabled = false;
          button.textContent = "Refresh Score";
          meta.textContent = error && error.message ? error.message : "AI score check failed";
          notify(meta.textContent, false);
        });
    });
    line.appendChild(button);

    value.appendChild(line);
    row.classList.add("is-visible");
  }

  function loadAiScoreForRecording(recordingId, row) {
    fetchAiScore(recordingId).then(function (score) {
      if (score) {
        renderAiScoreRow(row, score);
      } else {
        renderAiAnalyzeRow(row, recordingId);
      }
    });
  }

  function setupCustomAudioPlayer(card, audio, range, playButton, currentNode, durationNode, speedNode, subNode) {
    var loadingAudio = false;

    function updateButton() {
      if (loadingAudio) {
        playButton.textContent = "...";
        playButton.setAttribute("aria-label", "Loading 3CX recording");
        return;
      }

      playButton.innerHTML = audio.paused ? "&#9658;" : "&#10074;&#10074;";
      playButton.setAttribute("aria-label", audio.paused ? "Play 3CX recording" : "Pause 3CX recording");
    }

    function updateProgress() {
      var duration = audio.duration || 0;
      var current = audio.currentTime || 0;
      currentNode.textContent = formatSeconds(current);
      if (duration > 0) {
        range.value = String(Math.min(1000, Math.max(0, Math.round((current / duration) * 1000))));
      }
    }

    function updateDuration() {
      var duration = audio.duration || 0;
      durationNode.textContent = duration > 0 ? formatSeconds(duration) : "0:00";
      var longDuration = formatDurationLong(duration);
      if (longDuration) {
        subNode.textContent = "Number Application: 3CX Call Control \u2022 Duration " + longDuration;
      }
      updateProgress();
    }

    function ensurePlayableAudio() {
      if (audio.getAttribute("data-a7-blob-ready") === "1") {
        return Promise.resolve();
      }

      if (!window.URL || !window.Blob || !window.fetch) {
        return Promise.resolve();
      }

      var source = audio.getAttribute("data-a7-original-src") || audio.src;
      loadingAudio = true;
      playButton.disabled = true;
      updateButton();

      return fetchWithTimeout(source + (source.indexOf("?") === -1 ? "?" : "&") + "cb=" + Date.now(), {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store"
      }, 45000)
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Recording HTTP " + response.status);
          }
          return response.blob();
        })
        .then(function (blob) {
          if (!blob || !blob.size) {
            throw new Error("Recording file empty hai");
          }

          if (audio.getAttribute("data-a7-blob-url")) {
            URL.revokeObjectURL(audio.getAttribute("data-a7-blob-url"));
          }

          var blobUrl = URL.createObjectURL(blob);
          audio.src = blobUrl;
          audio.setAttribute("data-a7-blob-url", blobUrl);
          audio.setAttribute("data-a7-blob-ready", "1");
          audio.load();
        })
        .finally(function () {
          loadingAudio = false;
          playButton.disabled = false;
          updateButton();
        });
    }

    function playAudio() {
      if (audio.paused) {
        var allAudio = document.querySelectorAll("audio.a7-3cx-recording-native-audio");
        for (var i = 0; i < allAudio.length; i += 1) {
          if (allAudio[i] !== audio) {
            allAudio[i].pause();
          }
        }
        var promise = audio.play();
        if (promise && typeof promise.catch === "function") {
          promise.catch(function (error) {
            var message = error && error.message ? error.message : "";
            notify("Recording play nahi ho saki. Open in new tab try karain." + (message ? " (" + message + ")" : ""), false);
          });
        }
      } else {
        audio.pause();
      }
    }

    playButton.addEventListener("click", function () {
      if (!audio.paused) {
        audio.pause();
        return;
      }

      ensurePlayableAudio()
        .then(playAudio)
        .catch(function (error) {
          loadingAudio = false;
          playButton.disabled = false;
          updateButton();
          notify(error && error.message ? error.message : "Recording load nahi ho saki. Open in new tab try karain.", false);
        });
    });

    range.addEventListener("input", function () {
      if (!audio.duration) {
        return;
      }
      audio.currentTime = (Number(range.value || 0) / 1000) * audio.duration;
    });

    speedNode.addEventListener("click", function () {
      audio.playbackRate = audio.playbackRate === 1 ? 1.25 : audio.playbackRate === 1.25 ? 1.5 : 1;
      speedNode.textContent = audio.playbackRate.toFixed(audio.playbackRate % 1 ? 2 : 1) + "x";
    });

    audio.addEventListener("loadedmetadata", updateDuration);
    audio.addEventListener("durationchange", updateDuration);
    audio.addEventListener("timeupdate", updateProgress);
    audio.addEventListener("play", updateButton);
    audio.addEventListener("pause", updateButton);
    audio.addEventListener("ended", updateButton);
    audio.addEventListener("error", function () {
      updateButton();
    });
    updateButton();
  }

  function renderRecordingPlayer(target, data) {
    if (!target || !data || !data.id || target.getAttribute("data-a7-recording-id") === data.id) {
      return false;
    }

    ensureRecordingPlayerStyles();
    target.setAttribute("data-a7-recording-id", data.id);
    target.classList.add("a7-3cx-ignore");

    while (target.firstChild) {
      target.removeChild(target.firstChild);
    }

    var card = document.createElement("div");
    card.className = "a7-3cx-recording-card a7-3cx-ignore";
    card.setAttribute("data-recording-id", data.id);

    var header = document.createElement("div");
    header.className = "a7-3cx-recording-header";

    var title = document.createElement("div");
    title.className = "a7-3cx-recording-call-title";
    title.textContent = callTitle(data.callType);
    header.appendChild(title);

    var time = document.createElement("div");
    time.className = "a7-3cx-recording-time";
    time.textContent = formatStartTime(data.start);
    if (time.textContent) {
      header.appendChild(time);
    }
    card.appendChild(header);

    var body = document.createElement("div");
    body.className = "a7-3cx-recording-body";
    body.appendChild(makeRecordingArt());

    var content = document.createElement("div");
    content.className = "a7-3cx-recording-content";
    content.appendChild(makeInfoRow("Customer", data.phone || "3CX customer"));
    content.appendChild(makeInfoRow("3CX extension", data.extension || "-"));

    var typeRow = document.createElement("div");
    typeRow.className = "a7-3cx-recording-row";
    var typeLabel = document.createElement("div");
    typeLabel.className = "a7-3cx-recording-label";
    typeLabel.textContent = "Call type";
    typeRow.appendChild(typeLabel);
    var typeValue = document.createElement("div");
    typeValue.className = "a7-3cx-recording-value";
    var pill = document.createElement("span");
    pill.className = "a7-3cx-recording-pill";
    pill.textContent = prettyCallType(data.callType);
    typeValue.appendChild(pill);
    typeRow.appendChild(typeValue);
    content.appendChild(typeRow);

    var scoreRow = makeScoreRow();
    content.appendChild(scoreRow);
    loadAiScoreForRecording(data.id, scoreRow);

    var audio = document.createElement("audio");
    audio.className = "a7-3cx-recording-native-audio";
    audio.preload = "metadata";
    audio.src = RECORDING_PLAY_ENDPOINT + encodeURIComponent(data.id);
    audio.setAttribute("data-a7-original-src", audio.src);
    content.appendChild(audio);

    var player = document.createElement("div");
    player.className = "a7-3cx-recording-player";

    var playButton = document.createElement("button");
    playButton.type = "button";
    playButton.className = "a7-3cx-recording-play a7-3cx-ignore";
    playButton.innerHTML = "&#9658;";
    player.appendChild(playButton);

    var progressWrap = document.createElement("div");
    progressWrap.className = "a7-3cx-recording-progress-wrap";
    var range = document.createElement("input");
    range.className = "a7-3cx-recording-range a7-3cx-ignore";
    range.type = "range";
    range.min = "0";
    range.max = "1000";
    range.value = "0";
    progressWrap.appendChild(range);

    var times = document.createElement("div");
    times.className = "a7-3cx-recording-times";
    var current = document.createElement("span");
    current.textContent = "0:00";
    var duration = document.createElement("span");
    duration.textContent = "0:00";
    times.appendChild(current);
    times.appendChild(duration);
    progressWrap.appendChild(times);
    player.appendChild(progressWrap);

    var speed = document.createElement("button");
    speed.type = "button";
    speed.className = "a7-3cx-recording-speed a7-3cx-ignore";
    speed.textContent = "1.0x";
    player.appendChild(speed);
    content.appendChild(player);

    var sub = document.createElement("div");
    sub.className = "a7-3cx-recording-sub";
    sub.textContent = "Number Application: 3CX Call Control";
    content.appendChild(sub);

    var actions = document.createElement("div");
    actions.className = "a7-3cx-recording-actions";

    var callBtn = document.createElement("span");
    callBtn.className = "a7-3cx-recording-call-btn";
    callBtn.textContent = "CALL";
    actions.appendChild(callBtn);

    var open = document.createElement("a");
    open.className = "a7-3cx-recording-open a7-3cx-ignore";
    open.href = audio.src;
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = "Open recording in new tab";
    actions.appendChild(open);
    content.appendChild(actions);

    body.appendChild(content);
    card.appendChild(body);

    setupCustomAudioPlayer(card, audio, range, playButton, current, duration, speed, sub);

    target.appendChild(card);
    return true;
  }

  function enhanceRecordingPlayers(root) {
    root = root || document;
    var nodes = root.querySelectorAll ? root.querySelectorAll("div, p, span") : [];
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (!node || node.getAttribute("data-a7-recording-id") || node.closest(".a7-3cx-recording-card")) {
        continue;
      }

      var text = String(node.textContent || "").replace(/\s+/g, " ").trim();
      var isSyncedRecording = text.indexOf("3CX recording synced") !== -1;
      var isHistoricalRecording =
        text.indexOf("3CX recording stored securely") !== -1 &&
        text.indexOf("Secure recording archive") !== -1;
      if (text.length < 20 || text.length > 900 || (!isSyncedRecording && !isHistoricalRecording)) {
        continue;
      }

      var data = parseRecordingNode(node, text);
      if (!data) {
        continue;
      }

      if (document.querySelector(".a7-3cx-recording-card[data-recording-id='" + data.id + "']")) {
        continue;
      }

      renderRecordingPlayer(node, data);
    }
  }

  async function startCall(phone) {
    var entity = entityFromLocation();
    var params = new URLSearchParams();
    params.set("phone", phone);
    params.set("sessid", bitrixSessid());
    params.set("entityType", entity.entityType);
    params.set("entityId", entity.entityId);
    params.set("pageUrl", location.href);

    notify("3CX call start ho rahi hai: " + phone, true);

    var response = await fetchWithTimeout(ENDPOINT, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
      body: params.toString()
    }, A7_FETCH_TIMEOUT_MS);

    var text = await response.text();
    var data = null;
    try {
      data = JSON.parse(text);
    } catch (e) {
      var jsonMatch = text.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        try {
          data = JSON.parse(jsonMatch[0]);
        } catch (ignored) {}
      }
    }

    if (!response.ok || !data || !data.success) {
      var message = data && data.message ? data.message : "3CX call start nahi ho saki";
      throw new Error(message);
    }

    notify("3CX call started. Assigned user ki 3CX extension se call start hogi.", true);
  }

  function setupRecordingAutoSync() {
    if (window.A7_3CX_RECORDING_SYNC_TIMER) {
      return;
    }

    function canPollRecordingFromThisTab() {
      if (document.hidden) {
        return false;
      }

      try {
        var now = Date.now();
        var lock = null;
        try {
          lock = JSON.parse(localStorage.getItem(RECORDING_SYNC_LOCK_KEY) || "null");
        } catch (ignored) {}

        if (lock && lock.id && lock.id !== RECORDING_SYNC_TAB_ID && Number(lock.expires || 0) > now) {
          return false;
        }

        localStorage.setItem(
          RECORDING_SYNC_LOCK_KEY,
          JSON.stringify({ id: RECORDING_SYNC_TAB_ID, expires: now + RECORDING_SYNC_LOCK_TTL_MS })
        );
        return true;
      } catch (e) {
        return true;
      }
    }

    function releaseRecordingSyncLock() {
      try {
        var lock = JSON.parse(localStorage.getItem(RECORDING_SYNC_LOCK_KEY) || "null");
        if (lock && lock.id === RECORDING_SYNC_TAB_ID) {
          localStorage.removeItem(RECORDING_SYNC_LOCK_KEY);
        }
      } catch (e) {}
    }

    window.addEventListener("beforeunload", releaseRecordingSyncLock);

    async function pingRecordingSync() {
      if (!canPollRecordingFromThisTab()) {
        return;
      }

      try {
        await fetchWithTimeout(RECORDING_SYNC_ENDPOINT + "&cb=" + Date.now(), {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store"
        }, A7_FETCH_TIMEOUT_MS);
      } catch (e) {
        if (window.console && console.debug) {
          console.debug("[A7 3CX] recording sync ping skipped", e && e.message ? e.message : e);
        }
      }
    }

    window.A7_3CX_RECORDING_SYNC_TIMER = window.setInterval(pingRecordingSync, RECORDING_SYNC_POLL_MS);
    window.setTimeout(pingRecordingSync, 60000 + Math.floor(Math.random() * 60000));
  }

  function setupLiveCallMonitor() {
    if (window.A7_3CX_LIVE_CALL_TIMER) {
      return;
    }

    var seen = window.A7_3CX_LIVE_CALL_SEEN || {};
    window.A7_3CX_LIVE_CALL_SEEN = seen;

    function canPollFromThisTab() {
      if (document.hidden) {
        return false;
      }

      try {
        var now = Date.now();
        var lock = null;
        try {
          lock = JSON.parse(localStorage.getItem(LIVE_CALLS_LOCK_KEY) || "null");
        } catch (ignored) {}

        if (lock && lock.id && lock.id !== LIVE_CALLS_TAB_ID && Number(lock.expires || 0) > now) {
          return false;
        }

        localStorage.setItem(
          LIVE_CALLS_LOCK_KEY,
          JSON.stringify({ id: LIVE_CALLS_TAB_ID, expires: now + LIVE_CALLS_LOCK_TTL_MS })
        );
        return true;
      } catch (e) {
        return true;
      }
    }

    function releaseLiveCallLock() {
      try {
        var lock = JSON.parse(localStorage.getItem(LIVE_CALLS_LOCK_KEY) || "null");
        if (lock && lock.id === LIVE_CALLS_TAB_ID) {
          localStorage.removeItem(LIVE_CALLS_LOCK_KEY);
        }
      } catch (e) {}
    }

    window.addEventListener("beforeunload", releaseLiveCallLock);

    function messageForCall(call) {
      var direction = call.direction === "outbound" ? "Outbound" : "Incoming";
      var title = call.selectedEntity && call.selectedEntity.title ? call.selectedEntity.title : "CRM match nahi mila";
      var status = call.status ? " (" + call.status + ")" : "";
      return "3CX " + direction + " call" + status + ": " + (call.phoneMasked || "unknown") + " → " + title;
    }

    async function pingLiveCalls() {
      if (!canPollFromThisTab()) {
        return;
      }

      try {
        var response = await fetchWithTimeout(LIVE_CALLS_ENDPOINT + "&cb=" + Date.now(), {
          method: "GET",
          credentials: "same-origin",
          cache: "no-store"
        }, A7_FETCH_TIMEOUT_MS);
        if (!response.ok) {
          return;
        }

        var data = await response.json();
        if (!data || !data.success || !data.enabled || !data.calls || !data.calls.length) {
          return;
        }

        for (var i = 0; i < data.calls.length; i += 1) {
          var call = data.calls[i];
          var key = call.originId || [call.extension, call.status, call.phoneDigitsTail].join(":");
          if (!key || seen[key]) {
            continue;
          }

          seen[key] = Date.now();
          notify(messageForCall(call), true);

          if (call.sync && call.sync.status === "failed") {
            notify("3CX call Bitrix timeline mein log nahi ho saki.", false);
          } else if (call.sync && call.sync.status === "created") {
            notify("3CX call Bitrix timeline mein log ho gai.", true);
          }
        }

        var cutoff = Date.now() - 30 * 60 * 1000;
        Object.keys(seen).forEach(function (key) {
          if (seen[key] < cutoff) {
            delete seen[key];
          }
        });
      } catch (e) {
        if (window.console && console.debug) {
          console.debug("[A7 3CX] live call ping skipped", e && e.message ? e.message : e);
        }
      }
    }

    window.A7_3CX_LIVE_CALL_TIMER = window.setInterval(pingLiveCalls, LIVE_CALLS_POLL_MS);
    window.setTimeout(pingLiveCalls, 15000 + Math.floor(Math.random() * 15000));
  }

  function setupRecordingPlayerEnhancer() {
    enhanceRecordingPlayers(document);
    window.setTimeout(function () { enhanceRecordingPlayers(document); }, 2000);
    window.setTimeout(function () { enhanceRecordingPlayers(document); }, 6000);

    if (window.MutationObserver) {
      var observer = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i += 1) {
          for (var j = 0; j < mutations[i].addedNodes.length; j += 1) {
            var node = mutations[i].addedNodes[j];
            if (node && node.nodeType === 1) {
              enhanceRecordingPlayers(node);
            }
          }
        }
      });
      observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
    }
  }

  if (CLICK_TO_CALL_ENABLED) {
    document.addEventListener(
      "click",
      function (event) {
        if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
          return;
        }

        var candidates = findCallCandidatesFromClick(event.target);
        if (!candidates.length) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }

        choosePhone(candidates, event.clientX, event.clientY).then(function (phone) {
          if (!phone) {
            return;
          }
          startCall(phone).catch(function (error) {
            notify(error && error.message ? error.message : "3CX call error", false);
          });
        });
      },
      true
    );
  }

  setupRecordingAutoSync();
  if (LIVE_CALL_MONITOR_ENABLED) {
    setupLiveCallMonitor();
  }
  setupRecordingPlayerEnhancer();
})();
