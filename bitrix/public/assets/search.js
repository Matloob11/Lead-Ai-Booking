/**
 * KAAM A — SEARCH (search.js)
 * Full-text search in WhatsApp messages with debounced input, dropdown results,
 * highlighting, keyboard navigation, and deep-link conversation opening.
 */

import { el, clear, debounce, stamp } from "./dom.js";
import { searchMessages } from "./api-extras.js";

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function highlightTerm(text, term) {
  if (!text || !term) return escapeHtml(text || "");
  const escapedText = escapeHtml(text);
  const escapedTerm = escapeHtml(term);
  const regex = new RegExp(`(${escapedTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  return escapedText.replace(regex, '<mark class="wa-x-search-mark">$1</mark>');
}

export function mountSearch() {
  const slot = document.querySelector("#wa-search-slot");
  if (!slot) {
    console.warn("[search.js] #wa-search-slot anchor missing — search module skipping mount");
    return;
  }

  clear(slot);

  let currentResults = [];
  let selectedIndex = -1;

  // DOM elements
  const iconSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  iconSvg.setAttribute("viewBox", "0 0 24 24");
  iconSvg.setAttribute("width", "16");
  iconSvg.setAttribute("height", "16");
  iconSvg.setAttribute("fill", "none");
  iconSvg.setAttribute("stroke", "currentColor");
  iconSvg.setAttribute("stroke-width", "2");
  iconSvg.setAttribute("stroke-linecap", "round");
  iconSvg.setAttribute("stroke-linejoin", "round");
  iconSvg.classList.add("wa-x-search-icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z");
  iconSvg.appendChild(path);

  const input = el("input.wa-x-search-input", {
    type: "search",
    placeholder: "Messages mein dhoondein…",
    autocomplete: "off",
  });

  const dropdown = el("div.wa-x-search-dropdown", { hidden: true });
  const hintEl = el("div.wa-x-search-hint", { hidden: true });

  const container = el("div.wa-x-search-container", {}, [
    el("div.wa-x-search-field", {}, [iconSvg, input]),
    hintEl,
    dropdown,
  ]);

  slot.append(container);

  const closeDropdown = () => {
    dropdown.hidden = true;
    dropdown.replaceChildren();
    hintEl.hidden = true;
    currentResults = [];
    selectedIndex = -1;
  };

  const updateSelection = () => {
    const rows = dropdown.querySelectorAll(".wa-x-search-row");
    rows.forEach((row, idx) => {
      if (idx === selectedIndex) {
        row.classList.add("wa-x-search-row--selected");
        row.scrollIntoView({ block: "nearest" });
      } else {
        row.classList.remove("wa-x-search-row--selected");
      }
    });
  };

  const performSearch = debounce(async (term) => {
    if (term.length < 2) {
      closeDropdown();
      if (term.length === 1) {
        hintEl.textContent = "Dhoondne ke liye kam az kam 2 characters likhein";
        hintEl.hidden = false;
      }
      return;
    }

    hintEl.hidden = true;
    dropdown.replaceChildren(el("div.wa-x-search-status", {}, ["Dhoond rahe hain…"]));
    dropdown.hidden = false;

    try {
      const payload = await searchMessages({ q: term, limit: 50 });
      const results = payload?.results || [];
      const totalCount = payload?.count || results.length;
      currentResults = results;
      selectedIndex = -1;

      clear(dropdown);

      if (!results.length) {
        dropdown.append(el("div.wa-x-search-empty", {}, ["Kuch nahi mila."]));
        return;
      }

      const list = el("div.wa-x-search-list");

      results.forEach((m, idx) => {
        const contactName = m.conversation?.contact?.name || m.conversation?.contact?.wa_id || "Unknown";
        const snippetHtml = highlightTerm(m.body || `[${m.kind || "media"}]`, term);
        const timeStr = stamp(m.created_at);

        const snippetEl = el("div.wa-x-search-snippet");
        snippetEl.innerHTML = snippetHtml;

        const row = el(
          "div.wa-x-search-row",
          {
            onclick: () => {
              if (typeof window.a7wa?.openConversation === "function") {
                window.a7wa.openConversation(m.conversation_id, { highlightMessageId: m.id });
              } else {
                console.warn("[search.js] window.a7wa.openConversation function missing", m.conversation_id, m.id);
              }
              closeDropdown();
            },
          },
          [
            el("div.wa-x-search-row-head", {}, [
              el("span.wa-x-search-contact", {}, [contactName]),
              el("span.wa-x-search-time", {}, [timeStr]),
            ]),
            snippetEl,
          ]
        );

        row.addEventListener("mouseenter", () => {
          selectedIndex = idx;
          updateSelection();
        });

        list.append(row);
      });

      dropdown.append(list);

      if (totalCount > results.length) {
        dropdown.append(
          el("div.wa-x-search-footer", {}, [`${totalCount} mein se ${results.length} dikhaye ja rahe hain`])
        );
      }
    } catch (err) {
      clear(dropdown).append(el("div.wa-x-search-status.wa-x-search-status--err", {}, [`Error: ${err.message}`]));
    }
  }, 300);

  input.addEventListener("input", (e) => {
    const query = e.target.value.trim();
    performSearch(query);
  });

  input.addEventListener("keydown", (e) => {
    if (dropdown.hidden) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (currentResults.length) {
        selectedIndex = (selectedIndex + 1) % currentResults.length;
        updateSelection();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (currentResults.length) {
        selectedIndex = (selectedIndex - 1 + currentResults.length) % currentResults.length;
        updateSelection();
      }
    } else if (e.key === "Enter") {
      if (selectedIndex >= 0 && currentResults[selectedIndex]) {
        e.preventDefault();
        const m = currentResults[selectedIndex];
        if (typeof window.a7wa?.openConversation === "function") {
          window.a7wa.openConversation(m.conversation_id, { highlightMessageId: m.id });
        }
        closeDropdown();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeDropdown();
    }
  });

  // Close dropdown when clicking outside
  document.addEventListener("click", (e) => {
    if (!container.contains(e.target)) {
      closeDropdown();
    }
  });
}
