/**
 * Entry point for extras modules (Search, Reminders, Reply Buttons, Theme & Options Menu).
 * Self-mounts on "wa:ready" event or when DOM anchors become available.
 * Strictly uses SVG inline icons matching icons.js (NO EMOJIS).
 */

import { el, clear } from "../core/dom.js";
import { mountSearch } from "./search.js";
import { mountReminders } from "./reminders.js";
import { mountButtons } from "./buttons.js";

let isMounted = false;

function createIcon(shapes, size = 14) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.classList.add("icon");

  const list = Array.isArray(shapes) ? shapes : [shapes];
  list.forEach((item) => {
    if (typeof item === "string") {
      const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
      p.setAttribute("d", item);
      svg.appendChild(p);
    } else if (item && typeof item === "object") {
      const tag = item.tag || "path";
      const elem = document.createElementNS("http://www.w3.org/2000/svg", tag);
      Object.entries(item).forEach(([k, v]) => {
        if (k !== "tag") elem.setAttribute(k, String(v));
      });
      svg.appendChild(elem);
    }
  });
  return svg;
}

const ICON_SHAPES = {
  moon: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z",
  sun: [
    { tag: "circle", cx: 12, cy: 12, r: 5 },
    "M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42",
  ],
  layout: [
    { tag: "rect", x: 3, y: 3, width: 18, height: 18, rx: 2 },
    "M3 9h18M9 21V9",
  ],
  palette: "M12 21a9 9 0 1 1 0-18c2.5 0 4.5 1.8 4.5 4a3.5 3.5 0 0 1-3.5 3.5H11a2 2 0 0 0-2 2v.5C9 14.5 10.3 16 12 16h1a5 5 0 0 1 5 5",
  check: "M20 6 9 17l-5-5",
  dots: [
    { tag: "circle", cx: 12, cy: 5, r: 1.5 },
    { tag: "circle", cx: 12, cy: 12, r: 1.5 },
    { tag: "circle", cx: 12, cy: 19, r: 1.5 },
  ],
  hash: "M4 9h16M4 15h16M10 3 8 21M16 3l-2 18",
};

const THEMES = [
  { id: "glass-dark", label: "Liquid Glass (Dark)", iconKey: "moon" },
  { id: "glass-light", label: "Liquid Glass (Light)", iconKey: "sun" },
  { id: "classic", label: "Classic Bitrix", iconKey: "layout" },
];

function applyTheme(id) {
  let theme = id;
  if (!theme) {
    try {
      theme = localStorage.getItem("wa_theme") || "glass-dark";
    } catch {
      theme = "glass-dark";
    }
  }
  document.documentElement.setAttribute("data-wa-theme", theme);
  if (document.body) document.body.setAttribute("data-wa-theme", theme);
  try {
    localStorage.setItem("wa_theme", theme);
  } catch {
    /* private mode — the attribute still paints this session */
  }
  return theme;
}

function ensureGlassBg() {
  if (document.querySelector(".wa-x-glass-bg")) return;
  const bg = document.createElement("div");
  bg.className = "wa-x-glass-bg";
  bg.setAttribute("aria-hidden", "true");
  bg.innerHTML = `
      <div class="wa-x-blob wa-x-b1"></div>
      <div class="wa-x-blob wa-x-b2"></div>
      <div class="wa-x-blob wa-x-b3"></div>
      <div class="wa-x-blob wa-x-b4"></div>
    `;
  document.body.prepend(bg);
}

applyTheme();

function themeRow(t, current, onPick) {
  const active = t.id === current;
  return el(
    "button.btn.menu__item.wa-x-theme-item",
    {
      type: "button",
      class: active ? "wa-x-theme-item--active" : "",
      onclick: (e) => {
        e.stopPropagation();
        onPick(t.id);
      },
    },
    [
      el("div.wa-x-theme-item-left", {}, [
        createIcon(ICON_SHAPES[t.iconKey], 14),
        el("span", {}, [t.label]),
      ]),
      active ? createIcon(ICON_SHAPES.check, 13) : null,
    ]
  );
}

export function mountThemeSwitcher() {
  ensureGlassBg();
  applyTheme();

  const slot = document.querySelector("#wa-theme-slot");
  if (slot) {
    if (slot.dataset.mounted === "1") return;
    slot.dataset.mounted = "1";
    const paint = () => {
      const current = applyTheme();
      clear(slot);
      THEMES.forEach((t) =>
        slot.append(
          themeRow(t, current, (id) => {
            applyTheme(id);
            paint();
          })
        )
      );
    };
    paint();
    return;
  }

  const menu = document.querySelector(".sidebar__menu");
  if (menu) {
    menu.append(el("div.menu__section", {}, ["Design"]), el("div.slot", { id: "wa-theme-slot" }));
    return mountThemeSwitcher();
  }

  const sidebarTop = document.querySelector(".sidebar__top");
  const topbarSlot = document.querySelector("#wa-topbar-slot");
  if (!sidebarTop && !topbarSlot) return;
  if (document.querySelector(".wa-x-theme-container")) return;

  const themeBtn = el("button.wa-x-theme-btn", { type: "button", title: "Options & Design Theme" }, [
    createIcon(ICON_SHAPES.dots, 14),
    el("span.wa-x-theme-label", {}, ["Theme"]),
  ]);
  const dropdown = el("div.wa-x-theme-dropdown", { hidden: true });
  const renderDropdown = () => {
    clear(dropdown);
    const current = applyTheme();
    dropdown.append(el("div.wa-x-theme-head", {}, ["Design / Theme"]));
    THEMES.forEach((t) =>
      dropdown.append(
        themeRow(t, current, (id) => {
          applyTheme(id);
          dropdown.hidden = true;
          renderDropdown();
        })
      )
    );
  };
  renderDropdown();

  const container = el("div.wa-x-theme-container", {}, [themeBtn, dropdown]);
  if (topbarSlot) topbarSlot.prepend(container);
  else {
    const newBtn = sidebarTop.querySelector(".btn--primary") || sidebarTop.querySelector(".btn");
    if (newBtn) sidebarTop.insertBefore(container, newBtn);
    else sidebarTop.append(container);
  }

  themeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown.hidden = !dropdown.hidden;
  });
  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) dropdown.hidden = true;
  });
}

function mountAll(me) {
  if (isMounted) return;
  isMounted = true;

  try {
    mountThemeSwitcher();
  } catch (err) {
    console.error("[extras.js] Error mounting theme switcher:", err);
  }

  try {
    mountSearch(me);
  } catch (err) {
    console.error("[extras.js] Error mounting search:", err);
  }

  try {
    mountReminders(me);
  } catch (err) {
    console.error("[extras.js] Error mounting reminders:", err);
  }

  try {
    mountButtons(me);
  } catch (err) {
    console.error("[extras.js] Error mounting reply buttons:", err);
  }
}

// Contract 2: Listen for wa:ready event dispatched by inbox boot
window.addEventListener("wa:ready", (e) => {
  const me = e?.detail?.me;
  mountAll(me);
});

// Fallback: If DOM anchors already exist (e.g. if loaded after inbox mount)
function checkDomAndMount() {
  mountThemeSwitcher();
  if (
    document.querySelector("#wa-search-slot") ||
    document.querySelector("#wa-topbar-slot") ||
    document.querySelector("#wa-composer-slot") ||
    document.querySelector(".sidebar__top")
  ) {
    mountAll(null);
  }
}

if (document.querySelector(".sidebar__top")) {
  mountThemeSwitcher();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", checkDomAndMount);
} else {
  checkDomAndMount();
}
