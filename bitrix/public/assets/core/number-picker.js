/**
 * WhatsApp number filter — inline expand (never absolute overlay).
 * Absolute dropdowns painted over the chat list; this stays in document flow.
 */

import { el, clear, debounce } from "./dom.js";
import { icon } from "./icons.js";

/**
 * @param {{
 *   getNumbers: () => object[],
 *   getValue: () => string,
 *   setValue: (id: string) => void,
 *   onChange: (id: string) => void,
 *   labelFor: (number: object | null) => string,
 *   matchFilter: (number: object, query: string) => boolean,
 * }} opts
 */
export function createNumberPicker({ getNumbers, getValue, setValue, onChange, labelFor, matchFilter }) {
  const search = el("input.np__search", {
    type: "search",
    placeholder: "Search numbers…",
    autocomplete: "off",
  });

  const list = el("div.np__list", { role: "listbox" });
  const body = el("div.np__body", { hidden: true }, [search, list]);

  const label = el("span.np__label", {}, ["All numbers"]);
  const trigger = el(
    "button.np__trigger",
    {
      type: "button",
      "aria-haspopup": "listbox",
      "aria-expanded": "false",
    },
    [label, icon("chevronRight", { size: 14, className: "np__chevron" })]
  );

  const root = el("div.np", {}, [trigger, body]);

  let open = false;

  function setOpen(next) {
    open = next;
    root.classList.toggle("is-open", open);
    body.hidden = !open;
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      renderList();
      search.focus();
      search.select();
    }
  }

  function close() {
    setOpen(false);
  }

  function pick(id) {
    setValue(id);
    onChange(id);
    close();
    refreshTrigger();
  }

  function accountSuffix(number) {
    const name = String(number?.account_username || "").trim();
    return name ? ` · ${name}` : "";
  }

  function refreshTrigger() {
    const value = getValue();
    const numbers = getNumbers();
    const picked = numbers.find((n) => String(n.id) === String(value));
    label.textContent = picked ? `${labelFor(picked)}${accountSuffix(picked)}` : "All numbers";
  }

  function renderList() {
    clear(list);
    const query = search.value;
    const numbers = getNumbers();

    list.append(
      el(
        "button.np__option",
        {
          type: "button",
          role: "option",
          class: !getValue() ? "is-active" : "",
          onclick: () => pick(""),
        },
        ["All numbers"]
      )
    );

    let shown = 0;
    for (const number of numbers) {
      if (!matchFilter(number, query)) continue;
      shown += 1;
      const id = String(number.id);
      const account = String(number.account_username || "").trim();
      list.append(
        el(
          "button.np__option",
          {
            type: "button",
            role: "option",
            class: getValue() === id ? "is-active" : "",
            onclick: () => pick(id),
          },
          [
            el("span.np__option-text", {}, [labelFor(number)]),
            account ? el("span.np__option-waba", {}, [` · ${account}`]) : null,
          ]
        )
      );
    }

    if (String(query || "").trim() && !shown) {
      list.append(el("div.np__empty", {}, ["No numbers match"]));
    }
  }

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    setOpen(!open);
  });

  search.addEventListener(
    "input",
    debounce(() => renderList(), 100)
  );

  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
  });

  document.addEventListener(
    "click",
    (event) => {
      if (open && !root.contains(event.target)) close();
    },
    true
  );

  return {
    root,
    refresh({ resetSearch = false } = {}) {
      if (resetSearch) search.value = "";
      refreshTrigger();
      if (open) renderList();
    },
    setVisible(on) {
      root.hidden = !on;
      if (!on) close();
    },
  };
}
