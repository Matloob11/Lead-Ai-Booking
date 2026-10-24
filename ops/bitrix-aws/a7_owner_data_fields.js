/**
 * A7 Owner Data Fields — password only for:
 *   Select field | Create field | Hide field | Delete section
 * on SPA 1042 details cards. Values + field settings stay free.
 * Kanban/list clicks are never gated.
 */
(function () {
	"use strict";

	if (window.__A7_OWNER_DATA_FIELDS_JS__) {
		return;
	}
	window.__A7_OWNER_DATA_FIELDS_JS__ = true;

	var CFG = window.A7_OWNER_DATA_FIELDS || {};
	if (CFG.lockFields === false) {
		return;
	}

	var PARAM = CFG.param || "a7_stage_admin_password";
	var TITLE = CFG.title || "Admin password required";
	var TEXT =
		CFG.text ||
		"Enter admin password to Select field, Create field, Hide field, or Delete section:";
	var TYPE_ID = String(CFG.typeId || 1042);

	// Exact UI labels from the Owner Data details card (English).
	var UI_EXACT_RE =
		/^(select\s+field|create\s+field|hide(\s+field)?|delete\s+section)$/i;

	function pathIsOwnerDetails(path) {
		return /\/crm\/type\/1042\/details\//i.test(String(path || ""));
	}

	function onOwnerDetails() {
		if (pathIsOwnerDetails(window.location.pathname) || pathIsOwnerDetails(window.location.href)) {
			return true;
		}
		try {
			if (window.BX && BX.SidePanel && BX.SidePanel.Instance) {
				var slider =
					BX.SidePanel.Instance.getTopSlider && BX.SidePanel.Instance.getTopSlider();
				if (slider && slider.getUrl && pathIsOwnerDetails(slider.getUrl())) {
					return true;
				}
			}
		} catch (e) {}
		// Details editor open in this document (side panel ajax).
		try {
			if (
				document.querySelector(
					".ui-entity-editor-section-content a, .ui-entity-editor-section-actions"
				) &&
				/\/crm\/type\/1042\//i.test(String(window.location.pathname || ""))
			) {
				var links = document.querySelectorAll(
					".ui-entity-editor-section-content, .ui-entity-editor-section-actions, .ui-entity-editor-add-field"
				);
				for (var i = 0; i < links.length; i++) {
					var t = String(links[i].textContent || "");
					if (/select\s+field|create\s+field/i.test(t)) {
						return true;
					}
				}
			}
		} catch (e2) {}
		return false;
	}

	function showModal() {
		return new Promise(function (resolve, reject) {
			var overlay = document.createElement("div");
			overlay.className = "a7-odf-overlay";
			overlay.setAttribute("data-a7-odf-admin", "1");
			var box = document.createElement("div");
			box.className = "a7-odf-box";
			var h = document.createElement("div");
			h.className = "a7-odf-title";
			h.textContent = TITLE;
			var p = document.createElement("div");
			p.className = "a7-odf-text";
			p.textContent = TEXT;
			var input = document.createElement("input");
			input.type = "password";
			input.autocomplete = "off";
			input.className = "a7-odf-input";
			var row = document.createElement("div");
			row.className = "a7-odf-row";
			var cancel = document.createElement("button");
			cancel.type = "button";
			cancel.className = "a7-odf-btn";
			cancel.textContent = "Cancel";
			var ok = document.createElement("button");
			ok.type = "button";
			ok.className = "a7-odf-btn a7-odf-btn-ok";
			ok.textContent = "Continue";
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
					window.alert("Admin password required.");
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
		return String(window.__a7OdfPwdReady || "");
	}

	function rememberPassword(pwd) {
		window.__a7OdfPwdReady = String(pwd || "");
		window.setTimeout(function () {
			window.__a7OdfPwdReady = "";
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

	/** Create field AJAX only — not update/settings. */
	function looksCreateFieldAction(action) {
		var a = String(action || "").toLowerCase();
		if (!a) {
			return false;
		}
		if (a.indexOf("update") !== -1 || a.indexOf("delete") !== -1 || a.indexOf("list") !== -1 || a.indexOf("get") !== -1) {
			return false;
		}
		return (
			a.indexOf("userfieldconfig.add") !== -1 ||
			a.indexOf("userfield.add") !== -1 ||
			a.indexOf("user.type.add") !== -1 ||
			(a.indexOf("userfieldconfig") !== -1 && a.indexOf("add") !== -1)
		);
	}

	/** Card layout save: select / hide / delete section. */
	function looksLayoutSaveAction(action) {
		var a = String(action || "").toLowerCase();
		if (!a) {
			return false;
		}
		if (a.indexOf("userfieldconfig") !== -1) {
			return false;
		}
		if (
			a.indexOf("entityeditor") === -1 &&
			a.indexOf("entity.editor") === -1 &&
			a.indexOf("entityform") === -1 &&
			a.indexOf("formconfiguration") === -1 &&
			a.indexOf("editorconfig") === -1
		) {
			return false;
		}
		if (a.indexOf("get") !== -1 || a.indexOf("list") !== -1 || a.indexOf("load") !== -1 || a.indexOf("fetch") !== -1) {
			return false;
		}
		return (
			a.indexOf("set") !== -1 ||
			a.indexOf("save") !== -1 ||
			a.indexOf("update") !== -1 ||
			a.indexOf("reset") !== -1 ||
			a.indexOf("delete") !== -1 ||
			a.indexOf("add") !== -1
		);
	}

	function looksLockedAction(action) {
		return looksCreateFieldAction(action) || looksLayoutSaveAction(action);
	}

	function payloadMentionsOwner(data) {
		try {
			var raw = typeof data === "string" ? data : JSON.stringify(data || {});
			var s = String(raw || "").toLowerCase();
			if (s.indexOf("crm_5") !== -1) {
				return true;
			}
			if (s.indexOf("entitytypeid") !== -1 && s.indexOf(TYPE_ID) !== -1) {
				return true;
			}
			if (s.indexOf('"1042"') !== -1 || s.indexOf("'1042'") !== -1 || s.indexOf(":1042") !== -1) {
				return true;
			}
		} catch (e) {}
		return onOwnerDetails();
	}

	function putPasswordOnHeaders(init, pwd) {
		init.headers = init.headers || {};
		if (init.headers instanceof Headers) {
			init.headers.set("X-A7-Stage-Admin-Password", pwd);
			return;
		}
		init.headers["X-A7-Stage-Admin-Password"] = pwd;
	}

	function appendPasswordToBody(body, pwd) {
		if (typeof body === "string") {
			if (body.indexOf(PARAM + "=") !== -1) {
				return body;
			}
			return body + (body.length ? "&" : "") + encodeURIComponent(PARAM) + "=" + encodeURIComponent(pwd);
		}
		if (body && typeof FormData !== "undefined" && body instanceof FormData) {
			if (!body.get(PARAM)) {
				body.append(PARAM, pwd);
			}
			return body;
		}
		return body;
	}

	function shouldGateAjax(action, data) {
		if (!looksLockedAction(action)) {
			return false;
		}
		if (!payloadMentionsOwner(data) && !onOwnerDetails()) {
			return false;
		}
		return true;
	}

	function patchBxAjax() {
		if (!window.BX || typeof BX.ajax !== "function" || BX.ajax.__a7OdfPatched) {
			return false;
		}
		var original = BX.ajax;
		function wrapped(config) {
			try {
				if (config && typeof config === "object") {
					var action = (config.data && (config.data.action || config.data.ACTION)) || config.url || "";
					if (shouldGateAjax(action, config.data) || shouldGateAjax(config.url, config.data)) {
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
				if (shouldGateAjax(action, data) && !data[PARAM]) {
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
		if (typeof original.runComponentAction === "function") {
			wrapped.runComponentAction = function (component, action, config) {
				config = config || {};
				var combined = String(component || "") + "." + String(action || "");
				var data = config.data || {};
				if (shouldGateAjax(combined, data) && !data[PARAM]) {
					return askPassword().then(function (pwd) {
						config.data = data;
						config.data[PARAM] = pwd;
						config.headers = config.headers || {};
						config.headers["X-A7-Stage-Admin-Password"] = pwd;
						return original.runComponentAction.call(original, component, action, config);
					});
				}
				return original.runComponentAction.apply(original, arguments);
			};
		}
		wrapped.__a7OdfPatched = true;
		BX.ajax = wrapped;
		return true;
	}

	function patchXHR() {
		if (XMLHttpRequest.prototype.__a7OdfPatched) {
			return;
		}
		var open = XMLHttpRequest.prototype.open;
		var send = XMLHttpRequest.prototype.send;
		XMLHttpRequest.prototype.open = function (method, url) {
			this.__a7OdfUrl = url;
			this.__a7OdfMethod = method;
			return open.apply(this, arguments);
		};
		XMLHttpRequest.prototype.send = function (body) {
			var xhr = this;
			var url = String(this.__a7OdfUrl || "");
			var method = String(this.__a7OdfMethod || "GET").toUpperCase();
			if (method !== "POST" || !shouldGateAjax(url, body)) {
				return send.call(this, body);
			}
			try {
				if (typeof body === "string" && body.indexOf(PARAM + "=") !== -1) {
					return send.call(this, body);
				}
				if (body && typeof FormData !== "undefined" && body instanceof FormData && body.get(PARAM)) {
					return send.call(this, body);
				}
				askPassword()
					.then(function (pwd) {
						try {
							xhr.setRequestHeader("X-A7-Stage-Admin-Password", pwd);
						} catch (e) {}
						send.call(xhr, appendPasswordToBody(body, pwd));
					})
					.catch(function () {});
				return;
			} catch (e2) {}
			return send.call(this, body);
		};
		XMLHttpRequest.prototype.__a7OdfPatched = true;
	}

	function patchFetch() {
		if (!window.fetch || window.fetch.__a7OdfPatched) {
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
				if (!shouldGateAjax(url, init.body)) {
					return original.call(this, input, init);
				}
				var body = init.body;
				if (typeof body === "string" && body.indexOf(PARAM + "=") !== -1) {
					return original.call(this, input, init);
				}
				return askPassword().then(function (pwd) {
					var next = Object.assign({}, init, {
						body: appendPasswordToBody(body, pwd),
					});
					putPasswordOnHeaders(next, pwd);
					return original.call(window, input, next);
				});
			} catch (e) {}
			return original.call(this, input, init);
		};
		window.fetch.__a7OdfPatched = true;
	}

	function buttonLabel(el) {
		if (!el) {
			return "";
		}
		var t = String(el.getAttribute("title") || el.getAttribute("data-hint") || "").trim();
		if (t && UI_EXACT_RE.test(t)) {
			return t;
		}
		return String(el.textContent || "")
			.replace(/\s+/g, " ")
			.trim();
	}

	function isLockedUiTarget(el) {
		if (!el || !el.closest) {
			return false;
		}
		if (el.closest("[data-a7-odf-admin]")) {
			return false;
		}
		var node = el;
		for (var i = 0; i < 5 && node; i++) {
			var label = buttonLabel(node);
			if (label && UI_EXACT_RE.test(label)) {
				return true;
			}
			var aria = String((node.getAttribute && node.getAttribute("aria-label")) || "").trim();
			if (aria && UI_EXACT_RE.test(aria)) {
				return true;
			}
			node = node.parentElement;
		}
		return false;
	}

	function gateUiClicks() {
		if (document.documentElement.getAttribute("data-a7-odf-click") === "1") {
			return;
		}
		document.documentElement.setAttribute("data-a7-odf-click", "1");
		document.addEventListener(
			"click",
			function (ev) {
				if (!onOwnerDetails()) {
					return;
				}
				if (cachedPassword()) {
					return;
				}
				if (!isLockedUiTarget(ev.target)) {
					return;
				}
				ev.preventDefault();
				ev.stopPropagation();
				if (typeof ev.stopImmediatePropagation === "function") {
					ev.stopImmediatePropagation();
				}
				askPassword().catch(function () {});
			},
			true
		);
	}

	function boot() {
		patchBxAjax();
		patchXHR();
		patchFetch();
		gateUiClicks();
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

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", boot);
	} else {
		boot();
	}
})();
