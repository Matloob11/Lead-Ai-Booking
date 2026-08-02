/**
 * Entry point for extras modules (Search, Reminders, Reply Buttons).
 * Self-mounts on "wa:ready" event or when DOM anchors become available.
 */

import { mountSearch } from "./search.js";
import { mountReminders } from "./reminders.js";
import { mountButtons } from "./buttons.js";

let isMounted = false;

function mountAll(me) {
  if (isMounted) return;
  isMounted = true;

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
