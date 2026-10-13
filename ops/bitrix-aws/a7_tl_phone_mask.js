/**
 * A7 phone mask — last 4 digits hidden.
 * Loads for Team Leads (config list) + Admin & Finance dept members (auto),
 * except exempt users. Gate is in init.php OnProlog (all portal pages).
 * Eye + password admin222007 reveals for 30s.
 *
 * Deep leak seal: strips/masks title, aria-label, data-hint, tel/callto href,
 * copy payloads, and other tooltip attributes so hover cannot reveal the number.
 */
(function () {
  if (window.A7_TL_PHONE_MASK_V2) {
    return;
  }
  window.A7_TL_PHONE_MASK_V2 = true;
  window.A7_TL_PHONE_MASK_LOADED = true;

  var ENDPOINT = "/bitrix/tools/a7_tl_phone_mask.php";
  var STYLE_ID = "a7-tl-mask-style";
  var ATTR_FULL = "data-a7-full-phone";
  var ATTR_MASKED = "data-a7-masked";
  var ATTR_WRAP = "data-a7-mask-wrap";
  var ATTR_HREF = "data-a7-full-href";
  var ATTR_SEALED = "data-a7-leak-sealed";
  var REVEAL_MS = 30000;
  var unlockedUntil = 0;
  var scanTimer = 0;
  var busy = false;
  // A7_MASK_FREE_ZONE (2026-09-30): Messenger (chat window, side panel, desktop) and the file viewer / Disk files
  // are never masked or blocked, so shared files (Excel etc.) open and download with full numbers.
  var FREE_ZONE = "[class*='bx-im'], [class*='bx-messenger'], [class*='bx-desktop'], [class*='im-dialog'], " +
    "[class*='im-message'], [class*='im-chat'], .ui-viewer, [class*='ui-viewer'], [class*='disk-file'], [class*='bx-disk']";
  function inFreeZone(el) {
    try { return !!(el && el.closest && el.closest(FREE_ZONE)); } catch (e) { return false; }
  }

  var LEAK_ATTRS = [
    "title",
    "aria-label",
    "aria-description",
    "data-hint",
    "data-title",
    "data-tooltip",
    "data-copy",
    "data-clipboard-text",
    "data-text",
    "data-value",
    "data-phone",
    "data-number",
    "bx-tooltip-title",
    "bx-tooltip-content"
  ];

  function sessid() {
    try {
      if (window.BX && typeof BX.bitrix_sessid === "function") {
        return BX.bitrix_sessid();
      }
    } catch (e) {}
    return "";
  }

  function now() {
    return Date.now();
  }

  function isUnlocked() {
    return now() < unlockedUntil;
  }

  /** Hide last 4 digits: +971501234567 → +97150123**** */
  function maskPhoneDisplay(raw) {
    var s = String(raw || "");
    var digits = s.replace(/\D/g, "");
    if (digits.length < 8) {
      return s;
    }
    var digitCount = 0;
    var total = digits.length;
    var out = "";
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i);
      if (/\d/.test(ch)) {
        digitCount++;
        out += digitCount > total - 4 ? "*" : ch;
      } else {
        out += ch;
      }
    }
    return out;
  }

  function looksLikePhoneText(text) {
    var t = String(text || "").trim();
    if (!t || t.length > 40) {
      return false;
    }
    // Dates are not phones (29.09.2026, 2026-09-29, 29/09/2026) - 2026-09-29 fix.
    if (/^\d{1,4}[.\/-]\d{1,2}[.\/-]\d{1,4}$/.test(t)) {
      return false;
    }
    if (t.indexOf("*") !== -1 && /\d/.test(t)) {
      return false;
    }
    var digits = t.replace(/\D/g, "");
    if (digits.length < 8 || digits.length > 15) {
      return false;
    }
    if (/^\+?\d[\d\s\-().]{6,}\d$/.test(t)) {
      return true;
    }
    if (digits.length >= 9 && /^[\d\s+\-().]+$/.test(t)) {
      return true;
    }
    return false;
  }

  function phoneDigits(raw) {
    return String(raw || "").replace(/\D/g, "");
  }

  function attrContainsPhone(val, full) {
    var v = String(val || "");
    if (!v) {
      return false;
    }
    if (full && v.indexOf(full) !== -1) {
      return true;
    }
    var d = phoneDigits(v);
    var fd = phoneDigits(full);
    if (fd && d && d.indexOf(fd) !== -1) {
      return true;
    }
    return looksLikePhoneText(v) || (d.length >= 8 && d.length <= 15);
  }

  /**
   * Store originals once, then either restore (unlocked) or replace with masked /
   * empty values so native browser tooltips cannot leak the full number.
   */
  function sealLeakAttributes(el, full) {
    if (!el || el.nodeType !== 1) {
      return;
    }
    var masked = maskPhoneDisplay(full || "");
    var i;
    var name;
    var cur;
    var storeKey;

    for (i = 0; i < LEAK_ATTRS.length; i++) {
      name = LEAK_ATTRS[i];
      storeKey = "data-a7-orig-" + name;
      cur = el.getAttribute(name);
      if (cur != null && cur !== "" && !el.hasAttribute(storeKey) && attrContainsPhone(cur, full)) {
        el.setAttribute(storeKey, cur);
      }
      if (isUnlocked()) {
        if (el.hasAttribute(storeKey)) {
          el.setAttribute(name, el.getAttribute(storeKey));
        }
      } else if (el.hasAttribute(storeKey) || (cur != null && attrContainsPhone(cur, full))) {
        // Prefer empty title (no tooltip) over masked title that still invites hover.
        if (name === "title" || name === "aria-label" || name === "data-hint" || name === "bx-tooltip-title") {
          el.removeAttribute(name);
        } else if (masked) {
          el.setAttribute(name, masked);
        } else {
          el.removeAttribute(name);
        }
      }
    }

    // tel:/callto:/sms: href also appears in browser status / some tooltips
    var href = el.getAttribute("href") || "";
    var hm = href.match(/^(tel|callto|sms):(.+)$/i);
    if (hm) {
      if (!el.getAttribute(ATTR_HREF)) {
        el.setAttribute(ATTR_HREF, href);
      }
      if (isUnlocked()) {
        el.setAttribute("href", el.getAttribute(ATTR_HREF) || href);
      } else {
        // Keep scheme so UI still looks like a phone link, but digits are masked.
        var scheme = hm[1].toLowerCase();
        var rawNum = decodeURIComponent(hm[2] || "");
        var useFull = full || rawNum;
        el.setAttribute("href", scheme + ":" + maskPhoneDisplay(useFull));
      }
    }

    el.setAttribute(ATTR_SEALED, "1");
  }

  function sealTree(el, full) {
    if (!el || el.nodeType !== 1) {
      return;
    }
    sealLeakAttributes(el, full);
    // Parent row/cell often carries the same title in Bitrix entity editor
    var p = el.parentElement;
    var hops = 0;
    while (p && hops < 4 && p !== document.body) {
      sealLeakAttributes(p, full);
      p = p.parentElement;
      hops++;
    }
  }

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    var css = document.createElement("style");
    css.id = STYLE_ID;
    css.textContent =
      ".a7-tl-mask-wrap{display:inline-flex;align-items:center;gap:6px;max-width:100%;}" +
      ".a7-tl-mask-text{font-variant-numeric:tabular-nums;}" +
      ".a7-tl-mask-eye{border:0;background:#eef2f7;color:#1f2937;border-radius:6px;" +
      "width:26px;height:26px;padding:0;cursor:pointer;line-height:1;font-size:14px;}" +
      ".a7-tl-mask-eye:hover{background:#dde5ef;}" +
      ".a7-tl-mask-modal{position:fixed;inset:0;z-index:100000;background:rgba(15,23,42,.45);" +
      "display:flex;align-items:center;justify-content:center;}" +
      ".a7-tl-mask-card{background:#fff;border-radius:12px;padding:18px 20px;width:min(360px,92vw);" +
      "box-shadow:0 18px 50px rgba(0,0,0,.25);font-family:Arial,sans-serif;}" +
      ".a7-tl-mask-card h3{margin:0 0 8px;font-size:16px;}" +
      ".a7-tl-mask-card p{margin:0 0 12px;font-size:13px;color:#4b5563;}" +
      ".a7-tl-mask-card input{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #cbd5e1;" +
      "border-radius:8px;font-size:14px;margin-bottom:12px;}" +
      ".a7-tl-mask-actions{display:flex;gap:8px;justify-content:flex-end;}" +
      ".a7-tl-mask-actions button{border:0;border-radius:8px;padding:8px 14px;cursor:pointer;font-size:13px;}" +
      ".a7-tl-mask-cancel{background:#e5e7eb;}" +
      ".a7-tl-mask-ok{background:#0f766e;color:#fff;}" +
      ".a7-tl-mask-err{color:#b91c1c;font-size:12px;margin:-4px 0 10px;}" +
      /* Native title tooltips still possible on unsealed nodes — neutralize pointer hint on sealed links */
      "a[" + ATTR_SEALED + "]{cursor:default;}" +
      /* Profile / side panel close must stay above the dim overlay and receive clicks. */
      ".popup-window-close-icon,.side-panel-labels,.side-panel-label,.side-panel-close,.ui-sidepanel-close{" +
      "pointer-events:auto!important;z-index:13000!important;}";
    document.head.appendChild(css);
  }

  function notify(msg, ok) {
    try {
      if (window.BX && BX.UI && BX.UI.Notification && BX.UI.Notification.Center) {
        BX.UI.Notification.Center.notify({
          content: msg,
          autoHideDelay: ok === false ? 5000 : 2500
        });
        return;
      }
    } catch (e) {}
    if (window.console) {
      console[ok === false ? "warn" : "log"]("[A7 TL Mask]", msg);
    }
  }

  function askPassword() {
    return new Promise(function (resolve) {
      if (document.querySelector(".a7-tl-mask-modal")) {
        resolve(false);
        return;
      }
      ensureStyle();
      var modal = document.createElement("div");
      modal.className = "a7-tl-mask-modal";
      var card = document.createElement("div");
      card.className = "a7-tl-mask-card";
      var h = document.createElement("h3");
      h.textContent = "Admin password required";
      var p = document.createElement("p");
      p.textContent = "Enter password to view full phone numbers (30 seconds).";
      var input = document.createElement("input");
      input.type = "password";
      input.autocomplete = "current-password";
      input.placeholder = "Password";
      var err = document.createElement("div");
      err.className = "a7-tl-mask-err";
      err.style.display = "none";
      var actions = document.createElement("div");
      actions.className = "a7-tl-mask-actions";
      var cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "a7-tl-mask-cancel";
      cancel.textContent = "Cancel";
      var ok = document.createElement("button");
      ok.type = "button";
      ok.className = "a7-tl-mask-ok";
      ok.textContent = "Unlock";
      actions.appendChild(cancel);
      actions.appendChild(ok);
      card.appendChild(h);
      card.appendChild(p);
      card.appendChild(input);
      card.appendChild(err);
      card.appendChild(actions);
      modal.appendChild(card);
      document.body.appendChild(modal);
      input.focus();

      function close(result) {
        if (modal.parentNode) {
          modal.parentNode.removeChild(modal);
        }
        resolve(result);
      }

      cancel.addEventListener("click", function () {
        close(null);
      });
      modal.addEventListener("click", function (e) {
        if (e.target === modal) {
          close(null);
        }
      });
      ok.addEventListener("click", submit);
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          submit();
        }
        if (e.key === "Escape") {
          close(null);
        }
      });

      function submit() {
        var password = input.value || "";
        if (!password) {
          err.style.display = "block";
          err.textContent = "Password is required.";
          return;
        }
        ok.disabled = true;
        var body = new URLSearchParams();
        body.set("action", "unlock");
        body.set("password", password);
        body.set("sessid", sessid());
        fetch(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
          credentials: "same-origin"
        })
          .then(function (r) {
            return r.json();
          })
          .then(function (data) {
            if (!data || !data.ok) {
              err.style.display = "block";
              err.textContent = (data && data.error) || "Wrong password";
              ok.disabled = false;
              return;
            }
            var sec = Number(data.revealSeconds) || 30;
            REVEAL_MS = sec * 1000;
            unlockedUntil = now() + REVEAL_MS;
            close(true);
            window.setTimeout(function () {
              unlockedUntil = 0;
              remaskAll();
              notify("Phone numbers hidden again.", true);
            }, REVEAL_MS);
          })
          .catch(function () {
            err.style.display = "block";
            err.textContent = "Network error";
            ok.disabled = false;
          });
      }
    });
  }

  function unlockThen(cb) {
    if (isUnlocked()) {
      cb();
      return;
    }
    askPassword().then(function (ok) {
      if (ok) {
        cb();
      }
    });
  }

  function wrapPhoneNode(textNode) {
    var parent = textNode.parentNode;
    if (!parent || parent.nodeType !== 1) {
      return;
    }
    if (parent.closest && parent.closest("[" + ATTR_WRAP + "]")) {
      return;
    }
    var tag = parent.tagName;
    if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEXTAREA" || tag === "INPUT") {
      return;
    }
    if (parent.closest && parent.closest(".a7-od-call-btn, .a7-tl-mask-modal, .a7-tl-mask-eye")) {
      return;
    }

    var full = String(textNode.nodeValue || "").trim();
    if (!looksLikePhoneText(full)) {
      return;
    }

    var wrap = document.createElement("span");
    wrap.className = "a7-tl-mask-wrap";
    wrap.setAttribute(ATTR_WRAP, "1");
    wrap.setAttribute(ATTR_FULL, full);

    var text = document.createElement("span");
    text.className = "a7-tl-mask-text";
    text.setAttribute(ATTR_MASKED, "1");
    text.textContent = isUnlocked() ? full : maskPhoneDisplay(full);

    var eye = document.createElement("button");
    eye.type = "button";
    eye.className = "a7-tl-mask-eye";
    eye.title = "View full number";
    eye.setAttribute("aria-label", "View full number");
    eye.textContent = "\u25C9";

    eye.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      unlockThen(function () {
        text.textContent = full;
        notify("Numbers visible for 30 seconds.", true);
        remaskAll();
      });
    });

    wrap.appendChild(text);
    wrap.appendChild(eye);
    parent.replaceChild(wrap, textNode);
    sealTree(parent, full);
    sealTree(wrap, full);
  }

  function maskAnchor(a) {
    if (!a || a.nodeType !== 1) {
      return;
    }
    if (a.closest && a.closest(".a7-tl-mask-modal, .a7-od-call-btn")) {
      return;
    }
    var href = a.getAttribute("href") || "";
    var text = (a.textContent || "").trim();
    // If already wrapped, still re-seal leak attrs (Bitrix may re-add title)
    var existingFull = a.getAttribute(ATTR_FULL) || "";
    var fromHref = "";
    var m = href.match(/^(?:tel|callto|sms):(.+)$/i);
    if (m) {
      fromHref = decodeURIComponent(m[1]).trim();
      // If href already masked with stars, prefer stored full
      if (fromHref.indexOf("*") !== -1) {
        fromHref = a.getAttribute(ATTR_HREF)
          ? decodeURIComponent((a.getAttribute(ATTR_HREF).match(/^(?:tel|callto|sms):(.+)$/i) || [])[1] || "")
          : existingFull;
      }
    }
    var full = existingFull || (looksLikePhoneText(text) ? text : fromHref);
    if (!full && looksLikePhoneText(fromHref)) {
      full = fromHref;
    }
    if (!full || (!looksLikePhoneText(full) && full.indexOf("*") === -1 && !existingFull)) {
      // title-only leak: e.g. empty text but title has phone
      var titlePhone = a.getAttribute("title") || a.getAttribute("data-hint") || "";
      if (looksLikePhoneText(titlePhone)) {
        full = titlePhone;
      } else {
        return;
      }
    }

    if (!a.getAttribute(ATTR_WRAP)) {
      a.setAttribute(ATTR_WRAP, "1");
      a.setAttribute(ATTR_FULL, full);

      while (a.firstChild) {
        a.removeChild(a.firstChild);
      }
      var textEl = document.createElement("span");
      textEl.className = "a7-tl-mask-text";
      textEl.setAttribute(ATTR_MASKED, "1");
      textEl.textContent = isUnlocked() ? full : maskPhoneDisplay(full);
      a.appendChild(textEl);

      var eye = document.createElement("button");
      eye.type = "button";
      eye.className = "a7-tl-mask-eye";
      eye.title = "View full number";
      eye.setAttribute("aria-label", "View full number");
      eye.textContent = "\u25C9";
      eye.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        unlockThen(function () {
          remaskAll();
          notify("Numbers visible for 30 seconds.", true);
        });
      });
      if (a.parentNode && !(a.parentNode.classList && a.parentNode.classList.contains("a7-tl-mask-wrap"))) {
        var wrap = document.createElement("span");
        wrap.className = "a7-tl-mask-wrap";
        wrap.setAttribute(ATTR_WRAP, "1");
        wrap.setAttribute(ATTR_FULL, full);
        a.parentNode.insertBefore(wrap, a);
        wrap.appendChild(a);
        wrap.appendChild(eye);
      }
    } else {
      a.setAttribute(ATTR_FULL, full);
      var span = a.querySelector(".a7-tl-mask-text");
      if (span) {
        span.textContent = isUnlocked() ? full : maskPhoneDisplay(full);
      }
    }

    sealTree(a, full);
  }

  function maskPickerPhones(root) {
    var nodes = (root || document).querySelectorAll(".a7-od-call-picker-phone");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!el.getAttribute(ATTR_FULL)) {
        var full = (el.textContent || "").trim();
        if (!looksLikePhoneText(full)) {
          continue;
        }
        el.setAttribute(ATTR_FULL, full);
      }
      var stored = el.getAttribute(ATTR_FULL);
      el.textContent = isUnlocked() ? stored : maskPhoneDisplay(stored);
      el.setAttribute(ATTR_MASKED, "1");
      sealTree(el, stored);
    }
  }

  function remaskAll() {
    var texts = document.querySelectorAll(".a7-tl-mask-text[" + ATTR_MASKED + "]");
    for (var i = 0; i < texts.length; i++) {
      var el = texts[i];
      var wrap = el.closest("[" + ATTR_FULL + "]") || el.parentElement;
      var full = (wrap && wrap.getAttribute(ATTR_FULL)) || el.getAttribute(ATTR_FULL);
      if (!full) {
        continue;
      }
      el.textContent = isUnlocked() ? full : maskPhoneDisplay(full);
      if (wrap) {
        sealTree(wrap, full);
      }
    }
    var sealed = document.querySelectorAll("[" + ATTR_FULL + "]");
    for (var j = 0; j < sealed.length; j++) {
      sealTree(sealed[j], sealed[j].getAttribute(ATTR_FULL) || "");
    }
    maskProfilePhones(document);
    maskPickerPhones(document);
    maskFormInputs(document);
    sealOrphanTitleLeaks(document);
  }

  /**
   * Catch Bitrix nodes that expose phone only via title/tooltip (no text yet),
   * and any title that still holds a full number after SPA refresh.
   */
  function sealOrphanTitleLeaks(root) {
    var nodes = (root || document).querySelectorAll(
      "[title], [data-hint], [aria-label], [data-clipboard-text], [data-copy], a[href^='tel:'], a[href^='callto:']"
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.closest && (el.closest(".a7-tl-mask-modal, .a7-tl-mask-eye") || inFreeZone(el))) {
        continue;
      }
      var full = el.getAttribute(ATTR_FULL) || "";
      if (!full) {
        var candidates = [
          el.getAttribute("data-a7-orig-title"),
          el.getAttribute("title"),
          el.getAttribute("data-hint"),
          el.getAttribute("aria-label"),
          el.getAttribute("data-clipboard-text"),
          el.getAttribute("data-copy")
        ];
        var href = el.getAttribute(ATTR_HREF) || el.getAttribute("href") || "";
        var hm = href.match(/^(?:tel|callto|sms):(.+)$/i);
        if (hm) {
          candidates.push(decodeURIComponent(hm[1]));
        }
        for (var c = 0; c < candidates.length; c++) {
          if (looksLikePhoneText(candidates[c])) {
            full = candidates[c];
            break;
          }
        }
      }
      if (!full) {
        continue;
      }
      if (!el.getAttribute(ATTR_FULL) && looksLikePhoneText(full)) {
        el.setAttribute(ATTR_FULL, full);
      }
      sealTree(el, full);
    }
  }

  function maskFormInputs(root) {
    var nodes = (root || document).querySelectorAll(
      "input[type='text'], input[type='tel'], input:not([type]), textarea"
    );
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!el || el.closest(".a7-tl-mask-modal, [class*='tasks'], [class*='task-']") || inFreeZone(el)) {
        continue; // never touch task forms (2026-09-29 fix)
      }
      var name = String(el.name || el.id || el.getAttribute("data-name") || "").toLowerCase();
      var val = String(el.value || "").trim();
      var full = el.getAttribute(ATTR_FULL) || "";

      if (!full) {
        if (!looksLikePhoneText(val) && name.indexOf("phone") === -1 && name.indexOf("mobile") === -1) {
          if (!looksLikePhoneText(val)) {
            continue;
          }
        }
        if (!looksLikePhoneText(val)) {
          continue;
        }
        full = val;
        el.setAttribute(ATTR_FULL, full);
      }

      if (isUnlocked()) {
        el.value = full;
        el.readOnly = false;
        el.removeAttribute(ATTR_MASKED);
      } else {
        el.value = maskPhoneDisplay(full);
        el.readOnly = true;
        el.setAttribute(ATTR_MASKED, "1");
        if (!el.getAttribute("data-a7-eye")) {
          el.setAttribute("data-a7-eye", "1");
          var eye = document.createElement("button");
          eye.type = "button";
          eye.className = "a7-tl-mask-eye";
          eye.title = "View full number";
          eye.setAttribute("aria-label", "View full number");
          eye.textContent = "\u25C9";
          eye.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            unlockThen(function () {
              remaskAll();
              notify("Numbers visible for 30 seconds.", true);
            });
          });
          if (el.parentNode) {
            var wrap = document.createElement("span");
            wrap.className = "a7-tl-mask-wrap";
            wrap.setAttribute(ATTR_WRAP, "1");
            wrap.setAttribute(ATTR_FULL, full);
            el.parentNode.insertBefore(wrap, el);
            wrap.appendChild(el);
            wrap.appendChild(eye);
          }
        }
      }
      sealTree(el, full);
    }
  }

  function walkTextPhones(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node || !node.nodeValue || !node.parentElement) {
          return NodeFilter.FILTER_REJECT;
        }
        var p = node.parentElement;
        if (p.closest(".a7-tl-mask-wrap, .a7-tl-mask-modal, script, style, textarea, input, .a7-od-call-btn, [class*='tasks'], [class*='task-']") || inFreeZone(p)) {
          return NodeFilter.FILTER_REJECT;
        }
        // Profile card is Vue-owned. Replacing the text node makes it paint the full number again.
        if (p.closest(".intranet-user-mini-profile, .intranet-user-mini-profile-popup, .ui-entity-editor-content-block-field-phone")) {
          return NodeFilter.FILTER_REJECT;
        }
        if (!looksLikePhoneText(node.nodeValue)) {
          return NodeFilter.FILTER_SKIP;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var collect = [];
    while (walker.nextNode()) {
      collect.push(walker.currentNode);
    }
    for (var i = 0; i < collect.length; i++) {
      wrapPhoneNode(collect[i]);
    }
  }

  var PROFILE_PHONE_SEL = ".intranet-user-mini-profile, .intranet-user-mini-profile-popup, .ui-entity-editor-content-block-field-phone";

  function maskProfilePhones(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var boxes = scope.querySelectorAll(PROFILE_PHONE_SEL);
    for (var i = 0; i < boxes.length; i++) {
      if (!inFreeZone(boxes[i])) {
        rewriteProfileBox(boxes[i]);
      }
    }
  }

  function rewriteProfileBox(box) {
    var walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node || !node.parentElement) {
          return NodeFilter.FILTER_REJECT;
        }
        var p = node.parentElement;
        if (p.closest("script, style, textarea, input, .a7-tl-mask-modal, .a7-tl-mask-eye")) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var nodes = [];
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    for (var i = 0; i < nodes.length; i++) {
      rewriteProfileText(nodes[i]);
    }
  }

  function rewriteProfileText(node) {
    var raw = String(node.nodeValue || "");
    var parent = node.parentElement;
    if (!parent) {
      return;
    }
    var stored = parent.getAttribute(ATTR_FULL) || "";
    if (raw.indexOf("*") !== -1) {
      if (isUnlocked() && stored) {
        var maskedNow = maskPhoneDisplay(stored);
        if (raw.indexOf(maskedNow) !== -1 && raw.indexOf(stored) === -1) {
          node.nodeValue = raw.replace(maskedNow, stored);
        }
      }
      return;
    }
    var found = "";
    var match = raw.match(/\+?\d[\d\s\u00a0\-().]{6,}\d/);
    if (match) {
      var candidate = match[0].replace(/\u00a0/g, " ").trim();
      if (looksLikePhoneText(candidate)) {
        found = match[0];
      }
    }
    if (!stored && found) {
      stored = found.replace(/\u00a0/g, " ").trim();
      parent.setAttribute(ATTR_FULL, stored);
    }
    if (!stored || !found) {
      return;
    }
    var show = isUnlocked() ? stored : maskPhoneDisplay(stored);
    if (raw.indexOf(found) !== -1 && raw.indexOf(show) === -1) {
      node.nodeValue = raw.replace(found, show);
    }
    sealTree(parent, stored);
  }

  function profilePhoneTarget(t) {
    if (!t || !t.closest) {
      return null;
    }
    return t.closest(
      "a.intranet-user-mini-profile__detailed-info__contact-item-value, " +
      ".ui-entity-editor-content-block-field-phone .ui-entity-editor-content-block-text, " +
      ".intranet-user-profile-phone-icon"
    );
  }

  function blockProfilePhone(e) {
    if (isUnlocked()) {
      return;
    }
    var t = e.target;
    if (!t || !t.closest) {
      return;
    }
    if (t.closest(
      ".popup-window-close-icon, .popup-window-overlay, .side-panel-labels, .side-panel-label, " +
      ".side-panel-close, .ui-sidepanel-close, .ui-side-panel-close, .a7-tl-mask-eye"
    )) {
      return;
    }
    var hit = profilePhoneTarget(t);
    if (!hit || inFreeZone(hit)) {
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    unlockThen(function () {
      remaskAll();
      notify("Numbers visible for 30 seconds.", true);
    });
  }

  function scan() {
    if (busy) {
      return;
    }
    busy = true;
    try {
      ensureStyle();
      var root = document.body;
      if (!root) {
        return;
      }
      var anchors = root.querySelectorAll(
        'a[href^="tel:"], a[href^="callto:"], a[href^="sms:"], .crm-entity-phone-number, .crm-client-contacts-block-text a, .crm-entity-widget-content-block-inner a'
      );
      for (var i = 0; i < anchors.length; i++) {
        if (!inFreeZone(anchors[i])) {
          maskAnchor(anchors[i]);
        }
      }
      walkTextPhones(root);
      maskProfilePhones(root);
      maskPickerPhones(root);
      maskFormInputs(root);
      sealOrphanTitleLeaks(root);
    } finally {
      busy = false;
    }
  }

  function scheduleScan() {
    window.clearTimeout(scanTimer);
    scanTimer = window.setTimeout(scan, 200);
  }

  function interceptExport() {
    document.addEventListener(
      "click",
      function (e) {
        var t = e.target;
        if (!t || !t.closest) {
          return;
        }
        var btn = t.closest(
          "button, a, .ui-btn, .menu-popup-item, .main-grid-row-action-button, span"
        );
        if (!btn) {
          return;
        }
        if (inFreeZone(btn)) {
          return; // Messenger / file viewer: downloads allowed
        }
        var label = (
          (btn.getAttribute("title") || "") +
          " " +
          (btn.textContent || "") +
          " " +
          (btn.getAttribute("data-text") || "")
        ).toLowerCase();
        if (
          label.indexOf("excel") === -1 &&
          label.indexOf("export") === -1 &&
          label.indexOf("csv") === -1 &&
          label.indexOf("download") === -1
        ) {
          return;
        }
        if (isUnlocked()) {
          return;
        }
        e.preventDefault();
        e.stopPropagation();
        unlockThen(function () {
          notify("Export unlocked for 30 seconds. Click export again.", true);
        });
      },
      true
    );
  }

  /** Block copy / context that would expose full number while locked. */
  function interceptCopy() {
    document.addEventListener(
      "copy",
      function (e) {
        if (isUnlocked()) {
          return;
        }
        var sel = window.getSelection && window.getSelection();
        var text = sel ? String(sel.toString() || "") : "";
        if (!text && e.target && e.target.getAttribute) {
          text = e.target.getAttribute(ATTR_FULL) || e.target.value || "";
        }
        // If selection is inside a masked wrap, force masked clipboard
        var node = sel && sel.anchorNode ? sel.anchorNode : null;
        var el = node && node.nodeType === 3 ? node.parentElement : node;
        if (el && el.closest) {
          var wrap = el.closest("[" + ATTR_FULL + "]");
          if (wrap) {
            var full = wrap.getAttribute(ATTR_FULL) || "";
            if (full && e.clipboardData) {
              e.clipboardData.setData("text/plain", maskPhoneDisplay(full));
              e.preventDefault();
            }
          }
        }
      },
      true
    );

    // Prevent click-to-call while locked (href is masked but Bitrix JS may use stored number)
    document.addEventListener(
      "click",
      function (e) {
        if (isUnlocked()) {
          return;
        }
        var t = e.target;
        if (!t || !t.closest) {
          return;
        }
        if (t.closest(
          ".popup-window-close-icon, .popup-window-overlay, .side-panel-labels, .side-panel-label, " +
          ".side-panel-close, .ui-sidepanel-close, .ui-side-panel-close"
        )) {
          return;
        }
        if (profilePhoneTarget(t)) {
          blockProfilePhone(e);
          return;
        }
        var a = t.closest("a[href^='tel:'], a[href^='callto:'], a[href^='sms:'], a[" + ATTR_FULL + "]");
        if (!a || inFreeZone(a)) {
          return;
        }
        if (a.closest(".side-panel, .popup-window")) {
          return;
        }
        if (t.closest(".a7-tl-mask-eye")) {
          return;
        }
        // Allow navigation only after unlock
        e.preventDefault();
        e.stopPropagation();
        unlockThen(function () {
          remaskAll();
          notify("Numbers unlocked for 30 seconds. Click again to call.", true);
        });
      },
      true
    );
  }

  /**
   * Browser title tooltips fire ~400ms after hover. Strip title/hint immediately
   * on mouseenter (capture) so the native box never appears. Also hide Bitrix
   * hint popups that re-inject the full number.
   */
  function interceptHover() {
    function nukeHoverLeaks(start) {
      if (isUnlocked() || !start) {
        return;
      }
      var el = start.nodeType === 3 ? start.parentElement : start;
      if (inFreeZone(el)) {
        return;
      }
      var hops = 0;
      while (el && el.nodeType === 1 && hops < 8 && el !== document.documentElement) {
        var full = el.getAttribute(ATTR_FULL) || "";
        var title = el.getAttribute("title") || el.getAttribute("data-hint") || "";
        if (!full && looksLikePhoneText(title)) {
          full = title;
          el.setAttribute(ATTR_FULL, full);
        }
        if (full || looksLikePhoneText(title)) {
          sealLeakAttributes(el, full || title);
        }
        el = el.parentElement;
        hops++;
      }
      hidePhoneHintPopups();
    }

    function hidePhoneHintPopups() {
      // Hint bubbles only. Never .popup-window or .side-panel: those are the
      // account card and kanban slider. Removing them left the dim overlay up
      // and the close icon visible but not clickable.
      var pops = document.querySelectorAll(".ui-hint, .ui-hint-popup, .bx-ui-hint, [id^='bx-hint']");
      for (var i = 0; i < pops.length; i++) {
        var p = pops[i];
        if (p.closest && p.closest(".side-panel, .popup-window")) {
          continue;
        }
        var txt = (p.textContent || "").trim();
        if (looksLikePhoneText(txt) || (phoneDigits(txt).length >= 8 && phoneDigits(txt).length <= 15 && txt.indexOf("*") === -1)) {
          if (p.parentNode) {
            try {
              p.parentNode.removeChild(p);
            } catch (err) {}
          }
        }
      }
      releaseStuckOverlays();
    }

    function releaseStuckOverlays() {
      var overlays = document.querySelectorAll(".popup-window-overlay");
      for (var i = 0; i < overlays.length; i++) {
        var overlay = overlays[i];
        var next = overlay.nextElementSibling;
        var hasPopup = false;
        var node = overlay.parentElement ? overlay.parentElement.firstElementChild : null;
        while (node) {
          if (node.classList && node.classList.contains("popup-window") && node.offsetParent !== null) {
            hasPopup = true;
            break;
          }
          node = node.nextElementSibling;
        }
        if (!hasPopup && (!next || !next.classList || !next.classList.contains("popup-window"))) {
          try {
            overlay.parentNode.removeChild(overlay);
          } catch (err) {}
        }
      }
    }

    document.addEventListener("mouseup", function (e) {
      var t = e.target;
      if (!t || !t.closest || !t.closest(".intranet-user-profile-phone-icon")) {
        return;
      }
      blockProfilePhone(e);
    }, true);

    document.addEventListener("mouseover", function (e) {
      nukeHoverLeaks(e.target);
    }, true);
    document.addEventListener("mouseenter", function (e) {
      nukeHoverLeaks(e.target);
    }, true);
    document.addEventListener("pointerover", function (e) {
      nukeHoverLeaks(e.target);
    }, true);
  }

  function boot() {
    ensureStyle();
    interceptExport();
    interceptCopy();
    interceptHover();
    scan();
    scheduleScan();
    if (window.MutationObserver) {
      var obs = new MutationObserver(function (mutations) {
        var needs = false;
        for (var i = 0; i < mutations.length; i++) {
          var m = mutations[i];
          if (m.type === "attributes") {
            var an = m.attributeName || "";
            if (
              an === "title" ||
              an === "aria-label" ||
              an === "data-hint" ||
              an === "href" ||
              an === "data-clipboard-text" ||
              an === "data-copy"
            ) {
              needs = true;
              break;
            }
          } else if (m.type === "characterData") {
            var pn = m.target && m.target.parentElement;
            if (pn && pn.closest && pn.closest(PROFILE_PHONE_SEL + ", .popup-window, .side-panel")) {
              needs = true;
              break;
            }
          } else {
            needs = true;
            break;
          }
        }
        if (needs) {
          scheduleScan();
        }
      });
      obs.observe(document.documentElement, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: [
          "title",
          "aria-label",
          "data-hint",
          "href",
          "data-clipboard-text",
          "data-copy",
          "data-title",
          "bx-tooltip-title"
        ]
      });
    }
    window.setInterval(function () {
      if (isUnlocked() || !document.querySelector(PROFILE_PHONE_SEL)) {
        return;
      }
      maskProfilePhones(document);
    }, 500);
    window.A7TlPhoneMask = {
      scan: scan,
      isUnlocked: isUnlocked,
      maskPhoneDisplay: maskPhoneDisplay,
      remaskAll: remaskAll
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
