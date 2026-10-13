(function () {
	"use strict";

	var HR_CV_TYPES = { 1156: true, 1210: true };
	var PANEL_ID = "a7-hr-applied-badge";
	var MENU_ID = "a7-hr-applied-badge-menu";
	var DEFAULT_OPTIONS = [
		{ name: "IT Team", color: "#2F80ED" },
		{ name: "Sales Associate", color: "#27AE60" },
		{ name: "Social Media", color: "#9B51E0" },
		{ name: "HR", color: "#EB6EA5" },
		{ name: "Finance", color: "#F2C94C" },
		{ name: "Receptionist", color: "#F2994A" }
	];
	var busy = false;
	var started = false;

	function parseDetails() {
		var match = String(window.location.pathname || "").match(/\/type\/(1156|1210)\/details\/(\d+)/);
		if (!match) {
			return null;
		}
		return {
			entityTypeId: parseInt(match[1], 10),
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
		return fetch("/local/ajax/a7_hr_applied_badge.php", {
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
					throw new Error((data && data.error) || "Could not update position");
				}
				return data;
			});
		});
	}

	function findHost() {
		return (
			document.querySelector(".crm-entity-card-container") ||
			document.querySelector(".ui-entity-editor-column") ||
			document.querySelector(".crm-entity-section-info") ||
			document.querySelector(".ui-entity-editor")
		);
	}

	function shortPosition(name) {
		name = String(name || "").trim();
		if (!name) {
			return "";
		}
		var known = {
			"it team": "IT",
			"sales associate": "SA",
			"social media": "SM",
			"hr": "HR",
			"finance": "FIN",
			"receptionist": "REC"
		};
		var key = name.toLowerCase();
		if (known[key]) {
			return known[key];
		}
		var words = name.split(/\s+/).filter(Boolean);
		if (words.length >= 2) {
			return words.slice(0, 3).map(function (word) {
				return String(word.charAt(0) || "").toUpperCase();
			}).join("");
		}
		return name.replace(/[^A-Za-z0-9]/g, "").slice(0, 3).toUpperCase();
	}

	function contrastText(color) {
		var hex = String(color || "").replace("#", "");
		if (hex.length !== 6) {
			return "#fff";
		}
		var r = parseInt(hex.slice(0, 2), 16);
		var g = parseInt(hex.slice(2, 4), 16);
		var b = parseInt(hex.slice(4, 6), 16);
		var brightness = (r * 299 + g * 587 + b * 114) / 1000;
		return brightness > 160 ? "#1f252c" : "#fff";
	}

	function selectedOption(options, selected) {
		var wanted = String(selected || "").trim().toLowerCase();
		if (!wanted) {
			return null;
		}
		for (var i = 0; i < options.length; i++) {
			if (String(options[i].name || "").trim().toLowerCase() === wanted) {
				return options[i];
			}
		}
		return null;
	}

	function setBusy(panel, on) {
		busy = on;
		var trigger = panel.querySelector(".a7-hr-applied-badge__trigger");
		var menu = getMenu(panel);
		var save = (menu || panel).querySelector(".a7-hr-applied-badge__save");
		if (trigger) {
			trigger.disabled = on;
		}
		if (save) {
			save.disabled = on;
		}
		(menu || panel).querySelectorAll(".a7-hr-applied-badge__delete").forEach(function (btn) {
			btn.disabled = on;
		});
	}

	function getMenu(panel) {
		return document.getElementById(MENU_ID) || (panel && panel.querySelector(".a7-hr-applied-badge__menu"));
	}

	function showError(panel, message) {
		var menu = getMenu(panel);
		var error = (menu || panel).querySelector(".a7-hr-applied-badge__error");
		if (!error) {
			return;
		}
		if (message) {
			error.textContent = message;
			panel.classList.add("has-error");
			return;
		}
		error.textContent = "";
		panel.classList.remove("has-error");
	}

	function paint(panel, options, selected) {
		var triggerDot = panel.querySelector(".a7-hr-applied-badge__trigger-dot");
		var triggerName = panel.querySelector(".a7-hr-applied-badge__name");
		var menu = getMenu(panel);
		var list = (menu || panel).querySelector(".a7-hr-applied-badge__list");
		if (!triggerDot || !triggerName || !list) {
			return;
		}

		if (!options || !options.length) {
			options = DEFAULT_OPTIONS.slice();
		}
		panel.dataset.options = JSON.stringify(options || []);
		panel.dataset.selected = selected || "";

		var match = selectedOption(options || [], selected);
		if (match) {
			triggerDot.style.background = match.color || "#d5d7db";
			triggerDot.style.color = contrastText(match.color);
			triggerDot.textContent = shortPosition(match.name);
			triggerDot.classList.remove("is-empty");
			triggerName.textContent = match.name;
			triggerName.classList.remove("is-empty");
		} else {
			triggerDot.style.background = "";
			triggerDot.style.color = "";
			triggerDot.textContent = "";
			triggerDot.classList.add("is-empty");
			triggerName.textContent = "Select a position";
			triggerName.classList.add("is-empty");
		}

		list.innerHTML = "";
		if (!options || !options.length) {
			var empty = document.createElement("div");
			empty.className = "a7-hr-applied-badge__empty";
			empty.textContent = "No positions yet. Add one below.";
			list.appendChild(empty);
			return;
		}

		options.forEach(function (option) {
			var item = document.createElement("div");
			item.className = "a7-hr-applied-badge__item";
			if (match && option.name === match.name) {
				item.classList.add("is-selected");
			}

			var pick = document.createElement("button");
			pick.type = "button";
			pick.className = "a7-hr-applied-badge__row";
			pick.dataset.name = option.name;
			pick.setAttribute("role", "option");
			pick.setAttribute("aria-selected", match && option.name === match.name ? "true" : "false");

			var dot = document.createElement("span");
			dot.className = "a7-hr-applied-badge__dot";
			dot.style.background = option.color || "#d5d7db";
			dot.style.color = contrastText(option.color);
			dot.textContent = shortPosition(option.name);
			dot.setAttribute("aria-hidden", "true");

			var label = document.createElement("span");
			label.className = "a7-hr-applied-badge__row-name";
			label.textContent = option.name;

			pick.appendChild(dot);
			pick.appendChild(label);

			var del = document.createElement("button");
			del.type = "button";
			del.className = "a7-hr-applied-badge__delete";
			del.dataset.name = option.name;
			del.setAttribute("aria-label", "Delete " + option.name);
			del.textContent = "×";

			item.appendChild(pick);
			item.appendChild(del);
			list.appendChild(item);
		});
	}

	function request(panel, payload) {
		showError(panel, "");
		setBusy(panel, true);
		return post(Object.assign({
			entityTypeId: parseInt(panel.dataset.entityTypeId, 10),
			itemId: parseInt(panel.dataset.itemId, 10)
		}, payload))
			.then(function (data) {
				paint(panel, data.options || [], data.selected || "");
				var savedId = parseInt(panel.dataset.itemId, 10);
				if (savedId > 0) {
					kanbanCache[savedId] = {
						name: data.selected || "",
						color: data.color || "",
						ts: Date.now()
					};
					scheduleKanbanDots();
				}
				return data;
			})
			.catch(function (error) {
				showError(panel, error.message);
				notify(error.message);
			})
			.then(function (data) {
				setBusy(panel, false);
				return data;
			});
	}

	function placeMenu(panel) {
		var trigger = panel.querySelector(".a7-hr-applied-badge__trigger");
		var menu = document.getElementById(MENU_ID) || panel.querySelector(".a7-hr-applied-badge__menu");
		if (!trigger || !menu) {
			return;
		}
		var rect = trigger.getBoundingClientRect();
		var width = Math.max(rect.width, 280);
		menu.style.left = Math.max(12, rect.left) + "px";
		menu.style.top = rect.bottom + 6 + "px";
		menu.style.width = Math.min(width, window.innerWidth - 24) + "px";
		if (menu.parentNode !== document.body) {
			document.body.appendChild(menu);
		}
	}

	function closeMenu(panel) {
		if (!panel) {
			return;
		}
		panel.classList.remove("is-open");
		var trigger = panel.querySelector(".a7-hr-applied-badge__trigger");
		if (trigger) {
			trigger.setAttribute("aria-expanded", "false");
		}
		var menu = document.getElementById(MENU_ID);
		if (menu) {
			menu.classList.remove("is-open");
			if (menu.parentNode !== panel) {
				panel.appendChild(menu);
			}
		}
	}

	function openMenu(panel) {
		panel.classList.add("is-open");
		var trigger = panel.querySelector(".a7-hr-applied-badge__trigger");
		var menu = panel.querySelector(".a7-hr-applied-badge__menu") || document.getElementById(MENU_ID);
		if (trigger) {
			trigger.setAttribute("aria-expanded", "true");
		}
		if (menu) {
			menu.classList.add("is-open");
		}
		placeMenu(panel);
	}

	function mountPanel() {
		var details = parseDetails();
		if (!details || !HR_CV_TYPES[details.entityTypeId]) {
			var leftover = document.getElementById(PANEL_ID);
			if (leftover) {
				leftover.remove();
			}
			return;
		}

		var host = findHost();
		if (!host) {
			return;
		}

		var panel = document.getElementById(PANEL_ID);
		if (!panel) {
			panel = document.createElement("div");
			panel.id = PANEL_ID;
			panel.className = "a7-hr-applied-badge";
			panel.innerHTML =
				'<button type="button" class="a7-hr-applied-badge__trigger" aria-haspopup="listbox" aria-expanded="false">' +
				'<span class="a7-hr-applied-badge__dot a7-hr-applied-badge__trigger-dot is-empty" aria-hidden="true"></span>' +
				'<span class="a7-hr-applied-badge__copy">' +
				'<span class="a7-hr-applied-badge__label">Applied position</span>' +
				'<span class="a7-hr-applied-badge__name is-empty">Select a position</span>' +
				"</span>" +
				'<span class="a7-hr-applied-badge__chevron" aria-hidden="true">▾</span>' +
				"</button>" +
				'<div class="a7-hr-applied-badge__menu" id="a7-hr-applied-badge-menu">' +
				'<div class="a7-hr-applied-badge__list" role="listbox" aria-label="Positions"></div>' +
				'<div class="a7-hr-applied-badge__form">' +
				'<input class="a7-hr-applied-badge__input" type="text" maxlength="80" placeholder="New position" aria-label="New position name" />' +
				'<input class="a7-hr-applied-badge__color" type="color" value="#2F80ED" aria-label="Position color" />' +
				'<button type="button" class="a7-hr-applied-badge__save">Add</button>' +
				"</div>" +
				'<button type="button" class="a7-hr-applied-badge__clear">Clear from this CV</button>' +
				'<div class="a7-hr-applied-badge__error" role="alert"></div>' +
				"</div>";
			if (host.firstChild) {
				host.insertBefore(panel, host.firstChild);
			} else {
				host.appendChild(panel);
			}
		} else if (panel.parentNode !== host) {
			host.insertBefore(panel, host.firstChild);
		}

		if (panel.dataset.ready === "1" && panel.dataset.itemId === String(details.itemId)) {
			return;
		}
		panel.dataset.ready = "1";
		panel.dataset.entityTypeId = String(details.entityTypeId);
		panel.dataset.itemId = String(details.itemId);
		closeMenu(panel);

		request(panel, { action: "list" });

		if (panel.dataset.bound === "1") {
			return;
		}
		panel.dataset.bound = "1";

		function onWidgetClick(event) {
			var currentPanel = document.getElementById(PANEL_ID);
			if (!currentPanel) {
				return;
			}
			panel = currentPanel;
			event = event;
			var trigger = event.target.closest(".a7-hr-applied-badge__trigger");
			var del = event.target.closest(".a7-hr-applied-badge__delete");
			var pick = event.target.closest(".a7-hr-applied-badge__row[data-name]");
			var save = event.target.closest(".a7-hr-applied-badge__save");
			var clear = event.target.closest(".a7-hr-applied-badge__clear");

			if (trigger) {
				if (panel.classList.contains("is-open")) {
					closeMenu(panel);
				} else {
					openMenu(panel);
				}
				return;
			}

			if (del) {
				event.preventDefault();
				event.stopPropagation();
				var delName = del.dataset.name || "";
				if (!delName || busy) {
					return;
				}
				if (!window.confirm("Delete position \"" + delName + "\" from the list?")) {
					return;
				}
				request(panel, { action: "delete", positionName: delName }).then(function (data) {
					if (data) {
						notify("Position deleted.");
					}
				});
				return;
			}

			if (pick) {
				if (busy) {
					return;
				}
				request(panel, { action: "save", positionName: pick.dataset.name || "" }).then(function (data) {
					if (data) {
						closeMenu(panel);
					}
				});
				return;
			}

			if (save) {
				var menu = getMenu(panel);
				var nameInput = (menu || panel).querySelector(".a7-hr-applied-badge__input");
				var colorInput = (menu || panel).querySelector(".a7-hr-applied-badge__color");
				var name = nameInput ? String(nameInput.value || "").trim() : "";
				if (!name) {
					showError(panel, "Enter a position name first.");
					return;
				}
				request(panel, {
					action: "add",
					positionName: name,
					color: colorInput ? colorInput.value : "#2F80ED"
				}).then(function (data) {
					if (data && nameInput) {
						nameInput.value = "";
						notify("Position added.");
					}
				});
				return;
			}

			if (clear) {
				request(panel, { action: "save", positionName: "" }).then(function (data) {
					if (data) {
						closeMenu(panel);
					}
				});
			}
		}

		panel.addEventListener("click", onWidgetClick);
		var menu = getMenu(panel);
		if (menu && menu.dataset.bound !== "1") {
			menu.dataset.bound = "1";
			menu.addEventListener("click", onWidgetClick);
			menu.addEventListener("keydown", function (event) {
				if (event.key === "Escape") {
					closeMenu(document.getElementById(PANEL_ID));
				}
				if (event.key === "Enter" && event.target.classList.contains("a7-hr-applied-badge__input")) {
					event.preventDefault();
					var saveBtn = menu.querySelector(".a7-hr-applied-badge__save");
					if (saveBtn) {
						saveBtn.click();
					}
				}
			});
		}

		panel.addEventListener("keydown", function (event) {
			if (event.key === "Escape") {
				closeMenu(panel);
			}
		});
	}

	if (!window.a7HrAppliedBadgeDocBound) {
		window.a7HrAppliedBadgeDocBound = true;
		document.addEventListener("click", function (event) {
			var openPanel = document.getElementById(PANEL_ID);
			var openMenu = document.getElementById(MENU_ID);
			if (!openPanel) {
				return;
			}
			var insidePanel = openPanel.contains(event.target);
			var insideMenu = openMenu && openMenu.contains(event.target);
			if (!insidePanel && !insideMenu) {
				closeMenu(openPanel);
			}
		});
		window.addEventListener("resize", function () {
			var openPanel = document.getElementById(PANEL_ID);
			if (openPanel && openPanel.classList.contains("is-open")) {
				placeMenu(openPanel);
			}
		});
	}

	var kanbanCache = {};
	var kanbanBusy = false;
	var kanbanTimer = 0;

	function getKanbanGrid() {
		if (typeof Kanban !== "undefined" && Kanban && typeof Kanban.getData === "function") {
			return Kanban;
		}
		return null;
	}

	function getKanbanEntityTypeId() {
		var grid = getKanbanGrid();
		if (grid) {
			var data = grid.getData() || {};
			var fromGrid = parseInt(data.entityTypeInt, 10) || 0;
			if (HR_CV_TYPES[fromGrid]) {
				return fromGrid;
			}
		}
		var path = String(window.location.pathname || "") + String(window.location.search || "");
		var match = path.match(/\/type\/(1156|1210)(?:\/|$|\?)/);
		if (match) {
			return parseInt(match[1], 10);
		}
		if (/\/page\/hr_uae\//i.test(path) && /\/applicant(\/|$)/i.test(path)) {
			return 1210;
		}
		if (/\/page\/hr_pak\//i.test(path) && /\/applicant(\/|$)/i.test(path)) {
			return 1156;
		}
		return 0;
	}

	function kanbanItemId(node) {
		var raw = node.getAttribute("data-id") || node.getAttribute("data-item-id") || "";
		if (!raw && node.dataset) {
			raw = node.dataset.id || node.dataset.itemId || "";
		}
		var digits = String(raw).match(/(\d+)$/);
		return digits ? parseInt(digits[1], 10) : 0;
	}

	function cardTarget(node) {
		if (!node) {
			return null;
		}
		var outer = (node.closest && node.closest(".main-kanban-item")) || node;
		var inner = outer.querySelector ? outer.querySelector(".crm-kanban-item") : null;
		return inner || outer;
	}

	function collectKanbanCards() {
		var seen = {};
		var cards = [];

		function add(id, node) {
			id = parseInt(id, 10);
			node = cardTarget(node);
			if (!(id > 0) || !node || seen[id]) {
				return;
			}
			seen[id] = true;
			cards.push({ id: id, node: node });
		}

		var grid = getKanbanGrid();
		if (grid) {
			var items = typeof grid.getItems === "function" ? grid.getItems() || {} : {};
			Object.keys(items).forEach(function (key) {
				var item = items[key];
				if (!item) {
					return;
				}
				var id = item.getId ? item.getId() : key;
				var node = (item.getContainer && item.getContainer()) || (item.layout && item.layout.container);
				add(id, node);
			});
			if (typeof grid.getColumns === "function") {
				(grid.getColumns() || []).forEach(function (column) {
					var columnItems = column && column.getItems ? column.getItems() : [];
					if (!Array.isArray(columnItems)) {
						columnItems = columnItems ? Object.keys(columnItems).map(function (key) {
							return columnItems[key];
						}) : [];
					}
					columnItems.forEach(function (item) {
						if (!item) {
							return;
						}
						var id = item.getId ? item.getId() : item.id;
						var node = (item.getContainer && item.getContainer()) || (item.layout && item.layout.container);
						add(id, node);
					});
				});
			}
		}

		document.querySelectorAll(".main-kanban-item, .crm-kanban-item").forEach(function (node) {
			add(kanbanItemId(node), node);
		});
		return cards;
	}

	function paintKanbanDot(node, info) {
		if (!node) {
			return;
		}
		var color = info && info.color ? info.color : "";
		var dot = node.querySelector(".a7-hr-kanban-dot");
		var leftoverBar = node.querySelector(".a7-hr-kanban-bar");
		if (leftoverBar) {
			leftoverBar.remove();
		}
		if (!color) {
			if (dot) {
				dot.remove();
			}
			node.classList.remove("a7-hr-has-dot");
			return;
		}
		if (!dot) {
			dot = document.createElement("span");
			dot.className = "a7-hr-kanban-dot";
			dot.setAttribute("aria-hidden", "true");
			node.appendChild(dot);
		}
		dot.style.background = color;
		dot.style.color = contrastText(color);
		dot.textContent = shortPosition(info.name || "");
		dot.title = info.name || "";
		node.classList.add("a7-hr-has-dot");
	}

	function refreshKanbanDots() {
		var entityTypeId = getKanbanEntityTypeId();
		if (!HR_CV_TYPES[entityTypeId]) {
			return;
		}
		var cards = collectKanbanCards();
		if (!cards.length) {
			return;
		}
		var now = Date.now();
		var missing = [];
		var queued = {};
		cards.forEach(function (card) {
			var cached = kanbanCache[card.id];
			if (cached && cached.color) {
				paintKanbanDot(card.node, cached);
				if (now - (cached.ts || 0) < 15000) {
					return;
				}
			} else if (cached && now - (cached.ts || 0) < 2000) {
				paintKanbanDot(card.node, cached);
				return;
			}
			if (!queued[card.id]) {
				queued[card.id] = true;
				missing.push(card.id);
			}
		});
		if (!missing.length || kanbanBusy) {
			return;
		}
		kanbanBusy = true;
		post({
			action: "kanban",
			entityTypeId: entityTypeId,
			itemId: missing[0],
			itemIds: missing
		})
			.then(function (data) {
				var items = data.items || {};
				missing.forEach(function (id) {
					var row = items[String(id)] || { name: "", color: "" };
					kanbanCache[id] = {
						name: row.name || "",
						color: row.color || "",
						ts: Date.now()
					};
				});
				collectKanbanCards().forEach(function (card) {
					if (kanbanCache[card.id]) {
						paintKanbanDot(card.node, kanbanCache[card.id]);
					}
				});
			})
			.catch(function () {
				missing.forEach(function (id) {
					delete kanbanCache[id];
				});
			})
			.then(function () {
				kanbanBusy = false;
			});
	}

	function scheduleKanbanDots() {
		window.clearTimeout(kanbanTimer);
		kanbanTimer = window.setTimeout(refreshKanbanDots, 250);
	}

	function start() {
		if (started) {
			mountPanel();
			scheduleKanbanDots();
			return;
		}
		started = true;
		mountPanel();
		scheduleKanbanDots();
		if (typeof MutationObserver === "function") {
			var observer = new MutationObserver(function () {
				var details = parseDetails();
				var panel = document.getElementById(PANEL_ID);
				if (details && !panel) {
					mountPanel();
				} else if (details && panel && panel.dataset.itemId !== String(details.itemId)) {
					panel.remove();
					mountPanel();
				}
				if (getKanbanEntityTypeId()) {
					scheduleKanbanDots();
				}
			});
			observer.observe(document.body, { childList: true, subtree: true });
		}
		window.setInterval(function () {
			mountPanel();
			scheduleKanbanDots();
		}, 2000);
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start);
	} else {
		start();
	}
})();
