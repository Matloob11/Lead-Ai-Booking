(function () {
	"use strict";

	var HR_CV_TYPES = { 1156: true, 1210: true };
	var PANEL_ID = "a7-hr-cv-stage-panel";
	var LIST_ID = "a7-hr-cv-stage-list";
	var busy = false;
	var started = false;

	function parseDetails() {
		var match = String(window.location.pathname || "").match(/\/type\/(1156|1210)\/details\/(\d+)/);
		if (!match) {
			return null;
		}
		var entityTypeId = parseInt(match[1], 10);
		if (!HR_CV_TYPES[entityTypeId]) {
			return null;
		}
		return {
			entityTypeId: entityTypeId,
			itemId: parseInt(match[2], 10)
		};
	}

	function notify(message) {
		if (window.BX && BX.UI && BX.UI.Notification && BX.UI.Notification.Center) {
			BX.UI.Notification.Center.notify({
				content: message,
				autoHideDelay: 4000
			});
			return;
		}
		window.alert(message);
	}

	function post(payload) {
		var sessid = window.BX && BX.bitrix_sessid ? BX.bitrix_sessid() : "";
		return fetch("/local/ajax/a7_hr_cv_stage.php", {
			method: "POST",
			credentials: "same-origin",
			headers: {
				"Content-Type": "application/json",
				"X-Bitrix-Csrf-Token": sessid
			},
			body: JSON.stringify(Object.assign({ sessid: sessid }, payload))
		}).then(function (res) {
			return res.json().then(function (data) {
				if (!res.ok || !data || !data.ok) {
					throw new Error((data && data.error) || "Could not update category");
				}
				return data;
			});
		});
	}

	function fillOptions(list, input, options, selected) {
		list.innerHTML = "";
		(options || []).forEach(function (option) {
			var node = document.createElement("option");
			node.value = option.name;
			list.appendChild(node);
		});
		input.value = selected || "";
	}

	function mountPanel() {
		var details = parseDetails();
		if (!details) {
			var leftover = document.getElementById(PANEL_ID);
			if (leftover) {
				leftover.remove();
			}
			return;
		}

		var host =
			document.querySelector(".crm-entity-stream-container-content") ||
			document.querySelector(".crm-entity-stream-container") ||
			document.querySelector(".crm-entity-section-info") ||
			document.querySelector(".ui-entity-slider-content");
		if (!host) {
			return;
		}

		var panel = document.getElementById(PANEL_ID);
		if (!panel) {
			panel = document.createElement("div");
			panel.id = PANEL_ID;
			panel.className = "a7-hr-cv-stage";
			panel.innerHTML =
				'<div class="a7-hr-cv-stage__title">Applicant category</div>' +
				'<div class="a7-hr-cv-stage__row">' +
				'<input class="a7-hr-cv-stage__input" list="' + LIST_ID + '" maxlength="80" placeholder="Select or type a new category" aria-label="Applicant category" />' +
				'<datalist id="' + LIST_ID + '"></datalist>' +
				'<button type="button" class="a7-hr-cv-stage__save">Save</button>' +
				"</div>" +
				'<div class="a7-hr-cv-stage__hint">Pick an existing category or type a new name, then save. A new name creates that category and moves this CV there.</div>';
			if (host.firstChild) {
				host.insertBefore(panel, host.firstChild);
			} else {
				host.appendChild(panel);
			}
		} else if (panel.parentNode !== host) {
			host.insertBefore(panel, host.firstChild);
		}

		var input = panel.querySelector(".a7-hr-cv-stage__input");
		var list = panel.querySelector("#" + LIST_ID);
		var save = panel.querySelector(".a7-hr-cv-stage__save");
		if (!input || !list || !save || panel.dataset.ready === "1") {
			return;
		}
		panel.dataset.ready = "1";
		panel.dataset.entityTypeId = String(details.entityTypeId);
		panel.dataset.itemId = String(details.itemId);

		post({
			action: "list",
			entityTypeId: details.entityTypeId,
			itemId: details.itemId
		})
			.then(function (data) {
				fillOptions(list, input, data.options || [], data.selected || "");
			})
			.catch(function (error) {
				notify(error.message);
			});

		save.addEventListener("click", function () {
			if (busy) {
				return;
			}
			var name = String(input.value || "").trim();
			if (!name) {
				notify("Enter or select a category first.");
				return;
			}
			busy = true;
			save.disabled = true;
			post({
				action: "save",
				entityTypeId: details.entityTypeId,
				itemId: details.itemId,
				stageName: name
			})
				.then(function (data) {
					fillOptions(list, input, data.options || [], data.selected || name);
					notify(
						data.created
							? "Category created and CV moved to " + (data.selected || name) + "."
							: "CV moved to " + (data.selected || name) + "."
					);
				})
				.catch(function (error) {
					notify(error.message);
				})
				.then(function () {
					busy = false;
					save.disabled = false;
				});
		});

		input.addEventListener("keydown", function (event) {
			if (event.key === "Enter") {
				event.preventDefault();
				save.click();
			}
		});
	}

	function start() {
		if (started) {
			mountPanel();
			return;
		}
		started = true;
		mountPanel();
		if (typeof MutationObserver === "function") {
			var observer = new MutationObserver(function () {
				var details = parseDetails();
				var panel = document.getElementById(PANEL_ID);
				if (details && !panel) {
					mountPanel();
					return;
				}
				if (details && panel && panel.dataset.itemId !== String(details.itemId)) {
					panel.remove();
					mountPanel();
				}
			});
			observer.observe(document.body, { childList: true, subtree: true });
		}
		window.setInterval(mountPanel, 2000);
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start);
	} else {
		start();
	}
})();
