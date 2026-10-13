(function () {
	if (window.location.pathname.indexOf('/sign/') !== 0) return;

	function addButtons() {
		const toolbar = document.querySelector('.ui-toolbar-right-buttons, .ui-toolbar, .pagetitle-container');
		if (!toolbar) return false;

		if (!document.getElementById('a7-tenancy-btn')) {
			const a = document.createElement('a');
			a.id = 'a7-tenancy-btn';
			a.href = '/tenancy/';
			a.className = 'ui-btn ui-btn-success';
			a.textContent = 'Tenancy Contract';
			a.style.marginLeft = '8px';
			toolbar.appendChild(a);
		}

		if (!document.getElementById('a7-shop-tc-btn')) {
			const b = document.createElement('a');
			b.id = 'a7-shop-tc-btn';
			b.href = '/shop-tc/';
			b.className = 'ui-btn ui-btn-primary';
			b.textContent = 'Deal Scouting';
			b.style.marginLeft = '8px';
			toolbar.appendChild(b);
		}

		return !!(document.getElementById('a7-tenancy-btn') && document.getElementById('a7-shop-tc-btn'));
	}

	if (typeof BX !== 'undefined' && BX.ready) {
		BX.ready(function () {
			if (addButtons()) return;
			const t = setInterval(function () {
				if (addButtons()) clearInterval(t);
			}, 400);
			setTimeout(function () { clearInterval(t); }, 8000);
		});
	} else {
		document.addEventListener('DOMContentLoaded', addButtons);
	}
})();
