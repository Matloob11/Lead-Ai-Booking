/**
 * Compact inbox list filters — one row under the search box.
 */

import { el, clear } from "./dom.js";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "unread", label: "Unread" },
  { id: "pinned", label: "Pinned" },
  { id: "transferred", label: "Transferred" },
  { id: "rotate", label: "Rotate WhatsApp" },
];

/**
 * @param {{
 *   getActive: () => string,
 *   onChange: (id: string) => void,
 * }} opts
 */
export function createQuickFilters({ getActive, onChange }) {
  const root = el("div.filter__quick", { role: "tablist", "aria-label": "Conversation filters" });

  function render() {
    clear(root);
    const active = getActive();
    for (const filter of FILTERS) {
      root.append(
        el(
          "button.filter__quick-btn",
          {
            type: "button",
            role: "tab",
            class: active === filter.id ? "is-active" : "",
            "aria-selected": active === filter.id ? "true" : "false",
            onclick: () => {
              if (getActive() !== filter.id) onChange(filter.id);
            },
          },
          [filter.label]
        )
      );
    }
  }

  return { root, render };
}

/**
 * Tag chips for the sidebar menu — not in the chat list column.
 *
 * @param {{
 *   container: HTMLElement,
 *   getTags: () => Map<string, string>,
 *   getActive: () => string | null,
 *   onChange: (name: string | null) => void,
 * }} opts
 */
export function renderTagMenu({ container, getTags, getActive, onChange }) {
  if (!container) return;
  const tags = getTags();
  clear(container);

  if (!tags.size) {
    container.append(el("p.menu__tags-empty", {}, ["No tags on loaded chats yet."]));
    return;
  }

  const row = el("div.menu__tags", {});
  row.append(
    el(
      "button.menu__tag-chip",
      {
        type: "button",
        class: getActive() ? "" : "is-active",
        onclick: () => onChange(null),
      },
      ["All tags"]
    )
  );

  for (const [name, colour] of tags) {
    row.append(
      el(
        "button.menu__tag-chip",
        {
          type: "button",
          class: getActive() === name ? "is-active" : "",
          style:
            getActive() === name
              ? `background:${colour};border-color:${colour};color:#fff`
              : `--tag-colour:${colour}`,
          onclick: () => onChange(getActive() === name ? null : name),
        },
        [name]
      )
    );
  }

  container.append(row);
}
