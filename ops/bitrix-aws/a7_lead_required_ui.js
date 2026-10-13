(function () {
	'use strict';

	function isLeadPage() {
		var path = String(window.location.pathname || '');
		return path.indexOf('/crm/lead/') !== -1 || path.indexOf('/crm/type/1/') !== -1;
	}

	function sectionTitle(section) {
		var nodes = section.querySelectorAll(
			'.ui-entity-editor-header-title-text, .ui-entity-editor-section-title-text, .ui-entity-editor-section-header'
		);
		var i;
		var text;
		for (i = 0; i < nodes.length; i += 1) {
			text = String(nodes[i].textContent || '').replace(/\s+/g, ' ').trim();
			if (text) {
				return text;
			}
		}
		return '';
	}

	function isRequiredSection(section) {
		var title = sectionTitle(section).toLowerCase();
		return (
			title.indexOf('required details') !== -1 ||
			title.indexOf('required fields') !== -1 ||
			title.indexOf('required field') !== -1
		);
	}

	function tidyHeader(section) {
		var header =
			section.querySelector('.ui-entity-editor-section-header') ||
			section.querySelector('.ui-entity-editor-section-title');
		if (!header) {
			return;
		}

		var subs = header.querySelectorAll('.a7-req-sub');
		var i;
		for (i = 0; i < subs.length; i += 1) {
			subs[i].parentNode.removeChild(subs[i]);
		}

		var titleEl = header.querySelector(
			'.ui-entity-editor-header-title-text, .ui-entity-editor-section-title-text'
		);
		if (titleEl) {
			titleEl.textContent = 'REQUIRED FIELD';
		}

		if (header.querySelector('.a7-req-edit')) {
			return;
		}

		var edit = null;
		var nodes = header.querySelectorAll('a, span, button, div');
		var text;
		for (i = 0; i < nodes.length; i += 1) {
			text = String(nodes[i].textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
			if (text === 'edit' && nodes[i].children.length === 0) {
				edit = nodes[i];
				break;
			}
		}

		var icon =
			header.querySelector('.ui-entity-editor-header-edit') ||
			header.querySelector('[class*="pencil"]') ||
			header.querySelector('.ui-icon-set__scope') ||
			header.querySelector('span[class*="edit-icon"]');

		if (!edit && !icon) {
			return;
		}

		var row = document.createElement('div');
		row.className = 'a7-req-edit';
		if (icon && icon !== titleEl) {
			row.appendChild(icon);
		}
		if (edit) {
			row.appendChild(edit);
		}
		header.appendChild(row);
	}

	function closestSection(node) {
		while (node && node !== document.body) {
			if (
				node.classList &&
				(node.classList.contains('ui-entity-editor-section') ||
					node.classList.contains('crm-entity-widget-content') ||
					node.classList.contains('ui-entity-editor-column-content'))
			) {
				if (node.classList.contains('ui-entity-editor-section')) {
					return node;
				}
			}
			node = node.parentNode;
		}
		return null;
	}

	function fieldBlock(el) {
		return (
			el.closest('.ui-entity-editor-content-block') ||
			el.closest('.ui-entity-editor-field') ||
			el.closest('.crm-entity-widget-content-block')
		);
	}

	function tagField(section, matchers, className) {
		var titles = section.querySelectorAll(
			'.ui-entity-editor-block-title, .ui-entity-editor-field-title, .crm-entity-widget-content-block-title'
		);
		var i;
		var text;
		var block;
		for (i = 0; i < titles.length; i += 1) {
			text = String(titles[i].textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
			if (!text) {
				continue;
			}
			if (matchers.some(function (part) { return text === part || text.indexOf(part) === 0; })) {
				block = fieldBlock(titles[i]);
				if (block) {
					block.classList.add(className);
				}
			}
		}
	}

	function decorate(section) {
		if (!section) {
			return;
		}
		if (!section.classList.contains('a7-lead-required') && !isRequiredSection(section)) {
			return;
		}

		section.classList.add('a7-lead-required');
		tidyHeader(section);

		if (section.getAttribute('data-a7-req-tagged') === '1') {
			return;
		}
		section.setAttribute('data-a7-req-tagged', '1');

		tagField(section, ['name', 'first name'], 'a7-req-name');
		tagField(section, ['phone'], 'a7-req-phone');
		tagField(section, ['secondary phone'], 'a7-req-phone2');
		tagField(section, ['budget'], 'a7-req-budget');

		var blocks = section.querySelectorAll(
			'.ui-entity-editor-content-block, .ui-entity-editor-field, .crm-entity-widget-content-block'
		);
		var j;
		for (j = 0; j < blocks.length; j += 1) {
			if (
				!blocks[j].classList.contains('a7-req-name') &&
				!blocks[j].classList.contains('a7-req-phone') &&
				!blocks[j].classList.contains('a7-req-phone2') &&
				!blocks[j].classList.contains('a7-req-budget')
			) {
				blocks[j].classList.add('a7-req-wide');
			}
		}
	}

	function scan() {
		if (!isLeadPage()) {
			return;
		}
		var sections = document.querySelectorAll('.ui-entity-editor-section');
		var i;
		for (i = 0; i < sections.length; i += 1) {
			decorate(sections[i]);
		}
		if (sections.length === 0) {
			var titles = document.querySelectorAll(
				'.ui-entity-editor-header-title-text, .ui-entity-editor-section-title-text'
			);
			for (i = 0; i < titles.length; i += 1) {
				var section = closestSection(titles[i]);
				if (section) {
					decorate(section);
				}
			}
		}
	}

	if (!isLeadPage()) {
		return;
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', scan);
	} else {
		scan();
	}

	var scheduled = 0;
	var observer = new MutationObserver(function () {
		if (scheduled) {
			return;
		}
		scheduled = window.setTimeout(function () {
			scheduled = 0;
			scan();
		}, 200);
	});
	observer.observe(document.body, { childList: true, subtree: true });
})();
