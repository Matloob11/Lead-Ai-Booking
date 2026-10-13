/**
 * A7 Portal Lead Fields — Bayut / Property Finder / Dubizzle lead details:
 * hide junk phone UFs, gather empty fields + Call Recording into one bottom
 * section, and prompt for the stage-admin password before Create field.
 *
 * Works in full-page details and SidePanel (iframe or ajax). Portal is
 * detected from boot payload AND from Name/Source text on the card.
 */
(function () {
	"use strict";

	if (window.__A7_PORTAL_LEAD_FIELDS_JS__) {
		return;
	}
	window.__A7_PORTAL_LEAD_FIELDS_JS__ = true;

	var CFG = window.A7_PORTAL_LEAD_FIELDS || {};
	var PARAM = CFG.param || "a7_stage_admin_password";
	var TITLE = CFG.title || "Admin password required";
	var TEXT = CFG.text || "Enter admin password to create a new field:";
	var OTHER_TITLE = CFG.otherTitle || "Other fields";
	var HIDE = {};
	var ALWAYS_OTHER = {};
	(CFG.hideFields || []).forEach(function (id) {
		HIDE[String(id).toUpperCase()] = true;
	});
	(CFG.alwaysOther || []).forEach(function (id) {
		ALWAYS_OTHER[String(id).toUpperCase()] = true;
	});

	var PORTAL_NAME_RE = /bayut|property\s*finder|\bpf\b|dubizzle/i;
	var KEEP_TITLES = {
		name: true,
		phone: true,
		email: true,
		source: true,
		stage: true,
		status: true,
		"responsible person": true,
		responsible: true,
		observers: true,
		observer: true,
		comments: true,
		comment: true,
		"property reference": true,
		"portal lead id": true,
		community: true,
		"no. of bedrooms": true,
		"no of bedrooms": true,
		"deal amount.": true,
		"deal amount": true,
		owner: true,
		"rent / sale": true,
		"sub source": true,
		"whatsapp tracking link": true,
		"client type": true,
	};

	function docsToScan() {
		var out = [];
		function add(doc) {
			if (!doc || !doc.body) {
				return;
			}
			if (out.indexOf(doc) === -1) {
				out.push(doc);
			}
		}
		add(document);
		try {
			var frames = document.querySelectorAll("iframe");
			for (var i = 0; i < frames.length; i++) {
				try {
					add(frames[i].contentDocument);
				} catch (e) {}
			}
		} catch (e2) {}
		try {
			var panels = document.querySelectorAll(
				".side-panel-content, .side-panel-container, .side-panel iframe"
			);
			for (var j = 0; j < panels.length; j++) {
				var el = panels[j];
				if (el.tagName === "IFRAME") {
					try {
						add(el.contentDocument);
					} catch (e3) {}
				} else {
					add(el.ownerDocument || document);
				}
			}
		} catch (e4) {}
		return out;
	}

	function pathLooksDetails(path) {
		return /\/crm\/lead\/details\/\d+/i.test(path) || /\/crm\/type\/1\/details\/\d+/i.test(path);
	}

	function leadIdFromPath(path) {
		var m = String(path || "").match(/\/crm\/lead\/details\/(\d+)/i);
		if (m) {
			return parseInt(m[1], 10);
		}
		m = String(path || "").match(/\/crm\/type\/1\/details\/(\d+)/i);
		return m ? parseInt(m[1], 10) : 0;
	}

	function hasLeadEditor(doc) {
		return !!(
			doc.querySelector(".ui-entity-editor-content-block") ||
			doc.querySelector(".crm-entity-widget-content-block") ||
			doc.querySelector(".ui-entity-editor-section") ||
			doc.querySelector("[data-cid]")
		);
	}

	function isLeadContext(doc) {
		if (pathLooksDetails(window.location.pathname)) {
			return true;
		}
		try {
			if (window.location.href && pathLooksDetails(window.location.href)) {
				return true;
			}
		} catch (e) {}
		var root = doc.querySelector(
			".crm-entity-details, .crm-entity-card-container, .ui-entity-editor-container, [data-entity-type-id='1']"
		);
		if (!root) {
			return hasLeadEditor(doc) && /lead/i.test(String(doc.body && doc.body.className) + " " + String(window.location.pathname));
		}
		var html = root.getAttribute("data-entity-type-id") || root.getAttribute("data-type") || "";
		if (String(html) === "1" || /lead/i.test(html)) {
			return true;
		}
		// Side panel open with lead details URL in slider
		try {
			if (window.BX && BX.SidePanel && BX.SidePanel.Instance) {
				var slider = BX.SidePanel.Instance.getTopSlider && BX.SidePanel.Instance.getTopSlider();
				if (slider && slider.getUrl && pathLooksDetails(slider.getUrl())) {
					return true;
				}
			}
		} catch (e2) {}
		return hasLeadEditor(doc) && pathLooksDetails(String(window.location.href || ""));
	}

	function fieldValueByTitle(doc, want) {
		var wantL = String(want).toLowerCase();
		var titles = doc.querySelectorAll(
			".ui-entity-editor-block-title-text, .ui-entity-editor-field-title-text, .crm-entity-widget-content-block-title-text, .ui-entity-editor-block-title"
		);
		for (var i = 0; i < titles.length; i++) {
			var t = String(titles[i].textContent || "")
				.replace(/\s+/g, " ")
				.trim()
				.toLowerCase();
			if (t !== wantL && t.indexOf(wantL) !== 0) {
				continue;
			}
			var block = fieldBlock(titles[i]);
			if (!block) {
				continue;
			}
			return visibleText(block);
		}
		return "";
	}

	function detectPortal(doc) {
		if (CFG.isPortal === true) {
			var bootId = parseInt(CFG.leadId || 0, 10);
			var pathId = leadIdFromPath(window.location.pathname);
			if (!bootId || !pathId || bootId === pathId) {
				return true;
			}
		}
		var name = fieldValueByTitle(doc, "Name") || fieldValueByTitle(doc, "First name");
		if (PORTAL_NAME_RE.test(name)) {
			return true;
		}
		var source = fieldValueByTitle(doc, "Source");
		if (PORTAL_NAME_RE.test(source)) {
			return true;
		}
		// Header / pagetitle often carries the lead title
		var header = doc.querySelector(
			".pagetitle-inner-container, .ui-page-slider-page-header, .crm-entity-widget-content-block-title, h1, .ui-entity-editor-header-title-text"
		);
		var headerText = header ? String(header.textContent || "") : "";
		if (PORTAL_NAME_RE.test(headerText)) {
			return true;
		}
		if (PORTAL_NAME_RE.test(String(doc.title || ""))) {
			return true;
		}
		// Portal Lead ID field present + filled is a strong signal for these cards
		var portalId = fieldValueByTitle(doc, "Portal Lead ID");
		if (portalId && !isEmptyText(portalId)) {
			var ref = fieldValueByTitle(doc, "Property Reference");
			if (ref && !isEmptyText(ref)) {
				return true;
			}
		}
		return false;
	}

	function fieldBlock(el) {
		return (
			(el.closest &&
				(el.closest(".ui-entity-editor-content-block") ||
					el.closest(".ui-entity-editor-field") ||
					el.closest(".ui-entity-editor-block") ||
					el.closest(".crm-entity-widget-content-block"))) ||
			null
		);
	}

	function fieldCid(el) {
		var node = el;
		while (node && node !== document.documentElement) {
			if (node.getAttribute) {
				var cid = node.getAttribute("data-cid") || node.getAttribute("data-field-name");
				if (cid) {
					return String(cid).toUpperCase();
				}
			}
			node = node.parentNode;
		}
		return "";
	}

	function fieldTitle(block) {
		var titleEl = block.querySelector(
			".ui-entity-editor-block-title-text, .ui-entity-editor-field-title-text, .crm-entity-widget-content-block-title-text"
		);
		if (!titleEl) {
			titleEl = block.querySelector(
				".ui-entity-editor-block-title, .ui-entity-editor-field-title, .crm-entity-widget-content-block-title"
			);
		}
		return ((titleEl && titleEl.textContent) || "").replace(/\s+/g, " ").trim();
	}

	function visibleText(block) {
		var clone = block.cloneNode(true);
		var drop = clone.querySelectorAll(
			".ui-entity-editor-block-title, .ui-entity-editor-field-title, .crm-entity-widget-content-block-title, button, .ui-entity-editor-header-edit, .ui-hint, .ui-entity-editor-block-context-menu, .ui-entity-editor-block-draggable-btn, .ui-entity-editor-block-draggable-btn-container"
		);
		for (var i = 0; i < drop.length; i++) {
			if (drop[i].parentNode) {
				drop[i].parentNode.removeChild(drop[i]);
			}
		}
		return String(clone.textContent || "")
			.replace(/\s+/g, " ")
			.trim();
	}

	function isEmptyText(text) {
		var t = String(text || "")
			.replace(/\s+/g, " ")
			.trim()
			.toLowerCase();
		if (!t) {
			return true;
		}
		if (
			t === "field is empty" ||
			t === "none" ||
			t === "n/a" ||
			t === "na" ||
			t === "not filled" ||
			t === "not specified" ||
			t === "select" ||
			t === "enter value" ||
			t === "—" ||
			t === "–" ||
			t === "-"
		) {
			return true;
		}
		if (/^field is empty\.?$/.test(t)) {
			return true;
		}
		if (/^[\u2014\u2013\-\u00b7·•.]+$/.test(t)) {
			return true;
		}
		return false;
	}

	function hasFilledControl(block) {
		var inputs = block.querySelectorAll("input, textarea, select");
		for (var i = 0; i < inputs.length; i++) {
			var el = inputs[i];
			var type = String(el.type || "").toLowerCase();
			if (type === "hidden" || type === "button" || type === "submit" || type === "checkbox" || type === "radio") {
				continue;
			}
			var val = String(el.value || "").replace(/\s+/g, " ").trim();
			if (val !== "" && !isEmptyText(val)) {
				return true;
			}
		}
		var links = block.querySelectorAll("a[href]");
		for (var j = 0; j < links.length; j++) {
			var href = String(links[j].getAttribute("href") || "");
			var linkText = String(links[j].textContent || "")
				.replace(/\s+/g, " ")
				.trim();
			if (href && href !== "#" && href.indexOf("javascript:") !== 0 && !isEmptyText(linkText)) {
				return true;
			}
			if (href && href !== "#" && href.indexOf("javascript:") !== 0 && /https?:|whatsapp|tel:/i.test(href)) {
				return true;
			}
		}
		var media = block.querySelectorAll("img[src], audio[src], video[src], source[src]");
		if (media.length) {
			return true;
		}
		return false;
	}

	function isEmptyField(block) {
		if (hasFilledControl(block)) {
			return false;
		}
		return isEmptyText(visibleText(block));
	}

	function shouldHide(cid, title) {
		if (cid && HIDE[cid]) {
			return true;
		}
		var t = String(title || "")
			.replace(/\s+/g, " ")
			.trim()
			.toLowerCase();
		if (!t) {
			return false;
		}
		if (t === "phone") {
			return false; // system Phone stays
		}
		if (
			t === "mobile number" ||
			t === "secondary phone number" ||
			t === "phone (owner data)" ||
			t === "community (old)" ||
			t === "new number" ||
			t === "971529647138" ||
			t.indexOf("my mobile") !== -1 ||
			t.indexOf("whatsapp number") !== -1 ||
			t.indexOf("registered buyer phone") !== -1 ||
			t === "registered buyer phone"
		) {
			return true;
		}
		return false;
	}

	function shouldAlwaysOther(cid, title) {
		if (cid && ALWAYS_OTHER[cid]) {
			return true;
		}
		return /call recording/i.test(String(title || ""));
	}

	function shouldKeepFilled(cid, title) {
		var t = String(title || "")
			.replace(/\s+/g, " ")
			.trim()
			.toLowerCase();
		if (KEEP_TITLES[t]) {
			return true;
		}
		if (
			cid === "TITLE" ||
			cid === "NAME" ||
			cid === "LAST_NAME" ||
			cid === "SECOND_NAME" ||
			cid === "PHONE" ||
			cid === "EMAIL" ||
			cid === "SOURCE_ID" ||
			cid === "STATUS_ID" ||
			cid === "ASSIGNED_BY_ID" ||
			cid === "OBSERVER" ||
			cid === "COMMENTS" ||
			cid === "OPPORTUNITY" ||
			cid === "CURRENCY_ID"
		) {
			return true;
		}
		return false;
	}

	function findLeftColumn(doc) {
		return (
			doc.querySelector(".ui-entity-editor-column-left") ||
			doc.querySelector(".crm-entity-card-container") ||
			doc.querySelector(".ui-entity-editor-column") ||
			doc.querySelector(".ui-entity-editor-container") ||
			doc.querySelector(".crm-entity-section-info") ||
			doc.body
		);
	}

	function sectionTitleText(section) {
		var el = section.querySelector(
			".ui-entity-editor-header-title-text, .ui-entity-editor-section-title-text, .crm-entity-card-widget-title"
		);
		return ((el && el.textContent) || "").replace(/\s+/g, " ").trim().toLowerCase();
	}

	function ensureOtherSection(doc) {
		var existing = doc.querySelector('[data-a7-plf="other"]');
		if (existing) {
			existing.style.display = "";
			return existing;
		}
		// Prefer the form section we configured as "Other fields"
		var sections = doc.querySelectorAll(".ui-entity-editor-section, .crm-entity-card-widget");
		for (var s = 0; s < sections.length; s++) {
			var t = sectionTitleText(sections[s]);
			if (t === "other fields" || t.indexOf("other field") === 0) {
				sections[s].setAttribute("data-a7-plf", "other");
				sections[s].setAttribute("data-a7-keep", "1");
				var content =
					sections[s].querySelector(".ui-entity-editor-section-content") ||
					sections[s].querySelector(".crm-entity-card-widget-content") ||
					sections[s];
				content.classList.add("a7-plf-other-content");
				return sections[s];
			}
		}
		var host = findLeftColumn(doc);
		if (!host) {
			return null;
		}
		var section = doc.createElement("div");
		section.className = "ui-entity-editor-section a7-plf-other";
		section.setAttribute("data-a7-plf", "other");
		section.setAttribute("data-a7-keep", "1");

		var header = doc.createElement("div");
		header.className = "ui-entity-editor-section-header a7-plf-other-header";
		var titleWrap = doc.createElement("div");
		titleWrap.className = "ui-entity-editor-header-title";
		var titleText = doc.createElement("span");
		titleText.className = "ui-entity-editor-header-title-text";
		titleText.textContent = OTHER_TITLE;
		titleWrap.appendChild(titleText);
		header.appendChild(titleWrap);

		var contentEl = doc.createElement("div");
		contentEl.className = "ui-entity-editor-section-content a7-plf-other-content";

		section.appendChild(header);
		section.appendChild(contentEl);

		var hostSections = host.querySelectorAll(".ui-entity-editor-section");
		if (hostSections.length) {
			var last = hostSections[hostSections.length - 1];
			if (last.parentNode) {
				last.parentNode.insertBefore(section, last.nextSibling);
			} else {
				host.appendChild(section);
			}
		} else {
			host.appendChild(section);
		}
		return section;
	}

	function moveToOther(doc, block) {
		var section = ensureOtherSection(doc);
		if (!section) {
			return;
		}
		var content = section.querySelector(".a7-plf-other-content") || section;
		if (block.parentNode === content) {
			block.style.display = "";
			block.style.setProperty("display", "", "important");
			block.removeAttribute("data-a7-hidden");
			return;
		}
		block.setAttribute("data-a7-plf-moved", "1");
		block.style.display = "";
		block.style.setProperty("display", "", "important");
		block.removeAttribute("data-a7-hidden");
		content.appendChild(block);
	}

	function hideBlock(block) {
		block.style.setProperty("display", "none", "important");
		block.setAttribute("data-a7-plf-hide", "1");
	}

	function inStagePopup(node) {
		if (!node || !node.closest) {
			return false;
		}
		return !!node.closest(
			".popup-window, .popup-window-content, [id*='partial_editor'], [id*='_custom_editor']"
		);
	}

	function collectBlocks(doc) {
		var seen = [];
		var blocks = [];
		function push(block) {
			if (!block || seen.indexOf(block) !== -1) {
				return;
			}
			if (inStagePopup(block)) {
				return;
			}
			// Prefer outermost content block
			var outer =
				block.closest(".ui-entity-editor-content-block") ||
				block.closest(".crm-entity-widget-content-block") ||
				block;
			if (seen.indexOf(outer) !== -1) {
				return;
			}
			seen.push(outer);
			blocks.push(outer);
		}

		var titled = doc.querySelectorAll(
			".ui-entity-editor-block-title-text, .ui-entity-editor-field-title-text, .crm-entity-widget-content-block-title-text, .ui-entity-editor-block-title"
		);
		for (var i = 0; i < titled.length; i++) {
			push(fieldBlock(titled[i]));
		}
		var withCid = doc.querySelectorAll(
			".ui-entity-editor-content-block[data-cid], .ui-entity-editor-field[data-cid], [data-cid].ui-entity-editor-block, .crm-entity-widget-content-block[data-cid]"
		);
		for (var j = 0; j < withCid.length; j++) {
			push(withCid[j]);
		}
		return blocks;
	}

	function hideEmptySections(doc) {
		var sections = doc.querySelectorAll(".ui-entity-editor-section, .crm-entity-card-widget");
		for (var i = 0; i < sections.length; i++) {
			var section = sections[i];
			if (inStagePopup(section)) {
				continue;
			}
			if (section.getAttribute("data-a7-plf") === "other" || section.getAttribute("data-a7-keep") === "1") {
				continue;
			}
			var blocks = section.querySelectorAll(
				".ui-entity-editor-content-block, .ui-entity-editor-field, .crm-entity-widget-content-block"
			);
			var visible = 0;
			for (var j = 0; j < blocks.length; j++) {
				if (blocks[j].getAttribute("data-a7-plf-hide") === "1") {
					continue;
				}
				if (blocks[j].style.display === "none") {
					continue;
				}
				visible++;
			}
			if (visible === 0 && blocks.length > 0) {
				section.style.setProperty("display", "none", "important");
				section.setAttribute("data-a7-plf-empty-section", "1");
			}
		}
	}

	function organizeDoc(doc) {
		if (!hasLeadEditor(doc)) {
			return null;
		}
		if (!isLeadContext(doc) && !pathLooksDetails(window.location.pathname)) {
			// Still allow if portal markers are already on this document (slider ajax)
			if (!detectPortal(doc)) {
				return null;
			}
		}
		if (!detectPortal(doc)) {
			return null;
		}

		doc.documentElement.setAttribute("data-a7-plf-active", "1");

		var blocks = collectBlocks(doc);
		var moved = 0;
		var hidden = 0;
		for (var i = 0; i < blocks.length; i++) {
			var block = blocks[i];
			if (!block || block.getAttribute("data-a7-plf-hide") === "1") {
				continue;
			}
			if (block.closest && block.closest('[data-a7-plf="other"]') && block.getAttribute("data-a7-plf-moved") === "1") {
				block.style.setProperty("display", "", "important");
				continue;
			}
			var cid = fieldCid(block);
			var title = fieldTitle(block);

			if (shouldHide(cid, title)) {
				hideBlock(block);
				hidden++;
				continue;
			}

			if (shouldAlwaysOther(cid, title)) {
				moveToOther(doc, block);
				moved++;
				continue;
			}

			if (shouldKeepFilled(cid, title) && !isEmptyField(block)) {
				continue;
			}

			// Keep filled useful fields in place; move empties down
			if (isEmptyField(block)) {
				// Even "Name"/"Phone" empty stays — agents need them
				if (shouldKeepFilled(cid, title)) {
					continue;
				}
				moveToOther(doc, block);
				moved++;
			}
		}
		hideEmptySections(doc);
		var other = doc.querySelector('[data-a7-plf="other"]');
		if (other) {
			var kids = other.querySelectorAll(
				".ui-entity-editor-content-block, .ui-entity-editor-field, .crm-entity-widget-content-block"
			);
			other.style.display = kids.length ? "" : "none";
		}
		return { moved: moved, hidden: hidden, blocks: blocks.length };
	}

	function organize() {
		var result = null;
		docsToScan().forEach(function (doc) {
			try {
				var r = organizeDoc(doc);
				if (r) {
					result = r;
				}
			} catch (e) {}
		});
		return result;
	}

	/* ---------------- Create-field password lock ---------------- */

	function showModal() {
		return new Promise(function (resolve, reject) {
			var overlay = document.createElement("div");
			overlay.setAttribute("data-a7-plf-admin", "1");
			overlay.style.cssText =
				"position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;";
			var box = document.createElement("div");
			box.style.cssText =
				"background:#fff;color:#333;min-width:320px;max-width:420px;padding:20px 22px;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.25);font-family:Arial,sans-serif;";
			var h = document.createElement("div");
			h.textContent = TITLE;
			h.style.cssText = "font-size:16px;font-weight:700;margin-bottom:8px;";
			var p = document.createElement("div");
			p.textContent = TEXT;
			p.style.cssText = "font-size:13px;margin-bottom:12px;line-height:1.4;";
			var input = document.createElement("input");
			input.type = "password";
			input.autocomplete = "off";
			input.style.cssText =
				"width:100%;box-sizing:border-box;padding:8px 10px;font-size:14px;border:1px solid #c6c6c6;border-radius:4px;";
			var row = document.createElement("div");
			row.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:14px;";
			var cancel = document.createElement("button");
			cancel.type = "button";
			cancel.textContent = "Cancel";
			cancel.style.cssText = "padding:6px 12px;cursor:pointer;";
			var ok = document.createElement("button");
			ok.type = "button";
			ok.textContent = "Continue";
			ok.style.cssText =
				"padding:6px 14px;cursor:pointer;background:#2fc6f6;border:0;color:#fff;border-radius:4px;font-weight:600;";
			row.appendChild(cancel);
			row.appendChild(ok);
			box.appendChild(h);
			box.appendChild(p);
			box.appendChild(input);
			box.appendChild(row);
			overlay.appendChild(box);
			document.body.appendChild(overlay);
			setTimeout(function () {
				try {
					input.focus();
				} catch (e) {}
			}, 0);

			function close() {
				if (overlay.parentNode) {
					overlay.parentNode.removeChild(overlay);
				}
			}
			cancel.addEventListener("click", function () {
				close();
				reject(new Error("cancelled"));
			});
			ok.addEventListener("click", function () {
				var v = String(input.value || "");
				close();
				if (v === "") {
					window.alert("Admin password required. New field was not created.");
					reject(new Error("empty"));
					return;
				}
				resolve(v);
			});
			input.addEventListener("keydown", function (ev) {
				if (ev.key === "Enter") {
					ev.preventDefault();
					ok.click();
				}
				if (ev.key === "Escape") {
					ev.preventDefault();
					cancel.click();
				}
			});
		});
	}

	function cachedPassword() {
		return String(window.__a7PlfPwdReady || "");
	}

	function rememberPassword(pwd) {
		window.__a7PlfPwdReady = String(pwd || "");
		window.setTimeout(function () {
			window.__a7PlfPwdReady = "";
		}, 120000);
	}

	function askPassword() {
		var cached = cachedPassword();
		if (cached) {
			return Promise.resolve(cached);
		}
		return showModal().then(function (pwd) {
			rememberPassword(pwd);
			return pwd;
		});
	}

	function looksCreateFieldAction(action) {
		var a = String(action || "").toLowerCase();
		if (!a) {
			return false;
		}
		if (a.indexOf("delete") !== -1 || a.indexOf("update") !== -1 || a.indexOf("list") !== -1 || a.indexOf("get") !== -1) {
			return false;
		}
		return (
			a.indexOf("userfieldconfig.add") !== -1 ||
			a.indexOf("userfield.add") !== -1 ||
			a.indexOf("user.type.add") !== -1 ||
			(a.indexOf("userfield") !== -1 && a.indexOf("add") !== -1)
		);
	}

	function urlLooksLikeFieldCreate(url) {
		var u = String(url || "").toLowerCase();
		if (!u || u.indexOf("delete") !== -1) {
			return false;
		}
		return (
			(u.indexOf("userfieldconfig") !== -1 && u.indexOf("add") !== -1) ||
			u.indexOf("userfieldconfig.add") !== -1
		);
	}

	function putPasswordOnHeaders(init, pwd) {
		init.headers = init.headers || {};
		if (init.headers instanceof Headers) {
			init.headers.set("X-A7-Stage-Admin-Password", pwd);
			return;
		}
		init.headers["X-A7-Stage-Admin-Password"] = pwd;
	}

	function patchBxAjax() {
		if (!window.BX || typeof BX.ajax !== "function" || BX.ajax.__a7PlfPatched) {
			return false;
		}
		var original = BX.ajax;
		function wrapped(config) {
			try {
				if (config && typeof config === "object") {
					var action = (config.data && (config.data.action || config.data.ACTION)) || config.url || "";
					if (looksCreateFieldAction(action) || urlLooksLikeFieldCreate(config.url)) {
						var data = config.data || {};
						if (!data[PARAM]) {
							return askPassword()
								.then(function (pwd) {
									config.data = data;
									config.data[PARAM] = pwd;
									return original.call(BX, config);
								})
								.catch(function () {
									if (typeof config.onfailure === "function") {
										config.onfailure("cancelled");
									}
								});
						}
					}
				}
			} catch (e) {}
			return original.apply(this, arguments);
		}
		for (var k in original) {
			if (Object.prototype.hasOwnProperty.call(original, k)) {
				wrapped[k] = original[k];
			}
		}
		if (typeof original.runAction === "function") {
			wrapped.runAction = function (action, config) {
				config = config || {};
				var data = config.data || {};
				if (looksCreateFieldAction(action) && !data[PARAM]) {
					return askPassword().then(function (pwd) {
						config.data = data;
						config.data[PARAM] = pwd;
						config.headers = config.headers || {};
						config.headers["X-A7-Stage-Admin-Password"] = pwd;
						return original.runAction.call(original, action, config);
					});
				}
				return original.runAction.apply(original, arguments);
			};
		}
		wrapped.__a7PlfPatched = true;
		BX.ajax = wrapped;
		return true;
	}

	function patchXHR() {
		if (XMLHttpRequest.prototype.__a7PlfPatched) {
			return;
		}
		var open = XMLHttpRequest.prototype.open;
		var send = XMLHttpRequest.prototype.send;
		XMLHttpRequest.prototype.open = function (method, url) {
			this.__a7PlfUrl = url;
			this.__a7PlfMethod = method;
			return open.apply(this, arguments);
		};
		XMLHttpRequest.prototype.send = function (body) {
			var xhr = this;
			var url = String(this.__a7PlfUrl || "");
			var method = String(this.__a7PlfMethod || "GET").toUpperCase();
			if (method !== "POST" || !urlLooksLikeFieldCreate(url)) {
				return send.call(this, body);
			}
			try {
				if (typeof body === "string") {
					if (body.indexOf(PARAM + "=") !== -1) {
						return send.call(this, body);
					}
					askPassword()
						.then(function (pwd) {
							send.call(
								xhr,
								body + (body.length ? "&" : "") + encodeURIComponent(PARAM) + "=" + encodeURIComponent(pwd)
							);
						})
						.catch(function () {});
					return;
				}
				if (body && typeof FormData !== "undefined" && body instanceof FormData) {
					if (body.get(PARAM)) {
						return send.call(this, body);
					}
					askPassword()
						.then(function (pwd) {
							body.append(PARAM, pwd);
							send.call(xhr, body);
						})
						.catch(function () {});
					return;
				}
			} catch (e) {}
			return send.call(this, body);
		};
		XMLHttpRequest.prototype.__a7PlfPatched = true;
	}

	function patchFetch() {
		if (!window.fetch || window.fetch.__a7PlfPatched) {
			return;
		}
		var original = window.fetch;
		window.fetch = function (input, init) {
			try {
				var url = typeof input === "string" ? input : (input && input.url) || "";
				init = init || {};
				if (String(init.method || "GET").toUpperCase() !== "POST") {
					return original.call(this, input, init);
				}
				if (!urlLooksLikeFieldCreate(url) && !looksCreateFieldAction(url)) {
					return original.call(this, input, init);
				}
				var body = init.body;
				if (typeof body === "string" && body.indexOf(PARAM + "=") === -1) {
					return askPassword().then(function (pwd) {
						var next = Object.assign({}, init, {
							body: body + (body.length ? "&" : "") + encodeURIComponent(PARAM) + "=" + encodeURIComponent(pwd),
						});
						putPasswordOnHeaders(next, pwd);
						return original.call(window, input, next);
					});
				}
			} catch (e) {}
			return original.call(this, input, init);
		};
		window.fetch.__a7PlfPatched = true;
	}

	function bootLock() {
		if (CFG.lockCreate === false) {
			return;
		}
		patchBxAjax();
		patchXHR();
		patchFetch();
		document.addEventListener(
			"pointerdown",
			function () {
				patchBxAjax();
			},
			true
		);
		var tries = 0;
		var t = setInterval(function () {
			tries++;
			patchBxAjax();
			if (tries > 120) {
				clearInterval(t);
			}
		}, 500);
	}

	function bootLayout() {
		organize();
		var scheduled = 0;
		function schedule() {
			if (scheduled) {
				return;
			}
			scheduled = window.setTimeout(function () {
				scheduled = 0;
				organize();
			}, 200);
		}
		if (window.MutationObserver && document.documentElement) {
			var observer = new MutationObserver(schedule);
			observer.observe(document.documentElement, { childList: true, subtree: true });
		}
		if (window.BX && BX.addCustomEvent) {
			BX.addCustomEvent("SidePanel.Slider:onLoad", function () {
				window.setTimeout(organize, 100);
				window.setTimeout(organize, 600);
				window.setTimeout(organize, 1500);
			});
			BX.addCustomEvent("SidePanel.Slider:onOpenComplete", function () {
				window.setTimeout(organize, 100);
				window.setTimeout(organize, 800);
			});
		}
		[300, 800, 1500, 3000, 5000].forEach(function (ms) {
			window.setTimeout(organize, ms);
		});
	}

	bootLock();
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", bootLayout);
	} else {
		bootLayout();
	}
})();
