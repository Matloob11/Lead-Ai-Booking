/**
 * Entry point for extras modules (Search, Reminders, Reply Buttons, Theme Switcher).
 * Self-mounts on "wa:ready" event or when DOM anchors become available.
 */

import { el, clear } from "./dom.js";
import { mountSearch } from "./search.js";
import { mountReminders } from "./reminders.js";
import { mountButtons } from "./buttons.js";

let isMounted = false;

export function mountThemeSwitcher() {
  // Create background blobs container for glass themes if not existing
  if (!document.querySelector(".wa-x-glass-bg")) {
    const bg = document.createElement("div");
    bg.className = "wa-x-glass-bg";
    bg.innerHTML = `
      <div class="wa-x-blob wa-x-b1"></div>
      <div class="wa-x-blob wa-x-b2"></div>
      <div class="wa-x-blob wa-x-b3"></div>
      <div class="wa-x-blob wa-x-b4"></div>
    `;
    document.body.prepend(bg);
  }

  // Read saved theme or default to glass-dark
  const savedTheme = localStorage.getItem("wa_theme") || "glass-dark";
  document.body.setAttribute("data-wa-theme", savedTheme);

  const slot = document.querySelector("#wa-topbar-slot");
  if (!slot) return;

  // Check if theme switcher already mounted in slot
  if (slot.querySelector(".wa-x-theme-container")) return;

  // Palette icon
  const iconSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  iconSvg.setAttribute("viewBox", "0 0 24 24");
  iconSvg.setAttribute("width", "17");
  iconSvg.setAttribute("height", "17");
  iconSvg.setAttribute("fill", "none");
  iconSvg.setAttribute("stroke", "currentColor");
  iconSvg.setAttribute("stroke-width", "2");
  iconSvg.setAttribute("stroke-linecap", "round");
  iconSvg.setAttribute("stroke-linejoin", "round");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M12 21a9 9 0 1 1 0-18c2.5 0 4.5 1.8 4.5 4a3.5 3.5 0 0 1-3.5 3.5H11a2 2 0 0 0-2 2v.5C9 14.5 10.3 16 12 16h1a5 5 0 0 1 5 5");
  iconSvg.appendChild(path);

  const themeBtn = el("button.wa-x-btn-icon", { type: "button", title: "Design / Theme Change Karein" }, [iconSvg]);
  const dropdown = el("div.wa-x-theme-dropdown", { hidden: true });

  const themes = [
    { id: "glass-dark", label: "🌙 Liquid Glass (Dark)" },
    { id: "glass-light", label: "☀️ Liquid Glass (Light)" },
    { id: "classic", label: "🎨 Classic Bitrix" },
  ];

  const renderDropdown = () => {
    clear(dropdown);
    const current = document.body.getAttribute("data-wa-theme") || "glass-dark";
    const head = el("div.wa-x-theme-head", {}, ["Theme Select Karein"]);
    dropdown.append(head);

    themes.forEach((t) => {
      const active = t.id === current;
      const row = el(
        "button.wa-x-theme-item",
        {
          type: "button",
          class: active ? "wa-x-theme-item--active" : "",
          onclick: () => {
            document.body.setAttribute("data-wa-theme", t.id);
            localStorage.setItem("wa_theme", t.id);
            dropdown.hidden = true;
            renderDropdown();
          },
        },
        [t.label, active ? " ✓" : ""]
      );
      dropdown.append(row);
    });
  };

  renderDropdown();

  const container = el("div.wa-x-theme-container", {}, [themeBtn, dropdown]);
  slot.prepend(container);

  themeBtn.addEventListener("click", () => {
    dropdown.hidden = !dropdown.hidden;
  });

  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) {
      dropdown.hidden = true;
    }
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
    document.querySelector("#wa-composer-slot")
  ) {
    mountAll(null);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", checkDomAndMount);
} else {
  checkDomAndMount();
}
