(function () {
	"use strict";

	var HR_ENTITY_TYPE_IDS = {
		1156: true,
		1160: true,
		1168: true,
		1172: true,
		1210: true,
		1212: true,
		1214: true,
		1216: true
	};
	var BUTTON_CLASS = "a7-hr-stage-remove";
	var busy = false;

	function getGrid() {
		if (typeof Kanban !== "undefined" && Kanban && typeof Kanban.getColumn === "function") {
			return Kanban;
		}
		return null;
	}

	function getEntityTypeId() {
		var grid = getGrid();
		if (!grid || typeof grid.getData !== "function") {
			return 0;
		}
		var data = grid.getData() || {};
		return parseInt(data.entityTypeInt, 10) || 0;
	}

	function isHrBoard() {
		return !!HR_ENTITY_TYPE_IDS[getEntityTypeId()];
	}

	function getStageId(columnEl) {
		if (!columnEl) {
			return "";
		}
		var body = columnEl.querySelector(".main-kanban-column-body");
		return (body && body.getAttribute("data-id")) || columnEl.getAttribute("data-id") || "";
	}

	function getColumnTotal(stageId, columnEl) {
		var grid = getGrid();
		if (grid) {
			var column = grid.getColumn(stageId);
			if (column) {
				if (typeof column.getTotal === "function") {
					var total = Number(column.getTotal());
					if (Number.isFinite(total) && total > 0) {
						return total;
					}
				}
				if (typeof column.getItemsCount === "function") {
					var count = Number(column.getItemsCount());
					if (Number.isFinite(count) && count > 0) {
						return count;
					}
				}
			}
		}
		var totalEl = columnEl && columnEl.querySelector(".main-kanban-column-total-item");
		if (totalEl) {
			var parsed = parseInt(String(totalEl.textContent || "").replace(/[^\d]/g, ""), 10);
			if (Number.isFinite(parsed)) {
				return parsed;
			}
		}
		return 0;
	}

	function notify(message, error) {
		if (window.BX && BX.UI && BX.UI.Notification && BX.UI.Notification.Center) {
			BX.UI.Notification.Center.notify({
				content: message,
				autoHideDelay: 4000
			});
			return;
		}
		if (error) {
			window.alert(message);
		}
	}

	function postJson(payload) {
		var sessid = window.BX && BX.bitrix_sessid ? BX.bitrix_sessid() : "";
		return fetch("/local/ajax/a7_hr_stage_remove.php", {
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
					throw new Error((data && data.error) || "Could not remove this column");
				}
				return data;
			});
		});
	}

	function onRemoveClick(event) {
		event.preventDefault();
		event.stopPropagation();
		if (busy) {
			return;
		}
		var button = event.currentTarget;
		var columnEl = button.closest(".main-kanban-column");
		var stageId = getStageId(columnEl);
		var entityTypeId = getEntityTypeId();
		if (!stageId || !entityTypeId) {
			notify("Column not found", true);
			return;
		}
		var total = getColumnTotal(stageId, columnEl);
		if (total > 0) {
			notify("This column has data, so it cannot be deleted.", true);
			return;
		}
		if (!window.confirm("Delete this empty column?")) {
			return;
		}
		busy = true;
		button.classList.add("is-busy");
		postJson({
			entityTypeId: entityTypeId,
			stageId: stageId
		})
			.then(function () {
				var grid = getGrid();
				if (grid && typeof grid.removeColumn === "function") {
					grid.removeColumn(stageId);
				} else {
					window.location.reload();
				}
				notify("Empty column removed.");
			})
			.catch(function (error) {
				notify(error.message || "Could not remove this column", true);
			})
			.then(function () {
				busy = false;
				button.classList.remove("is-busy");
				paintButtons();
			});
	}

	function createButton() {
		var button = document.createElement("button");
		button.type = "button";
		button.className = BUTTON_CLASS;
		button.setAttribute("aria-label", "Delete column");
		button.title = "Delete column";
		button.innerHTML = '<span class="a7-hr-stage-remove-icon" aria-hidden="true"></span>';
		button.addEventListener("click", onRemoveClick);
		return button;
	}

	function ensureButton(columnEl) {
		var titleInfo = columnEl.querySelector(".main-kanban-column-title-info");
		if (!titleInfo) {
			return;
		}

		columnEl.querySelectorAll("." + BUTTON_CLASS).forEach(function (node) {
			if (node.parentNode !== titleInfo) {
				node.remove();
			}
		});

		var existing = titleInfo.querySelector("." + BUTTON_CLASS);
		if (!existing) {
			existing = createButton();
			var editButton = titleInfo.querySelector(".main-kanban-column-edit");
			if (editButton && editButton.nextSibling) {
				titleInfo.insertBefore(existing, editButton.nextSibling);
			} else if (editButton) {
				titleInfo.appendChild(existing);
			} else {
				titleInfo.appendChild(existing);
			}
		}

		var stageId = getStageId(columnEl);
		var total = getColumnTotal(stageId, columnEl);
		var locked = total > 0;
		existing.disabled = locked;
		existing.classList.toggle("is-locked", locked);
		existing.title = locked
			? "This column has data, so it cannot be deleted."
			: "Delete empty column";
	}

	function paintButtons() {
		if (!isHrBoard()) {
			return;
		}
		document.querySelectorAll(".main-kanban-column").forEach(ensureButton);
	}

	function start() {
		paintButtons();
		var root = document.querySelector(".main-kanban, #crm_kanban, .crm-kanban");
		if (root && typeof MutationObserver === "function") {
			var observer = new MutationObserver(function () {
				paintButtons();
			});
			observer.observe(root, { childList: true, subtree: true });
		}
		window.setInterval(paintButtons, 2500);
	}

	function waitForBoard() {
		if (isHrBoard()) {
			start();
			return;
		}
		if (document.querySelector(".main-kanban-column-title-info") && getEntityTypeId()) {
			if (!isHrBoard()) {
				return;
			}
		}
		window.setTimeout(waitForBoard, 400);
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", waitForBoard);
	} else {
		waitForBoard();
	}
})();
