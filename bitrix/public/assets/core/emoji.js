/**
 * Minimal emoji picker.
 *
 * A curated set rather than the full Unicode table: agents reach for the same
 * few dozen, a short list needs no search box or virtual scrolling, and the
 * CSP rules out pulling a picker library from a CDN anyway.
 */

import { el } from "./dom.js";

const GROUPS = [
  {
    name: "Aam",
    emoji: "😀 😃 😄 😁 😅 😂 🙂 😉 😊 😍 😘 😎 🤔 🙄 😐 😑 😢 😭 😤 😡 🥺 😴 🤝 🙏 👍 👎 👏 💪 🙌 👌 ✌️ 🤞 👋 ✋".split(" "),
  },
  {
    name: "Kaam",
    emoji: "✅ ❌ ⚠️ ❗ ❓ 📌 📎 📄 📷 🎤 🎬 📍 📞 📱 💬 📅 ⏰ ⏳ 🔔 🔍 ✏️ 📝 💰 💵 🏦 🧾 📊 🔑".split(" "),
  },
  {
    name: "Property",
    emoji: "🏠 🏡 🏢 🏬 🏗️ 🏘️ 🌇 🛏️ 🛋️ 🚿 🚗 🌳 🌊 🔥 ⭐ 🎉 ❤️ 💯".split(" "),
  },
];

/**
 * Anchors a picker popup to a button and inserts the chosen emoji at the
 * textarea's caret.
 *
 * @returns {{destroy: () => void}}
 */
export function bindEmojiPicker({ button, textarea }) {
  let popup = null;

  const close = () => {
    popup?.remove();
    popup = null;
    document.removeEventListener("click", onOutside, true);
    document.removeEventListener("keydown", onKey, true);
  };

  const onOutside = (event) => {
    if (popup && !popup.contains(event.target) && event.target !== button) close();
  };

  const onKey = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    close();
    textarea.focus();
  };

  /** Inserts at the caret so an emoji can land mid-sentence, not only at the end. */
  const insert = (emoji) => {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.value = textarea.value.slice(0, start) + emoji + textarea.value.slice(end);
    const caret = start + emoji.length;
    textarea.setSelectionRange(caret, caret);
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const toggle = (event) => {
    event.preventDefault();
    if (popup) return close();

    popup = el(
      "div.emoji",
      {},
      GROUPS.flatMap((group) => [
        el("div.emoji__title", {}, [group.name]),
        el(
          "div.emoji__grid",
          {},
          group.emoji.map((character) =>
            el("button.emoji__item", { type: "button", onclick: () => insert(character) }, [character])
          )
        ),
      ])
    );

    button.parentElement.append(popup);
    document.addEventListener("click", onOutside, true);
    document.addEventListener("keydown", onKey, true);
  };

  button.addEventListener("click", toggle);

  return {
    destroy: () => {
      close();
      button.removeEventListener("click", toggle);
    },
  };
}
