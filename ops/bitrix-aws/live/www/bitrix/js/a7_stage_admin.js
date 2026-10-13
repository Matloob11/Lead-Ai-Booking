/**
 * A7 Stage Admin — ask for admin password before kanban "+" creates a new stage.
 * Server still enforces the password; this is only the UX prompt.
 * HR PAK/UAE managers (Usman) skip the prompt on those boards only.
 */
(function () {
	"use strict";

	if (window.__A7_STAGE_ADMIN_JS__) {
		return;
	}
	window.__A7_STAGE_ADMIN_JS__ = true;

	var CFG = window.A7_STAGE_ADMIN || {};
	var PARAM = CFG.param || "a7_stage_admin_password";
	var TITLE = CFG.title || "Admin password required";
	var TEXT = CFG.text || "Enter admin password to create a new stage:";
	var HR_TYPES = {};
	(CFG.hrTypes || [1156, 1160, 1168, 1172, 1210, 1212, 1214, 1216]).forEach(function (id) {
		HR_TYPES[Number(id)] = true;
	});

	function isHrPage() {
		var path = String(window.location.pathname || "");
		if (/\/page\/hr_(pak|uae)(\/|$)/i.test(path)) {
			return true;
		}
		var m = path.match(/\/type\/(\d+)(?:\/|$)/);
		if (m && HR_TYPES[Number(m[1])]) {
			return true;
		}
		return false;
	}

	function skipPrompt() {
		return !!CFG.bypassHr && isHrPage();
	}

	function looksCreateAction(action) {
		var a = String(action || "").toLowerCase();
		if (!a) {
			return false;
		}
		if (a.indexOf("delete") !== -1 || a.indexOf("remove") !== -1) {
			return false;
		}
		return (
			a === "modifystage" ||
			a.indexOf("addstage") !== -1 ||
			a.indexOf("createstage") !== -1 ||
			a.indexOf("stage.add") !== -1 ||
			a.indexOf("stage.create") !== -1
		);
	}

	function isCreateStagePayload(data) {
		if (!data || typeof data !== "object") {
			return false;
		}
		if (data.delete === 1 || data.delete === "1" || data.delete === true || data.delete === "Y") {
			return false;
		}
		if (!looksCreateAction(data.action) && !looksCreateAction(data.ACTION)) {
			return false;
		}
		var columnId = data.columnId;
		if (columnId !== undefined && columnId !== null && String(columnId) !== "" && String(columnId) !== "0") {
			return false;
		}
		return true;
	}

	function urlLooksLikeStageCreate(url) {
		if (!url) {
			return false;
		}
		var u = String(url).toLowerCase();
		if (u.indexOf("delete") !== -1 && u.indexOf("stage") !== -1) {
			return false;
		}
		if (u.indexOf("crm.kanban") !== -1 && u.indexOf("modifystage") !== -1) {
			return true;
		}
		return (
			u.indexOf("addstage") !== -1 ||
			u.indexOf("createstage") !== -1 ||
			u.indexOf("stage.add") !== -1 ||
			u.indexOf("stage.create") !== -1
		);
	}

	function showModal() {
		return new Promise(function (resolve, reject) {
			var overlay = document.createElement("div");
			overlay.setAttribute("data-a7-stage-admin", "1");
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
					window.alert("Admin password required. New stage was not created.");
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

	function askPassword() {
		if (skipPrompt()) {
			return Promise.resolve("");
		}
		return showModal();
	}

	function ensurePasswordOnData(data) {
		if (skipPrompt()) {
			return Promise.resolve(true);
		}
		if (!isCreateStagePayload(data)) {
			return Promise.resolve(true);
		}
		if (data[PARAM]) {
			return Promise.resolve(true);
		}
		return askPassword().then(function (pwd) {
			data[PARAM] = pwd;
			return true;
		});
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
		if (!window.BX || typeof BX.ajax !== "function" || BX.ajax.__a7StageAdminPatched) {
			return false;
		}
		var original = BX.ajax;
		function wrapped(config) {
			try {
				if (config && typeof config === "object" && config.data && isCreateStagePayload(config.data)) {
					if (skipPrompt()) {
						return original.apply(this, arguments);
					}
					if (!config.data[PARAM]) {
						return askPassword()
							.then(function (pwd) {
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
				var looks = looksCreateAction(action) || isCreateStagePayload(data);
				if (looks && !skipPrompt() && !(data && data[PARAM])) {
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
		wrapped.__a7StageAdminPatched = true;
		BX.ajax = wrapped;
		return true;
	}

	function patchXHR() {
		if (XMLHttpRequest.prototype.__a7StageAdminPatched) {
			return;
		}
		var open = XMLHttpRequest.prototype.open;
		var send = XMLHttpRequest.prototype.send;

		XMLHttpRequest.prototype.open = function (method, url) {
			this.__a7Url = url;
			this.__a7Method = method;
			return open.apply(this, arguments);
		};

		XMLHttpRequest.prototype.send = function (body) {
			var xhr = this;
			var url = String(this.__a7Url || "");
			var method = String(this.__a7Method || "GET").toUpperCase();
			if (skipPrompt() || method !== "POST" || !urlLooksLikeStageCreate(url)) {
				return send.call(this, body);
			}
			try {
				if (typeof body === "string") {
					if (body.indexOf(PARAM + "=") !== -1) {
						return send.call(this, body);
					}
					var m = body.match(/(?:^|&)columnId=([^&]*)/);
					if (m && decodeURIComponent(m[1]) !== "" && decodeURIComponent(m[1]) !== "0") {
						return send.call(this, body);
					}
					if (/(?:^|&)delete=1(?:&|$)/.test(body)) {
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
					var cid = body.get("columnId");
					var del = body.get("delete");
					if (del === "1" || del === 1) {
						return send.call(this, body);
					}
					if (cid !== null && String(cid) !== "" && String(cid) !== "0") {
						return send.call(this, body);
					}
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

		XMLHttpRequest.prototype.__a7StageAdminPatched = true;
	}

	function patchFetch() {
		if (!window.fetch || window.fetch.__a7StageAdminPatched) {
			return;
		}
		var original = window.fetch;
		window.fetch = function (input, init) {
			try {
				var url = typeof input === "string" ? input : (input && input.url) || "";
				init = init || {};
				if (skipPrompt() || String(init.method || "GET").toUpperCase() !== "POST") {
					return original.call(this, input, init);
				}
				if (!urlLooksLikeStageCreate(url) && !looksCreateAction(url)) {
					return original.call(this, input, init);
				}
				var body = init.body;
				if (typeof body === "string" && body.indexOf(PARAM + "=") === -1) {
					var m = body.match(/(?:^|&)columnId=([^&]*)/);
					if (m && decodeURIComponent(m[1]) !== "" && decodeURIComponent(m[1]) !== "0") {
						return original.call(this, input, init);
					}
					if (/(?:^|&)delete=1(?:&|$)/.test(body)) {
						return original.call(this, input, init);
					}
					return askPassword().then(function (pwd) {
						var next = Object.assign({}, init, {
							body: body + (body.length ? "&" : "") + encodeURIComponent(PARAM) + "=" + encodeURIComponent(pwd)
						});
						putPasswordOnHeaders(next, pwd);
						return original.call(window, input, next);
					});
				}
			} catch (e) {}
			return original.call(this, input, init);
		};
		window.fetch.__a7StageAdminPatched = true;
	}

	function boot() {
		patchBxAjax();
		patchXHR();
		patchFetch();
	}

	boot();
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
})();
